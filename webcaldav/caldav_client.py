import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import caldav
from caldav.elements.ical import CalendarColor
from dateutil.rrule import rrulestr
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent
from icalendar.prop import vRecur

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


def _rrule_to_struct(rrule, dtstart: date | datetime) -> dict:
    """Render an icalendar vRecur into the editor's structured recurrence model."""
    parts = {str(k).upper(): (v if isinstance(v, list) else [v]) for k, v in rrule.items()}
    out: dict = {"freq": str((parts.get("FREQ") or ["DAILY"])[0]).lower(), "interval": 1}
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


def preview_recurrence(start: date | datetime, rule: dict) -> tuple[str | None, int | None]:
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
        try:
            out["recurrenceRule"] = _rrule_to_struct(rrule, vevent.decoded("dtstart"))
        except Exception:
            pass
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


class EventNotFoundError(Exception):
    """Raised when the target event UID is not present on the calendar."""


# ── Recurrence math ──────────────────────────────────────────────────────────
#
# Scoped recurring operations pivot on a single occurrence, identified by its
# original start ("recurrence id"). dateutil.rrule does the occurrence math; the
# helpers below translate between the master VEVENT and that engine, and mutate
# the master's RRULE/DTSTART in place for truncate/shift operations.


def _master_vevent(ical):
    """The series master VEVENT (the one without a RECURRENCE-ID)."""
    vevents = list(ical.walk("VEVENT"))
    for v in vevents:
        if "recurrence-id" not in v:
            return v
    return vevents[0] if vevents else None


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


def _rrule_text(vevent) -> str | None:
    rr = vevent.get("rrule")
    if not rr:
        return None
    return rr.to_ical().decode("utf-8")


def _rrule_parts(vevent) -> dict:
    """RRULE as a plain {NAME: [values]} dict that can be re-added via vevent.add."""
    rr = vevent.get("rrule")
    return {str(k): (list(v) if isinstance(v, list) else [v]) for k, v in rr.items()}


def _set_rrule(vevent, parts: dict) -> None:
    vevent.pop("rrule", None)
    vevent.add("rrule", parts)


def _shift_until(vevent, delta: timedelta) -> None:
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


def _count_through(vevent, pivot: date | datetime, inc: bool = True) -> int:
    """Number of occurrences from the series start through the pivot."""
    base = _as_dt(vevent.decoded("dtstart"))
    return len(rrulestr(_rrule_text(vevent), dtstart=base).between(base, _as_dt(pivot), inc=inc))


def _truncate_until(vevent, pivot: date | datetime) -> None:
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


def _add_exdate(vevent, pivot: date | datetime) -> None:
    vevent.add("exdate", pivot)


def _exdates(vevent) -> list:
    """All EXDATE exclusion points as a flat list of date/datetime values."""
    prop = vevent.get("exdate")
    if not prop:
        return []
    props = prop if isinstance(prop, list) else [prop]
    return [d.dt for p in props for d in p.dts]


def _set_exdates(vevent, dts) -> None:
    vevent.pop("exdate", None)
    for d in dts:
        vevent.add("exdate", d)


def _shift_exdate(vevent, delta: timedelta) -> None:
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


def _build_rrule(rule: dict, dtstart: date | datetime) -> dict:
    """Translate the editor's recurrence model into an icalendar RRULE dict.

    Monthly has two modes: ``monthday`` keeps the day of month (falling back to
    the last day for days >= 29, which February etc. cannot satisfy), and
    ``weekday`` schedules the Nth / last weekday of the month (BYDAY=2MO, -1FR).
    ``count`` and ``until`` are mutually exclusive; ``count`` wins if both arrive.
    """
    freq = _FREQ_MAP.get(str(rule.get("freq", "")).lower())
    if not freq:
        raise ValueError(f"unsupported recurrence frequency: {rule.get('freq')!r}")
    parts: dict = {"FREQ": freq}
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


def _remaining_rule_parts(vevent, pivot: date | datetime) -> dict:
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
    vevent,
    title: str,
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
) -> None:
    """Overwrite a VEVENT's editable fields + time span, bumping SEQUENCE."""
    def _replace(key: str, value) -> None:
        vevent.pop(key, None)
        if value is not None and value != "":
            vevent.add(key, value)

    _replace("summary", title)
    _replace("location", location)
    _replace("description", description)
    vevent.pop("dtstart", None)
    vevent.pop("dtend", None)
    vevent.pop("duration", None)
    vevent.add("dtstart", start)
    vevent.add("dtend", end)
    try:
        seq = int(vevent.get("sequence", 0)) + 1
    except (TypeError, ValueError):
        seq = 1
    vevent.pop("sequence", None)
    vevent.add("sequence", seq)
    _replace("last-modified", datetime.now(timezone.utc))


