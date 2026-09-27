import uuid
from datetime import date, datetime
from enum import Enum
from typing import Literal

from sqlalchemy import Boolean, Date, DateTime, FetchedValue, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from App.database import Base


# =========================================================
# VALORES PERMITIDOS (iguais aos CHECK do banco)
# =========================================================

class UserStatus(str, Enum):
    ativo = "ativo"
    inativo = "inativo"
    bloqueado = "bloqueado"

PerfilPessoa = Literal["MORADOR", "SINDICO", "CONSELHEIRO", "COLABORADOR", "PRESTADOR"]
TipoVaga = Literal["FIXA", "ROTATIVA"]
TipoRelacao = Literal["PROPRIETARIO", "INQUILINO", "RESIDENTE"]
Parentesco = Literal[
    "CONJUGE", "FILHO", "ENTEADO", "PAI_MAE", "SOGRO", "IRMAO",
    "AVO", "NETO", "OUTRO_PARENTE", "EMPREGADO_DOMESTICO", "OUTRO",
]
PrioridadeTarefa = Literal["baixa", "media", "alta", "urgente"]
StatusTarefa = Literal["pendente", "em_andamento", "concluida", "cancelada"]


# =========================================================
# COLUNAS PADRÃO
# =========================================================

def coluna_id():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

def coluna_condominio():
    return mapped_column(UUID(as_uuid=True), ForeignKey("condominios.id", ondelete="RESTRICT"), nullable=False, index=True)

def coluna_ativo():
    return mapped_column(Boolean, nullable=False, default=True, server_default="true")

def coluna_created_at():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

def coluna_updated_at():
    # atualizado pelo trigger do banco; FetchedValue avisa o SQLAlchemy para reler o valor
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), server_onupdate=FetchedValue())


# =========================================================
# LOGIN
# =========================================================

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = coluna_id()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ativo.value, server_default="ativo")
    admin_sistema: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()


# =========================================================
# CONDOMÍNIO
# =========================================================

class Condominio(Base):
    __tablename__ = "condominios"
    id: Mapped[uuid.UUID] = coluna_id()
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(14), unique=True)
    cep: Mapped[str | None] = mapped_column(String(8))
    logradouro: Mapped[str | None] = mapped_column(String(200))
    numero: Mapped[str | None] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str | None] = mapped_column(String(100))
    cidade: Mapped[str | None] = mapped_column(String(100))
    uf: Mapped[str | None] = mapped_column(String(2))
    telefone: Mapped[str | None] = mapped_column(String(11))
    email: Mapped[str | None] = mapped_column(String(255))
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()


# =========================================================
# PESSOAS
# =========================================================

class Pessoa(Base):
    __tablename__ = "pessoas"
    __table_args__ = (
        UniqueConstraint("condominio_id", "cpf"),
        UniqueConstraint("condominio_id", "user_id"),
    )
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    perfil: Mapped[str] = mapped_column(String(20), nullable=False, default="MORADOR", server_default="MORADOR")
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(11))
    email: Mapped[str | None] = mapped_column(String(255))
    telefone: Mapped[str | None] = mapped_column(String(11))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    usuario: Mapped["User | None"] = relationship()
    apartamentos: Mapped[list["PessoaApartamento"]] = relationship(back_populates="pessoa", cascade="all, delete-orphan", passive_deletes=True)
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="pessoa", passive_deletes=True)  # pessoa = condutor; ao excluir, o veículo fica sem condutor
    colaborador: Mapped["Colaborador | None"] = relationship(back_populates="pessoa", uselist=False, cascade="all, delete-orphan", passive_deletes=True)


# =========================================================
# APARTAMENTOS E VÍNCULOS
# =========================================================

