# ---------------------------------------------------------
# QUADRO DE AVISOS
# ---------------------------------------------------------
# ADM/SINDICO publicam, editam, fixam e arquivam avisos.
# Todos do condomínio leem e confirmam "li e estou ciente";
# a gestão acompanha quantos já confirmaram.
# Vigente = ativo e sem validade vencida.
# ---------------------------------------------------------

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, salvar
from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, get_contexto
from App.models import Aviso, AvisoLeitura, Pessoa, PrioridadeAviso, User

router = APIRouter(prefix="/avisos")

FUSO = ZoneInfo("America/Sao_Paulo")


def hoje() -> date:
    return datetime.now(FUSO).date()


def nome_do_autor(ctx: Contexto) -> str:
    return ctx.pessoa.nome if ctx.pessoa else ctx.usuario.full_name


# =========================================================
# DADOS
# =========================================================

class AvisoDados(BaseModel):
    titulo: str = Field(min_length=3, max_length=150)
    conteudo: str = Field(min_length=1)
    prioridade: PrioridadeAviso = "NORMAL"
    fixado: bool = False
    expira_em: date | None = None

    @field_validator("titulo", "conteudo")
    @classmethod
    def sem_espacos(cls, valor: str):
        valor = valor.strip()
        if not valor:
            raise ValueError("Campo obrigatório")
        return valor


class AvisoEditar(AvisoDados):
    ativo: bool = True


class AvisoResposta(BaseModel):
    id: uuid.UUID
    titulo: str
    conteudo: str
    prioridade: str
    fixado: bool
    expira_em: date | None
    ativo: bool
    vigente: bool
    autor_nome: str
    created_at: datetime
    updated_at: datetime
    lido: bool                          # o usuário logado já confirmou
    total_leituras: int | None          # só para a gestão
    total_destinatarios: int | None     # só para a gestão (pessoas com acesso ao sistema)


class Leitura(BaseModel):
    nome: str
    lido_em: datetime


# =========================================================
# AUXILIARES
# =========================================================

def vigente(aviso: Aviso, referencia: date) -> bool:
    return aviso.ativo and (aviso.expira_em is None or aviso.expira_em >= referencia)


def total_destinatarios(database: Session, condominio_id: uuid.UUID) -> int:
    return database.scalar(select(func.count()).select_from(Pessoa).where(
        Pessoa.condominio_id == condominio_id, Pessoa.ativo.is_(True), Pessoa.user_id.is_not(None),
    )) or 0


def montar_lista(database: Session, ctx: Contexto, avisos: list[Aviso]) -> list[dict]:
    ids = [a.id for a in avisos]
    lidos = set(database.scalars(select(AvisoLeitura.aviso_id).where(
        AvisoLeitura.aviso_id.in_(ids), AvisoLeitura.user_id == ctx.usuario.id,
    )).all()) if ids else set()

    contagem: dict[uuid.UUID, int] = {}
    destinatarios = None
    if ctx.edita_tudo and ids:
        contagem = dict(database.execute(
            select(AvisoLeitura.aviso_id, func.count()).where(AvisoLeitura.aviso_id.in_(ids)).group_by(AvisoLeitura.aviso_id)
        ).all())
    if ctx.edita_tudo:
        destinatarios = total_destinatarios(database, ctx.condominio_id)

    referencia = hoje()
    return [{
        "id": a.id, "titulo": a.titulo, "conteudo": a.conteudo, "prioridade": a.prioridade, "fixado": a.fixado,
        "expira_em": a.expira_em, "ativo": a.ativo, "vigente": vigente(a, referencia), "autor_nome": a.autor_nome,
        "created_at": a.created_at, "updated_at": a.updated_at, "lido": a.id in lidos,
        "total_leituras": contagem.get(a.id, 0) if ctx.edita_tudo else None,
        "total_destinatarios": destinatarios,
    } for a in avisos]


