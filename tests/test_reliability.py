from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
import json

import httpx
import pytest

from yttv_epg.crypto import encrypt
from yttv_epg.feeds import xmltv
from yttv_epg.innertube import CLIENTS, InnerTubeClient
from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import Airing, merge_airings, parse_browse
from yttv_epg.resolution import unresolved_soon
from yttv_epg.session_store import SavedSession, SessionStore
from xml.etree import ElementTree as ET

NOW = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)


def game(**kwargs):
    values = dict(video_id='abcdefghijk', title='Alabama at Georgia', station='ESPN+', kind='event',
                  start=NOW-timedelta(hours=1), end=NOW+timedelta(hours=2),
                  deeplink='https://tv.youtube.com/watch/abcdefghijk', live=True)
    values.update(kwargs)
    return Airing(**values)


def test_nfl_listing_unknown_status_stays_playable_without_assumed_flags():
    fixture = json.loads((Path(__file__).parent/'fixtures/nfl_network_prime_vision.json').read_text())['airing']
    fixture['start'] = datetime.fromisoformat(fixture['start'])
    fixture['end'] = datetime.fromisoformat(fixture['end'])
    item = Airing(**fixture)
    programme = ET.fromstring(xmltv([LaneAssignment(1,item)],1,now=NOW)).find('programme')
    assert programme.findtext('title') == item.title
    assert programme.findtext('url') == item.deeplink
    assert programme.find('live') is None and programme.find('new') is None


@pytest.mark.parametrize('evidence,live,new,repeat', [
    ({},False,False,False),
    ({'broadcast_live':True},True,False,False),
    ({'first_run':True},False,True,False),
    ({'broadcast_live':True,'first_run':True},True,True,False),
    ({'broadcast_live':True,'first_run':True,'is_repeat':True},False,False,True),
])
def test_independent_evidence_flags(evidence,live,new,repeat):
    item=game(**evidence)
    programme=ET.fromstring(xmltv([LaneAssignment(1,item)],1,now=NOW)).find('programme')
    assert (programme.find('live') is not None) == live
    assert (programme.find('new') is not None) == new
    assert (programme.find('previously-shown') is not None) == repeat


def test_explicit_repeat_wins_merge_but_does_not_transfer_to_later_slot():
    first=game(broadcast_live=True,first_run=True)
    repeat=replace(first,is_repeat=True)
    for rows in ([first,repeat],[repeat,first]):
        merged=merge_airings(rows)[0]
        assert merged.is_repeat is True
        assert merged.broadcast_live is False and merged.first_run is False
    later=replace(first,start=first.start+timedelta(days=1),end=first.end+timedelta(days=1))
    assert next(e for e in merge_airings([repeat,later]) if e.start==later.start).is_repeat is None


def test_epg_live_stream_is_not_evidence_of_live_sports():
    payload={'epgAiringRenderer':{'title':{'simpleText':'Alabama at Georgia'},'stationName':'NFL Network',
        'isLive':True,'badge':{'unpluggedTextBadgeRenderer':{'type':'LIVE'}},
        'startTime':int(NOW.timestamp()),'endTime':int(NOW.timestamp())+7200,
        'navigationEndpoint':{'watchEndpoint':{'videoId':'abcdefghijk'}}}}
    item=parse_browse(payload,now=NOW)[0]
    assert item.live
    assert item.broadcast_live is None and item.first_run is None
    payload['epgAiringRenderer']['badge']['unpluggedTextBadgeRenderer']['type']='REPEAT'
    item=parse_browse(payload,now=NOW)[0]
    assert item.is_repeat is True and item.first_run is False


def test_game_card_evidence_and_cross_station_language_isolation():
    card={'primaryText':{'simpleText':'Today 8:00 PM • ESPN+'},'secondaryText':{'simpleText':'Football'},
        'startTeamPrimaryText':{'simpleText':'Alabama'},'endTeamPrimaryText':{'simpleText':'Georgia'},
        'startTime':int(NOW.timestamp()),'endTime':int(NOW.timestamp())+7200,
        'navigationEndpoint':{'watchEndpoint':{'videoId':'abcdefghijk'}},
        'badges':[{'unpluggedTextBadgeRenderer':{'type':'LIVE'}},{'unpluggedTextBadgeRenderer':{'type':'NEW'}}]}
    payload={'epgRowRenderer':{'station':{'epgStationRenderer':{'name':{'simpleText':'TUDN'}}},
                              'airings':[{'unpluggedGameCardRenderer':card}]}}
    events=parse_browse(payload,now=NOW)
    item=next(e for e in events if e.station=='ESPN+')
    assert item.language == ''
    assert item.broadcast_live is True and item.first_run is True


