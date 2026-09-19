from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from yttv_epg.feeds import apituner_export, lane_id, m3u, whatson_payload, xmltv
from yttv_epg.lanes import LaneAssignment, pack_lanes, whatson
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
        artwork="https://yt3.ggpht.com/UConnMarylandArt=w960-h540-p-ns-nd",
    )


def test_xmltv_contains_event_and_deeplink():
    rows = [LaneAssignment(lane=1, airing=_airing())]
    body = xmltv(rows, lane_count=2, base_url="http://192.168.1.10:8095")
    assert 'id="yttv-sports-1"' in body
    assert "UConn vs Maryland" in body
    assert "https://tv.youtube.com/watch/YGUvoKVT5qk" in body
    assert 'channel="yttv-sports-1"' in body
    assert '<icon src="http://192.168.1.10:8095/static/logo.png" />' in body
    assert (
        '<icon src="https://yt3.ggpht.com/UConnMarylandArt=w720-h540-p-ns-nd" '
        'width="720" height="540" />'
    ) in body


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
    assert 'tvg-logo="http://192.168.1.10:8095/static/logo.png"' in body
    assert 'url-tvg="http://192.168.1.10:8095/xmltv.xml"' in body
    assert 'x-tvg-url="http://192.168.1.10:8095/xmltv.xml"' in body
    assert 'tvg-id="yttv-sports-1"' in body
    assert 'channel-id="yttv-sports-1"' in body


def test_xmltv_uses_product_logo_when_event_has_no_poster():
    start = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    game = Airing(
        video_id="tinyiconxx1",
        title="Inter Milan at Udinese Calcio",
        station="Universo",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/tinyiconxx1",
    )
    body = xmltv([LaneAssignment(lane=1, airing=game)], lane_count=1, base_url="http://192.168.1.10:8095")
    assert (
        '<icon src="http://192.168.1.10:8095/static/logo.png" '
        'width="720" height="540" />'
    ) in body


def test_xmltv_keeps_square_logo_dimensions():
    start = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    game = Airing(
        video_id="universo001",
        title="Inter Milan at Udinese Calcio",
        station="Universo",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/universo001",
        artwork="https://yt3.ggpht.com/UniversoChip=w540-h540-p-ns-nd",
    )
    body = xmltv([LaneAssignment(lane=1, airing=game)], lane_count=1)
    assert (
        '<icon src="https://yt3.ggpht.com/UniversoChip=w540-h540-p-ns-nd" '
        'width="540" height="540" />'
    ) in body


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


def test_whatson_payload_includes_fallback_artwork():
    payload = whatson_payload(1, _airing())
    assert payload["artwork"].startswith("https://yt3.ggpht.com/")
    start = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    bare = Airing(
        video_id="tinyiconxx1",
        title="Inter Milan at Udinese Calcio",
        station="Universo",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/tinyiconxx1",
    )
    assert whatson_payload(1, bare)["artwork"] == "/static/logo.png"


def test_pack_then_xmltv_round_trip():
    rows = pack_lanes([_airing()], lane_count=1)
    assert "YGUvoKVT5qk" in xmltv(rows, 1)


def test_xmltv_channel_ids_match_m3u_tvg_ids():
    rows = pack_lanes([_airing()], lane_count=3)
    xml_body = xmltv(rows, lane_count=3, base_url="http://192.168.1.10:8095")
    playlist = m3u(
        base_url="http://192.168.1.10:8095",
        lane_count=3,
        start_channel=9100,
        package_name="com.google.android.youtube.tvunplugged",
        alternate_package_name="com.amazon.firetv.youtube.tv",
    )
    channel_ids = re.findall(r'<channel id="([^"]+)"', xml_body)
    tvg_ids = re.findall(r'tvg-id="([^"]+)"', playlist)
    expected = [lane_id(lane) for lane in range(1, 4)]
    assert channel_ids == tvg_ids == expected
    assert 'channel="yttv-sports-1"' in xml_body
    assert 'url-tvg="http://192.168.1.10:8095/xmltv.xml"' in playlist


def test_xmltv_is_well_formed_and_programmes_do_not_overlap():
    t0 = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    rows = pack_lanes(
        [
            Airing(
                video_id="aaaaaaaaaaa",
                title="A & B <Final>",
                station="ESPN Unlimited",
                kind="event",
                start=t0,
                end=t0 + timedelta(hours=3),
                deeplink="https://tv.youtube.com/watch/aaaaaaaaaaa",
                sport="Football",
                channel="ESPN+",
            ),
            Airing(
                video_id="bbbbbbbbbbb",
                title="Night Game\x00",
                station="ESPN",
                kind="event",
                start=t0,
                end=t0 + timedelta(hours=3),
                deeplink="https://tv.youtube.com/watch/bbbbbbbbbbb",
                sport="Football",
                channel="ESPN",
            ),
            Airing(
                video_id="ccccccccccc",
                title="Late Game",
                station="ESPN",
                kind="event",
                start=t0 + timedelta(hours=4),
                end=t0 + timedelta(hours=6),
                deeplink="https://tv.youtube.com/watch/ccccccccccc",
                sport="Football",
                channel="ESPN",
            ),
        ],
        lane_count=2,
    )
    body = xmltv(rows, lane_count=2, base_url="http://192.168.1.10:8095")
    assert "\x00" not in body
    assert "A &amp; B &lt;Final&gt;" in body
    root = ET.fromstring(body)
    assert root.tag == "tv"
    by_channel: dict[str, list[tuple[str, str]]] = {}
    for programme in root.findall("programme"):
        channel = programme.get("channel") or ""
        by_channel.setdefault(channel, []).append(
            (programme.get("start") or "", programme.get("stop") or "")
        )
        assert channel in {item.get("id") for item in root.findall("channel")}
    for times in by_channel.values():
        times.sort()
        for index in range(1, len(times)):
            assert times[index - 1][1] <= times[index][0]


def test_whatson_matches_xmltv_programme_on_that_lane():
    t0 = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    rows = pack_lanes(
        [
            Airing(
                video_id="aaaaaaaaaaa",
                title="Game A",
                station="ESPN",
                kind="event",
                start=t0,
                end=t0 + timedelta(hours=3),
                deeplink="https://tv.youtube.com/watch/aaaaaaaaaaa",
            ),
            Airing(
                video_id="bbbbbbbbbbb",
                title="Game B",
                station="ESPN",
                kind="event",
                start=t0,
                end=t0 + timedelta(hours=3),
                deeplink="https://tv.youtube.com/watch/bbbbbbbbbbb",
            ),
        ],
        lane_count=2,
    )
    when = t0 + timedelta(minutes=30)
    body = xmltv(rows, lane_count=2)
    root = ET.fromstring(body)
    for row in rows:
        current = whatson(rows, row.lane, when)
        assert current is not None
        assert current.deeplink == row.airing.deeplink
        titles = [
            (item.findtext("title") or "")
            for item in root.findall("programme")
            if item.get("channel") == lane_id(row.lane)
        ]
        assert row.airing.title in titles
        payload = whatson_payload(row.lane, current)
        assert payload["ok"] is True
        assert payload["deeplink_url"] == row.airing.deeplink
