#!/usr/bin/env python3
"""Choose faces from a two-person photo, then recall those drawings from another phone.

Use a fitted, seat-facing three-zone gallery and a photograph with Lek on the right and
Bill on the left. The source and all traffic stay on loopback. --evidence saves seated views.
"""

import argparse
import json
import math
from pathlib import Path
import re
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_place import contour, contour_samples, evidence, physical_parts, unpack
from test_ring_faces import ready
from test_ring_guest_border import MOBILE, from_files, preview, save
from test_ring_lettering import seat_view
from test_ring_object_photo import PhoneTraffic, capture_stages, expand


def prepare(page, api, center):
    choose(page, 'zone', 'center')
    expand(page, '#centerPhoto')
    page.locator('#portraitFile').set_input_files(center)
    page.locator('#portraitSubmit').click()
    ready(page)
    payload, _ = save(page, api)
    assert payload['state']['portrait']
    choose(page, 'zone', 'outer')
    preview(page, 4, 'Lek', order='progressive')
    save(page, api)
    choose(page, 'zone', 'middle')
    for request in ('a phage for Thomas', 'an open book for Alex', 'a guitar for Lek'):
        suggest(page, request)
        save(page, api)


def request_face(page, words, person, slot, group):
    page.locator('#idea').fill(words)
    page.get_by_role('button', name='Preview suggestion').click()
    page.locator('#suggestionPhoto').click()
    expect(page.locator('#portraitPlace')).to_have_value(str(slot))
    expect(page.locator('#guestPhotoKind')).to_have_value('face')
    expect(page.locator('#portraitName')).to_have_value(person)
    page.locator('#portraitFile').set_input_files(group)
    page.locator('#portraitSubmit').click()
    faces = page.locator('#faceBoxes button')
    expect(faces).to_have_count(2, timeout=20000)
    assert page.locator('#portraitSource').evaluate('e => e.open')
    assert page.locator('#keep').is_hidden() or page.locator('#keep').is_disabled()
    assert page.locator('#downloads').is_hidden()

    # Identify the intended person by their known position in this particular photo;
    # the order in which the detector happens to report the boxes is immaterial.
    boxes = [face.bounding_box() for face in faces.all()]
    order = sorted(range(2), key=lambda i: boxes[i]['x'] + boxes[i]['width'] / 2)
    index = order[1 if person == 'Lek' else 0]
    faces.nth(index).click()
    ready(page)
    expect(faces.nth(index)).to_have_attribute('aria-pressed', 'true')
    recipient = ('Thomas', 'Alex', 'Lek')[slot]
    caption(page, recipient + ' · Portrait of ' + person)
    title = re.escape(' portrait of ' + person + ' for ' + recipient)
    expect(page.locator('#keep')).to_have_text(re.compile(r'^(?:Keep|Queue)' + title + r'$'))
    # Independently convert the selected index. The first preview may have shown the other face.
    return page.evaluate('''async index => {
        const live = JSON.parse(document.querySelector('#scene').textContent).live;
        const file = document.querySelector('#portraitFile').files[0];
        const photo = await GuestPhoto.fromFile(file, {
            face: index, portraitDiameterGrooves: 2 * live.planner.geometry.scale / live.groove
        });
        return photo.points.slice(1,-1);
    }''', index)


def seated_engraving(files, state, live, slot):
    catalog = live['planner']
    geom = catalog['geometry']
    assert geom['faceEdge']
    tile = catalog['places'][slot]
    route = from_files(files, unpack(catalog['transit'])[0])
    draw = physical_parts(route, tile, catalog)[2][len(unpack(tile['recut'])) - 1:]
    source = contour(state, slot, geom)
    anchor = source[np.argmax(np.linalg.norm(source, axis=1))]
    xy = draw[:, 1, None] * np.column_stack((np.cos(draw[:, 0]), np.sin(draw[:, 0])))
    anchors = np.flatnonzero(np.linalg.norm(xy-anchor, axis=1) < 4e-5)
    assert len(anchors) >= 2, 'Signed motion misses its entrance on the selected portrait.'
    # Remove approach, rail and exit. At each chair the viewer’s right follows the rim,
    # and the top of the face points toward the middle of the table.
    mm = live['radiusMM']
    ink = check.sample_walk(draw[anchors[0]:anchors[-1]+1], .1 / mm)
    angle = geom['angles'][slot]
    radial = np.array([math.cos(angle), math.sin(angle)])
    centered = (ink - geom['center'] * radial) * mm
    seated = np.column_stack((centered @ [-radial[1], radial[0]], -centered @ radial))
    path = state['custom'][state['ids'][slot]]
    intended = contour_samples(np.asarray(path) * (geom['scale'] * mm), .1)
    assert sampled_error(intended, seated) < .25, 'The signed portrait changed shape or rotated at the chair.'
    return seated


def sampled_error(a, b):
    return max(cKDTree(a).query(b)[0].max(), cKDTree(b).query(a)[0].max())


