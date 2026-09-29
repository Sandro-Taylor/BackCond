# ---------------------------------------------------------
# CONDOMÍNIOS
# ---------------------------------------------------------
# ADM do sistema: cria, edita, arquiva e restaura; vê o painel
#   de todos os condomínios; designa/troca o síndico.
# Síndico: edita só o contato/endereço do próprio condomínio
#   (nome e CNPJ ficam com o ADM).
# Listar e consultar: ADM vê todos; demais usuários veem só
# os condomínios onde têm cadastro ativo.
# ---------------------------------------------------------

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from App.database import get_database
from App.acesso import ligar_login
from App.consultas import buscar_no_condominio, garantir_unico, salvar
from App.dependencies import Contexto, exigir_admin_sistema, exigir_gestao, get_contexto, get_current_user
from App.models import Apartamento, Chamado, Condominio, Cota, Pessoa, Tarefa, User, Vaga, Veiculo
from Router.Pessoa.CadastrarPessoas import PessoaDados
from Router.Cargos import criar_cargos_padrao
from App.validacoes import normalizar_cep, normalizar_cnpj, normalizar_email, normalizar_telefone, normalizar_uf

router = APIRouter(prefix="/condominios")


# DADOS RECEBIDOS

class ContatoCondominio(BaseModel):
    # o que o síndico pode editar no próprio condomínio
    cep: str | None = None
    logradouro: str | None = Field(default=None, max_length=200)
    numero: str | None = Field(default=None, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str | None = Field(default=None, max_length=100)
    cidade: str | None = Field(default=None, max_length=100)
    uf: str | None = None
    telefone: str | None = None
    email: EmailStr | None = None

    @field_validator("cep")
    @classmethod
    def validar_cep(cls, valor):
        return normalizar_cep(valor)

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, valor):
        return normalizar_uf(valor)

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, valor):
        return normalizar_telefone(valor)

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class CondominioCriar(ContatoCondominio):
    nome: str = Field(min_length=3, max_length=150)
    cnpj: str | None = None

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, valor):
        return normalizar_cnpj(valor)


class DesignarSindico(BaseModel):
    pessoa_id: uuid.UUID | None = None   # pessoa já cadastrada no condomínio
    pessoa: PessoaDados | None = None    # ou os dados de uma pessoa nova
    email: EmailStr | None = None        # login (vazio = e-mail do cadastro)
    # o que acontece com o síndico atual
    sindico_anterior: Literal["MORADOR", "CONSELHEIRO", "MANTER"] = "MORADOR"

    @field_validator("email")
    @classmethod
    def validar_email(cls, valor):
        return normalizar_email(valor)


class CondominioEditar(CondominioCriar):
    nome: str | None = Field(default=None, min_length=3, max_length=150)


# RESPOSTA

class CondominioResposta(BaseModel):
    id: uuid.UUID
    nome: str
    cnpj: str | None
    cep: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    cidade: str | None
    uf: str | None
    telefone: str | None
    email: str | None
    ativo: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SindicoResumo(BaseModel):
    pessoa_id: uuid.UUID
    nome: str
    email: str | None
    tem_acesso: bool


class CondominioPainel(BaseModel):
    condominio: CondominioResposta
    sindicos: list[SindicoResumo]
    total_apartamentos: int
    total_pessoas: int
    total_usuarios: int          # pessoas com acesso ao sistema
    chamados_aguardando: int     # atendimento esperando resposta da gestão
    cotas_atrasadas: int
    tarefas_atrasadas: int


class SindicoDesignado(BaseModel):
    pessoa_id: uuid.UUID
    nome: str
    email: str
    senha_temporaria: str | None  # só quando o login é criado agora
    login_existente: bool


class ResumoCondominio(BaseModel):
    condominio: CondominioResposta
    total_apartamentos: int
    total_vagas: int
    vagas_fixas: int
    vagas_rotativas: int
    total_pessoas: int
    total_veiculos: int


# FUNÇÕES AUXILIARES

def buscar_condominio_ou_404(condominio_id: uuid.UUID, database: Session) -> Condominio:
    condominio = database.get(Condominio, condominio_id)
    if not condominio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")
    return condominio


