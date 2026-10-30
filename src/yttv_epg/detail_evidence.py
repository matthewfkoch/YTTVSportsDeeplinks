"""Cached, observational broadcast evidence. Never changes Airing status or feeds."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from yttv_epg.detail_probe import capture_details
from yttv_epg.parse import Airing
from yttv_epg.sports import channel_identity, norm_name

CURRENT_TTL = 300
UPCOMING_TTL = 3600
FAILURE_TTL = 300
RETENTION_DAYS = 7
MAX_RECORDS = 1000
SPANISH_MONTHS = {name: number for number, name in enumerate((
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre"), 1)}

# Only explicit programme descriptions, not mentions of instant replay in live coverage.
REPLAY_DESCRIPTION = re.compile(
    r"^\s*(?:replays?\s+of\b|(?:replay|repeat|rerun|rebroadcast)\s*:|"
    r"(?:a\s+)?(?:replay|repeat|rerun|rebroadcast)\s+(?:of|from)\b)", re.IGNORECASE)
SPANISH_DESCRIPTION_SIGNALS = (
    ("explicit_replay_description", re.compile(
        r"^\s*(?:repetici[oó]n|reemisi[oó]n)\s*(?::|del\s+(?:partido|encuentro|evento)\b)", re.IGNORECASE)),
    ("highlights_description", re.compile(
        r"^\s*(?:(?:los\s+)?momentos\s+m[aá]s\s+destacados\s+del\s+partido\b|"
        r"(?:compacto|resumen)\s+(?:del\s+(?:partido|encuentro)|de\s+la\s+fecha)\b)",
        re.IGNORECASE)),
    ("dated_match_description", re.compile(
        r"(?:^|[.!?]\s+)\s*disputad[oa]\s+el\s+(?P<day>\d{1,2})\s+de\s+"
        r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
        r"\s+de\s+(?P<year>\d{4})\b", re.IGNORECASE)),
)


def _detail_station(text: str) -> str:
    parts = [part.strip() for part in text.split("•")]
    if len(parts) > 1 and parts[0] in {"ES", "EN"}:
        parts.pop(0)
    if len(parts) > 1 and parts[-1] in {"TV-Y", "TV-Y7", "TV-G", "TV-PG", "TV-14", "TV-MA"}:
        parts.pop()
    return " • ".join(parts)


def airing_identity(airing: Airing) -> dict:
    return {"video_id": airing.watch_id() or airing.video_id, "entity_id": airing.entity_id,
            "title": airing.title, "station": airing.station,
            "start": airing.start.isoformat(), "end": airing.end.isoformat()}


def cache_key(airing: Airing) -> str:
    # Watch IDs may identify a rolling channel, not a particular programme.
    return hashlib.sha256(json.dumps(airing_identity(airing), sort_keys=True).encode()).hexdigest()


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    return value.get("simpleText") or "".join(r.get("text", "") for r in value.get("runs", []) if isinstance(r, dict))


def _timestamp(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def extract_evidence(airing: Airing, capture: dict) -> dict:
    """Associate facts only with exact title/station/time matches, without inference."""
    records = capture.get("details", [])
    matches = []
    candidates = []
    for record in records:
        if record.get("renderer") != "unpluggedCompactVideoRenderer":
            continue
        fields = record["fields"]
        title = _text(fields.get("primaryText"))
        station = _text(fields.get("secondaryText"))
        start = _timestamp(fields.get("startTimeSeconds"))
        end = _timestamp(fields.get("endTimeSeconds"))
        video = fields.get("navigationEndpoint", {}).get("watchEndpoint", {}).get("videoId")
        checks = {"title": norm_name(title) == norm_name(airing.title),
                  "station": channel_identity(_detail_station(station)) == channel_identity(airing.station),
                  "start": start == airing.start, "end": end == airing.end,
                  "video_id": not video or not airing.watch_id() or video == airing.watch_id()}
        mismatches = [name for name, matches_field in checks.items() if not matches_field]
        candidates.append({"path": record["path"], "title": title, "station": station,
                           "mismatched_fields": mismatches})
        if not mismatches:
            matches.append(record)
    # Duplicate renderers are common in detail pages; preserve their source paths.
    result = {"mode": "observe_only", "automatic_exclusions": False,
              "match": "exact_airing" if matches else "unmatched",
              "matched_paths": [r["path"] for r in matches],
              "event_date": None, "event_date_text": None, "content_type": None,
              "airing_date": airing.start.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
              "date_gap_days": None, "badges": [], "descriptions": [], "signals": [],
              "description_evidence": [], "unmatched_candidates": []}
    if not matches:
        result["signals"] = ["no_exact_airing_match"]
        result["unmatched_candidates"] = sorted(candidates, key=lambda c: len(c["mismatched_fields"]))[:5]
        return result
    for record in matches:
        fields = record["fields"]
        badges = [fields.get("badge")] + (fields.get("badges") or [])
        for badge in badges:
            if isinstance(badge, dict):
                token = badge.get("unpluggedTextBadgeRenderer", {}).get("type")
                if token and token not in result["badges"]:
                    result["badges"].append(token)
        description = _text(fields.get("description"))
        if description and description not in result["descriptions"]:
            result["descriptions"].append(description)
        replay = REPLAY_DESCRIPTION.search(description)
        if replay:
            result["description_evidence"].append({"path": record["path"],
                "field": "description", "phrase": replay.group().strip(), "description": description})
            if "explicit_replay_description" not in result["signals"]:
                result["signals"].append("explicit_replay_description")
        for signal, pattern in SPANISH_DESCRIPTION_SIGNALS:
            match = pattern.search(description)
            if match:
                result["description_evidence"].append({"path": record["path"],
                    "field": "description", "phrase": match.group().lstrip(".!? ").strip(),
                    "description": description, "signal": signal, "language": "es"})
                if signal not in result["signals"]:
                    result["signals"].append(signal)
                if signal == "dated_match_description":
                    try:
                        played = datetime(int(match["year"]),
                                          SPANISH_MONTHS[match["month"].casefold()],
                                          int(match["day"])).date()
                    except ValueError:
                        continue
                    item = result["description_evidence"][-1]
                    item["played_date"] = played.isoformat()
                    airing_date = airing.start.astimezone(ZoneInfo("America/New_York")).date()
                    if played < airing_date:
                        item["signal"] = "historical_match_description"
                        if "historical_match_description" not in result["signals"]:
                            result["signals"].append("historical_match_description")
    headers = [r["fields"] for r in records if r.get("renderer") == "unpluggedContentDetailsHeaderRenderer"
               and norm_name(_text(r["fields"].get("title"))) == norm_name(airing.title)]
    if len(headers) == 1:
        header = headers[0]
        result["content_type"] = header.get("contentType")
        result["event_date_text"] = _text(header.get("secondaryText")) or None
        if result["content_type"] == "SPORTS_EVENT" and result["event_date_text"]:
            try:
                date = datetime.strptime(result["event_date_text"], "%b %d, %Y").date()
                result["event_date"] = date.isoformat()
                gap = (airing.start.astimezone(ZoneInfo("America/New_York")).date() - date).days
                result["date_gap_days"] = gap
                result["signals"].append("earlier_event_date" if gap > 0 else
                                         "same_day_not_live_confirmation" if gap == 0 else "event_date_after_airing")
            except ValueError:
                result["signals"].append("unparsed_event_date")
    if any(b in result["badges"] for b in ("LIVE", "LIVE_AND_RECORDING")):
        result["signals"].append("on_air_badge_not_live_confirmation")
    if any(b in result["badges"] for b in ("REPLAY", "REPEAT", "RERUN")):
        result["signals"].append("explicit_repeat_badge")
    return result


class EvidenceStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY, attempted REAL NOT NULL, retry_at REAL NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY, captured REAL NOT NULL, data TEXT NOT NULL
            );
        ''')

    def get(self, key):
        with self.lock:
            row = self.conn.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
            return dict(row) if row else None

    def save(self, airing, now, *, capture=None, error=None):
        key = cache_key(airing)
        current = airing.start <= now < airing.end
        ttl = FAILURE_TTL if error else CURRENT_TTL if current else UPCOMING_TTL
        # Upcoming observations must refresh when the programme starts.
        retry = now + timedelta(seconds=ttl)
        if not error and airing.start > now:
            retry = min(retry, airing.start)
        with self.lock:
            previous = self.get(key)
            data = json.loads(previous["data"]) if previous else {
                "key": key, "airing": airing_identity(airing), "capture": None, "evidence": None}
            data.update(last_attempt=now.isoformat(), next_fetch=retry.isoformat(), error=error)
            if capture is not None:
                data.update(capture=capture, evidence=extract_evidence(airing, capture), captured_at=now.isoformat())
                self.conn.execute("INSERT INTO history(captured,data) VALUES (?,?)", (now.timestamp(), json.dumps(data)))
            self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                              (key, now.timestamp(), retry.timestamp(), json.dumps(data)))
            self.conn.commit()
            self.prune(now)

    def prune(self, now):
        with self.lock:
            cutoff = (now - timedelta(days=RETENTION_DAYS)).timestamp()
            self.conn.execute("DELETE FROM cache WHERE attempted < ?", (cutoff,))
            self.conn.execute("DELETE FROM history WHERE captured < ?", (cutoff,))
            self.conn.execute("DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY attempted DESC LIMIT -1 OFFSET ?)", (MAX_RECORDS,))
            self.conn.execute("DELETE FROM history WHERE id IN (SELECT id FROM history ORDER BY id DESC LIMIT -1 OFFSET ?)", (MAX_RECORDS,))
            self.conn.commit()

    def records(self, *, limit=50, offset=0, history=False, include_capture=False, now=None):
        now = now or datetime.now(timezone.utc)
        table, order = ("history", "id") if history else ("cache", "attempted")
        with self.lock:
            rows = self.conn.execute(f"SELECT data FROM {table} ORDER BY {order} DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        result = []
        for row in rows:
            data = json.loads(row["data"])
            data["stale"] = (bool(data.get("error"))
                             or now >= datetime.fromisoformat(data["next_fetch"])
                             or now >= datetime.fromisoformat(data["airing"]["end"]))
            if not include_capture:
                data.pop("capture", None)
            result.append(data)
        return result


async def collect_evidence(store, client, session, airings, *, now=None, limit=4):
    now = now or datetime.now(timezone.utc)
    store.prune(now)
    pending = {}
    for airing in airings:
        if (airing.kind != "event" or airing.end <= now or airing.end <= airing.start
                or airing.start > now + timedelta(hours=24) or not (airing.entity_id or airing.watch_id())):
            continue
        key = cache_key(airing)
        cached = store.get(key)
        if cached and cached["retry_at"] > now.timestamp():
            continue
        pending[key] = (airing, cached["attempted"] if cached else 0)
    # First observations before refreshes prevent a busy live slate starving upcoming games.
    selected = sorted(pending.values(), key=lambda pair: (pair[1], pair[0].start > now, pair[0].start))[:limit]
    for airing, _ in selected:
        try:
            kwargs = {"browse_id": airing.entity_id} if airing.entity_id else {"video_id": airing.watch_id()}
            capture = await asyncio.wait_for(capture_details(client, session, **kwargs), timeout=10)
            # A stale entity ID may point at a network hub. Resolve the watched
            # programme instead when the first response doesn't match this slot.
            if airing.entity_id and airing.watch_id() and extract_evidence(airing, capture)["match"] == "unmatched":
                capture = await asyncio.wait_for(capture_details(client, session, video_id=airing.watch_id()), timeout=10)
            store.save(airing, now, capture=capture)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Store only the exception class; provider messages may include session data.
            store.save(airing, now, error=type(exc).__name__)
    return len(selected)
