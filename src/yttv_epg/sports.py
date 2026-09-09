from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

MONTH_DAY_RE = re.compile(
    r"^(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\.?\s*\d{1,2}(?:,\s*\d{4})?$",
    re.I,
)
MATCHUP_VS_RE = re.compile(r"\s+vs\.?\s+", re.I)
MATCHUP_AT_RE = re.compile(r"\s+at\s+", re.I)
DAY_ONLY_RE = re.compile(r"^DAY\s+\d+$", re.I)
PAST_SEASON_RE = re.compile(r"^(20\d{2})(?:\s*:|\s+(?:NFC|AFC)\b)")

ESPN_PLUS_HINTS = (
    "ESPN+",
    "ESPN PLUS",
    "ESPN UNLIMITED",
)

DIGITAL_EXTRA_HINTS = ESPN_PLUS_HINTS + (
    "SEC+",
    "SEC PLUS",
    "ACC+",
    "ACC EXTRA",
    "ACC NETWORK EXTRA",
)

JUNK_TITLES = {
    "SIGN OFF",
    "OFF AIR",
    "PAID PROGRAMMING",
}

STUDIO_SHOW_HINTS = (
    "BEST OF",
    "INSIDE STUFF",
    "INSIDE THE NBA",
    "THIS WEEK",
    "STORIES",
    "SCOREBOARD",
    "POSTGAME",
    "PREGAME",
    "PRE MATCH",
    "PRE-MATCH",
    "PREMATCH",
    "MATCH PREVIEW",
    "SEASON PREVIEW",
    "GAMEDAY",
    "TOTAL ACCESS",
    "GOOD MORNING FOOTBALL",
    "COACHING LEGENDS",
    "DAN PATRICK",
    "GAME BREAK",
    "GOAL ZONE",
    "PRESS CONFERENCE",
    "GOLF CENTRAL",
    "GOLF TODAY",
    "COLLEGE FOOTBALL TODAY",
    "THE AMERICAN GAME",
    "HIGHLIGHTS",
    "COUNTDOWN",
    "30 FOR 30",
    "DOCUMENTARY",
    "MATCH POINT",
    "ESTA SEMANA",
    " EN 60",
    "HUDDLE",
)

MOVIE_AT_HINTS = (
    "NIGHT AT THE",
    "DAY AT THE MUSEUM",
    "LIVE AT ROCKPALAST",
    "LIVE AT WESTFALENHALLE",
)

SPORT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Field Hockey", ("FIELD HOCKEY",)),
    ("Volleyball", ("VOLLEYBALL",)),
    ("Water Polo", ("WATER POLO",)),
    ("Lacrosse", ("LACROSSE",)),
    ("Softball", ("SOFTBALL",)),
    ("Gymnastics", ("GYMNASTICS",)),
    ("Swimming", ("SWIMMING", "DIVING")),
    ("Track", ("TRACK & FIELD", "TRACK AND FIELD")),
    ("Rugby", ("RUGBY",)),
    ("Cricket", ("CRICKET",)),
    ("Fishing", ("FISHING", "ANGLING")),
    ("Disc Golf", ("DISC GOLF",)),
    ("Horse Racing", (
        "HORSE RACING",
        "THOROUGHBRED",
        "HARNESS RACING",
        "STEEPLECHASE",
        "KENTUCKY DOWNS",
        "KENTUCKY DERBY",
        "BREEDERS CUP",
        "BREEDERS' CUP",
        "PREAKNESS",
        "BELMONT STAKES",
        "TRIPLE CROWN",
        "SARATOGA",
        "CHURCHILL DOWNS",
        "KEENELAND",
        "SANTA ANITA",
        "GULFSTREAM",
        "DEL MAR",
        "NYRA",
        "AMERICA'S DAY AT THE RACES",
        "RACE DAY LIVE",
    )),
    ("Football", ("FOOTBALL", "NCAAF", "NFL", "WILD CARD", "SUPER BOWL", "COLLEGE GAMEDAY", "SEC NATION", "ACC HUDDLE")),
    ("Soccer", (
        "SOCCER",
        "MATCHDAY",
        "PREMIER LEAGUE",
        "LA LIGA",
        "LIGA MX",
        "MLS",
        "EFL",
        "SERIE A",
        "BUNDESLIGA",
        "EREDIVISIE",
        "USL",
        "CHAMPIONS LEAGUE",
        "LIGUE 1",
        "FA CUP",
        "3. LIGA",
        "LA LIGA 2",
        "LIGA PORTUGAL",
        "NWSL",
        "CONCACAF",
        "WORLD CUP",
        "FC",
        "CF",
    )),
    ("Basketball", ("BASKETBALL", "NBA", "WNBA", "NCAAM", "NCAAW")),
    ("Baseball", ("BASEBALL", "MLB")),
    ("Hockey", ("HOCKEY", "NHL")),
    ("Tennis", ("TENNIS", "ATP", "WTA", "U.S. OPEN", "US OPEN")),
    ("Golf", ("GOLF", "PGA", "LPGA")),
    ("Motorsports", (
        "NASCAR",
        "INDYCAR",
        "INDY 500",
        "FORMULA 1",
        "FORMULA ONE",
        "FORMULA E",
        "F1",
        "MOTORSPORT",
        "MOTOR SPORTS",
        "AUTO RACING",
        "MOTOGP",
        "MOTO GP",
        "NHRA",
        "IMSA",
        "SUPERCROSS",
        "MOTOCROSS",
        "LE MANS",
        "GRAND PRIX",
        "CUP SERIES",
        "XFINITY",
        "TRUCK SERIES",
        "DRAG RACING",
        "STOCK CAR",
        "DARLINGTON",
        "PRACTICE & QUALIFYING",
    )),
    ("Combat", ("UFC", "MMA", "BOXING", "WWE", "WRESTLING", "SLIPPERY STAIRS")),
    ("Studio", ("SPORTSCENTER", "SCOREBOARD", "GAMEDAY", "STUDIO")),
)

