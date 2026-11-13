from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from yttv_epg.branding import LOGO_PATH
from yttv_epg.broadcasts import label_live
from yttv_epg.parse import Airing
from yttv_epg.sports import clean_station, event_filter_channel


def local_tz(name: str = "") -> ZoneInfo:
    zone = name or os.environ.get("TZ") or "America/New_York"
    try:
        return ZoneInfo(zone)
    except Exception:
        return ZoneInfo("America/New_York")


def format_clock(start: datetime, *, tz: ZoneInfo | None = None) -> str:
    local = start.astimezone(tz or local_tz())
    return local.strftime("%I:%M %p").lstrip("0")


def format_day_heading(start: datetime, *, now: datetime | None = None, tz: ZoneInfo | None = None) -> str:
    zone = tz or local_tz()
    local = start.astimezone(zone)
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    today = current.date()
    if local.date() == today:
        return "Today"
    if local.date() == today + timedelta(days=1):
        return "Tomorrow"
    return f"{local.strftime('%A')}, {local.strftime('%B')} {local.day}"


def format_when(start: datetime, *, now: datetime | None = None, tz: ZoneInfo | None = None) -> str:
    zone = tz or local_tz()
    return f"{format_day_heading(start, now=now, tz=zone)} · {format_clock(start, tz=zone)}"


def format_refresh(value: str, *, now: datetime | None = None, tz: ZoneInfo | None = None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return format_when(parsed, now=now, tz=tz)


def event_for_ui(
    item: Airing, *, tz: ZoneInfo | None = None, now: datetime | None = None,
    live_on_air: bool = False,
) -> dict:
    zone = tz or local_tz()
    now = now or datetime.now(timezone.utc)
    payload = item.to_dict()
    payload["artwork_fallback"] = not bool(item.artwork)
    payload["artwork"] = item.artwork or LOGO_PATH
    payload["artwork_secondary"] = item.artwork_secondary
    payload["day"] = format_day_heading(item.start, now=now, tz=zone)
    payload["clock"] = format_clock(item.start, tz=zone) if item.has_scheduled_start else "Time TBD"
    payload["when"] = f'{payload["day"]} · {payload["clock"]}'
    payload["on_now"] = item.has_scheduled_start and item.start <= now < item.end
    payload["show_live"] = payload["on_now"] and label_live(item, now, live_on_air=live_on_air)
    payload["watchable"] = bool(item.watch_id())
    payload["channel"] = event_filter_channel(item)
    payload["station"] = clean_station(item.station, item.title) or payload["channel"]
    payload["search"] = " ".join(
        filter(None, [payload["day"], payload["clock"], item.sport, item.channel, item.title, item.station])
    ).lower()
    return payload


def group_events_for_ui(
    events: list[Airing],
    *,
    tz: ZoneInfo | None = None,
    now: datetime | None = None,
    limit: int = 1000,
    live_on_air: bool = False,
) -> list[dict]:
    zone = tz or local_tz()
    now = now or datetime.now(timezone.utc)
    groups: list[dict] = []
    current: dict | None = None
    for item in events[:limit]:
        heading = format_day_heading(item.start, now=now, tz=zone)
        if current is None or current["heading"] != heading:
            current = {"heading": heading, "events": []}
            groups.append(current)
        current["events"].append(event_for_ui(item, tz=zone, now=now, live_on_air=live_on_air))
    return groups
