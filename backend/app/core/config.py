"""Validated settings loaded once for each application instance."""

from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Only configuration consumed by the current foundation module."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTFLOW_",
        env_file=BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="AgentFlow API", min_length=1, max_length=100)
    environment: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    docs_enabled: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    trace_export_enabled: bool = False
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    groq_api_key: SecretStr | None = Field(default=None, validation_alias="GROQ_API_KEY")
    groq_model: str = Field(
        default="openai/gpt-oss-120b", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$"
    )
    groq_timeout_seconds: int = Field(default=45, ge=1, le=120)
    connection_encryption_key: SecretStr | None = None
    gmail_client_id: str | None = Field(default=None, min_length=1, max_length=300)
    gmail_client_secret: SecretStr | None = None
    gmail_redirect_uri: str | None = Field(default=None, min_length=1, max_length=500)
    worker_queue: str = Field(default="agentflow.transport", min_length=1, max_length=80)
    background_execution_enabled: bool = False
    worker_lease_seconds: int = Field(default=30, ge=5, le=3600)
    worker_redelivery_seconds: int = Field(default=30, ge=5, le=3600)
    worker_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    worker_retry_max_seconds: int = Field(default=60, ge=1, le=3600)
    jwt_secret_key: SecretStr | None = None
    jwt_issuer: str = Field(default="agentflow", min_length=1, max_length=100)
    jwt_audience: str = Field(default="agentflow-api", min_length=1, max_length=100)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)
    refresh_cookie_secure: bool = True
    auth_allowed_origins: tuple[str, ...] = Field(
        default=(
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ),
        min_length=1,
        max_length=10,
    )

    @field_validator("auth_allowed_origins")
    @classmethod
    def validate_auth_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            try:
                parsed = urlsplit(value)
                valid = (
                    parsed.scheme in {"http", "https"}
                    and bool(parsed.hostname)
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                    and "*" not in value
                    and "\\" not in value
                    and value.isascii()
                    and not any(character.isspace() for character in value)
                    and len(value) <= 300
                    and (parsed.port is None or 1 <= parsed.port <= 65535)
                    and value == f"{parsed.scheme}://{parsed.netloc}"
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("auth_allowed_origins must contain exact HTTP(S) origins")
        return values

    @field_validator("gmail_redirect_uri")
    @classmethod
    def validate_gmail_redirect_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname is not None
                and parsed.username is None
                and parsed.password is None
                and parsed.path == "/integrations/gmail/callback"
                and not parsed.query
                and not parsed.fragment
                and value.isascii()
                and "\\" not in value
                and not any(character.isspace() for character in value)
                and (parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1"})
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("gmail_redirect_uri must be a valid fixed callback URL")
        return value

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def reject_key_whitespace(cls, value: Any) -> Any:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str) and secret != secret.strip():
            raise ValueError("jwt_secret_key must not contain outer whitespace")
        return value

    @field_validator("connection_encryption_key")
    @classmethod
    def validate_connection_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            from app.modules.connections.secrets import ConnectionUnavailableError, cipher

            try:
                cipher(value)
            except ConnectionUnavailableError:
                raise ValueError("connection_encryption_key must be a Fernet key") from None
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_signing_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            secret = value.get_secret_value()
            if not 32 <= len(secret.encode("utf-8")) <= 4096 or secret != secret.strip():
                raise ValueError(
                    "jwt_secret_key must contain 32–4096 bytes without outer whitespace"
                )
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Require the supported driver and an explicit host/database without echoing secrets."""
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
            valid = (
                url.drivername == "postgresql+psycopg"
                and bool(url.host)
                and bool(url.database)
                and (url.port is None or 1 <= url.port <= 65535)
            )
        except (ArgumentError, ValueError):
            valid = False
        if not valid:
            raise ValueError("database_url must use postgresql+psycopg with a host and database")
        return value

    @field_validator("worker_queue")
    @classmethod
    def validate_worker_queue(cls, value: str) -> str:
        import re

        if re.fullmatch(r"agentflow\.[a-z0-9][a-z0-9._-]{0,69}", value) is None:
            raise ValueError("worker_queue must use the agentflow queue namespace")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        try:
            parsed = urlsplit(raw)
            valid = (
                parsed.scheme in {"redis", "rediss"}
                and bool(parsed.hostname)
                and (parsed.port is None or 1 <= parsed.port <= 65535)
                and parsed.path in {f"/{number}" for number in range(16)}
                and not parsed.query
                and not parsed.fragment
                and raw.isascii()
                and len(raw) <= 2048
                and not any(character.isspace() for character in raw)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("redis_url must use redis/rediss with a host and database 0–15")
        return value

    @model_validator(mode="after")
    def reject_production_debug(self) -> Self:
        """Prevent traceback responses from being enabled in production."""
        if self.environment == "production" and self.debug:
            raise ValueError("debug must be disabled in production")
        if self.worker_retry_max_seconds < self.worker_retry_base_seconds:
            raise ValueError("worker_retry_max_seconds must be at least worker_retry_base_seconds")
        if self.background_execution_enabled and (
            self.database_url is None or self.redis_url is None
        ):
            raise ValueError("background execution requires database_url and redis_url")
        if self.environment == "production":
            if not self.refresh_cookie_secure:
                raise ValueError("refresh_cookie_secure must be enabled in production")
            if self.jwt_secret_key is not None and any(
                not origin.startswith("https://") for origin in self.auth_allowed_origins
            ):
                raise ValueError("production authentication requires HTTPS origins")
            if self.redis_url is not None:
                redis = urlsplit(self.redis_url.get_secret_value())
                if redis.scheme != "rediss" or not redis.password:
                    raise ValueError("production Redis requires TLS and a password")
        return self


class ConfigurationError(RuntimeError):
    """Invalid application configuration, reported without supplied values."""


def load_settings() -> Settings:
    """Read environment/dotenv once; expose field errors without raw inputs."""
    try:
        return Settings()
    except SettingsError:
        raise ConfigurationError(
            "Invalid AgentFlow configuration: settings source could not be parsed."
        ) from None
    except ValidationError as exc:
        problems = []
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            field = ".".join(str(part) for part in error["loc"]) or "settings"
            problems.append(f"{field}: {error['msg']}")
        raise ConfigurationError(
            "Invalid AgentFlow configuration: " + "; ".join(problems)
        ) from None
