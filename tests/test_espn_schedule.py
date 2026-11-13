from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yttv_epg.espn_schedule import (
    EspnListing,
    apply_espn_sports,
    matchup_teams,
    parse_airings_payload,
    upcoming_days,
)
from yttv_epg.parse import Airing
from yttv_epg.sports import infer_sport, resolve_sport


def _airing(title: str, station: str, start: datetime, sport: str = "") -> Airing:
    return Airing(
        video_id="YGUvoKVT5qk",
        title=title,
        station=station,
        kind="event",
        start=start,
        end=start + timedelta(hours=3),
        deeplink="https://tv.youtube.com/watch/YGUvoKVT5qk",
        sport=sport or infer_sport(title, station),
    )


def test_matchup_teams_ignore_rankings_and_language():
    english = matchup_teams("East Carolina vs. #13 Alabama")
    at_home = matchup_teams("East Carolina at Alabama")
    spanish = matchup_teams("En Español-East Carolina vs. #13 Alabama")
    sky = matchup_teams("SkyCast - East Carolina vs. #13 Alabama (SkyCast)")
    assert english == at_home == spanish == sky
    assert matchup_teams("UAlbany vs. Cornell") == matchup_teams("Albany vs. Cornell")
    assert matchup_teams("Miami (OH) vs. Pittsburgh") == matchup_teams("Miami Ohio vs. Pittsburgh")


def test_parse_live_graph_payload():
    payload = {
        "data": {
            "airings": [
                {
                    "name": "Elon vs. Eastern Michigan",
                    "startDateTime": "2026-09-05T16:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Volleyball"},
                    "league": {"name": "NCAA Women's Volleyball"},
                    "category": {"name": "Volleyball"},
                },
                {
                    "name": "Liberty vs. James Madison",
                    "startDateTime": "2026-09-05T16:04:57.415Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Football"},
                    "league": {"name": "NCAA Football"},
                    "category": {"name": "Football"},
                },
                {
                    "name": "SEC Halftime Band Performances at Alabama",
                    "startDateTime": "2026-09-05T17:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Football"},
                    "league": {"name": "NCAA Football"},
                    "category": {"name": "Football"},
                },
                {
                    "name": "Army vs. Dartmouth",
                    "startDateTime": "2026-09-05T15:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Rugby"},
                    "league": {"name": "NCAA Women's Rugby"},
                    "category": {"name": "Rugby"},
                },
            ]
        }
    }
    listings = parse_airings_payload(payload)
    sports = {item.name: item.sport for item in listings}
    assert sports["Elon vs. Eastern Michigan"] == "Volleyball"
    assert sports["Liberty vs. James Madison"] == "Football"
    assert sports["Army vs. Dartmouth"] == "Rugby"
    assert "SEC Halftime Band Performances at Alabama" not in sports


def test_espn_live_schedule_corrects_college_extras():
    noon = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    listings = [
        EspnListing("Elon vs. Eastern Michigan", "Volleyball", noon),
        EspnListing("Army vs. UT Arlington", "Volleyball", noon),
        EspnListing("Binghamton vs. Sacred Heart", "Volleyball", noon),
        EspnListing("Liberty vs. James Madison", "Football", noon + timedelta(minutes=5)),
        EspnListing("East Carolina vs. #13 Alabama", "Football", noon),
        EspnListing("Army vs. Dartmouth", "Rugby", noon - timedelta(hours=1)),
        EspnListing("Elon vs. Davidson", "Football", noon + timedelta(hours=6)),
    ]
    rows = apply_espn_sports(
        [
            _airing("Elon vs. Eastern Michigan", "ESPN", noon),
            _airing("Army vs. UT Arlington", "ESPN", noon),
            _airing("Binghamton vs. Sacred Heart", "ESPN", noon),
            _airing("Liberty vs. James Madison", "ESPNU", noon),
            _airing("East Carolina at Alabama", "ABC 7", noon),
            _airing("Army vs. Dartmouth", "ESPN+", noon),
            _airing("Princeton vs. La Salle", "ESPN+", noon),
        ],
        listings,
    )
    by_title = {item.title: item.sport for item in rows}
    assert infer_sport("Elon vs. Eastern Michigan", "ESPN") == "Football"
    assert by_title["Elon vs. Eastern Michigan"] == "Volleyball"
    assert by_title["Army vs. UT Arlington"] == "Volleyball"
    assert by_title["Binghamton vs. Sacred Heart"] == "Volleyball"
    assert by_title["Liberty vs. James Madison"] == "Football"
    assert by_title["East Carolina at Alabama"] == "Football"
    assert by_title["Army vs. Dartmouth"] == "Rugby"
    assert by_title["Princeton vs. La Salle"] == "Other"


