# Project spec

## Part 1: Product requirements

### Who is the product for?

Self-hosters who run their own CalDAV server (e.g. Radicale) and want browser access to their calendar from machines where they can't or don't want to install dedicated software — typically a work computer. The user described in the brainstorming has moved away from Google services and uses native calendar apps on Ubuntu and Android; the gap is the browser.

Accounts are provisioned by the server administrator. The app is **not** a multi-tenant signup service.

### What problems does it solve?

- Existing self-hosted CalDAV web UIs (AgenDav, InfCloud) are abandoned and unmaintained.
- Nextcloud covers the use case but is far too heavy if calendar is all you need.

### What does the product do?

- Authenticates an admin-provisioned user.
- Lets the user register one or more CalDAV server credentials and pick which calendars from each to display.
- Shows events in month, week, and day views with per-calendar colors.
- Lets the user click any event to edit all of its attributes.
- Fires browser notifications for reminders on the supported browsers.

### User lifecycle

- **Creation.** Admin runs a CLI command that creates the user and prints a one-off password. Admin delivers the password to the user out-of-band (e.g. Signal, secure email).
- **First login.** The user logs in with the one-off password and is forced to change it before any other action.
- **No self-signup. No password-reset UI. No "forgot password" flow.** A forgotten password means the user's CalDAV credentials are unrecoverable — this is the explicit cost of zero-knowledge at rest. The admin can issue a new one-off password via the CLI, but doing so rotates the user's data encryption key, which invalidates their stored CalDAV credentials; the user must re-enter them after the reset.

### Milestones

| Milestone | Scope                                                              |
|-----------|--------------------------------------------------------------------|
| MVP       | Secure user login, read-only view of calendar events               |
| v1        | Basic editing of calendar events (no recurrence)                   |
| v2        | Editing of recurring events                                        |
| v3        | Event reminders (VALARM) and browser notifications                 |
| v4        | Task (VTODO) support: view, edit, complete, recurrence             |
| v5        | Dark mode (system / light / dark theme)                            |
| v6        | Internationalization (i18n) + Czech translation                    |
| v7        | MCP server: calendar/task access via API token                     |
| v8        | Configurable double-click action (event vs. task creation)         |
| v9        | VJOURNAL support (read and write calendar journal entries)         |
| v10       | Calendar sharing: read-only/read-write share links + `.ics` for a single item, a grid period, or an agenda slice |

## Part 2: Technical design

### Tech stack

- Python 3.12
- `uv` for packaging and dependency management
- FastAPI (async, auto-OpenAPI, Prometheus middleware)
- `caldav` library for CalDAV access
- SQLAlchemy 2.x + SQLite (WAL mode)
- Jinja2 for the single server-rendered host page
- FullCalendar.js for the calendar widget
- markdown-it (vendored, MIT) + plugins (container, task-lists, footnote, deflist, sub, sup, mark) and highlight.js to render the journal Markdown body; the "Edit" tab is a plain textarea, the "Display" tab is read-only rendered output (images disabled)
- Vanilla JavaScript for glue — no React, Vue, or Svelte
- `argon2-cffi` for argon2id
- `cryptography` for AES-GCM
- `structlog` for structured logging
- `pytest`, `pytest-asyncio`, `httpx` (ASGI `TestClient`), `pytest-cov` for tests
- `radicale` as a real CalDAV server fixture in integration tests
- `freezegun` (or an injectable clock) for time-dependent tests
- `ruff` for lint, `mypy` for type checks

### Data model

