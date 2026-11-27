#!/usr/bin/env python3
"""Exercise seat revision history, including a pre-history database. Pass a three-seat gallery."""
import argparse
import copy
from contextlib import closing
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import urlsplit

from garden_room import load_gallery, unpack_path
from ring_scene import join
from test_garden_room import API, room


def request(url, method='GET', payload=None, suffix='', headers=None):
    address = urlsplit(url)
    data = json.dumps(payload) if payload is not None else None
    with closing(HTTPConnection(address.hostname, address.port, timeout=10)) as http:
        http.request(method, API + suffix, data, {'Origin':url, 'Content-Type':'application/json', **(headers or {})})
        response = http.getresponse()
        body = response.read()
        return response.status, response.getheader('X-Oasis-Place-Revisions'), json.loads(body) if body else None


def change(spec, state, seat, subject, revision):
    updated = copy.deepcopy(state)
    old = updated['ids'][seat]
    updated['ids'][seat] = subject
    if 'guestBook' in updated:
        book = updated['guestBook']
        owner = book['active'][seat]
        next(person for person in book['people'] if person['name'].lower() == owner)['subject'] = subject
    fill = old == spec.open_subject
    parts = spec.place_paths[seat]
    engraving = unpack_path(spec.excursions[seat][subject])
    track = join(parts['approach'] if fill else parts['clear'], engraving,
                 parts['fill_exit'] if fill else parts['exit'])
    motion = {'zone':'middle', 'place':seat, 'files':[{
        'name':'seat.thr', 'text':''.join(f'{angle:.5f} {radius:.5f}\n' for angle, radius in track)}]}
    if fill:
        motion['fill'] = True
    return {'state':updated, 'motion':motion, 'revision':revision}


def exercise(gallery, database):
    _, layouts = load_gallery(gallery)
    spec = layouts['garden']
    # A historical save predates any records identifying which seat was changed.
    with closing(sqlite3.connect(database)) as db, db:
        db.execute('CREATE TABLE garden(layout TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL)')
        db.execute("INSERT INTO garden VALUES('garden',7,'null')")
    base = {**spec.initial, 'edition':next(iter(spec.editions)), 'labels':{}}
    before = base['ids'][0]
    other = 'guitar' if before != 'guitar' else 'pumpkin'
    with room(gallery, database) as url:
        assert request(url) == (200, '7,7,7', {'revision':7, 'state':None})
        first = change(spec, base, 0, other, 7)
        assert request(url, 'PUT', first) == (200, None, {'revision':8})
        assert request(url) == (200, '8,7,7', {'revision':8, 'state':first['state']})
        assert request(url, 'PUT', first) == (409, None, {'revision':8})
        # A -> B -> A has the same guest and art as the original preview, but a newer seat revision.
        second = change(spec, first['state'], 0, before, 8)
        assert request(url, 'PUT', second) == (200, None, {'revision':9})
        assert request(url) == (200, '9,7,7', {'revision':9, 'state':base})
        assert request(url, suffix='/drawings/middle')[1] is None
        assert request(url, headers={'If-None-Match':'"9"'}) == (304, None, None)
    with room(gallery, database) as url:
        assert request(url) == (200, '9,7,7', {'revision':9, 'state':base})
        named = change(spec, base, 0, other, 9)
        people = [dict(name=name, interest=interest, subject=subject) for (name, interest), subject in zip(
            [('Thomas','Bacteriophages'),('Alex','Teaching'),('Maya','Astronomy')], named['state']['ids'])]
        named['state']['guestBook'] = {'people':people, 'active':['thomas','alex','maya']}
        assert request(url, 'PUT', named) == (200, None, {'revision':10})
        assert request(url)[1] == '10,7,10'
        renamed = copy.deepcopy(named['state'])
        renamed['guestBook']['people'][0]['interest'] = 'Violin'
        assert request(url, 'PUT', {'revision':10, 'state':renamed}) == (200, None, {'revision':11})
        assert request(url)[1] == '11,11,11'
        assert request(url, 'PUT', {'revision':11, 'state':None}) == (200, None, {'revision':12})
        assert request(url) == (200, '12,12,12', {'revision':12, 'state':None})
    # Older room software can still use this database. It writes only the global revision.
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE garden SET revision=13 WHERE layout='garden'")
    with room(gallery, database) as url:
        assert request(url)[1] == '13,13,13'
        next_save = change(spec, base, 0, other, 13)
        assert request(url, 'PUT', next_save) == (200, None, {'revision':14})
        assert request(url)[1] == '14,13,13'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    with tempfile.TemporaryDirectory() as directory:
        exercise(parser.parse_args().gallery, Path(directory)/'room.db')
    print('Guest seat history, stale saves, metadata, reset and migration passed.')
