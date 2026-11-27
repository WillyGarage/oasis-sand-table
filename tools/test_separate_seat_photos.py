#!/usr/bin/env python3
"""Exercise a seated family portrait from separate original photos on two local mobile browsers.

Pass the new gallery, the previous single-photo gallery and a private directory containing
bill-with-lek.jpg, thomas.jpg, alex.jpg and lek.jpg. Only simulated sand is saved as evidence.
"""
import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from test_attached_garden import Table, served, wait_table
from test_garden_room import choose, drawing_files
from test_ring_guest_border import MOBILE, from_files, open_garden, preview, replay, save
from test_ring_object_photo import PhoneTraffic, expand
from test_ring_photo import frame
from test_ring_shadows import ready
from test_seated_beard import center_and_border


def photo_form(page):
    choose(page, 'zone', 'center')
    expand(page, '#centerPhoto')


def render(page):
    page.locator('#portraitSubmit').click()
    ready(page)
    return drawing_files(page, '#downloads')


def reference_pair(page, url, pair):
    page.goto(url + '?layout=portrait#photos')
    photo_form(page)
    page.locator('#portraitFile').set_input_files(pair)
    page.locator('#portraitMode').select_option('group')
    page.locator('#portraitStyle').select_option('seats')
    ordinary = render(page)
    page.locator('#seatedReveal').check()
    ready(page)
    early = drawing_files(page, '#downloads')
    assert ordinary != early
    return ordinary, early


def chair_photo(page, photo, face_count, *, left=None, replace=False):
    selector = '#replaceSeatPhotoFile' if replace else '#seatPhotoFile'
    page.locator(selector).set_input_files(photo)
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#downloads')).to_be_hidden()
    buttons = page.locator('#faceBoxes button')
    expect(buttons).to_have_count(face_count, timeout=15000)
    if left is not None:
        expand(page, '#portraitSource')
        positions = buttons.evaluate_all('bs => bs.map(b => parseFloat(b.style.left) + parseFloat(b.style.width)/2)')
        assert len(set(positions)) == len(positions)
        buttons.nth(int(np.argmin(positions) if left else np.argmax(positions))).tap()


def remove_unfinished_photo(page, photo, expected):
    # A late detector response from a removed chair must never select somebody
    # else's face or revive a stale preview.
    page.evaluate("""() => {
      const inspect = GuestPhoto.inspectSeatPhoto;
      GuestPhoto.inspectSeatPhoto = async file => {
        GuestPhoto.inspectSeatPhoto = inspect;
        await new Promise(resolve => window.finishSeatScan = resolve);
        try { return await inspect(file); }
        finally { window.seatScanReturned = true; }
      };
    }""")
    page.locator('#seatPhotoFile').set_input_files(photo)
    page.wait_for_function("typeof window.finishSeatScan === 'function'")
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#portraitSubmit')).to_be_disabled()
    page.locator('#seatPhotoRemove').click()
    page.evaluate('window.finishSeatScan()')
    page.wait_for_function('window.seatScanReturned')
    expect(page.locator('#seatPhotoList option')).to_have_count(2)
    assert render(page) == expected


def layout_and_edits(page, gallery, photos, reference):
    page.goto(gallery + '?layout=portrait#photos')
    photo_form(page)
    page.locator('#portraitMode').select_option('separate')
    chair_photo(page, photos['bill-with-lek'], 2, left=True)
    expect(page.locator('#keep')).to_be_hidden()
    chair_photo(page, photos['bill-with-lek'], 2, left=False)
    assert render(page) == reference[0], 'The same two photographed people moved on the new route'
    page.locator('#seatedReveal').check()
    ready(page)
    assert drawing_files(page, '#downloads') == reference[1]
    page.locator('#seatedReveal').uncheck()
    ready(page)

    chair_photo(page, photos['alex'], 1, replace=True)
    chair_photo(page, photos['lek'], 1)
    three = render(page)
    expect(page.locator('#seatNumber')).to_have_text('Seat 1 of 3')
    page.locator('#seatPhotoEarlier').click()
    assert render(page) != three
    page.locator('#seatPhotoLater').click()
    assert render(page) == three
    page.locator('#layout').select_option('garden')
    expect(page.locator('#seatPhotoList option')).to_have_count(3)
    compact = render(page)
    assert compact != three
    page.locator('#layout').select_option('portrait')
    assert render(page) == three
    page.locator('#seatPhotoRemove').click()
    expect(page.locator('#seatPhotoList option')).to_have_count(2)
    assert render(page) != three
    page.locator('#seatPhotoList').select_option('0')
    chair_photo(page, photos['thomas'], 1, replace=True)
    final = render(page)
    assert final != reference[0]
    remove_unfinished_photo(page, photos['bill-with-lek'], final)
    page.locator('#seatPhotoFile').set_input_files({'name':'damaged.jpg', 'mimeType':'image/jpeg', 'buffer':b'broken JPEG'})
    expect(page.locator('#portraitStatus')).to_contain_text('Could not open')
    expect(page.locator('#portraitSubmit')).to_be_disabled()
    expect(page.locator('#downloads')).to_be_hidden()
    page.locator('#seatPhotoRemove').click()
    assert render(page) == final


