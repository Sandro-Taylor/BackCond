# ---------------------------------------------------------
# GOOGLE DRIVE - cliente (OAuth + API REST v3)
# ---------------------------------------------------------
# O ADM conecta uma conta Google uma vez (página Arquivos).
# O backend guarda o refresh token e usa o Drive dessa conta.
# Escopo drive: o ADM vê o Drive inteiro da conta conectada.
# O que o sistema cria fica na pasta "Gerenciador".
# Excluir manda para a lixeira do Drive (dá para recuperar por 30 dias).
# O navegador nunca acessa o Drive: tudo passa pelo backend.
# Só biblioteca padrão (urllib): nenhuma dependência nova.
# ---------------------------------------------------------

import json
import ssl
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from App.models import DriveConexao
from config import settings

ESCOPO_DRIVE = "https://www.googleapis.com/auth/drive"
ESCOPOS = f"{ESCOPO_DRIVE} openid email"
URL_AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_API = "https://www.googleapis.com/drive/v3"
URL_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
PASTA = "application/vnd.google-apps.folder"
PASTA_RAIZ = "Gerenciador"

_pastas: dict = {}  # cache (pai, nome) -> id da pasta


def _contexto_ssl() -> ssl.SSLContext:
    # o Python do macOS (python.org) vem sem certificados: usa os do pacote certifi
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL = _contexto_ssl()


