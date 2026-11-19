import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal

from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, FetchedValue, ForeignKey, Index, Numeric, SmallInteger, String, Text, TypeDecorator, UniqueConstraint, Uuid, event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from App.database import Base


# =========================================================
# TIPOS PARA O MYSQL
# =========================================================

class DataHora(TypeDecorator):
    # data e hora sempre em UTC: o MySQL guarda sem fuso (DATETIME com
    # microssegundos); ao gravar converte para UTC, ao ler devolve com UTC
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None) if dialect.name == "mysql" else value
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


AGORA = text("CURRENT_TIMESTAMP(6)")  # padrão das colunas de data/hora


@event.listens_for(Base.metadata, "before_create")
def _tabelas_utf8mb4(metadata, connection, **_):
    # MySQL: todas as tabelas em InnoDB com utf8mb4 (acentos e emojis do WhatsApp)
    for tabela in metadata.tables.values():
        tabela.dialect_kwargs.setdefault("mysql_engine", "InnoDB")
        tabela.dialect_kwargs.setdefault("mysql_charset", "utf8mb4")


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
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

def coluna_condominio():
    return mapped_column(Uuid, ForeignKey("condominios.id", ondelete="RESTRICT"), nullable=False, index=True)

def coluna_ativo():
    return mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

def coluna_created_at():
    return mapped_column(DataHora, nullable=False, server_default=AGORA)

def coluna_updated_at():
    # atualizado pelo trigger do banco; FetchedValue avisa o SQLAlchemy para reler o valor
    return mapped_column(DataHora, nullable=False, server_default=AGORA, server_onupdate=FetchedValue())


# =========================================================
# LOGIN
# =========================================================

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = coluna_id()
    email: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)  # 191: limite de índice do MySQL 5.6 com utf8mb4
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ativo.value, server_default="ativo")
    admin_sistema: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    trocar_senha: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))  # senha temporária: troca obrigatória no próximo login
    responsavel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))  # recebe e responde as mensagens do WhatsApp (designado pelo ADM)
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
    # manutenções: avisar quantos dias antes do vencimento (sql/manutencoes.sql)
    alerta_manutencao_dias: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30, server_default="30")
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    perfil: Mapped[str] = mapped_column(String(20), nullable=False, default="MORADOR", server_default="MORADOR")
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(11))
    email: Mapped[str | None] = mapped_column(String(255))
    telefone: Mapped[str | None] = mapped_column(String(11))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    responsavel_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))  # RESPONSÁVEL do WhatsApp deste morador
    foto_arquivo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("arquivos.id", ondelete="SET NULL"))  # foto (no Google Drive)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    usuario: Mapped["User | None"] = relationship(foreign_keys=[user_id])
    responsavel: Mapped["User | None"] = relationship(foreign_keys=[responsavel_user_id])
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
    # fração ideal (sql/fracao_ideal.sql)
    fracao_ideal: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))       # % da unidade no rateio
    fracao_garagem: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    fracao_extra: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    nome_cobranca: Mapped[str | None] = mapped_column(String(200))            # nome no relatório da administradora

    pessoas: Mapped[list["PessoaApartamento"]] = relationship(back_populates="apartamento", cascade="all, delete-orphan", passive_deletes=True)
    vagas: Mapped[list["Vaga"]] = relationship(back_populates="apartamento", passive_deletes=True)  # ao excluir o apto, a vaga fica livre
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="apartamento", cascade="all, delete-orphan", passive_deletes=True)


