#!/usr/bin/env python3
"""Verify a guest's border from the real two-phone editor to its signed motion files.

Pass the combined gallery, its two generated scene manifests (--scenes GARDEN WIDE),
a local portrait (--photo) and the Mini gallery (--mini). The room has no physical controller.
"""

import argparse
import base64
import io
import json
import math
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

import check_ring_scene as check
from test_garden_room import caption, choose, drawing_files, room, suggest
from test_ring_photo import frame

MOBILE = dict(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
NAMES = ['Wheat garland', 'Crossing tides', 'Thai roof peaks', 'Lotus buds', 'Autumn leaves']


def open_garden(page, url, layout):
    page.goto('about:blank')
    api = '/api/garden/' + layout
    with page.expect_response(lambda r: urlsplit(r.url).path == api and r.request.method == 'GET') as opened:
        page.goto(url + '/garden?layout=' + layout + '#photos')
    assert opened.value.status == 200
    expect(page.locator('.controls')).not_to_have_attribute('inert', '')
    choose(page, 'zone', 'outer')


def preview(page, index, guest=None, order=None):
    page.locator('#borderDesign').select_option(str(index))
    if guest is not None:
        page.locator('#borderGuest').fill(guest)
    if order is not None:
        page.locator('#borderOrder').select_option(order)
    page.locator('#borderPreview').click()
    expect(page.locator('#keep')).to_be_visible()


def save(page, api):
    with page.expect_response(lambda r: r.url == api and r.request.method == 'PUT') as put:
        page.locator('#keep').click()
    response = put.value
    assert response.status == 200, response.text()
    expect(page.locator('#keep')).to_be_hidden()
    return response.request.post_data_json, response.json()['revision']


def from_files(files, start):
    pieces = [np.loadtxt(io.BytesIO(data)) for _, data in files]
    for left, right in zip(pieces, pieces[1:]):
        np.testing.assert_array_equal(left[-1], right[0])
    return check.joined(pieces, start, start, 'guest border')


def angular_sections(art, count, low, high):
    """Inspect the engraving alone, in the tangent/inward-depth frame of each sector."""
    angle = (art[:, 0] + math.pi / 2) % math.tau
    depth = (high - art[:, 1]) / (high - low)
    # Count each repeating ornament from its tallest point, apart from the access stem.
    peaks = np.sort(angle[(depth > 0.87) & (angle > 0.04) & (angle < math.tau - 0.04)])
    clusters = np.split(peaks, np.flatnonzero(np.diff(peaks) > 0.09) + 1)
    assert len(clusters) == count, ('wrong number of independent peaks', len(clusters), count)
    centers = np.arange(count) * math.tau / count + math.pi / count
    offsets = np.array([np.mean(c) for c in clusters]) - centers
    assert np.max(np.abs(offsets)) < 0.13 * math.tau / count
    for center in centers:
        x = np.angle(np.exp(1j * (angle - center))) * count / math.pi

        def heights(at):
            a, b = x[:-1], x[1:]
            crossed = (
                (np.minimum(a, b) <= at) & (at <= np.maximum(a, b)) & (abs(b - a) < 0.4) & (abs(b - a) > 1e-7)
            )
            f = (at - a[crossed]) / (b[crossed] - a[crossed])
            return depth[:-1][crossed] + f * (depth[1:][crossed] - depth[:-1][crossed])

        def band(a, b):
            return depth[(x >= a) & (x <= b)]

        yield heights, band


def ornament(art, index, low, high, radius_mm):
    if index == 4:
        from scipy.spatial import cKDTree

        depth = (high - art[:, 1]) / (high - low)
        angle = (art[:, 0] + math.pi / 2) % math.tau
        points = np.round(art, 5)
        sector = math.tau / 10
        foliage = []
        spans = []
        for i in range(10):
            x = (angle - (i + .5) * sector) * 2 / sector
            interior = abs(x) < .995
            leaf = interior & (depth > .35)
            # The twig connects at the sides and the body grows toward the center.
            edge = interior & (abs(x) > .94)
            assert edge.any() and depth[edge].max() < .4
            assert leaf.any() and depth[leaf].max() > .7 and np.ptp(x[leaf]) > .3
            # Independently detect veins from repeated edges back along the actual engraving.
            veins = set()
            retraced = 0
            for j in np.flatnonzero(leaf[:-1] & leaf[1:]):
                a, b = tuple(points[j]), tuple(points[j+1])
                if a != b:
                    retraced += (b, a) in veins
                    veins.add((a, b))
            assert retraced > 4, ('Leaf has no returning vein', i)
            spans.append(depth[leaf].max() - np.median(depth[edge]))
            foliage.append(np.column_stack((x[leaf], depth[leaf])))
        # Each neighboring pair should contain visibly different contours, including the last and first.
        differences = []
        for i, left in enumerate(foliage):
            right = foliage[(i+1) % len(foliage)]
            distances = np.r_[cKDTree(left).query(right)[0], cKDTree(right).query(left)[0]]
            differences.append(float(np.percentile(distances, 90)))
        assert min(differences) > .018, ('Two adjacent leaves share an engraving', differences)
        return {'leaves': 10, 'shortest_leaf_reach_mm': round(min(spans) * (high - low) * radius_mm, 1)}
    if index == 2:
        panel_heights, ridge_gaps, lower_tips, upper_tips = [], [], [], []
        for heights, band in angular_sections(art, 10, low, high):
            axial = heights(0.002)
            lower = axial[(axial > 0.025) & (axial < 0.3)]
            upper = axial[(axial > 0.32) & (axial < 0.75)]
            assert len(lower) and len(upper) and max(band(-0.11, 0.11)) > 0.9, (
                'missing roof tier or finial',
                axial,
            )
            panel_heights.append(min(upper) - max(lower))
            ridge = axial[(axial > 0.75) & (axial < 0.84)]
            assert len(ridge)
            ridge_gaps.append(min(ridge) - max(upper))
            for sign in (-1, 1):

                def side(a, b):
                    return band(*sorted((sign * a, sign * b)))

                lower_tips.append(max(side(0.70, 0.78)) - min(side(0.57, 0.65)))
                shoulder = side(0.29, 0.35)
                upper_tips.append(max(side(0.42, 0.49)) - min(shoulder[shoulder > 0.28]))
        assert (
            min(panel_heights) > 0.08
            and min(ridge_gaps) > 0.08
            and min(lower_tips) > 0.08
            and min(upper_tips) > 0.06
        )
        return {
            'roofs': 10,
            'gable_panel_height_mm': round(min(panel_heights) * (high - low) * radius_mm, 1),
            'roof_above_panel_mm': round(min(ridge_gaps) * (high - low) * radius_mm, 1),
            'lower_eave_rise_mm': round(min(lower_tips) * (high - low) * radius_mm, 1),
            'upper_eave_rise_mm': round(min(upper_tips) * (high - low) * radius_mm, 1),
        }
    gaps = []
    for _, band in angular_sections(art, 11, low, high):
        crown = max(band(-0.09, 0.09))
        for s in (-1, 1):
            tip = max(band(*sorted((s * 0.35, s * 0.42))))
            between = band(*sorted((s * 0.16, s * 0.22)))
            shoulder = min(between[between > 0.42])
            assert crown - tip > 0.14
            gaps.append(tip - shoulder)
    assert min(gaps) > 0.07
    return {
        'buds': 11,
        'petals_per_bud': 3,
        'side_petal_rise_mm': round(min(gaps) * (high - low) * radius_mm, 1),
    }


def replay(page, encoded, route, *rest):
    raster = page.evaluate(
        """([raw,parts])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent).live;
      const bed=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1),sim=new RingSand(s.size,s.groove,s.profile);
      for(const part of parts) sim.carve(bed,part); return sim.image(bed).split(',')[1];
    }""",
        [encoded, [part.tolist() for part in (route, *rest)]],
    )
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(raster))).convert('RGB'))


