#!/usr/bin/env python3
"""Replace occupied guest places with a portrait and a finger-drawn sailboat, then replay their signed movements.

Use --ordinary with the previous fitted gallery to capture its baseline. Both the garden room and
its simulated controller stay on loopback. No source image is used on the second phone.
"""

import argparse
import base64
from contextlib import closing
import copy
import hashlib
import io
import json
import math
import re
from pathlib import Path
import sqlite3
import tempfile
import zlib

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_attached_garden import Table, served, wait_table
from test_garden_room import API, caption, choose, drawing_files, open_room, suggest
from test_guest_place import contour, contour_samples, unpack
from test_guest_scene_request import regions
from test_named_guest_portraits import prepare, request_face
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_lettering import seat_view
from test_ring_object_photo import PhoneTraffic
from test_ring_photo import frame
from test_ring_sketch_crossings import finger_sketch


# Four finger lifts: a hull, mast, sail and pennant. The mast pierces the deck
# between its two vertices, as it does in the drawing made in the guest sketch pad.
SAILBOAT = [
    [(-.78, -.41), (.76, -.381), (.55, -.604), (.445, -.664), (-.404, -.67),
     (-.556, -.627), (-.704, -.54), (-.78, -.41)],
    [(-.125076, -.397666), (-.091, .795)],
    [(-.096086, .617), (.048, .568), (.215, .445), (.631, .04), (.39, .023), (-.112771, .033)],
    [(-.091, .795), (.135, .743), (.185, .709), (-.094657, .667)],
]


def source_coverage(route, design, radius_mm, cut, visit_ends):
    """Find consecutive signed engraving coordinates, ignoring rake strokes that merely cross a line."""
    unique = {}
    for a, b in zip(design, design[1:]):
        # A long straight finger stroke is engraved in <= .01 radius increments by the guest player.
        count = max(1, math.ceil(np.linalg.norm(b - a) / .01))
        points = np.linspace(a, b, count + 1)
        for start, end in zip(points, points[1:]):
            if np.linalg.norm(end - start) > 1e-7:
                key = tuple(sorted((tuple(start.round(7)), tuple(end.round(7)))))
                unique.setdefault(key, (start, end))
    endpoints = np.asarray(list(unique.values()))
    starts, ends = endpoints[:, 0], endpoints[:, 1]
    xy = route[:, 1, None] * np.column_stack((np.cos(route[:, 0]), np.sin(route[:, 0])))
    aa, bb = xy[:-1], xy[1:]
    tolerance = 2.5e-5  # signed file precision, including angle rounding
    tree = cKDTree((aa + bb) / 2)
    candidates = tree.query_ball_point((starts + ends) / 2, r=tolerance)
    traveled = check.travel(route) * radius_mm / 1000
    arrivals = []
    for start, end, indices in zip(starts, ends, candidates):
        ix = np.asarray(indices, dtype=int)
        forward = (np.linalg.norm(aa[ix]-start, axis=1) < tolerance) & (np.linalg.norm(bb[ix]-end, axis=1) < tolerance)
        reverse = (np.linalg.norm(bb[ix]-start, axis=1) < tolerance) & (np.linalg.norm(aa[ix]-end, axis=1) < tolerance)
        matches = ix[forward | reverse]
        arrivals.append(traveled[matches[0]+1] if len(matches) else np.inf)
    arrivals = np.asarray(arrivals)
    lengths = np.linalg.norm(ends - starts, axis=1)
    def percent(distance):
        return round(100 * float(lengths[arrivals <= distance].sum() / lengths.sum()), 2)
    assert percent(traveled[-1]) > 99.8, 'The signed file is missing parts of the final drawing.'
    return {
        'matched_segments': int(np.isfinite(arrivals).sum()), 'source_segments': len(lengths),
        'first_subject_m': round(float(arrivals.min()), 3), 'route_m': round(float(traveled[-1]), 3),
        'progress_m': round(float(traveled[cut]), 3), 'percent_at_progress': percent(traveled[cut]),
        'percent_at_half': percent(traveled[-1] / 2), 'percent_at_finish': percent(traveled[-1]),
        'visits': [{'travel_m': round(float(traveled[i]),3),
                    'travel_percent': round(float(100*traveled[i]/traveled[-1]),2),
                    'drawn_percent': percent(traveled[i])} for i in visit_ends],
    }


