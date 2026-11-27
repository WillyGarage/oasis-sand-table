#!/usr/bin/env python3
"""Check a drawing inspired by two guests, from the phone request through the exported sand path."""
import argparse
import io
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from check_ring_scene import joined, travel
from ring_scene import guest_excursion, pack_path
from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_guest_scene_request import regions
from test_ring_guest_border import MOBILE, replay, save
from test_ring_lettering import seat_view
from test_ring_photo import frame
from test_saved_guest_drawings import ask

POPUP = 'temple_popup_book'
TITLE = 'Thai roof pop-up book'
EXPLICIT = 'a Thai roof rising from an open book for Alex'


def prepare_neighbors(page, gallery, database):
    with room(gallery, database) as url:
        open_room(page, url)
        suggest(page, 'a guitar for Thomas and a Thai rooftop for Lek')
        return save(page, url + API)[0]['state']


def book_stage(walk, geometry, slot):
    """Find the finished page spread just before the first roof support rises."""
    heading = walk[:, 0] - geometry['angles'][slot]
    x = walk[:, 1] * np.sin(heading) / geometry['scale']
    y = (geometry['center'] - walk[:, 1] * np.cos(heading)) / geometry['scale']
    # The first paper tab climbs straight up from inside the right-hand page.
    rise, = np.flatnonzero((x[:-1] > .2) & (x[:-1] < .4) & (abs(np.diff(x)) < .001) &
                           (y[:-1] < 0) & (y[1:] > 0))
    gutter = np.flatnonzero((abs(x[:rise]) < .001) & (y[:rise] > -.4) & (y[:rise] < -.2))[-1]
    edges = (y[:gutter] < 0) & (y[:gutter] > -.6)
    assert x[:gutter][edges].min() < -.75 and x[:gutter][edges].max() > .75
    return gutter + 1


def exercise(browser, gallery, previous, output):
    with tempfile.TemporaryDirectory() as folder, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        database = Path(folder) / 'garden.db'
        original = prepare_neighbors(host, previous or gallery, database)
        assert original['ids'] == ['guitar_silhouette', 'open_place', 'temple_gable']
        with room(gallery, database) as url:
            api = url + API
            for page in (host, guest):
                open_room(page, url)
            assert host.request.get(api).json()['state'] == original
            catalog = host.evaluate("""() => {
                const live=JSON.parse(document.getElementById('scene').textContent).live;
                return {geometry:live.planner.geometry,groove:live.groove,radius:live.radiusMM,
                    paths:live.planner.excursions.map(place=>place.temple_popup_book)};
            }""")
            for slot, packed in enumerate(catalog['paths']):
                expected = guest_excursion(POPUP, slot, catalog['geometry'])
                assert pack_path(expected) == packed
                book_stage(expected, catalog['geometry'], slot)
            before = frame(host)
            suggest(host, EXPLICIT)
            caption(host, 'Alex · ' + TITLE)
            explicit = drawing_files(host, '#downloads')
            for source in ('Combine Alex and Lek’s interests for Alex', "Mix Lek and Alex's interests for Alex"):
                suggest(host, source)
                caption(host, 'Alex · ' + TITLE)
                assert drawing_files(host, '#downloads') == explicit
            paths = [np.loadtxt(io.BytesIO(data)) for _, data in explicit]
            dock = (-np.pi/2, 1)
            walk = joined(paths, dock, dock, 'pop-up book')
            cut = book_stage(walk, catalog['geometry'], 1)
            pages = replay(host, original['bed'], walk[:cut])
            after = frame(host)
            reconstructed = replay(host, original['bed'], *paths)
            assert np.abs(reconstructed.astype(float) - after).mean() < 1.1
            protected, places = regions(len(after), catalog)
            protected |= places[0] | places[2]
            np.testing.assert_array_equal(after[protected], before[protected])
            np.testing.assert_array_equal(pages[protected], before[protected])
            assert np.any(after[places[1]] != before[places[1]])
            assert np.any(pages[places[1]] != before[places[1]]) and np.any(pages[places[1]] != after[places[1]])
            if output:
                output.mkdir(parents=True, exist_ok=True)
                Image.fromarray(after).save(output/'whole-garden.png')
                seat_view(pages, catalog['geometry'], 1).save(output/'book-open.png')
                seat_view(after, catalog['geometry'], 1).save(output/'alex-detail.png')
                host.locator('#chairView').click()
                host.locator('#nextSeat').click()
                expect(host.locator('#seatNumber')).to_have_text('Alex’s chair')
                host.locator('.sand-display').screenshot(path=str(output/'alex-chair.png'))
                for name, data in explicit:
                    (output/name).write_bytes(data)
            first, _ = save(host, api)
            assert first['state']['ids'] == [original['ids'][0], POPUP, original['ids'][2]]
            assert first['motion']['fill'] and first['motion']['place'] == 1
            caption(guest, 'Alex · ' + TITLE)
            assert drawing_files(guest, '#roomFiles') == explicit

            # Changing either source interest should change the result, even
            # though the names and destination in the request are identical.
            guest.locator('#peopleBox').evaluate('el=>el.open=true')
            guest.locator('#personPick').select_option(label='Lek')
            guest.locator('#personInterest').fill('Guitar')
            guest.locator('#personDrawing').select_option(original['ids'][2])
            guest.locator('#personSubmit').click()
            save(guest, api)
            guest.locator('#peopleBox').evaluate('el=>el.open=false')
            suggest(guest, 'Combine Alex and Lek’s interests for Alex')
            replacement, _ = save(guest, api)
            changed = replacement['state']['ids'][1]
            assert changed != POPUP and 'guitar' in changed and 'book' in changed, changed
            assert replacement['state']['ids'][::2] == original['ids'][::2]

            snapshot = guest.request.get(api).json()
            ask(guest, 'Combine Alex and Nobody’s interests for Thomas')
            expect(guest.locator('#error')).not_to_be_empty()
            expect(guest.locator('#keep')).to_be_hidden()
            assert guest.request.get(api).json() == snapshot

            # A simple spatial request still gives two independently placed subjects.
            suggest(guest, 'a rooftop beside an open book for Thomas')
            pair, _ = save(guest, api)
            assert pair['state']['ids'][0].startswith('pair-beside-') and pair['state']['ids'][2] == original['ids'][2]
            meters = travel(walk) * catalog['radius'] / 1000
            print(f'Book visible after {meters[cut-1]:.3f} m. Complete trip: {meters[-1]:.3f} m, '
                  f'{len(walk)} points, {np.count_nonzero(protected):,} protected pixels. '
                  'Both phones received the same drawing; changing the guest interest changed the artwork.')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('gallery', type=Path)
    cli.add_argument('--previous', type=Path, help='Earlier fitted gallery with the same open-place layout')
    cli.add_argument('--evidence', type=Path)
    opts = cli.parse_args()
    with sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, opts.gallery, opts.previous, opts.evidence)
