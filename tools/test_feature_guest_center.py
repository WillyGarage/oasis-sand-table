#!/usr/bin/env python3
"""Feature live guest drawings in the center on two phones sharing the local 36-inch simulator."""
import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_place import contour, contour_samples
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_photo import frame
from thrcommon import unpack_path
from wide_portrait import chromium


START = 'a phage for Thomas, an open book for Alex, a Thai rooftop for Lek'


def verify_download(files, scene, state, slot):
    live, center = scene['live'], scene['zones']['center']
    radius, groove = live['radiusMM'], live['groove']
    dock, high = center['transit'][0], center['transit'][-1][1]
    route = from_files(files, dock)
    check.safe_route(route, dock[0], 0, high, dock, high, 'featured guest')
    assert abs(np.diff(route[:, 0])).max() < math.pi
    # Isolate the engraving after the physical center erase and before returning home.
    clear = unpack_path(center['photoErase']) if 'photoErase' in center else np.asarray(center['erase'])[::-1]
    transit = np.asarray(center['transit'])
    assert check.same_track(route[:len(transit)], transit)
    first = len(transit)-1
    assert check.same_track(route[first:first+len(clear)], clear)
    assert check.same_track(route[-len(transit):], transit[::-1])
    art = route[first+len(clear)-1:1-len(transit)]
    geometry = live['planner']['geometry']
    origin = geometry['center']*np.array([math.cos(geometry['angles'][slot]), math.sin(geometry['angles'][slot])])
    original = contour(state, slot, geometry)-origin
    size_ratio = (high-2*groove)/np.linalg.norm(original, axis=1).max()
    desired = original*size_ratio
    extent = np.linalg.norm(desired, axis=1).max()
    inside = np.flatnonzero(art[:, 1] <= extent+check.TOL)
    start, end = inside[0], inside[-1]
    assert end > start and check.same_track(art[:start+1], art[end:][::-1])
    # Compare the uploaded engraving with the actual signed movement, sampled between
    # each pair of waypoints. A transit through the subject would fail the reverse check.
    actual = check.sample_walk(art[start:end+1], .00015)
    wanted = contour_samples(desired, .00015)
    discrepancy = max(cKDTree(wanted).query(actual)[0].max(), cKDTree(actual).query(wanted)[0].max())*radius
    assert discrepancy < .2, discrepancy
    return {'drawing': state['ids'][slot], 'enlargement': round(float(size_ratio), 2),
            'travel_m': round(check.travel(route)[-1]*radius/1000, 3),
            'max_outline_error_mm': round(float(discrepancy), 3),
            'signed_rows': len(route), 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files}}


def protected_frames(before, cleared, redrawn, scene):
    n = len(before)
    y, x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
    radius = np.hypot(x, y)
    groove = scene['live']['groove']
    high = scene['zones']['center']['transit'][-1][1]
    access = (abs(x) < 2*groove) & (y > 0)
    for lo, hi in ((high+2*groove, .75), (.76, .99)):
        mask = (lo < radius) & (radius < hi) & ~access
        for stage in (cleared, redrawn):
            assert np.array_equal(before[mask], stage[mask]), 'Other artwork changed.'
    inner = radius < high-groove
    for a,b in ((before, cleared), (cleared, redrawn)):
        assert np.abs(a[inner].astype(float)-b[inner]).mean() > 1


def feature(page, scene, state, slot):
    choose(page, 'zone', 'center')
    before = frame(page)
    picker = page.get_by_label('Feature a guest drawing in the center')
    picker.select_option(str(slot))
    caption(page, 'in the center.')
    files = drawing_files(page, '#downloads')
    assert all(name.startswith('center-guest-') for name, _ in files)
    redrawn = frame(page)
    choose(page, 'stage', 'cleared')
    cleared = frame(page)
    protected_frames(before, cleared, redrawn, scene)
    choose(page, 'stage', 'redrawn')
    return files, verify_download(files, scene, state, slot), (before, cleared, redrawn)

