import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import caldav
from caldav.elements.ical import CalendarColor
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent

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


_FREQ_WORDS = {
    "SECONDLY": "second",
    "MINUTELY": "minute",
    "HOURLY": "hour",
    "DAILY": "day",
    "WEEKLY": "week",
    "MONTHLY": "month",
    "YEARLY": "year",
}
_DAY_WORDS = {
    "MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu",
    "FR": "Fri", "SA": "Sat", "SU": "Sun",
}


def _rrule_to_text(rrule) -> str:
    """Render an icalendar vRecur into a short human-readable summary."""
    try:
        parts: dict[str, list[str]] = {}
        for key, val in rrule.items():
            vals = val if isinstance(val, list) else [val]
            parts[str(key).upper()] = [str(v) for v in vals]
    except Exception:
        return "Repeats"

    freq = (parts.get("FREQ") or ["?"])[0].upper()
    word = _FREQ_WORDS.get(freq, "time")
    try:
        interval = int((parts.get("INTERVAL") or ["1"])[0])
    except ValueError:
        interval = 1

    if interval == 1:
        text = {"day": "Daily", "week": "Weekly",
                "month": "Monthly", "year": "Yearly"}.get(word, f"Every {word}")
    else:
        text = f"Every {interval} {word}s"

    byday = parts.get("BYDAY")
    if byday:
        days = ", ".join(_DAY_WORDS.get(d[-2:].upper(), d) for d in byday)
        text += f" on {days}"

    count = parts.get("COUNT")
    until = parts.get("UNTIL")
    if count:
        text += f", {count[0]} times"
    elif until:
        text += f", until {until[0]}"
    return text


def _reminder_to_text(trigger) -> str:
    """Render a VALARM trigger (timedelta or datetime) into friendly text."""
    if isinstance(trigger, datetime):
        return f"At {trigger.isoformat()}"
    if not isinstance(trigger, timedelta):
        return "Reminder"
    total = int(trigger.total_seconds())
    if total == 0:
        return "At time of event"
    before = total < 0
    secs = abs(total)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    bits = []
    if days:
        bits.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        bits.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        bits.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    span = " ".join(bits) or "0 minutes"
    return f"{span} {'before' if before else 'after'}"


def _extract_reminders(vevent) -> list[str]:
    reminders: list[str] = []
    for alarm in vevent.walk("VALARM"):
        if "trigger" not in alarm:
            continue
        try:
            trigger = alarm.decoded("trigger")
        except Exception:
            continue
        reminders.append(_reminder_to_text(trigger))
    return reminders


def _extract_props(vevent) -> dict:
    """Pull description/location/recurrence/reminders from a VEVENT."""
    out: dict = {}
    desc = vevent.get("description")
    if desc:
        out["description"] = str(desc)
    loc = vevent.get("location")
    if loc:
        out["location"] = str(loc)
    rrule = vevent.get("rrule")
    if rrule:
        out["recurrence"] = _rrule_to_text(rrule)
    reminders = _extract_reminders(vevent)
    if reminders:
        out["reminders"] = reminders
    return out


def _master_meta(cal, from_dt: datetime, to_dt: datetime) -> dict[str, dict]:
    """Map UID -> props from unexpanded masters.

    The expanded search drops RRULE (and often VALARM) from each occurrence,
    so recurrence/reminders are recovered from the master components here.
    """
    meta: dict[str, dict] = {}
    try:
        masters = cal.search(start=from_dt, end=to_dt, event=True, expand=False)
    except Exception as e:
        logger.warning("master search failed url=%s: %s", cal.url, e)
        return meta
    for event in masters:
        try:
            for vevent in event.icalendar_instance.walk("VEVENT"):
                uid = str(vevent.get("uid")) if vevent.get("uid") else None
                if not uid:
                    continue
                props = _extract_props(vevent)
                if props:
                    meta.setdefault(uid, {}).update(props)
        except Exception as e:
            logger.warning("Failed to parse master event: %s", e)
    return meta


class RecurringEventError(Exception):
    """Raised when an edit is attempted on a recurring event (out of scope for v1)."""


class EventNotFoundError(Exception):
    """Raised when the target event UID is not present on the calendar."""


