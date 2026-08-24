from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Team AI Gateway"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    public_base_url: str = "http://localhost:8000/v1"
    database_url: str = "sqlite+aiosqlite:///./data/ai_gateway.db"
    jwt_secret: SecretStr
    jwt_expire_minutes: int = 480
    api_key_pepper: SecretStr
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    glm_api_key: SecretStr = SecretStr("")
    glm_base_url: str = "https://open.bigmodel.cn/api/coding/paas/v4"
    kimi_api_key: SecretStr = SecretStr("")
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    qwen_api_key: SecretStr = SecretStr("")
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    max_api_keys_per_user: int = 3
    model_sync_enabled: bool = True
    model_sync_interval_seconds: int = 21600
    model_sync_initial_delay_seconds: int = 10
    cors_origins: Annotated[list[str], NoDecode] = []
    auto_migrate: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("public_base_url")
    @classmethod
    def trim_public_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def resolve_sqlite_path(cls, value: str) -> str:
        marker = "///./"
        if value.startswith("sqlite") and marker in value:
            prefix, relative_path = value.split(marker, 1)
            absolute_path = (BACKEND_DIR / relative_path).resolve().as_posix()
            return f"{prefix}///{absolute_path}"
        return value

    @field_validator("model_sync_interval_seconds")
    @classmethod
    def validate_model_sync_interval(cls, value: int) -> int:
        if value < 300:
            raise ValueError("MODEL_SYNC_INTERVAL_SECONDS不能小于300秒")
        return value

    @field_validator("model_sync_initial_delay_seconds")
    @classmethod
    def validate_model_sync_initial_delay(cls, value: int) -> int:
        if value < 0:
            raise ValueError("MODEL_SYNC_INITIAL_DELAY_SECONDS不能小于0")
        return value

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        jwt_value = self.jwt_secret.get_secret_value()
        pepper_value = self.api_key_pepper.get_secret_value()
        if len(jwt_value) < 32:
            raise ValueError("JWT_SECRET长度必须至少为32字符")
        if len(pepper_value) < 32:
            raise ValueError("API_KEY_PEPPER长度必须至少为32字符")
        if jwt_value.startswith("replace-with"):
            raise ValueError("JWT_SECRET仍是示例占位值")
        if pepper_value.startswith("replace-with"):
            raise ValueError("API_KEY_PEPPER仍是示例占位值")
        if not self.cors_origins:
            if self.is_production:
                raise ValueError("生产环境必须显式配置CORS_ORIGINS")
            self.cors_origins = ["http://localhost:5173"]
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS禁止使用通配符*")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