def actual(page, manifest, folder, index, old, encoded, scene_file):
    z = manifest['zones']['outer']
    dock = manifest['dock']
    files = drawing_files(page, '#downloads')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files:
        assert Path(name).name == name
        (folder / name).write_bytes(data)
    route = from_files(files, dock)
    wanted = z['variants'][index]
    python_parts = [check.read_path(scene_file.parent, name) for name in wanted['replace']]
    reference = check.joined(python_parts, dock, dock, 'generator border')
    assert check.same_track(reference, route)
    # Browser rounds the 7-decimal gallery paths to 5-decimal table files.
    np.testing.assert_allclose(route, reference, rtol=0, atol=1.01e-5)
    expect = check.joined(
        [z['transit'], z['erase'], wanted['path'], z['transit'][::-1]], dock, dock, 'intended border'
    )
    np.testing.assert_allclose(route, expect, rtol=0, atol=5.2e-6)
    lo, hi = z['safe_bounds']
    assert min(route[:, 1]) >= lo - check.TOL
    outside = route[:, 1] > hi + check.TOL
    assert check.seam_segments(route, -math.pi / 2)[outside[:-1] | outside[1:]].all()
    end_clear = len(z['transit']) + len(z['erase']) - 1
    art = route[end_clear - 1 : len(route) - len(z['transit']) + 1]
    report = ornament(art, index, lo, hi, manifest['assumed_working_radius_mm'])
    final = frame(page)
    choose(page, 'stage', 'cleared')
    cleared = frame(page)
    choose(page, 'stage', 'redrawn')
    n = len(old)
    y, x = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
    # The guard between usable bands is deliberately blank. The renderer's
    # angled lighting can change part of this guard even when no inner art moves.
    radial = np.hypot(x, y)
    last_inner = max(zone['safe_bounds'][1] for key, zone in manifest['zones'].items() if key != 'outer')
    # The six-o’clock access line intentionally joins both bands. Measure
    # the roof itself against the highest signed lane in the next zone.
    radius = manifest['assumed_working_radius_mm']
    if index == 2 and np.allclose(
        [radius, radius * manifest['groove_width'], radius * manifest['tracking_margin']],
        [420, 7, 3.5], rtol=0, atol=1e-5,
    ):
        away_from_gate = abs(check.wrapped(art[:, 0] + math.pi / 2)) > 1e-4
        gap = (art[away_from_gate, 1].min() - last_inner) * radius
        assert gap > 1.7 * 7 + 2 * 3.5, ('roof finial inside a neighboring cut’s clearance', gap)
        report['inner_tip_clearance_mm'] = round(gap, 2)
    inner = radial <= last_inner
    changed = np.any(old != cleared, axis=-1) | np.any(old != final, axis=-1)
    report['visible_inner_radius_mm'] = round(last_inner * manifest['assumed_working_radius_mm'], 1)
    report['first_changed_radius_mm'] = round(
        float(radial[changed].min() * manifest['assumed_working_radius_mm']), 1
    )
    report['divider_pixels_changed'] = int(np.sum(changed & (radial < z['bounds'][0])))
    assert np.array_equal(old[inner], cleared[inner]) and np.array_equal(old[inner], final[inner]), (
        'Inner sand changed'
    )
    assert np.any(final[~inner] != old[~inner])
    errors = []
    for shown, travel in ((cleared, route[:end_clear]), (final, route)):
        diff = np.abs(replay(page, encoded, travel).astype(np.int16) - shown.astype(np.int16))
        assert diff.mean() < 1.1 and np.percentile(diff, 99) < 5, (
            'display differs from real route',
            diff.mean(),
        )
        errors.append(round(float(diff.mean()), 3))
    for name, image in [('before', old), ('cleared', cleared), ('after', final)]:
        Image.fromarray(image).save(folder / (name + '.jpg'), quality=92)
    report.update(protected_pixels=int(inner.sum()), files=len(files), rows=len(route), replay_error=errors)
    return files, report


