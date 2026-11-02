# ---------------------------------------------------------
# LEITOR DO EXTRATO BANCÁRIO (.xlsx)
# ---------------------------------------------------------
# Lê a planilha "Lançamentos" exportada pelo banco:
#   cabeçalho: Nome:, Agência:, Conta:, Periodo: (dd/mm/aaaa até dd/mm/aaaa)
#   colunas:   Data | Lançamento | Razão Social | CPF/CNPJ | Valor (R$) | Saldo (R$)
# Linhas de saldo ("SALDO ANTERIOR", "SALDO TOTAL DISPONÍVEL DIA")
# não são lançamentos: servem para saldo inicial/final e conferência.
# Linha repetida: se no fim do dia o saldo do banco só fecha sem uma
# cópia de um lançamento idêntico (mesma data, texto e valor), essa
# cópia é ignorada e o fato vira um aviso.
# Só biblioteca padrão (zipfile + XML): nenhuma dependência nova.
# ---------------------------------------------------------

import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.etree import ElementTree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class ErroExtrato(ValueError):
    pass


@dataclass
class Lancamento:
    data: date
    lancamento: str
    razao_social: str | None
    cpf_cnpj: str | None
    valor: Decimal
    ordem: int

    @property
    def tipo(self) -> str:
        return "SAIDA" if self.valor < 0 else "ENTRADA"


@dataclass
class Extrato:
    titular: str | None = None
    agencia: str | None = None
    conta: str | None = None
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    saldo_anterior: Decimal | None = None
    saldo_final: Decimal | None = None
    lancamentos: list[Lancamento] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# =========================================================
# XLSX -> linhas (lista de valores por coluna A, B, C...)
# =========================================================

def _coluna(ref: str) -> int:
    letras = re.match(r"[A-Z]+", ref).group(0)
    numero = 0
    for letra in letras:
        numero = numero * 26 + (ord(letra) - 64)
    return numero - 1


def _texto(no) -> str:
    return "".join(t.text or "" for t in no.iter(f"{{{NS['m']}}}t"))


def ler_linhas(conteudo: bytes) -> list[list]:
    try:
        arquivo = zipfile.ZipFile(BytesIO(conteudo))
    except zipfile.BadZipFile:
        raise ErroExtrato("O arquivo não é uma planilha .xlsx válida")
    nomes = set(arquivo.namelist())

    compartilhadas = []
    if "xl/sharedStrings.xml" in nomes:
        raiz = ElementTree.fromstring(arquivo.read("xl/sharedStrings.xml"))
        compartilhadas = [_texto(si) for si in raiz.findall("m:si", NS)]

    # primeira aba (pela ordem do workbook)
    caminho = "xl/worksheets/sheet1.xml"
    try:
        livro = ElementTree.fromstring(arquivo.read("xl/workbook.xml"))
        primeira = livro.find("m:sheets/m:sheet", NS)
        rels = ElementTree.fromstring(arquivo.read("xl/_rels/workbook.xml.rels"))
        alvo = next(r.get("Target") for r in rels if r.get("Id") == primeira.get(NS_REL))
        caminho = "xl/" + alvo.lstrip("/").removeprefix("xl/")
    except (KeyError, StopIteration, AttributeError):
        pass
    if caminho not in nomes:
        raise ErroExtrato("Não encontrei a aba de lançamentos na planilha")

    linhas = []
    for row in ElementTree.fromstring(arquivo.read(caminho)).iter(f"{{{NS['m']}}}row"):
        valores: dict[int, object] = {}
        for c in row.findall("m:c", NS):
            tipo, v = c.get("t"), c.find("m:v", NS)
            if tipo == "s" and v is not None:
                valor = compartilhadas[int(v.text)]
            elif tipo == "inlineStr":
                valor = _texto(c)
            elif tipo in ("str", "e"):
                valor = v.text if v is not None else None
            elif tipo == "b":
                valor = v is not None and v.text == "1"
            elif v is not None and v.text not in (None, ""):
                valor = float(v.text)
            else:
                valor = None
            valores[_coluna(c.get("r"))] = valor
        if valores:
            linhas.append([valores.get(i) for i in range(max(valores) + 1)])
    return linhas


# =========================================================
# CONVERSÕES
# =========================================================

def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").upper().strip()


def _limpo(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _data(valor) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, float):  # data guardada como número do Excel
        return date(1899, 12, 30) + timedelta(days=int(valor))
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _dinheiro(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, float):
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto:  # formato brasileiro 1.234,56
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _documento(valor) -> str | None:
    numeros = re.sub(r"\D", "", str(valor or ""))
    return numeros[:14] or None


