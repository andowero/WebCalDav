# Changelog

## Unreleased — MVP

### Added — adjustable / disableable auto-logout with live countdown (2026-06-07)
- The top bar now shows a live "Logout in mm:ss" countdown until automatic
  session logout (turns red under 60s, redirects to login at zero).
- New per-user settings `auto_logout_enabled` and `auto_logout_timeout_seconds`
  (Preferences panel: enable checkbox + minutes field), persisted on
  `UserSettings`. Disabling auto-logout keeps the session alive indefinitely.
- The timeout is carried on the in-memory `SessionEntry` (seeded at login from
  the user's settings, falling back to the global `SESSION_IDLE_TIMEOUT`), and
  updated live on settings save — no re-login needed.
- New non-refreshing `GET /auth/session` endpoint reports
  `{enabled, timeout_seconds, remaining_seconds}` for the countdown. Crucially it
  uses `SessionStore.peek()`/`status()` which do **not** reset the sliding idle
  window, so polling the countdown cannot keep an idle session alive.
- Server rejects timeouts below 60s (`422`). No DB migration — schema is recreated.

### Fixed — deleted occurrence reappeared after moving the whole series (2026-06-07)
- A single-occurrence delete records an `EXDATE` at that occurrence's original
  time. Moving the **whole** series (drag, scope `all`) shifted `DTSTART`,
  detached overrides, and the `RRULE` `UNTIL` bound by the same delta — but left
  `EXDATE` stationary, so it no longer matched any generated slot and the deleted
  day reappeared; dragging the series back re-aligned the slots and it vanished
  again. `_shift_exdate` now carries `EXDATE` along with the series.
- The same gap on the **"this and following"** path is closed too: the
  first-occurrence rewrite shifts `EXDATE` with `DTSTART`, and a split migrates
  the master's post-pivot exclusions onto the spun-off series (rebased by the
  start delta), keeping pre-pivot ones on the truncated master. EXDATEs now
  thread through `_series_ical`. Two regression tests added.

### Fixed — "this and future" split left a ghost occurrence on re-edit (2026-06-07)
- A `thisfuture` split capped the master's `RRULE` `UNTIL` at `pivot − 1 second`,
  i.e. mid-day on the pivot's own day. Harmless alone, but the modal's end-by-date
  field is date-granular: a later "All events" edit round-tripped that `UNTIL` to
  end-of-day, which re-admitted the pivot occurrence into the master series — a
  duplicate "ghost" event appeared on the pivot day. `_truncate_until` now sets
  `UNTIL` to the **last actual occurrence strictly before the pivot**, so the
  date-granular round-trip stays within the series. Regression test added.
- Known limitation: sub-daily (hourly) frequencies still can't represent a
  same-day split exactly via a date-granular end-by field; weekly/daily+ are fixed.

### Changed — recurring scoped-edit redesign (2026-06-06)
- Aligned the scope set to the three industry-standard options
  (**This** / **This and following** / **All**); the non-standard
  `thisprev` ("this and previous") scope was removed from the API, CalDAV
  layer, and the scope chooser. `scope=thisprev` now returns 400.
- A `thisfuture` split is documented as producing two **fully independent**
  series (new UID, no `RELATED-TO` link) — matching Google/Apple/Outlook:
  editing or deleting one half never affects the other. Single-occurrence
  changes stay one resource via `RECURRENCE-ID` overrides; single deletes use
  `EXDATE`.
- **Fixed:** the "this" edit could duplicate the occurrence. A moved override
  and its original master-generated slot could both render; the fetch layer now
  suppresses the plain occurrence at any slot an override already covers.
- **Fixed:** deleting `thisfuture` left `RECURRENCE-ID` overrides past the pivot
  orphaned on the truncated master; they are now garbage-collected.
- Tests: dropped the `thisprev` cases, added a `thisprev`→400 route test, a
  no-duplicate regression, and an orphan-GC regression.

### Fixed — whole-series drag dropped UNTIL-bounded tail (2026-06-05)
- Dragging one occurrence of a recurring series with scope `all` shifts the
  master `DTSTART` by the drag delta. Previously the `RRULE` was left untouched,
  so an `UNTIL` bound stayed frozen and any occurrence shifted past it silently
  vanished (e.g. a Jun 16 + Jun 23 weekly series dragged +7d collapsed to a
  single Jun 23 event). `UNTIL` now shifts with `DTSTART`. `COUNT`-bounded and
  infinite series were unaffected. Regression test added.

### Added — drag/resize recurring events; lock "Repeats" (2026-06-05)
- Recurring events are now draggable and resizable on the month/week/day grid
  (previously the drag reverted). On drop/resize a "What to change?" scope chooser
  (`all` / `this` / `thisfuture` / `thisprev`) opens; the chosen scope and the
  occurrence's original `rawStart` pivot are sent to `PUT /events/{uid}`, reusing
  the same backend contract as the modal edit. Cancelling the chooser reverts.
- The grid now refetches after a successful drag/resize so scope splits and
  `RECURRENCE-ID` overrides (new resources) render immediately.
- The "Repeats" checkbox is locked when editing an existing recurring series — a
  series can't be un-recurred from the modal (unchecking had no backend effect).
- **Known bug:** editing only "this" occurrence of a recurring event sometimes
  duplicates the occurrence. See Project status → Known issues.

### Added — recurring events: create, edit, delete (2026-06-03)
- Recurring events are no longer read-only. Writes now take a `scope`
  (`all` / `this` / `thisfuture` / `thisprev`) plus a `recurrence_id` pivot (the
  clicked occurrence's original start, sent as the client's `rawStart`).
- **Delete** a recurring event opens a "What to delete?" chooser:
  - `all` drops the resource; `this` adds an `EXDATE`; `thisfuture` caps the rule
    with `UNTIL`; `thisprev` moves `DTSTART` past the pivot (decrementing `COUNT`).
- **Edit** a recurring event opens a "What to change?" chooser:
  - `all` rewrites the series (start changes applied as a delta so the anchor is
    preserved); `this` writes a `RECURRENCE-ID` override; `thisfuture` and
    `thisprev` split the series into two resources at the pivot.
  - Rule changes (frequency / interval / `UNTIL` / `COUNT`) apply on `all` and
    `thisfuture`. Recurring events can't be moved between calendars (a move
    recreates a single VEVENT) — the picker is disabled and the API returns 400.
- **Create** gains a full recurrence editor: frequency (hourly→yearly), "every X"
  interval, monthly by day-of-month or by Nth/last weekday, and a mutually
  exclusive end-by-date / end-after-N-occurrences control with a live "last
  occurrence" preview.
- New `POST /events/recurrence-preview` computes the last occurrence + count for a
  rule (via `python-dateutil`); `GET /events` now also emits a structured
  `extendedProps.recurrenceRule` so the editor can round-trip existing series.
- CalDAV-layer tests cover all four delete scopes, all four edit scopes (override
  + both split directions), rrule creation, and the preview helper; API tests
  cover the preview route and scope validation.

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
