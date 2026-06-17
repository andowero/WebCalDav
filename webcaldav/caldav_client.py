import asyncio
import ipaddress
import logging
import socket
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import caldav
from caldav.elements.ical import CalendarColor
from dateutil.rrule import rrulestr
from icalendar import Alarm as IAlarm
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent
from icalendar import Todo as ITodo
from icalendar.prop import vRecur

from .metrics import caldav_request_duration_seconds, caldav_request_errors_total

logger = logging.getLogger(__name__)


class CalendarInfo(NamedTuple):
    caldav_id: str
    display_name: str
    color: str


class UnsafeURLError(ValueError):
    """Raised when a CalDAV URL targets a disallowed (private/internal) address."""


def _ip_is_unsafe(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Unwrap IPv4-mapped IPv6 (::ffff:127.0.0.1) so the v4 checks apply.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254.0.0/16 — covers the cloud metadata IP
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_caldav_url(url: str) -> None:
    """Reject CalDAV URLs that target non-public addresses (SSRF guard).

    Resolves the hostname and rejects if any resolved address is private,
    loopback, link-local (incl. 169.254.169.254), reserved, multicast, or
    unspecified. Raises UnsafeURLError on any violation.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"unsupported scheme: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("missing host")
    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"could not resolve host: {host}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise UnsafeURLError(f"could not resolve host: {host}")
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise UnsafeURLError(f"unparseable address: {addr}")
        if _ip_is_unsafe(ip):
            raise UnsafeURLError(f"address not allowed: {addr}")


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


def _rrule_to_text(rrule: Any) -> str:
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


def _rrule_to_struct(rrule: Any, dtstart: date | datetime) -> dict[str, Any]:
    """Render an icalendar vRecur into the editor's structured recurrence model."""
    parts = {str(k).upper(): (v if isinstance(v, list) else [v]) for k, v in rrule.items()}
    out: dict[str, Any] = {"freq": str((parts.get("FREQ") or ["DAILY"])[0]).lower(), "interval": 1}
    try:
        out["interval"] = int((parts.get("INTERVAL") or ["1"])[0])
    except (ValueError, TypeError):
        pass
    if out["freq"] == "monthly":
        byday = parts.get("BYDAY")
        if byday:
            token = str(byday[0])  # e.g. "2MO" or "-1FR"
            out["monthly_mode"] = "weekday"
            try:
                out["ordinal"] = int(token[:-2])
            except ValueError:
                out["ordinal"] = None
        else:
            out["monthly_mode"] = "monthday"
    count = parts.get("COUNT")
    until = parts.get("UNTIL")
    if count:
        try:
            out["count"] = int(count[0])
        except (ValueError, TypeError):
            pass
    elif until:
        u = until[0]
        out["until"] = u.isoformat() if hasattr(u, "isoformat") else str(u)
    return out


def preview_recurrence(start: date | datetime, rule: dict[str, Any]) -> tuple[str | None, int | None]:
    """Last occurrence ISO + total count for a rule, or (None, None) if infinite."""
    parts = _build_rrule(rule, start)
    robj = rrulestr(vRecur(parts).to_ical().decode("utf-8"), dtstart=_as_dt(start))
    if "COUNT" not in parts and "UNTIL" not in parts:
        return None, None
    occs = list(robj)
    if not occs:
        return None, 0
    last = occs[-1]
    return (last.date().isoformat() if _is_all_day(start) else last.isoformat()), len(occs)


def _reminder_to_text(trigger: Any) -> str:
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


def _classify_alarm(alarm: Any, all_day: bool) -> tuple[timedelta, str] | None:
    """The (offset, RELATED) if this VALARM fits the editable reminder model.

    Editable: a duration TRIGGER (relative to DTSTART or DTEND, either sign) with
    a non-EMAIL action. The offset sign carries direction and RELATED carries the
    anchor; both round-trip through the four-way reminder editor. Only absolute
    datetime triggers and email alarms stay read-only — rewriting those as a
    DISPLAY reminder would lose data.
    """
    if "trigger" not in alarm:
        return None
    try:
        trigger = alarm.decoded("trigger")
    except Exception:
        return None
    if not isinstance(trigger, timedelta):
        return None
    try:
        prop = alarm["trigger"]
        if isinstance(prop, list):
            prop = prop[0]
        related = str(prop.params.get("RELATED", "START")).upper()
    except Exception:
        return None
    if related not in ("START", "END"):
        related = "START"
    if str(alarm.get("action", "DISPLAY")).upper() == "EMAIL":
        return None
    return trigger, related


def _add_anchor_direction(out: dict[str, Any], td: timedelta, related: str) -> dict[str, Any]:
    """Tag a reminder dict with anchor/direction, omitting the start/before
    defaults so legacy "before start" payloads stay byte-for-byte unchanged."""
    if related == "END":
        out["anchor"] = "end"
    if td.total_seconds() > 0:
        out["direction"] = "after"
    return out


def _timedelta_to_value_unit(td: timedelta, related: str) -> dict[str, Any]:
    """Trigger offset -> {value, unit, anchor?, direction?}, largest unit that fits."""
    minutes = round(abs(td.total_seconds()) / 60)
    if minutes and minutes % 10080 == 0:
        out = {"value": minutes // 10080, "unit": "weeks"}
    elif minutes and minutes % 1440 == 0:
        out = {"value": minutes // 1440, "unit": "days"}
    elif minutes and minutes % 60 == 0:
        out = {"value": minutes // 60, "unit": "hours"}
    else:
        out = {"value": minutes, "unit": "minutes"}
    return _add_anchor_direction(out, td, related)


def _timedelta_to_allday_parts(td: timedelta, related: str) -> dict[str, Any]:
    """All-day trigger offset -> {value, unit, time, anchor, direction}.

    The DATE anchor is midnight, so the offset splits into whole days plus a time
    of day. Python's modulo keeps the time non-negative, and the day index sign
    gives the direction: -P13DT15H -> 14 days before at 09:00, +PT9H -> on the
    day (0 days after) at 09:00, +P1DT9H -> 1 day after at 09:00.
    """
    trigger_min = round(td.total_seconds() / 60)
    time_min = trigger_min % 1440
    day_index = (trigger_min - time_min) // 1440
    days = abs(day_index)
    hhmm = f"{time_min // 60:02d}:{time_min % 60:02d}"
    if days > 0 and days % 7 == 0:
        out = {"value": days // 7, "unit": "weeks", "time": hhmm}
    else:
        out = {"value": days, "unit": "days", "time": hhmm}
    # day_index 0 is "on the day"; only a positive index is genuinely "after".
    if related == "END":
        out["anchor"] = "end"
    if day_index > 0:
        out["direction"] = "after"
    return out


def _extract_reminders(vevent: Any) -> list[dict[str, Any]]:
    try:
        dtstart = vevent.decoded("dtstart")
    except Exception:
        dtstart = None
    all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
    reminders: list[dict[str, Any]] = []
    for alarm in vevent.walk("VALARM"):
        if "trigger" not in alarm:
            continue
        editable = _classify_alarm(alarm, all_day)
        if editable is not None:
            offset, related = editable
            if all_day:
                reminders.append(_timedelta_to_allday_parts(offset, related))
            else:
                reminders.append(_timedelta_to_value_unit(offset, related))
            continue
        try:
            trigger = alarm.decoded("trigger")
        except Exception:
            continue
        entry: dict[str, Any] = {"text": _reminder_to_text(trigger), "readonly": True}
        # Absolute datetime triggers also carry the ISO instant so the client
        # can format it per the user's date/time-format settings.
        if isinstance(trigger, datetime):
            entry["at"] = _dt_to_iso(trigger)
        reminders.append(entry)
    return reminders


def _apply_alarms(
    vevent: Any, triggers: list[tuple[timedelta, str]] | None, end_key: str = "dtend"
) -> None:
    """Replace the VEVENT's editable VALARMs with one DISPLAY alarm per trigger.

    ``None`` means "leave alarms alone" (drag/resize updates never touch them);
    an empty list deletes all editable alarms. Each trigger is an (offset,
    RELATED) pair; END offsets need a DTEND/DURATION, so an END trigger on an
    event without one falls back to START. Alarms outside the editable model
    (see ``_classify_alarm``) always survive.
    """
    if triggers is None:
        return
    try:
        dtstart = vevent.decoded("dtstart")
    except Exception:
        dtstart = None
    all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
    has_end = end_key in vevent or "duration" in vevent
    for comp in list(vevent.subcomponents):
        if comp.name == "VALARM" and _classify_alarm(comp, all_day) is not None:
            vevent.subcomponents.remove(comp)
    for trig, related in triggers:
        alarm = IAlarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", "Reminder")
        if related == "END" and has_end:
            alarm.add("trigger", trig, parameters={"RELATED": "END"})
        else:
            alarm.add("trigger", trig)
        vevent.add_component(alarm)


def _extract_props(vevent: Any) -> dict[str, Any]:
    """Pull description/location/recurrence/reminders from a VEVENT."""
    out: dict[str, Any] = {}
    desc = vevent.get("description")
    if desc:
        out["description"] = str(desc)
    loc = vevent.get("location")
    if loc:
        out["location"] = str(loc)
    rrule = vevent.get("rrule")
    if rrule:
        out["recurrence"] = _rrule_to_text(rrule)
        try:
            out["recurrenceRule"] = _rrule_to_struct(rrule, vevent.decoded("dtstart"))
        except Exception:
            pass
    reminders = _extract_reminders(vevent)
    if reminders:
        out["reminders"] = reminders
    return out


class _Kind(NamedTuple):
    """A VCALENDAR component flavour. VEVENT and VTODO share almost all of the
    recurrence/override/reminder machinery; the few divergences (component name,
    the "end" property, the icalendar class, and the caldav search flag) are
    captured here so the shared helpers can serve both."""

    name: str  # "VEVENT" / "VTODO"
    end_key: str  # "dtend" / "due"
    make: Callable[[], Any]  # IEvent / ITodo
    search_kw: str  # "event" / "todo"


_EVENT = _Kind("VEVENT", "dtend", IEvent, "event")
_TODO = _Kind("VTODO", "due", ITodo, "todo")


def _master_meta(
    cal: Any, from_dt: datetime, to_dt: datetime, kind: _Kind = _EVENT
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], list[Any]]]:
    """(UID -> master props, (UID, recurrence id) -> override reminders).

    The expanded search drops RRULE (and often VALARM) from each occurrence,
    so recurrence/reminders are recovered from the unexpanded components here.
    Override props stay out of the master map — an override's own alarms must
    not leak to sibling occurrences via the fallback.
    """
    meta: dict[str, dict[str, Any]] = {}
    override_reminders: dict[tuple[str, str], list[Any]] = {}
    try:
        masters = cal.search(start=from_dt, end=to_dt, expand=False, **{kind.search_kw: True})
    except Exception as e:
        logger.warning("master search failed url=%s: %s", cal.url, e)
        return meta, override_reminders
    for event in masters:
        try:
            for vevent in event.icalendar_instance.walk(kind.name):
                uid = str(vevent.get("uid")) if vevent.get("uid") else None
                if not uid:
                    continue
                if "recurrence-id" in vevent:
                    rid = _dt_to_iso(vevent.decoded("recurrence-id"))
                    reminders = _extract_reminders(vevent)
                    if reminders:
                        override_reminders[(uid, rid)] = reminders
                    continue
                props = _extract_props(vevent)
                if props:
                    meta.setdefault(uid, {}).update(props)
        except Exception as e:
            logger.warning("Failed to parse master event: %s", e)
    return meta, override_reminders


class EventNotFoundError(Exception):
    """Raised when the target event UID is not present on the calendar."""


# ── Recurrence math ──────────────────────────────────────────────────────────
#
# Scoped recurring operations pivot on a single occurrence, identified by its
# original start ("recurrence id"). dateutil.rrule does the occurrence math; the
# helpers below translate between the master VEVENT and that engine, and mutate
# the master's RRULE/DTSTART in place for truncate/shift operations.


def _master_vevent(ical: Any, name: str = "VEVENT") -> Any:
    """The series master component (the one without a RECURRENCE-ID)."""
    comps = list(ical.walk(name))
    for v in comps:
        if "recurrence-id" not in v:
            return v
    return comps[0] if comps else None


def _as_dt(d: date | datetime) -> datetime:
    """Coerce a date/datetime to a datetime for rrule math (all-day -> midnight)."""
    if isinstance(d, datetime):
        return d
    return datetime(d.year, d.month, d.day)


def _is_all_day(d: date | datetime) -> bool:
    return isinstance(d, date) and not isinstance(d, datetime)


def _occurrence_dt(recurrence_id: str, dtstart: date | datetime) -> date | datetime:
    """Coerce the pivot ISO string into dtstart's value type / timezone."""
    if isinstance(dtstart, datetime):
        dt = datetime.fromisoformat(recurrence_id)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dtstart.tzinfo or timezone.utc)
        elif dtstart.tzinfo is not None:
            dt = dt.astimezone(dtstart.tzinfo)
        return dt
    return date.fromisoformat(recurrence_id[:10])


def _rrule_text(vevent: Any) -> str | None:
    rr = vevent.get("rrule")
    if not rr:
        return None
    return str(rr.to_ical().decode("utf-8"))


def _rrule_parts(vevent: Any) -> dict[str, Any]:
    """RRULE as a plain {NAME: [values]} dict that can be re-added via vevent.add."""
    rr = vevent.get("rrule")
    return {str(k): (list(v) if isinstance(v, list) else [v]) for k, v in rr.items()}


def _set_rrule(vevent: Any, parts: dict[str, Any]) -> None:
    vevent.pop("rrule", None)
    vevent.add("rrule", parts)


def _shift_until(vevent: Any, delta: timedelta) -> None:
    """Shift an RRULE UNTIL bound by ``delta`` (no-op for COUNT/infinite rules).

    Moving a whole series by dragging one occurrence shifts DTSTART; an UNTIL
    bound must move with it, or occurrences past the (stationary) UNTIL silently
    vanish.
    """
    if not delta:
        return
    parts = _rrule_parts(vevent)
    if "UNTIL" not in parts:
        return
    try:
        parts["UNTIL"] = [b + delta for b in parts["UNTIL"]]
    except TypeError:
        return
    _set_rrule(vevent, parts)


def _count_through(vevent: Any, pivot: date | datetime, inc: bool = True) -> int:
    """Number of occurrences from the series start through the pivot."""
    base = _as_dt(vevent.decoded("dtstart"))
    return len(rrulestr(_rrule_text(vevent), dtstart=base).between(base, _as_dt(pivot), inc=inc))


def _truncate_until(vevent: Any, pivot: date | datetime) -> None:
    """Cap the series so the pivot and every later occurrence are dropped.

    UNTIL is set to the *last actual occurrence strictly before the pivot*, not
    ``pivot - epsilon``. The editor's end-by-date field is date-granular, so a
    mid-day UNTIL on the pivot's own day would round-trip to end-of-day on the
    next "all" edit and silently re-admit the pivot occurrence into the series.
    """
    parts = _rrule_parts(vevent)
    parts.pop("COUNT", None)
    dtstart = vevent.decoded("dtstart")
    base = _as_dt(dtstart)
    last = rrulestr(_rrule_text(vevent), dtstart=base).before(_as_dt(pivot), inc=False)
    until: date | datetime
    if last is None:
        # No occurrence before the pivot (callers guard against this); fall back.
        if isinstance(pivot, datetime):
            until = pivot.astimezone(timezone.utc) - timedelta(seconds=1)
        else:
            until = pivot - timedelta(days=1)
    elif _is_all_day(dtstart):
        until = last.date()
    else:
        until = last.astimezone(timezone.utc)
    parts["UNTIL"] = [until]
    _set_rrule(vevent, parts)


def _add_exdate(vevent: Any, pivot: date | datetime) -> None:
    vevent.add("exdate", pivot)


def _exdates(vevent: Any) -> list[Any]:
    """All EXDATE exclusion points as a flat list of date/datetime values."""
    prop = vevent.get("exdate")
    if not prop:
        return []
    props = prop if isinstance(prop, list) else [prop]
    return [d.dt for p in props for d in p.dts]


def _set_exdates(vevent: Any, dts: Any) -> None:
    vevent.pop("exdate", None)
    for d in dts:
        vevent.add("exdate", d)


def _shift_exdate(vevent: Any, delta: timedelta) -> None:
    """Shift EXDATE exclusion points by ``delta`` to track a whole-series move.

    A deleted occurrence is recorded as an EXDATE at its original time. When the
    series start shifts, every generated slot moves; the EXDATE must move with it
    or it stops matching any occurrence and the deleted day silently reappears.
    """
    if not delta:
        return
    ex = _exdates(vevent)
    if ex:
        _set_exdates(vevent, [d + delta for d in ex])


_FREQ_MAP = {
    "yearly": "YEARLY", "monthly": "MONTHLY", "weekly": "WEEKLY",
    "daily": "DAILY", "hourly": "HOURLY",
}
_WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _build_rrule(rule: dict[str, Any], dtstart: date | datetime) -> dict[str, Any]:
    """Translate the editor's recurrence model into an icalendar RRULE dict.

    Monthly has two modes: ``monthday`` keeps the day of month (falling back to
    the last day for days >= 29, which February etc. cannot satisfy), and
    ``weekday`` schedules the Nth / last weekday of the month (BYDAY=2MO, -1FR).
    ``count`` and ``until`` are mutually exclusive; ``count`` wins if both arrive.
    """
    freq = _FREQ_MAP.get(str(rule.get("freq", "")).lower())
    if not freq:
        raise ValueError(f"unsupported recurrence frequency: {rule.get('freq')!r}")
    parts: dict[str, Any] = {"FREQ": freq}
    interval = int(rule.get("interval") or 1)
    if interval > 1:
        parts["INTERVAL"] = interval

    if freq == "MONTHLY":
        if (rule.get("monthly_mode") or "monthday") == "weekday":
            anchor = _as_dt(dtstart)
            ordinal = rule.get("ordinal")
            if ordinal is None:
                ordinal = (anchor.day - 1) // 7 + 1
            parts["BYDAY"] = f"{int(ordinal)}{_WEEKDAYS[anchor.weekday()]}"
        else:
            day = _as_dt(dtstart).day
            parts["BYMONTHDAY"] = -1 if day >= 29 else day

    count = rule.get("count")
    until = rule.get("until")
    if count:
        parts["COUNT"] = int(count)
    elif until:
        if _is_all_day(dtstart):
            parts["UNTIL"] = date.fromisoformat(str(until)[:10])
        else:
            u = datetime.fromisoformat(str(until))
            if u.tzinfo is None:
                u = u.replace(tzinfo=timezone.utc)
            parts["UNTIL"] = u.astimezone(timezone.utc)
    return parts


def _remaining_rule_parts(vevent: Any, pivot: date | datetime) -> dict[str, Any]:
    """Original rule, with COUNT reduced by the occurrences before the pivot."""
    parts = _rrule_parts(vevent)
    if "COUNT" in parts:
        # Occurrences strictly before the pivot (the pivot itself stays).
        before = _count_through(vevent, pivot, inc=True) - 1
        try:
            parts["COUNT"] = [max(1, int(parts["COUNT"][0]) - before)]
        except (ValueError, IndexError):
            pass
    return parts


def _apply_fields(
    vevent: Any,
    title: str,
    start: date | datetime | None,
    end: date | datetime | None,
    location: str | None,
    description: str | None,
    kind: _Kind = _EVENT,
) -> None:
    """Overwrite a component's editable fields + time span, bumping SEQUENCE.

    ``start``/``end`` may be ``None`` for tasks (VTODO needs neither DTSTART nor
    DUE); a ``None`` clears the property rather than re-adding it."""
    def _replace(key: str, value: Any) -> None:
        vevent.pop(key, None)
        if value is not None and value != "":
            vevent.add(key, value)

    _replace("summary", title)
    _replace("location", location)
    _replace("description", description)
    vevent.pop("dtstart", None)
    vevent.pop(kind.end_key, None)
    vevent.pop("duration", None)
    if start is not None:
        vevent.add("dtstart", start)
    if end is not None:
        vevent.add(kind.end_key, end)
    try:
        seq = int(vevent.get("sequence", 0)) + 1
    except (TypeError, ValueError):
        seq = 1
    vevent.pop("sequence", None)
    vevent.add("sequence", seq)
    _replace("last-modified", datetime.now(timezone.utc))


def _upsert_override(
    ical: Any,
    master: Any,
    pivot: date | datetime,
    title: str,
    start: date | datetime | None,
    end: date | datetime | None,
    location: str | None,
    description: str | None,
    reminders: list[tuple[timedelta, str]] | None = None,
    kind: _Kind = _EVENT,
    status: str | None = None,
    completed: datetime | None = None,
) -> None:
    """Add/replace a detached single-occurrence override (RECURRENCE-ID = pivot)."""
    for comp in list(ical.subcomponents):
        if comp.name == kind.name and "recurrence-id" in comp:
            try:
                if comp.decoded("recurrence-id") == pivot:
                    ical.subcomponents.remove(comp)
            except Exception:
                pass
    ov = kind.make()
    ov.add("uid", str(master.get("uid")))
    ov.add("recurrence-id", pivot)
    ov.add("dtstamp", datetime.now(timezone.utc))
    if title:
        ov.add("summary", title)
    if start is not None:
        ov.add("dtstart", start)
    if end is not None:
        ov.add(kind.end_key, end)
    if location:
        ov.add("location", location)
    if description:
        ov.add("description", description)
    if status:
        ov.add("status", status)
    if completed is not None:
        ov.add("completed", completed)
        ov.add("percent-complete", 100)
    _apply_alarms(ov, reminders, kind.end_key)
    ical.add_component(ov)


def _overrides(ical: Any, name: str = "VEVENT") -> list[Any]:
    """Detached single-occurrence overrides (those with a RECURRENCE-ID)."""
    return [
        c for c in ical.subcomponents
        if c.name == name and "recurrence-id" in c
    ]


def _shift_override(
    ve: Any, delta: timedelta, new_uid: str | None = None, kind: _Kind = _EVENT
) -> None:
    """Relocate a detached override by ``delta`` (and optionally re-key its UID).

    Only the recurrence id and time span move; the override's own customized
    text fields (summary/location/description) are intentionally left alone so a
    scoped edit on a *sibling* occurrence never clobbers them.
    """
    if new_uid is not None:
        ve.pop("uid", None)
        ve.add("uid", new_uid)
    if not delta:
        return
    for key in ("recurrence-id", "dtstart", kind.end_key):
        if key in ve:
            val = ve.decoded(key)
            ve.pop(key, None)
            ve.add(key, val + delta)


def _pop_overrides(
    ical: Any, keep: Callable[[Any], bool], name: str = "VEVENT"
) -> list[Any]:
    """Remove overrides whose recurrence id fails ``keep(rid)``; return the removed.

    ``keep`` receives the decoded RECURRENCE-ID; overrides it rejects are
    detached from ``ical`` (to migrate elsewhere) and returned in document order.
    """
    removed = []
    for comp in _overrides(ical, name):
        try:
            rid = comp.decoded("recurrence-id")
        except Exception:
            continue
        if not keep(rid):
            ical.subcomponents.remove(comp)
            removed.append(comp)
    return removed


def _series_ical(
    uid: str,
    title: str,
    start: date | datetime | None,
    end: date | datetime | None,
    location: str | None,
    description: str | None,
    rule_parts: dict[str, Any] | None,
    overrides: list[Any] | None = None,
    exdates: list[Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
    alarms: list[Any] | None = None,
    kind: _Kind = _EVENT,
    status: str | None = None,
    priority: int | None = None,
) -> str:
    ical = ICalendar()
    ical.add("prodid", "-//WebCalDav//EN")
    ical.add("version", "2.0")
    ve = kind.make()
    ve.add("uid", uid)
    ve.add("dtstamp", datetime.now(timezone.utc))
    if title:
        ve.add("summary", title)
    if start is not None:
        ve.add("dtstart", start)
    if end is not None:
        ve.add(kind.end_key, end)
    if location:
        ve.add("location", location)
    if description:
        ve.add("description", description)
    if status:
        ve.add("status", status)
    if priority is not None:
        ve.add("priority", priority)
    if rule_parts:
        ve.add("rrule", rule_parts)
    for d in exdates or []:
        ve.add("exdate", d)
    for a in alarms or []:
        ve.add_component(a)
    _apply_alarms(ve, reminders, kind.end_key)
    ical.add_component(ve)
    for ov in overrides or []:
        ical.add_component(ov)
    return str(ical.to_ical().decode("utf-8"))


def _sync_fetch_events(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    from_dt: datetime,
    to_dt: datetime,
    color: str,
    calendar_id: int,
) -> list[dict[str, Any]]:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        events = cal.search(start=from_dt, end=to_dt, event=True, expand=True)
        logger.info(
            "caldav_search done url=%s from=%s to=%s raw_count=%d",
            calendar_url, from_dt.isoformat(), to_dt.isoformat(), len(events),
        )
        meta, override_reminders = _master_meta(cal, from_dt, to_dt)

        # Slots covered by a detached override (keyed by uid + its RECURRENCE-ID).
        # Some servers' expand still emits the master-generated occurrence at that
        # slot alongside the moved override, which would show as a duplicate; the
        # override wins, so suppress the plain occurrence at the same slot below.
        overridden: set[tuple[str, str]] = set()
        for event in events:
            try:
                for vevent in event.icalendar_instance.walk("VEVENT"):
                    if "recurrence-id" not in vevent:
                        continue
                    uid = str(vevent.get("uid")) if vevent.get("uid") else str(event.url)
                    overridden.add((uid, _dt_to_iso(vevent.decoded("recurrence-id"))))
            except Exception as e:
                logger.warning("Failed to scan event for overrides: %s", e)

        result: list[dict[str, Any]] = []
        for event in events:
            try:
                ical = event.icalendar_instance
                for vevent in ical.walk("VEVENT"):
                    if "dtstart" not in vevent:
                        continue
                    uid = str(vevent.get("uid")) if vevent.get("uid") else str(event.url)
                    # Drop a plain occurrence that an override already covers.
                    if "recurrence-id" not in vevent and (uid, _dt_to_iso(vevent.decoded("dtstart"))) in overridden:
                        continue
                    summary = vevent.get("summary")
                    title = str(summary) if summary else "(No title)"
                    dtstart = vevent.decoded("dtstart")
                    all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
                    ev: dict[str, Any] = {
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
                            ev["end"] = _dt_to_iso(dtstart + dur)

                    # Instance props take priority; recurrence/reminders fall
                    # back to the master since expansion strips them.
                    inst = _extract_props(vevent)
                    master = meta.get(uid, {})
                    extended: dict[str, Any] = {"rawStart": ev["start"], "calendarId": calendar_id}
                    if "end" in ev:
                        extended["rawEnd"] = ev["end"]
                    # Detached overrides carry a stable RECURRENCE-ID that does not
                    # change when the occurrence is moved; it is the pivot the
                    # server keys overrides on, so expose it for scoped edits.
                    if "recurrence-id" in vevent:
                        rid = _dt_to_iso(vevent.decoded("recurrence-id"))
                        extended["recurrenceId"] = rid
                        # Expansion may strip the override's VALARMs as well;
                        # recover them from the unexpanded override component.
                        if "reminders" not in inst and (uid, rid) in override_reminders:
                            inst["reminders"] = override_reminders[(uid, rid)]
                    for key in (
                        "description", "location", "recurrence", "recurrenceRule", "reminders",
                    ):
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
) -> list[dict[str, Any]]:
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


def _sync_fetch_sync_token(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
) -> str:
    """Return a change-detection token for a calendar.

    Uses the caldav lib's sync-token machinery. Radicale lacks RFC 6578
    sync-collection, so the lib falls back to a "fake-" token hashed from all
    object ETags — it still changes whenever any event is added/edited/removed,
    and only ETags (not event bodies) are fetched. Used to skip event refetches
    when nothing changed.
    """
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        sync = cal.get_objects_by_sync_token(load_objects=False)
        return str(sync.sync_token)


async def fetch_sync_token(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
) -> str:
    with caldav_request_duration_seconds.labels(operation="fetch_sync_token").time():
        try:
            return await asyncio.to_thread(
                _sync_fetch_sync_token,
                account_url,
                username,
                password,
                calendar_url,
            )
        except Exception:
            caldav_request_errors_total.labels(operation="fetch_sync_token").inc()
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
    scope: str = "all",
    recurrence_id: str | None = None,
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            event = cal.event_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e

        ical = event.icalendar_instance
        master = _master_vevent(ical)
        if master is None:
            raise EventNotFoundError(uid)

        is_recurring = bool(master.get("rrule"))
        # A scoped op needs a pivot; without one (or on a plain event) treat as
        # a whole-event edit.
        if not is_recurring or not recurrence_id:
            scope = "all"

        if scope == "all":
            # The client edits one occurrence; for the whole series apply that as
            # a delta to the master so the anchor (and thus DTSTART) is preserved
            # when only non-time fields change.
            anchor_start = start
            anchor_end = end
            if is_recurring and recurrence_id:
                pivot = _occurrence_dt(recurrence_id, master.decoded("dtstart"))
                delta = _as_dt(start) - _as_dt(pivot)
                old_start = master.decoded("dtstart")
                anchor_start = old_start + delta
                anchor_end = anchor_start + (_as_dt(end) - _as_dt(start))
                # A whole-series time shift moves every generated slot; carry the
                # detached overrides along (times only) so they stay bound and
                # keep their own customized fields rather than orphaning.
                for ov in _overrides(ical):
                    _shift_override(ov, delta)
                _shift_exdate(master, delta)
            _apply_fields(master, title, anchor_start, anchor_end, location, description)
            _apply_alarms(master, reminders)
            if rrule is not None:
                _set_rrule(master, _build_rrule(rrule, anchor_start))
            elif is_recurring and recurrence_id:
                # No new rule supplied (e.g. a drag): keep the existing RRULE but
                # carry its UNTIL bound along with the shifted DTSTART.
                _shift_until(master, delta)
            event.data = ical.to_ical().decode("utf-8")
            event.save()
            return

        assert recurrence_id is not None  # scope != "all" implies a pivot (see above)
        pivot = _occurrence_dt(recurrence_id, master.decoded("dtstart"))

        if scope == "this":
            # Detach just this occurrence as a RECURRENCE-ID override.
            _upsert_override(
                ical, master, pivot, title, start, end, location, description,
                reminders=reminders,
            )
            event.data = ical.to_ical().decode("utf-8")
            event.save()
            return

        if scope == "thisfuture":
            base = _as_dt(master.decoded("dtstart"))
            new_rule = _build_rrule(rrule, start) if rrule else _remaining_rule_parts(master, pivot)
            if _as_dt(pivot) <= base:
                # Pivot is the first occurrence: just rewrite the whole series.
                # A start shift moves every slot, so carry the overrides with it.
                for ov in _overrides(ical):
                    _shift_override(ov, start - base)
                _shift_exdate(master, start - base)
                _apply_fields(master, title, start, end, location, description)
                _apply_alarms(master, reminders)
                _set_rrule(master, new_rule)
                event.data = ical.to_ical().decode("utf-8")
                event.save()
                return
            # Cap the original before the pivot, then spin off a fresh series
            # carrying the edited fields for the pivot and everything after it.
            # Overrides at/after the pivot belong to that new series, rebased by
            # the start delta; ones before the pivot stay with the old master.
            new_uid = f"{uuid.uuid4()}@webcaldav"
            migrated = _pop_overrides(ical, keep=lambda rid: _as_dt(rid) < _as_dt(pivot))
            for ov in migrated:
                _shift_override(ov, _as_dt(start) - _as_dt(pivot), new_uid=new_uid)
            old_ex = _exdates(master)
            _set_exdates(master, [d for d in old_ex if _as_dt(d) < _as_dt(pivot)])
            migrated_ex = [d + (_as_dt(start) - _as_dt(pivot)) for d in old_ex if _as_dt(d) >= _as_dt(pivot)]
            _truncate_until(master, pivot)
            event.data = ical.to_ical().decode("utf-8")
            event.save()
            # The new series inherits the master's alarms; _apply_alarms then
            # swaps the editable ones for the requested set (or keeps them all
            # when reminders is None, e.g. a drag).
            carried = [c for c in master.subcomponents if c.name == "VALARM"]
            cal.save_event(_series_ical(
                new_uid, title, start, end, location, description, new_rule,
                overrides=migrated, exdates=migrated_ex, reminders=reminders,
                alarms=carried,
            ))
            return

        # Unknown scope: fail safe by leaving the event untouched.
        raise ValueError(f"unknown scope: {scope!r}")


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
    scope: str = "all",
    recurrence_id: str | None = None,
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
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
                scope,
                recurrence_id,
                rrule,
                reminders,
            )
        except EventNotFoundError:
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
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        rule_parts = _build_rrule(rrule, start) if rrule else None
        cal.save_event(_series_ical(
            uid, title, start, end, location, description, rule_parts,
            reminders=reminders,
        ))


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
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
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
                rrule,
                reminders,
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
    scope: str = "all",
    recurrence_id: str | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            event = cal.event_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e

        ical = event.icalendar_instance
        master = _master_vevent(ical)
        # Whole-series delete, or a non-recurring event: drop the resource.
        if scope == "all" or master is None or not master.get("rrule") or not recurrence_id:
            event.delete()
            return

        pivot = _occurrence_dt(recurrence_id, master.decoded("dtstart"))
        base = _as_dt(master.decoded("dtstart"))

        if scope == "this":
            _add_exdate(master, pivot)
        elif scope == "thisfuture":
            if _as_dt(pivot) <= base:  # pivot is the first occurrence -> series gone
                event.delete()
                return
            _truncate_until(master, pivot)
            # Drop now-orphaned overrides at/after the pivot: their slots no
            # longer exist on the shortened master.
            _pop_overrides(ical, keep=lambda rid: _as_dt(rid) < _as_dt(pivot))
        else:
            event.delete()
            return

        event.data = ical.to_ical().decode("utf-8")
        event.save()


async def delete_event(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    scope: str = "all",
    recurrence_id: str | None = None,
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
                scope,
                recurrence_id,
            )
        except EventNotFoundError:
            raise
        except Exception:
            caldav_request_errors_total.labels(operation="delete_event").inc()
            raise


# ── Tasks (VTODO) ─────────────────────────────────────────────────────────────
#
# Tasks reuse the whole recurrence/override/reminder toolkit above via the _TODO
# kind. The orchestration below mirrors the event functions but talks to the
# caldav lib's todo_by_uid/save_todo/get_todos, anchors on DUE (falling back to
# DTSTART), tolerates undated tasks, and carries the VTODO-only STATUS / COMPLETED
# / PERCENT-COMPLETE / PRIORITY properties.


def _task_completed(vtodo: Any) -> bool:
    if str(vtodo.get("status") or "").upper() == "COMPLETED":
        return True
    if "completed" in vtodo:
        return True
    try:
        return int(vtodo.get("percent-complete") or 0) >= 100
    except (TypeError, ValueError):
        return False


def _extract_task_props(vtodo: Any) -> dict[str, Any]:
    """description/location/recurrence/reminders (shared) + VTODO-only props."""
    out = _extract_props(vtodo)
    prio = vtodo.get("priority")
    if prio is not None:
        try:
            out["priority"] = int(prio)
        except (TypeError, ValueError):
            pass
    return out


def _set_status(comp: Any, completed: bool) -> None:
    """Mark a VTODO component done/undone in place."""
    comp.pop("status", None)
    comp.pop("completed", None)
    comp.pop("percent-complete", None)
    if completed:
        comp.add("status", "COMPLETED")
        comp.add("percent-complete", 100)
        comp.add("completed", datetime.now(timezone.utc))
    else:
        comp.add("status", "NEEDS-ACTION")
        comp.add("percent-complete", 0)
    comp.pop("last-modified", None)
    comp.add("last-modified", datetime.now(timezone.utc))


def _occurrence_span(
    master: Any, pivot: date | datetime
) -> tuple[date | datetime | None, date | datetime | None]:
    """(dtstart, due) of the occurrence at ``pivot`` on a recurring VTODO."""
    anchor_key = "dtstart" if "dtstart" in master else "due"
    base = master.decoded(anchor_key)
    delta = _as_dt(pivot) - _as_dt(base)
    start = master.decoded("dtstart") + delta if "dtstart" in master else None
    due = master.decoded("due") + delta if "due" in master else None
    return start, due


def _build_task_event(
    vtodo: Any,
    color: str,
    calendar_id: int,
    meta: dict[str, dict[str, Any]],
    override_reminders: dict[tuple[str, str], list[Any]],
    fallback_uid: str,
    undated: bool = False,
) -> dict[str, Any] | None:
    uid = str(vtodo.get("uid")) if vtodo.get("uid") else fallback_uid
    summary = vtodo.get("summary")
    title = str(summary) if summary else "(No title)"

    dtstart = vtodo.decoded("dtstart") if "dtstart" in vtodo else None
    due = vtodo.decoded("due") if "due" in vtodo else None
    # The grid anchor is DUE if present, else DTSTART. A task with both renders
    # as a span (start -> due); start/due are also exposed individually so the
    # modal can populate its Start and Due fields.
    anchor = due if due is not None else dtstart
    all_day = _is_all_day(anchor) if anchor is not None else False

    ev: dict[str, Any] = {"id": uid, "title": title, "color": color, "allDay": all_day}
    if anchor is not None:
        ev["start"] = _dt_to_iso(anchor)
    if dtstart is not None and due is not None:
        ev["start"] = _dt_to_iso(dtstart)
        ev["end"] = _dt_to_iso(due)

    completed = _task_completed(vtodo)
    extended: dict[str, Any] = {
        "isTask": True,
        "calendarId": calendar_id,
        "completed": completed,
        "undated": undated,
        "status": str(vtodo.get("status") or ("COMPLETED" if completed else "NEEDS-ACTION")).upper(),
    }
    if dtstart is not None:
        extended["rawStart"] = _dt_to_iso(dtstart)
    if due is not None:
        extended["rawDue"] = _dt_to_iso(due)
    pct = vtodo.get("percent-complete")
    if pct is not None:
        try:
            extended["percentComplete"] = int(pct)
        except (TypeError, ValueError):
            pass

    inst = _extract_task_props(vtodo)
    master_props = meta.get(uid, {})
    if "recurrence-id" in vtodo:
        rid = _dt_to_iso(vtodo.decoded("recurrence-id"))
        extended["recurrenceId"] = rid
        if "reminders" not in inst and (uid, rid) in override_reminders:
            inst["reminders"] = override_reminders[(uid, rid)]
    for key in ("description", "location", "recurrence", "recurrenceRule", "reminders", "priority"):
        val = inst.get(key, master_props.get(key))
        if val:
            extended[key] = val
    ev["extendedProps"] = extended
    return ev


def _sync_fetch_tasks(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    from_dt: datetime,
    to_dt: datetime,
    color: str,
    calendar_id: int,
) -> list[dict[str, Any]]:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        todos = cal.search(start=from_dt, end=to_dt, todo=True, expand=True, include_completed=True)
        logger.info(
            "caldav_search_todos done url=%s from=%s to=%s raw_count=%d",
            calendar_url, from_dt.isoformat(), to_dt.isoformat(), len(todos),
        )
        meta, override_reminders = _master_meta(cal, from_dt, to_dt, _TODO)

        overridden: set[tuple[str, str]] = set()
        for todo in todos:
            try:
                for vtodo in todo.icalendar_instance.walk("VTODO"):
                    if "recurrence-id" not in vtodo:
                        continue
                    uid = str(vtodo.get("uid")) if vtodo.get("uid") else str(todo.url)
                    overridden.add((uid, _dt_to_iso(vtodo.decoded("recurrence-id"))))
            except Exception as e:
                logger.warning("Failed to scan todo for overrides: %s", e)

        result: list[dict[str, Any]] = []
        for todo in todos:
            try:
                for vtodo in todo.icalendar_instance.walk("VTODO"):
                    if "dtstart" not in vtodo and "due" not in vtodo:
                        continue
                    uid = str(vtodo.get("uid")) if vtodo.get("uid") else str(todo.url)
                    anchor_key = "due" if "due" in vtodo else "dtstart"
                    if "recurrence-id" not in vtodo and (uid, _dt_to_iso(vtodo.decoded(anchor_key))) in overridden:
                        continue
                    ev = _build_task_event(
                        vtodo, color, calendar_id, meta, override_reminders, str(todo.url)
                    )
                    if ev is not None:
                        result.append(ev)
            except Exception as e:
                logger.warning("Failed to parse todo: %s", e)

        # Undated tasks carry no date, so they never surface in the date-bounded
        # expand search above; fetch them separately and tag them undated.
        try:
            for todo in cal.todos(include_completed=True):
                for vtodo in todo.icalendar_instance.walk("VTODO"):
                    if "recurrence-id" in vtodo:
                        continue
                    if "dtstart" in vtodo or "due" in vtodo:
                        continue
                    ev = _build_task_event(
                        vtodo, color, calendar_id, {}, {}, str(todo.url), undated=True
                    )
                    if ev is not None:
                        result.append(ev)
        except Exception as e:
            logger.warning("Failed to fetch undated todos url=%s: %s", calendar_url, e)
        return result


async def fetch_tasks(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    from_dt: datetime,
    to_dt: datetime,
    color: str,
    calendar_id: int,
) -> list[dict[str, Any]]:
    with caldav_request_duration_seconds.labels(operation="fetch_tasks").time():
        try:
            return await asyncio.to_thread(
                _sync_fetch_tasks, account_url, username, password, calendar_url,
                from_dt, to_dt, color, calendar_id,
            )
        except Exception:
            caldav_request_errors_total.labels(operation="fetch_tasks").inc()
            raise


def _sync_create_task(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    start: date | datetime | None,
    due: date | datetime | None,
    location: str | None,
    description: str | None,
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
    priority: int | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        anchor = start or due
        rule_parts = _build_rrule(rrule, anchor) if rrule and anchor is not None else None
        cal.save_todo(_series_ical(
            uid, title, start, due, location, description, rule_parts,
            reminders=reminders, kind=_TODO, status="NEEDS-ACTION", priority=priority,
        ))


async def create_task(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    start: date | datetime | None,
    due: date | datetime | None,
    location: str | None,
    description: str | None,
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
    priority: int | None = None,
) -> None:
    with caldav_request_duration_seconds.labels(operation="create_task").time():
        try:
            await asyncio.to_thread(
                _sync_create_task, account_url, username, password, calendar_url,
                uid, title, start, due, location, description, rrule, reminders, priority,
            )
        except Exception:
            caldav_request_errors_total.labels(operation="create_task").inc()
            raise


def _set_priority(comp: Any, priority: int | None) -> None:
    comp.pop("priority", None)
    if priority is not None:
        comp.add("priority", priority)


def _sync_update_task(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    start: date | datetime | None,
    due: date | datetime | None,
    location: str | None,
    description: str | None,
    scope: str = "all",
    recurrence_id: str | None = None,
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
    priority: int | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            todo = cal.todo_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e

        ical = todo.icalendar_instance
        master = _master_vevent(ical, "VTODO")
        if master is None:
            raise EventNotFoundError(uid)

        is_recurring = bool(master.get("rrule"))
        if not is_recurring or not recurrence_id:
            scope = "all"

        if scope == "all":
            anchor_start = start
            anchor_end = due
            if is_recurring and recurrence_id:
                base_key = "dtstart" if "dtstart" in master else "due"
                pivot = _occurrence_dt(recurrence_id, master.decoded(base_key))
                edited_anchor = start if "dtstart" in master else due
                delta = _as_dt(edited_anchor) - _as_dt(pivot) if edited_anchor is not None else timedelta()
                old_start = master.decoded("dtstart") if "dtstart" in master else None
                old_due = master.decoded("due") if "due" in master else None
                anchor_start = old_start + delta if old_start is not None else None
                anchor_end = old_due + delta if old_due is not None else None
                for ov in _overrides(ical, "VTODO"):
                    _shift_override(ov, delta, kind=_TODO)
                _shift_exdate(master, delta)
            _apply_fields(master, title, anchor_start, anchor_end, location, description, kind=_TODO)
            _apply_alarms(master, reminders, _TODO.end_key)
            _set_priority(master, priority)
            rrule_anchor = anchor_start or anchor_end
            if rrule is not None and rrule_anchor is not None:
                _set_rrule(master, _build_rrule(rrule, rrule_anchor))
            elif is_recurring and recurrence_id:
                _shift_until(master, delta)
            todo.data = ical.to_ical().decode("utf-8")
            todo.save()
            return

        assert recurrence_id is not None
        base_key = "dtstart" if "dtstart" in master else "due"
        pivot = _occurrence_dt(recurrence_id, master.decoded(base_key))

        if scope == "this":
            _upsert_override(
                ical, master, pivot, title, start, due, location, description,
                reminders=reminders, kind=_TODO,
            )
            todo.data = ical.to_ical().decode("utf-8")
            todo.save()
            return

        if scope == "thisfuture":
            base = _as_dt(master.decoded(base_key))
            edited_anchor = start if base_key == "dtstart" else due
            anchor = edited_anchor if edited_anchor is not None else pivot
            new_rule = _build_rrule(rrule, anchor) if rrule else _remaining_rule_parts(master, pivot)
            if _as_dt(pivot) <= base:
                shift = _as_dt(anchor) - base
                for ov in _overrides(ical, "VTODO"):
                    _shift_override(ov, shift, kind=_TODO)
                _shift_exdate(master, shift)
                _apply_fields(master, title, start, due, location, description, kind=_TODO)
                _apply_alarms(master, reminders, _TODO.end_key)
                _set_priority(master, priority)
                _set_rrule(master, new_rule)
                todo.data = ical.to_ical().decode("utf-8")
                todo.save()
                return
            new_uid = f"{uuid.uuid4()}@webcaldav"
            shift = _as_dt(anchor) - _as_dt(pivot)
            migrated = _pop_overrides(ical, keep=lambda rid: _as_dt(rid) < _as_dt(pivot), name="VTODO")
            for ov in migrated:
                _shift_override(ov, shift, new_uid=new_uid, kind=_TODO)
            old_ex = _exdates(master)
            _set_exdates(master, [d for d in old_ex if _as_dt(d) < _as_dt(pivot)])
            migrated_ex = [d + shift for d in old_ex if _as_dt(d) >= _as_dt(pivot)]
            _truncate_until(master, pivot)
            todo.data = ical.to_ical().decode("utf-8")
            todo.save()
            carried = [c for c in master.subcomponents if c.name == "VALARM"]
            cal.save_todo(_series_ical(
                new_uid, title, start, due, location, description, new_rule,
                overrides=migrated, exdates=migrated_ex, reminders=reminders,
                alarms=carried, kind=_TODO, status="NEEDS-ACTION", priority=priority,
            ))
            return

        raise ValueError(f"unknown scope: {scope!r}")


async def update_task(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    title: str,
    start: date | datetime | None,
    due: date | datetime | None,
    location: str | None,
    description: str | None,
    scope: str = "all",
    recurrence_id: str | None = None,
    rrule: dict[str, Any] | None = None,
    reminders: list[tuple[timedelta, str]] | None = None,
    priority: int | None = None,
) -> None:
    with caldav_request_duration_seconds.labels(operation="update_task").time():
        try:
            await asyncio.to_thread(
                _sync_update_task, account_url, username, password, calendar_url,
                uid, title, start, due, location, description, scope, recurrence_id,
                rrule, reminders, priority,
            )
        except EventNotFoundError:
            raise
        except Exception:
            caldav_request_errors_total.labels(operation="update_task").inc()
            raise


def _sync_delete_task(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    scope: str = "all",
    recurrence_id: str | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            todo = cal.todo_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e

        ical = todo.icalendar_instance
        master = _master_vevent(ical, "VTODO")
        if scope == "all" or master is None or not master.get("rrule") or not recurrence_id:
            todo.delete()
            return

        base_key = "dtstart" if "dtstart" in master else "due"
        pivot = _occurrence_dt(recurrence_id, master.decoded(base_key))
        base = _as_dt(master.decoded(base_key))

        if scope == "this":
            _add_exdate(master, pivot)
        elif scope == "thisfuture":
            if _as_dt(pivot) <= base:
                todo.delete()
                return
            _truncate_until(master, pivot)
            _pop_overrides(ical, keep=lambda rid: _as_dt(rid) < _as_dt(pivot), name="VTODO")
        else:
            todo.delete()
            return

        todo.data = ical.to_ical().decode("utf-8")
        todo.save()


async def delete_task(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    scope: str = "all",
    recurrence_id: str | None = None,
) -> None:
    with caldav_request_duration_seconds.labels(operation="delete_task").time():
        try:
            await asyncio.to_thread(
                _sync_delete_task, account_url, username, password, calendar_url,
                uid, scope, recurrence_id,
            )
        except EventNotFoundError:
            raise
        except Exception:
            caldav_request_errors_total.labels(operation="delete_task").inc()
            raise


def _sync_set_task_status(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    completed: bool,
    recurrence_id: str | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        try:
            todo = cal.todo_by_uid(uid)
        except caldav.lib.error.NotFoundError as e:
            raise EventNotFoundError(uid) from e

        ical = todo.icalendar_instance
        master = _master_vevent(ical, "VTODO")
        if master is None:
            raise EventNotFoundError(uid)

        is_recurring = bool(master.get("rrule"))
        # Non-recurring (or no pivot): toggle the master directly.
        if not is_recurring or not recurrence_id:
            _set_status(master, completed)
            todo.data = ical.to_ical().decode("utf-8")
            todo.save()
            return

        # Recurring: RFC-advance. Completing the current occurrence writes a
        # COMPLETED override for that instance and leaves the master series, so
        # the next occurrence keeps showing. Un-completing drops the override.
        base_key = "dtstart" if "dtstart" in master else "due"
        pivot = _occurrence_dt(recurrence_id, master.decoded(base_key))
        # Remove any existing override at the pivot first.
        for comp in _overrides(ical, "VTODO"):
            try:
                if comp.decoded("recurrence-id") == pivot:
                    ical.subcomponents.remove(comp)
            except Exception:
                pass
        if completed:
            occ_start, occ_due = _occurrence_span(master, pivot)
            _upsert_override(
                ical, master, pivot, str(master.get("summary") or ""),
                occ_start, occ_due, None, None, kind=_TODO,
                status="COMPLETED", completed=datetime.now(timezone.utc),
            )
        todo.data = ical.to_ical().decode("utf-8")
        todo.save()


async def set_task_status(
    account_url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
    completed: bool,
    recurrence_id: str | None = None,
) -> None:
    with caldav_request_duration_seconds.labels(operation="set_task_status").time():
        try:
            await asyncio.to_thread(
                _sync_set_task_status, account_url, username, password, calendar_url,
                uid, completed, recurrence_id,
            )
        except EventNotFoundError:
            raise
        except Exception:
            caldav_request_errors_total.labels(operation="set_task_status").inc()
            raise
