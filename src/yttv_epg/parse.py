from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from yttv_epg.sports import (
    clean_station,
    infer_channel,
    infer_sport,
    is_digital_extra,
    is_espn_plus,
    is_extra_station,
    is_junk,
    is_matchup,
    is_sports_chip_title,
    is_sports_event,
    is_sports_hub_label,
    is_unusable_channel_label,
    norm_name,
    outlet_rank,
)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ENTITY_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,}$")
GAME_WHEN_SPLIT_RE = re.compile(r"\s*[•·|]\s*")
TRAILING_FOOTBALL_RE = re.compile(r"\s+football$", re.I)

LINEAR_STATIONS = {
    "ABC",
    "ACC NETWORK",
    "ACCN",
    "CBS",
    "CNBC",
    "CNN",
    "ESPN",
    "ESPN2",
    "ESPNU",
    "ESPNEWS",
    "ESPN DEPORTES",
    "FOX",
    "FOX SPORTS 1",
    "FOX SPORTS 2",
    "FS1",
    "FS2",
    "MLB NETWORK",
    "MSNBC",
    "NBA TV",
    "NBC",
    "NFL NETWORK",
    "NHL NETWORK",
    "SEC NETWORK",
    "SECN",
    "TBS",
    "TNT",
    "USA",
    "USA NETWORK",
}

MIN_UNIX_TS = 946684800  # 2000-01-01
MAX_UNIX_TS = 4102444800  # 2100-01-01
MIN_ARTWORK_WIDTH = 640
MIN_FALLBACK_ARTWORK_WIDTH = 200
ARTWORK_WIDTH = 960
ARTWORK_HEIGHT = 540
GUIDE_ARTWORK_WIDTH = 720
GUIDE_ARTWORK_HEIGHT = 540
POSTER_ARTWORK_SCORE = 1_000_000


@dataclass
class Airing:
    video_id: str
    title: str
    station: str
    kind: str  # linear | event
    start: datetime
    end: datetime
    deeplink: str
    live: bool = False
    source: str = ""
    sport: str = ""
    entity_id: str = ""
    channel: str = ""
    artwork: str = ""

    def watch_id(self) -> str:
        return self.video_id if _ok_video_id(self.video_id) else ""

    def event_key(self) -> str:
        return self.entity_id or self.video_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.watch_id() or self.video_id,
            "title": self.title,
            "station": self.station,
            "kind": self.kind,
            "sport": self.sport,
            "channel": self.channel,
            "entity_id": self.entity_id,
            "start": self.start.astimezone(timezone.utc).isoformat(),
            "end": self.end.astimezone(timezone.utc).isoformat(),
            "deeplink": self.deeplink,
            "live": self.live,
            "source": self.source,
            "artwork": self.artwork,
        }


def parse_browse(
    payload: Any,
    *,
    now: Optional[datetime] = None,
    fallback_minutes: int = 180,
    source: str = "",
) -> list[Airing]:
    now = now or datetime.now(timezone.utc)
    return merge_airings(_walk(payload, _WalkCtx(), now, fallback_minutes, source))


def merge_airings(airings: Iterable[Airing]) -> list[Airing]:
    found: dict[tuple[str, str, int], Airing] = {}
    for airing in airings:
        key = _airing_key(airing)
        prev = found.get(key)
        if prev is None:
            found[key] = airing
        elif _better_airing(airing, prev):
            found[key] = keep_artwork(airing, prev)
        else:
            found[key] = keep_artwork(prev, airing)
    return _prefer_linear_simulcasts(list(found.values()))


