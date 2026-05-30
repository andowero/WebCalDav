# Changelog

## Unreleased — MVP

### Added — event detail viewer (2026-05-31)
- Clickable events open a read-only detail window (pointer cursor on hover):
  name, duration (all-day flag + from/to), repetition, location, notes, reminders.
  All fields read-only; the all-day and repeats checkboxes toggle their dependent
  sections. Click outside / ✕ / Esc closes; window resizable (default = minimum,
  sized to fit all fields).
- `GET /events` now emits `extendedProps` per event: `description`, `location`,
  `recurrence` (human-readable RRULE summary), `reminders` (VALARM triggers as
  "15 minutes before"), plus `rawStart`/`rawEnd` for client-side formatting.
- Recurrence/reminders recovered from unexpanded master components: the expanded
  search strips RRULE/VALARM from occurrences, so a second `expand=False` search
  builds a UID→props map merged into each occurrence.

### Fixed — event detail viewer (2026-05-31)
- Detail from/to now respect timezone + 12h/24h settings (formatted via `Intl`
  with the configured `timeZone`) instead of the browser's locale defaults.
- All-day "to" was off by one day: iCal all-day `DTEND` is exclusive, so the
  display now subtracts a day to show the inclusive last day.
- Calendar view showed the wrong time for events whose source offset differed
  from the user's timezone (e.g. `+00:00` events under `Europe/Prague`): the base
  FullCalendar bundle only supports `local`/`UTC`. Added luxon + the
  `@fullcalendar/luxon3` plugin so named IANA timezones convert correctly, keeping
  the calendar and detail views consistent.

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
