from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from yttv_epg.gracenote import apply_gracenote, load_grid, parse_grid
from yttv_epg.parse import Airing
from yttv_epg.feeds import xmltv
from yttv_epg.lanes import LaneAssignment


def airing():
    start = datetime(2026, 11, 9, 23, tzinfo=timezone.utc)
    return Airing('abcdefghijk', 'Boston at Detroit', 'ESPN', 'event', start,
                  start + timedelta(hours=3), 'https://tv.youtube.com/watch/abcdefghijk', sport='Basketball')


def grid(flags):
    a = airing()
    return {'channels': [{'callSign': 'ESPN', 'events': [{
        'startTime': a.start.isoformat(), 'endTime': a.end.isoformat(),
        'program': {'title': 'NBA Basketball', 'episodeTitle': a.title}, 'flag': flags,
    }]}]}


@pytest.mark.parametrize('flags,live,new', [(['LIve', 'New'], True, True),
    (['Premiere'], None, None), (['New'], None, True), ([], None, None)])
def test_flags_are_independent(flags, live, new):
    result = apply_gracenote([airing()], parse_grid(grid(flags)))[0]
    assert result.broadcast_live is live
    assert result.first_run is new
    assert result.is_repeat is None
    assert result.to_dict()['gracenote_flags'] == sorted(f.lower() for f in flags)
    body = xmltv([LaneAssignment(1, result)], 1, now=airing().start)
    assert ('<live/>' in body) == (live is True)
    assert ('<new/>' in body) == (new is True)
    assert ('<premiere/>' in body) == ('Premiere' in flags)


@pytest.mark.parametrize('changes', [dict(station='ESPN2'), dict(title='Chicago at Detroit'),
    dict(start=airing().start + timedelta(minutes=1)), dict(end=airing().end + timedelta(minutes=1))])
def test_other_airings_do_not_inherit_live(changes):
    result = apply_gracenote([replace(airing(), **changes)], parse_grid(grid(['Live'])))[0]
    assert result.broadcast_live is None
    assert not result.gracenote_flags


def test_conflicting_duplicates_and_explicit_negative_evidence():
    payload = grid(['Live'])
    payload['channels'] += grid([])['channels']
    assert apply_gracenote([airing()], parse_grid(payload))[0].broadcast_live is None
    repeat = replace(airing(), is_repeat=True, broadcast_live=False, first_run=False)
    result = apply_gracenote([repeat], parse_grid(grid(['Live', 'New'])))[0]
    assert result.broadcast_live is False and result.first_run is False
    negative = replace(airing(), broadcast_live=False)
    assert apply_gracenote([negative], parse_grid(grid(['Live'])))[0].broadcast_live is False


def test_file_replacement_removal_and_invalid_input(tmp_path):
    path = tmp_path / 'grid.json'
    path.write_text(json.dumps(grid(['Live'])))
    assert apply_gracenote([airing()], load_grid(path))[0].broadcast_live is True
    path.write_text(json.dumps(grid(['Premiere'])))
    assert apply_gracenote([airing()], load_grid(path))[0].broadcast_live is None
    path.write_text('<html>Verification</html>')
    assert load_grid(path) == ()
    path.unlink()
    assert load_grid(path) == ()
    assert load_grid(None) == ()


def test_malformed_rows_are_ignored():
    payload = grid(['Live'])
    payload['channels'][0]['events'][0]['startTime'] = '2026-11-09T23:00:00'
    assert parse_grid(payload) == ()
    with pytest.raises(ValueError):
        parse_grid({'error': 'verification'})


@pytest.mark.asyncio
async def test_api_and_cached_lanes_use_file_without_persisting(monkeypatch, tmp_path):
    from yttv_epg import app as module
    from yttv_epg.catalog import Catalog
    catalog = Catalog(tmp_path / 'catalog.sqlite')
    monkeypatch.setattr(module.state, 'catalog', catalog)
    monkeypatch.setattr(module.state, 'lane_assignments', [LaneAssignment(1, airing())])
    monkeypatch.setattr(catalog, 'events', lambda *args, **kwargs: [airing()])
    monkeypatch.setattr(module.state, 'espn_listings', [])
    path = tmp_path / 'grid.json'
    path.write_text(json.dumps(grid(['Live', 'New'])))
    monkeypatch.setattr(module.settings, 'gracenote_grid_file', path)
    assert (await module.list_events('all'))['events'][0]['broadcast_live'] is True
    assert module._labeled_assignments()[0].airing.broadcast_live is True
    assert module.state.lane_assignments[0].airing.broadcast_live is None
    path.unlink()
    assert module._labeled_assignments()[0].airing.broadcast_live is None
