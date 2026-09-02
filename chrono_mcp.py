#!/usr/bin/env python3
"""chrono-mcp — a zero-dependency date & time MCP server.

Run directly with any Python 3.9+ interpreter; the only runtime dependency
is the Python standard library. The MCP protocol layer (JSON-RPC 2.0 over
stdio, newline-delimited) is implemented here so users don't need to
install the official `mcp` package just to get the current date.

Tools provided:
    get_current_time   — current date/time in any IANA timezone
    convert_time       — convert a wall-clock time across timezones
    time_offset        — current UTC-offset difference between two zones
    parse_natural_time — free-form phrases ("next tuesday 3pm") to ISO
    add_duration       — calendar arithmetic ("+3 hours", "3 business days")
    meeting_windows    — common meeting slots across timezones
    format_time        — strftime formatting helper for agents
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__version__ = "0.1.0"

PROTOCOL_VERSION = "2025-06-18"

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------------------------------------------------------------------------
# timezone helpers
# ---------------------------------------------------------------------------

_ALIAS_MAP = {
    "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "taipei": "Asia/Taipei",
    "tokyo": "Asia/Tokyo", "seoul": "Asia/Seoul", "singapore": "Asia/Singapore",
    "hongkong": "Asia/Hong_Kong", "hong kong": "Asia/Hong_Kong",
    "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
    "madrid": "Europe/Madrid", "rome": "Europe/Rome", "moscow": "Europe/Moscow",
    "istanbul": "Europe/Istanbul", "dubai": "Asia/Dubai", "mumbai": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata", "delhi": "Asia/Kolkata", "sydney": "Australia/Sydney",
    "auckland": "Pacific/Auckland", "losangeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "sanfrancisco": "America/Los_Angeles",
    "newyork": "America/New_York", "new york": "America/New_York",
    "chicago": "America/Chicago", "denver": "America/Denver", "houston": "America/Chicago",
    "boston": "America/New_York", "seattle": "America/Los_Angeles",
    "toronto": "America/Toronto", "vancouver": "America/Vancouver",
    "mexicocity": "America/Mexico_City", "saopaulo": "America/Sao_Paulo",
    "buenosaires": "America/Argentina/Buenos_Aires", "cairo": "Africa/Cairo",
    "lagos": "Africa/Lagos", "nairobi": "Africa/Nairobi",
    "johannesburg": "Africa/Johannesburg", "utc": "UTC", "gmt": "UTC", "z": "UTC",
}


def resolve_zone(name: str) -> ZoneInfo:
    """Validate an IANA name or resolve a friendly city alias."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Timezone must be a non-empty string.")
    key = name.strip()
    if "/" not in key:
        lowered = key.lower()
        if lowered in _ALIAS_MAP:
            key = _ALIAS_MAP[lowered]
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(
            f"Unknown timezone {name!r}. Use IANA names like 'Asia/Shanghai' or aliases like 'tokyo'."
        )


def _iso(when: dt.datetime) -> str:
    return when.isoformat(timespec="seconds")


def _utc_offset_label(zone: ZoneInfo, when: dt.datetime) -> str:
    local = when.astimezone(zone)
    return local.strftime("%z")[:3] + ":" + local.strftime("%z")[3:]


# ---------------------------------------------------------------------------
# shared parsing helpers
# ---------------------------------------------------------------------------

def _reference_date(date: str | None, zone: ZoneInfo) -> dt.date:
    """Default the reference date to 'today' in the given zone."""
    if not date:
        return dt.datetime.now(tz=zone).date()
    try:
        return dt.date.fromisoformat(date)
    except ValueError:
        raise ValueError(f"Invalid date {date!r}. Use YYYY-MM-DD.")


