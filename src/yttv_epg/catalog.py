from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import Airing, merge_airings
from yttv_epg.sports import clean_station, infer_channel, resolve_sport, visible_events


def _better_row(candidate: Airing, current: Airing) -> bool:
    if bool(candidate.watch_id()) != bool(current.watch_id()):
        return bool(candidate.watch_id())
    if len(candidate.title) != len(current.title):
        return len(candidate.title) > len(current.title)
    if bool(candidate.station) != bool(current.station):
        return bool(candidate.station)
    return len(candidate.station) > len(current.station)


class Catalog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
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
        self._conn.commit()

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
    ) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM events")
        cur.execute("DELETE FROM lanes")
        unique: dict[tuple[str, int], Airing] = {}
        for item in airings:
            key = (item.video_id, int(item.start.timestamp()))
            prev = unique.get(key)
            if prev is None or _better_row(item, prev):
                unique[key] = item
        rows = list(unique.values())
        try:
            cur.executemany(
                """
                INSERT INTO events(video_id, title, station, kind, start_ts, end_ts, deeplink, live, source, sport, entity_id, channel)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    channel = excluded.channel
                """,
                [
                    (
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
                    )
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
            self._set_meta("last_error", error, cur)
            self._set_meta("last_client", client, cur)
            self._set_meta("last_browse_id", browse_id, cur)
            self._set_meta("linear_ignored", str(linear_ignored), cur)
            self._set_meta("lanes_used", str(len({row.lane for row in assignments})), cur)
            self._set_meta("dropped_events", str(dropped), cur)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def replace_lanes(self, assignments: list[LaneAssignment]) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM lanes")
        cur.executemany(
            "INSERT INTO lanes(lane, video_id, start_ts, end_ts) VALUES (?, ?, ?, ?)",
            [
                (row.lane, row.airing.video_id, row.airing.start.timestamp(), row.airing.end.timestamp())
                for row in assignments
            ],
        )
        self._conn.commit()

    def update_sports(self, airings: list[Airing]) -> None:
        self._conn.executemany(
            "UPDATE events SET sport = ? WHERE video_id = ? AND start_ts = ?",
            [
                (item.sport, item.video_id, item.start.timestamp())
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
        self.set_hidden_channels(defaults)

    def set_error(self, message: str) -> None:
        self._set_meta("last_error", message)
        self._set_meta("last_refresh", datetime.now(timezone.utc).isoformat())
        self._conn.commit()

    def hidden_sports(self) -> list[str]:
        return self._meta_list("hidden_sports")

    def set_hidden_sports(self, sports: list[str]) -> None:
        self._set_meta_list("hidden_sports", sports)

    def hidden_channels(self) -> list[str]:
        return [
            item
            for item in self._meta_list("hidden_channels")
            if item not in {"Other", "Other extras"}
        ]

    def set_hidden_channels(self, channels: list[str]) -> None:
        self._set_meta_list(
            "hidden_channels",
            [item for item in channels if item not in {"Other", "Other extras"}],
        )

    def filtered_events(self) -> list[Airing]:
        return visible_events(
            merge_airings(self.events(kind="event")),
            self.hidden_sports(),
            self.hidden_channels(),
            require_watch_link=True,
        )

    def meta(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM meta").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def events(self, kind: Optional[str] = None) -> list[Airing]:
        sql = "SELECT * FROM events"
        args: tuple[Any, ...] = ()
        if kind:
            sql += " WHERE kind = ?"
            args = (kind,)
        sql += " ORDER BY start_ts, title"
        return [self._row_to_airing(row) for row in self._conn.execute(sql, args)]

    def assignments(self) -> list[LaneAssignment]:
        rows = self._conn.execute(
            """
            SELECT l.lane, e.*
            FROM lanes l
            JOIN events e ON e.video_id = l.video_id AND e.start_ts = l.start_ts
            ORDER BY l.lane, e.start_ts
            """
        ).fetchall()
        return [LaneAssignment(lane=int(row["lane"]), airing=self._row_to_airing(row)) for row in rows]

    def save_debug(self, data_dir: Path, name: str, payload: Any) -> None:
        target = data_dir / name
        target.write_text(json.dumps(payload, indent=2)[:2_000_000], encoding="utf-8")

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
            channel=infer_channel(station, title),
        )
