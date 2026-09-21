from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session
from App.database import get_database
from App.security import hash_password

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from App.database import Base

router = APIRouter()

class UserStatus(str, Enum):
    ativo = "ativo"
    inativo = "inativo"
    bloqueado = "bloqueado"

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255),unique=True,nullable=False)
    password_hash: Mapped[str] = mapped_column(String,nullable=False)
    full_name: Mapped[str] = mapped_column(String(150),nullable=False)
    status: Mapped[UserStatus] = mapped_column(ENUM(UserStatus,name="user_status",create_type=False),default=UserStatus.ativo,nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class UserCreate(BaseModel):
    full_name: str = Field(min_length=3,max_length=150)
    email: EmailStr
    password: str = Field(min_length=8,max_length=128)

class UserResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: EmailStr
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def criarUser( user_data: UserCreate, database: Session = Depends(get_database) ):
    existing_user = database.scalar( select(User).where(User.email == user_data.email.lower()))

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já cadastrado",
        )

    user = User(
        full_name=user_data.full_name,
        email=user_data.email.lower(),
        password_hash=hash_password(user_data.password),
    )

    database.add(user)
    database.commit()
    database.refresh(user)

    return user