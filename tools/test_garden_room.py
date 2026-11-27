#!/usr/bin/env python3
"""Exercise two independent phones in the shared garden, using a temporary local database.

    python3 tools/test_garden_room.py captures/ring-scene/oasis-ring-garden.html \
        --photo captures/photo2sand_test/chari.jpg

With no page argument, build a fresh gallery in a temporary directory.
"""
import argparse
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import expect, sync_playwright

from garden_room import make_server
import ring_preview
import ring_scene
from test_ring_photo import frame


API = '/api/garden/garden'
ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def room(page_file, database, **options):
    with make_server(page_file, database, bind='127.0.0.1', port=0, **options) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


def choose(page, group, value):
    page.locator(f'input[name={group}][value={value}] + span').click()


def caption(page, words):
    expect(page.locator('.caption')).to_contain_text(words, timeout=15000)


def suggest(page, words):
    page.locator('#idea').fill(words)
    page.get_by_role('button', name='Preview suggestion').click()
    expect(page.locator('#keep')).to_be_visible()


def open_room(page, url, fragment='guests'):
    with page.expect_response(lambda r: urlsplit(r.url).path == API and r.request.method == 'GET') as load:
        page.goto(url + '/garden#' + fragment)
    assert load.value.status == 200
    expect(page.locator('meta[name=oasis-room]')).to_have_count(1)


def keep(page, status=200):
    with page.expect_response(lambda r: urlsplit(r.url).path == API and r.request.method == 'PUT') as put:
        page.locator('#keep').click()
    response = put.value
    assert response.status == status, f'Unexpected save response {response.status}'
    if status == 200:
        expect(page.locator('#keep')).to_be_hidden()
    return int(response.headers['etag'].strip('"'))


def drawing_files(page, selector):
    details = page.locator(selector)
    if not details.evaluate('el => el.open'):
        details.locator('summary').click()
    links = details.locator('a')
    expect(links.first).to_be_visible()
    files = []
    for link in links.all():
        with page.expect_download() as pending:
            link.click()
        download = pending.value
        data = download.path().read_bytes()
        assert download.suggested_filename.endswith('.thr') and len(data.splitlines()) >= 2
        files.append((download.suggested_filename, data))
    assert sum(len(data.splitlines()) for _, data in files) > 100
    return files


def private_gallery(first, second, page_file):
    url = page_file.resolve().as_uri() + '#guests'
    first.goto(url)
    second.goto(url)
    assert first.locator('meta[name=oasis-room]').count() == 0
    suggest(first, 'a turkey for Thomas')
    first.locator('#keep').click()
    first.reload()
    second.reload()
    caption(first, 'Thomas · Turkey')
    caption(second, 'Thomas · Bacteriophage')


