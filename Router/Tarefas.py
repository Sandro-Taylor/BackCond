# ---------------------------------------------------------
# TAREFAS
# ---------------------------------------------------------
# ADM/SINDICO ... criam, editam, designam, mudam qualquer
#                 status e excluem
# CONSELHEIRO ... vê todas; atua nas designadas a ele
# FUNCIONARIO ... vê e atua só nas designadas a ele
# MORADOR/PRESTADOR sem acesso
#
# Responsável: pessoa ativa com perfil SINDICO, CONSELHEIRO
# ou FUNCIONARIO. Fluxo: PENDENTE -> EM_ANDAMENTO ->
# CONCLUIDA (CANCELADA só pela gestão). Cada mudança e
# comentário fica no histórico da tarefa.
# ---------------------------------------------------------

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from App.consultas import buscar_no_condominio, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, get_contexto, negar
from App.models import Funcionario, Pessoa, PrioridadeTarefa, StatusTarefa, Tarefa, TarefaHistorico

router = APIRouter(prefix="/tarefas")

FUSO = ZoneInfo("America/Sao_Paulo")
PERFIS_RESPONSAVEIS = ("SINDICO", "CONSELHEIRO", "FUNCIONARIO")
PERFIS_COM_ACESSO = {"ADM", "SINDICO", "CONSELHEIRO", "FUNCIONARIO"}
ROTULO_STATUS = {"PENDENTE": "Pendente", "EM_ANDAMENTO": "Em andamento", "CONCLUIDA": "Concluída", "CANCELADA": "Cancelada"}
ROTULO_PRIORIDADE = {"BAIXA": "Baixa", "MEDIA": "Média", "ALTA": "Alta", "URGENTE": "Urgente"}


def hoje() -> date:
    return datetime.now(FUSO).date()


