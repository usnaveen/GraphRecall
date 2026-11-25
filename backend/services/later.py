"""Parse "show me this later" captures without an LLM.

"show me the attention paper tomorrow"   -> text "the attention paper", tomorrow 09:00 local
"remind me about heaps in 3 days"        -> text "heaps", now + 3 days
"kafka retention settings, this weekend" -> Saturday 10:00 local

Recognised: later, tonight, tomorrow (morning/evening), in N minutes/hours/days/weeks, next week,
this weekend, next month, a weekday name, and ISO dates. Times are computed in the user's time zone
(IANA name from the client) and stored as UTC. Unrecognised phrasing defaults to tomorrow 09:00.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MORNING = time(9, 0)
EVENING = time(20, 0)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_UNITS = {"minute": 1 / 1440, "min": 1 / 1440, "hour": 1 / 24, "hr": 1 / 24, "day": 1, "week": 7}

_LEAD = re.compile(
    r"^\s*(?:(?:hey|ok|okay|please)[, ]+)*"
    r"(?:(?:can you |could you |please )?(?:show|remind|bring|resurface|surface|send)(?: back| up)?(?: me)?"
    r"(?: (?:about|of|this|that|it))*|save (?:this |that )?for|for)\s*", re.I)
_TRAIL_LATER = re.compile(r"[\s,;:-]*(?:\b(?:later|again)\b|\bback\b)(?:\s+(?:on|please))?\s*$", re.I)


@dataclass
class LaterParse:
    text: str
    show_at: datetime  # UTC
    phrase: Optional[str]


def _tz(name: Optional[str]) -> ZoneInfo | timezone:
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return timezone.utc


def _at(d: date, t: time, tz) -> datetime:
    return datetime.combine(d, t, tzinfo=tz)


def _resolve(phrase: str, now: datetime) -> Optional[datetime]:
    p = phrase.lower().strip()
    today = now.date()
    m = re.fullmatch(r"in (?:an? |(\d+|a couple of|a few) )?(minute|min|hour|hr|day|week)s?", p)
    if m:
        qty = {"a couple of": 2, "a few": 3}.get(m.group(1) or "", None)
        n = qty if qty is not None else int(m.group(1)) if m.group(1) and m.group(1).isdigit() else 1
        return now + timedelta(days=n * _UNITS[m.group(2)])
    if p == "tonight":
        t = _at(today, EVENING, now.tzinfo)
        return t if t > now else now + timedelta(hours=1)
    if p in {"tomorrow", "tomorrow morning"}:
        return _at(today + timedelta(days=1), MORNING, now.tzinfo)
    if p in {"tomorrow evening", "tomorrow night"}:
        return _at(today + timedelta(days=1), EVENING, now.tzinfo)
    if p in {"next week"}:
        return _at(today + timedelta(days=7), MORNING, now.tzinfo)
    if p in {"next month"}:
        return _at(today + timedelta(days=30), MORNING, now.tzinfo)
    if p in {"this weekend", "on the weekend", "at the weekend", "the weekend", "weekend"}:
        days = (5 - today.weekday()) % 7
        d = today + timedelta(days=days)
        t = _at(d, time(10, 0), now.tzinfo)
        return t if t > now else _at(d + timedelta(days=7 if days == 0 and now.weekday() == 6 else 1), time(10, 0), now.tzinfo)
    m = re.fullmatch(r"(?:on |next |this )?(" + "|".join(WEEKDAYS) + r")", p)
    if m:
        target = WEEKDAYS.index(m.group(1))
        days = (target - today.weekday()) % 7 or 7
        return _at(today + timedelta(days=days), MORNING, now.tzinfo)
    m = re.fullmatch(r"(?:on )?(\d{4}-\d{2}-\d{2})(?:[ t](\d{2}):(\d{2}))?", p)
    if m:
        d = date.fromisoformat(m.group(1))
        t = time(int(m.group(2)), int(m.group(3))) if m.group(2) else MORNING
        return _at(d, t, now.tzinfo)
    if p in {"later", "later today"}:
        return now + timedelta(hours=3)
    return None


_PHRASES = [
    r"in (?:an? |\d+ |a couple of |a few )?(?:minute|min|hour|hr|day|week)s?",
    r"tomorrow(?: morning| evening| night)?", r"tonight", r"next week", r"next month",
    r"(?:this |on the |at the |the )?weekend",
    r"(?:on |next |this )?(?:" + "|".join(WEEKDAYS) + r")",
    r"(?:on )?\d{4}-\d{2}-\d{2}(?:[ t]\d{2}:\d{2})?",
    r"later today", r"later",
]
_PHRASE_RE = re.compile(r"(?:^|[\s,;:(-])(" + "|".join(_PHRASES) + r")\s*[.!?)]*\s*$", re.I)


def parse_later(raw: str, *, when: Optional[str] = None, tz_name: Optional[str] = None,
                now: Optional[datetime] = None) -> LaterParse:
    """Split a capture into the thing to resurface and when. ``when`` (from a picker) wins over text."""
    tz = _tz(tz_name)
    now_local = (now or datetime.now(timezone.utc)).astimezone(tz)
    text = " ".join((raw or "").split())
    phrase = None
    show_at = None
    if when:
        show_at = _resolve(when, now_local)
        phrase = when if show_at else None
    if show_at is None:
        m = _PHRASE_RE.search(text)
        if m:
            cand = m.group(1)
            resolved = _resolve(cand, now_local)
            if resolved:
                show_at, phrase = resolved, cand
                text = text[: m.start(1)].rstrip(" ,;:-(")
    if show_at is None:
        show_at = _at(now_local.date() + timedelta(days=1), MORNING, tz)
    cleaned = _TRAIL_LATER.sub("", _LEAD.sub("", text)).strip(" ,;:-")
    # "show me this later" from the share sheet leaves no text; the shared URL is the item then.
    return LaterParse(text=cleaned, show_at=show_at.astimezone(timezone.utc), phrase=phrase)
