from __future__ import annotations

from yttv_epg.sports import (
    channel_counts,
    infer_channel,
    infer_sport,
    resolve_sport,
    is_extra_station,
    is_junk,
    is_matchup,
    is_non_sports_station,
    is_sports_event,
    parse_sport_list,
    visible_events,
)


def test_movie_at_is_not_a_matchup():
    assert not is_matchup("Night at the Museum")
    assert is_matchup("East Carolina at Alabama")
    assert is_matchup("Brentford vs. Sunderland")


def test_extras_and_volleyball_are_sports_events():
    assert is_sports_event("NBCSN Extra", "Brentford vs. Sunderland")
    assert is_sports_event("ESPN+", "Santa Clara vs. Hofstra")
    assert not is_sports_event("ESPN Unlimited", "US Open Radio", sport="Tennis")
    assert is_sports_event("T2", "2026 WTA Cincinnati")
    assert not is_sports_event("NBA TV", "Best of NBA Inside Stuff")
    assert not is_sports_event("ESPNU", "College Football 150: The American Game")
    assert not is_sports_event("NBA TV", "Best of NBA Action")
    assert not is_sports_event("ESPN", "College Football Scoreboard", sport="Football")
    assert not is_sports_event("TBS", "Practical Magic")
    assert is_sports_event("Golf Channel", "Day 1")
    assert is_sports_event("NBCSN Extra", "Day 2")
    assert not is_sports_event("ESPN Unlimited", "2026 US Open Radio Presented by American Express (Day 7)")
    assert is_sports_event("ESPN+", "Mobile Big Game Fishing Club Labor Day Invitational (Day 2)")
    assert not is_sports_event("NFL Network", "2025: Chicago Bears vs. San Francisco 49ers")
    assert not is_sports_event("NFL Network", "2025 NFC Divisional: Los Angeles Rams vs. Chicago Bears")
    assert infer_sport("Practical Magic", "TBS") == "Other"
    assert infer_sport("Celtics vs. Lakers", "NBA TV") == "Basketball"
    assert infer_sport("Fleetio 200 at Darlington Practice & Qualifying", "CW Sports") == "Motorsports"
    assert infer_sport("Villarreal CF vs. Deportivo de La Coruña", "ESPN+") == "Soccer"
    assert infer_sport("Wyoming at Colorado State", "USA") == "Football"
    assert infer_sport("Mobile Big Game Fishing Club Labor Day Invitational (Day 2)", "ESPN+") == "Fishing"
    assert infer_sport("Day 2", "NBCSN Extra") == "Horse Racing"
    assert infer_sport("Day 1", "Golf Channel") == "Golf"
    assert is_sports_event("Kentucky Downs: Day 4", "NBCSN Extra")
    assert is_sports_event("2026 WTA Cincinnati", "T2")
    assert not is_sports_event("HBCU GO", "HBCU Football Coaching Legends", sport="Football")
    assert not is_sports_event("ION", "NWSL On ION Pre Match Show", sport="Soccer")
    assert is_sports_event("theGRIO", "North Carolina Central at Texas Southern")
    assert is_sports_event("ION", "Gotham FC vs. Kansas City Current")
    assert infer_channel("Best of NBA Inside Stuff") == ""
    assert infer_channel("College Football 150: The American Game") == ""
    assert is_junk("SIGN OFF", "NBCSN Extra")
    assert infer_sport("NCAAW Volleyball", "", "NCAAW Volleyball") == "Volleyball"
    assert infer_sport("Brentford vs. Sunderland", "NBCSN Extra") == "Soccer"
    assert infer_sport("Brentford vs. Sunderland", "NBCSN Extra 4") == "Soccer"
    assert infer_sport("Liberty at James Madison", "ESPNU") == "Football"
    assert infer_sport("Oklahoma State at Tulsa", "ESPNU") == "Football"
    assert infer_sport("Western Michigan at Michigan", "NBC Sports 4K") == "Football"
    assert infer_sport("Hull City vs. Aston Villa", "NBC Sports 4K") == "Soccer"
    assert infer_sport("New York Yankees at San Diego Padres", "FOX 2") == "Baseball"
    assert infer_sport("Internazionale vs. Napoli", "CBS 62") == "Soccer"
    assert infer_sport("Sporting Gijón vs. Girona FC (Matchday #4)", "ESPN+") == "Soccer"
    assert infer_sport("(10) Anisimova vs. (24) Potapova (Women's Third Round)", "ESPN Unlimited") == "Tennis"
    assert infer_sport("Granollers/Zeballos vs. Jebens/Reyes-Varela (Men's Doubles First Round)", "ESPN+") == "Tennis"
    assert infer_sport("Baylor vs. Auburn", "ABC 7") == "Football"
    assert infer_sport("Kentucky Downs: Day 4", "NBCSN Extra") == "Horse Racing"
    assert infer_sport("Breeders' Cup Classic", "FS2") == "Horse Racing"
    assert infer_sport("Saratoga Live", "FS2") == "Horse Racing"
    assert infer_sport("NASCAR Cup Series at Darlington", "FS1") == "Motorsports"
    assert infer_sport("Formula 1: Italian Grand Prix", "ESPN") == "Motorsports"
    assert infer_sport("IndyCar Grand Prix", "USA") == "Motorsports"
    assert infer_sport("Rayo Vallecano vs. Real Racing", "ESPN+") == "Soccer"
    assert is_sports_event("NBCSN Extra", "Kentucky Downs: Day 4")
    assert is_sports_event("FS1", "NASCAR Cup Series at Darlington")
    assert infer_sport("Disc Golf Pro Tour", "ESPNews") == "Disc Golf"
    assert infer_sport("Fairleigh Dickinson vs. Lafayette", "ESPN+") == "Other"
    assert infer_sport("Court 8", "ESPN Unlimited") == "Tennis"
    assert infer_sport("United States vs. Czechia", "truTV") == "Hockey"
    assert infer_sport("Race Day Live: Columbus", "NBCSN Extra") == "Horse Racing"
    assert not is_sports_event("Telemundo", "El señor de los cielos: Extras")
    assert not is_sports_event("NBCSN Extra", "The Dan Patrick Show")
    assert is_sports_event("ESPN Unlimited", "Court 4")
    assert infer_sport("Elon vs. Eastern Michigan", "ESPN") == "Football"
    assert resolve_sport("Elon vs. Eastern Michigan", "ESPN", stored="Volleyball") == "Volleyball"
    assert is_junk("FOX 2 News at 10pm", "FOX 2")
    assert is_extra_station("NBCSN Extra 4")
    assert is_extra_station("NBC Sports Extra")
    assert not is_extra_station("ESPN")
    assert parse_sport_list("Volleyball, Field Hockey") == ["Volleyball", "Field Hockey"]


