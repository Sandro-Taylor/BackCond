from fastapi import Depends, APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel, ConfigDict, EmailStr

from App.database import get_database

from Router.Pessoa.CadastrarPessoas import (
    Pessoa,
    PessoaApartamento,
    Apartamento,
    Vaga,
)

import uuid
from datetime import datetime, date


router = APIRouter()


class VeiculoLista(BaseModel):
    id: uuid.UUID
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
    bloco: str | None
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
    nome: str
    cpf: str | None
    email: EmailStr | None
    telefone: str | None
    data_nascimento: date | None
    ativo: bool
    created_at: datetime

    apartamentos: list[ApartamentoPessoaLista]

    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[PessoaLista])
def listarPessoas(
    database: Session = Depends(get_database),
):

    pessoas = database.scalars(
        select(Pessoa)
        .options(
            selectinload(Pessoa.apartamentos)
            .selectinload(PessoaApartamento.apartamento)
            .selectinload(Apartamento.vagas)
            .selectinload(Vaga.veiculos)
        )
        .order_by(Pessoa.nome)
    ).all()

    return pessoas