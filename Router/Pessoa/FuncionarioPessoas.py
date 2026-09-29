# ---------------------------------------------------------
# PESSOAS – FICHA DO FUNCIONÁRIO
# ---------------------------------------------------------
# Pessoa com perfil FUNCIONARIO tem uma ficha com cargo,
# vínculo (próprio, terceirizado, autônomo), empresa, turno
# e admissão. A ficha é criada junto com a pessoa ou depois,
# por PUT /pessoas/{id}/funcionario, e é apagada quando o
# perfil deixa de ser FUNCIONARIO.
# ---------------------------------------------------------

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, salvar, texto
from App.database import get_database
from App.dependencies import Contexto, exigir_gestao
from App.models import Cargo, Funcionario, Pessoa, VinculoFuncionario

router = APIRouter()


class FichaFuncionario(BaseModel):
    cargo_id: uuid.UUID
    vinculo: VinculoFuncionario = "PROPRIO"
    empresa: str | None = Field(default=None, max_length=150)
    turno: str | None = Field(default=None, max_length=100)
    data_admissao: date | None = None


class FichaResposta(BaseModel):
    cargo_id: uuid.UUID
    cargo_nome: str
    vinculo: str
    empresa: str | None
    turno: str | None
    data_admissao: date | None
    model_config = ConfigDict(from_attributes=True)


def aplicar_ficha(database: Session, ctx: Contexto, pessoa: Pessoa, ficha: FichaFuncionario):
    # cria ou atualiza a ficha (o commit fica com quem chamou)
    if pessoa.perfil != "FUNCIONARIO":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A ficha é só para pessoas com perfil Funcionário")
    cargo = buscar_no_condominio(database, Cargo, ficha.cargo_id, ctx.condominio_id, "Cargo não encontrado")
    if not cargo.ativo and (not pessoa.funcionario or pessoa.funcionario.cargo_id != cargo.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este cargo está desativado")
    if ficha.vinculo == "TERCEIRIZADO" and not texto(ficha.empresa):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe a empresa do funcionário terceirizado")

    if not pessoa.funcionario:
        pessoa.funcionario = Funcionario(condominio_id=ctx.condominio_id, cargo_id=cargo.id)
    pessoa.funcionario.cargo_id = cargo.id
    pessoa.funcionario.cargo = cargo
    pessoa.funcionario.vinculo = ficha.vinculo
    pessoa.funcionario.empresa = texto(ficha.empresa) if ficha.vinculo != "PROPRIO" else None
    pessoa.funcionario.turno = texto(ficha.turno)
    pessoa.funcionario.data_admissao = ficha.data_admissao


@router.put("/{pessoa_id}/funcionario", response_model=FichaResposta)
def salvarFicha(pessoa_id: uuid.UUID, ficha: FichaFuncionario, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")
    aplicar_ficha(database, ctx, pessoa, ficha)
    salvar(database)
    database.refresh(pessoa)
    return pessoa.funcionario
