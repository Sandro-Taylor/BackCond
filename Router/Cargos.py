# ---------------------------------------------------------
# CARGOS DOS FUNCIONÁRIOS
# ---------------------------------------------------------
# Lista própria de cada condomínio (porteiro, zelador...).
# Todo condomínio novo já nasce com os cargos padrão.
# Ver: quem vê tudo. Criar/editar/excluir: ADM/SINDICO.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, garantir_unico, salvar
from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, exigir_leitura_geral
from App.models import Cargo, Funcionario

router = APIRouter(prefix="/cargos")

CARGOS_PADRAO = ["Porteiro", "Zelador", "Faxineiro", "Jardineiro", "Segurança", "Manobrista", "Gerente predial"]


def criar_cargos_padrao(database: Session, condominio_id: uuid.UUID):
    # chamada ao cadastrar um condomínio (o commit fica com quem chamou)
    for nome in CARGOS_PADRAO:
        database.add(Cargo(condominio_id=condominio_id, nome=nome))


class CargoDados(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    ativo: bool = True

    @field_validator("nome")
    @classmethod
    def limpar(cls, valor: str):
        valor = " ".join(valor.split())
        if len(valor) < 2:
            raise ValueError("Informe o nome do cargo")
        return valor[0].upper() + valor[1:]


class CargoResposta(BaseModel):
    id: uuid.UUID
    nome: str
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[CargoResposta])
async def listarCargos(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura_geral)):
    return database.scalars(select(Cargo).where(Cargo.condominio_id == ctx.condominio_id).order_by(Cargo.nome)).all()


@router.post("/", response_model=CargoResposta, status_code=status.HTTP_201_CREATED)
async def criarCargo(dados: CargoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    garantir_unico(database, Cargo, ctx.condominio_id, {"nome": dados.nome}, "Já existe um cargo com este nome")
    cargo = Cargo(condominio_id=ctx.condominio_id, nome=dados.nome, ativo=dados.ativo)
    database.add(cargo)
    salvar(database, "Já existe um cargo com este nome")
    database.refresh(cargo)
    return cargo


@router.put("/{cargo_id}", response_model=CargoResposta)
async def editarCargo(cargo_id: uuid.UUID, dados: CargoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    cargo = buscar_no_condominio(database, Cargo, cargo_id, ctx.condominio_id, "Cargo não encontrado")
    garantir_unico(database, Cargo, ctx.condominio_id, {"nome": dados.nome}, "Já existe um cargo com este nome", ignorar_id=cargo.id)
    cargo.nome = dados.nome
    cargo.ativo = dados.ativo
    salvar(database, "Já existe um cargo com este nome")
    database.refresh(cargo)
    return cargo


@router.delete("/{cargo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluirCargo(cargo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    cargo = buscar_no_condominio(database, Cargo, cargo_id, ctx.condominio_id, "Cargo não encontrado")
    if database.scalar(select(Funcionario.id).where(Funcionario.cargo_id == cargo.id).limit(1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Há funcionários com este cargo. Troque o cargo deles ou desative o cargo")
    database.delete(cargo)
    salvar(database)
