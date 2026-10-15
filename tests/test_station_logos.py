import json

from yttv_epg.station_logos import load_station_logos, station_key


def test_missing_and_invalid_override_files(tmp_path, caplog):
    path = tmp_path / "logos.json"
    assert load_station_logos(path) == {}
    assert not caplog.records
    for contents in ("{", "[]", "null"):
        path.write_text(contents)
        assert load_station_logos(path) == {}
    assert "Cannot load station logo overrides" in caplog.text


def test_override_normalization_and_invalid_entries(tmp_path, caplog):
    path = tmp_path / "logos.json"
    path.write_text(json.dumps({
        "  NFL   NETWORK ": "https://example.com/nfl.png",
        "ESPN": "http://example.com/espn.png",
        "ESPN2": "https://example.com/espn2.png",
        "FS1": "file:///local.png", "FS2": None,
        "": "https://example.com/empty.png", "Bad": "https://[invalid",
    }))
    assert load_station_logos(path) == {
        "nfl network": "https://example.com/nfl.png", "espn": "http://example.com/espn.png",
        "espn2": "https://example.com/espn2.png",
    }
    assert "Ignoring invalid" in caplog.text
    assert station_key("FS1") != station_key("FS2")
