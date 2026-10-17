from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yttv_epg.branding import for_ui
from yttv_epg.languages import broadcast_language
from yttv_epg.station_logos import station_key
from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import Airing, keep_artwork
from yttv_epg.sports import (CHANNEL_RULES, channel_filter, channel_identity, event_channel, clean_station,
                             infer_channel, is_matchup, resolve_sport)


def _better_row(candidate: Airing, current: Airing) -> bool:
    if bool(candidate.watch_id()) != bool(current.watch_id()):
        return bool(candidate.watch_id())
    cand_game = candidate.kind == "event" or is_matchup(candidate.title)
    cur_game = current.kind == "event" or is_matchup(current.title)
    if cand_game != cur_game:
        return cand_game
    if len(candidate.title) != len(current.title):
        return len(candidate.title) > len(current.title)
    if bool(candidate.station) != bool(current.station):
        return bool(candidate.station)
    if bool(candidate.artwork) != bool(current.artwork):
        return bool(candidate.artwork)
    if bool(candidate.artwork_secondary) != bool(current.artwork_secondary):
        return bool(candidate.artwork_secondary)
    return len(candidate.station) > len(current.station)


class Catalog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                station TEXT NOT NULL,
                kind TEXT NOT NULL,
                start_ts REAL NOT NULL,
                end_ts REAL NOT NULL,
                deeplink TEXT NOT NULL,
                live INTEGER NOT NULL,
                source TEXT NOT NULL,
                sport TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (video_id, start_ts)
            );
            CREATE TABLE IF NOT EXISTS lanes (
                lane INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                start_ts REAL NOT NULL,
                end_ts REAL NOT NULL
            );
            """
        )
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(events)")}
        if "sport" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN sport TEXT NOT NULL DEFAULT ''")
        if "entity_id" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN entity_id TEXT NOT NULL DEFAULT ''")
        if "channel" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN channel TEXT NOT NULL DEFAULT ''")
        if "artwork" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN artwork TEXT NOT NULL DEFAULT ''")
        if "artwork_secondary" not in cols:
            self._conn.execute(
                "ALTER TABLE events ADD COLUMN artwork_secondary TEXT NOT NULL DEFAULT ''"
            )
        if "station_logo" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN station_logo TEXT NOT NULL DEFAULT ''")
        if "language" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN language TEXT NOT NULL DEFAULT ''")
        for column in ("broadcast_live", "first_run", "is_repeat"):
            if column not in cols:
                self._conn.execute(f"ALTER TABLE events ADD COLUMN {column} INTEGER")
        self._conn.execute("CREATE TABLE IF NOT EXISTS station_logos (station TEXT PRIMARY KEY, url TEXT NOT NULL)")
        self._remember_station_logos(self._conn, self.events())
        self._conn.commit()

    def _remember_station_logos(self, cur, events: list[Airing]) -> None:
        cur.executemany(
            "INSERT INTO station_logos(station, url) VALUES (?, ?) ON CONFLICT(station) DO UPDATE SET url=excluded.url",
            [(station_key(item.station), item.station_logo) for item in events if station_key(item.station) and item.station_logo
             and channel_identity(item.station) == event_channel(item)],
        )

    def station_logos(self) -> dict[str, str]:
        with self._lock:
            return dict(self._conn.execute("SELECT station, url FROM station_logos").fetchall())

    def hide_spanish(self) -> bool:
        return self.meta().get("hide_spanish", "false") == "true"

    def set_hide_spanish(self, hidden: bool) -> None:
        with self._lock:
            self._set_meta("hide_spanish", "true" if hidden else "false")
            self._conn.commit()

    def ensure_hide_spanish(self, default: bool) -> None:
        if "hide_spanish" not in self.meta():
            self.set_hide_spanish(default)

    def replace(
        self,
        airings: list[Airing],
        assignments: list[LaneAssignment],
        *,
        error: str = "",
        client: str = "",
        browse_id: str = "",
        linear_ignored: int = 0,
        dropped: int = 0,
        visible_count: Optional[int] = None,
        watchable_count: Optional[int] = None,
    ) -> None:
        with self._lock:
            self._replace(
                airings,
                assignments,
                error=error,
                client=client,
                browse_id=browse_id,
                linear_ignored=linear_ignored,
                dropped=dropped,
                visible_count=visible_count,
                watchable_count=watchable_count,
            )

    def _replace(
        self,
        airings: list[Airing],
        assignments: list[LaneAssignment],
        *,
        error: str = "",
        client: str = "",
        browse_id: str = "",
        linear_ignored: int = 0,
        dropped: int = 0,
        visible_count: Optional[int] = None,
        watchable_count: Optional[int] = None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM events")
        cur.execute("DELETE FROM lanes")
        unique: dict[tuple[str, int], Airing] = {}
        for item in airings:
            key = (item.video_id, int(item.start.timestamp()))
            prev = unique.get(key)
            if prev is None:
                unique[key] = item
            elif _better_row(item, prev):
                unique[key] = keep_artwork(item, prev)
            else:
                unique[key] = keep_artwork(prev, item)
        rows = list(unique.values())
        try:
            self._remember_station_logos(cur, airings)
            cur.executemany(
                """
                INSERT INTO events(video_id, title, station, kind, start_ts, end_ts, deeplink, live, source, sport, entity_id, channel, artwork, artwork_secondary, station_logo, language, broadcast_live, first_run, is_repeat)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, start_ts) DO UPDATE SET
                    title = excluded.title,
                    station = excluded.station,
                    kind = excluded.kind,
                    end_ts = excluded.end_ts,
                    deeplink = excluded.deeplink,
                    live = excluded.live,
                    source = excluded.source,
                    sport = excluded.sport,
                    entity_id = excluded.entity_id,
                    channel = excluded.channel,
                    artwork = excluded.artwork,
                    artwork_secondary = excluded.artwork_secondary,
                    station_logo = excluded.station_logo,
                    language = excluded.language,
                    broadcast_live = excluded.broadcast_live,
                    first_run = excluded.first_run,
                    is_repeat = excluded.is_repeat
                """,
                [
                    self._row_values(item)
                    for item in rows
                ],
            )
            cur.executemany(
                "INSERT INTO lanes(lane, video_id, start_ts, end_ts) VALUES (?, ?, ?, ?)",
                [
                    (row.lane, row.airing.video_id, row.airing.start.timestamp(), row.airing.end.timestamp())
                    for row in assignments
                ],
            )
            self._set_meta("last_refresh", datetime.now(timezone.utc).isoformat(), cur)
            self._set_meta("last_error", for_ui(error), cur)
            self._set_meta("last_client", client, cur)
            self._set_meta("last_browse_id", browse_id, cur)
            self._set_meta("linear_ignored", str(linear_ignored), cur)
            self._write_count_meta(
                cur,
                assignments,
                dropped=dropped,
                visible_count=visible_count,
                watchable_count=watchable_count,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def replace_lanes(
        self,
        assignments: list[LaneAssignment],
        *,
        visible_count: Optional[int] = None,
        watchable_count: Optional[int] = None,
        dropped: Optional[int] = None,
    ) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM lanes")
            cur.executemany(
                "INSERT INTO lanes(lane, video_id, start_ts, end_ts) VALUES (?, ?, ?, ?)",
                [
                    (row.lane, row.airing.video_id, row.airing.start.timestamp(), row.airing.end.timestamp())
                    for row in assignments
                ],
            )
            if dropped is None and visible_count is not None:
                dropped = max(0, visible_count - len(assignments))
            self._write_count_meta(
                cur,
                assignments,
                dropped=dropped,
                visible_count=visible_count,
                watchable_count=watchable_count,
            )
            self._conn.commit()

    def replace_resolved(self, pairs: list[tuple[Airing, Airing]]) -> None:
        if not pairs:
            return
        with self._lock:
            cur = self._conn.cursor()
            self._remember_station_logos(cur, [resolved for _, resolved in pairs])
            for previous, resolved in pairs:
                cur.execute(
                    "DELETE FROM events WHERE video_id = ? AND start_ts = ?",
                    (previous.video_id, previous.start.timestamp()),
                )
                cur.execute(
                    """
                    INSERT INTO events(video_id, title, station, kind, start_ts, end_ts, deeplink, live, source, sport, entity_id, channel, artwork, artwork_secondary, station_logo, language, broadcast_live, first_run, is_repeat)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id, start_ts) DO UPDATE SET
                        title = excluded.title,
                        station = excluded.station,
                        kind = excluded.kind,
                        end_ts = excluded.end_ts,
                        deeplink = excluded.deeplink,
                        live = excluded.live,
                        source = excluded.source,
                        sport = excluded.sport,
                        entity_id = excluded.entity_id,
                        channel = excluded.channel,
                        artwork = excluded.artwork,
                        artwork_secondary = excluded.artwork_secondary,
                        station_logo = excluded.station_logo,
                        language = excluded.language,
                        broadcast_live = excluded.broadcast_live,
                        first_run = excluded.first_run,
                        is_repeat = excluded.is_repeat
                    """,
                    self._row_values(resolved),
                )
            self._conn.commit()

    def touch_refresh(self) -> None:
        with self._lock:
            self._set_meta("last_refresh", datetime.now(timezone.utc).isoformat())
            self._conn.commit()

    def update_sports(self, airings: list[Airing]) -> None:
        """Persist schedule enrichment, including verified broadcaster corrections."""
        with self._lock:
            self._conn.executemany(
                "UPDATE events SET sport = ?, station = ?, channel = ?, station_logo = ? WHERE video_id = ? AND start_ts = ?",
                [
                    (item.sport, item.station, item.channel, item.station_logo, item.video_id, item.start.timestamp())
                    for item in airings
                ],
            )
            self._conn.commit()

    def ensure_hidden_sports(self, defaults: list[str]) -> None:
        if "hidden_sports" in self.meta():
            return
        self.set_hidden_sports(defaults)

    def ensure_hidden_channels(self, defaults: list[str]) -> None:
        if "hidden_channels" in self.meta():
            return
        self._set_meta("channel_filter_version", "2")
        self.set_hidden_channels(defaults)

    def migrate_channel_filters(self) -> None:
        """Expand legacy family exclusions once before rebuilding startup lanes."""
        with self._lock:
            if self.meta().get("channel_filter_version") == "2":
                return
            hidden = self.hidden_channels()
            expanded = {channel_identity(name) for name in hidden}
            for family, hints in CHANNEL_RULES:
                if family in hidden:
                    expanded.update(channel_identity(hint) for hint in hints)
            for event in self.events():
                if infer_channel(event.station, event.title) in hidden:
                    expanded.add(event_channel(event))
            self._set_meta("hidden_channels", json.dumps(sorted(expanded - {""})))
            self._set_meta("channel_filter_version", "2")
            self._conn.commit()

    def set_error(self, message: str) -> None:
        with self._lock:
            self._set_meta("last_error", for_ui(message))
            self._set_meta("last_refresh", datetime.now(timezone.utc).isoformat())
            self._conn.commit()

    def clear_error(self) -> None:
        with self._lock:
            self._set_meta("last_error", "")
            self._conn.commit()

    def hidden_sports(self) -> list[str]:
        return self._meta_list("hidden_sports")

    def set_hidden_sports(self, sports: list[str]) -> None:
        with self._lock:
            self._set_meta_list("hidden_sports", sports)

    def hidden_channels(self) -> list[str]:
        return sorted({
            channel_filter(item)
            for item in self._meta_list("hidden_channels")
            if item not in {"Other", "Other extras"}
        })

    def set_hidden_channels(self, channels: list[str]) -> None:
        with self._lock:
            self._set_meta_list(
                "hidden_channels",
                [channel_filter(item) for item in channels if item not in {"Other", "Other extras"}],
            )

    def meta(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM meta").fetchall()
            return {str(row["key"]): str(row["value"]) for row in rows}

    def events(self, kind: Optional[str] = None) -> list[Airing]:
        sql = "SELECT * FROM events"
        args: tuple[Any, ...] = ()
        if kind:
            sql += " WHERE kind = ?"
            args = (kind,)
        sql += " ORDER BY start_ts, title"
        with self._lock:
            return [self._row_to_airing(row) for row in self._conn.execute(sql, args)]

    def assignments(self) -> list[LaneAssignment]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT l.lane, e.*
                FROM lanes l
                JOIN events e ON e.video_id = l.video_id
                    AND CAST(e.start_ts AS INTEGER) = CAST(l.start_ts AS INTEGER)
                ORDER BY l.lane, e.start_ts
                """
            ).fetchall()
            return [LaneAssignment(lane=int(row["lane"]), airing=self._row_to_airing(row)) for row in rows]

    def save_debug(self, data_dir: Path, name: str, payload: Any) -> None:
        target = data_dir / name
        target.write_text(json.dumps(payload, indent=2)[:2_000_000], encoding="utf-8")

    def _write_count_meta(
        self,
        cur: sqlite3.Cursor,
        assignments: list[LaneAssignment],
        *,
        dropped: Optional[int] = None,
        visible_count: Optional[int] = None,
        watchable_count: Optional[int] = None,
    ) -> None:
        self._set_meta("lanes_used", str(len({row.lane for row in assignments})), cur)
        if dropped is not None:
            self._set_meta("dropped_events", str(dropped), cur)
        if visible_count is not None:
            self._set_meta("visible_count", str(visible_count), cur)
        if watchable_count is not None:
            self._set_meta("watchable_count", str(watchable_count), cur)

    def _set_meta(self, key: str, value: str, cur: Optional[sqlite3.Cursor] = None) -> None:
        handle = cur or self._conn
        handle.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _meta_list(self, key: str) -> list[str]:
        raw = self.meta().get(key) or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [str(item) for item in data if item]

    def _set_meta_list(self, key: str, items: list[str]) -> None:
        cleaned = sorted({str(item).strip() for item in items if str(item).strip()})
        self._set_meta(key, json.dumps(cleaned))
        self._conn.commit()

    def _row_values(self, item: Airing) -> tuple[Any, ...]:
        return (
            item.video_id,
            item.title,
            item.station,
            item.kind,
            item.start.timestamp(),
            item.end.timestamp(),
            item.deeplink,
            1 if item.live else 0,
            item.source,
            item.sport,
            item.entity_id,
            item.channel or infer_channel(item.station, item.title),
            item.artwork,
            item.artwork_secondary,
            item.station_logo,
            broadcast_language(item),
            item.broadcast_live,
            item.first_run,
            item.is_repeat,
        )

    def _row_to_airing(self, row: sqlite3.Row) -> Airing:
        keys = row.keys()
        title = str(row["title"])
        station = clean_station(str(row["station"]), title)
        stored = str(row["sport"]) if "sport" in keys else ""
        sport = resolve_sport(title, station, stored)
        return Airing(
            video_id=str(row["video_id"]),
            title=title,
            station=station,
            kind=str(row["kind"]),
            start=datetime.fromtimestamp(float(row["start_ts"]), tz=timezone.utc),
            end=datetime.fromtimestamp(float(row["end_ts"]), tz=timezone.utc),
            deeplink=str(row["deeplink"]),
            live=bool(row["live"]),
            source=str(row["source"]),
            sport=sport,
            entity_id=str(row["entity_id"]) if "entity_id" in keys else "",
            channel=(str(row["channel"]) if "channel" in keys and row["channel"] else infer_channel(station, title)),
            artwork=str(row["artwork"]) if "artwork" in keys else "",
            artwork_secondary=str(row["artwork_secondary"]) if "artwork_secondary" in keys else "",
            station_logo=str(row["station_logo"]) if "station_logo" in keys else "",
            language=str(row["language"]) if "language" in keys else "",
            **{name: bool(row[name]) if name in keys and row[name] is not None else None
               for name in ("broadcast_live", "first_run", "is_repeat")},
        )
