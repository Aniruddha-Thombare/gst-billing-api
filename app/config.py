from typing import Literal
from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):
    database_url : str
    environment : Literal["development", "production", "testing"]
    secret_key : str
    access_token_expire_minutes : int = 30
    redis_url : str 

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False  
    )


settings = Settings()