def old_relief(page, manifest, index, previous_index, encoded, stages):
    """Repeat the same download on two different beds and isolate the old drawing's contribution."""
    from scipy.spatial import cKDTree

    zone = manifest['zones']['outer']
    groove = manifest['groove_width']
    old = check.sample_walk(zone['variants'][previous_index]['path'], groove * 0.10)
    new = cKDTree(check.sample_walk(zone['variants'][index]['path'], groove * 0.10))
    sites = old[(new.query(old)[0] > 1.3 * groove) & ((old[:, 1] > 0) | (np.abs(old[:, 0]) > 2 * groove))]
    size = round(math.sqrt(len(base64.b64decode(encoded))))
    uv = np.rint((sites * [1, -1] + 1) * ((size - 1) / 2)).astype(int)
    pixels = np.unique(uv[:, 1] * size + uv[:, 0])
    values = page.evaluate(
        """([raw,erase,stages,pixels,gate,count])=>{
        const s=JSON.parse(document.querySelector('#scene').textContent).live;
        const original=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1);
        const neutral=original.slice(), sim=new RingSand(s.size,s.groove,s.profile);
        sim.carve(neutral,erase);
        const sites=pixels.filter(i=>Math.abs(original[i]-neutral[i])>=.15);
        const firstWedge=sites.filter(i=>{
            const theta=Math.atan2(1-2*Math.floor(i/s.size)/(s.size-1),2*(i%s.size)/(s.size-1)-1);
            return (theta-gate+2*Math.PI)%(2*Math.PI) < 2*Math.PI/count;
        });
        const remaining=parts=>{
            const a=original.slice(),b=neutral.slice();
            for(const path of parts){sim.carve(a,path);sim.carve(b,path);}
            const ratio=group=>group.reduce((sum,i)=>sum+Math.abs(a[i]-b[i]),0) /
              group.reduce((sum,i)=>sum+Math.abs(original[i]-neutral[i]),0);
            return [ratio(sites),ratio(firstWedge)];
        };
        const [first,half,end]=stages.map(remaining);
        return [sites.length,first[0],half[0],end[0],firstWedge.length,first[1]];
    }""",
        [
            encoded,
            zone['erase'],
            [[part.tolist() for part in stage] for stage in stages],
            pixels.tolist(),
            manifest['dock'][0],
            len(zone['variants'][index]['reveal']['finished']),
        ],
    )
    count, early, middle, end, first_sites, first_residual = values
    assert first_sites > 20 and first_residual < 0.01, (
        'old drawing remains inside the completed wedge',
        values,
    )
    assert count > 100 and 0.05 < middle < early < 1 and end < 0.01, (
        'old engraving not progressively replaced',
        values,
    )
    return {
        'old_motif_pixels_sampled': count,
        'old_relief_after_first': round(early, 4),
        'first_wedge_old_pixels': first_sites,
        'first_wedge_old_relief': round(first_residual, 5),
        'old_relief_at_half': round(middle, 4),
        'old_relief_at_end': round(end, 5),
    }