def _prefer_linear_simulcasts(airings: list[Airing]) -> list[Airing]:
    ordered = sorted(
        airings,
        key=lambda item: (
            0 if item.watch_id() else 1,
            0 if "?vp=" in item.deeplink else 1,
            outlet_rank(item.station, item.title, item.channel),
            -len(item.title),
            item.video_id,
        ),
    )
    kept: list[Airing] = []
    buckets: dict[str, list[Airing]] = {}
    for item in ordered:
        if not is_matchup(item.title):
            kept.append(item)
            continue
        buckets.setdefault(_matchup_key(item.title), []).append(item)
    for group in buckets.values():
        group_kept: list[Airing] = []
        for item in group:
            if any(_same_matchup_slot(item, prev) for prev in group_kept):
                continue
            group_kept.append(item)
        filled: list[Airing] = []
        for kept_item in group_kept:
            if kept_item.artwork:
                filled.append(kept_item)
                continue
            art = next(
                (item.artwork for item in group if item.artwork and _same_matchup_slot(kept_item, item)),
                "",
            )
            filled.append(replace(kept_item, artwork=art) if art else kept_item)
        kept.extend(filled)
    return sorted(kept, key=lambda item: (item.start, item.title, item.video_id))


def _same_matchup_slot(left: Airing, right: Airing) -> bool:
    if not is_matchup(left.title) or not is_matchup(right.title):
        return False
    if _matchup_key(left.title) != _matchup_key(right.title):
        return False
    overlap = (min(left.end, right.end) - max(left.start, right.start)).total_seconds()
    return overlap >= 15 * 60


def _matchup_key(title: str) -> str:
    text = norm_name(title)
    text = re.sub(r"^EN ESPA[NÑ]OL[-\s]*", "", text)
    return text.strip()


def _airing_key(airing: Airing) -> tuple[str, str, int]:
    start = int(airing.start.timestamp())
    watch = airing.watch_id()
    if watch:
        return ("video", watch, start)
    if airing.entity_id:
        return ("entity", airing.entity_id, start)
    return ("title", f"{airing.title}|{airing.station}", start)


def _better_airing(candidate: Airing, current: Airing) -> bool:
    if bool(candidate.watch_id()) != bool(current.watch_id()):
        return bool(candidate.watch_id())
    cand_vp = "?vp=" in candidate.deeplink
    cur_vp = "?vp=" in current.deeplink
    if cand_vp != cur_vp:
        return cand_vp
    cand_rank = outlet_rank(candidate.station, candidate.title, candidate.channel)
    cur_rank = outlet_rank(current.station, current.title, current.channel)
    if cand_rank != cur_rank:
        return cand_rank < cur_rank
    if len(candidate.title) != len(current.title):
        return len(candidate.title) > len(current.title)
    if bool(candidate.station) != bool(current.station):
        return bool(candidate.station)
    if bool(candidate.artwork) != bool(current.artwork):
        return bool(candidate.artwork)
    return len(candidate.station) > len(current.station)


def keep_artwork(winner: Airing, other: Airing) -> Airing:
    if winner.artwork or not other.artwork:
        return winner
    return replace(winner, artwork=other.artwork)


@dataclass
class _WalkCtx:
    title: str = ""
    station: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    live: bool = False
    row_kind: str = ""
    sport: str = ""
    tab: str = ""
    entity_id: str = ""
    artwork: str = ""

    def child(self, **kwargs: Any) -> _WalkCtx:
        data = self.__dict__.copy()
        data.update(kwargs)
        return _WalkCtx(**data)


