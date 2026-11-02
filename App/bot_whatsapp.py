# ---------------------------------------------------------
# ATENDIMENTO AUTOMÁTICO DO WHATSAPP (robô com menu)
# ---------------------------------------------------------
# Toda conversa começa com o ROBÔ. Ele reconhece o morador pelo
# telefone cadastrado e responde com dados do sistema:
#   1 cotas em aberto | 2 avisos | 3 abrir chamado | 4 meus chamados
#   0 falar com uma pessoa (sempre disponível)
# Ao pedir uma pessoa, a conversa passa para o modo ATENDENTE:
# o robô para de responder e o responsável recebe o pop-up.
# Volta ao robô quando o atendente devolve a conversa ou depois
# de algumas horas sem resposta do atendente.
# Para trocar o menu por IA no futuro: substitua responder_bot().
# ---------------------------------------------------------

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from App import whatsapp as evolution
from App.models import Apartamento, Aviso, Chamado, ChamadoMensagem, Condominio, Cota, Pessoa, PessoaApartamento, WhatsappConversa, WhatsappMensagem
from App.responsaveis import variacoes_telefone
from config import settings

NOME_ROBO = "Assistente virtual"
log = logging.getLogger("uvicorn.error")
PEDIR_PESSOA = {"0", "atendente", "humano", "pessoa", "falar com atendente", "falar com alguem", "falar com alguém"}
VOLTAR_MENU = {"menu", "oi", "olá", "ola", "inicio", "início", "voltar"}
RODAPE = "\n\nDigite *menu* para ver as opções ou *0* para falar com uma pessoa."


# =========================================================
# ENVIO (usado pelo robô e pelos atendentes)
# =========================================================

def enviar_e_registrar(database: Session, conversa: WhatsappConversa, texto: str, autor_nome: str, autor_user_id=None) -> tuple[int | None, dict]:
    # envia pelo WhatsApp e grava a mensagem na conversa (sem duplicar se o webhook chegar antes)
    codigo, retorno = evolution.enviar_texto(conversa.telefone or conversa.jid, texto)
    if codigo is None or codigo >= 400:
        log.warning("WhatsApp: a Evolution não enviou a mensagem para %s (%s): %s", conversa.telefone or conversa.jid, codigo, retorno)
        return codigo, retorno
    wa_id = (retorno.get("key") or {}).get("id")
    existente = database.scalar(select(WhatsappMensagem).where(WhatsappMensagem.wa_id == wa_id)) if wa_id else None
    if existente:
        existente.autor_user_id, existente.autor_nome = autor_user_id, autor_nome
    else:
        database.add(WhatsappMensagem(conversa_id=conversa.id, wa_id=wa_id, recebida=False, texto=texto, autor_user_id=autor_user_id, autor_nome=autor_nome))
    conversa.ultima_mensagem = texto[:300]
    conversa.ultima_mensagem_em = datetime.now(timezone.utc)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
    return codigo, retorno


# =========================================================
# QUEM ESTÁ FALANDO
# =========================================================

def pessoas_do_telefone(database: Session, telefone: str | None) -> list[Pessoa]:
    if not telefone:
        return []
    return list(database.scalars(
        select(Pessoa).join(Condominio, Condominio.id == Pessoa.condominio_id)
        .where(Pessoa.telefone.in_(variacoes_telefone(telefone)), Pessoa.ativo.is_(True), Condominio.ativo.is_(True))
        .order_by(Condominio.nome)
    ).all())


def dados_bot(conversa: WhatsappConversa) -> dict:
    try:
        return json.loads(conversa.bot_dados or "{}")
    except ValueError:
        return {}


def salvar_dados(conversa: WhatsappConversa, dados: dict):
    conversa.bot_dados = json.dumps(dados) if dados else None


def nome_condominio(database: Session, condominio_id) -> str:
    c = database.get(Condominio, condominio_id)
    return c.nome if c else ""


def rotulo_apto(apartamento: Apartamento) -> str:
    return f"Bloco {apartamento.bloco} · {apartamento.numero}" if apartamento.bloco else f"Apto {apartamento.numero}"


def moeda(valor) -> str:
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# =========================================================
# RESPOSTAS
# =========================================================

