"""Select useful watch-link lookups without letting expired listings consume the budget."""
from datetime import datetime, timedelta, timezone
from typing import Iterable

from yttv_epg.parse import Airing


def unresolved_soon(events: Iterable[Airing], *, now: datetime | None = None,
                    within_hours: int = 36, limit: int = 80) -> list[Airing]:
    now = now or datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=within_hours)
    candidates = [item for item in events if isinstance(item, Airing)
                  and not item.watch_id() and item.entity_id
                  and item.end > item.start and item.end > now and item.start <= cutoff]
    candidates.sort(key=lambda item: (item.start > now, item.start, item.end, item.event_key()))
    return candidates[:max(0, limit)]