class PessoaApartamento(Base):
    __tablename__ = "pessoas_apartamentos"
    __table_args__ = (UniqueConstraint("pessoa_id", "apartamento_id"),)
    id: Mapped[uuid.UUID] = coluna_id()
    pessoa_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False)
    apartamento_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("apartamentos.id", ondelete="CASCADE"), nullable=False)
    tipo_relacao: Mapped[str] = mapped_column(String(20), nullable=False)
    reside: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))  # usado para o proprietário
    titular_vinculo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("pessoas_apartamentos.id", ondelete="CASCADE"))
    parentesco: Mapped[str | None] = mapped_column(String(30))
    principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
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
    apartamento_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("apartamentos.id", ondelete="SET NULL"))
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
    apartamento_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("apartamentos.id", ondelete="CASCADE"), nullable=False, index=True)
    pessoa_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("pessoas.id", ondelete="SET NULL"), index=True)  # condutor (opcional)
    vaga_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vagas.id", ondelete="SET NULL"))
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
        Index("ix_cotas_apartamento_mes", "apartamento_id", "competencia"),  # 1 ORDINARIA por mês: checado em Router/Financeiro.py
    )
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    apartamento_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("apartamentos.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)  # guardado para o histórico
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    conteudo: Mapped[str] = mapped_column(Text, nullable=False)
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, default="NORMAL", server_default="NORMAL")
    fixado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    expira_em: Mapped[date | None] = mapped_column(Date)  # depois dessa data some do quadro (continua no histórico)
    ativo: Mapped[bool] = coluna_ativo()
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    leituras: Mapped[list["AvisoLeitura"]] = relationship(back_populates="aviso", cascade="all, delete-orphan", passive_deletes=True)


class AvisoLeitura(Base):
    # "li e estou ciente"
    __tablename__ = "avisos_leituras"
    aviso_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("avisos.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    lido_em: Mapped[datetime] = coluna_created_at()

    aviso: Mapped["Aviso"] = relationship(back_populates="leituras")


class Chamado(Base):
    __tablename__ = "chamados"
    __table_args__ = (UniqueConstraint("condominio_id", "numero"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    numero: Mapped[int] = mapped_column(nullable=False)  # protocolo sequencial por condomínio
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    autor_pessoa_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("pessoas.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    assunto: Mapped[str] = mapped_column(String(150), nullable=False)
    categoria: Mapped[str] = mapped_column(String(15), nullable=False, default="OUTRO", server_default="OUTRO")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ABERTO", server_default="ABERTO")
    lido_pela_gestao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    lido_pelo_autor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    encerrado_em: Mapped[datetime | None] = mapped_column(DataHora)
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()

    autor_pessoa: Mapped["Pessoa | None"] = relationship()
    mensagens: Mapped[list["ChamadoMensagem"]] = relationship(
        back_populates="chamado", cascade="all, delete-orphan", passive_deletes=True, order_by="ChamadoMensagem.created_at",
    )


class ChamadoMensagem(Base):
    __tablename__ = "chamados_mensagens"
    id: Mapped[uuid.UUID] = coluna_id()
    chamado_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chamados.id", ondelete="CASCADE"), nullable=False, index=True)
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    da_gestao: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))  # resposta do síndico/ADM
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
    pessoa_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pessoas.id", ondelete="CASCADE"), unique=True, nullable=False)
    cargo_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cargos.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    responsavel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pessoas.id", ondelete="RESTRICT"), nullable=False, index=True)
    criado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    criado_por_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, default="MEDIA", server_default="MEDIA")
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="PENDENTE", server_default="PENDENTE")
    prazo: Mapped[date | None] = mapped_column(Date)
    concluida_em: Mapped[datetime | None] = mapped_column(DataHora)
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
    tarefa_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tarefas.id", ondelete="CASCADE"), nullable=False, index=True)
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # COMENTARIO ou EVENTO
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = coluna_created_at()

    tarefa: Mapped["Tarefa"] = relationship(back_populates="historico")


# =========================================================
# WHATSAPP (teste com a Evolution API: um número para o sistema todo)
# =========================================================
# Tabelas criadas automaticamente na inicialização (app.py).

