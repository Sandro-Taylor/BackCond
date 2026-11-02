# ---------------------------------------------------------
# MANUTENÇÕES E PRESTADORES
# ---------------------------------------------------------
# Manutenções (planilha "Controle"): item periódico com última execução
# e intervalo em meses. A empresa vem do cadastro de prestadores
# (prestador_id): nada de nome digitado em dois lugares. O sistema calcula:
#   próximo vencimento = última execução + intervalo (mesmo dia; dia 31
#     em mês curto vira o último dia do mês)
#   dias restantes = próximo vencimento - hoje
#   status: SEM_DATA (sem última execução) | VENCIDO (dias < 0)
#           | EM_BREVE (dias <= alerta) | EM_DIA
# Alerta (dias de antecedência): por condomínio (condominios.alerta_manutencao_dias).
# Prestadores (planilha "Fornecedores"): empresas e pessoas que trabalham
# para o condomínio, com contato, custo mensal e observações.
# Vê manutenções: ADM, síndico, conselheiro e funcionário.
# Vê prestadores: ADM, síndico e conselheiro (tem custos/salários).
# Edita tudo: ADM e síndico.
# ---------------------------------------------------------

import calendar
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, get_contexto, negar
from App.models import Condominio, Manutencao, Prestador

router = APIRouter()

