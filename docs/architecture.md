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
- Handles timeouts and retries.
- Never logs credentials or the DEK.

### Storage layer

- SQLAlchemy 2.x models for `users`, `caldav_accounts`, `calendars`, `user_settings`.
- `calendars.is_default` marks the per-user calendar pre-selected for new events
  (at most one, enforced at the API layer).
- SQLite in WAL mode on a named Docker volume.

### API layer

- FastAPI routers per resource: `auth`, `caldav_accounts`, `calendars`, `events`, `settings`, `ops` (`/health`, `/metrics`).
- Dependency injection resolves the current session and DEK; protected endpoints require an unrestricted session.

### Frontend

- Single Jinja2-rendered host page.
- Static assets: FullCalendar.js bundle (+ luxon and the `@fullcalendar/luxon3`
  plugin for named-IANA-timezone rendering) plus a small vanilla-JS glue layer
  that calls the API via `fetch`.
- An event modal opens on event click for viewing/editing, populated from the
  event's `extendedProps` (`description`, `location`, `recurrence`,
  `recurrenceRule`, `reminders`, `rawStart`/`rawEnd`); dates are formatted
  client-side per the timezone + time format settings. Recurrence is fully
  editable via a recurrence editor (frequency, interval, monthly by
  day-of-month or Nth/last weekday, end-by-date / end-after-N) with a live
  last-occurrence preview.
- Reminders are editable rows in the modal ("+" to add, × to delete; no
  in-place edit). Timed events use value + minutes/hours/days/weeks before;
  all-day events use days/weeks before at a time of day (entered via the app's
  own hh:mm + AM/PM fields so the 12h/24h `time_format` setting applies, and
  rendered per that setting in row text). The save request
  carries `reminders: [{value, unit, time?}]` (absent = don't touch alarms,
  `[]` = clear); the server maps each row to one `ACTION:DISPLAY` VALARM
  duration trigger and returns the same structured shape in
  `extendedProps.reminders`. Alarms outside that model (EMAIL, absolute
  triggers, `RELATED=END`, after-event) are preserved untouched and rendered
  read-only.
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
- No build step beyond bundling FullCalendar's CSS/JS.

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
