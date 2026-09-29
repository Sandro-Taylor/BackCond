# ---------------------------------------------------------
# FINANCEIRO (cotas condominiais)
# ---------------------------------------------------------
# Cada apartamento recebe uma cota ORDINARIA por mês
# (competência = dia 1 do mês) e pode ter cotas EXTRA.
# Situação: ABERTA, PAGA, CANCELADA; ATRASADA é calculada
# (aberta com vencimento passado), com multa e juros pelo
# padrão do condomínio (juros proporcionais aos dias).
#
# ADM/SINDICO ... configuram, geram, lançam e dão baixa
# CONSELHEIRO ... vê tudo
# MORADOR ....... vê só as cotas das próprias unidades
# ---------------------------------------------------------

import calendar
import re
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from App.consultas import buscar_no_condominio, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, apartamentos_do_usuario, exigir_financeiro, exigir_gestao
from App.models import Apartamento, Condominio, Cota, FormaPagamento, PessoaApartamento, TipoCota
from Router.Vagas import rotulo_apartamento

router = APIRouter(prefix="/financeiro")

FUSO = ZoneInfo("America/Sao_Paulo")
CENTAVO = Decimal("0.01")
Dinheiro = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


def hoje() -> date:
    return datetime.now(FUSO).date()


def ler_competencia(valor: str) -> date:
    # "2026-10" -> 2026-10-01
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", valor or ""):
        raise ValueError("Competência inválida (use AAAA-MM)")
    ano, mes = valor.split("-")
    return date(int(ano), int(mes), 1)


def vencimento_do_mes(competencia: date, dia: int) -> date:
    ultimo_dia = calendar.monthrange(competencia.year, competencia.month)[1]
    return competencia.replace(day=min(dia, ultimo_dia))


# =========================================================
# DADOS RECEBIDOS
# =========================================================

class Configuracao(BaseModel):
    valor_cota: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    dia_vencimento: int = Field(ge=1, le=31)
    multa_percentual: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    juros_mensal: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class GerarCotas(BaseModel):
    competencia: str
    valor: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)  # vazio = valor padrão
    dia_vencimento: int | None = Field(default=None, ge=1, le=31)                     # vazio = dia padrão

    @field_validator("competencia")
    @classmethod
    def validar_competencia(cls, valor):
        ler_competencia(valor)
        return valor


class CotaCriar(BaseModel):
    apartamento_id: uuid.UUID
    competencia: str
    tipo: TipoCota = "EXTRA"
    descricao: str | None = Field(default=None, max_length=150)
    valor: Dinheiro
    vencimento: date
    observacao: str | None = None

    @field_validator("competencia")
    @classmethod
    def validar_competencia(cls, valor):
        ler_competencia(valor)
        return valor


class CotaEditar(BaseModel):
    descricao: str | None = Field(default=None, max_length=150)
    valor: Dinheiro
    vencimento: date
    observacao: str | None = None


class Pagamento(BaseModel):
    data_pagamento: date
    valor_pago: Dinheiro
    forma_pagamento: FormaPagamento
    observacao: str | None = None


# =========================================================
# RESPOSTAS
# =========================================================

class ConfiguracaoResposta(BaseModel):
    valor_cota: float | None
    dia_vencimento: int
    multa_percentual: float
    juros_mensal: float
    model_config = ConfigDict(from_attributes=True)


class CotaResposta(BaseModel):
    id: uuid.UUID
    apartamento_id: uuid.UUID
    apartamento_rotulo: str
    responsavel: str | None
    competencia: date
    tipo: str
    descricao: str | None
    valor: float
    vencimento: date
    status: str
    situacao: str          # ABERTA, ATRASADA, PAGA, CANCELADA
    dias_atraso: int
    multa: float
    juros: float
    valor_atualizado: float  # valor + multa + juros (só muda quando atrasada)
    data_pagamento: date | None
    valor_pago: float | None
    forma_pagamento: str | None
    observacao: str | None


class ResultadoGeracao(BaseModel):
    criadas: int
    ja_existiam: int


# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def condominio_atual(database: Session, ctx: Contexto) -> Condominio:
    return database.get(Condominio, ctx.condominio_id)


def responsavel(apartamento: Apartamento) -> str | None:
    # quem paga: o inquilino, se houver; senão o proprietário
    vinculos = [v for v in apartamento.pessoas if v.ativo]
    for tipo in ("INQUILINO", "PROPRIETARIO"):
        do_tipo = sorted((v for v in vinculos if v.tipo_relacao == tipo), key=lambda v: not v.principal)
        if do_tipo:
            return do_tipo[0].pessoa.nome
    return None


