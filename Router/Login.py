from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from Router.Users import User, UserStatus
from App.security import create_access_token, verify_password
from App.database import get_database

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

router = APIRouter()

@router.post("/",response_model=TokenResponse)
def login( login_data: LoginRequest, database: Session = Depends(get_database) ):
    user = database.scalar( select(User).where( User.email == login_data.email.lower() ) )

    if not user or not verify_password( login_data.password, user.password_hash ):
        raise HTTPException( status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos" )

    if user.status != UserStatus.active:
        raise HTTPException( status_code=status.HTTP_403_FORBIDDEN, detail="Usuário sem acesso ao sistema" )

    access_token = create_access_token( str(user.id) )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }