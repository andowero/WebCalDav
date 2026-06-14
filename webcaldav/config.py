from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./webcaldav.db"
    log_level: str = "INFO"
    session_idle_timeout: int = 3600

    # When true, reject CalDAV server URLs that resolve to private/loopback/
    # link-local/metadata addresses and suppress raw connection-error detail
    # (SSRF hardening). Off by default for backward compatibility.
    block_private_caldav_urls: bool = False

    # Secure flag on the session cookie. Leave true behind a TLS-terminating
    # proxy (the intended deployment); set false only for plain-HTTP access
    # from non-localhost addresses (browsers exempt localhost).
    cookie_secure: bool = True

    # Per-IP throttle on POST /auth/login: at most `attempts` requests per
    # sliding `window` seconds. attempts=0 disables the limiter.
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300

    # Minimum length for passwords set via /auth/change-password.
    min_password_length: int = 12

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 131072
    argon2_parallelism: int = 1

    # How many days ahead the browser-notification scheduler loads events to
    # fire reminder/start notifications for. Raise it for reminders further out
    # (e.g. month-ahead birthdays).
    notification_horizon_days: int = 60

    # How many days *behind* now the scheduler also loads events for, so a
    # reminder anchored *after* an event that has already ended still fires
    # (e.g. "1 day after end"). Defaults to the horizon. Raise for after-event
    # reminders set further back than this.
    notification_lookback_days: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
