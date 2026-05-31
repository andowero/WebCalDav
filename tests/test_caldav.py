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
    RecurringEventError,
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


async def test_update_event_recurring_refused(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 12, 11, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(RecurringEventError):
        await update_event(
            base_url, USER, PASSWORD, url, "recur-event",
            title="Nope", all_day=False, start=start, end=end,
            location=None, description=None,
        )


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
