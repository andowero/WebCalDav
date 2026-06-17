"""In-process radicale integration tests for the VTODO (task) client layer.

Mirrors test_caldav.py but for tasks: create/fetch/update/delete, completion
toggling (incl. the recurring RFC-advance override), undated tasks, and
recurrence. Reuses the same ephemeral-radicale pattern.
"""
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from webcaldav.caldav_client import (
    EventNotFoundError,
    create_task,
    delete_task,
    fetch_tasks,
    set_task_status,
    update_task,
)

USER = "alice"
PASSWORD = "secret"


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):  # silence per-request logging
        pass


@pytest.fixture(scope="module")
def radicale_base():
    pytest.importorskip("radicale")
    from radicale import Application
    from radicale.config import load

    tmp = tempfile.mkdtemp()
    cfg = load(())
    cfg.update(
        {
            "storage": {"filesystem_folder": tmp},
            "auth": {"type": "none"},
            "rights": {"type": "authenticated"},
        },
        "test",
    )
    httpd = make_server("127.0.0.1", 0, Application(cfg), handler_class=_QuietHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def task_calendar(radicale_base):
    """A throwaway calendar for tasks, torn down per test."""
    import caldav

    with caldav.DAVClient(url=radicale_base, username=USER, password=PASSWORD) as client:
        cal = client.principal().make_calendar(name="Tasks")
        url = str(cal.url)
        try:
            yield radicale_base, url
        finally:
            cal.delete()


_FROM = datetime(2026, 6, 1, tzinfo=timezone.utc)
_TO = datetime(2026, 7, 31, tzinfo=timezone.utc)


async def _fetch(base, url):
    return await fetch_tasks(base, USER, PASSWORD, url, _FROM, _TO, "#abcdef", 3)


def _raw(base, url, uid):
    import caldav

    with caldav.DAVClient(url=base, username=USER, password=PASSWORD) as client:
        cal = caldav.Calendar(client=client, url=url)
        return cal.todo_by_uid(uid).data


async def test_create_and_fetch_dated_task(task_calendar):
    base, url = task_calendar
    due = datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc)
    await create_task(
        base, USER, PASSWORD, url, "t-dated@webcaldav",
        title="Submit report", start=None, due=due,
        location="Desk", description="Quarterly",
    )
    tasks = await _fetch(base, url)
    t = {x["id"]: x for x in tasks}["t-dated@webcaldav"]
    assert t["title"] == "Submit report"
    assert t["color"] == "#abcdef"
    assert t["start"].startswith("2026-06-15T17:00:00")
    p = t["extendedProps"]
    assert p["isTask"] is True
    assert p["completed"] is False
    assert p["undated"] is False
    assert p["location"] == "Desk"
    assert p["rawDue"].startswith("2026-06-15T17:00:00")


async def test_create_undated_task(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-undated@webcaldav",
        title="Someday", start=None, due=None, location=None, description=None,
    )
    tasks = await _fetch(base, url)
    t = {x["id"]: x for x in tasks}["t-undated@webcaldav"]
    assert t["title"] == "Someday"
    assert t["extendedProps"]["undated"] is True
    assert "start" not in t


async def test_create_allday_task(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-allday@webcaldav",
        title="Pay rent", start=None, due=date(2026, 6, 20),
        location=None, description=None,
    )
    tasks = await _fetch(base, url)
    t = {x["id"]: x for x in tasks}["t-allday@webcaldav"]
    assert t["allDay"] is True
    assert t["start"] == "2026-06-20"


async def test_update_task_fields(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-edit@webcaldav",
        title="Old", start=None, due=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
    )
    await update_task(
        base, USER, PASSWORD, url, "t-edit@webcaldav",
        title="New", start=None, due=datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
        location="Home", description="changed", priority=5,
    )
    t = {x["id"]: x for x in await _fetch(base, url)}["t-edit@webcaldav"]
    assert t["title"] == "New"
    assert t["start"].startswith("2026-06-12T12:00:00")
    assert t["extendedProps"]["location"] == "Home"
    assert t["extendedProps"]["priority"] == 5


