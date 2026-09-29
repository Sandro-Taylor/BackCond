# ---------------------------------------------------------
# USUÁRIOS – GESTÃO PELO ADM DO SISTEMA
# ---------------------------------------------------------
# Lista todos os logins do sistema com os condomínios e o
# perfil em cada um; bloqueia/desbloqueia e gera nova senha
# temporária. Só o ADM do sistema.
# ---------------------------------------------------------

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.acesso import gerar_senha_temporaria
from App.consultas import salvar
from App.database import get_database
from App.dependencies import exigir_admin_sistema
from App.models import Condominio, Pessoa, User
from App.security import hash_password

router = APIRouter()


class AcessoEmCondominio(BaseModel):
    condominio_id: uuid.UUID
    condominio_nome: str
    perfil: str
    ativo: bool


class UsuarioLista(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    status: str
    admin_sistema: bool
    trocar_senha: bool
    created_at: datetime
    condominios: list[AcessoEmCondominio]


class MudarStatus(BaseModel):
    status: Literal["ativo", "bloqueado"]


class NovaSenha(BaseModel):
    email: str
    senha_temporaria: str


def buscar_usuario(database: Session, user_id: uuid.UUID) -> User:
    usuario = database.get(User, user_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    return usuario


@router.get("/", response_model=list[UsuarioLista])
def listarUsuarios(database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    acessos: dict = {}
    for pessoa, nome in database.execute(
        select(Pessoa, Condominio.nome).join(Condominio, Condominio.id == Pessoa.condominio_id)
        .where(Pessoa.user_id.is_not(None)).order_by(Condominio.nome)
    ).all():
        acessos.setdefault(pessoa.user_id, []).append(
            {"condominio_id": pessoa.condominio_id, "condominio_nome": nome, "perfil": pessoa.perfil, "ativo": pessoa.ativo}
        )

    usuarios = database.scalars(select(User).order_by(User.admin_sistema.desc(), User.full_name)).all()
    return [{
        "id": u.id, "full_name": u.full_name, "email": u.email, "status": u.status, "admin_sistema": u.admin_sistema,
        "trocar_senha": u.trocar_senha, "created_at": u.created_at, "condominios": acessos.get(u.id, []),
    } for u in usuarios]


@router.patch("/{user_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def mudarStatus(user_id: uuid.UUID, dados: MudarStatus, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    usuario = buscar_usuario(database, user_id)
    if usuario.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Você não pode bloquear o seu próprio usuário")
    usuario.status = dados.status
    salvar(database)


@router.post("/{user_id}/nova-senha", response_model=NovaSenha)
def gerarNovaSenha(user_id: uuid.UUID, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    usuario = buscar_usuario(database, user_id)
    senha = gerar_senha_temporaria()
    usuario.password_hash = hash_password(senha)
    usuario.trocar_senha = True
    salvar(database)
    return {"email": usuario.email, "senha_temporaria": senha}
