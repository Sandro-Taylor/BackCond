# ---------------------------------------------------------
# PESSOAS – CADASTRO
# ---------------------------------------------------------
# Tudo é gravado no condomínio do contexto (cabeçalho
# X-Condominio-Id). Nenhuma consulta sai desse condomínio.
# ---------------------------------------------------------

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, garantir_unico, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import Apartamento, PerfilPessoa, Pessoa, PessoaApartamento, TipoRelacao, Vaga, Veiculo
from App.validacoes import normalizar_cpf, normalizar_email, normalizar_placa, normalizar_telefone

router = APIRouter()


# =========================================================
# DADOS RECEBIDOS
# =========================================================

class VeiculoCreate(BaseModel):
    placa: str | None = None
    marca: str | None = Field(default=None, max_length=50)
    modelo: str | None = Field(default=None, max_length=80)
    cor: str | None = Field(default=None, max_length=30)
    descricao: str | None = Field(default=None, max_length=255)

    @field_validator("placa")
    @classmethod
    def validar_placa(cls, valor):
        return normalizar_placa(valor)


class VagaCreate(BaseModel):
    numero: str = Field(min_length=1, max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None
    veiculos: list[VeiculoCreate] = Field(default_factory=list)


class ApartamentoCreate(BaseModel):
    bloco: str | None = Field(default=None, max_length=20)
    numero: str = Field(min_length=1, max_length=10)
    andar: int | None = Field(default=None, ge=-10, le=300)
    observacao: str | None = None
    tipo_relacao: TipoRelacao
    principal: bool = False
    vagas: list[VagaCreate] = Field(default_factory=list)


class PessoaCreate(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cpf: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    data_nascimento: date | None = None
    perfil: PerfilPessoa = "MORADOR"
    apartamentos: list[ApartamentoCreate] = Field(default_factory=list)

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


class NovaVaga(BaseModel):
    numero: str = Field(min_length=1, max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None


class NovoVeiculo(VeiculoCreate):
    pessoa_id: uuid.UUID


# =========================================================
# RESPOSTAS
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
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ApartamentoResposta(BaseModel):
    id: uuid.UUID
    bloco: str
    numero: str
    andar: int | None
    observacao: str | None
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


class VinculoResposta(BaseModel):
    id: uuid.UUID
    pessoa_id: uuid.UUID
    apartamento_id: uuid.UUID
    tipo_relacao: str
    principal: bool
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


class VagaResposta(BaseModel):
    id: uuid.UUID
    apartamento_id: uuid.UUID
    numero: str
    localizacao: str | None
    observacao: str | None
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


class VeiculoResposta(BaseModel):
    id: uuid.UUID
    pessoa_id: uuid.UUID
    vaga_id: uuid.UUID | None
    placa: str | None
    marca: str | None
    modelo: str | None
    cor: str | None
    descricao: str | None
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


# =========================================================
# CADASTRAR PESSOA (com apartamentos, vagas e veículos)
# =========================================================

@router.post("/", response_model=PessoaResponse, status_code=status.HTTP_201_CREATED)
def cadastrarPessoa(dados: PessoaCreate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    cid = ctx.condominio_id

    if dados.cpf:
        garantir_unico(database, Pessoa, cid, {"cpf": dados.cpf}, "CPF já cadastrado neste condomínio")

    if sum(1 for apartamento in dados.apartamentos if apartamento.principal) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Apenas um apartamento pode ser o principal")

    try:
        pessoa = Pessoa(
            condominio_id=cid,
            nome=dados.nome.strip(),
            cpf=dados.cpf,
            email=dados.email,
            telefone=dados.telefone,
            data_nascimento=dados.data_nascimento,
            perfil=dados.perfil,
        )
        database.add(pessoa)
        database.flush()

        for apartamento_data in dados.apartamentos:
            bloco = (apartamento_data.bloco or "").strip().upper()
            numero = apartamento_data.numero.strip()

            apartamento = database.scalar(
                select(Apartamento).where(Apartamento.condominio_id == cid, Apartamento.bloco == bloco, Apartamento.numero == numero)
            )
            if not apartamento:
                apartamento = Apartamento(
                    condominio_id=cid,
                    bloco=bloco,
                    numero=numero,
                    andar=apartamento_data.andar,
                    observacao=texto(apartamento_data.observacao),
                )
                database.add(apartamento)
                database.flush()

            vinculo_existente = database.scalar(
                select(PessoaApartamento.id).where(PessoaApartamento.pessoa_id == pessoa.id, PessoaApartamento.apartamento_id == apartamento.id)
            )
            if vinculo_existente:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Apartamento {numero} informado mais de uma vez")

            database.add(PessoaApartamento(
                pessoa_id=pessoa.id,
                apartamento_id=apartamento.id,
                tipo_relacao=apartamento_data.tipo_relacao,
                principal=apartamento_data.principal,
            ))
            database.flush()

            for vaga_data in apartamento_data.vagas:
                numero_vaga = vaga_data.numero.strip()
                vaga = database.scalar(select(Vaga).where(Vaga.condominio_id == cid, Vaga.numero == numero_vaga))
                if not vaga:
                    vaga = Vaga(
                        condominio_id=cid,
                        apartamento_id=apartamento.id,
                        numero=numero_vaga,
                        localizacao=texto(vaga_data.localizacao),
                        observacao=texto(vaga_data.observacao),
                    )
                    database.add(vaga)
                    database.flush()
                elif vaga.apartamento_id != apartamento.id:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A vaga {numero_vaga} já pertence a outro apartamento")

                for veiculo_data in vaga_data.veiculos:
                    if veiculo_data.placa:
                        garantir_unico(database, Veiculo, cid, {"placa": veiculo_data.placa}, f"Placa {veiculo_data.placa} já cadastrada neste condomínio")
                    database.add(Veiculo(
                        condominio_id=cid,
                        pessoa_id=pessoa.id,
                        vaga_id=vaga.id,
                        placa=veiculo_data.placa,
                        marca=texto(veiculo_data.marca),
                        modelo=texto(veiculo_data.modelo),
                        cor=texto(veiculo_data.cor),
                        descricao=texto(veiculo_data.descricao),
                    ))
                    database.flush()

        database.commit()
    except HTTPException:
        database.rollback()
        raise
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Não foi possível cadastrar: existem dados duplicados")

    database.refresh(pessoa)
    return pessoa


# =========================================================
# ADICIONAR VAGA A UM APARTAMENTO
# =========================================================

@router.post("/apartamentos/{apartamento_id}/vagas", response_model=VagaResposta, status_code=status.HTTP_201_CREATED)
def adicionarVaga(apartamento_id: uuid.UUID, dados: NovaVaga, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")

    numero = dados.numero.strip()
    garantir_unico(database, Vaga, ctx.condominio_id, {"numero": numero}, f"Vaga {numero} já cadastrada neste condomínio")

    vaga = Vaga(
        condominio_id=ctx.condominio_id,
        apartamento_id=apartamento.id,
        numero=numero,
        localizacao=texto(dados.localizacao),
        observacao=texto(dados.observacao),
    )
    database.add(vaga)
    salvar(database)
    database.refresh(vaga)
    return vaga


# =========================================================
# ADICIONAR VEÍCULO EM UMA VAGA
# =========================================================

@router.post("/vagas/{vaga_id}/veiculos", response_model=VeiculoResposta, status_code=status.HTTP_201_CREATED)
def adicionarVeiculo(vaga_id: uuid.UUID, dados: NovoVeiculo, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    cid = ctx.condominio_id
    vaga = buscar_no_condominio(database, Vaga, vaga_id, cid, "Vaga não encontrada")
    pessoa = buscar_no_condominio(database, Pessoa, dados.pessoa_id, cid, "Pessoa não encontrada")

    vinculo = database.scalar(
        select(PessoaApartamento.id).where(PessoaApartamento.pessoa_id == pessoa.id, PessoaApartamento.apartamento_id == vaga.apartamento_id)
    )
    if not vinculo:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A pessoa não possui vínculo com o apartamento desta vaga")

    if dados.placa:
        garantir_unico(database, Veiculo, cid, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio")

    veiculo = Veiculo(
        condominio_id=cid,
        pessoa_id=pessoa.id,
        vaga_id=vaga.id,
        placa=dados.placa,
        marca=texto(dados.marca),
        modelo=texto(dados.modelo),
        cor=texto(dados.cor),
        descricao=texto(dados.descricao),
    )
    database.add(veiculo)
    salvar(database)
    database.refresh(veiculo)
    return veiculo


# =========================================================
# ADICIONAR VEÍCULO SEM VAGA
# =========================================================

@router.post("/{pessoa_id}/veiculos", response_model=VeiculoResposta, status_code=status.HTTP_201_CREATED)
def adicionarVeiculoPessoa(pessoa_id: uuid.UUID, dados: VeiculoCreate, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    cid = ctx.condominio_id
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, cid, "Pessoa não encontrada")

    if dados.placa:
        garantir_unico(database, Veiculo, cid, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio")

    veiculo = Veiculo(
        condominio_id=cid,
        pessoa_id=pessoa.id,
        vaga_id=None,
        placa=dados.placa,
        marca=texto(dados.marca),
        modelo=texto(dados.modelo),
        cor=texto(dados.cor),
        descricao=texto(dados.descricao),
    )
    database.add(veiculo)
    salvar(database)
    database.refresh(veiculo)
    return veiculo