class ErroDrive(Exception):
    def __init__(self, codigo: int | None, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def configurado() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _http(metodo: str, url: str, dados: bytes | None = None, cabecalhos: dict | None = None, timeout: int = 60) -> tuple[int, bytes, dict]:
    requisicao = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos or {})
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout, context=SSL) as resposta:
            return resposta.status, resposta.read(), dict(resposta.headers)
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read(), dict(erro.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ErroDrive(None, f"Não foi possível falar com o Google: {erro}")


def _json(corpo: bytes) -> dict:
    try:
        return json.loads(corpo or b"{}")
    except ValueError:
        return {}


def _mensagem(corpo: bytes, padrao: str) -> str:
    dados = _json(corpo)
    erro = dados.get("error")
    if isinstance(erro, dict):
        return f"{padrao}: {erro.get('message', '')}".strip(": ")
    return f"{padrao}: {dados.get('error_description') or erro}" if erro else padrao


# =========================================================
# OAUTH
# =========================================================

def url_autorizacao(estado: str) -> str:
    return URL_AUTORIZACAO + "?" + urlencode({
        "client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
        "response_type": "code", "scope": ESCOPOS, "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": estado,
    })


def trocar_codigo(codigo: str) -> dict:
    status_http, corpo, _ = _http("POST", URL_TOKEN, urlencode({
        "code": codigo, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code",
    }).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    if status_http >= 400:
        raise ErroDrive(status_http, _mensagem(corpo, "O Google recusou a autorização"))
    return _json(corpo)


def email_do_token(id_token: str | None) -> str | None:
    # o id_token é um JWT do próprio Google recebido direto do endpoint de token: só lemos o e-mail
    if not id_token:
        return None
    try:
        import base64
        carga = id_token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return json.loads(base64.urlsafe_b64decode(carga)).get("email")
    except (IndexError, ValueError):
        return None


def conexao(database: Session) -> DriveConexao | None:
    return database.get(DriveConexao, 1)


def exigir_conexao(database: Session) -> DriveConexao:
    atual = conexao(database)
    if not atual:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O Google Drive ainda não foi conectado. Peça ao administrador para conectar em Arquivos (Drive)")
    return atual


def token(database: Session) -> str:
    # devolve um access token válido, renovando com o refresh token quando precisa
    atual = exigir_conexao(database)
    agora = datetime.now(timezone.utc)
    if atual.access_token and atual.expira_em and atual.expira_em > agora + timedelta(seconds=60):
        return atual.access_token
    status_http, corpo, _ = _http("POST", URL_TOKEN, urlencode({
        "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "refresh_token": atual.refresh_token, "grant_type": "refresh_token",
    }).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    if status_http >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_mensagem(corpo, "O Google não renovou o acesso ao Drive. Reconecte em Arquivos (Drive)"))
    dados = _json(corpo)
    atual.access_token = dados["access_token"]
    atual.expira_em = agora + timedelta(seconds=int(dados.get("expires_in", 3600)))
    database.commit()
    return atual.access_token


def revogar(refresh_token: str):
    try:
        _http("POST", "https://oauth2.googleapis.com/revoke?" + urlencode({"token": refresh_token}), b"", {"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    except ErroDrive:
        pass


# =========================================================
# API DO DRIVE
# =========================================================

def _api(database: Session, metodo: str, url: str, dados: bytes | None = None, cabecalhos: dict | None = None, padrao: str = "Erro no Google Drive") -> tuple[bytes, dict]:
    todos = {"Authorization": f"Bearer {token(database)}", **(cabecalhos or {})}
    try:
        status_http, corpo, resposta = _http(metodo, url, dados, todos)
    except ErroDrive as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    if status_http == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não encontrado no Google Drive")
    if status_http >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_mensagem(corpo, padrao))
    return corpo, resposta


CAMPOS = "id,name,mimeType,size,modifiedTime,createdTime,parents,webViewLink"


def info(database: Session, drive_id: str) -> dict:
    corpo, _ = _api(database, "GET", f"{URL_API}/files/{quote(drive_id)}?fields={CAMPOS}")
    return _json(corpo)


def listar(database: Session, pasta_id: str) -> list[dict]:
    itens, pagina = [], None
    while True:
        parametros = {
            "q": f"'{pasta_id}' in parents and trashed = false", "fields": f"nextPageToken,files({CAMPOS})",
            "orderBy": "folder,name", "pageSize": "200",
        }
        if pagina:
            parametros["pageToken"] = pagina
        corpo, _ = _api(database, "GET", f"{URL_API}/files?{urlencode(parametros)}")
        dados = _json(corpo)
        itens += dados.get("files", [])
        pagina = dados.get("nextPageToken")
        if not pagina:
            return itens


def criar_pasta(database: Session, nome: str, pai: str | None) -> str:
    metadados = {"name": nome, "mimeType": PASTA}
    if pai:
        metadados["parents"] = [pai]
    corpo, _ = _api(database, "POST", f"{URL_API}/files?fields=id", json.dumps(metadados).encode(), {"Content-Type": "application/json"}, "Não foi possível criar a pasta")
    return _json(corpo)["id"]


def garantir_pasta(database: Session, nome: str, pai: str) -> str:
    # acha (ou cria) a subpasta "nome" dentro de "pai"
    chave = (pai, nome)
    if chave in _pastas:
        return _pastas[chave]
    nome_q = nome.replace("\\", "\\\\").replace("'", "\\'")
    parametros = {"q": f"name = '{nome_q}' and '{pai}' in parents and mimeType = '{PASTA}' and trashed = false", "fields": "files(id)"}
    corpo, _ = _api(database, "GET", f"{URL_API}/files?{urlencode(parametros)}")
    achadas = _json(corpo).get("files", [])
    _pastas[chave] = achadas[0]["id"] if achadas else criar_pasta(database, nome, pai)
    return _pastas[chave]


def pasta_raiz(database: Session) -> str:
    atual = exigir_conexao(database)
    if atual.pasta_raiz_id:
        return atual.pasta_raiz_id
    atual.pasta_raiz_id = criar_pasta(database, PASTA_RAIZ, None)
    database.commit()
    return atual.pasta_raiz_id


def pasta_do_caminho(database: Session, *partes: str) -> str:
    # Gerenciador/<parte1>/<parte2>...
    atual = pasta_raiz(database)
    for parte in partes:
        atual = garantir_pasta(database, parte.strip() or "sem-nome", atual)
    return atual


def enviar(database: Session, nome: str, mime: str, conteudo: bytes, pasta_id: str) -> dict:
    fronteira = uuid.uuid4().hex
    metadados = json.dumps({"name": nome, "parents": [pasta_id]}).encode()
    corpo = (
        f"--{fronteira}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + metadados +
        f"\r\n--{fronteira}\r\nContent-Type: {mime}\r\n\r\n".encode() + conteudo + f"\r\n--{fronteira}--".encode()
    )
    resposta, _ = _api(database, "POST", f"{URL_UPLOAD}?uploadType=multipart&fields={CAMPOS}", corpo,
                       {"Content-Type": f"multipart/related; boundary={fronteira}"}, "Não foi possível enviar o arquivo")
    return _json(resposta)


# arquivos nativos do Google não têm "conteúdo": são exportados
EXPORTAR = {
    "application/vnd.google-apps.document": ("application/pdf", "pdf"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "application/vnd.google-apps.presentation": ("application/pdf", "pdf"),
    "application/vnd.google-apps.drawing": ("image/png", "png"),
}


def baixar(database: Session, drive_id: str, mime_original: str | None = None) -> tuple[bytes, str]:
    if mime_original in EXPORTAR:
        destino = EXPORTAR[mime_original][0]
        corpo, _ = _api(database, "GET", f"{URL_API}/files/{quote(drive_id)}/export?{urlencode({'mimeType': destino})}", padrao="Não foi possível exportar o arquivo")
        return corpo, destino
    corpo, cabecalhos = _api(database, "GET", f"{URL_API}/files/{quote(drive_id)}?alt=media", padrao="Não foi possível baixar o arquivo")
    return corpo, cabecalhos.get("Content-Type", "application/octet-stream")


_raiz_drive: dict = {}


def raiz_do_drive(database: Session) -> str:
    # id de "Meu Drive"
    if "id" not in _raiz_drive:
        corpo, _ = _api(database, "GET", f"{URL_API}/files/root?fields=id")
        _raiz_drive["id"] = _json(corpo)["id"]
    return _raiz_drive["id"]


def renomear(database: Session, drive_id: str, nome: str):
    _api(database, "PATCH", f"{URL_API}/files/{quote(drive_id)}", json.dumps({"name": nome}).encode(), {"Content-Type": "application/json"}, "Não foi possível renomear")


def excluir(database: Session, drive_id: str):
    # manda para a lixeira do Drive
    try:
        _api(database, "PATCH", f"{URL_API}/files/{quote(drive_id)}", json.dumps({"trashed": True}).encode(),
             {"Content-Type": "application/json"}, "Não foi possível excluir")
    except HTTPException as erro:
        if erro.status_code != 404:
            raise


def uso(database: Session) -> dict:
    corpo, _ = _api(database, "GET", f"{URL_API}/about?fields=storageQuota,user(emailAddress)")
    dados = _json(corpo)
    cota = dados.get("storageQuota", {})
    return {
        "email": (dados.get("user") or {}).get("emailAddress"),
        "usado": int(cota.get("usage", 0) or 0), "limite": int(cota["limit"]) if cota.get("limit") else None,
    }


def limpar_cache():
    _pastas.clear()
    _raiz_drive.clear()


# =========================================================
# CACHE DE CONTEÚDO (fotos exibidas com frequência)
# =========================================================

_cache: dict = {}            # drive_id -> (instante, mime, bytes)
CACHE_MAX_BYTES = 40 * 1024 * 1024
CACHE_TTL = 30 * 60


def baixar_com_cache(database: Session, drive_id: str, mime_original: str | None = None) -> tuple[bytes, str]:
    agora = time.time()
    if drive_id in _cache and agora - _cache[drive_id][0] < CACHE_TTL:
        _, mime, dados = _cache[drive_id]
        return dados, mime
    dados, mime = baixar(database, drive_id, mime_original)
    _cache[drive_id] = (agora, mime, dados)
    while sum(len(v[2]) for v in _cache.values()) > CACHE_MAX_BYTES and len(_cache) > 1:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    return dados, mime


def esquecer(drive_id: str):
    _cache.pop(drive_id, None)
