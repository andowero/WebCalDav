"""MCP server exposing the user's calendars and tasks to AI assistants.

Mounted at ``/mcp`` (Streamable HTTP) only when ``MCP_SERVER_ENABLED`` is set.
Authentication is per-request via an ``Authorization: Bearer WebCalDav...`` token
(see :mod:`webcaldav.tokens`); a pure-ASGI middleware resolves the token, sets a
context var, and every tool reads it. All wire I/O is English and ISO 8601.
"""
import contextvars
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from .caldav_client import (
    create_event,
    create_task,
    delete_event,
    delete_task,
    fetch_events,
    fetch_tasks,
    set_task_status,
    update_event,
    update_task,
)
from .crypto import decrypt_bytes
from .db import get_session_factory
from .models import Calendar, CalDAVAccount
from .routers.events import (
    EventUpdate,
    RecurrenceRule,
    Reminder,
    _calendar_for,
    _parse_dt,
    _reminder_deltas,
    _resolve_span,
)
from .routers.tasks import TaskUpdate, _resolve_task_span
from .session import SessionEntry
from .tokens import TokenContext, resolve_token

logger = structlog.get_logger()

_RECUR_SCOPES = ("this", "thisfuture", "all")

# Shared documentation fragments appended to tool descriptions so the recurrence
# and reminder object shapes are explained inline (their fields also carry
# per-field descriptions in the generated JSON schema; see RecurrenceRule /
# Reminder in routers/events.py).
_RECUR_DOC = (
    " To repeat, pass a recurrence object: freq "
    "('daily'|'weekly'|'monthly'|'yearly'|'hourly'), interval (repeat every N "
    "units, default 1), and EITHER until (ISO date/datetime of the last, "
    "inclusive, occurrence) OR count (total number of occurrences) — never both. "
    "For freq='monthly' set monthly_mode='monthday' (same day-of-month as the "
    "start) or monthly_mode='weekday' with ordinal 1-4 (the Nth weekday) or -1 "
    "(the last weekday). Example: every 2 weeks, 10 times = "
    "{freq:'weekly', interval:2, count:10}."
)
_REMINDER_DOC = (
    " reminders is an array of alarms; each: value (int) + unit "
    "('minutes'|'hours'|'days'|'weeks'), direction 'before'|'after' (default "
    "'before'), anchor 'start'|'end'/'due' (default 'start'). For all_day items "
    "each reminder also needs time 'HH:MM' (the clock time it fires). Example: 15 "
    "minutes before start = {value:15, unit:'minutes'}."
)
# Update tools additionally describe the omit-vs-clear reminder semantics.
_REMINDER_DOC_UPDATE = (
    _REMINDER_DOC
    + " On update, omit reminders to keep the current alarms, or pass [] to remove "
    "them; any provided list fully replaces them."
)

# Set by the ASGI auth middleware for the duration of each /mcp request.
_current: contextvars.ContextVar[TokenContext | None] = contextvars.ContextVar(
    "mcp_token_ctx", default=None
)