def _walk(
    node: Any,
    ctx: _WalkCtx,
    now: datetime,
    fallback_minutes: int,
    source: str,
) -> Iterable[Airing]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item, ctx, now, fallback_minutes, source)
        return
    if not isinstance(node, dict):
        return

    next_ctx = _context_from_node(node, ctx)
    watch_ep = _watch_endpoint_from_node(node)
    video_id = _video_id_from_watch(watch_ep) or _bare_video_id(node)
    watch_params = _watch_params(watch_ep)
    entity_id = _entity_id_from_node(node)
    if entity_id:
        next_ctx = next_ctx.child(entity_id=entity_id)
    if video_id or _is_schedule_card(node, entity_id, next_ctx):
        airing = _to_airing(
            video_id or entity_id or "",
            next_ctx,
            now,
            fallback_minutes,
            source,
            watch_params=watch_params,
        )
        if airing.video_id and not is_junk(airing.title, next_ctx.station):
            yield airing

    if "tabRenderer" in node and isinstance(node["tabRenderer"], dict):
        tab = node["tabRenderer"]
        yield from _walk(
            tab,
            next_ctx.child(tab=_text(tab.get("title")) or ctx.tab),
            now,
            fallback_minutes,
            source,
        )
        return
    if "shelfRenderer" in node and isinstance(node["shelfRenderer"], dict):
        shelf = node["shelfRenderer"]
        inferred = infer_sport("", "", _text(shelf.get("title")))
        sport = inferred if inferred != "Other" else ctx.sport
        yield from _walk(shelf, next_ctx.child(sport=sport), now, fallback_minutes, source)
        return
    if "epgAiringRenderer" in node and isinstance(node["epgAiringRenderer"], dict):
        yield from _walk(node["epgAiringRenderer"], next_ctx, now, fallback_minutes, source)
        return
    if "epgRowRenderer" in node and isinstance(node["epgRowRenderer"], dict):
        yield from _walk(node["epgRowRenderer"], next_ctx, now, fallback_minutes, source)
        return
    if "unpluggedVideoRenderer" in node and isinstance(node["unpluggedVideoRenderer"], dict):
        yield from _walk(node["unpluggedVideoRenderer"], next_ctx, now, fallback_minutes, source)
        return
    if "unpluggedGameCardRenderer" in node and isinstance(node["unpluggedGameCardRenderer"], dict):
        airing = _airing_from_game_card(
            node["unpluggedGameCardRenderer"], next_ctx, now, fallback_minutes, source
        )
        if airing is not None:
            yield airing
        return
    if "unpluggedHomeItemRenderer" in node and isinstance(node["unpluggedHomeItemRenderer"], dict):
        yield from _walk(node["unpluggedHomeItemRenderer"], next_ctx, now, fallback_minutes, source)
        return

    for value in node.values():
        yield from _walk(value, next_ctx, now, fallback_minutes, source)


def _context_from_node(node: dict[str, Any], ctx: _WalkCtx) -> _WalkCtx:
    title = _title_from_node(node) or ctx.title
    station = _station_from_node(node) or ctx.station
    start = (
        _time_from_node(
            node,
            ("startTime", "startTimeUtc", "start_time", "startTimestamp", "startTimeSeconds", "beginTimeMs"),
        )
        or ctx.start
    )
    end = (
        _time_from_node(
            node,
            ("endTime", "endTimeUtc", "end_time", "endTimestamp", "endTimeSeconds", "endTimeMs"),
        )
        or ctx.end
    )
    upcoming = node.get("upcomingEventData")
    if isinstance(upcoming, dict):
        start = _coerce_time(upcoming.get("startTime")) or start
    live = ctx.live or _is_live(node)
    sport = ctx.sport
    if title != ctx.title or station != ctx.station:
        inferred = infer_sport(title, station)
        if inferred != "Other":
            sport = inferred
    score, url = _best_artwork(node)
    artwork = url if url and (score >= POSTER_ARTWORK_SCORE or not ctx.artwork) else ctx.artwork
    return ctx.child(
        title=title,
        station=station,
        start=start,
        end=end,
        live=live,
        sport=sport,
        artwork=artwork,
    )


def _to_airing(
    video_id: str,
    ctx: _WalkCtx,
    now: datetime,
    fallback_minutes: int,
    source: str,
    watch_params: str = "",
) -> Airing:
    title = (ctx.title or ctx.station or f"YTTV {video_id}").strip()
    if is_unusable_channel_label(title):
        title = (ctx.title or f"YTTV {video_id}").strip()
    station = clean_station(ctx.station, title)
    start = ctx.start or now
    end = ctx.end or (start + timedelta(minutes=fallback_minutes))
    if end <= start:
        end = start + timedelta(minutes=fallback_minutes)
    kind = _classify(station, title, ctx.sport, ctx.tab)
    watch = video_id if _ok_video_id(video_id) else ""
    entity_id = ctx.entity_id
    if not watch and ENTITY_ID_RE.match(video_id or ""):
        entity_id = entity_id or video_id
    return Airing(
        video_id=watch or entity_id or video_id,
        title=title,
        station=station,
        kind=kind,
        start=_as_utc(start),
        end=_as_utc(end),
        deeplink=watch_deeplink(watch, watch_params),
        live=ctx.live or start <= now < end,
        source=source,
        sport=ctx.sport or infer_sport(title, station),
        entity_id=entity_id,
        channel=infer_channel(station, title),
        artwork=ctx.artwork,
    )