def validar_cnpj_unico(cnpj: str | None, database: Session, ignorar_id: uuid.UUID | None = None):
    if not cnpj:
        return
    consulta = select(Condominio.id).where(Condominio.cnpj == cnpj)
    if ignorar_id:
        consulta = consulta.where(Condominio.id != ignorar_id)
    if database.scalar(consulta):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CNPJ já cadastrado")


def consulta_condominios_do_usuario(usuario: User):
    # condomínios ativos onde o usuário tem uma pessoa ativa
    return (
        select(Condominio)
        .join(Pessoa, Pessoa.condominio_id == Condominio.id)
        .where(Pessoa.user_id == usuario.id, Pessoa.ativo.is_(True), Condominio.ativo.is_(True))
    )


# ROTAS

@router.post("/", response_model=CondominioResposta, status_code=status.HTTP_201_CREATED)
async def criarCondominio(dados: CondominioCriar, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    validar_cnpj_unico(dados.cnpj, database)
    condominio = Condominio(**dados.model_dump())
    condominio.nome = condominio.nome.strip()
    database.add(condominio)
    database.flush()  # gera o id para os cargos padrão
    criar_cargos_padrao(database, condominio.id)
    database.commit()
    database.refresh(condominio)
    return condominio


@router.get("/", response_model=list[CondominioResposta])
async def listarCondominios(database: Session = Depends(get_database), usuario: User = Depends(get_current_user)):
    if usuario.admin_sistema:
        consulta = select(Condominio)
    else:
        consulta = consulta_condominios_do_usuario(usuario)
    return database.scalars(consulta.order_by(Condominio.nome)).all()


@router.get("/atual/resumo", response_model=ResumoCondominio)
async def resumoCondominio(database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # dados e números do condomínio que está sendo acessado (página inicial)
    condominio = buscar_condominio_ou_404(ctx.condominio_id, database)

    def contar(modelo, *filtros) -> int:
        return database.scalar(select(func.count()).select_from(modelo).where(modelo.condominio_id == ctx.condominio_id, *filtros)) or 0

    return {
        "condominio": condominio,
        "total_apartamentos": contar(Apartamento),
        "total_vagas": contar(Vaga),
        "vagas_fixas": contar(Vaga, Vaga.tipo == "FIXA"),
        "vagas_rotativas": contar(Vaga, Vaga.tipo == "ROTATIVA"),
        "total_pessoas": contar(Pessoa),
        "total_veiculos": contar(Veiculo),
    }


@router.get("/painel", response_model=list[CondominioPainel])
async def painelCondominios(database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    # visão geral de todos os condomínios (ADM do sistema)
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()

    def por_condominio(modelo, *filtros) -> dict:
        return dict(database.execute(
            select(modelo.condominio_id, func.count()).where(*filtros).group_by(modelo.condominio_id)
        ).all())

    apartamentos = por_condominio(Apartamento)
    pessoas = por_condominio(Pessoa, Pessoa.ativo.is_(True))
    usuarios = por_condominio(Pessoa, Pessoa.ativo.is_(True), Pessoa.user_id.is_not(None))
    chamados = por_condominio(Chamado, Chamado.status == "ABERTO")
    cotas = por_condominio(Cota, Cota.status == "ABERTA", Cota.vencimento < hoje)
    tarefas = por_condominio(Tarefa, Tarefa.status.in_(("PENDENTE", "EM_ANDAMENTO")), Tarefa.prazo < hoje)

    sindicos: dict = {}
    for pessoa in database.scalars(select(Pessoa).where(Pessoa.perfil == "SINDICO", Pessoa.ativo.is_(True)).order_by(Pessoa.nome)):
        sindicos.setdefault(pessoa.condominio_id, []).append(
            {"pessoa_id": pessoa.id, "nome": pessoa.nome, "email": pessoa.email, "tem_acesso": pessoa.user_id is not None}
        )

    return [{
        "condominio": c,
        "sindicos": sindicos.get(c.id, []),
        "total_apartamentos": apartamentos.get(c.id, 0),
        "total_pessoas": pessoas.get(c.id, 0),
        "total_usuarios": usuarios.get(c.id, 0),
        "chamados_aguardando": chamados.get(c.id, 0),
        "cotas_atrasadas": cotas.get(c.id, 0),
        "tarefas_atrasadas": tarefas.get(c.id, 0),
    } for c in database.scalars(select(Condominio).order_by(Condominio.ativo.desc(), Condominio.nome))]


@router.put("/atual/contato", response_model=CondominioResposta)
async def editarContato(dados: ContatoCondominio, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    # síndico (ou ADM) edita contato e endereço do condomínio que está acessando
    condominio = buscar_condominio_ou_404(ctx.condominio_id, database)
    for campo, valor in dados.model_dump().items():
        setattr(condominio, campo, valor)
    salvar(database)
    database.refresh(condominio)
    return condominio


@router.post("/{condominio_id}/sindico", response_model=SindicoDesignado)
async def designarSindico(condominio_id: uuid.UUID, dados: DesignarSindico, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    # ADM designa (ou troca) o síndico e já deixa o login dele pronto
    buscar_condominio_ou_404(condominio_id, database)
    if bool(dados.pessoa_id) == bool(dados.pessoa):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Escolha uma pessoa já cadastrada ou informe os dados de uma nova")

    if dados.pessoa_id:
        pessoa = buscar_no_condominio(database, Pessoa, dados.pessoa_id, condominio_id, "Pessoa não encontrada neste condomínio")
        if not pessoa.ativo:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta pessoa está inativa")
    else:
        if dados.pessoa.cpf:
            garantir_unico(database, Pessoa, condominio_id, {"cpf": dados.pessoa.cpf}, "CPF já cadastrado neste condomínio. Escolha a pessoa na lista")
        pessoa = Pessoa(
            condominio_id=condominio_id, nome=dados.pessoa.nome.strip(), cpf=dados.pessoa.cpf, email=dados.pessoa.email,
            telefone=dados.pessoa.telefone, data_nascimento=dados.pessoa.data_nascimento, perfil="SINDICO",
        )
        database.add(pessoa)

    # síndico atual
    if dados.sindico_anterior != "MANTER":
        for anterior in database.scalars(select(Pessoa).where(
            Pessoa.condominio_id == condominio_id, Pessoa.perfil == "SINDICO", Pessoa.id != pessoa.id,
        )):
            anterior.perfil = dados.sindico_anterior

    pessoa.perfil = "SINDICO"
    pessoa.funcionario = None  # deixa de ser funcionário, se era

    # login
    senha = None
    if not pessoa.user_id:
        email = dados.email or pessoa.email
        if not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o e-mail do síndico: ele será o login")
        senha = ligar_login(database, pessoa, email)

    salvar(database, "Não foi possível designar o síndico: CPF ou e-mail já em uso neste condomínio")
    return {"pessoa_id": pessoa.id, "nome": pessoa.nome, "email": pessoa.email, "senha_temporaria": senha, "login_existente": senha is None}


@router.get("/{condominio_id}", response_model=CondominioResposta)
async def buscarCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), usuario: User = Depends(get_current_user)):
    if usuario.admin_sistema:
        return buscar_condominio_ou_404(condominio_id, database)
    condominio = database.scalar(consulta_condominios_do_usuario(usuario).where(Condominio.id == condominio_id))
    if not condominio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condomínio não encontrado")
    return condominio


@router.put("/{condominio_id}", response_model=CondominioResposta)
async def editarCondominio(condominio_id: uuid.UUID, dados: CondominioEditar, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    condominio = buscar_condominio_ou_404(condominio_id, database)
    dados_atualizados = dados.model_dump(exclude_unset=True)
    if "nome" in dados_atualizados:
        if not dados_atualizados["nome"] or not dados_atualizados["nome"].strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome é obrigatório")
        dados_atualizados["nome"] = dados_atualizados["nome"].strip()
    validar_cnpj_unico(dados_atualizados.get("cnpj"), database, ignorar_id=condominio_id)
    for campo, valor in dados_atualizados.items():
        setattr(condominio, campo, valor)
    database.commit()
    database.refresh(condominio)
    return condominio


@router.patch("/{condominio_id}/arquivar", response_model=CondominioResposta)
async def arquivarCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    condominio = buscar_condominio_ou_404(condominio_id, database)
    condominio.ativo = False
    database.commit()
    database.refresh(condominio)
    return condominio


@router.patch("/{condominio_id}/restaurar", response_model=CondominioResposta)
async def restaurarCondominio(condominio_id: uuid.UUID, database: Session = Depends(get_database), admin: User = Depends(exigir_admin_sistema)):
    condominio = buscar_condominio_ou_404(condominio_id, database)
    condominio.ativo = True
    database.commit()
    database.refresh(condominio)
    return condominio
