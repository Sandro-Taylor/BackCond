import uuid
from datetime import date, datetime
from enum import Enum
from typing import Literal

from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, FetchedValue, ForeignKey, Index, Numeric, SmallInteger, String, Text, UniqueConstraint, text
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

PerfilPessoa = Literal["MORADOR", "SINDICO", "CONSELHEIRO", "FUNCIONARIO", "PRESTADOR"]
VinculoFuncionario = Literal["PROPRIO", "TERCEIRIZADO", "AUTONOMO"]
TipoVaga = Literal["FIXA", "ROTATIVA"]
TipoRelacao = Literal["PROPRIETARIO", "INQUILINO", "RESIDENTE"]
Parentesco = Literal[
    "CONJUGE", "FILHO", "ENTEADO", "PAI_MAE", "SOGRO", "IRMAO",
    "AVO", "NETO", "OUTRO_PARENTE", "EMPREGADO_DOMESTICO", "OUTRO",
]
PrioridadeTarefa = Literal["BAIXA", "MEDIA", "ALTA", "URGENTE"]
StatusTarefa = Literal["PENDENTE", "EM_ANDAMENTO", "CONCLUIDA", "CANCELADA"]
TipoCota = Literal["ORDINARIA", "EXTRA"]
StatusCota = Literal["ABERTA", "PAGA", "CANCELADA"]  # "ATRASADA" não é gravado: é ABERTA com vencimento passado
FormaPagamento = Literal["PIX", "BOLETO", "DINHEIRO", "TRANSFERENCIA", "CARTAO", "OUTRO"]
PrioridadeAviso = Literal["NORMAL", "IMPORTANTE", "URGENTE"]
CategoriaChamado = Literal["DUVIDA", "SOLICITACAO", "RECLAMACAO", "SUGESTAO", "MANUTENCAO", "OUTRO"]
StatusChamado = Literal["ABERTO", "RESPONDIDO", "ENCERRADO"]


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
    trocar_senha: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")  # senha temporária: troca obrigatória no próximo login
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
    # financeiro: padrão usado ao gerar as cotas do mês
    valor_cota: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dia_vencimento: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10, server_default="10")
    multa_percentual: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("2"), server_default="2")
    juros_mensal: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1"), server_default="1")
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
    funcionario: Mapped["Funcionario | None"] = relationship(back_populates="pessoa", uselist=False, cascade="all, delete-orphan", passive_deletes=True)  # ficha (perfil FUNCIONARIO)


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
# FINANCEIRO (cotas condominiais)
# =========================================================

class Cota(Base):
    __tablename__ = "cotas"
    __table_args__ = (
        # uma cota ordinária por apartamento em cada mês (extras podem ser várias)
        Index("uq_cotas_ordinaria_mes", "apartamento_id", "competencia", unique=True, postgresql_where=text("tipo = 'ORDINARIA'")),
    )
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    apartamento_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("apartamentos.id", ondelete="RESTRICT"), nullable=False, index=True)
    competencia: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # sempre o dia 1 do mês
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="ORDINARIA", server_default="ORDINARIA")
    descricao: Mapped[str | None] = mapped_column(String(150))
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    vencimento: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ABERTA", server_default="ABERTA")
    data_pagamento: Mapped[date | None] = mapped_column(Date)
    valor_pago: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    forma_pagamento: Mapped[str | None] = mapped_column(String(20))
    observacao: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    apartamento: Mapped["Apartamento"] = relationship()


# =========================================================
# COMUNICAÇÃO: QUADRO DE AVISOS E ATENDIMENTO (fale com o síndico)
# =========================================================

class Aviso(Base):
    __tablename__ = "avisos"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)  # guardado para o histórico
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    conteudo: Mapped[str] = mapped_column(Text, nullable=False)
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, default="NORMAL", server_default="NORMAL")
    fixado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    expira_em: Mapped[date | None] = mapped_column(Date)  # depois dessa data some do quadro (continua no histórico)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    leituras: Mapped[list["AvisoLeitura"]] = relationship(back_populates="aviso", cascade="all, delete-orphan", passive_deletes=True)