def previous_relief(page, before, state, route, cut, slot, live):
    geom = live['planner']['geometry']
    groove = live['groove']
    original = contour_samples(contour(before, slot, geom), groove / 12)
    incoming = contour_samples(contour(state, slot, geom), groove / 12)
    sites = original[cKDTree(incoming).query(original)[0] > 1.25 * groove]
    side = live['size']
    pix = np.rint((sites * [1,-1] + 1) * (side-1)/2).astype(int)
    indices = np.unique(pix[:, 1] * side + pix[:, 0]).tolist()
    result = page.evaluate('''([raw, erase, route, cut, indices]) => {
        const l = JSON.parse(document.querySelector('#scene').textContent).live;
        const sim = new RingSand(l.size, l.groove, l.profile);
        const old = Float32Array.from(atob(raw), c=>c.charCodeAt(0)/170-1), flat=old.slice();
        sim.carve(flat, erase);
        const sites = indices.filter(i=>Math.abs(old[i]-flat[i]) >= .15);
        const difference = () => sites.reduce((n,i)=>n+Math.abs(old[i]-flat[i]),0);
        const initial = difference(), residual=[];
        for (const part of [route.slice(0,cut+1),route.slice(cut)]) {
            sim.carve(old,part); sim.carve(flat,part); residual.push(100*difference()/initial);
        }
        return {sites:sites.length, progress_pct:residual[0], final_pct:residual[1]};
    }''', [before['bed'], unpack(live['planner']['erase']).tolist(), route.tolist(), cut, indices])
    assert result['sites'] > 24 and result['final_pct'] < 2.5, result
    return result


def protected_sand(before, state, slot, live, frames):
    n = live['size']
    yy, xx = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
    r = np.hypot(xx, yy)
    geom = live['planner']['geometry']
    lo, hi = geom['bounds']
    groove = live['groove']
    masks = {'center': r < lo-2*groove, 'border': (r > hi+2*groove) & (r < .99) & ((yy < 0) | (abs(xx) > 2*groove))}
    for other in set(range(3)) - {slot}:
        assert before['ids'][other] == state['ids'][other]
        angle = geom['angles'][other]
        cx, cy = geom['center'] * np.array([np.cos(angle), np.sin(angle)])
        masks[('Thomas', 'Alex', 'Lek')[other]] = np.hypot(xx-cx, -yy-cy) < geom['scale'] * .93
    def bed(state):
        return np.frombuffer(base64.b64decode(state['bed']), np.uint8).reshape(n, n)
    baseline, final = bed(before), bed(state)
    for name, mask in masks.items():
        assert np.array_equal(baseline[mask], final[mask]), name
        assert all(np.array_equal(frames[0][mask], img[mask]) for img in frames[1:]), name
    return {name: int(mask.sum()) for name, mask in masks.items()}


def change_row(files, index):
    """Alter a single signed location by 0.42 mm on this fitted table, including both copies at a file seam."""
    offset = 0
    found = False
    for file in files:
        rows = file['text'].splitlines()
        local = index - offset
        if 0 <= local < len(rows):
            theta, radius = rows[local].split()
            rows[local] = f'{theta} {float(radius) + .001:.5f}'
            file['text'] = '\n'.join(rows) + '\n'
            found = True
        offset += len(rows) - 1
    assert found, index


def crossing_rows(tile, detour):
    """Unpack the marker in base clearing order, locating each visit in the signed file."""
    fields = {'clearSegment', 'artSegment', 'end'}
    visits = [detour]
    if 'second' in detour:
        assert set(detour) == fields | {'second'} and set(detour['second']) == fields
        assert detour['second']['clearSegment'] > detour['clearSegment']
        visits.append(detour['second'])
    else:
        assert set(detour) == fields

    offset = len(unpack(tile['approach']))
    for visit in visits:
        start = offset + visit['clearSegment']
        segment, end = visit['artSegment'], visit['end']
        count = end-segment if end > segment else segment-end+1
        assert count >= 2
        yield start, count
        offset += 2*count + 1


