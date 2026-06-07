# Project status

## Milestones

| Milestone | Scope                                                     | Status |
|-----------|-----------------------------------------------------------|--------|
| MVP       | Secure user login, read-only view of calendar events      | Complete |
| v1        | Basic editing of calendar events -> without repetition    | Complete |
| v2        | Editing of calendar events -> repetition                  | Complete |
| v3        | Reminders and browser notifications                       | Not started |

## Known issues

- None currently open.

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
- `GET/PUT /settings` (includes `auto_logout_enabled` / `auto_logout_timeout_seconds`)
- `GET /auth/session` (non-refreshing idle-logout countdown state)
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

### Event editing — v1 (2026-05-31)

Existing events are now editable in place — the detail window doubles as the edit form.

- `PUT /events/{uid}` writes name, all-day flag, from/to date+time, location, and
  notes back to CalDAV with no local cache. Locates the event by UID, mutates only
  the edited fields (preserving VALARM and everything else), bumps SEQUENCE.
- Recurrence (repetition) and reminders stay read-only per the v1 scope. Recurring
  events are refused (422) server-side and blocked in the UI.
- Events carry `extendedProps.calendarId` so the client targets the right calendar;
  timed edits round-trip through the user's effective timezone (luxon → zoneinfo).
- 33 tests passing (added timed / all-day / recurring-refusal / not-found cases).

### Modal date/time UX (2026-06-03)

Edit-modal date and time fields now respect the user's locale-style preferences.

- New `date_format` setting (`YYYY-MM-DD` / `MM/DD/YYYY` / `DD/MM/YYYY`) drives
  forced-format date inputs (year/month/day numeric fields), replacing the
  locale-dependent native date input.
- Time fields honour the 12h/24h `time_format`: 24h HH:MM, or 12h 1–12 + AM/PM
  toggle; the value sent to the API is always 24h.
- The 📅 picker is now a custom popup calendar honouring `first_day_of_week`
  (the native picker ignored it and always started on Sunday).
- Modal widened so the time picker is no longer clipped.

### Event create & delete (2026-06-03)

Completes the v1 editing milestone — events can now be created and removed, not just edited.

- `POST /events` creates an event (server-generated `<uuid>@webcaldav` UID) on a
  chosen calendar; `DELETE /events/{uid}?calendar_id=…` removes one. Backed by new
  `create_event` / `delete_event` in the CalDAV layer.
- Creating from the grid: month click prefills the clicked day + current time
  (rounded to 5 min, 1-hour duration); week/day click snaps to the nearest
  half-hour 30-min slot; week/day drag spans the dragged range; the all-day lane
  makes an all-day event. A 5px `selectMinDistance` separates click from drag.
- The create modal adds a calendar picker and requires a name to save; closing
  discards the draft.
- Edit modal gains a Delete button; right-clicking any event opens an Edit /
  Delete context menu, with a yes/no confirm before deletion.
- 37 tests passing (added create timed/all-day, delete, delete-not-found).

### Default calendar & calendar move (2026-06-03)

- `Calendar.is_default` column added (one default per user). Settings shows a
  "Default" checkbox per calendar; the create modal pre-selects it.
- The edit modal exposes the calendar picker so an event can be reassigned.
  Moving sends `original_calendar_id`; the server recreates on the target (same
  UID) and deletes from the source.

### Recurring events — v2 (2026-06-03)

Full create / edit / delete support for recurring events, with per-occurrence scoping.

- Recurring writes take a `scope` (`all` / `this` / `thisfuture` / `thisprev`) and a
  `recurrence_id` pivot (the clicked occurrence's `rawStart`). Delete and edit each
  open a scope chooser in the UI.
- Delete: `all` removes the resource, `this` adds `EXDATE`, `thisfuture` caps with
  `UNTIL`, `thisprev` advances `DTSTART` past the pivot.
- Edit: `all` rewrites the series (start as a delta to preserve the anchor), `this`
  writes a `RECURRENCE-ID` override, `thisfuture` / `thisprev` split the series in
  two at the pivot. Rule edits (`FREQ`/`INTERVAL`/`UNTIL`/`COUNT`) apply on `all`
  and `thisfuture`. Recurring events can't be moved between calendars (400).
- Create: a recurrence editor (frequency, interval, monthly by day-of-month or
  Nth/last weekday, end-by-date / end-after-N) with a live last-occurrence preview
  via `POST /events/recurrence-preview`. Occurrence math uses `python-dateutil`;
  `GET /events` emits a structured `recurrenceRule` so the editor round-trips
  existing series.
- 53 tests passing (added four delete scopes, four edit scopes, rrule creation,
  preview helper + route, and scope validation).

### Recurring scoped-edit redesign (2026-06-06)

Aligned recurring-event editing to the industry standard and fixed two bugs.

- Scope set reduced to the three standard options — **This** / **This and
  following** / **All** — matching Google/Apple/Outlook. The non-standard
  `thisprev` scope was removed everywhere (`scope=thisprev` → 400) and its dead
  CalDAV helpers deleted.
- A `thisfuture` split produces two **fully independent** series (new UID, no
  `RELATED-TO` link): editing or deleting one half never affects the other.
  Single-occurrence change → `RECURRENCE-ID` override; single delete → `EXDATE`.
- Fixed the "this" duplicate: the fetch layer now suppresses a plain occurrence
  at any slot already covered by an override (the override wins).
- Fixed orphaned overrides: deleting `thisfuture` now garbage-collects overrides
  past the pivot instead of leaving them on the truncated master.
- Fixed a `thisfuture`-split ghost: the master's `UNTIL` is now pinned to the last
  real occurrence before the pivot (was `pivot − 1s`, mid-day), so a later
  date-granular "all" edit no longer re-admits the pivot occurrence.
- 59 tests passing.

### Recurring EXDATE follows whole-series moves (2026-06-07)

Fixed a deleted occurrence reappearing after the series was moved.

- A single delete records an `EXDATE`; a whole-series move (`all`) shifted
  `DTSTART` / overrides / `UNTIL` but not `EXDATE`, so the exclusion stopped
  matching any slot and the deleted day came back (and toggled on drag-back).
  `_shift_exdate` now moves `EXDATE` with the series.
- The `thisfuture` path is fixed too: the first-occurrence rewrite shifts
  `EXDATE`, and a split migrates post-pivot exclusions onto the new series
  (rebased), keeping pre-pivot ones on the master; EXDATEs thread through
  `_series_ical`.
- 76 tests passing (added two EXDATE-shift regressions; total also includes the
  auto-logout suite).

## What is next

- v3: reminders and browser notifications.
