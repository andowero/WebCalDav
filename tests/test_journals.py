"""In-process radicale integration tests for the VJOURNAL (journal) client layer.

Mirrors test_caldav.py / test_tasks.py but for journals: create/fetch/update/
delete, all-day vs timed start, and the Markdown body round-trip. Journals carry
no end, recurrence or alarms. Reuses the same ephemeral-radicale pattern.
"""
import tempfile
import threading
from datetime import date, datetime, timezone
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from webcaldav.caldav_client import (
    EventNotFoundError,
    create_journal,
    delete_journal,
    fetch_journals,
    update_journal,
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
def journal_calendar(radicale_base):
    """A throwaway calendar for journals, torn down per test."""
    import caldav

    with caldav.DAVClient(url=radicale_base, username=USER, password=PASSWORD) as client:
        cal = client.principal().make_calendar(name="Journals")
        url = str(cal.url)
        try:
            yield radicale_base, url
        finally:
            cal.delete()


_FROM = datetime(2026, 6, 1, tzinfo=timezone.utc)
_TO = datetime(2026, 7, 31, tzinfo=timezone.utc)


async def _fetch(base, url):
    return await fetch_journals(base, USER, PASSWORD, url, _FROM, _TO, "#abcdef", 3)


def _raw(base, url, uid):
    import caldav

    with caldav.DAVClient(url=base, username=USER, password=PASSWORD) as client:
        cal = caldav.Calendar(client=client, url=url)
        return cal.journal_by_uid(uid).data


async def test_create_and_fetch_allday_journal(journal_calendar):
    base, url = journal_calendar
    await create_journal(
        base, USER, PASSWORD, url, "j-allday@webcaldav",
        title="Trip log", start=date(2026, 6, 15),
        description="# Day one\n\nWalked the `coast` path.",
    )
    journals = await _fetch(base, url)
    j = {x["id"]: x for x in journals}["j-allday@webcaldav"]
    assert j["title"] == "Trip log"
    assert j["color"] == "#abcdef"
    assert j["allDay"] is True
    assert j["start"] == "2026-06-15"
    p = j["extendedProps"]
    assert p["isJournal"] is True
    assert p["calendarId"] == 3
    assert "# Day one" in p["description"]
    # The Markdown body persists verbatim in DESCRIPTION.
    assert "coast" in _raw(base, url, "j-allday@webcaldav")


async def test_create_timed_journal(journal_calendar):
    base, url = journal_calendar
    await create_journal(
        base, USER, PASSWORD, url, "j-timed@webcaldav",
        title="Standup notes", start=datetime(2026, 6, 16, 9, 30, tzinfo=timezone.utc),
        description="notes",
    )
    j = {x["id"]: x for x in await _fetch(base, url)}["j-timed@webcaldav"]
    assert j["allDay"] is False
    assert j["start"].startswith("2026-06-16T09:30:00")


async def test_multiple_journals_same_day(journal_calendar):
    base, url = journal_calendar
    for n in (1, 2, 3):
        await create_journal(
            base, USER, PASSWORD, url, f"j-multi-{n}@webcaldav",
            title=f"Entry {n}", start=date(2026, 6, 18), description=f"body {n}",
        )
    same_day = [x for x in await _fetch(base, url) if x["start"] == "2026-06-18"]
    assert len(same_day) == 3


async def test_update_journal_fields(journal_calendar):
    base, url = journal_calendar
    await create_journal(
        base, USER, PASSWORD, url, "j-edit@webcaldav",
        title="Old", start=date(2026, 6, 10), description="old body",
    )
    await update_journal(
        base, USER, PASSWORD, url, "j-edit@webcaldav",
        title="New", start=date(2026, 6, 12), description="**new** body",
    )
    j = {x["id"]: x for x in await _fetch(base, url)}["j-edit@webcaldav"]
    assert j["title"] == "New"
    assert j["start"] == "2026-06-12"
    assert "**new** body" in j["extendedProps"]["description"]


async def test_delete_journal(journal_calendar):
    base, url = journal_calendar
    await create_journal(
        base, USER, PASSWORD, url, "j-del@webcaldav",
        title="Bye", start=date(2026, 6, 14), description=None,
    )
    await delete_journal(base, USER, PASSWORD, url, "j-del@webcaldav")
    assert "j-del@webcaldav" not in {x["id"] for x in await _fetch(base, url)}


async def test_delete_journal_not_found(journal_calendar):
    base, url = journal_calendar
    with pytest.raises(EventNotFoundError):
        await delete_journal(base, USER, PASSWORD, url, "nope@webcaldav")


async def test_update_journal_not_found(journal_calendar):
    base, url = journal_calendar
    with pytest.raises(EventNotFoundError):
        await update_journal(
            base, USER, PASSWORD, url, "nope@webcaldav",
            title="x", start=date(2026, 6, 14), description=None,
        )
