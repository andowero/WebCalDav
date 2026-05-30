# Changelog

## Unreleased — MVP

### Added — CalDAV wiring (2026-05-30)
- Real CalDAV event fetching in `GET /events` (read-only): per-calendar parallel
  fetch, parsed via the `icalendar` library; supports timed (TZID), all-day, and
  duration-based events.
- `POST /caldav-accounts` connects to the server, enumerates calendars, and reads
  each calendar's `calendar-color` (alpha-stripped to `#rrggbb`, fallback blue).
- Timezone picker (combo box populated from `Intl.supportedValuesOf`) and a
  persisted 12h/24h time-format setting (`UserSettings.time_format`); preference
  changes apply live without a page reload.
- Content-hash cache-busting on static JS/CSS so rebuilds are never served stale.
- In-process radicale integration tests for the CalDAV client layer.

### Fixed — CalDAV wiring (2026-05-30)
- Events were never displayed: parsing relied on `vobject`, which caldav 3.x makes
  optional — without it every event was dropped. Now parsed via `icalendar`.
- `GET /events` ignored the `from` query param (Python keyword shadowing), so the
  CalDAV search ran over a stale date window.
- Calendar colors were never read: `get_properties` was passed strings instead of
  `BaseElement` objects.

### Added — skeleton (2026-05-26)
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
- Automated tests across crypto, auth API, admin CLI, and CalDAV layers.
- Multi-stage `Dockerfile` + `docker-compose.yml`.
