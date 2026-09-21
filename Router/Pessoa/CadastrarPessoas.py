from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy import (select, DateTime, String, Boolean, Date, Integer, Text, ForeignKey, func)
from sqlalchemy.orm import Session, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from App.database import get_database, Base
import uuid
from datetime import datetime, date

router = APIRouter()

# MODELS

class Pessoa(Base):
    __tablename__ = "pessoas"
    id: Mapped[uuid.UUID] = mapped_column( UUID(as_uuid=True), primary_key=True, default=uuid.uuid4 )
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(14), unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255))
    telefone: Mapped[str | None] = mapped_column(String(20))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    ativo: Mapped[bool] = mapped_column(Boolean,nullable=False,default=True,)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),)
    apartamentos: Mapped[list["PessoaApartamento"]] = relationship(back_populates="pessoa",cascade="all, delete-orphan",)
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="pessoa")

class Apartamento(Base):
    __tablename__ = "apartamentos"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,)
    bloco: Mapped[str | None] = mapped_column(String(50))
    numero: Mapped[str] = mapped_column(String(20), nullable=False)
    andar: Mapped[int | None] = mapped_column(Integer)
    observacao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean,nullable=False,default=True)
    pessoas: Mapped[list["PessoaApartamento"]] = relationship(back_populates="apartamento",cascade="all, delete-orphan")
    vagas: Mapped[list["Vaga"]] = relationship(back_populates="apartamento",cascade="all, delete-orphan")

class PessoaApartamento(Base):
    __tablename__ = "pessoas_apartamentos"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,)
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),ForeignKey("pessoas.id", ondelete="CASCADE"),nullable=False,)
    apartamento_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),ForeignKey("apartamentos.id", ondelete="CASCADE"),nullable=False,)
    tipo_relacao: Mapped[str] = mapped_column(String(30),nullable=False,)
    principal: Mapped[bool] = mapped_column(Boolean,nullable=False,default=False,)
    ativo: Mapped[bool] = mapped_column(Boolean,nullable=False,default=True,)
    pessoa: Mapped["Pessoa"] = relationship(back_populates="apartamentos",)
    apartamento: Mapped["Apartamento"] = relationship(back_populates="pessoas",)

class Vaga(Base):
    __tablename__ = "vagas"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,)
    apartamento_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),ForeignKey("apartamentos.id", ondelete="CASCADE"),nullable=False,)
    numero: Mapped[str] = mapped_column(String(20),nullable=False,unique=True,)
    localizacao: Mapped[str | None] = mapped_column(String(100))
    observacao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean,nullable=False,default=True,)
    apartamento: Mapped["Apartamento"] = relationship(back_populates="vagas",)
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="vaga",)

class Veiculo(Base):
    __tablename__ = "veiculos"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,)
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),ForeignKey("pessoas.id", ondelete="CASCADE"),nullable=False,)
    vaga_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),ForeignKey("vagas.id", ondelete="SET NULL"),)
    placa: Mapped[str | None] = mapped_column(String(10),unique=True,)
    marca: Mapped[str | None] = mapped_column(String(50))
    modelo: Mapped[str | None] = mapped_column(String(80))
    cor: Mapped[str | None] = mapped_column(String(30))
    descricao: Mapped[str | None] = mapped_column(String(255))
    ativo: Mapped[bool] = mapped_column(Boolean,nullable=False,default=True,)
    pessoa: Mapped["Pessoa"] = relationship(back_populates="veiculos",)
    vaga: Mapped["Vaga | None"] = relationship(back_populates="veiculos")

# DADOS RECEBIDOS

class VeiculoCreate(BaseModel):
    placa: str | None = Field(default=None, max_length=10)
    marca: str | None = Field(default=None, max_length=50)
    modelo: str | None = Field(default=None, max_length=80)
    cor: str | None = Field(default=None, max_length=30)
    descricao: str | None = Field(default=None, max_length=255)

