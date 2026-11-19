# ---------------------------------------------------------
# USUÁRIOS (login)
# ---------------------------------------------------------
# Criação avulsa de login: só o ADM do sistema. Moradores,
# síndicos etc. recebem login pelo "Dar acesso ao sistema"
# (Router/Pessoa/AcessoPessoas.py).
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.acesso import gerar_senha_temporaria
from App.database import get_database
from App.dependencies import exigir_admin_sistema
from App.models import User
from App.security import hash_password

router = APIRouter()


class UserCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=150)
    email: EmailStr
    admin_sistema: bool = False  # ADM do sistema: vê e administra todos os condomínios


class UserResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    status: str
    admin_sistema: bool
    created_at: datetime
    senha_temporaria: str = ""  # mostrada uma única vez; troca obrigatória no primeiro login
    model_config = ConfigDict(from_attributes=True)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def criarUser(user_data: UserCreate, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    email = user_data.email.lower()

    if database.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado")

    senha = gerar_senha_temporaria()
    user = User(full_name=user_data.full_name.strip(), email=email, password_hash=hash_password(senha),
                admin_sistema=user_data.admin_sistema, trocar_senha=True)
    database.add(user)
    database.commit()
    database.refresh(user)
    resposta = UserResponse.model_validate(user)
    resposta.senha_temporaria = senha
    return resposta
