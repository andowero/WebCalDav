# Project status

## Milestones

| Milestone | Scope                                                     | Status      |
|-----------|-----------------------------------------------------------|-------------|
| MVP       | Secure user login, read-only view of calendar events      | Complete    |
| v1        | Editing of calendar events → from, to, all-day, name     | Not started |
| v2        | Editing of calendar events → notes, location, reminders  | Not started |
| v3        | Editing of calendar events → repetition                  | Not started |
| v4        | Browser notifications                                     | Not started |

## What has been accomplished

### MVP — secure login + dummy calendar (2026-05-26)

Full application skeleton implemented and tested.

**Auth & security**
- Zero-knowledge design: argon2id KEK derivation, AES-GCM DEK wrapping, HKDF-based password verifier.
- Admin CLI (`python -m webcaldav.admin`): `create-user`, `list-users`, `reset-password`, `delete-user`.
- First-login forced password change flow: restricted sessions block all routes except `/auth/change-password` and `/auth/logout`.
- Timing-safe login (dummy argon2 hash on unknown email).
- In-memory session store with idle timeout and injectable clock for tests.

**API surface**
- `POST /auth/login`, `POST /auth/logout`, `POST /auth/change-password`
- `GET/POST/DELETE /caldav-accounts`
- `GET /calendars`, `PATCH /calendars/{id}`
- `GET /events` (dummy demo events until real CalDAV is wired)
- `GET/PUT /settings`
- `GET /health`, `GET /metrics` (Prometheus)

**Frontend**
- Single Jinja2-rendered host page, state-driven JS.
- Login form → first-login change-password form → FullCalendar.js calendar.
- Dummy demo events shown until user connects a CalDAV server.

**Infrastructure**
- SQLAlchemy 2.x + SQLite WAL mode.
- Prometheus metrics: `active_sessions`, `http_requests_total`, `caldav_request_duration_seconds`, `caldav_request_errors_total`.
- `structlog` JSON logging, level controlled by `LOG_LEVEL`.
- Multi-stage `Dockerfile` + `docker-compose.yml`.
- `pyproject.toml` with `uv`, full dev toolchain (`ruff`, `mypy`, `pytest`).

**Tests — 26 passing**
- Crypto unit tests: KEK derivation determinism, DEK wrap/unwrap, AES-GCM roundtrip, verifier, nonce uniqueness.
- Auth API tests: full first-login flow, 401/403 boundaries, logout, no signup endpoint.
- Admin CLI tests: provisioning, verifier correctness, DEK roundtrip, password generation.

### CalDAV wiring (2026-05-30)

Read-only event viewing now works against real CalDAV servers (verified against Radicale).

- `POST /caldav-accounts` connects to the server, enumerates calendars, and stores each calendar's `calendar-color` (alpha-stripped to `#rrggbb`, fallback blue).
- `GET /events` fetches events per enabled calendar in parallel and parses them via the `icalendar` library (timed/TZID, all-day, and duration events).
- Settings: timezone combo box (`Intl.supportedValuesOf`), persisted 12h/24h time format (`UserSettings.time_format`); changes apply live with no page reload.
- Static JS/CSS are cache-busted by content hash.
- CalDAV integration tests added (in-process radicale): 29 tests passing total.

### Event detail viewer (2026-05-31)

Read-only detail window for events, foundation for the v1–v3 editing milestones.

- Clickable events open a resizable detail window showing name, duration (all-day
  + from/to), repetition, location, notes, and reminders. All fields read-only.
- `GET /events` enriched with `extendedProps`: `description`, `location`,
  `recurrence` (RRULE summary), `reminders` (VALARM triggers), `rawStart`/`rawEnd`.
  Recurrence/reminders recovered from unexpanded masters (second `expand=False`
  search), since expansion strips RRULE/VALARM from occurrences.
- Detail from/to respect the timezone + 12h/24h settings (`Intl` formatting).
- Named IANA timezones now render correctly in FullCalendar via the
  `@fullcalendar/luxon3` plugin (base bundle only supported `local`/`UTC`),
  fixing calendar-vs-detail time mismatches for offset-shifted events.

## What is next

- Complete v1 milestone: event create/update/delete via PUT/POST/DELETE `/events`,
  reusing the detail window as an edit form.
