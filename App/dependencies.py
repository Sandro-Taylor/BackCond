# ---------------------------------------------------------
# DEPENDÊNCIAS DA API
# ---------------------------------------------------------
# Disponibiliza o usuário autenticado para as rotas.
# ---------------------------------------------------------

from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from App.security import decode_access_token
from App.database import get_database
from Router.Users import User

authentication = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(authentication), database: Session = Depends(get_database)):
    try:
        user_id = decode_access_token(credentials.credentials)
        user_uuid = UUID(user_id)
    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        )
    user = database.get(User, user_uuid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado",
        )
    return user