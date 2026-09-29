# ---------------------------------------------------------
# VAGAS (cadastro geral do condomínio)
# ---------------------------------------------------------
# FIXA: vaga demarcada; pode pertencer a um apartamento ou
#       estar livre (sem dono).
# ROTATIVA: vaga de uso comum; nunca pertence a apartamento.
# Veículo sem vaga fixa = usa as vagas rotativas.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from App.consultas import buscar_no_condominio, garantir_unico, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, exigir_leitura_geral
from App.models import Apartamento, TipoVaga, Vaga, Veiculo

router = APIRouter(prefix="/vagas")


class VagaDados(BaseModel):
    numero: str = Field(min_length=1, max_length=20)
    tipo: TipoVaga = "FIXA"
    apartamento_id: uuid.UUID | None = None
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None


class VagaEditar(VagaDados):
    ativo: bool = True


class VagaLista(BaseModel):
    id: uuid.UUID
    numero: str
    tipo: str
    localizacao: str | None
    observacao: str | None
    ativo: bool
    apartamento_id: uuid.UUID | None
    apartamento_rotulo: str | None
    veiculos: list[str]  # placas (ou modelo) dos veículos que usam a vaga


def rotulo_apartamento(apartamento: Apartamento | None) -> str | None:
    if not apartamento:
        return None
    return f"Bloco {apartamento.bloco} · {apartamento.numero}" if apartamento.bloco else f"Apto {apartamento.numero}"


def montar(vaga: Vaga) -> dict:
    return {
        "id": vaga.id,
        "numero": vaga.numero,
        "tipo": vaga.tipo,
        "localizacao": vaga.localizacao,
        "observacao": vaga.observacao,
        "ativo": vaga.ativo,
        "apartamento_id": vaga.apartamento_id,
        "apartamento_rotulo": rotulo_apartamento(vaga.apartamento),
        "veiculos": [v.placa or v.modelo or "Sem placa" for v in vaga.veiculos],
    }


def carregar(database: Session, vaga_id: uuid.UUID, condominio_id: uuid.UUID) -> dict:
    vaga = database.scalar(
        select(Vaga)
        .where(Vaga.id == vaga_id, Vaga.condominio_id == condominio_id)
        .options(selectinload(Vaga.apartamento), selectinload(Vaga.veiculos))
        .execution_options(populate_existing=True)
    )
    if not vaga:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vaga não encontrada")
    return montar(vaga)


def validar_apartamento(database: Session, condominio_id: uuid.UUID, dados: VagaDados) -> uuid.UUID | None:
    if dados.tipo == "ROTATIVA":
        if dados.apartamento_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vaga rotativa é de uso comum e não pertence a um apartamento")
        return None
    if dados.apartamento_id:
        buscar_no_condominio(database, Apartamento, dados.apartamento_id, condominio_id, "Apartamento não encontrado")
    return dados.apartamento_id


@router.get("/", response_model=list[VagaLista])
def listarVagas(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura_geral)):
    vagas = database.scalars(
        select(Vaga)
        .where(Vaga.condominio_id == ctx.condominio_id)
        .options(selectinload(Vaga.apartamento), selectinload(Vaga.veiculos))
    ).all()
    vagas = sorted(vagas, key=lambda v: (v.tipo, len(v.numero), v.numero))
    return [montar(vaga) for vaga in vagas]


@router.post("/", response_model=VagaLista, status_code=status.HTTP_201_CREATED)
def criarVaga(dados: VagaDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    numero = dados.numero.strip()
    garantir_unico(database, Vaga, ctx.condominio_id, {"numero": numero}, f"Vaga {numero} já cadastrada neste condomínio")
    apartamento_id = validar_apartamento(database, ctx.condominio_id, dados)

    vaga = Vaga(
        condominio_id=ctx.condominio_id,
        tipo=dados.tipo,
        apartamento_id=apartamento_id,
        numero=numero,
        localizacao=texto(dados.localizacao),
        observacao=texto(dados.observacao),
    )
    database.add(vaga)
    salvar(database)
    return carregar(database, vaga.id, ctx.condominio_id)


@router.put("/{vaga_id}", response_model=VagaLista)
def editarVaga(vaga_id: uuid.UUID, dados: VagaEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    vaga = buscar_no_condominio(database, Vaga, vaga_id, ctx.condominio_id, "Vaga não encontrada")
    numero = dados.numero.strip()
    garantir_unico(database, Vaga, ctx.condominio_id, {"numero": numero}, f"Vaga {numero} já cadastrada neste condomínio", ignorar_id=vaga.id)
    apartamento_id = validar_apartamento(database, ctx.condominio_id, dados)

    # se a vaga mudou de dono (ou virou rotativa), os veículos do dono anterior saem dela
    if apartamento_id != vaga.apartamento_id:
        database.execute(update(Veiculo).where(Veiculo.vaga_id == vaga.id).values(vaga_id=None))

    vaga.numero = numero
    vaga.tipo = dados.tipo
    vaga.apartamento_id = apartamento_id
    vaga.localizacao = texto(dados.localizacao)
    vaga.observacao = texto(dados.observacao)
    vaga.ativo = dados.ativo
    salvar(database)
    return carregar(database, vaga.id, ctx.condominio_id)


@router.delete("/{vaga_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirVaga(vaga_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # os veículos que usavam a vaga passam a usar as rotativas
    vaga = buscar_no_condominio(database, Vaga, vaga_id, ctx.condominio_id, "Vaga não encontrada")
    database.delete(vaga)
    salvar(database)
