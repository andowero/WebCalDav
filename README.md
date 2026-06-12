# WebCalDav

A lightweight, self-hosted web UI for viewing and editing calendar events on your own CalDAV server (e.g. [Radicale](https://radicale.org/)). WebCalDav fills the gap left by abandoned projects like AgenDav and InfCloud — a plain web calendar for your CalDAV data, without pulling in a heavy platform such as Nextcloud. It ships as a single Docker container intended to run behind a reverse proxy.

## Features

- Month, week, and day views plus an infinitely scrolling agenda view, built on FullCalendar.
- Multiple CalDAV accounts per user; pick which calendars from each account to display.
- Per-calendar colors taken from the server's `calendar-color` property, with user override.
- All-day, multi-day, and recurring events; recurring events can be edited with "this event", "this and future", or "all events" scope.
- Event reminders (VALARM) with optional browser notifications, fired at each reminder and at event start (see [Browser notifications](#browser-notifications)).
- Per-user settings: timezone, first day of week, time and date format, default view, auto-logout.
- No event caching — every read and write goes straight to your CalDAV server.

> **Note:** FullCalendar and luxon are vendored into the container (`webcaldav/static/vendor/`) and served from the app itself — no third-party CDN, and the browser needs no internet access beyond your own server.

## Who is this for

Self-hosters who run their own CalDAV server and want a web calendar UI without adopting a whole groupware platform. WebCalDav is multi-user, but there is **no public signup** — an administrator creates each user from the CLI, and the user must change their one-off password on first login.

The app serves plain HTTP on port 8000 and does no TLS by design. **Run it behind a TLS-terminating reverse proxy** (nginx, Caddy, Traefik, …); don't expose the port directly to the internet.

## Running it

Build and start the container:

```sh
sudo docker compose up --build -d
```

Create a user (prints a one-off password to give to the user; they are forced to change it on first login):

```sh
sudo docker compose exec app python -m webcaldav.admin create-user --email email@example.com
```

Stop the container:

```sh
sudo docker compose down
```

Tear down **including the data volume** — this deletes all users, their settings, and stored CalDAV account credentials. Your calendar events are untouched; they live on the CalDAV server:

```sh
sudo docker compose down -v
```

## Configuring docker-compose.yml

The shipped compose file:

```yaml
services:
  app:
    build: .
    image: webcaldav:local
    ports:
      - "8000:8000"
    volumes:
      - data:/data
    environment:
      DATABASE_URL: sqlite+aiosqlite:////data/webcaldav.db
      LOG_LEVEL: INFO
      SESSION_IDLE_TIMEOUT: 3600
      BLOCK_PRIVATE_CALDAV_URLS: "true"
      LOGIN_RATE_LIMIT_ATTEMPTS: 5
      LOGIN_RATE_LIMIT_WINDOW_SECONDS: 300
      MIN_PASSWORD_LENGTH: 12
    restart: unless-stopped

volumes:
  data:
```

### Changing the exposed port

Change the host side of the port mapping (the left number). For example, to serve on host port 9000 and only on localhost (sensible when a reverse proxy on the same machine fronts the app):

```yaml
    ports:
      - "127.0.0.1:9000:8000"
```

### Using a local directory as the volume

By default the SQLite database lives at `/data/webcaldav.db` inside a named Docker volume. To keep it in a directory next to the compose file instead, replace the named volume with a bind mount and drop the top-level `volumes:` block:

```yaml
    volumes:
      - ./data:/data
```

### Environment variables

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:////data/webcaldav.db` | Location of the SQLite database. |
| `LOG_LEVEL` | `INFO` | Log verbosity for structured JSON logs: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `SESSION_IDLE_TIMEOUT` | `3600` | Seconds of inactivity before a login session expires. |
| `COOKIE_SECURE` | `true` | Set the `Secure` flag on the session cookie so browsers only send it over HTTPS. See below. |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | Max login attempts per IP within the rate-limit window. `0` disables login rate limiting. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Length of the sliding rate-limit window, in seconds. |
| `MIN_PASSWORD_LENGTH` | `12` | Minimum length for passwords users set on first login or when changing their password. |
| `ARGON2_TIME_COST` | `3` | Argon2id time cost for password key derivation. |
| `ARGON2_MEMORY_COST` | `131072` | Argon2id memory cost (KiB; default 128 MiB). |
| `ARGON2_PARALLELISM` | `1` | Argon2id parallelism factor. |
| `BLOCK_PRIVATE_CALDAV_URLS` | `false` | Reject CalDAV server URLs that resolve to private/loopback/link-local/metadata addresses, and hide raw connection errors. Shipped as `true` in the compose file. |
| `NOTIFICATION_HORIZON_DAYS` | `60` | How many days ahead the browser-notification scheduler loads events to fire reminder/start notifications for. Raise it for reminders further out (e.g. month-ahead birthdays). See [Browser notifications](#browser-notifications). |

The `ARGON2_*` parameters control how expensive it is to brute-force user passwords. The defaults are production-strength — don't weaken them on a real deployment (they exist as variables mainly so the test suite can run fast). Each user's password record stores the parameters it was created with, so raising the values later is safe: existing users keep logging in with their old parameters and pick up the stronger ones the next time they change their password.

### Login rate limiting

Each IP address gets at most `LOGIN_RATE_LIMIT_ATTEMPTS` login attempts per `LOGIN_RATE_LIMIT_WINDOW_SECONDS` sliding window; further attempts get HTTP 429 with a `Retry-After` header, and a successful login clears the counter. This blunts both password guessing and CPU-exhaustion attacks (every login attempt costs a full Argon2id hash). The client IP is taken from the rightmost `X-Forwarded-For` entry when the header is present — the one appended by your reverse proxy — so it works correctly behind the intended single-proxy setup. Counters are in memory and reset when the container restarts.

### Session cookie `Secure` flag

With `COOKIE_SECURE=true` (the default) browsers refuse to send the session cookie over plain HTTP, so it can't leak on a downgraded or stray `http://` request. Keep it on behind your TLS-terminating proxy. Browsers exempt `localhost`, so local development still works; set `COOKIE_SECURE=false` only if you access the app over plain HTTP on a non-localhost address (e.g. a LAN IP without TLS) — otherwise login will appear to succeed but the session won't stick.

### Blocking private CalDAV URLs (SSRF hardening)

By default (`false`) the server connects to whatever CalDAV URL a user enters. Because the request originates from the server, a user could point it at internal hosts the server can reach — `http://localhost`, a LAN IP, or a cloud metadata endpoint such as `169.254.169.254` — and connection-error messages get echoed back, which leaks whether those internal services exist.

Set `BLOCK_PRIVATE_CALDAV_URLS=true` to reject any CalDAV URL whose hostname resolves to a private, loopback, link-local, reserved, multicast, or unspecified address, and to replace detailed connection errors with a generic message. The shipped `docker-compose.yml` enables it.

**Caveat for self-hosters:** if your CalDAV server (e.g. Radicale) runs on a private/LAN address — a very common setup — enabling this will block adding it. In that case set `BLOCK_PRIVATE_CALDAV_URLS: "false"` in your compose file. The protection only matters when users you don't fully trust can add accounts and the server sits on a network with sensitive internal services.

## Browser notifications

WebCalDav can pop a desktop notification at each event's reminder (VALARM) **and** at each event's start time. They are **off by default**; turn them on per user under **Settings → Preferences → Browser notifications**. The first time you enable them the browser asks for notification permission — allow it. Each notification shows:

```
WebCalDav
<event name>
<event date/time in your date & time format>
```

and is handed to your operating system, so on Linux/macOS/Windows it lands in the system notification center.

**Supported browsers:** Firefox, Chrome, Opera, and Safari on macOS. They work while a WebCalDav tab is open, including when the tab is in the background.

### Important: notifications only fire while a tab is open

Notifications are scheduled **in your browser**, from events loaded while you are logged in. They fire only while a WebCalDav tab is open (it may be backgrounded). **If you close the browser, no notifications fire** — there is no server-side push.

This is a deliberate consequence of WebCalDav's [zero-knowledge design](#zero-knowledge-credential-storage): the server cannot read your calendar events without an active session, so it cannot push reminders when your browser is closed. Server-side push would require storing your reminder times and event titles on the server in the clear, which WebCalDav refuses to do. (On iOS, background web push needs an installed PWA; WebCalDav is desktop-first and does not target that.)

### Enabling notifications turns auto-logout off

Because the schedule has to be kept in sync with your calendar for as long as you want notifications, enabling notifications **disables automatic logout** for that user (the two settings are mutually exclusive, enforced on the server). Turn notifications back off to re-enable auto-logout.

### How far ahead notifications are scheduled

The scheduler loads events from now up to `NOTIFICATION_HORIZON_DAYS` (default **60**) ahead and refreshes them periodically, using a lightweight per-calendar change check so unchanged calendars aren't re-downloaded. If you keep reminders set more than ~2 months in advance (e.g. month-ahead birthday alerts that you want to be sure load early), raise `NOTIFICATION_HORIZON_DAYS` in `docker-compose.yml`.

## Updating the vendored frontend libraries

FullCalendar and luxon are not loaded from a CDN — they are committed under `webcaldav/static/vendor/` and served from the app itself. To move to newer versions, re-download the three files and rebuild the container. Find the latest versions on npm (FullCalendar and its luxon3 plugin share the same version number; luxon is versioned separately):

```sh
curl -s https://registry.npmjs.org/fullcalendar/latest | grep -o '"version":"[^"]*"'
curl -s https://registry.npmjs.org/luxon/latest | grep -o '"version":"[^"]*"'
```

Then overwrite the vendored files, substituting the versions (here `6.1.20` for FullCalendar / its plugin and `3.7.2` for luxon):

```sh
cd webcaldav/static/vendor
curl -fSL -o fullcalendar.min.js          https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.js
curl -fSL -o luxon.min.js                  https://cdn.jsdelivr.net/npm/luxon@3.7.2/build/global/luxon.min.js
curl -fSL -o fullcalendar-luxon3.min.js    https://cdn.jsdelivr.net/npm/@fullcalendar/luxon3@6.1.20/index.global.min.js
```

Notes:

- The FullCalendar v6 global bundle injects its own CSS — there is **no** separate stylesheet to download.
- Filenames are fixed; `index.html` references them by path, and the cache-busting `?v=` token is recomputed from the file contents on the next start, so browsers pick up the new bytes automatically.
- Commit the updated files and rebuild: `sudo docker compose up --build -d`. Then hard-reload the page once and confirm the calendar renders.

## User management (admin CLI)

All administration happens through the CLI inside the container; there is no admin web UI.

```sh
sudo docker compose exec app python -m webcaldav.admin create-user --email email@example.com
sudo docker compose exec app python -m webcaldav.admin list-users
sudo docker compose exec app python -m webcaldav.admin reset-password --email email@example.com
sudo docker compose exec app python -m webcaldav.admin delete-user --email email@example.com
```

- `create-user` — creates the user and prints a one-off password.
- `list-users` — lists all users and whether they still must change their password.
- `reset-password` — prints a new one-off password and **wipes the user's stored CalDAV credentials** (see below for why).
- `delete-user` — permanently deletes the user and all their data.

## Zero-knowledge credential storage

WebCalDav stores your CalDAV passwords encrypted such that the server cannot read them without you being logged in:

1. Your login password plus a per-user salt is run through Argon2id to derive a key-encryption key (KEK).
2. The KEK wraps a random per-user data-encryption key (DEK) using AES-GCM.
3. Your CalDAV account passwords are encrypted with the DEK.

The database holds only the wrapped DEK and ciphertexts — there is no master key on the server. A stolen database (or a curious server admin) yields nothing; the DEK can only be unwrapped while you have an active session, and it is held in memory only.

**The flip side: there is no password recovery.** If a user forgets their password, the stored CalDAV credentials are permanently undecryptable. The administrator runs:

```sh
sudo docker compose exec app python -m webcaldav.admin reset-password --email email@example.com
```

This issues a new one-off password, rotates the user's DEK, and deletes the now-useless encrypted CalDAV credentials. After logging in and setting a new password, the user re-enters their CalDAV accounts. Calendar events themselves are never at risk — they live on the CalDAV server, not in WebCalDav.

## Observability

- `GET /health` — returns `{"status": "ok"}` for liveness checks.
- `GET /metrics` — Prometheus metrics: HTTP request counts, active sessions, CalDAV request latency and error counters.

## More documentation

- [Project spec](project_spec.md) — full requirements, API surface, technical details.
- [Architecture](docs/architecture.md) — system design and data flows.
- [Changelog](docs/changelog.md) — version history.

## License

[MIT](LICENSE)
