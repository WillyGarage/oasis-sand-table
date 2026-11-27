#!/usr/bin/env python3
"""Compare guest head-and-shoulders and close-up drawings, including recall from a previous room.

Use a seated three-zone gallery, Bill and Lek's two-person JPEG, and a central portrait.
--previous accepts the gallery that first saved the original drawing. All networking stays on loopback.
"""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_place import detour_indices, unpack
from test_named_guest_portraits import keep_and_check, prepare, request_face, sampled_error
from test_ring_faces import ready
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_object_photo import PhoneTraffic, expand


@contextmanager
def phone(browser, url, traffic):
    with browser.new_context(**MOBILE, service_workers='block') as context:
        context.route('http**://**/*', traffic.check)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        open_room(page, url)
        yield page
        assert not errors and not traffic.violations, (errors, traffic.violations)


def live_scene(page):
    return page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")


def save_original(browser, previous, db, photo, center, output):
    with room(previous, db) as url:
        traffic = PhoneTraffic(url)
        source = traffic.photo(photo.name, photo.read_bytes(), 'image/jpeg')
        with phone(browser, url, traffic) as host:
            prepare(host, url + API, traffic.photo('background.jpg', center.read_bytes(), 'image/jpeg'))
            expected = request_face(host, 'a portrait of Lek for Thomas', 'Lek', 0, source)
            files = drawing_files(host, '#downloads')
            key, path, _ = keep_and_check(host, url, 'Lek', 0, live_scene(host), output / 'original')
            np.testing.assert_allclose(path, expected, atol=1e-8, rtol=0)
            suggest(host, 'a pumpkin for Thomas')
            save(host, url + API)
            assert key not in host.request.get(url + API).json()['state']['ids']
            assert traffic.writes == 7
            return key, path, files


def selected_face(page, person):
    boxes = page.locator('#faceBoxes button')
    expect(boxes).to_have_count(2, timeout=20000)
    bounds = [box.bounding_box() for box in boxes.all()]
    order = sorted(range(2), key=lambda i: bounds[i]['x'] + bounds[i]['width'] / 2)
    index = order[1 if person == 'Lek' else 0]
    boxes.nth(index).click()
    ready(page)
    expect(boxes.nth(index)).to_have_attribute('aria-pressed', 'true')
    return index


def source_head(page, index):
    return page.evaluate('''async index => {
        const live = JSON.parse(document.querySelector('#scene').textContent).live;
        const file = document.querySelector('#portraitFile').files[0];
        const art = await GuestPhoto.fromFile(file, {
            face: index, portraitFraming: 'head', portraitDiameterGrooves: 2*live.planner.geometry.scale/live.groove
        });
        return art.points.slice(1,-1);
    }''', index)


def direct(page, url, source, original, output):
    key, path, files = original
    catalog = live_scene(page)['planner']
    seat = catalog['places'][0]

    def ordinary(files):
        # A fitted table may engrave part of this saved face during the clearing.
        # The old room's entire underlying route, including its final drawing, still matches.
        moves = from_files(files, unpack(catalog['transit'])[0])
        visits = detour_indices(moves, unpack(seat['clear']), len(unpack(seat['approach']))-1)
        for start, stop in reversed(visits):
            moves = np.concatenate((moves[:start], moves[stop:]))
        return moves

    expected_motion = ordinary(files)
    suggest(page, 'Lek’s portrait for Thomas')
    caption(page, 'Thomas · Portrait of Lek')
    np.testing.assert_array_equal(ordinary(drawing_files(page, '#downloads')), expected_motion)
    assert page.request.get(url + API).json()['state']['custom'][key] == path
    page.goto('about:blank')
    open_room(page, url)
    expand(page, '#centerPhoto')
    page.locator('#portraitPlace').select_option('0')
    frame_picker = page.locator('#guestPortraitFrame')
    expect(frame_picker).to_have_value('bust')
    page.locator('#portraitFile').set_input_files(source)
    page.locator('#portraitName').fill('Lek')
    page.locator('#portraitSubmit').click()
    expect(page.locator('#portraitStatus')).to_contain_text('Tap Lek', timeout=20000)
    index = selected_face(page, 'Lek')
    np.testing.assert_array_equal(ordinary(drawing_files(page, '#downloads')), expected_motion)
    frame_picker.select_option('head')
    ready(page)
    expect(page.locator('#portraitName')).to_have_value('Lek')
    expect(page.locator('#portraitPlace')).to_have_value('0')
    expect(page.locator('#faceBoxes button').nth(index)).to_have_attribute('aria-pressed', 'true')
    close_files = drawing_files(page, '#downloads')
    assert close_files != files
    expected = source_head(page, index)
    kept = keep_and_check(page, url, 'Lek', 0, live_scene(page), output / 'close')
    assert kept[0] != key and kept[1] != path
    np.testing.assert_allclose(kept[1], expected, rtol=0, atol=1e-8)
    suggest(page, 'a pumpkin for Thomas')
    save(page, url + API)
    assert kept[0] not in page.request.get(url + API).json()['state']['ids']
    return kept


