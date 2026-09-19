from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from yttv_epg.catalog import Catalog
from yttv_epg.lanes import pack_lanes
from yttv_epg.parse import Airing


def _airing(title: str, start: datetime) -> Airing:
    return Airing(
        video_id="YGUvoKVT5qk",
        title=title,
        station="ESPN Unlimited",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
    )


def test_replace_dedupes_same_video_and_start(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    airings = [_airing("Game", start), _airing("UConn vs Maryland", start)]
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace(airings, pack_lanes(airings, 2), client="WEB_UNPLUGGED", browse_id="FEunplugged_epg")
    rows = catalog.events()
    assert len(rows) == 1
    assert rows[0].title == "UConn vs Maryland"


def test_replace_same_watch_id_different_entities(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    first = _airing("NEC Nijmegen vs. Feyenoord", start)
    first.entity_id = "UCYcBS3Z_sOJFVZmq8E5DotQ"
    second = _airing("En Español-N.E.C. vs. Feyenoord", start)
    second.entity_id = "UCAnotherEntityPage0000001"
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([first, second], pack_lanes([first, second], 2), client="WEB_UNPLUGGED", browse_id="hub")
    rows = catalog.events()
    assert len(rows) == 1
    assert rows[0].video_id == "YGUvoKVT5qk"


def test_ensure_hidden_sports_only_once(tmp_path: Path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.ensure_hidden_sports(["Volleyball"])
    assert catalog.hidden_sports() == ["Volleyball"]
    catalog.ensure_hidden_sports(["Soccer"])
    assert catalog.hidden_sports() == ["Volleyball"]
    catalog.set_hidden_sports([])
    assert catalog.hidden_sports() == []


def test_ensure_hidden_channels_only_once(tmp_path: Path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.ensure_hidden_channels(["ESPN+"])
    assert catalog.hidden_channels() == ["ESPN+"]
    catalog.ensure_hidden_channels(["NBC Sports Extra"])
    assert catalog.hidden_channels() == ["ESPN+"]
    catalog.set_hidden_channels([])
    assert catalog.hidden_channels() == []


def test_replace_persists_channel_family(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([_airing("UConn vs Maryland", start)], pack_lanes([_airing("UConn vs Maryland", start)], 2))
    assert catalog.events()[0].channel == "ESPN+"


def test_replace_persists_artwork(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    game = _airing("UConn vs Maryland", start)
    game.artwork = "https://yt3.ggpht.com/UConnMarylandArt=w960-h540-p-ns-nd"
    game.artwork_secondary = "https://yt3.ggpht.com/UnusedSecondary=w540-h540-p-ns-nd"
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([game], pack_lanes([game], 2))
    stored = catalog.events()[0]
    assert stored.artwork == game.artwork
    assert stored.artwork_secondary == game.artwork_secondary


def test_stored_volleyball_survives_school_name_football_guess(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    game = Airing(
        video_id="YGUvoKVT5qk",
        title="Elon vs. Eastern Michigan",
        station="ESPN",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
        sport="Volleyball",
    )
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([game], pack_lanes([game], 2))
    assert catalog.events()[0].sport == "Volleyball"


def test_update_sports_persists_espn_label(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    game = Airing(
        video_id="YGUvoKVT5qk",
        title="Liberty vs. James Madison",
        station="ESPN+",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
        sport="Football",
    )
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([game], pack_lanes([game], 2))
    labeled = Airing(
        video_id=game.video_id,
        title=game.title,
        station=game.station,
        kind=game.kind,
        start=game.start,
        end=game.end,
        deeplink=game.deeplink,
        sport="Field Hockey",
    )
    catalog.update_sports([labeled])
    assert catalog.events()[0].sport == "Field Hockey"


def test_replace_lanes_updates_counts(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    game = _airing("UConn vs Maryland", start)
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([game], pack_lanes([game], 2), visible_count=1, watchable_count=1)
    extra = Airing(
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
    catalog.replace_lanes(pack_lanes([game, extra], 2), visible_count=2, watchable_count=2)
    meta = catalog.meta()
    assert meta["visible_count"] == "2"
    assert meta["watchable_count"] == "2"
    assert meta["lanes_used"] == "2"
    assert meta["dropped_events"] == "0"


def test_replace_resolved_swaps_entity_pk(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    pending = Airing(
        video_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
        title="East Carolina at Alabama",
        station="ESPN+",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="",
        entity_id="UCYcBS3Z_sOJFVZmq8E5DotQ",
    )
    resolved = Airing(
        video_id="abcdefghijk",
        title=pending.title,
        station=pending.station,
        kind="event",
        start=start,
        end=pending.end,
        deeplink="https://tv.youtube.com/watch/abcdefghijk",
        entity_id=pending.entity_id,
        sport="Football",
        channel="ESPN+",
    )
    catalog = Catalog(tmp_path / "catalog.sqlite")
    catalog.replace([pending], [])
    catalog.replace_resolved([(pending, resolved)])
    rows = catalog.events()
    assert len(rows) == 1
    assert rows[0].video_id == "abcdefghijk"
    assert rows[0].watch_id() == "abcdefghijk"
    assert rows[0].entity_id == "UCYcBS3Z_sOJFVZmq8E5DotQ"


def test_assignments_round_trip_after_replace(tmp_path: Path):
    start = datetime(2026, 9, 5, 16, 0, 0, 250000, tzinfo=timezone.utc)
    game = _airing("UConn vs Maryland", start)
    extra = Airing(
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
    catalog = Catalog(tmp_path / "catalog.sqlite")
    packed = pack_lanes([game, extra], 4)
    catalog.replace([game, extra], packed)
    stored = {(row.lane, row.airing.video_id) for row in catalog.assignments()}
    assert stored == {(row.lane, row.airing.video_id) for row in packed}

