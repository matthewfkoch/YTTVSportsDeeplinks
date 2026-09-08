from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from yttv_epg.display import format_when


def test_format_when_today_and_weekday():
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 9, 5, 14, 30, tzinfo=timezone.utc)
    today = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    later = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)
    assert format_when(today, now=now, tz=tz) == "Today · 12:00 PM"
    assert format_when(later, now=now, tz=tz) == "Monday, September 7 · 12:00 PM"
