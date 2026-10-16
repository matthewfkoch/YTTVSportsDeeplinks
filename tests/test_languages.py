from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from yttv_epg.languages import broadcast_language, detect_language
from yttv_epg.parse import Airing, merge_airings, parse_browse
from yttv_epg.sports import visible_events


@pytest.mark.parametrize('station', ['ESPN Deportes','TUDN','Telemundo','Universo','Univision','UniMás','beIN SPORTS en Español','ViX Premium Deportes 12'])
def test_spanish_station_identities(station):
    assert detect_language(station) == 'es'


@pytest.mark.parametrize('label', ['En Español: Alabama at Georgia','Alabama at Georgia (Spanish)','Spanish-language broadcast','EN ESPANOL'])
def test_spanish_labels(label):
    assert detect_language('ESPN+', label) == 'es'


def test_unknown_and_explicit_languages():
    assert detect_language('ESPN+', 'Atlético de Madrid vs. Manchester United') == ''
    now = datetime(2026,10,20,tzinfo=timezone.utc)
    event = Airing('abcdefghijk','Game','ESPN+','event',now,now+timedelta(hours=2),'',language='en-US')
    assert broadcast_language(event) == 'en'


def test_parse_explicit_language_and_preserve_variants_before_deduplication():
    now = datetime(2026,10,20,tzinfo=timezone.utc)
    def card(watch, lang):
        return {'unpluggedVideoRenderer':{'videoId':watch,'title':{'simpleText':'Alabama at Georgia'},
                'stationName':'ESPN+','startTime':int(now.timestamp()),'endTime':int(now.timestamp())+7200,
                'audioLanguage':lang}}
    events = parse_browse([card('abcdefghijk','es-MX'),card('lmnopqrstuv','en')],now=now)
    assert len(events) == 2
    assert {broadcast_language(e) for e in events} == {'en','es'}
    assert len(merge_airings(events)) == 2
    visible = visible_events(events, hide_spanish=True, require_watch_link=True)
    assert len(visible) == 1
    assert visible[0].video_id == 'lmnopqrstuv'


def test_reconstructed_game_card_keeps_language_label():
    payload = {'unpluggedGameCardRenderer':{
        'primaryText':{'simpleText':'Tue 7:00 PM • ESPN+'},
        'secondaryText':{'simpleText':'En Español • Football'},
        'startTeamPrimaryText':{'simpleText':'Alabama'},'endTeamPrimaryText':{'simpleText':'Georgia'},
        'startTime':1792522800,'endTime':1792530000,
        'navigationEndpoint':{'watchEndpoint':{'videoId':'abcdefghijk'}},
    }}
    events = parse_browse(payload)
    assert len(events) == 1
    assert events[0].language == 'es'


@pytest.mark.parametrize("title", ["Spanish Fort at Alabama", "Spanish Springs vs. Reno", "English at Kentucky"])
def test_team_names_are_not_language_labels(title):
    assert detect_language("ESPN+", title) == ""
