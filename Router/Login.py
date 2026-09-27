# ---------------------------------------------------------
# LOGIN
# ---------------------------------------------------------

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.database import get_database
from App.models import User, UserStatus
from App.security import create_access_token, verify_password

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


@router.post("/", response_model=TokenResponse)
def login(login_data: LoginRequest, database: Session = Depends(get_database)):
    user = database.scalar(select(User).where(User.email == login_data.email.lower()))

    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos")

    if user.status != UserStatus.ativo.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário sem acesso ao sistema")

    return {"access_token": create_access_token(str(user.id)), "token_type": "bearer"}
