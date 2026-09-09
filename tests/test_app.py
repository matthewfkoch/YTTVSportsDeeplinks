from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, patch

os.environ["YTTV_EPG_DATA_DIR"] = tempfile.mkdtemp(prefix="yttv-epg-test-")
os.environ["ENABLE_CHROME"] = "0"
os.environ["ESPN_SCHEDULE"] = "0"

from fastapi.testclient import TestClient

from yttv_epg.app import app

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSAPISID\tsapi-value\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tsid-value\n"
)


def test_dashboard_imports_cookies_not_a_password_or_oauth_form():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "YTTV Sports Deeplinks" in home.text
        assert "/static/logo.png" in home.text
        assert "Sports" in home.text
        assert "Channels" in home.text
        assert "When live" not in home.text
        assert "Tap a chip" not in home.text
        assert "Import session" in home.text
        assert "tv.youtube.com" in home.text
        assert "youtube.com/tv" in home.text
        assert "Continue with Google" not in home.text
        assert 'type="password"' not in home.text
        assert 'name="password"' not in home.text
        assert 'id="refresh-toast"' in home.text
        assert "data-last-refresh" in home.text
        assert "data-refreshing" in home.text
        health = client.get("/health").json()
        assert health["signed_in"] is False
        assert health["refreshing"] is False
        status = client.get("/api/status").json()
        assert status["refreshing"] is False
        whatson = client.get("/whatson/1")
        assert whatson.status_code == 200
        assert whatson.json() == {"ok": False, "lane": 1, "deeplink_url": None}
        chrome = client.get("/api/auth/chrome/status").json()
        assert chrome["available"] is False
        capture = client.post("/api/auth/chrome/capture")
        assert capture.status_code == 503


def test_import_cookies_rejects_missing_sapisid():
    with TestClient(app) as client:
        response = client.post("/api/auth/cookies", json={"cookies": "SID=abc; HSID=def"})
        assert response.status_code == 400
        assert "SAPISID" in response.json()["detail"]
        assert client.get("/health").json()["signed_in"] is False


def test_import_cookies_saves_session():
    with TestClient(app) as client:
        with (
            patch("yttv_epg.app.InnerTubeClient.probe", new=AsyncMock(return_value="WEB_UNPLUGGED")),
            patch("yttv_epg.app.refresh_catalog", new=AsyncMock(return_value={"ok": True, "events": 0})),
        ):
            response = client.post("/api/auth/cookies", json={"cookies": NETSCAPE})
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert client.get("/health").json()["signed_in"] is True
        client.post("/api/auth/logout")
        assert client.get("/health").json()["signed_in"] is False


def test_channel_filter_hides_espn_plus_from_lanes():
    from datetime import datetime, timedelta, timezone

    from yttv_epg.app import state
    from yttv_epg.lanes import pack_lanes
    from yttv_epg.parse import Airing

    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    plus = Airing(
        video_id="YGUvoKVT5qk",
        title="UConn vs Maryland",
        station="ESPN Unlimited",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
        sport="Football",
        channel="ESPN+",
    )
    linear = Airing(
        video_id="bj3v-DQPnNs",
        title="Cowboys vs Giants",
        station="ESPN",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/bj3v-DQPnNs",
        sport="Football",
        channel="ESPN",
    )
    with TestClient(app) as client:
        state.catalog.replace([plus, linear], pack_lanes([plus, linear], 8))
        hidden = client.post("/api/filters", json={"toggle_channel": "ESPN+"})
        assert hidden.status_code == 200
        assert hidden.json()["hidden_channels"] == ["ESPN+"]
        home = client.get("/")
        assert "UConn vs Maryland" not in home.text
        assert "Cowboys vs Giants" in home.text
        assert "ESPN+ · 1" in home.text
        assert "Select all" in home.text
        assert "Unselect all" in home.text
        assert "Tap a chip" not in home.text
        hidden_all = client.post("/api/filters", json={"hidden_channels": ["ESPN+", "ESPN"]})
        assert set(hidden_all.json()["hidden_channels"]) == {"ESPN+", "ESPN"}
        empty = client.get("/")
        assert "UConn vs Maryland" not in empty.text
        assert "Cowboys vs Giants" not in empty.text
        client.post("/api/filters", json={"hidden_channels": []})
        state.catalog.replace([], [])