def recall(page, url, original_key, close, output):
    key, path, mesh = close
    assert page.locator('#portraitFile').evaluate('e => e.files.length') == 0
    page.locator('#idea').fill('Lek’s portrait for Alex')
    page.get_by_role('button', name='Preview suggestion').click()
    expect(page.locator('#error')).to_contain_text('2 drawings')
    expect(page.locator('#keep')).to_be_hidden()
    picker = page.get_by_role('combobox', name='Saved guest drawings')
    assert {original_key, key} <= set(picker.locator('option').evaluate_all('os => os.map(o=>o.value)'))
    picker.select_option(key)
    caption(page, 'Alex · Portrait of Lek')
    recalled_key, recalled_path, recalled_mesh = keep_and_check(page, url, 'Lek', 1, live_scene(page), output / 'recalled')
    assert (recalled_key, recalled_path) == (key, path)
    assert page.locator('#portraitFile').evaluate('e => e.files.length') == 0
    assert page.evaluate('typeof GuestPhoto') == 'undefined'
    error = float(sampled_error(mesh, recalled_mesh))
    assert error < .15, error
    return error


def center_to_place(page, url, source, output):
    choose(page, 'zone', 'center')
    expand(page, '#centerPhoto')
    page.locator('#portraitFile').set_input_files(source)
    page.locator('#portraitSubmit').click()
    ready(page)
    index = selected_face(page, 'Bill')
    center_files = drawing_files(page, '#downloads')
    picker = page.locator('#guestPortraitFrame')
    expect(picker).to_have_value('bust')
    page.locator('#portraitName').fill('Bill')
    page.locator('#portraitPlace').select_option('2')
    picker.select_option('head')
    assert drawing_files(page, '#downloads') == center_files
    expected = source_head(page, index)
    page.locator('#previewPlacePortrait').click()
    caption(page, 'Lek · Portrait of Bill')
    _, path, _ = keep_and_check(page, url, 'Bill', 2, live_scene(page), output / 'from-center')
    np.testing.assert_allclose(path, expected, rtol=0, atol=1e-8)
    return len(path)


def exercise(browser, gallery, previous, db, photo, center, output):
    original = save_original(browser, previous, db, photo, center, output)
    with room(gallery, db) as url:
        traffic = PhoneTraffic(url)
        source = traffic.photo(photo.name, photo.read_bytes(), 'image/jpeg')
        with phone(browser, url, traffic) as host:
            close = direct(host, url, source, original, output)
            with phone(browser, url, traffic) as guest:
                error = recall(guest, url, original[0], close, output)
            host.goto('about:blank')
            open_room(host, url)
            bill_points = center_to_place(host, url, source, output)
            assert traffic.writes == 4, traffic.writes
        report = dict(original_points=len(original[1]), close_points=len(close[1]),
                      recall_difference_mm=round(error, 4), bill_close_points=bill_points)
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('photo', type=Path, help='JPEG with Bill on the left and Lek on the right.')
    parser.add_argument('--center-photo', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, args.gallery, args.previous or args.gallery, Path(tmp) / 'room.db',
                     args.photo, args.center_photo or args.photo, args.evidence or Path(tmp))
