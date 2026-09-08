from __future__ import annotations

from yttv_epg.chrome import chrome_signed_in, from_cdp_cookies


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
