# Project status

## Milestones

| Milestone | Scope                                                     | Status |
|-----------|-----------------------------------------------------------|--------|
| MVP       | Secure user login, read-only view of calendar events      | Complete |
| v1        | Basic editing of calendar events -> without repetition    | Complete |
| v2        | Editing of calendar events -> repetition                  | Complete |
| v3        | Reminders and browser notifications                       | Complete |
| v4        | Tasks (VTODO): view, edit, complete, recurrence           | Complete |
| v5        | Dark mode (system/light/dark theme)                       | Complete |
| v6        | Internationalization (i18n) + Czech translation           | Complete |
| v7        | MCP server: calendar/task access via API token            | Complete |
| v8        | Configurable double-click to create events                | Complete |
| v9        | Journals (VJOURNAL): view, create, edit, delete           | Complete |
| v10       | Calendar sharing (links + .ics) for items/views/agenda    | Complete |
| v11       | Keyboard accessibility + basic agenda screen-reader support | Complete |
| v12       | Out-of-work day coloring (public holidays + weekend)      | Complete |

## Known issues

- None currently open.

## Recent additions

### Out-of-work day coloring (holidays + weekend)
- Colors public holidays and country-correct weekend days red (day number +
  light day tint), with the holiday name as a hover tooltip. Country selectable
  (Czechia first); per-user on/off. Holiday data is an authoritative local
  table with validity ranges per holiday (no runtime network calls); Easter is
  a hardcoded date table merged with fixed-date holidays. See `Plan.md` and
  `webcaldav/holidays.py`.

### Keyboard accessibility pass (2026-06-27)
- Makes the app fully operable by keyboard (WCAG 2.2 keyboard criteria) and gives
  the agenda basic screen-reader semantics. A shared `:focus-visible` ring covers
  every control; dialog modals move/trap/restore focus (driven from
  `show()`/`hide()`); the custom date/time picker is back in the tab order with
  Arrow-key grid navigation and Escape-to-close; agenda rows are focusable list
  items with composed `aria-label`s and Enter/Space activation; journal tabs get
  full tablist ARIA + arrow switching. Calendar grid shortcuts: PageUp/PageDown
  (prev/next period), Home (today), Insert (new event on focused day), Delete
  (delete focused event, with confirm), month-view arrow navigation, and Enter to
  create on an empty day. Plus a skip link, `role="alert"` errors,
  and a `prefers-reduced-motion` block. Verified by the manual keyboard checklist
  in `docs/accessibility_testing.md`. Out of scope this pass: colour contrast /
  high-contrast theme and full screen-reader support for the FullCalendar grids.

### Mobile / touch support (2026-06-22)
- New `@media (max-width: 768px)` CSS layer makes the settings panel and all
  modals bottom sheets, grows tap targets to 44px, uses 16px inputs (no iOS
  focus-zoom), and lets the FullCalendar toolbar wrap. JS adds long-press →
  context menu (mark done/edit/delete on touch) and swipe-down → dismiss for the
  sheets. Desktop layout unchanged (all rules inside the breakpoint).

### CalDAV connection reuse — sub-second calendar load (2026-06-22)
- Calendar loads were network-bound: a fresh `caldav.DAVClient` (new connection +
  HTTP/2/QUIC negotiation) was opened per calendar per endpoint. New
  `_make_dav_client()` forces HTTP/1.1 and a new account-level `fetch_account_data()`
  reuses one keep-alive connection across an account's calendars/kinds. A combined
  `GET /calendar-data` endpoint replaces the three separate view-load fetches; the
  notification scheduler and share `/items` use it too. Undated-task fetch folded
  into the masters search (3→2 round-trips). Regression test guards single-client
  reuse. No event caching added.

