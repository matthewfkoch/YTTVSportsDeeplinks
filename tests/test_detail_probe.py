import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from yttv_epg.detail_probe import capture_details, detail_id_from_watch, summarize_details
from yttv_epg.parse import parse_browse


def test_capture_excludes_credentials_tracking_and_recommendation_ids():
    payload = {
        "responseContext": {"visitorData": "SECRET"},
        "recommendations": {"browseEndpoint": {"browseId": "wrong"}},
        "videoMetadata": {"unpluggedVideoMetadataRenderer": {
            "title": {"runs": [{"text": "Game", "trackingParams": "SECRET"}]},
            "trackingParams": "SECRET",
            "navigationEndpoint": {"clickTrackingParams": "SECRET",
                                   "browseEndpoint": {"browseId": "right", "params": "SECRET"}},
            "stationNavigationEndpoint": {"browseEndpoint": {"browseId": "station"}},
        }},
    }
    assert detail_id_from_watch(payload) == "right"
    summary = json.dumps(summarize_details(payload))
    assert "SECRET" not in summary and "wrong" not in summary and "station" not in summary


def test_ambiguous_or_missing_watch_detail_id_is_rejected():
    with pytest.raises(ValueError):
        detail_id_from_watch({"browseEndpoint": {"browseId": "recommendation"}})
    with pytest.raises(ValueError):
        detail_id_from_watch({"items": [
            {"unpluggedVideoMetadataRenderer": {"navigationEndpoint": {"browseEndpoint": {"browseId": bid}}}}
            for bid in ("one", "two")
        ]})


@pytest.mark.asyncio
async def test_watch_capture_fetches_exact_detail_without_playback():
    client = AsyncMock()
    client._browse.side_effect = [
        {"unpluggedVideoMetadataRenderer": {"navigationEndpoint": {"browseEndpoint": {"browseId": "game"}}}},
        {"header": {"unpluggedContentDetailsHeaderRenderer": {"contentType": "SPORTS_EVENT"}}},
    ]
    result = await capture_details(client, object(), video_id="abcdefghijk")
    assert result["browse_id"] == "game"
    calls = client._browse.call_args_list
    assert len(calls) == 2
    assert calls[0].args[1]["path"] == "/youtubei/v1/next"
    assert calls[1].kwargs["body"] == {"browseId": "game"}


def test_real_acc_replay_live_badge_is_not_confirmed_live():
    fixture = json.loads((Path(__file__).parent / "fixtures/acc_replay_detail.json").read_text())
    header = next(r["fields"] for r in fixture["details"]
                  if r["renderer"] == "unpluggedContentDetailsHeaderRenderer")
    assert header["contentType"] == "SPORTS_EVENT"
    assert header["secondaryText"]["runs"][0]["text"] == "Oct 24, 2026"
    card = next(r["fields"] for r in fixture["details"]
                if r["renderer"] == "unpluggedCompactVideoRenderer")
    assert card["badge"]["unpluggedTextBadgeRenderer"]["type"] == "LIVE"
    airings = parse_browse({"unpluggedCompactVideoRenderer": card},
                           now=datetime.fromisoformat(fixture["captured_at"]))
    assert airings
    assert all(airing.broadcast_live is None for airing in airings)