def _parse_clock(value: str):
    """Parse 'HH:MM', 'HH:MM:SS', '3pm', '3:30pm' into (time, ampm)."""
    text = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?(am|pm)?", text)
    if not match:
        raise ValueError(f"Invalid time {value!r}. Use HH:MM, HH:MM:SS, or 3pm.")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    second = int(match.group(3) or 0)
    ampm = match.group(4)
    if ampm == "am" and hour == 12:
        hour = 0
    elif ampm == "pm" and hour < 12:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"Invalid time {value!r}.")
    return dt.time(hour, minute, second), ampm


def _parse_iso_flexible(value: str, zone: ZoneInfo) -> dt.datetime:
    """Parse an ISO timestamp, normalizing a trailing 'Z' and defaulting the zone."""
    text = value.strip()
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Invalid timestamp {value!r}. Use ISO format or 'now'.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed


def _timedelta_for(amount: int, unit: str) -> dt.timedelta:
    """Approximate a timedelta for a unit word ('month' = 30d, 'year' = 365d)."""
    table = {
        "second": dt.timedelta(seconds=1),
        "minute": dt.timedelta(minutes=1),
        "hour": dt.timedelta(hours=1),
        "day": dt.timedelta(days=1),
        "week": dt.timedelta(weeks=1),
        "month": dt.timedelta(days=30),
        "year": dt.timedelta(days=365),
    }
    unit = unit.lower().rstrip("s")
    if unit not in table:
        raise ValueError(f"Unknown unit {unit!r}. Use second/minute/hour/day/week/month/year.")
    return amount * table[unit]


# ---------------------------------------------------------------------------
# tool: get_current_time
# ---------------------------------------------------------------------------

def get_current_time(timezone: str = "UTC") -> dict:
    """Current date and time in the requested IANA timezone."""
    zone = resolve_zone(timezone)
    now = dt.datetime.now(tz=dt.timezone.utc).astimezone(zone)
    return {
        "timezone": zone.key,
        "iso": _iso(now),
        "unix": int(now.timestamp()),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "utc_offset": _utc_offset_label(zone, now),
        "is_dst": bool(now.dst()),
    }


# ---------------------------------------------------------------------------
# tool: convert_time
# ---------------------------------------------------------------------------

def convert_time(time: str, from_tz: str, to_tz: str, date: str | None = None) -> dict:
    """Convert a wall-clock time between two timezones (with date rollover)."""
    zone_from = resolve_zone(from_tz)
    zone_to = resolve_zone(to_tz)
    base_date = _reference_date(date, zone_from)
    tod, _ampm = _parse_clock(time)
    local = dt.datetime.combine(base_date, tod, tzinfo=zone_from)
    target = local.astimezone(zone_to)
    day_shift = "same day"
    if target.date() > local.date():
        day_shift = "next day"
    elif target.date() < local.date():
        day_shift = "previous day"
    return {
        "input": {
            "time": local.strftime("%H:%M"),
            "date": local.date().isoformat(),
            "timezone": zone_from.key,
        },
        "result": {
            "time": target.strftime("%H:%M"),
            "date": target.date().isoformat(),
            "timezone": zone_to.key,
        },
        "iso": _iso(target),
        "day_shift": day_shift,
        "note": (
            f"{local.strftime('%H:%M')} {zone_from.key} = "
            f"{target.strftime('%H:%M')} {zone_to.key} ({day_shift})"
        ),
    }


# ---------------------------------------------------------------------------
# tool: time_offset
# ---------------------------------------------------------------------------

def time_offset(from_timezone: str, to_timezone: str) -> dict:
    """Current UTC-offset difference between two zones, right now (DST-aware)."""
    zone_from = resolve_zone(from_timezone)
    zone_to = resolve_zone(to_timezone)
    now = dt.datetime.now(tz=dt.timezone.utc)
    minutes = int(
        (
            now.astimezone(zone_to).utcoffset() - now.astimezone(zone_from).utcoffset()
        ).total_seconds() // 60
    )
    sign = "+" if minutes >= 0 else "-"
    return {
        "from": {"timezone": zone_from.key, "utc_offset": _utc_offset_label(zone_from, now)},
        "to": {"timezone": zone_to.key, "utc_offset": _utc_offset_label(zone_to, now)},
        "difference_minutes": minutes,
        "difference_human": f"{sign}{abs(minutes) // 60:02d}h{abs(minutes) % 60:02d}m",
    }


