from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from yttv_epg.parse import Airing


@dataclass
class LaneAssignment:
    lane: int
    airing: Airing


def pack_lanes(events: list[Airing], lane_count: int) -> list[LaneAssignment]:
    if lane_count < 1:
        return []
    free_at = [datetime.min.replace(tzinfo=timezone.utc) for _ in range(lane_count)]
    assigned: list[LaneAssignment] = []
    for airing in sorted(events, key=lambda item: (not item.live, item.start, item.end, item.title)):
        if not airing.watch_id():
            continue
        for index, ready in enumerate(free_at):
            if airing.start >= ready:
                free_at[index] = airing.end
                assigned.append(LaneAssignment(lane=index + 1, airing=airing))
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
