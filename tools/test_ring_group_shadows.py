#!/usr/bin/env python3
"""Test a group's saved sand movements against measurements from the preceding gallery.

Pass the combined gallery, a tilted pair, a three-face group unused in development,
and a crowded photograph. --previous is a saved gallery from before group shadows.
For newer editors, --previous-editor compares exported treatments against a frozen
editor that already supports group shadows. Only a local, simulated garden is used.
"""

import argparse
import base64
import json
import math
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_garden_room import room, caption, drawing_files, suggest
from test_ring_photo import frame
from test_ring_shadows import choose, ready, export, distances, dense_route, check_views

MOBILE = dict(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
EYES = ('eye', 'glasses')
DETAILS = ('shade', 'hairline', 'brow', 'bridge', 'nose')


def source_measurements(page, legacy, files, *, shadow_input=False):
    """Use the earlier face engine. Keep measurements independent of the new drawing."""
    page.goto(legacy.resolve().as_uri() + '?layout=portrait#photos')
    models = page.locator('#portraitModels')
    if models.count():
        page.add_script_tag(content=models.text_content())
    source = page.locator('#portraitTools').text_content()
    functions = re.findall(
        r'function closeFaces\(image, landmarks, portraitDiameterGrooves(?:, locals=null)?\) \{', source
    )
    assert len(functions) == 1, 'The reference must expose the pre-engraving face measurements.'
    hook = functions[0]
    page.add_script_tag(
        content=source.replace(
            hook,
            hook
            + '''
      window.testPhotoLandmarks = landmarks.map(L => {
        const {head,glasses} = portraitShapes(image,L,false,30);
        return {L,head,glasses};
      });''',
        )
    )
    refs = {}
    for file in files:
        page.locator('#portraitFile').set_input_files(file)
        refs[file] = page.evaluate("""async shadow => {
          const res=await GuestPhoto.fromFile(document.querySelector('#portraitFile').files[0],
            {group:true,groupStyle:'faces',portraitStyle:shadow?'shadow':'line',portraitDiameterGrooves:140});
          return {boxes:res.includedFaces,faces:window.testPhotoLandmarks};
        }""", shadow_input)
        assert len(refs[file]['boxes']) == len(refs[file]['faces'])
    return refs


def submit(page, photo, style='shadows', group=True):
    page.locator('#portraitFile').set_input_files(photo)
    page.locator('#portraitMode').select_option('group' if group else 'one')
    page.locator('#portraitStyle' if group else '#soloStyle').select_option(style)
    page.locator('#portraitSubmit').click()
    ready(page)


def open_file(page, gallery, layout):
    # Opening the same URL with a fragment can retain the preceding guest's unkept
    # preview. Start every independent replay with a new document and untouched bed.
    page.goto('about:blank')
    page.goto(gallery.resolve().as_uri() + '?layout=' + layout + '#photos')
    return frame(page)


def toggle(page, index):
    panel = page.locator('#portraitSource')
    if not panel.evaluate('el => el.open'):
        panel.locator('summary').click()
    page.locator('#faceBoxes button').nth(index).click()
    ready(page)


def proposed(page, explicit_selection):
    """Collect the anatomical curves, then associate them with real exported travel."""
    return page.evaluate(
        """async explicit => {
      const scene=JSON.parse(document.querySelector('#scene').textContent), live=scene.live, z=scene.zones.center;
      const high=z.transit.at(-1)[1], file=document.querySelector('#portraitFile').files[0];
      const opt={group:true,groupStyle:'faces',portraitStyle:'shadow',
        portraitDiameterGrooves:2*high/live.groove,portraitDiameterMm:2*high*live.radiusMM};
      const initial=await GuestPhoto.fromFile(file,opt);
      if(explicit){
        const buttons=[...document.querySelectorAll('#faceBoxes button')];
        opt.groupFaces=initial.faceBoxes.map((b,i)=>({...b,included:buttons[i].getAttribute('aria-pressed')==='true'}));
      }
      const res=explicit?await GuestPhoto.fromFile(file,opt):initial;
      let plan;
      if(res.shadowMarks){
        try{plan=OasisRingPlanner.shadowPhoto(z,res.shadowMarks,live,{faces:res.includedFaces.map((_,i)=>i)});}
        catch(error){ /* The UI must show every selected face in the conventional fallback. */ }
      }
      if(!plan) plan=OasisRingPlanner.photo(z,res.points);
      return {high,radius:live.radiusMM,groove:live.groove,dock:z.transit[0],path:plan.path,
        marks:res.shadowMarks,events:plan.marks,boxes:res.includedFaces};
    }""",
        explicit_selection,
    )


def downloaded(page, directory, data):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    parts = export(page, directory)
    for left, right in zip(parts, parts[1:]):
        np.testing.assert_array_equal(left[-1], right[0])
    written = np.vstack([parts[0], *(p[1:] for p in parts[1:])])
    np.testing.assert_allclose(written, data['path'], rtol=0, atol=5.00001e-6)
    route = check.joined(parts, data['dock'], data['dock'], 'downloaded group portrait')
    assert abs(data['dock'][0] + math.pi / 2) <= check.TOL
    outside = route[:, 1] > data['high'] + check.TOL
    assert check.seam_segments(route, data['dock'][0])[outside[:-1] | outside[1:]].all()
    return route


def targets(mark, step):
    curve = np.array(mark['points'])
    if mark['closed']:
        curve = np.vstack([curve, curve[0]])
    lengths = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
    sample = np.linspace(0, lengths[-1], max(4, math.ceil(lengths[-1] / step) + 1))
    return np.column_stack([np.interp(sample, lengths, col) for col in curve.T])


def tangents(points):
    v = np.gradient(points, axis=0)
    return v / np.maximum(np.linalg.norm(v, axis=1)[:, None], 1e-12)


def engraving(route, mark, event, radius, width, cumulative):
    """Measure the first traversal of the actual contour from downloaded polar movements."""
    start, end = event['first'], event['last']
    xy, travel = dense_route(route[start : end + 1], radius, width * 0.055)
    points = targets(mark, width * 0.08)
    direction = tangents(xy)
    tree = cKDTree(xy)
    arrival = np.full(len(points), np.inf)
    for i, (v, neighbors) in enumerate(zip(tangents(points), tree.query_ball_point(points, width * 0.18))):
        neighbors = np.array(neighbors, dtype=int)
        along = neighbors[abs(direction[neighbors] @ v) > math.cos(math.radians(30))]
        if along.size:
            arrival[i] = (cumulative[start] + min(travel[along])) / cumulative[-1]
    fraction = np.isfinite(arrival).mean()
    if mark['kind'] in DETAILS:
        # The planner can shorten an optional shadow to keep two adjacent grooves separate.
        return fraction * np.linalg.norm(np.diff(points, axis=0), axis=1).sum()
    assert tree.query(points)[0].max() <= width * 0.18 and fraction >= 0.95, (mark['kind'], fraction)
    complete = float(np.max(arrival[np.isfinite(arrival)]))
    if mark['kind'] == 'head':
        crown = (points[:, 1] > np.percentile(points[:, 1], 80)) & np.isfinite(arrival)
        assert crown.any()
        return round(complete, 4), round(float(np.max(arrival[crown])), 4)
    return round(complete, 4)


def referenced_faces(boxes, ref):
    indices = [ref['boxes'].index(box) for box in boxes]
    assert len(set(indices)) == len(indices)
    return indices


def photographic_geometry(marks, face):
    """Recover one translation and uniform scale from the measured original head."""
    head = next(np.array(m['points']) for m in marks if m['kind'] == 'head')
    source = np.asarray(face['head']) * [1, -1]
    scale = np.ptp(head[:, 0]) / np.ptp(source[:, 0])
    shift = head.mean(axis=0) - source.mean(axis=0) * scale
    np.testing.assert_allclose(source * scale + shift, head, atol=0.02, rtol=0)
    landmarks = np.asarray(face['L']) * [1, -1] * scale + shift
    eyes = sorted([np.mean(m['points'], axis=0) for m in marks if m['kind'] in EYES], key=lambda c: c[0])
    eye_ref = [landmarks[36:42].mean(0), landmarks[42:48].mean(0)]
    if any(m['kind'] == 'glasses' for m in marks) and face.get('glasses'):
        eye_ref = sorted(
            [np.mean(lens, axis=0) * [1, -1] * scale + shift for lens in face['glasses']], key=lambda c: c[0]
        )
    mouth = next(np.mean(m['points'], axis=0) for m in marks if m['kind'] == 'smile')
    offsets = np.linalg.norm(
        np.vstack([*eyes, mouth]) - np.vstack([*eye_ref, landmarks[60:68].mean(0)]), axis=1
    )
    eye_axis = np.subtract(*eyes)
    source_axis = np.subtract(*eye_ref)
    tilt_error = np.degrees(
        np.arccos(
            np.clip(eye_axis @ source_axis / (np.linalg.norm(eye_axis) * np.linalg.norm(source_axis)), -1, 1)
        )
    )
    assert offsets.max() < 0.065 * np.ptp(head[:, 0]) and tilt_error < 7, (offsets, tilt_error)
    return scale, {
        'source_error_mm': np.round(offsets, 2).tolist(),
        'eye_tilt_error_deg': round(float(tilt_error), 2),
    }


def measure_people(route, data, ref):
    indices = referenced_faces(data['boxes'], ref)
    total = distances(route) * data['radius']
    width = data['groove'] * data['radius']
    reports, scales = [], []
    assert set(ev['owner'] for ev in data['events']) == set(range(len(indices)))
    for owner, reference_index in enumerate(indices):
        owned = [m for m in data['marks'] if m['owner'] == owner]
        scale, report = photographic_geometry(owned, ref['faces'][reference_index])
        scales.append(scale)
        timing, details = [], []
        for ev in data['events']:
            if ev['owner'] != owner:
                continue
            mark = data['marks'][ev['source']]
            assert mark['owner'] == owner and mark['kind'] == ev['kind']
            t = engraving(route, mark, ev, data['radius'], width, total)
            if mark['kind'] in DETAILS:
                if t >= width:
                    details.append(mark['kind'])
            elif mark['kind'] == 'head':
                timing += [('head', t[0]), ('crown', t[1])]
            else:
                timing.append((mark['kind'], t))
        assert sorted('eye' if k in EYES else k for k, t in timing) == ['crown', 'eye', 'eye', 'head', 'smile']
        # Each person in these fixtures contributes a recognizable feature before
        # the halfway image, even when one mouth or a whole crown arrives later.
        assert min(t for kind, t in timing if kind in (*EYES, 'smile')) < 0.5, ('late first feature', owner)
        assert details, ('missing independent photographic detail', owner)
        report.update(
            source_face=reference_index + 1,
            order=sorted(timing, key=lambda row: row[1]),
            details=sorted(set(details)),
        )
        reports.append(report)
    assert np.ptp(scales) < 0.001, 'Faces lost their photographed relative scale'
    return reports


def verify_ui(page, original, photo_ref, out, count, native, explicit=False):
    data = proposed(page, explicit)
    title = page.locator('.caption').inner_text()
    status = page.locator('#portraitStatus').inner_text()
    middle_label = page.locator('#middleStageLabel').inner_text()
    assert page.locator('#faceBoxes button[aria-pressed=true]').count() == len(data['boxes']) == count
    assert middle_label == ('Halfway' if native else 'Cleared'), (middle_label, status)
    assert native == bool(data.get('events'))
    route = downloaded(page, out, data)
    indices = referenced_faces(data['boxes'], photo_ref)
    result = {
        'caption': title,
        'status': status,
        'files': page.locator('#downloads a').count(),
        'source_faces': [i + 1 for i in indices],
    }
    if native:
        assert f'{count} faces in shadow' in title
        final = frame(page)
        choose(page, 'stage', 'cleared')
        middle = frame(page)
        result.update(check_views(page, route, data, original, middle, final))
        result['people'] = measure_people(route, data, photo_ref)
        choose(page, 'stage', 'redrawn')
        for name, im in [('half', middle), ('final', final)]:
            Image.fromarray(im).save(out / (name + '.jpg'), quality=92)
    elif count == 1:
        assert '1 face' in title and 'original pose' in status.lower()
    else:
        assert f'{count} faces together' in title
        assert ('both faces' if count == 2 else f'all {count} faces') in status.lower() and 'close-up' in status
    return route, result


def reference_output(page, previous, layout, photo, style, exclusions=(), group=True):
    """Read signed files from a separate, frozen UI, including its own style fallback."""
    open_file(page, previous, layout)
    submit(page, photo, style, group)
    for index in exclusions:
        toggle(page, index)
    return page.locator('#middleStageLabel').inner_text(), drawing_files(page, '#downloads')


def compare_previous(page, old_page, previous, layout, photo, style, exclusions=(), group=True):
    _, before = reference_output(old_page, previous, layout, photo, style, exclusions, group)
    assert drawing_files(page, '#downloads') == before, f'{layout} {style}: saved movement files changed'


def private_network(context, violations, uploads):
    def inspect(request):
        if request.url.startswith(('http://', 'https://')) and urlsplit(request.url).hostname != '127.0.0.1':
            violations.append(request.url)
        if request.method not in ('GET', 'HEAD'):
            uploads.append(request.post_data or '')

    context.on('request', inspect)
    context.route(
        'http**://**/*',
        lambda route: route.continue_()
        if urlsplit(route.request.url).hostname == '127.0.0.1'
        else route.abort(),
    )


def shared(browser, gallery, db, layout, photo, exclude):
    api = '/api/garden/' + layout
    problems, writes = [], []
    with room(gallery, db) as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        for ctx in (a, b):
            private_network(ctx, problems, writes)
        first, second = a.new_page(), b.new_page()
        for page in (first, second):
            page.on('pageerror', lambda error: problems.append(str(error)))
            with page.expect_response(lambda r: urlsplit(r.url).path == api and r.request.method == 'GET'):
                page.goto(url + '/garden?layout=' + layout + '#photos')
            expect(page.locator('.controls')).not_to_have_attribute('inert', '')
        submit(first, photo)
        if exclude is not None:
            toggle(first, exclude)
        name = first.locator('.caption').inner_text()
        assert 'faces in shadow' in name and not writes
        files = drawing_files(first, '#downloads')

        def save(page):
            with page.expect_response(
                lambda r: urlsplit(r.url).path == api and r.request.method == 'PUT'
            ) as put:
                page.locator('#keep').click()
            assert put.value.status == 200
            expect(page.locator('#keep')).to_be_hidden()

        save(first)
        caption(second, name)
        before = frame(second)
        assert drawing_files(second, '#roomFiles') == files
        zone = 'middle' if layout == 'garden' else 'outer'
        choose(second, 'zone', zone)
        if zone == 'middle':
            suggest(second, 'a turkey for Thomas')
        else:
            choose(second, 'stage', 'redrawn')
        save(second)
        after = frame(second)
        high, groove = second.evaluate("""()=>{const s=JSON.parse(document.getElementById('scene').textContent);
          return [s.zones.center.transit.at(-1)[1],s.live.groove]}""")
        y, x = np.mgrid[-1 : 1 : complex(len(after)), -1 : 1 : complex(len(after))]
        center = np.hypot(x, y) < high - 2 * groove
        assert np.array_equal(before[center], after[center]) and np.any(before[~center] != after[~center])
        choose(second, 'zone', 'center')
        caption(second, name)
        assert drawing_files(second, '#roomFiles') == files
        payload = ''.join(writes)
        raw = base64.b64encode(photo.read_bytes()).decode()
        assert (
            len(writes) == 2
            and 'data:image/' not in payload
            and photo.name not in payload
            and raw[len(raw) // 2 : len(raw) // 2 + 256] not in payload
        )
        assert not problems, problems
        return {
            'zone_changed': zone,
            'center_pixels_unchanged': int(center.sum()),
            'identical_files': len(files),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('gallery', 'pair', 'holdout', 'crowd'):
        parser.add_argument(name, type=Path)
    parser.add_argument(
        '--previous', type=Path, required=True, help='Frozen solo-shadow release for independent source landmarks.'
    )
    parser.add_argument(
        '--previous-editor', type=Path,
        help='Compare explicit styles to this frozen group-shadow editor. Defaults to testing the first group-shadow release.',
    )
    parser.add_argument('--solo', type=Path, required=True)
    parser.add_argument('--mini', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = (args.pair, args.holdout, args.crowd)
    route_reference = args.previous_editor or args.previous
    reports = {}
    chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
    with (
        tempfile.TemporaryDirectory() as temp,
        sync_playwright() as play,
        play.chromium.launch(executable_path=str(chrome)) as browser,
    ):
        with browser.new_context(**MOBILE) as ctx:
            problems, writes = [], []
            private_network(ctx, problems, writes)
            page, old = ctx.new_page(), ctx.new_page()
            page.on('pageerror', lambda e: problems.append(str(e)))
            refs = source_measurements(old, args.previous, files)
            if args.previous_editor:
                # The seven-person image has small faces. The newer engine
                # remeasures their landmarks using original pixels. Read those
                # source positions before any engraving or layout is generated.
                crowd = source_measurements(old, args.previous_editor, [args.crowd], shadow_input=True)[args.crowd]
                assert crowd['boxes'] == refs[args.crowd]['boxes'], 'The frozen editors must identify the same seven people.'
                refs[args.crowd] = crowd
            for layout in ('portrait', 'garden'):
                for tag, photo in zip(('pair', 'holdout', 'crowd'), files):
                    original = open_file(page, args.gallery, layout)
                    submit(page, photo)
                    count = len(refs[photo]['boxes'])
                    assert count == {'pair': 2, 'holdout': 3, 'crowd': 7}[tag]
                    # The original release needed outlines for seven people. Later
                    # versions fit all seven into the wide center. Pin that choice to
                    # the comparison release, independently of the current planner.
                    native = layout == 'portrait' and tag != 'crowd'
                    if args.previous_editor:
                        middle, saved = reference_output(old, route_reference, layout, photo, 'shadows')
                        assert middle in ('Halfway', 'Cleared')
                        if layout == 'portrait' and tag == 'crowd':
                            native = middle == 'Halfway'
                        assert drawing_files(page, '#downloads') == saved, f'{layout} {tag}: group shadow files changed'
                    key = layout + '-' + tag
                    first, result = verify_ui(page, original, refs[photo], args.evidence / key, count, native)
                    reports[key] = result
                    print(key, result, flush=True)
                    if not native and not args.previous_editor:
                        # The original fallback used the same close-ups as the old
                        # face tool. Later editors remeasure explicit close-ups;
                        # their shadow fallback is checked against its own style above.
                        compare_previous(page, old, route_reference, layout, photo, 'faces')
                    if tag == 'holdout':
                        toggle(page, 2)
                        pair_key = key + '-subset'
                        _, subset = verify_ui(
                            page, original, refs[photo], args.evidence / pair_key, 2, True, True
                        )
                        assert subset['source_faces'] == [1, 2], subset
                        reports[pair_key] = subset
                        print(pair_key, subset, flush=True)
                        toggle(page, 1)
                        _, one = verify_ui(
                            page, original, refs[photo], args.evidence / (key + '-one'), 1, False, True
                        )
                        assert one['source_faces'] == [1]
                        reference_style = 'shadows' if args.previous_editor else 'faces'
                        compare_previous(page, old, route_reference, layout, photo, reference_style, (2, 1))
                        toggle(page, 1)
                        toggle(page, 2)
                        restored = downloaded(page, args.evidence / (key + '-restored'), proposed(page, True))
                        np.testing.assert_array_equal(restored, first)
                    if args.previous_editor:
                        for style in ('faces', 'pose'):
                            submit(page, photo, style)
                            compare_previous(page, old, route_reference, layout, photo, style)
                open_file(page, args.gallery, layout)
                expected_default = 'auto' if page.locator('#soloStyle option[value=auto]').count() else 'line'
                assert page.locator('#soloStyle').input_value() == expected_default
                submit(page, args.solo, 'line', False)
                compare_previous(page, old, route_reference, layout, args.solo, 'line', group=False)
                page.locator('#soloStyle').select_option('shadow')
                ready(page)
                assert page.locator('#middleStageLabel').inner_text() == 'Halfway'
                compare_previous(page, old, route_reference, layout, args.solo, 'shadow', group=False)
                reports[layout + '-shared'] = shared(
                    browser,
                    args.gallery,
                    Path(temp) / (layout + '.db'),
                    layout,
                    args.pair if layout == 'portrait' else args.holdout,
                    None if layout == 'portrait' else 2,
                )
                print(layout + '-shared', reports[layout + '-shared'], flush=True)
            page.goto(args.gallery.resolve().as_uri() + '#example-group-shadows')
            ready(page)
            assert page.locator('#layout').input_value() == 'portrait'
            assert page.locator('#middleStageLabel').inner_text() == 'Halfway'
            caption(page, '3 faces in shadow')
            if args.mini:
                open_file(page, args.mini, 'garden')
                submit(page, args.pair, 'faces')
                option = page.locator('#portraitStyle option[value=shadows]')
                assert option.is_disabled() or option.evaluate('e=>e.hidden')
                assert page.locator('#middleStageLabel').inner_text() == 'Cleared'
            assert not problems and not writes, (problems, len(writes))
    (args.evidence / 'results.json').write_text(json.dumps(reports, indent=2) + '\n')


if __name__ == '__main__':
    main()