def montar(cota: Cota, condominio: Condominio, referencia: date) -> dict:
    multa = juros = Decimal("0")
    dias = 0
    situacao = cota.status
    if cota.status == "ABERTA" and referencia > cota.vencimento:
        situacao = "ATRASADA"
        dias = (referencia - cota.vencimento).days
        multa = (cota.valor * condominio.multa_percentual / 100).quantize(CENTAVO, ROUND_HALF_UP)
        juros = (cota.valor * condominio.juros_mensal / 100 * dias / 30).quantize(CENTAVO, ROUND_HALF_UP)
    return {
        "id": cota.id,
        "apartamento_id": cota.apartamento_id,
        "apartamento_rotulo": rotulo_apartamento(cota.apartamento),
        "responsavel": responsavel(cota.apartamento),
        "competencia": cota.competencia,
        "tipo": cota.tipo,
        "descricao": cota.descricao,
        "valor": cota.valor,
        "vencimento": cota.vencimento,
        "status": cota.status,
        "situacao": situacao,
        "dias_atraso": dias,
        "multa": multa,
        "juros": juros,
        "valor_atualizado": cota.valor + multa + juros,
        "data_pagamento": cota.data_pagamento,
        "valor_pago": cota.valor_pago,
        "forma_pagamento": cota.forma_pagamento,
        "observacao": cota.observacao,
    }


def consulta_cotas(condominio_id: uuid.UUID):
    return (
        select(Cota)
        .join(Apartamento, Apartamento.id == Cota.apartamento_id)
        .where(Cota.condominio_id == condominio_id)
        .options(selectinload(Cota.apartamento).selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa))
    )


def carregar(database: Session, cota_id: uuid.UUID, ctx: Contexto) -> dict:
    cota = database.scalar(consulta_cotas(ctx.condominio_id).where(Cota.id == cota_id).execution_options(populate_existing=True))
    if not cota:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cota não encontrada")
    return montar(cota, condominio_atual(database, ctx), hoje())


def cota_aberta(database: Session, cota_id: uuid.UUID, ctx: Contexto) -> Cota:
    cota = buscar_no_condominio(database, Cota, cota_id, ctx.condominio_id, "Cota não encontrada")
    if cota.status != "ABERTA":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Só é possível alterar uma cota em aberto")
    return cota


def ordinaria_existe(database: Session, apartamento_id: uuid.UUID, competencia: date) -> bool:
    return bool(database.scalar(select(Cota.id).where(
        Cota.apartamento_id == apartamento_id, Cota.competencia == competencia, Cota.tipo == "ORDINARIA",
    )))


# =========================================================
# CONFIGURAÇÃO
# =========================================================

@router.get("/configuracao", response_model=ConfiguracaoResposta)
async def verConfiguracao(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_financeiro)):
    return condominio_atual(database, ctx)


@router.put("/configuracao", response_model=ConfiguracaoResposta)
async def editarConfiguracao(dados: Configuracao, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    condominio = condominio_atual(database, ctx)
    for campo, valor in dados.model_dump().items():
        setattr(condominio, campo, valor)
    salvar(database)
    database.refresh(condominio)
    return condominio


# =========================================================
# COTAS
# =========================================================

@router.get("/cotas", response_model=list[CotaResposta])
async def listarCotas(
    competencia: str | None = Query(default=None, description="AAAA-MM; vazio = todos os meses"),
    apartamento_id: uuid.UUID | None = None,
    database: Session = Depends(get_database),
    ctx: Contexto = Depends(exigir_financeiro),
):
    consulta = consulta_cotas(ctx.condominio_id)
    if competencia:
        try:
            consulta = consulta.where(Cota.competencia == ler_competencia(competencia))
        except ValueError as erro:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(erro))
    if apartamento_id:
        consulta = consulta.where(Cota.apartamento_id == apartamento_id)
    if not ctx.ve_financeiro_tudo:
        consulta = consulta.where(Cota.apartamento_id.in_(apartamentos_do_usuario(database, ctx)))

    cotas = database.scalars(
        consulta.order_by(Cota.competencia.desc(), Apartamento.bloco, Apartamento.numero, Cota.tipo, Cota.vencimento)
    ).all()
    condominio = condominio_atual(database, ctx)
    referencia = hoje()
    return [montar(cota, condominio, referencia) for cota in cotas]


