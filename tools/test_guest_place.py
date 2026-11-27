#!/usr/bin/env python3
"""Replay actual phone downloads on occupied sand and verify shared guest-place replacements.

    python3 tools/test_guest_place.py GALLERY --previous PRIOR_GALLERY --evidence DIR
All browser networking and the simulated table stay on loopback.
"""

import argparse
import base64
import copy
import hashlib
import json
import math
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
import ring_scene
from test_attached_garden import Table, served, wait_table
from test_garden_room import API, caption, choose, drawing_files, open_room, suggest
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_photo import frame


def unpack(data):
    return np.frombuffer(base64.b64decode(data), '<i4').reshape(-1, 2).cumsum(axis=0) / 1e8


def contour(state, slot, geometry):
    name = state['ids'][slot]
    path = state.get('custom', {}).get(name)
    if path is None:
        path = ring_scene.motif(name)
    a = geometry['angles'][slot]
    radial = np.array([math.cos(a), math.sin(a)])
    center = radial * geometry['center']
    if geometry.get('faceEdge'):
        # Reconstruct the viewer's axes independently: their right follows the
        # rim counterclockwise, and the top of the drawing points into the table.
        x, y = np.asarray(path).T
        path = x[:,None] * [-radial[1], radial[0]] - y[:,None] * radial
    return np.asarray(path) * geometry['scale'] + center


def contour_samples(points, spacing):
    ds = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    d = np.linspace(0, ds[-1], math.ceil(ds[-1] / spacing) + 1)
    return np.column_stack([np.interp(d, ds, column) for column in points.T])


def detour_indices(route, clear, offset):
    """Find early out-and-back visits from the signed rows, independently of the phone's indices."""
    expected = clear + [math.tau * round((route[offset,0]-clear[0,0])/math.tau), 0]

    def match(start, row, remaining):
        frozen = expected[row:]
        actual = route[start:start+len(frozen)]
        if len(actual) < len(frozen):
            return None
        mismatches = np.flatnonzero(np.any(abs(actual-frozen) > check.TOL, axis=1))
        if not len(mismatches):
            return []
        if not remaining:
            return None
        first = mismatches[0]
        # A crossing very close to the next ordinary point can also round to it.
        for pos in (first, first-1):
            if pos < 0:
                continue
            begin = start+pos
            resumes = np.flatnonzero(np.all(abs(route[begin:]-frozen[pos]) <= check.TOL, axis=1))
            for width in resumes:
                if width < 3 or width % 2 != 1:
                    continue
                stop = begin+width
                branch = route[begin:stop]
                if check.same_track(branch, branch[::-1]):
                    rest = match(stop+1, row+pos+1, remaining-1)
                    if rest is not None:
                        return [(begin, stop), *rest]
        return None

    visits = match(offset, 0, 2)
    assert visits is not None, 'The signed clearing departed from its frozen rows without retracing its branch.'
    return visits