def exigir_acesso_tarefas(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    if ctx.perfil not in PERFIS_COM_ACESSO:
        negar()
    return ctx


# =========================================================
# DADOS
# =========================================================

class TarefaDados(BaseModel):
    titulo: str = Field(min_length=3, max_length=150)
    descricao: str | None = None
    local: str | None = Field(default=None, max_length=100)
    responsavel_id: uuid.UUID
    prioridade: PrioridadeTarefa = "MEDIA"
    prazo: date | None = None

    @field_validator("titulo")
    @classmethod
    def limpar_titulo(cls, valor: str):
        valor = valor.strip()
        if len(valor) < 3:
            raise ValueError("Informe um título (mínimo 3 letras)")
        return valor


class MudarStatus(BaseModel):
    status: StatusTarefa
    comentario: str | None = Field(default=None, max_length=2000)


class Comentario(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)

    @field_validator("texto")
    @classmethod
    def limpar(cls, valor: str):
        valor = valor.strip()
        if not valor:
            raise ValueError("Escreva o comentário")
        return valor


class Responsavel(BaseModel):
    id: uuid.UUID
    nome: str
    perfil: str
    cargo: str | None  # funcionário: porteiro, zelador...
    tem_acesso: bool   # tem login no sistema


class HistoricoResposta(BaseModel):
    id: uuid.UUID
    autor_nome: str
    tipo: str
    texto: str
    created_at: datetime


class TarefaResposta(BaseModel):
    id: uuid.UUID
    numero: int
    titulo: str
    descricao: str | None
    local: str | None
    responsavel_id: uuid.UUID
    responsavel_nome: str
    responsavel_perfil: str
    responsavel_cargo: str | None
    criado_por_nome: str
    prioridade: str
    status: str
    prazo: date | None
    atrasada: bool
    concluida_em: datetime | None
    created_at: datetime
    updated_at: datetime
    total_comentarios: int
    minha: bool          # designada ao usuário logado
    pode_atuar: bool     # pode mudar status e comentar


class TarefaDetalhe(TarefaResposta):
    historico: list[HistoricoResposta]


# =========================================================
# AUXILIARES
# =========================================================

def nome_do_usuario(ctx: Contexto) -> str:
    return ctx.pessoa.nome if ctx.pessoa else ctx.usuario.full_name


def cargo_de(pessoa: Pessoa) -> str | None:
    return pessoa.funcionario.cargo.nome if pessoa.funcionario else None


def eh_minha(tarefa: Tarefa, ctx: Contexto) -> bool:
    return ctx.pessoa is not None and tarefa.responsavel_id == ctx.pessoa.id


def registrar(tarefa: Tarefa, ctx: Contexto, tipo: str, mensagem: str):
    tarefa.historico.append(TarefaHistorico(autor_user_id=ctx.usuario.id, autor_nome=nome_do_usuario(ctx), tipo=tipo, texto=mensagem))


def montar(tarefa: Tarefa, ctx: Contexto, referencia: date, detalhe: bool = False) -> dict:
    minha = eh_minha(tarefa, ctx)
    dados = {
        "id": tarefa.id, "numero": tarefa.numero, "titulo": tarefa.titulo, "descricao": tarefa.descricao, "local": tarefa.local,
        "responsavel_id": tarefa.responsavel_id, "responsavel_nome": tarefa.responsavel.nome, "responsavel_perfil": tarefa.responsavel.perfil,
        "responsavel_cargo": cargo_de(tarefa.responsavel),
        "criado_por_nome": tarefa.criado_por_nome, "prioridade": tarefa.prioridade, "status": tarefa.status, "prazo": tarefa.prazo,
        "atrasada": bool(tarefa.prazo and tarefa.prazo < referencia and tarefa.status in ("PENDENTE", "EM_ANDAMENTO")),
        "concluida_em": tarefa.concluida_em, "created_at": tarefa.created_at, "updated_at": tarefa.updated_at,
        "total_comentarios": sum(1 for h in tarefa.historico if h.tipo == "COMENTARIO"),
        "minha": minha, "pode_atuar": ctx.edita_tudo or minha,
    }
    if detalhe:
        dados["historico"] = [
            {"id": h.id, "autor_nome": h.autor_nome, "tipo": h.tipo, "texto": h.texto, "created_at": h.created_at}
            for h in tarefa.historico
        ]
    return dados


def consulta_tarefas(ctx: Contexto):
    consulta = (
        select(Tarefa)
        .where(Tarefa.condominio_id == ctx.condominio_id)
        .options(
            selectinload(Tarefa.responsavel).selectinload(Pessoa.funcionario).selectinload(Funcionario.cargo),
            selectinload(Tarefa.historico),
        )
    )
    if ctx.perfil == "FUNCIONARIO":
        consulta = consulta.where(Tarefa.responsavel_id == (ctx.pessoa.id if ctx.pessoa else None))
    return consulta


def buscar(database: Session, ctx: Contexto, tarefa_id: uuid.UUID) -> Tarefa:
    tarefa = database.scalar(consulta_tarefas(ctx).where(Tarefa.id == tarefa_id).execution_options(populate_existing=True))
    if not tarefa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarefa não encontrada")
    return tarefa


def detalhe(database: Session, ctx: Contexto, tarefa_id: uuid.UUID) -> dict:
    return montar(buscar(database, ctx, tarefa_id), ctx, hoje(), detalhe=True)


def validar_responsavel(database: Session, ctx: Contexto, pessoa_id: uuid.UUID) -> Pessoa:
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Responsável não encontrado")
    if not pessoa.ativo or pessoa.perfil not in PERFIS_RESPONSAVEIS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O responsável precisa ser o síndico, um conselheiro ou um funcionário ativo")
    return pessoa


def formatar(data: date | None) -> str:
    return data.strftime("%d/%m/%Y") if data else "sem prazo"


# =========================================================
# ROTAS
# =========================================================

@router.get("/responsaveis", response_model=list[Responsavel])
async def listarResponsaveis(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    pessoas = database.scalars(
        select(Pessoa)
        .where(Pessoa.condominio_id == ctx.condominio_id, Pessoa.ativo.is_(True), Pessoa.perfil.in_(PERFIS_RESPONSAVEIS))
        .options(selectinload(Pessoa.funcionario).selectinload(Funcionario.cargo))
        .order_by(Pessoa.nome)
    ).all()
    return [{"id": p.id, "nome": p.nome, "perfil": p.perfil, "cargo": cargo_de(p), "tem_acesso": p.user_id is not None} for p in pessoas]


@router.get("/", response_model=list[TarefaResposta])
async def listarTarefas(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_acesso_tarefas)):
    tarefas = database.scalars(consulta_tarefas(ctx).order_by(Tarefa.prazo.is_(None), Tarefa.prazo.asc(), Tarefa.numero.desc())).all()
    referencia = hoje()
    return [montar(t, ctx, referencia) for t in tarefas]


@router.get("/{tarefa_id}", response_model=TarefaDetalhe)
async def verTarefa(tarefa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_acesso_tarefas)):
    return detalhe(database, ctx, tarefa_id)


