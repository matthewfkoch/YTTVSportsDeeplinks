from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from yttv_epg.parse import Airing


@dataclass
class LaneAssignment:
    lane: int
    airing: Airing


def pack_lanes(
    events: list[Airing],
    lane_count: int,
    previous: Optional[list[LaneAssignment]] = None,
) -> list[LaneAssignment]:
    if lane_count < 1:
        return []
    watchable: list[Airing] = []
    seen: set[tuple[str, int]] = set()
    for airing in events:
        watch = airing.watch_id()
        if not watch:
            continue
        key = (watch, int(airing.start.timestamp()))
        if key in seen:
            continue
        seen.add(key)
        watchable.append(airing)

    occupied: list[list[tuple[datetime, datetime]]] = [[] for _ in range(lane_count)]
    assigned: list[LaneAssignment] = []
    placed: set[int] = set()

    def fits(index: int, start: datetime, end: datetime) -> bool:
        if end <= start:
            return False
        for ready, until in occupied[index]:
            if start < until and end > ready:
                return False
        return True

    def place(index: int, airing: Airing) -> None:
        occupied[index].append((airing.start, airing.end))
        assigned.append(LaneAssignment(lane=index + 1, airing=airing))
        placed.add(id(airing))

    if previous:
        for row in previous:
            index = row.lane - 1
            if index < 0 or index >= lane_count:
                continue
            for airing in watchable:
                if id(airing) in placed:
                    continue
                if not _sticky_match(row.airing, airing):
                    continue
                if fits(index, airing.start, airing.end):
                    place(index, airing)
                    break

    leftover = [item for item in watchable if id(item) not in placed]
    leftover.sort(key=lambda item: (not item.live, item.start, item.end, item.title))
    for airing in leftover:
        if airing.end <= airing.start:
            continue
        for index in range(lane_count):
            if fits(index, airing.start, airing.end):
                place(index, airing)
                break
    return assigned


def whatson(
    assignments: list[LaneAssignment],
    lane: int,
    when: Optional[datetime] = None,
) -> Optional[Airing]:
    when = when or datetime.now(timezone.utc)
    matches = [
        row.airing
        for row in assignments
        if row.lane == lane and row.airing.start <= when < row.airing.end
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item.start, reverse=True)
    return matches[0]


def _sticky_match(previous: Airing, candidate: Airing) -> bool:
    watch = previous.watch_id()
    same_watch = bool(watch and watch == candidate.watch_id())
    same_entity = bool(
        previous.entity_id and candidate.entity_id and previous.entity_id == candidate.entity_id
    )
    if not same_watch and not same_entity:
        return False
    return previous.start < candidate.end and candidate.start < previous.end
