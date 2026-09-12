from __future__ import annotations

from pathlib import Path

import pytest

from yttv_epg.chrome import chrome_signed_in, from_cdp_cookies, non_youtube_cookies, prune_chrome_profile
from yttv_epg.session import youtube_tv_cookies


def test_from_cdp_cookies_maps_sapisid():
    cookies = from_cdp_cookies(
        {
            "cookies": [
                {
                    "name": "SAPISID",
                    "value": "secret",
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "expires": 1999999999,
                },
                {
                    "name": "LOGIN_INFO",
                    "value": "session",
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "expires": 1999999999,
                },
            ]
        }
    )
    assert cookies[0]["name"] == "SAPISID"
    assert cookies[0]["value"] == "secret"
    assert chrome_signed_in(cookies) is True


def test_chrome_signed_in_requires_sapisid():
    assert chrome_signed_in([{"name": "SID", "value": "x"}]) is False
    assert chrome_signed_in([{"name": "SAPISID", "value": "x", "domain": ".google.com"}]) is False


def test_prune_chrome_profile_drops_metrics_keeps_login(tmp_path: Path):
    profile = tmp_path / "chrome-profile"
    metrics = profile / "BrowserMetrics"
    metrics.mkdir(parents=True)
    (metrics / "BrowserMetrics-1.pma").write_bytes(b"x" * 4096)
    (profile / "BrowserMetrics-spare.pma").write_bytes(b"y" * 1024)
    crashpad = profile / "Crashpad" / "completed"
    crashpad.mkdir(parents=True)
    (crashpad / "dump").write_bytes(b"z" * 2048)
    cookies = profile / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_text("login")
    cache_file = profile / "Default" / "Cache" / "Cache_Data" / "blob"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"c" * 8192)

    removed = prune_chrome_profile(profile, cap_cache=True, max_cache_bytes=1024)

    assert removed >= 4096 + 1024 + 2048 + 8192
    assert not metrics.exists()
    assert not (profile / "BrowserMetrics-spare.pma").exists()
    assert not (profile / "Crashpad").exists()
    assert cookies.read_text() == "login"
    assert not (profile / "Default" / "Cache").exists()


def test_prune_chrome_profile_keeps_small_cache(tmp_path: Path):
    profile = tmp_path / "chrome-profile"
    cache_file = profile / "Default" / "Cache" / "f"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"c" * 64)

    assert prune_chrome_profile(profile, cap_cache=True, max_cache_bytes=1024) == 0
    assert cache_file.exists()
    assert prune_chrome_profile(profile) == 0
    assert cache_file.exists()


def test_prune_chrome_profile_missing_dir(tmp_path: Path):
    assert prune_chrome_profile(tmp_path / "missing") == 0


def test_mixed_cdp_jar_keeps_youtube_domains_only():
    cookies = from_cdp_cookies(
        {
            "cookies": [
                {
                    "name": "SAPISID",
                    "value": "yt",
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                },
                {
                    "name": "LOGIN_INFO",
                    "value": "session",
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                },
                {
                    "name": "SID",
                    "value": "gmail",
                    "domain": ".google.com",
                    "path": "/",
                    "secure": True,
                },
                {
                    "name": "HSID",
                    "value": "gmail-hsid",
                    "domain": ".google.com",
                    "path": "/",
                    "secure": True,
                },
            ]
        }
    )
    kept = youtube_tv_cookies(cookies)
    dropped = non_youtube_cookies(cookies)
    assert {item["name"] for item in kept} == {"SAPISID", "LOGIN_INFO"}
    assert {item["domain"].lstrip(".") for item in kept} == {"youtube.com"}
    assert {item["name"] for item in dropped} == {"SID", "HSID"}


