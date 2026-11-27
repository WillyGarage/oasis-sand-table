#!/usr/bin/env python3
"""Follow a personal inscription from the dinner phone form into a saved table movement."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from guest_fill_checks import checked_fill, original_excursion
from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_guest_place import contour_samples, unpack
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_lettering import seat_view
from test_ring_photo import frame
from wide_portrait import chromium


REQUEST = 'a heart with B and L inside for Lek'


def enter(page, text):
    page.locator('#idea').fill(text)
    page.get_by_role('button', name='Preview suggestion').click()


def download(page, text, label):
    suggest(page, text)
    caption(page, label)
    return drawing_files(page, '#downloads')


def verify_ink(page, files, state, slot, text):
    live = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
    catalog, radius = live['planner'], live['radiusMM']
    geometry = catalog['geometry']
    size = radius * geometry['scale']
    layout = page.evaluate('([text,groove])=>GuestLettering.inHeart(text,{groove})', [text, catalog['pairGroove']])
    np.testing.assert_allclose(layout['path'], state['custom'][state['ids'][slot]], rtol=0, atol=1e-8)
    route = from_files(files, unpack(catalog['transit'])[0])
    _, engraving, _ = checked_fill(route, catalog, slot, original_excursion(page, catalog, state, slot))
    axis = np.array([np.cos(geometry['angles'][slot]), np.sin(geometry['angles'][slot])])
    position = check.sample_walk(engraving, .0001) - geometry['center'] * axis
    local = np.column_stack((position @ [-axis[1], axis[0]], -position @ axis)) / geometry['scale']
    tree = cKDTree(local)
    errors = []
    for stroke in [layout['heart'], *layout['letters']]:
        measured = tree.query(contour_samples(np.asarray(stroke), .001))[0].max() * size
        assert measured < .15, ('Missing engraved line', measured)
        errors.append(round(float(measured), 3))
    assert layout['legible'] and len(layout['letters']) == len(text)
    return dict(positions=len(route), capital_mm=round(layout['capHeightGrooves'] * live['groove'] * radius, 2),
                heart_and_letter_misses_mm=errors, travel_m=round(float(check.travel(route)[-1]*radius/1000), 3),
                sha256=sha256(files[0][1]).hexdigest())


def run(browser, previous, editor, output, db):
    output.mkdir(parents=True, exist_ok=True)
    controls = ['write “BL” for Lek', 'a guitar for Alex']
    with browser.new_page(**MOBILE, offline=True) as old:
        old.goto(previous.resolve().as_uri() + '#guests')
        enter(old, REQUEST)
        expect(old.locator('#suggestionPhoto')).to_be_visible()
        expect(old.locator('#keep')).to_be_hidden()
        expect(old.locator('#downloads')).to_be_hidden()
        old.locator('#guestEditor').screenshot(path=output/'previous-form.png')
        prior = [download(old, phrase, label) for phrase, label in zip(controls, ['Lek · “BL”', 'Alex · Acoustic guitar'])]

    with browser.new_page(**MOBILE, offline=True) as p:
        p.goto(editor.resolve().as_uri() + '?layout=portrait#example-heart-initials')
        expect(p.locator('#layout')).to_have_value('garden')
        expect(p.locator('#idea')).to_have_value(REQUEST)
        caption(p, 'Lek · Heart with BL')
        reference = drawing_files(p, '#downloads')
        for phrase in ['please draw a heart with the initials B and L for Lek', 'draw a heart with BL inside for Lek',
                       'write B & L in a heart for Lek', 'a heart around the initials bl for Lek']:
            assert download(p, phrase, 'Lek · Heart with BL') == reference
        for phrase, files, label in zip(controls, prior, ['Lek · “BL”', 'Alex · Acoustic guitar']):
            assert download(p, phrase, label) == files
        assert download(p, 'put my initial in a heart for Alex', 'Alex · Heart with A') != reference
        for words in ['a heart with a bird in it for Lek', 'a heart with the initials BL painted on a guitar for Lek']:
            enter(p, words)
            assert 'Heart with BL' not in p.locator('.caption').inner_text()
        enter(p, 'a heart with B and L inside for Nobody')
        expect(p.locator('#error')).to_contain_text('Choose a guest')
        expect(p.locator('#keep')).to_be_hidden()
        design_failures = p.evaluate("""()=>{
          const c=JSON.parse(document.querySelector('#scene').textContent).live.planner;
          const invalid=[];
          for(const a of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')for(const b of ['','A','W']){
            const v=GuestLettering.inHeart(a+b,{groove:c.pairGroove}),p=v.path;
            if(!v.legible || p.length<10 || p.length>8000 || p.some(q=>!q.every(Number.isFinite)||Math.hypot(...q)>1) ||
              p[0][0]!==p.at(-1)[0] || p[0][1]!==p.at(-1)[1])invalid.push(a+b);
          }
          return invalid;
        }""")
        assert not design_failures, design_failures

    with room(editor, db) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        for p in (host, guest):
            open_room(p, url)
        download(host, 'a phage for Thomas and an open book for Alex', 'Alex · Open book')
        save(host, url + API)
        caption(guest, 'Alex · Open book')
        original = host.request.get(url + API).json()
        geom = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.geometry")
        files = download(guest, REQUEST, 'Lek · Heart with BL')
        assert files == reference and host.request.get(url + API).json() == original
        expected = frame(guest)
        seat_view(expected, geom, 2).save(output/'heart-bl.png')
        (output/'heart-bl.thr').write_bytes(files[0][1])
        guest.locator('#guestZoom').click()
        guest.locator('.bowl').scroll_into_view_if_needed()
        guest.screenshot(path=output/'phone.png')
        saved, _ = save(guest, url + API)
        before, now = original['state'], saved['state']
        assert now['ids'][:2] == before['ids'][:2] and saved['motion']['place'] == 2
        proof = verify_ink(guest, files, now, 2, 'BL')
        caption(host, 'Lek · Heart with BL')
        assert drawing_files(host, '#roomFiles') == files
        # Both phones restore the shared height grid. Its saved precision
        # can move the preview's shade by one level when the room is kept.
        np.testing.assert_array_equal(frame(host), frame(guest))
        assert np.max(np.abs(frame(host).astype(int)-expected.astype(int))) <= 1
        host.goto('about:blank')
        open_room(host, url, 'example-heart-initials')
        caption(host, 'Lek · Heart with BL')
        expect(host.locator('#keep')).to_be_hidden()
        assert drawing_files(host, '#roomFiles') == files
        expect(host.locator('#error')).to_be_empty()
        # The recipient gets their own initial. A second guest in the same
        # sentence can request a different engraving, without changing Lek's.
        download(host, 'put my initial in a heart for Alex and a guitar for Thomas', 'Alex · Heart with A')
        updated, _ = save(host, url+API)
        assert updated['state']['ids'][2] == now['ids'][2]
        caption(guest, 'Alex · Heart with A')
        caption(guest, 'Thomas · Acoustic guitar')
        caption(guest, 'Lek · Heart with BL')
        assert [part['place'] for part in updated['motion']['parts']] in ([0,1], [1,0])
    (output/'verified.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'editor', 'output'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw,None)) as browser:
        run(browser, args.previous, args.editor, args.output, Path(tmp)/'garden.sqlite')
