#!/usr/bin/env python3
"""Use two independent phones on a simulated Mini serving the actual compressed guest assets."""
import argparse
import gzip
from io import StringIO
import math
import mimetypes
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from check_ring_scene import joined, read_path, safe_route, same_pose, same_track
from oasis_player import near, points
from test_guest_web import ORIGIN, ROOT, Table, photo_fixture

DOCK = (-math.pi / 2, 1.0)
SAFE_CENTER = (0.70 * 114 - 2.5 - 2) / 114
NOTE_RECEIPT = 'a1a759434a86d62e07f04f3c621303539fb3fadd22af07f4932759931218a502'
MINI = '95878d6310836abdf12f3927'
TRACKS = ROOT / 'patterns/guest-rings'


class FramedMini(Table):
    def __init__(self, assets):
        super().__init__()
        self.assets = assets
        self.status = dict(fw='v8.17', state='idle', theta=DOCK[0], rho=1, receipt=dict(state='complete', id=NOTE_RECEIPT),
                           auto=0, paused=0, fault=0, boot_pending=0, queue=[], homed=1, device_id=MINI, pattern_points=439,
                           steps_rev=11378, home_steps=10700, cal=dict(l=.46, ef=.30283, b1=.000613592, b2=.000122718,
                           phi0=2.31486, a=.000552233, a1=.000306796, k=.0000613592, rmax=.905, emarg=.05, th0=0))
        self.staged = ''
        self.uploads = []
        self.started = 0
        self.lose_upload_reply = False

    def handle(self, route):
        req = route.request
        path = urlsplit(req.url).path
        if path.startswith('/lib/guest'):
            file = self.assets / (Path(path).name + '.gz')
            assert file.is_file(), f'Missing packaged dependency {path}'
            return route.fulfill(body=gzip.decompress(file.read_bytes()), content_type=mimetypes.guess_type(path)[0])
        if path == '/status':
            return route.fulfill(json=self.status)
        if path not in ('/thr', '/play'):
            assert path != '/guest-draw', 'Protected drawing fell back to a whole-table erase.'
            return super().handle(route)
        headers = req.headers
        receipt = self.status['receipt']
        run = headers['x-oasis-run']
        assert len(bytes.fromhex(run)) == 32 and headers['x-oasis-device'] == MINI and self.status['state'] == 'idle'
        if path == '/thr':
            assert headers['x-guest-rev'] == str(self.revision)
            assert receipt['state'] != 'staged' and receipt['id'] != run
            previous = headers.get('x-oasis-previous')
            assert (receipt['id'] if receipt['state'] == 'complete' else None) == previous
            text = req.post_data
            first, _, count = points(dict(name='phone.thr', text=text))
            assert near((self.status['theta'], self.status['rho']), first)
            self.staged = text
            self.uploads.append(text)
            self.status.update(pattern_points=count, receipt=dict(id=run, state='staged'))
            if self.lose_upload_reply:
                self.lose_upload_reply = False
                return route.abort()
            return route.fulfill(json=dict(points=count, skipped=0))
        assert receipt == dict(id=run, state='staged') and self.staged
        self.status.update(state='drawing', receipt=dict(id=run, state='running'))
        self.revision += 1
        self.started += 1
        return route.fulfill(body='started tagged drawing')

    def finish(self):
        assert self.status['state'] == 'drawing' and self.staged
        _, last, count = points(dict(name='phone.thr', text=self.staged))
        self.status['receipt']['state'] = 'complete'
        self.status.update(state='idle', theta=last[0], rho=last[1], total=count, index=count, progress=1)
        self.staged = ''


def verify_center(text, stock=None):
    route = np.loadtxt(StringIO(text))
    assert 2 <= len(route) <= 12000 and same_pose(route[0], DOCK) and same_pose(route[-1], DOCK)
    assert abs(np.diff(route[:, 0])).max() < math.pi + .000025
    safe_route(route, DOCK[0], 0, SAFE_CENTER, DOCK, SAFE_CENTER, 'phone download')
    if stock:
        originals = [read_path(TRACKS / 'mini-center', name + '.thr') for name in ('center-clear', stock)]
        assert same_track(route, joined(originals, DOCK, DOCK, 'archived center replacement'))
    return len(route)