def test_visible_events_hides_sports():
    class Row:
        def __init__(self, sport: str) -> None:
            self.sport = sport

    rows = [Row("Football"), Row("Volleyball"), Row("Soccer")]
    visible = visible_events(rows, ["Volleyball"])
    assert [item.sport for item in visible] == ["Football", "Soccer"]


def test_infer_channel_families():
    assert infer_channel("ESPN Unlimited") == "ESPN+"
    assert infer_channel("ESPN+") == "ESPN+"
    assert infer_channel("ESPN") == "ESPN"
    assert infer_channel("ESPN2") == "ESPN"
    assert infer_channel("NBCSN Extra 4") == "NBC Sports Extra"
    assert infer_channel("NBC Sports Extra") == "NBC Sports Extra"
    assert infer_channel("BTN Overflow 1") == "Big Ten Extra"
    assert infer_channel("BTN") == "Big Ten"
    assert infer_channel("CBS Sports Network") == "CBS Sports"
    assert infer_channel("CBS") == "CBS"
    assert infer_channel("FS1") == "Fox Sports"
    assert infer_channel("FOX SPORTS 1") == "Fox Sports"
    assert infer_channel("SEC Network") == "SEC Network"
    assert infer_channel("SEC+") == "SEC+"
    assert infer_channel("ACC Network Extra") == "ACC Extra"
    assert infer_channel("ACC Network") == "ACC Network"
    assert infer_channel("TruTV") == "TruTV"
    assert infer_channel("CW") == "CW"
    assert infer_channel("Big 12 Extra 2") == "Big 12 Extra 2"
    assert infer_channel("MLB Network") == "MLB Network"
    assert infer_channel("Sep 4") == ""
    assert infer_channel("Sep4") == ""
    assert infer_channel("Oct 8", "College Football 150: The American Game") == ""
    assert infer_channel("Hallmark Mystery") == "Hallmark Mystery"
    assert infer_channel("ES") == "ESPN+"


