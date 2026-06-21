# Changelog

## Unreleased — MVP

### Added — event search + agenda search-range pickers (2026-06-21)
- **A search box in the calendar toolbar** (after the "today" button) filters
  events, tasks, and journals by **title**, **location**, and **description**.
  Matching is case- and accent-insensitive, needs ≥ 3 characters, and matches a
  loose in-order subsequence (so `dbs` matches "Dog Barks"). The term persists
  across view switches; clearing it (delete below 3 chars, or the "×" button)
  stops filtering.
- **Month/week/day** filter the events already fetched for the visible interval
  (the FullCalendar `events` callback filters before `successCallback`, and a term
  change calls `refetchEvents()`).
- **Agenda**: with no search it behaves as before (infinite forward scroll). When
  a search is active, two **date pickers** ("From"/"To", reusing the event date
  widget) appear and bound the searched interval (no scroll past "To"); pinned
  overdue/undated rows are filtered too. Defaults come from two new user settings
  `agenda_search_from_days` (0) and `agenda_search_to_days` (365), editable in
  Preferences. Search/pickers are owner-only (hidden in shares).
- New i18n keys (EN + CS): `search_placeholder`, `search_clear`, `agenda_from`,
  `agenda_to`, `pref_agenda_from`, `pref_agenda_to`.
- The search box shows an "in progress" spinner (same look as the agenda loading
  spinner) while a search-driven load runs — grid views drive it from the
  FullCalendar `loading` callback, the agenda mirrors its own load state. The
  agenda from/to date boxes are compact (digit-width).

### Changed — customized occurrences are now pinned on series edits (2026-06-20)
- **Editing/dragging a recurring series no longer drags individually edited
  occurrences along.** Previously a whole-series ("all") or "this and future"
  time change shifted every detached `RECURRENCE-ID` override by the same delta,
  so a pinned occurrence silently moved. Now overrides keep their absolute time
  (and all other properties) — their `RECURRENCE-ID` is rebound to the new grid
  so they stay valid exceptions (no duplicate/orphan) while staying put.
  Implemented via `_shift_override(..., time_too=False)` in `caldav_client.py`.

### Added — reset customized occurrences on series edits (2026-06-20)
- **The scope chooser now offers "Reset customized events/tasks"** next to the
  "All" and "This and future" buttons when editing or **dragging** a recurring
  item. When checked, the properties the edit actually changed are reset on
  individually edited occurrences (detached `RECURRENCE-ID` overrides) back to the
  series values; properties the user did **not** change stay customized. Time
  resets to the occurrence's own series slot (dropping any pinned offset); title,
  location, description, reminders, and (tasks) priority reset to the new series
  values. Unchecked keeps the customized occurrences pinned (see above).
- The modal lists exactly which properties will be reset (derived from a
  before/after diff of the edit on the frontend; a drag/resize lists "Time") and
  is internationalized (English + Czech).
- Backend: new `_reset_override` helper in `caldav_client.py`, wired into the
  `all`/`thisfuture` branches of `_sync_update_event` and `_sync_update_task`;
  driven by `reset_overrides`/`reset_fields` on `EventUpdate`/`TaskUpdate`.

