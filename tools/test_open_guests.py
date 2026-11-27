#!/usr/bin/env python3
"""Verify no-erase fills of proved-open guest places using two phones and a simulated table.

python3 tools/test_open_guests.py OPEN_GALLERY --occupied OCCUPIED_GALLERY --evidence DIR
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
from unittest import TestCase

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from garden_room import Layout
from guest_fill_checks import checked_fill, original_excursion
from test_attached_garden import Table, served, wait_table
from test_garden_room import API, choose, drawing_files, open_room, suggest
from test_guest_place import contour, contour_samples, old_relief, physical_parts, sketch, unpack
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_photo import frame


def scene(page):
    return page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")


def signed_setup(page, live):
    catalog = live['planner']
    files = drawing_files(page, '#setupFiles')
    assert [data for _, data in files] == [f['text'].encode() for f in live['setup']]
    layout = from_files(files, unpack(catalog['transit'])[0])
    art = np.asarray(
        page.evaluate("""()=>{const c=JSON.parse(document.querySelector('#scene').textContent).live.planner;
                       return OasisRingPlanner.plan(c,c.defaults).art;}""")
    )
    candidates = np.where(
        (abs(check.wrapped(layout[:, 0] - art[0, 0])) < check.TOL) & (abs(layout[:, 1] - art[0, 1]) < check.TOL)
    )[0]
    found = [i for i in candidates if check.same_track(layout[i : i + len(art)], art)]
    assert len(found) == 1, 'The actual setup omitted or duplicated its declared guest drawings.'
    i = found[0]
    return layout[: i + 1], layout[i + len(art) - 1 :]


def private_profiles(browser, blank, occupied):
    # Give both real, self-contained pages exactly the same origin and clean
    # browser storage. Intercept all requests; neither gallery contacts a service.
    base = 'http://127.0.0.1:9012'
    docs = {base + '/blank': blank.read_bytes(), base + '/occupied': occupied.read_bytes()}
    with browser.new_context(**MOBILE) as ctx:
        ctx.route(
            '**/*',
            lambda r: r.fulfill(content_type='text/html', body=docs[r.request.url])
            if r.request.url in docs
            else r.abort(),
        )
        p = ctx.new_page()

        def visit(name):
            p.goto(base + '/' + name + '#guests')
            expect(p.locator('.controls')).not_to_have_attribute('inert', '')
            return scene(p)

        def stored(key):
            return p.evaluate('k=>JSON.parse(localStorage.getItem(k))', key)

        normal = visit('occupied')
        normal_setup = signed_setup(p, normal)
        normal_key = normal.get('storageKey', 'oasis-ring-garden-v1')
        assert normal['planner']['defaults'] == ['phage', 'books', 'temple']

        def other():
            p.locator('#layout').select_option('portrait')
            portrait = p.evaluate("JSON.parse(document.querySelector('#scene').textContent)")
            p.locator('#layout').select_option('garden')
            choose(p, 'zone', 'middle')
            return portrait

        portrait = other()
        assert portrait['layout'] == 'portrait' and 'middle' not in portrait['zones']
        p.locator('#openGuestPlaces').click()
        expect(p.locator('#keep')).to_be_visible()
        full = drawing_files(p, '#downloads')
        clear = normal['planner']['openSubject']
        empty = [clear] * 3
        wanted = p.evaluate(
            """ids=>OasisRingPlanner.files(OasisRingPlanner.plan(
            JSON.parse(document.querySelector('#scene').textContent).live.planner,ids).path,'guest-ring')""",
            empty,
        )
        assert full == [(f['name'], f['text'].encode()) for f in wanted]
        layout = Layout(p.evaluate("JSON.parse(document.getElementById('scene').textContent)"))
        layout.check_route('middle', wanted, state={'ids': empty})
        occupied_files = p.evaluate("""()=>{const c=JSON.parse(document.getElementById('scene').textContent).live.planner;
                 return OasisRingPlanner.files(OasisRingPlanner.plan(c,c.defaults).path);}""")
        with TestCase().assertRaisesRegex(ValueError, 'open place contains a drawing'):
            layout.check_route('middle', occupied_files, state={'ids': empty})
        assert stored(normal_key) is None
        # Keeping a different private drawing must not appear in the open profile.
        suggest(p, 'a pumpkin for Thomas')
        p.locator('#keep').click()
        kept = stored(normal_key)
        assert kept['ids'] == ['pumpkin', 'books', 'temple']
        opened = visit('blank')
        blank_setup = signed_setup(p, opened)
        for a, b in zip(normal_setup, blank_setup):
            assert check.same_track(a, b), 'Blank setup changed travel outside the guest ring.'
        for slot, gate in enumerate(opened['planner']['geometry']['gates']):
            trips = opened['planner']['excursions'][slot]
            rail = unpack(trips[clear])
            np.testing.assert_allclose(rail[[0, -1], 0], gate, rtol=0, atol=check.TOL)
            assert np.all(np.diff(rail[:, 0]) > 0) and np.allclose(
                rail[:, 1], opened['planner']['geometry']['rail']
            )
        open_key = opened['storageKey']
        assert open_key != normal_key and opened['planner']['defaults'] == empty
        assert opened['setup'] != normal['setup'] and opened['bed'] != normal['bed']
        assert other() == portrait, 'The portrait layout was altered by an empty guest setup.'
        assert stored(open_key) is None
        suggest(p, 'a guitar for Thomas')
        p.locator('#keep').click()
        new = stored(open_key)
        assert new['ids'] == ['guitar', clear, clear]
        for name, key, snapshot in (('occupied', normal_key, kept), ('blank', open_key, new)):
            visit(name)
            assert stored(key) == snapshot
            choose(p, 'stage', 'original')
            img = frame(p)
            raster = p.evaluate(
                """encoded=>{
                const s=JSON.parse(document.querySelector('#scene').textContent).live;
                const bed=Float32Array.from(atob(encoded),c=>c.charCodeAt(0)/170-1);
                return new RingSand(s.size,s.groove,s.profile).image(bed)===document.querySelector('#sand').src;
            }""",
                snapshot['bed'],
            )
            assert img.size and raster, 'The gallery restored the other profile’s saved bed.'
        return {
            'conventional': normal_key,
            'open': open_key,
            'portrait_unchanged': True,
            'all_open_full_ring_files': len(full),
        }


def verify_download(page, out, old, new, slot, files, frames, live, fill, short_fill=...):
    catalog = live['planner']
    geo = catalog['geometry']
    tile = catalog['places'][slot]
    open_subject = catalog['openSubject']
    route = from_files(files, unpack(catalog['transit'])[0])
    subject = new['ids'][slot]
    if fill:
        assert old['ids'][slot] == open_subject and subject != open_subject
        engraving = original_excursion(page, catalog, new, slot)
        start, art, exit_path = checked_fill(route, catalog, slot, engraving, short_fill)
        a = len(start) - 1
        length = check.travel(art)
        mid = int(np.argmin(abs(length - length[-1] / 2)))
        assert 0 < mid < len(art) - 1
        parts = [start, art[:mid+1], art[mid:], exit_path]
    else:
        assert subject == open_subject and old['ids'][slot] != open_subject
        parts = physical_parts(route, tile, catalog)
        # The last excursion now follows the decorative rail only.
        count = len(unpack(tile['recut'])) - 1
        art = parts[2][count:]
        assert check.same_track(art, unpack(catalog['excursions'][slot][open_subject]))
        assert np.max(abs(art[:, 1] - geo['rail'])) < check.TOL
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        assert Path(name).name == name
        (out / name).write_bytes(data)
    g = live['groove']
    R = live['radiusMM']
    n = len(frames[0])
    step = g / 32
    ys, xs = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
    r = np.hypot(xs, ys)
    lo, hi = geo['bounds']
    mask = (r < lo - 2 * g) | ((r > hi + 2 * g) & (r < 0.99) & ((ys < 0) | (abs(xs) > 2 * g)))
    tree = cKDTree(check.sample_walk(route, step))
    near = {}
    for neighbor in set(range(3)) - {slot}:
        assert old['ids'][neighbor] == new['ids'][neighbor]
        angle = geo['angles'][neighbor]
        cx, cy = geo['center'] * np.array([math.cos(angle), math.sin(angle)])
        # Include the complete interior of every other place in the displayed comparison.
        mask |= np.hypot(xs - cx, -ys - cy) < geo['scale'] * 0.93
        if old['ids'][neighbor] == open_subject:
            continue
        points = contour_samples(contour(old, neighbor, geo), step)
        assert np.array_equal(points, contour_samples(contour(new, neighbor, geo), step))
        lower = tree.query(points)[0].min() - step
        assert lower > 1.65 * g, ('a neighboring engraving touched moving sand', slot, neighbor, lower * R)
        near[old['ids'][neighbor]] = round(lower * R, 2)
    for name, img in zip(('before', 'middle', 'after'), frames):
        Image.fromarray(img).save(out / (name + '.png'))
        assert np.array_equal(img[mask], frames[0][mask]), ('neighbor changed', name)
    for img, moves in ((frames[1], parts[:2]), (frames[2], parts)):
        diff = abs(replay(page, old['bed'], *moves).astype(np.int16) - img.astype(np.int16))
        assert diff.mean() < 1.1 and np.percentile(diff, 99) < 5, (
            'different phone preview from download',
            diff.mean(),
        )
    assert np.any(frames[2] != frames[0]) and np.any(frames[1] != frames[2])
    result = {
        'place': slot,
        'from': old['ids'][slot],
        'to': subject,
        'route_m': round(check.travel(route)[-1] * R / 1000, 3),
        'protected_pixels': int(mask.sum()),
        'closest_neighbor_mm': near,
        'sha256': [hashlib.sha256(b).hexdigest() for _, b in files],
    }
    if fill:
        points = contour_samples(contour(new, slot, geo), step)
        ink = cKDTree(check.sample_walk(art, step))
        assert ink.query(points)[0].max() < g * 0.14, 'Actual engraving is missing the new drawing.'
        # Locate the first signed row at the hanging point of the new symbol.
        # The initial rail and hanging line read as setup travel to a spectator.
        xy = art[:, 1, None] * np.column_stack((np.cos(art[:, 0]), np.sin(art[:, 0])))
        first = np.flatnonzero(cKDTree(points).query(xy)[0] < g * 0.10)[0]
        d = check.travel(route)
        occupied_ids = new['ids'].copy()
        occupied_ids[slot] = 'phage' if subject != 'phage' else 'books'
        regular = page.evaluate(
            """([previous,next,custom,slot])=>{
                const c=JSON.parse(document.querySelector('#scene').textContent).live.planner;
                // Compare to an ordinary occupied-place clear even in galleries
                // which can visit a few selected subjects during that clear.
                for (const key of ['additions','reveals','revealTargets']) delete c.places[slot][key];
                delete c.customReveal;
                return OasisRingPlanner.planChange(c,previous,next,custom).path;
            }""",
            [occupied_ids, new['ids'], new['custom'], slot],
        )
        regular = np.asarray(regular)
        regular_parts = physical_parts(regular, tile, catalog)
        start_of_guest = len(unpack(tile['recut'])) - 1
        ordinary_art = regular_parts[2][start_of_guest:]
        assert check.same_track(engraving, ordinary_art), 'The fill changed the original gate-to-gate engraving.'
        ordinary_xy = ordinary_art[:,1,None] * np.column_stack((np.cos(ordinary_art[:,0]), np.sin(ordinary_art[:,0])))
        first_on_ordinary = np.flatnonzero(cKDTree(points).query(ordinary_xy)[0] < g * 0.10)[0]
        first_ordinary = sum(len(p)-1 for p in regular_parts[:2]) + start_of_guest + first_on_ordinary
        totals = check.travel(regular)
        assert d[a + first] < totals[first_ordinary] and d[-1] < totals[-1]
        result.update(
            first_subject_m=round(d[a + first] * R / 1000, 3),
            occupied_first_subject_m=round(totals[first_ordinary] * R / 1000, 3),
            occupied_route_m=round(totals[-1] * R / 1000, 3),
            travel_fraction=round(d[-1] / totals[-1], 4),
        )
    else:
        result.update(
            old_relief(
                page, old['bed'], contour(old, slot, geo), check.sample_walk(art, step), parts, catalog, g, n
            )
        )
    return result


def exercise(browser, gallery, occupied, out, db):
    report = {'private_profiles': private_profiles(browser, gallery, occupied)}
    table = Table(db)
    queue = []
    errors = []
    with (
        served(gallery, db, table, prepared=True) as url,
        browser.new_context(**MOBILE) as a,
        browser.new_context(**MOBILE) as b,
    ):
        phones = [c.new_page() for c in (a, b)]
        for p in phones:
            p.on('pageerror', lambda e: errors.append(str(e)))
            open_room(p, url)
        live = scene(phones[0])
        c = live['planner']
        empty = [c['openSubject']] * 3
        assert c['defaults'] == empty
        queue.extend(live['setup'])
        assert table.dispatched(1) == queue[0]

        # Keep one preview genuinely on revision zero while the other phone fills Thomas's place.
        def hold_poll(route):
            tag = route.request.headers.get('if-none-match')
            if route.request.method == 'GET' and tag:
                route.fulfill(status=304, headers={'ETag': tag})
            else:
                route.continue_()

        phones[1].route('**' + API, hold_poll)
        suggest(phones[1], 'a rocket for Thomas')
        edits = [
            ('Thomas', 0, lambda p: suggest(p, 'a guitar for Thomas')),
            ('Alex', 1, lambda p: suggest(p, 'books for Alex')),
            ('Lek', 2, lambda p: sketch(p, 'Lek')),
            ('clear-Thomas', 0, lambda p: suggest(p, 'clear Thomas’s place')),
            ('refill-Thomas', 0, lambda p: suggest(p, 'a rocket for Thomas')),
        ]
        stale_fill = None
        for index, (label, slot, action) in enumerate(edits):
            page, other = phones[:: 1 if index % 2 == 0 else -1]
            record = page.request.get(url + API).json()
            old = record['state'] or dict(ids=empty, custom={}, bed=live['bed'])
            choose(page, 'stage', 'original')
            original = frame(page)
            action(page)
            end = frame(page)
            files = drawing_files(page, '#downloads')
            choose(page, 'stage', 'cleared')
            middle = frame(page)
            fill = label != 'clear-Thomas'
            if fill:
                assert page.locator('#middleStageLabel').inner_text() == 'Halfway'
            choose(page, 'stage', 'redrawn')
            body, rev = save(page, url + API)
            motion = body['motion']
            assert motion['zone'] == 'middle' and motion['place'] == slot and motion.get('fill', False) == fill
            assert files == [(f['name'], f['text'].encode()) for f in motion['files']]
            queue.extend(motion['files'])
            if index == 0:
                with other.expect_response(
                    lambda r: r.request.method == 'PUT' and r.url == url + API
                ) as save_stale:
                    other.locator('#keep').click()
                response = save_stale.value
                assert response.status == 409
                stale_fill = response.request.post_data_json
                assert stale_fill['motion']['fill'] and stale_fill['state']['ids'][0] == 'rocket'
                other.unroute('**' + API, hold_poll)
                # The current sand, not just the revision and route shape, decides fill eligibility.
                latest = {**stale_fill, 'revision': rev}
                wrong = other.request.put(url + API, headers={'Origin': url}, data=latest)
                assert wrong.status == 400, wrong.text()
                missing = {**latest, 'motion': dict(latest['motion'])}
                del missing['motion']['fill']
                wrong = other.request.put(url + API, headers={'Origin': url}, data=missing)
                assert wrong.status == 400, wrong.text()
                assert other.request.get(url + API).json()['revision'] == rev
            other.goto('about:blank')
            open_room(other, url)
            assert other.request.get(url + API).json()['state'] == body['state']
            assert drawing_files(other, '#roomFiles') == files
            report[label] = verify_download(
                page, out / label, old, body['state'], slot, files, (original, middle, end), live, fill, motion.get('shortFill')
            )
            if label == 'refill-Thomas':
                assert motion['files'] == stale_fill['motion']['files'], (
                    'The same fill changes after a real clear.'
                )
            print(label, report[label], flush=True)
        assert not errors, errors
        assert len(table.calls) == 1
        wait_table(phones[0], url, state='drawing', revision=len(edits), queued=len(edits))
        # Finish setup, then fail the first submitted fill. The dependent clear/refill
        # must stay queued until this exact controller receipt is confirmed on restart.
        for i, part in enumerate(live['setup'], 1):
            assert table.dispatched(i) == part
            table.outcome = 'complete'
        first_fill = len(live['setup']) + 1
        assert table.dispatched(first_fill) == queue[first_fill - 1]
        table.outcome = 'failed'
        wait_table(phones[0], url, state='blocked')
        assert len(table.calls) == first_fill
    with served(gallery, db, table) as url, browser.new_context(**MOBILE) as phone:
        p = phone.new_page()
        open_room(p, url)
        wait_table(p, url, state='blocked', revision=len(edits))
        assert len(table.calls) == first_fill
        table.outcome = 'complete'
        for i, part in enumerate(queue[first_fill:], first_fill + 1):
            assert table.dispatched(i) == part
            table.outcome = 'complete'
        wait_table(p, url, state='idle', ready=True, queued=0)
        assert len(table.calls) == len(queue)
    report['controller'] = {'files': len(queue), 'changes': len(edits), 'failed_fill_held_after_restart': True}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path, help='new gallery built with --open-guests')
    parser.add_argument('--occupied', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report = exercise(browser, args.gallery, args.occupied, args.evidence, Path(folder) / 'room.db')
    (args.evidence / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Open and occupied profiles, two phones, fill/clear/refill, custom sketch and queued restart passed.')


if __name__ == '__main__':
    main()
