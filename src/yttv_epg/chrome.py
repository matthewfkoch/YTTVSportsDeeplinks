from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
from websockets.exceptions import WebSocketException

from yttv_epg.session import NEEDED_SID, is_youtube_cookie_domain, sapisidhash_header, youtube_tv_cookies

YOUTUBE_TV = "https://tv.youtube.com"
MAX_DISK_CACHE_BYTES = 256 * 1024 * 1024
_PROFILE_JUNK_DIRS = ("BrowserMetrics", "Crashpad", "Crash Reports")
_LOGIN_HOSTS = ("accounts.google.com", "accounts.youtube.com", "signin.google.com")
KEEPALIVE_FETCH = (
    "(async () => {"
    " const res = await fetch('https://tv.youtube.com/?keepalive=1',"
    "  {credentials:'include', cache:'no-store', redirect:'follow'});"
    " return {status: res.status, redirected: res.redirected, url: location.href};"
    "})()"
)
_FETCH_FORBIDDEN = {
    "accept-encoding",
    "access-control-request-headers",
    "access-control-request-method",
    "connection",
    "content-length",
    "cookie",
    "cookie2",
    "date",
    "dnt",
    "expect",
    "host",
    "keep-alive",
    "origin",
    "referer",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
    "via",
}


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


def non_youtube_cookies(cookies: list[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in cookies if not is_youtube_cookie_domain(item.get("domain") or "")]


def chrome_signed_in(cookies: list[dict[str, str]]) -> bool:
    from yttv_epg.session import select_cookies

    selected = select_cookies(cookies, "tv.youtube.com")
    names = {item.get("name") for item in selected}
    return "LOGIN_INFO" in names and bool(names.intersection(NEEDED_SID))


def is_google_login_url(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == item or host.endswith("." + item) for item in _LOGIN_HOSTS)


def is_youtube_tv_url(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host == "tv.youtube.com" or host.endswith(".tv.youtube.com")


def _url_path(url: str | None) -> str:
    path = (urlparse(url or "").path or "/").lower()
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def is_youtube_tv_app_url(url: str | None) -> bool:
    if not is_youtube_tv_url(url):
        return False
    path = _url_path(url)
    return path != "/welcome" and not path.startswith("/welcome/") and path != "/onboarding" and not path.startswith("/onboarding/")


def is_youtube_tv_detour_url(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    path = _url_path(url)
    if host == "play.google.com" or host.endswith(".play.google.com"):
        return True
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com"} and (
        path == "/tv" or path.startswith("/tv/")
    )


def browser_fetch_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        if not key or key.lower() in _FETCH_FORBIDDEN:
            continue
        out[key] = value
    return out


def _require_innertube_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "youtube.com" and host != "tv.youtube.com" and not host.endswith(".youtube.com"):
        raise ChromeError("InnerTube fetch is limited to YouTube hosts.")
    if "/youtubei/" not in (parsed.path or ""):
        raise ChromeError("InnerTube fetch is limited to youtubei endpoints.")


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
    if any(is_google_login_url(page.get("url")) for page in pages):
        login = next(page for page in pages if is_google_login_url(page.get("url")))
        return {"ok": True, "target": login.get("url"), "skipped": "login"}
    app = next((page for page in pages if is_youtube_tv_app_url(page.get("url"))), None)
    if app is not None:
        if app.get("id"):
            try:
                await http.get(f"{base}/json/activate/{app['id']}", timeout=3)
            except httpx.HTTPError:
                pass
        return {"ok": True, "target": app.get("url") or YOUTUBE_TV}
    if not any(is_youtube_tv_detour_url(page.get("url")) for page in pages) and any(
        is_youtube_tv_url(page.get("url")) for page in pages
    ):
        welcome = next(page for page in pages if is_youtube_tv_url(page.get("url")))
        return {"ok": True, "target": welcome.get("url"), "skipped": "welcome"}
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
        return {"ok": True, "target": YOUTUBE_TV}
    ws_url = await _browser_ws(http, cdp_url)
    await _cdp(ws_url, "Target.createTarget", {"url": YOUTUBE_TV})
    return {"ok": True, "target": YOUTUBE_TV}


async def keepalive_youtube_tv(http: httpx.AsyncClient, cdp_url: str) -> dict[str, Any]:
    """Rotate Google login cookies without reloading the YouTube TV tab."""
    pages = await _pages(http, cdp_url.rstrip("/"))
    if any(is_google_login_url(page.get("url")) for page in pages):
        return {"ok": True, "skipped": "login"}
    if any(is_youtube_tv_detour_url(page.get("url")) for page in pages):
        page = await _tv_page(http, cdp_url, navigate=True)
        return {"ok": True, "target": YOUTUBE_TV, "bounced": True, "from": page.get("url")}
    page = next((item for item in pages if is_youtube_tv_app_url(item.get("url"))), None)
    if page is None:
        return {"ok": True, "skipped": "not_app"}
    ws = page.get("webSocketDebuggerUrl")
    if not ws:
        raise ChromeError("Chromium has no page to keep the YTTV login alive.")
    result = await _cdp(
        str(ws),
        "Runtime.evaluate",
        {
            "expression": KEEPALIVE_FETCH,
            "awaitPromise": True,
            "returnByValue": True,
            "timeout": 20000,
        },
        timeout=25,
    )
    value = _evaluate_value(result)
    return {"ok": True, "target": page.get("url") or YOUTUBE_TV, "reloaded": False, "result": value}


async def innertube_post(
    http: httpx.AsyncClient,
    cdp_url: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[int, Any]:
    """POST InnerTube from the signed-in tv.youtube.com tab so cookies stay in-browser."""
    _require_innertube_url(url)
    pages = await _pages(http, cdp_url.rstrip("/"))
    if any(is_google_login_url(page.get("url")) for page in pages):
        raise ChromeError("Chromium is on the Google login page.")
    if not any(is_youtube_tv_app_url(item.get("url")) for item in pages):
        raise ChromeError("Chromium is not on the YouTube TV app.")
    page = await _tv_page(http, cdp_url, navigate=False)
    ws = page.get("webSocketDebuggerUrl")
    if not ws:
        raise ChromeError("Chromium has no tv.youtube.com tab for guide requests.")
    live_headers = dict(headers)
    try:
        auth = sapisidhash_header(await fetch_cookies(http, cdp_url))
        if auth:
            live_headers["Authorization"] = auth
    except ChromeError:
        pass
    safe_headers = browser_fetch_headers(live_headers)
    expression = (
        "(async () => {"
        f" const res = await fetch({json.dumps(url)}, {{"
        "  method: 'POST',"
        "  credentials: 'include',"
        f"  headers: {json.dumps(safe_headers)},"
        f"  body: {json.dumps(json.dumps(payload, separators=(',', ':')))}"
        " });"
        " return {status: res.status, body: await res.text()};"
        "})()"
    )
    result = await _cdp(
        str(ws),
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "timeout": 45000,
        },
        timeout=50,
    )
    value = _evaluate_value(result)
    if not isinstance(value, dict):
        raise ChromeError("Chromium fetch returned an unexpected payload.")
    try:
        status = int(value.get("status") or 0)
    except (TypeError, ValueError) as exc:
        raise ChromeError("Chromium fetch returned no HTTP status.") from exc
    raw = value.get("body")
    if raw in (None, ""):
        return status, None
    if not isinstance(raw, str):
        return status, raw
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, None


async def prune_non_youtube_cookies(
    http: httpx.AsyncClient,
    cdp_url: str,
    cookies: list[dict[str, str]],
) -> list[dict[str, str]]:
    kept = youtube_tv_cookies(cookies)
    dropped = non_youtube_cookies(cookies)
    if not dropped:
        return kept
    try:
        ws_url = await _browser_ws(http, cdp_url)
    except ChromeError:
        return kept
    for cookie in dropped:
        params: dict[str, str] = {"name": str(cookie.get("name") or "")}
        domain = str(cookie.get("domain") or "")
        path = str(cookie.get("path") or "")
        if domain:
            params["domain"] = domain
        if path:
            params["path"] = path
        try:
            await _cdp(ws_url, "Network.deleteCookies", params)
        except ChromeError:
            continue
    return kept


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
    on_login = False
    on_app = False
    on_detour = False
    try:
        pages = await _pages(http, cdp_url.rstrip("/"))
        login_page = next((item for item in pages if is_google_login_url(item.get("url"))), None)
        app_page = next((item for item in pages if is_youtube_tv_app_url(item.get("url"))), None)
        detour_page = next((item for item in pages if is_youtube_tv_detour_url(item.get("url"))), None)
        chosen = login_page or app_page or detour_page or (pages[0] if pages else None)
        url = chosen.get("url") if chosen else None
        on_login = login_page is not None
        on_app = login_page is None and app_page is not None
        on_detour = login_page is None and detour_page is not None
    except ChromeError:
        url = None
    return {
        "available": True,
        "signed_in": signed,
        "url": url,
        "cookie_count": len(cookies),
        "on_login": on_login,
        "on_app": on_app,
        "on_detour": on_detour,
    }


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


async def _tv_page(http: httpx.AsyncClient, cdp_url: str, *, navigate: bool) -> dict[str, Any]:
    base = cdp_url.rstrip("/")
    pages = await _pages(http, base)
    page = next((item for item in pages if is_youtube_tv_url(item.get("url"))), None)
    if page is None and pages:
        page = pages[0]
    if page is None:
        await _cdp(await _browser_ws(http, cdp_url), "Target.createTarget", {"url": YOUTUBE_TV})
        pages = await _pages(http, base)
        page = pages[0] if pages else {}
    ws = page.get("webSocketDebuggerUrl")
    if not ws:
        raise ChromeError("Chromium has no page websocket for tv.youtube.com.")
    url = page.get("url")
    if navigate or not is_youtube_tv_url(url):
        await _cdp(str(ws), "Page.enable")
        await _cdp(str(ws), "Page.navigate", {"url": YOUTUBE_TV})
        page = {**page, "url": await _wait_youtube_tv(str(ws))}
    return page


async def _wait_youtube_tv(ws_url: str, timeout: float = 20) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await _cdp(
            ws_url,
            "Runtime.evaluate",
            {"expression": "location.href", "returnByValue": True},
            timeout=5,
        )
        url = str(_evaluate_value(result) or "")
        if is_youtube_tv_url(url):
            return url
        if is_google_login_url(url):
            raise ChromeError("Chromium is on the Google login page.")
        await asyncio.sleep(0.25)
    raise ChromeError("Chromium did not open tv.youtube.com.")


def _evaluate_value(result: Any) -> Any:
    if not isinstance(result, dict):
        raise ChromeError("Chromium fetch returned an unexpected payload.")
    details = result.get("exceptionDetails")
    if isinstance(details, dict):
        exception = details.get("exception") if isinstance(details.get("exception"), dict) else {}
        text = (
            str(exception.get("description") or "")
            or str(details.get("text") or "")
            or "Chromium JavaScript threw."
        )
        raise ChromeError(text)
    inner = result.get("result")
    if isinstance(inner, dict):
        if inner.get("subtype") == "error":
            raise ChromeError(str(inner.get("description") or "Chromium JavaScript threw."))
        if "value" in inner:
            return inner["value"]
        return inner
    return result


async def _cdp(
    ws_url: str,
    method: str,
    params: Optional[dict[str, Any]] = None,
    *,
    timeout: float = 15,
) -> Any:
    payload = {"id": 1, "method": method, "params": params or {}}
    try:
        async with websockets.connect(ws_url, max_size=None, open_timeout=min(5.0, timeout)) as ws:
            await ws.send(json.dumps(payload))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if message.get("id") != 1:
                    continue
                if message.get("error"):
                    error = message["error"]
                    text = error.get("message") if isinstance(error, dict) else str(error)
                    raise ChromeError(text or method)
                return message.get("result") or {}
    except asyncio.TimeoutError as exc:
        raise ChromeError("Chromium DevTools timed out.") from exc
    except (OSError, WebSocketException, json.JSONDecodeError) as exc:
        raise ChromeError("Could not talk to Chromium DevTools.") from exc
