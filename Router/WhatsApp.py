# ---------------------------------------------------------
# WHATSAPP (Evolution API) - teste
# ---------------------------------------------------------
# Um número de WhatsApp para o sistema todo, ligado pela
# Evolution API (serviço "whatsapp" do docker-compose).
#   - a Evolution chama POST /whatsapp/webhook a cada mensagem;
#     ela é gravada na conversa do contato
#   - o front do ADM consulta /whatsapp/novidades a cada poucos
#     segundos e mostra um pop-up com a mensagem recebida
#   - o ADM responde pelo pop-up ou pela página WhatsApp
# Quem acessa:
#   Quem recebe o pop-up e responde: o responsável da pessoa dona do
#   telefone (padrão: o síndico do prédio). Número desconhecido ou sem
#   ninguém definido: todos os usuários marcados como RESPONSÁVEL.
#   Síndico vê só as conversas que são dele; RESPONSÁVEL e ADM veem todas.
# ROBÔ (App/bot_whatsapp.py): responde primeiro com um menu. O pop-up
#   só aparece quando a pessoa pede atendimento (modo ATENDENTE).
#   O robô só responde mensagem NOVA de um contato (enviada há no máximo
#   MAX_IDADE_RESPOSTA). Mensagens antigas que a Evolution reenvia ao
#   conectar/sincronizar o número são só gravadas: nunca disparam resposta.
#   ADM ........... conecta o número (QR code) e vê/responde as conversas
# ---------------------------------------------------------

import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from App import bot_whatsapp as robo
from App import whatsapp as evolution
from App.database import get_database
from App.dependencies import exigir_acesso_whatsapp, exigir_admin_sistema
from App.responsaveis import destinatarios_do_telefone, recebe_mensagem, variacoes_telefone
from App.models import Condominio, Pessoa, User, WhatsappConversa, WhatsappMensagem
from config import settings

router = APIRouter(prefix="/whatsapp")
log = logging.getLogger("uvicorn.error")

LIMITE_MENSAGENS = 200  # mensagens carregadas ao abrir uma conversa
MAX_IDADE_RESPOSTA = 120  # segundos: mensagem mais velha que isso não recebe resposta do robô


# =========================================================
# DADOS
# =========================================================

class StatusResposta(BaseModel):
    estado: str               # CONECTADO, CONECTANDO, DESCONECTADO, SEM_INSTANCIA, INDISPONIVEL
    qrcode: str | None = None  # imagem (data URL) para ler no celular
    mensagem: str | None = None


class MensagemResposta(BaseModel):
    id: uuid.UUID
    recebida: bool             # True = veio do contato; False = enviada por nós
    texto: str
    autor_nome: str | None
    created_at: datetime


class ConversaResumo(BaseModel):
    id: uuid.UUID
    nome: str | None
    telefone: str | None
    contatos: list[str]        # pessoas cadastradas com esse telefone ("Nome · Condomínio")
    nao_lidas: int
    modo: str                  # ROBO ou ATENDENTE
    ultima_mensagem: str | None
    ultima_mensagem_em: datetime


class ConversaDetalhe(ConversaResumo):
    mensagens: list[MensagemResposta]


class Novidade(BaseModel):
    id: uuid.UUID
    conversa_id: uuid.UUID
    nome: str | None
    telefone: str | None
    contatos: list[str]
    texto: str
    created_at: datetime


class NovidadesResposta(BaseModel):
    agora: datetime
    mensagens: list[Novidade]


class EnviarTexto(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)

    @field_validator("texto")
    @classmethod
    def limpar(cls, valor: str):
        valor = valor.strip()
        if not valor:
            raise ValueError("Escreva a mensagem")
        return valor


# =========================================================
# AUXILIARES
# =========================================================

def contatos_do_telefone(database: Session, telefone: str | None, cache: dict | None = None) -> list[str]:
    if not telefone:
        return []
    if cache is not None and telefone in cache:
        return cache[telefone]
    linhas = database.execute(
        select(Pessoa.nome, Condominio.nome)
        .join(Condominio, Condominio.id == Pessoa.condominio_id)
        .where(Pessoa.telefone.in_(variacoes_telefone(telefone)), Pessoa.ativo.is_(True))
        .order_by(Pessoa.nome)
    ).all()
    resultado = [f"{pessoa} · {condominio}" for pessoa, condominio in linhas]
    if cache is not None:
        cache[telefone] = resultado
    return resultado