def _airing_from_game_card(
    card: dict[str, Any],
    ctx: _WalkCtx,
    now: datetime,
    fallback_minutes: int,
    source: str,
) -> Optional[Airing]:
    when_text = _text(card.get("primaryText"))
    secondary = _text(card.get("secondaryText"))
    away, home = _game_card_teams(card)
    if away and home:
        title = f"{away} at {home}"
        station = _station_from_game_when(when_text) or _station_from_secondary(secondary, card) or ctx.station
        sport_hint = secondary
    elif is_matchup(when_text):
        title = when_text
        station = _station_from_secondary(secondary, card) or clean_station(secondary) or ctx.station
        sport_hint = secondary if station != secondary else ctx.sport
    else:
        return None
    if is_junk(title, station):
        return None
    start = (
        _time_from_node(card, ("startTime", "startTimeUtc", "startTimeSeconds", "beginTimeMs"))
        or _parse_game_card_start(when_text, now)
    )
    if start is None:
        if _is_live(card):
            start = now
        else:
            return None
    end = _time_from_node(card, ("endTime", "endTimeUtc", "endTimeSeconds", "endTimeMs"))
    if end is None or end <= start:
        end = start + timedelta(minutes=fallback_minutes)
    sport = sport_hint or ctx.sport
    if sport:
        inferred = infer_sport(f"{sport} {title}", station)
        sport = inferred if inferred != "Other" else (ctx.sport or inferred)
    watch_ep = _watch_endpoint_from_node(card)
    video_id = _video_id_from_watch(watch_ep) or _bare_video_id(card) or ""
    entity_id = _entity_id_from_node(card) or _game_card_entity(card)
    stored_id = video_id if _ok_video_id(video_id) else f"{title}|{station}|{int(_as_utc(start).timestamp())}"
    return _to_airing(
        stored_id,
        _WalkCtx(
            title=title,
            station=station,
            start=start,
            end=end,
            live=_is_live(card),
            sport=sport or "",
            tab=ctx.tab,
            entity_id=entity_id,
            artwork=_artwork_from_node(card),
        ),
        now,
        fallback_minutes,
        source,
        watch_params=_watch_params(watch_ep),
    )


def _game_card_teams(card: dict[str, Any]) -> tuple[str, str]:
    found: list[tuple[str, str]] = []

    def walk(node: Any, depth: int = 0) -> None:
        if found or depth > 8 or not isinstance(node, (dict, list)):
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        start = node.get("startTeamPrimaryText")
        end = node.get("endTeamPrimaryText")
        if start is not None or end is not None:
            away = _game_team_name(start)
            home = _game_team_name(end)
            if away and home:
                found.append((away, home))
                return
        for key, value in node.items():
            if key in {"thumbnail", "thumbnails", "trackingParams", "menu"}:
                continue
            walk(value, depth + 1)

    walk(card)
    return found[0] if found else ("", "")


def _game_team_name(node: Any) -> str:
    if not isinstance(node, dict):
        return TRAILING_FOOTBALL_RE.sub("", _text(node)).strip()
    acc = _dig(node, ("accessibility", "accessibilityData", "label"))
    name = acc.strip() if isinstance(acc, str) and acc.strip() else _text(node)
    return TRAILING_FOOTBALL_RE.sub("", name).strip()


def _station_from_game_when(text: str) -> str:
    parts = [part.strip() for part in GAME_WHEN_SPLIT_RE.split(text or "") if part.strip()]
    if len(parts) < 2:
        return clean_station(text)
    return clean_station(parts[-1])


