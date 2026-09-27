# ---------------------------------------------------------
# APARTAMENTOS (centro do cadastro)
# ---------------------------------------------------------
# O apartamento é a unidade do condomínio. Nele são ligados:
#  - pessoas: PROPRIETARIO (mora ou não no prédio), INQUILINO
#    e RESIDENTE (ligado a um titular, com parentesco)
#  - vagas
#  - veículos (pertencem ao apartamento; condutor opcional)
# Todas as rotas ficam restritas ao condomínio do contexto.
# As rotas de alteração devolvem o apartamento completo,
# para a tela se atualizar com uma única resposta.
# ---------------------------------------------------------

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from App.consultas import buscar_no_condominio, garantir_unico, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import Apartamento, Parentesco, Pessoa, PessoaApartamento, TipoRelacao, Vaga, Veiculo
from App.validacoes import normalizar_placa
from Router.Pessoa.CadastrarPessoas import PessoaDados

router = APIRouter(prefix="/apartamentos")

ORDEM_TIPO = {"PROPRIETARIO": 0, "INQUILINO": 1, "RESIDENTE": 2}


# =========================================================
# DADOS RECEBIDOS
# =========================================================

class ApartamentoDados(BaseModel):
    bloco: str | None = Field(default=None, max_length=20)
    numero: str = Field(min_length=1, max_length=10)
    andar: int | None = Field(default=None, ge=-10, le=300)
    observacao: str | None = None


class ApartamentoEditar(ApartamentoDados):
    ativo: bool = True


class VinculoDados(BaseModel):
    tipo_relacao: TipoRelacao
    reside: bool = True                           # só vale para PROPRIETARIO
    titular_vinculo_id: uuid.UUID | None = None   # obrigatório para RESIDENTE
    parentesco: Parentesco | None = None          # obrigatório para RESIDENTE


class AdicionarPessoa(VinculoDados):
    pessoa_id: uuid.UUID | None = None   # pessoa já cadastrada no condomínio
    pessoa: PessoaDados | None = None    # ou os dados de uma pessoa nova


class VinculoEditar(VinculoDados):
    ativo: bool = True


class VagaDados(BaseModel):
    numero: str = Field(min_length=1, max_length=20)
    localizacao: str | None = Field(default=None, max_length=100)
    observacao: str | None = None


class VagaEditar(VagaDados):
    ativo: bool = True


class VeiculoDados(BaseModel):
    placa: str | None = None
    marca: str | None = Field(default=None, max_length=50)
    modelo: str | None = Field(default=None, max_length=80)
    cor: str | None = Field(default=None, max_length=30)
    descricao: str | None = Field(default=None, max_length=255)
    vaga_id: uuid.UUID | None = None
    pessoa_id: uuid.UUID | None = None   # condutor (opcional)

    @field_validator("placa")
    @classmethod
    def validar_placa(cls, valor):
        return normalizar_placa(valor)


class VeiculoEditar(VeiculoDados):
    ativo: bool = True


# =========================================================
# RESPOSTAS
# =========================================================

class PessoaDoVinculo(BaseModel):
    id: uuid.UUID
    nome: str
    cpf: str | None
    email: str | None
    telefone: str | None
    data_nascimento: date | None
    perfil: str
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


class VinculoResposta(BaseModel):
    id: uuid.UUID
    pessoa_id: uuid.UUID
    tipo_relacao: str
    reside: bool
    titular_vinculo_id: uuid.UUID | None
    parentesco: str | None
    principal: bool
    ativo: bool
    pessoa: PessoaDoVinculo
    model_config = ConfigDict(from_attributes=True)


class VagaResposta(BaseModel):
    id: uuid.UUID
    numero: str
    tipo: str
    localizacao: str | None
    observacao: str | None
    ativo: bool
    model_config = ConfigDict(from_attributes=True)


class VeiculoResposta(BaseModel):
    id: uuid.UUID
    placa: str | None
    marca: str | None
    modelo: str | None
    cor: str | None
    descricao: str | None
    ativo: bool
    vaga_id: uuid.UUID | None
    vaga_numero: str | None     # None = usa vagas rotativas
    pessoa_id: uuid.UUID | None
    condutor_nome: str | None


class ApartamentoResumo(BaseModel):
    id: uuid.UUID
    bloco: str
    numero: str
    andar: int | None
    observacao: str | None
    ativo: bool
    ocupacao: str              # OCUPADO_PROPRIETARIO | ALUGADO | VAZIO
    proprietarios: list[str]
    inquilinos: list[str]
    total_residentes: int
    total_vagas: int
    total_veiculos: int