- `users(id, email, kdf_salt, wrapped_dek, dek_nonce, password_verifier, must_change_password, created_at)`
- `caldav_accounts(id, user_id, url, username, encrypted_password, nonce, created_at)`
- `calendars(id, caldav_account_id, caldav_id, display_name, color, enabled, is_default)`
- `user_settings(user_id, timezone, first_day_of_week, time_format, date_format, default_view, auto_logout_enabled, auto_logout_timeout_seconds, notifications_enabled, completed_task_display, undated_task_display, theme, language)`
- `api_tokens(id, user_id, name, token_sha256, sealed_blob, blob_nonce, mode, all_calendars, expires_at, created_at, last_used_at)` — MCP API tokens. `token_sha256` is the lookup hash; `sealed_blob`/`blob_nonce` is an AES-GCM blob keyed by the token secret holding the *authoritative* `{dek, mode, all_calendars, calendar_ids, expires_at}`. The plaintext `mode`/`all_calendars`/`expires_at` columns are a display-only mirror, never trusted for authorization.
- `api_token_calendars(id, api_token_id, calendar_id)` — display-only scope rows for a calendar-scoped token (authoritative scope is in `api_tokens.sealed_blob`).
- `shares(id, user_id, name, token_sha256, sealed_blob, blob_nonce, kind, mode, expires_at, item_uid, item_kind, item_calendar_id, grid_view, grid_anchor, agenda_from, agenda_to, default_calendar_id, created_at, last_used_at)` — share links. `kind` is `item`/`grid`/`agenda`. `token_sha256` is the lookup hash; `sealed_blob`/`blob_nonce` is an AES-GCM blob keyed by the URL-fragment secret holding the *authoritative* `{dek, kind, mode, scope, window, expires_at}`. All other columns are a display-only mirror, never trusted for authorization. Same sealing design as `api_tokens`.
- `share_calendars(id, share_id, calendar_id, writable)` — display-only calendar scope (and per-calendar write flag) for a grid/agenda share (authoritative scope is in `shares.sealed_blob`).

The canonical schema is in `webcaldav/models.py`; the table above is the logical summary. No plaintext password, no plaintext DEK, no server-held wrapping key, and no plaintext API-token secret are ever stored.

### Security — zero-knowledge design

**Keys and records.** Each user has a random 32-byte Data Encryption Key (DEK). The DEK is wrapped with a Key Encryption Key (KEK) derived from the user's password via argon2id using the per-user `kdf_salt`. Only the wrapped DEK is stored. A separate `password_verifier` (second argon2id invocation with a distinct context, or HKDF from KEK) is used to authenticate the password.

**User creation (admin-only, no UI).** The admin runs:

```
docker compose exec app python -m webcaldav.admin create-user --email alice@example.com
```

The CLI generates a random one-off password, generates a random DEK, derives KEK from the one-off password, wraps the DEK, stores `wrapped_dek` + `dek_nonce`, stores `password_verifier`, sets `must_change_password = true`, and prints the one-off password to stdout. There is **no HTTP endpoint for user creation.**

**Login.** The server re-derives KEK from the submitted password and stored `kdf_salt`, verifies `password_verifier`, unwraps the DEK, and stores the DEK only in a server-side in-memory session store keyed by an opaque session-ID cookie. The DEK is never persisted and never logged. If `must_change_password = true`, the session is flagged `restricted` — the only routes the session can hit are `POST /auth/change-password` and `POST /auth/logout`; anything else returns 403.

**First-login password change.** The user submits old and new passwords. The server re-derives the old KEK, unwraps the DEK, re-wraps it with the new KEK, updates `wrapped_dek` + `dek_nonce` + `password_verifier`, clears `must_change_password`, and keeps the session alive with the unwrapped DEK.

**Voluntary password change.** Same flow, requires the old password.

**CalDAV credentials at rest.** Encrypted with AES-GCM under the user's DEK, per-record nonce. Decryption requires an active session that holds the unwrapped DEK.

**Session termination.** Logout, session idle timeout, or process restart wipes the in-memory session map. DEKs drop out of scope and the user must log in again.

**Admin password reset.** `reset-password --email EMAIL` issues a new one-off password **and rotates the DEK.** All of the user's stored CalDAV credentials are invalidated and must be re-entered.

**Threat model covered.** Database theft without access to live server memory yields no CalDAV credentials.

**Threat model NOT covered.** A compromised running server can read in-memory DEKs for currently logged-in users. The server sees the user's password transiently during login (TLS is terminated by the reverse proxy, so the password arrives in plaintext at the app). Clients must trust the running server; zero-knowledge applies to data at rest, not during active use.

**Session cookie.** `HttpOnly`, `SameSite=Lax`, `Secure` (the latter set by the reverse proxy).

