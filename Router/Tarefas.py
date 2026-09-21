# # ---------------------------------------------------------
# # TAREFAS
# # ---------------------------------------------------------

# import uuid
# from datetime import datetime

# from fastapi import APIRouter, Depends, HTTPException, status
# from pydantic import BaseModel, ConfigDict, Field
# from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, select
# from sqlalchemy.dialects.postgresql import UUID
# from sqlalchemy.orm import Mapped, Session, mapped_column
# from sqlalchemy.sql import func

# from App.database import Base, get_database
# from App.dependencies import get_current_user
# from Router.Moradores.Moradores import Colaborador
# from Router.Projetos import Projeto


# router = APIRouter(prefix="/tarefas")


# class Tarefa(Base):
#     __tablename__ = "tarefas"

#     id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         primary_key=True,
#         server_default=func.gen_random_uuid(),
#     )

#     idProjeto: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("projetos.id"),
#         nullable=False,
#     )

#     idResponsavel: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("colaboradores.idColaborador"),
#         nullable=False,
#     )

#     tarefa: Mapped[str] = mapped_column(String(240), nullable=False)

#     descricao: Mapped[str | None] = mapped_column(Text, nullable=True)

#     prioridade: Mapped[str] = mapped_column(
#         String(10),
#         default="media",
#         server_default="media",
#         nullable=False,
#     )

#     prazo: Mapped[datetime | None] = mapped_column(
#         DateTime(timezone=True),
#         nullable=True,
#     )

#     dataCriacao: Mapped[datetime] = mapped_column(
#         DateTime(timezone=True),
#         server_default=func.now(),
#     )

#     dataAtualizacao: Mapped[datetime] = mapped_column(
#         DateTime(timezone=True),
#         server_default=func.now(),
#         onupdate=func.now(),
#     )

#     dataConclusao: Mapped[datetime | None] = mapped_column(
#         DateTime(timezone=True),
#         nullable=True,
#     )

#     status: Mapped[str | None] = mapped_column(String(80), nullable=True)

#     ativo: Mapped[bool] = mapped_column(
#         Boolean,
#         default=True,
#         server_default="true",
#         nullable=False,
#     )

#     dataArquivamento: Mapped[datetime | None] = mapped_column(
#         DateTime(timezone=True),
#         nullable=True,
#     )


# # ---------------------------------------------------------
# # SCHEMAS
# # ---------------------------------------------------------

# class TarefaCriar(BaseModel):
#     idProjeto: uuid.UUID
#     idResponsavel: uuid.UUID
#     tarefa: str = Field(min_length=3, max_length=240)
#     descricao: str | None = None
#     prioridade: str = "media"
#     prazo: datetime | None = None
#     status: str | None = None


# class TarefaEditar(BaseModel):
#     idProjeto: uuid.UUID | None = None
#     idResponsavel: uuid.UUID | None = None
#     tarefa: str | None = None
#     descricao: str | None = None
#     prioridade: str | None = None
#     prazo: datetime | None = None
#     status: str | None = None


# class TarefaResposta(BaseModel):
#     id: uuid.UUID
#     idProjeto: uuid.UUID
#     idResponsavel: uuid.UUID
#     tarefa: str
#     descricao: str | None
#     prioridade: str
#     prazo: datetime | None
#     dataCriacao: datetime
#     dataAtualizacao: datetime
#     dataConclusao: datetime | None
#     status: str | None
#     ativo: bool
#     dataArquivamento: datetime | None

#     model_config = ConfigDict(from_attributes=True)


# class ProjetoOpcao(BaseModel):
#     id: uuid.UUID
#     projeto: str


# class ColaboradorOpcao(BaseModel):
#     idColaborador: uuid.UUID
#     nome: str
#     cpf: str
#     cargo: str | None


# class TarefaOpcoesResposta(BaseModel):
#     projetos: list[ProjetoOpcao]
#     colaboradores: list[ColaboradorOpcao]


