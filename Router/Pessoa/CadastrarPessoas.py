# ---------------------------------------------------------
# PESSOAS – CADASTRO
# ---------------------------------------------------------
# Cadastra só os dados da pessoa. A ligação com apartamento
# (proprietário, inquilino, residente) é feita na tela e nas
# rotas de Apartamentos (Router/Apartamentos.py).
# ---------------------------------------------------------

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from App.consultas import garantir_unico, salvar
from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import PerfilPessoa, Pessoa
from App.validacoes import normalizar_cpf, normalizar_email, normalizar_telefone

router = APIRouter()


# =========================================================
# DADOS RECEBIDOS (também usados por Apartamentos.py)
# =========================================================

class PessoaDados(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cpf: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    data_nascimento: date | None = None

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, valor):
        return normalizar_cpf(valor)

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, valor):
        return normalizar_telefone(valor)

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class PessoaCreate(PessoaDados):
    perfil: PerfilPessoa = "MORADOR"


# =========================================================
# RESPOSTA
# =========================================================

class PessoaResponse(BaseModel):
    id: uuid.UUID
    nome: str
    cpf: str | None
    email: str | None
    telefone: str | None
    data_nascimento: date | None
    perfil: str
    ativo: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# =========================================================
# CADASTRAR PESSOA
# =========================================================

@router.post("/", response_model=PessoaResponse, status_code=status.HTTP_201_CREATED)
def cadastrarPessoa(dados: PessoaCreate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    if dados.cpf:
        garantir_unico(database, Pessoa, ctx.condominio_id, {"cpf": dados.cpf}, "CPF já cadastrado neste condomínio")

    pessoa = Pessoa(
        condominio_id=ctx.condominio_id,
        nome=dados.nome.strip(),
        cpf=dados.cpf,
        email=dados.email,
        telefone=dados.telefone,
        data_nascimento=dados.data_nascimento,
        perfil=dados.perfil,
    )
    database.add(pessoa)
    salvar(database)
    database.refresh(pessoa)
    return pessoa