class WhatsappConversa(Base):
    # uma conversa por contato do WhatsApp
    __tablename__ = "whatsapp_conversas"
    id: Mapped[uuid.UUID] = coluna_id()
    jid: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # identificador do WhatsApp (ex.: 5511999999999@s.whatsapp.net)
    telefone: Mapped[str | None] = mapped_column(String(20))                   # só números, com 55
    nome: Mapped[str | None] = mapped_column(String(150))                      # nome do perfil no WhatsApp
    nao_lidas: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    ultima_mensagem: Mapped[str | None] = mapped_column(String(300))
    ultima_mensagem_em: Mapped[datetime] = mapped_column(DataHora, nullable=False, server_default=AGORA, index=True)
    modo: Mapped[str] = mapped_column(String(10), nullable=False, default="ROBO", server_default="ROBO")  # ROBO ou ATENDENTE
    atendente_desde: Mapped[datetime | None] = mapped_column(DataHora)  # quando passou para uma pessoa
    bot_dados: Mapped[str | None] = mapped_column(Text)  # estado do robô (JSON): etapa, condomínio escolhido...
    created_at: Mapped[datetime] = coluna_created_at()


class WhatsappMensagem(Base):
    __tablename__ = "whatsapp_mensagens"
    id: Mapped[uuid.UUID] = coluna_id()
    conversa_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("whatsapp_conversas.id", ondelete="CASCADE"), nullable=False, index=True)
    wa_id: Mapped[str | None] = mapped_column(String(100), unique=True)  # id da mensagem no WhatsApp (evita duplicar)
    recebida: Mapped[bool] = mapped_column(Boolean, nullable=False)       # True = do contato; False = enviada por nós
    para_atendente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))  # recebida no modo ATENDENTE (gera pop-up)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    autor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    autor_nome: Mapped[str | None] = mapped_column(String(150))           # quem respondeu pelo sistema
    created_at: Mapped[datetime] = mapped_column(DataHora, nullable=False, server_default=AGORA, index=True)


# =========================================================
# ARQUIVOS (Google Drive)
# =========================================================
# Tabelas criadas automaticamente na inicialização (app.py).

class DriveConexao(Base):
    # conta Google conectada pelo ADM (uma só para o sistema: id = 1)
    __tablename__ = "drive_conexao"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    email: Mapped[str | None] = mapped_column(String(255))
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)
    expira_em: Mapped[datetime | None] = mapped_column(DataHora)
    pasta_raiz_id: Mapped[str | None] = mapped_column(String(100))  # pasta "Gerenciador" no Drive
    conectado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = coluna_created_at()


class Arquivo(Base):
    # arquivo guardado no Drive e usado pelo sistema (ex.: foto de uma pessoa)
    __tablename__ = "arquivos"
    id: Mapped[uuid.UUID] = coluna_id()
    drive_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    tamanho: Mapped[int | None] = mapped_column()
    categoria: Mapped[str] = mapped_column(String(30), nullable=False)          # ex.: FOTO_PESSOA, ADMIN
    condominio_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("condominios.id", ondelete="SET NULL"), index=True)
    enviado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = coluna_created_at()


# =========================================================
# MOVIMENTAÇÕES BANCÁRIAS (extrato mensal do banco)
# =========================================================
# Tabelas criadas manualmente: sql/movimentacoes_bancarias.sql

TipoMovimentacao = Literal["ENTRADA", "SAIDA"]  # valor negativo = SAIDA; positivo = ENTRADA


class ExtratoImportado(Base):
    # um arquivo de extrato enviado (normalmente um mês)
    __tablename__ = "extratos_importados"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    titular: Mapped[str | None] = mapped_column(String(200))
    agencia: Mapped[str | None] = mapped_column(String(20))
    conta: Mapped[str | None] = mapped_column(String(30))
    periodo_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_fim: Mapped[date] = mapped_column(Date, nullable=False)
    saldo_anterior: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    saldo_final: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_entradas: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0")
    total_saidas: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0")  # negativo
    quantidade: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    enviado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = coluna_created_at()

    movimentacoes: Mapped[list["MovimentacaoBancaria"]] = relationship(back_populates="extrato", cascade="all, delete-orphan", passive_deletes=True)


class MovimentacaoBancaria(Base):
    # um lançamento do extrato
    __tablename__ = "movimentacoes_bancarias"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = coluna_condominio()
    extrato_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("extratos_importados.id", ondelete="CASCADE"), nullable=False, index=True)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    lancamento: Mapped[str] = mapped_column(String(255), nullable=False)
    razao_social: Mapped[str | None] = mapped_column(String(255))
    cpf_cnpj: Mapped[str | None] = mapped_column(String(14))  # só números
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)  # como veio no extrato
    tipo: Mapped[str] = mapped_column(String(7), nullable=False)  # ENTRADA ou SAIDA
    ordem: Mapped[int] = mapped_column(nullable=False)  # posição da linha no extrato
    created_at: Mapped[datetime] = coluna_created_at()

    extrato: Mapped["ExtratoImportado"] = relationship(back_populates="movimentacoes")


