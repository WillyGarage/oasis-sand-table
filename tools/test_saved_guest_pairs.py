#!/usr/bin/env python3
"""Pair a kept photo drawing with a stock subject on a second phone, then change a neighboring place."""
import argparse
import base64
from pathlib import Path
import re
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_ring_guest_border import MOBILE, save
from test_ring_object_photo import PhoneTraffic, crop
from test_saved_guest_drawings import ask


def exercise(browser, gallery, photo):
    with tempfile.TemporaryDirectory() as tmp, room(gallery, Path(tmp) / 'room.db') as url, \
            browser.new_context(**MOBILE, service_workers='block') as first, \
            browser.new_context(**MOBILE, service_workers='block') as second:
        traffic = PhoneTraffic(url)
        for phone in (first, second):
            phone.route('http**://**/*', traffic.check)
        teacher, guest = first.new_page(), second.new_page()
        api = url + API
        open_room(teacher, url)

        ask(teacher, 'a meadow oak for Thomas')
        teacher.locator('#suggestionPhoto').click()
        teacher.locator('#portraitFile').set_input_files(traffic.photo('oak.jpg', photo.read_bytes(), 'image/jpeg'))
        teacher.locator('#portraitSubmit').click()
        expect(teacher.locator('#keep')).to_be_visible(timeout=25000)
        crop(teacher, .45, .485, .714)
        learned = save(teacher, api)[0]['state']
        oak = learned['ids'][0]
        suggest(teacher, 'a guitar for Thomas')
        before = save(teacher, api)[0]['state']
        assert oak not in before['ids']

        open_room(guest, url)
        ask(guest, 'the saved meadow oak beside an open book for Alex')
        caption(guest, 'Alex · Meadow oak beside open book')
        expect(guest.locator('#portraitFile')).to_have_value('')
        download = drawing_files(guest, '#downloads')
        placement = save(guest, api)[0]
        assert download == [(p['name'], p['text'].encode()) for p in placement['motion']['files']]
        assert placement['motion']['place'] == 1 and placement['motion']['fill']
        after = placement['state']
        pair = after['ids'][1]
        assert pair != oak and after['custom'][pair] != after['custom'][oak]
        assert after['custom'][oak] == learned['custom'][oak]
        assert after['ids'] == [before['ids'][0], pair, before['ids'][2]]

        caption(teacher, 'Alex · Meadow oak beside open book')
        assert drawing_files(teacher, '#roomFiles') == download
        geometry = teacher.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.geometry")
        kept = np.frombuffer(base64.b64decode(after['bed']), dtype=np.uint8)
        n = int(np.sqrt(kept.size))
        y, x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
        angle = geometry['angles'][1]
        cx, cy = geometry['center'] * np.array([np.cos(angle), np.sin(angle)])
        alex = np.hypot(x - cx, -y - cy) < geometry['scale']
        suggest(teacher, 'a Thai rooftop for Lek')
        final = save(teacher, api)[0]['state']
        caption(guest, re.compile(r'Lek · (?:Swept )?Thai rooftop', re.I))
        assert final['ids'][:2] == after['ids'][:2] and final['ids'][2] != after['ids'][2]
        assert final['custom'][pair] == after['custom'][pair]
        new_bed = np.frombuffer(base64.b64decode(final['bed']), dtype=np.uint8)
        np.testing.assert_array_equal(kept[alex.ravel()], new_bed[alex.ravel()])
        assert guest.request.get(api).json()['state'] == final
        assert not traffic.violations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path, help='Seated gallery with three open guest places')
    parser.add_argument('photo', type=Path, help='Local meadow oak reference')
    args = parser.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, args.gallery, args.photo)
    print('Both phones kept the oak-and-book drawing through the neighboring guest change.')
