# ---------------------------------------------------------
# VEÍCULOS (visão geral do condomínio)
# ---------------------------------------------------------
# Lista todos os veículos com unidade, vaga e condutor.
# Todo veículo pertence a um apartamento; vaga fixa da
# própria unidade ou rotativo (sem vaga); condutor opcional,
# ligado à unidade. As mesmas regras da página do apartamento.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from App.consultas import buscar_no_condominio, garantir_unico, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, apartamentos_do_usuario, exigir_edicao_apartamento, get_contexto, negar
from App.models import Apartamento, Veiculo
from Router.Apartamentos import VeiculoDados, validar_veiculo
from Router.Vagas import rotulo_apartamento
from pydantic import BaseModel

router = APIRouter(prefix="/veiculos")


class VeiculoGeral(VeiculoDados):
    apartamento_id: uuid.UUID


class VeiculoGeralEditar(VeiculoGeral):
    ativo: bool = True


class VeiculoLista(BaseModel):
    id: uuid.UUID
    placa: str | None
    marca: str | None
    modelo: str | None
    cor: str | None
    descricao: str | None
    ativo: bool
    apartamento_id: uuid.UUID
    apartamento_rotulo: str
    vaga_id: uuid.UUID | None
    vaga_numero: str | None      # None = usa vagas rotativas
    pessoa_id: uuid.UUID | None
    condutor_nome: str | None


def montar(veiculo: Veiculo) -> dict:
    return {
        "id": veiculo.id,
        "placa": veiculo.placa,
        "marca": veiculo.marca,
        "modelo": veiculo.modelo,
        "cor": veiculo.cor,
        "descricao": veiculo.descricao,
        "ativo": veiculo.ativo,
        "apartamento_id": veiculo.apartamento_id,
        "apartamento_rotulo": rotulo_apartamento(veiculo.apartamento),
        "vaga_id": veiculo.vaga_id,
        "vaga_numero": veiculo.vaga.numero if veiculo.vaga else None,
        "pessoa_id": veiculo.pessoa_id,
        "condutor_nome": veiculo.pessoa.nome if veiculo.pessoa else None,
    }


def consulta_veiculos(condominio_id: uuid.UUID):
    return (
        select(Veiculo)
        .where(Veiculo.condominio_id == condominio_id)
        .options(selectinload(Veiculo.apartamento), selectinload(Veiculo.vaga), selectinload(Veiculo.pessoa))
        .execution_options(populate_existing=True)
    )


def carregar(database: Session, veiculo_id: uuid.UUID, condominio_id: uuid.UUID) -> dict:
    veiculo = database.scalar(consulta_veiculos(condominio_id).where(Veiculo.id == veiculo_id))
    if not veiculo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Veículo não encontrado")
    return montar(veiculo)


@router.get("/", response_model=list[VeiculoLista])
def listarVeiculos(database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    consulta = consulta_veiculos(ctx.condominio_id)
    if not ctx.ve_tudo:
        if ctx.perfil != "MORADOR":
            negar()
        consulta = consulta.where(Veiculo.apartamento_id.in_(apartamentos_do_usuario(database, ctx)))
    veiculos = [montar(v) for v in database.scalars(consulta).all()]
    return sorted(veiculos, key=lambda v: (v["apartamento_rotulo"], v["placa"] or ""))


@router.post("/", response_model=VeiculoLista, status_code=status.HTTP_201_CREATED)
def criarVeiculo(dados: VeiculoGeral, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    exigir_edicao_apartamento(database, ctx, dados.apartamento_id)
    apartamento = buscar_no_condominio(database, Apartamento, dados.apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    validar_veiculo(database, apartamento, dados)
    if dados.placa:
        garantir_unico(database, Veiculo, ctx.condominio_id, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio")

    veiculo = Veiculo(
        condominio_id=ctx.condominio_id,
        apartamento_id=apartamento.id,
        pessoa_id=dados.pessoa_id,
        vaga_id=dados.vaga_id,
        placa=dados.placa,
        marca=texto(dados.marca),
        modelo=texto(dados.modelo),
        cor=texto(dados.cor),
        descricao=texto(dados.descricao),
    )
    database.add(veiculo)
    salvar(database)
    return carregar(database, veiculo.id, ctx.condominio_id)


@router.put("/{veiculo_id}", response_model=VeiculoLista)
def editarVeiculo(veiculo_id: uuid.UUID, dados: VeiculoGeralEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    veiculo = buscar_no_condominio(database, Veiculo, veiculo_id, ctx.condominio_id, "Veículo não encontrado")
    exigir_edicao_apartamento(database, ctx, veiculo.apartamento_id)
    exigir_edicao_apartamento(database, ctx, dados.apartamento_id)
    apartamento = buscar_no_condominio(database, Apartamento, dados.apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    validar_veiculo(database, apartamento, dados)
    if dados.placa:
        garantir_unico(database, Veiculo, ctx.condominio_id, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio", ignorar_id=veiculo.id)

    veiculo.apartamento_id = apartamento.id
    veiculo.placa = dados.placa
    veiculo.marca = texto(dados.marca)
    veiculo.modelo = texto(dados.modelo)
    veiculo.cor = texto(dados.cor)
    veiculo.descricao = texto(dados.descricao)
    veiculo.vaga_id = dados.vaga_id
    veiculo.pessoa_id = dados.pessoa_id
    veiculo.ativo = dados.ativo
    salvar(database)
    return carregar(database, veiculo.id, ctx.condominio_id)


@router.delete("/{veiculo_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirVeiculo(veiculo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    veiculo = buscar_no_condominio(database, Veiculo, veiculo_id, ctx.condominio_id, "Veículo não encontrado")
    exigir_edicao_apartamento(database, ctx, veiculo.apartamento_id)
    database.delete(veiculo)
    salvar(database)
