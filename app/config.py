from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings):

    # Strict Enforcement - Only three strings values are allowed
    ENVIRONMENT: Literal["development", "production", "testing"] = Field(default="development")
    
    # Used in OpenAPI Docs titles
    APP_NAME: str = Field(default="GST Billing API")

    # ... means it is required. If missing from .env - Immediate ValidationError at Startup
    # No Default values are provided because of security purpose
    DATABASE_URL: str = Field(...)
    REDIS_URL: str = Field(...)

    # min_length = 64 enforces a cryptograhically strong key 
    # Generated with: openssl rand -hex 64 
    # If someone gets this key they can forge tokens for ANY tenant.
    JWT_SECRET_KEY: str = Field(..., min_length=64)

    # 15 minutes is the industry standard for financial APIs.
    # Short enough that a stolen token expires before much damage is done.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default =15)

    # 7 days. Client uses this to get a new access token silently. 
    # Stored in DB so it can be revoked (unlike access tokens)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    # HS256 = HMAC with SHA-256. Symmetric — same key signs and verifies.
    # Upgrade path to RS256 (asymmetric) exists if you add a public key later.
    JWT_ALGORITHM: str = Field(default="HS256")
    
    model_config = SettingsConfigDict(
        env_file=".env",     # Read from .env file in project root
        env_file_encoding="utf-8",  # File encoding 
        case_sensitive=False   # DATABASE_URL and database_url both are accepted
    )

# SINGLETON INSTANCE: Instantiated ONCE at module load time.
# Every other file does: from app.config import settings
# They all get the same object — no re-reading the .env file repeatedly
settings = Settings()