SPORTS_HUB_STATIONS = {
    "ACC NETWORK",
    "BTN",
    "BTN OVERFLOW 1",
    "CBS SPORTS NETWORK",
    "ESPN",
    "ESPN2",
    "ESPNU",
    "ESPNEWS",
    "ESPN DEPORTES",
    "FOX SPORTS 1",
    "FOX SPORTS 2",
    "FS1",
    "FS2",
    "FOX SPORTS 4K",
    "GOLF CHANNEL",
    "MLB NETWORK",
    "NBA TV",
    "NBC SPORTS 4K",
    "NBC SPORTS EXTRA",
    "NBC SPORTS NETWORK",
    "NBCSN EXTRA",
    "NFL NETWORK",
    "NHL NETWORK",
    "SEC NETWORK",
    "TENNIS CHANNEL",
    "TUDN",
}

SOCCER_STATION_HINTS = (
    "NBCSN",
    "NBC SPORTS",
    "TUDN",
    "TELEMUNDO",
    "UNIVISION",
    "UNIVISIÓN",
    "USA",
    "GOLAZO",
)

FOOTBALL_AT_STATION_HINTS = (
    "ABC",
    "ACC NETWORK",
    "BTN",
    "BIG TEN",
    "CBS",
    "CW",
    "ESPN",
    "ESPN2",
    "ESPNU",
    "ESPNEWS",
    "FOX",
    "FS1",
    "FS2",
    "NBC",
    "SEC NETWORK",
    "THEGRIO",
    "THE GRIO",
    "TNT",
    "TRUTV",
    "USA",
    "USA NETWORK",
)

TENNIS_ROUND_RE = re.compile(
    r"\b(?:women'?s|men'?s|mixed)\s+"
    r"(?:singles|doubles|first round|second round|third round|fourth round|"
    r"round of \d+|quarter-?finals?|semi-?finals?|finals?)\b",
    re.I,
)
TENNIS_SEED_RE = re.compile(r"\(\d{1,2}\)\s+\S.+\s+vs", re.I)
TENNIS_DOUBLES_RE = re.compile(r"\b[\w'.-]+/[\w'.-]+\s+vs", re.I)
TENNIS_COURT_RE = re.compile(r"^COURT\s+\d+$", re.I)

HOCKEY_NATIONS = ("CZECHIA", "CZECH REPUBLIC", "FINLAND", "SWEDEN", "SLOVAKIA")
HOCKEY_NATION_STATIONS = ("TRUTV", "TRU TV", "TNT", "NHL NETWORK")

MLB_TEAMS = (
    "YANKEES", "RED SOX", "BLUE JAYS", "ORIOLES", "RAYS", "WHITE SOX", "GUARDIANS",
    "TIGERS", "ROYALS", "TWINS", "ASTROS", "ATHLETICS", "ANGELS",
    "MARINERS", "BRAVES", "PHILLIES", "METS", "MARLINS", "NATIONALS", "BREWERS",
    "CUBS", "REDS", "PIRATES", "DODGERS", "PADRES", "DIAMONDBACKS", "ROCKIES",
    "TEXAS RANGERS", "ST. LOUIS CARDINALS", "ST LOUIS CARDINALS", "SAN FRANCISCO GIANTS",
)

