# ---------------------------------------------------------
# PESSOAS – ACESSO AO SISTEMA
# ---------------------------------------------------------
# Dar acesso: usa o e-mail da pessoa como login.
#   - e-mail sem login: cria o login (nome da pessoa + senha
#     temporária, mostrada uma única vez)
#   - e-mail que já tem login (ex.: síndico de outro
#     condomínio): só liga o login existente à pessoa
# Remover acesso: desliga o login da pessoa (não apaga nada).
# Nova senha: gera outra senha temporária.
# Senha temporária obriga a troca no próximo login (/eu/senha).
# Tudo restrito a ADM e síndico; o acesso do síndico e dos
# conselheiros só o ADM remove.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, salvar
from App.database import get_database
from App.acesso import gerar_senha_temporaria, ligar_login
from App.dependencies import Contexto, exigir_adm_para_perfil, exigir_gestao
from App.models import Pessoa, User
from App.security import hash_password
from App.validacoes import normalizar_email

router = APIRouter()


class DarAcesso(BaseModel):
    email: EmailStr | None = None  # vazio = usa o e-mail do cadastro

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class AcessoResposta(BaseModel):
    email: str
    senha_temporaria: str | None  # só quando um login é criado ou a senha é redefinida
    login_existente: bool


@router.post("/{pessoa_id}/acesso", response_model=AcessoResposta)
def darAcesso(pessoa_id: uuid.UUID, dados: DarAcesso, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")
    if pessoa.user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta pessoa já tem acesso ao sistema")

    email = dados.email or pessoa.email
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o e-mail: ele será o login da pessoa")

    senha = ligar_login(database, pessoa, email)
    salvar(database)
    return {"email": email, "senha_temporaria": senha, "login_existente": senha is None}


@router.delete("/{pessoa_id}/acesso", status_code=status.HTTP_204_NO_CONTENT)
def removerAcesso(pessoa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")
    exigir_adm_para_perfil(ctx, pessoa.perfil)  # acesso do síndico/conselheiro: só o ADM remove
    pessoa.user_id = None
    salvar(database)


@router.post("/{pessoa_id}/acesso/nova-senha", response_model=AcessoResposta)
def novaSenha(pessoa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")
    usuario = database.get(User, pessoa.user_id) if pessoa.user_id else None
    if not usuario:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta pessoa não tem acesso ao sistema")
    if usuario.admin_sistema and not ctx.usuario.admin_sistema:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Não é possível redefinir a senha do administrador do sistema")

    senha = gerar_senha_temporaria()
    usuario.password_hash = hash_password(senha)
    usuario.trocar_senha = True
    salvar(database)
    return {"email": usuario.email, "senha_temporaria": senha, "login_existente": True}
