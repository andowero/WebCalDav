from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./webcaldav.db"
    log_level: str = "INFO"
    session_idle_timeout: int = 3600

    # Reverse-proxy header authentication. When enabled, users can be
    # auto-authenticated from a trusted upstream identity header.
    # Keep off by default; this mode assumes the app is reachable only behind
    # a proxy that strips/spoofs the configured header safely.
    header_authentication: bool = False
    header_auth_header_name: str = "Remote-User"
    header_auth_secret: str | None = None

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

    # Toggle the MCP server (mounted at /mcp) on or off. Off by default: when
    # off, /mcp is not mounted and new API tokens cannot be created (existing
    # tokens can still be listed and revoked). An API token can decrypt the
    # user's CalDAV credentials, so this stays opt-in.
    mcp_server_enabled: bool = False

    # Toggle calendar sharing (the share buttons + POST /shares). On by default.
    # When off, new shares cannot be created (existing shares can still be
    # listed and revoked). A share secret can decrypt the user's CalDAV
    # credentials, same as an API token, so it can be disabled per deployment.
    sharing_enabled: bool = True

    # Public base URL used to build share links, e.g.
    # "https://calendar.zdeneknovak.one". When unset, the URL is derived from
    # the X-Forwarded-Proto / X-Forwarded-Host headers the reverse proxy sets
    # (falling back to the request Host). Set this when those headers are
    # unreliable.
    public_base_url: str | None = None

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
