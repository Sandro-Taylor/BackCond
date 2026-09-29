# ---------------------------------------------------------
# PESSOAS – EXCLUSÃO
# ---------------------------------------------------------
# Ao excluir: vínculos com apartamentos e residentes ligados a
# ela são apagados; veículos em que era condutor ficam sem
# condutor. Não exclui se for responsável por tarefas.
# ---------------------------------------------------------

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from App.consultas import buscar_no_condominio, salvar
from App.database import get_database
from App.dependencies import Contexto, exigir_adm_para_perfil, exigir_gestao
from App.models import Pessoa, Tarefa

router = APIRouter()


@router.delete("/{pessoa_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirPessoa(pessoa_id: uuid.UUID, database: Session = Depends(get_database), ctx: Contexto = Depends(exigir_gestao)):
    pessoa = buscar_no_condominio(database, Pessoa, pessoa_id, ctx.condominio_id, "Pessoa não encontrada")
    exigir_adm_para_perfil(ctx, pessoa.perfil)

    total_tarefas = database.scalar(select(func.count()).select_from(Tarefa).where(Tarefa.responsavel_id == pessoa.id))
    if total_tarefas:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Esta pessoa é responsável por {total_tarefas} tarefa(s). Transfira as tarefas para outro responsável ou inative a pessoa.",
        )

    database.delete(pessoa)
    salvar(database)
