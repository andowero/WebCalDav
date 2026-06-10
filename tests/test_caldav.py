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

# Mixed VALARMs: three editable duration triggers plus one EMAIL alarm that
# must survive untouched (the editable reminder model never rewrites it).
_ALARM_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:alarm-event
DTSTAMP:20260101T000000Z
DTSTART:20260605T090000Z
DTEND:20260605T100000Z
SUMMARY:Alarmed
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-PT15M
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-PT1H
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-P1W
END:VALARM
BEGIN:VALARM
ACTION:EMAIL
SUMMARY:Mail reminder
DESCRIPTION:Mail me
ATTENDEE:mailto:alice@example.com
TRIGGER:-PT30M
END:VALARM
END:VEVENT
END:VCALENDAR"""

# UNTIL-bounded series: two occurrences, Jun 16 and Jun 23 (UNTIL Jun 24).
_RECUR_UNTIL_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:recur-until
DTSTAMP:20260101T000000Z
DTSTART:20260616T090000Z
DTEND:20260616T093000Z
RRULE:FREQ=WEEKLY;UNTIL=20260624T000000Z
SUMMARY:Bounded sync
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
        cal.save_event(_ALARM_EVENT)
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


async def test_update_recurring_all_until_drag(edit_calendar):
    """Dragging the whole UNTIL-bounded series must shift UNTIL with DTSTART.

    Regression: the series ran Jun 16 + Jun 23 (UNTIL Jun 24). Dragging the
    Jun 23 occurrence to Jun 30 (scope "all") shifts the series +7d. If UNTIL
    stays put, the new Jun 30 tail falls past it and silently disappears,
    leaving a single occurrence on Jun 23.
    """
    import caldav

    base_url, url = edit_calendar
    with caldav.DAVClient(url=base_url, username=USER, password=PASSWORD) as client:
        caldav.Calendar(client=client, url=url).save_event(_RECUR_UNTIL_EVENT)

    start = datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 30, 9, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-until",
        title="Bounded sync", all_day=False, start=start, end=end,
        location=None, description=None, scope="all",
        recurrence_id="2026-06-23T09:00:00+00:00",
    )

    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    dates = sorted(e["start"][:10] for e in events if e["id"] == "recur-until")
    # Both occurrences survive, shifted +7d: Jun 23 and Jun 30.
    assert dates == ["2026-06-23", "2026-06-30"]


async def test_update_recurring_all_shifts_exdate(edit_calendar):
    """A deleted occurrence must stay deleted after the whole series is dragged.

    Regression: delete Jun 19 (EXDATE), then drag the series +7d (scope "all")
    by moving the Jun 26 occurrence to Jul 3. If the EXDATE does not shift with
    DTSTART it stops matching any slot and the deleted day reappears.
    """
    base_url, url = edit_calendar
    # Delete the Jun 19 occurrence -> EXDATE at 2026-06-19T09:00.
    await delete_event(
        base_url, USER, PASSWORD, url, "recur-event", scope="this", recurrence_id=_PIVOT
    )
    # Drag the whole series +7d.
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Shifted", all_day=False,
        start=datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 3, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="all",
        recurrence_id="2026-06-26T09:00:00+00:00",
    )
    starts = await _recur_starts(base_url, url)
    # Series shifts to Jun 19, 26, Jul 3, 10. The Jun 19 EXDATE moves with it to
    # Jun 26, so Jun 26 is excluded; Jun 19 is now a real slot and survives.
    assert "2026-06-26" not in starts
    assert "2026-06-19" in starts


async def test_update_recurring_thisfuture_carries_exdate(edit_calendar):
    """A deleted future occurrence stays deleted after a this+future split.

    Regression: delete Jul 3 (EXDATE), then split the series at Jun 26 (scope
    "thisfuture") onto a fresh series. The new series must carry the Jul 3
    exclusion or the deleted occurrence reappears on it.
    """
    base_url, url = edit_calendar
    # Delete the Jul 3 occurrence -> EXDATE.
    await delete_event(
        base_url, USER, PASSWORD, url, "recur-event", scope="this",
        recurrence_id="2026-07-03T09:00:00+00:00",
    )
    # Split from Jun 26 forward onto a new series (no time change).
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Split", all_day=False,
        start=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="thisfuture",
        recurrence_id="2026-06-26T09:00:00+00:00",
    )
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    dates = sorted(e["start"][:10] for e in events)
    # Jul 3 stays excluded on the spun-off series; earlier + pivot slots survive.
    assert "2026-07-03" not in dates
    assert "2026-06-19" in dates and "2026-06-26" in dates


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


async def test_thisfuture_split_until_survives_all_rename(edit_calendar):
    """A this+future split must bound the master at its last real occurrence.

    Regression: the split set the master UNTIL to pivot-1s (mid-day on the pivot
    day). The editor's end-by-date is date-granular, so a later "all" edit
    round-tripped that to end-of-day and re-admitted the pivot occurrence -> a
    ghost third event appeared on the master.
    """
    base_url, url = edit_calendar
    # 1. Split off Jun 19+ to a new 11:00 series; master keeps Jun 12 only.
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Future", all_day=False,
        start=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 19, 11, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="thisfuture", recurrence_id=_PIVOT,
    )
    # 2. Re-open the master and round-trip its rule exactly as the UI does: the
    #    end-by-date field is date-granular and re-serializes to end-of-day.
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    rule = dict({e["id"]: e for e in events}["recur-event"]["extendedProps"]["recurrenceRule"])
    assert rule.get("until")
    rule["until"] = f'{rule["until"][:10]}T23:59:59'
    # 3. Rename the whole (remaining) series.
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Renamed", all_day=False,
        start=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="all",
        recurrence_id="2026-06-12T09:00:00+00:00", rrule=rule,
    )
    view = await _recur_view(base_url, url)
    # No ghost: the master holds exactly its one occurrence, not the pivot day too.
    renamed = sorted(x[0][:10] for x in view if x[1] == "Renamed")
    assert renamed == ["2026-06-12"]


async def test_update_recurring_thisfuture_after_this_override(edit_calendar):
    """A this+future split must carry a prior "this only" override with it.

    Regression: detaching Jun 26 ("this"), then splitting from Jun 19 forward
    ("thisfuture") left the Jun 26 override orphaned on the truncated master
    while the new series regenerated Jun 26 -> two events that day.
    """
    base_url, url = edit_calendar
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo", all_day=False,
        start=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this",
        recurrence_id="2026-06-26T09:00:00+00:00",
    )
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Future", all_day=False,
        start=datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 19, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="thisfuture", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    jun26 = [v for v in view if v[0][:10] == "2026-06-26"]
    assert len(jun26) == 1 and jun26[0][1] == "Solo"
    assert len(view) == 4  # no duplicate


async def test_update_recurring_all_drag_after_this_override(edit_calendar):
    """A whole-series drag must move a prior override too, without clobbering it."""
    base_url, url = edit_calendar
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo", all_day=False,
        start=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this",
        recurrence_id="2026-06-26T09:00:00+00:00",
    )
    # Drag the whole series +7d (click Jun 19, drop on Jun 26) and rename.
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Renamed", all_day=False,
        start=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="all", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    assert len(view) == 4  # no duplicate
    days = [v[0][:10] for v in view]
    assert len(set(days)) == len(days)  # one event per day
    # The override followed the +7d shift (Jun 26 -> Jul 3) and kept its title.
    jul3 = [v for v in view if v[0][:10] == "2026-07-03"]
    assert len(jul3) == 1 and jul3[0][1] == "Solo"


async def test_update_recurring_two_this_overrides_isolated(edit_calendar):
    """Two "this only" overrides coexist; neither affects the other or the series."""
    base_url, url = edit_calendar
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo", all_day=False,
        start=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 26, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this",
        recurrence_id="2026-06-26T09:00:00+00:00",
    )
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Other", all_day=False,
        start=datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 19, 9, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    assert len(view) == 4
    by_day = {v[0][:10]: v[1] for v in view}
    assert by_day["2026-06-26"] == "Solo"
    assert by_day["2026-06-19"] == "Other"
    assert by_day["2026-06-12"] == "Weekly sync"
    assert by_day["2026-07-03"] == "Weekly sync"


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


async def test_delete_recurring_thisfuture_drops_orphan_override(edit_calendar):
    """Deleting this+future must not leave an override past the pivot orphaned."""
    base_url, url = edit_calendar
    # Detach a late occurrence (Jun 26) as its own override...
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Solo", all_day=False,
        start=datetime(2026, 6, 26, 11, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 26, 11, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this",
        recurrence_id="2026-06-26T09:00:00+00:00",
    )
    # ...then delete from Jun 19 forward. The Jun 26 override sits past the pivot
    # and must be removed, not left orphaned on the truncated master.
    await delete_event(
        base_url, USER, PASSWORD, url, "recur-event", scope="thisfuture", recurrence_id=_PIVOT
    )
    assert await _recur_starts(base_url, url) == ["2026-06-12"]


async def test_update_recurring_this_no_duplicate(edit_calendar):
    """A moved single occurrence shows exactly once (no master/override dup)."""
    base_url, url = edit_calendar
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Moved", all_day=False,
        start=datetime(2026, 6, 19, 13, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 19, 13, 30, tzinfo=timezone.utc),
        location=None, description=None, scope="this", recurrence_id=_PIVOT,
    )
    view = await _recur_view(base_url, url)
    # No plain occurrence lingers at the original 09:00 slot alongside the move.
    jun19 = [v for v in view if v[0][:10] == "2026-06-19"]
    assert len(jun19) == 1
    assert jun19[0][1] == "Moved" and jun19[0][0][11:16] == "13:00"


# ── Reminders (VALARM) ───────────────────────────────────────────────────────


async def _fetch_one(base_url, url, uid) -> dict:
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    return {e["id"]: e for e in events}[uid]


def _raw_ical(base_url, url, uid) -> str:
    import caldav

    with caldav.DAVClient(url=base_url, username=USER, password=PASSWORD) as client:
        cal = caldav.Calendar(client=client, url=url)
        return cal.event_by_uid(uid).data


def _editable(reminders) -> list[dict]:
    return [r for r in reminders if not r.get("readonly")]


async def test_fetch_structured_reminders(edit_calendar):
    base_url, url = edit_calendar
    ev = await _fetch_one(base_url, url, "alarm-event")
    rems = ev["extendedProps"]["reminders"]
    editable = _editable(rems)
    # Units normalize to the largest that divides evenly.
    assert {"value": 15, "unit": "minutes"} in editable
    assert {"value": 1, "unit": "hours"} in editable
    assert {"value": 1, "unit": "weeks"} in editable
    locked = [r for r in rems if r.get("readonly")]
    assert len(locked) == 1
    assert "30 minutes before" in locked[0]["text"]


async def test_create_event_with_reminders(edit_calendar):
    from datetime import timedelta

    base_url, url = edit_calendar
    start = datetime(2026, 6, 24, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 24, 10, 0, tzinfo=timezone.utc)
    await create_event(
        base_url, USER, PASSWORD, url, "with-rem@webcaldav",
        title="Pinged", all_day=False, start=start, end=end,
        location=None, description=None,
        reminders=[timedelta(minutes=-10), timedelta(hours=-2)],
    )
    ev = await _fetch_one(base_url, url, "with-rem@webcaldav")
    editable = _editable(ev["extendedProps"]["reminders"])
    assert sorted(editable, key=lambda r: r["value"]) == [
        {"value": 2, "unit": "hours"},
        {"value": 10, "unit": "minutes"},
    ]


async def test_update_event_replaces_reminders(edit_calendar):
    from datetime import timedelta

    base_url, url = edit_calendar
    start = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "alarm-event",
        title="Alarmed", all_day=False, start=start, end=end,
        location=None, description=None,
        reminders=[timedelta(minutes=-5)],
    )
    ev = await _fetch_one(base_url, url, "alarm-event")
    rems = ev["extendedProps"]["reminders"]
    assert _editable(rems) == [{"value": 5, "unit": "minutes"}]
    # The EMAIL alarm is outside the editable model and must survive.
    assert any(r.get("readonly") for r in rems)
    raw = _raw_ical(base_url, url, "alarm-event")
    assert raw.count("BEGIN:VALARM") == 2
    assert "ACTION:EMAIL" in raw


async def test_update_event_reminders_none_untouched(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
    # A drag-style update never sends reminders; all four alarms must remain.
    await update_event(
        base_url, USER, PASSWORD, url, "alarm-event",
        title="Dragged", all_day=False, start=start, end=end,
        location=None, description=None,
    )
    raw = _raw_ical(base_url, url, "alarm-event")
    assert raw.count("BEGIN:VALARM") == 4


async def test_update_event_clears_reminders(edit_calendar):
    base_url, url = edit_calendar
    start = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "alarm-event",
        title="Silenced", all_day=False, start=start, end=end,
        location=None, description=None, reminders=[],
    )
    raw = _raw_ical(base_url, url, "alarm-event")
    # Only the non-editable EMAIL alarm survives a clear.
    assert raw.count("BEGIN:VALARM") == 1
    assert "ACTION:EMAIL" in raw


async def test_create_allday_reminders_roundtrip(edit_calendar):
    from datetime import date, timedelta

    base_url, url = edit_calendar
    await create_event(
        base_url, USER, PASSWORD, url, "allday-rem@webcaldav",
        title="Big day", all_day=True,
        start=date(2026, 6, 25), end=date(2026, 6, 26),
        location=None, description=None,
        reminders=[
            timedelta(hours=9) - timedelta(weeks=2),  # 2 weeks before at 09:00
            timedelta(hours=9),                        # on the day at 09:00
        ],
    )
    raw = _raw_ical(base_url, url, "allday-rem@webcaldav")
    assert "TRIGGER:-P13DT15H" in raw
    assert "TRIGGER:PT9H" in raw
    ev = await _fetch_one(base_url, url, "allday-rem@webcaldav")
    editable = _editable(ev["extendedProps"]["reminders"])
    assert {"value": 2, "unit": "weeks", "time": "09:00"} in editable
    assert {"value": 0, "unit": "days", "time": "09:00"} in editable


async def test_update_recurring_all_reminders(edit_calendar):
    from datetime import timedelta

    base_url, url = edit_calendar
    start = datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 9, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Weekly sync", all_day=False, start=start, end=end,
        location=None, description=None, scope="all", recurrence_id=_PIVOT,
        reminders=[timedelta(minutes=-30)],
    )
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    occurrences = [e for e in events if e["id"] == "recur-event"]
    assert len(occurrences) == 4
    for occ in occurrences:
        assert _editable(occ["extendedProps"]["reminders"]) == [
            {"value": 30, "unit": "minutes"}
        ]


async def test_update_recurring_this_reminders(edit_calendar):
    from datetime import timedelta

    base_url, url = edit_calendar
    start = datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 9, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Weekly sync", all_day=False, start=start, end=end,
        location=None, description=None, scope="this", recurrence_id=_PIVOT,
        reminders=[timedelta(minutes=-10)],
    )
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    occurrences = {e["start"][:10]: e for e in events if e["id"] == "recur-event"}
    assert _editable(occurrences["2026-06-19"]["extendedProps"].get("reminders", [])) == [
        {"value": 10, "unit": "minutes"}
    ]
    # Siblings keep the master's (empty) alarm set — no leak from the override.
    for day in ("2026-06-12", "2026-06-26", "2026-07-03"):
        assert occurrences[day]["extendedProps"].get("reminders") in (None, [])


async def test_update_recurring_thisfuture_reminders(edit_calendar):
    from datetime import timedelta

    base_url, url = edit_calendar
    start = datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, 9, 30, tzinfo=timezone.utc)
    await update_event(
        base_url, USER, PASSWORD, url, "recur-event",
        title="Weekly sync", all_day=False, start=start, end=end,
        location=None, description=None, scope="thisfuture", recurrence_id=_PIVOT,
        reminders=[timedelta(minutes=-20)],
    )
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 31, tzinfo=timezone.utc)
    events = await fetch_events(base_url, USER, PASSWORD, url, frm, to, "#000000", 7)
    with_rem = sorted(
        e["start"][:10] for e in events
        if e["title"] == "Weekly sync"
        and _editable(e["extendedProps"].get("reminders", []))
        == [{"value": 20, "unit": "minutes"}]
    )
    without = sorted(
        e["start"][:10] for e in events
        if e["title"] == "Weekly sync"
        and not e["extendedProps"].get("reminders")
    )
    # The new series (pivot onward) carries the reminder; the capped old one doesn't.
    assert with_rem == ["2026-06-19", "2026-06-26", "2026-07-03"]
    assert without == ["2026-06-12"]


def test_extract_reminders_absolute_trigger_carries_iso():
    """Absolute datetime triggers stay read-only but include the ISO instant
    so the client can format it per the user's date/time settings."""
    from icalendar import Calendar as ICalendar

    from webcaldav.caldav_client import _extract_reminders

    ical = ICalendar.from_ical(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        "BEGIN:VEVENT\r\nUID:abs\r\nDTSTAMP:20260101T000000Z\r\n"
        "DTSTART;VALUE=DATE:20260615\r\nDTEND;VALUE=DATE:20260616\r\n"
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:R\r\n"
        "TRIGGER;VALUE=DATE-TIME:20260614T090000Z\r\nEND:VALARM\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = next(c for c in ical.walk("VEVENT"))
    rems = _extract_reminders(vevent)
    assert len(rems) == 1
    assert rems[0]["readonly"] is True
    assert rems[0]["at"] == "2026-06-14T09:00:00+00:00"