def _parse_game_card_start(text: str, now: datetime) -> Optional[datetime]:
    parts = [part.strip() for part in GAME_WHEN_SPLIT_RE.split(text or "") if part.strip()]
    when = parts[0] if parts else (text or "").strip()
    if not when:
        return None
    zone = ZoneInfo("America/New_York")
    local = now.astimezone(zone)
    when = re.sub(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+", "", when, flags=re.I)
    lowered = when.lower()
    if lowered == "today":
        day = local.date()
    elif lowered == "tomorrow":
        day = local.date() + timedelta(days=1)
    else:
        parsed = None
        for fmt in ("%b %d", "%B %d"):
            try:
                parsed = datetime.strptime(when.replace(".", ""), fmt).replace(year=local.year)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
        day = parsed.date()
        if day < (local.date() - timedelta(days=14)):
            day = day.replace(year=local.year + 1)
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=zone).astimezone(timezone.utc)


def _game_card_entity(card: dict[str, Any]) -> str:
    found: list[str] = []

    def walk(node: Any) -> None:
        if found or not isinstance(node, (dict, list)):
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        browse_id = node.get("browseId")
        if isinstance(browse_id, str) and ENTITY_ID_RE.match(browse_id):
            found.append(browse_id)
            return
        for key, value in node.items():
            if key in {"thumbnail", "thumbnails", "trackingParams"}:
                continue
            walk(value)

    walk(card)
    return found[0] if found else ""


def _classify(station: str, title: str, sport: str = "", tab: str = "") -> str:
    if is_sports_event(station, title, sport, tab):
        return "event"
    station_u = _norm_name(station)
    title_u = _norm_name(title)
    if station_u in LINEAR_STATIONS or (title_u in LINEAR_STATIONS and not station):
        return "linear"
    return "other"


def _norm_name(value: str) -> str:
    return norm_name(value)


def _is_schedule_card(node: dict[str, Any], entity_id: str, ctx: _WalkCtx) -> bool:
    if not entity_id:
        return False
    if node.get("startTimeSeconds") is None and ctx.start is None:
        return False
    return "primaryText" in node or "entityPageNavigationEndpoint" in node


def _entity_id_from_node(node: dict[str, Any]) -> str:
    if node.get("startTimeSeconds") is None and "entityPageNavigationEndpoint" not in node:
        return ""
    for key in ("entityPageNavigationEndpoint", "navigationEndpoint"):
        nested = node.get(key)
        if not isinstance(nested, dict):
            continue
        browse_id = _browse_id_from(nested)
        if ENTITY_ID_RE.match(browse_id):
            return browse_id
    return ""


def discover_event_hubs(payload: Any) -> list[str]:
    extras: list[str] = []
    espn: list[str] = []
    other: list[str] = []
    seen: set[str] = set()

    def add(browse_id: str, label: str = "", extra: bool = False) -> None:
        if not browse_id.startswith("UC") or browse_id in seen:
            return
        seen.add(browse_id)
        name = _norm_name(label)
        if extra or is_extra_station(name):
            extras.append(browse_id)
        elif "ESPN" in name:
            espn.append(browse_id)
        else:
            other.append(browse_id)

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        station = node.get("epgStationRenderer")
        if isinstance(station, dict):
            label = str(
                _dig(station, ("icon", "accessibility", "accessibilityData", "label"))
                or _text(station.get("title"))
                or _text(station.get("name"))
                or ""
            )
            if is_sports_hub_label(label):
                add(_browse_id_from(station), label)
        airing = node.get("epgAiringRenderer")
        if isinstance(airing, dict) and (
            _has_phrase(airing.get("tertiaryContainer"), "more live events")
            or _has_phrase(airing.get("primaryText"), "watch live sports")
        ):
            add(_browse_id_from(airing), extra=True)
        for value in node.values():
            walk(value)

    walk(payload)
    return extras + espn + other


KEEP_HUB_TABS = ("LIVE", "UPCOMING", "SCHEDULE", "EVENTS")