def rejected_edits(page, url, body, live):
    """Exercise the verifier using copies of the exact phone PUT while the original is held."""
    api = url + API
    original = page.request.get(api).json()
    assert body['revision'] == original['revision']
    queue = page.request.get(url + '/api/playback').json()
    stored = page.request.get(api + '/drawings/middle').json()
    motion = body['motion']
    tile = live['planner']['places'][motion['place']]
    detour = motion['customReveal']
    def reject(variant, label):
        response = page.request.put(api, headers={'Origin': url}, data=variant)
        assert response.status == 400, (label, response.status, response.text())

    bad = copy.deepcopy(body)
    del bad['motion']['customReveal']
    reject(bad, 'unmarked detour')
    for number, (start, count) in enumerate(crossing_rows(tile, detour)):
        if number == 1:
            bad = copy.deepcopy(body)
            del bad['motion']['customReveal']['second']
            reject(bad, 'unmarked second visit')
            bad = copy.deepcopy(body)
            bad['motion']['customReveal']['second']['clearSegment'] = detour['clearSegment']
            reject(bad, 'second visit on the first clearing row')
        for field in ('clearSegment', 'artSegment', 'end'):
            for missing in (True, False):
                bad = copy.deepcopy(body)
                branch = bad['motion']['customReveal']
                if number == 1:
                    branch = branch['second']
                if missing:
                    del branch[field]
                else:
                    branch[field] += 1
                reject(bad, f'visit {number+1}, {field}, missing={missing}')

        point = count//2
        # In one copy both legs agree but the selected line differs. In the
        # other copy the early engraving is correct but the return is not.
        bad = copy.deepcopy(body)
        change_row(bad['motion']['files'], start + point)
        change_row(bad['motion']['files'], start + 2*count - point)
        reject(bad, f'changed early groove on visit {number+1} with a matching retrace')
        bad = copy.deepcopy(body)
        change_row(bad['motion']['files'], start + 2*count - point)
        reject(bad, f'changed return on visit {number+1}')
    bad = copy.deepcopy(body)
    key = bad['state']['ids'][motion['place']]
    bad['state']['custom'][key] = [[-x,y] for x,y in bad['state']['custom'][key]]
    reject(bad, 'different final drawing')
    assert page.request.get(api).json() == original
    assert page.request.get(api + '/drawings/middle').json() == stored
    after = page.request.get(url + '/api/playback').json()
    assert (after['revision'], after['queued']) == (queue['revision'], queue['queued'])


def checked_save(page, url, live):
    api = url + API
    errors = []
    def check_pending(route):
        if route.request.method == 'PUT':
            body = route.request.post_data_json
            if 'customReveal' in body['motion']:
                try:
                    rejected_edits(page, url, body, live)
                except Exception as error:
                    errors.append(error)
                    route.fulfill(status=409, content_type='application/json', body='{}')
                    return
        route.fallback()
    page.route(api, check_pending)
    try:
        return save(page, api)
    finally:
        page.unroute(api, check_pending)
        if errors:
            raise errors[0]