class AvisoLeitura(Base):
    # "li e estou ciente"
    __tablename__ = "avisos_leituras"
    aviso_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avisos.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    lido_em: Mapped[datetime] = coluna_created_at()

    aviso: Mapped["Aviso"] = relationship(back_populates="leituras")


class Chamado(Base):
    __tablename__ = "chamados"
    __table_args__ = (UniqueConstraint("condominio_id", "numero"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    numero: Mapped[int] = mapped_column(nullable=False)  # protocolo sequencial por condomínio
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    autor_pessoa_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    assunto: Mapped[str] = mapped_column(String(150), nullable=False)
    categoria: Mapped[str] = mapped_column(String(15), nullable=False, default="OUTRO", server_default="OUTRO")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ABERTO", server_default="ABERTO")
    lido_pela_gestao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    lido_pelo_autor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    encerrado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    autor_pessoa: Mapped["Pessoa | None"] = relationship()
    mensagens: Mapped[list["ChamadoMensagem"]] = relationship(
        back_populates="chamado", cascade="all, delete-orphan", passive_deletes=True, order_by="ChamadoMensagem.created_at",
    )


class ChamadoMensagem(Base):
    __tablename__ = "chamados_mensagens"
    id: Mapped[uuid.UUID] = coluna_id()
    chamado_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chamados.id", ondelete="CASCADE"), nullable=False, index=True)
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    da_gestao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")  # resposta do síndico/ADM
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = coluna_created_at()

    chamado: Mapped["Chamado"] = relationship(back_populates="mensagens")


# =========================================================
# FUNCIONÁRIOS (ficha complementar da pessoa com perfil FUNCIONARIO)
# =========================================================

class Cargo(Base):
    # porteiro, zelador, faxineiro... (lista própria de cada condomínio)
    __tablename__ = "cargos"
    __table_args__ = (UniqueConstraint("condominio_id", "nome"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    nome: Mapped[str] = mapped_column(String(80), nullable=False)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()


class Funcionario(Base):
    __tablename__ = "funcionarios"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="CASCADE"), unique=True, nullable=False)
    cargo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cargos.id", ondelete="RESTRICT"), nullable=False, index=True)
    vinculo: Mapped[str] = mapped_column(String(15), nullable=False, default="PROPRIO", server_default="PROPRIO")
    empresa: Mapped[str | None] = mapped_column(String(150))  # terceirizada
    turno: Mapped[str | None] = mapped_column(String(100))    # ex.: "12x36 noturno"
    data_admissao: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    pessoa: Mapped["Pessoa"] = relationship(back_populates="funcionario")
    cargo: Mapped["Cargo"] = relationship()

    @property
    def cargo_nome(self) -> str:
        return self.cargo.nome


# =========================================================
# TAREFAS (designadas pela gestão)
# =========================================================

class Tarefa(Base):
    __tablename__ = "tarefas"
    __table_args__ = (UniqueConstraint("condominio_id", "numero"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    numero: Mapped[int] = mapped_column(nullable=False)  # sequencial por condomínio
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    local: Mapped[str | None] = mapped_column(String(100))
    responsavel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pessoas.id", ondelete="RESTRICT"), nullable=False, index=True)
    criado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    criado_por_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, default="MEDIA", server_default="MEDIA")
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="PENDENTE", server_default="PENDENTE")
    prazo: Mapped[date | None] = mapped_column(Date)
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    responsavel: Mapped["Pessoa"] = relationship()
    historico: Mapped[list["TarefaHistorico"]] = relationship(
        back_populates="tarefa", cascade="all, delete-orphan", passive_deletes=True, order_by="TarefaHistorico.created_at",
    )


class TarefaHistorico(Base):
    # comentários e mudanças (criação, status, responsável, prazo)
    __tablename__ = "tarefas_historico"
    id: Mapped[uuid.UUID] = coluna_id()
    tarefa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tarefas.id", ondelete="CASCADE"), nullable=False, index=True)
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # COMENTARIO ou EVENTO
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = coluna_created_at()

    tarefa: Mapped["Tarefa"] = relationship(back_populates="historico")
