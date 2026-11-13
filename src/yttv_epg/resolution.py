"""Select useful watch-link lookups without letting expired listings consume the budget."""
from datetime import datetime, timedelta, timezone
from typing import Iterable

from yttv_epg.parse import GAME_CARD_ZONE, Airing


def unresolved_soon(events: Iterable[Airing], *, now: datetime | None = None,
                    within_hours: int = 36, limit: int = 80) -> list[Airing]:
    now = now or datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=within_hours)
    today = now.astimezone(GAME_CARD_ZONE).date()
    last_day = cutoff.astimezone(GAME_CARD_ZONE).date()
    candidates = [item for item in events if isinstance(item, Airing)
                  and item.entity_id and item.start_source != "legacy"
                  and (not item.watch_id() or item.start_source == "date")
                  and (
                      today <= item.start.astimezone(GAME_CARD_ZONE).date() <= last_day
                      if item.start_source == "date"
                      else item.end > item.start and item.end > now and item.start <= cutoff
                  )]
    candidates.sort(key=lambda item: (
        not item.has_scheduled_start, item.start > now, item.start, item.end, item.event_key()
    ))
    return candidates[:max(0, limit)]
