# ---------------------------------------------------------
# SETORES
# ---------------------------------------------------------
# Cadastro simples de setores, usado para classificar os
# colaboradores (Router/Pessoa/Moradores.py -> Colaborador.idSetor).
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func

from App.database import Base, get_database
from App.dependencies import get_current_user
from App.models import Setor

router = APIRouter(prefix="/setores")


class SetorCriar(BaseModel):
    nome: str = Field(min_length=2, max_length=120)


class SetorEditar(BaseModel):
    nome: str = Field(min_length=2, max_length=120)


class SetorResposta(BaseModel):
    id: uuid.UUID
    nome: str
    dataCriacao: datetime

    model_config = ConfigDict(from_attributes=True)


def buscar_setor_ou_404(setor_id: uuid.UUID, database: Session) -> Setor:
    setor = database.get(Setor, setor_id)
    if not setor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setor não encontrado")
    return setor


# ROTAS

@router.post("/", response_model=SetorResposta, status_code=status.HTTP_201_CREATED)
async def criarSetor(
    dados: SetorCriar,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    existente = database.scalar(select(Setor).where(Setor.nome == dados.nome))
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um setor com esse nome",
        )

    novo_setor = Setor(nome=dados.nome)
    database.add(novo_setor)
    database.commit()
    database.refresh(novo_setor)
    return novo_setor


@router.get("/", response_model=list[SetorResposta])
async def listarSetores(
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    return database.scalars(select(Setor).order_by(Setor.nome)).all()


@router.put("/{setor_id}", response_model=SetorResposta)
async def editarSetor(
    setor_id: uuid.UUID,
    dados: SetorEditar,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    setor = buscar_setor_ou_404(setor_id, database)

    existente = database.scalar(
        select(Setor).where(Setor.nome == dados.nome, Setor.id != setor_id)
    )
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um setor com esse nome",
        )

    setor.nome = dados.nome
    database.commit()
    database.refresh(setor)
    return setor


@router.delete("/{setor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluirSetor(
    setor_id: uuid.UUID,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    setor = buscar_setor_ou_404(setor_id, database)
    database.delete(setor)
    database.commit()
