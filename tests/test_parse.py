from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from yttv_epg.parse import parse_browse

FIXTURE = Path(__file__).parent / "fixtures" / "sample_browse.json"


def test_parse_linear_and_event_airings():
    payload = json.loads(FIXTURE.read_text())
    now = datetime.fromtimestamp(1730001000, tz=timezone.utc)
    airings = parse_browse(payload, now=now, fallback_minutes=180)
    by_id = {item.video_id: item for item in airings}

    espn = by_id["bj3v-DQPnNs"]
    assert espn.kind == "linear"
    assert espn.station == "ESPN"
    assert espn.channel == "ESPN"
    assert espn.deeplink == "https://tv.youtube.com/watch/bj3v-DQPnNs"

    event = by_id["YGUvoKVT5qk"]
    assert event.kind == "event"
    assert event.title == "UConn vs Maryland"
    assert event.channel == "ESPN+"
    assert event.deeplink.endswith("YGUvoKVT5qk")

    tennis = by_id["abcdefghijk"]
    assert tennis.kind == "event"
    assert tennis.sport == "Tennis"
    assert tennis.title == "US Open Tennis"


def test_linear_matchup_is_not_espn_plus():
    from yttv_epg.parse import is_espn_plus

    payload = {
        "epgAiringRenderer": {
            "title": {"simpleText": "Cowboys vs Giants"},
            "station": {
                "epgStationRenderer": {
                    "icon": {"accessibility": {"accessibilityData": {"label": "TNT"}}}
                }
            },
            "navigationEndpoint": {"watchEndpoint": {"videoId": "tnteventxx1"}},
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].kind == "event"
    assert not is_espn_plus(airings[0].station, airings[0].title)


def test_nat_geo_wild_matchup_is_not_a_sports_event():
    payload = {
        "epgAiringRenderer": {
            "title": {"simpleText": "Cougars vs Wolves"},
            "station": {
                "epgStationRenderer": {
                    "icon": {"accessibility": {"accessibilityData": {"label": "Nat Geo Wild"}}}
                }
            },
            "navigationEndpoint": {"watchEndpoint": {"videoId": "natgeowild1"}},
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].station == "Nat Geo Wild"
    assert airings[0].kind != "event"


def test_popup_watch_endpoint():
    payload = {
        "epgAiringRenderer": {
            "title": {"simpleText": "Home feed"},
            "navigationEndpoint": {
                "unpluggedPopupEndpoint": {
                    "popupRenderer": {
                        "unpluggedSelectionMenuDialogRenderer": {
                            "items": [
                                {
                                    "unpluggedMenuItemRenderer": {
                                        "command": {
                                            "watchEndpoint": {"videoId": "qwertyuiopa"}
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            },
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].video_id == "qwertyuiopa"


def test_linear_simulcast_beats_espn_plus():
    from datetime import timedelta

    from yttv_epg.parse import Airing, merge_airings

    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=3)
    linear = Airing(
        video_id="abc7linear01",
        title="East Carolina at Alabama",
        station="ABC 7",
        kind="event",
        start=start,
        end=end,
        deeplink="https://tv.youtube.com/watch/abc7linear01",
        channel="ABC",
    )
    extra = Airing(
        video_id="espnplusxxx1",
        title="East Carolina at Alabama",
        station="ESPN Unlimited",
        kind="event",
        start=start + timedelta(seconds=2),
        end=end,
        deeplink="https://tv.youtube.com/watch/espnplusxxx1",
        channel="ESPN+",
    )
    merged = merge_airings([extra, linear])
    assert len(merged) == 1
    assert merged[0].station == "ABC 7"


def test_duplicate_video_and_start_keeps_longer_title():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    payload = {
        "contents": [
            {
                "watchEndpoint": {"videoId": "YGUvoKVT5qk"},
                "title": {"simpleText": "Game"},
                "startTime": int(now.timestamp()),
            },
            {
                "epgAiringRenderer": {
                    "title": {"simpleText": "UConn vs Maryland"},
                    "navigationEndpoint": {"watchEndpoint": {"videoId": "YGUvoKVT5qk"}},
                    "startTime": int(now.timestamp()),
                }
            },
        ]
    }
    airings = parse_browse(payload, now=now, fallback_minutes=60)
    matches = [item for item in airings if item.video_id == "YGUvoKVT5qk"]
    assert len(matches) == 1
    assert matches[0].title == "UConn vs Maryland"


def test_same_watch_id_merges_across_entity_ids():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    ts = str(int(now.timestamp()))
    payload = {
        "contents": [
            {
                "unpluggedVideoRenderer": {
                    "navigationEndpoint": {"watchEndpoint": {"videoId": "tR-JpuY763Q"}},
                    "entityPageNavigationEndpoint": {
                        "browseEndpoint": {"browseId": "UCYcBS3Z_sOJFVZmq8E5DotQ"}
                    },
                    "primaryText": {"runs": [{"text": "NEC Nijmegen vs. Feyenoord"}]},
                    "secondaryText": {"runs": [{"text": "ESPN+"}]},
                    "startTimeSeconds": ts,
                    "endTimeSeconds": str(int(now.timestamp()) + 7500),
                }
            },
            {
                "unpluggedVideoRenderer": {
                    "navigationEndpoint": {"watchEndpoint": {"videoId": "tR-JpuY763Q"}},
                    "primaryText": {"runs": [{"text": "N.E.C. vs. Feyenoord"}]},
                    "secondaryText": {"runs": [{"text": "ESPN+"}]},
                    "startTimeSeconds": ts,
                    "endTimeSeconds": str(int(now.timestamp()) + 7500),
                }
            },
        ]
    }
    airings = parse_browse(payload, now=now, fallback_minutes=60)
    matches = [item for item in airings if item.watch_id() == "tR-JpuY763Q"]
    assert len(matches) == 1


def test_unplugged_video_card_is_espn_plus():
    start = 1788618300
    payload = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "tR-JpuY763Q"}},
            "primaryText": {"runs": [{"text": "NEC Nijmegen vs. Feyenoord"}]},
            "secondaryText": {"runs": [{"text": "ESPN+"}]},
            "startTimeSeconds": str(start),
            "endTimeSeconds": str(start + 7500),
            "badge": {"unpluggedTextBadgeRenderer": {"label": {"runs": [{"text": "LIVE"}]}, "type": "LIVE"}},
        }
    }
    now = datetime.fromtimestamp(start + 60, tz=timezone.utc)
    airings = parse_browse(payload, now=now, fallback_minutes=60)
    assert len(airings) == 1
    event = airings[0]
    assert event.kind == "event"
    assert event.station == "ESPN+"
    assert event.channel == "ESPN+"
    assert event.title == "NEC Nijmegen vs. Feyenoord"
    assert event.video_id == "tR-JpuY763Q"
    assert event.live is True


def test_home_card_secondary_keeps_network_not_clock():
    payload = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "homeeventx1"}},
            "primaryText": {"runs": [{"text": "Alabama State vs. Gardner-Webb"}]},
            "secondaryText": {"runs": [{"text": "ESPN+ • TODAY, 10:00 AM - 12:00 PM"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].station == "ESPN+"
    assert airings[0].channel == "ESPN+"
    assert airings[0].kind == "event"


def test_date_secondary_is_not_a_channel():
    payload = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "datechanne1"}},
            "primaryText": {"runs": [{"text": "Best of NBA Inside Stuff"}]},
            "secondaryText": {"runs": [{"text": "Sep 4"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].station == ""
    assert airings[0].channel == ""
    assert airings[0].title == "Best of NBA Inside Stuff"


def test_year_school_and_recap_secondaries_are_not_channels():
    year_school = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "yearschool1"}},
            "primaryText": {"runs": [{"text": "Indiana State vs Purdue"}]},
            "secondaryText": {"runs": [{"text": "2026 Indiana State"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    recap = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "darlrecapxx"}},
            "primaryText": {"runs": [{"text": "NASCAR Cup Series at Darlington"}]},
            "secondaryText": {"runs": [{"text": "Darlington Recap"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    war = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "worldatwar1"}},
            "primaryText": {"runs": [{"text": "World at War"}]},
            "secondaryText": {"runs": [{"text": "World at War"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    year_event = parse_browse(year_school, fallback_minutes=60)[0]
    assert year_event.station == ""
    assert year_event.channel == ""
    recap_event = parse_browse(recap, fallback_minutes=60)[0]
    assert recap_event.station == ""
    assert recap_event.channel == ""
    war_airings = parse_browse(war, fallback_minutes=60)
    assert war_airings
    assert war_airings[0].kind != "event"
    assert war_airings[0].station == ""
    assert war_airings[0].channel == ""


def test_date_then_network_keeps_network():
    payload = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "dateespnpl1"}},
            "primaryText": {"runs": [{"text": "Santa Clara vs. Hofstra"}]},
            "secondaryText": {"runs": [{"text": "Sep 4 • ESPN+"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].station == "ESPN+"
    assert airings[0].channel == "ESPN+"


def test_spanish_espn_plus_secondary_is_not_es():
    payload = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"watchEndpoint": {"videoId": "spanishplu1"}},
            "primaryText": {"runs": [{"text": "Rayo Vallecano vs. Real Racing"}]},
            "secondaryText": {"runs": [{"text": "ES • ESPN+"}]},
            "startTimeSeconds": "1788618300",
            "endTimeSeconds": "1788625500",
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert airings[0].station == "ESPN+"
    assert airings[0].channel == "ESPN+"


def test_spanish_espn_plus_badge_counts():
    from yttv_epg.parse import is_espn_plus

    assert is_espn_plus("ES • ESPN+", "Athletic de Bilbao vs. Atlético de Madrid")
    assert not is_espn_plus("SEC+", "Kentucky vs Tennessee")


def test_upcoming_without_watch_id_is_kept_with_entity():
    payload = {
        "unpluggedVideoRenderer": {
            "navigationEndpoint": {"browseEndpoint": {"browseId": "UCYcBS3Z_sOJFVZmq8E5DotQ"}},
            "entityPageNavigationEndpoint": {"browseEndpoint": {"browseId": "UCYcBS3Z_sOJFVZmq8E5DotQ"}},
            "primaryText": {"runs": [{"text": "Santa Clara vs. Hofstra"}]},
            "secondaryText": {"runs": [{"text": "ESPN+"}]},
            "startTimeSeconds": "1788618600",
            "endTimeSeconds": "1788625800",
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert len(airings) == 1
    assert airings[0].entity_id == "UCYcBS3Z_sOJFVZmq8E5DotQ"
    assert airings[0].watch_id() == ""
    assert airings[0].deeplink == ""
    assert airings[0].kind == "event"


def test_sign_off_is_ignored():
    payload = {
        "epgAiringRenderer": {
            "title": {"simpleText": "SIGN OFF"},
            "station": {
                "epgStationRenderer": {
                    "icon": {"accessibility": {"accessibilityData": {"label": "NBCSN Extra"}}}
                }
            },
            "navigationEndpoint": {"watchEndpoint": {"videoId": "signoffxxxx"}},
        }
    }
    assert parse_browse(payload, fallback_minutes=60) == []


def test_discover_event_hubs_from_espn_row():
    from yttv_epg.parse import discover_event_hubs

    payload = {
        "epgRowRenderer": {
            "station": {
                "epgStationRenderer": {
                    "icon": {"accessibility": {"accessibilityData": {"label": "ESPN"}}},
                    "navigationEndpoint": {"browseEndpoint": {"browseId": "UCakwQ1jKQnYJcUMghvnp-Yw"}},
                }
            },
            "airings": [
                {
                    "epgAiringRenderer": {
                        "primaryText": {"runs": [{"text": "Watch live sports, studio shows and originals on ESPN"}]},
                        "navigationEndpoint": {"browseEndpoint": {"browseId": "UCakwQ1jKQnYJcUMghvnp-Yw"}},
                        "tertiaryContainer": [
                            {"unpluggedTextRenderer": {"text": {"runs": [{"text": "2 more live events on now."}]}}}
                        ],
                    }
                }
            ],
        }
    }
    assert discover_event_hubs(payload) == ["UCakwQ1jKQnYJcUMghvnp-Yw"]


def test_discover_numbered_extra_hubs_before_espn():
    from yttv_epg.parse import discover_browse_tabs, discover_event_hubs, keep_hub_tab

    payload = {
        "rows": [
            {
                "epgRowRenderer": {
                    "station": {
                        "epgStationRenderer": {
                            "icon": {"accessibility": {"accessibilityData": {"label": "ESPN"}}},
                            "navigationEndpoint": {"browseEndpoint": {"browseId": "UCakwQ1jKQnYJcUMghvnp-Yw"}},
                        }
                    }
                }
            },
            {
                "epgRowRenderer": {
                    "station": {
                        "epgStationRenderer": {
                            "icon": {"accessibility": {"accessibilityData": {"label": "NBCSN Extra 4"}}},
                            "navigationEndpoint": {"browseEndpoint": {"browseId": "UCnbcsnextra000000000001"}},
                        }
                    }
                }
            },
        ]
    }
    assert discover_event_hubs(payload) == [
        "UCnbcsnextra000000000001",
        "UCakwQ1jKQnYJcUMghvnp-Yw",
    ]
    tabs = discover_browse_tabs(
        {
            "tabs": [
                {
                    "tabRenderer": {
                        "title": {"simpleText": "LIVE"},
                        "selected": True,
                        "endpoint": {"browseEndpoint": {"browseId": "UCakwQ1jKQnYJcUMghvnp-Yw"}},
                    }
                },
                {
                    "tabRenderer": {
                        "title": {"simpleText": "UPCOMING"},
                        "endpoint": {
                            "browseEndpoint": {
                                "browseId": "UCakwQ1jKQnYJcUMghvnp-Yw",
                                "params": "upcoming-params",
                            }
                        },
                    }
                },
                {
                    "tabRenderer": {
                        "title": {"simpleText": "Replay"},
                        "endpoint": {
                            "browseEndpoint": {
                                "browseId": "UCakwQ1jKQnYJcUMghvnp-Yw",
                                "params": "replay-params",
                            }
                        },
                    }
                },
            ]
        }
    )
    assert [tab["title"] for tab in tabs] == ["LIVE", "UPCOMING", "Replay"]
    assert keep_hub_tab("UPCOMING")
    assert not keep_hub_tab("Replay")
    assert tabs[1]["params"] == "upcoming-params"


def test_game_card_upcoming_is_kept():
    payload = {
        "unpluggedGameCardRenderer": {
            "entityPageNavigationEndpoint": {"browseEndpoint": {"browseId": "UCYcBS3Z_sOJFVZmq8E5DotQ"}},
            "primaryText": {"runs": [{"text": "Michigan vs. Oklahoma"}]},
            "secondaryText": {"runs": [{"text": "ESPN+"}]},
            "startTimeSeconds": "1788700000",
            "endTimeSeconds": "1788707200",
        }
    }
    airings = parse_browse(payload, fallback_minutes=60)
    assert len(airings) == 1
    assert airings[0].title == "Michigan vs. Oklahoma"
    assert airings[0].watch_id() == ""
    assert airings[0].kind == "event"


def test_upcoming_tab_continuation_and_sports_chip():
    from yttv_epg.parse import discover_browse_tabs, discover_sports_chips

    payload = {
        "tabs": [
            {
                "tabRenderer": {
                    "title": {"simpleText": "UPCOMING"},
                    "endpoint": {"browseEndpoint": {"browseId": "UCakwQ1jKQnYJcUMghvnp-Yw"}},
                    "content": {
                        "sectionListRenderer": {
                            "continuations": [
                                {
                                    "reloadContinuationData": {
                                        "continuation": "abcdefghijklmnopqrstuvwxyz0123456789"
                                    }
                                }
                            ]
                        }
                    },
                }
            }
        ],
        "chips": [
            {
                "chipCloudChipRenderer": {
                    "text": {"simpleText": "Sports"},
                    "navigationEndpoint": {
                        "browseEndpoint": {"browseId": "FEunplugged_chips", "params": "sports-params"}
                    },
                }
            }
        ],
    }
    tabs = discover_browse_tabs(payload)
    assert tabs[0]["continuation"].startswith("abcdefghijklmnopqrstuvwxyz")
    chips = discover_sports_chips(payload)
    assert chips[0]["browse_id"] == "FEunplugged_chips"
    assert chips[0]["params"] == "sports-params"


def test_same_matchup_on_different_days_is_kept():
    from datetime import timedelta

    from yttv_epg.parse import Airing, merge_airings

    start = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    first = Airing(
        video_id="saturdaygm1",
        title="East Carolina at Alabama",
        station="ABC 7",
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/saturdaygm1",
        channel="ABC",
    )
    second = Airing(
        video_id="sundaygame1",
        title="East Carolina at Alabama",
        station="ESPN",
        kind="event",
        start=start + timedelta(hours=24),
        end=start + timedelta(hours=27),
        deeplink="https://tv.youtube.com/watch/sundaygame1",
        channel="ESPN",
    )
    merged = merge_airings([first, second])
    assert {item.video_id for item in merged} == {"saturdaygm1", "sundaygame1"}
