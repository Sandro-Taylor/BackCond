# ---------------------------------------------------------
# MOVIMENTAÇÕES BANCÁRIAS (extrato mensal)
# ---------------------------------------------------------
# Todo mês a gestão envia o extrato do banco (.xlsx, sempre no
# mesmo formato). Cada lançamento vira uma movimentação:
#   valor negativo = SAIDA | valor positivo = ENTRADA
# Enviar de novo o mesmo período da mesma conta: o sistema pede
# confirmação e substitui o extrato anterior (sem duplicar).
# Quem envia: ADM e síndico. Quem vê: ADM, síndico e conselheiro.
# Tabelas: sql/movimentacoes_bancarias.sql (criadas manualmente).
# Envio: corpo bruto da requisição (sem multipart), nome do
# arquivo no cabeçalho X-Nome-Arquivo.
# Resumos: /fluxo (fluxo de caixa mês a mês por conta, saldo
# acumulado), /favorecidos (saídas agrupadas por favorecido) e
# /previsao (estimativa dos próximos 6 meses pelos fixos dos últimos 12).
# Conta = agência + conta do extrato.
# SALDOS INFORMADOS (saldos_informados, regra em App/saldos.py): saldo da
#   conta corrente lido no banco -> + lançamentos do extrato depois da data.
# INVESTIMENTOS (investimentos_lancamentos, App/fundo_reserva.py): o CDB é
#   digitado à mão (posição, aplicação, resgate, rendimento) e comparado com
#   as aplicações/resgates do extrato. Fundo de reserva = soma dos CDBs.
# "SALDO ANTERIOR"/"SALDO TOTAL" do extrato não entram no saldo (só servem
# para conferir lançamento repetido na importação).
# Na conta, "APLICACAO CDB DI"/"RESGATE CDB" não são gasto nem receita.
# ---------------------------------------------------------

import calendar
import re
import uuid
from statistics import median
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from App.database import get_database
from App.dependencies import Contexto, exigir_gestao, get_contexto, negar
from App.extrato_xlsx import ErroExtrato, ler_extrato
from App import fundo_reserva as fundo
from App import saldos
from App.models import ExtratoImportado, InvestimentoLancamento, LancamentoFuturo, MovimentacaoBancaria, SaldoInformado

router = APIRouter(prefix="/movimentacoes")

LIMITE_ARQUIVO = 5 * 1024 * 1024


# =========================================================
# DADOS
# =========================================================

class MovimentacaoResposta(BaseModel):
    id: uuid.UUID
    data: date
    lancamento: str
    razao_social: str | None
    cpf_cnpj: str | None
    valor: Decimal
    tipo: str


class ListaMovimentacoes(BaseModel):
    itens: list[MovimentacaoResposta]
    total_entradas: Decimal
    total_saidas: Decimal       # negativo
    resultado: Decimal          # entradas + saídas


class MesDisponivel(BaseModel):
    mes: str                    # AAAA-MM
    quantidade: int


class ExtratoResposta(BaseModel):
    id: uuid.UUID
    nome_arquivo: str
    titular: str | None
    agencia: str | None
    conta: str | None
    periodo_inicio: date
    periodo_fim: date
    saldo_anterior: Decimal | None
    saldo_final: Decimal | None
    total_entradas: Decimal
    total_saidas: Decimal
    quantidade: int
    created_at: datetime


class ResultadoImportacao(BaseModel):
    extrato: ExtratoResposta
    substituiu: bool
    avisos: list[str]


# =========================================================
# AUXILIARES
# =========================================================

def exigir_leitura(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    if not ctx.ve_financeiro_tudo:  # ADM, síndico e conselheiro
        negar()
    return ctx


def intervalo_do_mes(mes: str) -> tuple[date, date]:
    try:
        ano, numero = (int(p) for p in mes.split("-"))
        inicio = date(ano, numero, 1)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mês inválido (use AAAA-MM)")
    fim = date(ano + (numero == 12), 1 if numero == 12 else numero + 1, 1)
    return inicio, fim


# =========================================================
# ROTAS
# =========================================================

@router.get("/", response_model=ListaMovimentacoes)
def listarMovimentacoes(
    mes: str | None = Query(None, description="AAAA-MM; vazio = todas"),
    tipo: Literal["ENTRADA", "SAIDA"] | None = None,
    database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura),
):
    filtros = [MovimentacaoBancaria.condominio_id == ctx.condominio_id]
    if mes:
        inicio, fim = intervalo_do_mes(mes)
        filtros += [MovimentacaoBancaria.data >= inicio, MovimentacaoBancaria.data < fim]
    if tipo:
        filtros.append(MovimentacaoBancaria.tipo == tipo)

    itens = database.scalars(
        select(MovimentacaoBancaria).where(*filtros)
        .order_by(MovimentacaoBancaria.data.desc(), MovimentacaoBancaria.extrato_id, MovimentacaoBancaria.ordem.desc())
    ).all()
    entradas = sum((m.valor for m in itens if m.tipo == "ENTRADA"), Decimal("0"))
    saidas = sum((m.valor for m in itens if m.tipo == "SAIDA"), Decimal("0"))
    return {"itens": itens, "total_entradas": entradas, "total_saidas": saidas, "resultado": entradas + saidas}


