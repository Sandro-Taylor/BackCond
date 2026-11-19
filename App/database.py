# ---------------------------------------------------------
# CONEXÃO COM O BANCO (PostgreSQL)
# ---------------------------------------------------------
# DATABASE_URL: postgresql+psycopg://usuario:senha@host:5432/banco
# Datas/horas gravadas com fuso (timestamptz); o front mostra no horário de Brasília.
# ---------------------------------------------------------

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=280)


@event.listens_for(engine, "connect")
def _sessao_utc(conexao, _registro):
    # só para MySQL (o sistema usa Postgres): NOW() em UTC
    if engine.dialect.name == "mysql":
        cursor = conexao.cursor()
        cursor.execute("SET time_zone = '+00:00'")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_database():
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
