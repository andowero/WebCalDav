import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import caldav

from .metrics import caldav_request_duration_seconds, caldav_request_errors_total

logger = logging.getLogger(__name__)

_COLOR_PROPS = [
    "{http://apple.com/ns/ical/}calendar-color",
    "{http://calendarserver.org/ns/}calendar-color",
]


class CalendarInfo(NamedTuple):
    caldav_id: str
    display_name: str
    color: str


def _sync_discover_calendars(url: str, username: str, password: str) -> list[CalendarInfo]:
    with caldav.DAVClient(url=url, username=username, password=password) as client:
        principal = client.principal()
        results: list[CalendarInfo] = []
        for cal in principal.calendars():
            name = str(cal.name) if cal.name else "Unnamed"
            color = "#3788d8"
            try:
                for prop in _COLOR_PROPS:
                    props = cal.get_properties([prop])
                    val = props.get(prop) if props else None
                    if val:
                        val = val.strip()
                        if not val.startswith("#"):
                            val = "#" + val
                        color = val
                        break
            except Exception:
                pass
            results.append(CalendarInfo(
                caldav_id=str(cal.url),
                display_name=name,
                color=color,
            ))
        return results


async def discover_calendars(url: str, username: str, password: str) -> list[CalendarInfo]:
    with caldav_request_duration_seconds.labels(operation="discover").time():
        try:
            return await asyncio.to_thread(_sync_discover_calendars, url, username, password)
        except Exception:
            caldav_request_errors_total.labels(operation="discover").inc()
            raise


def _dt_to_iso(dt: date | datetime) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return dt.isoformat()


def _sync_fetch_events(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    from_dt: datetime,
    to_dt: datetime,
    color: str,
) -> list[dict]:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        events = cal.search(start=from_dt, end=to_dt, event=True, expand=True)
        result: list[dict] = []
        for event in events:
            try:
                vi = event.vobject_instance
                for vevent in vi.components():
                    if vevent.name != "VEVENT":
                        continue
                    uid = str(vevent.uid.value) if hasattr(vevent, "uid") else str(event.url)
                    title = str(vevent.summary.value) if hasattr(vevent, "summary") else "(No title)"
                    dtstart = vevent.dtstart.value
                    all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
                    ev: dict = {
                        "id": uid,
                        "title": title,
                        "start": _dt_to_iso(dtstart),
                        "allDay": all_day,
                        "color": color,
                    }
                    if hasattr(vevent, "dtend"):
                        ev["end"] = _dt_to_iso(vevent.dtend.value)
                    elif hasattr(vevent, "duration"):
                        dur = vevent.duration.value
                        if isinstance(dur, timedelta):
                            ev["end"] = _dt_to_iso(dtstart + dur)  # type: ignore[arg-type]
                    result.append(ev)
            except Exception as e:
                logger.warning("Failed to parse event: %s", e)
        return result


async def fetch_events(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    from_dt: datetime,
    to_dt: datetime,
    color: str,
) -> list[dict]:
    with caldav_request_duration_seconds.labels(operation="fetch_events").time():
        try:
            return await asyncio.to_thread(
                _sync_fetch_events,
                account_url,
                username,
                password,
                calendar_url,
                from_dt,
                to_dt,
                color,
            )
        except Exception:
            caldav_request_errors_total.labels(operation="fetch_events").inc()
            raise
