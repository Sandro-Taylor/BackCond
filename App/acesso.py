# ---------------------------------------------------------
# ACESSO AO SISTEMA (login ligado a uma pessoa)
# ---------------------------------------------------------
# Usado ao "dar acesso" a uma pessoa e ao designar o síndico
# de um condomínio.
#   - e-mail sem login: cria o login com senha temporária
#     (troca obrigatória no primeiro acesso)
#   - e-mail que já tem login: só liga o login à pessoa
# ---------------------------------------------------------

import secrets

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.models import Pessoa, User, UserStatus
from App.security import hash_password


def gerar_senha_temporaria() -> str:
    return secrets.token_urlsafe(9)


def ligar_login(database: Session, pessoa: Pessoa, email: str) -> str | None:
    # devolve a senha temporária quando um login novo é criado (o commit fica com quem chamou)
    usuario = database.scalar(select(User).where(User.email == email))
    senha = None

    if usuario:
        ligado_aqui = database.scalar(select(Pessoa.id).where(
            Pessoa.condominio_id == pessoa.condominio_id, Pessoa.user_id == usuario.id, Pessoa.id != pessoa.id,
        ))
        if ligado_aqui:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este e-mail já é o login de outra pessoa deste condomínio")
    else:
        senha = gerar_senha_temporaria()
        usuario = User(email=email, full_name=pessoa.nome, password_hash=hash_password(senha), status=UserStatus.ativo.value, trocar_senha=True)
        database.add(usuario)
        database.flush()

    pessoa.email = email
    pessoa.user_id = usuario.id
    return senha