def physical_parts(route, place, catalog, *, with_progress=False):
    access, clear, leaves, depart = [unpack(place[key]) for key in ('approach', 'clear', 'recut', 'exit')]
    # Boundaries come from the frozen public catalog. All evidence below comes from the
    # five-decimal download. The engraving length can vary for typed or freehand art.
    c = len(access) - 1
    a = c + len(clear) - 1
    visits = detour_indices(route, clear, c)
    a += sum(stop-start for start, stop in visits)
    cleared = route[c:a+1]
    for start, stop in reversed(visits):
        cleared = np.concatenate((cleared[:start-c], cleared[stop-c:]))
    progress = visits[-1][1]-1 if visits else a
    e = len(route) - len(depart)
    assert e > a + len(leaves)
    parts = [route[: c + 1], route[c : a + 1], route[a : e + 1], route[e:]]
    for actual, expected in zip(
        (parts[0], cleared, parts[2][: len(leaves)], parts[3]), (access, clear, leaves, depart)
    ):
        assert check.same_track(actual, expected), (
            'A frozen access, erase or return path changed in the phone download.'
        )
    geom = catalog['geometry']
    low, high = geom['bounds']
    rail, dock = geom['rail'], access[0, 0]
    # Fixed background strokes can fan out past the chosen subject's limits.
    # Other guest gate pairs bound where their engravings and hanging lines live.
    # Between the gates, only existing access circles may cross another place.
    slot = min(range(3), key=lambda i: abs(check.wrapped(geom['angles'][i] - np.mean(place['limits']))))
    wedge = np.ones(len(route), dtype=bool)
    for other, (left, right) in enumerate(geom['gates']):
        if other != slot:
            offset = abs(check.wrapped(route[:, 0] - (left + right) / 2))
            wedge &= offset >= (right - left) / 2 - check.TOL
    # A signed interpolation stays inside each convex angular/radial interval.
    # The signed difference test also rejects a complete turn between identical endpoints.
    assert abs(np.diff(route[:, 0])).max() < 0.2
    assert route[:, 1].min() >= low - check.TOL
    stem = check.seam_segments(route, dock)
    off_rail = ~stem
    for r in (rail, low, high):
        on_rail = abs(route[:, 1] - r) <= check.TOL
        off_rail &= ~(on_rail[:-1] & on_rail[1:])
    assert np.all((wedge[:-1] & wedge[1:])[off_rail]), 'A movement crosses a neighboring guest’s gates.'
    if 'workLimits' in place:
        left, right = place['workLimits']
        assert left < right and right - left < math.tau
        angle = abs(check.wrapped(route[:, 0] - (left + right) / 2))
        within = angle <= (right - left) / 2 + check.TOL
        assert np.all((within[:-1] & within[1:])[off_rail]), 'The actual clearing escaped its angular bounds.'
    beyond = route[:, 1] > high + check.TOL
    assert np.all(stem[beyond[:-1] | beyond[1:]])
    return (parts, progress) if with_progress else parts


def library_clearance(route, catalog, slot, live):
    """A future neighbor might use any stock design, even a long rocket or calendar tip."""
    g = live['groove']
    step = g / 48
    tree = cKDTree(check.sample_walk(route, step))
    nearest = math.inf
    worst = None
    for other in set(range(3)) - {slot}:
        for subject in catalog['subjects']:
            points = contour_samples(contour({'ids': [subject] * 3}, other, catalog['geometry']), step)
            distance = float(tree.query(points)[0].min())
            if distance < nearest:
                nearest, worst = distance, (other, subject)
    # The continuous tracks are at most a half sample from each sample cloud.
    # 1.15 grooves is the modeled reach of displaced sand, plus half a groove
    # for the existing engraving. The two footprints may not touch.
    lower = nearest - step
    assert lower > 1.65 * g, (
        'the travel can disturb an existing stock drawing',
        slot,
        worst,
        lower * live['radiusMM'],
    )
    return {
        'neighbor': worst,
        'minimum_mm': round(lower * live['radiusMM'], 2),
        'catalog_subjects': len(catalog['subjects']),
    }


def old_relief(page, bed, before, after, parts, catalog, groove, size):
    old = contour_samples(before, groove / 12)
    final = cKDTree(contour_samples(after, groove / 12))
    unique = old[final.query(old)[0] > 1.25 * groove]
    uv = np.rint((unique * [1, -1] + 1) * ((size - 1) / 2)).astype(int)
    pixels = np.unique(uv[:, 1] * size + uv[:, 0]).tolist()
    values = page.evaluate(
        """([raw,erase,parts,pixels])=>{
        const meta=JSON.parse(document.querySelector('#scene').textContent).live;
        const a=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1), b=a.slice();
        const sim=new RingSand(meta.size,meta.groove,meta.profile);
        sim.carve(b,erase);
        const sites=pixels.filter(i=>Math.abs(a[i]-b[i])>=.15);
        const diff=()=>sites.reduce((s,i)=>s+Math.abs(a[i]-b[i]),0);
        const before=diff(); const remaining=[];
        for(const part of parts){sim.carve(a,part);sim.carve(b,part);remaining.push(diff()/before);}
        return [sites.length,remaining[1],remaining[3]];
    }""",
        [bed, unpack(catalog['erase']).tolist(), [p.tolist() for p in parts], pixels],
    )
    assert values[0] > 24 and max(values[1:]) < 0.025, ('old subject relief survived the new clearing', values)
    return {
        'old_pixels': values[0],
        'old_relief_after_clear': round(values[1], 5),
        'old_relief_after_redraw': round(values[2], 5),
    }