@router.get("/meses", response_model=list[MesDisponivel])
def mesesDisponiveis(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    mes = func.to_char(MovimentacaoBancaria.data, "YYYY-MM")
    linhas = database.execute(
        select(mes, func.count()).where(MovimentacaoBancaria.condominio_id == ctx.condominio_id).group_by(mes).order_by(mes.desc())
    ).all()
    return [{"mes": m, "quantidade": q} for m, q in linhas]


@router.get("/extratos", response_model=list[ExtratoResposta])
def listarExtratos(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    return database.scalars(
        select(ExtratoImportado).where(ExtratoImportado.condominio_id == ctx.condominio_id).order_by(ExtratoImportado.periodo_inicio.desc())
    ).all()


@router.post("/importar", response_model=ResultadoImportacao, status_code=status.HTTP_201_CREATED)
async def importarExtrato(
    request: Request,
    substituir: bool = False,
    database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao),
):
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum arquivo enviado")
    if len(conteudo) > LIMITE_ARQUIVO:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Arquivo maior que 5 MB")
    nome_arquivo = (unquote(request.headers.get("x-nome-arquivo", "")).strip() or "extrato.xlsx")[:255]

    try:
        extrato = ler_extrato(conteudo)
    except ErroExtrato as erro:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(erro))

    # mesmo período da mesma conta já enviado: só substitui se confirmado
    anterior = database.scalar(select(ExtratoImportado).where(
        ExtratoImportado.condominio_id == ctx.condominio_id,
        ExtratoImportado.agencia.is_not_distinct_from(extrato.agencia),
        ExtratoImportado.conta.is_not_distinct_from(extrato.conta),
        ExtratoImportado.periodo_inicio == extrato.periodo_inicio,
        ExtratoImportado.periodo_fim == extrato.periodo_fim,
    ))
    if anterior and not substituir:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"O extrato de {extrato.periodo_inicio:%d/%m/%Y} a {extrato.periodo_fim:%d/%m/%Y} já foi enviado em {anterior.created_at:%d/%m/%Y}. Deseja substituir?",
        )

    avisos = list(extrato.avisos)
    # conta diferente das enviadas antes: avisa (pode ser extrato de outro condomínio)
    outras = database.execute(
        select(ExtratoImportado.agencia, ExtratoImportado.conta).where(ExtratoImportado.condominio_id == ctx.condominio_id).distinct()
    ).all()
    if outras and (extrato.agencia, extrato.conta) not in outras:
        avisos.insert(0, f"Atenção: a conta deste extrato (agência {extrato.agencia}, conta {extrato.conta}) é diferente das enviadas antes para este condomínio.")

    # períodos que se sobrepõem a outro extrato da mesma conta (lançamentos em dobro)
    sobreposto = database.scalar(select(ExtratoImportado).where(
        ExtratoImportado.condominio_id == ctx.condominio_id,
        ExtratoImportado.agencia.is_not_distinct_from(extrato.agencia),
        ExtratoImportado.conta.is_not_distinct_from(extrato.conta),
        ExtratoImportado.periodo_inicio <= extrato.periodo_fim,
        ExtratoImportado.periodo_fim >= extrato.periodo_inicio,
        *( [ExtratoImportado.id != anterior.id] if anterior else [] ),
    ))
    if sobreposto:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Este período se sobrepõe ao extrato de {sobreposto.periodo_inicio:%d/%m/%Y} a {sobreposto.periodo_fim:%d/%m/%Y} já enviado. Os lançamentos ficariam em dobro.",
        )

    try:
        if anterior:
            database.delete(anterior)  # apaga também as movimentações dele (CASCADE)
            database.flush()
        entradas = sum((l.valor for l in extrato.lancamentos if l.tipo == "ENTRADA"), Decimal("0"))
        saidas = sum((l.valor for l in extrato.lancamentos if l.tipo == "SAIDA"), Decimal("0"))
        novo = ExtratoImportado(
            condominio_id=ctx.condominio_id, nome_arquivo=nome_arquivo, titular=extrato.titular,
            agencia=extrato.agencia, conta=extrato.conta,
            periodo_inicio=extrato.periodo_inicio, periodo_fim=extrato.periodo_fim,
            saldo_anterior=extrato.saldo_anterior, saldo_final=extrato.saldo_final,
            total_entradas=entradas, total_saidas=saidas, quantidade=len(extrato.lancamentos),
            enviado_por_user_id=ctx.usuario.id,
        )
        novo.movimentacoes = [MovimentacaoBancaria(
            condominio_id=ctx.condominio_id, data=l.data, lancamento=l.lancamento, razao_social=l.razao_social,
            cpf_cnpj=l.cpf_cnpj, valor=l.valor, tipo=l.tipo, ordem=l.ordem,
        ) for l in extrato.lancamentos]
        database.add(novo)
        database.commit()
    except Exception:
        database.rollback()
        raise
    database.refresh(novo)
    return {"extrato": novo, "substituiu": anterior is not None, "avisos": avisos}


