import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from config import settings

from App.database import engine
from Router.Login import router as login
from Router.Usuarios.CriarUsers import router as criarUser

from Router.Pessoa.CadastrarPessoas import router as criarPessoa
from Router.Pessoa.EditarPessoas import router as editarPessoa
from Router.Pessoa.ExcluirPessoas import router as excluirPessoa
from Router.Pessoa.ListarPessoas import router as listarPessoas
from Router.Eu import router as eu
from Router.Pessoa.Moradores import router as colaboradores
# from Router.Projetos import router as projetos
from Router.Setores import router as setores
from Router.Tarefas import router as tarefas
from Router.Condominios import router as condominios

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro das rotas
app.include_router(login, prefix="/login", tags=["Autenticação"])
app.include_router(criarUser, prefix="/users", tags=["Autenticação"])
app.include_router(eu, prefix="/eu", tags=["Autenticação"])
# app.include_router(criarOrganizacao, prefix="/org", tags=["Organização"])
# app.include_router(listarDep, prefix="/dep", tags=["Departamentos"])
app.include_router(colaboradores, tags=["Colaboradores"])
app.include_router(setores, tags=["Setores"])
app.include_router(condominios, tags=["Condomínios"])
app.include_router(tarefas, tags=["Tarefas"])

app.include_router(criarPessoa, prefix="/pessoas", tags=["Pessoas"])
app.include_router(editarPessoa, prefix="/pessoas", tags=["Pessoas"])
app.include_router(excluirPessoa, prefix="/pessoas", tags=["Pessoas"])
app.include_router(listarPessoas, prefix="/pessoas", tags=["Pessoas"])

@app.get("/")
async def root():
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "status": "online",
    }

@app.get("/health")
async def health_check():
    with engine.connect() as connection: connection.execute(text("SELECT 1"))
    return {"status": "healthy","database": "connected"}

if __name__ == "__main__":
    uvicorn.run( "app:app",host="127.0.0.1",port=8000,reload=True)