class VagaCreate(BaseModel):
    numero: str = Field(max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None
    veiculos: list[VeiculoCreate] = Field(default_factory=list)

class ApartamentoCreate(BaseModel):
    bloco: str | None = Field(default=None, max_length=50)
    numero: str = Field(max_length=20)
    andar: int | None = None
    observacao: str | None = None
    tipo_relacao: str
    principal: bool = False
    vagas: list[VagaCreate] = Field(default_factory=list)

class PessoaCreate(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    cpf: str | None = Field(default=None, max_length=14)
    email: EmailStr | None = None
    telefone: str | None = Field(default=None, max_length=20)
    data_nascimento: date | None = None
    apartamentos: list[ApartamentoCreate] = Field(default_factory=list)

class NovaVaga(BaseModel):
    numero: str = Field(max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None

class NovoVeiculo(BaseModel):
    pessoa_id: uuid.UUID
    placa: str | None = Field(default=None, max_length=10)
    marca: str | None = Field(default=None, max_length=50)
    modelo: str | None = Field(default=None, max_length=80)
    cor: str | None = Field(default=None, max_length=30)
    descricao: str | None = Field(default=None, max_length=255)

# RESPOSTA

class PessoaResponse(BaseModel):
    id: uuid.UUID
    nome: str
    cpf: str | None
    email: EmailStr | None
    telefone: str | None
    data_nascimento: date | None
    ativo: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# CADASTRAR

@router.post("/", response_model=PessoaResponse, status_code=status.HTTP_201_CREATED)
def cadastrarPessoa(pessoa_data: PessoaCreate, database: Session = Depends(get_database)):
    if pessoa_data.cpf:
        existente = database.scalar(select(Pessoa).where(Pessoa.cpf == pessoa_data.cpf))
        if existente:
            raise HTTPException( status_code=status.HTTP_409_CONFLICT, detail="CPF já cadastrado")
    try:
        pessoa = Pessoa(
            nome=pessoa_data.nome.strip(),
            cpf=pessoa_data.cpf,
            email=(pessoa_data.email.lower()
                if pessoa_data.email
                else None
            ),
            telefone=pessoa_data.telefone,
            data_nascimento=pessoa_data.data_nascimento,
        )
        database.add(pessoa)
        database.flush()
        for apartamento_data in pessoa_data.apartamentos:
            apartamento = database.scalar(select(Apartamento).where(Apartamento.bloco == apartamento_data.bloco,Apartamento.numero == apartamento_data.numero))
            if not apartamento:
                apartamento = Apartamento(
                    bloco=apartamento_data.bloco,
                    numero=apartamento_data.numero,
                    andar=apartamento_data.andar,
                    observacao=apartamento_data.observacao,
                )
                database.add(apartamento)
                database.flush()
            vinculo = PessoaApartamento(
                pessoa_id=pessoa.id,
                apartamento_id=apartamento.id,
                tipo_relacao=apartamento_data.tipo_relacao,
                principal=apartamento_data.principal,
            )
            database.add(vinculo)
            for vaga_data in apartamento_data.vagas:
                vaga = database.scalar(select(Vaga).where(Vaga.numero == vaga_data.numero))
                if not vaga:
                    vaga = Vaga(
                        apartamento_id=apartamento.id,
                        numero=vaga_data.numero,
                        localizacao=vaga_data.localizacao,
                        observacao=vaga_data.observacao,
                    )
                    database.add(vaga)
                    database.flush()
                elif vaga.apartamento_id != apartamento.id:
                    raise HTTPException(
                        status_code=409,
                        detail=f"A vaga {vaga_data.numero} já pertence a outro apartamento",
                    )
                for veiculo_data in vaga_data.veiculos:
                    if veiculo_data.placa:
                        veiculo_existente = database.scalar(select(Veiculo).where(Veiculo.placa == veiculo_data.placa))
                        if veiculo_existente:
                            raise HTTPException(status_code=409,detail=f"Placa {veiculo_data.placa} já cadastrada",)
                    veiculo = Veiculo(
                        pessoa_id=pessoa.id,
                        vaga_id=vaga.id,
                        placa=veiculo_data.placa,
                        marca=veiculo_data.marca,
                        modelo=veiculo_data.modelo,
                        cor=veiculo_data.cor,
                        descricao=veiculo_data.descricao,
                    )
                    database.add(veiculo)
        database.commit()
        database.refresh(pessoa)
        return pessoa
    except HTTPException:
        database.rollback()
        raise
    except Exception:
        database.rollback()
        raise

# ADICIONAR VAGA

@router.post(
    "/apartamentos/{apartamento_id}/vagas",
    status_code=status.HTTP_201_CREATED
)
def adicionarVaga(
    apartamento_id: uuid.UUID,
    dados: NovaVaga,
    database: Session = Depends(get_database)
):
    apartamento = database.get(Apartamento, apartamento_id)

    if not apartamento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Apartamento não encontrado"
        )

    vaga_existente = database.scalar(
        select(Vaga).where(Vaga.numero == dados.numero)
    )

    if vaga_existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vaga {dados.numero} já cadastrada"
        )

    vaga = Vaga(
        apartamento_id=apartamento.id,
        numero=dados.numero,
        localizacao=dados.localizacao,
        observacao=dados.observacao,
    )

    database.add(vaga)
    database.commit()
    database.refresh(vaga)

    return vaga


# ADICIONAR VEÍCULO

@router.post(
    "/vagas/{vaga_id}/veiculos",
    status_code=status.HTTP_201_CREATED
)
def adicionarVeiculo(
    vaga_id: uuid.UUID,
    dados: NovoVeiculo,
    database: Session = Depends(get_database)
):
    vaga = database.get(Vaga, vaga_id)

    if not vaga:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vaga não encontrada"
        )

    pessoa = database.get(Pessoa, dados.pessoa_id)

    if not pessoa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pessoa não encontrada"
        )

    vinculo = database.scalar(
        select(PessoaApartamento).where(
            PessoaApartamento.pessoa_id == pessoa.id,
            PessoaApartamento.apartamento_id == vaga.apartamento_id,
        )
    )

    if not vinculo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pessoa não possui vínculo com o apartamento desta vaga"
        )

    if dados.placa:
        veiculo_existente = database.scalar(
            select(Veiculo).where(Veiculo.placa == dados.placa)
        )

        if veiculo_existente:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Placa {dados.placa} já cadastrada"
            )

    veiculo = Veiculo(
        pessoa_id=pessoa.id,
        vaga_id=vaga.id,
        placa=dados.placa,
        marca=dados.marca,
        modelo=dados.modelo,
        cor=dados.cor,
        descricao=dados.descricao,
    )

    database.add(veiculo)
    database.commit()
    database.refresh(veiculo)

    return veiculo