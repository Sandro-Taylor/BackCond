from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from datetime import date
import uuid

from App.database import get_database
from Router.Pessoa.CadastrarPessoas import (
    Pessoa,
    Apartamento,
    PessoaApartamento,
    Vaga,
    Veiculo,
)

router = APIRouter()


# =========================================================
# PESSOA
# =========================================================

class PessoaUpdate(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cpf: str | None = Field(default=None, max_length=14)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=20)
    data_nascimento: date | None = None
    ativo: bool


@router.put("/{pessoa_id}")
def editarPessoa(
    pessoa_id: uuid.UUID,
    dados: PessoaUpdate,
    database: Session = Depends(get_database)
):
    pessoa = database.get(Pessoa, pessoa_id)

    if not pessoa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pessoa não encontrada"
        )

    pessoa.nome = dados.nome
    pessoa.cpf = dados.cpf
    pessoa.email = dados.email.lower() if dados.email else None
    pessoa.telefone = dados.telefone
    pessoa.data_nascimento = dados.data_nascimento
    pessoa.ativo = dados.ativo

    database.commit()
    database.refresh(pessoa)

    return pessoa


# =========================================================
# APARTAMENTO
# =========================================================

class ApartamentoUpdate(BaseModel):
    bloco: str | None = Field(default=None, max_length=50)
    numero: str = Field(max_length=20)
    andar: int | None = None
    observacao: str | None = None
    ativo: bool


@router.put("/apartamentos/{apartamento_id}")
def editarApartamento(
    apartamento_id: uuid.UUID,
    dados: ApartamentoUpdate,
    database: Session = Depends(get_database)
):
    apartamento = database.get(Apartamento, apartamento_id)

    if not apartamento:
        raise HTTPException(
            status_code=404,
            detail="Apartamento não encontrado"
        )

    apartamento.bloco = dados.bloco
    apartamento.numero = dados.numero
    apartamento.andar = dados.andar
    apartamento.observacao = dados.observacao
    apartamento.ativo = dados.ativo

    database.commit()
    database.refresh(apartamento)

    return apartamento


# =========================================================
# VÍNCULO PESSOA / APARTAMENTO
# =========================================================

class VinculoUpdate(BaseModel):
    tipo_relacao: str
    principal: bool
    ativo: bool


@router.put("/vinculos/{vinculo_id}")
def editarVinculo(
    vinculo_id: uuid.UUID,
    dados: VinculoUpdate,
    database: Session = Depends(get_database)
):
    vinculo = database.get(PessoaApartamento, vinculo_id)

    if not vinculo:
        raise HTTPException(
            status_code=404,
            detail="Vínculo não encontrado"
        )

    if dados.tipo_relacao not in ("PROPRIETARIO", "MORADOR"):
        raise HTTPException(
            status_code=400,
            detail="Tipo de relação inválido"
        )

    vinculo.tipo_relacao = dados.tipo_relacao
    vinculo.principal = dados.principal
    vinculo.ativo = dados.ativo

    database.commit()
    database.refresh(vinculo)

    return vinculo


# =========================================================
# VAGA
# =========================================================

class VagaUpdate(BaseModel):
    numero: str = Field(max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None
    ativo: bool


@router.put("/vagas/{vaga_id}")
def editarVaga(
    vaga_id: uuid.UUID,
    dados: VagaUpdate,
    database: Session = Depends(get_database)
):
    vaga = database.get(Vaga, vaga_id)

    if not vaga:
        raise HTTPException(
            status_code=404,
            detail="Vaga não encontrada"
        )

    vaga.numero = dados.numero
    vaga.localizacao = dados.localizacao
    vaga.observacao = dados.observacao
    vaga.ativo = dados.ativo

    database.commit()
    database.refresh(vaga)

    return vaga


# =========================================================
# VEÍCULO
# =========================================================

class VeiculoUpdate(BaseModel):
    placa: str | None = Field(default=None, max_length=10)
    marca: str | None = Field(default=None, max_length=50)
    modelo: str | None = Field(default=None, max_length=80)
    cor: str | None = Field(default=None, max_length=30)
    descricao: str | None = Field(default=None, max_length=255)
    vaga_id: uuid.UUID | None = None
    ativo: bool


@router.put("/veiculos/{veiculo_id}")
def editarVeiculo(
    veiculo_id: uuid.UUID,
    dados: VeiculoUpdate,
    database: Session = Depends(get_database)
):
    veiculo = database.get(Veiculo, veiculo_id)

    if not veiculo:
        raise HTTPException(
            status_code=404,
            detail="Veículo não encontrado"
        )

    if dados.vaga_id:
        vaga = database.get(Vaga, dados.vaga_id)

        if not vaga:
            raise HTTPException(
                status_code=404,
                detail="Vaga não encontrada"
            )

    veiculo.placa = dados.placa
    veiculo.marca = dados.marca
    veiculo.modelo = dados.modelo
    veiculo.cor = dados.cor
    veiculo.descricao = dados.descricao
    veiculo.vaga_id = dados.vaga_id
    veiculo.ativo = dados.ativo

    database.commit()
    database.refresh(veiculo)

    return veiculo