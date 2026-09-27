# ---------------------------------------------------------
# PESSOAS – LISTAGEM
# ---------------------------------------------------------
# Lista só as pessoas do condomínio do contexto, com
# apartamentos, vagas e veículos.
# ---------------------------------------------------------

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import Apartamento, Pessoa, PessoaApartamento, Vaga

router = APIRouter()


class VeiculoLista(BaseModel):
    id: uuid.UUID
    pessoa_id: uuid.UUID
    vaga_id: uuid.UUID | None
    placa: str | None
    marca: str | None
    modelo: str | None
    cor: str | None
    descricao: str | None
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


class VagaLista(BaseModel):
    id: uuid.UUID
    numero: str
    localizacao: str | None
    observacao: str | None
    ativo: bool
    veiculos: list[VeiculoLista]
    model_config = ConfigDict(from_attributes=True)


class ApartamentoDadosLista(BaseModel):
    id: uuid.UUID
    bloco: str
    numero: str
    andar: int | None
    observacao: str | None
    ativo: bool
    vagas: list[VagaLista]
    model_config = ConfigDict(from_attributes=True)


class ApartamentoPessoaLista(BaseModel):
    id: uuid.UUID
    tipo_relacao: str
    principal: bool
    ativo: bool
    apartamento: ApartamentoDadosLista
    model_config = ConfigDict(from_attributes=True)


class PessoaLista(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    perfil: str
    nome: str
    cpf: str | None
    email: str | None
    telefone: str | None
    data_nascimento: date | None
    ativo: bool
    created_at: datetime
    apartamentos: list[ApartamentoPessoaLista]
    veiculos: list[VeiculoLista]
    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[PessoaLista])
def listarPessoas(database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    return database.scalars(
        select(Pessoa)
        .where(Pessoa.condominio_id == ctx.condominio_id)
        .options(
            selectinload(Pessoa.apartamentos)
            .selectinload(PessoaApartamento.apartamento)
            .selectinload(Apartamento.vagas)
            .selectinload(Vaga.veiculos),
            selectinload(Pessoa.veiculos),
        )
        .order_by(Pessoa.nome)
    ).all()