NFL_TEAMS = (
    "BILLS", "DOLPHINS", "PATRIOTS", "RAVENS", "BENGALS", "BROWNS", "STEELERS",
    "TEXANS", "COLTS", "JAGUARS", "TITANS", "BRONCOS", "CHIEFS", "RAIDERS", "CHARGERS",
    "COWBOYS", "EAGLES", "COMMANDERS", "BEARS", "LIONS", "PACKERS", "VIKINGS",
    "FALCONS", "PANTHERS", "SAINTS", "BUCCANEERS", "49ERS", "SEAHAWKS", "RAMS",
    "NEW YORK GIANTS", "NEW YORK JETS", "ARIZONA CARDINALS",
)

NBA_TEAMS = (
    "LAKERS", "CELTICS", "KNICKS", "NETS", "76ERS", "BULLS", "CAVALIERS", "PISTONS",
    "PACERS", "BUCKS", "HAWKS", "HORNETS", "HEAT", "MAGIC", "WIZARDS", "NUGGETS",
    "TIMBERWOLVES", "THUNDER", "TRAIL BLAZERS", "JAZZ", "WARRIORS", "CLIPPERS",
    "SUNS", "MAVERICKS", "ROCKETS", "GRIZZLIES", "PELICANS", "SPURS", "RAPTORS",
)

NHL_TEAMS = (
    "BRUINS", "MAPLE LEAFS", "CANADIENS", "SABRES", "RED WINGS", "BLACKHAWKS",
    "NEW YORK RANGERS", "ISLANDERS", "DEVILS", "FLYERS", "CAPITALS", "PENGUINS", "HURRICANES",
    "BLUE JACKETS", "LIGHTNING", "PREDATORS", "STARS", "AVALANCHE",
    "WILD", "WINNIPEG JETS", "GOLDEN KNIGHTS", "KRAKEN", "SHARKS", "DUCKS",
    "FLAMES", "OILERS", "CANUCKS",
)

SOCCER_CLUBS = (
    "INTERNAZIONALE", "NAPOLI", "GIRONA", "VALLECANO", "GIJON", "GIJÓN",
    "SPORTING GIJON", "SPORTING GIJÓN", "REAL RACING", "BAYERN", "BORUSSIA",
    "ARSENAL", "CHELSEA", "LIVERPOOL", "TOTTENHAM", "WEST HAM", "ASTON VILLA",
    "MANCHESTER CITY", "MANCHESTER UNITED", "REAL MADRID", "BARCELONA",
    "ATLETICO", "ATLÉTICO", "JUVENTUS", "AC MILAN", "INTER MILAN", "ROMA",
    "ATALANTA", "PSG", "AJAX", "PUMAS", "CHIVAS", "AMERICA", "AMÉRICA", "PUEBLA",
    "BOURNEMOUTH", "BRENTFORD", "BRIGHTON", "CRYSTAL PALACE", "IPSWICH",
    "LEEDS UNITED", "HULL CITY", "SCHALKE", "GIRONA FC",
    "VILLARREAL", "DEPORTIVO DE LA CORUNA", "LA CORUNA", "MALLORCA", "ELDENSE",
)

