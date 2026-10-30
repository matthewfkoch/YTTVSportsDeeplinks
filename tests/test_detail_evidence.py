import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from xml.etree import ElementTree as ET

import pytest

from yttv_epg.detail_evidence import EvidenceStore, cache_key, collect_evidence, extract_evidence
from yttv_epg.feeds import xmltv
from yttv_epg.lanes import LaneAssignment
from yttv_epg.parse import Airing

CAPTURE = json.loads((Path(__file__).parent / 'fixtures/acc_replay_detail.json').read_text())
NOW = datetime.fromisoformat(CAPTURE['captured_at'])
GAME = Airing('VasWEa--oME', 'Virginia Tech at Clemson', 'ACC Network', 'event',
              datetime(2026, 10, 28, 11, tzinfo=timezone.utc),
              datetime(2026, 10, 28, 14, tzinfo=timezone.utc),
              'https://tv.youtube.com/watch/VasWEa--oME', entity_id=CAPTURE['browse_id'])


def test_acc_evidence_is_observation_not_exclusion(tmp_path):
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    before = xmltv([LaneAssignment(1, GAME)], 1, now=NOW, live_on_air=True)
    store.save(GAME, NOW, capture=CAPTURE)
    row = store.records(now=NOW)[0]
    assert row['evidence']['match'] == 'exact_airing'
    assert row['evidence']['date_gap_days'] == 4
    assert row['evidence']['event_date'] == '2026-10-24'
    assert 'earlier_event_date' in row['evidence']['signals']
    assert 'on_air_badge_not_live_confirmation' in row['evidence']['signals']
    assert row['evidence']['automatic_exclusions'] is False
    assert row['stale'] is False
    assert 'capture' not in row
    assert GAME.broadcast_live is None and GAME.is_repeat is None
    assert xmltv([LaneAssignment(1, GAME)], 1, now=NOW, live_on_air=True) == before
    assert ET.fromstring(before).find('programme/live') is not None


@pytest.mark.parametrize('change', [
    {'station': 'ESPN'}, {'title': 'Other at Game'}, {'video_id': 'abcdefghijk'},
    {'start': GAME.start + timedelta(hours=1)}, {'end': GAME.end + timedelta(hours=1)},
])
def test_other_slots_and_channels_do_not_inherit_evidence(change):
    evidence = extract_evidence(replace(GAME, **change), CAPTURE)
    assert evidence['match'] == 'unmatched'
    assert evidence['event_date'] is None
    assert evidence['badges'] == []


def test_date_and_badge_signals_are_channel_independent():
    capture = json.loads(json.dumps(CAPTURE))
    for record in capture['details']:
        if record['renderer'] == 'unpluggedCompactVideoRenderer':
            record['fields']['secondaryText'] = {'simpleText': 'CBS Sports Network'}
    evidence = extract_evidence(replace(GAME, station='CBS Sports Network'), capture)
    assert evidence['match'] == 'exact_airing'
    assert evidence['date_gap_days'] == 4


@pytest.mark.parametrize('date,signal,gap', [
    ('Oct 28, 2026', 'same_day_not_live_confirmation', 0),
    ('Oct 27, 2026', 'earlier_event_date', 1),
    ('Oct 29, 2026', 'event_date_after_airing', -1),
    ('Tomorrow', 'unparsed_event_date', None),
])
def test_date_signals_never_make_a_classification(date, signal, gap):
    capture = json.loads(json.dumps(CAPTURE))
    for record in capture['details']:
        if record['renderer'] == 'unpluggedContentDetailsHeaderRenderer':
            record['fields']['secondaryText'] = {'simpleText': date}
    evidence = extract_evidence(GAME, capture)
    assert signal in evidence['signals'] and evidence['date_gap_days'] == gap
    assert evidence['automatic_exclusions'] is False


def test_cache_persists_failure_preserves_capture_and_history(tmp_path):
    path = tmp_path / 'evidence.sqlite'
    store = EvidenceStore(path)
    store.save(GAME, NOW, capture=CAPTURE)
    store.save(GAME, NOW + timedelta(minutes=6), error='TimeoutError')
    reopened = EvidenceStore(path)
    latest = reopened.records(now=NOW + timedelta(minutes=6), include_capture=True)[0]
    assert latest['error'] == 'TimeoutError' and latest['stale']
    assert latest['captured_at'] == NOW.isoformat()
    assert latest['capture'] == CAPTURE
    assert len(reopened.records(history=True)) == 1
    assert reopened.get(cache_key(GAME))['retry_at'] == (NOW + timedelta(minutes=11)).timestamp()
    assert cache_key(replace(GAME, start=GAME.start + timedelta(days=1))) != cache_key(GAME)
    reopened.prune(NOW + timedelta(days=8))
    assert reopened.records() == [] and reopened.records(history=True) == []


