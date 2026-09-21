from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy.orm import Session
import uuid

from App.database import get_database
from Router.Pessoa.CadastrarPessoas import (
    Pessoa,
    Apartamento,
    PessoaApartamento,
    Vaga,
    Veiculo,
)

router = APIRouter()


# =========================================================
# PESSOA
# =========================================================

@router.delete("/{pessoa_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluirPessoa(
    pessoa_id: uuid.UUID,
    database: Session = Depends(get_database)
):
    pessoa = database.get(Pessoa, pessoa_id)

    if not pessoa:
        raise HTTPException(
            status_code=404,
            detail="Pessoa não encontrada"
        )

    database.delete(pessoa)
    database.commit()

    return None


# =========================================================
# APARTAMENTO
# =========================================================

@router.delete("/apartamentos/{apartamento_id}", status_code=204)
def excluirApartamento(
    apartamento_id: uuid.UUID,
    database: Session = Depends(get_database)
):
    apartamento = database.get(Apartamento, apartamento_id)

    if not apartamento:
        raise HTTPException(
            status_code=404,
            detail="Apartamento não encontrado"
        )

    database.delete(apartamento)
    database.commit()

    return None


# =========================================================
# VÍNCULO PESSOA / APARTAMENTO
# =========================================================

@router.delete("/vinculos/{vinculo_id}", status_code=204)
def excluirVinculo(
    vinculo_id: uuid.UUID,
    database: Session = Depends(get_database)
):
    vinculo = database.get(PessoaApartamento, vinculo_id)

    if not vinculo:
        raise HTTPException(
            status_code=404,
            detail="Vínculo não encontrado"
        )

    database.delete(vinculo)
    database.commit()

    return None


# =========================================================
# VAGA
# =========================================================

@router.delete("/vagas/{vaga_id}", status_code=204)
def excluirVaga(
    vaga_id: uuid.UUID,
    database: Session = Depends(get_database)
):
    vaga = database.get(Vaga, vaga_id)

    if not vaga:
        raise HTTPException(
            status_code=404,
            detail="Vaga não encontrada"
        )

    database.delete(vaga)
    database.commit()

    return None


# =========================================================
# VEÍCULO
# =========================================================

@router.delete("/veiculos/{veiculo_id}", status_code=204)
def excluirVeiculo(
    veiculo_id: uuid.UUID,
    database: Session = Depends(get_database)
):
    veiculo = database.get(Veiculo, veiculo_id)

    if not veiculo:
        raise HTTPException(
            status_code=404,
            detail="Veículo não encontrado"
        )

    database.delete(veiculo)
    database.commit()

    return None