def keep_and_check(page, url, person, slot, live, folder):
    api = url + API
    before = page.request.get(api).json()['state']
    fixed = [page.request.get(api + '/drawings/' + zone).json() for zone in ('center', 'outer')]
    files = drawing_files(page, '#downloads')
    frames = capture_stages(page)
    payload, _ = save(page, api)
    state = payload['state']
    key = state['ids'][slot]
    assert state['labels'][key] == 'Portrait of ' + person
    assert payload['motion']['place'] == slot and not payload['motion'].get('fill')
    assert files == [(f['name'], f['text'].encode()) for f in payload['motion']['files']]
    assert [page.request.get(api + '/drawings/' + zone).json() for zone in ('center', 'outer')] == fixed
    assert state['portrait'] == before['portrait'] and state['outer'] == before['outer']
    mesh = seated_engraving(files, state, live, slot)
    report = evidence(page, folder, before, state, frames, files, live['planner'], slot, live)
    chair = seat_view(frames[-1], live['planner']['geometry'], slot)
    chair.save(folder / 'chair.png')
    (folder / 'metrics.json').write_text(json.dumps(report, indent=2))
    return key, state['custom'][key], mesh


def exercise(browser, gallery, photo, center, folder):
    with tempfile.TemporaryDirectory() as tmp, room(gallery, Path(tmp) / 'room.db') as url, \
            browser.new_context(**MOBILE, service_workers='block') as left, \
            browser.new_context(**MOBILE, service_workers='block') as right:
        traffic = PhoneTraffic(url)
        host, guest = left.new_page(), right.new_page()
        errors = []
        for ctx, page in ((left, host), (right, guest)):
            ctx.route('http**://**/*', traffic.check)
            page.on('pageerror', lambda err: errors.append(str(err)))
        source = traffic.photo(photo.name, photo.read_bytes(), 'image/jpeg')
        backdrop = traffic.photo('center.jpg', center.read_bytes(), 'image/jpeg')
        open_room(host, url)
        prepare(host, url + API, backdrop)
        live = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        kept = {}
        for person, slot, recall_slot, words, recall in (
            ('Lek', 0, 1, 'a portrait of Lek for Thomas', 'Lek’s portrait for Alex'),
            ('Bill', 2, 0, 'Bill’s portrait for Lek', 'a portrait of Bill for Thomas'),
        ):
            if kept:
                host.goto('about:blank')
                open_room(host, url)
            expected = request_face(host, words, person, slot, source)
            key, path, source_mesh = keep_and_check(host, url, person, slot, live, folder / (person + '-first'))
            np.testing.assert_allclose(path, expected, rtol=0, atol=1e-8)
            assert key not in kept and all(path != old_path for old_path in kept.values())
            kept[key] = path
            # Prove recall after the drawing has left the sand entirely.
            previous_guest = ('Thomas', 'Alex', 'Lek')[slot]
            suggest(host, 'a pumpkin for ' + previous_guest)
            save(host, url + API)
            assert key not in host.request.get(url + API).json()['state']['ids']
            guest.goto('about:blank')
            open_room(guest, url)
            assert guest.locator('#portraitFile').evaluate('e => e.files.length') == 0
            suggest(guest, recall)
            caption(guest, ('Thomas', 'Alex', 'Lek')[recall_slot] + ' · Portrait of ' + person)
            recall_key, recall_path, recall_mesh = keep_and_check(guest, url, person, recall_slot, live,
                                                                 folder / (person + '-recalled'))
            assert recall_key == key and recall_path == path
            assert guest.locator('#portraitFile').evaluate('e => e.files.length') == 0
            assert guest.evaluate('typeof GuestPhoto') == 'undefined'
            error = float(sampled_error(source_mesh, recall_mesh))
            assert error < .15, (person, error)
            print(f'{person}: kept the original {len(path)} points, {error:.4f} mm maximum sampled '
                  'difference between the two signed chair engravings.', flush=True)
        # Short requests can use a saved name, including as part of a dinner
        # scene that gives two guests different faces. The previews do not save.
        suggest(guest, 'draw Lek for Thomas')
        caption(guest, 'Thomas · Portrait of Lek')
        suggest(guest, 'Lek’s portrait for Thomas and a portrait of Bill for Alex')
        caption(guest, 'Thomas · Portrait of Lek')
        caption(guest, 'Alex · Portrait of Bill')
        assert not errors and not traffic.violations, (errors, traffic.violations)
        assert traffic.writes == 11, traffic.writes
        print('Eleven local saves, no source image or filename sent, and no photo used on the second phone.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('photo', type=Path, help='Two-person JPEG with Bill on the left and Lek on the right.')
    parser.add_argument('--center-photo', type=Path, help='JPEG for the occupied center. Defaults to the same file.')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as evidence_dir, sync_playwright() as pw:
        out = args.evidence or Path(evidence_dir)
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, args.gallery, args.photo, args.center_photo or args.photo, out)
