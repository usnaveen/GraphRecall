"""'Show me this later' parsing: time phrases, cleanup, time zones."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.services.later import parse_later

KOLKATA = "Asia/Kolkata"
# Wednesday 2026-11-25 14:30 in Kolkata
NOW = datetime(2026, 11, 25, 14, 30, tzinfo=ZoneInfo(KOLKATA)).astimezone(timezone.utc)


def local(p):
    return p.show_at.astimezone(ZoneInfo(KOLKATA))


@pytest.mark.parametrize("raw,text,expect", [
    ("show me the attention paper tomorrow", "the attention paper", (2026, 11, 26, 9, 0)),
    ("remind me about heaps in 3 days", "heaps", (2026, 11, 28, 14, 30)),
    ("kafka retention settings, this weekend", "kafka retention settings", (2026, 11, 28, 10, 0)),
    ("bring back the LoRA notes on friday", "the LoRA notes", (2026, 11, 27, 9, 0)),
    ("Show me this later", "", None),
    ("revisit union-find tonight", "revisit union-find", (2026, 11, 25, 20, 0)),
    ("the monad explanation next week", "the monad explanation", (2026, 12, 2, 9, 0)),
    ("dijkstra proof in 2 hours", "dijkstra proof", (2026, 11, 25, 16, 30)),
    ("CAP theorem examples", "CAP theorem examples", (2026, 11, 26, 9, 0)),  # default: tomorrow 9am
])
def test_phrases(raw, text, expect):
    p = parse_later(raw, tz_name=KOLKATA, now=NOW)
    assert p.text == text
    if expect:
        assert local(p).timetuple()[:5] == expect


def test_later_alone_is_three_hours():
    p = parse_later("show me this later", tz_name=KOLKATA, now=NOW)
    assert local(p).timetuple()[:5] == (2026, 11, 25, 17, 30) and p.phrase == "later"


def test_picker_value_wins_and_words_stay():
    p = parse_later("read about friday's release", when="in 1 week", tz_name=KOLKATA, now=NOW)
    assert p.text == "read about friday's release" and local(p).day == 2


def test_weekday_today_means_next_week_and_bad_tz_is_utc():
    p = parse_later("gym plan wednesday", tz_name="Not/AZone", now=NOW)
    assert p.show_at.date().isoformat() == "2026-12-02" and p.show_at.hour == 9
