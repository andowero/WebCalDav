# Project goals

Provide a self-hosted, lightweight web UI for viewing and editing events on user-owned CalDAV servers (e.g. Radicale). The app targets the gap left by abandoned projects like AgenDav and InfCloud, without requiring a heavy platform such as Nextcloud. Primary deployment is behind a reverse proxy at `calendar.zdeneknovak.one`.

# Project overview

Multi-user web application where each user links one or more CalDAV servers and picks which calendars from each to display. The calendar UI offers month, week, and day views. Events are read from and written directly to the CalDAV server with no local caching. Deployed as a single Docker container behind a reverse proxy.

# Design style guide

Minimal, utilitarian UI built around FullCalendar.js. Event color is taken per-calendar — from the CalDAV server's `calendar-color` property when available, otherwise a fallback blue, with user override. Broader visual guidelines will be added once the MVP UI exists.

# Product & UX guidelines

- Three calendar views: month, week, day.
- First day of the week is a user setting.
- Timezone is a user setting; default from the browser.
- All event attributes are editable; all-day and multi-day events supported.
- Events are clickable and editable in place.
- Desktop-first. Mobile browsers should work but are not the priority — native mobile apps already cover that use case.
- Browser notifications for reminders on Firefox, Chrome, Opera, and Safari.

# Constraints and policies

- **No TLS in the app.** The reverse proxy terminates TLS.
- **No public signup.** Users and their initial one-off passwords are created by the server administrator via an admin CLI. The user is forced to change that password on first login before any other action.
- **Zero-knowledge at rest for CalDAV credentials.** Credentials are encrypted with a per-user key derived from the user's login password. The server cannot decrypt them without an active user session; a stolen database alone yields nothing.
- **No event caching.** Reads and writes go straight to the CalDAV server.
- **Observability required.** Expose `/health` and `/metrics` (Prometheus).
- **Structured logging** with levels DEBUG/INFO/WARNING/ERROR. Passwords and DEKs must never be logged.

# Repository etiquette

- Update files in `./docs` after major milestones or major additions to the project.
- When commiting changes, always update files in `./docs` (if necessary)

# Often used commands

TBD — populated once the app is scaffolded. Expected: `uv run pytest` (test suite), `uv run ruff check`, `uv run mypy`.

# Testing instructions

The app is tested primarily by calling the HTTP API directly with an in-process ASGI client — no running container or live network needed. Layers:

- **Crypto unit tests** — KEK/DEK/AES-GCM roundtrips, `password_verifier`, nonce uniqueness, DEK rotation on reset.
- **API tests** — FastAPI `TestClient` over a temp SQLite DB: first-login restricted→unrestricted flow, 401/403 auth boundaries, session lifecycle, `caldav-accounts`/`calendars`/`settings` CRUD.
- **CalDAV layer** — a fake client injected via `app.dependency_overrides` for fast `/events` tests, plus an in-process `radicale` instance for real protocol integration tests.
- **Admin CLI** — entrypoint functions called directly (no subprocess).

Rules for keeping the suite testable:

- Inject the CalDAV client and session store as dependencies so tests can override them.
- Use weak argon2id parameters under test (set via config/env) — real parameters make the suite crawl.
- Point each test at a throwaway DB via `DATABASE_URL`.
- Use an injectable clock for idle-timeout tests rather than sleeping.
- Share one provisioning function between the admin CLI and test fixtures.

No automated browser/E2E tests (no Playwright). FullCalendar, the Service Worker, and notifications are verified manually against the supported browsers.

# Documentation

- [Project spec](project_spec.md) - Full requirements, API specs, tech details
- [Architecture](docs/architecture.md) - System design and data flow
- [Changelog](docs/changelog.md) - Version history
- [Project status](docs/project_status.md) - Current progress
- Update files in the `./docs` folder after major milestones and major additions to the project.
- Use the /update-docs-and-commit slash command when making git commits.
