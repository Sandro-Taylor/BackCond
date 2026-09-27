# ---------------------------------------------------------
# PESSOAS – EDIÇÃO
# ---------------------------------------------------------
# Edita os dados da pessoa. Vínculos com apartamentos, vagas e
# veículos são editados em Router/Apartamentos.py.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, garantir_unico, salvar
from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import PerfilPessoa, Pessoa
from Router.Pessoa.CadastrarPessoas import PessoaDados, PessoaResponse

router = APIRouter()


class PessoaUpdate(PessoaDados):
    ativo: bool
    perfil: PerfilPessoa | None = None  # opcional: só altera se for enviado


@router.put("/{pessoa_id}", response_model=PessoaResponse)
def editarPessoa(pessoa_id: uuid.UUID, dados: PessoaUpdate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")

    if dados.cpf:
        garantir_unico(database, Pessoa, ctx.condominio_id, {"cpf": dados.cpf}, "CPF já cadastrado neste condomínio", ignorar_id=pessoa.id)

    pessoa.nome = dados.nome.strip()
    pessoa.cpf = dados.cpf
    pessoa.email = dados.email
    pessoa.telefone = dados.telefone
    pessoa.data_nascimento = dados.data_nascimento
    pessoa.ativo = dados.ativo
    if dados.perfil:
        pessoa.perfil = dados.perfil

    salvar(database)
    database.refresh(pessoa)
    return pessoa