CFB_TEAMS = (
    "ALABAMA", "AUBURN", "CLEMSON", "LSU", "FLORIDA", "GEORGIA", "TENNESSEE",
    "KENTUCKY", "SOUTH CAROLINA", "ARKANSAS", "MISSOURI", "TEXAS", "OKLAHOMA",
    "TEXAS A&M", "TEXAS AM", "OHIO STATE", "MICHIGAN", "PENN STATE", "OREGON",
    "WASHINGTON", "USC", "UCLA", "NOTRE DAME", "MIAMI", "FLORIDA STATE",
    "NORTH CAROLINA", "NC STATE", "DUKE", "VIRGINIA", "VIRGINIA TECH", "PITTSBURGH",
    "SYRACUSE", "LOUISVILLE", "WAKE FOREST", "BOSTON COLLEGE", "CAL", "STANFORD",
    "WISCONSIN", "IOWA", "MINNESOTA", "NEBRASKA", "ILLINOIS", "INDIANA", "PURDUE",
    "NORTHWESTERN", "MICHIGAN STATE", "RUTGERS", "MARYLAND", "BAYLOR", "TCU",
    "OKLAHOMA STATE", "KANSAS", "KANSAS STATE", "IOWA STATE", "WEST VIRGINIA",
    "CINCINNATI", "UCF", "HOUSTON", "BYU", "COLORADO", "UTAH", "ARIZONA",
    "ARIZONA STATE", "ALABAMA", "AUBURN", "OLE MISS", "MISSISSIPPI STATE",
    "VANDERBILT", "SOUTH FLORIDA", "SMU", "MEMPHIS", "TULANE", "NAVY", "ARMY",
    "AIR FORCE", "TROY", "APPALACHIAN STATE", "COASTAL CAROLINA", "JAMES MADISON",
    "LIBERTY", "MARSHALL", "WESTERN KENTUCKY", "BOISE STATE", "FRESNO STATE",
    "SAN DIEGO STATE", "UNLV", "COLORADO STATE", "WYOMING", "NEVADA", "UTAH STATE",
    "AIR FORCE", "HAWAII", "SAN JOSE STATE", "NEW MEXICO", "EAST CAROLINA",
    "TULSA", "RICE", "UTSA", "NORTH TEXAS", "TEXAS STATE", "SOUTH ALABAMA",
    "SOUTHERN MISS", "LOUISIANA", "TEXAS TECH", "OREGON STATE", "WASHINGTON STATE",
    "BALL STATE", "TOLEDO", "OHIO", "MIAMI (OHIO)", "MIAMI OHIO", "BOWLING GREEN",
    "WESTERN MICHIGAN", "CENTRAL MICHIGAN", "EASTERN MICHIGAN", "NORTHERN ILLINOIS",
    "KENT STATE", "AKRON", "BUFFALO", "UMASS", "UCONN", "TEMPLE", "GEORGIA TECH",
    "WAKE FOREST", "CLEMSON", "FLORIDA ATLANTIC", "FIU", "CHARLOTTE", "OLD DOMINION",
    "GEORGIA SOUTHERN", "GEORGIA STATE", "COASTAL CAROLINA", "APP STATE",
    "JACKSONVILLE STATE", "SAM HOUSTON", "KENNESAW",
    "NEW HAMPSHIRE", "SACRED HEART", "HARVARD", "YALE", "PRINCETON", "DARTMOUTH",
    "BROWN", "CORNELL", "PENN", "COLUMBIA", "HOLY CROSS", "LEHIGH", "LAFAYETTE",
    "FORDHAM", "GEORGETOWN", "COLGATE", "BUCKNELL", "ELON", "TOWSON", "JAMES MADISON",
    "WILLIAM & MARY", "VILLANOVA", "DELAWARE", "RICHMOND", "MAINE", "ALBANY",
    "STONY BROOK", "URI", "RHODE ISLAND", "MONMOUTH", "CAMPBELL", "BRYANT",
    "DUQUESNE", "ROBERT MORRIS", "WAGNER", "LIU", "CENTRAL CONNECTICUT",
    "MERRIMACK", "STONEHILL", "IDAHO STATE", "WEBER STATE", "MONTANA", "MONTANA STATE",
    "NORTH DAKOTA STATE", "SOUTH DAKOTA STATE", "SOUTH DAKOTA", "NORTH DAKOTA",
    "NORTHERN IOWA", "SOUTHERN ILLINOIS", "ILLINOIS STATE", "YOUNGSTOWN STATE",
    "NORTH ALABAMA", "NORTH CAROLINA CENTRAL", "TEXAS SOUTHERN", "ALCORN STATE",
    "PRAIRIE VIEW", "GRAMBLING", "JACKSON STATE", "FLORIDA A&M", "HOWARD",
    "NORFOLK STATE", "MORGAN STATE", "DELAWARE STATE", "SOUTH CAROLINA STATE",
    "NORTH CAROLINA A&T", "BETHUNE-COOKMAN", "ABILENE CHRISTIAN", "STEPHEN F AUSTIN",
    "TARLETON", "UT ARLINGTON", "UTAH STATE", "OKLAHOMA STATE", "KENTUCKY",
    "BOISE STATE", "OREGON", "CINCINNATI", "PENN STATE", "NEBRASKA", "INDIANA",
    "IOWA", "NORTHWESTERN", "ARKANSAS", "SOUTH CAROLINA", "LSU", "CLEMSON",
    "AUBURN", "ALABAMA", "TEXAS", "HOUSTON", "TULSA", "NAVY", "ARMY", "DUKE",
    "SYRACUSE", "PITTSBURGH", "WEST VIRGINIA", "COASTAL CAROLINA",
)

