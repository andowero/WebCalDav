# Changelog

## Unreleased — MVP

### Added
- Full application skeleton: FastAPI + SQLAlchemy 2.x + SQLite (WAL).
- Zero-knowledge auth: argon2id KEK, AES-GCM DEK wrapping, HKDF password verifier.
- Admin CLI (`python -m webcaldav.admin`): `create-user`, `list-users`, `reset-password`, `delete-user`.
- Forced first-login password change; restricted session blocks all routes except change-password and logout.
- Timing-safe login to prevent user enumeration.
- In-memory session store with configurable idle timeout and injectable clock.
- REST API: auth, caldav-accounts, calendars, events, settings, health, metrics.
- Prometheus metrics: `active_sessions`, `http_requests_total`, `caldav_request_duration_seconds`, `caldav_request_errors_total`.
- Structured JSON logging via `structlog`.
- FullCalendar.js frontend: login → first-login change-password → calendar views (month/week/day).
- Dummy demo events shown until user connects a CalDAV server.
- 26 automated tests across crypto, auth API, and admin CLI layers.
- Multi-stage `Dockerfile` + `docker-compose.yml`.
