# ---------------------------------------------------------
# ADMINISTRAÇÃO GERAL (só o ADM do sistema)
# ---------------------------------------------------------
# Visão geral: todos os condomínios, com síndicos e números.
# Condomínio selecionado: todos os apartamentos com as pessoas
# ligadas e tudo o que o sistema tem sobre cada uma (cadastro,
# vínculo, veículos, vagas, cotas em aberto, chamados e
# WhatsApp). O ADM edita os dados direto nesta tela e define o
# RESPONSÁVEL do WhatsApp de cada pessoa (só o ADM pode).
# Responsáveis: pessoas de fora dos condomínios (sem apartamento),
# criadas aqui com login próprio, que atendem o WhatsApp.
# Regra de quem recebe: App/responsaveis.py.
# ---------------------------------------------------------

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from App.acesso import gerar_senha_temporaria
from App.consultas import garantir_unico, salvar
from App.database import get_database
from App.dependencies import exigir_admin_sistema
from App.models import Apartamento, Chamado, Condominio, Cota, Pessoa, PessoaApartamento, User, UserStatus, Veiculo, WhatsappConversa
from App.responsaveis import quem_recebe, responsaveis_cadastrados, sindicos_do_condominio, validar_responsavel_escolhido, variacoes_telefone
from App.security import hash_password
from App.validacoes import normalizar_cpf, normalizar_email, normalizar_telefone
from Router.Vagas import rotulo_apartamento

router = APIRouter(prefix="/administracao")

PERFIS_MORADORES = {"MORADOR", "SINDICO", "CONSELHEIRO"}


# =========================================================
# DADOS
# =========================================================

class ResponsavelResumo(BaseModel):
    id: uuid.UUID
    nome: str
    email: str


class SindicoVisao(BaseModel):
    pessoa_id: uuid.UUID
    nome: str
    telefone: str | None
    email: str | None
    tem_login: bool = False   # sem login o síndico não recebe o WhatsApp


class CondominioVisao(BaseModel):
    id: uuid.UUID
    nome: str
    cidade: str | None
    uf: str | None
    ativo: bool
    sindicos: list[SindicoVisao]
    total_apartamentos: int
    total_moradores: int
    sem_responsavel: int      # moradores no padrão (síndico do prédio)


class VeiculoInfo(BaseModel):
    placa: str | None
    marca: str | None
    modelo: str | None
    cor: str | None
    condutor: str | None
    vaga: str | None


class VagaInfo(BaseModel):
    numero: str
    tipo: str
    localizacao: str | None


class FinanceiroInfo(BaseModel):
    cotas_abertas: int
    cotas_atrasadas: int
    valor_em_aberto: float


class ChamadoInfo(BaseModel):
    id: uuid.UUID
    numero: int
    assunto: str
    status: str
    updated_at: datetime


class WhatsappInfo(BaseModel):
    conversa_id: uuid.UUID
    nome: str | None
    nao_lidas: int
    ultima_mensagem: str | None
    ultima_mensagem_em: datetime


class PessoaAdmin(BaseModel):
    id: uuid.UUID
    nome: str
    perfil: str
    cpf: str | None
    email: str | None
    telefone: str | None
    data_nascimento: date | None
    foto_arquivo_id: uuid.UUID | None
    tem_login: bool
    login_status: str | None
    responsavel: ResponsavelResumo | None      # None = padrão (síndico do prédio)
    recebe_origem: str                         # ESCOLHIDO, SINDICO ou TODOS
    recebe_nomes: list[str]                    # quem recebe as mensagens de fato
    chamados_abertos: list[ChamadoInfo]
    whatsapp: WhatsappInfo | None
    created_at: datetime


class PessoaNaUnidade(BaseModel):
    vinculo_id: uuid.UUID
    tipo_relacao: str
    reside: bool
    parentesco: str | None
    principal: bool
    titular_nome: str | None
    pessoa: PessoaAdmin


