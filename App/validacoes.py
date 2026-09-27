# ---------------------------------------------------------
# VALIDAÇÕES E NORMALIZAÇÃO
# ---------------------------------------------------------
# Tudo é gravado sem máscara. Cada função limpa o valor,
# valida e devolve no formato do banco (ou None se vazio).
# Gera ValueError quando inválido (o Pydantic transforma
# em erro 422 com a mensagem).
# ---------------------------------------------------------

import re

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def somente_numeros(valor: str | None) -> str | None:
    if valor is None:
        return None
    numeros = re.sub(r"\D", "", valor)
    return numeros or None


def normalizar_cpf(valor: str | None) -> str | None:
    cpf = somente_numeros(valor)
    if cpf is None:
        return None
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ValueError("CPF inválido")
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        if (soma * 10) % 11 % 10 != int(cpf[tamanho]):
            raise ValueError("CPF inválido")
    return cpf


def normalizar_cnpj(valor: str | None) -> str | None:
    # aceita CNPJ numérico e alfanumérico (Receita Federal, a partir de 07/2026)
    if valor is None:
        return None
    cnpj = re.sub(r"[^0-9A-Za-z]", "", valor).upper() or None
    if cnpj is None:
        return None
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", cnpj) or cnpj == cnpj[0] * 14:
        raise ValueError("CNPJ inválido")
    pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for tamanho in (12, 13):
        soma = sum((ord(cnpj[i]) - 48) * pesos[i + 13 - tamanho] for i in range(tamanho))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(cnpj[tamanho]):
            raise ValueError("CNPJ inválido")
    return cnpj


def normalizar_telefone(valor: str | None) -> str | None:
    telefone = somente_numeros(valor)
    if telefone is not None and len(telefone) not in (10, 11):
        raise ValueError("Telefone deve ter DDD + número (10 ou 11 dígitos)")
    return telefone


def normalizar_cep(valor: str | None) -> str | None:
    cep = somente_numeros(valor)
    if cep is not None and len(cep) != 8:
        raise ValueError("CEP deve ter 8 dígitos")
    return cep


def normalizar_uf(valor: str | None) -> str | None:
    if not valor or not valor.strip():
        return None
    uf = valor.strip().upper()
    if uf not in UFS:
        raise ValueError("UF inválida")
    return uf


def normalizar_placa(valor: str | None) -> str | None:
    # aceita padrão antigo (ABC1234) e Mercosul (ABC1D23), com ou sem hífen
    if valor is None:
        return None
    placa = re.sub(r"[^0-9A-Za-z]", "", valor).upper() or None
    if placa is not None and not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", placa):
        raise ValueError("Placa inválida")
    return placa


def normalizar_email(valor: str | None) -> str | None:
    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip().lower()