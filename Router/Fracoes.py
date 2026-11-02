# ---------------------------------------------------------
# FRAÇÃO IDEAL
# ---------------------------------------------------------
# Quanto (%) cada apartamento representa no condomínio (rateio das
# despesas), com o nome do relatório da administradora
# ("Relatório de Unidades - Conferência de Frações").
# Os dados ficam no próprio apartamento (sql/fracao_ideal.sql); o
# apartamento também mostra a fração (Router/Apartamentos.py).
# Vê: ADM, síndico e conselheiro. Edita: ADM e síndico.
# ---------------------------------------------------------

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, get_contexto, negar
from App.models import Apartamento, PessoaApartamento

router = APIRouter(prefix="/fracoes")


class FracaoDados(BaseModel):
    fracao_ideal: Decimal | None = Field(default=None, ge=0, le=100)
    fracao_garagem: Decimal | None = Field(default=None, ge=0, le=100)
    fracao_extra: Decimal | None = Field(default=None, ge=0, le=100)
    nome_cobranca: str | None = Field(default=None, max_length=200)


class FracaoUnidade(FracaoDados):
    apartamento_id: uuid.UUID
    bloco: str
    numero: str
    proprietarios: list[str]        # do cadastro do sistema (para conferir com o nome do relatório)


class Fracoes(BaseModel):
    itens: list[FracaoUnidade]
    total_fracao: Decimal           # deve dar 100
    total_garagem: Decimal
    total_extra: Decimal
    sem_fracao: int                 # apartamentos ativos sem fração informada


CAMPOS = list(FracaoDados.model_fields)


def exigir_leitura(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    if not ctx.ve_financeiro_tudo:  # ADM, síndico e conselheiro
        negar()
    return ctx


def montar(a: Apartamento) -> dict:
    proprietarios = sorted(v.pessoa.nome for v in a.pessoas if v.ativo and v.tipo_relacao == "PROPRIETARIO")
    return {"apartamento_id": a.id, "bloco": a.bloco, "numero": a.numero, "proprietarios": proprietarios, **{c: getattr(a, c) for c in CAMPOS}}


@router.get("", response_model=Fracoes)
def listarFracoes(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    apartamentos = database.scalars(
        select(Apartamento).where(Apartamento.condominio_id == ctx.condominio_id, Apartamento.ativo.is_(True))
        .options(selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa))
    ).all()
    apartamentos = sorted(apartamentos, key=lambda a: (a.bloco, len(a.numero), a.numero))
    zero = Decimal("0")
    return {
        "itens": [montar(a) for a in apartamentos],
        "total_fracao": sum((a.fracao_ideal or zero for a in apartamentos), zero),
        "total_garagem": sum((a.fracao_garagem or zero for a in apartamentos), zero),
        "total_extra": sum((a.fracao_extra or zero for a in apartamentos), zero),
        "sem_fracao": sum(1 for a in apartamentos if a.fracao_ideal is None),
    }


@router.put("/{apartamento_id}", response_model=FracaoUnidade)
def editarFracao(apartamento_id: uuid.UUID, dados: FracaoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    a = database.scalar(
        select(Apartamento).where(Apartamento.id == apartamento_id, Apartamento.condominio_id == ctx.condominio_id)
        .options(selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa))
    )
    if not a:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartamento não encontrado")
    for campo in CAMPOS:
        valor = getattr(dados, campo)
        if isinstance(valor, str):
            valor = valor.strip() or None
        setattr(a, campo, valor)
    database.commit()
    database.refresh(a)
    return montar(a)
