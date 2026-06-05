"""In-process radicale integration tests for the CalDAV client layer.

Spins up a real radicale server over wsgiref on an ephemeral port and exercises
discover_calendars / fetch_events against it — no network, no container.

Regression guard: events used to be parsed via vobject, which caldav 3.x makes
optional. When vobject is absent, vobject_instance is None and every event is
dropped (count=0). The client now parses via icalendar; these tests assert real
events come back.
"""
import tempfile
import threading
from datetime import datetime, timezone
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from webcaldav.caldav_client import (
    EventNotFoundError,
    create_event,
    delete_event,
    discover_calendars,
    fetch_events,
    update_event,
)

USER = "alice"
PASSWORD = "secret"

_TZ_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:tz-event
DTSTAMP:20260101T000000Z
DTSTART;TZID=Europe/Prague:20260515T100000
DTEND;TZID=Europe/Prague:20260515T113000
SUMMARY:Standup
END:VEVENT
END:VCALENDAR"""

_ALLDAY_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:allday-event
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:20260520
DTEND;VALUE=DATE:20260521
SUMMARY:Holiday
END:VEVENT
END:VCALENDAR"""

_DURATION_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:duration-event
DTSTAMP:20260101T000000Z
DTSTART:20260518T090000Z
DURATION:PT1H
SUMMARY:Call
END:VEVENT
END:VCALENDAR"""


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):  # silence per-request logging
        pass


@pytest.fixture(scope="module")
def radicale_server():
    """Run radicale on an ephemeral port; yield (base_url, calendars dict)."""
    radicale = pytest.importorskip("radicale")
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

    base_url = f"http://127.0.0.1:{port}/"

    import caldav
    from caldav.elements.ical import CalendarColor

    calendars: dict[str, str] = {}
    try:
        with caldav.DAVClient(url=base_url, username=USER, password=PASSWORD) as client:
            principal = client.principal()

            work = principal.make_calendar(name="Work")
            work.set_properties([CalendarColor("#FF000099")])  # alpha must be stripped
            work.save_event(_TZ_EVENT)
            work.save_event(_ALLDAY_EVENT)
            work.save_event(_DURATION_EVENT)
            calendars["Work"] = str(work.url)

            plain = principal.make_calendar(name="Plain")  # no color set
            calendars["Plain"] = str(plain.url)

        yield base_url, calendars
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


async def test_discover_calendars_returns_color(radicale_server):
    base_url, _ = radicale_server
    cals = await discover_calendars(base_url, USER, PASSWORD)

    by_name = {c.display_name: c for c in cals}
    assert "Work" in by_name
    assert "Plain" in by_name
    # 8-digit #rrggbbaa from the server is normalized to 6-digit #rrggbb
    assert by_name["Work"].color == "#FF0000"
    # no server color -> fallback blue
    assert by_name["Plain"].color == "#3788d8"


async def test_fetch_events_parses_all_event_types(radicale_server):
    base_url, calendars = radicale_server
    frm = datetime(2026, 5, 1, tzinfo=timezone.utc)
    to = datetime(2026, 6, 1, tzinfo=timezone.utc)

    events = await fetch_events(
        base_url, USER, PASSWORD, calendars["Work"], frm, to, color="#abcdef", calendar_id=1
    )

    by_id = {e["id"]: e for e in events}
    # regression: all three events must come back (vobject-None used to drop them)
    assert set(by_id) == {"tz-event", "allday-event", "duration-event"}

    tz = by_id["tz-event"]
    assert tz["title"] == "Standup"
    assert tz["allDay"] is False
    assert tz["color"] == "#abcdef"
    assert tz["start"].startswith("2026-05-15T10:00:00")
    assert "end" in tz

    allday = by_id["allday-event"]
    assert allday["allDay"] is True
    assert allday["start"] == "2026-05-20"

    dur = by_id["duration-event"]
    # DURATION resolved to an explicit end
    assert dur["end"].startswith("2026-05-18T10:00:00")


async def test_fetch_events_naive_range(radicale_server):
    """FullCalendar sends date-only/naive bounds; fetch must still work."""
    base_url, calendars = radicale_server
    events = await fetch_events(
        base_url,
        USER,
        PASSWORD,
        calendars["Work"],
        datetime(2026, 5, 1),
        datetime(2026, 6, 1),
        color="#000000",
        calendar_id=1,
    )
    assert {e["id"] for e in events} == {"tz-event", "allday-event", "duration-event"}


_EDIT_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:edit-event
DTSTAMP:20260101T000000Z
DTSTART:20260610T090000Z
DTEND:20260610T100000Z
SUMMARY:Original
LOCATION:Old place
END:VEVENT
END:VCALENDAR"""