def evidence(page, folder, before, after, frames, files, catalog, slot, live):
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        assert name == Path(name).name
        (folder / name).write_bytes(data)
    place = catalog['places'][slot]
    dock = unpack(catalog['transit'])[0]
    route = from_files(files, dock)
    parts, progress = physical_parts(route, place, catalog, with_progress=True)
    geom = catalog['geometry']
    g = live['groove']
    s = len(frames[0])
    yy, xx = np.mgrid[-1 : 1 : complex(s), -1 : 1 : complex(s)]
    r = np.hypot(xx, yy)
    lo, hi = geom['bounds']
    protected = (r < lo - 2 * g) | ((r > hi + 2 * g) & (r < 0.99) & ((yy < 0) | (abs(xx) > 2 * g)))
    xy = np.stack([xx, -yy], axis=-1)
    sample_step = g / 24
    all_motion = cKDTree(check.sample_walk(route, sample_step))
    engraved = np.zeros_like(protected)
    shoulders = np.zeros_like(protected)
    cores = np.zeros_like(protected)
    clearances = {}
    for other in set(range(3)) - {slot}:
        assert before['ids'][other] == after['ids'][other]
        points = contour_samples(contour(before, other, geom), sample_step)
        assert np.array_equal(points, contour_samples(contour(after, other, geom), sample_step))
        nearest = all_motion.query(points)[0].min() - sample_step
        # Both sample clouds are at most half a step from the continuous walks.
        # This bound applies through every movement, before and after each frame.
        assert nearest > 1.65 * g, ('physical route approaches a sibling picture', other, nearest / g)
        clearances[before['ids'][other]] = round(float(nearest * live['radiusMM']), 1)
        lower, upper = points.min(axis=0) - g, points.max(axis=0) + g
        box = ((xy >= lower) & (xy <= upper)).all(axis=-1)
        dist = cKDTree(points).query(xy[box])[0]
        assert np.sum(dist < 0.5 * g) > 150 and np.ptp(frames[0][box][dist < 0.5 * g]) > 20
        engraved[box] |= dist <= 0.5 * g
        shoulders[box] |= dist <= 0.85 * g
        cores[box] |= dist < 0.3 * g
    unchanged_heights = page.evaluate(
        """([raw,parts,indices])=>{
        const s=JSON.parse(document.querySelector('#scene').textContent).live;
        const old=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1), bed=old.slice();
        const sim=new RingSand(s.size,s.groove,s.profile);
        let delta=0;
        for (const part of parts){
          sim.carve(bed,part);
          for(const i of indices)delta=Math.max(delta,Math.abs(bed[i]-old[i]));
        }
        return delta;
    }""",
        [before['bed'], [p.tolist() for p in parts], np.flatnonzero(engraved).tolist()],
    )
    # Room saves quantize bed height into units of 1/170.
    assert unchanged_heights < 1 / 170, ('protected relief changed by a saved height step', unchanged_heights)
    original, clear, redrawn = frames
    shadow_error = 0
    core_peak = 0
    for label, img in zip(('before', 'progress' if progress < len(parts[0])+len(parts[1])-2 else 'cleared', 'redrawn'), frames):
        Image.fromarray(img).save(folder / (label + '.png'))
        assert np.array_equal(original[protected], img[protected]), ('another engraving changed', label)
        delta = np.max(abs(original[shoulders].astype(int) - img[shoulders].astype(int)), axis=1)
        shadow_error = max(shadow_error, float(np.mean(delta)))
        core = np.max(abs(original[cores].astype(int) - img[cores].astype(int)), axis=1)
        core_peak = max(core_peak, int(core.max()))
        # Reusing the hanging rail can change the light on some neighboring
        # shoulders and tips. Measure and report that separately from bed height.
        assert core.max() < 12 and np.mean(core) < 0.25
        assert np.mean(delta) < 1 and np.mean(delta > 24) < 0.01, (
            'neighbor picture changed',
            label,
            np.mean(delta),
        )
    assert not np.array_equal(original, clear) and not np.array_equal(clear, redrawn)
    for img, moves in ((clear, (route[:progress+1],)), (redrawn, parts)):
        rebuilt = replay(page, before['bed'], *moves)
        delta = abs(rebuilt.astype(np.int16) - img.astype(np.int16))
        assert delta.mean() < 1.1 and np.percentile(delta, 99) < 5, ('phone versus download', delta.mean())
    old, new = (contour(state, slot, geom) for state in (before, after))
    engraving = cKDTree(check.sample_walk(parts[2], g / 24))
    missing = engraving.query(contour_samples(new, g / 12))[0].max()
    assert missing < 0.15 * g, ('selected contour missing from the engraving', missing / g)
    full = page.evaluate(
        """s=>OasisRingPlanner.plan(JSON.parse(document.querySelector('#scene').textContent)
                .live.planner,s.ids,s.custom).path""",
        {'ids': after['ids'], 'custom': after['custom']},
    )
    meters = lambda p: round(float(check.travel(np.asarray(p))[-1]) * live['radiusMM'] / 1000, 2)
    return {
        'place': slot,
        'before': before['ids'][slot],
        'after': after['ids'][slot],
        'distance_m': meters(route),
        'full_ring_m': meters(full),
        'signed_points': len(route),
        'bytes_sha256': [hashlib.sha256(data).hexdigest() for _, data in files],
        'untouched_pixels': int(protected.sum()),
        'neighbor_relief_max_change': float(unchanged_heights),
        'neighbor_shoulder_mean_RGB_error': round(shadow_error, 4),
        'neighbor_core_peak_RGB_error': core_peak,
        'nearest_sibling_mm': clearances,
        **old_relief(page, before['bed'], old, new, parts, catalog, g, s),
    }