def _upsert_override(
    ical,
    master,
    pivot: date | datetime,
    title: str,
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
) -> None:
    """Add/replace a detached single-occurrence override (RECURRENCE-ID = pivot)."""
    for comp in list(ical.subcomponents):
        if comp.name == "VEVENT" and "recurrence-id" in comp:
            try:
                if comp.decoded("recurrence-id") == pivot:
                    ical.subcomponents.remove(comp)
            except Exception:
                pass
    ov = IEvent()
    ov.add("uid", str(master.get("uid")))
    ov.add("recurrence-id", pivot)
    ov.add("dtstamp", datetime.now(timezone.utc))
    if title:
        ov.add("summary", title)
    ov.add("dtstart", start)
    ov.add("dtend", end)
    if location:
        ov.add("location", location)
    if description:
        ov.add("description", description)
    ical.add_component(ov)


def _overrides(ical) -> list:
    """Detached single-occurrence override VEVENTs (those with a RECURRENCE-ID)."""
    return [
        c for c in ical.subcomponents
        if c.name == "VEVENT" and "recurrence-id" in c
    ]


def _shift_override(ve, delta: timedelta, new_uid: str | None = None) -> None:
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
    for key in ("recurrence-id", "dtstart", "dtend"):
        if key in ve:
            val = ve.decoded(key)
            ve.pop(key, None)
            ve.add(key, val + delta)


def _pop_overrides(ical, keep) -> list:
    """Remove overrides whose recurrence id fails ``keep(rid)``; return the removed.

    ``keep`` receives the decoded RECURRENCE-ID; overrides it rejects are
    detached from ``ical`` (to migrate elsewhere) and returned in document order.
    """
    removed = []
    for comp in _overrides(ical):
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
    start: date | datetime,
    end: date | datetime,
    location: str | None,
    description: str | None,
    rule_parts: dict | None,
    overrides: list | None = None,
    exdates: list | None = None,
) -> str:
    ical = ICalendar()
    ical.add("prodid", "-//WebCalDav//EN")
    ical.add("version", "2.0")
    ve = IEvent()
    ve.add("uid", uid)
    ve.add("dtstamp", datetime.now(timezone.utc))
    if title:
        ve.add("summary", title)
    ve.add("dtstart", start)
    ve.add("dtend", end)
    if location:
        ve.add("location", location)
    if description:
        ve.add("description", description)
    if rule_parts:
        ve.add("rrule", rule_parts)
    for d in exdates or []:
        ve.add("exdate", d)
    ical.add_component(ve)
    for ov in overrides or []:
        ical.add_component(ov)
    return ical.to_ical().decode("utf-8")


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

        result: list[dict] = []
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
                    # Detached overrides carry a stable RECURRENCE-ID that does not
                    # change when the occurrence is moved; it is the pivot the
                    # server keys overrides on, so expose it for scoped edits.
                    if "recurrence-id" in vevent:
                        extended["recurrenceId"] = _dt_to_iso(vevent.decoded("recurrence-id"))
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
    scope: str = "all",
    recurrence_id: str | None = None,
    rrule: dict | None = None,
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
                delta = start - pivot
                old_start = master.decoded("dtstart")
                anchor_start = old_start + delta
                anchor_end = anchor_start + (end - start)
                # A whole-series time shift moves every generated slot; carry the
                # detached overrides along (times only) so they stay bound and
                # keep their own customized fields rather than orphaning.
                for ov in _overrides(ical):
                    _shift_override(ov, delta)
                _shift_exdate(master, delta)
            _apply_fields(master, title, anchor_start, anchor_end, location, description)
            if rrule is not None:
                _set_rrule(master, _build_rrule(rrule, anchor_start))
            elif is_recurring and recurrence_id:
                # No new rule supplied (e.g. a drag): keep the existing RRULE but
                # carry its UNTIL bound along with the shifted DTSTART.
                _shift_until(master, delta)
            event.data = ical.to_ical().decode("utf-8")
            event.save()
            return

        pivot = _occurrence_dt(recurrence_id, master.decoded("dtstart"))

        if scope == "this":
            # Detach just this occurrence as a RECURRENCE-ID override.
            _upsert_override(ical, master, pivot, title, start, end, location, description)
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
                _shift_override(ov, start - pivot, new_uid=new_uid)
            old_ex = _exdates(master)
            _set_exdates(master, [d for d in old_ex if _as_dt(d) < _as_dt(pivot)])
            migrated_ex = [d + (start - pivot) for d in old_ex if _as_dt(d) >= _as_dt(pivot)]
            _truncate_until(master, pivot)
            event.data = ical.to_ical().decode("utf-8")
            event.save()
            cal.save_event(_series_ical(
                new_uid, title, start, end, location, description, new_rule,
                overrides=migrated, exdates=migrated_ex,
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
    rrule: dict | None = None,
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
    rrule: dict | None = None,
) -> None:
    with caldav.DAVClient(url=account_url, username=username, password=password) as client:
        cal = caldav.Calendar(client=client, url=calendar_url)
        rule_parts = _build_rrule(rrule, start) if rrule else None
        cal.save_event(_series_ical(uid, title, start, end, location, description, rule_parts))


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
    rrule: dict | None = None,
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
