#!/usr/bin/env python3
"""Preview and keep one suggestion for several dinner guests on two phones in a local room.

Pass a fitted three-place gallery with open guest places. No table is attached.
"""
import argparse
import base64
import io
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

import check_ring_scene as check
from guest_fill_checks import checked_fill, check_tour_leg, tour_legs
from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_place import unpack
from test_ring_guest_border import MOBILE, replay, save
from test_ring_photo import frame
from test_saved_guest_drawings import ask


OPEN = {0: 'a phage for Thomas', 1: 'books for Alex', 2: 'a Thai rooftop for Lek'}
REPLACE = {0: 'a guitar for Thomas', 1: 'a pumpkin for Alex'}
BATCH = 'a phage for Thomas, books for Alex and a Thai rooftop for Lek'


def single_drawings(page, gallery):
    page.goto(gallery.resolve().as_uri() + '?layout=garden#guests')
    live = page.evaluate("""() => {
      const live=JSON.parse(document.querySelector('#scene').textContent).live, c=live.planner;
      return {key:live.storageKey || 'oasis-ring-garden-v1', bed:live.bed, groove:live.groove, radiusMM:live.radiusMM,
        geometry:c.geometry, transit:c.transit, fillTours:c.fillTours, excursions:c.excursions,
        places:c.places.map(p=>({approach:p.approach,exit:p.fillExit||p.exit,shortFill:p.shortFill||{}}))};
    }""")
    reference = []
    for requests in (OPEN, REPLACE):
        trips = {}
        for place, request in requests.items():
            suggest(page, request)
            trips[place] = [body for _, body in drawing_files(page, '#downloads')]
            page.locator('#keep').click()
            expect(page.locator('#keep')).to_be_hidden()
        ids = page.evaluate('k => JSON.parse(localStorage.getItem(k)).ids', live['key'])
        labels = page.locator('.caption').inner_text().split(' / ')
        reference.append((ids, trips, labels))
    return live, reference


def regions(size, live):
    y, x = np.mgrid[-1:1:complex(size), -1:1:complex(size)]
    r = np.hypot(x, y)
    geo, g = live['geometry'], live['groove']
    lo, hi = geo['bounds']
    # Keep the shared entry groove and its shoulders outside the protected border sample.
    protected = (r < lo - 2*g) | ((r > hi + 2*g) & (r < .99) & ((y < 0) | (abs(x) > 2*g)))
    places = [np.hypot(x-geo['center']*np.cos(a), -y-geo['center']*np.sin(a)) < .9*geo['scale']
              for a in geo['angles']]
    return protected, places


