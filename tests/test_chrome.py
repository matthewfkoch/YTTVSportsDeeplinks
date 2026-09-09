from __future__ import annotations

from pathlib import Path

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
