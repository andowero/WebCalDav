"""In-process radicale integration tests for the share .ics export helpers.

The export path serializes *unexpanded* components, so RRULE / VALARM survive in
the downloaded file (a real, importable iCalendar). A single VCALENDAR carries
many components, which is how multiple events are exported in one file.
"""
import tempfile
import threading
from datetime import datetime, timezone
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from webcaldav.caldav_client import (
    EventNotFoundError,
    export_item_ics,
    export_range_ics,
)

USER = "alice"
PASSWORD = "secret"

_PLAIN_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:plain-1
DTSTAMP:20260101T000000Z
DTSTART:20260610T090000Z
DTEND:20260610T100000Z
SUMMARY:Standup
END:VEVENT
END:VCALENDAR"""

# A weekly series that runs well past any single-month window.
_RECUR_EVENT = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//webcaldav-test//EN
BEGIN:VEVENT
UID:recur-1
DTSTAMP:20260101T000000Z
DTSTART:20260612T120000Z
DTEND:20260612T123000Z
RRULE:FREQ=WEEKLY;COUNT=20
SUMMARY:Weekly sync
END:VEVENT
END:VCALENDAR"""


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def radicale_server():
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
    base_url = f"http://127.0.0.1:{port}/"

    import caldav

    calendars: dict[str, str] = {}
    try:
        with caldav.DAVClient(url=base_url, username=USER, password=PASSWORD) as client:
            principal = client.principal()
            cal = principal.make_calendar(name="Shared")
            cal.save_event(_PLAIN_EVENT)
            cal.save_event(_RECUR_EVENT)
            calendars["Shared"] = str(cal.url)
        yield base_url, calendars
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


async def test_export_item_single(radicale_server):
    base_url, calendars = radicale_server
    ics = await export_item_ics(
        base_url, USER, PASSWORD, calendars["Shared"], "plain-1", "event"
    )
    assert "BEGIN:VCALENDAR" in ics
    assert "UID:plain-1" in ics
    assert "SUMMARY:Standup" in ics
    # Only the one item is in the file.
    assert ics.count("BEGIN:VEVENT") == 1


async def test_export_item_missing(radicale_server):
    base_url, calendars = radicale_server
    with pytest.raises(EventNotFoundError):
        await export_item_ics(
            base_url, USER, PASSWORD, calendars["Shared"], "no-such-uid", "event"
        )


async def test_export_range_combines_and_keeps_rrule(radicale_server):
    base_url, calendars = radicale_server
    sources = [
        {
            "account_url": base_url,
            "username": USER,
            "password": PASSWORD,
            "calendar_url": calendars["Shared"],
        }
    ]
    # A one-month window: the recurring master is included unexpanded, so the
    # whole series (RRULE reaching past the window) survives the export.
    frm = datetime(2026, 6, 1, tzinfo=timezone.utc)
    to = datetime(2026, 7, 1, tzinfo=timezone.utc)
    ics = await export_range_ics(sources, frm, to)
    assert ics.count("BEGIN:VCALENDAR") == 1  # one merged calendar
    assert "UID:plain-1" in ics
    assert "UID:recur-1" in ics
    assert "RRULE:FREQ=WEEKLY" in ics  # unexpanded -> the rule is preserved
