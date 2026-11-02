from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi.security import HTTPBearer

authentication = HTTPBearer()

class Settings(BaseSettings):
    app_name: str = "Gestão Condominial"
    app_version: str = "1.0.0"
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60
    # WhatsApp (Evolution API - serviço "whatsapp" do docker-compose)
    evolution_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instancia: str = "condominio"
    whatsapp_webhook_url: str = "http://host.docker.internal:8000/whatsapp/webhook"  # endereço do backend visto de dentro do Docker
    whatsapp_webhook_token: str = ""
    whatsapp_robo_ativo: bool = True          # atendimento automático (menu)
    whatsapp_horas_atendente: int = 6         # sem resposta do atendente por esse tempo: volta para o robô
    # Google Drive (armazenamento de arquivos)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/drive/callback"
    frontend_url: str = "http://localhost:5173"
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()