def progressive(page, manifest, scene_file, index, previous_index, encoded, original, folder):
    zone = manifest['zones']['outer']
    variant = zone['variants'][index]
    files = drawing_files(page, '#downloads')
    route = from_files(files, manifest['dock'])
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, data in files:
        assert Path(name).name == name
        (folder / name).write_bytes(data)
    # These are the coordinates used to render the staged progress pictures.
    shown = page.evaluate("""i => {
        const z = JSON.parse(document.querySelector('#scene').textContent).zones.outer;
        return OasisRingPlanner.borderReveal(z, i).segments.flatMap((part, n) => part.slice(n ? 1 : 0));
    }""", index)
    np.testing.assert_array_equal(shown, route)
    exported = check.joined(
        (check.read_path(scene_file.parent, n) for n in variant['reveal']['replace']),
        manifest['dock'],
        manifest['dock'],
        'generated progressive border',
    )
    np.testing.assert_allclose(route, exported, atol=1.01e-5, rtol=0)
    lo, hi = zone['safe_bounds']
    check.safe_route(route, manifest['dock'][0], lo, hi, manifest['dock'], lo, variant['name'])
    report = check.check_reveal(manifest, zone, variant, route)
    first = report['endpoints'][0]
    scale = manifest['assumed_working_radius_mm'] / 1000
    length = check.travel(route)
    regular = check.joined(
        [zone['transit'], zone['erase'], variant['path'], zone['transit'][::-1]],
        manifest['dock'],
        manifest['dock'],
        'whole border first',
    )
    edge = manifest['dock'][0] + math.tau / len(report['endpoints'])
    ordinary_first = (
        len(zone['transit'])
        + len(zone['erase'])
        - 2
        + np.flatnonzero(np.asarray(variant['path'])[:, 0] >= edge - check.TOL)[0]
    )
    report['first_m'] = round(float(length[first] * scale), 2)
    report['ordinary_first_m'] = round(float(check.travel(regular)[ordinary_first] * scale), 2)
    halfway_index = int(np.argmin(abs(length - length[-1] / 2)))
    report['completed_at_half'] = int(np.sum(np.asarray(report.pop('endpoints')) <= halfway_index))
    report['total_m'] = round(float(length[-1] * scale), 2)
    report['ordinary_total_m'] = round(float(check.travel(regular)[-1] * scale), 2)
    report['files'] = len(files)
    report['rows'] = len(route)
    assert report['completed_at_half'] > 0
    assert page.locator('#middleStageLabel').inner_text() == 'Halfway'
    final = frame(page)
    choose(page, 'stage', 'cleared')
    middle = frame(page)
    noun = {2:'roof peaks', 3:'buds', 4:'leaves'}[index]
    caption(page, f"{report['completed_at_half']} of {len(variant['reveal']['finished'])} {noun} complete")
    choose(page, 'stage', 'redrawn')
    # The browser spreads sand in groups of adjacent movements. Recreate its
    # arrival/first-half/second-half/departure calls using the rounded download.
    entry = len(zone['transit']) - 1
    exit_at = len(route) - entry - 1
    first_parts = [route[: entry + 1], route[entry : first + 1]]
    half_parts = [route[: entry + 1], route[entry : halfway_index + 1]]
    all_parts = [*half_parts, route[halfway_index : exit_at + 1], route[exit_at:]]
    inner_limit = max(z['safe_bounds'][1] for key, z in manifest['zones'].items() if key != 'outer')
    n = len(original)
    y, x = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
    protected = np.hypot(x, y) <= inner_limit
    assert np.array_equal(original[protected], middle[protected]) and np.array_equal(
        original[protected], final[protected]
    )
    for display, parts in ((middle, half_parts), (final, all_parts)):
        diff = np.abs(display.astype(np.int16) - replay(page, encoded, *parts).astype(np.int16))
        assert diff.mean() < 1.1 and np.percentile(diff, 99) < 5, (
            'progress preview differs from download',
            diff.mean(),
        )
    report.update(old_relief(page, manifest, index, previous_index, encoded, [first_parts, half_parts, all_parts]))
    for name, im in [('first', replay(page, encoded, *first_parts)), ('half', middle), ('after', final)]:
        Image.fromarray(im).save(folder / (name + '.jpg'), quality=92)
    return files, report


