#!/usr/bin/env python3
"""Verify the guest book through the self-contained garden's phone controls.

    python3 tools/test_ring_people.py captures/ring-scene/oasis-ring-garden.html
"""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import sync_playwright

import check_ring_scene as check
import ring_scene
from test_ring_photo import frame
from garden_room import unpack_path


def test_people(page, url, folder):
    page.goto(url + '#guests')
    caption = page.locator('.caption')
    book = page.locator('#peopleBox')
    keep = page.locator('#keep')

    def choose(group, value):
        page.locator(f'input[name={group}][value={value}] + span').click()

    def suggest(message):
        if book.evaluate('el=>el.open'):
            book.locator(':scope > summary').click()
        page.locator('#idea').fill(message)
        page.get_by_role('button', name='Preview suggestion').click()
        keep.wait_for()

    def open_book():
        if not book.evaluate('el=>el.open'):
            book.locator(':scope > summary').click()

    def recall(name):
        open_book()
        selector = page.locator('#personPick')
        options = selector.locator('option').evaluate_all('os => os.map(o=>[o.textContent.trim(),o.value])')
        matches = [value for label, value in options if name.lower() in label.lower()]
        assert len(matches) == 1, f'{name} did not appear exactly once in the remembered guest list: {options}'
        selector.select_option(matches[0])
        assert page.locator('#personName').input_value() == name
        return page.locator('#personInterest').input_value()

    def introduce(name, interest, drawing=None):
        open_book()
        picker = page.locator('#personPick')
        fresh = picker.locator('option').evaluate_all(
            "os => os.find(o => o.value === '' || /new guest|add.*guest/i.test(o.textContent))?.value")
        assert fresh is not None, 'The guest book must provide a new guest entry'
        picker.select_option(fresh)
        page.locator('#personName').fill(name)
        page.locator('#personInterest').fill(interest)
        page.locator('#personPlace').select_option('0')
        if drawing:
            menu = page.locator('#personDrawing')
            matches = menu.locator('option').evaluate_all(
                '(os, label)=>os.filter(o=>o.textContent.includes(label)).map(o=>o.value)', drawing)
            assert len(matches) == 1, f'A guest should be able to choose {drawing} for an unfamiliar interest'
            menu.select_option(matches[0])
        page.locator('#personSubmit').click()
        keep.wait_for()

    def downloaded_route():
        details = page.locator('#downloads')
        if not details.evaluate('el => el.open'):
            details.locator('summary').click()
        links = details.locator('a')
        links.first.wait_for()
        parts = []
        for link in links.all():
            with page.expect_download() as operation:
                link.click()
            download = operation.value
            assert download.suggested_filename.endswith('.thr')
            download.save_as(folder / download.suggested_filename)
            parts.append(check.read_path(folder, download.suggested_filename))
        return check.joined(parts, ring_scene.DOCK, ring_scene.DOCK, 'guest drawing')

    # Make a real nondefault drawing. Serialize precisely the fields used by
    # the earlier, pre-guest-book gallery, including its actual saved sand.
    suggest('a pumpkin for Thomas')
    keep.click()
    old = frame(page)
    page.evaluate("""() => {
      const key = 'oasis-ring-garden-v1';
      const s = JSON.parse(localStorage.getItem(key));
      const legacy = {};
      for (const field of ['edition','bed','center','outer','portrait','ids','custom','labels']) legacy[field] = s[field];
      localStorage.setItem(key, JSON.stringify(legacy));
    }""")
    page.reload()
    assert 'Thomas · Pumpkin' in caption.inner_text()
    assert np.abs(frame(page).astype(float) - old).mean() < 1

    before = frame(page)
    size = len(before)
    yy, xx = np.mgrid[-1:1:complex(size), -1:1:complex(size)]
    radius = np.hypot(xx, yy)
    neighbors = ((radius < .32) | ((radius > .81) & (radius < .95))) & (abs(xx) > .06)
    left = (xx < -.29) & (yy > .10) & (radius < .73)
    introduce('Maya Chen', 'plays guitar')
    assert 'Maya Chen · Acoustic guitar' in caption.inner_text()
    candidate = frame(page)
    assert np.array_equal(before[neighbors], candidate[neighbors])
    assert abs(before[left].astype(float) - candidate[left]).mean() > 1
    choose('stage', 'original')
    assert 'Thomas · Pumpkin' in caption.inner_text() and np.array_equal(frame(page), before)
    choose('stage', 'redrawn')
    assert 'Maya Chen · Acoustic guitar' in caption.inner_text()

    # Keeping an independent outer change while the guest addition is only
    # a preview must never apply her name to Thomas's old artwork.
    choose('zone', 'outer')
    choose('stage', 'redrawn')
    keep.click()
    choose('zone', 'middle')
    assert 'Thomas · Pumpkin' in caption.inner_text() and 'Maya Chen' not in caption.inner_text()
    page.reload()
    assert 'Thomas · Pumpkin' in caption.inner_text()

    introduce('Maya Chen', 'plays guitar')
    assert 'Alex · Stack of books' in caption.inner_text() and 'Lek · Thai rooftop' in caption.inner_text()
    # This selection is identical to the original Python-generated guitar
    # composition; compare the real browser downloads point for point.
    native = folder / 'native'
    ring_scene.build(native, 450, 5, 2.5, 4)
    dock = ring_scene.DOCK
    places = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.places?.length || 0")
    full_reference = check.joined((check.read_path(native, f.name) for f in sorted(native.glob('replace-middle-1-*.thr'))),
                             dock, dock, 'native guitar')
    route = downloaded_route()
    if places:
        # Assemble the Python-generated access, erase and engraving independently of the browser.
        catalog = json.loads((native / 'scene.json').read_text())['guest_plan']
        place = catalog['places'][0]
        paths = [unpack_path(place[key]) for key in ('approach', 'clear', 'recut')]
        paths.extend([unpack_path(catalog['excursions'][0]['guitar']), unpack_path(place['exit'])])
        reference = check.joined(paths, dock, dock, 'local native guitar')
        assert check.travel(route)[-1] < check.travel(full_reference)[-1]
    else:
        reference = full_reference
    assert check.same_track(route, reference)
    keep.click()
    page.reload()
    assert 'Maya Chen · Acoustic guitar' in caption.inner_text()
    assert recall('Maya Chen') == 'plays guitar'
    suggest('a rocket for Maya Chen')
    assert 'Maya Chen · Rocket' in caption.inner_text() and 'Alex · Stack of books' in caption.inner_text()
    keep.click()
    page.reload()
    assert 'Maya Chen · Rocket' in caption.inner_text()
    assert recall('Thomas')
    page.locator('#personPlace').select_option('0')
    page.locator('#personSubmit').click()
    keep.wait_for()
    assert 'Thomas · Pumpkin' in caption.inner_text() and 'Maya Chen' not in caption.inner_text()
    keep.click()
    page.reload()
    assert 'Thomas · Pumpkin' in caption.inner_text() and recall('Maya Chen') == 'plays guitar'

    # A different guest can have the same subject. Only the names change,
    # so there should be no redundant middle erase or drawing to download.
    same_sand = frame(page)
    introduce('Robin', 'pumpkins')
    assert 'Robin · Pumpkin' in caption.inner_text() and page.locator('#downloads').is_hidden()
    assert np.array_equal(frame(page), same_sand)
    keep.click()
    assert 'Robin · Pumpkin' in caption.inner_text() and np.array_equal(frame(page), same_sand)
    assert recall('Maya Chen') == 'plays guitar'
    page.locator('#personPlace').select_option('0')
    page.locator('#personSubmit').click()
    assert 'Maya Chen · Rocket' in caption.inner_text()
    keep.click()
    # Moving an active person to a second active place exchanges both guests
    # and their pictures. It must not duplicate a person.
    recall('Maya Chen')
    page.locator('#personPlace').select_option('1')
    page.locator('#personSubmit').click()
    assert caption.inner_text().index('Alex · Stack of books') < caption.inner_text().index('Maya Chen · Rocket')
    keep.click()
    page.reload()
    assert caption.inner_text().count('Maya Chen') == 1
    assert caption.inner_text().index('Alex · Stack of books') < caption.inner_text().index('Maya Chen · Rocket')

    # A remembered sketch must survive when nobody currently displayed uses
    # that private shape. Comparing its exported path checks the exact strokes.
    page.locator('#idea').fill('a qzxwgy for Maya Chen')
    preview = page.get_by_role('button', name='Preview suggestion')
    preview.click()
    pad = page.locator('#sketchPad')
    pad.scroll_into_view_if_needed()
    box = pad.bounding_box()
    x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
    page.mouse.move(x-38, y+5)
    page.mouse.down()
    page.mouse.move(x+4, y-32, steps=7)
    page.mouse.move(x+35, y+18, steps=7)
    page.mouse.up()
    preview.click()
    assert 'Maya Chen · a qzxwgy' in caption.inner_text()
    hand = downloaded_route()
    keep.click()
    recall('Thomas')
    page.locator('#personPlace').select_option('1')
    page.locator('#personSubmit').click()
    keep.click()
    page.reload()
    assert 'Maya Chen' not in caption.inner_text() and 'Thomas · Pumpkin' in caption.inner_text()
    recall('Maya Chen')
    page.locator('#personPlace').select_option('1')
    page.locator('#personSubmit').click()
    assert 'Maya Chen · a qzxwgy' in caption.inner_text()
    assert check.same_track(downloaded_route(), hand)
    keep.click()
    introduce('Jo', 'qzwxy weaving', drawing='Hot pot')
    assert 'Jo · Hot pot' in caption.inner_text()
    keep.click()
    page.reload()
    assert recall('Jo') == 'qzwxy weaving'
    introduce('Ada', 'stargazing and photography')
    assert 'Ada · Telescope on a tripod' in caption.inner_text()
    keep.click()
    assert recall('Ada') == 'stargazing and photography'
    camera = page.locator('#personDrawing option').evaluate_all(
        "os=>os.find(o=>o.textContent==='Camera')?.value")
    assert camera is not None, 'The second interest should offer its own drawing'
    page.locator('#personDrawing').select_option(camera)
    page.locator('#personSubmit').click()
    assert 'Ada · Camera' in caption.inner_text()
    keep.click()
    page.reload()
    assert 'Ada · Camera' in caption.inner_text() and recall('Ada') == 'stargazing and photography'
    # The sample uses the same guest form and never writes until kept.
    page.goto(url + '#example-telescope')
    keep.wait_for()
    assert 'Bill · Telescope on a tripod' in caption.inner_text()
    keep.click()
    suggest('Draw something for Bill')
    assert 'Bill · Ringed planet' in caption.inner_text()
    keep.click()
    suggest('Draw something for Bill')
    assert 'Bill · Comet' in caption.inner_text()
    page.locator('#reset').click()
    page.reload()
    assert 'Thomas · Bacteriophage' in caption.inner_text() and page.locator('#reset').is_hidden()
    assert recall('Ada') == 'stargazing and photography'
    assert page.locator('#personDrawing option:checked').inner_text() == 'Camera'
    assert recall('Maya Chen') == 'plays guitar'
    page.locator('#personSubmit').click()
    assert 'Maya Chen · a qzxwgy' in caption.inner_text()
    # A returning guest can still have the older DNA engraving in their saved drawing.
    recall('Thomas')
    page.locator('#personDrawing').select_option('dna')
    page.locator('#personSubmit').click()
    keep.click()
    suggest('replace DNA with a guitar')
    assert 'Thomas · Acoustic guitar' in caption.inner_text()
    suggest('draw DNA for Alex')
    assert 'Alex · Open double helix' in caption.inner_text()
    keep.click()
    page.locator('#idea').fill('replace DNA with a guitar')
    page.get_by_role('button', name='Preview suggestion').click()
    assert 'Two guests' in page.locator('#error').inner_text() and keep.is_hidden()
    suggest('replace the open double helix with a guitar')
    assert 'Alex · Acoustic guitar' in caption.inner_text() and 'Thomas · Double helix' in caption.inner_text()
    open_subject = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.openSubject")
    if open_subject:
        # A guest with an empty place keeps their interests and can choose a new drawing after reloading.
        assert recall('Ada') == 'stargazing and photography'
        page.locator('#personPlace').select_option('1')
        page.locator('#personDrawing').select_option(open_subject)
        page.locator('#personSubmit').click()
        assert 'Ada · Open place' in caption.inner_text()
        keep.click()
        page.reload()
        assert recall('Ada') == 'stargazing and photography'
        assert page.locator('#personDrawing').input_value() == open_subject
        page.locator('#personDrawing').select_option(camera)
        page.locator('#personSubmit').click()
        assert 'Ada · Camera' in caption.inner_text()
        assert page.locator('#middleStageLabel').inner_text() == 'Halfway'
        assert page.locator('#lastStageLabel').inner_text() == 'Drawn'
        keep.click()
        if book.evaluate('el=>el.open'):
            book.locator(':scope > summary').click()
        page.locator('#openGuestPlaces').click()
        keep.click()
        suggest('a Thai rooftop')
        assert 'Lek · Thai rooftop' in caption.inner_text()
        assert page.locator('#lastStageLabel').inner_text() == 'Drawn'
    print(f'Guest preview, independent ring edit, legacy save, named suggestion, exact recall, '
          f'same-art seat change, active swap, displaced sketch recovery, manual subject and two interests passed. '
          f'The {len(route)}-point guest download matches the native guitar route.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            test_people(page, args.page.resolve().as_uri(), Path(tmp))
            assert not errors, errors