class ApartamentoDetalhe(BaseModel):
    id: uuid.UUID
    bloco: str
    numero: str
    andar: int | None
    observacao: str | None
    ativo: bool
    ocupacao: str
    pessoas: list[VinculoResposta]
    vagas: list[VagaResposta]
    veiculos: list[VeiculoResposta]


# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def calcular_ocupacao(vinculos: list[PessoaApartamento]) -> str:
    ativos = [vinculo for vinculo in vinculos if vinculo.ativo]
    if any(vinculo.tipo_relacao == "INQUILINO" for vinculo in ativos):
        return "ALUGADO"
    if any(vinculo.tipo_relacao == "PROPRIETARIO" and vinculo.reside for vinculo in ativos):
        return "OCUPADO_PROPRIETARIO"
    return "VAZIO"


def residentes_da_unidade(vinculos: list[PessoaApartamento]) -> int:
    return sum(1 for vinculo in vinculos if vinculo.ativo and vinculo.reside)


def ordenar_apartamentos(apartamentos):
    # ordem natural: bloco, depois número (101 antes de 1001)
    return sorted(apartamentos, key=lambda a: (a.bloco, len(a.numero), a.numero))


def carregar_apartamento(database: Session, apartamento_id: uuid.UUID, condominio_id: uuid.UUID) -> Apartamento:
    apartamento = database.scalar(
        select(Apartamento)
        .where(Apartamento.id == apartamento_id, Apartamento.condominio_id == condominio_id)
        .options(
            selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa),
            selectinload(Apartamento.vagas),
            selectinload(Apartamento.veiculos).selectinload(Veiculo.pessoa),
            selectinload(Apartamento.veiculos).selectinload(Veiculo.vaga),
        )
        .execution_options(populate_existing=True)
    )
    if not apartamento:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apartamento não encontrado")
    return apartamento


def montar_detalhe(apartamento: Apartamento) -> dict:
    vinculos = sorted(apartamento.pessoas, key=lambda v: (ORDEM_TIPO.get(v.tipo_relacao, 9), v.pessoa.nome))
    return {
        "id": apartamento.id,
        "bloco": apartamento.bloco,
        "numero": apartamento.numero,
        "andar": apartamento.andar,
        "observacao": apartamento.observacao,
        "ativo": apartamento.ativo,
        "ocupacao": calcular_ocupacao(apartamento.pessoas),
        "pessoas": vinculos,
        "vagas": sorted(apartamento.vagas, key=lambda v: (len(v.numero), v.numero)),
        "veiculos": [
            {
                "id": veiculo.id,
                "placa": veiculo.placa,
                "marca": veiculo.marca,
                "modelo": veiculo.modelo,
                "cor": veiculo.cor,
                "descricao": veiculo.descricao,
                "ativo": veiculo.ativo,
                "vaga_id": veiculo.vaga_id,
                "vaga_numero": veiculo.vaga.numero if veiculo.vaga else None,
                "pessoa_id": veiculo.pessoa_id,
                "condutor_nome": veiculo.pessoa.nome if veiculo.pessoa else None,
            }
            for veiculo in apartamento.veiculos
        ],
    }


def detalhe(database: Session, apartamento_id: uuid.UUID, condominio_id: uuid.UUID) -> dict:
    return montar_detalhe(carregar_apartamento(database, apartamento_id, condominio_id))


def buscar_do_apartamento(database: Session, modelo, registro_id: uuid.UUID, apartamento_id: uuid.UUID, mensagem: str):
    registro = database.scalar(select(modelo).where(modelo.id == registro_id, modelo.apartamento_id == apartamento_id))
    if not registro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=mensagem)
    return registro