class ApartamentoAdmin(BaseModel):
    id: uuid.UUID
    rotulo: str
    bloco: str
    numero: str
    andar: int | None
    observacao: str | None
    ocupacao: str             # OCUPADO_PROPRIETARIO, ALUGADO ou VAZIO
    pessoas: list[PessoaNaUnidade]
    veiculos: list[VeiculoInfo]
    vagas: list[VagaInfo]
    financeiro: FinanceiroInfo


class CondominioDetalhe(BaseModel):
    id: uuid.UUID
    nome: str
    sindicos: list[SindicoVisao]
    responsaveis_disponiveis: list[ResponsavelResumo]
    apartamentos: list[ApartamentoAdmin]
    sem_unidade: list[PessoaAdmin]   # síndico, conselheiro ou morador sem apartamento ligado


class DefinirResponsavel(BaseModel):
    responsavel_user_id: uuid.UUID | None   # None = síndico do prédio (padrão)


class AplicarResponsavel(BaseModel):
    responsavel_user_id: uuid.UUID
    somente_sem_responsavel: bool = True


class EditarPessoaAdmin(BaseModel):
    # só os campos enviados são alterados
    nome: str | None = Field(default=None, min_length=3, max_length=150)
    cpf: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    data_nascimento: date | None = None
    responsavel_user_id: uuid.UUID | None = None

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, valor):
        return normalizar_cpf(valor)

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, valor):
        return normalizar_telefone(valor)

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class ResponsavelLista(BaseModel):
    id: uuid.UUID
    nome: str
    email: str
    status: str
    trocar_senha: bool
    total_pessoas: int        # pessoas que têm este responsável
    created_at: datetime


class CriarResponsavel(BaseModel):
    nome: str = Field(min_length=3, max_length=150)
    email: EmailStr


class ResponsavelCriado(BaseModel):
    id: uuid.UUID
    nome: str
    email: str
    senha_temporaria: str | None   # None quando o e-mail já tinha login
    login_existente: bool


# =========================================================
# AUXILIARES
# =========================================================

def resumo_responsavel(usuario: User | None) -> dict | None:
    return {"id": usuario.id, "nome": usuario.full_name, "email": usuario.email} if usuario else None


def e_morador(pessoa: Pessoa) -> bool:
    return pessoa.perfil in PERFIS_MORADORES or any(v.ativo for v in pessoa.apartamentos)


def sindicos_do(pessoas: list[Pessoa]) -> list[dict]:
    return [{
        "pessoa_id": p.id, "nome": p.nome, "telefone": p.telefone, "email": p.email,
        "tem_login": bool(p.usuario and p.usuario.status == UserStatus.ativo.value),
    } for p in pessoas if p.perfil == "SINDICO" and p.ativo]


def ocupacao(vinculos: list[PessoaApartamento]) -> str:
    ativos = [v for v in vinculos if v.ativo]
    if any(v.tipo_relacao == "INQUILINO" for v in ativos):
        return "ALUGADO"
    if any(v.tipo_relacao == "PROPRIETARIO" and v.reside for v in ativos):
        return "OCUPADO_PROPRIETARIO"
    return "VAZIO"


def ordem_vinculo(v: PessoaApartamento):
    return ({"PROPRIETARIO": 0, "INQUILINO": 1}.get(v.tipo_relacao, 2), v.pessoa.nome if v.pessoa else "")


# =========================================================
# VISÃO GERAL
# =========================================================

