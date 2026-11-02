# ---------------------------------------------------------
# DEPENDÊNCIAS DA API
# ---------------------------------------------------------
# get_usuario_logado   -> usuário logado (token válido e ativo)
# get_current_user     -> idem, mas bloqueia quem ainda precisa
#                         trocar a senha temporária
# get_contexto         -> usuário + condomínio que ele está
#                         acessando + perfil dele nesse condomínio
# exigir_admin_sistema -> só o ADM do sistema passa
# exigir_responsavel   -> só o RESPONSÁVEL (recebe o WhatsApp)
# exigir_acesso_whatsapp -> ADM do sistema, RESPONSÁVEL ou SÍNDICO
#
# PERMISSÕES POR PERFIL (dentro do condomínio)
#   ADM, SINDICO ............ veem e editam tudo
#   CONSELHEIRO, FUNCIONARIO  veem tudo, não editam
#   MORADOR ................. vê e edita só as próprias unidades
#                             (pessoas, veículos); vagas só vê
#   PRESTADOR ............... só a página inicial
# Síndico e conselheiros são designados só pelo ADM do sistema.
#
# RESPONSÁVEL DO WHATSAPP: cada pessoa tem um (App/responsaveis.py).
#   Padrão: o síndico do prédio. Ou um usuário marcado como
#   RESPONSÁVEL pelo ADM em Usuários. Quem é o responsável
#   recebe o pop-up das mensagens daquela pessoa e responde.
#   O ADM conecta o número e vê todas as conversas.
#
# FINANCEIRO
#   ADM, SINDICO ............ veem e lançam tudo
#   CONSELHEIRO ............. vê tudo, não lança
#   MORADOR ................. vê só as cotas das próprias unidades
#   FUNCIONARIO, PRESTADOR .. sem acesso
# ---------------------------------------------------------

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from App.database import get_database
from App.models import Condominio, Pessoa, PessoaApartamento, User, UserStatus
from App.security import decode_access_token

authentication = HTTPBearer()


def get_usuario_logado(credentials: HTTPAuthorizationCredentials = Depends(authentication), database: Session = Depends(get_database)) -> User:
    try:
        user_uuid = UUID(decode_access_token(credentials.credentials))
    except (InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")

    user = database.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")

    if user.status != UserStatus.ativo.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário sem acesso ao sistema")

    return user


def get_current_user(usuario: User = Depends(get_usuario_logado)) -> User:
    # enquanto a senha for temporária, só /eu e /eu/senha funcionam
    if usuario.trocar_senha:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Troque sua senha temporária antes de continuar")
    return usuario


PERFIS_EDITAM_TUDO = {"ADM", "SINDICO"}
PERFIS_VEEM_TUDO = {"ADM", "SINDICO", "CONSELHEIRO", "FUNCIONARIO"}
PERFIS_VEEM_FINANCEIRO = {"ADM", "SINDICO", "CONSELHEIRO"}
PERFIS_SO_ADM = {"SINDICO", "CONSELHEIRO"}  # cargos eleitos: só o ADM do sistema atribui ou retira
SEM_PERMISSAO = "Seu perfil não tem permissão para esta ação"


@dataclass
class Contexto:
    usuario: User
    condominio_id: UUID
    pessoa: Pessoa | None  # None quando é o ADM do sistema sem cadastro nesse condomínio
    perfil: str            # "ADM" para o ADM do sistema; senão, o perfil da pessoa

    @property
    def edita_tudo(self) -> bool:
        return self.perfil in PERFIS_EDITAM_TUDO

    @property
    def ve_tudo(self) -> bool:
        return self.perfil in PERFIS_VEEM_TUDO

    @property
    def ve_financeiro_tudo(self) -> bool:
        return self.perfil in PERFIS_VEEM_FINANCEIRO


def get_contexto(
    x_condominio_id: UUID = Header(description="Id do condomínio que está sendo acessado"),
    usuario: User = Depends(get_current_user),
    database: Session = Depends(get_database),
) -> Contexto:
    condominio = database.get(Condominio, x_condominio_id)
    if not condominio or (not condominio.ativo and not usuario.admin_sistema):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")

    pessoa = database.scalar(
        select(Pessoa).where(
            Pessoa.condominio_id == x_condominio_id,
            Pessoa.user_id == usuario.id,
            Pessoa.ativo.is_(True),
        )
    )

    if usuario.admin_sistema:
        return Contexto(usuario=usuario, condominio_id=x_condominio_id, pessoa=pessoa, perfil="ADM")

    if not pessoa:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem acesso a este condomínio")

    return Contexto(usuario=usuario, condominio_id=x_condominio_id, pessoa=pessoa, perfil=pessoa.perfil)


def exigir_admin_sistema(usuario: User = Depends(get_current_user)) -> User:
    if not usuario.admin_sistema:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o administrador do sistema pode fazer isso")
    return usuario


# =========================================================
# PERMISSÕES
# =========================================================

def negar():
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SEM_PERMISSAO)


def exigir_adm_para_perfil(ctx: Contexto, *perfis: str | None):
    # síndico e conselheiro são designados pelo ADM do sistema (o síndico não se promove nem promove outros)
    if not ctx.usuario.admin_sistema and any(perfil in PERFIS_SO_ADM for perfil in perfis):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Somente o administrador do sistema pode designar ou alterar síndico e conselheiros")


def exigir_gestao(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    # ADM ou síndico
    if not ctx.edita_tudo:
        negar()
    return ctx


def exigir_leitura_geral(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    # quem vê tudo do condomínio (não inclui morador nem prestador)
    if not ctx.ve_tudo:
        negar()
    return ctx


def apartamentos_do_usuario(database: Session, ctx: Contexto) -> set[UUID]:
    # unidades às quais a pessoa logada está ligada (vínculo ativo)
    if not ctx.pessoa:
        return set()
    return set(database.scalars(
        select(PessoaApartamento.apartamento_id).where(
            PessoaApartamento.pessoa_id == ctx.pessoa.id,
            PessoaApartamento.ativo.is_(True),
        )
    ).all())


def pode_editar_apartamento(database: Session, ctx: Contexto, apartamento_id: UUID) -> bool:
    if ctx.edita_tudo:
        return True
    return ctx.perfil == "MORADOR" and apartamento_id in apartamentos_do_usuario(database, ctx)


def exigir_edicao_apartamento(database: Session, ctx: Contexto, apartamento_id: UUID):
    if not pode_editar_apartamento(database, ctx, apartamento_id):
        negar()


def exigir_leitura_apartamento(database: Session, ctx: Contexto, apartamento_id: UUID):
    if ctx.ve_tudo:
        return
    if ctx.perfil == "MORADOR" and apartamento_id in apartamentos_do_usuario(database, ctx):
        return
    negar()


def exigir_financeiro(ctx: Contexto = Depends(get_contexto)) -> Contexto:
    # entra na área financeira: quem vê tudo ou o morador (só as próprias unidades)
    if not ctx.ve_financeiro_tudo and ctx.perfil != "MORADOR":
        negar()
    return ctx


# =========================================================
# WHATSAPP
# =========================================================

def exigir_responsavel(usuario: User = Depends(get_current_user)) -> User:
    if not usuario.responsavel:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o responsável recebe as mensagens do WhatsApp")
    return usuario


def exigir_acesso_whatsapp(usuario: User = Depends(get_current_user), database: Session = Depends(get_database)) -> User:
    from App.responsaveis import e_sindico
    if not (usuario.admin_sistema or usuario.responsavel or e_sindico(database, usuario)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas o administrador, os responsáveis e os síndicos acessam o WhatsApp")
    return usuario