_EDIT_ALLDAY = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:edit-allday
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:20260611
DTEND;VALUE=DATE:20260612
SUMMARY:Day off
END:VEVENT
END:VCALENDAR"""

_RECUR_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:recur-event
DTSTAMP:20260101T000000Z
DTSTART:20260612T090000Z
DTEND:20260612T093000Z
RRULE:FREQ=WEEKLY;COUNT=4
SUMMARY:Weekly sync
END:VEVENT
END:VCALENDAR"""


@pytest.fixture()
def edit_calendar(radicale_server):
    """A throwaway calendar seeded with editable events, torn down per test."""
    import caldav

    base_url, _ = radicale_server
    name = "Edit"
    with caldav.DAVClient(url=base_url, username=USER, password=PASSWORD) as client:
        cal = client.principal().make_calendar(name=name)
        cal.save_event(_EDIT_EVENT)
        cal.save_event(_EDIT_ALLDAY)
        cal.save_event(_RECUR_EVENT)
        url = str(cal.url)
        try:
            yield base_url, url
        finally:
            cal.delete()


async def test_update_event_timed(edit_calendar):
    base_url, url = edit_calendar
    new_start = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "edit-event",
        title="Renamed", all_day=False, start=new_start, end=new_end,
        location="New place", description="Some notes",
    )

    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    ev = {e["id"]: e for e in events}["edit-event"]
    assert ev["title"] == "Renamed"
    assert ev["start"].startswith("2026-06-10T14:00:00")
    assert ev["end"].startswith("2026-06-10T15:30:00")
    assert ev["extendedProps"]["location"] == "New place"
    assert ev["extendedProps"]["description"] == "Some notes"


async def test_update_event_allday(edit_calendar):
    from datetime import date

    base_url, url = edit_calendar
    await update_event(
        base_url, USER, PASSWORD, url, "edit-allday",
        title="Vacation", all_day=True,
        start=date(2026, 6, 15), end=date(2026, 6, 18),  # exclusive DTEND
        location=None, description=None,
    )

    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    ev = {e["id"]: e for e in events}["edit-allday"]
    assert ev["title"] == "Vacation"
    assert ev["allDay"] is True
    assert ev["start"] == "2026-06-15"
    assert ev["end"] == "2026-06-18"


async def _recur_view(base_url, url) -> list[tuple[str, str]]:
    """(start ISO, title) for every occurrence on/after the recur series start."""
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    return sorted((e["start"], e["title"]) for e in events if e["start"][:10] >= "2026-06-12")


async def test_update_recurring_all(edit_calendar):
    base_url, url = edit_calendar
    # User clicks the Jun 19 occurrence and renames the whole series (no time change).
    start = datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 9, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Renamed", all_day=False, start=start, end=end,
        location=None, description=None, scope="all", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    # All four occurrences keep their dates (anchor preserved) and get the new title.
    assert [v[1] for v in view] == ["Renamed"] * 4
    assert [v[0][:10] for v in view] == [
        "2026-06-12", "2026-06-19", "2026-06-26", "2026-07-03",
    ]


