#!/usr/bin/env python3
"""Use a phone browser and a real room server with a simulated table.

    python3 tools/test_attached_garden.py captures/zone-playback/garden.html

Without an argument, generate both layouts in a temporary folder.
"""
import argparse
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
from playwright.sync_api import expect, sync_playwright

from garden_room import make_server
from oasis_player import PlaybackError
import ring_preview
import ring_scene
from test_garden_playback import Controller
from test_garden_room import API, caption, keep, open_room, suggest
from test_ring_photo import frame


class Table(Controller):
    identity = 'calibrated-local-table'

    def bind_identity(self, expected=None):
        if expected is not None and expected != self.identity:
            raise PlaybackError('A different physical table is connected.')
        return self.identity

    def dispatched(self, count):
        deadline = time.monotonic() + 3
        while (len(self.calls) < count or self.outcome != 'running') and time.monotonic() < deadline:
            time.sleep(.01)
        assert len(self.calls) == count and self.outcome == 'running'
        return self.last_file


@contextmanager
def served(page_file, database, table, prepared=False, *, layout='garden'):
    with make_server(page_file, database, controller=table, table_layout=layout,
                     prepared=prepared, hold_seconds=2, poll_seconds=.05) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


def refused(page_file, database, message, **options):
    try:
        server = make_server(page_file, database, **options)
    except (ValueError, PlaybackError) as error:
        assert message.lower() in str(error).lower(), str(error)
    else:
        server.server_close()
        raise AssertionError('Unexpectedly allowed attachment: ' + message)


def wait_table(page, url, **wanted):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        response = page.request.get(url + '/api/playback')
        assert response.status == 200
        state = response.json()
        if all(state[key] == value for key, value in wanted.items()):
            return state
        time.sleep(.12)
    raise AssertionError(f'Expected {wanted}, last observed {state}')


