from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pytest

from yttv_epg.catalog import Catalog
from yttv_epg.config import Settings
from yttv_epg.display import event_for_ui
from yttv_epg.feeds import xmltv
from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import Airing


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("offset,enabled,status,repeat,expected", [
    (0, False, None, None, False),
    (0, True, None, None, True),
    (-1, True, None, None, True),
    (1, True, None, None, False),
    (-60, True, None, None, False),
    (0, True, False, None, False),
    (0, True, None, True, False),
    (0, True, True, True, False),
    (1, False, True, None, True),
])
def test_live_fallback_boundaries_and_evidence(offset, enabled, status, repeat, expected):
    start = NOW + timedelta(minutes=offset)
    item = Airing("abcdefghijk", "A at B", "ACC Network", "event", start,
                  start + timedelta(hours=1), "https://tv.youtube.com/watch/abcdefghijk",
                  live=True, broadcast_live=status, is_repeat=repeat)
    programme = ET.fromstring(xmltv([LaneAssignment(1, item)], 1, now=NOW,
                                   live_on_air=enabled)).find("programme")
    assert (programme.find("live") is not None) is expected
    assert event_for_ui(item, now=NOW, live_on_air=enabled)["show_live"] is (expected and offset <= 0)
    assert programme.find("new") is None
    assert item.broadcast_live is status
    assert (programme.find("previously-shown") is not None) is (repeat is True)


def test_saved_preference_overrides_environment_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XMLTV_LIVE_ON_AIR", "true")
    default = Settings(_env_file=None).xmltv_live_on_air
    assert default is True
    path = tmp_path / "catalog.sqlite"
    catalog = Catalog(path)
    catalog.ensure_xmltv_live_on_air(default)
    assert catalog.xmltv_live_on_air() is True
    catalog.set_xmltv_live_on_air(False)
    reopened = Catalog(path)
    reopened.ensure_xmltv_live_on_air(default)
    assert reopened.xmltv_live_on_air() is False