**Share links.** Same sealing design as MCP API tokens. A share's URL carries a random secret in its **fragment** (`/s/<id>#<secret>`); the DEK and the share's authoritative kind/mode/scope/window/expiry are sealed in an AES-GCM blob keyed by `derive_token_key(secret)`. Only `sha256(secret)` is stored; the `shares`/`share_calendars` mirror columns are display-only and never trusted for authorization. The secret is sent in the `X-Share-Secret` header (never the request line), keeping it out of access/proxy logs and the Referer. A stolen DB without the secret, or a leaked URL without the DB row, yields nothing — both are needed. Expiry is enforced from the sealed blob; reads are clamped to the sealed window and writes to the sealed writable-calendar set. Anyone holding a link has the granted access, so links expire (default 30 days) and are revocable. Gated by `SHARING_ENABLED`. See `SHARING.md`.

**No TLS termination in the app.**

### API surface

Authentication:

- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/change-password` — used for both the forced first-login flow and voluntary changes

CalDAV accounts and calendars:

- `GET /caldav-accounts`, `POST /caldav-accounts`, `DELETE /caldav-accounts/{id}`
- `GET /calendars`
- `PATCH /calendars/{id}` — change color or enabled flag

Events (proxy to CalDAV, no local cache):

- `GET /events?from=&to=&calendar_ids=`
- `POST /events`
- `PUT /events/{uid}`
- `DELETE /events/{uid}`

Tasks — VTODO (proxy to CalDAV, no local cache):

- `GET /tasks?from=&to=`
- `POST /tasks`, `PUT /tasks/{uid}`, `DELETE /tasks/{uid}`
- `POST /tasks/{uid}/status` — mark done/undone

Journals — VJOURNAL (proxy to CalDAV, no local cache):

- `GET /journals?from=&to=&calendar_ids=`
- `POST /journals`, `PUT /journals/{uid}`, `DELETE /journals/{uid}`
- A journal is a title + a Markdown body anchored on a single date(time); no end, recurrence or reminders.

Combined read (proxy to CalDAV, no local cache):

- `GET /calendar-data?from=&to=&kinds=events,tasks,journals` → `{events, tasks, journals}`.
- One request for the main view loads: calendars are grouped by account and each account is fetched over a single reused CalDAV connection (one client per account, plain HTTP/1.1). `kinds` selects which item kinds to return. The per-kind `/events`, `/tasks`, `/journals` endpoints remain for MCP/shares/tests.

Settings and ops:

- `GET /settings`, `PUT /settings`
- `GET /health`
- `GET /metrics`

MCP API tokens (settings UI):

- `GET /api-tokens` — list token metadata (never the secret)
- `POST /api-tokens` — mint a token (requires `MCP_SERVER_ENABLED` + active session); returns the plaintext once
- `DELETE /api-tokens/{id}` — revoke (works even when the MCP server is disabled)

MCP server (only mounted when `MCP_SERVER_ENABLED`):

- `/mcp` — Streamable HTTP (`mcp` SDK / `FastMCP`), authenticated by
  `Authorization: Bearer WebCalDav…`. Tools: `list_items`, `list_journals`,
  `get_item_details`, `create_event`, `create_task`, `create_journal`,
  `update_event`, `update_task`, `update_journal`, `set_task_status`,
  `delete_event`, `delete_task`, `delete_journal`. English + ISO 8601;
  read-only tokens are rejected by mutating tools; scoped tokens are limited to
  their calendars. `list_journals` defaults to a backward time window (journals
  are mostly in the past). See `MCP.md`.

Calendar sharing:

- `GET /shares` — list the user's share links (metadata only, never the secret)
- `POST /shares` — create a share of kind `item`/`grid`/`agenda` (requires
  `SHARING_ENABLED` + active session; DEK + scope sealed in); returns the URL
  with its fragment secret once
- `DELETE /shares/{id}` — revoke (works even when `SHARING_ENABLED` is off)
- `GET /s/{id}` — the share-view page; reuses the main app (`index.html` +
  `app.js`) in a navigation-locked share mode (the secret rides in the fragment
  and is never sent to this route). The sharer's display settings are injected
  server-side by share id.
- Share-secret-authed (the `X-Share-Secret` header carries the fragment secret):
  `POST /shares/resolve` (view config, no DEK), `GET /shares/items` (events/tasks/
  journals clamped to the sealed window/scope), `POST|PUT|DELETE
  /shares/{events,tasks,journals}[/{uid}]` (read-write shares only; scope-checked
  against the writable calendars), `GET /shares/{id}/export.ics` (a single
  VCALENDAR; `text/calendar`). See `SHARING.md`.

**There is no `POST /auth/signup` or equivalent.** User creation is CLI-only.

### Admin CLI

`python -m webcaldav.admin` subcommands, intended to be run via `docker compose exec app …`:

- `create-user --email EMAIL` — prints one-off password
- `list-users`
- `reset-password --email EMAIL` — prints new one-off password, rotates DEK, wipes CalDAV credentials and API tokens
- `delete-user --email EMAIL`

### Deployment

- Multi-stage `Dockerfile` on `python:3.12-slim`.
- `docker-compose.yml` for local and production use.
- Image published to GHCR via GitHub Actions on tag push.
- SQLite file on a named Docker volume.
- Environment variables: `DATABASE_URL`, `LOG_LEVEL`, `SESSION_IDLE_TIMEOUT`.
- **No server-side master key.** All sensitive encryption is per-user and keyed by the user password.

### Observability

- Prometheus `/metrics` exposing at minimum:
  - `active_sessions` (gauge)
  - `caldav_request_duration_seconds` (histogram, labeled by operation)
  - `caldav_request_errors_total` (counter)
  - `http_requests_total` (counter, labeled by route and status)
- Structured JSON logs via `structlog`, levels DEBUG/INFO/WARNING/ERROR.
- Passwords, DEKs, and CalDAV credentials are never logged.

### Testing

The app is tested primarily by calling the HTTP API directly with an in-process ASGI client — no live network, no running container required. Four layers:

**1. Crypto unit tests.** The security core, tested as pure functions:
- KEK derivation is deterministic for a given password + `kdf_salt`.
- DEK wrap → unwrap roundtrip recovers the original key; wrong password fails.
- AES-GCM encrypt → decrypt roundtrip for CalDAV credentials; tampered ciphertext fails.
- `password_verifier` accepts the correct password and rejects wrong ones.
- Nonces are unique across calls.
- `reset-password` rotates the DEK so old `encrypted_password` records no longer decrypt.

**2. API tests (call the endpoints).** FastAPI `TestClient` over httpx ASGI against a temporary SQLite database created per test. Coverage:
- First-login flow: login → `restricted` session → every protected route returns 403 → `POST /auth/change-password` clears `must_change_password` → session becomes unrestricted.
- Auth boundaries: no session → 401; restricted session limited to `change-password`/`logout`; confirm no signup endpoint exists.
- Session behavior: cookie attributes, idle timeout, logout wipes the session entry.
- CRUD on `caldav-accounts`, `calendars` (`PATCH` color/enabled), and `settings`.

**3. CalDAV layer tests (mock + real Radicale).** Two complementary suites:
- *Fast suite:* a fake CalDAV client injected via FastAPI `dependency_overrides`, exercising the adapter and the `/events` proxy logic without a server.
- *Integration suite:* a real `radicale` instance run in-process on a temp directory, exercising actual REPORT/PUT/DELETE against `/events` for end-to-end protocol confidence.

**4. Admin CLI tests.** Call the CLI entrypoint functions directly (not via subprocess): `create-user` inserts the user and prints a one-off password, `reset-password` rotates the DEK and wipes CalDAV credentials, `list-users`, `delete-user`. The CLI and test fixtures share one provisioning function.

**Testability requirements baked into the design:**
- **Dependency injection** for the CalDAV client and the session store, so tests swap fakes via `app.dependency_overrides`.
- **Configurable argon2id parameters** — real parameters make the suite crawl, so tests run with deliberately weak parameters set via config/env.
- **`DATABASE_URL` override** to point each test at a throwaway database.
- **Injectable clock** so idle-timeout tests advance time instead of sleeping.
- **Shared provisioning function** used by both the admin CLI and test fixtures, so user setup needs no subprocess.

**Out of scope.** No automated browser/E2E tests (no Playwright). The FullCalendar UI, Service Worker, and browser notifications are verified manually against the supported browsers.

### Browser support

Latest two versions of Firefox, Chrome, Opera, and Safari. Notifications via the Web Notifications API, backed by a Service Worker for background reminder delivery.
