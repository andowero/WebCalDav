# Calendar sharing

WebCalDav can produce **share links** and **`.ics` downloads** so you can hand a
single event, a calendar period, or a slice of your agenda to someone else —
without giving them a login. A link opens a **navigation-locked** view of exactly
what you shared — the same calendar UI, editing modal, markdown rendering and
type markers as the normal app, just bounded to the shared window and shown in
**your** timezone/language/formats. You choose **read-only** (they can look and
download) or **read & write** (they can also add and edit within scope, including
recurring events).

## What you can share

| Scope | Where the share button is | The link opens… |
|-------|---------------------------|-----------------|
| **Single item** (event / task / journal) | the item's edit modal header (🔗) | that one item, read-only or editable |
| **Grid period** (month / week / day) | next to the calendar title (🔗) | that month/week/day, locked to the period |
| **Agenda slice** | next to the agenda title (🔗); pick a from/to range | just that date range, no scrolling outside |

For a grid or agenda share you select **which calendars** are included, mark
which are **writable** (read & write only), and pick a **default calendar** for
anything the recipient creates.

Every share modal also offers a **`.ics` download** — a standard iCalendar file
that imports into Google Calendar, Apple Calendar, Outlook, etc. A single `.ics`
holds many events, so a grid/agenda export is one file with everything in the
window. `.ics` is the only download format offered because it is the universal
interchange standard; the "other format" is the live link itself.

## Read-only vs read & write

- **Read-only** — the recipient sees the shared events/tasks/journals and can
  download the `.ics`. They cannot change anything.
- **Read & write** — additionally, the recipient can create new items (via the
  `+` button, clicking/dragging empty space) and edit/delete existing ones,
  **but only on the calendars you marked writable**. Recurring events that reach
  past the shared window are written in full; the view still only renders the
  occurrences inside the window.

## Expiry and revocation

When you create a link you choose an expiry: **1 day, 7 days, 30 days (default),
or never**. Manage your links in **Settings → Shares**: every active link is
listed with its scope, access level and expiry, and a **Revoke** button.
Revoking deletes the link immediately — the URL stops working at once.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `SHARING_ENABLED` | `true` | When `false`, new links cannot be created (the share buttons/section are inert); existing links can still be **listed and revoked**. |
| `PUBLIC_BASE_URL` | _(unset)_ | The external origin used to build links, e.g. `https://calendar.zdeneknovak.one`. When unset it is derived from the reverse proxy's `X-Forwarded-Proto` / `X-Forwarded-Host` headers (falling back to `Host`). Set it if those headers are unreliable. |

## Security model

A share link is **high-value** — treat it like a password. It can decrypt your
CalDAV credentials for the duration the server uses it, exactly like an MCP API
token.

- **The secret lives in the URL fragment** (`https://host/s/<id>#<secret>`). The
  share page's JavaScript reads it and sends it in the `X-Share-Secret` **header**
  — it never appears in the request line, so it stays out of WebCalDav's access
  logs, the reverse-proxy logs, and the `Referer` header. Browser history and
  bookmarks still retain the full URL, which is why links expire and can be
  revoked.
- **Zero-knowledge at rest is preserved.** The session DEK plus the
  authoritative kind / access mode / calendar scope / window / expiry are sealed
  in an AES-GCM blob keyed by a key derived from the secret. Only the
  `SHA-256(secret)` is stored for lookup. A stolen database **without** the
  secret cannot unseal anything; a leaked URL **without** the database row has no
  blob to unseal. Both are needed together.
- **The database mirror columns are display-only.** Mode, scope, expiry and the
  per-calendar writable flags are duplicated in plain columns purely to render
  the Settings list. Authorization always reads the sealed blob, so tampering
  with those rows cannot widen a link's access — it would only break it.
- **Expiry is enforced from the sealed blob**, not the column. **Writes are
  scope-checked** on every request: read-only links reject all writes, and a
  read & write link can only write to the calendars you marked writable (a
  single-item link only to that one item). Reads are clamped to the sealed
  window; the recipient cannot widen the range via request parameters.

Anyone who has the link has the access you granted — share it over a trusted
channel, prefer a short expiry for read & write links, and revoke links you no
longer need.

See also: [MCP server](MCP.md) (the same sealed-blob token design), the
[architecture notes](docs/architecture.md), and the
[project spec](project_spec.md).
