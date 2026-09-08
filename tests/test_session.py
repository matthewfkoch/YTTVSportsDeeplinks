from __future__ import annotations

from pathlib import Path

import pytest

from yttv_epg.crypto import encrypt
from yttv_epg.session import (
    CookieError,
    parse_cookie_text,
    require_youtube_tv_cookies,
    sapisidhash_header,
    select_cookies,
)
from yttv_epg.session_store import SavedSession, SessionStore


NETSCAPE = """# Netscape HTTP Cookie File
#HttpOnly_.youtube.com	TRUE	/	TRUE	1999999999	SAPISID	sapi-secret
.youtube.com	TRUE	/	TRUE	1999999999	SID	sid-value
.google.com	TRUE	/	TRUE	1999999999	HSID	hsid-value
"""


def test_parse_netscape_and_require_youtube_tv():
    cookies = require_youtube_tv_cookies(parse_cookie_text(NETSCAPE))
    names = {item["name"] for item in cookies}
    assert "SAPISID" in names
    assert "SID" in names


def test_parse_json_cookies():
    raw = '[{"name":"SAPISID","value":"abc","domain":".youtube.com"},{"name":"SID","value":"def"}]'
    cookies = require_youtube_tv_cookies(parse_cookie_text(raw))
    assert cookies[0]["name"] == "SAPISID"


def test_parse_cookie_header():
    cookies = require_youtube_tv_cookies(parse_cookie_text("SAPISID=abc; SID=def; HSID=ghi"))
    assert {item["name"] for item in cookies} >= {"SAPISID", "SID"}


def test_missing_sapisid_is_rejected():
    with pytest.raises(CookieError, match="SAPISID"):
        require_youtube_tv_cookies(parse_cookie_text("SID=abc; HSID=def"))


def test_select_youtube_sapisid_over_google():
    cookies = [
        {"name": "SAPISID", "value": "google-sapi", "domain": ".google.com"},
        {"name": "SAPISID", "value": "youtube-sapi", "domain": ".youtube.com"},
        {"name": "SID", "value": "google-sid", "domain": ".google.com"},
        {"name": "SID", "value": "youtube-sid", "domain": ".youtube.com"},
    ]
    selected = {item["name"]: item["value"] for item in select_cookies(cookies, "tv.youtube.com")}
    assert selected["SAPISID"] == "youtube-sapi"
    assert selected["SID"] == "youtube-sid"


def test_sapisidhash_header_shape():
    header = sapisidhash_header(
        [{"name": "SAPISID", "value": "secret", "domain": ".youtube.com"}],
        origin="https://tv.youtube.com",
    )
    assert header.startswith("SAPISIDHASH ")
    stamp, digest = header.split(" ", 1)[1].split("_", 1)
    assert stamp.isdigit()
    assert len(digest) == 40


def test_session_store_persists_cookies(tmp_path: Path):
    store = SessionStore(tmp_path, "unit-test-secret")
    session = SavedSession(kind="cookies", cookies=[{"name": "SAPISID", "value": "abc"}])
    store.save(session)
    loaded = store.load()
    assert loaded is not None
    assert loaded.cookies[0]["value"] == "abc"
    store.clear()
    assert store.load() is None


def test_legacy_oauth_file_is_dropped(tmp_path: Path):
    store = SessionStore(tmp_path, "unit-test-secret")
    store.legacy_path.write_bytes(encrypt("unit-test-secret", b'{"access_token":"ya29"}'))
    assert store.load() is None
    assert not store.legacy_path.exists()
