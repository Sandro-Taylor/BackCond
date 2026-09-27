# ---------------------------------------------------------
# CONDOMÍNIOS
# ---------------------------------------------------------
# Criar, editar, arquivar e restaurar: só ADM do sistema.
# Listar e consultar: ADM vê todos; demais usuários veem só
# os condomínios onde têm cadastro ativo.
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.database import get_database
from App.dependencies import exigir_admin_sistema, get_current_user
from App.models import Condominio, Pessoa, User
from App.validacoes import normalizar_cep, normalizar_cnpj, normalizar_email, normalizar_telefone, normalizar_uf

router = APIRouter(prefix="/condominios")


# DADOS RECEBIDOS

class CondominioCriar(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cnpj: str | None = None
    cep: str | None = None
    logradouro: str | None = Field(default=None, max_length=200)
    numero: str | None = Field(default=None, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str | None = Field(default=None, max_length=100)
    cidade: str | None = Field(default=None, max_length=100)
    uf: str | None = None
    telefone: str | None = None
    email: EmailStr | None = None

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, valor):
        return normalizar_cnpj(valor)

    @field_validator("cep")
    @classmethod
    def validar_cep(cls, valor):
        return normalizar_cep(valor)

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, valor):
        return normalizar_uf(valor)

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, valor):
        return normalizar_telefone(valor)

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class CondominioEditar(CondominioCriar):
    nome: str | None = Field(default=None, min_length=3, max_length=150)


# RESPOSTA

class CondominioResposta(BaseModel):
    id: uuid.UUID
    nome: str
    cnpj: str | None
    cep: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    cidade: str | None
    uf: str | None
    telefone: str | None
    email: str | None
    ativo: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# FUNÇÕES AUXILIARES

def buscar_condominio_ou_404(condominio_id: uuid.UUID, database: Session) -> Condominio:
    condominio = database.get(Condominio, condominio_id)
    if not condominio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")
    return condominio


def validar_cnpj_unico(cnpj: str | None, database: Session, ignorar_id: uuid.UUID | None = None):
    if not cnpj:
        return
    consulta = select(Condominio.id).where(Condominio.cnpj == cnpj)
    if ignorar_id:
        consulta = consulta.where(Condominio.id != ignorar_id)
    if database.scalar(consulta):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CNPJ já cadastrado")


def consulta_condominios_do_usuario(usuario: User):
    # condomínios ativos onde o usuário tem uma pessoa ativa
    return (
        select(Condominio)
        .join(Pessoa, Pessoa.condominio_id == Condominio.id)
        .where(Pessoa.user_id == usuario.id, Pessoa.ativo.is_(True), Condominio.ativo.is_(True))
    )


# ROTAS

@router.post("/", response_model=CondominioResposta, status_code=status.HTTP_201_CREATED)
async def criarCondominio(dados: CondominioCriar, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    validar_cnpj_unico(dados.cnpj, database)
    condominio = Condominio(**dados.model_dump())
    condominio.nome = condominio.nome.strip()
    database.add(condominio)
    database.commit()
    database.refresh(condominio)
    return condominio


@router.get("/", response_model=list[CondominioResposta])
async def listarCondominios(database: Session = Depends(get_database), usuario: User = Depends(get_current_user)):
    if usuario.admin_sistema:
        consulta = select(Condominio)
    else:
        consulta = consulta_condominios_do_usuario(usuario)
    return database.scalars(consulta.order_by(Condominio.nome)).all()


@router.get("/{condominio_id}", response_model=CondominioResposta)
async def buscarCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), usuario: User = Depends(get_current_user)):
    if usuario.admin_sistema:
        return buscar_condominio_ou_404(condominio_id, database)
    condominio = database.scalar(consulta_condominios_do_usuario(usuario).where(Condominio.id == condominio_id))
    if not condominio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")
    return condominio


@router.put("/{condominio_id}", response_model=CondominioResposta)
async def editarCondominio(condominio_id: uuid.UUID, dados: CondominioEditar, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    condominio = buscar_condominio_ou_404(condominio_id, database)
    dados_atualizados = dados.model_dump(exclude_unset=True)
    if "nome" in dados_atualizados:
        if not dados_atualizados["nome"] or not dados_atualizados["nome"].strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome é obrigatório")
        dados_atualizados["nome"] = dados_atualizados["nome"].strip()
    validar_cnpj_unico(dados_atualizados.get("cnpj"), database, ignorar_id=condominio_id)
    for campo, valor in dados_atualizados.items():
        setattr(condominio, campo, valor)
    database.commit()
    database.refresh(condominio)
    return condominio


@router.patch("/{condominio_id}/arquivar", response_model=CondominioResposta)
async def arquivarCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    condominio = buscar_condominio_ou_404(condominio_id, database)
    condominio.ativo = False
    database.commit()
    database.refresh(condominio)
    return condominio


@router.patch("/{condominio_id}/restaurar", response_model=CondominioResposta)
async def restaurarCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    condominio = buscar_condominio_ou_404(condominio_id, database)
    condominio.ativo = True
    database.commit()
    database.refresh(condominio)
    return condominio
