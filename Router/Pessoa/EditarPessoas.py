# ---------------------------------------------------------
# PESSOAS – EDIÇÃO
# ---------------------------------------------------------
# Só edita registros do condomínio do contexto.
# ---------------------------------------------------------

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import update
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, buscar_vinculo_no_condominio, garantir_unico, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import Apartamento, PerfilPessoa, Pessoa, PessoaApartamento, TipoRelacao, Vaga, Veiculo
from App.validacoes import normalizar_cpf, normalizar_email, normalizar_placa, normalizar_telefone
from Router.Pessoa.CadastrarPessoas import ApartamentoResposta, PessoaResponse, VagaResposta, VeiculoResposta, VinculoResposta

router = APIRouter()


# =========================================================
# PESSOA
# =========================================================

class PessoaUpdate(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cpf: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    data_nascimento: date | None = None
    ativo: bool
    perfil: PerfilPessoa | None = None  # opcional: só altera se for enviado

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


# =========================================================
# APARTAMENTO
# =========================================================

class ApartamentoUpdate(BaseModel):
    bloco: str | None = Field(default=None, max_length=20)
    numero: str = Field(min_length=1, max_length=10)
    andar: int | None = Field(default=None, ge=-10, le=300)
    observacao: str | None = None
    ativo: bool


@router.put("/apartamentos/{apartamento_id}", response_model=ApartamentoResposta)
def editarApartamento(apartamento_id: uuid.UUID, dados: ApartamentoUpdate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")

    bloco = (dados.bloco or "").strip().upper()
    numero = dados.numero.strip()
    garantir_unico(database, Apartamento, ctx.condominio_id, {"bloco": bloco, "numero": numero}, "Já existe um apartamento com este bloco e número", ignorar_id=apartamento.id)

    apartamento.bloco = bloco
    apartamento.numero = numero
    apartamento.andar = dados.andar
    apartamento.observacao = texto(dados.observacao)
    apartamento.ativo = dados.ativo

    salvar(database)
    database.refresh(apartamento)
    return apartamento


# =========================================================
# VÍNCULO PESSOA / APARTAMENTO
# =========================================================

class VinculoUpdate(BaseModel):
    tipo_relacao: TipoRelacao
    principal: bool
    ativo: bool


@router.put("/vinculos/{vinculo_id}", response_model=VinculoResposta)
def editarVinculo(vinculo_id: uuid.UUID, dados: VinculoUpdate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    vinculo = buscar_vinculo_no_condominio(database, vinculo_id, ctx.condominio_id)

    # só pode haver 1 apartamento principal por pessoa: desmarca os outros antes
    if dados.principal and not vinculo.principal:
        database.execute(
            update(PessoaApartamento)
            .where(PessoaApartamento.pessoa_id == vinculo.pessoa_id, PessoaApartamento.id != vinculo.id)
            .values(principal=False)
        )

    vinculo.tipo_relacao = dados.tipo_relacao
    vinculo.principal = dados.principal
    vinculo.ativo = dados.ativo

    salvar(database)
    database.refresh(vinculo)
    return vinculo


# =========================================================
# VAGA
# =========================================================

class VagaUpdate(BaseModel):
    numero: str = Field(min_length=1, max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None
    ativo: bool


@router.put("/vagas/{vaga_id}", response_model=VagaResposta)
def editarVaga(vaga_id: uuid.UUID, dados: VagaUpdate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    vaga = buscar_no_condominio(database, Vaga, vaga_id, ctx.condominio_id, "Vaga não encontrada")

    numero = dados.numero.strip()
    garantir_unico(database, Vaga, ctx.condominio_id, {"numero": numero}, f"Vaga {numero} já cadastrada neste condomínio", ignorar_id=vaga.id)

    vaga.numero = numero
    vaga.localizacao = texto(dados.localizacao)
    vaga.observacao = texto(dados.observacao)
    vaga.ativo = dados.ativo

    salvar(database)
    database.refresh(vaga)
    return vaga


# =========================================================
# VEÍCULO
# =========================================================

class VeiculoUpdate(BaseModel):
    placa: str | None = None
    marca: str | None = Field(default=None, max_length=50)
    modelo: str | None = Field(default=None, max_length=80)
    cor: str | None = Field(default=None, max_length=30)
    descricao: str | None = Field(default=None, max_length=255)
    vaga_id: uuid.UUID | None = None
    ativo: bool

    @field_validator("placa")
    @classmethod
    def validar_placa(cls, valor):
        return normalizar_placa(valor)


@router.put("/veiculos/{veiculo_id}", response_model=VeiculoResposta)
def editarVeiculo(veiculo_id: uuid.UUID, dados: VeiculoUpdate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    veiculo = buscar_no_condominio(database, Veiculo, veiculo_id, ctx.condominio_id, "Veículo não encontrado")

    if dados.vaga_id:
        buscar_no_condominio(database, Vaga, dados.vaga_id, ctx.condominio_id, "Vaga não encontrada")

    if dados.placa:
        garantir_unico(database, Veiculo, ctx.condominio_id, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio", ignorar_id=veiculo.id)

    veiculo.placa = dados.placa
    veiculo.marca = texto(dados.marca)
    veiculo.modelo = texto(dados.modelo)
    veiculo.cor = texto(dados.cor)
    veiculo.descricao = texto(dados.descricao)
    veiculo.vaga_id = dados.vaga_id
    veiculo.ativo = dados.ativo

    salvar(database)
    database.refresh(veiculo)
    return veiculo