def pode_ver(database: Session, usuario: User, conversa: WhatsappConversa, cache: dict) -> bool:
    # ADM e RESPONSÁVEL veem todas; síndico, só as conversas que são dele
    if usuario.admin_sistema or usuario.responsavel:
        return True
    return usuario.id in destinatarios_do_telefone(database, conversa.telefone, cache)


def resumo(database: Session, conversa: WhatsappConversa, cache: dict | None = None) -> dict:
    return {
        "id": conversa.id, "nome": conversa.nome, "telefone": conversa.telefone,
        "contatos": contatos_do_telefone(database, conversa.telefone, cache),
        "nao_lidas": conversa.nao_lidas, "modo": conversa.modo or "ROBO", "ultima_mensagem": conversa.ultima_mensagem,
        "ultima_mensagem_em": conversa.ultima_mensagem_em,
    }


def detalhe(database: Session, conversa: WhatsappConversa) -> dict:
    mensagens = database.scalars(
        select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == conversa.id)
        .order_by(WhatsappMensagem.created_at.desc()).limit(LIMITE_MENSAGENS)
    ).all()
    dados = resumo(database, conversa)
    dados["mensagens"] = [{
        "id": m.id, "recebida": m.recebida, "texto": m.texto, "autor_nome": m.autor_nome, "created_at": m.created_at,
    } for m in reversed(mensagens)]
    return dados


def buscar_conversa(database: Session, conversa_id: uuid.UUID, usuario: User | None = None) -> WhatsappConversa:
    conversa = database.get(WhatsappConversa, conversa_id)
    if not conversa or (usuario and not pode_ver(database, usuario, conversa, {})):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada")
    return conversa


def exigir_evolution(estado: str):
    if estado == "INDISPONIVEL":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível falar com a Evolution API. Confira se o container 'whatsapp' está rodando e se a EVOLUTION_API_KEY está certa",
        )


