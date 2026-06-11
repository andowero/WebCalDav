# WebCalDav

A lightweight, self-hosted web UI for viewing and editing calendar events on your own CalDAV server (e.g. [Radicale](https://radicale.org/)). WebCalDav fills the gap left by abandoned projects like AgenDav and InfCloud — a plain web calendar for your CalDAV data, without pulling in a heavy platform such as Nextcloud. It ships as a single Docker container intended to run behind a reverse proxy.

## Features

- Month, week, and day views plus an infinitely scrolling agenda view, built on FullCalendar.
- Multiple CalDAV accounts per user; pick which calendars from each account to display.
- Per-calendar colors taken from the server's `calendar-color` property, with user override.
- All-day, multi-day, and recurring events; recurring events can be edited with "this event", "this and future", or "all events" scope.
- Event reminders (VALARM) with browser notifications.
- Per-user settings: timezone, first day of week, time and date format, default view, auto-logout.
- No event caching — every read and write goes straight to your CalDAV server.

> **Note:** the frontend loads FullCalendar and luxon from the jsDelivr CDN, so the *browser* needs internet access. The server itself only talks to your CalDAV server.

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
| `ARGON2_TIME_COST` | `3` | Argon2id time cost for password key derivation. |
| `ARGON2_MEMORY_COST` | `65536` | Argon2id memory cost (KiB). |
| `ARGON2_PARALLELISM` | `1` | Argon2id parallelism factor. |

The `ARGON2_*` parameters control how expensive it is to brute-force user passwords. The defaults are production-strength — don't weaken them on a real deployment (they exist as variables mainly so the test suite can run fast).

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
