# ---------------------------------------------------------
# ATENDIMENTO (fale com o síndico)
# ---------------------------------------------------------
# Qualquer pessoa com acesso abre um chamado (protocolo nº)
# com assunto, categoria e mensagem. A conversa fica
# registrada e é privada entre quem abriu e a gestão.
# ADM/SINDICO veem e respondem todos os chamados.
# Situação: ABERTO (aguardando a gestão), RESPONDIDO
# (aguardando o morador) e ENCERRADO.
# ---------------------------------------------------------

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from App.consultas import salvar
from App.database import get_database
from App.dependencies import Contexto, get_contexto, negar
from App.models import CategoriaChamado, Chamado, ChamadoMensagem, Pessoa, PessoaApartamento
from Router.Vagas import rotulo_apartamento

router = APIRouter(prefix="/chamados")


# =========================================================
# DADOS
# =========================================================

def validar_texto(valor: str) -> str:
    valor = valor.strip()
    if not valor:
        raise ValueError("Campo obrigatório")
    return valor


class ChamadoCriar(BaseModel):
    assunto: str = Field(min_length=3, max_length=150)
    categoria: CategoriaChamado = "OUTRO"
    mensagem: str = Field(min_length=1, max_length=5000)

    @field_validator("assunto", "mensagem")
    @classmethod
    def limpar(cls, valor: str):
        return validar_texto(valor)


class MensagemCriar(BaseModel):
    texto: str = Field(min_length=1, max_length=5000)

    @field_validator("texto")
    @classmethod
    def limpar(cls, valor: str):
        return validar_texto(valor)


class MensagemResposta(BaseModel):
    id: uuid.UUID
    autor_nome: str
    da_gestao: bool
    minha: bool
    texto: str
    created_at: datetime


class ChamadoResumo(BaseModel):
    id: uuid.UUID
    numero: int
    assunto: str
    categoria: str
    status: str
    autor_nome: str
    autor_unidades: list[str]
    nao_lido: bool          # há novidade para quem está vendo
    total_mensagens: int
    created_at: datetime
    updated_at: datetime
    encerrado_em: datetime | None


class ChamadoDetalhe(ChamadoResumo):
    mensagens: list[MensagemResposta]


# =========================================================
# AUXILIARES
# =========================================================

def nome_do_autor(ctx: Contexto) -> str:
    return ctx.pessoa.nome if ctx.pessoa else ctx.usuario.full_name


def consulta_chamados(ctx: Contexto):
    consulta = (
        select(Chamado)
        .where(Chamado.condominio_id == ctx.condominio_id)
        .options(
            selectinload(Chamado.mensagens),
            selectinload(Chamado.autor_pessoa).selectinload(Pessoa.apartamentos).selectinload(PessoaApartamento.apartamento),
        )
    )
    if not ctx.edita_tudo:
        consulta = consulta.where(Chamado.autor_user_id == ctx.usuario.id)  # cada um vê só os próprios
    return consulta


def unidades(chamado: Chamado) -> list[str]:
    if not chamado.autor_pessoa:
        return []
    return [rotulo_apartamento(v.apartamento) for v in chamado.autor_pessoa.apartamentos if v.ativo]


def montar(chamado: Chamado, ctx: Contexto, detalhe: bool = False) -> dict:
    dados = {
        "id": chamado.id, "numero": chamado.numero, "assunto": chamado.assunto, "categoria": chamado.categoria,
        "status": chamado.status, "autor_nome": chamado.autor_nome, "autor_unidades": unidades(chamado),
        "nao_lido": not (chamado.lido_pela_gestao if ctx.edita_tudo else chamado.lido_pelo_autor),
        "total_mensagens": len(chamado.mensagens),
        "created_at": chamado.created_at, "updated_at": chamado.updated_at, "encerrado_em": chamado.encerrado_em,
    }
    if detalhe:
        dados["mensagens"] = [{
            "id": m.id, "autor_nome": m.autor_nome, "da_gestao": m.da_gestao, "minha": m.autor_user_id == ctx.usuario.id,
            "texto": m.texto, "created_at": m.created_at,
        } for m in chamado.mensagens]
    return dados


