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
        assert "Your sports guide, ready to watch." in home.text
        assert "dedicated YTTV Google account" in home.text
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
        assert client.get("/docs").status_code == 404
        assert client.get("/linear").status_code == 404
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


def test_signed_in_dashboard_does_not_connect_login_desktop():
    from yttv_epg.app import state
    from yttv_epg.session_store import SavedSession

    with TestClient(app) as client:
        state.session = SavedSession(
            kind="browser",
            cookies=[{"name": "SAPISID", "value": "x", "domain": ".youtube.com"}],
        )
        state.store.save(state.session)
        state.catalog.clear_error()
        try:
            with (
                patch("yttv_epg.app.settings.enable_chrome", True),
                patch("yttv_epg.app._chrome_snapshot", new=AsyncMock(return_value={})),
            ):
                home = client.get("/")
            assert home.status_code == 200
            assert 'id="idle-auth" hidden' in home.text
            assert "desktop-frame" not in home.text
            assert "<iframe" not in home.text
        finally:
            client.post("/api/auth/logout")


def test_signed_out_dashboard_embeds_login_desktop_when_chrome_enabled():
    with TestClient(app) as client:
        with (
            patch("yttv_epg.app.settings.enable_chrome", True),
            patch("yttv_epg.app._chrome_snapshot", new=AsyncMock(return_value={})),
        ):
            home = client.get("/")
        assert home.status_code == 200
        assert 'id="desktop-frame"' in home.text
        assert "autoconnect=true" in home.text


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


def test_successful_probe_clears_expired_flag_before_refresh():
    from yttv_epg.app import state
    from yttv_epg.innertube import MineError

    with TestClient(app) as client:
        state.catalog.set_error("YTTV session expired. Sign in again on tv.youtube.com.")
        with (
            patch("yttv_epg.app.InnerTubeClient.probe", new=AsyncMock(return_value="WEB_UNPLUGGED")),
            patch(
                "yttv_epg.app.refresh_catalog",
                new=AsyncMock(side_effect=MineError("guide timed out")),
            ),
        ):
            response = client.post("/api/auth/cookies", json={"cookies": NETSCAPE})
        assert response.status_code == 200
        health = client.get("/health").json()
        assert health["signed_in"] is True
        assert health["session_expired"] is False
        client.post("/api/auth/logout")


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
        assert 'url-tvg="http://192.168.1.20:8095/xmltv.xml"' in playlist
        assert 'x-tvg-url="http://192.168.1.20:8095/xmltv.xml"' in playlist
        xml = client.get("/xmltv.xml").text
        assert '<icon src="http://192.168.1.20:8095/static/logo.png" />' in xml
        assert 'id="yttv-sports-1"' in xml
        assert 'tvg-id="yttv-sports-1"' in playlist
        logo = client.get("/static/logo.png")
        assert logo.status_code == 200
        assert logo.headers["content-type"].startswith("image/")
        export = client.get("/api/export").json()
        assert export[0]["url"].startswith("http://192.168.1.20:8095/whatson/1")


