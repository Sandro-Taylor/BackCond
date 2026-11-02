# ---------------------------------------------------------
# PESSOAS – EDIÇÃO
# ---------------------------------------------------------
# Edita os dados da pessoa. Vínculos com apartamentos, vagas e
# veículos são editados em Router/Apartamentos.py.
# Se a pessoa tem acesso ao sistema, o login (e-mail e nome)
# acompanha o cadastro.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, garantir_unico, salvar
from App.database import get_database
from App.dependencies import Contexto, apartamentos_do_usuario, exigir_adm_para_perfil, get_contexto, negar
from App.models import PerfilPessoa, Pessoa, PessoaApartamento, User
from App.responsaveis import validar_responsavel_escolhido
from Router.Pessoa.CadastrarPessoas import PessoaDados, PessoaResponse

router = APIRouter()


class PessoaUpdate(PessoaDados):
    ativo: bool
    perfil: PerfilPessoa | None = None  # opcional: só altera se for enviado


@router.put("/{pessoa_id}", response_model=PessoaResponse)
def editarPessoa(pessoa_id: uuid.UUID, dados: PessoaUpdate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")

    # morador: só pessoas das próprias unidades, sem mudar perfil nem situação
    if not ctx.edita_tudo:
        if ctx.perfil != "MORADOR":
            negar()
        da_unidade = database.scalar(
            select(PessoaApartamento.id).where(
                PessoaApartamento.pessoa_id == pessoa.id,
                PessoaApartamento.apartamento_id.in_(apartamentos_do_usuario(database, ctx)),
            )
        )
        if not da_unidade or (dados.perfil and dados.perfil != pessoa.perfil) or dados.ativo != pessoa.ativo:
            negar()
        if "responsavel_user_id" in dados.model_fields_set and dados.responsavel_user_id != pessoa.responsavel_user_id:
            negar()  # o responsável é definido pela gestão

    # mudar o perfil de/para síndico ou conselheiro, ou inativá-los: só o ADM
    if dados.perfil and dados.perfil != pessoa.perfil:
        exigir_adm_para_perfil(ctx, pessoa.perfil, dados.perfil)
    if dados.ativo != pessoa.ativo:
        exigir_adm_para_perfil(ctx, pessoa.perfil)

    if dados.cpf:
        garantir_unico(database, Pessoa, ctx.condominio_id, {"cpf": dados.cpf}, "CPF já cadastrado neste condomínio", ignorar_id=pessoa.id)

    # login acompanha o cadastro (e-mail e nome)
    if pessoa.user_id:
        if not dados.email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta pessoa tem acesso ao sistema: o e-mail é obrigatório, pois é o login dela")
        usuario = database.get(User, pessoa.user_id)
        if usuario:
            if usuario.email != dados.email:
                em_uso = database.scalar(select(User.id).where(User.email == dados.email, User.id != usuario.id))
                if em_uso:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este e-mail já é o login de outro usuário")
                usuario.email = dados.email
            usuario.full_name = dados.nome.strip()

    pessoa.nome = dados.nome.strip()
    pessoa.cpf = dados.cpf
    pessoa.email = dados.email
    pessoa.telefone = dados.telefone
    pessoa.data_nascimento = dados.data_nascimento
    pessoa.ativo = dados.ativo
    if "responsavel_user_id" in dados.model_fields_set and dados.responsavel_user_id != pessoa.responsavel_user_id:
        if not ctx.usuario.admin_sistema:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Somente o administrador do sistema define o responsável")
        validar_responsavel_escolhido(database, dados.responsavel_user_id)
        pessoa.responsavel_user_id = dados.responsavel_user_id
    if dados.perfil:
        pessoa.perfil = dados.perfil
        if dados.perfil != "FUNCIONARIO":
            pessoa.funcionario = None  # a ficha só existe para funcionário

    salvar(database)
    database.refresh(pessoa)
    return pessoa
