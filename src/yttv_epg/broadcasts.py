"""Content broadcast status, separate from whether a TV stream is on air."""
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yttv_epg.parse import Airing


def label_live(airing: "Airing", now: datetime, *, live_on_air: bool = False) -> bool:
    return airing.has_scheduled_start and airing.is_repeat is not True and now < airing.end and (
        airing.broadcast_live is True
        or (live_on_air and airing.broadcast_live is None and airing.start <= now)
    )


def programme_badges(node: dict[str, Any]) -> dict[str, bool | None]:
    """Read explicit repeat and first-run badges. LIVE can describe a replay stream."""
    tokens: set[str] = set()
    values = [node.get("badge")]
    badges = node.get("badges")
    if isinstance(badges, list):
        values.extend(badges)
    for value in values:
        if not isinstance(value, dict):
            continue
        badge = value.get("unpluggedTextBadgeRenderer")
        if isinstance(badge, dict) and isinstance(badge.get("type"), str):
            tokens.add(badge["type"].upper())
    repeat = bool(tokens & {"REPLAY", "REPEAT", "RERUN"})
    return {
        "broadcast_live": False if repeat else None,
        "first_run": False if repeat else (True if "NEW" in tokens else None),
        "is_repeat": True if repeat else None,
    }


def merged_status(winner: Any, other: Any) -> Any:
    # A related game's status is not evidence for this specific broadcast slot.
    same_id = bool(
        winner.watch_id() and winner.watch_id() == other.watch_id()
        or winner.entity_id and winner.entity_id == other.entity_id
    )
    if not same_id or winner.start != other.start:
        return winner
    fields = {}
    for name in ("broadcast_live", "first_run", "is_repeat"):
        current, incoming = getattr(winner, name), getattr(other, name)
        if name == "is_repeat":
            fields[name] = True if current is True or incoming is True else (current if current is not None else incoming)
        else:
            # Negative explicit evidence wins a conflict; unknown adds no evidence.
            fields[name] = False if current is False or incoming is False else (current if current is not None else incoming)
    if fields["is_repeat"] is True:
        fields.update(broadcast_live=False, first_run=False)
    return replace(winner, **fields)