CHANNEL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ESPN+", ("ESPN+", "ESPN PLUS", "ESPN UNLIMITED", "ES • ESPN+")),
    ("NBC Sports Extra", ("NBCSN EXTRA", "NBC SPORTS EXTRA")),
    ("Big Ten Extra", ("BTN OVERFLOW", "BIG TEN PLUS", "BIG TEN EXTRA", "B1G+")),
    ("ACC Extra", ("ACC NETWORK EXTRA", "ACC EXTRA", "ACC+")),
    ("SEC+", ("SEC+", "SEC PLUS")),
    ("CBS Sports Extra", ("CBSSN EXTRA", "CBS SPORTS EXTRA")),
    ("Fox Sports Extra", ("FS1 EXTRA", "FS2 EXTRA", "FOX SPORTS EXTRA")),
    ("ESPN", ("ESPN2", "ESPNU", "ESPNEWS", "ESPN DEPORTES", "ESPN")),
    ("Fox Sports", ("FOX SPORTS 1", "FOX SPORTS 2", "FOX SPORTS 4K", "FS1", "FS2")),
    ("NBC Sports", ("NBC SPORTS NETWORK", "NBC SPORTS 4K", "NBCSN")),
    ("Big Ten", ("BIG TEN", "BTN")),
    ("CBS Sports", ("CBS SPORTS", "CBSSN")),
    ("ACC Network", ("ACC NETWORK", "ACCN")),
    ("SEC Network", ("SEC NETWORK", "SECN")),
    ("NFL Network", ("NFL NETWORK", "NFL REDZONE", "NFL RED ZONE")),
    ("NBA TV", ("NBA TV",)),
    ("MLB Network", ("MLB NETWORK",)),
    ("NHL Network", ("NHL NETWORK",)),
    ("Golf Channel", ("GOLF CHANNEL",)),
    ("Tennis Channel", ("TENNIS CHANNEL",)),
    ("TUDN", ("TUDN", "UNIVISION", "TELEMUNDO")),
    ("NBC", ("NBC",)),
    ("CBS", ("CBS",)),
    ("ABC", ("ABC",)),
    ("FOX", ("FOX",)),
    ("TNT", ("TNT",)),
    ("TBS", ("TBS",)),
    ("USA", ("USA NETWORK", "USA")),
)


def norm_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("®", "").strip().upper())


def is_espn_plus(station: str, title: str = "") -> bool:
    blob = norm_name(f"{station} {title}")
    return any(hint in blob for hint in ESPN_PLUS_HINTS)


def is_digital_extra(station: str, title: str = "") -> bool:
    blob = norm_name(f"{station} {title}")
    if any(hint in blob for hint in DIGITAL_EXTRA_HINTS):
        return True
    return is_extra_station(station)


def is_extra_station(station: str) -> bool:
    label = f" {norm_name(station)} "
    if "OVERFLOW" in label:
        return True
    if " EXTRA" in label or label.strip().endswith("EXTRA"):
        return True
    return False


def is_sports_hub_label(station: str) -> bool:
    label = norm_name(station)
    if not label:
        return False
    if is_extra_station(label):
        return True
    if label in SPORTS_HUB_STATIONS:
        return True
    if "ESPN" in label or "SPORTS" in label or "DEPORTES" in label:
        return True
    return False


def parse_sport_list(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def is_junk(title: str, station: str = "") -> bool:
    title_u = norm_name(title)
    if not title_u or title_u in JUNK_TITLES:
        return True
    if "WATCH LIVE SPORTS" in title_u or title_u.startswith("WATCH ON "):
        return True
    if "NEWS AT" in title_u or re.search(r"\bNEWS\b", title_u):
        return True
    if re.search(r"\bRADIO\b", title_u):
        return True
    past = PAST_SEASON_RE.match(title_u)
    if past and int(past.group(1)) < datetime.now(timezone.utc).year:
        return True
    station_u = norm_name(station)
    if station_u and title_u == station_u and not is_matchup(title):
        return True
    return False


def is_matchup(title: str) -> bool:
    if not title:
        return False
    if MATCHUP_VS_RE.search(title):
        return True
    if not MATCHUP_AT_RE.search(title):
        return False
    upper = norm_name(title)
    return not any(hint in upper for hint in MOVIE_AT_HINTS)


def infer_channel(station: str, title: str = "") -> str:
    station_pad = f" {norm_name(station)} "
    combined = f" {norm_name(station)} {norm_name(title)} "
    for blob in (station_pad, combined):
        if not blob.strip():
            continue
        for name, hints in CHANNEL_RULES:
            if any(_channel_hint_match(blob, hint) for hint in hints):
                return name
    station_label = clean_station(station)
    if station_label:
        return station_label
    return ""


def _channel_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("®", "").strip())


