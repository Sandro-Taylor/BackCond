# ---------------------------------------------------------
# REGRA ÚNICA DE SALDO (conta corrente e investimentos/CDB)
# ---------------------------------------------------------
# A gestão informa saldos lidos no banco (tabela saldos_informados).
# Saldo num dia:
#   - há saldo informado até o dia: último informado + eventos depois dele
#   - só há informados depois do dia: o primeiro informado - eventos entre
#     o dia e ele (calcula para trás)
#   - nenhum informado: soma dos eventos até o dia (começa em zero)
# Eventos: lançamentos do extrato (conta) ou aplicações/resgates/juros (CDB,
# investimentos_lancamentos; ver App/fundo_reserva.py).
# ---------------------------------------------------------

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from App.models import SaldoInformado

CONTA = "CONTA"
CDB = "CDB"
ZERO = Decimal("0")


def chave(agencia: str | None, conta: str | None) -> str:
    # "0004645-2" e "04645-2" são a mesma conta: só números, sem zeros à esquerda
    def numeros(v):
        return re.sub(r"\D", "", v or "").lstrip("0")
    return f"{numeros(agencia)}|{numeros(conta)}"


def informados(database: Session, condominio_id, tipo: str | None = None) -> list[SaldoInformado]:
    filtros = [SaldoInformado.condominio_id == condominio_id]
    if tipo:
        filtros.append(SaldoInformado.tipo == tipo)
    return list(database.scalars(select(SaldoInformado).where(*filtros).order_by(SaldoInformado.data)).all())


def por_conta(lista: list[SaldoInformado]) -> dict[str, list[SaldoInformado]]:
    agrupado: dict = {}
    for s in lista:
        agrupado.setdefault(chave(s.agencia, s.conta), []).append(s)
    return agrupado


def saldo_em(saldos: list, eventos: list[tuple[date, Decimal]], dia: date) -> Decimal:
    # saldos: informados da mesma conta, por data; eventos: (data, valor) com sinal
    anteriores = [s for s in saldos if s.data <= dia]
    if anteriores:
        base = anteriores[-1]
        return base.valor + sum((v for d, v in eventos if base.data < d <= dia), ZERO)
    if saldos:
        base = saldos[0]
        return base.valor - sum((v for d, v in eventos if dia < d <= base.data), ZERO)
    return sum((v for d, v in eventos if d <= dia), ZERO)
