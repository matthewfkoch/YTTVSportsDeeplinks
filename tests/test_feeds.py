from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yttv_epg.feeds import apituner_export, m3u, whatson_payload, xmltv
from yttv_epg.lanes import LaneAssignment, pack_lanes
from yttv_epg.parse import Airing


def _airing() -> Airing:
    start = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    return Airing(
        video_id="YGUvoKVT5qk",
        title="UConn vs Maryland",
        station="ESPN Unlimited",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
    )


def test_xmltv_contains_event_and_deeplink():
    rows = [LaneAssignment(lane=1, airing=_airing())]
    body = xmltv(rows, lane_count=2)
    assert 'id="yttv-sports-1"' in body
    assert "UConn vs Maryland" in body
    assert "https://tv.youtube.com/watch/YGUvoKVT5qk" in body
    assert 'channel="yttv-sports-1"' in body


def test_xmltv_omits_events_without_watch_link():
    start = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    upcoming = Airing(
        video_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
        title="East Carolina at Alabama",
        station="ESPN+",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="",
        entity_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
    )
    body = xmltv([LaneAssignment(lane=1, airing=upcoming)], lane_count=1)
    assert "East Carolina at Alabama" not in body
    assert "<programme" not in body


def test_m3u_uses_whatson_resolver():
    body = m3u(
        base_url="http://192.168.1.10:8095",
        lane_count=1,
        start_channel=9100,
        package_name="com.google.android.youtube.tvunplugged",
        alternate_package_name="com.amazon.firetv.youtube.tv",
    )
    assert "/whatson/1?format=json" in body
    assert "dynamic_url_json_key=deeplink_url" in body
    assert "tvg-chno=\"9100\"" in body


def test_apituner_export_is_separate_source():
    rows = apituner_export(
        base_url="http://yttvsportsdeeplinks:8095",
        lane_count=1,
        start_channel=9100,
        package_name="com.google.android.youtube.tvunplugged",
        alternate_package_name="com.amazon.firetv.youtube.tv",
    )
    assert rows[0]["source"] == "yttv-sports"
    assert rows[0]["tvg_id"] == "yttv-sports-1"
    assert rows[0]["package_name"] == "com.google.android.youtube.tvunplugged"


def test_whatson_payload_empty_lane():
    payload = whatson_payload(3, None)
    assert payload == {"ok": False, "lane": 3, "deeplink_url": None}


def test_pack_then_xmltv_round_trip():
    rows = pack_lanes([_airing()], lane_count=1)
    assert "YGUvoKVT5qk" in xmltv(rows, 1)
