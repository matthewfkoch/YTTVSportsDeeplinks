from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from yttv_epg.innertube import CLIENTS, InnerTubeClient, MineError, session_expired_message
from yttv_epg.parse import Airing
from yttv_epg.session_store import SavedSession

SESSION = SavedSession(
    kind="cookies",
    cookies=[
        {"name": "SAPISID", "value": "sapi", "domain": ".youtube.com"},
        {"name": "SID", "value": "sid", "domain": ".youtube.com"},
    ],
)

HUBS = [f"UC{'a' * 20}{i:02d}" for i in range(4)]
CONT = "abcdefghijklmnopqrstuvwx"


def _station(browse_id: str, label: str = "ESPN") -> dict:
    return {
        "epgStationRenderer": {
            "icon": {"accessibility": {"accessibilityData": {"label": label}}},
            "endpoint": {"browseEndpoint": {"browseId": browse_id}},
        }
    }


def _card(video_id: str, title: str, station: str = "ESPN") -> dict:
    return {
        "unpluggedVideoRenderer": {
            "videoId": video_id,
            "title": {"simpleText": title},
            "stationName": station,
            "startTime": 1788700000,
            "endTime": 1788707200,
        }
    }


@pytest.fixture
def patched_pages(monkeypatch):
    from yttv_epg.config import settings

    monkeypatch.setattr(settings, "epg_pages", 2)
    monkeypatch.setattr(settings, "hub_pages", 0)
    monkeypatch.setattr(settings, "max_hubs", 4)
    monkeypatch.setattr(settings, "mine_concurrency", 4)


def _client_for(handler) -> InnerTubeClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return InnerTubeClient(http)


@pytest.mark.asyncio
async def test_browse_all_pages_are_serial(patched_pages):
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("browseId") == "FEunplugged_epg":
            order.append("epg")
            return httpx.Response(
                200,
                json={
                    "continuation": CONT,
                    "contents": [_card("abcdefghijk", "Alabama vs Auburn")],
                    "responseContext": {"visitorData": "visitor-epg"},
                    "contentsStations": [_station(hub) for hub in HUBS],
                },
            )
        if body.get("continuation") == CONT:
            assert order == ["epg"]
            order.append("page2")
            return httpx.Response(200, json={"contents": [_card("lmnopqrstuv", "Duke vs Clemson")]})
        browse_id = body.get("browseId") or ""
        order.append(browse_id)
        return httpx.Response(200, json={"contents": [_card("wxyzaaaaaaa", "Live extra")]})

    innertube = _client_for(handler)
    result = await innertube.mine(SESSION)
    assert order[0] == "epg"
    assert order[1] == "page2"
    assert {item.video_id for item in result.airings} >= {"abcdefghijk", "lmnopqrstuv"}


@pytest.mark.asyncio
async def test_hubs_are_requested_after_epg(patched_pages):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        browse_id = str(body.get("browseId") or "")
        if browse_id:
            seen.append(browse_id)
        if browse_id == "FEunplugged_epg":
            return httpx.Response(
                200,
                json={
                    "contents": [_card("abcdefghijk", "Alabama vs Auburn")]
                    + [_station(hub) for hub in HUBS],
                    "responseContext": {"visitorData": "visitor-epg"},
                },
            )
        return httpx.Response(200, json={"contents": [_card("bbbbbbbbbbb", "Game on hub")]})

    innertube = _client_for(handler)
    await innertube.mine(SESSION)
    assert seen[0] == "FEunplugged_epg"
    for hub in HUBS:
        assert hub in seen
    assert innertube.visitor_data == "visitor-epg"


@pytest.mark.asyncio
async def test_frozen_visitor_ignores_later_hub_visitor(patched_pages):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        browse_id = str(body.get("browseId") or "")
        if browse_id == "FEunplugged_epg":
            return httpx.Response(
                200,
                json={
                    "contents": [_card("abcdefghijk", "Alabama vs Auburn"), _station(HUBS[0])],
                    "responseContext": {"visitorData": "visitor-epg"},
                },
            )
        return httpx.Response(
            200,
            json={
                "contents": [_card("bbbbbbbbbbb", "Hub game")],
                "responseContext": {"visitorData": "visitor-hub"},
            },
        )

    innertube = _client_for(handler)
    await innertube.mine(SESSION)
    assert innertube.visitor_data == "visitor-epg"


@pytest.mark.asyncio
async def test_hub_401_aborts_client_and_tries_fallback(patched_pages, monkeypatch):
    monkeypatch.setattr("yttv_epg.innertube.CLIENTS", (CLIENTS[0],))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        browse_id = str(body.get("browseId") or "")
        seen.append(browse_id)
        if browse_id == "FEunplugged_epg":
            return httpx.Response(
                200,
                json={"contents": [_card("abcdefghijk", "Alabama vs Auburn"), _station(HUBS[0])]},
            )
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    innertube = _client_for(handler)
    with pytest.raises(MineError, match="session expired"):
        await innertube.mine(SESSION)
    assert "FEunplugged_epg" in seen
    assert HUBS[0] in seen


def test_session_expired_message_detects_innertube_401():
    assert session_expired_message("YTTV session expired. Sign in again on tv.youtube.com.")
    assert session_expired_message("HTTP 401")
    assert not session_expired_message("ESPN schedule timed out")
    assert not session_expired_message("")


@pytest.mark.asyncio
async def test_resolve_soon_runs_pending_entity_browses(patched_pages):
    now = datetime.now(timezone.utc)
    pending = Airing(
        video_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
        title="East Carolina at Alabama",
        station="ESPN+",
        kind="event",
        start=now,
        end=now + timedelta(hours=3),
        deeplink="",
        entity_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
    )
    linked = Airing(
        video_id="abcdefghijk",
        title="UConn vs Maryland",
        station="ESPN",
        kind="event",
        start=now,
        end=now + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/abcdefghijk",
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        browse_id = str(body.get("browseId") or "")
        seen.append(browse_id)
        return httpx.Response(200, json={"contents": [_card("resolvedxx1", pending.title, "ESPN+")]})

    innertube = _client_for(handler)
    out = await innertube.resolve_soon(SESSION, dict(CLIENTS[0]), [pending, linked])
    assert seen == ["UCYcBS3Z_sOJFVZmq8E5DotQ"]
    by_title = {item.title: item for item in out}
    assert by_title["East Carolina at Alabama"].watch_id() == "resolvedxx1"
    assert by_title["UConn vs Maryland"].watch_id() == "abcdefghijk"
