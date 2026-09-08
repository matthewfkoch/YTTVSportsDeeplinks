from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import httpx

from yttv_epg.parse import Airing
from yttv_epg.sports import (
    MATCHUP_AT_RE,
    MATCHUP_VS_RE,
    infer_sport,
    is_studio_show,
    norm_name,
)

GRAPH_URL = "https://watch.graph.api.espn.com/api"
GRAPH_KEY = "0dbf88e8-cc6d-41da-aa83-18b5c630bc5c"
MATCH_WINDOW = timedelta(hours=3)
UPCOMING_DAYS = 5
PROTECTED_SPORTS = {"Tennis"}

AIRINGS_QUERY = (
    "query Airings($countryCode:String!,$deviceType:DeviceType!,$tz:String!,"
    "$type:AiringType,$day:String,$limit:Int){"
    "airings(countryCode:$countryCode,deviceType:$deviceType,tz:$tz,type:$type,day:$day,limit:$limit){"
    "name startDateTime endDateTime program{isStudio} sport{name} league{name} "
    "category{name} subcategory{name}"
    "}}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.espn.com",
    "Referer": "https://www.espn.com/watch/schedule/_/type/upcoming",
}

SPORT_ALIASES = {
    "NHRA": "Motorsports",
    "IMSA": "Motorsports",
    "HORSE RACING": "Horse Racing",
    "THOROUGHBRED": "Horse Racing",
    "MMA": "Combat",
    "BOXING": "Combat",
    "PRO WRESTLING": "Combat",
    "WRESTLING": "Combat",
    "TRACK & FIELD": "Track",
    "TRACK AND FIELD": "Track",
    "NHL": "Hockey",
    "NBA": "Basketball",
    "WNBA": "Basketball",
    "MLB": "Baseball",
    "NFL": "Football",
    "NCAAF": "Football",
    "NCAAM": "Basketball",
    "NCAAW": "Basketball",
}

LEAGUE_HINTS = (
    ("FIELD HOCKEY", "Field Hockey"),
    ("WATER POLO", "Water Polo"),
    ("VOLLEYBALL", "Volleyball"),
    ("DISC GOLF", "Disc Golf"),
    ("HORSE RACING", "Horse Racing"),
    ("LACROSSE", "Lacrosse"),
    ("SOFTBALL", "Softball"),
    ("GYMNASTICS", "Gymnastics"),
    ("RUGBY", "Rugby"),
    ("FOOTBALL", "Football"),
    ("SOCCER", "Soccer"),
    ("BASEBALL", "Baseball"),
    ("BASKETBALL", "Basketball"),
    ("HOCKEY", "Hockey"),
    ("TENNIS", "Tennis"),
    ("GOLF", "Golf"),
)

SKIP_SPORTS = {
    "ESPN THE OCHO",
    "SEC NOW",
    "SEC STORIED",
    "SPORTSCENTER",
    "SPORTSCENTER NOCHE",
    "SPORTSCENTER MEDIANOCHE",
    "30 FOR 30",
    "TRUESOUTH",
    "E60",
    "OTHERS",
    "GAMING",
    "CORNHOLE",
    "FISHING",
    "SPIKEBALL",
    "JAI ALAI",
    "AXE THROWING",
    "BULL RIDING",
    "ACTION SPORTS",
    "NCAA",
    "STUDIO",
}

SKIP_TITLE_HINTS = (
    "HALFTIME BAND",
    "SCOREBOARD",
    "PRESS CONFERENCE",
    "SPORTSCENTER",
    "SEC NOW",
)

TEAM_ALIASES = {
    "UALBANY": "ALBANY",
    "ALBANY": "ALBANY",
    "MIAMI OH": "MIAMI OHIO",
    "MIAMI OHIO": "MIAMI OHIO",
    "APP STATE": "APPALACHIAN STATE",
    "JMU": "JAMES MADISON",
    "REAL RACING": "RACING SANTANDER",
    "RACING SANTANDER": "RACING SANTANDER",
    "ST JOHNS": "ST JOHN S",
    "ST JOHN S": "ST JOHN S",
    "UT ARLINGTON": "UT ARLINGTON",
    "TEXAS ARLINGTON": "UT ARLINGTON",
}

