# MCP server

WebCalDav can expose your calendars and tasks to AI assistants over the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP). Once enabled,
an assistant with one of your API tokens can list, read, create, edit, complete,
and delete events and tasks on your CalDAV calendars — the same operations the
web UI performs, driven by natural language.

The server speaks **Streamable HTTP** at the **`/mcp`** route. All MCP input and
output is **English** and uses **ISO 8601** dates/times regardless of your UI
language.

## Enabling it

The MCP server is **off by default**. Turn it on with an environment variable:

```sh
MCP_SERVER_ENABLED=true
```

(For Docker, add it under `environment:` in `docker-compose.yml`.)

When it is **off**:

- `/mcp` is not mounted (requests 404).
- You **cannot create** new API tokens — the create form in Settings is greyed
  out.
- You **can still list and revoke** existing tokens, so you can clean up after
  turning the server off.

## Security model — read this

**An API token can decrypt your stored CalDAV credentials.** It is a
high-value secret; treat it exactly like a password.

WebCalDav is normally *zero-knowledge at rest*: your CalDAV passwords are
encrypted with a key (the DEK) derived from your login password, so a stolen
database alone reveals nothing. An API token deliberately punches a hole in
that: so an assistant can act without your login password present, the DEK is
sealed inside the token.

The design keeps the at-rest guarantee intact:

- The token's plaintext (`WebCalDav…`) is shown to you **once, at creation, and
  never stored**. The database keeps only a SHA-256 of it (for lookup) and an
  AES-GCM blob.
- That blob — holding the DEK **and** the token's mode/scope/expiry — is
  encrypted with a key derived from the token secret itself. Without the token
  plaintext, a stolen database still reveals nothing.
- Because the scope and mode are sealed in the authenticated blob (not just
  stored in plain columns), **editing the database cannot widen a token's access
  or flip it to read-write** — tampering only breaks the token.

If a token is exposed, **revoke it** in Settings → API Tokens. Changing your
login password does **not** invalidate tokens (the DEK is unchanged); an
administrator password **reset** does (it rotates the DEK and deletes tokens
along with your stored CalDAV accounts).

## Creating a token

In the web UI: **Settings → API Tokens (MCP) → Create token**. Choose:

- **Name** — a label to recognize it later.
- **Access** — **Read-only** or **Read & write**. The mode is visible in the
  token text: read-only tokens start with `WebCalDavRO`, read-write with
  `WebCalDavRW`. Read-only tokens are rejected by every mutating tool.
- **Calendars** — *all calendars* (unscoped; **includes calendars you add
  later**) or a specific subset (**scoped**; only the calendars you tick, never
  ones added afterward).
- **Expires** *(optional)* — a date after which the token stops working. Leave
  empty for no expiry.

Copy the token immediately — it will not be shown again.

## Connecting a client

Point your MCP client at the Streamable-HTTP endpoint and send the token as a
bearer credential:

```
URL:     https://your-webcaldav-host/mcp
Header:  Authorization: Bearer WebCalDavRW…
```

Example MCP client config (Claude Desktop / similar, via an HTTP transport):

```json
{
  "mcpServers": {
    "webcaldav": {
      "url": "https://your-webcaldav-host/mcp",
      "headers": { "Authorization": "Bearer WebCalDavRW…" }
    }
  }
}
```

## Tools

All datetimes are ISO 8601. `calendar_id` values come from `list_items`
(`calendarId` in each item's `extendedProps`). For recurring items, `scope` is
`this` (only the occurrence at `recurrence_id`), `thisfuture` (it and all later
occurrences), or `all` (the whole series; the default). Mutating tools require a
read-write (`WebCalDavRW…`) token.

| Tool | Access | Purpose |
|------|--------|---------|
| `list_calendars` | read | List the calendars the token can access (id, name, color, default, account). Use the returned `calendar_id` with the other tools. |
| `list_items` | read | List events and/or tasks between two instants (`item_type` = `events`/`tasks`/`both`). Optional `time_min`/`time_max` (default: now → +30 days) and `calendar_ids`. |
| `get_item_details` | read | Full detail of one event/task: description, location, recurrence, reminders, priority, status, raw start/end/due. |
| `create_event` | write | Create a calendar event (timed or all-day), optionally recurring, with reminders. |
| `create_task` | write | Create a task (VTODO) with optional start/due, priority (0–9), recurrence, reminders. |
| `update_event` | write | Edit an event by `uid`; `scope` selects which occurrences of a recurring series. |
| `update_task` | write | Edit a task by `uid`; same `scope` semantics. |
| `set_task_status` | write | Mark a task done/undone (`completed` true/false); `recurrence_id` toggles a single occurrence. |
| `delete_event` | write | Delete an event by `uid`; `scope` selects single occurrence / future / whole series. |
| `delete_task` | write | Delete a task by `uid`; same `scope` semantics. |

A token scoped to specific calendars cannot see or modify items in any other
calendar; out-of-scope `calendar_id` values are rejected.

### Recurrence and reminders

The `create_*` and `update_*` tools accept two structured objects (also described
per-field in each tool's input schema):

- **`recurrence`** — `{ "freq": "daily"|"weekly"|"monthly"|"yearly"|"hourly",
  "interval": <int, default 1>, and EITHER "until": <ISO date/datetime, inclusive>
  OR "count": <int> }`. For `"freq": "monthly"`, add `"monthly_mode": "monthday"`
  (same day-of-month as the start) or `"monthly_mode": "weekday"` with
  `"ordinal": 1..4` (the Nth weekday) or `-1` (the last weekday). Example —
  every other week, 10 times: `{ "freq": "weekly", "interval": 2, "count": 10 }`.
- **`reminders`** — an array of alarms, each `{ "value": <int>, "unit":
  "minutes"|"hours"|"days"|"weeks", "direction": "before"|"after" (default
  "before"), "anchor": "start"|"end" (default "start") }`. For all-day items each
  reminder also needs `"time": "HH:MM"` (the clock time it fires). Example —
  15 minutes before start: `{ "value": 15, "unit": "minutes" }`. On **update**,
  omit `reminders` to keep the existing alarms, or pass `[]` to clear them.

For recurring items, `scope` (`this` / `thisfuture` / `all`) plus `recurrence_id`
(the ISO start of the target occurrence, returned as `extendedProps.recurrenceId`
by `list_items`) select which occurrences an edit or delete touches.
