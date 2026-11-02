# ---------------------------------------------------------
# PESSOAS – CADASTRO
# ---------------------------------------------------------
# Cadastra os dados da pessoa (e a ficha, se for funcionário).
# A ligação com apartamento
# (proprietário, inquilino, residente) é feita na tela e nas
# rotas de Apartamentos (Router/Apartamentos.py).
# Responsável do WhatsApp: vazio = síndico do prédio (padrão)
# ou um usuário marcado como RESPONSÁVEL (App/responsaveis.py).
# Só o ADM do sistema define o responsável.
# ---------------------------------------------------------

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from App.consultas import garantir_unico, salvar
from App.database import get_database
from App.dependencies import Contexto, exigir_adm_para_perfil, exigir_gestao
from App.models import PerfilPessoa, Pessoa
from App.responsaveis import responsaveis_cadastrados, sindicos_do_condominio, validar_responsavel_escolhido
from App.validacoes import normalizar_cpf, normalizar_email, normalizar_telefone
from Router.Pessoa.FuncionarioPessoas import FichaFuncionario, FichaResposta, aplicar_ficha

router = APIRouter()


# =========================================================
# DADOS RECEBIDOS (também usados por Apartamentos.py)
# =========================================================

class PessoaDados(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cpf: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    data_nascimento: date | None = None
    responsavel_user_id: uuid.UUID | None = None  # responsável do WhatsApp; vazio = síndico do prédio

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, valor):
        return normalizar_cpf(valor)

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, valor):
        return normalizar_telefone(valor)

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class PessoaCreate(PessoaDados):
    perfil: PerfilPessoa = "MORADOR"
    funcionario: FichaFuncionario | None = None  # obrigatória quando o perfil é FUNCIONARIO


# =========================================================
# RESPOSTA
# =========================================================

class PessoaResponse(BaseModel):
    id: uuid.UUID
    nome: str
    cpf: str | None
    email: str | None
    telefone: str | None
    data_nascimento: date | None
    perfil: str
    ativo: bool
    responsavel_user_id: uuid.UUID | None = None
    created_at: datetime
    funcionario: FichaResposta | None = None
    model_config = ConfigDict(from_attributes=True)


# =========================================================
# OPÇÕES DE RESPONSÁVEL (para o campo do cadastro)
# =========================================================

class OpcaoResponsavel(BaseModel):
    id: uuid.UUID
    nome: str


class OpcaoSindico(OpcaoResponsavel):
    tem_login: bool                        # sem login o síndico não recebe o WhatsApp


class OpcoesResponsavel(BaseModel):
    sindicos: list[OpcaoSindico]           # quem recebe no padrão "síndico do prédio"
    responsaveis: list[OpcaoResponsavel]   # usuários marcados como RESPONSÁVEL


@router.get("/opcoes-responsavel", response_model=OpcoesResponsavel)
def opcoesResponsavel(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    return {
        "sindicos": [{"id": s["pessoa_id"], "nome": s["nome"], "tem_login": s["tem_login"]} for s in sindicos_do_condominio(database, ctx.condominio_id)],
        "responsaveis": [{"id": u.id, "nome": u.full_name} for u in responsaveis_cadastrados(database)],
    }


# =========================================================
# CADASTRAR PESSOA
# =========================================================

@router.post("/", response_model=PessoaResponse, status_code=status.HTTP_201_CREATED)
def cadastrarPessoa(dados: PessoaCreate, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    exigir_adm_para_perfil(ctx, dados.perfil)
    if dados.cpf:
        garantir_unico(database, Pessoa, ctx.condominio_id, {"cpf": dados.cpf}, "CPF já cadastrado neste condomínio")
    if dados.perfil == "FUNCIONARIO" and not dados.funcionario:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o cargo do funcionário")
    if dados.responsavel_user_id and not ctx.usuario.admin_sistema:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Somente o administrador do sistema define o responsável")
    validar_responsavel_escolhido(database, dados.responsavel_user_id)

    pessoa = Pessoa(
        condominio_id=ctx.condominio_id,
        nome=dados.nome.strip(),
        cpf=dados.cpf,
        email=dados.email,
        telefone=dados.telefone,
        data_nascimento=dados.data_nascimento,
        perfil=dados.perfil,
        responsavel_user_id=dados.responsavel_user_id,
    )
    if dados.perfil == "FUNCIONARIO":
        aplicar_ficha(database, ctx, pessoa, dados.funcionario)
    database.add(pessoa)
    salvar(database)
    database.refresh(pessoa)
    return pessoa