def test_visible_events_hides_channels():
    class Row:
        def __init__(self, sport: str, station: str, channel: str) -> None:
            self.sport = sport
            self.station = station
            self.title = "Team vs Team"
            self.channel = channel

    rows = [
        Row("Soccer", "ESPN+", "ESPN+"),
        Row("Soccer", "ESPN", "ESPN"),
        Row("Soccer", "NBCSN Extra 4", "NBC Sports Extra"),
    ]
    visible = visible_events(rows, hidden_channels=["ESPN+"])
    assert [item.station for item in visible] == ["ESPN", "NBCSN Extra 4"]


def test_emma_is_not_mma_and_hallmark_is_not_sports():
    assert infer_sport("Emma Fielding Mysteries", "Hallmark Mystery") == "Other"
    assert infer_sport("UFC 300", "ESPN+") == "Combat"
    assert infer_sport("MMA Fight Night", "ESPN") == "Combat"
    assert not is_sports_event("Hallmark Mystery", "Emma Fielding Mysteries", sport="Combat")
    assert not is_sports_event("ID", "Deadly Influence: The Social Media Murders", sport="Football")
    assert not is_sports_event("Comet TV", "Biography: WWE Legends")
    assert is_sports_event("TruTV", "CCU at WVU")
    assert is_sports_event("theGRIO", "Howard vs. Norfolk State")


def test_visible_events_drops_entertainment_stations():
    class Row:
        def __init__(self, station: str) -> None:
            self.sport = "Combat"
            self.station = station
            self.title = "Emma Fielding Mysteries"
            self.channel = station

        def watch_id(self) -> str:
            return "watchidxxxx"

    rows = [Row("Hallmark Mystery"), Row("ESPN")]
    assert [item.station for item in visible_events(rows, require_watch_link=True)] == ["ESPN"]