@router.post("/cotas/gerar", response_model=ResultadoGeracao)
async def gerarCotas(dados: GerarCotas, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # cria a cota ORDINARIA do mês para cada apartamento ativo que ainda não tem
    condominio = condominio_atual(database, ctx)
    valor = dados.valor or condominio.valor_cota
    if not valor:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Defina o valor padrão da cota na configuração ou informe o valor")

    competencia = ler_competencia(dados.competencia)
    vencimento = vencimento_do_mes(competencia, dados.dia_vencimento or condominio.dia_vencimento)

    apartamentos = database.scalars(select(Apartamento.id).where(
        Apartamento.condominio_id == ctx.condominio_id, Apartamento.ativo.is_(True),
    )).all()
    ja_tem = set(database.scalars(select(Cota.apartamento_id).where(
        Cota.condominio_id == ctx.condominio_id, Cota.competencia == competencia, Cota.tipo == "ORDINARIA",
    )).all())

    novos = [a for a in apartamentos if a not in ja_tem]
    for apartamento_id in novos:
        database.add(Cota(
            condominio_id=ctx.condominio_id, apartamento_id=apartamento_id, competencia=competencia,
            tipo="ORDINARIA", valor=valor, vencimento=vencimento,
        ))
    salvar(database, "Algumas cotas deste mês já foram geradas. Atualize a página e tente de novo")
    return {"criadas": len(novos), "ja_existiam": len(apartamentos) - len(novos)}


@router.post("/cotas", response_model=CotaResposta, status_code=status.HTTP_201_CREATED)
async def criarCota(dados: CotaCriar, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    buscar_no_condominio(database, Apartamento, dados.apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    competencia = ler_competencia(dados.competencia)
    if dados.tipo == "ORDINARIA" and ordinaria_existe(database, dados.apartamento_id, competencia):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este apartamento já tem a cota ordinária deste mês")

    cota = Cota(
        condominio_id=ctx.condominio_id, apartamento_id=dados.apartamento_id, competencia=competencia,
        tipo=dados.tipo, descricao=texto(dados.descricao), valor=dados.valor, vencimento=dados.vencimento,
        observacao=texto(dados.observacao),
    )
    database.add(cota)
    salvar(database, "Este apartamento já tem a cota ordinária deste mês")
    return carregar(database, cota.id, ctx)


@router.put("/cotas/{cota_id}", response_model=CotaResposta)
async def editarCota(cota_id: uuid.UUID, dados: CotaEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    cota = cota_aberta(database, cota_id, ctx)
    cota.descricao = texto(dados.descricao)
    cota.valor = dados.valor
    cota.vencimento = dados.vencimento
    cota.observacao = texto(dados.observacao)
    salvar(database)
    return carregar(database, cota.id, ctx)


@router.post("/cotas/{cota_id}/pagamento", response_model=CotaResposta)
async def registrarPagamento(cota_id: uuid.UUID, dados: Pagamento, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    cota = cota_aberta(database, cota_id, ctx)
    if dados.data_pagamento > hoje():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A data do pagamento não pode ser futura")
    cota.status = "PAGA"
    cota.data_pagamento = dados.data_pagamento
    cota.valor_pago = dados.valor_pago
    cota.forma_pagamento = dados.forma_pagamento
    if texto(dados.observacao):
        cota.observacao = texto(dados.observacao)
    salvar(database)
    return carregar(database, cota.id, ctx)


@router.delete("/cotas/{cota_id}/pagamento", response_model=CotaResposta)
async def estornarPagamento(cota_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # desfaz uma baixa lançada por engano: a cota volta a ficar em aberto
    cota = buscar_no_condominio(database, Cota, cota_id, ctx.condominio_id, "Cota não encontrada")
    if cota.status != "PAGA":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta cota não está paga")
    cota.status = "ABERTA"
    cota.data_pagamento = None
    cota.valor_pago = None
    cota.forma_pagamento = None
    salvar(database)
    return carregar(database, cota.id, ctx)


@router.patch("/cotas/{cota_id}/cancelar", response_model=CotaResposta)
async def cancelarCota(cota_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    cota = cota_aberta(database, cota_id, ctx)
    cota.status = "CANCELADA"
    salvar(database)
    return carregar(database, cota.id, ctx)


@router.patch("/cotas/{cota_id}/reabrir", response_model=CotaResposta)
async def reabrirCota(cota_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    cota = buscar_no_condominio(database, Cota, cota_id, ctx.condominio_id, "Cota não encontrada")
    if cota.status != "CANCELADA":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Só é possível reabrir uma cota cancelada")
    cota.status = "ABERTA"
    salvar(database)
    return carregar(database, cota.id, ctx)


@router.delete("/cotas/{cota_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluirCota(cota_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # lançamento errado; cota paga precisa ter o pagamento estornado antes
    cota = buscar_no_condominio(database, Cota, cota_id, ctx.condominio_id, "Cota não encontrada")
    if cota.status == "PAGA":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estorne o pagamento antes de excluir a cota")
    database.delete(cota)
    salvar(database)
