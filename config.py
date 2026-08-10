# ---------------------------------------------------------
# CONFIGURAÇÕES DA APLICAÇÃO
# ---------------------------------------------------------
# Este arquivo carrega as configurações armazenadas no arquivo .env.
# ---------------------------------------------------------

from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi.security import HTTPBearer

authentication = HTTPBearer()

class Settings(BaseSettings):
    app_name: str = "GT - Gerenciador de Tarefas"
    app_version: str = "1.0.0"
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()