@router.delete("/extratos/{extrato_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirExtrato(extrato_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # remove o extrato e todas as movimentações que vieram dele
    extrato = database.scalar(select(ExtratoImportado).where(ExtratoImportado.id == extrato_id, ExtratoImportado.condominio_id == ctx.condominio_id))
    if not extrato:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extrato não encontrado")
    database.delete(extrato)
    database.commit()


# =========================================================
# RESUMOS: FLUXO DE CAIXA E SALDOS
# =========================================================

class MesFluxo(BaseModel):
    mes: int                         # 1 a 12
    entradas: Decimal
    saidas: Decimal                  # negativo
    rendimento: Decimal | None = None  # só no fundo de reserva
    resultado: Decimal               # entradas + saídas (+ rendimento)
    saldo_acumulado: Decimal | None  # saldo no fim do mês
    tem_extrato: bool
    conferido: bool = False          # CDB: saldo do fim do mês informado (igual ao banco)


class ContaFluxo(BaseModel):
    chave: str
    agencia: str | None
    conta: str | None
    titular: str | None
    saldo_atual: Decimal | None
    saldo_em: date | None
    saldo_inicial: Decimal | None = None      # último saldo informado (conta) / última posição (fundo)
    data_saldo_inicial: date | None = None
    saldo_configurado: bool = True            # False = nenhum saldo informado ainda
    meses: list[MesFluxo]


class FluxoCaixa(BaseModel):
    ano: int
    anos: list[int]
    contas: list[ContaFluxo]
    total: ContaFluxo              # só saldo em conta
    fundo: ContaFluxo | None       # fundo de reserva = soma dos CDBs (entradas = aplicações; saídas = resgates)
    fundos: list[ContaFluxo] = []  # um por CDB (agência|conta)
    fundo_configurado: bool        # algum saldo de CDB informado


def chave_conta(agencia: str | None, conta: str | None) -> str:
    # chave da conta na tela (como veio no extrato)
    return f"{agencia or ''}|{conta or ''}"


def fim_do_mes(ano: int, mes: int) -> date:
    return date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1) - timedelta(days=1)