def _sync_fetch_events(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    from_dt: datetime,
    to_dt: datetime,
    color: str,
    calendar_id: int,
) -> list[dict]:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        events = cal.search(start=from_dt, end=to_dt, event=True, expand=True)
        logger.info(
            "caldav_search done url=%s from=%s to=%s raw_count=%d",
            calendar_url, from_dt.isoformat(), to_dt.isoformat(), len(events),
        )
        meta = _master_meta(cal, from_dt, to_dt)
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

                    # Instance props take priority; recurrence/reminders fall
                    # back to the master since expansion strips them.
                    inst = _extract_props(vevent)
                    master = meta.get(uid, {})
                    extended: dict = {"rawStart": ev["start"], "calendarId": calendar_id}
                    if "end" in ev:
                        extended["rawEnd"] = ev["end"]
                    for key in ("description", "location", "recurrence", "reminders"):
                        val = inst.get(key, master.get(key))
                        if val:
                            extended[key] = val
                    ev["extendedProps"] = extended

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
    calendar_id: int,
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
                calendar_id,
            )
        except Exception:
            caldav_request_errors_total.labels(operation="fetch_events").inc()
            raise


def _sync_update_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    all_day: bool,
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            event = cal.event_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e

        ical = event.icalendar_instance
        vevent = next((c for c in ical.walk("VEVENT")), None)
        if vevent is None:
            raise EventNotFoundError(uid)
        # v1 does not support editing recurring events; refuse rather than
        # silently rewriting the whole series.
        if vevent.get("rrule"):
            raise RecurringEventError(uid)

        def _replace(key: str, value) -> None:
            vevent.pop(key, None)
            if value is not None and value != "":
                vevent.add(key, value)

        _replace("summary", title)
        _replace("location", location)
        _replace("description", description)

        # Rewrite the time span; drop any DURATION so DTEND is authoritative.
        vevent.pop("dtstart", None)
        vevent.pop("dtend", None)
        vevent.pop("duration", None)
        vevent.add("dtstart", start)
        vevent.add("dtend", end)

        # Bump SEQUENCE so compliant servers accept the update.
        try:
            seq = int(vevent.get("sequence", 0)) + 1
        except (TypeError, ValueError):
            seq = 1
        vevent.pop("sequence", None)
        vevent.add("sequence", seq)
        _replace("last-modified", datetime.now(timezone.utc))

        event.data = ical.to_ical().decode("utf-8")
        event.save()


async def update_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    all_day: bool,
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
) -> None:
    with caldav_request_duration_seconds.labels(operation="update_event").time():
        try:
            await asyncio.to_thread(
                _sync_update_event,
                account_url,
                username,
                password,
                calendar_url,
                uid,
                title,
                all_day,
                start,
                end,
                location,
                description,
            )
        except (RecurringEventError, EventNotFoundError):
            raise
        except Exception:
            caldav_request_errors_total.labels(operation="update_event").inc()
            raise


def _sync_create_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    all_day: bool,
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        ical = ICalendar()
        ical.add("prodid", "-//WebCalDav//EN")
        ical.add("version", "2.0")
        vevent = IEvent()
        vevent.add("uid", uid)
        vevent.add("dtstamp", datetime.now(timezone.utc))
        if title:
            vevent.add("summary", title)
        vevent.add("dtstart", start)
        vevent.add("dtend", end)
        if location:
            vevent.add("location", location)
        if description:
            vevent.add("description", description)
        ical.add_component(vevent)
        cal.save_event(ical.to_ical().decode("utf-8"))


async def create_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    all_day: bool,
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
) -> None:
    with caldav_request_duration_seconds.labels(operation="create_event").time():
        try:
            await asyncio.to_thread(
                _sync_create_event,
                account_url,
                username,
                password,
                calendar_url,
                uid,
                title,
                all_day,
                start,
                end,
                location,
                description,
            )
        except Exception:
            caldav_request_errors_total.labels(operation="create_event").inc()
            raise


def _sync_delete_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            event = cal.event_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e
        event.delete()


async def delete_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
) -> None:
    with caldav_request_duration_seconds.labels(operation="delete_event").time():
        try:
            await asyncio.to_thread(
                _sync_delete_event,
                account_url,
                username,
                password,
                calendar_url,
                uid,
            )
        except EventNotFoundError:
            raise
        except Exception:
            caldav_request_errors_total.labels(operation="delete_event").inc()
            raise