def verify_preview(page, url, before, slot, live, folder, ordinary):
    folder.mkdir(parents=True, exist_ok=True)
    api = url + API
    fixed = [page.request.get(api+'/drawings/'+z).json() for z in ('center','outer')]
    middle_label = page.locator('#middleStageLabel').inner_text()
    files = drawing_files(page, '#downloads')
    choose(page, 'stage', 'original')
    original = frame(page)
    choose(page, 'stage', 'cleared')
    progress = frame(page)
    progress_caption = page.locator('.caption').inner_text()
    choose(page, 'stage', 'redrawn')
    final = frame(page)
    payload, revision = checked_save(page, url, live)
    state = payload['state']
    move = payload['motion']
    assert move['place'] == slot and move['zone'] == 'middle' and not move.get('fill')
    assert files == [(file['name'], file['text'].encode()) for file in move['files']]
    assert [page.request.get(api+'/drawings/'+z).json() for z in ('center','outer')] == fixed
    assert all(before[k] == state[k] for k in ('center', 'portrait', 'outer', 'borderGuest'))
    early = 'customReveal' in move
    if early:
        assert middle_label == 'In progress' and not ordinary
    else:
        assert 'cleared' in middle_label.lower(), middle_label
    catalog = live['planner']
    route = from_files(files, unpack(catalog['transit'])[0])
    tile = catalog['places'][slot]
    visit_ends = [start+2*count for start,count in crossing_rows(tile,move['customReveal'])] if early else []
    cut = visit_ends[-1] if early else len(unpack(tile['approach'])) + len(unpack(tile['clear'])) - 2
    assert 0 < cut < len(route)-1
    rebuilt_progress = replay(page, before['bed'], route[:cut+1])
    rebuilt_final = replay(page, before['bed'], route)
    for actual, rebuilt in [(progress, rebuilt_progress), (final, rebuilt_final)]:
        delta = np.abs(actual.astype(np.int16) - rebuilt.astype(np.int16))
        assert delta.mean() < 1.1 and np.percentile(delta,99) < 6, ('phone vs signed movement', delta.mean())
    distances = check.travel(route)
    half = np.argmin(abs(distances-distances[-1]/2))
    halfway = replay(page, before['bed'], route[:half+1])
    geom = catalog['geometry']
    metrics = source_coverage(route, contour(state, slot, geom), live['radiusMM'], cut, visit_ends)
    if early:
        shown = re.search(r'\bAt (\d+)% of the ball[’\']s travel', progress_caption)
        assert shown, progress_caption
        # Calculate travel from each actual signed row; a row count would give a different percent.
        measured = math.floor(100 * distances[cut] / distances[-1] + .5)
        assert int(shown[1]) == measured, (progress_caption, measured)
        metrics['caption_percent_travel'] = measured
        if len(visit_ends) == 2:
            assert metrics['visits'][1]['drawn_percent'] > metrics['visits'][0]['drawn_percent'], metrics['visits']
            first_visit = replay(page, before['bed'], route[:visit_ends[0]+1])
            seat_view(first_visit, geom, slot).save(folder/'first-visit-chair.png')
        assert metrics['percent_at_progress'] > 0 and metrics['first_subject_m'] < metrics['progress_m']
    else:
        assert metrics['percent_at_progress'] == 0
    crossings = int(early) + int('second' in move.get('customReveal', {}))
    metrics.update(crossings=crossings, early=early, previous=before['ids'][slot], source=state['ids'][slot], stage=middle_label,
                   sha256=[hashlib.sha256(b).hexdigest() for _,b in files],
                   protected=protected_sand(before,state,slot,live,(original,progress,halfway,final)),
                   old_relief=previous_relief(page,before,state,route,cut,slot,live))
    for label, img in [('before',original), ('progress',rebuilt_progress), ('half',halfway), ('finish',rebuilt_final)]:
        seat_view(img, geom, slot).save(folder/(label+'-chair.png'))
    Image.fromarray(rebuilt_final).save(folder/'whole-table.png')
    for name, data in files:
        (folder/name).write_bytes(data)
    (folder/'report.json').write_text(json.dumps(metrics,indent=2))
    print(('Thomas', 'Alex', 'Lek')[slot], metrics, flush=True)
    return state, files, revision, crossings


