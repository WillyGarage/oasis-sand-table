#!/usr/bin/env python3
"""Exercise the guest's shadow-portrait controls and actual downloaded movements, offline.

python3 tools/test_ring_shadows.py gallery.html single1.jpg single2.jpg group.jpg --mini mini.html
Use --evidence DIR for sand-only before/half/after images, motion files and measurements.
Optional --reference JSON JSON accepts independently retained source landmarks for each solo.
"""
import argparse
import base64
import io
import json
import math
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_ring_faces import no_faces
from test_ring_photo import frame


def distances(route):
    dr = np.diff(route[:, 1])
    arc = np.diff(route[:, 0]) * (route[:-1, 1] + route[1:, 1]) / 2
    return np.r_[0., np.cumsum(np.hypot(dr, arc))]


def at_half(route):
    distance = distances(route)
    halfway = distance[-1] / 2
    i = np.searchsorted(distance, halfway)
    frac = (halfway - distance[i - 1]) / (distance[i] - distance[i - 1])
    return np.vstack([route[:i], route[i - 1] + frac * (route[i] - route[i - 1])])


def dense_route(route, radius_mm, step_mm):
    distance = distances(route) * radius_mm
    grid = np.linspace(0, distance[-1], math.ceil(distance[-1] / step_mm) + 1)
    theta, r = [np.interp(grid, distance, column) for column in route.T]
    xy = radius_mm * np.column_stack([r * np.cos(theta), r * np.sin(theta)])
    return xy, grid


def feature_progress(route, marks, radius, width):
    """First fraction visiting the whole curve, with 95% traced in the measured direction.
    A crossing spiral can visit the center of an eye without drawing either eyelid.
    """
    xy, travel = dense_route(route, radius, width * .06)
    tangents = np.gradient(xy, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-10)
    tree = cKDTree(xy)
    result = []
    for mark in marks:
        if mark['kind'] not in ('eye', 'glasses', 'smile'):
            continue
        shape = np.asarray(mark['points'], dtype=float)
        if mark['closed']:
            shape = np.vstack([shape, shape[0]])
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(shape, axis=0), axis=1))]
        spots = np.linspace(0, lengths[-1], max(3, math.ceil(lengths[-1] / (width * .1))))
        points = np.column_stack([np.interp(spots, lengths, column) for column in shape.T])
        direction = np.gradient(points, axis=0)
        direction /= np.maximum(np.linalg.norm(direction, axis=1)[:, None], 1e-10)
        aligned_arrivals = []
        spatial_arrivals = []
        for v, candidates in zip(direction, tree.query_ball_point(points, width * .17)):
            ix = np.array(candidates, dtype=int)
            spatial_arrivals.append(travel[ix].min() / travel[-1] if len(ix) else 2.)
            # Either direction engraves the same stroke. A tangent check rules out radial crossings.
            ix = ix[np.abs(tangents[ix] @ v) > math.cos(math.radians(28))]
            aligned_arrivals.append(travel[ix].min() / travel[-1] if len(ix) else 2.)
        t = max(float(np.percentile(aligned_arrivals, 95)), max(spatial_arrivals))
        assert t < .5, (mark['kind'], 'not engraved by halfway', t)
        result.append((mark['kind'], round(float(t), 4)))
    assert sorted('eye' if k == 'glasses' else k for k, t in result) == ['eye', 'eye', 'smile'], result
    return result


def engraved_shading(route, data):
    """Keep points from the downloaded excursions that lie on actual shadow contours."""
    radius = data['radius']
    width = radius * data['groove']
    result = []
    for section in data['events']:
        if section['kind'] != 'shade':
            continue
        source = data['marks'][section['source']]
        curve = np.array(source['points'])
        if source['closed']:
            curve = np.vstack([curve, curve[0]])
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
        sample = np.linspace(0, lengths[-1], math.ceil(lengths[-1] / (width * .08)) + 1)
        outline = np.column_stack([np.interp(sample, lengths, axis) for axis in curve.T])
        observed, _ = dense_route(route[section['first']:section['last'] + 1], radius, width * .08)
        # The short connector to the spiral does not represent the source shadow.
        near = cKDTree(outline).query(observed)[0] < width * .12
        assert near.sum() > 5, 'Exported shadow excursion missed its proposed contour'
        result.append(observed[near])
    assert result, 'No photo-derived shadow contour survived into the downloaded movement'
    return np.vstack(result)


