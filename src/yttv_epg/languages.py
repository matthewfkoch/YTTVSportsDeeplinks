"""Conservative broadcast-language detection, independent of teams or geography."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def language_code(value: str) -> str:
    value = _fold(value).strip().replace("_", "-")
    if value in {"spanish", "espanol", "spa"} or value == "es" or value.startswith("es-"):
        return "es"
    if value in {"english", "eng"} or value == "en" or value.startswith("en-"):
        return "en"
    return ""


def detect_language(station: str = "", *labels: str) -> str:
    text = _fold(" ".join(labels))
    if re.search(r"\b(en espanol|espanol|spanish(?:[- ]language)?)\b", text):
        return "es"
    if re.search(r"\b(in english|english(?:[- ]language)?)\b", text):
        return "en"
    key = " ".join(_fold(station).split())
    if key in {"espn deportes", "tudn", "telemundo", "universo", "univision", "unimas", "bein sports en espanol"}:
        return "es"
    if re.fullmatch(r"vix premium deportes(?: \d+)?", key):
        return "es"
    return ""


def broadcast_language(event: Any) -> str:
    return language_code(getattr(event, "language", "") or "") or detect_language(
        getattr(event, "station", "") or "", getattr(event, "title", "") or "",
    )