def test_dashboard_lane_count_repacks_feeds_and_survives_restart(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from xml.etree import ElementTree as ET

    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    from yttv_epg.parse import Airing

    path = tmp_path / "catalog.sqlite"
    catalog = Catalog(path)
    monkeypatch.setattr(module.state, "catalog", catalog)
    monkeypatch.setattr(module.state, "lane_assignments", None)
    monkeypatch.setattr(module.state, "espn_listings", [])
    monkeypatch.setattr(module.settings, "lane_count", 1)
    now = datetime.now(timezone.utc)
    games = [
        Airing(watch, title, "ESPN", "event", now - timedelta(minutes=1),
               now + timedelta(hours=2), f"https://tv.youtube.com/watch/{watch}", sport="Football")
        for watch, title in [("abcdefghijk", "Alabama at Georgia"), ("lmnopqrstuv", "Michigan at Ohio State")]
    ]
    catalog.replace(games, [])

    with TestClient(app) as client:
        assert 'value="1" required' in client.get("/").text
        assert client.get("/api/status").json()["dropped"] == 1
        original = client.get("/api/export").json()
        first_game = client.get("/whatson/1").json()

        for invalid in (0, -1, 751, True, "2", 2.5, None):
            response = client.post("/api/filters", json={"lane_count": invalid, "hide_spanish": True})
            assert response.status_code == 400
        assert not catalog.hide_spanish()
        assert client.get("/api/export").json() == original

        saved = client.post("/api/filters", json={"lane_count": 2}).json()
        assert (saved["lane_count"], saved["lanes_used"], saved["dropped"]) == (2, 2, 0)
        assert client.get("/whatson/1").json() == first_game
        assert client.get("/whatson/2").json()["ok"]
        export = client.get("/api/export").json()
        assert export[:1] == original and export[1]["number"] == original[0]["number"] + 1
        assert 'tvg-id="yttv-sports-2"' in client.get("/playlist.m3u").text
        guide = ET.fromstring(client.get("/xmltv.xml").text)
        assert [item.get("channel") for item in guide.findall("programme")] == ["yttv-sports-1", "yttv-sports-2"]

    monkeypatch.setattr(module.state, "catalog", Catalog(path))
    monkeypatch.setattr(module.state, "lane_assignments", None)
    monkeypatch.setattr(module.settings, "lane_count", 3)
    with TestClient(app) as client:
        assert client.get("/api/status").json()["lane_count"] == 2
        assert client.get("/api/export").json() == export
        saved = client.post("/api/filters", json={"lane_count": 1}).json()
        assert (saved["lane_count"], saved["lanes_used"], saved["dropped"]) == (1, 1, 1)
        assert client.get("/api/export").json() == original
        assert "yttv-sports-2" not in client.get("/playlist.m3u").text
        assert "yttv-sports-2" not in client.get("/xmltv.xml").text
        assert client.get("/whatson/1").json() == first_game
        assert client.get("/whatson/2").status_code == 404


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
        with patch.object(state.innertube, "resolve_soon", new=AsyncMock(return_value=[resolved])), patch(
            "yttv_epg.app._touch_chrome_login", new=AsyncMock()
        ) as touch:
            result = await refresh_watch_ids()
        touch.assert_not_called()
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
async def test_light_refresh_adds_timed_lane_for_existing_watch_link(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import httpx

    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    from yttv_epg.innertube import InnerTubeClient
    from yttv_epg.parse import GAME_CARD_ZONE, Airing
    from yttv_epg.session_store import SavedSession

    now = datetime.now(timezone.utc).replace(microsecond=0)
    placeholder = now.astimezone(GAME_CARD_ZONE).replace(hour=12, minute=0, second=0)
    pending = Airing(
        "abcdefghijk", "Alabama at Georgia", "ESPN+", "event",
        placeholder, placeholder + timedelta(hours=3),
        "https://tv.youtube.com/watch/abcdefghijk?vp=original",
        entity_id="UCabcdefghijklmnopqrstuv", start_source="date", end_estimated=True,
    )
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([pending], [])
    monkeypatch.setattr(module.state, "catalog", catalog)
    monkeypatch.setattr(module.state, "lane_assignments", None)
    monkeypatch.setattr(module.state, "session", SavedSession(kind="cookies"))
    monkeypatch.setattr(module.state, "espn_listings", [])
    monkeypatch.setattr(module.settings, "enable_chrome", False)
    detail = {
        "title": {"simpleText": pending.title}, "stationName": pending.station,
        "startTime": int(now.timestamp()), "endTime": int((now + timedelta(hours=2)).timestamp()),
        "navigationEndpoint": {"watchEndpoint": {"videoId": pending.watch_id()}},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        inner = InnerTubeClient(http)
        browse = AsyncMock(return_value={"epgAiringRenderer": {
            **detail, "navigationEndpoint": {"watchEndpoint": {"videoId": "replay00001"}},
        }})
        monkeypatch.setattr(inner, "_browse", browse)
        monkeypatch.setattr(module.state, "innertube", inner)

        assert (await http.get("/whatson/1")).json()["deeplink_url"] is None
        assert not (await module.refresh_watch_ids())["changed"]
        assert catalog.events()[0].start_source == "date"

        browse.return_value = {"epgAiringRenderer": detail}
        assert (await module.refresh_watch_ids())["changed"]
        [resolved] = catalog.events()
        assert resolved.start == now and resolved.has_scheduled_start
        assert resolved.end == now + timedelta(hours=2) and not resolved.end_estimated
        assert (await http.get("/whatson/1")).json()["deeplink_url"] == pending.deeplink
        assert pending.title in (await http.get("/xmltv.xml")).text
        assert not (await module.refresh_watch_ids())["changed"]
        assert browse.await_count == 2


def test_upgrade_withholds_legacy_programmes_until_full_refresh(tmp_path, monkeypatch):
    import sqlite3
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from xml.etree import ElementTree as ET

    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    from yttv_epg.innertube import MineError, MineResult
    from yttv_epg.lanes import LaneAssignment
    from yttv_epg.parse import Airing
    from yttv_epg.session_store import SavedSession

    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    cached = Airing(
        "abcdefghijk", "Alabama at Georgia", "ESPN", "event", start,
        start + timedelta(hours=3), "https://tv.youtube.com/watch/abcdefghijk",
    )
    path = tmp_path / "catalog.sqlite"
    old = Catalog(path)
    old.replace([cached], [LaneAssignment(2, cached)])
    old._conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN start_source")
        conn.execute("ALTER TABLE events DROP COLUMN end_estimated")

    catalog = Catalog(path)
    monkeypatch.setattr(module.state, "catalog", catalog)
    monkeypatch.setattr(module.state, "lane_assignments", None)
    monkeypatch.setattr(module.state, "session", SavedSession(kind="cookies"))
    monkeypatch.setattr(module.state, "last_full_mine_at", None)
    monkeypatch.setattr(module.state, "espn_listings", [])
    monkeypatch.setattr(module.settings, "enable_chrome", False)
    monkeypatch.setattr(module.settings, "lane_count", 2)
    verified = replace(cached, start=start + timedelta(minutes=1))
    mine = AsyncMock(side_effect=[MineError("Guide temporarily unavailable"),
                                  MineResult([verified], "WEB_UNPLUGGED", "FEunplugged_epg", {})])
    monkeypatch.setattr(module, "_mine_with_chrome_recovery", mine)

    with TestClient(app) as client:
        assert "Time TBD" in client.get("/").text
        assert ET.fromstring(client.get("/xmltv.xml").text).find("programme") is None
        assert client.get("/whatson/2").json()["deeplink_url"] is None

        assert client.post("/api/refresh").status_code == 502
        assert ET.fromstring(client.get("/xmltv.xml").text).find("programme") is None

        assert client.post("/api/refresh").status_code == 200
        [programme] = ET.fromstring(client.get("/xmltv.xml").text).findall("programme")
        assert programme.get("channel") == "yttv-sports-2"
        assert programme.get("start") == verified.start.strftime("%Y%m%d%H%M%S +0000")
        assert client.get("/whatson/2").json()["deeplink_url"] == cached.deeplink


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
        with (
            patch.object(state.innertube, "mine", new=AsyncMock(return_value=mined)),
            patch("yttv_epg.app._touch_chrome_login", new=AsyncMock()) as touch,
        ):
            await refresh_catalog()
        touch.assert_awaited()
        titles = {item.title for item in state.catalog.events()}
        assert titles == {"UConn vs Maryland"}
        state.catalog.replace([], [])
        _set_lane_cache([])
        state.session = None
        state.last_full_mine_at = None


@pytest.mark.asyncio
async def test_chrome_keepalive_is_throttled_but_can_be_forced():
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _touch_chrome_login, state

    state.last_chrome_keepalive_at = datetime.now(timezone.utc)
    keepalive = AsyncMock(return_value={"ok": True, "reloaded": True})
    try:
        with (
            patch("yttv_epg.app.settings.enable_chrome", True),
            patch("yttv_epg.app.settings.chrome_keepalive_seconds", 14400),
            patch("yttv_epg.app.chrome_available", new=AsyncMock(return_value=True)),
            patch("yttv_epg.app.keepalive_youtube_tv", new=keepalive),
        ):
            assert await _touch_chrome_login() is False
            keepalive.assert_not_awaited()
            assert await _touch_chrome_login(force=True) is True
            keepalive.assert_awaited_once()
    finally:
        state.last_chrome_keepalive_at = None


@pytest.mark.asyncio
async def test_browser_mine_renews_session_once_after_auth_failure():
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _mine_with_chrome_recovery, state
    from yttv_epg.innertube import MineError, MineResult
    from yttv_epg.session_store import SavedSession

    session = SavedSession(
        kind="browser",
        cookies=[{"name": "SAPISID", "value": "x", "domain": ".youtube.com"}],
    )
    mined = MineResult(airings=[], client="WEB_UNPLUGGED", browse_id="FEunplugged_epg", raw={})
    mine = AsyncMock(
        side_effect=[
            MineError("YTTV session expired. Sign in again on tv.youtube.com."),
            mined,
        ]
    )
    state.session = session
    try:
        with (
            patch.object(state.innertube, "mine", new=mine),
            patch("yttv_epg.app._touch_chrome_login", new=AsyncMock(return_value=True)) as touch,
            patch("yttv_epg.app._sync_session_from_chrome", new=AsyncMock(return_value=True)),
        ):
            assert await _mine_with_chrome_recovery(session) is mined
        touch.assert_awaited_once_with(force=True)
        assert mine.await_count == 2
    finally:
        state.session = None


@pytest.mark.asyncio
async def test_refresh_failure_does_not_wipe_chrome_cookies():
    from yttv_epg.app import _mark_refresh_failure, state
    from yttv_epg.innertube import MineError, session_expired_message

    with TestClient(app) as client:
        with patch("yttv_epg.app.clear_browser_cookies", new=AsyncMock()) as wiped:
            await _mark_refresh_failure(MineError("YTTV session expired. Sign in again on tv.youtube.com."))
            wiped.assert_not_called()
        assert session_expired_message(state.catalog.meta().get("last_error"))
        client.post("/api/auth/logout")
        assert not state.catalog.meta().get("last_error")


@pytest.mark.asyncio
async def test_refresh_401_does_not_flag_expired_when_chrome_signed_in():
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _mark_refresh_failure, state
    from yttv_epg.innertube import MineError, session_expired_message

    with TestClient(app) as client:
        with (
            patch("yttv_epg.app.settings.enable_chrome", True),
            patch(
                "yttv_epg.app.chrome_status",
                new=AsyncMock(return_value={"available": True, "signed_in": True, "on_app": True}),
            ),
            patch("yttv_epg.app._sync_session_from_chrome", new=AsyncMock(return_value=True)),
        ):
            await _mark_refresh_failure(MineError("YTTV session expired. Sign in again on tv.youtube.com."))
        meta = state.catalog.meta()
        assert not session_expired_message(meta.get("last_error"))
        assert "still signed in" in str(meta.get("last_error") or "").lower()
        health = client.get("/health").json()
        assert health["session_expired"] is False
        client.post("/api/auth/logout")


def test_api_refresh_reports_still_signed_in_not_expired_when_chrome_live():
    from yttv_epg.app import state
    from yttv_epg.innertube import MineError
    from yttv_epg.session_store import SavedSession

    with TestClient(app) as client:
        state.session = SavedSession(
            kind="cookies",
            cookies=[{"name": "SAPISID", "value": "x", "domain": ".youtube.com"}],
        )
        state.store.save(state.session)
        try:
            with (
                patch("yttv_epg.app.settings.enable_chrome", True),
                patch("yttv_epg.app._sync_session_from_chrome", new=AsyncMock(return_value=True)),
                patch("yttv_epg.app._refresh_espn_listings", new=AsyncMock(return_value=False)),
                patch(
                    "yttv_epg.app.chrome_status",
                    new=AsyncMock(return_value={"available": True, "signed_in": True, "on_app": True}),
                ),
                patch.object(
                    state.innertube,
                    "mine",
                    new=AsyncMock(
                        side_effect=MineError("YTTV session expired. Sign in again on tv.youtube.com.")
                    ),
                ),
            ):
                response = client.post("/api/refresh")
            assert response.status_code == 502
            detail = response.json()["detail"]
            assert "still signed in" in detail.lower()
            assert "session expired" not in detail.lower()
            home = client.get("/")
            assert home.status_code == 200
            assert "YTTV session expired" not in home.text
            assert home.text.count("Guide refresh failed") == 1
            assert "still signed in" in home.text.lower()
        finally:
            client.post("/api/auth/logout")


@pytest.mark.asyncio
async def test_refresh_401_keeps_session_when_only_third_party_sapisid_remains():
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _mark_refresh_failure, state
    from yttv_epg.innertube import MineError, session_expired_message

    cookies = [{"name": "__Secure-3PAPISID", "value": "x", "domain": ".youtube.com"}]
    with TestClient(app) as client:
        with (
            patch("yttv_epg.app.settings.enable_chrome", True),
            patch(
                "yttv_epg.app.chrome_status",
                new=AsyncMock(
                    return_value={"available": True, "signed_in": True, "on_app": True}
                ),
            ),
            patch("yttv_epg.app.fetch_cookies", new=AsyncMock(return_value=cookies)),
            patch("yttv_epg.app._sync_session_from_chrome", new=AsyncMock(return_value=True)),
        ):
            await _mark_refresh_failure(MineError("YTTV session expired. Sign in again on tv.youtube.com."))
        meta = state.catalog.meta()
        assert not session_expired_message(meta.get("last_error"))
        assert "still signed in" in str(meta.get("last_error") or "").lower()
        client.post("/api/auth/logout")


@pytest.mark.asyncio
async def test_refresh_401_flags_expired_when_chrome_is_on_welcome():
    from unittest.mock import AsyncMock, patch

    from yttv_epg.app import _mark_refresh_failure, state
    from yttv_epg.innertube import MineError, session_expired_message

    with TestClient(app) as client:
        with (
            patch("yttv_epg.app.settings.enable_chrome", True),
            patch(
                "yttv_epg.app.chrome_status",
                new=AsyncMock(
                    return_value={
                        "available": True,
                        "signed_in": True,
                        "on_app": False,
                        "on_welcome": True,
                    }
                ),
            ),
            patch("yttv_epg.app._sync_session_from_chrome", new=AsyncMock(return_value=False)),
        ):
            await _mark_refresh_failure(MineError("YTTV session expired. Sign in again on tv.youtube.com."))
        assert session_expired_message(state.catalog.meta().get("last_error"))
        client.post("/api/auth/logout")


def test_feed_routes_use_startup_logo_overrides_and_subtitle_setting(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    from xml.etree import ElementTree as ET
    from yttv_epg import app as app_module
    from yttv_epg.config import Settings
    from yttv_epg.lanes import LaneAssignment
    from yttv_epg.parse import Airing

    monkeypatch.setenv("XMLTV_INCLUDE_SUBTITLE", "false")
    assert Settings(_env_file=None).xmltv_include_subtitle is False
    monkeypatch.setenv("XMLTV_INCLUDE_SUBTITLE", "true")
    assert Settings(_env_file=None).xmltv_include_subtitle is True
    now = datetime.now(timezone.utc)
    game = Airing("abcdefghijk", "Alabama at Kentucky", "ESPN", "event",
                  now - timedelta(minutes=10), now + timedelta(hours=2),
                  "https://tv.youtube.com/watch/abcdefghijk", sport="Football",
                  station_logo="https://example.com/automatic.png", broadcast_live=True, first_run=True)
    path = tmp_path / "logos.json"
    logo = "https://example.com/override.png?a=1&b=2"
    path.write_text(json.dumps({" Espn ": logo}))
    monkeypatch.setattr(app_module.settings, "station_logos_file", path)
    monkeypatch.setattr(app_module.settings, "xmltv_include_subtitle", False)
    monkeypatch.setattr(app_module, "_labeled_assignments", lambda: [LaneAssignment(1, game)])
    with TestClient(app) as client:
        xml = ET.fromstring(client.get("/xmltv.xml").text)
        assert xml.find("channel/icon").get("src") == logo
        assert xml.find("programme/sub-title") is None
        assert "ESPN" in xml.findtext("programme/desc")
        assert xml.find("programme/live") is not None
        assert f'tvg-logo="{logo}"' in client.get("/playlist.m3u").text
        # Overrides are a startup snapshot, not re-read on each feed request.
        path.write_text("{}")
        assert f'tvg-logo="{logo}"' in client.get("/playlist.m3u").text
        monkeypatch.setattr(app_module.settings, "xmltv_include_subtitle", True)
        assert ET.fromstring(client.get("/epg.xml").text).findtext("programme/sub-title") == "ESPN"


def test_hide_spanish_rebuilds_lanes_feeds_and_playback(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from yttv_epg import app as app_module
    from yttv_epg.catalog import Catalog
    from yttv_epg.parse import Airing

    catalog = Catalog(tmp_path / "filters.sqlite")
    monkeypatch.setattr(app_module.state, "catalog", catalog)
    monkeypatch.setattr(app_module.state, "lane_assignments", None)
    monkeypatch.setattr(app_module.state, "session", None)
    now = datetime.now(timezone.utc)
    def event(watch, title, language):
        return Airing(watch,title,"ESPN+","event",now-timedelta(minutes=10),now+timedelta(hours=2),
                      "https://tv.youtube.com/watch/"+watch,sport="Football",language=language)
    spanish=event("abcdefghijk","En Español: Alabama at Georgia","es")
    english=event("lmnopqrstuv","Alabama at Georgia","en")
    unknown=event("zyxwvutsrqp","Kentucky at Tennessee","")
    catalog.replace([spanish,english,unknown],[])
    with TestClient(app) as client:
        assert client.get('/api/filters').json()['hide_spanish'] is False
        assert 'Hide Spanish broadcasts' in client.get('/').text
        response=client.post('/api/filters',json={'hide_spanish':True})
        assert response.status_code == 200
        assert response.json()['events'] == 2
        assert response.json()['hide_spanish'] is True
        xml=client.get('/xmltv.xml').text
        assert spanish.deeplink not in xml
        assert english.deeplink in xml and unknown.deeplink in xml
        assert all(row.airing.language != 'es' for row in app_module._labeled_assignments())
        for row in app_module._labeled_assignments():
            assert client.get(f'/whatson/{row.lane}').json()['deeplink_url'] != spanish.deeplink
        home=client.get('/').text
        assert 'data-language="es"' in home
        assert catalog.hide_spanish()
        assert client.post('/api/filters',json={'hide_spanish':'false'}).status_code == 400
        assert client.post('/api/filters',json={'hide_spanish':False}).json()['events'] == 3
        assert spanish.deeplink in client.get('/xmltv.xml').text
    catalog._conn.close()


def test_all_bundled_network_logos_are_served_as_png():
    from yttv_epg.station_logos import BUNDLED_LOGOS

    with TestClient(app) as client:
        for name in set(BUNDLED_LOGOS.values()):
            response = client.get(f'/static/station-logos/{name}.png')
            assert response.status_code == 200
            assert response.headers['content-type'].startswith('image/png')
            assert response.content.startswith(b'\x89PNG\r\n\x1a\n')


def test_dashboard_status_and_filters_are_uncached_and_script_is_versioned():
    from yttv_epg.app import SCRIPT_VERSION
    with TestClient(app) as client:
        for path in ('/','/api/filters','/api/status'):
            response=client.get(path)
            assert response.headers['cache-control']=='no-store'
        assert isinstance(client.get('/api/status').json()['hide_spanish'],bool)
        assert f'/static/app.js?v={SCRIPT_VERSION}' in client.get('/').text


def test_corrupt_session_leaves_dashboard_available_with_recovery_warning(tmp_path,monkeypatch):
    from yttv_epg import app as module
    from yttv_epg.session_store import SessionStore
    store=SessionStore(tmp_path,'key');store.path.write_bytes(b'corrupt')
    assert store.load() is None
    monkeypatch.setattr(module.state,'store',store)
    monkeypatch.setattr(module.state,'session',None)
    with TestClient(app) as client:
        response=client.get('/')
        assert response.status_code==200
        assert 'original file is preserved' in response.text
        assert client.get('/api/status').json()['signed_in'] is False
        assert store.path.read_bytes()==b'corrupt'


def test_saved_spanish_preference_survives_catalog_refresh_and_dashboard_restart(tmp_path,monkeypatch):
    import re
    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    catalog=Catalog(tmp_path/'saved-filter.sqlite');catalog.set_hide_spanish(True)
    monkeypatch.setattr(module.state,'catalog',catalog)
    monkeypatch.setattr(module.state,'lane_assignments',None)
    for _ in range(2):
        with TestClient(app) as client:
            catalog.replace([],[])
            html=client.get('/').text
            assert re.search(r'id="hide-spanish"[^>]*checked',html)
            assert client.get('/api/status').json()['hide_spanish'] is True
    catalog._conn.close()


def test_independent_channel_filters_update_dashboard_and_feeds(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from xml.etree import ElementTree as ET
    from yttv_epg import app as app_module
    from yttv_epg.catalog import Catalog
    from yttv_epg.parse import Airing

    now = datetime.now(timezone.utc)
    catalog = Catalog(tmp_path / "independent.sqlite")
    events = [
        Airing("abcdefghij" + str(index), title, station, "event",
               now - timedelta(minutes=5), now + timedelta(hours=2),
               "https://tv.youtube.com/watch/abcdefghij" + str(index),
               sport="Football", channel=channel)
        for index, (title, station, channel) in enumerate([
            ("Michigan vs Ohio State", "FOX SPORTS 1", "Fox Sports"),
            ("UConn vs Maryland", "FS2", "Fox Sports"),
            ("Alabama vs Georgia", "ESPN2", "ESPN"),
            ("Western Michigan vs Central Michigan", "ESPN Unlimited", "ESPN"),
            ("Chivas vs America", "ViX Premium Deportes 1", "ViX Premium Deportes 1"),
            ("Pumas vs Tigres", "ViX Premium Deportes 2", "ViX Premium Deportes 2"),
        ])
    ]
    catalog.replace(events, [])
    monkeypatch.setattr(app_module.state, "catalog", catalog)
    with TestClient(app) as client:
        names = {item["name"] for item in client.get("/api/filters").json()["channels"]}
        assert names == {"FS1", "FS2", "ESPN2", "ESPN+", "ViX"}
        result = client.post("/api/filters", json={"toggle_channel": "FS1"})
        assert result.json()["hidden_channels"] == ["FS1"]
        home = client.get("/").text
        assert 'data-channel="FS2"' in home
        assert 'data-channel="ESPN2"' in home
        xml = ET.fromstring(client.get("/xmltv.xml").text)
        titles = [row.findtext("title") for row in xml.findall("programme")]
        assert "Michigan vs Ohio State" not in titles
        assert "UConn vs Maryland" in titles
        assert "Alabama vs Georgia" in titles
        playlist = client.get("/playlist.m3u").text
        assert "/static/station-logos/fs1.png" not in playlist
        assert "/static/station-logos/fs2.png" in playlist
        assert "/static/station-logos/espn-plus.png" in playlist
        client.post("/api/filters", json={"toggle_channel": "FS1"})
        assert catalog.hidden_channels() == []
        assert "Michigan vs Ohio State" in client.get("/xmltv.xml").text
        assert "ViX · 2" in client.get("/").text
        assert 'data-channel="ViX Premium Deportes 1"' not in client.get("/").text
        hidden_vix = client.post("/api/filters", json={"toggle_channel": "ViX"})
        assert hidden_vix.json()["hidden_channels"] == ["ViX"]
        guide = client.get("/xmltv.xml").text
        assert "Chivas vs America" not in guide
        assert "Pumas vs Tigres" not in guide
        assert "Michigan vs Ohio State" in guide
        client.post("/api/filters", json={"toggle_channel": "ViX"})
        assert "Chivas vs America" in client.get("/xmltv.xml").text


@pytest.mark.parametrize(("field", "first", "second"), [
    ("hidden", "Football", "Basketball"),
    ("hidden_channels", "ESPN2", "FS1"),
])
def test_filter_revision_changes_when_event_counts_stay_the_same(tmp_path, monkeypatch, field, first, second):
    from datetime import datetime, timedelta, timezone
    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    from yttv_epg.parse import Airing

    now = datetime.now(timezone.utc)
    events = [
        Airing("football001", "Michigan at Ohio State", "ESPN2", "event", now,
               now + timedelta(hours=2), "https://tv.youtube.com/watch/football001", sport="Football"),
        Airing("basketball1", "Detroit Pistons at Boston Celtics", "FS1", "event", now,
               now + timedelta(hours=2), "https://tv.youtube.com/watch/basketball1", sport="Basketball"),
    ]
    catalog = Catalog(tmp_path / "filters.sqlite")
    catalog.replace(events, [])
    monkeypatch.setattr(module.state, "catalog", catalog)
    monkeypatch.setattr(module.state, "lane_assignments", None)
    with TestClient(app) as client:
        first_save = client.post("/api/filters", json={field: [first]}).json()
        before = client.get("/api/status").json()
        assert before["filter_revision"] == first_save["filter_revision"]
        assert f'data-filter-revision="{before["filter_revision"]}"' in client.get("/").text

        second_save = client.post("/api/filters", json={field: [second]}).json()
        after = client.get("/api/status").json()
        assert before["events"] == after["events"] == 1
        assert before["all_events"] == after["all_events"] == 2
        assert before["last_refresh"] == after["last_refresh"]
        assert after["filter_revision"] == second_save["filter_revision"] != before["filter_revision"]


def test_dashboard_and_xmltv_share_gracenote_and_live_preference(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    from yttv_epg.parse import Airing

    now = datetime.now(timezone.utc).replace(microsecond=0)
    game = Airing("abcdefghijk", "Boston at Detroit", "ESPN", "event",
                  now - timedelta(minutes=5), now + timedelta(hours=2),
                  "https://tv.youtube.com/watch/abcdefghijk", sport="Basketball")
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([game], [])
    path = tmp_path / "grid.json"
    path.write_text(json.dumps({"channels": [{"callSign": game.station, "events": [{
        "startTime": game.start.isoformat(), "endTime": game.end.isoformat(),
        "program": {"title": game.title}, "flag": ["Live"],
    }]}]}))
    monkeypatch.setattr(module.state, "catalog", catalog)
    monkeypatch.setattr(module.state, "lane_assignments", None)
    monkeypatch.setattr(module.settings, "gracenote_grid_file", path)
    with TestClient(app) as client:
        client.post("/api/filters", json={"xmltv_live_on_air": False}).raise_for_status()
        assert '>LIVE</span>' in client.get("/").text
        assert "<live/>" in client.get("/xmltv.xml").text

        path.unlink()
        dashboard = client.get("/").text
        assert '>LIVE</span>' not in dashboard
        assert '>On now</span>' in dashboard
        assert "<live/>" not in client.get("/xmltv.xml").text

        client.post("/api/filters", json={"xmltv_live_on_air": True}).raise_for_status()
        assert '>LIVE</span>' in client.get("/").text
        assert "<live/>" in client.get("/xmltv.xml").text


def test_date_only_game_shows_tbd_without_claiming_a_lane(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    from yttv_epg.parse import merge_airings, parse_browse

    now = datetime.now(timezone.utc)
    card = {
        "primaryText": {"simpleText": "Today • ESPN+"},
        "secondaryText": {"simpleText": "NCAA Football"},
        "startTeamPrimaryText": {"simpleText": "Alabama"},
        "endTeamPrimaryText": {"simpleText": "Georgia"},
        "navigationEndpoint": {"watchEndpoint": {"videoId": "abcdefghijk"}},
    }
    pending = parse_browse({"unpluggedGameCardRenderer": card}, now=now)[0]
    assert pending.start_source == "date" and pending.end_estimated
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([pending], [])
    monkeypatch.setattr(module.state, "catalog", catalog)
    monkeypatch.setattr(module.state, "lane_assignments", None)
    monkeypatch.setattr(module.state, "espn_listings", [])
    with TestClient(app) as client:
        client.post("/api/filters", json={"xmltv_live_on_air": True}).raise_for_status()
        dashboard = client.get("/").text
        assert "Alabama at Georgia" in dashboard
        assert "Time TBD" in dashboard
        assert "<programme " not in client.get("/xmltv.xml").text
        assert not client.get("/whatson/1").json()["ok"]
        assert client.get("/events").json()["events"][0]["start_source"] == "date"

        card["startTimeSeconds"] = int(now.timestamp())
        card["endTimeSeconds"] = int((now + timedelta(hours=2)).timestamp())
        scheduled = parse_browse({"unpluggedGameCardRenderer": card}, now=now)[0]
        assert scheduled.start_source == "guide" and not scheduled.end_estimated
        # The guide slot wins over a date-only listing of the same stream.
        assert merge_airings([pending, scheduled]) == [scheduled]
        catalog.replace_resolved([(pending, scheduled)])
        client.post("/api/filters", json={"hide_spanish": False}).raise_for_status()
        assert "Time TBD" not in client.get("/").text
        assert "Alabama at Georgia" in client.get("/xmltv.xml").text
        assert client.get("/whatson/1").json()["deeplink_url"] == scheduled.deeplink


def test_live_on_air_preference_routes_and_validation(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from yttv_epg import app as module
    from yttv_epg.lanes import LaneAssignment
    from yttv_epg.parse import Airing

    now = datetime.now(timezone.utc)
    game = Airing('abcdefghijk', 'A at B', 'ACC Network', 'event',
                  now - timedelta(minutes=10), now + timedelta(hours=1),
                  'https://tv.youtube.com/watch/abcdefghijk')
    monkeypatch.setattr(module, '_labeled_assignments', lambda: [LaneAssignment(1, game)])
    with TestClient(app) as client:
        module.state.catalog.set_xmltv_live_on_air(False)
        try:
            assert client.get('/api/filters').json()['xmltv_live_on_air'] is False
            assert '<live/>' not in client.get('/xmltv.xml').text
            saved = client.post('/api/filters', json={'xmltv_live_on_air': True})
            assert saved.json()['xmltv_live_on_air'] is True
            assert client.get('/api/status').json()['xmltv_live_on_air'] is True
            assert 'id="xmltv-live-on-air"' in client.get('/').text
            for route in ('/xmltv.xml', '/epg.xml'):
                body = client.get(route).text
                assert '<live/>' in body and '<new/>' not in body
            client.post('/api/filters', json={})
            assert client.get('/api/filters').json()['xmltv_live_on_air'] is True
            old_language = module.state.catalog.hide_spanish()
            for invalid in ('false', 1, None, []):
                response = client.post('/api/filters', json={
                    'hide_spanish': not old_language, 'xmltv_live_on_air': invalid})
                assert response.status_code == 400
                assert module.state.catalog.hide_spanish() is old_language
                assert module.state.catalog.xmltv_live_on_air() is True
            client.post('/api/filters', json={'xmltv_live_on_air': False})
            assert '<live/>' not in client.get('/xmltv.xml').text
        finally:
            module.state.catalog.set_xmltv_live_on_air(False)


def test_broadcast_evidence_endpoint_is_diagnostic_protected_and_not_cached(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from yttv_epg import app as module
    from yttv_epg.detail_evidence import EvidenceStore
    from yttv_epg.parse import Airing

    capture = json.loads((Path(__file__).parent / 'fixtures/acc_replay_detail.json').read_text())
    game = Airing('VasWEa--oME', 'Virginia Tech at Clemson', 'ACC Network', 'event',
                  datetime(2026, 10, 28, 11, tzinfo=timezone.utc),
                  datetime(2026, 10, 28, 14, tzinfo=timezone.utc), '')
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    store.save(game, datetime.now(timezone.utc), capture=capture)
    monkeypatch.setattr(module.state, 'evidence', store)
    monkeypatch.setattr(module.settings, 'admin_user', 'admin')
    monkeypatch.setattr(module.settings, 'admin_password', 'password')
    with TestClient(app) as client:
        assert client.get('/api/broadcast-evidence').status_code == 401
        auth = ('admin', 'password')
        response = client.get('/api/broadcast-evidence', auth=auth)
        assert response.headers['cache-control'] == 'no-store'
        body = response.json()
        assert body['automatic_exclusions'] is False and body['mode'] == 'observe_only'
        assert body['records'][0]['evidence']['date_gap_days'] == 4
        assert 'capture' not in body['records'][0]
        history = client.get('/api/broadcast-evidence?history=true&include_capture=true', auth=auth).json()
        assert history['records'][0]['capture'] == capture
        assert client.get('/api/broadcast-evidence?limit=101', auth=auth).status_code == 422
        assert client.get('/api/broadcast-evidence?offset=1', auth=auth).json()['records'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,busy,signed_in,collects', [
    (True, False, True, True), (False, False, True, False),
    (True, True, True, False), (True, False, False, False),
])
async def test_evidence_worker_gates_and_cancels(monkeypatch, enabled, busy, signed_in, collects):
    import asyncio
    from yttv_epg import app as module
    from yttv_epg.session_store import SavedSession

    # Drive one background iteration without a real delay or network request.
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    collect = AsyncMock(return_value=0)
    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    monkeypatch.setattr(module, 'collect_evidence', collect)
    monkeypatch.setattr(module.settings, 'detail_evidence', enabled)
    monkeypatch.setattr(module.state, 'refreshing', busy)
    monkeypatch.setattr(module.state, 'refresh_lock', asyncio.Lock())
    monkeypatch.setattr(module.state, 'session', SavedSession(kind='browser') if signed_in else None)
    with pytest.raises(asyncio.CancelledError):
        await module.evidence_loop()
    assert collect.await_count == int(collects)
    assert not module.state.refresh_lock.locked()


@pytest.mark.asyncio
async def test_evidence_failure_does_not_fail_guide_or_kill_worker(monkeypatch):
    import asyncio
    from yttv_epg import app as module
    from yttv_epg.session_store import SavedSession

    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock(side_effect=[None, None, asyncio.CancelledError()]))
    collect = AsyncMock(side_effect=[RuntimeError('sensitive'), 0])
    monkeypatch.setattr(module, 'collect_evidence', collect)
    monkeypatch.setattr(module.settings, 'detail_evidence', True)
    monkeypatch.setattr(module.state, 'refreshing', False)
    monkeypatch.setattr(module.state, 'refresh_lock', asyncio.Lock())
    monkeypatch.setattr(module.state, 'session', SavedSession(kind='browser'))
    with pytest.raises(asyncio.CancelledError):
        await module.evidence_loop()
    assert collect.await_count == 2
    assert module.state.evidence_error is None
    assert not module.state.refresh_lock.locked()