def test_espn_uses_start_time_when_same_teams_play_two_sports():
    noon = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    listings = [
        EspnListing("Liberty vs. James Madison", "Field Hockey", noon - timedelta(hours=1)),
        EspnListing("Liberty vs. James Madison", "Football", noon),
    ]
    football = apply_espn_sports([_airing("Liberty vs. James Madison", "ESPNU", noon)], listings)
    hockey = apply_espn_sports(
        [_airing("Liberty vs. James Madison", "ESPN+", noon - timedelta(hours=1))],
        listings,
    )
    assert football[0].sport == "Football"
    assert hockey[0].sport == "Field Hockey"


def test_espn_does_not_override_tennis_or_empty_cache():
    start = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc)
    tennis = _airing("(22) Keys vs. Zheng (Women's Third Round)", "ESPN Unlimited", start)
    assert tennis.sport == "Tennis"
    labeled = apply_espn_sports(
        [tennis],
        [EspnListing("(22) Keys vs. Zheng (Women's Third Round)", "Football", start)],
    )
    assert labeled[0].sport == "Tennis"
    leftover = apply_espn_sports([_airing("Navy vs. Brown", "ESPN+", start, "Other")], [])
    assert leftover[0].sport == "Other"


def test_upcoming_days_cover_the_watch_espn_day_tabs():
    now = datetime(2026, 9, 5, 17, 35, tzinfo=timezone.utc)
    assert upcoming_days(now, count=3) == ["2026-09-05", "2026-09-06", "2026-09-07"]


def test_parse_upcoming_field_hockey_and_rugby():
    payload = {
        "data": {
            "airings": [
                {
                    "name": "Liberty vs. James Madison",
                    "startDateTime": "2026-09-06T16:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Field Hockey"},
                    "league": {"name": "CFHOC"},
                    "category": {"name": "Field Hockey"},
                },
                {
                    "name": "Southern Nazarene vs. Lindenwood",
                    "startDateTime": "2026-09-06T16:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Rugby"},
                    "league": {"name": "CWRUG"},
                    "category": {"name": "Rugby"},
                },
                {
                    "name": "Harvard vs. UC Davis",
                    "startDateTime": "2026-09-06T16:30:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Water Polo"},
                    "league": {"name": "NCAAM Water Polo"},
                    "category": {"name": "Water Polo"},
                },
            ]
        }
    }
    sports = {item.name: item.sport for item in parse_airings_payload(payload)}
    assert sports["Liberty vs. James Madison"] == "Field Hockey"
    assert sports["Southern Nazarene vs. Lindenwood"] == "Rugby"
    assert sports["Harvard vs. UC Davis"] == "Water Polo"


def test_upcoming_day_does_not_relabel_todays_football():
    saturday = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    sunday = datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc)
    listings = [
        EspnListing("Liberty vs. James Madison", "Football", saturday),
        EspnListing("Liberty vs. James Madison", "Field Hockey", sunday),
        EspnListing("Southern Nazarene vs. Lindenwood", "Rugby", sunday),
        EspnListing("Harvard vs. UC Davis", "Water Polo", sunday + timedelta(minutes=30)),
    ]
    rows = apply_espn_sports(
        [
            _airing("Liberty at James Madison", "ESPNU", saturday),
            _airing("Liberty vs. James Madison", "ESPN+", sunday),
            _airing("Southern Nazarene vs. Lindenwood", "ESPN+", sunday, "Other"),
            _airing("Harvard vs. UC Davis", "ESPN+", sunday, "Other"),
        ],
        listings,
    )
    by_title = {item.title: item.sport for item in rows}
    assert by_title["Liberty at James Madison"] == "Football"
    assert by_title["Liberty vs. James Madison"] == "Field Hockey"
    assert by_title["Southern Nazarene vs. Lindenwood"] == "Rugby"
    assert by_title["Harvard vs. UC Davis"] == "Water Polo"


def test_espn_plus_uses_schedule_sport_for_named_streams():
    noon = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)
    listings = [
        EspnListing("Court 8", "Tennis", noon),
        EspnListing("Court 13", "Tennis", noon),
        EspnListing("2026 US Open Court 4", "Tennis", noon),
        EspnListing("Mobile Big Game Fishing Classic", "Fishing", noon),
        EspnListing("Kansas City vs. Drake", "Soccer", noon),
    ]
    rows = apply_espn_sports(
        [
            _airing("Court 8", "ESPN Unlimited", noon, "Other"),
            _airing("Court 4", "ESPN Unlimited", noon, "Other"),
            _airing("Court 18", "ESPN Unlimited", noon, "Other"),
            _airing("Mobile Big Game Fishing Classic", "ESPN+", noon, "Other"),
            _airing("Kansas City vs. Drake", "ESPN+", noon),
            _airing("Princeton vs. La Salle", "ESPN+", noon, "Other"),
        ],
        listings,
    )
    by_title = {item.title: item.sport for item in rows}
    assert by_title["Court 8"] == "Tennis"
    assert by_title["Court 4"] == "Tennis"
    assert by_title["Court 18"] == "Other"
    assert by_title["Mobile Big Game Fishing Classic"] == "Fishing"
    assert by_title["Kansas City vs. Drake"] == "Soccer"
    assert by_title["Princeton vs. La Salle"] == "Other"


