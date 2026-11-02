# ---------------------------------------------------------
# FUNDO DE RESERVA = INVESTIMENTOS (CDB), digitados à mão
# ---------------------------------------------------------
# A conta corrente vem do extrato (.xlsx). O CDB não tem extrato no
# sistema: a gestão digita os lançamentos dele, copiados do app do banco
# (tabela investimentos_lancamentos):
#   SALDO ....... posição líquida numa data (valor do banco)
#   APLICACAO ... + entrou no CDB      RESGATE ... - saiu do CDB
#   RENDIMENTO .. + juro do período
# Um card por CONTA (agência + conta): os vários CDBs da conta (nome do
# produto) são somados. Posição da conta numa data = soma das posições
# dos produtos digitadas nessa data.
# Saldo da conta de investimento num dia (regra única, App/saldos.py):
#   última posição (SALDO) + aplicações + rendimentos - resgates depois dela.
# Mês com SALDO digitado = conferido (bate com o banco).
# Rendimento do mês = variação do saldo - aplicações + resgates
#   (inclui o juro digitado e a diferença que aparece ao digitar o SALDO).
# Fundo = soma dos investimentos.
# COMPARATIVO com o extrato: cada "APLICACAO CDB DI" (saída da conta) deve
# ter uma APLICACAO digitada no CDB, com o mesmo valor; "RESGATE CDB" idem.
# ---------------------------------------------------------

import calendar
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from App import saldos
from App.models import ExtratoImportado, InvestimentoLancamento, MovimentacaoBancaria

TEXTO_APLICACAO = "APLICACAO CDB DI"
TEXTO_RESGATE = "RESGATE CDB"
SALDO, APLICACAO, RESGATE, RENDIMENTO = "SALDO", "APLICACAO", "RESGATE", "RENDIMENTO"
SINAL = {APLICACAO: 1, RESGATE: -1, RENDIMENTO: 1}
ZERO = Decimal("0")
TOLERANCIA_DIAS = 5   # comparativo: o banco pode lançar no CDB alguns dias depois


def _normal(texto: str | None) -> str:
    texto = unicodedata.normalize("NFD", texto or "")
    return " ".join("".join(c for c in texto if unicodedata.category(c) != "Mn").upper().split())


def efeito_no_fundo(m: MovimentacaoBancaria) -> Decimal | None:
    # lançamento do extrato que vai para o CDB (+ aplicação, - resgate); None = não é do fundo
    texto = _normal(m.lancamento)
    if m.tipo == "SAIDA" and TEXTO_APLICACAO in texto:
        return -m.valor          # saída de 500 -> fundo +500
    if m.tipo == "ENTRADA" and TEXTO_RESGATE in texto:
        return -m.valor          # entrada de 500 -> fundo -500
    return None


def e_do_fundo(m: MovimentacaoBancaria) -> bool:
    return efeito_no_fundo(m) is not None


def chave_investimento(agencia: str | None, conta: str | None, nome: str | None = None) -> str:
    # o card é por conta; o nome do produto só detalha o lançamento
    return saldos.chave(agencia, conta)


def mesmo_produto(a: str | None, b: str | None) -> bool:
    return (_normal(a) or "CDB") == (_normal(b) or "CDB")


def lancamentos(database: Session, condominio_id) -> list[InvestimentoLancamento]:
    return list(database.scalars(
        select(InvestimentoLancamento).where(InvestimentoLancamento.condominio_id == condominio_id)
        .order_by(InvestimentoLancamento.data, InvestimentoLancamento.created_at)
    ).all())


@dataclass
class EstadoFundo:
    eventos: dict = field(default_factory=dict)    # chave -> [(data, valor com sinal)]
    posicoes: dict = field(default_factory=dict)   # chave -> [SALDO] (um por data: soma dos produtos)
    nomes: dict = field(default_factory=dict)      # chave -> (agencia, conta, nome)
    movimentos: dict = field(default_factory=dict) # chave -> [(data, tipo, valor)] aplicações/resgates/juros

    @property
    def chaves(self) -> list:
        return sorted(self.nomes)

    def datas(self) -> list[date]:
        return [d for lista in self.eventos.values() for d, _ in lista] + [p.data for lista in self.posicoes.values() for p in lista]


def montar(itens: list[InvestimentoLancamento]) -> EstadoFundo:
    est = EstadoFundo()
    por_data: dict = {}   # chave -> {data: {produto: valor}} (mesmo produto e data: vale o último digitado)
    for i in sorted(itens, key=lambda x: (x.data, x.created_at)):
        k = chave_investimento(i.agencia, i.conta)
        est.nomes.setdefault(k, (i.agencia, i.conta, "CDB"))
        est.eventos.setdefault(k, [])
        est.movimentos.setdefault(k, [])
        if i.tipo == SALDO:
            por_data.setdefault(k, {}).setdefault(i.data, {})[_normal(i.nome) or "CDB"] = i.valor
        elif i.tipo in SINAL:
            est.eventos[k].append((i.data, SINAL[i.tipo] * i.valor))
            est.movimentos[k].append((i.data, i.tipo, i.valor))
    for k in est.nomes:
        est.posicoes[k] = [SimpleNamespace(data=d, valor=sum(v.values(), ZERO)) for d, v in sorted(por_data.get(k, {}).items())]
    return est