def exercise(browser, page_file, database, photo):
    mobile = dict(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    errors = []
    with room(page_file, database) as url, browser.new_context(**mobile) as left, browser.new_context(**mobile) as right:
        first, second = left.new_page(), right.new_page()
        for page in (first, second):
            page.on('pageerror', lambda error: errors.append(str(error)))
        private_gallery(first, second, page_file)
        open_room(first, url, 'photos')
        open_room(second, url)
        caption(second, 'Thomas · Bacteriophage')
        choose(second, 'zone', 'center')
        # The listener must see the change without navigating or reloading.
        time_origin = second.evaluate('performance.timeOrigin')
        first.locator('#portraitFile').set_input_files(photo)
        first.locator('#portraitSubmit').click()
        expect(first.locator('#keep')).to_be_visible(timeout=30000)
        portrait = first.locator('.caption').inner_text()
        assert portrait in ('Guest portrait', 'Photo outlines')
        photo_files = drawing_files(first, '#downloads')
        keep(first)
        caption(second, portrait)
        before_border = frame(second)
        choose(first, 'zone', 'outer')
        choose(second, 'zone', 'outer')
        choose(second, 'stage', 'redrawn')
        border_name = second.locator('.caption').inner_text()
        keep(second)
        caption(first, border_name)
        background = frame(first)
        n = len(background)
        yy, xx = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
        radius = np.hypot(xx, yy)
        center = radius < .32
        border = (radius > .81) & (radius < .95) & (abs(xx) > .06)
        assert np.array_equal(before_border[center], background[center])
        assert np.any(before_border[border] != background[border])
        choose(first, 'zone', 'middle')
        choose(second, 'zone', 'middle')
        first.locator('#peopleBox > summary').click()
        first.locator('#personName').fill('Maya')
        first.locator('#personInterest').fill('plays guitar')
        first.locator('#personPlace').select_option('0')
        first.locator('#personSubmit').click()
        caption(first, 'Maya · Acoustic guitar')
        keep(first)
        caption(second, 'Maya · Acoustic guitar')
        assert second.evaluate('performance.timeOrigin') == time_origin
        neighbors = center | border
        assert np.array_equal(background[neighbors], frame(second)[neighbors])
        choose(second, 'zone', 'center')
        caption(second, portrait)
        assert drawing_files(second, '#roomFiles') == photo_files
        choose(second, 'zone', 'middle')

        # A poll sees a newer change while Maya's phone still has a preview.
        suggest(first, 'a pumpkin for Alex')
        held = frame(first)
        suggest(second, 'a rocket for Alex')
        keep(second)
        expect(first.locator('#roomReload')).to_be_visible(timeout=15000)
        caption(first, 'Alex · Pumpkin')
        assert np.array_equal(frame(first), held)
        first.locator('#roomReload').click()
        caption(first, 'Alex · Rocket')
        caption(first, 'Maya · Acoustic guitar')
        expect(first.locator('#idea')).to_have_value('a pumpkin for Alex')
        first.get_by_role('button', name='Preview suggestion').click()
        caption(first, 'Alex · Pumpkin')
        caption(first, 'Maya · Acoustic guitar')

        # Make both editors start on the same revision. Only the background
        # GET is held at that revision, so the stale PUT reaches the real server.
        def old_poll(route):
            tag = route.request.headers.get('if-none-match')
            if route.request.method == 'GET' and tag:
                route.fulfill(status=304, headers={'ETag': tag})
            else:
                route.continue_()

        first.route('**' + API, old_poll)
        suggest(first, 'a turkey for Lek')
        suggest(second, 'a pumpkin for Lek')
        accepted = keep(second)
        assert keep(first, status=409) == accepted
        caption(first, 'Lek · Turkey')
        current = second.request.get(url + API).json()
        assert current['revision'] == accepted
        assert current['state']['ids'] == ['guitar', 'rocket', 'pumpkin']
        first.unroute('**' + API, old_poll)
        expect(first.locator('#roomReload')).to_be_visible()
        first.locator('#roomReload').click()
        caption(first, 'Lek · Pumpkin')
        caption(first, 'Alex · Rocket')
        expect(first.locator('#idea')).to_have_value('a turkey for Lek')
        final = frame(first)
        assert np.array_equal(background[neighbors], final[neighbors])
        first.goto(page_file.resolve().as_uri() + '#guests')
        caption(first, 'Thomas · Turkey')

    # The old listener and both phones are gone. A newly started service
    # must restore both the shared sand and the center movement files.
    with room(page_file, database) as restarted, browser.new_context(**mobile) as newcomer:
        page = newcomer.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        open_room(page, restarted)
        for words in ('Maya · Acoustic guitar', 'Alex · Rocket', 'Lek · Pumpkin'):
            caption(page, words)
        assert np.array_equal(frame(page), final)
        choose(page, 'zone', 'center')
        caption(page, portrait)
        assert drawing_files(page, '#roomFiles') == photo_files
        choose(page, 'zone', 'outer')
        caption(page, border_name)
    assert not errors, errors
    print(f'Two phones shared a portrait, new guest and border. Both stale-edit paths held. '
          f'The private drawing stayed separate. Shared sand and {len(photo_files)} portrait file(s) survived restart.')


def shared_rotation(browser, page_file, database):
    # A suggestion arrives just before another guest's scheduled turn.
    with room(page_file, database) as url, browser.new_context() as a, browser.new_context() as b:
        host, guest = a.new_page(), b.new_page()
        host.clock.install(time='2026-11-20T19:00:00Z')
        host.clock.pause_at('2026-11-20T19:00:01Z')
        open_room(host, url, 'changing-garden')
        open_room(guest, url, 'people')
        panel = host.locator('#changingGarden')
        panel.get_by_role('button').click()
        expect(panel.get_by_role('status')).to_contain_text('Thomas')
        host.clock.fast_forward(26_000)
        guest.locator('#personName').fill('Bill')
        guest.locator('#personInterest').fill('Stargazing')
        guest.locator('#personDrawing').select_option('telescope')
        guest.locator('#personSubmit').click()
        revision = keep(guest)
        host.clock.fast_forward(2_100)
        caption(host, 'Bill · Telescope')
        expect(panel.get_by_role('status')).to_contain_text('Bill')
        host.clock.fast_forward(29_999)
        assert guest.request.get(url + API).json()['revision'] == revision
        with host.expect_response(lambda r: r.request.method == 'PUT' and r.status == 200):
            host.clock.fast_forward(1)
        caption(guest, 'Bill · Ringed planet')
        assert guest.request.get(url + API).json()['state']['ids'][1:] == ['books', 'temple']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', nargs='?', type=Path, help='a self-contained three-zone gallery')
    parser.add_argument('--photo', type=Path, default=ROOT / 'patterns/dog/face_crop.jpg')
    parser.add_argument('--chromium', type=Path, help='use an existing Chromium executable')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as name, sync_playwright() as playwright:
        folder = Path(name)
        page_file = args.page
        if page_file is None:
            ring_scene.build(folder, 450, 5, 2.5, 4)
            page_file = folder / 'garden.html'
            ring_preview.build(folder / 'scene.json', page_file, size=820)
        binary = args.chromium
        if binary is None and not Path(playwright.chromium.executable_path).is_file():
            installed = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
            binary = installed[-1] if installed else None
        with playwright.chromium.launch(executable_path=binary) as browser:
            exercise(browser, page_file, folder / 'room.sqlite3', args.photo)
            shared_rotation(browser, page_file, folder / 'rotation.sqlite3')