def sketch(page, name):
    button = page.get_by_role('button', name='Preview suggestion')
    page.locator('#idea').fill('a qzxwgy for ' + name)
    button.click()
    pad = page.locator('#sketchPad')
    pad.scroll_into_view_if_needed()
    rect = pad.bounding_box()
    x, y = rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2
    page.mouse.move(x - 35, y + 4)
    page.mouse.down()
    for dx, dy in ((-17, -25), (0, -7), (14, -30), (37, 14)):
        page.mouse.move(x + dx, y + dy, steps=5)
    page.mouse.up()
    button.click()
    expect(page.locator('#keep')).to_be_visible()


def guest(page, name, slot, interest=None):
    box = page.locator('#peopleBox')
    if not box.evaluate('e=>e.open'):
        box.locator('summary').click()
    picker = page.locator('#personPick')
    options = picker.locator('option').evaluate_all('os=>os.map(o=>[o.textContent,o.value])')
    if interest is None:
        picker.select_option(next(v for label, v in options if name.lower() in label.lower()))
    else:
        picker.select_option('')
        page.locator('#personName').fill(name)
        page.locator('#personInterest').fill(interest)
    page.locator('#personPlace').select_option(str(slot))
    page.locator('#personSubmit').click()
    expect(page.locator('#keep')).to_be_visible()


def dense_sketch(page, url):
    # A few long strokes after thousands of points at a single tip. The file
    # rounds many short movements onto the same few motor coordinates.
    rng = np.random.default_rng(6)
    tip = 0.65 + rng.uniform(-0.000022, 0.000022, (6997, 2))
    shape = np.vstack((tip, [-0.5, 0.2], [0.3, -0.8], tip[0])).tolist()
    prior = page.request.get(url + API).json()
    draft = page.evaluate(
        """([previous,shape])=>{
        const meta=JSON.parse(document.querySelector('#scene').textContent).live;
        const state=structuredClone(previous.state), ids=state.ids.slice(), id='sketch-7000';
        ids[0]=id;state.custom[id]=shape;state.labels[id]='Fine-tipped sketch';
        const route=OasisRingPlanner.planChange(meta.planner,state.ids,ids,state.custom);
        if(route.place!==0)throw Error('Expected a single-place sketch');
        const files=OasisRingPlanner.files(route.path,'guest-ring');
        const h=Float32Array.from(atob(state.bed),c=>c.charCodeAt(0)/170-1);
        const sim=new RingSand(meta.size,meta.groove,meta.profile);
        for(const part of route.segments)sim.carve(h,part);
        const bytes=Uint8Array.from(h,v=>Math.round((1+Math.max(-1,Math.min(.5,v)))*170));
        let packed='';
        for(let i=0;i<bytes.length;i+=8192)packed+=String.fromCharCode(...bytes.subarray(i,i+8192));
        state.bed=btoa(packed);state.ids=ids;
        state.guestBook.people.find(p=>GuestArt.normalize(p.name)===state.guestBook.active[0]).subject=id;
        return {state,revision:previous.revision,motion:{zone:'middle',place:0,files}};
    }""",
        [prior, shape],
    )
    response = page.request.put(url + API, headers={'Origin': url}, data=draft)
    assert response.status == 200, response.text()
    stored = page.request.get(url + API + '/drawings/middle').json()['files']
    assert stored == draft['motion']['files']
    return {'sketch_vertices': len(shape), 'exported_rows': sum(len(f['text'].splitlines()) for f in stored)}


