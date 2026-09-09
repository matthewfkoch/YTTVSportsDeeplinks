from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
from websockets.exceptions import WebSocketException

from yttv_epg.session import NEEDED_SID

YOUTUBE_TV = "https://tv.youtube.com"
MAX_DISK_CACHE_BYTES = 256 * 1024 * 1024
_PROFILE_JUNK_DIRS = ("BrowserMetrics", "Crashpad", "Crash Reports")


class ChromeError(RuntimeError):
    pass


def prune_chrome_profile(
    profile: Path,
    *,
    cap_cache: bool = False,
    max_cache_bytes: int = MAX_DISK_CACHE_BYTES,
) -> int:
    """Delete Chromium metrics dumps. Optionally cap the disk cache. Login data stays."""
    if not profile.is_dir():
        return 0
    removed = 0
    for name in _PROFILE_JUNK_DIRS:
        removed += _remove_tree(profile / name)
    for pma in profile.glob("*.pma"):
        removed += _remove_file(pma)
    if cap_cache:
        removed += _cap_directory(profile / "Default" / "Cache", max_cache_bytes)
    return removed


def _remove_tree(path: Path) -> int:
    if not path.exists():
        return 0
    size = _path_size(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        _remove_file(path)
    return size if not path.exists() else 0


def _remove_file(path: Path) -> int:
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _cap_directory(path: Path, max_bytes: int) -> int:
    if max_bytes < 0 or not path.is_dir():
        return 0
    size = _path_size(path)
    if size <= max_bytes:
        return 0
    return _remove_tree(path)


def from_cdp_cookies(raw: Any) -> list[dict[str, str]]:
    rows = raw
    if isinstance(raw, dict):
        rows = raw.get("cookies") or []
    cookies: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return cookies
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        expires = item.get("expires")
        cookies.append(
            {
                "name": name,
                "value": str(item.get("value") or ""),
                "domain": str(item.get("domain") or ".youtube.com"),
                "path": str(item.get("path") or "/"),
                "secure": "TRUE" if item.get("secure") else "FALSE",
                "expires": "" if expires in {None, -1} else str(expires),
                "httpOnly": "1" if item.get("httpOnly") else "0",
            }
        )
    return cookies


def chrome_signed_in(cookies: list[dict[str, str]]) -> bool:
    from yttv_epg.session import select_cookies

    selected = select_cookies(cookies, "tv.youtube.com")
    names = {item.get("name") for item in selected}
    return "LOGIN_INFO" in names and bool(names.intersection(NEEDED_SID))


async def available(http: httpx.AsyncClient, cdp_url: str) -> bool:
    try:
        response = await http.get(cdp_url.rstrip("/") + "/json/version", timeout=1.5)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


async def fetch_cookies(http: httpx.AsyncClient, cdp_url: str) -> list[dict[str, str]]:
    errors: list[str] = []
    ws_url = await _browser_ws(http, cdp_url)
    for method in ("Network.getAllCookies", "Storage.getCookies"):
        try:
            cookies = from_cdp_cookies(await _cdp(ws_url, method))
        except ChromeError as exc:
            errors.append(str(exc))
            continue
        if cookies:
            return cookies
    for page in await _pages(http, cdp_url.rstrip("/")):
        ws = page.get("webSocketDebuggerUrl")
        if not ws:
            continue
        try:
            cookies = from_cdp_cookies(await _cdp(str(ws), "Network.getAllCookies"))
        except ChromeError as exc:
            errors.append(str(exc))
            continue
        if cookies:
            return cookies
    raise ChromeError(
        errors[-1] if errors else "Chromium has no cookies yet. Sign in on tv.youtube.com in the window below."
    )


async def open_youtube_tv(http: httpx.AsyncClient, cdp_url: str) -> dict[str, Any]:
    base = cdp_url.rstrip("/")
    pages = await _pages(http, base)
    for page in pages:
        ws = page.get("webSocketDebuggerUrl")
        if not ws:
            continue
        await _cdp(str(ws), "Page.enable")
        await _cdp(str(ws), "Page.navigate", {"url": YOUTUBE_TV})
        if page.get("id"):
            try:
                await http.get(f"{base}/json/activate/{page['id']}", timeout=3)
            except httpx.HTTPError:
                pass
        return {"ok": True, "target": page.get("url") or YOUTUBE_TV}
    ws_url = await _browser_ws(http, cdp_url)
    await _cdp(ws_url, "Target.createTarget", {"url": YOUTUBE_TV})
    return {"ok": True, "target": YOUTUBE_TV}


async def clear_browser_cookies(http: httpx.AsyncClient, cdp_url: str) -> None:
    ws_url = await _browser_ws(http, cdp_url)
    for method in ("Network.clearBrowserCookies", "Storage.clearCookies"):
        try:
            await _cdp(ws_url, method)
        except ChromeError:
            continue


async def status(http: httpx.AsyncClient, cdp_url: str) -> dict[str, Any]:
    if not await available(http, cdp_url):
        return {"available": False, "signed_in": False, "url": None}
    try:
        cookies = await fetch_cookies(http, cdp_url)
        signed = chrome_signed_in(cookies)
    except ChromeError:
        cookies = []
        signed = False
    url = None
    try:
        pages = await _pages(http, cdp_url.rstrip("/"))
        page = next((item for item in pages if item.get("type") == "page"), None)
        if page:
            url = page.get("url")
    except ChromeError:
        url = None
    return {"available": True, "signed_in": signed, "url": url, "cookie_count": len(cookies)}


async def _pages(http: httpx.AsyncClient, base: str) -> list[dict[str, Any]]:
    try:
        response = await http.get(base + "/json/list", timeout=3)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ChromeError("Chromium DevTools is not reachable.") from exc
    data = response.json()
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("type") == "page"]


async def _browser_ws(http: httpx.AsyncClient, cdp_url: str) -> str:
    try:
        response = await http.get(cdp_url.rstrip("/") + "/json/version", timeout=3)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ChromeError("Chromium is not running inside the container yet.") from exc
    data = response.json()
    if not isinstance(data, dict) or not data.get("webSocketDebuggerUrl"):
        raise ChromeError("Chromium did not expose a DevTools websocket.")
    return _local_ws(str(data["webSocketDebuggerUrl"]))


def _local_ws(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


async def _cdp(ws_url: str, method: str, params: Optional[dict[str, Any]] = None) -> Any:
    payload = {"id": 1, "method": method, "params": params or {}}
    try:
        async with websockets.connect(ws_url, max_size=None, open_timeout=5) as ws:
            await ws.send(json.dumps(payload))
            while True:
                message = json.loads(await ws.recv())
                if message.get("id") != 1:
                    continue
                if message.get("error"):
                    error = message["error"]
                    text = error.get("message") if isinstance(error, dict) else str(error)
                    raise ChromeError(text or method)
                return message.get("result") or {}
    except (OSError, WebSocketException) as exc:
        raise ChromeError("Could not talk to Chromium DevTools.") from exc
