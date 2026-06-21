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


async def test_complete_keeps_moved_occurrence_time(task_calendar):
    """A moved single occurrence (scope='this' override) keeps its new time when
    later marked done — completion must not snap it back to the series time."""
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-mvdone@webcaldav",
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    # Move the Jun 19 occurrence from 09:00 to 15:00.
    await update_task(
        base, USER, PASSWORD, url, "t-mvdone@webcaldav",
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 19, 15, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="this", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    # Mark that occurrence done (pivot is the override's stable RECURRENCE-ID).
    await set_task_status(
        base, USER, PASSWORD, url, "t-mvdone@webcaldav",
        completed=True, recurrence_id="2026-06-19T09:00:00+00:00",
    )
    by_day = {
        x["start"][:10]: x for x in await _fetch(base, url) if x["id"] == "t-mvdone@webcaldav"
    }
    jun19 = by_day["2026-06-19"]
    assert jun19["extendedProps"]["completed"] is True
    # The moved 15:00 time survived; it did not revert to the 09:00 series time.
    assert "15:00" in jun19["extendedProps"]["rawDue"]

    # Un-completing keeps the moved override (and its time), just flips status.
    await set_task_status(
        base, USER, PASSWORD, url, "t-mvdone@webcaldav",
        completed=False, recurrence_id="2026-06-19T09:00:00+00:00",
    )
    by_day = {
        x["start"][:10]: x for x in await _fetch(base, url) if x["id"] == "t-mvdone@webcaldav"
    }
    jun19 = by_day["2026-06-19"]
    assert jun19["extendedProps"]["completed"] is False
    assert "15:00" in jun19["extendedProps"]["rawDue"]


async def test_update_keeps_done_status_nonrecurring(task_calendar):
    """Editing (e.g. dragging) a completed non-recurring task keeps it done."""
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-updone@webcaldav",
        title="One-off", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
    )
    await set_task_status(base, USER, PASSWORD, url, "t-updone@webcaldav", completed=True)
    await update_task(
        base, USER, PASSWORD, url, "t-updone@webcaldav",
        title="One-off", start=None,
        due=datetime(2026, 6, 12, 15, 0, tzinfo=timezone.utc),
        location=None, description=None,
    )
    task = next(x for x in await _fetch(base, url) if x["id"] == "t-updone@webcaldav")
    assert task["extendedProps"]["completed"] is True
    assert "15:00" in task["extendedProps"]["rawDue"]