def first_leaf_zoom(page, scene):
    whole = frame(page)
    page.get_by_role('button', name='Enlarge border').click()
    radius = sum(scene['zones']['outer']['safe_bounds']) / 2
    angle = scene['dock'][0] + math.pi / 10
    relative_error = page.locator('#sand').evaluate("""(im,[x,y])=>{
        const img=im.getBoundingClientRect(), bowl=im.closest('.bowl').getBoundingClientRect();
        const shownX=img.x+img.width*(1+x)/2, shownY=img.y+img.height*(1-y)/2;
        return Math.hypot(shownX-bowl.x-bowl.width/2,shownY-bowl.y-bowl.height/2)/bowl.width;
    }""", [radius * math.cos(angle), radius * math.sin(angle)])
    assert relative_error < .01, ('zoom missed the middle of the first leaf sector', relative_error)
    assert np.array_equal(whole, frame(page))
    page.get_by_role('button', name='Show whole table').click()


def check_layout(browser, gallery, scene_file, layout, database, out, portrait, previous=None):
    scene = json.loads(scene_file.read_text())
    assert [d['name'] for d in scene['zones']['outer']['variants']] == NAMES
    with room(gallery, database) as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        api = url + '/api/garden/' + layout
        errors = []
        for ctx in (a, b):
            ctx.route(
                'http**://**/*', lambda r: r.continue_() if r.request.url.startswith(url + '/') else r.abort()
            )
        first, second = a.new_page(), b.new_page()
        for page in (first, second):
            page.on('pageerror', lambda e: errors.append(str(e)))
            open_garden(page, url, layout)
            guest_frame = page.locator('#scene').evaluate('el=>JSON.parse(el.textContent).live.guestBorder===true')
            assert page.locator('#borderDesign option').all_text_contents() == (NAMES + ['Guest drawings'] if guest_frame else NAMES)
            expect(page.locator('#borderGuest')).to_have_value('')
            caption(page, 'Wheat garland')
        # Make a name-only change before there has been any outer drawing.
        pristine = frame(first)
        preview(first, 0, 'Lek')
        assert first.locator('#keep').inner_text() == 'Save guest name'
        assert first.locator('#downloads').is_hidden()
        payload, revision = save(first, api)
        assert not payload.get('motion') and payload['state']['outer'] == 0
        caption(second, 'Lek · Wheat garland')
        assert np.array_equal(frame(second), pristine)
        # An older guest's phone can omit the new field without losing the name.
        legacy = payload['state'].copy()
        legacy.pop('borderGuest')
        response = second.request.put(
            api, headers={'Origin': url}, data={'revision': revision, 'state': legacy}
        )
        assert response.status == 200, response.text()
        assert second.request.get(api).json()['state']['borderGuest'] == 'Lek'
        # Bring both phones to this revision before they submit real artwork.
        open_garden(first, url, layout)
        open_garden(second, url, layout)

        choose(first, 'zone', 'center')
        photo_panel = first.locator('#centerPhoto')
        if not photo_panel.evaluate('e=>e.open'):
            photo_panel.locator(':scope > summary').click()
        first.locator('#portraitFile').set_input_files(portrait)
        first.locator('#portraitSubmit').click()
        caption(first, 'Guest portrait')
        center, _ = save(first, api)
        assert center['state']['portrait'] in ('Guest portrait', 'Guest portrait · photo shadows')
        protected_files = {'center': center['motion']['files']}
        if layout == 'garden':
            choose(first, 'zone', 'middle')
            suggest(first, 'a pumpkin for Alex')
            expect(first.locator('input[name=zone][value=middle]')).to_be_checked()
            guest, _ = save(first, api)
            assert guest['motion']['zone'] == 'middle' and guest['motion']['place'] == 1
            original_ids = center['state']['ids']
            pumpkin = scene['guest_plan'].get('preferredSubjects', {}).get('pumpkin', 'pumpkin')
            assert guest['state']['ids'] == [original_ids[0], pumpkin, original_ids[2]]
            assert guest['state']['outer'] == center['state']['outer']
            protected_files['middle'] = guest['motion']['files']
        for page in (first, second):
            open_garden(page, url, layout)

        reports = {}
        for index, tag in ((2, 'roofs'), (3, 'buds'), (4, 'leaves')):
            sending, receiving = (first, second) if index % 2 == 0 else (second, first)
            typed = index == 4 and layout == 'garden'
            if typed:
                # A request for Lek must override the previous owner, even when the chooser has been closed.
                preview(sending, 3, 'Alex')
                renamed, _ = save(sending, api)
                assert not renamed.get('motion')
                caption(receiving, 'Alex · Lotus buds')
            before = frame(sending)
            state = sending.request.get(api).json()['state']
            expect(sending.locator('#borderGuest')).to_have_value('Alex' if typed else 'Lek')
            reveal = scene['zones']['outer']['variants'][index].get('reveal')
            preview(sending, index, 'Lek', order='whole' if reveal else None)
            assert sending.locator('#middleStageLabel').inner_text() == 'Cleared'
            caption(sending, 'Lek · ' + NAMES[index])
            files, report = actual(
                sending, scene, out / (layout + '-' + tag), index, before, state['bed'], scene_file
            )
            if previous and index < 4:
                with browser.new_context(**MOBILE) as fresh:
                    prior = fresh.new_page()
                    prior.goto(previous.resolve().as_uri() + '?layout=' + layout + '#border')
                    prior_order = 'whole' if prior.locator('#borderOrder option[value=whole]').count() else None
                    preview(prior, index, 'Lek', prior_order)
                    assert drawing_files(prior, '#downloads') == files, 'Whole-border replacement changed'
            if reveal:
                ordinary = files
                if index == 3:
                    ordinary_buds = ordinary
                preview(sending, index, order='progressive')
                if index == 4:
                    first_leaf_zoom(sending, scene)
                    assert len(reveal['finished']) == 10
                files, reveal_report = progressive(
                    sending,
                    scene,
                    scene_file,
                    index,
                    state['outer'],
                    state['bed'],
                    before,
                    out / (layout + '-' + tag + '-progressive'),
                )
                assert files != ordinary
                report['progressive'] = reveal_report
            if typed:
                selected = frame(sending)
                choose(sending, 'zone', 'middle')
                suggest(sending, 'a border of autumn leaves for Lek')
                expect(sending.locator('input[name=zone][value=outer]')).to_be_checked()
                expect(sending.locator('#borderOrder')).to_have_value('progressive')
                caption(sending, 'Lek · Autumn leaves')
                assert np.array_equal(frame(sending), selected)
                assert drawing_files(sending, '#downloads') == files
                assert sending.request.get(api).json()['state'] == state
            saved, _ = save(sending, api)
            assert saved['state']['borderGuest'] == 'Lek' and saved['state']['outer'] == index
            assert saved['motion']['zone'] == 'outer'
            for key in ('portrait', 'center', 'ids', 'custom', 'labels', 'guestBook'):
                assert saved['state'].get(key) == state.get(key)
            assert [(p['name'], p['text'].encode()) for p in saved['motion']['files']] == files
            caption(receiving, 'Lek · ' + NAMES[index])
            assert drawing_files(receiving, '#roomFiles') == files
            if index == 4:
                open_garden(receiving, url, layout)
                caption(receiving, 'Lek · Autumn leaves')
                assert drawing_files(receiving, '#roomFiles') == files
                assert np.array_equal(frame(receiving), frame(sending))
                for protected_zone, wanted in protected_files.items():
                    choose(receiving, 'zone', protected_zone)
                    caption(receiving, 'Guest portrait' if protected_zone == 'center' else 'Alex · Pumpkin')
                    assert drawing_files(receiving, '#roomFiles') == [(f['name'], f['text'].encode()) for f in wanted]
                choose(receiving, 'zone', 'outer')
            if index == 2:
                # Metadata-only saves must leave an already-recorded drawing available.
                for name in ('Lek Hunt', 'Lek'):
                    preview(receiving, index, name)
                    assert receiving.locator('#keep').inner_text() == 'Save guest name'
                    assert receiving.locator('#downloads').is_hidden()
                    assert receiving.locator('#borderOrder').is_hidden()
                    metadata, _ = save(receiving, api)
                    assert not metadata.get('motion') and metadata['state']['bed'] == saved['state']['bed']
                    caption(sending, name + ' · Thai roof peaks')
                    assert drawing_files(sending, '#roomFiles') == files
                with browser.new_context(**MOBILE) as isolated:
                    demo = isolated.new_page()
                    demo.goto(gallery.resolve().as_uri() + '?layout=' + layout + '#example-lek-border')
                    caption(demo, 'Lek · Thai roof peaks')
                    assert drawing_files(demo, '#downloads') == files
                    wide = frame(demo)
                    demo.locator('#guestZoom').click()
                    assert demo.locator('#guestZoom').inner_text() == 'Show whole table'
                    assert np.array_equal(frame(demo), wide)
                    assert drawing_files(demo, '#downloads') == files
                    choose(demo, 'zone', 'center')
                    assert demo.locator('#sand').evaluate("im=>im.style.transform") in ('', 'none')
            reports[tag] = report
        assert files
        # After saving a different zone from a second phone, every border
        # inscription and its identity survive. Only the shared access stem is exempt.
        before = frame(first)
        zone = 'middle' if layout == 'garden' else 'center'
        choose(first, 'zone', zone)
        if zone == 'middle':
            # The two-object scene fits the original fine-groove gallery. On
            # the fitted table, use the full-size guitar in the smaller seat.
            request = 'a guitar for Thomas' if 'guest_clearance_mm' in scene else 'a comet over a telescope for Thomas'
            suggest(first, request)
        else:
            choose(first, 'stage', 'redrawn')
        moved, rev = save(first, api)
        assert moved['motion']['zone'] == zone and moved['state']['borderGuest'] == 'Lek'
        after = frame(first)
        n = len(before)
        yy, xx = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
        radius = np.hypot(xx, yy)
        g = scene['groove_width']
        border = (
            (radius >= scene['zones']['outer']['safe_bounds'][0])
            & (radius < 0.997)
            & ((yy < 0) | (abs(xx) > 3 * g))
        )
        assert np.array_equal(before[border], after[border]) and np.any(before[~border] != after[~border])
        # A valid movement for another zone may not smuggle in a border rename.
        forged = {**moved, 'revision': rev, 'state': {**moved['state'], 'borderGuest': 'Different guest'}}
        rejected = second.request.put(api, headers={'Origin': url}, data=forged)
        assert rejected.status == 400 and second.request.get(api).json()['revision'] == rev, rejected.text()
        open_garden(second, url, layout)
        caption(second, 'Lek · Autumn leaves')
        assert drawing_files(second, '#roomFiles') == files
        preview(second, 3, order='whole')
        assert drawing_files(second, '#downloads') == ordinary_buds
        restored, _ = save(second, api)
        assert restored['state']['outer'] == 3 and restored['state']['borderGuest'] == 'Lek'
        for key in ('center', 'portrait', 'ids', 'custom', 'labels', 'guestBook'):
            assert restored['state'].get(key) == moved['state'].get(key)
        choose(first, 'zone', 'outer')
        caption(first, 'Lek · Lotus buds')
        assert drawing_files(first, '#roomFiles') == ordinary_buds
        assert not errors, errors
        reports['other_zone'] = zone
        reports['border_pixels_kept'] = int(border.sum())
        return reports