class SaldoInformado(Base):
    # saldo lido no banco numa data, digitado pela gestão (sql/saldos_informados.sql)
    #   CONTA: saldo da conta corrente  -> + lançamentos do extrato depois da data
    #   (CDB: antigo; agora em investimentos_lancamentos)
    __tablename__ = "saldos_informados"
    __table_args__ = (UniqueConstraint("condominio_id", "tipo", "agencia", "conta", "data", name="uq_saldos_informados"),)
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(5), nullable=False)  # CONTA ou CDB
    agencia: Mapped[str] = mapped_column(String(20), nullable=False)
    conta: Mapped[str] = mapped_column(String(30), nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(100))
    data: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    informado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = coluna_created_at()


class InvestimentoLancamento(Base):
    # lançamento de investimento (CDB do fundo de reserva) digitado à mão (sql/investimentos.sql)
    #   SALDO (posição líquida) | APLICACAO | RESGATE | RENDIMENTO
    # investimento = agência + conta + nome
    __tablename__ = "investimentos_lancamentos"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    agencia: Mapped[str] = mapped_column(String(20), nullable=False)
    conta: Mapped[str] = mapped_column(String(30), nullable=False)
    nome: Mapped[str] = mapped_column(String(60), nullable=False, default="CDB")
    data: Mapped[date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    valor_bruto: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    imposto: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    observacao: Mapped[str | None] = mapped_column(String(200))
    informado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = coluna_created_at()


class LancamentoFuturo(Base):
    # pagamento/recebimento combinado que ainda não está no extrato (sql/lancamentos_futuros.sql)
    # parcelas do mesmo acordo: mesmo grupo_id; entra na previsão se a data for depois do último extrato
    __tablename__ = "lancamentos_futuros"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    grupo_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    favorecido: Mapped[str | None] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(7), nullable=False)  # ENTRADA ou SAIDA
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)  # positivo
    data: Mapped[date] = mapped_column(Date, nullable=False)
    parcela: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    total_parcelas: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    criado_por_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = coluna_created_at()


# =========================================================
# MANUTENÇÕES E PRESTADORES (sql/manutencoes.sql)
# =========================================================

class Manutencao(Base):
    # manutenção/renovação periódica; próximo vencimento = última execução + intervalo (calculado)
    __tablename__ = "manutencoes"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    ordem: Mapped[int] = mapped_column(nullable=False, default=0)
    categoria: Mapped[str] = mapped_column(String(80), nullable=False)
    item: Mapped[str] = mapped_column(String(200), nullable=False)
    # empresa/pessoa responsável: cadastro de prestadores (sql/manutencoes_prestador.sql)
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("prestadores.id", ondelete="SET NULL"))
    periodicidade: Mapped[str | None] = mapped_column(String(60))
    intervalo_meses: Mapped[int | None] = mapped_column(SmallInteger)
    base_legal: Mapped[str | None] = mapped_column(String(200))
    ultima_execucao: Mapped[date | None] = mapped_column(Date)
    observacoes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()


class Prestador(Base):
    # empresas, prestadores, fornecedores e pessoas que trabalham para o condomínio
    __tablename__ = "prestadores"
    id: Mapped[uuid.UUID] = coluna_id()
    condominio_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    ordem: Mapped[int] = mapped_column(nullable=False, default=0)
    empresa: Mapped[str] = mapped_column(String(150), nullable=False)
    setor: Mapped[str | None] = mapped_column(String(150))
    pessoa: Mapped[str | None] = mapped_column(String(150))
    cnpj: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(30))
    custo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # custo mensal
    observacoes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = coluna_created_at()
    updated_at: Mapped[datetime] = coluna_updated_at()
