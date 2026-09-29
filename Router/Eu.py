# ---------------------------------------------------------
# EU (usuário autenticado)
# ---------------------------------------------------------
# Retorna os dados do usuário logado e os condomínios que ele
# pode acessar, com o perfil em cada um.
# Troca de senha: obrigatória no primeiro acesso (senha
# temporária) e disponível a qualquer momento.
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from App.database import get_database
from App.consultas import salvar
from App.dependencies import get_usuario_logado
from App.models import Condominio, Pessoa, User
from App.security import hash_password, verify_password

router = APIRouter()


class CondominioDoUsuario(BaseModel):
    id: uuid.UUID
    nome: str
    perfil: str
    pessoa_id: uuid.UUID | None


class EuResposta(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    status: str
    admin_sistema: bool
    trocar_senha: bool
    created_at: datetime
    condominios: list[CondominioDoUsuario]


@router.get("/", response_model=EuResposta)
def eu(user: User = Depends(get_usuario_logado), database: Session = Depends(get_database)):
    if user.admin_sistema:
        # ADM do sistema: todos os condomínios ativos
        linhas = database.execute(
            select(Condominio.id, Condominio.nome, Pessoa.id.label("pessoa_id"))
            .outerjoin(Pessoa, and_(Pessoa.condominio_id == Condominio.id, Pessoa.user_id == user.id))
            .where(Condominio.ativo.is_(True))
            .order_by(Condominio.nome)
        ).all()
        condominios = [{"id": l.id, "nome": l.nome, "perfil": "ADM", "pessoa_id": l.pessoa_id} for l in linhas]
    else:
        # Demais usuários: só os condomínios onde têm uma pessoa ativa
        linhas = database.execute(
            select(Condominio.id, Condominio.nome, Pessoa.perfil, Pessoa.id.label("pessoa_id"))
            .join(Pessoa, Pessoa.condominio_id == Condominio.id)
            .where(Pessoa.user_id == user.id, Pessoa.ativo.is_(True), Condominio.ativo.is_(True))
            .order_by(Condominio.nome)
        ).all()
        condominios = [{"id": l.id, "nome": l.nome, "perfil": l.perfil, "pessoa_id": l.pessoa_id} for l in linhas]

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "status": user.status,
        "admin_sistema": user.admin_sistema,
        "trocar_senha": user.trocar_senha,
        "created_at": user.created_at,
        "condominios": condominios,
    }


class TrocarSenha(BaseModel):
    senha_atual: str
    nova_senha: str = Field(min_length=8, max_length=128)


@router.post("/senha", status_code=204)
def trocarSenha(dados: TrocarSenha, user: User = Depends(get_usuario_logado), database: Session = Depends(get_database)):
    if not verify_password(dados.senha_atual, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta")
    if dados.nova_senha == dados.senha_atual:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A nova senha precisa ser diferente da atual")

    user.password_hash = hash_password(dados.nova_senha)
    user.trocar_senha = False
    salvar(database)