def is_unusable_channel_label(label: str) -> bool:
    text = _channel_label(label)
    if not text:
        return False
    padded = f" {norm_name(text)} "
    if any(token in padded for token in (" AM ", " PM ", " TODAY ", " TOMORROW ", " MIN LEFT ", " STARTS ")):
        return True
    if "SEASON PREVIEW" in padded:
        return True
    return bool(MONTH_DAY_RE.match(text))


def clean_station(station: str, title: str = "") -> str:
    _ = title
    label = _channel_label(station)
    if not label or is_unusable_channel_label(label) or is_studio_show(label):
        return ""
    if norm_name(label) == "ES":
        return "ESPN+"
    return label


def _channel_hint_match(padded: str, hint: str) -> bool:
    token = f" {hint} "
    if token in padded:
        return True
    if hint.endswith("+") and hint in padded:
        return True
    return False


def event_channel(item: Any) -> str:
    title = getattr(item, "title", "") or ""
    station = clean_station(getattr(item, "station", "") or "", title)
    channel = getattr(item, "channel", "") or ""
    if channel in {"Other", "Other extras"} or is_unusable_channel_label(channel) or is_studio_show(channel):
        channel = ""
    if channel and channel == title:
        channel = ""
    if channel:
        return infer_channel(channel, title) or channel
    return infer_channel(station, title)


def is_vs_matchup(title: str) -> bool:
    return bool(title and MATCHUP_VS_RE.search(title))


def is_at_matchup(title: str) -> bool:
    return bool(is_matchup(title) and MATCHUP_AT_RE.search(title) and not is_vs_matchup(title))


def infer_sport(title: str, station: str = "", shelf: str = "") -> str:
    blob = norm_name(f"{shelf} {station} {title}")
    padded = f" {blob} "
    for sport, hints in SPORT_RULES:
        if any(_sport_hint_match(padded, hint) for hint in hints):
            return sport
    if _looks_like_tennis(title):
        return "Tennis"
    if _international_hockey(title, station):
        return "Hockey"
    if DAY_ONLY_RE.match(norm_name(title)):
        # NBC Sports /watch/schedule has no extras API. NBCSN Extra "Day N"
        # cards this meet are Kentucky Downs (Days 4/6). Keep the row.
        family = infer_channel(station, title)
        if family in {"NBC Sports Extra", "NBC Sports"} or "NBCSN" in norm_name(station):
            return "Horse Racing"
    title_pad = f" {norm_name(title)} "
    if is_matchup(title):
        if _has_team(title_pad, MLB_TEAMS):
            return "Baseball"
        if _has_team(title_pad, NBA_TEAMS):
            return "Basketball"
        if _has_team(title_pad, NHL_TEAMS):
            return "Hockey"
        if _has_team(title_pad, SOCCER_CLUBS):
            return "Soccer"
        if _has_team(title_pad, NFL_TEAMS):
            return "Football"
    if is_vs_matchup(title) and any(token in blob for token in SOCCER_STATION_HINTS):
        return "Soccer"
    if is_at_matchup(title) and _football_at_station(station):
        return "Football"
    if (
        is_vs_matchup(title)
        and _football_vs_station(station)
        and _has_team(padded, CFB_TEAMS)
    ):
        return "Football"
    if is_matchup(title):
        return "Other"
    return "Other"


def resolve_sport(title: str, station: str = "", stored: str = "", shelf: str = "") -> str:
    inferred = infer_sport(title, station, shelf)
    stored_ok = stored not in {"", "Other", "Studio"}
    if inferred == "Other":
        return stored if stored_ok else inferred
    if stored_ok and inferred in {"Football", "Soccer"} and stored != inferred:
        return stored
    return inferred


def _looks_like_tennis(title: str) -> bool:
    if TENNIS_COURT_RE.match(norm_name(title)):
        return True
    if TENNIS_ROUND_RE.search(title or ""):
        return True
    if TENNIS_SEED_RE.search(title or ""):
        return True
    if TENNIS_DOUBLES_RE.search(title or ""):
        return True
    return False


def _international_hockey(title: str, station: str) -> bool:
    if not is_vs_matchup(title):
        return False
    blob = norm_name(title)
    if not any(nation in blob for nation in HOCKEY_NATIONS):
        return False
    padded = f" {norm_name(station)} "
    return any(f" {hint} " in padded for hint in HOCKEY_NATION_STATIONS)


def _has_team(padded: str, teams: tuple[str, ...]) -> bool:
    return any(f" {team} " in padded for team in teams)


def _football_at_station(station: str) -> bool:
    padded = f" {norm_name(station)} "
    return any(f" {hint} " in padded for hint in FOOTBALL_AT_STATION_HINTS)


def _football_vs_station(station: str) -> bool:
    if is_espn_plus(station) or is_extra_station(station):
        return False
    return _football_at_station(station)