def moeda(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# =========================================================
# EXTRATO
# =========================================================

def _copia_que_sobra(do_dia: list[Lancamento], excesso: Decimal) -> Lancamento | None:
    # lançamento idêntico (data, texto, favorecido e valor) que aparece 2+ vezes
    # no dia e cujo valor é exatamente o que sobra na conferência do saldo
    vistos: dict = {}
    for item in do_dia:
        chave = (item.data, item.lancamento, item.razao_social, item.cpf_cnpj, item.valor)
        if chave in vistos and item.valor == excesso:
            return item  # a última cópia
        vistos[chave] = item
    return None


def ler_extrato(conteudo: bytes) -> Extrato:
    linhas = ler_linhas(conteudo)
    extrato = Extrato()

    # cabeçalho e linha de títulos das colunas
    inicio = None
    for i, linha in enumerate(linhas):
        rotulo = _sem_acento(str(linha[0])) if linha and linha[0] is not None else ""
        valor = _limpo(linha[1]) if len(linha) > 1 else None
        if rotulo == "NOME:":
            extrato.titular = valor
        elif rotulo == "AGENCIA:":
            extrato.agencia = valor
        elif rotulo == "CONTA:":
            extrato.conta = valor
        elif rotulo == "PERIODO:" and valor:
            datas = re.findall(r"\d{2}/\d{2}/\d{4}", valor)
            if len(datas) == 2:
                extrato.periodo_inicio, extrato.periodo_fim = _data(datas[0]), _data(datas[1])
        elif rotulo == "DATA" and len(linha) > 4 and _sem_acento(str(linha[1] or "")).startswith("LANCAMENTO"):
            inicio = i + 1
            break
    if inicio is None:
        raise ErroExtrato("Não encontrei a linha de títulos (Data, Lançamento, Razão Social, CPF/CNPJ, Valor, Saldo). Confira se é o extrato do banco")

    # lançamentos + conferência do saldo de cada dia
    saldo_conferencia: Decimal | None = None
    soma_dia = Decimal("0")
    do_dia: list[Lancamento] = []  # lançamentos desde o último saldo
    ordem = 0
    for numero, linha in enumerate(linhas[inicio:], start=inicio + 1):
        linha = list(linha) + [None] * (6 - len(linha))
        bruto_data, descricao, razao, doc, bruto_valor, bruto_saldo = linha[:6]
        descricao = _limpo(descricao)
        if not descricao and bruto_valor in (None, "") and bruto_saldo in (None, ""):
            continue  # linha vazia
        quando = _data(bruto_data)
        valor = _dinheiro(bruto_valor)
        saldo = _dinheiro(bruto_saldo)
        nome = _sem_acento(descricao or "")

        if nome.startswith("SALDO"):
            if saldo is None:
                continue
            if nome.startswith("SALDO ANTERIOR"):
                extrato.saldo_anterior = saldo
            elif saldo_conferencia is not None:
                calculado = saldo_conferencia + soma_dia
                if calculado != saldo:
                    dia = quando.strftime("%d/%m/%Y") if quando else f"linha {numero}"
                    excesso = calculado - saldo
                    repetido = _copia_que_sobra(do_dia, excesso)
                    if repetido:
                        extrato.lancamentos.remove(repetido)
                        extrato.avisos.append(
                            f"{dia}: \"{repetido.lancamento}\" de {moeda(repetido.valor)} aparece repetido no extrato e o saldo do banco "
                            f"só fecha sem a cópia. A cópia foi ignorada."
                        )
                    else:
                        extrato.avisos.append(
                            f"{dia}: a soma dos lançamentos dá {moeda(calculado)}, mas o banco informa saldo de {moeda(saldo)} "
                            f"(diferença de {moeda(saldo - calculado)}). Confira o extrato."
                        )
            saldo_conferencia, soma_dia, do_dia = saldo, Decimal("0"), []
            extrato.saldo_final = saldo
            continue

        if valor is None:
            extrato.avisos.append(f"Linha {numero} ignorada: sem valor ({descricao or 'sem descrição'}).")
            continue
        if quando is None:
            extrato.avisos.append(f"Linha {numero} ignorada: data inválida ({bruto_data}).")
            continue

        ordem += 1
        novo = Lancamento(
            data=quando, lancamento=(descricao or "Sem descrição")[:255], razao_social=(_limpo(razao) or None) and _limpo(razao)[:255],
            cpf_cnpj=_documento(doc), valor=valor, ordem=ordem,
        )
        extrato.lancamentos.append(novo)
        do_dia.append(novo)
        soma_dia += valor
        if saldo_conferencia is None and extrato.saldo_anterior is not None:
            saldo_conferencia = extrato.saldo_anterior

    if not extrato.lancamentos:
        raise ErroExtrato("Nenhum lançamento encontrado no arquivo")
    for posicao, lancamento in enumerate(extrato.lancamentos, start=1):
        lancamento.ordem = posicao  # renumera depois de ignorar repetidos

    # período: do cabeçalho ou, se faltar, das próprias datas
    if not extrato.periodo_inicio or not extrato.periodo_fim:
        datas = [l.data for l in extrato.lancamentos]
        extrato.periodo_inicio = extrato.periodo_inicio or min(datas).replace(day=1)
        extrato.periodo_fim = extrato.periodo_fim or max(datas)
        extrato.avisos.append("O arquivo não informa o período; usei as datas dos lançamentos.")
    fora = [l for l in extrato.lancamentos if not (extrato.periodo_inicio <= l.data <= extrato.periodo_fim)]
    if fora:
        extrato.avisos.append(f"{len(fora)} lançamento(s) com data fora do período {extrato.periodo_inicio:%d/%m/%Y} a {extrato.periodo_fim:%d/%m/%Y}.")
    return extrato