### Event search + agenda search-range pickers (2026-06-21)
- Toolbar search box filters events/tasks/journals by title/location/description
  (case- and accent-insensitive, ≥ 3 chars, loose subsequence). Grid views filter
  the visible interval; the agenda gains "From"/"To" date pickers (shown only
  while searching) bounded by new `agenda_search_from_days`/`agenda_search_to_days`
  user settings (defaults 0 / 365). Owner-only (hidden in shares).

### Reset customized occurrences on series edits (2026-06-20)
- Editing a recurring event/task with scope "All" or "This and future" now offers
  an opt-in "Reset customized events/tasks" checkbox. When set, only the
  properties the edit changed are reset on individually edited occurrences
  (`RECURRENCE-ID` overrides) back to the series values; unchanged properties stay
  customized. Driven by `reset_overrides`/`reset_fields` and the new
  `_reset_override` helper in `caldav_client.py`. Modal lists the affected
  properties (EN + CS).

## Recent fixes

### Task drag/resize + moved-occurrence completion (2026-06-20)
- Tasks are now drag-movable and edge-resizable in grid views (recurring tasks
  prompt for scope); undated "today" tasks remain fixed.
- Completing a moved recurring occurrence keeps its edited time (the
  `RECURRENCE-ID` override is toggled in place, not rebuilt from the series).

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

### Faster date-picker navigation (2026-06-07)

UX improvements to the custom mini date picker; frontend only.

- The picker title drills into a **month grid** (arrows step years); the empty
  recurrence end-date field opens on the event's start month.
- The **FullCalendar header title** is clickable: month view jumps to a chosen
  month (year-stepping arrows), week/day views open a day picker and jump to the
  chosen date. The picker was generalised (`openCalPicker`) to drive a form
  field or `_fcCalendar.gotoDate`.

### Agenda view, "+" FAB, default-view setting (2026-06-11)

A fourth way to browse events plus quicker event creation.

- **Agenda**: a custom infinitely-scrolling DOM panel (not a FullCalendar view)
  listing upcoming events from the start of today, sorted by start, one row per
  recurring occurrence, grouped under sticky day headers. Loads `GET /events`
  in tiled 30-day windows on scroll; open-ended recurrence scrolls forever,
  finite calendars stop after 6 empty windows. Rows open the standard edit
  modal. The FC toolbar stays visible (title shows "Agenda"); any toolbar
  button leaves the agenda.
- **"+" FAB** in all views opens the create modal with no start/end preselected.
- **`default_view` setting** (month/week/day/agenda) in Preferences picks the
  view loaded at sign-in; validated server-side (422 on unknown values).
- 79 tests passing (added `default_view` API tests).

### Editable reminders / VALARM (2026-06-11)

First half of v3: reminders can now be created and deleted per event.

- Event modal grows a reminder editor: "+" adds a row, rows sort soonest-first,
  committed rows are delete-only (delete + re-add to change). Saving the event
  persists the set as `ACTION:DISPLAY` VALARMs; absent `reminders` in a PUT
  (drag/resize) leaves alarms untouched, `[]` clears.
- Timed events: N minutes/hours/days/weeks before (no "months" — not an
  RFC 5545 duration). All-day events: N days/weeks before **at HH:MM**, encoded
  as one duration trigger off the DATE start (e.g. 2 weeks at 09:00 →
  `-P13DT15H`; on-day 09:00 → `PT9H`).
- Non-conforming alarms (EMAIL, absolute datetime triggers) are preserved
  verbatim and shown read-only. (`RELATED=END` / after-event became editable in
  the 2026-06-14 update below.)
- Scope-aware for recurring events: "all" → master, "this" → override snapshot,
  "this+future" → new split series inherits then replaces. Override reminders
  are recovered from unexpanded components and no longer leak to siblings.
- Reminder times follow the `time_format`/`date_format` settings everywhere:
  custom hh:mm (+ AM/PM) inputs for the all-day time-of-day (not the
  locale-driven native time input), formatted committed-row text, and
  client-side formatting of absolute-trigger read-only alarms (server sends
  the ISO instant as `at`).
