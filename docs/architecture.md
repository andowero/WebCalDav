# Architecture

## System context

```
                    TLS
  [Browser] ─────────────────► [Reverse proxy]
                                     │ plain HTTP
                                     ▼
                              [WebCalDav (FastAPI)]
                                 │         │
                          plain  │         │ HTTPS (Basic auth,
                                 ▼         ▼  creds decrypted per request)
                          [SQLite volume]  [1..N user-configured CalDAV servers]
```

The app is a single container. TLS is terminated by the reverse proxy and the app never sees it. SQLite holds users, CalDAV account metadata, calendar selections, and user settings; event data is never cached locally.

## Components

### Auth module

- Endpoints: `POST /auth/login`, `POST /auth/logout`, `POST /auth/change-password`. No signup endpoint.
- Flow: argon2id(password, kdf_salt) → KEK → verify `password_verifier` → unwrap DEK (AES-GCM).
- Session store: in-memory `dict[session_id] = {user_id, dek, last_seen, restricted}`.
- Session lifecycle: opaque session-ID cookie (`HttpOnly`, `SameSite=Lax`, `Secure` per `COOKIE_SECURE`, default on), idle timeout (`SESSION_IDLE_TIMEOUT`), wiped on process restart.
- First-login guard: `restricted` sessions (when `users.must_change_password` is true) may only call `/auth/change-password` and `/auth/logout`; everything else returns 403.
- Login rate limiting: in-memory per-IP sliding window (`LOGIN_RATE_LIMIT_ATTEMPTS` per `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, 0 disables), checked before the argon2 derivation; 429 + `Retry-After` when exceeded, counter cleared on successful login. Client IP = rightmost `X-Forwarded-For` entry (appended by the trusted proxy) or the socket peer.
- CSRF defense-in-depth: middleware rejects mutating requests (POST/PUT/PATCH/DELETE) without `X-Requested-With: fetch` (403), on top of `SameSite=Lax`.
- Password policy: `change-password` enforces `MIN_PASSWORD_LENGTH` (default 12).

### Admin CLI

- `python -m webcaldav.admin` exposes `create-user`, `list-users`, `reset-password`, `delete-user`.
- The **only** path for provisioning users. Runs inside the container (`docker compose exec`).
- `create-user` and `reset-password` print a one-off password to stdout; the admin delivers it out-of-band.

### Crypto module

- Thin wrapper around argon2id (via `argon2-cffi`) and AES-GCM (via `cryptography`).
- argon2id parameters come from config (`ARGON2_*`, default `time_cost=3, memory_cost=131072, parallelism=1`) and are stored per user (`users.kdf_*`) at provision/password-change time, so hardening the defaults never locks out existing users; a startup migration backfills the columns with the legacy values (3/65536/1).
- Responsible for generating `kdf_salt` and all nonces.
- Zeroes DEK buffers on session teardown where the language permits.

### CalDAV client layer

- Wraps the `caldav` library.
- For each outbound request, looks up the current session's DEK, decrypts the relevant `caldav_accounts.encrypted_password`, and uses the plaintext credential only for the duration of that HTTP call.
- Handles **VEVENT** (events), **VTODO** (tasks), and **VJOURNAL** (journals).
  The recurrence, scoped-override, EXDATE/UNTIL, and VALARM helpers are
  generalised over a component `_Kind` (component name, end property
  `dtend`/`due`/none, icalendar class, caldav search flag) so the kinds share one
  implementation; tasks add
  `fetch_tasks`/`create_task`/`update_task`/`delete_task`/`set_task_status`.
  Tasks anchor on DUE (else DTSTART), both optional (undated tasks), and carry
  STATUS/COMPLETED/PERCENT-COMPLETE/PRIORITY; completing a recurring task writes
  a per-occurrence COMPLETED override (RFC advance).
- **Journals** (`_JOURNAL` kind, empty end-key) are the simplest: a SUMMARY +
  Markdown DESCRIPTION anchored on a single DTSTART (date or datetime), with no
  end, recurrence or alarms. `fetch_journals`/`create_journal`/`update_journal`/
  `delete_journal` write whole resources; the shared field helpers skip the end
  property when the kind has no end-key.
- Handles timeouts and retries.
- Never logs credentials or the DEK.

### MCP server & API tokens

- Optional MCP server (`webcaldav/mcp_server.py`, official `mcp` SDK / `FastMCP`,
  Streamable HTTP) mounted at `/mcp` only when `MCP_SERVER_ENABLED` is set. Its
  ten tools delegate to the same CalDAV client primitives and
  `EventUpdate`/`TaskUpdate` validation as the web routers; output is English +
  ISO 8601.
- Auth is per-request via `Authorization: Bearer WebCalDav…`. A pure-ASGI
  middleware resolves the token (`webcaldav/tokens.py`) into a `TokenContext`
  (user_id, DEK, mode, calendar scope) held in a `contextvars.ContextVar`; tools
  read it, enforce read-only vs read-write, and reject out-of-scope calendars.
- **Token sealing.** A token is `WebCalDav` + `RO`/`RW` + a random secret, shown
  once. The DB stores `sha256(secret)` (lookup) and an AES-GCM blob — keyed by a
  key derived from the secret (`derive_token_key`) — that seals the DEK together
  with the token's *authoritative* mode/scope/expiry. So (a) a stolen DB stays
  zero-knowledge without the token plaintext, and (b) the plaintext mirror
  columns / `api_token_calendars` rows are display-only — editing them cannot
  escalate a token because authorization reads the sealed blob.
- `/mcp` is exempt from the CSRF-header middleware (bearer auth, no ambient
  cookie). FastMCP DNS-rebinding Host validation is disabled (the app runs behind
  a trusted, Host-controlling reverse proxy). The FastMCP session manager is
  started inside the app lifespan (a mounted sub-app's lifespan is not run by the
  parent); the wrapper is mounted at the root so its own `/mcp` route is reached
  unstripped (no trailing-slash redirect).
- Token CRUD lives at `/api-tokens` (`routers/api_tokens.py`); creation requires
  an active session (the live DEK is sealed in) and `MCP_SERVER_ENABLED`, while
  listing/revoking always work. Admin `reset_password` rotates the DEK and
  deletes the user's tokens.

### Calendar sharing

- Share links and `.ics` export for a single item, a grid period
  (month/week/day), or an agenda slice (`webcaldav/routers/shares.py`,
  `webcaldav/shares.py`). The design mirrors MCP tokens exactly: the URL carries
  a random secret in its **fragment** (`/s/<id>#<secret>`); the DB stores
  `sha256(secret)` plus an AES-GCM blob — keyed by `derive_token_key(secret)` —
  sealing the DEK together with the share's *authoritative*
  kind/mode/scope/window/expiry. The `Share` mirror columns and `ShareCalendar`
  rows are display-only, never trusted for authorization.
- The share page (`GET /s/{id}`) **reuses the main app** (`index.html` +
  `app.js`) in a "share mode" (`window.__SHARE_MODE__`) so the editing/viewing
  modal, markdown rendering, type symbols, recurrence editor, i18n and date/time
  formatting match the normal calendar exactly; only the FullCalendar toolbar is
  locked (no nav/view switch, `validRange` = the sealed window) and the api*
  helpers reroute `/events|tasks|journals` to `/shares/*`. The sharer's display
  settings (timezone, first day, formats, theme, language) are looked up by share
  id and injected server-side, so the view renders as the sharer sees it. app.js
  reads the fragment secret and sends it as the `X-Share-Secret` header (never
  the request line, so it stays out of access/proxy logs and the Referer).
  `get_share_context`
  (`webcaldav/deps.py`) resolves it into a `ShareContext` (user_id, DEK, mode,
  readable/writable calendar sets, window). The share-view endpoints
  (`/shares/resolve`, `/shares/items`, the `/shares/{events,tasks,journals}`
  writers, `/shares/{id}/export.ics`) build a fake `SessionEntry` from the
  context and reuse the existing event/task/journal route handlers, enforcing
  read-only vs read-write and clamping reads to the sealed window. Writes are
  scope-checked against the writable calendar set (a single-item share only to
  its own uid). The window is re-derived server-side from the blob, so request
  params can only narrow, never widen.
- Grid windows are computed from the view + anchor date + the sharer's
  first-day-of-week (month = a fixed 6-week grid). Base URL for links is detected
  from `X-Forwarded-Proto`/`X-Forwarded-Host` (`webcaldav/baseurl.py`), override
  via `PUBLIC_BASE_URL`. Share CRUD at `/shares` requires a session (DEK sealed
  in) + `SHARING_ENABLED`; list/revoke always work. The `.ics` export serializes
  *unexpanded* components so RRULE/VALARM survive; a single VCALENDAR holds many.

### Storage layer

- SQLAlchemy 2.x models for `users`, `caldav_accounts`, `calendars`,
  `user_settings`, `api_tokens`, `shares`/`share_calendars`.
- `calendars.is_default` marks the per-user calendar pre-selected for new events
  (at most one, enforced at the API layer).
- `user_settings` carries the task display prefs `completed_task_display`
  (`hidden`/`grayed`) and `undated_task_display` (`agenda`/`today`); columns are
  added to pre-existing DBs via the `ALTER TABLE` migrations in `create_tables`.
- SQLite in WAL mode on a named Docker volume.

### API layer

- FastAPI routers per resource: `auth`, `caldav_accounts`, `calendars`, `events`, `tasks`, `journals`, `settings`, `ops` (`/health`, `/metrics`).
- `tasks` mirrors `events` for VTODO: `GET/POST /tasks`, `PUT/DELETE /tasks/{uid}`, and `POST /tasks/{uid}/status` (done/undone). It reuses the events router's recurrence/reminder models and helpers.
- `journals` is a trimmed mirror for VJOURNAL: `GET/POST /journals`, `PUT/DELETE /journals/{uid}`. No recurrence/reminders/end — just title, a single start (date or datetime), and a Markdown `description` body; calendar move on edit works as for events.
- `calendars` also serves `GET /calendars/ctags` — a per-calendar change token (the caldav lib's sync-token, falling back to an etag-hash on Radicale) used by the notification scheduler to skip redundant event refetches.
- `settings` carries `notifications_enabled`; enabling it forces `auto_logout_enabled` off (the two are mutually exclusive — notifications need a live session).
- Dependency injection resolves the current session and DEK; protected endpoints require an unrestricted session.

### Frontend

- Single Jinja2-rendered host page.
- Static assets: FullCalendar.js bundle (+ luxon and the `@fullcalendar/luxon3`
  plugin for named-IANA-timezone rendering) plus a small vanilla-JS glue layer
  that calls the API via `fetch`. Third-party libs are vendored under
  `static/vendor/` and served from `/static` (no CDN); the FullCalendar v6
  global bundle injects its own CSS, so there is no separate stylesheet.
- An event modal opens on event click for viewing/editing, populated from the
  event's `extendedProps` (`description`, `location`, `recurrence`,
  `recurrenceRule`, `reminders`, `rawStart`/`rawEnd`); dates are formatted
  client-side per the timezone + time format settings. Recurrence is fully
  editable via a recurrence editor (frequency, interval, monthly by
  day-of-month or Nth/last weekday, end-by-date / end-after-N) with a live
  last-occurrence preview.
- Reminders are editable rows in the modal ("+" to add, × to delete; no
  in-place edit). Timed events use value + minutes/hours/days/weeks; all-day
  events use days/weeks at a time of day (entered via the app's own hh:mm +
  AM/PM fields so the 12h/24h `time_format` setting applies, and rendered per
  that setting in row text). A per-row dropdown picks the **anchor + direction**:
  before/after the event **start** or **end** (default before start). The save
  request carries `reminders: [{value, unit, time?, anchor?, direction?}]`
  (absent = don't touch alarms, `[]` = clear; `anchor`/`direction` default to
  `start`/`before` and are omitted when default). The server maps each row to
  one `ACTION:DISPLAY` VALARM duration trigger — the offset sign carries
  direction and the `RELATED` parameter carries the anchor (`RELATED=END` only
  when the event has an end, else it falls back to `START`) — and returns the
  same structured shape in `extendedProps.reminders`. Only EMAIL and
  absolute-time alarms stay read-only.
- Deleting or editing a recurring event opens a scope chooser
  (`this` / `this+future` / `all` — the three industry-standard options); the
  chosen scope and the occurrence's pivot are sent to the API. Dragging or resizing a
  recurring occurrence on the grid opens the same chooser before persisting; the
  modal's "Repeats" checkbox is locked when editing an existing recurring series
  (a series can't be un-recurred from there).
- Creating events: clicking empty grid space (or dragging in week/day) opens the
  same modal blank with view-specific prefilled times and a calendar picker that
  defaults to the user's default calendar. The picker is also shown when editing,
  so an event can be moved between calendars.
- Deleting events: a Delete button in the modal, plus a right-click context menu
  (Edit / Delete) with a yes/no confirm before removal.
- Besides the three FullCalendar views (month/week/day) there is an **agenda**
  view: a custom infinitely-scrolling panel that fetches `/events` in tiled
  forward 30-day windows (IntersectionObserver sentinel) and lists upcoming
  occurrences chronologically; rows reuse the event modal via a small
  FC-event shim. A "+" floating button (all views) opens the create modal with
  no dates preselected. A per-user `default_view` setting picks the view shown
  at sign-in.
- **Browser notifications** (opt-in per user, off by default). While a tab is
  open and `notifications_enabled` is set, a client-side scheduler loads a
  window of events (back `NOTIFICATION_LOOKBACK_DAYS` and ahead
  `NOTIFICATION_HORIZON_DAYS`, both default 60), builds a trigger per event start
  and per reminder, drops any whose time is already past, and `setTimeout`s a
  notification for each. The look-back is what lets a reminder anchored *after*
  an event still fire once the event itself has ended. Notifications are shown via a Service Worker (`static/sw.js`,
  `registration.showNotification`) so the OS routes them to its notification
  center and clicks focus the tab; the SW does no caching or fetch interception.
  The body is `WebCalDav` / event name / event datetime (datetime in the user's
  formats). The scheduler re-polls every 10 min, gated by `GET /calendars/ctags`
  so unchanged calendars aren't re-fetched, and dedupes fired triggers by tag
  (persisted in `localStorage`). **Foreground-only:** no Web Push, so closing
  the browser stops notifications — see "Reminders while logged out" below.
- No build step beyond bundling FullCalendar's CSS/JS.

### Internationalization (i18n)

- The app ships **English** and **Czech**. Translation catalogs are JSON files
  under `webcaldav/locales/` (`en.json` is the source of truth; `cs.json` mirrors
  its key set — a test enforces parity). Catalog sections: `ui` (static markup),
  `dyn` (dynamic JS strings with `{placeholder}` interpolation and a Czech-aware
  3-form plural helper), `errors` (server `HTTPException` detail strings keyed by
  their exact English text), `fc` (FullCalendar button/helper text), plus `units`
  and `ordinals` for grammar.
- **Effective language** is resolved server-side in `webcaldav/i18n.py`
  (`resolve_language`): the per-user `language` setting (`autodetect` / `english`
  / `czech`) wins when concrete; `autodetect` parses the browser
  `Accept-Language` header by q-order and falls back to English. The `/` route
  sets `<html lang>` and injects the resolved catalog as `window.__I18N__` plus
  `window.__LANG__`.
- The frontend consumes the catalog in one place: a `tr(key, params)` helper
  (named `tr`, not `t`, to avoid clashing with task variables) and a one-time
  `applyTranslations()` DOM sweep over `data-i18n` / `data-i18n-placeholder` /
  `data-i18n-title` / `data-i18n-aria-label` attributes. Server error messages
  are translated at the `api*` fetch boundary via the `errors` map, so every call
  site benefits without change. Changing the language setting triggers a reload
  (the catalog is fixed at render time). Date locale is fully localized:
  FullCalendar gets a locale object whose `code` drives native `Intl`
  month/weekday names (no locale bundle vendored) and Luxon's default locale is
  set to the active language.

### Observability

- Prometheus middleware on FastAPI for `http_requests_total`.
- App-level metrics: `active_sessions`, `caldav_request_duration_seconds`, `caldav_request_errors_total`.
- `structlog` for JSON logs; level controlled by `LOG_LEVEL`.

### Testing

Tested mainly by driving the HTTP API in-process — no container, no live network. Four layers:

- **Crypto unit tests** — KEK derivation, DEK wrap/unwrap, AES-GCM roundtrip, `password_verifier`, nonce uniqueness, DEK rotation on reset.
- **API tests** — FastAPI `TestClient` (httpx ASGI) over a temp SQLite DB: first-login `restricted`→unrestricted flow, 403/401 auth boundaries, session lifecycle, `caldav-accounts`/`calendars`/`settings` CRUD.
- **CalDAV layer** — a fake client injected via `dependency_overrides` for fast `/events` proxy tests, plus an in-process **`radicale`** instance for real REPORT/PUT/DELETE integration tests.
- **Admin CLI** — entrypoint functions called directly (no subprocess) for `create-user`/`reset-password`/`list-users`/`delete-user`.

Design choices that make this work:

- **Dependency injection** for the CalDAV client and session store, swapped in tests via `app.dependency_overrides`.
- **Configurable argon2id parameters** — weak parameters under test so the suite stays fast; real parameters in production.
- **`DATABASE_URL` override** for a throwaway DB per test.
- **Injectable clock** so idle-timeout tests advance time without sleeping.
- **Shared provisioning function** behind both the admin CLI and test fixtures.

No automated browser/E2E tests; the frontend, Service Worker, and notifications are verified manually.

## Data flows

### User provisioning

```
admin ── docker compose exec app python -m webcaldav.admin create-user --email alice@example.com
         │
         ▼
 CLI generates one-off password + DEK
 KEK = argon2id(one-off password, kdf_salt)
 wrapped_dek = AES-GCM-encrypt(DEK, KEK, dek_nonce)
 INSERT INTO users (..., must_change_password = true)
 print(one-off password)  ──► admin delivers out-of-band
```

### First login

```
browser ── POST /auth/login ──► verify password_verifier
                                unwrap DEK
                                session = { restricted = true }
                                set session cookie
browser ── any protected route ─► 403 (restricted)
browser ── POST /auth/change-password ──► re-wrap DEK with new KEK
                                          clear must_change_password
                                          clear restricted flag
                                          session continues with DEK
```

### Normal login

```
browser ── POST /auth/login ──► argon2id(password, kdf_salt)
                                verify password_verifier
                                unwrap DEK
                                sessions[session_id] = { user_id, dek, ... }
                                set opaque session cookie
password is discarded as soon as the KEK has been derived
```

### View events

```
browser (FullCalendar range query)
   │
   ▼
GET /events?calendar_ids=…&from=…&to=…
   │
   ▼
session lookup → DEK
for each requested calendar:
   decrypt caldav_accounts.encrypted_password with DEK
   issue CalDAV REPORT
merge + normalize responses → JSON
```

No local event cache.

### Create / edit / delete event

```
create:  POST   /events                       ──► DEK-decrypt creds ──► CalDAV PUT (new UID)
                                                   (optional RRULE from recurrence editor)
edit:    PUT    /events/{uid}                  ──► DEK-decrypt creds ──► CalDAV PUT (in place)
move:    PUT    /events/{uid}                  ──► create on target calendar (same UID),
           (original_calendar_id ≠ calendar_id)     then delete from source calendar
delete:  DELETE /events/{uid}?calendar_id=…    ──► DEK-decrypt creds ──► CalDAV DELETE
preview: POST   /events/recurrence-preview     ──► dateutil.rrule ──► {last, count}
```

Recurring writes carry a `scope` (`this` / `thisfuture` / `all` — the three
standard options Google/Apple/Outlook use) and a `recurrence_id` pivot (the
occurrence's original start). The CalDAV layer maps these to iCalendar edits:
whole-resource delete, `EXDATE`, `UNTIL` truncation, `RECURRENCE-ID` overrides,
or splitting the series at the pivot. A `thisfuture` split produces two **fully
independent** resources (new UID for the spun-off series, no `RELATED-TO` link),
matching the de-facto standard: editing or deleting one half never touches the
other. Overrides outside a surviving range are garbage-collected rather than
orphaned. Moving a recurring event is rejected (400) since a move recreates a
single VEVENT. No local event cache.

### View / create / edit / complete tasks

```
view:    GET    /tasks?from=…&to=…          ──► CalDAV REPORT (VTODO, expand)
                                                + a pass for undated VTODOs
create:  POST   /tasks                      ──► CalDAV PUT (new UID, VTODO)
edit:    PUT    /tasks/{uid}                 ──► CalDAV PUT (in place)
status:  POST   /tasks/{uid}/status         ──► set STATUS/COMPLETED (or a
           {completed, recurrence_id?}           per-occurrence override for a series)
delete:  DELETE /tasks/{uid}?calendar_id=…  ──► CalDAV DELETE / EXDATE / truncate
```

Tasks follow the same scope/recurrence rules as events (shared CalDAV helpers).
The frontend merges `/tasks` into the FullCalendar source and the agenda,
applying the `completed_task_display` (hidden/grayed) and `undated_task_display`
(agenda/today) settings client-side. No local task cache.

### View / create / edit / delete journals

```
view:    GET    /journals?from=…&to=…        ──► CalDAV REPORT (VJOURNAL)
create:  POST   /journals                    ──► CalDAV PUT (new UID, VJOURNAL)
edit:    PUT    /journals/{uid}              ──► CalDAV PUT (in place / move)
delete:  DELETE /journals/{uid}?calendar_id=… ──► CalDAV DELETE
```

Journals are dated notes: SUMMARY + Markdown DESCRIPTION on a single DTSTART, no
end/recurrence/alarms. The frontend merges `/journals` into the FullCalendar
source and the agenda, rendering each with a downward-triangle marker and editing
the body in a two-tab editor — an "Edit" tab (a plain textarea of raw Markdown)
and a read-only "Display" tab that renders it via vendored markdown-it + plugins
(container, task-lists, footnote, deflist, sub/sup, mark) with highlight.js for
fenced code (images disabled, raw HTML escaped). No local journal cache.

### Logout or expiry

```
session entry deleted → DEK drops out of scope
subsequent requests require fresh login
```

## Deployment topology

- Single container, reachable only via the reverse proxy network.
- Bind-mounted or named Docker volume for the SQLite file.
- Environment variables: `DATABASE_URL`, `LOG_LEVEL`, `SESSION_IDLE_TIMEOUT`.
- **No `APP_SECRET_KEY` / master key.** All sensitive encryption is per-user and keyed by the user's password.
- Admin operations run via `docker compose exec app python -m webcaldav.admin …`.

## Open questions

- **Reminders while logged out — resolved (foreground-only).** Reminders need fresh CalDAV state, which needs the DEK, which only exists during a session. Rather than persist a DEK-encrypted reminder cache (extra at-rest surface) or push from the server (which would require plaintext reminder data on the server, breaking zero-knowledge), notifications are **foreground-only**: scheduled in the browser from events loaded during the session and fired while a WebCalDav tab stays open (background tab is fine). Closing the browser stops them. Enabling notifications disables auto-logout so the session stays alive. Server-side Web Push was deliberately rejected; on iOS background push would also need an installed PWA, which the desktop-first product doesn't target.
- **Single-user vs. multi-user deployments.** The design supports multiple users in one container; whether typical self-hosters prefer one-container-per-user (simpler backup, simpler reset semantics) is unresolved.