def buscar(database: Session, ctx: Contexto, chamado_id: uuid.UUID) -> Chamado:
    chamado = database.scalar(consulta_chamados(ctx).where(Chamado.id == chamado_id).execution_options(populate_existing=True))
    if not chamado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chamado não encontrado")
    return chamado


def detalhe(database: Session, ctx: Contexto, chamado_id: uuid.UUID) -> dict:
    return montar(buscar(database, ctx, chamado_id), ctx, detalhe=True)


# =========================================================
# ROTAS
# =========================================================

@router.get("/", response_model=list[ChamadoResumo])
async def listarChamados(database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    chamados = database.scalars(consulta_chamados(ctx).order_by(Chamado.updated_at.desc())).all()
    return [montar(c, ctx) for c in chamados]


@router.post("/", response_model=ChamadoDetalhe, status_code=status.HTTP_201_CREATED)
async def abrirChamado(dados: ChamadoCriar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    if ctx.edita_tudo:
        negar()  # a gestão responde os chamados; quem abre são os demais
    numero = (database.scalar(select(func.max(Chamado.numero)).where(Chamado.condominio_id == ctx.condominio_id)) or 0) + 1
    autor = nome_do_autor(ctx)
    chamado = Chamado(
        condominio_id=ctx.condominio_id, numero=numero, autor_user_id=ctx.usuario.id,
        autor_pessoa_id=ctx.pessoa.id if ctx.pessoa else None, autor_nome=autor,
        assunto=dados.assunto, categoria=dados.categoria,
    )
    chamado.mensagens.append(ChamadoMensagem(autor_user_id=ctx.usuario.id, autor_nome=autor, texto=dados.mensagem))
    database.add(chamado)
    salvar(database, "Não foi possível abrir o chamado agora. Tente novamente")
    return detalhe(database, ctx, chamado.id)


@router.get("/{chamado_id}", response_model=ChamadoDetalhe)
async def verChamado(chamado_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # abrir a conversa marca como lida para quem está vendo
    chamado = buscar(database, ctx, chamado_id)
    if ctx.edita_tudo and not chamado.lido_pela_gestao:
        chamado.lido_pela_gestao = True
        salvar(database)
    elif not ctx.edita_tudo and not chamado.lido_pelo_autor:
        chamado.lido_pelo_autor = True
        salvar(database)
    return detalhe(database, ctx, chamado_id)


@router.post("/{chamado_id}/mensagens", response_model=ChamadoDetalhe)
async def responderChamado(chamado_id: uuid.UUID, dados: MensagemCriar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    chamado = buscar(database, ctx, chamado_id)
    if chamado.status == "ENCERRADO":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chamado encerrado. Reabra para enviar uma nova mensagem")

    da_gestao = ctx.edita_tudo
    database.add(ChamadoMensagem(chamado_id=chamado.id, autor_user_id=ctx.usuario.id, autor_nome=nome_do_autor(ctx), da_gestao=da_gestao, texto=dados.texto))
    chamado.status = "RESPONDIDO" if da_gestao else "ABERTO"
    chamado.lido_pela_gestao = da_gestao
    chamado.lido_pelo_autor = not da_gestao
    salvar(database)
    return detalhe(database, ctx, chamado_id)


@router.patch("/{chamado_id}/encerrar", response_model=ChamadoDetalhe)
async def encerrarChamado(chamado_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    chamado = buscar(database, ctx, chamado_id)
    if chamado.status != "ENCERRADO":
        chamado.status = "ENCERRADO"
        chamado.encerrado_em = func.now()
        # avisa o outro lado que o chamado foi encerrado
        if ctx.edita_tudo:
            chamado.lido_pelo_autor = False
        else:
            chamado.lido_pela_gestao = False
        salvar(database)
    return detalhe(database, ctx, chamado_id)


@router.patch("/{chamado_id}/reabrir", response_model=ChamadoDetalhe)
async def reabrirChamado(chamado_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    chamado = buscar(database, ctx, chamado_id)
    if chamado.status == "ENCERRADO":
        chamado.status = "ABERTO"
        chamado.encerrado_em = None
        chamado.lido_pela_gestao = ctx.edita_tudo
        salvar(database)
    return detalhe(database, ctx, chamado_id)