@router.post("/", response_model=TarefaDetalhe, status_code=status.HTTP_201_CREATED)
async def criarTarefa(dados: TarefaDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    responsavel = validar_responsavel(database, ctx, dados.responsavel_id)
    numero = (database.scalar(select(func.max(Tarefa.numero)).where(Tarefa.condominio_id == ctx.condominio_id)) or 0) + 1
    tarefa = Tarefa(
        condominio_id=ctx.condominio_id, numero=numero, titulo=dados.titulo, descricao=texto(dados.descricao),
        local=texto(dados.local), responsavel_id=responsavel.id, criado_por_user_id=ctx.usuario.id,
        criado_por_nome=nome_do_usuario(ctx), prioridade=dados.prioridade, prazo=dados.prazo,
    )
    registrar(tarefa, ctx, "EVENTO", f"Tarefa criada e designada a {responsavel.nome}")
    database.add(tarefa)
    salvar(database, "Não foi possível criar a tarefa agora. Tente novamente")
    return detalhe(database, ctx, tarefa.id)


@router.put("/{tarefa_id}", response_model=TarefaDetalhe)
async def editarTarefa(tarefa_id: uuid.UUID, dados: TarefaDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    tarefa = buscar(database, ctx, tarefa_id)
    if tarefa.responsavel_id != dados.responsavel_id:
        novo = validar_responsavel(database, ctx, dados.responsavel_id)
        registrar(tarefa, ctx, "EVENTO", f"Responsável alterado de {tarefa.responsavel.nome} para {novo.nome}")
        tarefa.responsavel_id = novo.id
    if tarefa.prazo != dados.prazo:
        registrar(tarefa, ctx, "EVENTO", f"Prazo alterado de {formatar(tarefa.prazo)} para {formatar(dados.prazo)}")
    if tarefa.prioridade != dados.prioridade:
        registrar(tarefa, ctx, "EVENTO", f"Prioridade alterada para {ROTULO_PRIORIDADE[dados.prioridade]}")
    tarefa.titulo = dados.titulo
    tarefa.descricao = texto(dados.descricao)
    tarefa.local = texto(dados.local)
    tarefa.prioridade = dados.prioridade
    tarefa.prazo = dados.prazo
    salvar(database)
    return detalhe(database, ctx, tarefa_id)


@router.patch("/{tarefa_id}/status", response_model=TarefaDetalhe)
async def mudarStatus(tarefa_id: uuid.UUID, dados: MudarStatus, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_acesso_tarefas)):
    tarefa = buscar(database, ctx, tarefa_id)
    if not ctx.edita_tudo:
        if not eh_minha(tarefa, ctx):
            negar()
        # o responsável só avança a tarefa; cancelar e reabrir é com a gestão
        if dados.status == "CANCELADA" or tarefa.status in ("CONCLUIDA", "CANCELADA"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Somente o síndico pode cancelar ou reabrir uma tarefa")
    if dados.status == tarefa.status:
        return detalhe(database, ctx, tarefa_id)

    registrar(tarefa, ctx, "EVENTO", f"Status alterado de {ROTULO_STATUS[tarefa.status]} para {ROTULO_STATUS[dados.status]}")
    if texto(dados.comentario):
        registrar(tarefa, ctx, "COMENTARIO", texto(dados.comentario))
    tarefa.status = dados.status
    tarefa.concluida_em = func.now() if dados.status == "CONCLUIDA" else None
    salvar(database)
    return detalhe(database, ctx, tarefa_id)


@router.post("/{tarefa_id}/comentarios", response_model=TarefaDetalhe)
async def comentarTarefa(tarefa_id: uuid.UUID, dados: Comentario, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_acesso_tarefas)):
    tarefa = buscar(database, ctx, tarefa_id)
    if not (ctx.edita_tudo or eh_minha(tarefa, ctx)):
        negar()
    registrar(tarefa, ctx, "COMENTARIO", dados.texto)
    salvar(database)
    return detalhe(database, ctx, tarefa_id)


@router.delete("/{tarefa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluirTarefa(tarefa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    tarefa = buscar_no_condominio(database, Tarefa, tarefa_id, ctx.condominio_id, "Tarefa não encontrada")
    database.delete(tarefa)
    salvar(database)
