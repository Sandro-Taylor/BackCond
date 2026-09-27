# ---------------------------------------------------------
# PESSOAS – EXCLUSÃO
# ---------------------------------------------------------
# Só exclui registros do condomínio do contexto.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, buscar_vinculo_no_condominio, salvar
from App.database import get_database
from App.dependencies import Contexto, get_contexto
from App.models import Apartamento, Pessoa, Tarefa, Vaga, Veiculo

router = APIRouter()


# PESSOA (apaga junto: vínculos, veículos e cadastro de colaborador)
@router.delete("/{pessoa_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirPessoa(pessoa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")

    total_tarefas = database.scalar(select(func.count()).select_from(Tarefa).where(Tarefa.responsavel_id == pessoa.id))
    if total_tarefas:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Esta pessoa é responsável por {total_tarefas} tarefa(s). Transfira as tarefas ou inative a pessoa.",
        )

    database.delete(pessoa)
    salvar(database)


# APARTAMENTO (apaga junto: vínculos e vagas; veículos das vagas ficam sem vaga)
@router.delete("/apartamentos/{apartamento_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirApartamento(apartamento_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    apartamento = buscar_no_condominio(database, Apartamento, apartamento_id, ctx.condominio_id, "Apartamento não encontrado")
    database.delete(apartamento)
    salvar(database)


# VÍNCULO PESSOA / APARTAMENTO
@router.delete("/vinculos/{vinculo_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirVinculo(vinculo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    vinculo = buscar_vinculo_no_condominio(database, vinculo_id, ctx.condominio_id)
    database.delete(vinculo)
    salvar(database)


# VAGA (veículos da vaga ficam sem vaga)
@router.delete("/vagas/{vaga_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirVaga(vaga_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    vaga = buscar_no_condominio(database, Vaga, vaga_id, ctx.condominio_id, "Vaga não encontrada")
    database.delete(vaga)
    salvar(database)


# VEÍCULO
@router.delete("/veiculos/{veiculo_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirVeiculo(veiculo_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(get_contexto)):
    veiculo = buscar_no_condominio(database, Veiculo, veiculo_id, ctx.condominio_id, "Veículo não encontrado")
    database.delete(veiculo)
    salvar(database)
