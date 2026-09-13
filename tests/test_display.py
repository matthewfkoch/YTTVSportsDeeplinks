from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from yttv_epg.display import event_for_ui, format_when
from yttv_epg.parse import Airing


def test_format_when_today_and_weekday():
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 9, 5, 14, 30, tzinfo=timezone.utc)
    today = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    later = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)
    assert format_when(today, now=now, tz=tz) == "Today · 12:00 PM"
    assert format_when(later, now=now, tz=tz) == "Monday, September 7 · 12:00 PM"


def test_event_for_ui_uses_product_logo_when_artwork_is_missing():
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    event = Airing(
        video_id="tinyiconxx1",
        title="Inter Milan at Udinese Calcio",
        station="Universo",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/tinyiconxx1",
    )
    payload = event_for_ui(event, tz=ZoneInfo("America/New_York"))
    assert payload["artwork"] == "/static/logo.png"
    assert payload["artwork_fallback"] is True