def frozen(browser, gallery, previous, folder):
    # A genuine previous editor saves the occupied bed and guest book. Reopen that
    # very database with the new editor, without translating the saved subjects.

    db = folder / 'old-room.db'
    table = Table(db)
    with browser.new_context(**MOBILE) as ctx:
        page = ctx.new_page()
        with served(previous, db, table, prepared=True) as url:
            open_room(page, url)
            suggest(page, 'a pumpkin for Alex')
            old_files = drawing_files(page, '#downloads')
            old, rev = save(page, url + API)
            assert 'place' not in old['motion']
            old_fingerprint = old['state']['edition']
        with served(gallery, db, table) as url:
            open_room(page, url)
            caption(page, 'Alex · Pumpkin')
            assert page.request.get(url + API).json()['state'] == old['state']
            assert drawing_files(page, '#roomFiles') == old_files
            # An active-place swap changes two pictures together, so it must still
            # produce the same canonical full-ring export the older gallery can play.
            guest(page, 'Alex', 0)
            full = drawing_files(page, '#downloads')
            new, after = save(page, url + API)
            assert after == rev + 1 and 'place' not in new['motion']
            want = page.evaluate(
                """s=>OasisRingPlanner.files(OasisRingPlanner.plan(
              JSON.parse(document.querySelector('#scene').textContent).live.planner,s.ids,s.custom).path,'guest-ring')
              """,
                {'ids': new['state']['ids'], 'custom': new['state']['custom']},
            )
            assert full == [(f['name'], f['text'].encode()) for f in want]
            wait_table(page, url, state='drawing', revision=after, queued=2)
            assert len(table.calls) == 1
            return {
                'earlier_edition': old_fingerprint,
                'old_files_recovered': len(old_files),
                'whole_ring_points': sum(len(b.splitlines()) for _, b in full),
                'dense_sketch': dense_sketch(page, url),
            }


