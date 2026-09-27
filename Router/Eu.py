# ---------------------------------------------------------
# EU (usuário autenticado)
# ---------------------------------------------------------
# Retorna os dados do usuário logado e os condomínios que ele
# pode acessar, com o perfil em cada um.
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from App.database import get_database
from App.dependencies import get_current_user
from App.models import Condominio, Pessoa, User

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
    created_at: datetime
    condominios: list[CondominioDoUsuario]


@router.get("/", response_model=EuResposta)
def eu(user: User = Depends(get_current_user), database: Session = Depends(get_database)):
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
        "created_at": user.created_at,
        "condominios": condominios,
    }