async def test_update_recurring_this(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 11, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo", all_day=False, start=start, end=end,
        location=None, description=None, scope="this", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    # The Jun 19 occurrence is detached (new title + 11:00); the rest are untouched.
    titles = {v[1] for v in view}
    assert titles == {"Weekly sync", "Solo"}
    solo = [v for v in view if v[1] == "Solo"]
    assert len(solo) == 1 and solo[0][0].startswith("2026-06-19T11:00:00")
    assert len(view) == 4


async def test_update_recurring_this_twice(edit_calendar):
    """Re-editing a detached occurrence must update it, not spawn a duplicate.

    Regression: the client must pivot the second edit on the override's stable
    RECURRENCE-ID (exposed as extendedProps.recurrenceId), not its moved start.
    """
    base_url, url = edit_calendar
    # First "this" edit: detach Jun 19, move it to 11:00 and rename to "Solo".
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo", all_day=False,
        start=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 19, 11, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this", recurrence_id=_PIVOT,
    )

    # Client refetches; the moved occurrence keeps its original RECURRENCE-ID.
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    solo = [e for e in events if e["title"] == "Solo"]
    assert len(solo) == 1
    pivot = solo[0]["extendedProps"]["recurrenceId"]
    assert pivot.startswith("2026-06-19T09:00:00")

    # Second "this" edit on the same occurrence, pivoting on the stable id.
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo2", all_day=False,
        start=datetime(2026, 6, 19, 13, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 19, 13, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this", recurrence_id=pivot,
    )

    view = await _recur_view(base_url, url)
    # Still four occurrences: no duplicate. The detached one moved to 13:00.
    assert len(view) == 4
    titles = {v[1] for v in view}
    assert titles == {"Weekly sync", "Solo2"}
    solo2 = [v for v in view if v[1] == "Solo2"]
    assert len(solo2) == 1 and solo2[0][0].startswith("2026-06-19T13:00:00")