def _sport_hint_match(padded: str, hint: str) -> bool:
    token = hint.strip()
    compact = token.replace(".", "").replace(" ", "")
    if len(compact) <= 4 and compact.isalnum():
        return f" {token} " in padded or f" {compact} " in padded
    return token in padded


# Exact labels for short or punctuation-heavy nets. Longer brands use NON_SPORTS_FAMILIES.
NON_SPORTS_STATIONS = {
    "A&E",
    "AETV",
    "AMC",
    "AWE",
    "BET",
    "BRAVO",
    "CHARGE",
    "CHARGE!",
    "CHEDDAR",
    "CMT",
    "CNBC",
    "CNN",
    "COMET",
    "COMET TV",
    "COZI",
    "COZI TV",
    "DABL",
    "DIY",
    "E!",
    "FX",
    "FXM",
    "FXX",
    "FYI",
    "GSN",
    "HGTV",
    "HLN",
    "HSN",
    "ID",
    "IFC",
    "LOGO",
    "MSNBC",
    "MS NOW",
    "MSNOW",
    "MTV",
    "NECN",
    "OAN",
    "OANN",
    "OWN",
    "OXYGEN",
    "PBS",
    "POP",
    "QVC",
    "ROAR",
    "SYFY",
    "TCM",
    "TLC",
    "TV LAND",
    "TYT",
    "VH1",
    "WE TV",
    "WETV",
}

# Word-boundary tokens so short names do not match inside sports labels.
NON_SPORTS_TOKENS = {
    "AMC",
    "AWE",
    "BET",
    "CMT",
    "CNN",
    "DIY",
    "FX",
    "FYI",
    "GSN",
    "HLN",
    "HSN",
    "ID",
    "IFC",
    "MTV",
    "OAN",
    "OWN",
    "PBS",
    "POP",
    "QVC",
    "ROAR",
    "TCM",
    "TLC",
    "TYT",
    "VH1",
}

# Substrings for a whole network family (Nat Geo *, C-SPAN2, Oxygen True Crime, Recipe.TV, …).
NON_SPORTS_FAMILIES = (
    "HALLMARK",
    "BBC AMERICA",
    "BBC NEWS",
    "BBC WORLD",
    "BBC EARTH",
    "NATIONAL GEOGRAPHIC",
    "NAT GEO",
    "NATGEO",
    "C-SPAN",
    "CSPAN",
    "C SPAN",
    "FOX NEWS",
    "FOX BUSINESS",
    "FOX WEATHER",
    "FOX SOUL",
    "ONE AMERICA NEWS",
    "NEWSMAX",
    "NEWSNATION",
    "NEWS NATION",
    "MSNBC",
    "MS NOW",
    "CNBC",
    "BLOOMBERG",
    "CHEDDAR",
    "WEATHER CHANNEL",
    "WEATHER",
    "LIVENOW",
    "LIVE NOW",
    "COURT TV",
    "LAW & CRIME",
    "LAW AND CRIME",
    "GAME SHOW",
    "COMEDY",
    "PARAMOUNT NETWORK",
    "OXYGEN",
    "BRAVO",
    "LIFETIME",
    "FREEFORM",
    "CARTOON NETWORK",
    "ADULT SWIM",
    "BOOMERANG",
    "DISNEY",
    "NICKELODEON",
    "NICK JR",
    "NICKTOONS",
    "TEENNICK",
    "COMET",
    "MAGNOLIA",
    "HGTV",
    "FOOD NETWORK",
    "COOKING",
    "RECIPE",
    "TASTEMADE",
    "TRAVEL CHANNEL",
    "INVESTIGATION DISCOVERY",
    "ANIMAL PLANET",
    "SMITHSONIAN",
    "DISCOVERY",
    "HISTORY",
    "BRAINERD",
    "GREAT AMERICAN",
    "THE NEST",
    "START TV",
    "TV LAND",
    "BET HER",
    "SYFY",
    "SUNDANCE",
    "LOCAL NOW",
    "LOCALISH",
    "ABC NEWS",
    "NBC NEWS",
    "CBS NEWS",
    "A&E",
    "E!",
    "QVC",
    "HSN",
    "SHOP LC",
    "SHOPHQ",
    "DABL",
    "COZI",
)

LINEAR_CHANNEL_FAMILIES = {
    "ABC",
    "ACC Network",
    "Big Ten",
    "CBS",
    "CBS Sports",
    "ESPN",
    "FOX",
    "Fox Sports",
    "Golf Channel",
    "MLB Network",
    "NBA TV",
    "NBC",
    "NBC Sports",
    "NFL Network",
    "NHL Network",
    "SEC Network",
    "TBS",
    "Tennis Channel",
    "TNT",
    "TUDN",
    "USA",
}

