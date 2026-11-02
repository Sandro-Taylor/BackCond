# ---------------------------------------------------------
# ARQUIVOS (GOOGLE DRIVE)
# ---------------------------------------------------------
# ADM do sistema:
#   - conecta/desconecta a conta Google (OAuth, uma vez)
#   - navega no Drive inteiro da conta, envia, renomeia, baixa e
#     exclui (vai para a lixeira do Drive)
#   - o que o sistema cria fica na pasta "Gerenciador"
# Síndico (e ADM do condomínio): vê e mexe em todo o Drive, como o ADM
#   (não conecta/desconecta). Demais perfis: sem acesso.
# Sistema todo:
#   - foto da pessoa: guardada em Gerenciador/<condomínio>/fotos-pessoas
#   - GET /arquivos/{id}: entrega o arquivo para quem tem acesso
#     (o navegador nunca acessa o Drive direto; não há link público)
# Envio de arquivo: corpo bruto da requisição (sem multipart),
# nome em X-Nome-Arquivo e tipo em Content-Type.
# ---------------------------------------------------------

import uuid
from uuid import UUID
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlencode

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from App import drive
from App.database import get_database
from App.dependencies import Contexto, apartamentos_do_usuario, exigir_admin_sistema, get_contexto, get_current_user, negar
from App.models import Arquivo, Condominio, DriveConexao, Pessoa, PessoaApartamento, User
from config import settings

router = APIRouter()

LIMITE_FOTO = 5 * 1024 * 1024
LIMITE_ARQUIVO = 25 * 1024 * 1024
TIPOS_FOTO = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


# =========================================================
# DADOS
# =========================================================

class StatusDrive(BaseModel):
    configurado: bool        # GOOGLE_CLIENT_ID e SECRET no .env
    conectado: bool
    email: str | None = None
    usado: int | None = None
    limite: int | None = None
    erro: str | None = None


class ItemDrive(BaseModel):
    id: str
    nome: str
    mime: str
    pasta: bool
    tamanho: int | None
    modificado_em: datetime | None
    uso_no_sistema: str | None   # ex.: "Foto de Ana" (None = não ligado a nada)
    link_web: str | None = None  # abrir no Google (Drive/Planilhas/Documentos)


class PastaDrive(BaseModel):
    id: str
    nome: str


class Navegacao(BaseModel):
    pasta: PastaDrive
    caminho: list[PastaDrive]    # da raiz até a pasta atual
    itens: list[ItemDrive]


class NovaPasta(BaseModel):
    pai: str
    nome: str = Field(min_length=1, max_length=120)


class Renomear(BaseModel):
    nome: str = Field(min_length=1, max_length=255)


class FotoResposta(BaseModel):
    foto_arquivo_id: uuid.UUID | None


# =========================================================
# AUXILIARES
# =========================================================