def ler_manutencoes(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    if not ctx.ve_tudo:
        negar()
    return ctx


def ler_prestadores(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    if not ctx.ve_financeiro_tudo:
        negar()
    return ctx


def texto(v: str | None) -> str | None:
    return (v or "").strip() or None


# =========================================================
# MANUTENÇÕES
# =========================================================

class ManutencaoDados(BaseModel):
    categoria: str = Field(min_length=1, max_length=80)
    item: str = Field(min_length=1, max_length=200)
    prestador_id: uuid.UUID | None = None      # empresa/pessoa (cadastro de prestadores)
    periodicidade: str | None = Field(default=None, max_length=60)
    intervalo_meses: int | None = Field(default=None, ge=1, le=600)
    base_legal: str | None = Field(default=None, max_length=200)
    ultima_execucao: date | None = None
    observacoes: str | None = None


class ManutencaoResposta(ManutencaoDados):
    id: uuid.UUID
    ordem: int
    empresa: str | None              # empresa do prestador ligado
    responsavel: str | None          # pessoa do prestador ligado
    proximo_vencimento: date | None
    dias_restantes: int | None
    status: str                      # SEM_DATA | VENCIDO | EM_BREVE | EM_DIA


class Manutencoes(BaseModel):
    hoje: date
    alerta_dias: int
    resumo: dict[str, int]           # quantidade por status
    itens: list[ManutencaoResposta]


class Alerta(BaseModel):
    dias: int = Field(ge=0, le=365)


class Execucao(BaseModel):
    data: date


def somar_meses(dia: date, meses: int) -> date:
    total = dia.month - 1 + meses
    ano, mes = dia.year + total // 12, total % 12 + 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def prestadores_do(database: Session, condominio_id) -> dict:
    return {p.id: p for p in database.scalars(select(Prestador).where(Prestador.condominio_id == condominio_id)).all()}


def calcular(m: Manutencao, alerta: int, hoje: date, prestadores: dict) -> dict:
    proximo = somar_meses(m.ultima_execucao, m.intervalo_meses) if m.ultima_execucao and m.intervalo_meses else None
    dias = (proximo - hoje).days if proximo else None
    situacao = "SEM_DATA" if dias is None else "VENCIDO" if dias < 0 else "EM_BREVE" if dias <= alerta else "EM_DIA"
    p = prestadores.get(m.prestador_id)
    return {
        "id": m.id, "ordem": m.ordem, "categoria": m.categoria, "item": m.item, "periodicidade": m.periodicidade,
        "prestador_id": m.prestador_id, "empresa": p.empresa if p else None, "responsavel": p.pessoa if p else None,
        "intervalo_meses": m.intervalo_meses, "base_legal": m.base_legal,
        "ultima_execucao": m.ultima_execucao, "observacoes": m.observacoes,
        "proximo_vencimento": proximo, "dias_restantes": dias, "status": situacao,
    }


def alerta_do(database: Session, condominio_id) -> int:
    condominio = database.get(Condominio, condominio_id)
    return condominio.alerta_manutencao_dias if condominio else 30


def buscar_manutencao(database: Session, ctx: Contexto, manutencao_id: uuid.UUID) -> Manutencao:
    m = database.scalar(select(Manutencao).where(Manutencao.id == manutencao_id, Manutencao.condominio_id == ctx.condominio_id))
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manutenção não encontrada")
    return m


def aplicar(m: Manutencao, dados: ManutencaoDados, prestadores: dict):
    if dados.prestador_id and dados.prestador_id not in prestadores:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prestador não encontrado neste condomínio")
    m.categoria, m.item, m.prestador_id = dados.categoria.strip(), dados.item.strip(), dados.prestador_id
    m.periodicidade, m.base_legal, m.observacoes = texto(dados.periodicidade), texto(dados.base_legal), texto(dados.observacoes)
    m.intervalo_meses, m.ultima_execucao = dados.intervalo_meses, dados.ultima_execucao


@router.get("/manutencoes", response_model=Manutencoes)
def listarManutencoes(database: Session = Depends(get_database), ctx: Contexto = Depends(ler_manutencoes)):
    hoje, alerta, prestadores = date.today(), alerta_do(database, ctx.condominio_id), prestadores_do(database, ctx.condominio_id)
    itens = [calcular(m, alerta, hoje, prestadores) for m in database.scalars(
        select(Manutencao).where(Manutencao.condominio_id == ctx.condominio_id).order_by(Manutencao.ordem, Manutencao.created_at)
    ).all()]
    resumo = {s: sum(1 for i in itens if i["status"] == s) for s in ("VENCIDO", "EM_BREVE", "EM_DIA", "SEM_DATA")}
    return {"hoje": hoje, "alerta_dias": alerta, "resumo": resumo, "itens": itens}


@router.post("/manutencoes", response_model=ManutencaoResposta, status_code=status.HTTP_201_CREATED)
def criarManutencao(dados: ManutencaoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    ultima = database.scalar(select(func.max(Manutencao.ordem)).where(Manutencao.condominio_id == ctx.condominio_id)) or 0
    m = Manutencao(condominio_id=ctx.condominio_id, ordem=ultima + 1)
    prestadores = prestadores_do(database, ctx.condominio_id)
    aplicar(m, dados, prestadores)
    database.add(m)
    database.commit()
    return calcular(m, alerta_do(database, ctx.condominio_id), date.today(), prestadores)


@router.put("/manutencoes/alerta", response_model=Alerta)
def alterarAlerta(dados: Alerta, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    condominio = database.get(Condominio, ctx.condominio_id)
    condominio.alerta_manutencao_dias = dados.dias
    database.commit()
    return dados


@router.put("/manutencoes/{manutencao_id}", response_model=ManutencaoResposta)
def editarManutencao(manutencao_id: uuid.UUID, dados: ManutencaoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    m = buscar_manutencao(database, ctx, manutencao_id)
    prestadores = prestadores_do(database, ctx.condominio_id)
    aplicar(m, dados, prestadores)
    database.commit()
    return calcular(m, alerta_do(database, ctx.condominio_id), date.today(), prestadores)


@router.post("/manutencoes/{manutencao_id}/executada", response_model=ManutencaoResposta)
def registrarExecucao(manutencao_id: uuid.UUID, dados: Execucao, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # "foi feita em <data>": vira a última execução e o vencimento anda sozinho
    m = buscar_manutencao(database, ctx, manutencao_id)
    m.ultima_execucao = dados.data
    database.commit()
    return calcular(m, alerta_do(database, ctx.condominio_id), date.today(), prestadores_do(database, ctx.condominio_id))


@router.delete("/manutencoes/{manutencao_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirManutencao(manutencao_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    database.delete(buscar_manutencao(database, ctx, manutencao_id))
    database.commit()


# =========================================================
# PRESTADORES
# =========================================================

class PrestadorDados(BaseModel):
    empresa: str = Field(min_length=1, max_length=150)
    setor: str | None = Field(default=None, max_length=150)
    pessoa: str | None = Field(default=None, max_length=150)
    cnpj: str | None = Field(default=None, max_length=20)
    telefone: str | None = Field(default=None, max_length=30)
    custo: Decimal | None = Field(default=None, ge=0)
    observacoes: str | None = None


class PrestadorResposta(PrestadorDados):
    id: uuid.UUID
    ordem: int


class Prestadores(BaseModel):
    custo_mensal: Decimal
    itens: list[PrestadorResposta]


def buscar_prestador(database: Session, ctx: Contexto, prestador_id: uuid.UUID) -> Prestador:
    p = database.scalar(select(Prestador).where(Prestador.id == prestador_id, Prestador.condominio_id == ctx.condominio_id))
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prestador não encontrado")
    return p


def aplicar_prestador(p: Prestador, dados: PrestadorDados):
    p.empresa = dados.empresa.strip()
    for campo in ("setor", "pessoa", "cnpj", "telefone", "observacoes"):
        setattr(p, campo, texto(getattr(dados, campo)))
    p.custo = dados.custo


@router.get("/prestadores", response_model=Prestadores)
def listarPrestadores(database: Session = Depends(get_database), ctx: Contexto = Depends(ler_prestadores)):
    itens = database.scalars(select(Prestador).where(Prestador.condominio_id == ctx.condominio_id).order_by(Prestador.ordem, Prestador.created_at)).all()
    return {"custo_mensal": sum((p.custo or Decimal("0") for p in itens), Decimal("0")), "itens": itens}


@router.post("/prestadores", response_model=PrestadorResposta, status_code=status.HTTP_201_CREATED)
def criarPrestador(dados: PrestadorDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    ultima = database.scalar(select(func.max(Prestador.ordem)).where(Prestador.condominio_id == ctx.condominio_id)) or 0
    p = Prestador(condominio_id=ctx.condominio_id, ordem=ultima + 1)
    aplicar_prestador(p, dados)
    database.add(p)
    database.commit()
    database.refresh(p)
    return p


@router.put("/prestadores/{prestador_id}", response_model=PrestadorResposta)
def editarPrestador(prestador_id: uuid.UUID, dados: PrestadorDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    p = buscar_prestador(database, ctx, prestador_id)
    aplicar_prestador(p, dados)
    database.commit()
    database.refresh(p)
    return p


@router.delete("/prestadores/{prestador_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirPrestador(prestador_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    database.delete(buscar_prestador(database, ctx, prestador_id))
    database.commit()
