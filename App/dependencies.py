# ---------------------------------------------------------
# DEPENDÊNCIAS DA API
# ---------------------------------------------------------
# get_current_user     -> usuário logado (token válido e ativo)
# get_contexto         -> usuário + condomínio que ele está
#                         acessando + perfil dele nesse condomínio
# exigir_admin_sistema -> só o ADM do sistema passa
# ---------------------------------------------------------

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.database import get_database
from App.models import Condominio, Pessoa, User, UserStatus
from App.security import decode_access_token

authentication = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(authentication), database: Session = Depends(get_database)) -> User:
    try:
        user_uuid = UUID(decode_access_token(credentials.credentials))
    except (InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")

    user = database.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")

    if user.status != UserStatus.ativo.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário sem acesso ao sistema")

    return user


@dataclass
class Contexto:
    usuario: User
    condominio_id: UUID
    pessoa: Pessoa | None  # None quando é o ADM do sistema sem cadastro nesse condomínio
    perfil: str            # "ADM" para o ADM do sistema; senão, o perfil da pessoa


def get_contexto(
    x_condominio_id: UUID = Header(description="Id do condomínio que está sendo acessado"),
    usuario: User = Depends(get_current_user),
    database: Session = Depends(get_database),
) -> Contexto:
    condominio = database.get(Condominio, x_condominio_id)
    if not condominio or (not condominio.ativo and not usuario.admin_sistema):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")

    pessoa = database.scalar(
        select(Pessoa).where(
            Pessoa.condominio_id == x_condominio_id,
            Pessoa.user_id == usuario.id,
            Pessoa.ativo.is_(True),
        )
    )

    if usuario.admin_sistema:
        return Contexto(usuario=usuario, condominio_id=x_condominio_id, pessoa=pessoa, perfil="ADM")

    if not pessoa:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem acesso a este condomínio")

    return Contexto(usuario=usuario, condominio_id=x_condominio_id, pessoa=pessoa, perfil=pessoa.perfil)


def exigir_admin_sistema(usuario: User = Depends(get_current_user)) -> User:
    if not usuario.admin_sistema:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o administrador do sistema pode fazer isso")
    return usuario
