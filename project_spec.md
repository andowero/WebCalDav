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

| Milestone | Scope                                                 |
|-----------|-------------------------------------------------------|
| MVP       | Secure user login, read-only view of calendar events |
| v1        | Editing of calendar events                            |

## Part 2: Technical design

### Tech stack

- Python 3.12
- `uv` for packaging and dependency management
- FastAPI (async, auto-OpenAPI, Prometheus middleware)
- `caldav` library for CalDAV access
- SQLAlchemy 2.x + SQLite (WAL mode)
- Jinja2 for the single server-rendered host page
- FullCalendar.js for the calendar widget
- Vanilla JavaScript for glue — no React, Vue, or Svelte
- `argon2-cffi` for argon2id
- `cryptography` for AES-GCM
- `structlog` for structured logging

### Data model

- `users(id, email, kdf_salt, wrapped_dek, dek_nonce, password_verifier, must_change_password, created_at)`
- `caldav_accounts(id, user_id, url, username, encrypted_password, nonce, created_at)`
- `calendars(id, caldav_account_id, caldav_id, display_name, color, enabled)`
- `user_settings(user_id, timezone, first_day_of_week)`

No plaintext password, no plaintext DEK, and no server-held wrapping key are ever stored.

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

Settings and ops:

- `GET /settings`, `PUT /settings`
- `GET /health`
- `GET /metrics`

**There is no `POST /auth/signup` or equivalent.** User creation is CLI-only.

### Admin CLI

`python -m webcaldav.admin` subcommands, intended to be run via `docker compose exec app …`:

- `create-user --email EMAIL` — prints one-off password
- `list-users`
- `reset-password --email EMAIL` — prints new one-off password, rotates DEK, wipes CalDAV credentials
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

### Browser support

Latest two versions of Firefox, Chrome, Opera, and Safari. Notifications via the Web Notifications API, backed by a Service Worker for background reminder delivery.