@pytest.mark.asyncio
async def test_collection_ttl_and_per_slot_identity(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    capture = AsyncMock(return_value=CAPTURE)
    monkeypatch.setattr('yttv_epg.detail_evidence.capture_details', capture)
    await collect_evidence(store, object(), object(), [GAME, GAME], now=NOW)
    assert capture.await_count == 1
    await collect_evidence(store, object(), object(), [GAME], now=NOW + timedelta(minutes=4))
    assert capture.await_count == 1
    await collect_evidence(store, object(), object(), [GAME], now=NOW + timedelta(minutes=5))
    assert capture.await_count == 2
    assert len(store.records(history=True)) == 2


@pytest.mark.asyncio
async def test_collection_fallback_and_failure_backoff(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    capture = AsyncMock(side_effect=[{'details': []}, CAPTURE])
    monkeypatch.setattr('yttv_epg.detail_evidence.capture_details', capture)
    await collect_evidence(store, object(), object(), [GAME], now=NOW)
    assert capture.call_args_list[0].kwargs == {'browse_id': GAME.entity_id}
    assert capture.call_args_list[1].kwargs == {'video_id': GAME.watch_id()}
    capture.side_effect = RuntimeError('SECRET provider error')
    await collect_evidence(store, object(), object(), [GAME], now=NOW + timedelta(minutes=6))
    count = capture.await_count
    await collect_evidence(store, object(), object(), [GAME], now=NOW + timedelta(minutes=7))
    assert capture.await_count == count
    row = store.records(include_capture=True)[0]
    assert row['error'] == 'RuntimeError' and row['capture'] == CAPTURE
    assert 'SECRET' not in json.dumps(row)


@pytest.mark.asyncio
async def test_collection_selection_limit_and_start_expiry(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    capture = AsyncMock(return_value=CAPTURE)
    monkeypatch.setattr('yttv_epg.detail_evidence.capture_details', capture)
    upcoming = replace(GAME, entity_id='', start=NOW + timedelta(minutes=10), end=NOW + timedelta(hours=2))
    expired = replace(GAME, end=NOW)
    far = replace(GAME, start=NOW + timedelta(days=2), end=NOW + timedelta(days=3))
    await collect_evidence(store, object(), object(), [upcoming, expired, far, GAME], now=NOW, limit=1)
    assert capture.call_args.kwargs == {'browse_id': GAME.entity_id}
    await collect_evidence(store, object(), object(), [upcoming, GAME], now=NOW, limit=1)
    assert store.get(cache_key(upcoming))['retry_at'] == upcoming.start.timestamp()
    assert len(store.records()) == 2


def test_cache_and_history_size_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr('yttv_epg.detail_evidence.MAX_RECORDS', 2)
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    for i in range(3):
        store.save(replace(GAME, title=f'Game {i}'), NOW + timedelta(seconds=i), capture=CAPTURE)
    store.prune(NOW + timedelta(seconds=3))
    assert len(store.records()) == len(store.records(history=True)) == 2
    assert store.get(cache_key(replace(GAME, title='Game 0'))) is None


@pytest.mark.asyncio
async def test_cancellation_is_not_saved_as_a_fetch_failure(tmp_path, monkeypatch):
    import asyncio
    store = EvidenceStore(tmp_path / 'evidence.sqlite')
    monkeypatch.setattr('yttv_epg.detail_evidence.capture_details', AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await collect_evidence(store, object(), object(), [GAME], now=NOW)
    assert store.records() == []


@pytest.mark.parametrize('filename', ['rhode_island_live_detail.json', 'arsenal_live_detail.json'])
def test_schedule_corroborated_live_captures_stay_observational(filename):
    capture = json.loads((Path(__file__).parent / 'fixtures' / filename).read_text())
    card = next(r['fields'] for r in capture['details']
                if r['renderer'] == 'unpluggedCompactVideoRenderer')
    game = Airing(capture['video_id'], ''.join(r['text'] for r in card['primaryText']['runs']),
                  ''.join(r['text'] for r in card['secondaryText']['runs']), 'event',
                  datetime.fromtimestamp(int(card['startTimeSeconds']), timezone.utc),
                  datetime.fromtimestamp(int(card['endTimeSeconds']), timezone.utc), '')
    evidence = extract_evidence(game, capture)
    assert evidence['match'] == 'exact_airing'
    assert evidence['date_gap_days'] == 0
    assert evidence['event_date'] == '2026-10-28'
    assert 'LIVE' in evidence['badges']
    assert 'earlier_event_date' not in evidence['signals']
    assert evidence['automatic_exclusions'] is False
    assert game.broadcast_live is None and game.is_repeat is None


SAMPLES = json.loads((Path(__file__).parent / 'fixtures/detail_matching_samples.json').read_text())


@pytest.mark.parametrize('sample', SAMPLES, ids=lambda s: s['airing']['title'])
def test_captured_channel_decorations_and_episode_titles(sample):
    data = sample['airing']
    game = Airing(data['video_id'], data['title'], data['station'], 'event',
                  datetime.fromisoformat(data['start']), datetime.fromisoformat(data['end']),
                  '', entity_id=data['entity_id'])
    before = xmltv([LaneAssignment(1, game)], 1, now=game.start, live_on_air=True)
    evidence = extract_evidence(game, sample['capture'])
    if game.station == 'T2':
        assert evidence['match'] == 'unmatched'
        assert evidence['unmatched_candidates'][0]['mismatched_fields'] == ['title']
        assert evidence['event_date'] is None
        assert evidence['descriptions'] == []
    else:
        assert evidence['match'] == 'exact_airing'
        assert evidence['unmatched_candidates'] == []
        if game.station == 'BTN':
            assert 'explicit_replay_description' in evidence['signals']
            assert evidence['description_evidence'][0]['phrase'] == 'Replays of'
            assert evidence['description_evidence'][0]['path'] in evidence['matched_paths']
    assert evidence['automatic_exclusions'] is False
    assert game.is_repeat is None and game.broadcast_live is None
    assert xmltv([LaneAssignment(1, game)], 1, now=game.start, live_on_air=True) == before


@pytest.mark.parametrize('description,expected', [
    ('Replays of the best action from Big Ten contests.', True),
    ('A rebroadcast of Saturday’s game.', True),
    ('Replay: California at USC.', True),
    ('Live coverage with instant replays.', False),
    ('Officials review a replay of the final play.', False),
    ('No replays of previous games.', False),
    ('A rematch of last year’s final.', False),
    ('Coverage from ATP and WTA events.', False),
])
def test_explicit_description_signals_require_programme_replay_wording(description, expected):
    capture = json.loads(json.dumps(CAPTURE))
    for record in capture['details']:
        if record['renderer'] == 'unpluggedCompactVideoRenderer':
            record['fields']['description'] = {'simpleText': description}
    evidence = extract_evidence(GAME, capture)
    assert ('explicit_replay_description' in evidence['signals']) is expected
    assert bool(evidence['description_evidence']) is expected
    unrelated = extract_evidence(replace(GAME, title='Unrelated game'), capture)
    assert unrelated['description_evidence'] == []
    assert 'explicit_replay_description' not in unrelated['signals']


@pytest.mark.parametrize('station,expected', [
    ('ES • ACC Network', True), ('ACC Network • TV-G', True),
    ('ES • ACC Network • TV-PG', True), ('ES • SEC Network', False),
    ('ACC Network • ESPN', False), ('Unknown • ACC Network', False),
])
def test_channel_normalization_only_strips_known_decorations(station, expected):
    capture = json.loads(json.dumps(CAPTURE))
    for record in capture['details']:
        if record['renderer'] == 'unpluggedCompactVideoRenderer':
            record['fields']['secondaryText'] = {'simpleText': station}
    evidence = extract_evidence(GAME, capture)
    assert (evidence['match'] == 'exact_airing') is expected


@pytest.mark.parametrize('description,signals', [
    ('Repetición del partido entre Santos Laguna y Pumas.', {'explicit_replay_description'}),
    ('REEMISIÓN: Santos Laguna vs. Pumas.', {'explicit_replay_description'}),
    ('Los momentos más destacados del partido de la fecha 13. Disputado el 21 de octubre de 2026.',
     {'highlights_description', 'historical_match_description'}),
    ('Compacto de la fecha 3. Disputado el 21 de octubre de 2026.',
     {'highlights_description', 'historical_match_description'}),
    ('Resumen del encuentro entre dos equipos.', {'highlights_description'}),
    ('Disputado el 29 de octubre de 2026.', {'dated_match_description'}),
    ('Cobertura en vivo con repetición instantánea.', set()),
    ('Repetición de la jugada revisada por el árbitro.', set()),
    ('El partido será disputado el 30 de octubre de 2026.', set()),
    ('No es una repetición del partido.', set()),
    ('Retransmisión en directo del partido.', set()),
])
def test_spanish_description_evidence_is_scoped_and_observational(description, signals):
    capture = json.loads(json.dumps(CAPTURE))
    for record in capture['details']:
        if record['renderer'] == 'unpluggedCompactVideoRenderer':
            record['fields']['description'] = {'simpleText': description}
    before = xmltv([LaneAssignment(1, GAME)], 1, now=NOW, live_on_air=True)
    evidence = extract_evidence(GAME, capture)
    spanish = [e for e in evidence['description_evidence'] if e.get('language') == 'es']
    assert {e['signal'] for e in spanish} == signals
    for item in spanish:
        assert item['path'] in evidence['matched_paths']
        assert item['phrase'] in description
    assert signals <= set(evidence['signals'])
    assert evidence['automatic_exclusions'] is False
    assert xmltv([LaneAssignment(1, GAME)], 1, now=NOW, live_on_air=True) == before
    assert extract_evidence(replace(GAME, title='Other game'), capture)['description_evidence'] == []
