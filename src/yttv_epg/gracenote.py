"""Optional enrichment from locally supplied Gracenote /api/grid JSON.

No network requests or authentication cookies are needed. Evidence is applied at
read time so removing/replacing the file cannot leave persisted Live flags behind.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import re

from yttv_epg.parse import Airing
from yttv_epg.sports import channel_identity, is_sports_event

log = logging.getLogger(__name__)
REPEAT_FLAGS = {"repeat", "replay", "rerun", "previously shown"}
DELAY_FLAGS = {"tape delay", "tape delayed"}


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold() if isinstance(value, str) else ""


def _station(value: object) -> str:
    return _text(channel_identity(value)) if isinstance(value, str) else ""


@dataclass(frozen=True)
class Listing:
    station: str
    start: datetime
    end: datetime
    titles: frozenset[str]
    flags: frozenset[str]


def parse_grid(payload: object) -> tuple[Listing, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("channels"), list):
        raise ValueError("Expected a Gracenote grid object with channels")
    listings = []
    for channel in payload["channels"]:
        if not isinstance(channel, dict) or not isinstance(channel.get("events"), list):
            continue
        station = _station(channel.get("callSign"))
        if not station:
            continue
        for event in channel["events"]:
            if not isinstance(event, dict):
                continue
            program = event.get("program")
            flags = event.get("flag")
            if not isinstance(program, dict) or not isinstance(flags, list):
                continue
            try:
                start = datetime.fromisoformat(event["startTime"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(event["endTime"].replace("Z", "+00:00"))
                if start.utcoffset() is None or end.utcoffset() is None or end <= start:
                    continue
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            title, episode = _text(program.get("title")), _text(program.get("episodeTitle"))
            titles = frozenset(t for t in (title, episode, f"{title}: {episode}" if title and episode else "") if t)
            if titles:
                listings.append(Listing(station, start, end, titles,
                                        frozenset(_text(f) for f in flags if _text(f))))
    return tuple(listings)


@lru_cache(maxsize=4)
def _load(path: str, mtime: int, size: int) -> tuple[Listing, ...]:
    try:
        return parse_grid(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        log.warning("Unable to read Gracenote grid JSON: %s", path)
        return ()


def load_grid(path: Path | None) -> tuple[Listing, ...]:
    if path is None:
        return ()
    try:
        stat = path.stat()
        return _load(str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ()


def apply_gracenote(events: list[Airing], listings: tuple[Listing, ...]) -> list[Airing]:
    index: dict[tuple, list[Listing]] = {}
    for listing in listings:
        index.setdefault((listing.station, listing.start, listing.end), []).append(listing)
    result = []
    for event in events:
        matches = [row for row in index.get((_station(event.station), event.start, event.end), [])
                   if _text(event.title) in row.titles]
        # Conflicting duplicates provide no usable evidence.
        if (not event.has_scheduled_start or event.end_estimated
                or not matches or len({row.flags for row in matches}) != 1
                or not is_sports_event(event.station, event.title, event.sport)):
            result.append(event)
            continue
        flags = matches[0].flags
        changes = {"gracenote_flags": tuple(sorted(flags))}
        if flags & REPEAT_FLAGS:
            changes.update(is_repeat=True, broadcast_live=False, first_run=False)
        elif event.is_repeat is not True:
            if flags & DELAY_FLAGS:
                changes["broadcast_live"] = False
            elif "live" in flags and event.broadcast_live is None:
                changes["broadcast_live"] = True
            if "new" in flags and event.first_run is None:
                changes["first_run"] = True
        result.append(replace(event, **changes))
    return result
