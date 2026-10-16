"""Station identity and optional broadcaster-logo overrides."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


def station_key(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def load_station_logos(path: Path) -> dict[str, str]:
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("expected an object mapping station names to URLs")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Cannot load station logo overrides from %s: %s", path, exc)
        return {}
    logos: dict[str, str] = {}
    for name, value in values.items():
        try:
            url = value.strip() if isinstance(value, str) else ""
            parts = urlsplit(url)
            valid = (
                station_key(name) and parts.scheme in {"http", "https"}
                and parts.hostname and not any(c.isspace() for c in url)
            )
        except ValueError:
            valid = False
        if not valid:
            log.warning("Ignoring invalid station logo override for %r", name)
            continue
        logos[station_key(name)] = url
    return logos


BUNDLED_LOGOS = {
    "espn": "espn", "espn2": "espn2", "espnu": "espnu", "espnews": "espnews",
    "espn+": "espn-plus", "espn plus": "espn-plus",
    "sec network": "sec-network", "sec+": "sec-plus", "sec network +": "sec-plus",
    "sec network+": "sec-plus", "sec network plus": "sec-plus",
    "acc network": "acc-network", "accn": "acc-network", "acc extra": "acc-extra",
    "acc network extra": "acc-extra", "accnx": "acc-extra",
    "fs1": "fs1", "fox sports 1": "fs1", "fs2": "fs2", "fox sports 2": "fs2",
    "cbs sports network": "cbs-sports-network", "cbssn": "cbs-sports-network",
    "nfl network": "nfl-network",
}


def bundled_logo(station: str, base_url: str) -> str:
    name = BUNDLED_LOGOS.get(station_key(station))
    return f"{base_url.rstrip('/')}/static/station-logos/{name}.png" if name else ""
