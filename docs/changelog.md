# Changelog

## Unreleased — MVP

### Added — default calendar & calendar move (2026-06-03)
- New `Calendar.is_default` column (one default per user, enforced in
  `PATCH /calendars/{id}`; setting it clears the others). Surfaced as a "Default"
  checkbox per row in Settings. The create modal pre-selects the default calendar.
- The edit modal now shows a calendar picker (previously create-only). Changing it
  moves the event: `PUT /events/{uid}` takes `original_calendar_id` and, when it
  differs from `calendar_id`, recreates the event on the target (same UID) then
  deletes it from the source.

### Added — event creation & deletion (2026-06-03)
- `POST /events` creates a new event on the chosen calendar (server-generated
  `<uuid>@webcaldav` UID); `DELETE /events/{uid}?calendar_id=…` removes one.
  New `create_event` / `delete_event` in the CalDAV layer (radicale integration
  tests cover timed, all-day, and not-found cases).
- Create from the calendar grid:
  - Month: click a day → modal prefilled with that day as From/To and the current
    time rounded to 5 min, 1-hour default duration.
  - Week/Day: click empty space → nearest half-hour, 30-min slot; the all-day
    lane → a one-day all-day event.
  - Week/Day: drag empty space → modal spanning the dragged range (a 5px
    `selectMinDistance` separates click from drag).
- The create modal adds a calendar picker; closing without saving discards the
  event and clears the selection. Save still requires a name.
- Delete button added to the edit modal (deletes immediately).
- Right-click an event → context menu with **Edit** (opens the modal) and
  **Delete** (yes/no confirm dialog before removing).

### Added — modal date/time fields honour user settings (2026-06-03)
- New `date_format` user setting (`UserSettings.date_format`, default `YYYY-MM-DD`;
  also `MM/DD/YYYY`, `DD/MM/YYYY`) plumbed through `GET/PUT /settings` and the host
  page so the edit modal renders dates in the chosen order with no reload.
- Edit-modal date inputs are now three forced-format numeric fields (year/month/day)
  rebuilt per open, replacing the locale-dependent native `<input type="date">`.
- Time inputs honour the 12h/24h `time_format` setting: 24h shows HH:MM, 12h shows
  1–12 plus an AM/PM toggle. Inputs are rebuilt per open; the canonical value sent
  to the API stays 24h. Custom ▲▼ steppers replace native number spinners.

### Fixed — modal date/time pickers (2026-06-03)
- Edit modal widened (420→500px) and the from/to row wraps, so the time picker is
  no longer clipped behind the modal edge.
- Time picker always rendered 24h regardless of the `time_format` setting; now
  follows it (12h with AM/PM toggle).
- The 📅 mini date picker always started the week on Sunday: the native picker
  ignores first-day-of-week. Replaced with a custom popup calendar that honours the
  `first_day_of_week` setting (0=Sun … 6=Sat).

### Added — drag & resize editing (2026-05-31)
- Events are now movable/resizable by mouse in all views, persisted via the
  existing `PUT /events/{uid}` (`eventDrop` / `eventResize` handlers).
  - Month: drag shifts by whole days (timed events keep their time); all-day
    left/right edges move from/to dates.
  - Week: drag changes date (L/R) and time (U/D); top/bottom edges move
    from/to, and edge-drag across day columns changes the date.
  - Day: drag changes time only; top/bottom edges move from/to.
- Edge resize from both ends enabled (`editable`, `eventResizableFromStart`).
- Only calendar-backed, non-recurring events are draggable; demo and recurring
  events are locked. Failed writes revert the change in the UI.

### Added — event editing, v1 (2026-05-31)
- The event detail window is now an edit form: name, all-day flag, from/to
  date+time, location, and notes are editable, with Save / Cancel. Recurrence
  and reminders remain read-only (deferred to v2/v3).
- `PUT /events/{uid}` writes changes straight to CalDAV: locates the event by
  UID via `event_by_uid`, rewrites SUMMARY/LOCATION/DESCRIPTION/DTSTART/DTEND,
  drops any DURATION, bumps SEQUENCE + LAST-MODIFIED, and preserves all other
  properties (e.g. VALARM). All-day DTEND is written exclusive (+1 day).
- Recurring events are refused server-side (`RecurringEventError` → 422) and
  blocked in the UI with a notice; out of scope until v2.
- Each event now carries its owning calendar in `extendedProps.calendarId`, so
  the client can target the right calendar on save; demo events (no calendar)
  are non-editable.
- Timed edits are interpreted in the user's effective IANA timezone (setting or
  browser-resolved), parsed wall-clock with luxon on the client and re-attached
  via `zoneinfo` on the server.
- CalDAV integration tests for update: timed edit, all-day edit, recurring
  refusal, and not-found — 33 tests passing total.

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