def mini(browser, file, reference):
    def cycle(page, gallery):
        page.goto(gallery.resolve().as_uri() + '#photos')
        choose(page, 'zone', 'outer')
        assert page.locator('#borderForm').is_hidden() and page.locator('#borderOrder').is_hidden()
        names = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).zones.outer.names")
        assert names == ['Open ribbon', 'Shell arches']
        items = []
        for label in names[::-1]:
            choose(page, 'stage', 'redrawn')
            caption(page, label)
            items.append(drawing_files(page, '#downloads'))
            page.locator('#keep').click()
        return items

    with browser.new_context(**MOBILE) as ctx:
        assert cycle(ctx.new_page(), file) == cycle(ctx.new_page(), reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('--scenes', nargs=2, type=Path, required=True, metavar=('GARDEN', 'WIDE'))
    parser.add_argument('--mini', type=Path, required=True)
    parser.add_argument('--photo', type=Path, default=Path(__file__).resolve().parents[1] / 'captures/family-source/lek.jpg',
                        help='A local single-face photograph to keep in the center of both layouts.')
    parser.add_argument('--previous-mini', type=Path, required=True)
    parser.add_argument(
        '--previous', type=Path, help='prior large-table gallery for byte-identical conventional exports'
    )
    parser.add_argument('--evidence', type=Path, required=True)
    a = parser.parse_args()
    a.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {}
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            mini(browser, a.mini, a.previous_mini)
            for layout, scene in zip(('garden', 'portrait'), a.scenes):
                report[layout] = check_layout(
                    browser, a.gallery, scene, layout, Path(temp) / (layout + '.db'), a.evidence, a.photo, a.previous
                )
                print(layout, report[layout], flush=True)
    (a.evidence / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
