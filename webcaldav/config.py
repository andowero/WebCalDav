from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./webcaldav.db"
    log_level: str = "INFO"
    session_idle_timeout: int = 3600

    # When true, reject CalDAV server URLs that resolve to private/loopback/
    # link-local/metadata addresses and suppress raw connection-error detail
    # (SSRF hardening). Off by default for backward compatibility.
    block_private_caldav_urls: bool = False

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 1

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
