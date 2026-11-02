# ---------------------------------------------------------
# RESPONSÁVEL DO WHATSAPP DE CADA PESSOA
# ---------------------------------------------------------
# pessoas.responsavel_user_id:
#   vazio .... SÍNDICO DO PRÉDIO (padrão; acompanha a troca de síndico)
#   preenchido um usuário marcado como RESPONSÁVEL (em Usuários)
# Quem recebe a mensagem de um telefone:
#   - o responsável de cada pessoa com esse telefone, ou o síndico
#     do condomínio dela quando o responsável é o padrão
#   - ninguém encontrado (número desconhecido, síndico sem login):
#     todos os usuários marcados como RESPONSÁVEL
# ---------------------------------------------------------

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.models import Pessoa, User, UserStatus


def variacoes_telefone(telefone: str) -> list[str]:
    # o WhatsApp manda 55 + DDD + número, às vezes sem o 9; o cadastro guarda DDD + número
    numeros = "".join(c for c in telefone if c.isdigit())
    local = numeros[2:] if numeros.startswith("55") and len(numeros) in (12, 13) else numeros
    opcoes = {local}
    if len(local) == 10:
        opcoes.add(local[:2] + "9" + local[2:])
    if len(local) == 11 and local[2] == "9":
        opcoes.add(local[:2] + local[3:])
    return list(opcoes)


def sindicos_com_login(database: Session, condominio_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    # síndicos ativos do condomínio que têm login ativo (só eles conseguem receber)
    return [(uid, nome) for uid, nome in database.execute(
        select(User.id, Pessoa.nome)
        .join(User, User.id == Pessoa.user_id)
        .where(Pessoa.condominio_id == condominio_id, Pessoa.perfil == "SINDICO", Pessoa.ativo.is_(True), User.status == UserStatus.ativo.value)
        .order_by(Pessoa.nome)
    ).all()]


def sindicos_do_condominio(database: Session, condominio_id: uuid.UUID) -> list[dict]:
    # todos os síndicos ativos, com ou sem login (sem login não recebe o WhatsApp)
    linhas = database.execute(
        select(Pessoa.id, Pessoa.nome, User.id, User.status)
        .outerjoin(User, User.id == Pessoa.user_id)
        .where(Pessoa.condominio_id == condominio_id, Pessoa.perfil == "SINDICO", Pessoa.ativo.is_(True))
        .order_by(Pessoa.nome)
    ).all()
    return [{"pessoa_id": pid, "nome": nome, "user_id": uid, "tem_login": bool(uid) and situacao == UserStatus.ativo.value}
            for pid, nome, uid, situacao in linhas]


def quem_recebe(responsavel: User | None, sindicos: list[dict]) -> tuple[str, list[str]]:
    # (origem, nomes) de quem recebe as mensagens de uma pessoa
    #   ESCOLHIDO: responsável definido | SINDICO: padrão | TODOS: síndico sem login ou sem síndico
    if responsavel:
        return "ESCOLHIDO", [responsavel.full_name]
    com_login = [s["nome"] for s in sindicos if s["tem_login"]]
    if com_login:
        return "SINDICO", com_login
    return "TODOS", ["Todos os responsáveis cadastrados"]


def responsaveis_cadastrados(database: Session) -> list[User]:
    return list(database.scalars(
        select(User).where(User.responsavel.is_(True), User.status == UserStatus.ativo.value).order_by(User.full_name)
    ).all())


def validar_responsavel_escolhido(database: Session, user_id: uuid.UUID | None):
    if user_id is None:
        return  # síndico do prédio
    usuario = database.get(User, user_id)
    if not usuario or not usuario.responsavel:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Escolha o síndico do prédio ou um usuário marcado como responsável (em Usuários)")


def destinatarios_do_telefone(database: Session, telefone: str | None, cache: dict) -> set[uuid.UUID]:
    # vazio = ninguém definido: a mensagem vai para todos os RESPONSÁVEIS
    if not telefone:
        return set()
    if telefone in cache:
        return cache[telefone]
    destinos: set[uuid.UUID] = set()
    sindicos_cache = cache.setdefault("__sindicos__", {})
    for condominio_id, responsavel_id in database.execute(
        select(Pessoa.condominio_id, Pessoa.responsavel_user_id).where(Pessoa.telefone.in_(variacoes_telefone(telefone)), Pessoa.ativo.is_(True))
    ).all():
        if responsavel_id:
            destinos.add(responsavel_id)
        else:
            if condominio_id not in sindicos_cache:
                sindicos_cache[condominio_id] = {uid for uid, _ in sindicos_com_login(database, condominio_id)}
            destinos |= sindicos_cache[condominio_id]
    cache[telefone] = destinos
    return destinos


def e_sindico(database: Session, usuario: User) -> bool:
    return bool(database.scalar(
        select(Pessoa.id).where(Pessoa.user_id == usuario.id, Pessoa.perfil == "SINDICO", Pessoa.ativo.is_(True)).limit(1)
    ))


def recebe_mensagem(usuario: User, destinos: set[uuid.UUID]) -> bool:
    # destinos definidos: só eles; nenhum: todos os RESPONSÁVEIS
    return usuario.id in destinos if destinos else usuario.responsavel
