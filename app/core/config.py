from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SafeDoc API"
    root_path: str = ""
    secret_key: str = "CHANGE_ME_IN_PROD"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    jwt_cookie_name: str = "safedoc_access_token"
    jwt_cookie_samesite: str = "lax"
    jwt_cookie_secure: bool = False
    jwt_cookie_domain: str | None = None

    enable_https_redirect: bool = False
    trusted_hosts: str = "localhost,127.0.0.1,testserver"

    database_url: str = "postgresql+asyncpg://safedoc:safedoc_pass@localhost:5432/safedoc"

    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "safedoc"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 10

    default_superadmin_login: str = "admin"
    default_superadmin_password: str = "admin123"
    max_file_size_mb: int = Field(default=300, gt=0)
    internal_service_token: str = "safedoc-internal-token"
    audit_service_url: str | None = None
    notification_service_url: str | None = None
    access_control_service_url: str | None = None

    storage_dir: str = "storage"
    logs_dir: str = "logs"
    local_storage_migration_interval_seconds: int = Field(default=60, gt=0)
    audit_log_archive_interval_seconds: int = Field(default=60, gt=0)

    cors_origins: str = "http://localhost,http://127.0.0.1"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()