# ---------------------------------------------------------------------------
# tool: parse_natural_time
# ---------------------------------------------------------------------------

def parse_natural_time(text: str, timezone: str = "UTC", now: str | None = None) -> dict:
    """Parse a free-form phrase like 'next tuesday 3pm' into a precise timestamp."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Provide a phrase like 'next tuesday 3pm' or 'tomorrow 09:00'.")
    zone = resolve_zone(timezone)
    ref = _parse_iso_flexible(now, zone) if now else dt.datetime.now(tz=zone)
    return _parse_phrase(text, ref, zone)


def _parse_phrase(text: str, ref: dt.datetime, zone: ZoneInfo) -> dict:
    original = text
    text = re.sub(r"\s+", " ", text.strip().lower())
    # strip filler words but keep 'in'/'ago' (they carry meaning)
    text = re.sub(r"\b(at|on|the)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # explicit ISO datetime first: "2026-09-10 14:30"
    m = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})(?:[ t](\d{1,2}:\d{2}(?::\d{2})?)(am|pm)?)?", text
    )
    if m:
        try:
            day = dt.date.fromisoformat(m.group(1))
        except ValueError:
            raise ValueError(f"Invalid date {m.group(1)!r}.")
        tod, ampm = (_parse_clock(m.group(2) + (m.group(3) or "")) if m.group(2) else (None, None))
        return _assemble(day, tod, ampm, zone, original, "explicit date")

    # relative days with optional time: "tomorrow", "tomorrow 3pm", "tonight"
    m = re.fullmatch(r"(yesterday|today|tonight|tomorrow)(?:\s+(.+))?", text)
    if m:
        word = m.group(1)
        day = ref.date() + dt.timedelta(
            days={"yesterday": -1, "today": 0, "tonight": 0, "tomorrow": 1}[word]
        )
        if m.group(2):
            tod, ampm = _parse_clock(m.group(2))
        elif word == "tonight":
            tod, ampm = dt.time(20, 0), None
        else:
            tod, ampm = None, None
        return _assemble(day, tod, ampm, zone, original, word)

    # durations: "in 2 hours" / "2 days ago" / "half an hour ago"
    rel = _parse_relative(text, ref, zone, original)
    if rel:
        return rel

    # weekday references: friday / next friday / last friday 3pm
    weekday_match = re.fullmatch(
        r"(?:(next|last|this)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"(?:\s+(.+))?",
        text,
    )
    if weekday_match:
        modifier = weekday_match.group(1)
        target = _WEEKDAYS.index(weekday_match.group(2))
        day = _resolve_weekday(ref.date(), target, modifier)
        tod, ampm = (None, None)
        if weekday_match.group(3):
            tod, ampm = _parse_clock(weekday_match.group(3))
        return _assemble(day, tod, ampm, zone, original, f"{modifier or 'this'} {weekday_match.group(2)}")

    # month-name dates: "sep 10 3pm", "10 september", "september 10, 2026"
    month_day = _parse_month_name_date(text, ref)
    if month_day:
        day, tod, ampm = month_day
        return _assemble(day, tod, ampm, zone, original, "month-name date")

    # time-only phrases: "3pm", "14:30", "9am"
    if re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?(am|pm)?", text):
        tod, ampm = _parse_clock(text)
        return _assemble(ref.date(), tod, ampm, zone, original, "time today")

    raise ValueError(
        f"Could not parse {original!r}. Try 'next tuesday 3pm', 'tomorrow 09:00', "
        "'in 2 hours', '3 days ago', '2026-09-10 14:30', or 'sep 10 3pm'."
    )


def _resolve_weekday(today: dt.date, target: int, modifier: str | None) -> dt.date:
    """Date for 'this/next/last <weekday>' relative to today."""
    current = today.weekday()
    if modifier == "last":
        back = (current - target) % 7 or 7
        return today - dt.timedelta(days=back)
    diff = (target - current) % 7
    if modifier == "next" and diff == 0:
        diff = 7
    return today + dt.timedelta(days=diff)


def _parse_relative(text: str, ref: dt.datetime, zone: ZoneInfo, original: str) -> dict | None:
    """Handle 'in N units' / 'N units ago' / 'half an hour ago'."""
    m = re.fullmatch(r"in\s+(\d+)\s+(second|minute|hour|day|week|month|year)s?", text)
    if m:
        then = ref + _timedelta_for(int(m.group(1)), m.group(2))
        return _relative_result(then, zone, original, f"in {m.group(1)} {m.group(2)}s")
    m = re.fullmatch(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text)
    if m:
        then = ref - _timedelta_for(int(m.group(1)), m.group(2))
        return _relative_result(then, zone, original, f"{m.group(1)} {m.group(2)}s ago")
    if re.fullmatch(r"(?:in\s+)?half\s+an?\s+hour(?:\s+ago)?", text):
        back = text.endswith("ago")
        then = ref - dt.timedelta(minutes=30) if back else ref + dt.timedelta(minutes=30)
        return _relative_result(then, zone, original, "half an hour")
    return None


def _relative_result(then: dt.datetime, zone: ZoneInfo, original: str, rule: str) -> dict:
    return {
        "input": original,
        "iso": _iso(then),
        "unix": int(then.timestamp()),
        "date": then.strftime("%Y-%m-%d"),
        "time": then.strftime("%H:%M:%S"),
        "timezone": zone.key,
        "time_provided": True,
        "rule_matched": rule,
    }


def _assemble(day: dt.date, tod: dt.time | None, ampm: str | None, zone: ZoneInfo, original: str, rule: str) -> dict:
    """Combine date + time-of-day into an aware datetime and the final result."""
    time_provided = tod is not None
    if tod is None:
        naive = dt.datetime(day.year, day.month, day.day)
    else:
        hour = tod.hour
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        naive = dt.datetime(day.year, day.month, day.day, hour, tod.minute, tod.second)
    aware = naive.replace(tzinfo=zone)
    return {
        "input": original,
        "iso": _iso(aware),
        "unix": int(aware.timestamp()),
        "date": day.isoformat(),
        "time": aware.strftime("%H:%M:%S"),
        "timezone": zone.key,
        "time_provided": time_provided,
        "rule_matched": rule,
        "note": (
            None if time_provided
            else "No time of day in the phrase; result is midnight in the target timezone."
        ),
    }


def _parse_month_name_date(text: str, ref: dt.datetime):
    """Extract (date, time, ampm) from 'sep 10 3pm' / '10 september' style phrases."""
    tokens = text.split()
    months_full = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    months_abbr = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
    months_abbr["sept"] = 9
    for i, tok in enumerate(tokens):
        stripped = tok.rstrip(",.")
        month = months_full.get(stripped) or months_abbr.get(stripped)
        if month is None:
            continue
        for j in (i + 1, i - 1):
            if not (0 <= j < len(tokens)):
                continue
            m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", tokens[j].rstrip(",."))
            if not m:
                continue
            day_num = int(m.group(1))
            if not (1 <= day_num <= 31):
                continue
            year = None
            for tok_k in tokens:
                if re.fullmatch(r"\d{4}", tok_k):
                    year = int(tok_k)
                    break
            try:
                day = dt.date(year or ref.year, month, day_num)
            except ValueError:
                continue
            tod, ampm = None, None
            for tok2 in tokens:
                tm = re.fullmatch(r"\d{1,2}(?::\d{2})?(?::\d{2})?(?:am|pm)?", tok2)
                if tm and ((":" in tok2) or tok2.endswith(("am", "pm"))):
                    tod, ampm = _parse_clock(tok2)
                    break
            return day, tod, ampm
    return None


# ---------------------------------------------------------------------------
# tool: add_duration
# ---------------------------------------------------------------------------

def add_duration(start: str = "now", duration: str = "0 minutes", timezone: str = "UTC") -> dict:
    """Add a signed duration to a start time. start = 'now' or ISO timestamp."""
    zone = resolve_zone(timezone)
    if start.strip().lower() == "now":
        base = dt.datetime.now(tz=zone)
    else:
        base = _parse_iso_flexible(start, zone)
    amount, unit, business = _parse_duration(duration)
    if business:
        end = _add_business_days(base, amount)
        rule = f"{duration.strip()} (business days skip Sat/Sun)"
    else:
        end = base + _timedelta_for(amount, unit)
        rule = f"{duration.strip()} ({unit}s)"
    return {
        "start_iso": _iso(base),
        "result_iso": _iso(end),
        "start_unix": int(base.timestamp()),
        "result_unix": int(end.timestamp()),
        "difference_human": rule,
        "calendar_days_between": (end.date() - base.date()).days,
        "timezone": zone.key,
    }


def _parse_duration(duration: str):
    """Parse '+3 hours', '-2h30m', '3 business days', '90m', '2 days', '45' (minutes)."""
    if not isinstance(duration, str) or not duration.strip():
        raise ValueError("Provide a duration like '+3 hours', '-2h30m', or '3 business days'.")
    compact = re.sub(r"\s+", "", duration.strip().lower())
    sign_num = lambda s: int(("-" if s.startswith("-") else "") + s.lstrip("+-"))

    # business days first (so 'days' isn't shadowed)
    m = re.fullmatch(r"([+-]?)(\d+)businessdays?", compact)
    if m:
        return sign_num(m.group(1) + m.group(2)), "day", True

    # compound H:MM-style: '2h30m', '-2h30m'
    m = re.fullmatch(r"([+-]?)(\d+)h(\d+)m", compact)
    if m:
        total = int(m.group(2)) * 60 + int(m.group(3))
        return -total if m.group(1) == "-" else total, "minute", False

    # unit words: '90m', '3hours', '2days', '1w', '6mo', '2y'
    m = re.fullmatch(
        r"([+-]?)(\d+)(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d"
        r"|weeks?|wks?|w|months?|mo|years?|yrs?|y)",
        compact,
    )
    if m:
        word = m.group(3)
        unit = (
            "second" if word[0] == "s" else
            "minute" if word == "m" or word.startswith("min") else
            "hour" if word[0] == "h" else
            "day" if word == "d" or word.startswith("day") else
            "week" if word[0] == "w" else
            "month" if word.startswith("mo") else
            "year"
        )
        return sign_num(m.group(1) + m.group(2)), unit, False

    # bare number = minutes
    m = re.fullmatch(r"([+-]?)(\d+)", compact)
    if m:
        return sign_num(m.group(1) + m.group(2)), "minute", False

    raise ValueError(
        f"Invalid duration {duration!r}. Try '+3 hours', '-2h30m', '90m', '2 days', or '3 business days'."
    )


def _add_business_days(base: dt.datetime, amount: int) -> dt.datetime:
    """Add business days (Mon-Fri), skipping weekends. Holidays are not tracked."""
    step = 1 if amount >= 0 else -1
    remaining = abs(amount)
    cursor = base
    while remaining > 0:
        cursor = cursor + dt.timedelta(days=step)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor


# ---------------------------------------------------------------------------
# tool: meeting_windows
# ---------------------------------------------------------------------------

def meeting_windows(
    timezones: list,
    start_hour: int = 9,
    end_hour: int = 18,
    date: str | None = None,
    duration_minutes: int = 60,
) -> dict:
    """Find common meeting windows across timezones within local business hours."""
    if not isinstance(timezones, list) or len(timezones) < 1:
        raise ValueError("Provide a list of timezones, e.g. ['Asia/Shanghai', 'America/New_York'].")
    if not (0 <= start_hour < end_hour <= 24):
        raise ValueError(f"Need 0 <= start_hour < end_hour <= 24, got {start_hour}..{end_hour}.")
    if not (1 <= duration_minutes <= 24 * 60):
        raise ValueError("duration_minutes must be between 1 and 1440.")
    zones = [resolve_zone(tz) for tz in timezones]
    base_date = _reference_date(date, zones[0])
    day_start_utc = dt.datetime.combine(base_date, dt.time(0), tzinfo=zones[0]).astimezone(dt.timezone.utc)

    def _fits(slot_utc: dt.datetime) -> bool:
        """True if the whole meeting stays inside business hours in every zone."""
        end_utc = slot_utc + dt.timedelta(minutes=duration_minutes)
        for zone in zones:
            ls = slot_utc.astimezone(zone)
            le = end_utc.astimezone(zone)
            if ls.date() != le.date():
                return False  # crosses local midnight somewhere
            ms = ls.hour * 60 + ls.minute
            me = le.hour * 60 + le.minute
            if ms < start_hour * 60 or me > end_hour * 60:
                return False
        return True

    slots = []
    cursor = day_start_utc
    slot_step = dt.timedelta(minutes=30)
    while cursor <= day_start_utc + dt.timedelta(days=2):
        if _fits(cursor):
            slots.append(cursor)
        cursor += slot_step

    if not slots:
        return {
            "date": base_date.isoformat(),
            "timezones": [z.key for z in zones],
            "windows": [],
            "message": (
                f"No common window with every zone inside {start_hour:02d}:00-{end_hour:02d}:00 "
                f"local for a {duration_minutes}-minute meeting. Try widening the hours, shortening "
                "the meeting, or picking another date."
            ),
        }

    # merge contiguous 30-min slots into windows; a window's end is its last
    # start slot plus the meeting duration
    windows = []
    span = dt.timedelta(minutes=duration_minutes)
    win_start, prev = slots[0], slots[0]
    for s in slots[1:]:
        if s - prev > slot_step:
            windows.append((win_start, prev + span))
            win_start = s
        prev = s
    windows.append((win_start, prev + span))

    return {
        "date": base_date.isoformat(),
        "timezones": [z.key for z in zones],
        "business_hours": f"{start_hour:02d}:00-{end_hour:02d}:00 local, in every zone",
        "windows": [
            {
                "start_utc": _iso(w[0].astimezone(dt.timezone.utc)),
                "end_utc": _iso(w[1].astimezone(dt.timezone.utc)),
                "local_start": {z.key: w[0].astimezone(z).strftime("%H:%M") for z in zones},
                "local_end": {z.key: w[1].astimezone(z).strftime("%H:%M") for z in zones},
            }
            for w in windows
        ],
    }


# ---------------------------------------------------------------------------
# tool: format_time
# ---------------------------------------------------------------------------

def format_time(timestamp: str, format: str = "%Y-%m-%d %H:%M:%S", timezone: str | None = None) -> dict:
    """Format an ISO timestamp (or 'now') with a strftime pattern, optionally in a timezone."""
    zone = resolve_zone(timezone) if timezone else dt.timezone.utc
    if timestamp.strip().lower() == "now":
        parsed = dt.datetime.now(tz=zone)
    else:
        parsed = _parse_iso_flexible(timestamp, zone)
        if timezone:
            parsed = parsed.astimezone(zone)
    try:
        formatted = parsed.strftime(format)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Bad strftime pattern {format!r}: {exc}")
    tz_name = getattr(parsed.tzinfo, "key", None) or "UTC"
    return {
        "timestamp": _iso(parsed),
        "format": format,
        "result": formatted,
        "timezone": tz_name,
    }


# ---------------------------------------------------------------------------
# MCP protocol layer (JSON-RPC 2.0 over stdio, newline-delimited)
# ---------------------------------------------------------------------------

TOOLS_SPEC = [
    {
        "name": "get_current_time",
        "description": "Get the current date and time in any IANA timezone (e.g. 'Asia/Shanghai', 'America/New_York', or aliases like 'tokyo').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "default": "UTC", "description": "IANA timezone name or city alias."},
            },
        },
    },
    {
        "name": "convert_time",
        "description": "Convert a wall-clock time between timezones, e.g. 09:00 Shanghai -> New York, including date rollover.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "Time as HH:MM or HH:MM:SS."},
                "from_tz": {"type": "string", "description": "Source IANA timezone or alias."},
                "to_tz": {"type": "string", "description": "Target IANA timezone or alias."},
                "date": {"type": "string", "description": "Optional reference date YYYY-MM-DD (defaults to today in source zone)."},
            },
            "required": ["time", "from_tz", "to_tz"],
        },
    },
    {
        "name": "time_offset",
        "description": "Get the current UTC-offset difference in minutes between two timezones (DST-aware).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_timezone": {"type": "string"},
                "to_timezone": {"type": "string"},
            },
            "required": ["from_timezone", "to_timezone"],
        },
    },
    {
        "name": "parse_natural_time",
        "description": "Parse natural-language phrases like 'next tuesday 3pm', 'tomorrow 09:00', 'in 2 hours', '3 days ago' into precise ISO timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The phrase to parse."},
                "timezone": {"type": "string", "default": "UTC", "description": "IANA timezone for the result."},
                "now": {"type": "string", "description": "Optional ISO 'now' reference for reproducible parsing (used by tests)."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "add_duration",
        "description": "Add or subtract a duration from 'now' or an ISO timestamp. Supports '+3 hours', '-2h30m', '90m', '2 days', '3 business days'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "default": "now", "description": "'now' or an ISO timestamp."},
                "duration": {"type": "string", "description": "Duration expression."},
                "timezone": {"type": "string", "default": "UTC"},
            },
            "required": ["duration"],
        },
    },
    {
        "name": "meeting_windows",
        "description": "Find common meeting windows across multiple timezones within local business hours (DST-aware).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezones": {"type": "array", "items": {"type": "string"}, "description": "List of IANA timezone names or aliases."},
                "start_hour": {"type": "integer", "default": 9, "description": "Earliest acceptable local hour."},
                "end_hour": {"type": "integer", "default": 18, "description": "Latest acceptable local hour (meeting must end by then)."},
                "date": {"type": "string", "description": "Optional date YYYY-MM-DD; defaults to today in the first zone."},
                "duration_minutes": {"type": "integer", "default": 60, "description": "Meeting length in minutes."},
            },
            "required": ["timezones"],
        },
    },
    {
        "name": "format_time",
        "description": "Format an ISO timestamp (or 'now') with a strftime pattern, optionally converting to a timezone first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string", "description": "ISO timestamp or 'now'."},
                "format": {"type": "string", "default": "%Y-%m-%d %H:%M:%S"},
                "timezone": {"type": "string", "description": "Optional target timezone."},
            },
            "required": ["timestamp"],
        },
    },
]

IMPLEMENTATIONS = {
    "get_current_time": get_current_time,
    "convert_time": convert_time,
    "time_offset": time_offset,
    "parse_natural_time": parse_natural_time,
    "add_duration": add_duration,
    "meeting_windows": meeting_windows,
    "format_time": format_time,
}


def dispatch_tool(name: str, arguments: dict) -> dict:
    """Run a tool by name; ValueError messages become clean tool errors."""
    impl = IMPLEMENTATIONS.get(name)
    if impl is None:
        raise ValueError(f"Unknown tool {name!r}. Available: {', '.join(IMPLEMENTATIONS)}.")
    return impl(**(arguments or {}))


def handle_request(msg: dict) -> dict | None:
    """Route one JSON-RPC request to a response (None for notifications)."""
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "chrono-mcp", "version": __version__},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS_SPEC}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = dispatch_tool(name, args)
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            },
        }
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    """Read newline-delimited JSON-RPC requests from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}) + "\n"
            )
            sys.stdout.flush()
            continue
        response = handle_request(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
