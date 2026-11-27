#!/usr/bin/env python3
"""Rehearse the Mayflower on two local phones and compare the actual guest drawing files."""
import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene

from test_folded_guest_crane import measure
from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_guest_place import contour, contour_samples
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_lettering import seat_view
from test_ring_photo import frame
from wide_portrait import chromium


def neighbor_files(page):
    requests = ('a phage for Thomas', 'an open book for Alex')
    result = {}
    for words in requests:
        suggest(page, words)
        result[words] = drawing_files(page, '#downloads')
    return result


def controls(page, gallery):
    page.goto(gallery.resolve().as_uri() + '#guests')
    result = neighbor_files(page)
    for words in ('a mayflower blossom', 'a mayflower flower', 'a lotus flower', 'a sailboat', 'a ship'):
        suggest(page, words + ' for Lek')
        result[words] = drawing_files(page, '#downloads')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('gallery', 'previous', 'out'):
        parser.add_argument(key, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        with browser.new_page(**MOBILE, offline=True) as old, browser.new_page(**MOBILE, offline=True) as new:
            assert controls(old, args.previous) == controls(new, args.gallery)
            new.goto(args.gallery.resolve().as_uri() + '?layout=portrait#example-mayflower')
            caption(new, 'Lek · Mayflower sailing ship')
            linked = drawing_files(new, '#downloads')
            geometry = new.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.geometry")
            seat_view(frame(new), geometry, 2).save(args.out / 'chair.png')
            for words in ('the Mayflower', 'please draw the Mayflower ship', 'the Mayflower sailing ship', 'a pilgrim ship'):
                suggest(new, words + ' for Lek')
                caption(new, 'Lek · Mayflower sailing ship')
                assert drawing_files(new, '#downloads') == linked
            new.locator('#target').select_option('2')
            shelf = new.locator('#thanksgivingDrawings')
            shelf.locator('summary').click()
            expect(shelf.get_by_role('button')).to_have_count(23)
            shelf.get_by_role('button', name='Preview Mayflower sailing ship', exact=True).click()
            assert drawing_files(new, '#downloads') == linked
            new.locator('#guestZoom').click()
            new.locator('.bowl').scroll_into_view_if_needed()
            new.screenshot(path=args.out / 'phone.png')
            suggest(new, 'the Mayflower beside a maple leaf for Lek')
            caption(new, 'Mayflower sailing ship beside maple leaf')
            assert drawing_files(new, '#downloads') != linked
            for detail in ('a Mayflower ship with a painted red hull', 'the Mayflower flying a rainbow flag'):
                new.locator('#idea').fill(detail + ' for Lek')
                new.get_by_role('button', name='Preview suggestion').click()
                expect(new.locator('#keep')).to_be_hidden()
                expect(new.locator('#suggestionPhoto')).to_be_visible()
        database = Path(tmp) / 'room.db'
        with room(args.previous, database) as url, browser.new_page(**MOBILE) as original:
            open_room(original, url)
            suggest(original, 'a phage for Thomas, an open book for Alex')
            opening, revision = save(original, url+API)
        with room(args.gallery, database) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as friend:
            for page in (host, friend):
                open_room(page, url)
                caption(page, 'Alex · Open book')
            before = host.request.get(url+API).json()
            assert before['state'] == opening['state']
            suggest(host, 'the Mayflower for Lek')
            caption(host, 'Lek · Mayflower sailing ship')
            actual = drawing_files(host, '#downloads')
            assert actual == linked
            assert friend.request.get(url+API).json() == before
            measurements = measure(host, 'mayflower_ship', 2, actual)
            radius = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.radiusMM")
            positions = check_ring_scene.sample_walk(from_files(actual, (-math.pi/2, 1)), .00012)
            tree = cKDTree(positions)
            clearance = [min(tree.query(contour_samples(contour(opening['state'], slot, geometry), .00045))[0])*radius
                         for slot in (0, 1)]
            assert min(clearance) > measurements['groove_mm']
            measurements['nearest_other_engraving_mm'] = round(float(min(clearance)), 2)
            (args.out / actual[0][0]).write_bytes(actual[0][1])
            kept, new_revision = save(host, url+API)
            assert new_revision == revision+1
            assert kept['state']['ids'] == [*opening['state']['ids'][:2], 'mayflower_ship']
            caption(friend, 'Lek · Mayflower sailing ship')
            assert drawing_files(friend, '#roomFiles') == actual
            friend.goto('about:blank')
            open_room(friend, url)
            caption(friend, 'Lek · Mayflower sailing ship')
            assert drawing_files(friend, '#roomFiles') == actual
            assert friend.request.get(url+API).json()['state'] == kept['state']
        measurements['editor_sha256'] = hashlib.sha256(args.gallery.read_bytes()).hexdigest()
        (args.out / 'verified.json').write_text(json.dumps(measurements, indent=2) + '\n')
        print(json.dumps(measurements, indent=2))


if __name__ == '__main__':
    main()
