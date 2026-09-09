from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

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
        assert "/static/logo.svg" in home.text
        assert "/static/logo.png" in home.text
        assert "Sports" in home.text
        assert "Channels" in home.text
        assert "When live" not in home.text
        assert "Tap a chip" not in home.text
        assert "Import session" in home.text
        assert "tv.youtube.com" in home.text
        assert "youtube.com/tv" in home.text
        assert "YouTube TV" not in home.text
        assert "YTTV sports events" in home.text
        assert "Continue with Google" not in home.text
        assert 'type="password"' not in home.text
        assert 'name="password"' not in home.text
        assert 'id="refresh-toast"' in home.text
        assert "data-last-refresh" in home.text
        assert "data-all-events" in home.text
        assert "data-refreshing" in home.text
        health = client.get("/health").json()
        assert health["signed_in"] is False
        assert health["session_expired"] is False
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


def test_expired_session_is_not_shown_as_signed_in():
    from yttv_epg.app import state
    from yttv_epg.session_store import SavedSession

    with TestClient(app) as client:
        state.session = SavedSession(
            kind="cookies",
            cookies=[{"name": "SAPISID", "value": "x", "domain": ".youtube.com"}],
        )
        state.store.save(state.session)
        state.catalog.set_error("YTTV session expired. Sign in again on tv.youtube.com.")
        try:
            home = client.get("/")
            assert home.status_code == 200
            assert "Session expired" in home.text
            assert ">Signed in<" not in home.text
            assert 'data-session-expired="true"' in home.text
            assert "Cookies are still stored" in home.text
            assert "Sign out" in home.text
            assert "Import session" in home.text
            assert 'id="idle-auth" hidden' not in home.text
            assert home.text.count("YTTV session expired") == 1
            status = client.get("/api/status").json()
            assert status["signed_in"] is True
            assert status["session_expired"] is True
            health = client.get("/health").json()
            assert health["signed_in"] is True
            assert health["session_expired"] is True
        finally:
            client.post("/api/auth/logout")
        after = client.get("/health").json()
        assert after["signed_in"] is False
        assert after["session_expired"] is False
        assert after["last_error"] is None


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
        from yttv_epg.app import _set_lane_cache

        assignments = pack_lanes([plus, linear], 8)
        state.catalog.replace([plus, linear], assignments)
        _set_lane_cache(assignments)
        hidden = client.post("/api/filters", json={"toggle_channel": "ESPN+"})
        assert hidden.status_code == 200
        assert hidden.json()["hidden_channels"] == ["ESPN+"]
        home = client.get("/")
        assert "UConn vs Maryland" in home.text
        assert "Cowboys vs Giants" in home.text
        uconn_row = home.text.split("UConn vs Maryland")[0][-500:]
        assert 'data-channel="ESPN+"' in uconn_row
        assert "hidden" in uconn_row
        cowboys_row = home.text.split("Cowboys vs Giants")[0].rsplit("<tr", 1)[-1]
        assert "hidden" not in cowboys_row.split(">")[0]
        xml = client.get("/xmltv.xml").text
        assert "UConn vs Maryland" not in xml
        assert "Cowboys vs Giants" in xml
        assert "ESPN+ · 1" in home.text
        assert "Select all" in home.text
        assert "Unselect all" in home.text
        assert "Tap a chip" not in home.text
        hidden_all = client.post("/api/filters", json={"hidden_channels": ["ESPN+", "ESPN"]})
        assert set(hidden_all.json()["hidden_channels"]) == {"ESPN+", "ESPN"}
        empty = client.get("/")
        assert "UConn vs Maryland" in empty.text
        assert "Cowboys vs Giants" in empty.text
        for title in ("UConn vs Maryland", "Cowboys vs Giants"):
            assert "hidden" in empty.text.split(title)[0][-500:]
        xml_empty = client.get("/xmltv.xml").text
        assert "UConn vs Maryland" not in xml_empty
        assert "Cowboys vs Giants" not in xml_empty
        client.post("/api/filters", json={"hidden_channels": []})
        state.catalog.replace([], [])
        _set_lane_cache([])


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
        from yttv_epg.app import _set_lane_cache

        assignments = pack_lanes([upcoming, linked], 8)
        state.catalog.replace([upcoming, linked], assignments)
        _set_lane_cache(assignments)
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
        _set_lane_cache([])


