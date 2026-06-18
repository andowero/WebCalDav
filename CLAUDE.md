# Project goals

Provide a self-hosted, lightweight web UI for viewing and editing events on user-owned CalDAV servers (e.g. Radicale). The app targets the gap left by abandoned projects like AgenDav and InfCloud, without requiring a heavy platform such as Nextcloud. Primary deployment is behind a reverse proxy at `calendar.zdeneknovak.one`.

# Project overview

Multi-user web application where each user links one or more CalDAV servers and picks which calendars from each to display. The calendar UI offers month, week, day, and agenda views. Events (VEVENT), tasks (VTODO), and journals (VJOURNAL) are read from and written directly to the CalDAV server with no local caching; journals are dated Markdown notes edited in a two-tab editor (raw-Markdown "Edit" + rendered read-only "Display"). UI theme is user-selectable (system/light/dark). The interface is internationalized; Czech translation is included and locale is auto-detected from the browser. An optional MCP server (at `/mcp`, toggled by `MCP_SERVER_ENABLED`) lets AI assistants read and write the same calendars/tasks/journals via per-user API tokens. Deployed as a single Docker container behind a reverse proxy.

# Design style guide

Minimal, utilitarian UI built around FullCalendar.js. Event color is taken per-calendar — from the CalDAV server's `calendar-color` property when available, otherwise a fallback blue, with user override. Broader visual guidelines will be added once the MVP UI exists.

# Product & UX guidelines

- Four calendar views: month, week, day, and agenda (infinitely scrolling).
- Tasks (VTODO): view, create, edit, complete, and set recurrence alongside calendar events.
- Journals (VJOURNAL): view, create, edit, and delete dated notes with a Markdown body (no recurrence/reminders); shown with a downward-triangle marker.
- First day of the week is a user setting.
- Timezone is a user setting; default from the browser.
- UI theme is a user setting: system (follows OS), light, or dark.
- Locale is auto-detected from the browser; Czech translation included; more languages can be added under `webcaldav/locales/`.
- All event and task attributes are editable; all-day and multi-day events supported.
- Events and tasks are clickable and editable in place.
- Desktop-first. Mobile browsers should work but are not the priority — native mobile apps already cover that use case.
- Browser notifications for event and task reminders on Firefox, Chrome, Opera, and Safari.

# Constraints and policies

- **No TLS in the app.** The reverse proxy terminates TLS.
- **No public signup.** Users and their initial one-off passwords are created by the server administrator via an admin CLI. The user is forced to change that password on first login before any other action.
- **Zero-knowledge at rest for CalDAV credentials.** Credentials are encrypted with a per-user key derived from the user's login password. The server cannot decrypt them without an active user session; a stolen database alone yields nothing.
- **No event caching.** Reads and writes go straight to the CalDAV server.
- **MCP API tokens are high-value.** A token can decrypt the user's CalDAV credentials. To preserve zero-knowledge-at-rest, the DEK and the token's authoritative mode/scope/expiry are sealed in an AES-GCM blob keyed by the token secret (only its SHA-256 is stored); plaintext token columns are display-only and must never be trusted for authorization. The MCP server is off by default. See `MCP.md`.
- **Observability required.** Expose `/health` and `/metrics` (Prometheus).
- **Structured logging** with levels DEBUG/INFO/WARNING/ERROR. Passwords and DEKs must never be logged.

# Repository etiquette

- Update files in `./docs` after major milestones or major additions to the project.
- When commiting changes, always update files in `./docs` (if necessary)
- When commiting changes, always check `CLAUDE.md` if it is still up to date
- Before commiting change, check if `README.md` is up to date with newest changes

# Often used commands

```sh
uv run pytest                    # run test suite
uv run pytest --cov              # run tests with coverage
uv run ruff check .              # lint
uv run mypy webcaldav/           # type check
```

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

- [MCP server](MCP.md) - Enabling the MCP server, API tokens, tool list, security model
- [Project spec](project_spec.md) - Full requirements, API specs, tech details
- [Architecture](docs/architecture.md) - System design and data flow
- [Changelog](docs/changelog.md) - Version history
- [Project status](docs/project_status.md) - Current progress
- Update files in the `./docs` folder after major milestones and major additions to the project.