EXTRA_CHANNEL_FAMILIES = {
    "ACC Extra",
    "Big Ten Extra",
    "CBS Sports Extra",
    "ESPN+",
    "Fox Sports Extra",
    "NBC Sports Extra",
    "SEC+",
}


def _compact_station(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value)


NON_SPORTS_COMPACT = {
    _compact_station(name) for name in NON_SPORTS_STATIONS if len(_compact_station(name)) >= 3
}


def is_non_sports_station(station: str) -> bool:
    label = norm_name(station)
    if not label:
        return False
    # Extras and sports hubs (ESPNews, Fox Sports, NFL Network) stay in the guide.
    if is_sports_hub_label(label):
        return False
    compact = _compact_station(label)
    spaced = re.sub(r"[^A-Z0-9]+", " ", label).strip()
    padded = f" {spaced} "
    if label in NON_SPORTS_STATIONS or compact in NON_SPORTS_COMPACT:
        return True
    if any(f" {token} " in padded for token in NON_SPORTS_TOKENS):
        return True
    for family in NON_SPORTS_FAMILIES:
        if family in label or family in spaced:
            return True
        key = _compact_station(family)
        if len(key) >= 4 and key in compact:
            return True
    if "NEWS" in padded or "NEWS" in compact:
        return True
    return False


def is_studio_show(title: str) -> bool:
    blob = norm_name(title)
    if not blob:
        return False
    return any(hint in blob for hint in STUDIO_SHOW_HINTS)


def is_sports_event(station: str, title: str, sport: str = "", tab: str = "") -> bool:
    if is_junk(title, station) or is_non_sports_station(station) or is_studio_show(title):
        return False
    own_sport = infer_sport(title, station)
    if own_sport == "Studio":
        return False
    if is_extra_station(station) or is_digital_extra(station, title):
        return True
    if is_matchup(title):
        return True
    if own_sport and own_sport not in {"", "Other"}:
        return True
    tab_u = (tab or "").strip().upper()
    if tab_u in {"LIVE", "UPCOMING", "SCHEDULE", "EVENTS"} and sport and sport not in {"", "Other"}:
        return True
    if is_sports_hub_label(station) and sport and sport not in {"", "Other", "Studio"}:
        return True
    return False


def outlet_rank(station: str, title: str = "", channel: str = "") -> int:
    family = channel or infer_channel(station, title)
    if family == "ESPN+" or is_espn_plus(station, title):
        return 4
    if family in EXTRA_CHANNEL_FAMILIES or is_extra_station(station):
        return 3
    if family in LINEAR_CHANNEL_FAMILIES:
        return 0
    return 1


def has_watch_link(item: Any) -> bool:
    method = getattr(item, "watch_id", None)
    if callable(method):
        return bool(method())
    deeplink = str(getattr(item, "deeplink", "") or "")
    return "/watch/" in deeplink


def visible_events(
    events: Iterable[Any],
    hidden: Iterable[str] = (),
    hidden_channels: Iterable[str] = (),
    *,
    require_watch_link: bool = False,
) -> list[Any]:
    blocked_sports = {item for item in hidden if item}
    blocked_channels = {item for item in hidden_channels if item}
    visible: list[Any] = []
    for item in events:
        if require_watch_link and not has_watch_link(item):
            continue
        title = getattr(item, "title", "") or ""
        station = getattr(item, "station", "") or ""
        channel = getattr(item, "channel", "") or ""
        if title and not is_sports_event(station, title, getattr(item, "sport", "") or ""):
            continue
        if is_non_sports_station(station) or is_non_sports_station(channel):
            continue
        sport = getattr(item, "sport", None) or "Other"
        if sport in blocked_sports:
            continue
        if event_channel(item) in blocked_channels:
            continue
        visible.append(item)
    return visible


def sport_counts(events: Iterable[Any]) -> list[dict[str, int | str]]:
    counts = Counter(getattr(item, "sport", None) or "Other" for item in events)
    return [
        {"name": name, "count": count}
        for name, count in sorted(
            counts.items(),
            key=lambda pair: (pair[0] == "Other", -pair[1], pair[0]),
        )
    ]


def channel_counts(events: Iterable[Any]) -> list[dict[str, int | str]]:
    counts = Counter(name for name in (event_channel(item) for item in events) if name)
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


def toggle_name(current: list[str], name: str) -> list[str]:
    if name in current:
        return [item for item in current if item != name]
    return current + [name]