SPANISH_PREFIX_RE = re.compile(r"^EN ESPA[NÑ]OL[-\s]*", re.I)
SKY_PREFIX_RE = re.compile(r"^(?:SKYCAST|SKYCAM\+)\s*[-:]\s*", re.I)
SKY_SUFFIX_RE = re.compile(r"\s*\((?:SKYCAST|SKYCAM\+)\)\s*$", re.I)
SEED_RE = re.compile(r"\(\d+\)\s*")
RANK_RE = re.compile(r"#\d+\s*")


@dataclass(frozen=True)
class EspnListing:
    name: str
    sport: str
    start: Optional[datetime] = None
    league: str = ""

    def teams(self) -> Optional[frozenset[str]]:
        return matchup_teams(self.name)


def upcoming_days(now: Optional[datetime] = None, count: int = UPCOMING_DAYS) -> list[str]:
    when = now or datetime.now(timezone.utc)
    local = when.astimezone(ZoneInfo("America/New_York")).date()
    return [(local + timedelta(days=offset)).isoformat() for offset in range(max(1, count))]


def espn_tz_param(now: Optional[datetime] = None) -> str:
    when = now or datetime.now(ZoneInfo("America/New_York"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("America/New_York"))
    offset = when.utcoffset() or timedelta(0)
    hours = int(offset.total_seconds() // 3600)
    sign = "-" if hours < 0 else "+"
    return f"UTC{sign}{abs(hours):02d}00"


def matchup_teams(title: str) -> Optional[frozenset[str]]:
    text = _strip_title(title)
    if not text:
        return None
    parts = MATCHUP_VS_RE.split(text, maxsplit=1)
    if len(parts) != 2:
        parts = MATCHUP_AT_RE.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    teams = {key for key in (_team_key(part) for part in parts) if key}
    if len(teams) != 2:
        return None
    return frozenset(teams)


def parse_airings_payload(payload: Any) -> list[EspnListing]:
    rows = _airing_rows(payload)
    listings: list[EspnListing] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        listing = _listing_from_row(row)
        if listing is None:
            continue
        teams = listing.teams()
        start_ts = int(listing.start.timestamp()) if listing.start else 0
        key = (teams or listing.name, listing.sport, start_ts)
        if key in seen:
            continue
        seen.add(key)
        listings.append(listing)
    return listings


async def fetch_espn_schedule(http: httpx.AsyncClient) -> list[EspnListing]:
    jobs = [_fetch_airings(http, "LIVE")]
    jobs.extend(_fetch_airings(http, "UPCOMING", day=day) for day in upcoming_days())
    found: list[EspnListing] = []
    results = await asyncio.gather(*jobs, return_exceptions=True)
    for payload in results:
        if isinstance(payload, Exception) or not isinstance(payload, dict):
            continue
        found.extend(parse_airings_payload(payload))
    return _dedupe_listings(found)


def _dedupe_listings(listings: Iterable[EspnListing]) -> list[EspnListing]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[EspnListing] = []
    for item in listings:
        teams = item.teams()
        start_ts = int(item.start.timestamp()) if item.start else 0
        key = (teams or item.name, item.sport, start_ts)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


async def _fetch_airings(
    http: httpx.AsyncClient,
    airing_type: str,
    day: Optional[str] = None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "deviceType": "DESKTOP",
        "countryCode": "US",
        "tz": espn_tz_param(),
        "type": airing_type,
        "limit": 1000,
    }
    if day:
        variables["day"] = day
    response = await http.post(
        GRAPH_URL,
        params={"apiKey": GRAPH_KEY, "features": "pbov7"},
        headers=HEADERS,
        json={"query": AIRINGS_QUERY, "variables": variables},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("ESPN schedule was not JSON")
    if payload.get("errors"):
        raise ValueError("ESPN schedule GraphQL error")
    return payload


def apply_espn_sports(
    airings: Iterable[Airing],
    listings: Iterable[EspnListing],
) -> list[Airing]:
    indexed = _index_listings(listings)
    labeled: list[Airing] = []
    for item in airings:
        sport = espn_sport_for(item, indexed)
        if sport and sport != item.sport:
            labeled.append(replace(item, sport=sport))
        else:
            labeled.append(item)
    return labeled


def espn_sport_for(
    airing: Airing,
    indexed: dict[frozenset[str], list[EspnListing]],
) -> Optional[str]:
    if is_studio_show(airing.title) or _skip_title(airing.title):
        return None
    teams = matchup_teams(airing.title)
    if not teams:
        return None
    candidates = indexed.get(teams) or []
    if not candidates:
        return None
    timed = [item for item in candidates if _within_window(airing.start, item.start)]
    if timed:
        best = min(timed, key=lambda item: _start_delta(airing.start, item.start))
        sport = best.sport
    else:
        sports = {item.sport for item in candidates}
        if len(sports) != 1:
            return None
        sport = next(iter(sports))
    current = airing.sport or infer_sport(airing.title, airing.station)
    if current in PROTECTED_SPORTS and sport != current:
        return None
    return sport


def _index_listings(
    listings: Iterable[EspnListing],
) -> dict[frozenset[str], list[EspnListing]]:
    indexed: dict[frozenset[str], list[EspnListing]] = {}
    for item in listings:
        teams = item.teams()
        if not teams:
            continue
        indexed.setdefault(teams, []).append(item)
    return indexed


def _listing_from_row(row: dict[str, Any]) -> Optional[EspnListing]:
    name = str(row.get("name") or row.get("shortName") or "").strip()
    if not name or _skip_title(name):
        return None
    program = row.get("program") if isinstance(row.get("program"), dict) else {}
    if program.get("isStudio"):
        return None
    sport = map_espn_sport(
        _nested_name(row.get("sport")),
        _nested_name(row.get("league")),
        _nested_name(row.get("category")),
        _nested_name(row.get("subcategory")),
    )
    if not sport:
        return None
    return EspnListing(
        name=name,
        sport=sport,
        start=_parse_dt(row.get("startDateTime")),
        league=_nested_name(row.get("league")),
    )


def map_espn_sport(*labels: str) -> str:
    blob = norm_name(" ".join(label for label in labels if label))
    if not blob or blob in SKIP_SPORTS:
        return ""
    for label in labels:
        alias = SPORT_ALIASES.get(norm_name(label), "")
        if alias:
            return alias
        cleaned = (label or "").strip()
        if cleaned in {
            "Football", "Soccer", "Tennis", "Volleyball", "Baseball", "Basketball",
            "Hockey", "Golf", "Rugby", "Field Hockey", "Water Polo", "Lacrosse",
            "Softball", "Gymnastics", "Swimming", "Track", "Cricket", "Disc Golf",
            "Horse Racing", "Motorsports", "Combat",
        }:
            return cleaned
    for hint, sport in LEAGUE_HINTS:
        if hint in blob:
            return sport
    return ""


def _airing_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("airings"), list):
        return data["airings"]
    if isinstance(payload.get("airings"), list):
        return payload["airings"]
    return []


def _nested_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    return str(value or "").strip()


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _strip_title(title: str) -> str:
    text = SPANISH_PREFIX_RE.sub("", title or "")
    text = SKY_PREFIX_RE.sub("", text)
    text = SKY_SUFFIX_RE.sub("", text)
    return text.strip()


def _team_key(name: str) -> str:
    text = norm_name(name)
    text = text.replace("(OH)", "OHIO").replace("(OHIO)", "OHIO")
    text = SEED_RE.sub("", text)
    text = RANK_RE.sub("", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return TEAM_ALIASES.get(text, text)


def _skip_title(title: str) -> bool:
    blob = norm_name(title)
    return any(hint in blob for hint in SKIP_TITLE_HINTS)


def _within_window(start: datetime, other: Optional[datetime]) -> bool:
    if other is None:
        return False
    return abs((start - other).total_seconds()) <= MATCH_WINDOW.total_seconds()


def _start_delta(start: datetime, other: Optional[datetime]) -> float:
    if other is None:
        return 10**12
    return abs((start - other).total_seconds())
