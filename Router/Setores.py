import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from App.database import Base, get_database
from App.dependencies import get_current_user

router = APIRouter(prefix="/setores")


class Setor(Base):
    __tablename__ = "setores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    setor: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )


class SetorCriar(BaseModel):
    nome: str


class SetorResposta(BaseModel):
    id: uuid.UUID
    nome: str

    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/",
    response_model=SetorResposta,
    status_code=status.HTTP_201_CREATED,
)
async def criarSetor(
    dados: SetorCriar,
    database: Session = Depends(get_database),
    usuario_atual=Depends(get_current_user),
):
    existente = database.scalar(
        select(Setor).where(Setor.setor == dados.nome)
    )

    if existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um setor com esse nome",
        )

    novo_setor = Setor(setor=dados.nome)
    database.add(novo_setor)
    database.commit()
    database.refresh(novo_setor)

    return {
        "id": novo_setor.id,
        "nome": novo_setor.setor,
    }


@router.get("/", response_model=list[SetorResposta])
async def listarSetores(
    database: Session = Depends(get_database),
):
    setores = database.scalars(
        select(Setor).order_by(Setor.setor)
    ).all()

    return [
        {
            "id": setor.id,
            "nome": setor.setor,
        }
        for setor in setores
    ]