@router.get("/visao-geral", response_model=list[CondominioVisao])
def visaoGeral(database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    condominios = database.scalars(select(Condominio).order_by(Condominio.ativo.desc(), Condominio.nome)).all()
    pessoas = database.scalars(
        select(Pessoa).where(Pessoa.ativo.is_(True)).options(selectinload(Pessoa.apartamentos), selectinload(Pessoa.usuario))
    ).all()
    total_aptos = dict(database.execute(
        select(Apartamento.condominio_id, func.count()).where(Apartamento.ativo.is_(True)).group_by(Apartamento.condominio_id)
    ).all())
    por_condominio: dict = {}
    for p in pessoas:
        por_condominio.setdefault(p.condominio_id, []).append(p)

    resultado = []
    for c in condominios:
        lista = por_condominio.get(c.id, [])
        moradores = [p for p in lista if e_morador(p)]
        resultado.append({
            "id": c.id, "nome": c.nome, "cidade": c.cidade, "uf": c.uf, "ativo": c.ativo,
            "sindicos": sindicos_do(lista), "total_apartamentos": total_aptos.get(c.id, 0),
            "total_moradores": len(moradores),
            "sem_responsavel": sum(1 for p in moradores if p.responsavel_user_id is None),
        })
    return resultado


# =========================================================
# CONDOMÍNIO: APARTAMENTOS, PESSOAS E TUDO SOBRE ELAS
# =========================================================

@router.get("/condominios/{condominio_id}", response_model=CondominioDetalhe)
def detalheCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    condominio = database.get(Condominio, condominio_id)
    if not condominio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")

    apartamentos = database.scalars(
        select(Apartamento)
        .where(Apartamento.condominio_id == condominio_id, Apartamento.ativo.is_(True))
        .options(
            selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa).selectinload(Pessoa.usuario),
            selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa).selectinload(Pessoa.responsavel),
            selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.titular).selectinload(PessoaApartamento.pessoa),
            selectinload(Apartamento.veiculos).selectinload(Veiculo.pessoa),
            selectinload(Apartamento.veiculos).selectinload(Veiculo.vaga),
            selectinload(Apartamento.vagas),
        )
    ).all()
    apartamentos = sorted(apartamentos, key=lambda a: (a.bloco, len(a.numero), a.numero))

    pessoas = database.scalars(
        select(Pessoa).where(Pessoa.condominio_id == condominio_id, Pessoa.ativo.is_(True))
        .options(selectinload(Pessoa.usuario), selectinload(Pessoa.responsavel), selectinload(Pessoa.apartamentos))
        .order_by(Pessoa.nome)
    ).all()

    # cotas em aberto por apartamento
    hoje = date.today()
    financeiro: dict = {}
    for apto_id, abertas, atrasadas, total in database.execute(
        select(Cota.apartamento_id, func.count(), func.count().filter(Cota.vencimento < hoje), func.coalesce(func.sum(Cota.valor), 0))
        .where(Cota.condominio_id == condominio_id, Cota.status == "ABERTA").group_by(Cota.apartamento_id)
    ).all():
        financeiro[apto_id] = {"cotas_abertas": abertas, "cotas_atrasadas": atrasadas, "valor_em_aberto": float(total)}

    # chamados em andamento por pessoa
    chamados: dict = {}
    for ch in database.scalars(
        select(Chamado).where(Chamado.condominio_id == condominio_id, Chamado.status != "ENCERRADO", Chamado.autor_pessoa_id.is_not(None))
        .order_by(Chamado.updated_at.desc())
    ).all():
        chamados.setdefault(ch.autor_pessoa_id, []).append({"id": ch.id, "numero": ch.numero, "assunto": ch.assunto, "status": ch.status, "updated_at": ch.updated_at})

    # conversa do WhatsApp pelo telefone (com ou sem o 9)
    conversa_por_telefone: dict = {}
    for conversa in database.scalars(select(WhatsappConversa).where(WhatsappConversa.telefone.is_not(None)).order_by(WhatsappConversa.ultima_mensagem_em)).all():
        for numero in variacoes_telefone(conversa.telefone):
            conversa_por_telefone[numero] = conversa

    sindicos = sindicos_do_condominio(database, condominio_id)

    def montar_pessoa(p: Pessoa) -> dict:
        conversa = conversa_por_telefone.get(p.telefone) if p.telefone else None
        origem, nomes = quem_recebe(p.responsavel, sindicos)
        return {
            "id": p.id, "nome": p.nome, "perfil": p.perfil, "cpf": p.cpf, "email": p.email, "telefone": p.telefone,
            "data_nascimento": p.data_nascimento, "foto_arquivo_id": p.foto_arquivo_id, "tem_login": p.user_id is not None,
            "login_status": p.usuario.status if p.usuario else None,
            "responsavel": resumo_responsavel(p.responsavel), "recebe_origem": origem, "recebe_nomes": nomes,
            "chamados_abertos": chamados.get(p.id, []),
            "whatsapp": {
                "conversa_id": conversa.id, "nome": conversa.nome, "nao_lidas": conversa.nao_lidas,
                "ultima_mensagem": conversa.ultima_mensagem, "ultima_mensagem_em": conversa.ultima_mensagem_em,
            } if conversa else None,
            "created_at": p.created_at,
        }

    sem_financeiro = {"cotas_abertas": 0, "cotas_atrasadas": 0, "valor_em_aberto": 0.0}
    lista_aptos = []
    for a in apartamentos:
        vinculos = sorted((v for v in a.pessoas if v.ativo and v.pessoa and v.pessoa.ativo), key=ordem_vinculo)
        lista_aptos.append({
            "id": a.id, "rotulo": rotulo_apartamento(a) or "", "bloco": a.bloco, "numero": a.numero, "andar": a.andar,
            "observacao": a.observacao, "ocupacao": ocupacao(a.pessoas),
            "pessoas": [{
                "vinculo_id": v.id, "tipo_relacao": v.tipo_relacao, "reside": v.reside, "parentesco": v.parentesco,
                "principal": v.principal, "titular_nome": v.titular.pessoa.nome if v.titular and v.titular.pessoa else None,
                "pessoa": montar_pessoa(v.pessoa),
            } for v in vinculos],
            "veiculos": [{
                "placa": v.placa, "marca": v.marca, "modelo": v.modelo, "cor": v.cor,
                "condutor": v.pessoa.nome if v.pessoa else None, "vaga": v.vaga.numero if v.vaga else None,
            } for v in a.veiculos if v.ativo],
            "vagas": [{"numero": v.numero, "tipo": v.tipo, "localizacao": v.localizacao} for v in sorted(a.vagas, key=lambda v: v.numero) if v.ativo],
            "financeiro": financeiro.get(a.id, sem_financeiro),
        })

    sem_unidade = [montar_pessoa(p) for p in pessoas if p.perfil in PERFIS_MORADORES and not any(v.ativo for v in p.apartamentos)]

    return {
        "id": condominio.id, "nome": condominio.nome, "sindicos": sindicos_do(pessoas),
        "responsaveis_disponiveis": [resumo_responsavel(u) for u in responsaveis_cadastrados(database)],
        "apartamentos": lista_aptos, "sem_unidade": sem_unidade,
    }