def um(database: Session, ctx: Contexto, aviso: Aviso) -> dict:
    database.refresh(aviso)
    return montar_lista(database, ctx, [aviso])[0]


def validar_validade(expira_em: date | None):
    if expira_em and expira_em < hoje():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A validade não pode ser uma data passada")


# =========================================================
# ROTAS
# =========================================================

@router.get("/", response_model=list[AvisoResposta])
async def listarAvisos(historico: bool = False, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # padrão: só os vigentes (quadro). historico=true: inclui vencidos (e arquivados, para a gestão)
    consulta = select(Aviso).where(Aviso.condominio_id == ctx.condominio_id)
    if not historico:
        consulta = consulta.where(Aviso.ativo.is_(True), or_(Aviso.expira_em.is_(None), Aviso.expira_em >= hoje()))
    elif not ctx.edita_tudo:
        consulta = consulta.where(Aviso.ativo.is_(True))

    ordem_prioridade = case({"URGENTE": 0, "IMPORTANTE": 1}, value=Aviso.prioridade, else_=2)
    avisos = database.scalars(consulta.order_by(Aviso.fixado.desc(), ordem_prioridade, Aviso.created_at.desc())).all()
    return montar_lista(database, ctx, list(avisos))


@router.post("/", response_model=AvisoResposta, status_code=status.HTTP_201_CREATED)
async def publicarAviso(dados: AvisoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    validar_validade(dados.expira_em)
    aviso = Aviso(condominio_id=ctx.condominio_id, autor_user_id=ctx.usuario.id, autor_nome=nome_do_autor(ctx), **dados.model_dump())
    database.add(aviso)
    salvar(database)
    return um(database, ctx, aviso)


@router.put("/{aviso_id}", response_model=AvisoResposta)
async def editarAviso(aviso_id: uuid.UUID, dados: AvisoEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    aviso = buscar_no_condominio(database, Aviso, aviso_id, ctx.condominio_id, "Aviso não encontrado")
    if dados.expira_em != aviso.expira_em:
        validar_validade(dados.expira_em)
    for campo, valor in dados.model_dump().items():
        setattr(aviso, campo, valor)
    salvar(database)
    return um(database, ctx, aviso)


@router.delete("/{aviso_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluirAviso(aviso_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    aviso = buscar_no_condominio(database, Aviso, aviso_id, ctx.condominio_id, "Aviso não encontrado")
    database.delete(aviso)
    salvar(database)


@router.post("/{aviso_id}/ciente", response_model=AvisoResposta)
async def confirmarLeitura(aviso_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    aviso = buscar_no_condominio(database, Aviso, aviso_id, ctx.condominio_id, "Aviso não encontrado")
    if not aviso.ativo and not ctx.edita_tudo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aviso não encontrado")
    if not database.get(AvisoLeitura, (aviso.id, ctx.usuario.id)):
        database.add(AvisoLeitura(aviso_id=aviso.id, user_id=ctx.usuario.id))
        salvar(database)
    return um(database, ctx, aviso)


@router.get("/{aviso_id}/leituras", response_model=list[Leitura])
async def listarLeituras(aviso_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    buscar_no_condominio(database, Aviso, aviso_id, ctx.condominio_id, "Aviso não encontrado")
    # nome da pessoa no condomínio; se não houver, o nome do login
    nome = func.coalesce(Pessoa.nome, User.full_name)
    linhas = database.execute(
        select(nome, AvisoLeitura.lido_em)
        .join(User, User.id == AvisoLeitura.user_id)
        .outerjoin(Pessoa, (Pessoa.user_id == User.id) & (Pessoa.condominio_id == ctx.condominio_id))
        .where(AvisoLeitura.aviso_id == aviso_id)
        .order_by(AvisoLeitura.lido_em.desc())
    ).all()
    return [{"nome": n, "lido_em": lido_em} for n, lido_em in linhas]