def test_login_and_tv_url_helpers():
    from yttv_epg.chrome import (
        is_google_login_url,
        is_youtube_tv_app_url,
        is_youtube_tv_detour_url,
        is_youtube_tv_url,
    )

    assert is_google_login_url("https://accounts.google.com/signin/v2")
    assert is_google_login_url("https://accounts.youtube.com/accounts/SetSID")
    assert not is_google_login_url("https://tv.youtube.com/")
    assert is_youtube_tv_url("https://tv.youtube.com/watch/abc")
    assert is_youtube_tv_url("https://www.tv.youtube.com/")
    assert not is_youtube_tv_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_tv_app_url("https://tv.youtube.com/")
    assert is_youtube_tv_app_url("https://tv.youtube.com/watch/abc")
    assert not is_youtube_tv_app_url("https://tv.youtube.com/welcome/?rd_rsn=lo")
    assert not is_youtube_tv_app_url("https://www.youtube.com/tv")
    assert is_youtube_tv_detour_url("https://www.youtube.com/tv")
    assert is_youtube_tv_detour_url("https://www.youtube.com/tv/upgrade")
    assert not is_youtube_tv_detour_url("https://tv.youtube.com/welcome/")
    assert is_youtube_tv_detour_url("https://play.google.com/store/apps/details?id=com.google.android.youtube.tvunplugged")
    assert not is_youtube_tv_detour_url("https://tv.youtube.com/")


def test_browser_fetch_headers_keep_authorization_drop_cookie():
    from yttv_epg.chrome import browser_fetch_headers

    out = browser_fetch_headers(
        {
            "Cookie": "SAPISID=stale",
            "Authorization": "SAPISIDHASH 1_deadbeef",
            "Origin": "https://tv.youtube.com",
            "Referer": "https://tv.youtube.com/",
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "X-YouTube-Client-Name": "41",
        }
    )
    assert "Cookie" not in out
    assert out["Authorization"] == "SAPISIDHASH 1_deadbeef"
    assert "Origin" not in out
    assert out["Content-Type"] == "application/json"
    assert out["X-YouTube-Client-Name"] == "41"


def test_innertube_url_is_limited_to_youtubei():
    import pytest

    from yttv_epg.chrome import ChromeError, _require_innertube_url

    _require_innertube_url("https://tv.youtube.com/youtubei/v1/browse?alt=json")
    with pytest.raises(ChromeError, match="YouTube hosts"):
        _require_innertube_url("https://example.com/youtubei/v1/browse")
    with pytest.raises(ChromeError, match="youtubei"):
        _require_innertube_url("https://tv.youtube.com/watch/abc")


def test_evaluate_value_unwraps_cdp_result():
    import pytest

    from yttv_epg.chrome import ChromeError, _evaluate_value

    assert _evaluate_value({"result": {"type": "object", "value": {"status": 200}}}) == {"status": 200}
    with pytest.raises(ChromeError, match="threw"):
        _evaluate_value({"exceptionDetails": {"text": "TypeError", "exception": {"description": "threw"}}})


@pytest.mark.asyncio
async def test_keepalive_skips_google_login_tab(monkeypatch):
    import httpx

    from yttv_epg.chrome import keepalive_youtube_tv

    async def fake_pages(http, base):
        return [{"url": "https://accounts.google.com/signin", "type": "page"}]

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    result = await keepalive_youtube_tv(httpx.AsyncClient(), "http://127.0.0.1:9222")
    assert result["ok"] is True
    assert result["skipped"] == "login"


@pytest.mark.asyncio
async def test_keepalive_skips_welcome_page(monkeypatch):
    import httpx

    from yttv_epg.chrome import keepalive_youtube_tv

    async def fake_pages(http, base):
        return [{"url": "https://tv.youtube.com/welcome/?rd_rsn=lo", "type": "page"}]

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    result = await keepalive_youtube_tv(httpx.AsyncClient(), "http://127.0.0.1:9222")
    assert result["skipped"] == "not_app"


@pytest.mark.asyncio
async def test_open_youtube_tv_leaves_google_login_alone(monkeypatch):
    import httpx

    from yttv_epg.chrome import open_youtube_tv

    navigated = []

    async def fake_pages(http, base):
        return [{"url": "https://accounts.google.com/signin", "type": "page", "id": "1"}]

    async def fake_cdp(ws_url, method, params=None, *, timeout=15):
        navigated.append(method)
        return {}

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    monkeypatch.setattr("yttv_epg.chrome._cdp", fake_cdp)
    result = await open_youtube_tv(httpx.AsyncClient(), "http://127.0.0.1:9222")
    assert result["skipped"] == "login"
    assert navigated == []