def verify_source(photo, reference, data, route):
    """Compare exported eye/mouth locations against landmarks from a separate reading of the source."""
    record = json.loads(reference.read_text())
    q = record.get('QA') or record.get('qa') or record
    head = np.array(q['people'][0]['head'])
    landmarks = np.array(q['landmarks'][0])
    marks = data['marks']
    diameter = 2 * data['radius'] * data['high']
    radius = np.ptp(head[:, 1]) / 1.58
    center = np.array([(min(head[:, 0]) + max(head[:, 0])) / 2, min(head[:, 1]) + .9 * radius])
    silhouette = np.vstack([head, *q['people'][0].get('glasses', [])])
    groove_count = 2 * data['high'] / data['groove']
    radius = max(radius, np.linalg.norm(silhouette - center, axis=1).max() / (1 - 3.5 / groove_count))
    scale = diameter / (2 * radius)
    def source(mark):
        return np.asarray(mark['points']) / scale * [1, -1] + center
    eyes = sorted([source(m) for m in marks if m['kind'] in ('eye', 'glasses')], key=lambda p:p[:, 0].mean())
    expected = sorted([landmarks[36:42], landmarks[42:48]], key=lambda p:p[:, 0].mean())
    mouth = next(source(m) for m in marks if m['kind'] == 'smile')
    centers = [np.linalg.norm(a.mean(axis=0) - b.mean(axis=0)) * scale
               for a, b in zip([*eyes, mouth], [*expected, landmarks[48:60]])]
    assert max(centers) < .05 * diameter, ('Measured feature misses the source photo', centers)
    im = ImageOps.exif_transpose(Image.open(photo)).convert('L')
    factor = min(1., 1000 / max(im.size))
    gray = np.array(im.resize(tuple(round(factor * v) for v in im.size), Image.Resampling.LANCZOS))
    shade = engraved_shading(route, data) / scale * [1, -1] + center
    x, y = np.rint(shade).astype(int).T
    assert ((x >= 0) & (x < gray.shape[1]) & (y >= 0) & (y < gray.shape[0])).all()
    mask = cv2.fillPoly(np.zeros_like(gray), [np.rint(head).astype(np.int32)], 255).astype(bool)
    return {'source_feature_center_offsets_mm':np.round(centers, 1).tolist(),
            'shade_median_source_luminance':int(np.median(gray[y, x])),
            'head_median_source_luminance':int(np.median(gray[mask]))}


def choose(page, name, value):
    page.locator(f'input[name={name}][value={value}] + span').click()


def ready(page):
    page.wait_for_function("""!document.querySelector('#portraitSubmit').disabled &&
      document.querySelector('input[name=stage]:checked').value==='redrawn' &&
      !document.querySelector('#keep').hidden""")


def export(page, folder):
    details = page.locator('#downloads')
    if not details.evaluate('el => el.open'):
        details.locator('summary').click()
    links = details.locator('a')
    links.first.wait_for()
    files = []
    for link in links.all():
        with page.expect_download() as wait:
            link.click()
        saved = wait.value
        assert Path(saved.suggested_filename).name == saved.suggested_filename
        saved.save_as(folder / saved.suggested_filename)
        files.append(check.read_path(folder, saved.suggested_filename))
    assert files
    return files


def replay(page, route):
    # Reconstruct the physical download on the original occupied surface; never use a prepared portrait image.
    encoded = page.evaluate("""route => {
      const scene=JSON.parse(document.querySelector('#scene').textContent), live=scene.live;
      const bed=Float32Array.from(atob(live.bed),b=>b.charCodeAt(0)/170-1);
      const sim=new RingSand(live.size,live.groove,live.profile); sim.carve(bed,route);
      return sim.image(bed).split(',')[1];
    }""", route.tolist())
    return np.array(Image.open(io.BytesIO(base64.b64decode(encoded))).convert('RGB'))