async def test_update_recurring_thisfuture(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 11, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Future", all_day=False, start=start, end=end,
        location=None, description=None, scope="thisfuture", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    # Jun 12 stays on the original series; Jun 19/26/Jul 3 become the new 11:00 series.
    assert (v := [x for x in view if x[1] == "Weekly sync"]) and len(v) == 1
    assert v[0][0].startswith("2026-06-12T09:00:00")
    future = sorted(x[0][:10] for x in view if x[1] == "Future")
    assert future == ["2026-06-19", "2026-06-26", "2026-07-03"]
    assert all(x[0][11:16] == "11:00" for x in view if x[1] == "Future")


async def test_update_recurring_thisprev(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc)  # +1h delta
    end = datetime(2026, 6, 19, 10, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Past", all_day=False, start=start, end=end,
        location=None, description=None, scope="thisprev", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    # Past+current shifted +1h to 10:00 and renamed; future stays at 09:00.
    past = sorted(x[0] for x in view if x[1] == "Past")
    assert [p[:10] for p in past] == ["2026-06-12", "2026-06-19"]
    assert all(p[11:16] == "10:00" for p in past)
    future = sorted(x[0] for x in view if x[1] == "Weekly sync")
    assert [f[:10] for f in future] == ["2026-06-26", "2026-07-03"]
    assert all(f[11:16] == "09:00" for f in future)


async def test_update_event_not_found(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 12, 11, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(EventNotFoundError):
        await update_event(
            base_url, USER, PASSWORD, url, "does-not-exist",
            title="x", all_day=False, start=start, end=end,
            location=None, description=None,
        )


async def test_create_event_timed(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    await create_event(
        base_url, USER, PASSWORD, url, "new-timed@webcaldav",
        title="Fresh meeting", all_day=False, start=start, end=end,
        location="Room 1", description="Notes",
    )

    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    ev = {e["id"]: e for e in events}["new-timed@webcaldav"]
    assert ev["title"] == "Fresh meeting"
    assert ev["allDay"] is False
    assert ev["start"].startswith("2026-06-20T09:00:00")
    assert ev["end"].startswith("2026-06-20T10:00:00")
    assert ev["extendedProps"]["location"] == "Room 1"


async def test_create_event_allday(edit_calendar):
    from datetime import date

    base_url, url = edit_calendar
    await create_event(
        base_url, USER, PASSWORD, url, "new-allday@webcaldav",
        title="Trip", all_day=True,
        start=date(2026, 6, 21), end=date(2026, 6, 23),  # exclusive DTEND
        location=None, description=None,
    )

    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    ev = {e["id"]: e for e in events}["new-allday@webcaldav"]
    assert ev["title"] == "Trip"
    assert ev["allDay"] is True
    assert ev["start"] == "2026-06-21"
    assert ev["end"] == "2026-06-23"


async def test_delete_event(edit_calendar):
    base_url, url = edit_calendar
    await delete_event(base_url, USER, PASSWORD, url, "edit-event")

    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    assert "edit-event" not in {e["id"] for e in events}


async def test_delete_event_not_found(edit_calendar):
    base_url, url = edit_calendar
    with pytest.raises(EventNotFoundError):
        await delete_event(base_url, USER, PASSWORD, url, "does-not-exist")


# ── Recurring delete scopes ──────────────────────────────────────────────────
# _RECUR_EVENT is FREQ=WEEKLY;COUNT=4 from 2026-06-12 09:00Z, i.e. occurrences
# on Jun 12, 19, 26 and Jul 3. The pivot used below is the Jun 19 occurrence.

_PIVOT = "2026-06-19T09:00:00+00:00"


async def _recur_starts(base_url, url) -> list[str]:
    """Sorted YYYY-MM-DD start dates of every surviving recur-event occurrence."""
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    return sorted(e["start"][:10] for e in events if e["id"] == "recur-event")


async def test_create_recurring_weekly_count(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 22, 9, 30, tzinfo=timezone.utc)
    await create_event(
        base_url, USER, PASSWORD, url, "new-recur@webcaldav",
        title="Standup", all_day=False, start=start, end=end,
        location=None, description=None,
        rrule={"freq": "weekly", "interval": 1, "count": 3},
    )
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 8, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    occ = sorted(e["start"][:10] for e in events if e["id"] == "new-recur@webcaldav")
    assert occ == ["2026-06-22", "2026-06-29", "2026-07-06"]
    ev = next(e for e in events if e["id"] == "new-recur@webcaldav")
    assert ev["extendedProps"]["recurrenceRule"]["freq"] == "weekly"
    assert ev["extendedProps"]["recurrenceRule"]["count"] == 3


def test_preview_recurrence_count():
    from webcaldav.caldav_client import preview_recurrence

    start = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    last, count = preview_recurrence(start, {"freq": "weekly", "count": 3})
    assert count == 3
    assert last.startswith("2026-07-06")


def test_preview_recurrence_until():
    from webcaldav.caldav_client import preview_recurrence

    start = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    last, count = preview_recurrence(start, {"freq": "weekly", "until": "2026-07-07T00:00:00Z"})
    # Jun 22, 29, Jul 6 fall before the until bound.
    assert count == 3
    assert last.startswith("2026-07-06")


def test_preview_recurrence_infinite():
    from webcaldav.caldav_client import preview_recurrence

    start = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    assert preview_recurrence(start, {"freq": "daily"}) == (None, None)


def test_preview_recurrence_monthly_weekday():
    from webcaldav.caldav_client import preview_recurrence

    # 2026-06-22 is the 4th Monday of June; weekday mode should keep Mondays.
    start = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    last, count = preview_recurrence(
        start, {"freq": "monthly", "monthly_mode": "weekday", "count": 2}
    )
    assert count == 2
    # 4th Monday of July 2026 is the 27th.
    assert last.startswith("2026-07-27")


async def test_delete_recurring_all(edit_calendar):
    base_url, url = edit_calendar
    await delete_event(base_url, USER, PASSWORD, url, "recur-event", scope="all")
    assert await _recur_starts(base_url, url) == []


async def test_delete_recurring_this(edit_calendar):
    base_url, url = edit_calendar
    await delete_event(
        base_url, USER, PASSWORD, url, "recur-event", scope="this", recurrence_id=_PIVOT
    )
    # Only the Jun 19 occurrence is removed (EXDATE); the rest remain.
    assert await _recur_starts(base_url, url) == ["2026-06-12", "2026-06-26", "2026-07-03"]


async def test_delete_recurring_thisfuture(edit_calendar):
    base_url, url = edit_calendar
    await delete_event(
        base_url, USER, PASSWORD, url, "recur-event", scope="thisfuture", recurrence_id=_PIVOT
    )
    # Pivot and everything after it are dropped; only the earlier date survives.
    assert await _recur_starts(base_url, url) == ["2026-06-12"]


async def test_delete_recurring_thisprev(edit_calendar):
    base_url, url = edit_calendar
    await delete_event(
        base_url, USER, PASSWORD, url, "recur-event", scope="thisprev", recurrence_id=_PIVOT
    )
    # Pivot and everything before it are dropped; only later dates survive.
    assert await _recur_starts(base_url, url) == ["2026-06-26", "2026-07-03"]