@pytest.mark.asyncio
async def test_open_youtube_tv_leaves_welcome_alone(monkeypatch):
    import httpx

    from yttv_epg.chrome import open_youtube_tv

    navigated = []

    async def fake_pages(http, base):
        return [{"url": "https://tv.youtube.com/welcome/?rd_rsn=lo", "type": "page", "id": "1"}]

    async def fake_cdp(ws_url, method, params=None, *, timeout=15):
        navigated.append(method)
        return {}

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    monkeypatch.setattr("yttv_epg.chrome._cdp", fake_cdp)
    result = await open_youtube_tv(httpx.AsyncClient(), "http://127.0.0.1:9222")
    assert result["skipped"] == "welcome"
    assert navigated == []


@pytest.mark.asyncio
async def test_open_youtube_tv_bounces_youtube_tv_leanback(monkeypatch):
    import httpx

    from yttv_epg.chrome import YOUTUBE_TV, open_youtube_tv

    navigated = []

    async def fake_pages(http, base):
        return [
            {
                "url": "https://www.youtube.com/tv",
                "type": "page",
                "id": "1",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1",
            }
        ]

    async def fake_cdp(ws_url, method, params=None, *, timeout=15):
        navigated.append((method, (params or {}).get("url")))
        return {}

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    monkeypatch.setattr("yttv_epg.chrome._cdp", fake_cdp)
    result = await open_youtube_tv(httpx.AsyncClient(), "http://127.0.0.1:9222")
    assert result["target"] == YOUTUBE_TV
    assert ("Page.navigate", YOUTUBE_TV) in navigated


@pytest.mark.asyncio
async def test_innertube_post_refuses_login_tab(monkeypatch):
    import httpx
    import pytest

    from yttv_epg.chrome import ChromeError, innertube_post

    async def fake_pages(http, base):
        return [{"url": "https://accounts.google.com/v3/signin", "type": "page"}]

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    with pytest.raises(ChromeError, match="login page"):
        await innertube_post(
            httpx.AsyncClient(),
            "http://127.0.0.1:9222",
            "https://tv.youtube.com/youtubei/v1/browse",
            {},
            {"browseId": "FEunplugged_epg"},
        )


@pytest.mark.asyncio
async def test_innertube_post_refuses_welcome_tab(monkeypatch):
    import httpx
    import pytest

    from yttv_epg.chrome import ChromeError, innertube_post

    async def fake_pages(http, base):
        return [{"url": "https://tv.youtube.com/welcome/?rd_rsn=lo", "type": "page"}]

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    with pytest.raises(ChromeError, match="not on the YouTube TV app"):
        await innertube_post(
            httpx.AsyncClient(),
            "http://127.0.0.1:9222",
            "https://tv.youtube.com/youtubei/v1/browse",
            {"Authorization": "SAPISIDHASH stale"},
            {"browseId": "FEunplugged_epg"},
        )


@pytest.mark.asyncio
async def test_keepalive_does_not_reload_app_tab(monkeypatch):
    import httpx

    from yttv_epg.chrome import keepalive_youtube_tv

    calls: list[str] = []

    async def fake_pages(http, base):
        return [
            {
                "url": "https://tv.youtube.com/",
                "type": "page",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1",
            }
        ]

    async def fake_cdp(ws_url, method, params=None, *, timeout=15):
        calls.append(method)
        if method == "Runtime.evaluate":
            assert "redirect:'follow'" in str((params or {}).get("expression") or "")
            assert "Page.navigate" not in calls
            return {"result": {"type": "object", "value": {"status": 200, "url": "https://tv.youtube.com/"}}}
        return {}

    monkeypatch.setattr("yttv_epg.chrome._pages", fake_pages)
    monkeypatch.setattr("yttv_epg.chrome._cdp", fake_cdp)
    result = await keepalive_youtube_tv(httpx.AsyncClient(), "http://127.0.0.1:9222")
    assert result["reloaded"] is False
    assert "Page.navigate" not in calls
    assert "Runtime.evaluate" in calls


def test_keepalive_fetch_follows_redirects():
    from yttv_epg.chrome import KEEPALIVE_FETCH

    assert "redirect:'follow'" in KEEPALIVE_FETCH
    assert "redirect:'manual'" not in KEEPALIVE_FETCH


def test_chrome_policy_allows_google_session_hosts():
    import json
    from pathlib import Path

    policy = json.loads((Path(__file__).resolve().parents[1] / "chromium-policy.json").read_text())
    allow = policy["URLAllowlist"]
    assert "https://[*.]google.com" in allow
    assert "wss://[*.]google.com" in allow
    assert "wss://[*.]youtube.com" in allow
    assert "wss://tv.youtube.com" in allow