def test_parse_keeps_espn_plus_courts_and_fishing():
    payload = {
        "data": {
            "airings": [
                {
                    "name": "Court 8",
                    "startDateTime": "2026-09-07T16:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Tennis"},
                    "league": {"name": "US Open"},
                    "category": {"name": "Tennis"},
                },
                {
                    "name": "Mobile Big Game Fishing Classic",
                    "startDateTime": "2026-09-07T16:00:00Z",
                    "program": {"isStudio": False},
                    "sport": {"name": "Fishing"},
                    "league": {"name": "Fishing"},
                    "category": {"name": "Fishing"},
                },
            ]
        }
    }
    sports = {item.name: item.sport for item in parse_airings_payload(payload)}
    assert sports["Court 8"] == "Tennis"
    assert sports["Mobile Big Game Fishing Classic"] == "Fishing"


def test_resolve_sport_keeps_stored_volleyball_over_school_name_football():
    assert infer_sport("Elon vs. Eastern Michigan", "ESPN") == "Football"
    assert resolve_sport("Elon vs. Eastern Michigan", "ESPN", stored="Volleyball") == "Volleyball"
    assert resolve_sport("Liberty vs. James Madison", "ESPNU", stored="Football") == "Football"
    assert resolve_sport("Fairleigh Dickinson vs. Lafayette", "ESPN+", stored="Rugby") == "Rugby"


def test_espn_fills_placeholder_kickoff_from_team_names():
    from dataclasses import replace

    noon = datetime(2026, 9, 12, 16, 0, tzinfo=timezone.utc)
    kickoff = datetime(2026, 9, 12, 19, 30, tzinfo=timezone.utc)
    scheduled = _airing("Penn State Nittany Lions at Temple Owls", "ESPN2", noon, "Football")
    pending = replace(scheduled, start_source="date", end_estimated=True)
    listing = EspnListing("Penn State vs Temple", "Football", kickoff, network="ESPN2",
                          end=kickoff + timedelta(hours=4))

    corrected, unchanged = apply_espn_sports([pending, scheduled], [listing])
    assert corrected.start == kickoff and corrected.start_source == "espn"
    assert corrected.end == listing.end and not corrected.end_estimated
    assert corrected.sport == "Football"
    assert unchanged.start == noon and unchanged.end == scheduled.end
    assert apply_espn_sports([pending], [replace(listing, network="ESPN+")])[0] == pending
    assert apply_espn_sports([pending], [listing, replace(listing, start=noon)])[0] == pending
    assert apply_espn_sports([replace(pending, is_repeat=True)], [listing])[0].start == noon

    without_end = apply_espn_sports([pending], [replace(listing, end=None)])[0]
    assert without_end.end_estimated and without_end.end - kickoff == pending.end - noon


def test_reported_uconn_broadcaster_corrected_from_official_schedule():
    from dataclasses import replace
    start = datetime(2026, 10, 17, 19, tzinfo=timezone.utc)
    game = _airing("#8 UConn vs. #7 Princeton", "ESPN", start)
    game.station_logo = "https://example.com/espn.png"
    listing = EspnListing(game.title, "Hockey", start, network="ESPN+")
    corrected = apply_espn_sports([game], [listing])[0]
    assert corrected.station == corrected.channel == "ESPN+"
    assert corrected.station_logo == ""
    assert corrected.sport == "Hockey"
    assert corrected.deeplink == game.deeplink
    assert corrected.broadcast_live == game.broadcast_live
    for listings in (
        [replace(listing, start=start + timedelta(days=1))],
        [replace(listing, start=start + timedelta(minutes=6))],
        [replace(listing, name="UConn vs Princeton")],
        [listing, replace(listing, network="ESPN")],
        [listing, replace(listing, network="")],
    ):
        assert apply_espn_sports([game], listings)[0].station == "ESPN"
    assert apply_espn_sports([replace(game, station="ESPN2")], [listing])[0].station == "ESPN2"


def test_schedule_keeps_conflicting_broadcasters_for_same_game():
    rows = [{"name": "UConn vs Princeton", "sport": {"name": "Hockey"},
             "startDateTime": "2026-10-17T19:00:00Z", "network": {"name": network}}
            for network in ("ESPN", "ESPN+")]
    assert {row.network for row in parse_airings_payload({"data": {"airings": rows}})} == {"ESPN", "ESPN+"}
