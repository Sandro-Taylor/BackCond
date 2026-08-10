# ---------------------------------------------------------
# APLICAÇÃO PRINCIPAL
# Este arquivo inicia a API e disponibiliza as rotas do sistema.
# ---------------------------------------------------------

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from config import settings

from App.database import engine
from Router.Login import router as login
from Router.Users import router as criar_user
from Router.Eu import router as eu
# from Router.Org import router as criarOrganizacao
# from Router.Dep import router as listarDep
from Router.Colaboradores import router as colaboradores
from Router.Projetos import router as projetos
from Router.Setores import router as setores
from Router.Tarefas import router as tarefas


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
app.include_router(criar_user, prefix="/users", tags=["Autenticação"])
app.include_router(eu, prefix="/eu", tags=["Autenticação"])
# app.include_router(criarOrganizacao, prefix="/org", tags=["Organização"])
# app.include_router(listarDep, prefix="/dep", tags=["Departamentos"])
app.include_router(colaboradores, tags=["Colaboradores"])
app.include_router(projetos, tags=["Projetos"])
app.include_router(setores, tags=["Setores"])
app.include_router(tarefas, tags=["Tarefas"])

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