async def test_move_done_occurrence_keeps_done(task_calendar):
    """Dragging a completed recurring occurrence (scope='this') keeps it done."""
    base, url = task_calendar
    await create_task(
        base, USER, PASSWORD, url, "t-mvdn2@webcaldav",
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    # Mark Jun 19 done, then drag it to 15:00.
    await set_task_status(
        base, USER, PASSWORD, url, "t-mvdn2@webcaldav",
        completed=True, recurrence_id="2026-06-19T09:00:00+00:00",
    )
    await update_task(
        base, USER, PASSWORD, url, "t-mvdn2@webcaldav",
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 19, 15, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="this", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    by_day = {
        x["start"][:10]: x for x in await _fetch(base, url) if x["id"] == "t-mvdn2@webcaldav"
    }
    jun19 = by_day["2026-06-19"]
    assert jun19["extendedProps"]["completed"] is True
    assert "15:00" in jun19["extendedProps"]["rawDue"]


async def test_redrag_moved_occurrence_no_orphan(task_calendar):
    """Re-dragging an already-moved occurrence edits the same override in place,
    even if the client passes the occurrence's MOVED anchor as recurrence_id
    instead of its stable RECURRENCE-ID. Must not spawn a duplicate/orphan
    override (which the UI shows as a spurious extra/"new series")."""
    base, url = task_calendar
    UID = "t-redrag@webcaldav"
    await create_task(
        base, USER, PASSWORD, url, UID,
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    await set_task_status(base, USER, PASSWORD, url, UID, completed=True,
                          recurrence_id="2026-06-19T09:00:00+00:00")
    # Drag 1 → 15:00 (stable RECURRENCE-ID 09:00).
    await update_task(
        base, USER, PASSWORD, url, UID, title="Weekly chore",
        start=None, due=datetime(2026, 6, 19, 15, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="this", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    # Drag 2 → 18:00, but the client now sends the MOVED anchor (15:00) as pivot.
    await update_task(
        base, USER, PASSWORD, url, UID, title="Weekly chore",
        start=None, due=datetime(2026, 6, 19, 18, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="this", recurrence_id="2026-06-19T15:00:00+00:00",
    )
    rows = [
        x for x in await _fetch(base, url) if x["id"] == UID
    ]
    # Exactly the four series occurrences — no orphan extra instance.
    assert len(rows) == 4
    by_day = {x["start"]: x for x in rows}
    jun19 = by_day["2026-06-19T18:00:00+00:00"]
    assert jun19["extendedProps"]["completed"] is True
    assert jun19["extendedProps"]["recurrenceId"] == "2026-06-19T09:00:00+00:00"


async def test_task_thisfuture_after_this_moves_pivot(task_calendar):
    """Splitting a task occurrence that already has a 'this' time-move must move it.

    Bug: move Jun 19 due to 11:00 ('this'), then drag the same occurrence to
    13:00 ('thisfuture'). The stale 11:00 override shadowed the new series anchor
    so the pivot stayed at 11:00 while only future occurrences moved.
    """
    base, url = task_calendar
    UID = "t-tf-pivot@webcaldav"
    await create_task(
        base, USER, PASSWORD, url, UID,
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    # 1. Detach Jun 19 due to 11:00.
    await update_task(
        base, USER, PASSWORD, url, UID, title="Weekly chore",
        start=None, due=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="this", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    # 2. Drag the (now 11:00) occurrence to 13:00, this+future; client sends the
    #    moved anchor as recurrence_id, _resolve_pivot maps it back to 09:00.
    await update_task(
        base, USER, PASSWORD, url, UID, title="Weekly chore",
        start=None, due=datetime(2026, 6, 19, 13, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="thisfuture", recurrence_id="2026-06-19T11:00:00+00:00",
    )
    by_day = {x["start"][:10]: x for x in await _fetch(base, url)}
    assert len(by_day) == 4  # no orphan, no vanish
    # The pivot moved to 13:00, not stuck at the prior 11:00 override.
    assert "13:00" in by_day["2026-06-19"]["extendedProps"]["rawDue"]


async def test_task_thisfuture_twice_until_keeps_all(task_calendar):
    """Two this+future splits forward on an UNTIL-bounded task keep every occurrence.

    Bug (UNTIL-bounded only): the spun-off series inherited the old master's
    UNTIL unshifted, so the moved tail fell past the stationary bound and vanished.
    """
    base, url = task_calendar
    UID = "t-tf-until@webcaldav"
    await create_task(
        base, USER, PASSWORD, url, UID,
        title="Bounded chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "until": "2026-07-03T12:00:00+00:00"},
    )
    # 1. Split Jun 26 forward +1d -> Jun 27 (carries Jul 3 -> Jul 4).
    await update_task(
        base, USER, PASSWORD, url, UID, title="Bounded chore",
        start=None, due=datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="thisfuture", recurrence_id="2026-06-26T09:00:00+00:00",
    )
    # 2. Split the past Jun 19 forward +1d -> Jun 20; the new series UNTIL must
    #    shift +1d too or Jun 20 falls past the stale bound and vanishes.
    await update_task(
        base, USER, PASSWORD, url, UID, title="Bounded chore",
        start=None, due=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="thisfuture", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    dates = sorted(x["start"][:10] for x in await _fetch(base, url))
    # Jun 12 (old master), Jun 20 (step 2), Jun 27 + Jul 4 (step 1's series).
    assert dates == ["2026-06-12", "2026-06-20", "2026-06-27", "2026-07-04"]


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


async def _recur_task_with_override(base, url):
    """Weekly chore (due 09:00 x4) with Jun 19 detached as "Solo" due 11:00."""
    UID = "t-reset@webcaldav"
    await create_task(
        base, USER, PASSWORD, url, UID,
        title="Weekly chore", start=None,
        due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 4},
    )
    await update_task(
        base, USER, PASSWORD, url, UID, title="Solo",
        start=None, due=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
        location=None, description=None,
        scope="this", recurrence_id="2026-06-19T09:00:00+00:00",
    )
    return UID


async def test_update_recurring_task_all_reset_title_only(task_calendar):
    """Task reset + title-only change: override title resets, pinned due kept."""
    base, url = task_calendar
    UID = await _recur_task_with_override(base, url)
    await update_task(
        base, USER, PASSWORD, url, UID, title="Renamed",
        start=None, due=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        location=None, description=None, scope="all",
        recurrence_id="2026-06-12T09:00:00+00:00",
        reset_overrides=True, reset_fields=["title"],
    )
    by_day = {x["start"][:10]: x for x in await _fetch(base, url)}
    assert len(by_day) == 4
    assert {x["title"] for x in by_day.values()} == {"Renamed"}
    assert "11:00" in by_day["2026-06-19"]["extendedProps"]["rawDue"]


async def test_update_recurring_task_all_reset_time_and_title(task_calendar):
    """Task reset + time & title change: both reset on the override."""
    base, url = task_calendar
    UID = await _recur_task_with_override(base, url)
    await update_task(
        base, USER, PASSWORD, url, UID, title="Renamed",
        start=None, due=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        location=None, description=None, scope="all",
        recurrence_id="2026-06-12T09:00:00+00:00",
        reset_overrides=True, reset_fields=["time", "title"],
    )
    by_day = {x["start"][:10]: x for x in await _fetch(base, url)}
    assert len(by_day) == 4
    assert {x["title"] for x in by_day.values()} == {"Renamed"}
    # Override due snapped to the series 10:00 slot.
    assert "10:00" in by_day["2026-06-19"]["extendedProps"]["rawDue"]


async def test_update_recurring_task_all_no_reset_keeps_override(task_calendar):
    """No reset: customized occurrence pinned — keeps title and absolute due."""
    base, url = task_calendar
    UID = await _recur_task_with_override(base, url)
    await update_task(
        base, USER, PASSWORD, url, UID, title="Renamed",
        start=None, due=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        location=None, description=None, scope="all",
        recurrence_id="2026-06-12T09:00:00+00:00",
    )
    by_day = {x["start"][:10]: x for x in await _fetch(base, url)}
    assert len(by_day) == 4
    assert by_day["2026-06-19"]["title"] == "Solo"
    # Pinned at its customized 11:00 (NOT dragged to 12:00).
    assert "11:00" in by_day["2026-06-19"]["extendedProps"]["rawDue"]