def expected(page, shadow, group=False, head=False):
    return page.evaluate("""async ([shadow,group,head]) => {
      const scene=JSON.parse(document.querySelector('#scene').textContent),live=scene.live,z=scene.zones.center;
      const high=z.transit.at(-1)[1], diameter=2*high*live.radiusMM;
      const file=document.querySelector('#portraitFile').files[0];
      const res=await GuestPhoto.fromFile(file,{group,portraitStyle:shadow?'shadow':'line',
        portraitFraming:head?'framedHead':undefined,
        portraitTrackingGrooves:head && Number.isFinite(live.trackingMarginMM) ? live.trackingMarginMM/(live.groove*live.radiusMM) : undefined,
        portraitDiameterMm:diameter,portraitDiameterGrooves:2*high/live.groove});
      const plan=shadow?OasisRingPlanner.shadowPhoto(z,res.shadowMarks,live):OasisRingPlanner.photo(z,res.points);
      return {path:plan.path, marks:res.shadowMarks, events:plan.marks, radius:live.radiusMM, groove:live.groove, high,
        dock:z.transit[0], clear:shadow?null:OasisRingPlanner.join(plan.segments.slice(0,2))};
    }""", [shadow, group, head])


def check_views(page, route, result, original, middle, final):
    high, groove, radius = [result[n] for n in ('high', 'groove', 'radius')]
    n = len(original)
    y, x = np.mgrid[:n, :n]
    x = x / ((n - 1) / 2) - 1
    y = 1 - y / ((n - 1) / 2)
    r = np.hypot(x, y)
    protected = (r > high + 3 * groove) & (r < .99) & ((y >= 0) | (abs(x) > 3 * groove))
    assert np.array_equal(original[protected], middle[protected]) and np.array_equal(original[protected], final[protected])
    half = at_half(route)
    error = []
    for shown, traced in [(middle, half), (final, route)]:
        delta = abs(shown.astype(np.int16) - replay(page, traced).astype(np.int16))
        error.append(round(float(delta.mean()), 3))
        assert delta.mean() < 1.1 and np.percentile(delta, 99) < 5, ('Preview differs from exported travel', error)
    # Dilate the *actual half-path* by enlarged groove + image-filter support.
    points, _ = dense_route(half, radius, radius * groove * .12)
    uv = np.rint((points / radius * [1, -1] + 1) * (n - 1) / 2).astype(np.int32)
    ink = cv2.polylines(np.zeros((n, n), np.uint8), [uv], False, 255, max(3, math.ceil(4 * groove * n / 2)))
    unswept = (ink == 0) & (r < high - groove)
    assert unswept.sum() > .02 * np.sum(r < high)
    assert np.array_equal(middle[unswept], original[unswept]), 'Old sand changed ahead of the ball'
    old_art = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).zones.center.drawings[0]")
    flower, _ = dense_route(np.array(old_art), radius, radius * groove * .12)
    old_uv = np.rint((flower / radius * [1,-1] + 1) * (n-1)/2).astype(np.int32)
    tracks = cv2.polylines(np.zeros((n,n),np.uint8),[old_uv],False,255,max(1,round(.4*groove*n/2)))
    old_petals = unswept & (tracks>0) & (r<.95*high) & ((y>=0)|(abs(x)>2*groove))
    assert old_petals.sum()>50, 'The unswept area must include visible strokes from the original flower'
    assert np.abs(middle.astype(float) - final).mean() > .2
    return {'replay_mean_8bit_error':error, 'old_center_pixels_untouched_at_half':int(unswept.sum()),
            'original_flower_track_pixels_untouched_at_half':int(old_petals.sum())}