def campos_do_vinculo(database: Session, apartamento_id: uuid.UUID, dados: VinculoDados, vinculo_atual_id: uuid.UUID | None = None) -> dict:
    """Valida as regras do vínculo e devolve os campos já ajustados."""
    if dados.tipo_relacao == "RESIDENTE":
        if not dados.titular_vinculo_id or not dados.parentesco:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Para residente, informe o titular (proprietário ou inquilino) e o parentesco")
        if vinculo_atual_id and dados.titular_vinculo_id == vinculo_atual_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A pessoa não pode ser titular dela mesma")
        titular = database.scalar(
            select(PessoaApartamento).where(PessoaApartamento.id == dados.titular_vinculo_id, PessoaApartamento.apartamento_id == apartamento_id)
        )
        if not titular or titular.tipo_relacao not in ("PROPRIETARIO", "INQUILINO"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O titular precisa ser proprietário ou inquilino deste apartamento")
        return {"tipo_relacao": "RESIDENTE", "reside": True, "titular_vinculo_id": titular.id, "parentesco": dados.parentesco}

    # proprietário pode não residir; inquilino sempre reside
    return {
        "tipo_relacao": dados.tipo_relacao,
        "reside": dados.reside if dados.tipo_relacao == "PROPRIETARIO" else True,
        "titular_vinculo_id": None,
        "parentesco": None,
    }


def validar_veiculo(database: Session, apartamento: Apartamento, dados: VeiculoDados):
    if dados.vaga_id:
        buscar_do_apartamento(database, Vaga, dados.vaga_id, apartamento.id, "A vaga escolhida não é uma vaga fixa deste apartamento")
    if dados.pessoa_id:
        ligado = database.scalar(
            select(PessoaApartamento.id).where(PessoaApartamento.pessoa_id == dados.pessoa_id, PessoaApartamento.apartamento_id == apartamento.id)
        )
        if not ligado:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O condutor precisa ser uma pessoa ligada a este apartamento")


# =========================================================
# APARTAMENTO
# =========================================================

@router.get("/", response_model=list[ApartamentoResumo])
def listarApartamentos(database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamentos = database.scalars(
        select(Apartamento)
        .where(Apartamento.condominio_id == ctx.condominio_id)
        .options(
            selectinload(Apartamento.pessoas).selectinload(PessoaApartamento.pessoa),
            selectinload(Apartamento.vagas),
            selectinload(Apartamento.veiculos),
        )
    ).all()

    resumo = []
    for apartamento in ordenar_apartamentos(apartamentos):
        ativos = [vinculo for vinculo in apartamento.pessoas if vinculo.ativo]
        resumo.append({
            "id": apartamento.id,
            "bloco": apartamento.bloco,
            "numero": apartamento.numero,
            "andar": apartamento.andar,
            "observacao": apartamento.observacao,
            "ativo": apartamento.ativo,
            "ocupacao": calcular_ocupacao(apartamento.pessoas),
            "proprietarios": [v.pessoa.nome for v in ativos if v.tipo_relacao == "PROPRIETARIO"],
            "inquilinos": [v.pessoa.nome for v in ativos if v.tipo_relacao == "INQUILINO"],
            "total_residentes": residentes_da_unidade(apartamento.pessoas),
            "total_vagas": len(apartamento.vagas),
            "total_veiculos": len(apartamento.veiculos),
        })
    return resumo


@router.post("/", response_model=ApartamentoDetalhe, status_code=status.HTTP_201_CREATED)
def criarApartamento(dados: ApartamentoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    bloco = (dados.bloco or "").strip().upper()
    numero = dados.numero.strip()
    garantir_unico(database, Apartamento, ctx.condominio_id, {"bloco": bloco, "numero": numero}, "Já existe um apartamento com este bloco e número")

    apartamento = Apartamento(condominio_id=ctx.condominio_id, bloco=bloco, numero=numero, andar=dados.andar, observacao=texto(dados.observacao))
    database.add(apartamento)
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.get("/{apartamento_id}", response_model=ApartamentoDetalhe)
def buscarApartamento(apartamento_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    return detalhe(database, apartamento_id, ctx.condominio_id)


@router.put("/{apartamento_id}", response_model=ApartamentoDetalhe)
def editarApartamento(apartamento_id: uuid.UUID, dados: ApartamentoEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")

    bloco = (dados.bloco or "").strip().upper()
    numero = dados.numero.strip()
    garantir_unico(database, Apartamento, ctx.condominio_id, {"bloco": bloco, "numero": numero}, "Já existe um apartamento com este bloco e número", ignorar_id=apartamento.id)

    apartamento.bloco = bloco
    apartamento.numero = numero
    apartamento.andar = dados.andar
    apartamento.observacao = texto(dados.observacao)
    apartamento.ativo = dados.ativo
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.delete("/{apartamento_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirApartamento(apartamento_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # apaga junto: vínculos com pessoas e veículos da unidade; as vagas ficam livres e as pessoas continuam cadastradas
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    database.delete(apartamento)
    salvar(database)


# =========================================================
# PESSOAS DO APARTAMENTO
# =========================================================

@router.post("/{apartamento_id}/pessoas", response_model=ApartamentoDetalhe, status_code=status.HTTP_201_CREATED)
def adicionarPessoa(apartamento_id: uuid.UUID, dados: AdicionarPessoa, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    cid = ctx.condominio_id
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, cid, "Apartamento não encontrado")

    if (dados.pessoa_id is None) == (dados.pessoa is None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe uma pessoa já cadastrada ou os dados de uma pessoa nova")

    campos = campos_do_vinculo(database, apartamento.id, dados)

    try:
        if dados.pessoa_id:
            pessoa = buscar_no_condominio(database, Pessoa, dados.pessoa_id, cid, "Pessoa não encontrada")
        else:
            nova = dados.pessoa
            if nova.cpf:
                existente = database.scalar(select(Pessoa).where(Pessoa.condominio_id == cid, Pessoa.cpf == nova.cpf))
                if existente:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Este CPF já pertence a {existente.nome}. Use a busca por CPF para ligar a pessoa ao apartamento.",
                    )
            pessoa = Pessoa(
                condominio_id=cid,
                nome=nova.nome.strip(),
                cpf=nova.cpf,
                email=nova.email,
                telefone=nova.telefone,
                data_nascimento=nova.data_nascimento,
            )
            database.add(pessoa)
            database.flush()

        ja_ligada = database.scalar(
            select(PessoaApartamento.id).where(PessoaApartamento.pessoa_id == pessoa.id, PessoaApartamento.apartamento_id == apartamento.id)
        )
        if ja_ligada:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta pessoa já está ligada a este apartamento")

        # o primeiro apartamento da pessoa vira o principal dela
        tem_principal = database.scalar(
            select(PessoaApartamento.id).where(PessoaApartamento.pessoa_id == pessoa.id, PessoaApartamento.principal.is_(True))
        )
        database.add(PessoaApartamento(pessoa_id=pessoa.id, apartamento_id=apartamento.id, principal=not tem_principal, **campos))
        database.commit()
    except HTTPException:
        database.rollback()
        raise
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Não foi possível adicionar: existem dados duplicados")

    return detalhe(database, apartamento.id, cid)


@router.put("/{apartamento_id}/pessoas/{vinculo_id}", response_model=ApartamentoDetalhe)
def editarVinculo(apartamento_id: uuid.UUID, vinculo_id: uuid.UUID, dados: VinculoEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    vinculo = buscar_do_apartamento(database, PessoaApartamento, vinculo_id, apartamento.id, "Vínculo não encontrado")

    campos = campos_do_vinculo(database, apartamento.id, dados, vinculo_atual_id=vinculo.id)

    # um titular com residentes ligados não pode virar residente
    if campos["tipo_relacao"] == "RESIDENTE" and vinculo.tipo_relacao != "RESIDENTE":
        tem_residentes = database.scalar(select(PessoaApartamento.id).where(PessoaApartamento.titular_vinculo_id == vinculo.id))
        if tem_residentes:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta pessoa tem residentes ligados a ela. Mude o titular deles antes.")

    for campo, valor in campos.items():
        setattr(vinculo, campo, valor)
    vinculo.ativo = dados.ativo
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.delete("/{apartamento_id}/pessoas/{vinculo_id}", response_model=ApartamentoDetalhe)
def removerPessoa(apartamento_id: uuid.UUID, vinculo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # remove só o vínculo (a pessoa continua cadastrada); residentes ligados a este titular saem junto
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    vinculo = buscar_do_apartamento(database, PessoaApartamento, vinculo_id, apartamento.id, "Vínculo não encontrado")
    database.delete(vinculo)
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


# =========================================================
# VAGAS DO APARTAMENTO
# =========================================================

@router.post("/{apartamento_id}/vagas", response_model=ApartamentoDetalhe, status_code=status.HTTP_201_CREATED)
def adicionarVaga(apartamento_id: uuid.UUID, dados: VagaDados, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    numero = dados.numero.strip()
    garantir_unico(database, Vaga, ctx.condominio_id, {"numero": numero}, f"Vaga {numero} já cadastrada neste condomínio")

    database.add(Vaga(
        condominio_id=ctx.condominio_id,
        tipo="FIXA",
        apartamento_id=apartamento.id,
        numero=numero,
        localizacao=texto(dados.localizacao),
        observacao=texto(dados.observacao),
    ))
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.put("/{apartamento_id}/vagas/{vaga_id}", response_model=ApartamentoDetalhe)
def editarVaga(apartamento_id: uuid.UUID, vaga_id: uuid.UUID, dados: VagaEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    vaga = buscar_do_apartamento(database, Vaga, vaga_id, apartamento.id, "Vaga não encontrada")
    numero = dados.numero.strip()
    garantir_unico(database, Vaga, ctx.condominio_id, {"numero": numero}, f"Vaga {numero} já cadastrada neste condomínio", ignorar_id=vaga.id)

    vaga.numero = numero
    vaga.localizacao = texto(dados.localizacao)
    vaga.observacao = texto(dados.observacao)
    vaga.ativo = dados.ativo
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.post("/{apartamento_id}/vagas/{vaga_id}/vincular", response_model=ApartamentoDetalhe)
def vincularVaga(apartamento_id: uuid.UUID, vaga_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # liga uma vaga FIXA livre (cadastrada na tela Vagas) a este apartamento
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    vaga = buscar_no_condominio(database, Vaga, vaga_id, ctx.condominio_id, "Vaga não encontrada")
    if vaga.tipo != "FIXA":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vaga rotativa é de uso comum e não pode ser de um apartamento")
    if vaga.apartamento_id and vaga.apartamento_id != apartamento.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A vaga {vaga.numero} já pertence a outro apartamento")
    vaga.apartamento_id = apartamento.id
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.delete("/{apartamento_id}/vagas/{vaga_id}", response_model=ApartamentoDetalhe)
def liberarVaga(apartamento_id: uuid.UUID, vaga_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    # tira a vaga do apartamento (ela continua cadastrada, livre); os veículos que a usavam passam a rotativo
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    vaga = buscar_do_apartamento(database, Vaga, vaga_id, apartamento.id, "Vaga não encontrada")
    database.execute(update(Veiculo).where(Veiculo.vaga_id == vaga.id).values(vaga_id=None))
    vaga.apartamento_id = None
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


# =========================================================
# VEÍCULOS DO APARTAMENTO
# =========================================================

@router.post("/{apartamento_id}/veiculos", response_model=ApartamentoDetalhe, status_code=status.HTTP_201_CREATED)
def adicionarVeiculo(apartamento_id: uuid.UUID, dados: VeiculoDados, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    validar_veiculo(database, apartamento, dados)
    if dados.placa:
        garantir_unico(database, Veiculo, ctx.condominio_id, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio")

    database.add(Veiculo(
        condominio_id=ctx.condominio_id,
        apartamento_id=apartamento.id,
        pessoa_id=dados.pessoa_id,
        vaga_id=dados.vaga_id,
        placa=dados.placa,
        marca=texto(dados.marca),
        modelo=texto(dados.modelo),
        cor=texto(dados.cor),
        descricao=texto(dados.descricao),
    ))
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.put("/{apartamento_id}/veiculos/{veiculo_id}", response_model=ApartamentoDetalhe)
def editarVeiculo(apartamento_id: uuid.UUID, veiculo_id: uuid.UUID, dados: VeiculoEditar, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    veiculo = buscar_do_apartamento(database, Veiculo, veiculo_id, apartamento.id, "Veículo não encontrado")
    validar_veiculo(database, apartamento, dados)
    if dados.placa:
        garantir_unico(database, Veiculo, ctx.condominio_id, {"placa": dados.placa}, f"Placa {dados.placa} já cadastrada neste condomínio", ignorar_id=veiculo.id)

    veiculo.placa = dados.placa
    veiculo.marca = texto(dados.marca)
    veiculo.modelo = texto(dados.modelo)
    veiculo.cor = texto(dados.cor)
    veiculo.descricao = texto(dados.descricao)
    veiculo.vaga_id = dados.vaga_id
    veiculo.pessoa_id = dados.pessoa_id
    veiculo.ativo = dados.ativo
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)


@router.delete("/{apartamento_id}/veiculos/{veiculo_id}", response_model=ApartamentoDetalhe)
def excluirVeiculo(apartamento_id: uuid.UUID, veiculo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    veiculo = buscar_do_apartamento(database, Veiculo, veiculo_id, apartamento.id, "Veículo não encontrado")
    database.delete(veiculo)
    salvar(database)
    return detalhe(database, apartamento.id, ctx.condominio_id)