def run(browser, device, group_photo, screenshot):
    errors = []

    def phone():
        page = browser.new_page(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.context.route('**/*', lambda r: device.handle(r) if r.request.url.startswith(ORIGIN + '/') else r.abort())
        page.goto(ORIGIN + '/lib/guest.html')
        expect(page.locator('#previewButton')).to_be_enabled()
        return page

    def preview(page):
        page.locator('#previewButton').click()
        expect(page.locator('#draw')).to_be_enabled(timeout=9000)

    def start(page):
        with page.expect_response(lambda response: urlsplit(response.url).path == '/play') as response:
            page.locator('#draw').click()
        assert response.value.ok
        expect(page.locator('#message')).not_to_be_empty()

    a, b = phone(), phone()
    for page, subject in ((a, 'phage'), (b, 'guitar')):
        expect(page.locator('[data-tab="center"]')).to_have_attribute('aria-pressed', 'true')
        page.locator('#centerSubject').select_option(subject)
        preview(page)
    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        b.screenshot(path=str(screenshot), full_page=True)
    start(a)
    a.close()
    assert verify_center(device.uploads[0], 'phage') == 5722
    device.finish()
    # Second phone previewed the old guitar+note. Whether or not its poll has
    # already retired the preview, clicking cannot start a second upload.
    b.locator('#draw').evaluate('button => button.click()')
    expect(b.locator('#draw')).to_be_disabled()
    assert len(device.uploads) == device.started == 1
    b.close()

    guest = phone()
    expect(guest.locator('[data-tab="center"]')).to_have_attribute('aria-pressed', 'true')
    guest.locator('#centerSubject').select_option('guitar')
    preview(guest)
    start(guest)
    assert verify_center(device.uploads[-1], 'guitar') == 5625
    device.finish()
    guest.reload()
    guest.locator('#centerPhotoButton').click()
    assert guest.locator('#photoTarget').input_value() == 'center'
    guest.locator('#file').set_input_files(group_photo or photo_fixture())
    if group_photo:
        guest.locator('#photoMode').select_option('one')
        expect(guest.get_by_label('Head only')).to_be_checked()
        guest.get_by_label('Head only').uncheck()
        preview(guest)
        guest.locator('#faceBoxes button').nth(1).click()
        expect(guest.locator('#draw')).to_be_enabled()
        single = guest.locator('#drawing').evaluate('canvas => canvas.toDataURL()')
        guest.get_by_label('Head only').check()
        expect(guest.locator('#draw')).to_be_disabled()
        preview(guest)
        expect(guest.locator('#faceBoxes button').nth(1)).to_have_attribute('aria-pressed', 'true')
        assert single != guest.locator('#drawing').evaluate('canvas => canvas.toDataURL()')
        head, diameter = guest.evaluate('''async () => {
            const file=document.querySelector('#file').files[0], diameter=await GuestCenterRoutes.photoDiameterGrooves();
            const head=await GuestPhoto.fromFile(file,{face:1,portraitFraming:'framedHead',portraitDiameterGrooves:diameter});
            return [head.points,diameter];
        }''')
        assert head[0][1] <= -math.sqrt(.5) and head[-1] == head[0]
        assert np.max(np.linalg.norm(head[1:-1], axis=1)) <= 1 - 3/diameter + 1e-8
        guest.get_by_label('Head only').uncheck()
        preview(guest)
        assert single == guest.locator('#drawing').evaluate('canvas => canvas.toDataURL()')
    guest.locator('#photoMode').select_option('group')
    expect(guest.get_by_label('Close up on faces')).to_be_visible()
    preview(guest)
    if group_photo:
        expect(guest.locator('#faceBoxes button[aria-pressed=true]')).to_have_count(2)
        assert single != guest.locator('#drawing').evaluate('canvas => canvas.toDataURL()')
    if screenshot:
        guest.locator('.preview').screenshot(path=str(screenshot.with_name('group-preview.png')))
    start(guest)
    group_count = verify_center(device.uploads[-1])
    device.finish()
    guest.close()

    # A reboot or unrelated drawing loses the border receipt. Preview may
    # only re-establish it after an explicit choice. Start around the rim.
    device.status.update(receipt=dict(state='none', id=''), theta=.81, rho=1)
    device.revision += 1
    host = phone()
    expect(host.locator('[data-tab="people"]')).to_have_attribute('aria-pressed', 'true')
    host.locator('[data-tab="center"]').click()
    host.locator('#previewButton').click()
    expect(host.locator('#error')).not_to_be_empty()
    expect(host.locator('#draw')).to_be_disabled()
    assert device.started == 3
    host.locator('#centerSubject').select_option('frame')
    preview(host)
    start(host)
    frame = np.loadtxt(StringIO(device.uploads[-1]))
    original = read_path(TRACKS, 'lek-mini-gables-1.thr')
    assert same_track(frame[-len(original):], original)
    approach = frame[:-len(original)+1]
    assert near(approach[0], (.81, 1)) and np.all(approach[:, 1] == 1)
    delta = np.diff(approach[:, 0])
    assert np.abs(delta).sum() <= math.pi + .000025 and np.abs(delta).max() <= .05002
    device.finish()
    host.close()
    after = phone()
    expect(after.locator('[data-tab="center"]')).to_have_attribute('aria-pressed', 'true')
    assert device.started == len(device.uploads) == 4
    # The first phone explicitly asked for a guitar, but closed after upload
    # and before play. Opening a new phone must not start anything by itself.
    after.locator('#centerSubject').select_option('guitar')
    preview(after)
    device.lose_upload_reply = True
    after.locator('#draw').click()
    expect(after.locator('#resumeCenter')).to_be_visible()
    after.close()
    recovery = phone()
    expect(recovery.locator('#resumeCenter')).to_be_visible()
    assert device.started == 4 and len(device.uploads) == 5
    recovery.locator('#resumeCenter').click()
    expect(recovery.locator('#message')).to_contain_text('started')
    assert device.started == len(device.uploads) == 5 and not errors, errors
    verify_center(device.uploads[-1], 'guitar')
    device.finish()
    recovery.locator('#centerSubject').select_option('book-pencil')
    recovery.locator('#previewButton').click()
    expect(recovery.locator('#error')).to_contain_text('Draw the open book')
    expect(recovery.locator('#draw')).to_be_disabled()
    recovery.locator('#centerSubject').select_option('book')
    preview(recovery)
    start(recovery)
    verify_center(device.uploads[-1], 'book')
    device.finish()
    with phone() as other:
        other.locator('#centerSubject').select_option('book-pencil')
        preview(other)
        expect(other.locator('#effect')).to_contain_text('follows the existing book')
        start(other)
        text = device.uploads[-1]
        verify_center(text)
        assert text == (TRACKS / 'mini-center' / 'add-pencil.thr').read_text()
        device.finish()
        other.locator('#previewButton').click()
        expect(other.locator('#error')).to_contain_text('already on the open book')
        expect(other.locator('#draw')).to_be_disabled()
    assert device.started == len(device.uploads) == 7 and not errors, errors
    print(f'Two phones drew the phage (5,722 points), guitar (5,625), group photo ({group_count:,}), '
          f'border ({len(frame):,}), open book and additive pencil. The pencil required the matching book. '
          'A stale preview was rejected and an interrupted upload started once. All routes finished at the rim.')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--group-photo', type=Path, help='Optional real two-person photo; converted only in this browser.')
    cli.add_argument('--screenshot', type=Path)
    args = cli.parse_args()
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        assets = Path(temp)
        build_guest_web_assets(ROOT / 'web', assets)
        cached = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(**({'executable_path': str(cached[-1])} if cached else {})) as browser:
            run(browser, FramedMini(assets), args.group_photo, args.screenshot)


if __name__ == '__main__':
    main()
