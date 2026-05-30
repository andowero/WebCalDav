import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import caldav
from caldav.elements.ical import CalendarColor

from .metrics import caldav_request_duration_seconds, caldav_request_errors_total

logger = logging.getLogger(__name__)


class CalendarInfo(NamedTuple):
    caldav_id: str
    display_name: str
    color: str


def _normalize_color(val: str | None) -> str | None:
    """Coerce a CalDAV color value to a 6-digit #rrggbb hex string.

    Radicale and Apple servers report colors as #rrggbbaa (8 hex digits);
    <input type="color"> only accepts #rrggbb, so drop the alpha channel.
    """
    if not val:
        return None
    val = val.strip()
    if not val.startswith("#"):
        val = "#" + val
    if len(val) == 9:  # #rrggbbaa -> #rrggbb
        val = val[:7]
    elif len(val) == 5:  # #rgba -> #rgb
        val = val[:4]
    if len(val) not in (4, 7):
        return None
    return val


def _sync_discover_calendars(url: str, username: str, password: str) -> list[CalendarInfo]:
    with caldav.DAVClient(url=url, username=username, password=password) as client:
        principal = client.principal()
        results: list[CalendarInfo] = []
        for cal in principal.calendars():
            try:
                display = cal.get_display_name()
            except Exception:
                display = None
            name = str(display) if display else "Unnamed"
            color = "#3788d8"
            try:
                tag = CalendarColor().tag
                props = cal.get_properties([CalendarColor()])
                val = _normalize_color(props.get(tag) if props else None)
                if val:
                    color = val
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
        logger.info(
            "caldav_search done url=%s from=%s to=%s raw_count=%d",
            calendar_url, from_dt.isoformat(), to_dt.isoformat(), len(events),
        )
        result: list[dict] = []
        for event in events:
            try:
                ical = event.icalendar_instance
                for vevent in ical.walk("VEVENT"):
                    if "dtstart" not in vevent:
                        continue
                    uid = str(vevent.get("uid")) if vevent.get("uid") else str(event.url)
                    summary = vevent.get("summary")
                    title = str(summary) if summary else "(No title)"
                    dtstart = vevent.decoded("dtstart")
                    all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
                    ev: dict = {
                        "id": uid,
                        "title": title,
                        "start": _dt_to_iso(dtstart),
                        "allDay": all_day,
                        "color": color,
                    }
                    if "dtend" in vevent:
                        ev["end"] = _dt_to_iso(vevent.decoded("dtend"))
                    elif "duration" in vevent:
                        dur = vevent.decoded("duration")
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
