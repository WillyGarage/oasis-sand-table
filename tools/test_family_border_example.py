"""Check a private family-border link against the same saved portrait in a regular two-phone room.

Run with the dinner editor, a two-zone scene.json and the .oasisportrait supplied to --family-border.
"""

import argparse
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from check_ring_scene import check_reveal, travel
from test_garden_room import caption, choose, drawing_files, room
from test_ring_guest_border import MOBILE, from_files, preview, replay, save
from test_ring_photo import frame
from test_ring_shadows import ready
from wide_portrait import chromium


def check(gallery, manifest, drawing):
    import json

    scene = json.loads(manifest.read_text())
    with tempfile.TemporaryDirectory() as tmp, room(gallery, Path(tmp)/'room.db') as url, sync_playwright() as pw, \
            pw.chromium.launch(executable_path=chromium(pw, None)) as browser, \
            browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as phone:
        api = url + '/api/garden/portrait'
        host.goto(url+'/garden?layout=portrait#prepared-portrait')
        host.locator('#portraitFile').set_input_files(drawing)
        host.locator('#portraitSubmit').click()
        ready(host)
        portrait_files = drawing_files(host, '#downloads')
        payload, _ = save(host, api)
        choose(host, 'zone', 'outer')
        original = frame(host)
        preview(host, 2, 'Lek', 'progressive')
        border_files = drawing_files(host, '#downloads')
        route = from_files(border_files, scene['dock'])
        outer = scene['zones']['outer']
        report = check_reveal(scene, outer, outer['variants'][2], route)
        first = report['endpoints'][0]
        entry = len(outer['transit'])-1
        first_image = replay(host, payload['state']['bed'], route[:entry+1], route[entry:first+1])
        final = frame(host)
        _, revision = save(host, api)

        # Anyone opening this link gets the same opening, even if both the
        # shared room and this browser had already changed the border.
        phone.route('**/private?*', lambda request: request.fulfill(path=gallery, content_type='text/html'))
        phone.goto(url+'/private?layout=portrait#border')
        preview(phone, 3, 'Lek', 'progressive')
        phone.locator('#keep').click()
        expect(phone.locator('#keep')).to_be_hidden()
        stored = phone.evaluate('Object.entries(localStorage)')
        assert stored
        requests = []
        phone.on('request', lambda request: requests.append(request.url) if '/api/' in request.url else None)
        link = url+'/garden?layout=portrait&example=family-border#border'
        phone.goto(link)
        expect(phone.locator('#layoutChoice')).to_be_hidden()
        expect(phone.locator('#borderDesign')).to_have_value('2')
        expect(phone.locator('#borderGuest')).to_have_value('Lek')
        np.testing.assert_array_equal(frame(phone), original)
        setup = drawing_files(phone, '#setupFiles')
        assert [b for _, b in setup[-len(portrait_files):]] == [b for _, b in portrait_files]
        phone.locator('#borderPreview').click()
        assert drawing_files(phone, '#downloads') == border_files
        choose(phone, 'stage', 'cleared')
        caption(phone, f'{round(100*report["first_fraction"])}% of the ball')
        caption(phone, '1 of 10 roof peaks complete')
        first_on_phone = frame(phone)
        zoom = phone.get_by_role('button', name='Enlarge border')
        zoom.click()
        expect(phone.locator('#guestZoom')).to_have_attribute('aria-pressed', 'true')
        phone.locator('#guestZoom').click()
        error = np.abs(first_on_phone.astype(float)-first_image)
        assert error.mean() < .1 and np.percentile(error, 99) < 2
        ny, nx = original.shape[:2]
        y, x = np.mgrid[-1:1:complex(ny), -1:1:complex(nx)]
        inner = np.hypot(x, y) <= scene['zones']['center']['safe_bounds'][1]
        np.testing.assert_array_equal(first_on_phone[inner], original[inner])
        length = travel(route)
        half = np.argmin(np.abs(length-length[-1]/2))
        complete = sum(i <= half for i in report['endpoints'])
        phone.locator('#guestMoment').select_option('halfway')
        caption(phone, f'{complete} of 10 roof peaks complete')
        choose(phone, 'stage', 'redrawn')
        np.testing.assert_array_equal(frame(phone), final)
        np.testing.assert_array_equal(final[inner], original[inner])
        phone.locator('#keep').click()
        expect(phone.locator('#keep')).to_be_hidden()
        phone.locator('#reset').click()
        np.testing.assert_array_equal(frame(phone), original)
        expect(phone.locator('#borderDesign')).to_have_value('2')
        expect(phone.locator('#borderGuest')).to_have_value('Lek')
        phone.reload()
        np.testing.assert_array_equal(frame(phone), original)
        assert not requests and stored == phone.evaluate('Object.entries(localStorage)')
        assert host.request.get(api).json()['revision'] == revision
        print('The family border matched both saved movement files, completed its first roof, and preserved both gardens.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('gallery', 'manifest', 'drawing'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    check(args.gallery, args.manifest, args.drawing)