def combined_request(page, api, live, singles, folder):
    """Check every offered moment against the individual files that actually drew both guests."""
    folder.mkdir(parents=True, exist_ok=True)
    suggest(page,'a faceted phage for Thomas, an open book for Alex and a guitar for Lek')
    seed, previous_revision=save(page,api)
    before=seed['state']
    original=frame(page)
    suggest(page,'Lek’s portrait for Alex and the saved Bay sailboat for Lek')
    signed=drawing_files(page,'#downloads')
    final_image=frame(page)
    choose(page,'stage','cleared')
    select=page.get_by_label('Show a moment in the drawing')
    expect(select.locator('option')).to_have_count(4)
    expect(select).to_have_value('1')  # the first finished drawing
    observations=[]
    for i in (0,1,2,3):
        select.select_option(str(i))
        label=select.locator('option:checked').inner_text()
        observations.append((label,page.locator('.caption').inner_text(),frame(page)))
        expect(page.locator('#keep')).to_be_hidden()
        if i==0:
            page.locator('#guestZoom').click()
            expect(page.locator('#guestZoom')).to_have_text('Show whole table')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=folder/'phone.png')
        if i==2:
            assert 'rotate(' in page.locator('#sand').evaluate('el=>el.style.transform')
            page.locator('#guestZoom').click()
    choose(page,'stage','redrawn')
    expect(select).to_be_hidden()
    assert np.array_equal(frame(page),final_image) and signed==drawing_files(page,'#downloads')
    assert page.request.get(api).json()['revision']==previous_revision
    payload,revision=save(page,api)
    assert revision==previous_revision+1
    state,motion=payload['state'],payload['motion']
    assert state['ids'][0]==before['ids'][0] and motion['zone']=='middle'
    assert {part['place'] for part in motion['parts']}=={1,2}
    assert [(file['name'],file['text'].encode()) for file in motion['files']]==signed
    catalog=live['planner']
    protected,places=regions(len(original),dict(geometry=catalog['geometry'],groove=live['groove']))
    protected |= places[0]
    arrays=[np.loadtxt(io.BytesIO(raw)) for _,raw in signed]
    dock=unpack(catalog['transit'])[0]
    distances=check.travel(check.joined(arrays,dock,dock,'two personal drawings'))
    start=0
    report=[]
    for index,part in enumerate(motion['parts']):
        place=part['place']
        name=('Thomas','Alex','Lek')[place]
        end=start+part['count']
        assert [raw for _,raw in signed[start:end]]==[raw for _,raw in singles[place]]
        tile=catalog['places'][place]
        # Locate the end of the actual out-and-back detour. The last point of
        # the part is the return to the dock after finishing the engraving.
        visits=list(crossing_rows(tile,part['customReveal']))
        crossing,length=visits[-1]
        drawing_finished = sum(len(a)-1 for a in arrays[start:end])
        for forming, stop in [(True, crossing + 2*length), (False, drawing_finished)]:
            label,caption_text,shown=observations[len(report)]
            assert label==name+('’s drawing takes shape' if forming else '’s drawing is finished')
            cut_index = sum(len(a)-1 for a in arrays[:start]) + stop
            percentage = math.floor(100 * distances[cut_index] / distances[-1] + .5)
            assert f'At {percentage}% of the ball’s travel' in caption_text
            prefix=list(arrays[:start])
            for array in arrays[start:end]:
                prefix.append(array[:stop+1])
                stop-=len(array)-1
                if stop<=0: break
            rebuilt=replay(page,before['bed'],*prefix)
            error=np.abs(shown.astype(float)-rebuilt)
            assert error.mean()<.15 and np.percentile(error,99)<2
            assert np.array_equal(shown[protected],original[protected])
            if index==0:
                untouched = places[motion['parts'][1]['place']]
                assert np.array_equal(shown[untouched], original[untouched])
            if not forming:
                assert np.array_equal(shown[places[place]],final_image[places[place]])
            seat_view(shown,catalog['geometry'],place).save(folder/f'{len(report)}-chair.png')
            meters = distances[cut_index] * live['radiusMM'] / 1000
            report.append(dict(moment=label, travel_percent=percentage, travel_m=round(float(meters), 2)))
        start=end
    assert start==len(signed) and np.array_equal(observations[-1][2],final_image)
    (folder/'moments.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Combined guest request:',report,flush=True)
    return state,signed,revision


