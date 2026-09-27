# ---------------------------------------------------------
# CONSULTAS COMPARTILHADAS
# ---------------------------------------------------------
# Funções usadas por várias rotas. Todas recebem o
# condominio_id e nunca buscam fora dele.
# ---------------------------------------------------------

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from App.models import Pessoa, PessoaApartamento


def buscar_no_condominio(database: Session, modelo, registro_id: uuid.UUID, condominio_id: uuid.UUID, mensagem: str):
    registro = database.scalar(select(modelo).where(modelo.id == registro_id, modelo.condominio_id == condominio_id))
    if not registro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=mensagem)
    return registro


def buscar_vinculo_no_condominio(database: Session, vinculo_id: uuid.UUID, condominio_id: uuid.UUID) -> PessoaApartamento:
    vinculo = database.scalar(
        select(PessoaApartamento)
        .join(Pessoa, Pessoa.id == PessoaApartamento.pessoa_id)
        .where(PessoaApartamento.id == vinculo_id, Pessoa.condominio_id == condominio_id)
    )
    if not vinculo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vínculo não encontrado")
    return vinculo


def garantir_unico(database: Session, modelo, condominio_id: uuid.UUID, filtros: dict, mensagem: str, ignorar_id: uuid.UUID | None = None):
    consulta = select(modelo.id).where(
        modelo.condominio_id == condominio_id,
        *[getattr(modelo, campo) == valor for campo, valor in filtros.items()],
    )
    if ignorar_id is not None:
        consulta = consulta.where(modelo.id != ignorar_id)
    if database.scalar(consulta):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mensagem)


def salvar(database: Session, mensagem: str = "Não foi possível salvar: já existe um registro com esses dados ou ele está em uso"):
    # rede de segurança: se o banco recusar por duplicidade/vínculo, devolve 409 em vez de 500
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mensagem)


def texto(valor: str | None) -> str | None:
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None
