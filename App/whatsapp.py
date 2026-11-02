# ---------------------------------------------------------
# EVOLUTION API (WhatsApp) - cliente HTTP
# ---------------------------------------------------------
# Conversa com o container "whatsapp" do docker-compose.
# Um único número (instância) para o sistema todo.
# Usa só a biblioteca padrão (urllib): nenhuma dependência nova.
# ---------------------------------------------------------

import json
import urllib.error
import urllib.request
from urllib.parse import quote

from config import settings

EVENTOS_WEBHOOK = ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]


def _instancia() -> str:
    return quote(settings.evolution_instancia, safe="")


def _chamar(metodo: str, caminho: str, corpo: dict | None = None, timeout: int = 15) -> tuple[int | None, dict]:
    # devolve (status HTTP, JSON); status None = Evolution fora do ar
    url = settings.evolution_url.rstrip("/") + caminho
    dados = json.dumps(corpo).encode() if corpo is not None else None
    requisicao = urllib.request.Request(url, data=dados, method=metodo, headers={"apikey": settings.evolution_api_key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            texto = resposta.read().decode("utf-8", errors="ignore")
            return resposta.status, _json(texto)
    except urllib.error.HTTPError as erro:
        return erro.code, _json(erro.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, {}


def _json(texto: str) -> dict:
    try:
        valor = json.loads(texto) if texto else {}
    except ValueError:
        return {}
    return valor if isinstance(valor, dict) else {"lista": valor}


def mensagem_de_erro(dados: dict, padrao: str) -> str:
    resposta = dados.get("response") if isinstance(dados.get("response"), dict) else {}
    detalhe = resposta.get("message") or dados.get("message") or dados.get("error")
    if isinstance(detalhe, list):
        detalhe = "; ".join(str(item) for item in detalhe)
    return f"{padrao}: {detalhe}" if detalhe else padrao


def url_webhook() -> str:
    return f"{settings.whatsapp_webhook_url}?token={quote(settings.whatsapp_webhook_token, safe='')}"


# =========================================================
# INSTÂNCIA (conexão do número)
# =========================================================

def estado() -> str:
    # CONECTADO, CONECTANDO, DESCONECTADO, SEM_INSTANCIA ou INDISPONIVEL
    codigo, dados = _chamar("GET", f"/instance/connectionState/{_instancia()}")
    if codigo is None or codigo in (401, 403) or codigo >= 500:
        return "INDISPONIVEL"
    if codigo == 404:
        return "SEM_INSTANCIA"
    situacao = (dados.get("instance") or {}).get("state") or dados.get("state")
    return {"open": "CONECTADO", "connecting": "CONECTANDO"}.get(situacao, "DESCONECTADO")


def criar_instancia() -> tuple[int | None, dict]:
    return _chamar("POST", "/instance/create", {
        "instanceName": settings.evolution_instancia,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
        "groupsIgnore": True,
        "webhook": {"url": url_webhook(), "byEvents": False, "base64": False, "events": EVENTOS_WEBHOOK},
    }, timeout=30)


def configurar_webhook() -> tuple[int | None, dict]:
    return _chamar("POST", f"/webhook/set/{_instancia()}", {
        "webhook": {"enabled": True, "url": url_webhook(), "byEvents": False, "base64": False, "events": EVENTOS_WEBHOOK},
    })


def pedir_qrcode() -> tuple[int | None, dict]:
    return _chamar("GET", f"/instance/connect/{_instancia()}", timeout=30)


def desconectar() -> tuple[int | None, dict]:
    return _chamar("DELETE", f"/instance/logout/{_instancia()}")


# =========================================================
# MENSAGENS
# =========================================================

def enviar_texto(numero: str, texto: str) -> tuple[int | None, dict]:
    return _chamar("POST", f"/message/sendText/{_instancia()}", {"number": numero, "text": texto}, timeout=30)


def extrair_texto(mensagem: dict | None) -> str | None:
    # texto exibível da mensagem; None = ignorar (reação, aviso de sistema...)
    m = mensagem or {}
    for envelope in ("ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2", "documentWithCaptionMessage"):
        if isinstance(m.get(envelope), dict) and isinstance(m[envelope].get("message"), dict):
            m = m[envelope]["message"]
    if m.get("conversation"):
        return m["conversation"]
    if isinstance(m.get("extendedTextMessage"), dict):
        return m["extendedTextMessage"].get("text") or None
    midias = {"imageMessage": "[imagem]", "videoMessage": "[vídeo]", "documentMessage": "[documento]"}
    for chave, rotulo in midias.items():
        if isinstance(m.get(chave), dict):
            legenda = m[chave].get("caption")
            return f"{rotulo} {legenda}" if legenda else rotulo
    outros = {"audioMessage": "[áudio]", "stickerMessage": "[figurinha]", "locationMessage": "[localização]", "contactMessage": "[contato]", "contactsArrayMessage": "[contatos]"}
    for chave, rotulo in outros.items():
        if chave in m:
            return rotulo
    if "reactionMessage" in m or "protocolMessage" in m or "senderKeyDistributionMessage" in m or not m:
        return None
    return "[mensagem não suportada]"
