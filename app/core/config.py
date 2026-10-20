"""Application settings, loaded from AGENCYOS_* environment variables."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = (  # noqa: S105 — placeholder, not a real secret
    "dev-only-secret-change-me-dev-only-secret"
)
_DEV_MFA_KEY = "41viZg081Ww-yoKpjf75xyCZUQNruwxDa8Ken-EqgOw="  # noqa: S105 — dev-only Fernet key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENCYOS_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Runtime connection: a non-owner role, so Row-Level Security is enforced.
    database_url: str = "postgresql+psycopg://agencyos_app:agencyos_app@localhost:5432/agencyos"
    # Schema-owner connection, used by Alembic only.
    migration_database_url: str = "postgresql+psycopg://agencyos:agencyos@localhost:5432/agencyos"
    db_pool_size: int = 10

    jwt_secret: SecretStr = SecretStr(_DEV_SECRET)
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    invite_ttl_days: int = 7
    password_reset_ttl_minutes: int = 30
    password_reset_rate_limit_per_hour: int = 5
    mfa_pending_token_ttl_minutes: int = 5

    # Fernet key (32 url-safe base64 bytes) for encrypting TOTP seeds at rest.
    # Generate a real one with `python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())"` for any non-dev environment.
    mfa_encryption_key: SecretStr = SecretStr(_DEV_MFA_KEY)
    mfa_issuer_name: str = "AgencyOS"
    mfa_recovery_code_count: int = 10

    idempotency_key_ttl_hours: int = 24

    login_rate_limit_per_5min: int = 10
    signup_rate_limit_per_hour: int = 5

    cors_origins: list[str] = ["http://localhost:5173"]
    cookie_secure: bool = True

    # Password hashing cost (argon2id). Tests lower these for speed.
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536

    max_failed_logins: int = 5
    lockout_minutes: int = 15

    otel_enabled: bool = False
    otel_exporter: Literal["console", "otlp"] = "console"
    otel_otlp_endpoint: str | None = None  # e.g. http://collector:4318/v1/traces
    otel_service_name: str = "agencyos-api"

    storage_dir: str = "./var/files"
    max_upload_bytes: int = 20 * 1024 * 1024

    email_backend: Literal["console", "memory", "smtp"] = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str = "noreply@agencyos.local"
    smtp_starttls: bool = True
    app_base_url: str = "http://localhost:5173"

    @model_validator(mode="after")
    def _require_real_secrets_in_prod(self) -> Self:
        if self.env == "prod":
            secret = self.jwt_secret.get_secret_value()
            if secret == _DEV_SECRET or len(secret) < 32:
                raise ValueError("AGENCYOS_JWT_SECRET must be set to a strong value in prod")
            if self.mfa_encryption_key.get_secret_value() == _DEV_MFA_KEY:
                raise ValueError(
                    "AGENCYOS_MFA_ENCRYPTION_KEY must be set to a strong value in prod"
                )
            if not self.cookie_secure:
                raise ValueError("AGENCYOS_COOKIE_SECURE must be true in prod")
            if "*" in self.cors_origins:
                raise ValueError("AGENCYOS_CORS_ORIGINS must not contain * in prod")
            invalid_origins = [
                origin for origin in self.cors_origins
                if not origin.startswith("https://")
                and origin not in {"http://localhost", "http://127.0.0.1"}
            ]
            if invalid_origins:
                raise ValueError("Production CORS origins must use HTTPS")
            if self.email_backend != "smtp":
                raise ValueError("AGENCYOS_EMAIL_BACKEND must be smtp in prod")
            if not self.smtp_host:
                raise ValueError("AGENCYOS_SMTP_HOST must be set in prod")
            if self.smtp_username and not self.smtp_password:
                raise ValueError("AGENCYOS_SMTP_PASSWORD is required when SMTP username is set")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
