# ---------------------------------------------------------
# EU (usuário autenticado)
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.database import get_database
from App.dependencies import get_current_user
from Router.Colaboradores import Colaborador
from Router.Users import User, UserResponse


router = APIRouter()

TIPO_NOMES = {
    "1": "Visualizador",
    "2": "Editor",
    "3": "Analista",
    "4": "Supervisor",
    "5": "Administrador",
}


class AuthenticatedUserResponse(UserResponse):
    idColaborador: uuid.UUID | None
    tipo: str | None
    role: str | None
    cargo: str | None
    ativo: bool | None


@router.get("/", response_model=AuthenticatedUserResponse)
def eu(
    user: User = Depends(get_current_user),
    database: Session = Depends(get_database),
):
    colaborador = database.scalar(
        select(Colaborador).where(Colaborador.idUser == user.id)
    )

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "status": user.status,
        "created_at": user.created_at,
        "idColaborador": colaborador.idColaborador if colaborador else None,
        "tipo": colaborador.tipo if colaborador else None,
        "role": TIPO_NOMES.get(colaborador.tipo) if colaborador else None,
        "cargo": colaborador.cargo if colaborador else None,
        "ativo": colaborador.ativo if colaborador else None,
    }