def feature_request(host, friend, url, opening, scene, out):
    """Enlarge a suggestion before keeping it, then compare it to the same saved ring drawing."""
    button = host.get_by_role('button', name='Preview larger in the center')
    choose(host, 'zone', 'middle')
    before = frame(host)
    host.locator('#target').select_option('2')
    suggest(host, 'a hand-cranked coffee grinder')
    caption(host, 'Lek · Hand-cranked coffee grinder')
    guest_files = drawing_files(host, '#downloads')
    host.screenshot(path=out/'guest-request.png')
    button.click()
    caption(host, 'Lek · Hand-cranked coffee grinder in the center.')
    expect(host.locator('#featureGuest')).to_have_value('')  # The ring still holds Lek's roof.
    expect(host.locator('#featureGuest option:checked')).to_have_text('Lek · Hand-cranked coffee grinder (suggestion)')
    center_files = drawing_files(host, '#downloads')
    redrawn = frame(host)
    choose(host, 'stage', 'cleared')
    protected_frames(before, frame(host), redrawn, scene)
    choose(host, 'stage', 'redrawn')
    host.evaluate('scrollTo(0,0)')
    host.screenshot(path=out/'center-request.png')
    assert host.request.get(url+API).json()['state'] == opening
    featured, _ = save(host, url+API)
    for key in ('ids','guestBook','outer','labels','custom'):
        assert featured['state'].get(key) == opening.get(key)
    friend.reload()
    caption(friend, 'Lek · Hand-cranked coffee grinder')
    assert drawing_files(friend, '#roomFiles') == center_files

    choose(friend, 'zone', 'middle')
    suggest(friend, 'a hand-cranked coffee grinder for Lek')
    assert drawing_files(friend, '#downloads') == guest_files
    # Starting to type a different request removes the previous picture's center action.
    friend.locator('#idea').fill('a roof')
    expect(friend.locator('#featureRequest')).to_be_hidden()
    suggest(friend, 'a hand-cranked coffee grinder for Lek')
    kept, revision = save(friend, url+API)
    assert kept['state']['ids'][2] == 'coffee_grinder' and kept['state']['ids'][:2] == opening['ids'][:2]
    expect(host.locator('#featureGuest option[value="2"]')).to_have_text(
        'Lek · Hand-cranked coffee grinder', timeout=10000)
    friend.locator('#featureRequest').click()
    caption(friend, 'Lek · Hand-cranked coffee grinder in the center.')
    expect(friend.locator('#featureGuest')).to_have_value('2')
    assert drawing_files(friend, '#downloads') == center_files
    assert friend.request.get(url+API).json()['revision'] == revision
    choose(friend, 'zone', 'middle')
    suggest(friend, 'a pumpkin for Alex and a turkey for Lek')
    expect(friend.locator('#featureRequest')).to_be_hidden()
    # A guest's newly composed drawing also has an exact outline before it exists in a seat.
    suggest(friend, 'a heart with AL inside for Alex')
    friend.locator('#featureRequest').click()
    caption(friend, 'Alex · Heart with AL in the center.')
    custom_files = drawing_files(friend, '#downloads')
    custom_center, _ = save(friend, url+API)
    assert custom_center['state']['ids'] == kept['state']['ids'] and custom_files != center_files
    choose(friend, 'zone', 'middle')
    suggest(friend, 'a heart with AL inside for Alex')
    custom_ring, _ = save(friend, url+API)
    assert custom_ring['state']['ids'][1] in custom_ring['state']['custom']
    friend.locator('#featureRequest').click()
    assert drawing_files(friend, '#downloads') == custom_files
    verify_download(custom_files, scene, custom_ring['state'], 1)
    return verify_download(center_files, scene, kept['state'], 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('gallery', 'previous', 'out'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        # All three conventional zone controls still export the previous bytes.
        with browser.new_page(**MOBILE, offline=True) as old, browser.new_page(**MOBILE, offline=True) as new:
            def conventional(page, gallery):
                page.goto(gallery.resolve().as_uri())
                choose(page, 'stage', 'redrawn')
                files = [drawing_files(page, '#downloads')]
                choose(page, 'zone', 'outer')
                choose(page, 'stage', 'redrawn')
                files.append(drawing_files(page, '#downloads'))
                choose(page, 'zone', 'middle')
                suggest(page, START)
                files.append(drawing_files(page, '#downloads'))
                return files
            assert conventional(old, args.previous) == conventional(new, args.gallery)
            choose(new, 'zone', 'center')
            expect(new.locator('#featureGuest')).to_be_hidden()
            new.locator('#layout').select_option('portrait')
            expect(new.locator('#featureGuest')).to_be_hidden()
        db = Path(tmp)/'room.db'
        with room(args.previous, db) as url, browser.new_page(**MOBILE) as old:
            open_room(old, url)
            suggest(old, START)
            previous_state, revision = save(old, url+API)
        with room(args.gallery, db) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as friend:
            for p in (host, friend):
                p.on('pageerror', lambda e: errors.append(str(e)))
                open_room(p, url, '')
            opening = previous_state['state']
            assert host.request.get(url+API).json()['state'] == opening
            scene = host.evaluate("JSON.parse(document.querySelector('#scene').textContent)")
            for slot in (1, 2, 0):
                files, measurement, stages = feature(host, scene, opening, slot)
                results.append(measurement)
            assert friend.request.get(url+API).json()['revision'] == revision
            # Switching to photos, or clearing the selection, abandons the feature preview.
            host.locator('#centerPhoto > summary').click()
            expect(host.locator('#keep')).to_be_hidden()
            host.locator('#centerPhoto > summary').click()
            expect(host.locator('#featureGuest')).to_have_value('')
            host.locator('#featureGuest').select_option('0')
            host.locator('#featureGuest').select_option('')
            expect(host.locator('#keep')).to_be_hidden()
            host.locator('#featureGuest').select_option('0')
            assert drawing_files(host, '#downloads') == files
            host.evaluate('scrollTo(0,0)')
            host.screenshot(path=args.out/'phone.png')
            for stage, image in zip(('before','cleared','featured'), stages):
                Image.fromarray(image).save(args.out/(stage+'.png'))
            for name, data in files:
                (args.out/name).write_bytes(data)
            kept, next_revision = save(host, url+API)
            assert next_revision == revision+1
            for key in ('ids','guestBook','outer','custom','labels'):
                assert kept['state'].get(key) == opening.get(key)
            caption(friend, 'Thomas · Faceted bacteriophage')
            assert drawing_files(friend, '#roomFiles') == files
            # Changing the original ring drawing leaves its featured copy in the center.
            center_before = frame(friend)
            choose(friend, 'zone', 'middle')
            suggest(friend, 'a telescope for Thomas and a guitar for Alex')
            center_after = frame(friend)
            n=len(center_before)
            y,x=np.mgrid[-1:1:complex(n), -1:1:complex(n)]
            protected = np.hypot(x,y) < scene['zones']['center']['transit'][-1][1]-scene['live']['groove']
            assert np.array_equal(center_before[protected], center_after[protected])
            new_state, revised = save(friend, url+API)
            assert revised == next_revision+1 and new_state['state']['portrait'] == kept['state']['portrait']
            # Reopening the garden gives guests the new subject and its correct orientation.
            host.goto('about:blank')
            open_room(host, url, '')
            guitar_files, measurement, _ = feature(host, scene, new_state['state'], 1)
            assert guitar_files != files
            results.append(measurement)
            choose(host, 'zone', 'middle')
            suggest(host, 'a heart with BL inside for Thomas')
            new_state, _ = save(host, url+API)
            choose(host, 'zone', 'center')
            expect(host.locator('#featureGuest option:has-text("Heart with BL")')).to_have_count(1)
            custom_files, measurement, _ = feature(host, scene, new_state['state'], 0)
            assert new_state['state']['ids'][0] in new_state['state']['custom'] and custom_files != files
            results.append(measurement)
            save(host, url+API)
            friend.goto('about:blank')
            open_room(friend, url, '')
            caption(friend, 'Thomas · Heart with BL')
            assert drawing_files(friend, '#roomFiles') == custom_files
        with room(args.gallery, Path(tmp)/'request.db') as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as friend:
            for page in (host, friend):
                page.on('pageerror', lambda e: errors.append(str(e)))
                open_room(page, url, '')
            choose(host, 'zone', 'middle')
            suggest(host, START)
            kept, _ = save(host, url+API)
            scene = host.evaluate("JSON.parse(document.querySelector('#scene').textContent)")
            results.append(feature_request(host, friend, url, kept['state'], scene, args.out))
        assert not errors, errors
    evidence = {'editor_sha256': hashlib.sha256(args.gallery.read_bytes()).hexdigest(), 'changes':results}
    (args.out/'verified.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