async def ler_envio(request: Request, limite: int) -> tuple[str, str, bytes]:
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum arquivo enviado")
    if len(conteudo) > limite:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Arquivo maior que {limite // (1024 * 1024)} MB")
    nome = unquote(request.headers.get("x-nome-arquivo", "")).strip() or "arquivo"
    mime = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    return nome[:255], mime, conteudo


def resposta_arquivo(dados: bytes, mime: str, nome: str | None = None, baixar: bool = False) -> Response:
    cabecalhos = {"Cache-Control": "private, max-age=3600"}
    if baixar and nome:
        cabecalhos["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(nome)}"
    return Response(content=dados, media_type=mime, headers=cabecalhos)


def uso_no_sistema(database: Session, drive_ids: list[str]) -> dict:
    if not drive_ids:
        return {}
    arquivos = database.scalars(select(Arquivo).where(Arquivo.drive_id.in_(drive_ids))).all()
    fotos = {a.id: a.drive_id for a in arquivos}
    resultado = {a.drive_id: "Enviado pela administração" if a.categoria == "ADMIN" else "Arquivo do sistema" for a in arquivos}
    if fotos:
        for nome, foto_id in database.execute(select(Pessoa.nome, Pessoa.foto_arquivo_id).where(Pessoa.foto_arquivo_id.in_(list(fotos)))).all():
            resultado[fotos[foto_id]] = f"Foto de {nome}"
    return resultado


@dataclass
class Escopo:
    # onde o usuário pode mexer no Drive: raiz None = Drive inteiro (ADM do sistema)
    usuario: User
    raiz: str | None = None
    nome_raiz: str = "Meu Drive"


def escopo_drive(
    database: Session = Depends(get_database), usuario: User = Depends(get_current_user),
    x_condominio_id: UUID | None = Header(default=None),
) -> Escopo:
    if usuario.admin_sistema:
        return Escopo(usuario)
    if not x_condominio_id:
        negar()
    ctx = get_contexto(x_condominio_id, usuario, database)
    if not ctx.edita_tudo:  # só síndico ou ADM do condomínio
        negar()
    return Escopo(usuario)  # Drive inteiro


def caminho_ate(database: Session, pasta_id: str, escopo: Escopo | None = None) -> list[dict]:
    # da raiz permitida ("Meu Drive" ou a pasta do condomínio) até a pasta
    # (itens compartilhados podem não ter caminho completo)
    raiz = escopo.raiz if escopo and escopo.raiz else drive.raiz_do_drive(database)
    nome_raiz = escopo.nome_raiz if escopo and escopo.raiz else "Meu Drive"
    caminho, atual = [], pasta_id
    for _ in range(25):  # limite de segurança
        if atual == raiz:
            caminho.append({"id": raiz, "nome": nome_raiz})
            break
        dados = drive.info(database, atual)
        caminho.append({"id": dados["id"], "nome": dados.get("name", "")})
        pais = dados.get("parents") or []
        if not pais:
            break
        atual = pais[0]
    return list(reversed(caminho))


def exigir_dentro(database: Session, escopo: Escopo, drive_id: str, permite_raiz: bool = True):
    # síndico: o item tem que estar dentro da pasta do condomínio
    if escopo.raiz is None:
        return
    if drive_id == escopo.raiz:
        if permite_raiz:
            return
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A pasta do condomínio não pode ser alterada")
    caminho = caminho_ate(database, drive_id, escopo)
    if not caminho or caminho[0]["id"] != escopo.raiz:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este arquivo não é da pasta do condomínio")


def pode_editar_pessoa(database: Session, ctx: Contexto, pessoa: Pessoa) -> bool:
    if ctx.edita_tudo:
        return True
    if ctx.perfil != "MORADOR":
        return False
    return bool(database.scalar(select(PessoaApartamento.id).where(
        PessoaApartamento.pessoa_id == pessoa.id, PessoaApartamento.apartamento_id.in_(apartamentos_do_usuario(database, ctx)),
    )))


# =========================================================
# CONEXÃO COM A CONTA GOOGLE (ADM)
# =========================================================

@router.get("/drive/status", response_model=StatusDrive)
def statusDrive(database: Session = Depends(get_database), usuario: User = Depends(get_current_user)):
    if not drive.configurado():
        return {"configurado": False, "conectado": False, "erro": "Preencha GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env do backend e reinicie"}
    atual = drive.conexao(database)
    if not atual:
        return {"configurado": True, "conectado": False}
    if not usuario.admin_sistema:
        return {"configurado": True, "conectado": True}  # síndico: só se está conectado
    try:
        return {"configurado": True, "conectado": True, **drive.uso(database)}
    except HTTPException as erro:
        return {"configurado": True, "conectado": True, "email": atual.email, "erro": erro.detail}


@router.post("/drive/conectar")
def conectarDrive(admin: User = Depends(exigir_admin_sistema)):
    if not drive.configurado():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Preencha GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env do backend e reinicie")
    estado = jwt.encode(
        {"sub": str(admin.id), "uso": "drive", "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    return {"url": drive.url_autorizacao(estado)}


@router.get("/drive/callback", include_in_schema=False)
def callbackDrive(code: str | None = None, state: str | None = None, error: str | None = None, database: Session = Depends(get_database)):
    # o Google volta aqui depois do login; no fim, devolve o navegador para a página Arquivos
    def voltar(**parametros):
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/Drive?{urlencode(parametros)}")

    if error or not code or not state:
        return voltar(drive="erro", mensagem=error or "Autorização cancelada")
    try:
        carga = jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        admin = database.get(User, uuid.UUID(carga["sub"]))
        if carga.get("uso") != "drive" or not admin or not admin.admin_sistema:
            raise ValueError
    except (jwt.InvalidTokenError, ValueError, KeyError):
        return voltar(drive="erro", mensagem="Pedido de conexão inválido ou expirado. Tente de novo")

    try:
        tokens = drive.trocar_codigo(code)
    except drive.ErroDrive as erro:
        return voltar(drive="erro", mensagem=str(erro))
    if drive.ESCOPO_DRIVE not in (tokens.get("scope") or "").split():
        drive.revogar(tokens.get("refresh_token") or tokens.get("access_token", ""))
        return voltar(drive="erro", mensagem="Faltou permitir o acesso ao Drive. Clique em Conectar de novo e, na tela do Google, MARQUE a caixa do Google Drive antes de continuar")
    if not tokens.get("refresh_token"):
        return voltar(drive="erro", mensagem="O Google não enviou a autorização permanente. Remova o acesso do app na sua conta Google e conecte de novo")

    atual = drive.conexao(database) or DriveConexao(id=1, refresh_token="")
    atual.refresh_token = tokens["refresh_token"]
    atual.access_token = tokens.get("access_token")
    atual.expira_em = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    atual.email = drive.email_do_token(tokens.get("id_token"))
    atual.conectado_por_user_id = admin.id
    atual.pasta_raiz_id = None  # conta nova: cria a pasta Gerenciador
    database.merge(atual)
    database.commit()
    drive.limpar_cache()
    try:
        drive.pasta_raiz(database)
    except HTTPException as erro:
        return voltar(drive="erro", mensagem=str(erro.detail))
    return voltar(drive="conectado")


@router.post("/drive/desconectar", status_code=status.HTTP_204_NO_CONTENT)
def desconectarDrive(database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    atual = drive.conexao(database)
    if atual:
        drive.revogar(atual.refresh_token)
        database.delete(atual)
        database.commit()
    drive.limpar_cache()


# =========================================================
# NAVEGAR E GERENCIAR (ADM: Drive inteiro; síndico: pasta do condomínio)
# =========================================================

@router.get("/drive/navegar", response_model=Navegacao)
def navegar(pasta: str | None = None, database: Session = Depends(get_database), escopo: Escopo = Depends(escopo_drive)):
    pasta_sistema = drive.pasta_raiz(database)
    pasta_id = pasta or escopo.raiz or drive.raiz_do_drive(database)
    exigir_dentro(database, escopo, pasta_id)
    caminho = caminho_ate(database, pasta_id, escopo)
    itens = drive.listar(database, pasta_id)
    usos = uso_no_sistema(database, [i["id"] for i in itens])
    usos[pasta_sistema] = "Pasta do sistema"
    return {
        "pasta": caminho[-1], "caminho": caminho,
        "itens": [{
            "id": i["id"], "nome": i.get("name", ""), "mime": i.get("mimeType", ""), "pasta": i.get("mimeType") == drive.PASTA,
            "tamanho": int(i["size"]) if i.get("size") else None, "modificado_em": i.get("modifiedTime"),
            "uso_no_sistema": usos.get(i["id"]), "link_web": i.get("webViewLink"),
        } for i in itens],
    }


@router.post("/drive/pastas", response_model=PastaDrive, status_code=status.HTTP_201_CREATED)
def criarPasta(dados: NovaPasta, database: Session = Depends(get_database), escopo: Escopo = Depends(escopo_drive)):
    exigir_dentro(database, escopo, dados.pai)
    return {"id": drive.criar_pasta(database, dados.nome.strip(), dados.pai), "nome": dados.nome.strip()}


@router.post("/drive/enviar", response_model=ItemDrive, status_code=status.HTTP_201_CREATED)
async def enviarArquivo(request: Request, pasta: str = Query(...), database: Session = Depends(get_database), escopo: Escopo = Depends(escopo_drive)):
    exigir_dentro(database, escopo, pasta)
    nome, mime, conteudo = await ler_envio(request, LIMITE_ARQUIVO)
    criado = drive.enviar(database, nome, mime, conteudo, pasta)
    database.add(Arquivo(drive_id=criado["id"], nome=nome, mime=mime, tamanho=len(conteudo), categoria="ADMIN", enviado_por_user_id=escopo.usuario.id))
    database.commit()
    return {
        "id": criado["id"], "nome": nome, "mime": mime, "pasta": False, "tamanho": len(conteudo),
        "modificado_em": criado.get("modifiedTime"), "uso_no_sistema": "Enviado pela administração", "link_web": criado.get("webViewLink"),
    }


@router.get("/drive/itens/{drive_id}/conteudo", include_in_schema=False)
def conteudoItem(drive_id: str, baixar: bool = False, database: Session = Depends(get_database), escopo: Escopo = Depends(escopo_drive)):
    exigir_dentro(database, escopo, drive_id)
    item = drive.info(database, drive_id)
    dados, mime = drive.baixar_com_cache(database, drive_id, item.get("mimeType"))
    nome = item.get("name") or "arquivo"
    if item.get("mimeType") in drive.EXPORTAR:
        nome = f"{nome}.{drive.EXPORTAR[item['mimeType']][1]}"
    return resposta_arquivo(dados, mime, nome, baixar)


@router.patch("/drive/itens/{drive_id}", status_code=status.HTTP_204_NO_CONTENT)
def renomearItem(drive_id: str, dados: Renomear, database: Session = Depends(get_database), escopo: Escopo = Depends(escopo_drive)):
    exigir_dentro(database, escopo, drive_id, permite_raiz=False)
    drive.renomear(database, drive_id, dados.nome.strip())
    arquivo = database.scalar(select(Arquivo).where(Arquivo.drive_id == drive_id))
    if arquivo:
        arquivo.nome = dados.nome.strip()
        database.commit()
    drive.limpar_cache()


@router.delete("/drive/itens/{drive_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirItem(drive_id: str, database: Session = Depends(get_database), escopo: Escopo = Depends(escopo_drive)):
    exigir_dentro(database, escopo, drive_id, permite_raiz=False)
    if drive_id == drive.pasta_raiz(database):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A pasta Gerenciador é usada pelo sistema e não pode ser excluída")
    drive.excluir(database, drive_id)
    arquivo = database.scalar(select(Arquivo).where(Arquivo.drive_id == drive_id))
    if arquivo:
        database.delete(arquivo)  # a foto ligada a ele some da pessoa (ON DELETE SET NULL)
        database.commit()
    drive.esquecer(drive_id)
    drive.limpar_cache()


# =========================================================
# ENTREGAR ARQUIVO DO SISTEMA (qualquer usuário com acesso)
# =========================================================

@router.get("/arquivos/{arquivo_id}", include_in_schema=False)
def verArquivo(arquivo_id: uuid.UUID, database: Session = Depends(get_database), usuario: User = Depends(get_current_user)):
    arquivo = database.get(Arquivo, arquivo_id)
    if not arquivo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não encontrado")
    # ADM e responsáveis (atendem vários condomínios) veem tudo; os demais, só do próprio condomínio
    if not (usuario.admin_sistema or usuario.responsavel):
        do_condominio = arquivo.condominio_id and database.scalar(select(Pessoa.id).where(
            Pessoa.condominio_id == arquivo.condominio_id, Pessoa.user_id == usuario.id, Pessoa.ativo.is_(True),
        ))
        if not do_condominio:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não encontrado")
    dados, mime = drive.baixar_com_cache(database, arquivo.drive_id)
    return resposta_arquivo(dados, mime or arquivo.mime)


# =========================================================
# FOTO DA PESSOA
# =========================================================

@router.post("/pessoas/{pessoa_id}/foto", response_model=FotoResposta)
async def enviarFoto(pessoa_id: uuid.UUID, request: Request, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    pessoa = database.scalar(select(Pessoa).where(Pessoa.id == pessoa_id, Pessoa.condominio_id == ctx.condominio_id))
    if not pessoa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada")
    if not pode_editar_pessoa(database, ctx, pessoa):
        negar()
    _, mime, conteudo = await ler_envio(request, LIMITE_FOTO)
    if mime not in TIPOS_FOTO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Envie uma imagem JPG, PNG ou WEBP")

    condominio = database.get(Condominio, ctx.condominio_id)
    pasta = drive.pasta_do_caminho(database, condominio.nome if condominio else "sem-condominio", "fotos-pessoas")
    nome = f"{pessoa.nome} - {str(pessoa.id)[:8]}.{TIPOS_FOTO[mime]}"
    criado = drive.enviar(database, nome, mime, conteudo, pasta)

    anterior = database.get(Arquivo, pessoa.foto_arquivo_id) if pessoa.foto_arquivo_id else None
    novo = Arquivo(drive_id=criado["id"], nome=nome, mime=mime, tamanho=len(conteudo), categoria="FOTO_PESSOA",
                   condominio_id=ctx.condominio_id, enviado_por_user_id=ctx.usuario.id)
    database.add(novo)
    database.flush()
    pessoa.foto_arquivo_id = novo.id
    if anterior:
        database.delete(anterior)
    database.commit()
    if anterior:
        drive.excluir(database, anterior.drive_id)
        drive.esquecer(anterior.drive_id)
    return {"foto_arquivo_id": novo.id}


@router.delete("/pessoas/{pessoa_id}/foto", response_model=FotoResposta)
def removerFoto(pessoa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    pessoa = database.scalar(select(Pessoa).where(Pessoa.id == pessoa_id, Pessoa.condominio_id == ctx.condominio_id))
    if not pessoa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada")
    if not pode_editar_pessoa(database, ctx, pessoa):
        negar()
    anterior = database.get(Arquivo, pessoa.foto_arquivo_id) if pessoa.foto_arquivo_id else None
    pessoa.foto_arquivo_id = None
    if anterior:
        database.delete(anterior)
    database.commit()
    if anterior:
        drive.excluir(database, anterior.drive_id)
        drive.esquecer(anterior.drive_id)
    return {"foto_arquivo_id": None}