def exercise(browser, page_file, folder):
    database = folder / 'party.db'
    table = Table(database)
    mobile = dict(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
    errors = []
    # Fresh sand must be confirmed explicitly. An existing preview-only room
    # carries no information about what is really on the table.
    refused(page_file, database, 'prepared sand', controller=table, table_layout='garden')
    private = folder / 'private.db'
    with make_server(page_file, private):
        pass
    refused(page_file, private, 'physical layout', controller=table, table_layout='garden', prepared=True)
    assert not table.calls
    with served(page_file, database, table, prepared=True) as url, browser.new_context(**mobile) as phone:
        page = phone.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        open_room(page, url, 'changing-garden')
        expect(page.locator('#tableStatus')).to_contain_text('Drawing the starting layout · part 1 of 2')
        assert page.locator('#layout').input_value() == 'garden'
        expect(page.locator('#layoutChoice')).to_be_hidden()
        setup = page.evaluate("JSON.parse(document.getElementById('scene').textContent).live.setup")
        assert len(setup) == 2 and table.dispatched(1) == setup[0]
        writes = []
        page.on('request', lambda req: writes.append(req.post_data_json) if req.method == 'PUT' else None)
        initial = frame(page)
        n = len(initial)
        yy, xx = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
        radius = np.hypot(xx, yy)
        protected = ((radius < .32) | ((radius > .81) & (radius < .95))) & (abs(xx) > .06)
        suggest(page, 'a guitar for Thomas')
        candidate = frame(page)
        assert np.array_equal(candidate[protected], initial[protected])
        assert np.any(candidate != initial)
        expect(page.locator('#keep')).to_have_text('Queue this drawing')
        assert keep(page) == 1
        manual = writes[-1]
        queued = wait_table(page, url, state='drawing', revision=1, queued=1, part=1)
        assert queued['drawing']['zone'] == 'setup' and not queued['ready']

        page.locator('#peopleBox > summary').click()
        page.locator('#personName').fill('Maya')
        page.locator('#personInterest').fill('plays guitar')
        page.locator('#personPlace').select_option('0')
        page.locator('#personSubmit').click()
        caption(page, 'Maya · Acoustic guitar')
        expect(page.locator('#keep')).to_have_text('Keep guest')
        assert keep(page) == 2
        assert 'motion' not in writes[-1], 'A guest taking the same drawing should need no movement.'
        saved = page.request.get(url + API).json()
        assert saved['revision'] == 2
        wait_table(page, url, queued=1, revision=2)
        payload = dict(manual, state=saved['state'], revision=2)

        def reject(body, code, path=API):
            response = page.request.put(url + path, headers={'Origin':url}, data=body)
            assert response.status == code, response.text()[:300]

        reject(dict(payload, automatic=True), 409)
        reject({'revision':2, 'state':None}, 400)
        reject(dict(revision=2, state=dict(saved['state'], starting=True)), 400)
        reject({'revision':0, 'state':None}, 409, '/api/garden/portrait')
        expect(page.locator('#reset')).to_be_hidden()
        reject(dict(payload, state=dict(saved['state'], center=1-saved['state']['center'])), 400)
        outside = copy.deepcopy(payload)
        part = outside['motion']['files'][0]
        points = part['text'].splitlines()
        # This remains a dock-to-dock route but a mid-ring segment now cuts
        # straight into the protected center at ten percent of the radius.
        mid = len(points) // 2
        points[mid] = points[mid].split()[0] + ' 0.10000'
        part['text'] = '\n'.join(points) + '\n'
        reject(outside, 400)
        assert page.request.get(url + API).json()['revision'] == 2 and len(table.calls) == 1

        # The host can arm rotation now. Its own real HTTP save must wait
        # through both the multipart setup and the queued manual change.
        toggle = page.locator('#changingGarden button')
        toggle.click()
        expect(toggle).to_have_text('Stop changing')
        table.outcome = 'complete'
        wait_table(page, url, state='drawing', part=2)
        assert table.dispatched(2) == setup[1]
        table.outcome = 'complete'
        displayed = wait_table(page, url, state='hold', part=2)
        assert displayed['holdSeconds'] > 0 and displayed['lastCompleted'] == {'revision':0, 'zone':'setup'}
        assert displayed['queued'] == 1 and not displayed['ready'] and len(writes) == 2
        wait_table(page, url, state='drawing', drawing={'revision':1, 'zone':'middle'})
        assert table.dispatched(3) == manual['motion']['files'][0]
        assert not any(body.get('automatic') for body in writes)
        table.outcome = 'complete'
        displayed = wait_table(page, url, state='hold', drawing={'revision':1, 'zone':'middle'})
        assert displayed['lastCompleted']['revision'] == 1 and not displayed['ready']
        with page.expect_response(lambda response: response.request.method == 'PUT' and
                                  response.request.post_data_json.get('automatic'), timeout=15000) as save:
            pass
        assert save.value.status == 200
        automatic = save.value.request.post_data_json
        assert automatic['revision'] == 2 and automatic['motion']['zone'] == 'middle'
        assert automatic['state']['ids'] != saved['state']['ids']
        wait_table(page, url, state='drawing', drawing={'revision':3, 'zone':'middle'})
        assert table.dispatched(4) == automatic['motion']['files'][0]
        assert len(table.calls) == 4 and sum(bool(body.get('automatic')) for body in writes) == 1
        # A second host cannot enqueue the same physical change at this revision.
        reject(automatic, 409)
        retained = page.request.get(url + API).json()
        assert retained['revision'] == 3
        last_token = table.token

    # A different device, altered working radius, another layout or reopening
    # as a private preview must never replay an existing physical session.
    refused(page_file, database, 'attached table')
    refused(page_file, database, 'physical layout', controller=table, table_layout='portrait')
    other = Table(database)
    other.identity = 'another-local-table'
    refused(page_file, database, 'different physical table', controller=other, table_layout='garden')
    # Keep the original paths, bed and edition byte-for-byte equivalent.
    # A corrected physical radius alone invalidates its calibration.
    different = folder / 'different.html'
    prefix, marker, tail = page_file.read_text().partition('<script type="application/json" id="scene">')
    data, closer, tail = tail.partition('</script>')
    assert marker and closer
    revised = json.loads(data)
    revised['live']['radiusMM'] += 1
    different.write_text(prefix + marker + json.dumps(revised, separators=(',', ':')) + closer + tail)
    refused(different, database, 'physical layout', controller=table, table_layout='garden')
    assert not other.calls and len(table.calls) == 4

    with served(page_file, database, table) as url, browser.new_context(**mobile) as phone:
        page = phone.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        open_room(page, url)
        caption(page, 'Maya')
        wait_table(page, url, state='drawing', revision=3)
        assert len(table.calls) == 4 and table.token == last_token
        assert page.request.get(url + API).json() == retained
        table.outcome = 'complete'
        wait_table(page, url, state='idle', ready=True, revision=3, queued=0)
        expect(page.locator('#tableStatus')).to_have_text('Table ready', timeout=7000)
        assert len(table.calls) == 4
        expect(page.locator('#tableFinished')).to_contain_text('guest ring (change 3)')
    assert not errors, errors
    print('Attached phone garden passed. Two setup files finished in order; a manual guest drawing queued '
          'during setup, a same-art guest needed no motion, and the host added one automatic drawing '
          'after the viewing hold. Protected zones, table identity and restart receipts were enforced.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', nargs='?', type=Path, help='generated gallery containing both layouts')
    parser.add_argument('--chromium', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as name, sync_playwright() as pw:
        folder = Path(name)
        page_file = args.page
        if page_file is None:
            for key in ('garden', 'portrait'):
                ring_scene.build(folder / key, 450, 5, 2.5, 4, key)
            page_file = folder / 'layouts.html'
            ring_preview.build(folder / 'garden/scene.json', page_file, size=650,
                               portrait_layout=folder / 'portrait/scene.json')
        binary = args.chromium
        if binary is None and not Path(pw.chromium.executable_path).is_file():
            installed = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
            binary = installed[-1] if installed else None
        with pw.chromium.launch(executable_path=binary) as browser:
            exercise(browser, page_file, folder)
