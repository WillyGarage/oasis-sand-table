"""Check the Mini guest's two same-size smile treatments in the restaurant group photo.

python3 tools/test_guest_single_smile.py captures/family-source/nov21/restaurant-three.jpg
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

from build_guest_center import build_guest_web_assets
from check_ring_scene import sample_walk
from test_guest_inward_pair import RADIUS_MM, open_photo, simulated_mini, submit
from test_guest_inward_portrait import check_rim_letters, phone, preview
from wide_portrait import chromium


def portrait(browser, assets, photo, style, name='', face=2):
    device = simulated_mini(assets, 375.42036)
    with phone(browser, device) as page:
        open_photo(page, photo, group=False, style='quiet-engraved')
        preview(page)
        page.locator('#faceBoxes button').nth(face).click()
        expect(page.locator('#draw')).to_be_enabled(timeout=20000)
        select = page.locator('#soloSmile')
        expect(select).to_have_value('original')
        select.select_option('open')
        expect(page.locator('#effect')).to_contain_text('both photographed corners')
        if style != 'open':
            select.select_option(style)
            expect(page.locator('#draw')).to_be_enabled(timeout=20000)
        if name:
            page.get_by_label('Name under the portrait').fill(name)
            preview(page)
            expect(select).to_be_visible()
            expect(select).to_have_value(style)
            expect(page.locator('#effect')).to_contain_text('follows the lower rim')
        chosen = page.evaluate("""async ([style,name,face])=>{
          const r=await GuestPhoto.fromFile(document.querySelector('#file').files[0],{
            face,portraitFraming:'head',inwardContours:true,
            portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
          const lines=style==='original' ? r.inwardContours : r.soloSmile[style];
          const contours=lines.concat(r.inwardHair);
          const intended=name
            ? await GuestInwardPortrait.namedPlan(contours,375.42036,name,{quietFace:true})
            : GuestInwardPortrait.plan(contours,375.42036,{quietFace:true});
          return {lines,old:r.inwardContours,expected:intended.text};
        }""", [style, name, face])
        signed = submit(page, device)
        if name:
            check_rim_letters(page, signed, name)
    assert chosen['expected'] == device.staged
    return chosen, signed


def exercise(browser, assets, photo):
    earlier, earlier_route = portrait(browser, assets, photo, 'original')
    line, line_route = portrait(browser, assets, photo, 'line')
    opened, open_route = portrait(browser, assets, photo, 'open')
    signed_original, _ = portrait(browser, assets, photo, 'original', 'Mom')
    signed_open, _ = portrait(browser, assets, photo, 'open', 'Mom')
    assert signed_original['expected'] != signed_open['expected']
    assert signed_open['lines'] == opened['lines']
    assert earlier['old'] == earlier['lines'] == opened['old'] == line['old']
    assert line['lines'][:-1] == opened['lines'][:-1]
    assert earlier['lines'][0] == opened['lines'][0] and earlier['lines'][-1] == opened['lines'][-2]
    assert len({len(route) for route in (earlier_route, line_route, open_route)}) == 3
    scale = (RADIUS_MM - 5.32 / 2) / max(np.linalg.norm(curve, axis=1).max() for curve in earlier['lines'])
    lower = np.asarray(line['lines'][-1][:25]) * scale
    loop = np.asarray(opened['lines'][-1]) * scale
    np.testing.assert_array_equal(loop[:len(lower)], lower)
    upper = np.vstack([loop[0], loop[25:][::-1], loop[24]])
    opening = np.linalg.norm(upper - lower, axis=1)
    assert 8 < max(opening) < 13 and 55 < np.linalg.norm(loop[24] - loop[0]) < 66
    sand = cKDTree(sample_walk(open_route, .0008) * RADIUS_MM)
    assert sand.query(loop)[0].max() < .18

    # The first sitter wears glasses. Replacing the cartoon lip loop must
    # keep both separate eyelids, their rims and the head at the same scale.
    framed, _ = portrait(browser, assets, photo, 'open', face=0)
    old = framed['old']
    new = framed['lines']
    assert len(new) == len(old) + 1
    changed = [i for i,(before,after) in enumerate(zip(old,new)) if before != after]
    assert len(changed) == 1 and 0 < changed[0] < len(old) - 2
    assert len(new[changed[0]]) < len(old[changed[0]]) and len(new[-1]) == 48
    for lid in new[-3:-1]:
        assert len(lid) >= 9 and lid == lid[::-1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('photo', type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as temp, sync_playwright() as sw:
        assets = Path(temp)
        build_guest_web_assets(Path(__file__).resolve().parents[1] / 'web', assets, mini_only=True)
        with sw.chromium.launch(executable_path=chromium(sw, None)) as browser:
            exercise(browser, assets, args.photo)
    print('The original, single line and open smile matched their guest downloads and the same-size face.')