# DNS-rebinding Host/Origin validation is disabled: WebCalDav runs behind a
# TLS-terminating reverse proxy that controls the Host header, and MCP auth is
# by bearer token (no ambient browser cookie), so the rebinding threat the check
# defends against does not apply. Left on, it would reject the deployment Host
# (e.g. calendar.zdeneknovak.one) outright.
#
# Keep the default streamable_http_path ("/mcp"): the wrapper app is mounted at
# the root (see build_mcp_app / app.py) so the "/mcp" path reaches it unstripped,
# giving a clean non-redirecting endpoint at exactly /mcp.
mcp = FastMCP(
    "WebCalDav",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


class ToolError(Exception):
    """Surfaced to the MCP client as a tool error."""


def _ctx() -> TokenContext:
    ctx = _current.get()
    if ctx is None:
        raise ToolError(
            "Not authenticated. Send an 'Authorization: Bearer WebCalDav...' header "
            "with a token minted in the WebCalDav settings panel."
        )
    return ctx


def _require_rw(ctx: TokenContext) -> None:
    if ctx.mode != "rw":
        raise ToolError(
            "This token is read-only (WebCalDavRO...). Use a read-write "
            "(WebCalDavRW...) token for this operation."
        )


def _entry(ctx: TokenContext) -> SessionEntry:
    """A SessionEntry the existing router helpers accept (they read user_id/dek)."""
    return SessionEntry(
        user_id=ctx.user_id, dek=ctx.dek, last_seen=datetime.now(UTC), restricted=False
    )


def _check_scope(ctx: TokenContext, calendar_id: int) -> None:
    if not ctx.all_calendars and calendar_id not in (ctx.calendar_ids or []):
        raise ToolError(f"This token has no access to calendar {calendar_id}.")


async def _scoped_calendars(ctx: TokenContext, db: Any) -> list[tuple[Calendar, CalDAVAccount]]:
    """Enabled calendars visible to the token (all, or the scoped subset)."""
    rows = (
        await db.execute(
            select(Calendar, CalDAVAccount)
            .join(CalDAVAccount, Calendar.caldav_account_id == CalDAVAccount.id)
            .where(
                CalDAVAccount.user_id == ctx.user_id,
                Calendar.enabled == True,  # noqa: E712
            )
        )
    ).all()
    out = []
    for cal, account in rows:
        if ctx.all_calendars or cal.id in (ctx.calendar_ids or []):
            out.append((cal, account))
    return out


def _password(account: CalDAVAccount, ctx: TokenContext) -> str:
    return decrypt_bytes(account.encrypted_password, account.nonce, ctx.dek).decode()


def _mcp_event(it: dict[str, Any]) -> dict[str, Any]:
    """Expose an all-day EVENT's end as the inclusive last day. iCal DTEND is
    exclusive (a single-day all-day event ends the next day), which the web UI
    handles itself but would mislead an assistant into reading an extra day. A
    single-day all-day event then has end == start. Timed events and tasks (whose
    all-day DUE is the deadline day itself) are returned unchanged. This is the
    inverse of _resolve_span, so an inclusive end fed back to update_event is
    interpreted correctly."""
    if it.get("allDay") and it.get("end") and not it.get("extendedProps", {}).get("isTask"):
        try:
            d = date.fromisoformat(str(it["end"])[:10]) - timedelta(days=1)
            return {**it, "end": d.isoformat()}
        except ValueError:
            pass
    return it


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "List calendar events and/or tasks between two instants (agenda style). "
        "item_type is 'events', 'tasks', or 'both'. time_min/time_max are ISO 8601 "
        "datetimes; if omitted, defaults to now through 30 days ahead. Optionally "
        "restrict to specific calendar_ids. Returns a flat list of items: each has "
        "'id' (the uid to pass to other tools), title, start, end/due, allDay, and "
        "an extendedProps object with calendarId (the calendar_id other tools "
        "need), completed (tasks), and, for a recurring occurrence, recurrenceId "
        "(use as recurrence_id with scope='this'/'thisfuture'). For all-day events "
        "end is the inclusive last day (a single-day all-day event has end == "
        "start)."
    )
)
async def list_items(
    item_type: Literal["events", "tasks", "both"] = "both",
    time_min: str | None = None,
    time_max: str | None = None,
    calendar_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    ctx = _ctx()
    from_dt = _parse_dt(time_min) or datetime.now(UTC)
    to_dt = _parse_dt(time_max) or (datetime.now(UTC).replace(microsecond=0))
    if _parse_dt(time_max) is None:
        to_dt = from_dt + timedelta(days=30)

    async with get_session_factory()() as db:
        cals = await _scoped_calendars(ctx, db)
        if calendar_ids is not None:
            wanted = set(calendar_ids)
            cals = [(c, a) for c, a in cals if c.id in wanted]

        results: list[dict[str, Any]] = []
        for cal, account in cals:
            pw = _password(account, ctx)
            if item_type in ("events", "both"):
                try:
                    results.extend(
                        _mcp_event(e)
                        for e in await fetch_events(
                            account_url=account.url,
                            username=account.username,
                            password=pw,
                            calendar_url=cal.caldav_id,
                            from_dt=from_dt,
                            to_dt=to_dt,
                            color=cal.color,
                            calendar_id=cal.id,
                        )
                    )
                except Exception as e:
                    logger.warning("mcp_list_events_failed", calendar_id=cal.id, error=repr(e))
            if item_type in ("tasks", "both"):
                try:
                    results.extend(
                        await fetch_tasks(
                            account_url=account.url,
                            username=account.username,
                            password=pw,
                            calendar_url=cal.caldav_id,
                            from_dt=from_dt,
                            to_dt=to_dt,
                            color=cal.color,
                            calendar_id=cal.id,
                        )
                    )
                except Exception as e:
                    logger.warning("mcp_list_tasks_failed", calendar_id=cal.id, error=repr(e))
        return results


@mcp.tool(
    description=(
        "Get the full detail of one event or task by uid and calendar_id: "
        "description, location, recurrence rule, reminders, priority, status, and "
        "raw start/end/due. item_type is 'event' or 'task'. recurrence and "
        "reminders come back under extendedProps in the same shape the create/"
        "update tools accept."
    )
)
async def get_item_details(
    uid: str,
    calendar_id: int,
    item_type: Literal["event", "task"],
) -> dict[str, Any]:
    ctx = _ctx()
    _check_scope(ctx, calendar_id)
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
        # Wide window so a single recurring master/override is captured.
        from_dt = datetime.now(UTC) - timedelta(days=3650)
        to_dt = datetime.now(UTC) + timedelta(days=3650)
        fetch = fetch_events if item_type == "event" else fetch_tasks
        items = await fetch(
            account_url=account.url,
            username=account.username,
            password=pw,
            calendar_url=cal.caldav_id,
            from_dt=from_dt,
            to_dt=to_dt,
            color=cal.color,
            calendar_id=cal.id,
        )
    for it in items:
        if it.get("id") == uid:
            return _mcp_event(it) if item_type == "event" else it
    raise ToolError(f"{item_type} {uid} not found in calendar {calendar_id}.")


@mcp.tool(
    description=(
        "List the calendars this token can read/write. Returns each calendar's "
        "calendar_id (pass to other tools), name, color, is_default (the calendar "
        "new items default to), and account_url. A scoped token sees only its "
        "calendars; only enabled calendars are returned."
    )
)
async def list_calendars() -> list[dict[str, Any]]:
    ctx = _ctx()
    async with get_session_factory()() as db:
        cals = await _scoped_calendars(ctx, db)
    return [
        {
            "calendar_id": cal.id,
            "name": cal.display_name,
            "color": cal.color,
            "is_default": cal.is_default,
            "account_url": account.url,
        }
        for cal, account in cals
    ]


# --------------------------------------------------------------------------- #
# Write tools — events
# --------------------------------------------------------------------------- #
async def _create(ctx: TokenContext, body: EventUpdate | TaskUpdate, is_task: bool) -> dict[str, Any]:
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(body.calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
    uid = f"{uuid.uuid4()}@webcaldav"
    rrule = body.recurrence.model_dump() if body.recurrence else None
    reminders = _reminder_deltas(body.reminders, body.all_day)
    if is_task:
        assert isinstance(body, TaskUpdate)
        start, due = _resolve_task_span(body)
        await create_task(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, title=body.title, start=start, due=due,
            location=body.location, description=body.description, rrule=rrule,
            reminders=reminders, priority=body.priority,
        )
    else:
        assert isinstance(body, EventUpdate)
        start, end = _resolve_span(body)
        await create_event(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, title=body.title, all_day=body.all_day,
            start=start, end=end, location=body.location, description=body.description,
            rrule=rrule, reminders=reminders,
        )
    return {"status": "ok", "id": uid}


@mcp.tool(
    name="create_event",
    description=(
        "Create a calendar event. For a timed event pass ISO 8601 start and end "
        "plus timezone (IANA name, e.g. 'Europe/Prague'); for an all-day event set "
        "all_day=true and pass dates (YYYY-MM-DD), where end is the inclusive last "
        "day. calendar_id comes from list_items (extendedProps.calendarId)."
        + _RECUR_DOC + _REMINDER_DOC + " Requires a read-write token."
    )
)
async def create_event_tool(
    calendar_id: int,
    title: str,
    start: str,
    end: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    timezone: str | None = None,
    recurrence: RecurrenceRule | None = None,
    reminders: list[Reminder] | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    body = EventUpdate(
        calendar_id=calendar_id, title=title, start=start, end=end, all_day=all_day,
        location=location, description=description, timezone=timezone,
        recurrence=recurrence, reminders=reminders,
    )
    try:
        return await _create(ctx, body, is_task=False)
    except Exception as e:
        raise ToolError(f"Failed to create event: {e}")


@mcp.tool(
    name="create_task",
    description=(
        "Create a task (VTODO). start and due are both optional ISO 8601 values — a "
        "task may have neither (undated), one, or both; for an all-day task set "
        "all_day=true and pass dates (YYYY-MM-DD). priority is 0-9 (0 = none). "
        "calendar_id comes from list_items (extendedProps.calendarId)."
        + _RECUR_DOC + _REMINDER_DOC + " Requires a read-write token."
    )
)
async def create_task_tool(
    calendar_id: int,
    title: str,
    start: str | None = None,
    due: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    timezone: str | None = None,
    recurrence: RecurrenceRule | None = None,
    reminders: list[Reminder] | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    body = TaskUpdate(
        calendar_id=calendar_id, title=title, start=start, due=due, all_day=all_day,
        location=location, description=description, priority=priority, timezone=timezone,
        recurrence=recurrence, reminders=reminders,
    )
    try:
        return await _create(ctx, body, is_task=True)
    except Exception as e:
        raise ToolError(f"Failed to create task: {e}")


@mcp.tool(
    name="update_event",
    description=(
        "Update an event by uid (from list_items). Pass the full desired field set "
        "— provided fields replace the current ones. scope controls recurring "
        "series: 'this' (only the occurrence at recurrence_id), 'thisfuture' (it "
        "and later), or 'all' (whole series; the default, also for non-recurring). "
        "recurrence_id is the ISO start of the pivot occurrence "
        "(extendedProps.recurrenceId or rawStart). A recurrence rule applies only "
        "with scope 'all' or 'thisfuture'."
        + _RECUR_DOC + _REMINDER_DOC_UPDATE + " Requires a read-write token."
    )
)
async def update_event_tool(
    uid: str,
    calendar_id: int,
    title: str,
    start: str,
    end: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    timezone: str | None = None,
    scope: Literal["this", "thisfuture", "all"] = "all",
    recurrence_id: str | None = None,
    recurrence: RecurrenceRule | None = None,
    reminders: list[Reminder] | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    body = EventUpdate(
        calendar_id=calendar_id, title=title, start=start, end=end, all_day=all_day,
        location=location, description=description, timezone=timezone, scope=scope,
        recurrence_id=recurrence_id, recurrence=recurrence, reminders=reminders,
    )
    rrule = body.recurrence.model_dump() if body.recurrence and scope in ("all", "thisfuture") else None
    start_v, end_v = _resolve_span(body)
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
    try:
        await update_event(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, title=body.title, all_day=body.all_day,
            start=start_v, end=end_v, location=body.location, description=body.description,
            scope=scope, recurrence_id=recurrence_id, rrule=rrule,
            reminders=_reminder_deltas(body.reminders, body.all_day),
        )
    except Exception as e:
        raise ToolError(f"Failed to update event: {e}")
    return {"status": "ok"}


@mcp.tool(
    name="update_task",
    description=(
        "Update a task by uid (from list_items). Pass the full desired field set — "
        "provided fields replace the current ones. scope behaves like update_event "
        "('this' / 'thisfuture' / 'all', default 'all'); recurrence_id is the ISO "
        "start of the pivot occurrence. start/due are optional ISO 8601 values; "
        "priority is 0-9. A recurrence rule applies only with scope 'all' or "
        "'thisfuture'."
        + _RECUR_DOC + _REMINDER_DOC_UPDATE + " Requires a read-write token."
    )
)
async def update_task_tool(
    uid: str,
    calendar_id: int,
    title: str,
    start: str | None = None,
    due: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    timezone: str | None = None,
    scope: Literal["this", "thisfuture", "all"] = "all",
    recurrence_id: str | None = None,
    recurrence: RecurrenceRule | None = None,
    reminders: list[Reminder] | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    body = TaskUpdate(
        calendar_id=calendar_id, title=title, start=start, due=due, all_day=all_day,
        location=location, description=description, priority=priority, timezone=timezone,
        scope=scope, recurrence_id=recurrence_id, recurrence=recurrence, reminders=reminders,
    )
    rrule = body.recurrence.model_dump() if body.recurrence and scope in ("all", "thisfuture") else None
    start_v, due_v = _resolve_task_span(body)
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
    try:
        await update_task(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, title=body.title, start=start_v, due=due_v,
            location=body.location, description=body.description, scope=scope,
            recurrence_id=recurrence_id, rrule=rrule,
            reminders=_reminder_deltas(body.reminders, body.all_day), priority=body.priority,
        )
    except Exception as e:
        raise ToolError(f"Failed to update task: {e}")
    return {"status": "ok"}


@mcp.tool(
    name="set_task_status",
    description=(
        "Mark a task done or undone. Set completed=true to complete, false to "
        "reopen. For a recurring task, pass recurrence_id (ISO start of the "
        "occurrence) to toggle just that occurrence. Requires a read-write token."
    )
)
async def set_task_done(
    uid: str,
    calendar_id: int,
    completed: bool,
    recurrence_id: str | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
    try:
        await set_task_status(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, completed=completed,
            recurrence_id=recurrence_id,
        )
    except Exception as e:
        raise ToolError(f"Failed to set task status: {e}")
    return {"status": "ok"}


@mcp.tool(
    name="delete_event",
    description=(
        "Delete an event by uid. scope: 'this' deletes only the occurrence at "
        "recurrence_id, 'thisfuture' deletes it and all later occurrences, 'all' "
        "deletes the whole event/series (default). Requires a read-write token."
    )
)
async def delete_event_tool(
    uid: str,
    calendar_id: int,
    scope: Literal["this", "thisfuture", "all"] = "all",
    recurrence_id: str | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
    try:
        await delete_event(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, scope=scope, recurrence_id=recurrence_id,
        )
    except Exception as e:
        raise ToolError(f"Failed to delete event: {e}")
    return {"status": "ok"}


@mcp.tool(
    name="delete_task",
    description=(
        "Delete a task by uid. scope behaves like delete_event ('this' / "
        "'thisfuture' / 'all', default 'all'). Requires a read-write token."
    )
)
async def delete_task_tool(
    uid: str,
    calendar_id: int,
    scope: Literal["this", "thisfuture", "all"] = "all",
    recurrence_id: str | None = None,
) -> dict[str, Any]:
    ctx = _ctx()
    _require_rw(ctx)
    _check_scope(ctx, calendar_id)
    async with get_session_factory()() as db:
        cal, account = await _calendar_for(calendar_id, _entry(ctx), db)
        pw = _password(account, ctx)
    try:
        await delete_task(
            account_url=account.url, username=account.username, password=pw,
            calendar_url=cal.caldav_id, uid=uid, scope=scope, recurrence_id=recurrence_id,
        )
    except Exception as e:
        raise ToolError(f"Failed to delete task: {e}")
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# ASGI auth middleware
# --------------------------------------------------------------------------- #
class TokenAuthMiddleware:
    """Pure-ASGI wrapper that resolves the bearer token into a context var for
    the duration of each /mcp request. Invalid/absent tokens leave the var unset;
    tools then raise an authentication error."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw = headers.get(b"authorization", b"").decode("latin-1")
        ctx: TokenContext | None = None
        if raw.lower().startswith("bearer "):
            token = raw[7:].strip()
            try:
                async with get_session_factory()() as db:
                    ctx = await resolve_token(token, db)
            except Exception:
                logger.warning("mcp_token_resolve_failed", exc_info=True)
                ctx = None
        reset = _current.set(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(reset)


def build_mcp_app() -> Any:
    """The Streamable-HTTP ASGI app to mount at /mcp, wrapped with auth."""
    return TokenAuthMiddleware(mcp.streamable_http_app())
