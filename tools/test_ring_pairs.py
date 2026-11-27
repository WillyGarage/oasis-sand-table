#!/usr/bin/env python3
"""Download guest-request drawings from the real phone controls and measure both subjects.

    python3 tools/test_ring_pairs.py gallery.html --previous previous-gallery.html --evidence DIR
The shared-phone part uses an isolated local garden without a table controller.
"""

import argparse
import io
import json
import math
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.optimize import differential_evolution
from scipy.spatial import cKDTree

import check_ring_scene as check
import ring_scene
from test_guest_place import physical_parts, unpack
from test_garden_room import caption, choose, drawing_files, keep, open_room, room, suggest
from test_ring_photo import frame
from test_ring_shadows import dense_route, replay

MOBILE = dict(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
LEAN = 'a guitar leaning against my books'
ABOVE = 'a comet over a telescope'
REVERSE = 'a telescope over a comet'
PAIR_ID = 'pair-above-symbol-2604__telescope'


def visit(page, gallery, fragment='guests'):
    page.goto('about:blank')
    page.goto(gallery.resolve().as_uri() + '?layout=garden#' + fragment)


def geometry(page):
    return page.evaluate("""()=> {
      const scene=JSON.parse(document.querySelector('#scene').textContent), c=scene.live.planner;
      const normal=OasisRingPlanner.plan(c,c.defaults);
      return {...c.geometry,defaults:c.defaults,places:c.places,
        groove:scene.live.groove,dock:normal.path[0],transit:normal.segments[0],
        prefix:OasisRingPlanner.join(normal.segments.slice(0,2))};
    }""")


def stock_route(page, ids, local=False):
    return np.asarray(
        page.evaluate(
            """([ids,local])=>{const c=JSON.parse(document.querySelector('#scene').textContent).live.planner;
              return (local ? OasisRingPlanner.planChange(c,c.defaults,ids) : OasisRingPlanner.plan(c,ids)).path;}""",
            [ids,local],
        )
    )


def tracks(files, geom, dest=None, slot=None):
    if dest:
        dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name, data in files:
            assert Path(name).name == name
            (dest / name).write_bytes(data)
    parts = [np.loadtxt(io.BytesIO(data)) for _, data in files]
    for a, b in zip(parts, parts[1:]):
        np.testing.assert_array_equal(a[-1], b[0])
    route = check.joined(parts, geom['dock'], geom['dock'], 'middle guest ring')
    if slot is not None and geom.get('places'):
        place = geom['places'][slot]
        parts = physical_parts(route, place, {'geometry':geom})
        return route, parts[2][len(unpack(place['recut']))-1:]
    np.testing.assert_allclose(route[: len(geom['prefix'])], geom['prefix'], atol=5.001e-6, rtol=0)
    low, high = geom['bounds']
    assert route[:, 1].min() >= low - check.TOL
    outside = route[:, 1] > high + check.TOL
    assert check.seam_segments(route, -math.pi / 2)[outside[:-1] | outside[1:]].all()
    art = route[len(geom['prefix']) - 1 : len(route) - len(geom['transit']) + 1]
    assert np.max(art[:, 1]) <= high + check.TOL
    return route, art


def local_tree(art, geom, slot):
    # Isolate actual post-erase engraving. Spiral crossings cannot satisfy a missing picture.
    xy, _ = dense_route(art, 1, geom['groove'] * 0.05)
    a = geom['angles'][slot]
    points = (xy - geom['center'] * np.array([math.cos(a), math.sin(a)])) / geom['scale']
    return cKDTree(points[np.linalg.norm(points, axis=1) < 1.01])


def sample(lines, spacing=0.025):
    out = []
    for line in lines:
        p = np.asarray(line)
        ds = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
        if ds[-1] == 0:
            continue
        d = np.linspace(0, ds[-1], max(2, math.ceil(ds[-1] / spacing)))
        out.append(np.column_stack([np.interp(d, ds, v) for v in p.T]))
    return np.vstack(out)


def comet_signature(mirrored):
    # Independent visual landmarks in nucleus radii. The nearly circular head
    # closes completely. Each rightward tail has its own tip and two flanks.
    a = np.linspace(0, math.tau, 65)
    nucleus = np.column_stack((np.cos(a), np.sin(a)))
    upper_tail = np.array([[2.45, 1.18], [3.75, 1.10], [5.26, 0.86], [3.63, 0.61], [2.47, 0.43]])
    lower_tail = np.array([[2.5, 0.25], [3.55, 0.2], [4.71, 0.02], [3.29, -0.13], [2.44, -0.27]])
    angle = math.radians(20)
    turn = np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]])
    reflection = [-1, 1] if mirrored else [1, 1]
    return [((line * 0.245 + [-0.48, 0]) @ turn) * reflection for line in (nucleus, upper_tail, lower_tail)]