def test_dashboard_and_xmltv_omit_events_without_watch_link():
    from datetime import datetime, timedelta, timezone

    from yttv_epg.app import state
    from yttv_epg.lanes import pack_lanes
    from yttv_epg.parse import Airing

    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    upcoming = Airing(
        video_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
        title="East Carolina at Alabama",
        station="ESPN+",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="",
        sport="Football",
        channel="ESPN+",
        entity_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
    )
    linked = Airing(
        video_id="YGUvoKVT5qk",
        title="UConn vs Maryland",
        station="ESPN Unlimited",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
        sport="Football",
        channel="ESPN+",
    )
    with TestClient(app) as client:
        state.catalog.replace([upcoming, linked], pack_lanes([upcoming, linked], 8))
        home = client.get("/")
        assert home.status_code == 200
        assert "UConn vs Maryland" in home.text
        assert "East Carolina at Alabama" not in home.text
        assert "When live" not in home.text
        xml = client.get("/xmltv.xml").text
        assert "UConn vs Maryland" in xml
        assert "East Carolina at Alabama" not in xml
        events = client.get("/events").json()
        assert events["count"] == 1
        assert events["events"][0]["title"] == "UConn vs Maryland"
        state.catalog.replace([], [])


def test_dashboard_omits_non_sports_station_families():
    from datetime import datetime, timedelta, timezone

    from yttv_epg.app import state
    from yttv_epg.lanes import pack_lanes
    from yttv_epg.parse import Airing

    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    wild = Airing(
        video_id="natgeowild1",
        title="Cougars vs Wolves",
        station="Nat Geo Wild",
        kind="event",
        start=start,
        end=start + timedelta(hours=1),
        deeplink="https://tv.youtube.com/watch/natgeowild1",
        sport="Hockey",
        channel="Nat Geo Wild",
    )
    oxygen = Airing(
        video_id="oxygenevs01",
        title="Killer vs Killer",
        station="Oxygen",
        kind="event",
        start=start,
        end=start + timedelta(hours=1),
        deeplink="https://tv.youtube.com/watch/oxygenevs01",
        sport="Combat",
        channel="Oxygen",
    )
    espn = Airing(
        video_id="bj3v-DQPnNs",
        title="Cowboys vs Giants",
        station="ESPN",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/bj3v-DQPnNs",
        sport="Football",
        channel="ESPN",
    )
    with TestClient(app) as client:
        state.catalog.replace([wild, oxygen, espn], pack_lanes([wild, oxygen, espn], 8))
        home = client.get("/")
        assert home.status_code == 200
        assert "Cowboys vs Giants" in home.text
        assert "Nat Geo Wild" not in home.text
        assert "Oxygen" not in home.text
        assert "Cougars vs Wolves" not in home.text
        xml = client.get("/xmltv.xml").text
        assert "Cowboys vs Giants" in xml
        assert "Cougars vs Wolves" not in xml
        events = client.get("/events").json()
        assert [item["station"] for item in events["events"]] == ["ESPN"]
        state.catalog.replace([], [])


def test_status_reports_refreshing_flag():
    from yttv_epg.app import state

    with TestClient(app) as client:
        assert client.get("/api/status").json()["refreshing"] is False
        state.refreshing = True
        try:
            assert client.get("/api/status").json()["refreshing"] is True
            assert client.get("/health").json()["refreshing"] is True
        finally:
            state.refreshing = False
        assert client.get("/api/status").json()["refreshing"] is False


def test_feeds_follow_request_host_when_public_base_is_localhost():
    with TestClient(app, base_url="http://192.168.1.20:8095") as client:
        home = client.get("/")
        assert "http://192.168.1.20:8095/api/export" in home.text
        playlist = client.get("/playlist.m3u").text
        assert "http://192.168.1.20:8095/whatson/1" in playlist
        assert 'tvg-logo="http://192.168.1.20:8095/static/logo.png"' in playlist
        xml = client.get("/xmltv.xml").text
        assert '<icon src="http://192.168.1.20:8095/static/logo.png" />' in xml
        logo = client.get("/static/logo.png")
        assert logo.status_code == 200
        assert logo.headers["content-type"].startswith("image/")
        export = client.get("/api/export").json()
        assert export[0]["url"].startswith("http://192.168.1.20:8095/whatson/1")
