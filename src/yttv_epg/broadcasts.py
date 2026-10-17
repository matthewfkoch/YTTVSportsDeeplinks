"""Content broadcast status, separate from whether a TV stream is on air."""
from dataclasses import replace
from typing import Any


def programme_badges(node: dict[str, Any], *, sports_card: bool = False) -> dict[str, bool | None]:
    """Only direct programme badges are evidence; isLive/live may describe the stream.

    LIVE is content evidence only on an event-specific sports game card. Missing
    badges and LIVE badges on a linear EPG airing remain unknown.
    """
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
        "broadcast_live": False if repeat else (True if sports_card and "LIVE" in tokens else None),
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
