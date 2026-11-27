#!/usr/bin/env python3
"""Exercise two- and three-guest saves through a local room and simulated table."""
import copy
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import tempfile

from playwright.sync_api import sync_playwright

from garden_room import unpack_path
from test_attached_garden import Table, served, wait_table
from test_garden_reveal_room import change, expose_routes, put
from test_garden_room import API, ROOT, room
from test_guest_custom_reveal import change_row, crossing_rows


def paired_request(page, starting, routes):
    files, parts = [], []
    for place, target in [(0, 'guitar'), (1, 'temple')]:
        source = starting['ids'][place]
        originals = routes[place, source, target]
        parts.append({'place': place, 'earlyFrom': source, 'count': len(originals)})
        for original in originals:
            files.append({'name': f'guest-ring-{len(files)+1}.thr', 'text': original['text']})
    request = change(page, starting, 0, 0, 'guitar', files)
    request['state']['ids'][1] = 'temple'
    request['motion'] = {'zone': 'middle', 'files': files, 'parts': parts}
    return request


def edited_motion(request, **changes):
    return dict(request, motion=dict(request['motion'], **changes))


def reject_bad_requests(page, url, request):
    parts, files = (request['motion'][key] for key in ('parts', 'files'))
    first, second = parts
    for bad in ([], [first], [first, first], [first, second, second, first],
                [first, dict(second, count=1)], [dict(first, count=1), dict(second, count=3)],
                [dict(first, count=True), second], [first, dict(second, place=3)],
                [dict(first, earlyFrom='books'), second], [first, dict(second, earlyFrom='phage')],
                [first, dict(second, fill=True)], [second, first]):
        put(page, url, edited_motion(request, parts=bad), 400)
    for extra in ({'place': 0}, {'fill': True}, {'earlyFrom': 'phage'}, {'zone': 'outer'}):
        put(page, url, edited_motion(request, **extra), 400)
    # Reorder lines/files or substitute another signed trip. All the constituent
    # trips still start and end at the dock. Ordering and exact bytes must match.
    for a, b in ((0, 1), (2, 3), (0, 2)):
        swapped = copy.deepcopy(files)
        swapped[a]['text'], swapped[b]['text'] = swapped[b]['text'], swapped[a]['text']
        put(page, url, edited_motion(request, files=swapped), 400)
    for index in (0, 2):
        altered = copy.deepcopy(files)
        altered[index]['text'] = altered[index]['text'].replace(' ', '  ', 1)
        put(page, url, edited_motion(request, files=altered), 400)
    bad_names = copy.deepcopy(files)
    bad_names[2]['name'] = 'replacement.thr'
    put(page, url, edited_motion(request, files=bad_names), 400)
    put(page, url, dict(request, motion={'zone': 'middle', 'files': files}), 400)
    for ids in (['guitar', 'temple', 'pumpkin'], ['guitar', 'books', 'temple']):
        put(page, url, dict(request, state=dict(request['state'], ids=ids)), 400)


def planned_request(page, stored, ids, *, whole=False, custom=None, legacy_fills=False):
    result = page.evaluate('''([previous, ids, whole, custom, legacyFills]) => {
      const catalog = JSON.parse(document.querySelector('#scene').textContent).live.planner;
      if (legacyFills) for (const place of catalog.places || []) if (place) delete place.shortFill;
      const route = whole ? OasisRingPlanner.plan(catalog, ids, custom) :
        OasisRingPlanner.planChange(catalog, previous, ids, custom);
      return {files: route.files || OasisRingPlanner.files(route.path), parts: route.parts || null,
        tour: route.tour === true};
    }''', [stored['state']['ids'], ids, whole, custom or {}, legacy_fills])
    request = change(page, stored['state'], stored['revision'], 0, ids[0], result['files'])
    request['state']['ids'] = ids
    request['motion'] = {'zone': 'middle', 'files': result['files']}
    if not whole:
        request['motion']['parts'] = result['parts']
        if result['tour']:
            request['motion']['tour'] = True
    if custom:
        request['state']['custom'].update(custom)
        request['state']['labels'].update({key: 'Guest sketch' for key in custom})
    return request


def split_file(motion, part, index, cut):
    rows = motion['files'][index]['text'].splitlines(keepends=True)
    assert 0 < cut < len(rows)-1
    motion['files'][index:index+1] = [dict(text=''.join(rows[:cut+1])), dict(text=''.join(rows[cut:]))]
    part['count'] += 1
    for j, file in enumerate(motion['files'], 1):
        file['name'] = f'guest-ring-{j}.thr'