def test_non_sports_station_families_stay_out_of_the_guide():
    leaks = [
        ("Nat Geo Wild", "Cougars vs Wolves"),
        ("National Geographic", "Shark vs Tiger"),
        ("Oxygen", "Killer vs Killer"),
        ("Oxygen True Crime", "Buried in the Backyard"),
        ("VH1", "Love & Hip Hop"),
        ("CSPAN", "Hearing at the Capitol"),
        ("C-SPAN", "Washington Journal"),
        ("C-SPAN2", "Senate at Work"),
        ("OAN", "NewsNight"),
        ("Game Show Network", "Celebrity Family Feud"),
        ("Brainerd", "Brainerd at Home"),
        ("Recipe.TV", "Dinner at Giada's"),
        ("Newsmax", "Newsmax Prime"),
        ("Food Network", "Chopped"),
        ("Cooking Channel", "Dinner at Mom's"),
        ("CNN", "CNN Newsroom"),
        ("Fox News", "Fox News at Night"),
        ("BBC America", "Planet Earth: Kingdom"),
    ]
    for station, title in leaks:
        assert is_non_sports_station(station), station
        assert not is_sports_event(station, title, sport="Hockey"), station

    keep = [
        ("ESPN", "Cowboys vs Giants"),
        ("ESPNews", "Lakers vs Celtics"),
        ("FS1", "NASCAR Cup Series at Darlington"),
        ("NFL Network", "Cowboys vs Giants"),
        ("Tennis Channel", "ATP Tour"),
        ("NBCSN Extra", "Kentucky Downs: Day 4"),
        ("ESPN+", "Santa Clara vs. Hofstra"),
        ("FOX Deportes", "Chivas vs America"),
        ("FOX 2", "New York Yankees at San Diego Padres"),
        ("MAVTV", "NHRA Drag Racing"),
        ("Pickleball TV", "Shooters vs Atlas"),
    ]
    for station, title in keep:
        assert not is_non_sports_station(station), station
        assert is_sports_event(station, title), station

    assert infer_sport("Wild vs Predators", "ESPN") == "Hockey"
    assert infer_sport("Cougars vs Wolves", "Nat Geo Wild") == "Other"
    assert infer_sport("Planet Earth: Kingdom", "BBC America") == "Other"
    assert infer_channel("Pickleball TV") == "Pickleball TV"
    assert infer_channel("MAVTV") == "MAVTV"
    assert infer_channel("Nat Geo Wild") == "Nat Geo Wild"


def test_visible_events_and_chips_drop_non_sports_families():
    class Row:
        def __init__(self, station: str, title: str, sport: str = "Hockey") -> None:
            self.sport = sport
            self.station = station
            self.title = title
            self.channel = station

        def watch_id(self) -> str:
            return "watchidxxxx"

    rows = [
        Row("Nat Geo Wild", "Cougars vs Wolves"),
        Row("Oxygen", "Killer vs Killer"),
        Row("C-SPAN2", "Senate at Work", "Other"),
        Row("Recipe.TV", "Dinner at Giada's", "Other"),
        Row("ESPN", "Wild vs Predators"),
        Row("NBCSN Extra", "Kentucky Downs: Day 4", "Horse Racing"),
    ]
    visible = visible_events(rows, require_watch_link=True)
    assert [item.station for item in visible] == ["ESPN", "NBCSN Extra"]
    assert {item["name"] for item in channel_counts(visible)} == {"ESPN", "NBC Sports Extra"}


def test_visible_events_drops_studio_shows():
    class Row:
        def __init__(self, title: str, station: str) -> None:
            self.sport = "Basketball"
            self.station = station
            self.title = title
            self.channel = station

        def watch_id(self) -> str:
            return "watchidxxxx"

    rows = [
        Row("Best of NBA Inside Stuff", "NBA TV"),
        Row("College Football 150: The American Game", "ESPNU"),
        Row("HBCU Football Coaching Legends", "HBCU GO"),
        Row("NWSL On ION Pre Match Show", "ION"),
        Row("Practical Magic", "TBS"),
        Row("Celtics vs. Lakers", "NBA TV"),
        Row("North Carolina Central at Texas Southern", "theGRIO"),
    ]
    assert [item.title for item in visible_events(rows, require_watch_link=True)] == [
        "Celtics vs. Lakers",
        "North Carolina Central at Texas Southern",
    ]


def test_visible_events_can_require_watch_link():
    class Row:
        def __init__(self, sport: str, watch: str) -> None:
            self.sport = sport
            self.station = "ESPN"
            self.title = "Team vs Team"
            self.channel = "ESPN"
            self._watch = watch

        def watch_id(self) -> str:
            return self._watch

    rows = [Row("Soccer", "YGUvoKVT5qk"), Row("Soccer", "")]
    assert [item.watch_id() for item in visible_events(rows)] == ["YGUvoKVT5qk", ""]
    linked = visible_events(rows, require_watch_link=True)
    assert [item.watch_id() for item in linked] == ["YGUvoKVT5qk"]