def locate(tree, lines, top, width):
    """Fit a uniform scale and translation; disallow mirroring or shape deformation."""
    source = sample(lines)
    probe = source[:: max(1, len(source) // 160)]

    def error(params):
        x, y, scale = params
        return np.mean(tree.query(probe * scale + [x, y])[0] ** 2)

    y = (-0.75, -0.035) if not top else (0.035, 0.75)
    fit = differential_evolution(
        error, [(-0.75, 0.75), y, (0.32, 0.9)], seed=2, popsize=18, maxiter=100, tol=1e-7
    )
    x, y, scale = fit.x
    miss = tree.query(source * scale + [x, y])[0] / width
    assert np.percentile(miss, 95) < 0.25 and max(miss) < 0.65, (
        'source contour missing',
        fit.x,
        np.percentile(miss, 95),
        max(miss),
    )
    return {
        'center': [round(x, 3), round(y, 3)],
        'scale': round(scale, 3),
        'p95_grooves': round(float(np.percentile(miss, 95)), 3),
    }


def protected_mask(im, geom):
    n = len(im)
    y, x = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
    r = np.hypot(x, y)
    lo, hi = geom['bounds']
    g = geom['groove']
    # The center is never touched. The one transit stem crosses the lower border.
    return (r < lo - 3 * g) | ((r > hi + 3 * g) & (r < 0.985) & ((y <= 0) | (abs(x) > 3 * g)))


def checked(page, geom, before, initial_ids, slot, folder):
    files = drawing_files(page, '#downloads')
    route, art = tracks(files, geom, folder, slot)
    image = frame(page)
    untouched = protected_mask(image, geom)
    assert np.array_equal(image[untouched], before[untouched])
    choose(page, 'stage', 'cleared')
    cleared = frame(page)
    assert np.array_equal(cleared[untouched], before[untouched])
    choose(page, 'stage', 'redrawn')
    replayed = replay(page, route)
    delta = abs(image.astype(np.int16) - replayed.astype(np.int16))
    assert delta.mean() < 1.1 and np.percentile(delta, 99) < 5, ('download vs phone', delta.mean())
    for other, subject in enumerate(initial_ids):
        if other == slot:
            continue
        if geom.get('places'):
            g = geom['groove']
            a = geom['angles'][other]
            center = np.array([math.cos(a),math.sin(a)])*geom['center']
            sibling = sample([ring_scene.motif(subject)])*geom['scale']+center
            motion = cKDTree(check.sample_walk(route,g/12))
            assert motion.query(sibling)[0].min() > 1.2*g, ('ball approached a neighboring subject',subject)
            # Every pixel on these neighboring contours is the same at both stages.
            yy,xx = np.mgrid[1:-1:complex(len(image)),-1:1:complex(len(image))]
            region = (np.hypot(xx-center[0],yy-center[1]) < geom['scale']+g)
            near = cKDTree(sibling).query(np.column_stack((xx[region],yy[region])))[0] < .75*g
            assert near.sum()>40
            for stage in (cleared,image):
                assert np.array_equal(stage[region][near],before[region][near])
        else:
            error = local_tree(art, geom, other).query(ring_scene.motif(subject))[0]
            assert max(error) < 0.002, ('another guest changed', subject, max(error))
    if folder:
        Image.fromarray(image).save(folder / 'sand.jpg', quality=90)
    return files, route, local_tree(art, geom, slot)


def refused(page, words):
    page.locator('#idea').fill(words)
    page.get_by_role('button', name='Preview suggestion').click()
    expect(page.locator('#error')).to_be_visible()
    assert page.locator('#sketch').evaluate('el=>el.open')
    assert page.locator('#keep').is_hidden() and page.locator('#downloads').is_hidden()


def shared_pair(browser, gallery, database):
    with room(gallery, database) as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        for context in (a, b):
            context.route(
                'http**://**/*',
                lambda route: route.continue_() if route.request.url.startswith(url + '/') else route.abort(),
            )
        first, second = a.new_page(), b.new_page()
        open_room(first, url)
        open_room(second, url)
        suggest(first, ABOVE + ' for Thomas')
        files = drawing_files(first, '#downloads')
        keep(first)
        # Compare the kept composition on both phones. The preceding preview
        # also describes the erase, which varies with the garden layout.
        caption(first, 'Thomas · Comet above telescope')
        pair = first.locator('.caption').inner_text()
        caption(second, pair)
        assert drawing_files(second, '#roomFiles') == files
        before = frame(second)
        choose(second, 'zone', 'outer')
        choose(second, 'stage', 'redrawn')
        keep(second)
        after = frame(second)
        geom = geometry(second)
        n = len(before)
        y, x = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
        r = np.hypot(x, y)
        middle = (r > geom['bounds'][0]) & (r < geom['bounds'][1])
        assert np.array_equal(before[middle], after[middle]) and np.any(before[~middle] != after[~middle])
        choose(second, 'zone', 'middle')
        caption(second, pair)
        assert drawing_files(second, '#roomFiles') == files
        stored = second.request.get(url + '/api/garden/garden').json()['state']
        assert stored['ids'] == [PAIR_ID, 'books', 'temple']
        suggest(second, 'replace the comet above the telescope with a rocket')
        caption(second, 'Thomas · Rocket')
        assert 'Alex · Stack of books' in second.locator('.caption').inner_text()
        return {'identical_files': len(files), 'unchanged_middle_pixels': int(middle.sum())}


def exercise(browser, args, out):
    errors = []
    with browser.new_context(**MOBILE) as private:
        private.route('http**://**/*', lambda route: route.abort())
        current, previous = private.new_page(), private.new_page()
        for page in (current, previous):
            page.on('pageerror', lambda e: errors.append(str(e)))
        visit(previous, args.previous)
        suggest(previous, LEAN + ' for Alex')
        caption(previous, 'Alex · Acoustic guitar')
        old = drawing_files(previous, '#downloads')
        visit(current, args.gallery)
        original = frame(current)
        geo = geometry(current)
        ids = geo['defaults']
        suggest(current, LEAN + ' for Alex')
        caption(current, 'Alex · Guitar leaning on books')
        native, native_route, tree = checked(current, geo, original, ids, 1, out / 'guitar-books')
        assert native != old
        np.testing.assert_allclose(
            native_route, stock_route(current, ['phage', 'guitar_books', 'temple'],local=bool(geo.get('places'))), atol=5.001e-6, rtol=0
        )
        before_route, _ = tracks(old, geo)
        np.testing.assert_allclose(
            before_route, stock_route(previous, ['phage', 'guitar', 'temple']), atol=5.001e-6, rtol=0
        )
        assert tree.query(ring_scene.motif('guitar_books'))[0].max() < 0.002
        # The same request without a name indicates the guest whose books are already drawn.
        visit(current, args.gallery)
        suggest(current, LEAN)
        assert drawing_files(current, '#downloads') == native
        visit(current, args.gallery, 'example-guitar-books')
        caption(current, 'Alex · Guitar leaning on books')
        assert drawing_files(current, '#downloads') == native
        report = {}
        for words, above in ((ABOVE, 'comet'), (REVERSE, 'telescope')):
            visit(current, args.gallery)
            suggest(current, words + ' for Thomas')
            title = current.locator('.caption').inner_text().lower()
            assert 'thomas' in title and 'comet' in title and 'telescope' in title
            files, route, tree = checked(current, geo, original, ids, 0, out / (above + '-above'))
            native_telescope = [ring_scene.motif('telescope')]
            comet = comet_signature(mirrored=above == 'comet')
            width = geo['groove'] / geo['scale']
            pos = {
                'telescope': locate(tree, native_telescope, above == 'telescope', width),
                'comet': locate(tree, comet, above == 'comet', width),
            }
            below = 'telescope' if above == 'comet' else 'comet'
            assert pos[above]['center'][1] - pos[below]['center'][1] > 0.35
            if above == 'comet':
                # Register the independently measured semicircular objective and
                # the round nucleus against the actual travel.
                glass = native_telescope[0][[0, 9, 18]] * pos['telescope']['scale'] + pos['telescope']['center']
                axis = glass[1] - (glass[0] + glass[2]) / 2
                axis /= np.linalg.norm(axis)
                nucleus_points = comet[0][:-1] * pos['comet']['scale'] + pos['comet']['center']
                nucleus = nucleus_points.mean(axis=0)
                radius = np.linalg.norm(nucleus_points[0] - nucleus)
                sight = nucleus - glass[1]
                sideways = abs(axis[0] * sight[1] - axis[1] * sight[0]) / width
                gap = (sight @ axis - radius) / width
                assert sideways < 0.25 and 4.4 < gap < 5.2, ('telescope misses the comet', sideways, gap)
                pos['aim'] = {
                    'perpendicular_error_grooves': round(float(sideways), 3),
                    'glass_to_comet_grooves': round(float(gap), 2),
                }
            report[above + '-above'] = pos
            if above == 'comet':
                visit(current, args.gallery, 'example-comet-telescope')
                assert drawing_files(current, '#downloads') == files
                visit(current, args.gallery)
                suggest(current, 'a telescope under a comet for Thomas')
                assert drawing_files(current, '#downloads') == files
        visit(current, args.gallery)
        suggest(current, 'a violin above a telescope for Lek')
        caption(current, 'Lek')
        _, _, tree = checked(current, geo, original, ids, 2, out / 'violin-above')
        glyph = current.evaluate("GuestArt.glyphIdea('violin').glyph")
        violin = current.evaluate("ch=>GuestArt.glyphStrokes(ch)", glyph)
        width = geo['groove'] / geo['scale']
        report['violin-above'] = {
            'violin': locate(tree, violin, True, width),
            'telescope': locate(tree, [ring_scene.motif('telescope')], False, width),
        }
        for text in (
            'a comet above a zqxwy for Thomas',
            'a comet above a telescope and a rocket for Thomas',
            'a rocket inside a pumpkin for Thomas',
        ):
            visit(current, args.gallery)
            refused(current, text)
        visit(current, args.gallery)
        visit(previous, args.previous)
        for p in (current, previous):
            suggest(p, 'a leafy pumpkin for Alex')
            caption(p, 'Alex · Pumpkin')
        # Local layouts change how the ball gets there, retaining the exact native pumpkin.
        received = drawing_files(current, '#downloads')
        earlier = drawing_files(previous, '#downloads')
        if geo.get('places'):
            _, art = tracks(received,geo,slot=1)
            _, old_art = tracks(earlier,geo)
            target = ring_scene.motif('pumpkin')
            for track in (art,old_art):
                assert local_tree(track,geo,1).query(target)[0].max() < .002
        else:
            assert received == earlier
        assert not errors, errors
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('gallery', type=Path)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--evidence', type=Path)
    args = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        out = args.evidence or Path(tmp)
        out.mkdir(mode=0o700, parents=True, exist_ok=True)
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report = exercise(browser, args, out)
            report['two-phones'] = shared_pair(browser, args.gallery, Path(tmp) / 'room.db')
            (out / 'measurements.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