def split_sketch(tour, live):
    """Split a small real sketch inside its engraving to exercise a hardware file boundary."""
    motion = tour['motion']
    assert motion['tour'] and all(part['count'] == 1 and part['fill'] for part in motion['parts'])
    i = next(i for i, part in enumerate(motion['parts']) if part['place'] == 2)
    catalog = live['planner']
    order = [p['place'] for p in motion['parts']]
    steps = next(path for path in catalog['fillTours']['1-2'] if [s['place'] for s in path] == order)
    rows = motion['files'][i]['text'].splitlines(keepends=True)
    start = len(unpack_path(steps[i]['approach'])) - 1
    end = len(rows) - (len(unpack_path(steps[i]['exit']))-1 if 'exit' in steps[i] else 0)
    ink = [j for j in range(start, end) if abs(float(rows[j].split()[1])-catalog['geometry']['rail']) > .001]
    cut = ink[len(ink)//2]
    split_file(motion, motion['parts'][i], i, cut)


def reject_bad_tours(page, url, tour):
    motion = tour['motion']
    first, second = motion['parts']
    for parts in ([first, first], [second, first], [dict(first, fill=False), second],
                  [dict(first, earlyFrom='guitar'), second], [dict(first, customReveal={}), second],
                  [dict(first, shortFill='left'), second],
                  [dict(first, count=second['count']), dict(second, count=first['count'])]):
        put(page, url, edited_motion(tour, parts=parts), 400)
    for bad in (dict(motion, tour=1), dict(motion, place=1), dict(motion, zone='outer'),
                {k:v for k,v in motion.items() if k != 'tour'}, {k:v for k,v in motion.items() if k != 'parts'}):
        put(page, url, dict(tour, motion=bad), 400)
    for ids in (['guitar', 'books', 'sketch-1'], ['pumpkin', 'phage', 'sketch-1']):
        put(page, url, dict(tour, state=dict(tour['state'], ids=ids)), 400)
    bad_shape = {'sketch-1': [[0,.5], [-.2,.1], [.3,-.3], [0,.5]]}
    put(page, url, dict(tour, state=dict(tour['state'], custom=bad_shape)), 400)
    for file_index, row in [(first['count'], 1), (first['count'], 0), (0, 0), (-1, -1)]:
        files = copy.deepcopy(motion['files'])
        rows = files[file_index]['text'].splitlines()
        theta, radius = map(float, rows[row].split())
        rows[row] = f'{theta:.5f} {radius-.005:.5f}'
        files[file_index]['text'] = '\n'.join(rows)+'\n'
        put(page, url, edited_motion(tour, files=files), 400)


def check_custom_pair(page, url, request, live):
    motion = request['motion']
    native, custom = motion['parts']
    assert native['place'] == 1 and native['earlyFrom'] == live['planner']['defaults'][1]
    assert custom['place'] == 0 and custom['count'] == 1
    detour = custom['customReveal']
    start, count = next(crossing_rows(live['planner']['places'][0], detour))
    offset = native['count']
    # The ball turns around on the early drawing, right between signed files.
    split_file(motion, custom, offset, start+count)
    old = page.request.get(url+API).json()
    download = page.request.get(url+API+'/drawings/middle').json()
    queue = page.request.get(url+'/api/playback').json()
    unmarked = {k:v for k,v in custom.items() if k != 'customReveal'}
    for parts in ([native, unmarked], [dict(native, customReveal=detour), unmarked],
                  [native, dict(custom, fill=True)], [native, dict(custom, earlyFrom='phage')],
                  [native, dict(custom, customReveal=dict(detour, end=10**30))],
                  [native, dict(custom, customReveal=dict(detour, second=detour))],
                  [dict(native, count=offset+1), dict(custom, count=1)],
                  [dict(native, earlyFrom='phage'), custom]):
        put(page, url, edited_motion(request, parts=parts), 400)
    for change_outward_too in (True, False):
        altered = copy.deepcopy(motion['files'])
        point = count//2
        if change_outward_too:
            change_row(altered[offset:], start+point)
        change_row(altered[offset:], start+2*count-point)
        put(page, url, edited_motion(request, files=altered), 400)
    seam = copy.deepcopy(motion['files'])
    change_row(seam[offset+1:], 0)
    put(page, url, edited_motion(request, files=seam), 400)
    different = copy.deepcopy(request)
    key = different['state']['ids'][custom['place']]
    different['state']['custom'][key] = [[-x,y] for x,y in different['state']['custom'][key]]
    put(page, url, different, 400)
    assert page.request.get(url+API).json() == old
    assert page.request.get(url+API+'/drawings/middle').json() == download
    after = page.request.get(url+'/api/playback').json()
    assert (after['revision'], after['queued']) == (queue['revision'], queue['queued'])
    revision = put(page, url, request, 200).json()['revision']
    assert put(page, url, request, 409).json()['revision'] == revision
    assert page.request.get(url+API+'/drawings/middle').json() == {'revision':revision, 'files':motion['files']}


def exercise(browser, folder):
    gallery, live, routes = expose_routes(folder)
    initial = {'edition': live['edition'], 'bed': live['bed'], 'ids': live['planner']['defaults'],
               'center': 0, 'outer': 0, 'portrait': '', 'custom': {}, 'labels': {}}
    db = folder/'room.db'
    table = Table(db)
    with served(gallery, db, table, prepared=True) as url, browser.new_page() as page:
        page.goto(url+'/garden')
        assert table.dispatched(1) == live['setup'][0]
        request = paired_request(page, initial, routes)
        reject_bad_requests(page, url, request)
        assert page.request.get(url+API).json() == {'revision': 0, 'state': None}
        assert put(page, url, request, 200).json()['revision'] == 1
        assert put(page, url, request, 409).json()['revision'] == 1
        put(page, url, dict(request, revision=1), 400)
        response = page.request.get(url+API)
        assert response.headers['x-oasis-place-revisions'] == '1,1,0'
        stored = response.json()
        assert stored == {'revision': 1, 'state': request['state']}
        with closing(sqlite3.connect(db)) as conn:
            assert conn.execute('SELECT revision, parts FROM playback_job ORDER BY revision').fetchall() == [
                (0, len(live['setup'])), (1, 4)]
    with served(gallery, db, table) as url, browser.new_page() as page:
        page.goto(url+'/garden')
        page.add_script_tag(path=str(ROOT/'web/ring-planner.js'))
        assert page.request.get(url+API).json() == stored
        assert page.request.get(url+API+'/drawings/middle').json() == {
            'revision': 1, 'files': request['motion']['files']}
        # The original complete guest-ring route can still be used by older phones.
        open_place = live['planner']['openSubject']
        full = planned_request(page, stored, ['guitar', open_place, open_place], whole=True)
        assert put(page, url, full, 200).json()['revision'] == 2
        # Two guests fill empty seats, one replaces a full seat. Include an actual
        # custom drawing to exercise the saved-shape/engraved-path checks.
        sketch = [[0, .6], [-.35, -.25], [.45, -.25], [0, .6]]
        current = page.request.get(url+API).json()
        mixed = planned_request(page, current, ['pumpkin', 'rocket', 'sketch-1'], custom={'sketch-1': sketch})
        parts = mixed['motion']['parts']
        assert len(parts) == 3 and sorted(p['place'] for p in parts if p.get('fill')) == [1, 2]
        other_sketch = dict(mixed['state'], custom={'sketch-1': [[0,.5], [-.2,.1], [.3,-.3], [0,.5]]})
        put(page, url, dict(mixed, state=other_sketch), 400)
        assert put(page, url, mixed, 200).json()['revision'] == 3
        assert page.request.get(url+API).headers['x-oasis-place-revisions'] == '3,3,3'
        opened = planned_request(page, page.request.get(url+API).json(), ['pumpkin', open_place, open_place], whole=True)
        assert put(page, url, opened, 200).json()['revision'] == 4
        tour = planned_request(page, page.request.get(url+API).json(), ['pumpkin', 'books', 'sketch-1'],
                               custom={'sketch-1': sketch}, legacy_fills=True)
        split_sketch(tour, live)
        reject_bad_tours(page, url, tour)
        # A different phone has an occupied seat in the same position. Even a
        # geometrically correct early drawing cannot replace our empty seat.
        wrong = page.request.get(url+API).json()
        wrong['state']['ids'][2] = 'temple'
        foreign = planned_request(page, wrong, tour['state']['ids'], custom={'sketch-1': sketch})
        assert [p['place'] for p in foreign['motion']['parts'] if 'customReveal' in p] == [2]
        put(page, url, foreign, 400)
        assert put(page, url, tour, 200).json()['revision'] == 5
        assert put(page, url, tour, 409).json()['revision'] == 5
        assert page.request.get(url+API).headers['x-oasis-place-revisions'] == '4,5,5'
        prior_files = live['setup'] + [file for move in (request, full, mixed, opened) for file in move['motion']['files']]
        for i, file in enumerate(prior_files, 1):
            assert table.dispatched(i) == file
            table.outcome = 'complete'
        assert table.dispatched(len(prior_files)+1) == tour['motion']['files'][0]
    with served(gallery, db, table) as url, browser.new_page() as page:
        assert page.request.get(url+API+'/drawings/middle').json() == {'revision':5, 'files':tour['motion']['files']}
        for i, file in enumerate(tour['motion']['files'], len(prior_files)+1):
            assert table.dispatched(i) == file
            table.outcome = 'complete'
        wait_table(page, url, state='idle', ready=True, queued=0, revision=5)
        assert len(table.calls) == len(prior_files)+len(tour['motion']['files'])
        page.goto(url+'/garden')
        page.add_script_tag(path=str(ROOT/'web/ring-planner.js'))
        restored = planned_request(page, page.request.get(url+API).json(), initial['ids'], whole=True)
        assert put(page, url, restored, 200).json()['revision'] == 6
        pair = planned_request(page, page.request.get(url+API).json(), ['sketch-2', 'temple', initial['ids'][2]],
                               custom={'sketch-2':sketch})
        check_custom_pair(page, url, pair, live)
        pending = restored['motion']['files'] + pair['motion']['files']
        first_pending = len(prior_files)+len(tour['motion']['files'])+1
        assert table.dispatched(first_pending) == pending[0]
    with served(gallery, db, table) as url, browser.new_page() as page:
        for i, file in enumerate(pending, first_pending):
            assert table.dispatched(i) == file
            table.outcome = 'complete'
        wait_table(page, url, state='idle', ready=True, queued=0, revision=7)
        assert len(table.calls) == first_pending-1+len(pending)
    with room(gallery, folder/'virtual.db') as url, browser.new_page() as page:
        put(page, url, dict(request, motion={'zone':'middle', 'files': request['motion']['files']}), 400)
        assert put(page, url, request, 200).json()['revision'] == 1
        assert put(page, url, full, 200).json()['revision'] == 2
        assert put(page, url, mixed, 200).json()['revision'] == 3
        # Changing two *occupied* seats cannot reuse drawing-only routes.
        occupied = dict(tour['state'], ids=['pumpkin', 'books', 'sketch-2'],
                        labels={'sketch-2':'Guest sketch'}, custom={'sketch-2':sketch})
        put(page, url, dict(tour, state=occupied, revision=3), 400)
        assert put(page, url, opened, 200).json()['revision'] == 4
        reject_bad_tours(page, url, tour)
        assert put(page, url, tour, 200).json()['revision'] == 5
        page.goto(url+'/garden')
        page.add_script_tag(path=str(ROOT/'web/ring-planner.js'))
        empty = planned_request(page, page.request.get(url+API).json(), [open_place]*3, whole=True)
        assert put(page, url, empty, 200).json()['revision'] == 6
        three = planned_request(page, page.request.get(url+API).json(), ['phage', 'books', 'temple'], legacy_fills=True)
        assert three['motion']['tour'] and len(three['motion']['parts']) == 3
        assert put(page, url, three, 200).json()['revision'] == 7
        assert page.request.get(url+API).headers['x-oasis-place-revisions'] == '7,7,7'
        star = [[r*math.cos(i*math.pi/4), r*math.sin(i*math.pi/4)]
                for i, r in enumerate([.89, .39]*4)]
        pair = planned_request(page, page.request.get(url+API).json(), ['sketch-2','books','sketch-3'],
                               custom={'sketch-2':sketch, 'sketch-3':star+[star[0]]})
        parts = pair['motion']['parts']
        tags = {p['place']:p['customReveal'] for p in parts}
        assert set(tags) == {0,2} and 'second' in tags[2]
        swapped = [dict(p, customReveal=other['customReveal']) for p, other in zip(parts, reversed(parts))]
        put(page, url, edited_motion(pair, parts=swapped), 400)
        missing = copy.deepcopy(parts)
        del next(p for p in missing if p['place'] == 2)['customReveal']['second']
        put(page, url, edited_motion(pair, parts=missing), 400)
        assert put(page, url, pair, 200).json()['revision'] == 8
        assert page.request.get(url+API).headers['x-oasis-place-revisions'] == '8,7,8'
        occupied = planned_request(page, page.request.get(url+API).json(), wrong['state']['ids'], whole=True)
        assert put(page, url, occupied, 200).json()['revision'] == 9
        # The same direct fill and custom replacement now start in the claimed places.
        fill_pair = planned_request(page, page.request.get(url+API).json(), tour['state']['ids'],
                                    custom={'sketch-1':sketch})
        assert fill_pair['motion'] == foreign['motion']
        assert put(page, url, fill_pair, 200).json()['revision'] == 10
    print('Paired guest saves checked both signatures, exact prior files, omitted parts, stale sources and revisions. '
          'Both attached and virtual rooms accepted historical whole-ring paths. Three guests mixed an occupied '
          'replacement with two direct additions including a sketch. A dock-to-dock tour filled two open places, '
          'checked both engravings and resumed the signed files in order across restart. '
          'Two new sketches revealed their own outlines, including a two-visit star. A native-and-sketch pair '
          'checked the locked source, sketch crossing, file seam and order through a second restart.')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, Path(temp))