def test_candidate_selection_skips_expired_and_prioritizes_current_then_next():
    expired=[game(video_id='pending'+str(i),entity_id='old'+str(i),start=NOW-timedelta(days=2),end=NOW-timedelta(days=1)) for i in range(80)]
    current=game(video_id='',entity_id='current',live=False)
    later=game(video_id='',entity_id='later',start=NOW+timedelta(hours=2),end=NOW+timedelta(hours=3))
    sooner=replace(later,entity_id='sooner',start=NOW+timedelta(hours=1))
    too_far=replace(later,entity_id='far',start=NOW+timedelta(hours=40),end=NOW+timedelta(hours=42),live=True)
    invalid=replace(current,end=current.start)
    assert unresolved_soon(expired+[later,too_far,sooner,invalid,current],now=NOW) == [current,sooner,later]
    assert unresolved_soon([later,current],now=NOW,limit=1) == [current]


@pytest.mark.asyncio
async def test_full_lookup_uses_selector_and_keeps_playback_parameters():
    now=datetime.now(timezone.utc)
    pending=game(video_id='',entity_id='UCabcdefghijklmnopqrstuv',start=now,end=now+timedelta(hours=2),deeplink='')
    expired=replace(pending,entity_id='expired',start=now-timedelta(days=2),end=now-timedelta(days=1))
    payload={'epgAiringRenderer':{'title':{'simpleText':pending.title},'stationName':'ESPN+',
        'navigationEndpoint':{'watchEndpoint':{'videoId':'abcdefghijk','params':'0gEEEgIwAQ=='}}}}
    async with httpx.AsyncClient() as http:
        client=InnerTubeClient(http);client._browse=AsyncMock(return_value=payload)
        rows=await client.resolve_soon(SavedSession(kind='cookies'),CLIENTS[0],[expired]*80+[pending])
        assert client._browse.await_count == 1
        assert rows[-1].deeplink == 'https://tv.youtube.com/watch/abcdefghijk?vp=0gEEEgIwAQ%3D%3D'


@pytest.mark.parametrize('failure', ['truncated','wrong_key','bad_json','bad_structure'])
def test_session_recovery_preserves_original_and_allows_new_signin(tmp_path,failure):
    store=SessionStore(tmp_path,'original-key')
    store.save(SavedSession(kind='cookies',cookies=[{'name':'SID','value':'original'}]))
    if failure=='truncated': store.path.write_bytes(store.path.read_bytes()[:20])
    elif failure=='wrong_key': store=SessionStore(tmp_path,'different-key')
    elif failure=='bad_json': store.path.write_bytes(encrypt('original-key',b'not json'))
    else: store.path.write_bytes(encrypt('original-key',b'{}'))
    original=store.path.read_bytes()
    assert store.load() is None
    assert store.load_error
    assert store.path.read_bytes()==original
    session=SavedSession(kind='cookies',cookies=[{'name':'SID','value':'replacement'}])
    store.save(session)
    assert store.load()==session and not store.load_error
    backups=list(tmp_path.glob('session-recovery-*.enc'))
    assert len(backups)==1 and backups[0].read_bytes()==original
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_failed_atomic_save_keeps_existing_session(tmp_path,monkeypatch):
    import yttv_epg.session_store as module
    store=SessionStore(tmp_path,'key');session=SavedSession(kind='cookies')
    store.save(session);original=store.path.read_bytes()
    def fail(*args):raise OSError('Simulated interruption')
    monkeypatch.setattr(module.os,'replace',fail)
    with pytest.raises(OSError):store.save(SavedSession(kind='browser'))
    assert store.path.read_bytes()==original and store.load()==session
    assert not list(tmp_path.glob('.session.enc-*'))


def test_unreadable_session_does_not_escape_as_startup_exception(tmp_path,monkeypatch):
    store=SessionStore(tmp_path,'key');store.path.write_bytes(b'bad')
    def fail(*args,**kwargs):raise PermissionError('Unreadable')
    monkeypatch.setattr(Path,'read_bytes',fail)
    assert store.load() is None and store.load_error
