from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: str = "dev"
    database_url: str = "postgresql+asyncpg://rento:rento@localhost:5441/rento"
    test_database_url: str = "postgresql+asyncpg://rento:rento@localhost:5441/rento_test"
    redis_url: str = "redis://localhost:6391/0"

    s3_endpoint_url: str = "http://localhost:9110"
    s3_public_endpoint_url: str = "http://localhost:9110"
    s3_access_key: str = "rentominio"
    s3_secret_key: str = "rentominio-dev-secret"
    s3_bucket: str = "rento"
    s3_region: str = "us-east-1"

    jwt_secret: str = Field(default="dev-only-change-me-dev-only-change-me", min_length=32)
    link_secret: str = Field(default="dev-only-link-secret-change-me", min_length=16)
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""

    timezone: str = "Asia/Tashkent"
    app_base_url: str = "http://localhost:3010"
    cors_origins: str = "http://localhost:3010"

    max_photo_bytes: int = 8 * 1024 * 1024

    @model_validator(mode="after")
    def _no_dev_secrets_in_prod(self) -> "Settings":
        if self.environment == "prod" and (
            self.jwt_secret.startswith("dev-only")
            or self.link_secret.startswith("dev-only")
            or self.s3_secret_key == "rentominio-dev-secret"
        ):
            raise ValueError("Refusing to start in prod with dev default secrets")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
