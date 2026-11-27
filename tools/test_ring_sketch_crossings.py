#!/usr/bin/env python3
"""Draw a kite and a star with touch input and verify the actual signed sand movements.

Run with a fitted three-zone, seat-facing gallery. The shared room stays on loopback.
"""

import argparse
import math
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_guest_place import contour_samples, physical_parts, unpack
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_object_photo import expand


KITE = [
    [(0, .82), (-.52, .32), (0, -.10), (.52, .32), (0, .82)],
    [(0, -.10), (.09, -.74)],
    [(-.21, -.34), (.28, -.59), (.26, -.34), (-.18, -.60), (-.21, -.34)],
]
STAR = [
    [(0, .79), (-.68, -.39), (.68, -.39), (0, .79)],
    [(0, -.79), (.68, .39), (-.68, .39), (0, -.79)],
]
SUBJECTS = [('Ribbon kite', KITE), ('Crossed star', STAR)]


def finger_sketch(page, label, strokes):
    page.locator('#idea').fill(label + ' for Lek')
    expand(page, '#sketch')
    pad = page.locator('#sketchPad')
    pad.evaluate('el => el.scrollIntoView({block:"center"})')
    # Observe exactly what the browser delivered, including its subpixel coordinate rounding.
    pad.evaluate('''el => {
        window.touchStrokes = [];
        if (el.dataset.recordTouch) return;
        el.dataset.recordTouch = 'yes';
        for (const event of ['pointerdown', 'pointermove']) {
            el.addEventListener(event, e => {
                if (e.pointerType !== 'touch' || !e.isTrusted) return;
                const b = el.getBoundingClientRect();
                if (event === 'pointerdown') window.touchStrokes.push([]);
                window.touchStrokes.at(-1).push([
                    2 * (e.clientX-b.left) / b.width - 1,
                    1 - 2 * (e.clientY-b.top) / b.height
                ]);
            }, {capture: true});
        }
    }''')
    box = pad.bounding_box()
    cdp = page.context.new_cdp_session(page)
    finger_paths = []
    for stroke in strokes:
        finger_points = [stroke[0]]
        for start, end in zip(stroke, stroke[1:]):
            count = math.ceil(math.dist(start, end) / .12)
            finger_points.extend(np.linspace(start, end, count + 1)[1:])
        finger_paths.append(finger_points)
        for i, (x, y) in enumerate(finger_points):
            event = 'touchStart' if i == 0 else 'touchMove'
            point = dict(x=box['x'] + (x + 1) * box['width'] / 2, y=box['y'] + (1 - y) * box['height'] / 2)
            cdp.send('Input.dispatchTouchEvent', dict(type=event, touchPoints=[point]))
        cdp.send('Input.dispatchTouchEvent', dict(type='touchEnd', touchPoints=[]))
    cdp.detach()
    actual = page.evaluate('window.touchStrokes')
    assert [len(s) for s in actual] == [len(s) for s in finger_paths]
    for expected, observed in zip(finger_paths, actual):
        np.testing.assert_allclose(observed, expected, rtol=0, atol=.003)
    page.get_by_role('button', name='Preview suggestion').click()
    caption(page, 'Lek · ' + label)
    expect(page.locator('#keep')).to_be_visible()
    return actual


def signed_sketch(files, live, raw_strokes):
    """Compare the guest’s actual movement between first and final contact with their sketch."""
    catalog = live['planner']
    geom = catalog['geometry']
    mm = live['radiusMM']
    tile = catalog['places'][2]
    route = from_files(files, unpack(catalog['transit'])[0])
    draw = physical_parts(route, tile, catalog)[2][len(unpack(tile['recut'])) - 1:]
    assert geom['faceEdge']
    angle = geom['angles'][2]
    radial = np.array([math.cos(angle), math.sin(angle)])
    right = np.array([-radial[1], radial[0]])
    table_lines = []
    for stroke in raw_strokes:
        p = np.asarray(stroke)
        offsets = p[:, 0, None] * right - p[:, 1, None] * radial
        table_lines.append(geom['center'] * radial + geom['scale'] * offsets)

    # The normal hanging line enters and leaves at the outermost tip of the sketch.
    # Restrict the comparison to motion between those visits to count only ink on the page.
    vertices = np.concatenate(table_lines)
    anchor = vertices[np.argmax(np.linalg.norm(vertices, axis=1))]
    xy = draw[:, 1, None] * np.column_stack((np.cos(draw[:, 0]), np.sin(draw[:, 0])))
    anchors = np.flatnonzero(np.linalg.norm(xy - anchor, axis=1) < 4e-5)
    assert len(anchors) >= 2, 'Missing the outer tip of the actual finger sketch.'
    engraving = draw[anchors[0]:anchors[-1] + 1]

    # 0.1 mm samples are much closer together than the physical groove width.
    spacing = .1 / mm
    wanted = np.vstack([contour_samples(stroke, spacing) for stroke in table_lines])
    actual = check.sample_walk(engraving, spacing)
    excess = cKDTree(wanted).query(actual)[0] * mm
    gaps = cKDTree(actual).query(wanted)[0] * mm
    distance = np.linalg.norm(np.diff(actual, axis=0), axis=1) * mm
    groove = live['groove'] * mm
    return {
        'peak_distance_from_ink_mm': round(float(excess.max()), 3),
        'peak_missing_ink_mm': round(float(gaps.max()), 3),
        'travel_beyond_half_groove_mm': round(float(distance[excess[:-1] > groove / 2].sum()), 2),
        'engraving_travel_mm': round(float(distance.sum()), 2),
        'groove_mm': round(groove, 2),
    }


def exercise(browser, gallery):
    with tempfile.TemporaryDirectory() as tmp, room(gallery, Path(tmp) / 'room.db') as url, \
            browser.new_context(**MOBILE) as left, browser.new_context(**MOBILE) as right:
        host, guest = left.new_page(), right.new_page()
        open_room(host, url)
        suggest(host, 'a guitar for Lek')
        save(host, url + API)
        live = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        kept = {}
        for label, strokes in SUBJECTS:
            actual = finger_sketch(host, label, strokes)
            files = drawing_files(host, '#downloads')
            payload, _ = save(host, url + API)
            assert payload['motion']['place'] == 2
            assert files == [(f['name'], f['text'].encode()) for f in payload['motion']['files']]
            metrics = signed_sketch(files, live, actual)
            assert metrics['peak_missing_ink_mm'] < .25, (label, metrics)
            assert metrics['peak_distance_from_ink_mm'] < .25, (label, metrics)
            subject = payload['state']['ids'][2]
            kept[label] = subject, payload['state']['custom'][subject], files

        open_room(guest, url)
        suggest(guest, 'the saved Ribbon kite for Lek')
        caption(guest, 'Lek · Ribbon kite')
        kite, kite_path, kite_files = kept['Ribbon kite']
        assert drawing_files(guest, '#downloads') == kite_files
        recall, _ = save(guest, url + API)
        assert recall['state']['ids'][2] == kite and recall['state']['custom'][kite] == kite_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    args = parser.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, args.gallery)
    print('Touch input, signed kite and star engravings, and cross-phone sketch recall passed.')
