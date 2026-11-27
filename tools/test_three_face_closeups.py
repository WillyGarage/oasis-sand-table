"""Inspect three separate head close-ups in the actual downloads from a guest phone.

Pass a fitted garden editor and a local photograph of three faces. If the face
picker also finds bystanders, repeat --exclude-face with their 1-based numbers.
"""

import argparse
import itertools
import json
import tempfile
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright
from scipy.spatial import cKDTree

from check_ring_scene import TOL, joined
from test_ring_group_shadows import MOBILE, submit, toggle
from test_ring_shadows import dense_route, export
from wide_portrait import chromium


def check(browser, editor, photo, excluded):
    with browser.new_page(offline=True, **MOBILE) as page, tempfile.TemporaryDirectory() as temp:
        page.goto(editor.resolve().as_uri() + '?layout=portrait#photos')
        submit(page, photo, 'heads')
        buttons = page.locator('#faceBoxes button')
        assert buttons.count() == 3 + len(excluded)
        for number in excluded:
            if buttons.nth(number - 1).get_attribute('aria-pressed') == 'true':
                toggle(page, number - 1)
        assert page.locator('#faceBoxes button[aria-pressed=true]').count() == 3
        geometry = page.evaluate("""() => {
          const s=JSON.parse(document.querySelector('#scene').textContent), g=s.live, z=g.wideCenter||s.zones.center;
          return {radius:g.radiusMM, groove:g.groove*g.radiusMM, tracking:g.trackingMarginMM,
                  high:z.transit.at(-1)[1],dock:z.transit[0]};
        }""")
        movements = joined(export(page, Path(temp)), geometry['dock'], geometry['dock'], 'three close-ups')

    # The clear visits the center and then the perimeter. The next move outside
    # the portrait area is the final dock trip. Measure only the art in between.
    high, radius, groove = (geometry[key] for key in ('high', 'radius', 'groove'))
    rho = movements[:, 1]
    center = np.flatnonzero(rho < TOL)[-1]
    first = center + np.flatnonzero(rho[center:] >= high - TOL)[0]
    end = first + np.flatnonzero(rho[first:] > high + TOL)[0]
    art = movements[first:end]
    # Ignore the tiny chord error in the sampled round perimeter.
    active = np.flatnonzero((high - art[:, 1]) * radius > groove / 12)
    runs = np.split(active, np.flatnonzero(np.diff(active) > 1) + 1)
    assert len(runs) == 3, f'Expected a separate rim visit for each person, saw {len(runs)}'
    faces = []
    for run in runs:
        section = art[run[0] - 1 : run[-1] + 2]
        xy, _ = dense_route(section, radius, groove / 12)
        assert np.linalg.norm(xy[0] - xy[-1]) < groove / 8, 'A face did not return to its rim gate'
        assert min(np.ptp(xy, axis=0)) > 5 * groove, 'A rim excursion contains no portrait'
        faces.append(xy)
    # These samples include both the artwork and its approach. Allow for the
    # sample interval as well as the specified drift on both passes.
    gaps = [float(cKDTree(a).query(b)[0].min()) for a, b in itertools.combinations(faces, 2)]
    assert min(gaps) > groove + 2 * geometry['tracking'] + groove / 12, gaps
    return {'closestCenterlinesMm': min(gaps), 'totalRows': len(movements), 'faces': len(runs)}


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('editor', type=Path)
    cli.add_argument('photo', type=Path)
    cli.add_argument('--exclude-face', type=int, action='append', default=[])
    args = cli.parse_args()
    with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        print(json.dumps(check(browser, args.editor, args.photo, args.exclude_face), indent=2))