def enviada_em(item: dict) -> datetime | None:
    # horário em que o contato enviou (messageTimestamp: segundos; às vezes texto ou {"low": n})
    valor = item.get("messageTimestamp")
    if isinstance(valor, dict):
        valor = valor.get("low")
    try:
        return datetime.fromtimestamp(int(valor), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def mensagem_nova(item: dict) -> bool:
    # só mensagem recém-enviada pode acionar o robô; sem horário = não responde (mais seguro)
    quando = enviada_em(item)
    return quando is not None and (datetime.now(timezone.utc) - quando).total_seconds() <= MAX_IDADE_RESPOSTA


def registrar_mensagem(database: Session, item: dict):
    # grava uma mensagem vinda do webhook (recebida do contato ou enviada pelo próprio celular)
    chave = item.get("key") or {}
    jid = chave.get("remoteJid") or ""
    if not jid or jid.endswith(("@g.us", "@broadcast", "@newsletter")):
        return  # grupos, status e canais ficam de fora

    # contas novas do WhatsApp chegam com @lid; quando vier o número de verdade, usa ele
    alternativo = chave.get("remoteJidAlt") or chave.get("senderPn") or item.get("senderPn")
    if jid.endswith("@lid") and alternativo:
        jid = alternativo if "@" in alternativo else f"{alternativo}@s.whatsapp.net"

    texto = evolution.extrair_texto(item.get("message"))
    if texto is None:
        return

    wa_id = chave.get("id")
    if wa_id and database.scalar(select(WhatsappMensagem.id).where(WhatsappMensagem.wa_id == wa_id)):
        return  # já gravada (ex.: resposta enviada pelo sistema)

    de_mim = bool(chave.get("fromMe"))
    conversa = database.scalar(select(WhatsappConversa).where(WhatsappConversa.jid == jid))
    if not conversa:
        telefone = jid.split("@")[0] if jid.endswith("@s.whatsapp.net") else None
        conversa = WhatsappConversa(jid=jid, telefone=telefone, nao_lidas=0)
        database.add(conversa)
        database.flush()

    if not de_mim and item.get("pushName"):
        conversa.nome = str(item["pushName"])[:150]

    mensagem = WhatsappMensagem(
        conversa_id=conversa.id, wa_id=wa_id, recebida=not de_mim, texto=texto,
        autor_nome="Pelo celular" if de_mim else None,
    )
    database.add(mensagem)
    conversa.ultima_mensagem = texto[:300]
    conversa.ultima_mensagem_em = datetime.now(timezone.utc)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()  # chegou em duplicidade ao mesmo tempo: a outra cópia já foi gravada
        return
    if not de_mim:
        if not mensagem_nova(item):
            log.info("WhatsApp: mensagem antiga de %s gravada sem resposta do robô", conversa.telefone or conversa.jid)
            return
        try:
            robo.processar(database, conversa, mensagem)  # robô responde ou passa para uma pessoa
        except Exception:
            database.rollback()
            log.exception("WhatsApp: erro no robô ao responder %s", conversa.telefone or conversa.jid)


# =========================================================
# WEBHOOK (chamado pela Evolution API, sem login)
# =========================================================

@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, token: str = Query(""), database: Session = Depends(get_database)):
    if not settings.whatsapp_webhook_token or not secrets.compare_digest(token, settings.whatsapp_webhook_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token do webhook inválido")

    try:
        corpo = await request.json()
    except ValueError:
        return {"ok": False}
    if not isinstance(corpo, dict):
        return {"ok": False}

    evento = str(corpo.get("event", "")).lower().replace("_", ".")
    if evento != "messages.upsert":
        return {"ok": True}

    itens = corpo.get("data")
    if isinstance(itens, dict) and isinstance(itens.get("messages"), list):
        itens = itens["messages"]
    if isinstance(itens, dict):
        itens = [itens]
    for item in itens or []:
        if isinstance(item, dict):
            registrar_mensagem(database, item)
    return {"ok": True}


# =========================================================
# CONEXÃO DO NÚMERO (QR code)
# =========================================================

@router.get("/status", response_model=StatusResposta)
def statusWhatsApp(_: User = Depends(exigir_acesso_whatsapp)):
    estado = evolution.estado()
    mensagem = "Evolution API fora do ar ou chave inválida" if estado == "INDISPONIVEL" else None
    return {"estado": estado, "mensagem": mensagem}


@router.post("/conectar", response_model=StatusResposta)
def conectarWhatsApp(_: User = Depends(exigir_admin_sistema)):
    estado = evolution.estado()
    exigir_evolution(estado)

    if estado == "SEM_INSTANCIA":
        codigo, dados = evolution.criar_instancia()
        if codigo is None or codigo >= 400:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=evolution.mensagem_de_erro(dados, "Não foi possível criar a conexão do WhatsApp"))
        evolution.configurar_webhook()
        qrcode = (dados.get("qrcode") or {}).get("base64")
        if qrcode:
            return {"estado": "CONECTANDO", "qrcode": qrcode}
    else:
        evolution.configurar_webhook()  # garante o webhook atualizado (URL e token)
        if estado == "CONECTADO":
            return {"estado": estado}

    codigo, dados = evolution.pedir_qrcode()
    if codigo is None or codigo >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=evolution.mensagem_de_erro(dados, "Não foi possível gerar o QR code"))
    if dados.get("base64"):
        return {"estado": "CONECTANDO", "qrcode": dados["base64"]}
    return {"estado": evolution.estado(), "mensagem": "QR code ainda não disponível. Tente novamente em alguns segundos"}


@router.post("/desconectar", response_model=StatusResposta)
def desconectarWhatsApp(_: User = Depends(exigir_admin_sistema)):
    exigir_evolution(evolution.estado())
    codigo, dados = evolution.desconectar()
    if codigo is None or codigo >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=evolution.mensagem_de_erro(dados, "Não foi possível desconectar"))
    return {"estado": evolution.estado()}


# =========================================================
# CONVERSAS
# =========================================================

@router.get("/conversas", response_model=list[ConversaResumo])
def listarConversas(database: Session = Depends(get_database), usuario: User = Depends(exigir_acesso_whatsapp)):
    conversas = database.scalars(select(WhatsappConversa).order_by(WhatsappConversa.ultima_mensagem_em.desc())).all()
    cache: dict = {}
    cache_destinos: dict = {}
    return [resumo(database, c, cache) for c in conversas if pode_ver(database, usuario, c, cache_destinos)]