- 90 tests passing (radicale round-trips incl. unit normalization, all-day
  decomposition, per-scope persistence; API validation; absolute-trigger
  extraction).

### Browser notifications (2026-06-12)

Second half of v3, completing the milestone.

- Per-user toggle (Settings → Preferences), off by default. Fires a desktop
  notification at each reminder (VALARM) **and** at each event start. Body is
  `WebCalDav` / event name / event datetime, datetime in the user's formats.
- **Foreground-only by design** — answers the logged-out-reminder question
  below. The schedule is built client-side from events loaded during the
  session and shown through a Service Worker (`static/sw.js`) so the OS routes
  it to the notification center. No server-side Web Push: pushing reminders
  while the browser is closed would require plaintext reminder data on the
  server, breaking zero-knowledge at rest. Notifications fire only while a tab
  is open (background tab is fine). Enabling notifications forces auto-logout
  off (server-enforced), since the tab must stay logged in to resync.
- Scheduler loads a `NOTIFICATION_HORIZON_DAYS` (default 60) future window and
  re-polls every 10 min, gated by `GET /calendars/ctags`. Radicale has no
  RFC 6578 sync-collection, so the change token is the caldav lib's etag-hash
  fallback (`fetch_sync_token`).
- Browsers: Firefox, Chrome, Opera, Safari (macOS). Verified manually (no
  automated browser tests, per project policy). Backend covered by new settings
  and `fetch_sync_token` tests.

### Anchored reminders — before/after × start/end (2026-06-14)

Post-v3 enhancement to the reminder editor.

- Reminders can fire relative to the event **start or end**, **before or after**
  (four quadrants), picked via one per-row dropdown. Motivating case: a reminder
  15 minutes before an event ends (e.g. picking a child up from class).
- `Reminder` gains `anchor` (`start`|`end`) and `direction` (`before`|`after`),
  both defaulting to the old behavior and omitted from payloads when default, so
  existing reminders round-trip byte-for-byte. The pair maps to the VALARM
  `TRIGGER`'s `RELATED` parameter plus the duration sign; `RELATED=END` is only
  emitted when the event has an end, else it degrades to `START`.
- `RELATED=END` and after-event triggers are now editable; only EMAIL and
  absolute-time alarms remain read-only. Browser notifications compute
  end-anchored fire times from `rawEnd`.
- The notification scheduler loads past events too (`NOTIFICATION_LOOKBACK_DAYS`,
  default 60 = the horizon), so an after-event reminder still pending in the
  future fires even once the event has ended — fixing a bug where after-end
  reminders on past events silently never fired.
- All 120 tests pass (new round-trip coverage for each quadrant + an all-day
  after-end case; model validation for the new fields).

### Tasks — VTODO (2026-06-16) — v4

CalDAV task support, mirroring the event stack.

- New `/tasks` API and `webcaldav/routers/tasks.py`; CalDAV layer gains
  `fetch_tasks` / `create_task` / `update_task` / `delete_task` /
  `set_task_status`. The delicate recurrence/override/VALARM helpers were
  generalised over a component `_Kind` (VEVENT vs VTODO) and reused, so events
  and tasks share one implementation; only the thin orchestration is duplicated.
- Anchor on DUE (else DTSTART); DTSTART and DUE are both optional, so undated
  tasks are first-class. STATUS / COMPLETED / PERCENT-COMPLETE / PRIORITY are
  read and written; unknown VTODO properties round-trip untouched (in-place edit).
- Frontend: tasks merge into the same FullCalendar source and agenda, render a
  checkbox **square** (empty/ticked) coloured per calendar, and reuse the event
  modal via an Event/Task type toggle (Start/Due fields, Priority, optional
  dates). Completion toggles from the square or the right-click menu; recurring
  completion uses RFC advance (per-occurrence COMPLETED override).
- Settings: `completed_task_display` (hidden/grayed) and `undated_task_display`
  (agenda/today), with SQLite migrations; the Settings panel scrolls with a
  pinned Save button.
