import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from config import settings
from App.database import Base, engine
from App.models import Arquivo, DriveConexao, WhatsappConversa, WhatsappMensagem
from Router.Login import router as login
from Router.Usuarios.CriarUsers import router as criarUser
from Router.Usuarios.GerenciarUsers import router as gerenciarUsers
from Router.Pessoa.CadastrarPessoas import router as criarPessoa
from Router.Pessoa.EditarPessoas import router as editarPessoa
from Router.Pessoa.ExcluirPessoas import router as excluirPessoa
from Router.Pessoa.ListarPessoas import router as listarPessoas
from Router.Pessoa.AcessoPessoas import router as acessoPessoas
from Router.Pessoa.FuncionarioPessoas import router as funcionarioPessoas
from Router.Eu import router as eu
from Router.Condominios import router as condominios
from Router.Apartamentos import router as apartamentos
from Router.Vagas import router as vagas
from Router.Veiculos import router as veiculos
from Router.Financeiro import router as financeiro
from Router.Avisos import router as avisos
from Router.Chamados import router as chamados
from Router.Tarefas import router as tarefas
from Router.Cargos import router as cargos
from Router.WhatsApp import router as whatsapp
from Router.Administracao import router as administracao
from Router.Drive import router as drive
from Router.Movimentacoes import router as movimentacoes
from Router.Fracoes import router as fracoes
from Router.Manutencoes import router as manutencoes

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # tabelas do WhatsApp (teste): criadas se ainda não existirem
    Base.metadata.create_all(engine, tables=[WhatsappConversa.__table__, WhatsappMensagem.__table__, DriveConexao.__table__, Arquivo.__table__])
    # categoria RESPONSÁVEL (recebe o WhatsApp): coluna nova em users
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS responsavel boolean NOT NULL DEFAULT false"))
        connection.execute(text("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS responsavel_user_id uuid REFERENCES users(id) ON DELETE SET NULL"))
        # robô do WhatsApp
        connection.execute(text("ALTER TABLE whatsapp_conversas ADD COLUMN IF NOT EXISTS modo varchar(10) NOT NULL DEFAULT 'ROBO'"))
        connection.execute(text("ALTER TABLE whatsapp_conversas ADD COLUMN IF NOT EXISTS atendente_desde timestamptz"))
        connection.execute(text("ALTER TABLE whatsapp_conversas ADD COLUMN IF NOT EXISTS bot_dados text"))
        connection.execute(text("ALTER TABLE whatsapp_mensagens ADD COLUMN IF NOT EXISTS para_atendente boolean NOT NULL DEFAULT false"))
        # foto da pessoa (Google Drive)
        connection.execute(text("ALTER TABLE pessoas ADD COLUMN IF NOT EXISTS foto_arquivo_id uuid REFERENCES arquivos(id) ON DELETE SET NULL"))
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
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
app.include_router(gerenciarUsers, prefix="/users", tags=["Usuários"])
app.include_router(eu, prefix="/eu", tags=["Autenticação"])
app.include_router(condominios, tags=["Condomínios"])
app.include_router(apartamentos, tags=["Apartamentos"])
app.include_router(vagas, tags=["Vagas"])
app.include_router(veiculos, tags=["Veículos"])
app.include_router(financeiro, tags=["Financeiro"])
app.include_router(avisos, tags=["Avisos"])
app.include_router(chamados, tags=["Atendimento"])
app.include_router(tarefas, tags=["Tarefas"])
app.include_router(criarPessoa, prefix="/pessoas", tags=["Pessoas"])
app.include_router(editarPessoa, prefix="/pessoas", tags=["Pessoas"])
app.include_router(excluirPessoa, prefix="/pessoas", tags=["Pessoas"])
app.include_router(listarPessoas, prefix="/pessoas", tags=["Pessoas"])
app.include_router(acessoPessoas, prefix="/pessoas", tags=["Pessoas"])
app.include_router(funcionarioPessoas, prefix="/pessoas", tags=["Pessoas"])
app.include_router(cargos, tags=["Funcionários"])
app.include_router(whatsapp, tags=["WhatsApp"])
app.include_router(administracao, tags=["Administração geral"])
app.include_router(drive, tags=["Arquivos (Google Drive)"])
app.include_router(movimentacoes, tags=["Movimentações bancárias"])
app.include_router(fracoes, tags=["Fração ideal"])
app.include_router(manutencoes, tags=["Manutenções e prestadores"])

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