def exercise(browser, gallery, folder, out):
    database = folder / 'attached.db'
    table = Table(database)
    queue = []
    errors = []
    results = {}
    with (
        served(gallery, database, table, prepared=True) as url,
        browser.new_context(**MOBILE) as a,
        browser.new_context(**MOBILE) as b,
    ):
        phones = [c.new_page() for c in (a, b)]
        for phone in phones:
            phone.on('pageerror', lambda e: errors.append(str(e)))
            open_room(phone, url)
        live = phones[0].evaluate("""()=>{const s=JSON.parse(document.querySelector('#scene').textContent).live;
                  return {groove:s.groove,radiusMM:s.radiusMM,planner:s.planner,bed:s.bed,setup:s.setup};}""")
        catalog = live['planner']
        queue.extend(live['setup'])
        assert table.dispatched(1) == queue[0]
        # Leave setup running. Accepted changes depend in order on each previous
        # intended bed even while the simulated controller is working on setup.
        actions = [
            ('Thomas', 0, lambda p: suggest(p, 'a guitar for Thomas')),
            ('Alex', 1, lambda p: suggest(p, 'a guitar leaning against my books for Alex')),
            ('Lek', 2, lambda p: sketch(p, 'Lek')),
            ('Thomas-again', 0, lambda p: suggest(p, 'a rocket for Thomas')),
            ('Maya', 2, lambda p: guest(p, 'Maya', 2, 'stargazing')),
            ('Lek-return', 2, lambda p: guest(p, 'Lek', 2)),
        ]
        first_sketch = None
        for i, (key, slot, action) in enumerate(actions):
            page, viewer = phones[:: 1 if i % 2 == 0 else -1]
            before = page.request.get(url + API).json()['state'] or dict(
                ids=catalog['defaults'], bed=live['bed'], custom={}
            )
            choose(page, 'stage', 'original')
            original = frame(page)
            action(page)
            redrawn = frame(page)
            files = drawing_files(page, '#downloads')
            choose(page, 'stage', 'cleared')
            caption(page, 'place cleared')
            cleared = frame(page)
            choose(page, 'stage', 'redrawn')
            if key == 'Thomas-again':
                # Validate against this exact earlier bed, before accepting the normal
                # save. Even under the same identifier an undrawn sibling contour is
                # a second change. Missing the single-place field must not bypass it.
                def check_before_save(route):
                    if route.request.method != 'PUT':
                        route.continue_()
                        return
                    draft = route.request.post_data_json
                    wrong = copy.deepcopy(draft)
                    sibling = wrong['state']['ids'][2]
                    points = wrong['state']['custom'][sibling]
                    wrong['state']['custom'][sibling] = [[x * 0.8, y * 0.8] for x, y in points]
                    unmarked = copy.deepcopy(draft)
                    del unmarked['motion']['place']
                    for incompatible in (wrong, unmarked):
                        r = viewer.request.put(url + API, headers={'Origin': url}, data=incompatible)
                        assert r.status == 400, r.text()
                    route.continue_()

                page.route('**' + API, check_before_save)
            proposed, rev = save(page, url + API)
            if key == 'Thomas-again':
                page.unroute('**' + API, check_before_save)
            after = proposed['state']
            assert proposed['motion'].get('place') == slot, proposed['motion'].keys()
            assert files == [(f['name'], f['text'].encode()) for f in proposed['motion']['files']]
            queue.extend(proposed['motion']['files'])
            open_room(viewer, url)
            assert viewer.request.get(url + API).json()['state'] == after
            assert drawing_files(viewer, '#roomFiles') == files
            results[key] = evidence(
                page, out / key, before, after, (original, cleared, redrawn), files, catalog, slot, live
            )
            if i < 3:
                dock = unpack(catalog['transit'])[0]
                results[key]['stock_clearance'] = library_clearance(
                    from_files(files, dock), catalog, slot, live
                )
            if key == 'Lek':
                first_sketch = files
            if key == 'Lek-return':
                assert files == first_sketch, 'The returning guest lost the exact hand-drawn path.'
            if i == 0:
                # A second phone still holding revision zero cannot apply another
                # place update based on that old bed, even with a valid route.
                stale = viewer.request.put(url + API, headers={'Origin': url}, data=proposed)
                assert stale.status == 409
                forged = copy.deepcopy(proposed)
                forged['revision'] = rev
                forged['motion']['place'] = 1
                rejected = viewer.request.put(url + API, headers={'Origin': url}, data=forged)
                assert rejected.status == 400, rejected.text()
            print(key, results[key], flush=True)
        count = len(actions)
        assert len(table.calls) == 1
        wait_table(phones[0], url, revision=count, queued=count)
        # Stop while the first file owns the simulated table. Restart with the
        # same database and the same token. No successor may pass a failed setup.
    with served(gallery, database, table) as url, browser.new_context(**MOBILE) as ctx:
        page = ctx.new_page()
        open_room(page, url)
        wait_table(page, url, revision=count, state='drawing')
        table.outcome = 'failed'
        wait_table(page, url, state='blocked')
        assert len(table.calls) == 1
        assert table.last_file == queue[0]
        table.outcome = 'complete'
        for count_dispatched, movement in enumerate(queue[1:], start=2):
            assert table.dispatched(count_dispatched) == movement
            table.outcome = 'complete'
        wait_table(page, url, ready=True, state='idle', queued=0, revision=count)
        assert len(table.calls) == len(queue)
    assert not errors, errors
    results['queue'] = {
        'uploaded_files': len(queue),
        'guest_drawings': count,
        'failed_predecessor_blocked': True,
        'restart_without_replay': True,
    }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report = exercise(browser, args.gallery, Path(tmp), args.evidence)
            report['previous'] = frozen(browser, args.gallery, args.previous, Path(tmp))
    (args.evidence / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Two phones, occupied places, retained sketch, full-ring swap and queued restart passed.')


if __name__ == '__main__':
    main()