- 138 tests pass (18 new: VTODO create/fetch/update/delete/status incl. recurring
  RFC-advance and undated, plus tasks-API validation and settings round-trip).
  FullCalendar rendering, the square, and notifications remain manually verified.

### Dark mode (2026-06-17) — v5

User-selectable UI theme.

- New `theme` user setting: `system` (default), `light`, `dark`. Added to the
  `UserSettings` model, the `/settings` API (validated like other enum settings),
  and the Settings → Preferences form, with the usual SQLite `ALTER TABLE`
  migration.
- `app.css` was refactored from hardcoded hex to CSS custom properties on
  `:root`; a dark palette overrides them under `:root[data-theme="dark"]` and,
  for `system`, under a `prefers-color-scheme: dark` media query. FullCalendar is
  themed via its own `--fc-*` variables; per-calendar event colours are untouched.
- The server renders `data-theme` on `<html>` so the right theme paints on first
  load with no flash; live changes set `document.documentElement.dataset.theme`.
  `system` tracks the OS automatically (no JS).
- 141 tests pass (3 new: theme default, round-trip, invalid-value rejection).
  Visual theming is verified manually across the supported browsers.

### MCP server & API tokens (2026-06-17) — v7

AI-assistant access to calendars and tasks over the Model Context Protocol.

- New optional MCP server at `/mcp` (Streamable HTTP via the official `mcp`
  SDK / `FastMCP`), gated by `MCP_SERVER_ENABLED` (off by default). Ten tools:
  `list_calendars`, `list_items`, `get_item_details`, `create_event`/`create_task`,
  `update_event`/`update_task`, `set_task_status`, `delete_event`/`delete_task`.
  Recurring edits/deletes take a `this`/`thisfuture`/`all` scope. Tools delegate
  to the same `caldav_client` primitives and `EventUpdate`/`TaskUpdate` models as
  the web routers (`webcaldav/mcp_server.py`). MCP I/O is English + ISO 8601.
- API tokens (`webcaldav/tokens.py`, `routers/api_tokens.py`, `APIToken` /
  `APITokenCalendar` models) minted in Settings → API Tokens, shown once. Token
  plaintext `WebCalDav{RO,RW}<secret>` makes the mode visible; tokens are
  read-only or read-write, optionally calendar-scoped, with optional expiry.
- Security: the DEK and the token's authoritative mode/scope/expiry are sealed in
  an AES-GCM blob keyed by the token secret (only its SHA-256 is stored), so a
  stolen DB stays zero-knowledge and DB tampering of the display-only mirror rows
  cannot escalate a token. `/mcp` is CSRF-exempt (bearer auth); FastMCP host
  validation is disabled (trusted reverse proxy). Admin `reset_password` now
  deletes the user's tokens along with the DEK rotation.
- 168 tests pass (15 new: token mint/resolve, expiry, mode-prefix binding, API
  CRUD + toggle gating, DB-tamper-cannot-escalate, RO/RW + scope enforcement,
  admin reset revokes tokens). The live MCP transport was verified end-to-end
  (initialize, tools/list, RO rejection). Documented in `MCP.md`.

### Double-click to create events (2026-06-18)

Optional calmer click behavior on empty calendar space.

- New `double_click_to_create_events` boolean user setting (off by default), added
  to the `UserSettings` model with the usual SQLite `ALTER TABLE` migration and
  plumbed through `/settings`, the page render context, and `window.__SETTINGS__`.