def check_change(page, api, text, reference, bed, live, evidence):
    ids, trips, labels = reference
    initial = page.request.get(api).json()['revision']
    before = frame(page)
    suggest(page, text)
    proposed = frame(page)
    files = drawing_files(page, '#downloads')
    paths = [np.loadtxt(io.BytesIO(body)) for _, body in files]
    dock = unpack(live['transit'])[0]
    route = check.joined(paths, dock, dock, 'combined guest request')
    expected = replay(page, bed, *paths)
    error = np.abs(expected.astype(float) - proposed)
    assert error.mean() < 1.1 and np.percentile(error, 99) < 5, 'Preview and downloaded drawing disagree'
    expect(page.locator('#middleStageLabel')).to_have_text('In progress')
    choose(page, 'stage', 'cleared')
    middle = frame(page)
    progress = page.locator('.caption').inner_text()
    choose(page, 'stage', 'redrawn')
    assert np.array_equal(proposed, frame(page))
    assert page.request.get(api).json()['revision'] == initial
    protected, places = regions(len(before), live)
    for i, area in enumerate(places):
        if i not in trips:
            protected |= area
    for image in (middle, proposed):
        assert np.array_equal(before[protected], image[protected])
    finished = []
    for i in trips:
        area = places[i]
        assert not np.array_equal(before[area], proposed[area]), 'A requested place never changed'
        if np.array_equal(before[area], middle[area]):
            continue
        assert np.abs(middle[area].astype(float) - proposed[area]).mean() < .25, 'In-progress place is incomplete'
        finished.append(i)
    assert len(finished) == 1, 'The intermediate view should show the first finished guest'
    put, revision = save(page, api)
    motion, state = put['motion'], put['state']
    assert revision == initial + 1 and state['ids'] == ids
    assert files == [(f['name'], f['text'].encode()) for f in motion['files']]
    order = [part['place'] for part in motion['parts']]
    assert sorted(order) == sorted(trips) and finished == order[:1]
    assert progress.startswith(labels[finished[0]] + '.'), 'The first finished picture must match its caption'
    canonical = [body for place in order for body in trips[place]]
    if motion.get('tour'):
        # Each seat still gets its individual, signed engraving. The journey
        # between two seats stays in the middle ring instead of returning to the rim.
        assert all(part['fill'] for part in motion['parts'])
        assert np.max(route[1:-1,1]) < 1-check.TOL
        start = 0
        for part, frozen in zip(motion['parts'], tour_legs(live, motion['parts'])):
            place = part['place']
            solo = check.joined([np.loadtxt(io.BytesIO(body)) for body in trips[place]], dock, dock, 'individual fill')
            art = unpack(live['excursions'][place][ids[place]])
            checked_fill(solo, live, place, art)
            chunks = paths[start:start+part['count']]
            leg = check.joined(chunks, chunks[0][0], chunks[-1][-1], 'connected fill')
            check_tour_leg(leg, frozen, art)
            start += part['count']
        assert start == len(paths)
        assert check.travel(route)[-1] < sum(check.travel(np.loadtxt(io.BytesIO(body)))[-1] for body in canonical)
    else:
        assert [body for _, body in files] == canonical
        for part in motion['parts']:
            if part.get('fill'):
                place = part['place']
                leg = check.joined([np.loadtxt(io.BytesIO(body)) for body in trips[place]], dock, dock, 'individual fill')
                checked_fill(leg, live, place, unpack(live['excursions'][place][ids[place]]), part.get('shortFill'))
    prev = np.frombuffer(base64.b64decode(bed), np.uint8)
    kept = np.frombuffer(base64.b64decode(state['bed']), np.uint8)
    assert np.array_equal(prev[protected.ravel()], kept[protected.ravel()])
    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        for name, data in files:
            (evidence / name).write_bytes(data)
        images = {'before': before, 'in-progress': middle, 'after': proposed, 'download-replay': expected}
        for label, image in images.items():
            Image.fromarray(image).save(evidence / (label + '.png'))
    metres = [check.travel(path)[-1] * live['radiusMM'] / 1000 for path in paths]
    return state, files, {
        'files': len(files), 'signed_rows': len(route), 'first_finished': labels[finished[0]],
        'first_finished_m': round(sum(metres[:motion['parts'][0]['count']]), 2), 'total_m': round(sum(metres), 2),
        'protected_pixels': int(protected.sum()), 'mean_replay_error': round(float(error.mean()), 3),
    }


def exercise(browser, gallery, database, out):
    with room(gallery, database) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        api = url + API
        errors = []
        for phone in (host, guest):
            phone.on('pageerror', lambda error: errors.append(str(error)))
            phone.route('http**://**/*', lambda r: r.continue_() if r.request.url.startswith(url + '/') else r.abort())
        live, (opening, replacements) = single_drawings(host, gallery)
        open_room(host, url)
        open_room(guest, url)
        state, files, initial = check_change(host, api, BATCH, opening, live['bed'], live, out / 'three' if out else None)
        guest.goto('about:blank')
        open_room(guest, url)
        assert drawing_files(guest, '#roomFiles') == files
        previous = guest.request.get(api).json()
        for invalid in ('a guitar for Thomas, a pumpkin for Thomas',
                        'a guitar for Thomas and a pumpkin for Rowan',
                        'a guitar for Thomas, a telescope for Alex and for Lek',
                        'a guitar for Thomas and a zqxwy for Lek'):
            ask(guest, invalid)
            expect(guest.locator('#keep')).to_be_hidden()
            expect(guest.locator('#downloads')).to_be_hidden()
            expect(guest.locator('#error')).not_to_have_text('')
            assert guest.request.get(api).json() == previous
        _, pair, later = check_change(guest, api, 'a guitar for Thomas and a pumpkin for Alex',
                                      replacements, state['bed'], live, out / 'two' if out else None)
        host.goto('about:blank')
        open_room(host, url)
        caption(host, 'Lek · ')
        assert drawing_files(host, '#roomFiles') == pair
        ask(host, 'a comet beside a telescope for Thomas and write “Hi” for Alex')
        caption(host, 'Thomas · Comet beside telescope')
        caption(host, 'Alex · “Hi”')
        mixed = save(host, api)[0]
        assert {part['place'] for part in mixed['motion']['parts']} == {0,1}
        assert mixed['state']['ids'][2] == state['ids'][2]
        # A subject that already matches in one named seat needs no trip.
        ask(host, 'something for Thomas and a Thai rooftop for Lek')
        expect(host.locator('#keep')).to_be_visible()
        single = save(host, api)[0]
        assert single['motion']['place'] == 0 and 'parts' not in single['motion']
        assert single['state']['ids'][1:] == mixed['state']['ids'][1:]
        assert not errors, errors
        return {'three_guest_request': initial, 'two_guest_replacement': later, 'canonical_ids': opening[0]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report = exercise(browser, args.gallery, Path(tmp) / 'room.db', args.evidence)
    if args.evidence:
        (args.evidence / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