async def test_set_task_status_toggle(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-done@webcaldav",
        title="Toggle", start=None, due=datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
    )
    await set_task_status(base, USER, PASSWORD, url, "t-done@webcaldav", completed=True)
    t = {x["id"]: x for x in await _fetch(base, url)}["t-done@webcaldav"]
    assert t["extendedProps"]["completed"] is True
    assert "STATUS:COMPLETED" in _raw(base, url, "t-done@webcaldav")

    await set_task_status(base, USER, PASSWORD, url, "t-done@webcaldav", completed=False)
    t = {x["id"]: x for x in await _fetch(base, url)}["t-done@webcaldav"]
    assert t["extendedProps"]["completed"] is False
    assert "STATUS:NEEDS-ACTION" in _raw(base, url, "t-done@webcaldav")


async def test_delete_task(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-del@webcaldav",
        title="Bye", start=None, due=datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
    )
    await delete_task(base, USER, PASSWORD, url, "t-del@webcaldav")
    assert "t-del@webcaldav" not in {x["id"] for x in await _fetch(base, url)}


async def test_delete_task_not_found(task_calendar):
    base, url = task_calendar
    with pytest.raises(EventNotFoundError):
        await delete_task(base, USER, PASSWORD, url, "nope@webcaldav")


async def test_create_task_with_reminder(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-rem@webcaldav",
        title="Pinged", start=None, due=datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        reminders=[(timedelta(minutes=-15), "START")],
    )
    t = {x["id"]: x for x in await _fetch(base, url)}["t-rem@webcaldav"]
    editable = [r for r in t["extendedProps"]["reminders"] if not r.get("readonly")]
    assert {"value": 15, "unit": "minutes"} in editable


async def test_create_recurring_task(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-recur@webcaldav",
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    occ = sorted(
        x["start"][:10] for x in await _fetch(base, url) if x["id"] == "t-recur@webcaldav"
    )
    assert occ == ["2026-06-12", "2026-06-19", "2026-06-26", "2026-07-03"]


async def test_recurring_task_rfc_advance(task_calendar):
    """Completing one occurrence marks just that instance done; the series
    keeps generating later occurrences (RFC advance)."""
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-radv@webcaldav",
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    # Mark the Jun 19 occurrence done.
    await set_task_status(
        base, USER, PASSWORD, url, "t-radv@webcaldav",
        completed=True, recurrence_id="2026-06-19T09:00:00+00:00",
    )
    by_day = {
        x["start"][:10]: x for x in await _fetch(base, url) if x["id"] == "t-radv@webcaldav"
    }
    # All four occurrences still present; only Jun 19 is completed.
    assert set(by_day) == {"2026-06-12", "2026-06-19", "2026-06-26", "2026-07-03"}
    assert by_day["2026-06-19"]["extendedProps"]["completed"] is True
    for day in ("2026-06-12", "2026-06-26", "2026-07-03"):
        assert by_day[day]["extendedProps"]["completed"] is False

    # Un-completing drops the override; Jun 19 reverts to pending.
    await set_task_status(
        base, USER, PASSWORD, url, "t-radv@webcaldav",
        completed=False, recurrence_id="2026-06-19T09:00:00+00:00",
    )
    by_day = {
        x["start"][:10]: x for x in await _fetch(base, url) if x["id"] == "t-radv@webcaldav"
    }
    assert by_day["2026-06-19"]["extendedProps"]["completed"] is False


async def test_delete_recurring_task_this(task_calendar):
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-rdel@webcaldav",
        title="Chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    await delete_task(
        base, USER, PASSWORD, url, "t-rdel@webcaldav",
        scope="this", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    occ = sorted(
        x["start"][:10] for x in await _fetch(base, url) if x["id"] == "t-rdel@webcaldav"
    )
    assert occ == ["2026-06-12", "2026-06-26", "2026-07-03"]