def exercise(page, url, photo, group, out, reference, layout, transitions):
    page.goto(url + "?layout=" + layout + "#photos")
    original = frame(page)
    style = page.locator('#soloStyle')
    upload = page.locator('#portraitFile')
    assert style.input_value() == 'auto'
    style.select_option('line')
    upload.set_input_files(photo)
    page.locator('#portraitSubmit').click()
    ready(page)
    line = expected(page, False)
    line_folder = out / 'outline'
    line_folder.mkdir(exist_ok=True)
    plain = check.joined(export(page, line_folder), line['dock'], line['dock'], 'ordinary portrait')
    assert check.same_track(plain, np.asarray(line['path']))
    line_distance = distances(plain)
    clear_end = float(line_distance[len(line['clear']) - 1] / line_distance[-1])
    style.select_option('shadow')
    ready(page)
    assert page.locator('#middleStageLabel').inner_text() == 'Halfway', page.locator('#portraitStatus').inner_text()
    data = expected(page, True)
    dock = data['dock']
    final = frame(page)
    files = export(page, out)
    route = check.joined(files, dock, dock, 'shadow portrait')
    assert check.same_track(route, np.array(data['path']))
    # Each file starts on its predecessor's exact signed pose. Check every
    # exported coordinate at the format's precision, before any turn alignment.
    for left, right in zip(files, files[1:]):
        np.testing.assert_array_equal(left[-1], right[0])
    written = np.vstack([files[0], *(part[1:] for part in files[1:])])
    np.testing.assert_allclose(written, data['path'], rtol=0, atol=5.00001e-6)
    outside = route[:, 1] > data['high'] + check.TOL
    assert check.seam_segments(route, dock[0])[outside[:-1] | outside[1:]].all()
    choose(page, 'stage', 'cleared')
    middle = frame(page)
    result = check_views(page, route, data, original, middle, final)
    timing = feature_progress(route, data['marks'], data['radius'], data['groove'] * data['radius'])
    assert max(t for _, t in timing) < clear_end
    result.update(early_features=timing, ordinary_clear_fraction=round(clear_end, 3), files=len(files), points=len(route),
                  distance_m=round(float(distances(route)[-1] * data['radius'] / 1000), 2))
    if reference:
        result.update(verify_source(photo, reference, data, route))
    for name, im in [('before', original), ('half', middle), ('complete', final)]:
        Image.fromarray(im).save(out / (name + '.jpg'), quality=93)
    choose(page, 'stage', 'redrawn')
    if transitions:
        # The same upload must resume its selected treatment after visits to incompatible modes.
        page.locator('#layout').select_option('garden')
        ready(page)
        assert style.is_visible() and style.input_value() == 'shadow'
        assert page.locator('#middleStageLabel').inner_text() == 'Halfway'
        page.locator('#layout').select_option('portrait')
        ready(page)
        assert style.input_value() == 'shadow' and np.array_equal(frame(page), final)
        page.locator('#portraitMode').select_option('group')
        page.locator('#portraitSubmit').click()
        ready(page)
        assert page.locator('#soloStyles').is_hidden() and page.locator('#middleStageLabel').inner_text() == 'Cleared'
        page.locator('#portraitMode').select_option('one')
        page.locator('#portraitSubmit').click()
        ready(page)
        assert style.input_value() == 'shadow' and np.array_equal(frame(page), final)
    page.locator('#keep').click()
    saved = frame(page)
    assert 'photo shadows' in page.locator('.caption').inner_text().lower()
    page.reload()
    assert 'photo shadows' in page.locator('.caption').inner_text().lower()
    assert np.abs(frame(page).astype(float) - saved).mean() < 1
    assert not upload.input_value() and not page.locator('#sourceImage').get_attribute('src')
    state = page.evaluate("Object.fromEntries(Object.entries(localStorage))")
    encoded = base64.b64encode(photo.read_bytes()).decode()
    assert encoded[len(encoded)//2:len(encoded)//2 + 512] not in json.dumps(state) + page.content()
    item = json.loads(state['oasis-ring-' + layout + '-v1'])
    assert len(base64.b64decode(item['bed'])) == len(final)**2
    assert not any('data:image/' in v for v in state.values())
    metadata = {k:v for k, v in item.items() if k != 'bed'}
    assert len(json.dumps(metadata)) < 12000, 'Unexpected embedded data outside the sand height field'
    if layout == 'garden':
        center_before_ring = frame(page)
        n = len(center_before_ring)
        y, x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
        center = np.hypot(x, y) < data['high'] - 2 * data['groove']
        choose(page, 'zone', 'middle')
        choose(page, 'stage', 'redrawn')
        ring = frame(page)
        assert np.array_equal(ring[center], center_before_ring[center])
        assert not np.array_equal(ring[~center], center_before_ring[~center])
        page.locator('#keep').click()
    page.locator('#reset').click()
    assert np.array_equal(frame(page), original)
    if transitions:
        page.locator('#centerPhoto summary').first.click()
        assert style.input_value() == 'auto'
        upload.set_input_files(group)
        page.locator('#portraitMode').select_option('group')
        page.locator('#portraitStyle').select_option('pose')
        page.locator('#portraitSubmit').click()
        ready(page)
        candidate = expected(page, False, True)
        group_dir = out / 'group'
        group_dir.mkdir(exist_ok=True)
        assert check.same_track(check.joined(export(page, group_dir), dock, dock, 'group'), np.asarray(candidate['path']))
        page.locator('#portraitMode').select_option('one')
        upload.set_input_files(no_faces())
        style.select_option('shadow')
        page.locator('#portraitSubmit').click()
        ready(page)
        assert 'no face' in page.locator('#portraitStatus').inner_text().lower()
        assert page.locator('#middleStageLabel').inner_text() == 'Cleared'
        page.reload()
        assert np.array_equal(frame(page), original), 'Unkept photo persisted'
        if page.locator('#sampleOne').count() and page.evaluate(
                "!!JSON.parse(document.querySelector('#scene').textContent).live.examples?.one"):
            page.goto(url + '?layout=portrait#example-shadows')
            ready(page)
            assert style.input_value() == 'shadow' and page.locator('#middleStageLabel').inner_text() == 'Halfway'
            style.select_option('line')
            ready(page)
            assert 'example-shadows' not in page.url
    return result


def mini_fallback(page, gallery, photo, out):
    page.goto(gallery.resolve().as_uri() + '#photos')
    assert page.locator('#soloStyle').is_visible()
    assert page.locator('#soloStyle option[value=shadow]').is_disabled()
    page.locator('#soloStyle').select_option('line')
    page.locator('#portraitFile').set_input_files(photo)
    page.locator('#portraitSubmit').click()
    ready(page)
    assert page.locator('#middleStageLabel').inner_text() == 'Cleared'
    line = expected(page, False)
    assert 2 * line['high'] / line['groove'] < 60
    assert check.same_track(check.joined(export(page, out), line['dock'], line['dock'], 'Mini'), np.array(line['path']))
    page.locator('#soloStyle').select_option('head')
    ready(page)
    assert page.locator('#photoCaption').is_enabled()
    head = expected(page, False, head=True)
    downloads = check.joined(export(page, out), head['dock'], head['dock'], 'Mini close-up')
    assert check.same_track(downloads, np.array(head['path']))
    assert not check.same_track(downloads, np.array(line['path']))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('gallery', type=Path)
    p.add_argument('solos', nargs=2, type=Path)
    p.add_argument('group', type=Path)
    p.add_argument('--mini', type=Path)
    p.add_argument('--evidence', type=Path)
    p.add_argument('--reference', nargs=2, type=Path)
    args = p.parse_args()
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        output = args.evidence or Path(temp)
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            if args.mini:
                mini = output / 'mini'
                mini.mkdir(exist_ok=True)
                page = browser.new_page(viewport={'width':390, 'height':844}, is_mobile=True)
                mini_fallback(page, args.mini, args.solos[0], mini)
                page.close()
            for layout in ('portrait', 'garden'):
                for i, photo in enumerate(args.solos):
                    context = browser.new_context(viewport={'width':390, 'height':844}, is_mobile=True)
                    net = []
                    errors = []
                    context.on('request', lambda req:net.append(req.url) if req.url.startswith(('http://', 'https://')) else None)
                    context.route('http**://**/*', lambda r:r.abort())
                    page = context.new_page()
                    page.on('pageerror', lambda e:errors.append(str(e)))
                    dest = output / f'{layout}-solo-{i+1}'
                    dest.mkdir(mode=0o700, exist_ok=True)
                    report = exercise(page, args.gallery.resolve().as_uri(), photo, args.group, dest,
                                    args.reference[i] if args.reference else None, layout, i == 0 and layout == 'portrait')
                    assert not errors and not net, (errors, net)
                    (dest / 'measurements.json').write_text(json.dumps(report, indent=2) + '\n')
                    print(f'{layout} solo {i+1}: {report}', flush=True)
                    context.close()


if __name__ == '__main__':
    main()
