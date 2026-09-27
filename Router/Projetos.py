# # PROJETOS

# import uuid
# from datetime import date
# from fastapi import APIRouter, Depends, HTTPException, status
# from pydantic import BaseModel, ConfigDict
# from sqlalchemy import Boolean, Date, String, Text, select
# from sqlalchemy.dialects.postgresql import UUID
# from sqlalchemy.orm import Mapped, Session, mapped_column
# from App.database import Base, get_database
# from App.dependencies import get_current_user

# router = APIRouter(prefix="/projetos")

# class Projeto(Base):
#     __tablename__ = "projetos"
#     id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#     projeto: Mapped[str] = mapped_column(String(180), nullable=False)
#     descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
#     ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
#     dataCriacao: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
#     dataAtualizacao: Mapped[date] = mapped_column(Date, default=date.today, onupdate=date.today, nullable=False)
#     dataArquivamento: Mapped[date | None] = mapped_column(Date, nullable=True)

# class ProjetoCriar(BaseModel):
#     projeto: str
#     descricao: str | None = None
#     ativo: bool = True

# class ProjetoEditar(BaseModel):
#     projeto: str | None = None
#     descricao: str | None = None

# class ProjetoResposta(BaseModel):
#     id: uuid.UUID
#     projeto: str
#     descricao: str | None
#     ativo: bool
#     dataCriacao: date
#     dataAtualizacao: date
#     dataArquivamento: date | None
#     model_config = ConfigDict(from_attributes=True)

# def buscar_projeto_ou_404(projeto_id: uuid.UUID, database: Session) -> Projeto:
#     projeto = database.get(Projeto, projeto_id)
#     if not projeto:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projeto não encontrado")
#     return projeto

# # ROTAS

# @router.post("/", response_model=ProjetoResposta, status_code=status.HTTP_201_CREATED)
# async def criarProjeto(dados: ProjetoCriar,database: Session = Depends(get_database),usuario_atual=Depends(get_current_user)):
#     novo_projeto = Projeto(projeto=dados.projeto, descricao=dados.descricao, ativo=dados.ativo)
#     database.add(novo_projeto)
#     database.commit()
#     database.refresh(novo_projeto)
#     return novo_projeto

# @router.get("/", response_model=list[ProjetoResposta])
# async def listarProjetos(database: Session = Depends(get_database),usuario_atual=Depends(get_current_user)):
#     return database.scalars(select(Projeto).order_by(Projeto.dataCriacao.desc())).all()

# @router.put("/{projeto_id}", response_model=ProjetoResposta)
# async def editarProjeto(projeto_id: uuid.UUID,dados: ProjetoEditar,database: Session = Depends(get_database),usuario_atual=Depends(get_current_user)):
#     projeto = buscar_projeto_ou_404(projeto_id, database)
#     dados_atualizados = dados.model_dump(exclude_unset=True)
#     for campo, valor in dados_atualizados.items():
#         setattr(projeto, campo, valor)
#     projeto.dataAtualizacao = date.today()
#     database.commit()
#     database.refresh(projeto)
#     return projeto

# @router.patch("/{projeto_id}/arquivar", response_model=ProjetoResposta)
# async def arquivarProjeto(projeto_id: uuid.UUID,database: Session = Depends(get_database),usuario_atual=Depends(get_current_user)):
#     projeto = buscar_projeto_ou_404(projeto_id, database)
#     projeto.ativo = False
#     projeto.dataArquivamento = date.today()
#     projeto.dataAtualizacao = date.today()
#     database.commit()
#     database.refresh(projeto)
#     return projeto

# @router.patch("/{projeto_id}/restaurar", response_model=ProjetoResposta)
# async def restaurarProjeto(projeto_id: uuid.UUID,database: Session = Depends(get_database),usuario_atual=Depends(get_current_user)):
#     projeto = buscar_projeto_ou_404(projeto_id, database)
#     projeto.ativo = True
#     projeto.dataArquivamento = None
#     projeto.dataAtualizacao = date.today()
#     database.commit()
#     database.refresh(projeto)
#     return projeto

# @router.delete("/{projeto_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def excluirProjeto(projeto_id: uuid.UUID,database: Session = Depends(get_database),usuario_atual=Depends(get_current_user)):
#     projeto = buscar_projeto_ou_404(projeto_id, database)
#     database.delete(projeto)
#     database.commit()