def menu(pessoa: Pessoa | None, database: Session, saudacao: bool) -> str:
    if not pessoa:
        return ("Olá! Sou o assistente virtual da administração do condomínio.\n"
                "Não encontrei seu telefone no cadastro.\n\n"
                "Digite *0* para falar com uma pessoa.")
    primeiro = pessoa.nome.split()[0]
    inicio = f"Olá, {primeiro}! Sou o assistente virtual do {nome_condominio(database, pessoa.condominio_id)}.\n\n" if saudacao else ""
    return (inicio + "Escolha uma opção:\n"
            "*1* – Minhas cotas em aberto\n"
            "*2* – Avisos do condomínio\n"
            "*3* – Abrir um chamado\n"
            "*4* – Meus chamados\n"
            "*0* – Falar com uma pessoa")


def resposta_cotas(database: Session, pessoa: Pessoa) -> str:
    aptos = list(database.scalars(select(PessoaApartamento.apartamento_id).where(PessoaApartamento.pessoa_id == pessoa.id, PessoaApartamento.ativo.is_(True))).all())
    if not aptos:
        return "Não encontrei apartamento ligado ao seu cadastro." + RODAPE
    cotas = database.scalars(
        select(Cota).where(Cota.apartamento_id.in_(aptos), Cota.status == "ABERTA").order_by(Cota.vencimento)
    ).all()
    if not cotas:
        return "Você está em dia: nenhuma cota em aberto. ✅" + RODAPE
    hoje = date.today()
    linhas = []
    for c in cotas[:10]:
        atraso = " (atrasada)" if c.vencimento < hoje else ""
        linhas.append(f"• {c.competencia.strftime('%m/%Y')} – {moeda(c.valor)} – vence {c.vencimento.strftime('%d/%m/%Y')}{atraso}")
    total = sum(float(c.valor) for c in cotas)
    return "Suas cotas em aberto:\n" + "\n".join(linhas) + f"\n\nTotal: {moeda(total)}" + RODAPE


def resposta_avisos(database: Session, pessoa: Pessoa) -> str:
    hoje = date.today()
    avisos = database.scalars(
        select(Aviso).where(Aviso.condominio_id == pessoa.condominio_id, Aviso.ativo.is_(True), (Aviso.expira_em.is_(None)) | (Aviso.expira_em >= hoje))
        .order_by(Aviso.fixado.desc(), Aviso.created_at.desc()).limit(3)
    ).all()
    if not avisos:
        return "Nenhum aviso no momento." + RODAPE
    partes = [f"*{a.titulo}*\n{a.conteudo[:400]}" for a in avisos]
    return "Avisos do condomínio:\n\n" + "\n\n".join(partes) + RODAPE


def resposta_chamados(database: Session, pessoa: Pessoa) -> str:
    chamados = database.scalars(
        select(Chamado).where(Chamado.autor_pessoa_id == pessoa.id, Chamado.status != "ENCERRADO").order_by(Chamado.updated_at.desc()).limit(5)
    ).all()
    if not chamados:
        return "Você não tem chamados em andamento." + RODAPE
    situacao = {"ABERTO": "aguardando a administração", "RESPONDIDO": "respondido"}
    linhas = [f"• #{c.numero:04d} – {c.assunto} – {situacao.get(c.status, c.status)}" for c in chamados]
    return "Seus chamados em andamento:\n" + "\n".join(linhas) + RODAPE


def abrir_chamado(database: Session, pessoa: Pessoa, texto: str) -> str:
    numero = (database.scalar(select(func.max(Chamado.numero)).where(Chamado.condominio_id == pessoa.condominio_id)) or 0) + 1
    assunto = texto.strip().split("\n")[0][:80] or "Mensagem pelo WhatsApp"
    if len(assunto) < 3:
        assunto = "Mensagem pelo WhatsApp"
    chamado = Chamado(
        condominio_id=pessoa.condominio_id, numero=numero, autor_user_id=pessoa.user_id, autor_pessoa_id=pessoa.id,
        autor_nome=pessoa.nome, assunto=f"[WhatsApp] {assunto}"[:150], categoria="OUTRO",
    )
    chamado.mensagens.append(ChamadoMensagem(autor_user_id=pessoa.user_id, autor_nome=pessoa.nome, texto=texto.strip()[:5000]))
    database.add(chamado)
    database.commit()
    return f"Chamado aberto! Protocolo *#{numero:04d}*. A administração vai responder em breve." + RODAPE


