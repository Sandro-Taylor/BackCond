# (PESSOAS)
import secrets
import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func

from App.database import Base, get_database
from App.dependencies import get_current_user
from App.security import hash_password
from Router.Usuarios.CriarUsers import User

router = APIRouter(prefix="/colaboradores")

TipoColaborador = Literal[1, 2, 3, 4, 5]  # 1=Visualizador 2=Editor 3=Analista 4=Supervisor 5=Administrador

class Colaborador(Base):
    __tablename__ = "colaboradores"
    idColaborador: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idUser: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    idSetor: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    cpf: Mapped[str] = mapped_column(String(11), nullable=False)
    dataNascimento: Mapped[date] = mapped_column(Date, nullable=False)
    cargo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dataCriacao: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dataAtualizacao: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    telefone: Mapped[str | None] = mapped_column(String(9), nullable=True)
    ddd: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tipo: Mapped[str] = mapped_column(String(2), nullable=False)

class PessoaCriar(BaseModel):
    idSetor: uuid.UUID
    nome: str
    cpf: str
    dataNascimento: date
    cargo: str | None = None
    email: EmailStr
    telefone: str | None = None
    ddd: str | None = None
    tipo: TipoColaborador
    ativo: bool = True

class PessoaEditar(BaseModel):
    idSetor: uuid.UUID | None = None
    nome: str | None = None
    cpf: str | None = None
    dataNascimento: date | None = None
    cargo: str | None = None
    email: str | None = None
    telefone: str | None = None
    ddd: str | None = None
    tipo: TipoColaborador | None = None

class PessoaResposta(BaseModel):
    idColaborador: uuid.UUID
    idUser: uuid.UUID
    idSetor: uuid.UUID
    nome: str
    cpf: str
    dataNascimento: date
    cargo: str | None
    ativo: bool
    dataCriacao: datetime
    dataAtualizacao: datetime
    email: str | None
    telefone: str | None
    ddd: str | None
    tipo: str
    model_config = ConfigDict(from_attributes=True)

class PessoaCriadaResposta(PessoaResposta):
    senhaTemporaria: str

def buscar_pessoa_ou_404(pessoa_id: uuid.UUID, database: Session) -> Colaborador:
    pessoa = database.get(Colaborador, pessoa_id)
    if not pessoa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador não encontrado")
    return pessoa

def gerar_senha_temporaria() -> str:
    return secrets.token_urlsafe(9)

# ROTAS
@router.post("/", response_model=PessoaCriadaResposta, status_code=status.HTTP_201_CREATED)
async def criarPessoas(
    dados: PessoaCriar,
    database: Session = Depends(get_database),
):
    cpf_cadastrado = database.scalar(
        select(Colaborador.idColaborador).where(
            Colaborador.cpf == dados.cpf
        )
    )

    if cpf_cadastrado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CPF já cadastrado",
        )

    email_normalizado = dados.email.lower()

    email_cadastrado = database.scalar(
        select(User.id).where(User.email == email_normalizado)
    )

    if email_cadastrado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail já cadastrado",
        )

    senha_temporaria = gerar_senha_temporaria()

    novo_user = User(
        email=email_normalizado,
        password_hash=hash_password(senha_temporaria),
        full_name=dados.nome,
    )
    database.add(novo_user)
    database.flush()  # gera novo_user.id sem commitar a transação ainda

    nova_pessoa = Colaborador(
        idUser=novo_user.id,
        idSetor=dados.idSetor,
        nome=dados.nome,
        cpf=dados.cpf,
        dataNascimento=dados.dataNascimento,
        cargo=dados.cargo,
        email=email_normalizado,
        telefone=dados.telefone,
        ddd=dados.ddd,
        tipo=str(dados.tipo),
        ativo=dados.ativo,
    )
    database.add(nova_pessoa)
    database.commit()
    database.refresh(nova_pessoa)

    resposta = PessoaResposta.model_validate(nova_pessoa).model_dump()
    resposta["senhaTemporaria"] = senha_temporaria
    return resposta


@router.get("/", response_model=list[PessoaResposta])
async def listarPessoas(
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    return database.scalars(select(Colaborador).order_by(Colaborador.dataCriacao.desc())).all()


@router.put("/{pessoa_id}", response_model=PessoaResposta)
async def editarPessoas(
    pessoa_id: uuid.UUID,
    dados: PessoaEditar,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    pessoa = buscar_pessoa_ou_404(pessoa_id, database)

    dados_atualizados = dados.model_dump(exclude_unset=True)
    if "tipo" in dados_atualizados:
        dados_atualizados["tipo"] = str(dados_atualizados["tipo"])

    for campo, valor in dados_atualizados.items():
        setattr(pessoa, campo, valor)

    # mantém o e-mail do login sincronizado com o e-mail do colaborador
    if "email" in dados_atualizados and dados_atualizados["email"]:
        usuario = database.get(User, pessoa.idUser)
        if usuario:
            usuario.email = dados_atualizados["email"].lower()

    database.commit()
    database.refresh(pessoa)
    return pessoa


@router.patch("/{pessoa_id}/arquivar", response_model=PessoaResposta)
async def arquivarPessoa(
    pessoa_id: uuid.UUID,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    pessoa = buscar_pessoa_ou_404(pessoa_id, database)
    pessoa.ativo = False

    # bloqueia o login do colaborador arquivado
    usuario = database.get(User, pessoa.idUser)
    if usuario:
        usuario.status = "blocked"

    database.commit()
    database.refresh(pessoa)
    return pessoa


@router.patch("/{pessoa_id}/restaurar", response_model=PessoaResposta)
async def restaurarPessoa(
    pessoa_id: uuid.UUID,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    pessoa = buscar_pessoa_ou_404(pessoa_id, database)
    pessoa.ativo = True

    usuario = database.get(User, pessoa.idUser)
    if usuario:
        usuario.status = "active"

    database.commit()
    database.refresh(pessoa)
    return pessoa


@router.delete("/{pessoa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluirPessoas(
    pessoa_id: uuid.UUID,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    pessoa = buscar_pessoa_ou_404(pessoa_id, database)
    usuario = database.get(User, pessoa.idUser)

    database.delete(pessoa)
    if usuario:
        database.delete(usuario)  # remove o login junto — colaborador excluído não deve mais logar

    database.commit()