@router.get("/conversas/{conversa_id}", response_model=ConversaDetalhe)
def verConversa(conversa_id: uuid.UUID, database: Session = Depends(get_database), usuario: User = Depends(exigir_acesso_whatsapp)):
    # abrir a conversa marca como lida
    conversa = buscar_conversa(database, conversa_id, usuario)
    if conversa.nao_lidas:
        conversa.nao_lidas = 0
        database.commit()
    return detalhe(database, conversa)


@router.post("/conversas/{conversa_id}/mensagens", response_model=ConversaDetalhe)
def responderConversa(conversa_id: uuid.UUID, dados: EnviarTexto, database: Session = Depends(get_database), usuario: User = Depends(exigir_acesso_whatsapp)):
    conversa = buscar_conversa(database, conversa_id, usuario)
    # quem responde assume a conversa: o robô para de responder
    conversa.modo, conversa.atendente_desde, conversa.nao_lidas = "ATENDENTE", datetime.now(timezone.utc), 0
    codigo, retorno = robo.enviar_e_registrar(database, conversa, dados.texto, usuario.full_name, usuario.id)
    if codigo is None:
        exigir_evolution("INDISPONIVEL")
    if codigo >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=evolution.mensagem_de_erro(retorno, "O WhatsApp não aceitou a mensagem"))
    return detalhe(database, buscar_conversa(database, conversa_id))


@router.post("/conversas/{conversa_id}/assumir", response_model=ConversaDetalhe)
def assumirConversa(conversa_id: uuid.UUID, database: Session = Depends(get_database), usuario: User = Depends(exigir_acesso_whatsapp)):
    # a pessoa passa a atender: o robô para de responder
    conversa = buscar_conversa(database, conversa_id, usuario)
    conversa.modo, conversa.atendente_desde, conversa.bot_dados = "ATENDENTE", datetime.now(timezone.utc), None
    database.commit()
    return detalhe(database, conversa)


@router.post("/conversas/{conversa_id}/devolver", response_model=ConversaDetalhe)
def devolverAoRobo(conversa_id: uuid.UUID, database: Session = Depends(get_database), usuario: User = Depends(exigir_acesso_whatsapp)):
    # encerra o atendimento humano: o robô volta a responder
    conversa = buscar_conversa(database, conversa_id, usuario)
    conversa.modo, conversa.atendente_desde, conversa.bot_dados, conversa.nao_lidas = "ROBO", None, None, 0
    database.commit()
    robo.enviar_e_registrar(database, conversa, "Atendimento encerrado. Obrigado! Se precisar, é só mandar uma mensagem. 🙂", robo.NOME_ROBO)
    return detalhe(database, buscar_conversa(database, conversa_id))


# =========================================================
# NOVIDADES (pop-up de quem recebe a mensagem)
# =========================================================

@router.get("/novidades", response_model=NovidadesResposta)
def novidades(desde: datetime | None = None, database: Session = Depends(get_database), usuario: User = Depends(exigir_acesso_whatsapp)):
    # primeira chamada (sem "desde") só devolve a hora do servidor, para não abrir pop-up de mensagens antigas
    agora = datetime.now(timezone.utc)
    if desde is None:
        return {"agora": agora, "mensagens": []}
    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=timezone.utc)

    linhas = database.execute(
        select(WhatsappMensagem, WhatsappConversa)
        .join(WhatsappConversa, WhatsappConversa.id == WhatsappMensagem.conversa_id)
        .where(WhatsappMensagem.recebida.is_(True), WhatsappMensagem.para_atendente.is_(True), WhatsappMensagem.created_at > desde)
        .order_by(WhatsappMensagem.created_at)
        .limit(50)
    ).all()
    cache: dict = {}
    cache_destinos: dict = {}
    mensagens = []
    for m, c in linhas:
        if not recebe_mensagem(usuario, destinatarios_do_telefone(database, c.telefone, cache_destinos)):
            continue  # a mensagem é de outro responsável
        mensagens.append({
            "id": m.id, "conversa_id": c.id, "nome": c.nome, "telefone": c.telefone,
            "contatos": contatos_do_telefone(database, c.telefone, cache), "texto": m.texto, "created_at": m.created_at,
        })
    return {"agora": agora, "mensagens": mensagens}