def attached(browser, args, db):
    table = Table(db)
    errors = []
    api_path = '/api/garden/portrait'
    with served(args.gallery, db, table, prepared=True, layout='portrait') as url, browser.new_page(**MOBILE) as host:
        traffic = PhoneTraffic(url, api_path)
        host.route('http**://**/*', traffic.check)
        host.on('pageerror', lambda error: errors.append(str(error)))
        open_garden(host, url, 'portrait')
        api = url + api_path
        jobs = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
        preview(host, 4, 'Lek', order='progressive')
        request, _ = save(host, api)
        jobs.extend(request['motion']['files'])
        before = frame(host)
        initial = host.request.get(api).json()['state']
        photo_form(host)
        host.locator('#portraitMode').select_option('separate')
        for name, count in [('thomas', 1), ('alex', 1), ('lek', 1), ('bill-with-lek', 2)]:
            file = args.photos / (name + '.jpg')
            source = traffic.photo(file.name, file.read_bytes(), 'image/jpeg')
            chair_photo(host, source, count, left=True if count == 2 else None)
        files = render(host)
        host.locator('#seatedReveal').check()
        ready(host)
        early = drawing_files(host, '#downloads')
        assert early != files
        data = host.evaluate("""() => {
          const s=JSON.parse(document.querySelector('#scene').textContent);
          return {radius:s.zones.center.transit.at(-1)[1], groove:s.live.groove, dock:s.zones.center.transit[0]};
        }""")
        route = from_files(early, data['dock'])
        center, border = center_and_border(len(before), data)
        rebuilt = replay(host, initial['bed'], route)
        shown = frame(host)
        difference = abs(rebuilt.astype(np.int16) - shown)
        assert difference.mean() < 1.1 and np.percentile(difference, 99) < 5
        for image in [shown, rebuilt]:
            np.testing.assert_array_equal(image[border], before[border])
            assert np.any(image[center] != before[center])
        Image.fromarray(rebuilt).save(args.evidence / 'four-people-signed.png')
        saved, _ = save(host, api)
        jobs.extend(saved['motion']['files'])
        assert saved['state']['portraitSeats'] == 4
        assert [(p['name'], p['text'].encode()) for p in saved['motion']['files']] == early
        assert traffic.writes == 2 and not traffic.violations, traffic.violations
        settled = frame(host)
        assert not errors, errors

    with served(args.gallery, db, table, layout='portrait') as url, browser.new_page(**MOBILE) as guest:
        api = url + api_path
        guest.on('pageerror', lambda error: errors.append(str(error)))
        open_garden(guest, url, 'portrait')
        choose(guest, 'zone', 'center')
        assert drawing_files(guest, '#roomFiles') == early
        assert np.array_equal(frame(guest), settled)
        assert guest.locator('#seatPhotoList option').count() == 0
        for index in range(4):
            expect(guest.locator('#seatNumber')).to_have_text(f'Seat {index+1} of 4')
            angle = guest.locator('#sand').evaluate('el=>parseFloat(getComputedStyle(el).rotate)||0')
            assert abs((angle + 90*index + 180) % 360 - 180) < .001
            guest.locator('#nextSeat').tap()
        choose(guest, 'zone', 'outer')
        preview(guest, 3, 'Lek', order='whole')
        changed, revision = save(guest, api)
        jobs.extend(changed['motion']['files'])
        after = frame(guest)
        assert np.array_equal(after[center], settled[center]) and np.any(after[border] != settled[border])
        assert guest.request.get(api + '/drawings/center').json()['files'] == saved['motion']['files']
        for index, job in enumerate(jobs, 1):
            assert table.dispatched(index) == job
            table.outcome = 'complete'
        wait_table(guest, url, state='idle', queued=0, ready=True, revision=revision)
        assert len(table.calls) == len(jobs) and not errors, errors
        return dict(seats=4, protected_center_pixels=int(center.sum()), protected_border_pixels=int(border.sum()),
                    ordered_files=len(jobs), source_uploads=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('previous', type=Path)
    parser.add_argument('photos', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    photos = {p.stem:p for p in args.photos.glob('*.jpg')}
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            with browser.new_page(**MOBILE) as first:
                reference = reference_pair(first, args.previous.resolve().as_uri(), photos['bill-with-lek'])
            with browser.new_page(**MOBILE) as host:
                layout_and_edits(host, args.gallery.resolve().as_uri(), photos, reference)
            result = attached(browser, args, Path(temp) / 'room.db')
        (args.evidence / 'phone-results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(result, flush=True)


if __name__ == '__main__':
    main()
