from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    database_url: str
    groq_api_key: str

    model_config = {
        "env_file": ".env"
    }

settings = Settings()