def discover_browse_tabs(payload: Any) -> list[dict[str, str | bool]]:
    found: list[dict[str, str | bool]] = []
    seen: set[tuple[str, str, str]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        tab = node.get("tabRenderer")
        if isinstance(tab, dict):
            title = _text(tab.get("title"))
            browse_id, params = _browse_request_from(tab)
            continuation = _tab_continuation(tab)
            key = (browse_id, params, continuation)
            if (browse_id or continuation) and key not in seen:
                seen.add(key)
                found.append(
                    {
                        "browse_id": browse_id,
                        "params": params,
                        "continuation": continuation,
                        "title": title,
                        "selected": bool(tab.get("selected")),
                    }
                )
        for value in node.values():
            walk(value)

    walk(payload)
    return found


CHIP_RENDERERS = (
    "chipCloudChipRenderer",
    "chipRenderer",
    "unpluggedChipCloudChipRenderer",
    "unpluggedFilterChipRenderer",
    "unpluggedChipRenderer",
)


def discover_sports_chips(payload: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in CHIP_RENDERERS:
            chip = node.get(key)
            if not isinstance(chip, dict):
                continue
            title = _text(chip.get("text") or chip.get("title") or chip.get("label"))
            if not is_sports_chip_title(title):
                continue
            browse_id, params = _browse_request_from(chip)
            key_id = (browse_id, params)
            if browse_id and key_id not in seen:
                seen.add(key_id)
                found.append({"browse_id": browse_id, "params": params, "title": title})
        for value in node.values():
            walk(value)

    walk(payload)
    return found


def keep_hub_tab(title: str) -> bool:
    if not title:
        return True
    upper = title.strip().upper()
    return any(token in upper for token in KEEP_HUB_TABS)


def _tab_continuation(tab: dict[str, Any]) -> str:
    for key in ("content", "endpoint", "continuationEndpoint"):
        nested = tab.get(key)
        if isinstance(nested, dict):
            token = _first_continuation(nested)
            if token:
                return token
    return _first_continuation(tab)


def _first_continuation(node: Any) -> str:
    found: list[str] = []
    skip = {
        "unpluggedVideoRenderer",
        "unpluggedGameCardRenderer",
        "epgAiringRenderer",
        "thumbnail",
        "menu",
        "onTap",
    }

    def walk(item: Any, depth: int = 0) -> None:
        if found or depth > 10 or not isinstance(item, (dict, list)):
            return
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
            return
        reload_data = item.get("reloadContinuationData")
        if isinstance(reload_data, dict) and isinstance(reload_data.get("continuation"), str):
            token = str(reload_data["continuation"])
            if len(token) > 20:
                found.append(token)
                return
        command = item.get("continuationCommand")
        if isinstance(command, dict) and isinstance(command.get("token"), str):
            token = str(command["token"])
            if len(token) > 20:
                found.append(token)
                return
        for key, value in item.items():
            if key in skip:
                continue
            walk(value, depth + 1)

    walk(node)
    return found[0] if found else ""


def _browse_request_from(node: dict[str, Any]) -> tuple[str, str]:
    for key in ("endpoint", "navigationEndpoint", "browseEndpoint", "command"):
        nested = node.get(key)
        if not isinstance(nested, dict):
            continue
        if key == "browseEndpoint" or "browseId" in nested:
            browse_id = nested.get("browseId")
            params = nested.get("params")
            if isinstance(browse_id, str) and browse_id:
                return browse_id, str(params) if isinstance(params, str) else ""
        found = _browse_request_from(nested)
        if found[0]:
            return found
    return "", ""


def _browse_id_from(node: dict[str, Any]) -> str:
    return _browse_request_from(node)[0]


def watch_deeplink(video_id: str, params: str = "") -> str:
    if not _ok_video_id(video_id):
        return ""
    url = f"https://tv.youtube.com/watch/{video_id}"
    encoded = _vp_query_value(params)
    if encoded:
        return f"{url}?vp={encoded}"
    return url


def _vp_query_value(params: str) -> str:
    text = (params or "").strip()
    if not text:
        return ""
    if "%" in text:
        return text
    return quote(text, safe="")


def _watch_endpoint_from_node(node: dict[str, Any]) -> Optional[dict[str, Any]]:
    watch = node.get("watchEndpoint")
    if isinstance(watch, dict) and _ok_video_id(watch.get("videoId")):
        return watch
    for key in ("navigationEndpoint", "command", "endpoint"):
        nested = node.get(key)
        if isinstance(nested, dict):
            found = _watch_endpoint_from_node(nested)
            if found:
                return found
    popup = node.get("unpluggedPopupEndpoint")
    if isinstance(popup, dict):
        found = _watch_endpoint_from_popup(popup)
        if found:
            return found
    return None


def _watch_endpoint_from_popup(node: Any) -> Optional[dict[str, Any]]:
    if isinstance(node, list):
        for item in node:
            found = _watch_endpoint_from_popup(item)
            if found:
                return found
        return None
    if not isinstance(node, dict):
        return None
    watch = node.get("watchEndpoint")
    if isinstance(watch, dict) and _ok_video_id(watch.get("videoId")):
        return watch
    items = node.get("items")
    if isinstance(items, list):
        found = _watch_endpoint_from_popup(items)
        if found:
            return found
    for key in (
        "unpluggedPopupEndpoint",
        "popupRenderer",
        "unpluggedSelectionMenuDialogRenderer",
        "unpluggedMenuItemRenderer",
        "command",
        "navigationEndpoint",
    ):
        nested = node.get(key)
        if nested is not None:
            found = _watch_endpoint_from_popup(nested)
            if found:
                return found
    return None


def _video_id_from_watch(watch: Optional[dict[str, Any]]) -> Optional[str]:
    if isinstance(watch, dict) and _ok_video_id(watch.get("videoId")):
        return str(watch["videoId"])
    return None


def _watch_params(watch: Optional[dict[str, Any]]) -> str:
    if not isinstance(watch, dict):
        return ""
    params = watch.get("params")
    return str(params) if isinstance(params, str) else ""


def _bare_video_id(node: dict[str, Any]) -> Optional[str]:
    direct = node.get("videoId")
    return str(direct) if _ok_video_id(direct) else None


def _video_id_from_node(node: dict[str, Any]) -> Optional[str]:
    found = _video_id_from_watch(_watch_endpoint_from_node(node))
    if found:
        return found
    return _bare_video_id(node)


def _ok_video_id(value: Any) -> bool:
    return isinstance(value, str) and bool(VIDEO_ID_RE.match(value))


def _artwork_from_node(node: dict[str, Any]) -> str:
    return _best_artwork(node)[1]


def _best_artwork(node: dict[str, Any]) -> tuple[int, str]:
    best: tuple[int, str] = (0, "")
    for item in _thumbnail_entries(node):
        url = _normalize_artwork_url(item.get("url"))
        if not url:
            continue
        score = _artwork_score(_positive_int(item.get("width")), _positive_int(item.get("height")))
        if score > best[0]:
            best = (score, url)
    return best


def _artwork_score(width: int, height: int) -> int:
    if width >= MIN_ARTWORK_WIDTH and (not height or width >= int(height * 1.2)):
        return POSTER_ARTWORK_SCORE + width
    if width >= MIN_FALLBACK_ARTWORK_WIDTH:
        return width
    return 0


def _thumbnail_entries(node: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for key in ("thumbnail", "primaryThumbnail"):
        value = node.get(key)
        if isinstance(value, dict):
            thumbs = value.get("thumbnails")
            if isinstance(thumbs, list):
                found.extend(item for item in thumbs if isinstance(item, dict))
            elif isinstance(value.get("url"), str):
                found.append(value)
        elif isinstance(value, list):
            found.extend(item for item in value if isinstance(item, dict))
    return found


def _normalize_artwork_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text.startswith("https://"):
        return ""
    host = urlparse(text).netloc.lower()
    if "ggpht.com" not in host and "googleusercontent.com" not in host:
        return ""
    return sized_artwork_url(text, ARTWORK_WIDTH, ARTWORK_HEIGHT)


def sized_artwork_url(url: str, width: int, height: int) -> str:
    text = (url or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text.startswith("https://"):
        return ""
    host = urlparse(text).netloc.lower()
    if "ggpht.com" not in host and "googleusercontent.com" not in host:
        return text
    base, sep, _params = text.partition("=")
    if not sep:
        base = text
    return f"{base}=w{width}-h{height}-p-ns-nd"


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _title_from_node(node: dict[str, Any]) -> str:
    for key in ("title", "headline", "overlayTitle", "primaryText", "label"):
        text = _text(node.get(key))
        if text:
            return text
    acc = _dig(node, ("accessibility", "accessibilityData", "label"))
    if isinstance(acc, str) and acc.strip() and not acc.strip().endswith(".png"):
        return acc.strip()
    return ""


def _station_from_node(node: dict[str, Any]) -> str:
    station = node.get("station")
    if isinstance(station, dict):
        renderer = station.get("epgStationRenderer") or station
        if isinstance(renderer, dict):
            label = _dig(renderer, ("icon", "accessibility", "accessibilityData", "label"))
            if isinstance(label, str) and label.strip() and not is_unusable_channel_label(label):
                cleaned = clean_station(label)
                if cleaned:
                    return cleaned
            text = _text(renderer.get("title")) or _text(renderer.get("name"))
            if text and not is_unusable_channel_label(text):
                cleaned = clean_station(text)
                if cleaned:
                    return cleaned
    for key in ("stationName", "networkName", "channelName"):
        text = _text(node.get(key))
        if text and not is_unusable_channel_label(text):
            cleaned = clean_station(text)
            if cleaned:
                return cleaned
    secondary = _text(node.get("secondaryText"))
    if secondary:
        found = _station_from_secondary(secondary, node)
        if found:
            return found
    return ""


def _station_from_secondary(secondary: str, node: dict[str, Any]) -> str:
    parts = [part.strip() for part in re.split(r"[•·|]", secondary) if part.strip()]
    usable = [part for part in parts if not is_unusable_channel_label(part)]
    for part in usable:
        if (
            is_espn_plus(part)
            or is_digital_extra(part)
            or is_extra_station(part)
            or is_sports_hub_label(part)
        ):
            cleaned = clean_station(part)
            if cleaned:
                return cleaned
    if is_espn_plus(secondary) or is_digital_extra(secondary):
        family = infer_channel(secondary)
        if family:
            return family
    if node.get("startTimeSeconds") is not None:
        for part in usable:
            cleaned = clean_station(part)
            if cleaned:
                return cleaned
    return ""


def _looks_like_schedule(text: str) -> bool:
    return is_unusable_channel_label(text)


def _is_live(node: dict[str, Any]) -> bool:
    if node.get("isLive") is True or node.get("live") is True:
        return True
    badge = node.get("badge")
    if isinstance(badge, dict):
        renderer = badge.get("unpluggedTextBadgeRenderer") or badge
        if isinstance(renderer, dict) and str(renderer.get("type") or "").upper() == "LIVE":
            return True
    text = " ".join(
        filter(
            None,
            [
                _text(node.get("badge")),
                _text(node.get("badges")),
                str(node.get("style") or ""),
            ],
        )
    ).upper()
    return "LIVE" in text and "UPCOMING" not in text


def _time_from_node(node: dict[str, Any], keys: tuple[str, ...]) -> Optional[datetime]:
    for key in keys:
        if key in node:
            parsed = _coerce_time(node.get(key))
            if parsed:
                return parsed
    return None


def _coerce_time(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:
            number /= 1000.0
        elif 1e11 < number <= 1e12:
            number /= 1000.0
        if number < MIN_UNIX_TS or number > MAX_UNIX_TS:
            return None
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.lstrip("-").isdigit():
            return _coerce_time(int(text))
        try:
            return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(filter(None, (_text(item) for item in value))).strip()
    if isinstance(value, dict):
        if "simpleText" in value:
            return str(value.get("simpleText") or "").strip()
        if "runs" in value and isinstance(value["runs"], list):
            return "".join(str(run.get("text") or "") for run in value["runs"] if isinstance(run, dict)).strip()
        if "label" in value:
            return _text(value.get("label"))
        if "accessibilityData" in value:
            return _text(value.get("accessibilityData"))
        if "accessibility" in value:
            return _text(value.get("accessibility"))
    return ""


def _dig(node: Any, path: tuple[str, ...]) -> Any:
    cur = node
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _has_phrase(node: Any, phrase: str) -> bool:
    needle = phrase.lower()
    if isinstance(node, str):
        return needle in node.lower()
    if isinstance(node, list):
        return any(_has_phrase(item, phrase) for item in node)
    if isinstance(node, dict):
        return any(_has_phrase(value, phrase) for value in node.values())
    return False
