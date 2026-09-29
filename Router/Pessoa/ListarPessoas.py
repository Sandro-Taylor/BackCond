# ---------------------------------------------------------
# PESSOAS – LISTAGEM E BUSCA
# ---------------------------------------------------------
# Lista as pessoas do condomínio com as unidades a que estão
# ligadas. Busca por CPF (usada ao adicionar pessoa num
# apartamento, para reaproveitar quem já está cadastrado).
# ---------------------------------------------------------

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from App.database import get_database
from App.dependencies import Contexto, apartamentos_do_usuario, get_contexto, negar
from App.models import Funcionario, Pessoa, PessoaApartamento
from App.validacoes import normalizar_cpf
from Router.Pessoa.CadastrarPessoas import PessoaResponse
from Router.Pessoa.FuncionarioPessoas import FichaResposta

router = APIRouter()


class ApartamentoResumo(BaseModel):
    id: uuid.UUID
    bloco: str
    numero: str
    model_config = ConfigDict(from_attributes=True)


class VinculoDaPessoa(BaseModel):
    id: uuid.UUID
    tipo_relacao: str
    reside: bool
    parentesco: str | None
    titular_nome: str | None
    principal: bool
    ativo: bool
    apartamento: ApartamentoResumo


class VeiculoDaPessoa(BaseModel):
    id: uuid.UUID
    apartamento_id: uuid.UUID
    placa: str | None
    marca: str | None
    modelo: str | None
    cor: str | None
    model_config = ConfigDict(from_attributes=True)


class PessoaLista(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    perfil: str
    nome: str
    cpf: str | None
    email: str | None
    telefone: str | None
    data_nascimento: date | None
    ativo: bool
    created_at: datetime
    apartamentos: list[VinculoDaPessoa]
    veiculos: list[VeiculoDaPessoa]
    funcionario: FichaResposta | None


def montar_pessoa(pessoa: Pessoa) -> dict:
    return {
        "id": pessoa.id,
        "user_id": pessoa.user_id,
        "perfil": pessoa.perfil,
        "nome": pessoa.nome,
        "cpf": pessoa.cpf,
        "email": pessoa.email,
        "telefone": pessoa.telefone,
        "data_nascimento": pessoa.data_nascimento,
        "ativo": pessoa.ativo,
        "created_at": pessoa.created_at,
        "apartamentos": [
            {
                "id": vinculo.id,
                "tipo_relacao": vinculo.tipo_relacao,
                "reside": vinculo.reside,
                "parentesco": vinculo.parentesco,
                "titular_nome": vinculo.titular.pessoa.nome if vinculo.titular else None,
                "principal": vinculo.principal,
                "ativo": vinculo.ativo,
                "apartamento": vinculo.apartamento,
            }
            for vinculo in pessoa.apartamentos
        ],
        "veiculos": pessoa.veiculos,
        "funcionario": pessoa.funcionario,
    }


@router.get("/", response_model=list[PessoaLista])
def listarPessoas(database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    consulta = select(Pessoa).where(Pessoa.condominio_id == ctx.condominio_id)
    if not ctx.ve_tudo:
        # morador: só as pessoas ligadas às próprias unidades
        if ctx.perfil != "MORADOR":
            negar()
        consulta = consulta.where(
            Pessoa.id.in_(
                select(PessoaApartamento.pessoa_id).where(PessoaApartamento.apartamento_id.in_(apartamentos_do_usuario(database, ctx)))
            )
        )

    pessoas = database.scalars(
        consulta
        .options(
            selectinload(Pessoa.apartamentos).selectinload(PessoaApartamento.apartamento),
            selectinload(Pessoa.apartamentos).selectinload(PessoaApartamento.titular).selectinload(PessoaApartamento.pessoa),
            selectinload(Pessoa.veiculos),
            selectinload(Pessoa.funcionario).selectinload(Funcionario.cargo),
        )
        .order_by(Pessoa.nome)
    ).all()
    return [montar_pessoa(pessoa) for pessoa in pessoas]


@router.get("/cpf/{cpf}", response_model=PessoaResponse)
def buscarPorCpf(cpf: str, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # usada ao adicionar pessoa num apartamento: gestão ou morador
    if not ctx.edita_tudo and ctx.perfil != "MORADOR":
        negar()
    try:
        cpf_limpo = normalizar_cpf(cpf)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CPF inválido")

    pessoa = database.scalar(select(Pessoa).where(Pessoa.condominio_id == ctx.condominio_id, Pessoa.cpf == cpf_limpo))
    if not pessoa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhuma pessoa com este CPF no condomínio")
    return pessoa
