from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yttv_epg.lanes import pack_lanes, whatson
from yttv_epg.parse import Airing


def _event(vid: str, start: datetime, hours: float, title: str) -> Airing:
    return Airing(
        video_id=vid,
        title=title,
        station="ESPN Unlimited",
        kind="event",
        start=start,
        end=start + timedelta(hours=hours),
        deeplink=f"https://tv.youtube.com/watch/{vid}",
    )


def test_pack_overlapping_events_use_separate_lanes():
    t0 = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    events = [
        _event("aaaaaaaaaaa", t0, 3, "Game A"),
        _event("bbbbbbbbbbb", t0, 3, "Game B"),
        _event("ccccccccccc", t0 + timedelta(hours=4), 2, "Game C"),
    ]
    rows = pack_lanes(events, lane_count=2)
    lanes = {row.airing.video_id: row.lane for row in rows}
    assert lanes["aaaaaaaaaaa"] == 1
    assert lanes["bbbbbbbbbbb"] == 2
    assert lanes["ccccccccccc"] == 1


def test_whatson_returns_current_deeplink():
    t0 = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    events = [_event("YGUvoKVT5qk", t0, 3, "UConn vs Maryland")]
    rows = pack_lanes(events, lane_count=1)
    current = whatson(rows, 1, t0 + timedelta(minutes=30))
    assert current is not None
    assert current.deeplink == "https://tv.youtube.com/watch/YGUvoKVT5qk"
    assert whatson(rows, 1, t0 + timedelta(hours=5)) is None


def test_pack_lanes_skips_events_without_watch_link():
    t0 = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    upcoming = Airing(
        video_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
        title="East Carolina at Alabama",
        station="ESPN+",
        kind="event",
        start=t0,
        end=t0 + timedelta(hours=3),
        deeplink="",
        entity_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
    )
    linked = _event("YGUvoKVT5qk", t0, 3, "UConn vs Maryland")
    rows = pack_lanes([upcoming, linked], lane_count=2)
    assert [row.airing.video_id for row in rows] == ["YGUvoKVT5qk"]