class Apartamento(Base):
    __tablename__ = "apartamentos"
    __table_args__ = (UniqueConstraint("condominio_id", "bloco", "numero"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    bloco: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    numero: Mapped[str] = mapped_column(String(10), nullable=False)
    andar: Mapped[int | None] = mapped_column(SmallInteger)
    observacao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    pessoas: Mapped[list["PessoaApartamento"]] = relationship(back_populates="apartamento", cascade="all, delete-orphan", passive_deletes=True)
    vagas: Mapped[list["Vaga"]] = relationship(back_populates="apartamento", passive_deletes=True)  # ao excluir o apto, a vaga fica livre
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="apartamento", cascade="all, delete-orphan", passive_deletes=True)


class PessoaApartamento(Base):
    __tablename__ = "pessoas_apartamentos"
    __table_args__ = (UniqueConstraint("pessoa_id", "apartamento_id"),)
    id: Mapped[uuid.UUID] = coluna_id()
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False)
    apartamento_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("apartamentos.id", ondelete="CASCADE"), nullable=False)
    tipo_relacao: Mapped[str] = mapped_column(String(20), nullable=False)
    reside: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")  # usado para o proprietário
    titular_vinculo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas_apartamentos.id", ondelete="CASCADE"))
    parentesco: Mapped[str | None] = mapped_column(String(30))
    principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()

    pessoa: Mapped["Pessoa"] = relationship(back_populates="apartamentos")
    apartamento: Mapped["Apartamento"] = relationship(back_populates="pessoas")
    # RESIDENTE -> vínculo do titular (proprietário ou inquilino) ao qual está ligado
    titular: Mapped["PessoaApartamento | None"] = relationship(remote_side="PessoaApartamento.id", back_populates="residentes")
    residentes: Mapped[list["PessoaApartamento"]] = relationship(back_populates="titular", cascade="all, delete-orphan", passive_deletes=True)


# =========================================================
# VAGAS E VEÍCULOS
# =========================================================

class Vaga(Base):
    __tablename__ = "vagas"
    __table_args__ = (UniqueConstraint("condominio_id", "numero"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    # FIXA: pode ser de um apartamento (ou estar livre); ROTATIVA: uso comum, nunca de um apartamento
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="FIXA", server_default="FIXA")
    apartamento_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("apartamentos.id", ondelete="SET NULL"))
    numero: Mapped[str] = mapped_column(String(20), nullable=False)
    localizacao: Mapped[str | None] = mapped_column(String(100))
    observacao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    apartamento: Mapped["Apartamento | None"] = relationship(back_populates="vagas")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="vaga", passive_deletes=True)


class Veiculo(Base):
    __tablename__ = "veiculos"
    __table_args__ = (UniqueConstraint("condominio_id", "placa"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    apartamento_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("apartamentos.id", ondelete="CASCADE"), nullable=False, index=True)
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"), index=True)  # condutor (opcional)
    vaga_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vagas.id", ondelete="SET NULL"))
    placa: Mapped[str | None] = mapped_column(String(7))
    marca: Mapped[str | None] = mapped_column(String(50))
    modelo: Mapped[str | None] = mapped_column(String(80))
    cor: Mapped[str | None] = mapped_column(String(30))
    descricao: Mapped[str | None] = mapped_column(String(255))
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    apartamento: Mapped["Apartamento"] = relationship(back_populates="veiculos")
    pessoa: Mapped["Pessoa | None"] = relationship(back_populates="veiculos")
    vaga: Mapped["Vaga | None"] = relationship(back_populates="veiculos")


# =========================================================
# SETORES E COLABORADORES
# =========================================================

class Setor(Base):
    __tablename__ = "setores"
    __table_args__ = (UniqueConstraint("condominio_id", "nome"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = coluna_created_at()

    colaboradores: Mapped[list["Colaborador"]] = relationship(back_populates="setor")


class Colaborador(Base):
    __tablename__ = "colaboradores"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="CASCADE"), unique=True, nullable=False)
    setor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("setores.id", ondelete="RESTRICT"), nullable=False)
    cargo: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    pessoa: Mapped["Pessoa"] = relationship(back_populates="colaborador")
    setor: Mapped["Setor"] = relationship(back_populates="colaboradores")


# =========================================================
# PROJETOS (obras/melhorias) E TAREFAS
# =========================================================

class Projeto(Base):
    __tablename__ = "projetos"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    nome: Mapped[str] = mapped_column(String(180), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = coluna_ativo()
    data_arquivamento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    tarefas: Mapped[list["Tarefa"]] = relationship(back_populates="projeto")


class Tarefa(Base):
    __tablename__ = "tarefas"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    projeto_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projetos.id", ondelete="RESTRICT"), nullable=False, index=True)
    responsavel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="RESTRICT"), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(240), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, default="media", server_default="media")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente", server_default="pendente")
    prazo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_conclusao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ativo: Mapped[bool] = coluna_ativo()
    data_arquivamento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    projeto: Mapped["Projeto"] = relationship(back_populates="tarefas")
    responsavel: Mapped["Pessoa"] = relationship()