def estado(database: Session, condominio_id) -> EstadoFundo:
    return montar(lancamentos(database, condominio_id))


def por_investimento(est: EstadoFundo) -> dict[str, EstadoFundo]:
    return {k: EstadoFundo(eventos={k: est.eventos[k]}, posicoes={k: est.posicoes[k]}, nomes={k: est.nomes[k]}, movimentos={k: est.movimentos[k]})
            for k in est.chaves}


def saldo_em(est: EstadoFundo, dia: date) -> Decimal | None:
    if not est.chaves:
        return None
    return sum((saldos.saldo_em(est.posicoes[k], est.eventos[k], dia) for k in est.chaves), ZERO)


def inicio(est: EstadoFundo) -> tuple[int, int] | None:
    datas = est.datas()
    if not datas:
        return None
    primeira = min(datas)
    return primeira.year, primeira.month


def serie_mensal(est: EstadoFundo, ano: int) -> list[dict]:
    # por mês do ano: aplicações, resgates, rendimento e saldo no fim do mês
    comeco = inicio(est)
    meses = []
    for mes in range(1, 13):
        if comeco is None or (ano, mes) < comeco:
            meses.append({"mes": mes, "entradas": ZERO, "saidas": ZERO, "rendimento": ZERO, "resultado": ZERO, "saldo_acumulado": None,
                          "tem_extrato": False, "conferido": False})
            continue
        primeiro_dia = date(ano, mes, 1)
        ultimo_dia = date(ano, mes, calendar.monthrange(ano, mes)[1])
        do_mes = [(t, v) for k in est.chaves for d, t, v in est.movimentos[k] if primeiro_dia <= d <= ultimo_dia]
        aplicado = sum((v for t, v in do_mes if t == APLICACAO), ZERO)
        resgatado = sum((v for t, v in do_mes if t == RESGATE), ZERO)
        juro = sum((v for t, v in do_mes if t == RENDIMENTO), ZERO)
        saldo = saldo_em(est, ultimo_dia)
        if (ano, mes) > comeco:
            # variação do saldo que não é aplicação nem resgate = rendimento
            rendimento = saldo - saldo_em(est, primeiro_dia - timedelta(days=1)) - aplicado + resgatado
        else:
            rendimento = juro
        posicao_no_mes = [any(primeiro_dia <= p.data <= ultimo_dia for p in est.posicoes[k]) for k in est.chaves]
        meses.append({"mes": mes, "entradas": aplicado, "saidas": -resgatado, "rendimento": rendimento,
                      "resultado": aplicado - resgatado + rendimento, "saldo_acumulado": saldo,
                      "tem_extrato": bool(do_mes) or any(posicao_no_mes), "conferido": all(posicao_no_mes)})
    return meses


def saldo_do_fundo(database: Session, condominio_id) -> Decimal:
    est = estado(database, condominio_id)
    return saldo_em(est, max(est.datas() + [date.today()])) or ZERO


# ---------------------------------------------------------
# COMPARATIVO: extrato da conta x lançamentos digitados no CDB
# ---------------------------------------------------------

def comparativo(database: Session, condominio_id, itens: list[InvestimentoLancamento] | None = None) -> dict:
    # liga cada aplicação/resgate do extrato a um lançamento digitado de mesmo tipo e valor
    # (data até TOLERANCIA_DIAS de diferença). O que sobra fica pendente dos dois lados.
    itens = lancamentos(database, condominio_id) if itens is None else itens
    do_extrato = []
    for m, agencia, conta in database.execute(
        select(MovimentacaoBancaria, ExtratoImportado.agencia, ExtratoImportado.conta)
        .join(ExtratoImportado, ExtratoImportado.id == MovimentacaoBancaria.extrato_id)
        .where(MovimentacaoBancaria.condominio_id == condominio_id)
        .order_by(MovimentacaoBancaria.data, MovimentacaoBancaria.ordem)
    ).all():
        efeito = efeito_no_fundo(m)
        if efeito is not None:
            do_extrato.append({"id": m.id, "data": m.data, "lancamento": m.lancamento, "agencia": agencia, "conta": conta,
                               "tipo": APLICACAO if efeito > 0 else RESGATE, "valor": abs(efeito), "lancamento_id": None})
    livres = [i for i in itens if i.tipo in (APLICACAO, RESGATE)]
    for e in do_extrato:
        par = min((i for i in livres if i.tipo == e["tipo"] and i.valor == e["valor"] and abs((i.data - e["data"]).days) <= TOLERANCIA_DIAS),
                  key=lambda i: abs((i.data - e["data"]).days), default=None)
        if par is not None:
            e["lancamento_id"] = par.id
            livres.remove(par)
    return {"extrato": do_extrato, "sem_extrato": [i.id for i in livres]}
