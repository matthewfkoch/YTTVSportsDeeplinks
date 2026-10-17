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



def test_station_logo_migrates_and_round_trips(tmp_path):
    import sqlite3
    from dataclasses import replace

    path = tmp_path / "catalog.sqlite"
    original = Catalog(path)
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    game = _airing("Alabama at Kentucky", now)
    original.replace([game], pack_lanes([game], 1))
    original._conn.close()
    # Reproduce a pre-v0.2.5 schema while retaining its event and lane data.
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN station_logo")
    catalog = Catalog(path)
    assert catalog.events()[0].station_logo == ""
    assert catalog.assignments()[0].airing.station_logo == ""
    logo = "https://example.com/espn.png"
    with_logo = replace(game, station_logo=logo)
    catalog.replace([with_logo, game], pack_lanes([with_logo], 1))
    assert catalog.events()[0].station_logo == logo
    assert catalog.assignments()[0].airing.station_logo == logo
    resolved = replace(with_logo, video_id="abcdefghijk")
    catalog.replace_resolved([(with_logo, resolved)])
    assert catalog.events()[0].station_logo == logo
    catalog._conn.close()
    reopened = Catalog(path)
    assert reopened.events()[0].station_logo == logo
    reopened._conn.close()


def test_station_cache_survives_event_replacement_and_restart(tmp_path):
    from dataclasses import replace

    path = tmp_path / "catalog.sqlite"
    catalog = Catalog(path)
    game = replace(_airing("Alabama at Georgia", datetime(2026,10,20,tzinfo=timezone.utc)),
                   station="ESPN", station_logo="https://example.com/espn.png", language="es")
    catalog.replace([game], pack_lanes([game], 1))
    assert catalog.events()[0].language == "es"
    catalog.replace([], [])
    catalog._conn.close()
    catalog = Catalog(path)
    assert catalog.station_logos() == {"espn": game.station_logo}
    assert "espn2" not in catalog.station_logos()
    catalog.ensure_hide_spanish(True)
    assert catalog.hide_spanish()
    catalog.set_hide_spanish(False)
    catalog.ensure_hide_spanish(True)
    catalog._conn.close()
    reopened = Catalog(path)
    assert not reopened.hide_spanish()
    reopened._conn.close()


def test_language_column_migration_preserves_old_data(tmp_path):
    import sqlite3

    path = tmp_path / "catalog.sqlite"
    old = Catalog(path)
    old.replace([_airing("Alabama at Georgia", datetime(2026,10,20,tzinfo=timezone.utc))], [])
    old._conn.close()
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE events DROP COLUMN language")
        conn.execute("DROP TABLE station_logos")
    migrated = Catalog(path)
    assert migrated.events()[0].language == ""
    assert not migrated.hide_spanish()
    migrated._conn.close()


def test_broadcast_status_roundtrip_and_migration_defaults_unknown(tmp_path):
    from dataclasses import replace
    import sqlite3
    path=tmp_path/'broadcasts.sqlite';catalog=Catalog(path)
    item=replace(_airing('Alabama at Georgia',datetime(2026,10,20,tzinfo=timezone.utc)),
                 broadcast_live=True,first_run=False,is_repeat=False)
    catalog.replace([item],pack_lanes([item],1))
    loaded=catalog.assignments()[0].airing
    assert (loaded.broadcast_live,loaded.first_run,loaded.is_repeat)==(True,False,False)
    catalog._conn.close()
    with sqlite3.connect(path) as conn:
        for name in ('broadcast_live','first_run','is_repeat'):conn.execute(f'ALTER TABLE events DROP COLUMN {name}')
    migrated=Catalog(path);loaded=migrated.events()[0]
    assert loaded.broadcast_live is None and loaded.first_run is None and loaded.is_repeat is None
    migrated._conn.close()
