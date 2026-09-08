from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Iterable

ORIGIN = "https://tv.youtube.com"

NEEDED_SID = ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID")


class CookieError(ValueError):
    pass


def parse_cookie_text(raw: str) -> list[dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        raise CookieError("No cookies were provided.")
    if text.startswith("[") or text.startswith("{"):
        return _from_json(text)
    if "\t" in text or text.startswith("#") or "netscape" in text.lower():
        return _from_netscape(text)
    if "=" in text and ";" in text:
        return _from_header(text)
    if "=" in text and "\n" not in text:
        return _from_header(text)
    return _from_netscape(text)


def require_youtube_tv_cookies(cookies: list[dict[str, str]]) -> list[dict[str, str]]:
    names = {item["name"] for item in cookies if item.get("name")}
    if not names.intersection(NEEDED_SID):
        raise CookieError(
            "These cookies are missing SAPISID. Export from tv.youtube.com after you are signed in."
        )
    youtubeish = any(
        "youtube" in (item.get("domain") or "").lower()
        or item.get("name") in {"SID", "HSID", "SSID", "LOGIN_INFO", "SAPISID", "__Secure-3PAPISID"}
        for item in cookies
    )
    if not youtubeish:
        raise CookieError("Export cookies from tv.youtube.com, not from an unrelated Google page.")
    return cookies


def select_cookies(cookies: Iterable[dict[str, str]], host: str = "tv.youtube.com") -> list[dict[str, str]]:
    ranked: list[tuple[tuple[int, int], dict[str, str]]] = []
    for item in cookies:
        if not item.get("name"):
            continue
        if not _domain_matches(item.get("domain") or "", host):
            continue
        ranked.append((_cookie_rank(item.get("domain") or "", host), item))
    ranked.sort(key=lambda pair: pair[0])
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, item in ranked:
        name = item["name"]
        if name in seen:
            continue
        seen.add(name)
        selected.append(item)
    return selected


def cookie_header(cookies: Iterable[dict[str, str]], host: str = "tv.youtube.com") -> str:
    parts: list[str] = []
    for item in select_cookies(cookies, host):
        parts.append(f"{item['name']}={item.get('value') or ''}")
    return "; ".join(parts)


def sapisidhash_header(cookies: Iterable[dict[str, str]], origin: str = ORIGIN) -> str:
    host = origin.replace("https://", "").replace("http://", "")
    selected = select_cookies(cookies, host)
    ts = str(int(time.time()))
    chunks: list[str] = []
    mapping = (
        ("SAPISIDHASH", ("SAPISID", "__Secure-3PAPISID")),
        ("SAPISID1PHASH", ("__Secure-1PAPISID",)),
        ("SAPISID3PHASH", ("__Secure-3PAPISID",)),
    )
    for scheme, names in mapping:
        value = _first(selected, names)
        if not value:
            continue
        digest = hashlib.sha1(f"{ts} {value} {origin}".encode("utf-8")).hexdigest()
        chunks.append(f"{scheme} {ts}_{digest}")
    return " ".join(chunks)


def innertube_headers(cookies: list[dict[str, str]], client: dict[str, str]) -> dict[str, str]:
    origin = client.get("origin") or ORIGIN
    host = origin.replace("https://", "").replace("http://", "")
    selected = select_cookies(cookies, host)
    headers = {
        "Cookie": cookie_header(selected, host),
        "Content-Type": "application/json",
        "Origin": origin,
        "X-Origin": origin,
        "Referer": origin + "/",
        "X-YouTube-Client-Name": client["id"],
        "X-YouTube-Client-Version": client["version"],
        "User-Agent": client["ua"],
        "X-Goog-AuthUser": "0",
    }
    auth = sapisidhash_header(selected, origin)
    if auth:
        headers["Authorization"] = auth
    return headers


def _first(cookies: Iterable[dict[str, str]], names: tuple[str, ...]) -> str:
    wanted = set(names)
    for item in cookies:
        if item.get("name") in wanted and item.get("value"):
            return str(item["value"])
    return ""


def _cookie_rank(domain: str, host: str) -> tuple[int, int]:
    domain = (domain or "").lstrip(".").lower()
    host = host.lower()
    if domain == host:
        return (0, -len(domain))
    if host.endswith("." + domain):
        return (1, -len(domain))
    if "youtube.com" in host:
        if domain.endswith("youtube.com"):
            return (2, -len(domain))
        if domain.endswith("google.com"):
            return (4, -len(domain))
    return (3, -len(domain))


def _domain_matches(domain: str, host: str) -> bool:
    domain = (domain or "").lstrip(".").lower()
    host = host.lower()
    if not domain:
        return True
    if host == domain or host.endswith("." + domain) or domain.endswith(host):
        return True
    # Google SID cookies often live on .google.com while InnerTube is called on tv.youtube.com.
    google_family = domain in {"google.com", "youtube.com", "tv.youtube.com"}
    host_family = "youtube.com" in host or "google.com" in host
    return google_family and host_family


def _from_netscape(text: str) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_") :]
        parts = line.split("\t")
        if len(parts) < 7:
            parts = line.split()
        if len(parts) < 7:
            continue
        domain, _flag, path, secure, expires, name, value = parts[:7]
        cookies.append(
            {
                "domain": domain,
                "path": path,
                "name": name,
                "value": value,
                "secure": secure.upper(),
                "expires": expires,
                "httpOnly": "1" if http_only else "0",
            }
        )
    if not cookies:
        raise CookieError("Could not parse a Netscape cookies.txt file.")
    return cookies


def _from_json(text: str) -> list[dict[str, str]]:
    data = json.loads(text)
    rows = data if isinstance(data, list) else data.get("cookies") or data.get("Cookie") or []
    if isinstance(data, dict) and not rows:
        rows = [{"name": key, "value": str(value), "domain": ".youtube.com"} for key, value in data.items()]
    cookies: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("Name") or "")
        value = str(item.get("value") or item.get("Value") or "")
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": str(item.get("domain") or item.get("Domain") or ".youtube.com"),
                "path": str(item.get("path") or "/"),
            }
        )
    if not cookies:
        raise CookieError("Could not parse JSON cookies.")
    return cookies


def _from_header(text: str) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    for part in text.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if name:
            cookies.append({"name": name, "value": value, "domain": ".youtube.com", "path": "/"})
    if not cookies:
        raise CookieError("Could not parse a Cookie header.")
    return cookies