# def buscar_tarefa_ou_404(tarefa_id: uuid.UUID, database: Session) -> Tarefa:
#     tarefa = database.get(Tarefa, tarefa_id)
#     if not tarefa:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarefa não encontrada")
#     return tarefa


# # ---------------------------------------------------------
# # ROTAS
# # ---------------------------------------------------------

# @router.get("/opcoes", response_model=TarefaOpcoesResposta)
# async def opcoesTarefas(
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     projetos = database.scalars(
#         select(Projeto).where(Projeto.ativo.is_(True)).order_by(Projeto.projeto)
#     ).all()

#     colaboradores = database.scalars(
#         select(Colaborador).where(Colaborador.ativo.is_(True)).order_by(Colaborador.nome)
#     ).all()

#     return {
#         "projetos": projetos,
#         "colaboradores": colaboradores,
#     }


# @router.post("/", response_model=TarefaResposta, status_code=status.HTTP_201_CREATED)
# async def criarTarefa(
#     dados: TarefaCriar,
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     projeto = database.get(Projeto, dados.idProjeto)
#     if not projeto:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")

#     responsavel = database.get(Colaborador, dados.idResponsavel)
#     if not responsavel:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Responsável não encontrado")

#     nova_tarefa = Tarefa(
#         idProjeto=dados.idProjeto,
#         idResponsavel=dados.idResponsavel,
#         tarefa=dados.tarefa,
#         descricao=dados.descricao,
#         prioridade=dados.prioridade,
#         prazo=dados.prazo,
#         status=dados.status,
#     )

#     database.add(nova_tarefa)
#     database.commit()
#     database.refresh(nova_tarefa)
#     return nova_tarefa


# @router.get("/", response_model=list[TarefaResposta])
# async def listarTarefas(
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     return database.scalars(select(Tarefa).order_by(Tarefa.dataCriacao.desc())).all()


# @router.put("/{tarefa_id}", response_model=TarefaResposta)
# async def editarTarefa(
#     tarefa_id: uuid.UUID,
#     dados: TarefaEditar,
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     tarefa = buscar_tarefa_ou_404(tarefa_id, database)

#     dados_atualizados = dados.model_dump(exclude_unset=True)

#     if "idProjeto" in dados_atualizados:
#         projeto = database.get(Projeto, dados_atualizados["idProjeto"])
#         if not projeto:
#             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")

#     if "idResponsavel" in dados_atualizados:
#         responsavel = database.get(Colaborador, dados_atualizados["idResponsavel"])
#         if not responsavel:
#             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Responsável não encontrado")

#     for campo, valor in dados_atualizados.items():
#         setattr(tarefa, campo, valor)

#     database.commit()
#     database.refresh(tarefa)
#     return tarefa


# @router.patch("/{tarefa_id}/arquivar", response_model=TarefaResposta)
# async def arquivarTarefa(
#     tarefa_id: uuid.UUID,
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     tarefa = buscar_tarefa_ou_404(tarefa_id, database)
#     tarefa.ativo = False
#     tarefa.dataArquivamento = datetime.now()
#     database.commit()
#     database.refresh(tarefa)
#     return tarefa


# @router.patch("/{tarefa_id}/restaurar", response_model=TarefaResposta)
# async def restaurarTarefa(
#     tarefa_id: uuid.UUID,
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     tarefa = buscar_tarefa_ou_404(tarefa_id, database)
#     tarefa.ativo = True
#     tarefa.dataArquivamento = None
#     database.commit()
#     database.refresh(tarefa)
#     return tarefa


# @router.delete("/{tarefa_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def excluirTarefa(
#     tarefa_id: uuid.UUID,
#     database: Session = Depends(get_database),
#     usuario_atual=Depends(get_current_user),
# ):
#     tarefa = buscar_tarefa_ou_404(tarefa_id, database)
#     database.delete(tarefa)
#     database.commit()