# =========================================================
# CÉREBRO DO ROBÔ
# =========================================================

def responder_bot(database: Session, conversa: WhatsappConversa, texto: str) -> str | None:
    # devolve a resposta do robô; None = passou para uma pessoa
    comando = texto.strip().lower()
    dados = dados_bot(conversa)
    pessoas = pessoas_do_telefone(database, conversa.telefone)

    if comando in PEDIR_PESSOA:
        return None

    # telefone em mais de um condomínio: pergunta qual
    pessoa = None
    if len(pessoas) == 1:
        pessoa = pessoas[0]
    elif len(pessoas) > 1:
        escolhida = dados.get("pessoa_id")
        pessoa = next((p for p in pessoas if str(p.id) == escolhida), None)
        if not pessoa:
            if dados.get("etapa") == "ESCOLHER_CONDOMINIO" and comando.isdigit() and 1 <= int(comando) <= len(pessoas):
                pessoa = pessoas[int(comando) - 1]
                salvar_dados(conversa, {"pessoa_id": str(pessoa.id)})
                return menu(pessoa, database, saudacao=True)
            salvar_dados(conversa, {"etapa": "ESCOLHER_CONDOMINIO"})
            opcoes = "\n".join(f"*{i}* – {nome_condominio(database, p.condominio_id)}" for i, p in enumerate(pessoas, 1))
            return f"Olá, {pessoas[0].nome.split()[0]}! Seu telefone está em mais de um condomínio. Sobre qual você quer falar?\n{opcoes}\n*0* – Falar com uma pessoa"

    if not pessoa:
        primeira = not dados.get("saudou")
        salvar_dados(conversa, {"saudou": True})
        return menu(None, database, saudacao=primeira)

    # aguardando a descrição do chamado
    if dados.get("etapa") == "CHAMADO":
        dados.pop("etapa", None)
        salvar_dados(conversa, dados)
        if comando in VOLTAR_MENU:
            return menu(pessoa, database, saudacao=False)
        return abrir_chamado(database, pessoa, texto)

    if comando == "1":
        return resposta_cotas(database, pessoa)
    if comando == "2":
        return resposta_avisos(database, pessoa)
    if comando == "3":
        salvar_dados(conversa, {**dados, "etapa": "CHAMADO"})
        return "Descreva em uma mensagem o que você precisa (ex.: vazamento na garagem, barulho no 302...).\nPara cancelar, digite *menu*."
    if comando == "4":
        return resposta_chamados(database, pessoa)

    primeira = not dados.get("saudou")
    salvar_dados(conversa, {**dados, "saudou": True})
    if not primeira and comando not in VOLTAR_MENU:
        return "Não entendi. 🙂\n\n" + menu(pessoa, database, saudacao=False)
    return menu(pessoa, database, saudacao=primeira)


def processar(database: Session, conversa: WhatsappConversa, mensagem: WhatsappMensagem):
    # chamado pelo webhook a cada mensagem recebida do contato
    agora = datetime.now(timezone.utc)

    # sem resposta do atendente há muito tempo: volta para o robô
    if conversa.modo == "ATENDENTE" and conversa.atendente_desde and agora - conversa.atendente_desde > timedelta(hours=settings.whatsapp_horas_atendente):
        conversa.modo = "ROBO"
        salvar_dados(conversa, {})

    if conversa.modo == "ATENDENTE" or not settings.whatsapp_robo_ativo:
        mensagem.para_atendente = True
        conversa.nao_lidas = (conversa.nao_lidas or 0) + 1
        database.commit()
        return

    resposta = responder_bot(database, conversa, mensagem.texto)
    if resposta is None:  # pediu uma pessoa
        conversa.modo = "ATENDENTE"
        conversa.atendente_desde = agora
        salvar_dados(conversa, {})
        mensagem.para_atendente = True
        conversa.nao_lidas = (conversa.nao_lidas or 0) + 1
        database.commit()
        enviar_e_registrar(database, conversa, "Certo! Vou chamar uma pessoa da administração. Aguarde que logo alguém responde por aqui. 🙂", NOME_ROBO)
        return
    database.commit()
    enviar_e_registrar(database, conversa, resposta, NOME_ROBO)