# =========================================================
# EDIÇÃO MANUAL PELO ADM
# =========================================================

@router.patch("/pessoas/{pessoa_id}", status_code=status.HTTP_204_NO_CONTENT)
def editarPessoaAdmin(pessoa_id: uuid.UUID, dados: EditarPessoaAdmin, database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    pessoa = database.get(Pessoa, pessoa_id)
    if not pessoa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada")
    enviados = dados.model_fields_set

    if "nome" in enviados:
        if not dados.nome or not dados.nome.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o nome")
        pessoa.nome = dados.nome.strip()
        if pessoa.usuario:
            pessoa.usuario.full_name = pessoa.nome  # o login acompanha o cadastro
    if "cpf" in enviados:
        if dados.cpf:
            garantir_unico(database, Pessoa, pessoa.condominio_id, {"cpf": dados.cpf}, "CPF já cadastrado neste condomínio", ignorar_id=pessoa.id)
        pessoa.cpf = dados.cpf
    if "email" in enviados:
        if pessoa.user_id:
            if not dados.email:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta pessoa tem acesso ao sistema: o e-mail é obrigatório, pois é o login dela")
            usuario = database.get(User, pessoa.user_id)
            if usuario and usuario.email != dados.email:
                if database.scalar(select(User.id).where(User.email == dados.email, User.id != usuario.id)):
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este e-mail já é o login de outro usuário")
                usuario.email = dados.email
        pessoa.email = dados.email
    if "telefone" in enviados:
        pessoa.telefone = dados.telefone
    if "data_nascimento" in enviados:
        pessoa.data_nascimento = dados.data_nascimento
    if "responsavel_user_id" in enviados:
        validar_responsavel_escolhido(database, dados.responsavel_user_id)
        pessoa.responsavel_user_id = dados.responsavel_user_id
    salvar(database)


@router.patch("/pessoas/{pessoa_id}/responsavel", status_code=status.HTTP_204_NO_CONTENT)
def definirResponsavel(pessoa_id: uuid.UUID, dados: DefinirResponsavel, database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    pessoa = database.get(Pessoa, pessoa_id)
    if not pessoa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada")
    validar_responsavel_escolhido(database, dados.responsavel_user_id)
    pessoa.responsavel_user_id = dados.responsavel_user_id
    salvar(database)


@router.post("/condominios/{condominio_id}/responsavel")
def aplicarResponsavel(condominio_id: uuid.UUID, dados: AplicarResponsavel, database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    # o mesmo responsável para os moradores do condomínio (por padrão, só os que estão com o síndico)
    validar_responsavel_escolhido(database, dados.responsavel_user_id)
    pessoas = database.scalars(
        select(Pessoa).where(Pessoa.condominio_id == condominio_id, Pessoa.ativo.is_(True)).options(selectinload(Pessoa.apartamentos))
    ).all()
    alvo = [p.id for p in pessoas if e_morador(p) and (not dados.somente_sem_responsavel or p.responsavel_user_id is None)]
    if alvo:
        database.execute(update(Pessoa).where(Pessoa.id.in_(alvo)).values(responsavel_user_id=dados.responsavel_user_id))
    salvar(database)
    return {"atualizados": len(alvo)}


# =========================================================
# RESPONSÁVEIS (de fora dos condomínios)
# =========================================================

@router.get("/responsaveis", response_model=list[ResponsavelLista])
def listarResponsaveis(database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    contagem = dict(database.execute(
        select(Pessoa.responsavel_user_id, func.count()).where(Pessoa.responsavel_user_id.is_not(None), Pessoa.ativo.is_(True))
        .group_by(Pessoa.responsavel_user_id)
    ).all())
    usuarios = database.scalars(select(User).where(User.responsavel.is_(True)).order_by(User.full_name)).all()
    return [{
        "id": u.id, "nome": u.full_name, "email": u.email, "status": u.status, "trocar_senha": u.trocar_senha,
        "total_pessoas": contagem.get(u.id, 0), "created_at": u.created_at,
    } for u in usuarios]


@router.post("/responsaveis", response_model=ResponsavelCriado, status_code=status.HTTP_201_CREATED)
def criarResponsavel(dados: CriarResponsavel, database: Session = Depends(get_database), _: User = Depends(exigir_admin_sistema)):
    # cria o login (senha temporária) ou, se o e-mail já tem login, só marca como responsável
    email = dados.email.lower()
    usuario = database.scalar(select(User).where(User.email == email))
    senha = None
    if usuario:
        if usuario.responsavel:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este e-mail já é de um responsável")
        usuario.responsavel = True
    else:
        senha = gerar_senha_temporaria()
        usuario = User(full_name=dados.nome.strip(), email=email, password_hash=hash_password(senha),
                       status=UserStatus.ativo.value, trocar_senha=True, responsavel=True)
        database.add(usuario)
    salvar(database, "Não foi possível criar o responsável: e-mail já cadastrado")
    return {"id": usuario.id, "nome": usuario.full_name, "email": usuario.email, "senha_temporaria": senha, "login_existente": senha is None}
