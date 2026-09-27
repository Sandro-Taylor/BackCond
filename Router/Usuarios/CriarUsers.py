# ---------------------------------------------------------
# USUÁRIOS (login)
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.database import get_database
from App.models import User, UserStatus  # UserStatus: ainda usado por Moradores.py até o 3.3.5
from App.security import hash_password

router = APIRouter()


class UserCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    status: str
    admin_sistema: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def criarUser(user_data: UserCreate, database: Session = Depends(get_database)):
    email = user_data.email.lower()

    if database.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-mail já cadastrado")

    user = User(full_name=user_data.full_name.strip(), email=email, password_hash=hash_password(user_data.password))
    database.add(user)
    database.commit()
    database.refresh(user)
    return user
