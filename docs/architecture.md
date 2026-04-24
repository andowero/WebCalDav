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
- Session lifecycle: opaque session-ID cookie, idle timeout (`SESSION_IDLE_TIMEOUT`), wiped on process restart.
- First-login guard: `restricted` sessions (when `users.must_change_password` is true) may only call `/auth/change-password` and `/auth/logout`; everything else returns 403.

### Admin CLI

- `python -m webcaldav.admin` exposes `create-user`, `list-users`, `reset-password`, `delete-user`.
- The **only** path for provisioning users. Runs inside the container (`docker compose exec`).
- `create-user` and `reset-password` print a one-off password to stdout; the admin delivers it out-of-band.

### Crypto module

- Thin wrapper around argon2id (via `argon2-cffi`) and AES-GCM (via `cryptography`).
- Fixed argon2id parameters chosen once and committed.
- Responsible for generating `kdf_salt` and all nonces.
- Zeroes DEK buffers on session teardown where the language permits.

### CalDAV client layer

- Wraps the `caldav` library.
- For each outbound request, looks up the current session's DEK, decrypts the relevant `caldav_accounts.encrypted_password`, and uses the plaintext credential only for the duration of that HTTP call.
- Handles timeouts and retries.
- Never logs credentials or the DEK.

### Storage layer

- SQLAlchemy 2.x models for `users`, `caldav_accounts`, `calendars`, `user_settings`.
- SQLite in WAL mode on a named Docker volume.

### API layer

- FastAPI routers per resource: `auth`, `caldav_accounts`, `calendars`, `events`, `settings`, `ops` (`/health`, `/metrics`).
- Dependency injection resolves the current session and DEK; protected endpoints require an unrestricted session.

### Frontend

- Single Jinja2-rendered host page.
- Static assets: FullCalendar.js bundle plus a small vanilla-JS glue layer that calls the API via `fetch`.
- No build step beyond bundling FullCalendar's CSS/JS.

### Observability

- Prometheus middleware on FastAPI for `http_requests_total`.
- App-level metrics: `active_sessions`, `caldav_request_duration_seconds`, `caldav_request_errors_total`.
- `structlog` for JSON logs; level controlled by `LOG_LEVEL`.

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

### Edit event

```
browser ── PUT /events/{uid} ──► DEK-decrypt CalDAV creds ──► CalDAV PUT ──► return updated event
```

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

- **Reminders while logged out.** Reminders that require fetching fresh CalDAV state have no DEK available when the user is not logged in. A likely approach is a small DEK-encrypted reminder cache, maintained while the user is logged in, that the Service Worker reads for near-term notifications; open question what happens for reminders beyond the last session.
- **Single-user vs. multi-user deployments.** The design supports multiple users in one container; whether typical self-hosters prefer one-container-per-user (simpler backup, simpler reset semantics) is unresolved.