def exercise(browser, gallery, db, photo, center, output, ordinary, together):
    table = Table(db)
    with served(gallery, db, table, prepared=True) as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        traffic = PhoneTraffic(url)
        for context in (a,b):
            context.route('http**://**/*', traffic.check)
        p, q = a.new_page(), b.new_page()
        errors = []
        for page in (p,q):
            page.on('pageerror', lambda error: errors.append(str(error)))
        open_room(p, url)
        api = url+API
        prepare(p, api, traffic.photo('background.jpg', center.read_bytes(), 'image/jpeg'))
        live = p.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        before = p.request.get(api).json()['state']
        source = traffic.photo(photo.name, photo.read_bytes(), 'image/jpeg')
        expected = request_face(p, 'a portrait of Lek for Thomas', 'Lek', 0, source)
        first, first_files, first_revision, first_visits = verify_preview(p,url,before,0,live,output/'Thomas',ordinary)
        key = first['ids'][0]
        np.testing.assert_allclose(first['custom'][key],expected,atol=1e-8,rtol=0)
        suggest(p, 'a pumpkin for Thomas')
        save(p, api)
        open_room(q, url)
        before = q.request.get(api).json()['state']
        assert key not in before['ids']
        suggest(q, 'Lek’s portrait for Alex')
        caption(q, 'Alex · Portrait of Lek')
        second, second_files, second_revision, second_visits = verify_preview(q,url,before,1,live,output/'Alex',ordinary)
        assert second['ids'][1] == key and second['custom'][key] == first['custom'][key]
        assert q.evaluate("typeof GuestPhoto === 'undefined' && document.querySelector('#portraitFile').files.length === 0")
        assert ordinary or first_visits or second_visits, 'Both occupied guest portraits fell back to a complete clear.'
        before = q.request.get(api).json()['state']
        assert before['ids'][2] == 'guitar_silhouette'
        finger_sketch(q, 'Bay sailboat', SAILBOAT)
        last, last_files, revision, sail_visits = verify_preview(q,url,before,2,live,output/'sailboat',ordinary)
        assert last['ids'][1] == key and last['custom'][key] == first['custom'][key]
        assert ordinary or max(first_visits, second_visits, sail_visits) == 2, 'No two-crossing phone case.'
        if together:
            last,last_files,revision=combined_request(q,api,live,{1:second_files,2:last_files},output/'together')
            p.goto('about:blank')
            open_room(p,url)
            assert drawing_files(p,'#roomFiles')==last_files
        assert not errors and not traffic.violations and traffic.writes == (11 if together else 9), (errors,traffic.violations,traffic.writes)
    with served(gallery,db,table) as url, browser.new_page(**MOBILE) as returning:
        open_room(returning,url)
        assert returning.request.get(url+API).json()['state'] == last
        assert drawing_files(returning,'#roomFiles') == last_files
        with closing(sqlite3.connect(db)) as conn:
            records = [(rev,name,zlib.decompress(raw)) for rev,name,raw in conn.execute(
                'SELECT revision,name,track FROM playback_part ORDER BY revision,part')]
        for rev, files in ((first_revision, first_files), (second_revision, second_files), (revision, last_files)):
            assert [(name, raw) for stored, name, raw in records if stored == rev] == files
        parts = [(name, raw) for _, name, raw in records]
        for i,(name,raw) in enumerate(parts,1):
            assert table.dispatched(i) == {'name':name,'text':raw.decode('ascii')}
            table.outcome = 'complete'
        wait_table(returning,url,state='idle',ready=True,queued=0,revision=revision)
        assert len(table.calls) == len(parts)
        print(f'{len(parts)} signed files played once and in order across a room restart.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('photo', type=Path, help='Two-person JPEG with Lek on the right.')
    parser.add_argument('--center-photo', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--ordinary', action='store_true', help='Verify an earlier edition without early custom drawing.')
    parser.add_argument('--together', action='store_true', help='Also request both saved guest drawings in one change.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args.gallery,Path(tmp)/'room.db',args.photo,args.center_photo or args.photo,
                     args.evidence or Path(tmp),args.ordinary,args.together)