@router.get("/fluxo", response_model=FluxoCaixa)
def fluxoCaixa(ano: int | None = None, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    zero = Decimal("0")
    extratos = database.scalars(
        select(ExtratoImportado).where(ExtratoImportado.condominio_id == ctx.condominio_id).order_by(ExtratoImportado.periodo_fim)
    ).all()

    # entradas e saídas por conta e dia
    somas_dia = database.execute(
        select(
            ExtratoImportado.agencia, ExtratoImportado.conta, MovimentacaoBancaria.data,
            func.coalesce(func.sum(case((MovimentacaoBancaria.tipo == "ENTRADA", MovimentacaoBancaria.valor), else_=0)), 0),
            func.coalesce(func.sum(case((MovimentacaoBancaria.tipo == "SAIDA", MovimentacaoBancaria.valor), else_=0)), 0),
        )
        .join(ExtratoImportado, ExtratoImportado.id == MovimentacaoBancaria.extrato_id)
        .where(MovimentacaoBancaria.condominio_id == ctx.condominio_id)
        .group_by(ExtratoImportado.agencia, ExtratoImportado.conta, MovimentacaoBancaria.data)
    ).all()
    informados = saldos.por_conta(saldos.informados(database, ctx.condominio_id, saldos.CONTA))

    anos = sorted({d.year for _, _, d, _, _ in somas_dia} | {e.periodo_fim.year for e in extratos}, reverse=True)
    ano = ano or (anos[0] if anos else date.today().year)

    contas: dict[str, dict] = {}
    for e in extratos:
        conta = contas.setdefault(chave_conta(e.agencia, e.conta), {"agencia": e.agencia, "conta": e.conta, "titular": e.titular, "extratos": [], "mes": {}, "eventos": []})
        conta["extratos"].append(e)
        conta["titular"] = e.titular or conta["titular"]
    for agencia, numero, d, entradas, saidas in somas_dia:
        conta = contas.setdefault(chave_conta(agencia, numero), {"agencia": agencia, "conta": numero, "titular": None, "extratos": [], "mes": {}, "eventos": []})
        e0, s0 = conta["mes"].get((d.year, d.month), (zero, zero))
        conta["mes"][(d.year, d.month)] = (e0 + Decimal(entradas), s0 + Decimal(saidas))
        conta["eventos"].append((d, Decimal(entradas) + Decimal(saidas)))

    resultado_contas = []
    for chave, conta in sorted(contas.items()):
        lista = informados.get(saldos.chave(conta["agencia"], conta["conta"]), [])
        datas = [d for d, _ in conta["eventos"]] + [s.data for s in lista] + [e.periodo_inicio for e in conta["extratos"]]
        primeiro = min(datas) if datas else None
        meses_extrato = set()
        for e in conta["extratos"]:
            a, m = e.periodo_inicio.year, e.periodo_inicio.month
            while (a, m) <= (e.periodo_fim.year, e.periodo_fim.month):
                meses_extrato.add((a, m))
                a, m = (a + 1, 1) if m == 12 else (a, m + 1)

        meses = []
        for m in range(1, 13):
            entradas, saidas = conta["mes"].get((ano, m), (zero, zero))
            antes = primeiro is None or (ano, m) < (primeiro.year, primeiro.month)
            meses.append({
                "mes": m, "entradas": entradas, "saidas": saidas, "resultado": entradas + saidas,
                "saldo_acumulado": None if antes else saldos.saldo_em(lista, conta["eventos"], fim_do_mes(ano, m)),
                "tem_extrato": (ano, m) in meses_extrato,
            })
        ultimo = conta["extratos"][-1] if conta["extratos"] else None
        hoje = max([date.today()] + datas)
        resultado_contas.append({
            "chave": chave, "agencia": conta["agencia"], "conta": conta["conta"], "titular": conta["titular"],
            "saldo_atual": saldos.saldo_em(lista, conta["eventos"], hoje), "saldo_em": ultimo.periodo_fim if ultimo else None,
            "saldo_inicial": lista[-1].valor if lista else None, "data_saldo_inicial": lista[-1].data if lista else None,
            "saldo_configurado": bool(lista), "meses": meses,
        })

    # total de todas as contas
    total_meses = []
    for i in range(12):
        da_linha = [c["meses"][i] for c in resultado_contas]
        acumulados = [x["saldo_acumulado"] for x in da_linha if x["saldo_acumulado"] is not None]
        entradas = sum((x["entradas"] for x in da_linha), zero)
        saidas = sum((x["saidas"] for x in da_linha), zero)
        total_meses.append({"mes": i + 1, "entradas": entradas, "saidas": saidas, "resultado": entradas + saidas,
                            "saldo_acumulado": sum(acumulados, zero) if acumulados else None, "tem_extrato": any(x["tem_extrato"] for x in da_linha)})
    saldos_atuais = [c["saldo_atual"] for c in resultado_contas if c["saldo_atual"] is not None]
    datas_total = [c["saldo_em"] for c in resultado_contas if c["saldo_em"]]
    total = {"chave": "TOTAL", "agencia": None, "conta": None, "titular": "Total", "saldo_atual": sum(saldos_atuais, zero) if saldos_atuais else None,
             "saldo_em": max(datas_total) if datas_total else None, "meses": total_meses}

    est = fundo.estado(database, ctx.condominio_id)
    return {"ano": ano, "anos": anos or [ano], "contas": resultado_contas, "total": total,
            "fundo": fluxo_do_fundo(est, ano), "fundo_configurado": any(est.posicoes.values()),
            "fundos": fluxos_dos_investimentos(est, ano)}


def fluxos_dos_investimentos(est: "fundo.EstadoFundo", ano: int) -> list[dict]:
    return [f for k, e in fundo.por_investimento(est).items() if (f := fluxo_do_fundo(e, ano, k))]


def fluxo_do_fundo(est: "fundo.EstadoFundo", ano: int, chave: str | None = None) -> dict | None:
    # fundo de reserva (ou um CDB, com chave) mês a mês: aplicações (entrada), resgates (saída), rendimento e saldo
    if fundo.inicio(est) is None:
        return None
    agencia, conta, _ = (est.nomes.get(chave) if chave else None) or (None, None, None)
    zero = Decimal("0")
    datas = est.datas()
    # "última posição" exibida: soma da posição mais recente de cada investimento
    ultimas = [lista[-1] for lista in est.posicoes.values() if lista]
    return {
        "chave": f"CDB|{chave}" if chave else "FUNDO", "agencia": agencia, "conta": conta,
        "titular": "Investimentos (CDB)" if chave else "Fundo de reserva",
        "saldo_atual": fundo.saldo_em(est, max(datas + [date.today()])), "saldo_em": max(datas) if datas else None,
        "saldo_inicial": sum((p.valor for p in ultimas), zero) if ultimas else None,
        "data_saldo_inicial": max((p.data for p in ultimas), default=None),
        "saldo_configurado": bool(ultimas), "meses": fundo.serie_mensal(est, ano),
    }


# =========================================================
# SALDOS INFORMADOS (conta corrente e CDB, digitados pela gestão)
# =========================================================

class SaldoInformadoDados(BaseModel):
    tipo: Literal["CONTA", "CDB"]
    agencia: str
    conta: str
    descricao: str | None = None
    data: date
    valor: Decimal


class SaldoInformadoResposta(SaldoInformadoDados):
    id: uuid.UUID
    created_at: datetime


class SaldosInformadosResposta(BaseModel):
    itens: list[SaldoInformadoResposta]       # mais recentes primeiro
    fundo_atual: Decimal                      # saldo do fundo de reserva hoje


@router.get("/saldos-informados", response_model=SaldosInformadosResposta)
def listarSaldosInformados(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    itens = sorted(saldos.informados(database, ctx.condominio_id), key=lambda s: (s.data, s.created_at), reverse=True)
    return {"itens": itens, "fundo_atual": fundo.saldo_do_fundo(database, ctx.condominio_id)}


@router.post("/saldos-informados", response_model=SaldoInformadoResposta, status_code=status.HTTP_201_CREATED)
def informarSaldo(dados: SaldoInformadoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # mesma conta, tipo e data: substitui o valor
    agencia, conta = dados.agencia.strip(), dados.conta.strip()
    if not agencia or not conta:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe agência e conta")
    if dados.tipo == saldos.CDB:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O CDB agora é lançado na aba Investimentos")
    chave = saldos.chave(agencia, conta)
    linha = next((s for s in saldos.informados(database, ctx.condominio_id, dados.tipo)
                  if saldos.chave(s.agencia, s.conta) == chave and s.data == dados.data), None)
    linha = linha or SaldoInformado(condominio_id=ctx.condominio_id, tipo=dados.tipo, agencia=agencia, conta=conta, data=dados.data)
    linha.descricao = (dados.descricao or "").strip()[:100] or None
    linha.valor = dados.valor
    linha.informado_por_user_id = ctx.usuario.id
    database.add(linha)
    database.commit()
    database.refresh(linha)
    return linha


@router.delete("/saldos-informados/{saldo_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirSaldoInformado(saldo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    linha = database.scalar(select(SaldoInformado).where(SaldoInformado.id == saldo_id, SaldoInformado.condominio_id == ctx.condominio_id))
    if not linha:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saldo não encontrado")
    database.delete(linha)
    database.commit()


# =========================================================
# INVESTIMENTOS (CDB do fundo de reserva), digitados à mão
# =========================================================

TipoInvestimento = Literal["SALDO", "APLICACAO", "RESGATE", "RENDIMENTO"]


class InvestimentoDados(BaseModel):
    agencia: str
    conta: str
    nome: str = "CDB"
    data: date
    tipo: TipoInvestimento
    valor: Decimal                    # SALDO: saldo líquido
    valor_bruto: Decimal | None = None
    imposto: Decimal | None = None    # IR + IOF
    observacao: str | None = None


class InvestimentoResposta(InvestimentoDados):
    id: uuid.UUID
    chave: str                        # conta do investimento (agência|conta); nome = produto
    created_at: datetime


class ItemComparativo(BaseModel):
    id: uuid.UUID                     # movimentação do extrato
    data: date
    lancamento: str
    agencia: str | None
    conta: str | None
    tipo: str                         # APLICACAO | RESGATE
    valor: Decimal                    # positivo
    lancamento_id: uuid.UUID | None   # lançamento digitado que bate (None = falta lançar no CDB)


class Comparativo(BaseModel):
    extrato: list[ItemComparativo]
    sem_extrato: list[uuid.UUID]      # digitados no CDB sem aplicação/resgate no extrato


class Investimentos(BaseModel):
    ano: int
    anos: list[int]
    total: ContaFluxo | None          # fundo de reserva (soma)
    investimentos: list[ContaFluxo]   # um por conta de investimento (produtos somados)
    lancamentos: list[InvestimentoResposta]   # mais recentes primeiro
    comparativo: Comparativo


def resposta_investimento(i: InvestimentoLancamento) -> dict:
    return {"id": i.id, "chave": fundo.chave_investimento(i.agencia, i.conta, i.nome), "agencia": i.agencia, "conta": i.conta, "nome": i.nome,
            "data": i.data, "tipo": i.tipo, "valor": i.valor, "valor_bruto": i.valor_bruto, "imposto": i.imposto,
            "observacao": i.observacao, "created_at": i.created_at}


@router.get("/investimentos", response_model=Investimentos)
def listarInvestimentos(ano: int | None = None, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    itens = fundo.lancamentos(database, ctx.condominio_id)
    est = fundo.montar(itens)
    comparativo = fundo.comparativo(database, ctx.condominio_id, itens)
    anos = sorted({i.data.year for i in itens} | {e["data"].year for e in comparativo["extrato"]}, reverse=True)
    ano = ano or (anos[0] if anos else date.today().year)
    return {
        "ano": ano, "anos": anos or [ano], "total": fluxo_do_fundo(est, ano),
        "investimentos": fluxos_dos_investimentos(est, ano),
        "lancamentos": [resposta_investimento(i) for i in sorted(itens, key=lambda i: (i.data, i.created_at), reverse=True)],
        "comparativo": comparativo,
    }


@router.post("/investimentos/lancamentos", response_model=InvestimentoResposta, status_code=status.HTTP_201_CREATED)
def lancarInvestimento(dados: InvestimentoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    agencia, conta, nome = dados.agencia.strip(), dados.conta.strip(), (dados.nome or "").strip()[:60] or "CDB"
    if not agencia or not conta:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe agência e conta do investimento")
    if dados.valor < 0 or (dados.tipo != "SALDO" and dados.valor == 0):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe um valor positivo")
    # conta/produto já cadastrados com outra grafia (ex.: 04645-2 x 4645-2): usa a grafia existente
    chave = fundo.chave_investimento(agencia, conta)
    da_conta = [i for i in fundo.lancamentos(database, ctx.condominio_id) if fundo.chave_investimento(i.agencia, i.conta) == chave]
    if da_conta:
        agencia, conta = da_conta[0].agencia, da_conta[0].conta
        nome = next((i.nome for i in da_conta if fundo.mesmo_produto(i.nome, nome)), nome)
    linha = InvestimentoLancamento(
        condominio_id=ctx.condominio_id, agencia=agencia, conta=conta, nome=nome, data=dados.data, tipo=dados.tipo, valor=dados.valor,
        valor_bruto=dados.valor_bruto if dados.tipo == "SALDO" else None, imposto=dados.imposto if dados.tipo == "SALDO" else None,
        observacao=(dados.observacao or "").strip()[:200] or None, informado_por_user_id=ctx.usuario.id,
    )
    database.add(linha)
    database.commit()
    database.refresh(linha)
    return resposta_investimento(linha)


@router.delete("/investimentos/lancamentos/{lancamento_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirLancamentoInvestimento(lancamento_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    linha = database.scalar(select(InvestimentoLancamento).where(InvestimentoLancamento.id == lancamento_id, InvestimentoLancamento.condominio_id == ctx.condominio_id))
    if not linha:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento não encontrado")
    database.delete(linha)
    database.commit()


# =========================================================
# LANÇAMENTOS FUTUROS (parcelas combinadas, entram na previsão)
# =========================================================

class FuturoDados(BaseModel):
    descricao: str
    favorecido: str | None = None
    tipo: Literal["ENTRADA", "SAIDA"] = "SAIDA"
    valor_parcela: Decimal            # positivo
    parcelas: int = 1                 # 1 a 60, uma por mês a partir da primeira data
    primeira_data: date


class FuturoResposta(BaseModel):
    id: uuid.UUID
    grupo_id: uuid.UUID
    descricao: str
    favorecido: str | None
    tipo: str
    valor: Decimal
    data: date
    parcela: int
    total_parcelas: int
    na_previsao: bool                 # data depois do último extrato (antes disso já deve estar no extrato)


def mais_meses(dia: date, meses: int) -> date:
    # mesmo dia, N meses depois (dia 31 em mês curto vira o último dia do mês)
    total = dia.month - 1 + meses
    ano, mes = dia.year + total // 12, total % 12 + 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def ultimo_extrato(database: Session, condominio_id) -> date | None:
    return database.scalar(select(func.max(ExtratoImportado.periodo_fim)).where(ExtratoImportado.condominio_id == condominio_id))


@router.get("/futuros", response_model=list[FuturoResposta])
def listarFuturos(database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura)):
    limite = ultimo_extrato(database, ctx.condominio_id)
    itens = database.scalars(select(LancamentoFuturo).where(LancamentoFuturo.condominio_id == ctx.condominio_id)
                             .order_by(LancamentoFuturo.data, LancamentoFuturo.parcela)).all()
    return [{"id": f.id, "grupo_id": f.grupo_id, "descricao": f.descricao, "favorecido": f.favorecido, "tipo": f.tipo, "valor": f.valor,
             "data": f.data, "parcela": f.parcela, "total_parcelas": f.total_parcelas, "na_previsao": limite is None or f.data > limite} for f in itens]


@router.post("/futuros", status_code=status.HTTP_201_CREATED)
def criarFuturo(dados: FuturoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    descricao = dados.descricao.strip()[:200]
    if not descricao:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe a descrição")
    if dados.valor_parcela <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o valor da parcela")
    if not 1 <= dados.parcelas <= 60:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parcelas: de 1 a 60")
    grupo = uuid.uuid4()
    for n in range(dados.parcelas):
        database.add(LancamentoFuturo(
            condominio_id=ctx.condominio_id, grupo_id=grupo, descricao=descricao, favorecido=(dados.favorecido or "").strip()[:200] or None,
            tipo=dados.tipo, valor=dados.valor_parcela, data=mais_meses(dados.primeira_data, n), parcela=n + 1, total_parcelas=dados.parcelas,
            criado_por_user_id=ctx.usuario.id,
        ))
    database.commit()
    return {"grupo_id": grupo, "parcelas": dados.parcelas}


@router.delete("/futuros/{futuro_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirFuturo(futuro_id: uuid.UUID, todas: bool = False, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # todas=true: apaga todas as parcelas do mesmo acordo
    linha = database.scalar(select(LancamentoFuturo).where(LancamentoFuturo.id == futuro_id, LancamentoFuturo.condominio_id == ctx.condominio_id))
    if not linha:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento não encontrado")
    alvo = database.scalars(select(LancamentoFuturo).where(LancamentoFuturo.grupo_id == linha.grupo_id, LancamentoFuturo.condominio_id == ctx.condominio_id)).all() if todas else [linha]
    for f in alvo:
        database.delete(f)
    database.commit()


# =========================================================
# RESUMOS: SAÍDAS POR FAVORECIDO
# =========================================================

class Favorecido(BaseModel):
    favorecido: str
    cpf_cnpj: str | None
    quantidade: int
    total: Decimal               # negativo (saídas)
    ultimo_pagamento: date


@router.get("/favorecidos", response_model=list[Favorecido])
def saidasPorFavorecido(
    mes: str | None = Query(None, description="AAAA-MM"), ano: int | None = None,
    database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura),
):
    # sem razão social (ex.: contas de consumo, tarifas): agrupa pelo texto do lançamento
    nome = func.coalesce(func.nullif(MovimentacaoBancaria.razao_social, ""), MovimentacaoBancaria.lancamento)
    filtros = [
        MovimentacaoBancaria.condominio_id == ctx.condominio_id, MovimentacaoBancaria.tipo == "SAIDA",
        # aplicação no fundo de reserva não é despesa
        func.upper(MovimentacaoBancaria.lancamento).not_like(f"%{fundo.TEXTO_APLICACAO}%"),
    ]
    if mes:
        inicio, fim = intervalo_do_mes(mes)
        filtros += [MovimentacaoBancaria.data >= inicio, MovimentacaoBancaria.data < fim]
    elif ano:
        filtros += [MovimentacaoBancaria.data >= date(ano, 1, 1), MovimentacaoBancaria.data < date(ano + 1, 1, 1)]
    linhas = database.execute(
        select(nome, func.max(MovimentacaoBancaria.cpf_cnpj), func.count(), func.sum(MovimentacaoBancaria.valor), func.max(MovimentacaoBancaria.data))
        .where(*filtros).group_by(nome).order_by(func.sum(MovimentacaoBancaria.valor))
    ).all()
    return [{"favorecido": n, "cpf_cnpj": d, "quantidade": q, "total": t, "ultimo_pagamento": u} for n, d, q, t, u in linhas]


# =========================================================
# PREVISÃO DOS PRÓXIMOS MESES
# =========================================================
# Base: os últimos 12 meses com extrato (até o último mês enviado).
# FIXO: lançamento (mesmo favorecido/descrição e mesmo tipo) que aparece
#   em pelo menos 60% dos meses analisados (mínimo 2 meses; com 1 mês
#   de histórico, tudo daquele mês vira base, com confiança BAIXA). Valor
#   previsto = mediana dos totais mensais (meses fora do normal pesam pouco).
# EVENTUAL: o resto; entra na previsão como média mensal (opcional na tela).
# Saldo atual: regra única (último saldo informado + lançamentos depois dele).
# FUTUROS (lancamentos_futuros): parcelas combinadas que ainda não estão no
#   extrato; entram no mês da data se ela for depois do último extrato.
# Aplicação no CDB: só muda o dinheiro de lugar (conta -> fundo); o
#   disponível (conta + fundo) não muda. Sem contar o fundo, ela reduz a conta.

class ItemPrevisao(BaseModel):
    nome: str
    tipo: str                    # ENTRADA ou SAIDA
    meses_presente: int
    valor_mensal: Decimal        # mediana por mês (saída negativa)
    ultimo_valor: Decimal
    ultima_data: date


class MesPrevisao(BaseModel):
    mes: str                     # AAAA-MM
    entradas_fixas: Decimal
    saidas_fixas: Decimal        # negativo (sem as aplicações no fundo)
    futuros_entradas: Decimal    # lançamentos futuros do mês
    futuros_saidas: Decimal      # negativo
    aplicacao_fundo: Decimal     # transferência conta -> fundo (negativo na conta)
    saidas_eventuais: Decimal    # negativo (média)
    entradas_eventuais: Decimal  # média (não entra no saldo previsto: conservador)
    saldo_sem_eventuais: Decimal # saldo em conta
    saldo_previsto: Decimal      # saldo em conta com a média de saídas eventuais
    saldo_fundo: Decimal         # fundo de reserva previsto


class Previsao(BaseModel):
    base_inicio: str | None      # AAAA-MM
    base_fim: str | None
    meses_analisados: int
    confianca: str               # BAIXA (<3 meses), MEDIA (<6), ALTA
    saldo_atual: Decimal         # saldo em conta
    saldo_em: date | None
    fundo_atual: Decimal         # fundo de reserva hoje
    aplicacao_mensal: Decimal    # aplicação fixa no fundo por mês (0 se não for recorrente)
    contas: list[str]            # chaves das contas consideradas
    fixos: list[ItemPrevisao]
    eventuais_maiores: list[ItemPrevisao]
    meses: list[MesPrevisao]


def nome_do_lancamento(m: MovimentacaoBancaria) -> str:
    # agrupa o mesmo favorecido/serviço: tira datas, códigos e números longos
    if m.razao_social:
        return m.razao_social.strip().upper()
    texto = re.sub(r"\b\d{2}/\d{2}(/\d{2,4})?S?\b", " ", m.lancamento.upper())
    texto = re.sub(r"\b\d{4,}\b", " ", texto)
    return re.sub(r"\s+", " ", texto).strip() or m.lancamento.upper()


def proximo_mes(ano: int, mes: int) -> tuple[int, int]:
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def futuros_por_mes(database: Session, condominio_id, depois_de: date) -> dict:
    # (ano, mês) -> (entradas, saídas negativas) dos lançamentos futuros depois do último extrato
    zero = Decimal("0")
    por_mes: dict = {}
    for f in database.scalars(select(LancamentoFuturo).where(LancamentoFuturo.condominio_id == condominio_id, LancamentoFuturo.data > depois_de)).all():
        e, s = por_mes.get((f.data.year, f.data.month), (zero, zero))
        por_mes[(f.data.year, f.data.month)] = (e + f.valor, s) if f.tipo == "ENTRADA" else (e, s - f.valor)
    return por_mes


@router.get("/previsao", response_model=Previsao)
def previsao(
    meses: int = Query(6, ge=1, le=12),
    contas: list[str] | None = Query(None, description="chaves 'agência|conta'; vazio = todas"),
    database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_leitura),
):
    zero = Decimal("0")
    extratos = database.scalars(
        select(ExtratoImportado).where(ExtratoImportado.condominio_id == ctx.condominio_id).order_by(ExtratoImportado.periodo_fim)
    ).all()
    escolhidas = set(contas or [chave_conta(e.agencia, e.conta) for e in extratos])
    extratos = [e for e in extratos if chave_conta(e.agencia, e.conta) in escolhidas]

    # saldo atual de cada conta: regra única (último saldo informado + lançamentos depois)
    informados = saldos.por_conta(saldos.informados(database, ctx.condominio_id, saldos.CONTA))
    saldo_atual = zero
    for chave in {chave_conta(e.agencia, e.conta) for e in extratos}:
        e0 = next(e for e in extratos if chave_conta(e.agencia, e.conta) == chave)
        ids_conta = [e.id for e in extratos if chave_conta(e.agencia, e.conta) == chave]
        eventos = [(d, Decimal(v)) for d, v in database.execute(
            select(MovimentacaoBancaria.data, func.sum(MovimentacaoBancaria.valor))
            .where(MovimentacaoBancaria.extrato_id.in_(ids_conta)).group_by(MovimentacaoBancaria.data)
        ).all()]
        lista = informados.get(saldos.chave(e0.agencia, e0.conta), [])
        saldo_atual += saldos.saldo_em(lista, eventos, max([date.today()] + [d for d, _ in eventos] + [s.data for s in lista]))
    saldo_em = max((e.periodo_fim for e in extratos), default=None)

    fundo_atual = fundo.saldo_do_fundo(database, ctx.condominio_id)
    vazio = {"base_inicio": None, "base_fim": None, "meses_analisados": 0, "confianca": "BAIXA", "saldo_atual": saldo_atual,
             "saldo_em": saldo_em, "fundo_atual": fundo_atual, "aplicacao_mensal": zero,
             "contas": sorted(escolhidas), "fixos": [], "eventuais_maiores": [], "meses": []}
    if not extratos:
        return vazio

    # janela: 12 meses até o último mês com extrato
    fim = max(e.periodo_fim for e in extratos)
    ano_ini, mes_ini = fim.year, fim.month
    for _ in range(11):
        ano_ini, mes_ini = (ano_ini - 1, 12) if mes_ini == 1 else (ano_ini, mes_ini - 1)
    inicio = date(ano_ini, mes_ini, 1)
    ids = [e.id for e in extratos]
    movimentos = database.scalars(
        select(MovimentacaoBancaria).where(
            MovimentacaoBancaria.condominio_id == ctx.condominio_id, MovimentacaoBancaria.extrato_id.in_(ids),
            MovimentacaoBancaria.data >= inicio, MovimentacaoBancaria.data <= fim,
        )
    ).all()
    if not movimentos:
        return vazio

    meses_com_dados = sorted({(m.data.year, m.data.month) for m in movimentos})
    n = len(meses_com_dados)
    # fixo: 60% dos meses (arredondado para cima), no mínimo 2; com 1 mês só, o próprio mês é a base
    minimo = 1 if n == 1 else max(2, -(-n * 6 // 10))

    # aplicações/resgates do fundo não são gasto nem receita: ficam à parte
    aplicado_por_mes: dict = {}
    for m in movimentos:
        efeito = fundo.efeito_no_fundo(m)
        if efeito is not None and efeito > 0:
            aplicado_por_mes[(m.data.year, m.data.month)] = aplicado_por_mes.get((m.data.year, m.data.month), zero) + efeito
    movimentos = [m for m in movimentos if not fundo.e_do_fundo(m)]

    # total por item e mês
    por_item: dict = {}
    for m in movimentos:
        chave = (nome_do_lancamento(m), m.tipo)
        item = por_item.setdefault(chave, {"meses": {}, "ultimo": m})
        mes = (m.data.year, m.data.month)
        item["meses"][mes] = item["meses"].get(mes, zero) + m.valor
        if (m.data, m.ordem) >= (item["ultimo"].data, item["ultimo"].ordem):
            item["ultimo"] = m

    fixos, eventuais = [], []
    for (nome, tipo), item in por_item.items():
        valores = list(item["meses"].values())
        registro = {
            "nome": nome, "tipo": tipo, "meses_presente": len(valores),
            "valor_mensal": Decimal(str(median(valores))).quantize(Decimal("0.01")),
            "ultimo_valor": item["ultimo"].valor, "ultima_data": item["ultimo"].data,
        }
        (fixos if len(valores) >= minimo else eventuais).append((registro, sum(valores, zero)))

    entradas_fixas = sum((r["valor_mensal"] for r, _ in fixos if r["tipo"] == "ENTRADA"), zero)
    saidas_fixas = sum((r["valor_mensal"] for r, _ in fixos if r["tipo"] == "SAIDA"), zero)
    saidas_eventuais = (sum((t for r, t in eventuais if r["tipo"] == "SAIDA"), zero) / n).quantize(Decimal("0.01"))
    entradas_eventuais = (sum((t for r, t in eventuais if r["tipo"] == "ENTRADA"), zero) / n).quantize(Decimal("0.01"))

    # aplicação fixa no fundo: recorrente como os demais fixos (mediana dos meses em que houve)
    aplicacao = Decimal(str(median(aplicado_por_mes.values()))).quantize(Decimal("0.01")) if len(aplicado_por_mes) >= minimo else zero

    projecao = []
    ano, mes = fim.year, fim.month
    saldo_sem, saldo_com, saldo_fundo = saldo_atual, saldo_atual, fundo_atual
    futuros = futuros_por_mes(database, ctx.condominio_id, fim)
    for _ in range(meses):
        ano, mes = proximo_mes(ano, mes)
        f_entradas, f_saidas = futuros.get((ano, mes), (zero, zero))
        saldo_sem += entradas_fixas + saidas_fixas + f_entradas + f_saidas - aplicacao
        saldo_com += entradas_fixas + saidas_fixas + f_entradas + f_saidas + saidas_eventuais - aplicacao
        saldo_fundo += aplicacao
        projecao.append({
            "mes": f"{ano}-{mes:02d}", "entradas_fixas": entradas_fixas, "saidas_fixas": saidas_fixas,
            "futuros_entradas": f_entradas, "futuros_saidas": f_saidas, "aplicacao_fundo": -aplicacao,
            "saidas_eventuais": saidas_eventuais, "entradas_eventuais": entradas_eventuais,
            "saldo_sem_eventuais": saldo_sem, "saldo_previsto": saldo_com, "saldo_fundo": saldo_fundo,
        })

    fixos.sort(key=lambda x: (x[0]["tipo"], -abs(x[0]["valor_mensal"])))
    maiores = sorted((r for r, t in eventuais if r["tipo"] == "SAIDA"), key=lambda r: r["valor_mensal"])[:10]
    return {
        "base_inicio": f"{meses_com_dados[0][0]}-{meses_com_dados[0][1]:02d}", "base_fim": f"{meses_com_dados[-1][0]}-{meses_com_dados[-1][1]:02d}",
        "meses_analisados": n, "confianca": "BAIXA" if n < 3 else "MEDIA" if n < 6 else "ALTA",
        "saldo_atual": saldo_atual, "saldo_em": saldo_em, "fundo_atual": fundo_atual, "aplicacao_mensal": aplicacao,
        "contas": sorted(escolhidas), "fixos": [r for r, _ in fixos], "eventuais_maiores": maiores, "meses": projecao,
    }
