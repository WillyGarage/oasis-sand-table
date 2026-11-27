"""Check the signed Mini portrait of Lek against the source photo and a short-haired control.

python3 tools/test_guest_inward_long_hair.py captures/family-source
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

from build_guest_center import build_guest_web_assets
from check_ring_scene import sample_walk
from test_guest_center import FramedMini, ROOT
from test_guest_inward_portrait import checked_route, distance_to_stroke, phone, preview
from wide_portrait import chromium


def engrave(browser, assets, file, face=None):
    device = FramedMini(assets)
    opening = device.status['theta'] = 256.57295
    with phone(browser, device) as page:
        page.get_by_role('button', name='Photo', exact=True).click()
        page.locator('#photoTarget').select_option('full')
        page.locator('#file').set_input_files(file)
        style = page.locator('#inwardPortrait')
        style.select_option('inward')
        preview(page)
        page.evaluate("""() => {
            const plan = GuestInwardPortrait.plan;
            GuestInwardPortrait.plan = (contours, theta) => {
                const drawing = plan(contours, theta);
                window.observed = {contours, text:drawing.text};
                return drawing;
            };
        }""")
        style.select_option('engraved')
        preview(page)
        if face is not None:
            buttons = page.locator('#faceBoxes button')
            expect(buttons).to_have_count(2)
            buttons.nth(face).click()
            expect(page.locator('#draw')).to_be_enabled(timeout=20000)
        page.locator('#draw').click()
        expect(page.locator('#message')).to_contain_text('started')
        observed = page.evaluate('window.observed')
    assert device.uploads == [observed['text']] and device.started == 1
    path = checked_route(device.staged, opening)
    curves = [np.asarray(line) for line in observed['contours']]
    extent = max(np.linalg.norm(line, axis=1).max() for line in curves)
    lines = [line * ((114.03 - 5.32 / 2) / extent) for line in curves]
    # The path that was actually sent should visit each outline and strand.
    sand = cKDTree(sample_walk(path, .001) * 114.03)
    for line in lines:
        assert sand.query(line)[0].max() < .16
    return lines, extent


def redwoods(lines, extent):
    outer, jaw, eye = lines[:3]
    np.testing.assert_allclose(extent, 1, atol=1e-8)
    np.testing.assert_allclose(outer[1], outer[-1])
    # The two outer corners were 18.89 mm apart on the preceding real Mini
    # portrait. Cropping the hair must preserve the photographed facial scale.
    assert abs(np.linalg.norm(eye[3] - eye[0]) - 18.89) < .15
    assert min(line[:, 1].min() for line in lines[7:]) < jaw[:, 1].min() - 8

    # Locations sampled on the original photo, measured in mm from the outer
    # eye corner at the same scale. The reddish tree adjoins the crown.
    crown = [[5.56, 103.09], [22.04, 110.21], [36.27, 111.33],
             [45.64, 110.96], [55.75, 109.08], [77.48, 100.84]]
    shirt = [[-43.63, -15.65], [-44.56, -19.40], [-45.96, -23.89], [-41.08, -37.00],
             [-39.93, -41.87], [-34.22, -46.74], [-33.92, -51.98], [-35.79, -57.23],
             [-37.92, -63.22], [-40.67, -68.47], [-44.34, -74.46]]
    errors = [distance_to_stroke(eye[0] + point, outer) for point in crown]
    assert max(errors) < 3
    errors = [distance_to_stroke(eye[0] + point, outer) for point in shirt]
    assert max(errors) < 4.8 and np.median(errors) < 1.5


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('source', type=Path, help='Private directory with the original family photos')
    args = cli.parse_args()
    with TemporaryDirectory() as temp, sync_playwright() as w, w.chromium.launch(executable_path=chromium(w, None)) as browser:
        assets = Path(temp)
        build_guest_web_assets(ROOT / 'web', assets, mini_only=True)
        redwoods(*engrave(browser, assets, args.source / 'nov21/redwood-pair.jpg', face=1))
        short, _ = engrave(browser, assets, args.source / 'thomas.jpg')
        # Thomas's short hair keeps its closed head contour from the previous
        # portrait, with the real crown and chin at opposite ends of the crop.
        head = short[0]
        assert head[:, 1].max() > 107 and head[:, 1].min() < -107
        assert np.linalg.norm(head[1] - head[-1]) > 4
    print('Verified the photographed crown, hair against the shirt, original eye scale,')
    print('long locks on the signed drawing, and the short-haired control.')


if __name__ == '__main__':
    main()
