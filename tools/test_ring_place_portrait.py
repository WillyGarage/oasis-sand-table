#!/usr/bin/env python3
"""Check a photo in an occupied guest place, then in the same place after it is cleared."""
import argparse
import math
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, choose, drawing_files, keep, open_room, room, suggest
from test_guest_place import evidence
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_photo import frame


def select_photo(page, file):
    choose(page, 'zone', 'center')
    panel = page.locator('#centerPhoto')
    if not panel.evaluate('el=>el.open'):
        panel.locator('summary').first.click()
    page.locator('#portraitFile').set_input_files(file)
    page.locator('#portraitSubmit').click()
    expect(page.locator('#previewPlacePortrait')).to_be_visible(timeout=25000)


def select_guest_photo(page, file, slot, name):
    choose(page, 'zone', 'middle')
    panel = page.locator('#centerPhoto')
    if not panel.evaluate('el=>el.open'):
        panel.locator(':scope > summary').click()
    expect(panel.locator(':scope > summary')).to_have_text('Draw from a guest photo')
    page.locator('#portraitPlace').select_option(str(slot))
    page.locator('#portraitFile').set_input_files(file)
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#portraitMode')).to_be_hidden()
    expect(page.locator('#previewPlacePortrait')).to_be_hidden()
    page.get_by_role('button',name='Preview in '+name+'’s place').click()
    caption(page,name+' · Portrait from photo')
    expect(page.locator('input[name=zone][value=middle]')).to_be_checked()
    expect(page.locator('#keep')).to_have_text('Keep '+name+'’s portrait')


def check_gallery(gallery, center_photo, ring_photo, folder, group_photo):
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp, room(gallery, Path(temp) / 'garden.db') as url, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        browser = pw.chromium.launch(executable_path=str(chrome))
        first, second = [browser.new_page(**MOBILE) for _ in range(2)]
        open_room(first, url, 'photos')
        open_room(second, url)
        select_photo(first, center_photo)
        keep(first)
        center_files = drawing_files(first, '#roomFiles')
        live = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        catalog = live['planner']
        slot = 2
        for vacant in (False, True):
            if vacant:
                suggest(second, 'clear Lek’s place')
                keep(second)
                caption(first, 'Lek · Open place')
            before = first.request.get(url + API).json()['state']
            select_guest_photo(first, ring_photo, slot, 'Lek')
            if not vacant:
                choose(first, 'zone', 'center')
                expect(first.locator('input[name=stage][value=original]')).to_be_checked()
                expect(first.locator('#keep')).to_be_hidden()
                select_guest_photo(first, ring_photo, slot, 'Lek')
            assert first.request.get(url + API).json()['state'] == before
            frames = []
            for stage in ('original', 'cleared', 'redrawn'):
                choose(first, 'stage', stage)
                frames.append(frame(first))
            files = drawing_files(first, '#downloads')
            body, _ = save(first, url + API)
            assert body['motion']['place'] == slot and body['motion'].get('fill', False) == vacant
            assert [(f['name'], f['text'].encode()) for f in body['motion']['files']] == files
            after = body['state']
            assert before['portrait'] == after['portrait'] and before['ids'][:2] == after['ids'][:2]
            caption(second, 'Lek · Portrait from photo')
            assert drawing_files(second, '#roomFiles') == files
            second.reload()
            caption(second, 'Lek · Portrait from photo')
            if vacant:
                # Check the saved change from a fresh phone and the complete signed path.
                route = from_files(files, [-math.pi / 2, 1])
                assert route.shape[0] > 100 and np.isfinite(route).all()
                assert np.array_equal(frame(first), frame(second))
            else:
                metrics = evidence(first, folder, before, after, frames, files, catalog, slot, live)
                print('Occupied guest portrait', metrics, flush=True)
                for name, raster in zip(('before', 'cleared', 'redrawn'), frames):
                    Image.fromarray(raster).save(folder / (name + '.webp'), quality=95)
            choose(second, 'zone', 'center')
            assert drawing_files(second, '#roomFiles') == center_files
            choose(second, 'zone', 'middle')
        select_photo(first, ring_photo)
        first.locator('#portraitPlace').select_option(str(slot))
        first.locator('#previewPlacePortrait').click()
        expect(first.locator('#portraitStatus')).to_contain_text('already in that guest')
        first.locator('#portraitMode').select_option('group')
        expect(first.locator('#portraitPlaceField')).to_be_hidden()
        if group_photo:
            select_guest_photo(first, group_photo, 0, 'Thomas')
            face = first.locator('#faceBoxes button').nth(1)
            face.click()
            expect(face).to_have_attribute('aria-pressed', 'true')
            expect(first.locator('#keep')).to_be_visible()
            expected_shape = first.evaluate("""async () => {
                const c = JSON.parse(document.querySelector('#scene').textContent).live;
                const file = document.querySelector('#portraitFile').files[0];
                const result = await GuestPhoto.fromFile(file, {face:1,
                    portraitDiameterGrooves:2*c.planner.geometry.scale/c.groove});
                return result.points.slice(1,-1);
            }""")
            first.locator('#portraitPlace').select_option('1')
            caption(first, 'Alex · Portrait from photo')
            body, _ = save(first, url + API)
            state = body['state']
            assert body['motion']['zone'] == 'middle' and body['motion']['place'] == 1
            np.testing.assert_allclose(state['custom'][state['ids'][1]], expected_shape)
        # A person who starts at the center can still send that face to a guest.
        before = first.request.get(url + API).json()['state']
        select_photo(first, ring_photo)
        first.locator('#portraitPlace').select_option('0')
        first.locator('#previewPlacePortrait').click()
        caption(first, 'Thomas · Portrait from photo')
        expect(first.locator('input[name=zone][value=middle]')).to_be_checked()
        assert first.request.get(url + API).json()['state'] == before
        browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('center_photo', type=Path)
    parser.add_argument('ring_photo', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--group-photo', type=Path, help='Also pick a second face from this group.')
    args = parser.parse_args()
    check_gallery(args.gallery, args.center_photo, args.ring_photo, args.evidence, args.group_photo)