def test_dashboard_omits_non_sports_station_families():
    from datetime import datetime, timedelta, timezone

    from yttv_epg.app import state
    from yttv_epg.lanes import pack_lanes
    from yttv_epg.parse import Airing
    from yttv_epg.sports import visible_events

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
        from yttv_epg.app import _set_lane_cache

        rows = [wild, oxygen, espn]
        assignments = pack_lanes(visible_events(rows, require_watch_link=True), 8)
        state.catalog.replace(rows, assignments)
        _set_lane_cache(assignments)
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
        _set_lane_cache([])


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


@pytest.mark.asyncio
async def test_light_refresh_resolves_watch_ids_and_skips_noop():
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _set_lane_cache, refresh_watch_ids, state
    from yttv_epg.lanes import pack_lanes
    from yttv_epg.parse import Airing
    from yttv_epg.session_store import SavedSession

    start = datetime.now(timezone.utc)
    pending = Airing(
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
        video_id="abcdefghijk",
        title="UConn vs Maryland",
        station="ESPN",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/abcdefghijk",
        sport="Football",
        channel="ESPN",
    )
    resolved = Airing(
        video_id="resolvedxx1",
        title=pending.title,
        station=pending.station,
        kind="event",
        start=pending.start,
        end=pending.end,
        deeplink="https://tv.youtube.com/watch/resolvedxx1",
        sport="Football",
        channel="ESPN+",
        entity_id=pending.entity_id,
    )
    with TestClient(app) as client:
        _ = client
        state.session = SavedSession(
            kind="cookies",
            cookies=[{"name": "SAPISID", "value": "x", "domain": ".youtube.com"}],
        )
        assignments = pack_lanes([linked], 8)
        state.catalog.replace([pending, linked], assignments)
        _set_lane_cache(assignments)
        before = state.catalog.meta().get("last_refresh")
        with patch.object(state.innertube, "resolve_soon", new=AsyncMock(return_value=[resolved])):
            result = await refresh_watch_ids()
        assert result["resolved"] == 1
        assert result["changed"] is True
        by_title = {item.title: item for item in state.catalog.events()}
        assert by_title[pending.title].watch_id() == "resolvedxx1"
        after = state.catalog.meta().get("last_refresh")
        assert after != before
        with patch.object(state.innertube, "resolve_soon", new=AsyncMock(return_value=[])) as resolve:
            noop = await refresh_watch_ids()
        assert noop["changed"] is False
        assert noop["resolved"] == 0
        resolve.assert_not_called()
        assert state.catalog.meta().get("last_refresh") == after
        state.catalog.replace([], [])
        _set_lane_cache([])
        state.session = None


@pytest.mark.asyncio
async def test_full_mine_drops_cancelled_event():
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _set_lane_cache, refresh_catalog, state
    from yttv_epg.innertube import MineResult
    from yttv_epg.lanes import pack_lanes
    from yttv_epg.parse import Airing
    from yttv_epg.session_store import SavedSession

    start = datetime.now(timezone.utc)
    cancelled = Airing(
        video_id="zzzzzzzzzzz",
        title="Cancelled vs Gone",
        station="ESPN",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/zzzzzzzzzzz",
        sport="Football",
        channel="ESPN",
    )
    kept = Airing(
        video_id="abcdefghijk",
        title="UConn vs Maryland",
        station="ESPN",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/abcdefghijk",
        sport="Football",
        channel="ESPN",
    )
    with TestClient(app) as client:
        _ = client
        state.session = SavedSession(
            kind="cookies",
            cookies=[{"name": "SAPISID", "value": "x", "domain": ".youtube.com"}],
        )
        assignments = pack_lanes([cancelled, kept], 8)
        state.catalog.replace([cancelled, kept], assignments)
        _set_lane_cache(assignments)
        mined = MineResult(airings=[kept], client="WEB_UNPLUGGED", browse_id="FEunplugged_epg", raw={})
        with patch.object(state.innertube, "mine", new=AsyncMock(return_value=mined)):
            await refresh_catalog()
        titles = {item.title for item in state.catalog.events()}
        assert titles == {"UConn vs Maryland"}
        state.catalog.replace([], [])
        _set_lane_cache([])
        state.session = None
        state.last_full_mine_at = None
