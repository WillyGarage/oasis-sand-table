#!/usr/bin/env python3
"""Check real local photographs from the guest page through to its downloaded sand routes.

    python3 tools/test_ring_photo.py captures/ring-scene/oasis-ring-garden.html \
        captures/photo2sand_test/chari.jpg captures/guest-photo/nasa-three.jpg

Supply a single portrait and a group with at least two detectable faces.
Add `--layout portrait` to test the wide center in a combined gallery.
"""
import argparse
import base64
import io
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageFilter
from playwright.sync_api import sync_playwright

import check_ring_scene as check
from thrcommon import to_xy


def frame(page):
    data = page.locator('#sand').evaluate("async im=>{await im.decode(); return im.src.split(',')[1]}")
    return np.array(Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB'))


def sample_by_length(xy, fractions):
    """Walk the complete polyline in drawing order, including repeated parts."""
    distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    keep = np.r_[True, np.diff(distance) > 0]
    distance, xy = distance[keep], xy[keep]
    return np.column_stack([np.interp(fractions * distance[-1], distance, column) for column in xy.T])


def outward_pitch(clear):
    """Largest radial advance in any full turn after leaving the centre."""
    points = np.asarray(clear)
    radial = points[:, 1]
    center = np.flatnonzero(radial <= 1e-9)[-1]
    assert check.seam_segments(points[:center + 1], points[0, 0]).all()
    assert np.diff(radial[:center + 1]).max(initial=0) < check.TOL
    assert np.diff(radial[center:]).min(initial=0) > -check.TOL
    angular_steps = np.diff(points[center:, 0])
    assert angular_steps.min() >= -check.TOL or angular_steps.max() <= check.TOL
    angle = np.r_[0, np.cumsum(abs(angular_steps))]
    valid = angle + math.tau <= angle[-1]
    assert valid.any()
    return float((np.interp(angle[valid] + math.tau, angle, radial[center:]) - radial[center:][valid]).max())


def ordinary_erase_pitch(clear):
    points = np.asarray(clear)
    # Large flowers start toward the center. The earlier clear and the Mini
    # start by tracing the perimeter, then spiral inward.
    inward_spoke = check.seam_segments(points, points[0, 0])[0]
    return outward_pitch(points if inward_spoke else points[::-1])


def check_portrait(source, segments, downloaded, groove, ordinary_pitch, fine):
    transit, clear, art, leave = [np.asarray(part, float) for part in segments]
    gate, high = transit[-1]
    dock = transit[0]
    rebuilt = check.joined(segments, dock, dock, 'photo')
    assert check.same_track(downloaded, rebuilt), 'Saved movement differs from the photo preview'
    assert np.array_equal(transit, leave[::-1])
    assert clear[:, 1].min() == 0 and clear[:, 1].max() <= high + check.TOL
    pitch = outward_pitch(clear)
    assert pitch < ordinary_pitch - check.TOL if fine else abs(pitch - ordinary_pitch) < check.TOL
    assert np.all((art[:, 1] >= 0) & (art[:, 1] <= high + check.TOL))
    protected = downloaded[:, 1] > high + check.TOL
    assert check.seam_segments(downloaded, gate)[protected[:-1] | protected[1:]].all()

    # Find the converter's rim entry in the actual art. All other added
    # travel must remain on the boundary or go straight back along the stem.
    target = high * np.asarray(source)
    xy = np.column_stack(to_xy(art))
    entry = np.flatnonzero(np.linalg.norm(xy - target[0], axis=1) < 1e-7)
    assert entry.size >= 2
    i, j = entry[0], entry[-1]
    np.testing.assert_allclose(art[:i + 1, 1], high, atol=1e-7, rtol=0)
    np.testing.assert_allclose(art[j:, 1], high, atol=1e-7, rtol=0)
    np.testing.assert_allclose(xy[:i + 1], xy[j:][::-1], atol=1e-7, rtol=0)

    # Sample between waypoints as the table moves. A jump across a cheek or
    # the group on the way out would diverge from the ordered source walk,
    # even when all original face vertices still occurred somewhere before it.
    samples = [art[i]]
    for a, b in zip(art[i:j], art[i + 1:j + 1]):
        n = max(1, math.ceil(abs(b[0] - a[0]) / .02), math.ceil(abs(b[1] - a[1]) / .002))
        samples.extend(np.linspace(a, b, n + 1)[1:])
    trace = np.column_stack(to_xy(samples))
    fractions = np.linspace(0, 1, 20001)
    error = np.linalg.norm(sample_by_length(target, fractions) - sample_by_length(trace, fractions), axis=1)
    assert error.max() < groove / 8, 'Ordered portrait deviates by more than one eighth of a groove'
    return float(error.max())


def exercise(page_path, single, group, folder, layout):
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            url = page_path.resolve().as_uri() + ('?layout=' + layout if layout else '')
            page.goto(url + '#photos')
            groove = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.groove")
            keys = page.evaluate("Object.keys(JSON.parse(document.querySelector('#scene').textContent).zones)")
            assert set(keys) in ({'center', 'outer'}, {'center', 'middle', 'outer'})
            selector = page.locator('#layout')
            if layout == 'portrait':
                assert set(keys) == {'center', 'outer'}
                if selector.count():
                    assert selector.input_value() == layout
            rings = [key for key in ('outer', 'middle') if key in keys]
            visible = page.locator('input[name=zone] + span:visible')
            offered = visible.evaluate_all("labels => labels.map(item => item.previousElementSibling.value)")
            assert set(offered) == set(keys), f'Offered {offered}, expected {keys}'
            original = frame(page)
            n = len(original)
            y, x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
            r = np.hypot(x, y)
            mini_blossom = page.evaluate("""() => {
                const scene = JSON.parse(document.querySelector('#scene').textContent);
                return scene.live.radiusMM === 114 && scene.zones.center.names[0] === 'Anemone';
            }""")
            if mini_blossom:
                # Camera comparison on 2026-11-20: the fine rake between petals
                # spans ~7 grey levels, the flower including its bed spans ~24.
                # The single-sidelight renderer gave ~42 and ~72 respectively.
                grey = Image.fromarray(original).convert('L')
                width = groove * n / 2
                relief = (np.asarray(grey.filter(ImageFilter.GaussianBlur(.10 * width)), dtype=np.int16)
                          - np.asarray(grey.filter(ImageFilter.GaussianBlur(.55 * width)), dtype=np.int16))
                between_petals = (r > .44) & (r < .60) & (np.cos(6 * np.arctan2(y, x)) > .72)
                flower = (r > .20) & (r < .60)
                assert np.ptp(np.percentile(relief[between_petals], [10, 90])) < 16, 'Rake dominates the flower'
                assert 15 < np.ptp(np.percentile(relief[flower], [10, 90])) < 43, 'Wrong Mini flower contrast'
            photo_form = page.locator('#centerPhoto')
            summary = []

            def choose(grouping, item):
                page.locator(f'input[name={grouping}][value={item}] + span').click()

            zone = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).zones.center")
            ordinary_pitch = ordinary_erase_pitch(zone['erase'])
            fine = bool(zone.get('photoErase'))
            plan = """points => OasisRingPlanner.photo(
                JSON.parse(document.querySelector('#scene').textContent).zones.center, points).segments"""
            for mode, source_file in [('one', single), ('group', group)]:
                choose('zone', 'center')
                if not photo_form.evaluate('d=>d.open'):
                    photo_form.locator(':scope > summary').click()
                before = frame(page)
                file = page.locator('#portraitFile')
                file.set_input_files(source_file)
                page.locator('#portraitMode').select_option(mode)
                page.locator('#portraitStyle' if mode=='group' else '#soloStyle').select_option('pose' if mode=='group' else 'line')
                page.locator('#portraitSubmit').click()
                page.wait_for_function("document.querySelector('input[name=stage]:checked').value === 'redrawn'")
                source = file.evaluate('(f,options)=>GuestPhoto.fromFile(f.files[0], options)',
                                       {'group': mode == 'group', 'portraitDiameterGrooves': 2 * zone['transit'][-1][1] / groove})
                faces = source['facesDetected']
                assert faces == 1 if mode == 'one' else faces >= 2
                segments = page.evaluate(plan, source['points'])
                high = segments[0][-1][1]
                centre = r < high - groove
                neighbors = (r > high + 3 * groove) & (r < .99) & ((y < 0) | (abs(x) > 3 * groove))
                after = frame(page)
                assert np.array_equal(before[neighbors], after[neighbors]), 'Guest rings changed during the photo'
                assert np.abs(before[centre].astype(float) - after[centre]).mean() > 1
                page.locator('#downloads summary').click()
                links = page.locator('#downloads a')
                links.first.wait_for()
                files = []
                sizes = []
                for link in links.all():
                    with page.expect_download() as wait:
                        link.click()
                    saved = wait.value
                    assert saved.suggested_filename.startswith('center-portrait-')
                    name = mode + '-' + saved.suggested_filename
                    saved.save_as(folder / name)
                    sizes.append((folder / name).stat().st_size)
                    files.append(check.read_path(folder, name))
                dock = segments[0][0]
                route = check.joined(files, dock, dock, mode)
                deviation = check_portrait(source['points'], segments, route, groove, ordinary_pitch, fine)
                page.locator('#keep').click()
                for ring in rings:
                    choose('zone', ring)
                    previous = frame(page)
                    choose('stage', 'redrawn')
                    changed = frame(page)
                    assert np.array_equal(changed[centre], after[centre]), f'{ring} redraw altered the portrait'
                    assert np.any(changed[neighbors] != previous[neighbors]), f'{ring} was never redrawn'
                    page.locator('#keep').click()
                    assert np.array_equal(frame(page)[centre], after[centre])
                # Persistence quantizes sand height to a byte, which can shift
                # rendered brightness slightly but never the position of a stroke.
                saved = frame(page)
                page.reload()
                error = abs(frame(page).astype(np.int16) - saved.astype(np.int16))
                assert error[centre].mean() < 1 and np.percentile(error[centre], 99.9) < 5
                assert page.locator('#reset').is_visible()
                assert 'portrait' in page.locator('.caption').inner_text().lower()
                summary.append(f'{faces} face(s), {len(route)} points in {len(files)} file(s) '
                               f'({sum(sizes)} bytes), '
                               f'{deviation/groove:.3f} groove maximum ordered-trace error')

            # Opening an embedded example previews a candidate. Returning to
            # the garden without keeping it must restore the family's saved art.
            examples = [mode for mode, button in [('one', '#sampleOne'), ('group', '#sampleGroup')]
                        if page.locator(button).is_visible()]
            kept = frame(page)
            for example in examples:
                anchor = '#example-group' if example == 'group' else '#example-portrait'
                candidate = page.context.new_page()
                candidate.goto(url + anchor)
                candidate.wait_for_function("document.querySelector('input[name=stage]:checked').value === 'redrawn'")
                assert candidate.locator('#portraitMode').input_value() == example
                assert candidate.locator('#downloads').is_visible()
                assert np.array_equal(frame(candidate)[neighbors], kept[neighbors])
                candidate.close()
            page.reload()
            assert np.array_equal(frame(page), kept)
            if selector.count() and selector.locator('option').count() == 2:
                initial = selector.input_value()
                values = selector.locator('option').evaluate_all('items => items.map(item => item.value)')
                other = next(value for value in values if value != initial)
                def switch(value):
                    selector.select_option(value)
                    page.wait_for_function("""n => Object.keys(
                        JSON.parse(document.querySelector('#scene').textContent).zones).length === n""",
                                           arg=2 if value == 'portrait' else 3)
                switch(other)
                assert page.locator('#reset').is_hidden()
                choose('zone', 'outer')
                choose('stage', 'redrawn')
                page.locator('#keep').click()
                other_bed = frame(page)
                switch(initial)
                assert np.array_equal(frame(page), kept), 'Keeping another layout replaced this portrait'
                switch(other)
                error = abs(frame(page).astype(np.int16) - other_bed.astype(np.int16))
                assert error.mean() < 1 and np.percentile(error, 99.9) < 5
                page.locator('#reset').click()
                switch(initial)
                assert np.array_equal(frame(page), kept), 'Resetting another layout erased this portrait'
            page.locator('#reset').click()
            assert np.array_equal(frame(page), original)
            # A diameter whose centre falls away from its midpoint used to
            # be an easy way for two polar waypoints to introduce a curved scar.
            diameter = [[1.,0.], [.82,0.], [-.29,0.], [-.42,-.18], [.16,.43], [.76,.19], [1.,0.]]
            segments = page.evaluate(plan, diameter)
            route = check.joined(segments, dock, dock, 'off-midpoint diameter')
            check_portrait(diameter, segments, route, groove, ordinary_pitch, fine)
            angle, radius = np.asarray(segments[2]).T
            at_center = (radius[1:] < 1e-9) & (radius[:-1] < 1e-9)
            assert np.isclose(np.sum(abs(np.diff(angle))[at_center]), math.pi)
            assert not errors, errors
            print(f'{len(keys)} zones. Single and group centers held through {", ".join(rings)} edits and reload. '
                  + ' / '.join(summary))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path)
    parser.add_argument('single', type=Path)
    parser.add_argument('group', type=Path)
    parser.add_argument('--layout', choices=['portrait'], help='open the wide center in the combined gallery')
    args = parser.parse_args()
    for file in (args.page, args.single, args.group):
        if not file.is_file():
            parser.error(f'File does not exist: {file}')
    with tempfile.TemporaryDirectory() as temporary:
        exercise(args.page, args.single, args.group, Path(temporary), args.layout)