### Fixed — task drag + completion of moved occurrences (2026-06-20)
- **Tasks are now draggable and resizable** in the month/week/day grid views,
  matching events: a drag moves DTSTART/DUE, and tasks that span (both DTSTART
  and DUE) have draggable edges. Recurring tasks prompt for scope as events do.
  Undated tasks parked on "today" stay fixed. The drag handler routes task
  changes to `PUT /tasks/` with a start/**due** body (`taskToBody` in
  `app.js`).
- **Marking a moved recurring task occurrence done no longer reverts its time.**
  `_sync_set_task_status` now toggles an existing `RECURRENCE-ID` override in
  place instead of rebuilding it from the master series, so a `scope="this"`
  time edit survives completion (and un-completion).
- **Editing a done recurring occurrence no longer marks it undone.** A
  `scope="this"` edit (e.g. dragging a completed occurrence) now carries the
  prior override's COMPLETED state into the rebuilt override.
- **Re-dragging an already-moved occurrence no longer spawns duplicate/orphan
  overrides** (which surfaced as a stuck occurrence plus a spurious "new
  series"). A pivot resolver (`_resolve_pivot`) maps a request's
  `recurrence_id` back to an existing override's stable RECURRENCE-ID when the
  client sends the occurrence's already-moved anchor instead, so repeated edits
  update the same occurrence in place. The same `_resolve_pivot` guard is
  applied to recurring **events** (`_sync_update_event`), which had the
  identical latent orphan-override bug.

### Fixed — "this and future" split edge cases (2026-06-20)
- **Splitting an occurrence that already had a "this only" time-move now moves
  it.** Promoting a moved occurrence to `scope="thisfuture"` left the stale
  single-occurrence override at the pivot, which shadowed the new series' first
  occurrence — the dragged event appeared stuck at its old time while only the
  future occurrences moved. The split now drops any override at the pivot (the
  occurrence becomes the new series' anchor) in both `_sync_update_event` and
  `_sync_update_task`.
- **A second forward "this and future" split on an UNTIL-bounded series no
  longer drops an occurrence.** The spun-off series inherited the old master's
  `UNTIL` bound unshifted; moving the series forward pushed its tail past the
  stationary bound, so an occurrence silently vanished (only on `UNTIL`-bounded
  series, never `COUNT`/infinite — hence intermittent). The new series' `UNTIL`
  now shifts with the drag delta (`_shift_until_in_parts`), mirroring the
  whole-series-drag guard.
- Fixed a latent crash in the task `thisfuture` split for **due-only** VTODOs:
  `_count_through`/`_truncate_until` assumed a `DTSTART`; they now fall back to
  `DUE` via `_series_anchor`.

### Added — calendar sharing (2026-06-19)
- **Share links and `.ics` export** for three scopes: a **single item**
  (event/task/journal), a **grid period** (month/week/day), and an **agenda
  slice** (explicit from/to). A share link opens a navigation- and
  settings-locked view of exactly the shared window; **read-only** shows it,
  **read & write** lets the sharee add/edit within scope (including recurring
  events that extend past the window).
- **Security model mirrors the MCP API token** (`webcaldav/shares.py`): the URL
  carries a random secret in its **fragment only** (`/s/<id>#<secret>`); the
  session DEK plus the authoritative kind/mode/scope/window/expiry are sealed in
  an AES-GCM blob keyed by a key derived from the secret. Only `SHA-256(secret)`
  is stored; the DB mirror columns are display-only and never trusted for
  authorization. Zero-knowledge at rest is preserved (a stolen DB without the
  secret, or a URL without the DB blob, yields nothing). The secret travels in
  the `X-Share-Secret` header, never the request line, so it stays out of
  access/proxy logs and the `Referer`.
- New `Share` / `ShareCalendar` models; new `/shares` API
  (`webcaldav/routers/shares.py`): session-authed create/list/revoke, plus the
  share-secret-authed `resolve`, `items`, the `events|tasks|journals` write
  endpoints (which reuse the existing recurrence/reminder code paths), and
  `{id}/export.ics`. Multi-calendar grid/agenda shares mark which calendars are
  writable and a default target for sharee-created items.
- Reverse-proxy-aware base URL detection (`webcaldav/baseurl.py`, reads
  `X-Forwarded-Proto` / `X-Forwarded-Host`, override via `PUBLIC_BASE_URL`).
- New config: `SHARING_ENABLED` (default on; gates link creation, revoke always
  works), `PUBLIC_BASE_URL`. The share-view page (`GET /s/{id}`) **reuses the main
  app** (`index.html` + `app.js`) in a "share mode" so the editing/viewing modal,
  markdown rendering, type symbols, recurrence editor, i18n and date/time
  formatting are identical to the normal calendar — only the toolbar is locked to
  the shared window and data/CRUD calls reroute to `/shares/*` with the
  `X-Share-Secret` header. The sharer's display settings (timezone, language,
  formats, theme) are injected server-side by share id so the view renders as the
  sharer sees it. Share buttons in the item modal header and next to the
  grid/agenda title; a **Shares** section in Settings (list + revoke). English
  and Czech strings added. See [SHARING.md](../SHARING.md).

### Added — journals (VJOURNAL) (2026-06-18)
- Full CalDAV **journal** support alongside events and tasks. Journals are dated
  free-text notes (a SUMMARY title + a Markdown DESCRIPTION body anchored on a
  single DTSTART, date or datetime); they have **no end, recurrence or alarms**.
  Shown in every view (month, week, day, agenda) on their DTSTART day, visually
  distinct via a **downward-pointing triangle** marker (events use a dot, tasks a
  checkbox square), sharing the per-calendar colour. Multiple journals per day are
  supported (independent VJOURNAL resources).
- New `/journals` API: `GET /journals`, `POST /journals`, `PUT /journals/{uid}`,
  `DELETE /journals/{uid}` (`webcaldav/routers/journals.py`). The CalDAV layer
  gains `fetch_journals` / `create_journal` / `update_journal` / `delete_journal`
  via a new `_JOURNAL` `_Kind` (empty end-key; the shared field helpers skip the
  end property). Calendar move on edit works as for events (recreate + delete).
- The editing modal gains a **Journal** type with a **two-tab Markdown editor**
  for the body: an **"Edit"** tab (a plain textarea of raw Markdown) and a
  read-only **"Display"** tab that renders it via vendored
  [markdown-it](https://github.com/markdown-it/markdown-it) 14.1.0 (MIT, under
  `static/vendor/`). New journals default to the Edit tab; existing ones open on
  Display. **Images are disabled** (CalDAV can't store them) and raw HTML is
  escaped. Journals use one date(time) picker and hide the event/task-only fields
  (recurrence, reminders, priority, location, end).
- The Display tab supports **GFM tables, nested/ordered lists, blockquotes**
  (CSS restored inside the rendered region — the global reset had stripped list
  markers/indents and table borders), **syntax-highlighted** fenced code
  ([highlight.js](https://highlightjs.org) 11.10, themed for light/dark), and the
  plugins **task-lists** (`- [x]`), **custom containers** (`::: name` →
  `div.md-container.md-<name>`, any name; `warning`/`danger`/`tip` get accent
  colours), **footnotes**, **definition lists**, **sub/superscript**, and
  **`==mark==`** — all vendored under `static/vendor/`, no CDN.
- **MCP tools** for journals: `list_journals` (dedicated, with a **backward**
  default window — 30 days ago through now, the reverse of `list_items`; returns
  title/date/uid only, **not** the Markdown body), `create_journal`,
  `update_journal`, `delete_journal`, plus a `journal` item_type for
  `get_item_details` (which returns the full body). Write tools require a
  read-write token and respect scope.
- i18n strings added in English and Czech (`opt_journal`, `journal`,
  `new_journal`, `noun_journal`, `this_journal`, `date`, `modal_journal_body`).
- Tests: radicale round-trip CRUD + Markdown-body persistence + multiple-per-day
  (`tests/test_journals.py`), router validation/auth (`tests/test_journals_api.py`),
  and MCP journal tools incl. the backward listing window (`tests/test_mcp.py`).

### Added — Double-click to create events (2026-06-18)
- New per-user setting **`double_click_to_create_events`** (Settings → Preferences,
  off by default). When off, a single click on empty calendar space opens the
  create modal as before. When on, a single click only highlights the day/slot and
  a double click opens the create modal. Drag-to-select keeps opening the modal in
  both modes. New `UserSettings` column (with a migration default) plumbed through
  `/settings`, the page render context, and `window.__SETTINGS__`; the FullCalendar
  `dateClick` handler does manual double-click detection in `webcaldav/static/app.js`.

### Added — MCP server & API tokens (2026-06-17)
- New optional **MCP server** at `/mcp` (Streamable HTTP, via the official `mcp`
  SDK / `FastMCP`) letting AI assistants read and write the user's calendars and
  tasks. Off by default; gated by the `MCP_SERVER_ENABLED` env var. All MCP I/O
  is English and ISO 8601. Documented in `MCP.md` (linked from `README.md`, with
  the feature highlighted in the intro).
- Tools: `list_calendars`, `list_items` (events/tasks/both, agenda style),
  `get_item_details`,
  `create_event`, `create_task`, `update_event`, `update_task`, `set_task_status`
  (done/undone), `delete_event`, `delete_task`. Recurring edits/deletes take a
  `scope` of `this` / `thisfuture` / `all`. Mutating tools reuse the same
  CalDAV/recurrence/reminder primitives as the `/events` and `/tasks` routers
  (`webcaldav/mcp_server.py`).
- **API tokens** (`webcaldav/tokens.py`, `routers/api_tokens.py`, new `APIToken`
  / `APITokenCalendar` models): minted in **Settings → API Tokens**, shown once.
  Token plaintext is `WebCalDav` + `RO`/`RW` + a random secret, so the access
  mode is visible in the token. Tokens can be **read-only or read-write**
  (read-only is rejected by mutating tools) and **scoped** to specific calendars
  (unscoped tokens include calendars added later; scoped ones do not) with an
  **optional expiry**.
- **Security:** an API token can decrypt the user's CalDAV credentials, but the
  zero-knowledge-at-rest property is preserved — the DEK *and* the token's
  authoritative mode/scope/expiry are sealed in an AES-GCM blob keyed by the
  token secret (only its SHA-256 is stored). Tampering with the plaintext mirror
  columns / `api_token_calendars` rows cannot widen scope or flip to read-write
  without the secret. Changing the login password keeps tokens valid (DEK
  unchanged); admin `reset_password` rotates the DEK and now deletes the user's
  tokens. The `/mcp` route is exempt from the CSRF header check (bearer-auth, no
  ambient cookie); FastMCP DNS-rebinding Host validation is disabled because the
  app runs behind a trusted reverse proxy. When `MCP_SERVER_ENABLED` is off,
  `/mcp` is unmounted and token creation is blocked, but listing/revoking still
  works (the UI greys out only the create form).

### Added — internationalization + Czech (2026-06-17)
- The app is now **translatable**, shipping **English** and **Czech**. A new
  per-user **language** setting (`autodetect` / `english` / `czech`) lives on
  `UserSettings` (with the usual SQLite `ALTER TABLE` migration) and on
  `/settings`, with a **Language** picker in Settings → Preferences. Changing it
  reloads the page (the active catalog is injected at render time).
- Language resolution is server-side (`webcaldav/i18n.py`): a concrete setting
  wins; `autodetect` parses the browser `Accept-Language` header (by q-order)
  and falls back to English. The server sets `<html lang>` and injects the
  resolved catalog as `window.__I18N__` + `window.__LANG__`.
- Translation catalogs are JSON under `webcaldav/locales/` (`en.json` is the
  source of truth; `cs.json` mirrors its keys). Sections: `ui` (static markup,
  applied client-side over `data-i18n*` attributes), `dyn` (dynamic JS strings
  with `{placeholder}` + Czech-aware pluralization), `errors` (server
  `HTTPException` detail strings, translated client-side at the `api*` boundary),
  and `fc` (FullCalendar buttons/labels). Date locale is **fully localized**:
  FullCalendar uses a locale object whose `code` drives native Intl
  month/weekday names, and Luxon's default locale follows the language.

### Added — dark mode (2026-06-17)
- User-selectable UI **theme**: `system` (follow OS `prefers-color-scheme`,
  default), `light`, or `dark`. New `theme` field on `UserSettings` (with the
  usual SQLite `ALTER TABLE` migration) and on `/settings`.
- The whole UI is themed via CSS custom properties on `:root`; the server
  renders `data-theme` on `<html>` so the correct theme paints on first load
  (no flash). `system` tracks the OS live through a `prefers-color-scheme`
  media query; explicit changes apply instantly via `document.documentElement`.
  FullCalendar is themed through its own `--fc-*` variables. A **Theme** picker
  was added to the Settings → Preferences form.

### Added — tasks (VTODO) (2026-06-16)
- Full CalDAV **task** support alongside events. Tasks are read from and written
  to the same calendars as VTODO components and shown in every view (month,
  week, day, agenda), visually distinct from events: a **checkbox square**
  (empty / ticked) instead of the event dot, sharing the per-calendar colour.
- New `/tasks` API mirroring `/events`: `GET /tasks`, `POST /tasks`,
  `PUT /tasks/{uid}`, `DELETE /tasks/{uid}`, plus `POST /tasks/{uid}/status` for
  done/undone toggling. Implemented in `webcaldav/routers/tasks.py`; the CalDAV
  layer gains `fetch_tasks` / `create_task` / `update_task` / `delete_task` /
  `set_task_status` that **reuse** the existing recurrence, override, and VALARM
  machinery (generalised over a component `_Kind`).
- Tasks reuse the **same editing modal** as events via an Event/Task type
  toggle; Start → DTSTART, Due → DUE (both optional — undated tasks are
  supported), plus a Priority field. All-day, recurrence, reminders, location,
  notes, and cross-calendar move work the same as events.
- **Completion**: toggle via the checkbox square or the right-click menu
  ("Mark as done" / "Mark as undone"). Recurring tasks use **RFC advance** —
  completing one occurrence writes a per-occurrence `STATUS:COMPLETED` override
  and leaves the series so the next occurrence still appears.
- Two new user settings (with SQLite `ALTER TABLE` migrations and `/settings`
  fields): `completed_task_display` (`hidden` default / `grayed`) and
  `undated_task_display` (`agenda` default / `today`). Undated tasks appear in a
  dedicated "Tasks" section in the agenda, and (in `today` mode) pinned to the
  current day in the grid views.
- The Settings panel now scrolls between a fixed header and a **pinned Save
  button** that stays visible at the bottom.
- **Browser notifications for tasks**: the foreground scheduler now fetches
  `/tasks` alongside `/events` and fires reminders + due/start notifications for
  tasks the same way as events. Completed tasks are skipped; undated tasks (no
  date) produce no triggers.
- The editing modal gains a **"Task done" checkbox** (existing tasks only),
  which toggles completion on save via `/tasks/{uid}/status`. The
  this/this-and-future/all scope prompt now reads "task" instead of "event"
  when acting on a task.
- Fix: the checkbox square on **timed** tasks (dot-style chips in month/list
  views) now keeps its per-calendar colour instead of rendering black.
- The agenda view gains a pinned **"Overdue"** section (dated tasks still undone
  with a due/start before today, each shown with its date + time), sitting above
  the existing undated **"Tasks"** section and the day-grouped scroll list.

### Added — anchored reminders (before/after × start/end) (2026-06-14)
- Reminders can now fire relative to either the event **start** or **end**, and
  either **before** or **after** it — four quadrants instead of the old
  "before start" only. Use case: "15 minutes before the class ends." Each
  reminder row gains a single dropdown (before start / after start / before end /
  after end); the value/unit/time controls are unchanged.
- Wire format adds optional `anchor` (`start`|`end`, default `start`) and
  `direction` (`before`|`after`, default `before`) to each reminder; absent
  fields preserve the legacy behavior, so old payloads round-trip unchanged.
  The server maps the pair to the VALARM `TRIGGER`'s `RELATED` parameter and the
  duration sign (`TRIGGER;RELATED=END:-PT15M`, `TRIGGER:PT20M`, …). `RELATED=END`
  is only written when the event has a `DTEND`/`DURATION`, else it falls back to
  `START`.
- VALARMs with `RELATED=END` or after-event offsets are now **editable** (no
  longer surfaced read-only); only absolute-time and EMAIL alarms stay read-only.
- Browser notifications schedule end-anchored reminders off the event's end time
  (`rawEnd`), skipping any that lack one.
- The notification scheduler now also loads **past** events, back
  `NOTIFICATION_LOOKBACK_DAYS` (default 60, = the horizon), so an after-event
  reminder whose fire time is still in the future fires even once the event
  itself has ended. `buildTriggers` already drops anything past `now`, so the
  wider window only adds the pending after-anchored reminders.

### Added — browser notifications (2026-06-12)
- Optional per-user desktop notifications that fire at each event's reminder
  (VALARM) **and** at each event's start. Off by default; toggled under
  Settings → Preferences. New `user_settings.notifications_enabled` column
  (with a SQLite `ALTER TABLE` migration in `create_tables`) and a
  `notifications_enabled` field on the `/settings` API. Enabling it forces
  `auto_logout_enabled` off (server-enforced) — notifications need the tab to
  stay logged in to keep resyncing.
- **Foreground-only by design.** Notifications are scheduled client-side from
  events loaded during the session and shown via a new Service Worker
  (`webcaldav/static/sw.js`) so the OS routes them to its notification center.
  No Web Push / server-side push: that would require storing reminder times and
  titles server-side in the clear, breaking zero-knowledge at rest. They fire
  only while a WebCalDav tab is open (background tab is fine).
- Scheduler loads a future window of events (`NOTIFICATION_HORIZON_DAYS`,
  default 60) and re-polls every 10 min, gated by a new
  `GET /calendars/ctags` change channel. Radicale lacks RFC 6578
  sync-collection, so `fetch_sync_token` uses the caldav lib's etag-hash
  fallback token (changes on any add/edit/delete) to skip redundant refetches.
- Notification body is `WebCalDav` / event name / event datetime, the datetime
  rendered in the user's date & time format.

### Added — site icon / favicon (2026-06-12)
- Brand icon added under `webcaldav/static/`: master `icon.png` plus generated
  `favicon.ico` (16/32/48), `favicon-16x16.png`, `favicon-32x32.png`, and
  `apple-touch-icon.png` (180). Favicon `<link>`s wired into `index.html`
  `<head>`; inline logo shown on the login and change-password cards and beside
  the calendar header title. CSS adds `.auth-logo` (64px, centered) and
  `.app-logo` (24px, header).

### Fixed — event timezone drift on drag (2026-06-12)
- Dragging a timed event in month view shifted its start by the zone's UTC
  offset on every move (e.g. +2h in `Europe/Prague`, none in UTC). The drag
  sends a start with a numeric offset (`...+02:00`); the server kept that
  fixed-offset tzinfo, which icalendar serialized as a bogus
  `TZID="UTC+02:00"` with no VTIMEZONE, so the value read back as floating/UTC.
  `_resolve_span` now normalizes tz-aware start/end onto the named request
  timezone (`astimezone`), emitting a proper `TZID=Europe/Prague` and a stable
  round-trip.

### Fixed — audit findings L1–L4 (2026-06-11)
- **L2 — vendored frontend assets (no CDN):** FullCalendar, luxon, and the
  luxon3 plugin are now committed under `webcaldav/static/vendor/` and served
  from `/static`, replacing the jsDelivr `<script>` tags. Removes CDN-compromise
  risk (script in the authenticated origin holding the session cookie + DEK) and
  drops the browser-needs-internet requirement. Bumped to current latest:
  FullCalendar 6.1.20, luxon 3.7.2. The dead FullCalendar CSS `<link>` (the v6
  global bundle injects its own styles; the separate file 404s on jsDelivr now)
  was removed. Vendor files fold into the `?v=` cache-bust hash.
- **L1 — root handler:** `except Exception: pass` in the `/` session/DB lookup
  now logs at WARNING (`root_session_lookup_failed`) instead of silently
  rendering the anonymous page on a real failure.
- **L3 — event field caps:** `title` / `location` / `description` in
  `EventUpdate` now have `max_length=8000`.
- **L4 — cleanup:** removed the dead duplicate `select(CalDAVAccount)` in
  `admin.reset_password`.

### Security — auth hardening: fixes audit findings M1, M2, M4 (2026-06-11)
- **Secure session cookie + CSRF header (M1):** session cookie now sets
  `Secure` per new `COOKIE_SECURE` setting (default `true`); new middleware
  rejects mutating requests (POST/PUT/PATCH/DELETE) lacking
  `X-Requested-With: fetch` with 403, as defense-in-depth on top of
  `SameSite=Lax`. Frontend `api*` helpers and direct logout fetches send the
  header.
- **Login rate limiting (M2):** new in-memory per-IP sliding-window limiter
  (`webcaldav/ratelimit.py`) on `POST /auth/login`, checked *before* the
  argon2 derivation to close the CPU-amplification vector. Configurable via
  `LOGIN_RATE_LIMIT_ATTEMPTS` (default 5; 0 disables) and
  `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default 300); 429 + `Retry-After` when
  exceeded; successful login resets the counter. Client IP from the rightmost
  `X-Forwarded-For` entry (proxy-appended) or the socket peer.
- **argon2 hardening + password policy (M4):** default `ARGON2_MEMORY_COST`
  raised 65536 → 131072 (128 MiB). KDF parameters are now stored per user
  (`users.kdf_time_cost/kdf_memory_cost/kdf_parallelism`, backfilled by a
  startup column migration with the legacy 3/65536/1), so existing users keep
  logging in and upgrade to the new parameters on their next password change.
  `change-password` enforces `MIN_PASSWORD_LENGTH` (default 12).
- `docs/known_vulnerabilities.md`: M1, M2, M4 removed as fixed.

### Added — SSRF guard for CalDAV URLs (2026-06-11)
- New `BLOCK_PRIVATE_CALDAV_URLS` setting (default `false`; shipped `true` in
  `docker-compose.yml`). When enabled, `POST /caldav-accounts` rejects CalDAV
  server URLs whose hostname resolves to a private/loopback/link-local
  (incl. the `169.254.169.254` metadata IP)/reserved/multicast/unspecified
  address with a generic 400, and connection failures return a generic 502
  with no raw exception text (closing the internal-service probe oracle).
- New `validate_caldav_url()` / `UnsafeURLError` in `caldav_client.py`; resolves
  via `getaddrinfo` and checks every returned address (unwrapping IPv4-mapped
  IPv6). Disabled by default preserves prior behaviour for LAN CalDAV servers.
- Known residual: DNS-rebind/TOCTOU on later fetches (validation is on write).

### Added — MIT license (2026-06-11)
- `LICENSE` file (MIT, Zdeněk Novák), `license = "MIT"` in `pyproject.toml`,
  License section in `README.md`.

### Added — editable reminders / VALARM support (2026-06-11)
- Reminders are now fully editable in the event modal: a "+" button adds a row
  (number + unit + delete button), committed rows sort soonest-first and can
  only be deleted (delete + re-add to change one). Saving the event persists
  the full set as `ACTION:DISPLAY` VALARMs.
- Timed events take minutes/hours/days/weeks before the start ("months" is not
  an RFC 5545 duration and is deliberately absent). All-day events use a
  different model: days/weeks before **at a time of day** ("2 weeks before at
  9:00"), encoded as a single duration trigger off the DATE start (midnight) —
  e.g. `-P13DT15H`; "0 days before at 9:00" is the positive trigger `PT9H`.
  Toggling all-day in the modal drops rows the new mode can't express.
- Wire format both ways is structured: `reminders: [{value, unit, time?}]` in
  POST/PUT `/events` (absent = leave alarms untouched, so drag/resize updates
  never clobber them; `[]` = clear) and in `extendedProps.reminders` on fetch.
  Validation: value 0–10000, ≤10 reminders, all-day rows need `HH:MM` + a
  days/weeks unit (422 otherwise).
- Alarms outside the editable model — EMAIL alarms, absolute datetime triggers,
  `RELATED=END`, after-event offsets — are never rewritten or deleted; they
  show as dimmed read-only rows.
- Recurring events honour the existing scope chooser: "all" replaces the
  master's alarms (overrides keep their own), "this" snapshots the set onto the
  detached override, "this + future" carries the master's alarms to the new
  split series before applying the edit. Fixed a latent fallback leak where an
  override's properties could bleed into sibling occurrences via the master
  metadata map.
- All reminder times honour the user's `time_format` and `date_format`
  settings: the all-day row's time-of-day editor is the app's own hh:mm
  (+ AM/PM) fields rather than a locale-driven native `<input type="time">`,
  committed row text renders "9:00 PM" in 12h mode, and read-only
  absolute-trigger alarms ship the ISO instant (`at`) so the client formats
  them per settings instead of showing raw ISO.
- 90 tests passing (9 new radicale round-trip tests covering unit
  normalization, replace/clear/untouched semantics, all-day decomposition, and
  per-scope persistence, plus API validation and absolute-trigger tests).

### Added — agenda view, global "+" button, default-view setting (2026-06-11)
- New **Agenda** toolbar view: a flat chronological list of upcoming events from
  the start of today onward, one row per recurring occurrence, grouped under
  sticky day headers (today highlighted). Rows honour the time/date-format and
  timezone settings; clicking a row opens the normal edit modal (scope chooser
  included) via a minimal FullCalendar-event shim.
- The agenda is a custom DOM panel, not a FullCalendar view: it fetches
  `GET /events` in tiled forward 30-day windows and appends on scroll
  (IntersectionObserver sentinel + a post-load top-up loop that keeps fetching
  until the sentinel sits ~300px below the fold). An open-ended recurring series
  scrolls forever; a finite calendar stops after 6 consecutive empty windows
  ("No more events." / "No upcoming events."). Fetch errors show an inline Retry.
- While the agenda is open the FullCalendar header toolbar stays visible (only
  the view area collapses), the header title reads **Agenda**, and any toolbar
  button (views, prev/next/today) leaves the agenda; the title's date picker is
  disabled there.
- New **"+" floating action button** (bottom-right, all views) opens the create
  modal with no start/end preselected (saving still requires a start date).
- New `UserSettings.default_view` setting (`dayGridMonth` / `timeGridWeek` /
  `timeGridDay` / `agenda`, default month) with a Preferences select; invalid
  values are rejected with 422. The chosen view loads on sign-in. No DB
  migration — schema recreated.
- 79 tests passing (added `default_view` default/roundtrip/validation API tests).

### Added — faster date-picker navigation (2026-06-07)
- The mini date picker's title is now clickable: it switches to a **month grid**
  (title shows just the year) and the ‹ › arrows step whole **years**; clicking a
  month returns to that month's day grid. Makes jumping years ahead quick.
- The recurrence **end-date** picker now opens on the event's **start** month
  when empty, instead of today, so a future series doesn't force scrolling.
- The **FullCalendar header title** is now clickable too. In month view it opens
  the month grid (arrows step years) and jumps to the chosen month; in week/day
  view it opens a day picker and jumps to the chosen date's week/day. The custom
  picker was generalised (`openCalPicker`) to drive either a form field or
  `gotoDate`.

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