- When off, a single click opens the create modal (unchanged). When on, a single
  click only highlights the day/slot (via FullCalendar's own selection) and a
  double click opens the modal; the `dateClick` handler does manual double-click
  detection and the per-view create logic was extracted into
  `openCreateFromDateClick`. Drag-to-select still opens the modal in both modes.
- 170 tests pass (2 new: setting default-off and round-trip). The click/highlight
  interaction is verified manually.

### Journals — VJOURNAL (2026-06-18) — v9

A third CalDAV item kind alongside events and tasks: dated free-text notes.

- A journal is a SUMMARY (title) + a Markdown DESCRIPTION body anchored on a
  single DTSTART (date or datetime). No end, recurrence or alarms. Multiple
  journals per day are supported (independent VJOURNAL resources).
- CalDAV layer adds a `_JOURNAL` `_Kind` (empty end-key) and
  `fetch_journals`/`create_journal`/`update_journal`/`delete_journal`; the shared
  field/series helpers were guarded to skip the end property when a kind has none.
  New `/journals` router (`GET/POST/PUT/DELETE`), a trimmed mirror of `/events`,
  with calendar-move on edit.
- Frontend: journals merge into the FullCalendar source and the agenda, render a
  **downward-pointing triangle** marker (events use a dot, tasks a checkbox), and
  reuse the editing modal via a new Journal type. The body uses a **two-tab editor**:
  an "Edit" tab (raw-Markdown textarea) and a read-only "Display" tab rendered via
  vendored **markdown-it** (MIT, `static/vendor/`; images disabled, raw HTML
  escaped). New journals default to Edit, existing ones to Display. One date(time)
  picker; the event/task-only fields are hidden.
- MCP: dedicated `list_journals` (backward default window — 30 days ago → now),
  `create_journal`/`update_journal`/`delete_journal`, and a `journal` item_type
  for `get_item_details`. Write tools require an RW token and respect scope.
- i18n strings added in English and Czech.
- 186 tests pass (16 new: radicale round-trip CRUD + Markdown-body persistence +
  multiple-per-day, router validation/auth, MCP journal tools incl. the backward
  window). The Markdown editor, triangle marker, and agenda rendering are verified
  manually.

### Calendar sharing (2026-06-19) — v10

- **Share links + `.ics` download** for a single item, a grid period
  (month/week/day), or an agenda slice. A link opens a navigation-locked share
  view bounded to the shared window; read-only shows it, read-write lets the
  sharee add/edit within scope (recurring events included). The secret rides in
  the URL **fragment** and is sent via the `X-Share-Secret` header, never the
  request line.
- The share page **reuses the main app** (`index.html` + `app.js`) in a share
  mode: the editing/viewing modal, markdown rendering, type symbols, recurrence
  editor, i18n and date/time formatting are identical to the normal calendar;
  only the toolbar is locked (`validRange` = window) and CRUD reroutes to
  `/shares/*`. The sharer's display settings are injected server-side by share id.
- Security mirrors the MCP token exactly: DEK + authoritative
  kind/mode/scope/window/expiry sealed in an AES-GCM blob keyed by the secret
  (`webcaldav/shares.py`); only `SHA-256(secret)` stored; DB mirror columns are
  display-only. Zero-knowledge at rest preserved.
- New `Share`/`ShareCalendar` models, `/shares` router (create/list/revoke +
  share-secret-authed resolve/items/writes/export), `webcaldav/baseurl.py`
  reverse-proxy URL detection, `SHARING_ENABLED` / `PUBLIC_BASE_URL` config,
  `GET /s/{id}` share-mode page, Shares settings section, share buttons (item
  modal + grid/agenda title). English + Czech strings.
- 210 tests pass (23 new: share mint/resolve roundtrip + tamper/expiry/mirror
  rejection + grid-window math, the share API incl. create gating/validation,
  resolve auth + grid anchor/window, window-clamped reads, RW scope enforcement,
  RO rejection, item-uid limiting, `.ics` export, share-mode page render, and
  radicale export round-trips). The share view (FullCalendar lock, RW edit via
  the normal modal) is verified manually.
- See [SHARING.md](../SHARING.md).

## What is next

| Milestone | Scope | Status |
|-----------|-------|--------|
| v12 | Per-calendar ACL sharing with named recipients / accounts | Planned |
