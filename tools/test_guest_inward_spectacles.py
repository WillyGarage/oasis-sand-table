"""Check the Mini's separate eyelid grooves on two photos of a person in glasses.

Pass the restaurant and redwoods group photographs. The leftmost face is used.
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from playwright.sync_api import sync_playwright

from build_guest_center import build_guest_web_assets
from test_guest_inward_pair import simulated_mini, submit
from test_guest_inward_portrait import phone
from test_guest_reviewed_portrait import open_face
from wide_portrait import chromium


def check(browser, assets, photo):
    opening = 400.55306
    device = simulated_mini(assets, opening)
    with phone(browser, device) as page:
        open_face(page, photo, 0)
        proof = page.evaluate("""async opening => {
          const file = document.querySelector('#file').files[0];
          const options = {face:0, portraitFraming:'head',
            portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')};
          const usual = await GuestPhoto.fromFile(file,options);
          const face = await GuestPhoto.fromFile(file,{...options,inwardContours:true});
          const lines = face.inwardContours.concat(face.inwardHair);
          return {
            sameOutline:JSON.stringify(usual.points)===JSON.stringify(face.points),
            eyes:face.inwardContours.slice(-2),
            earlier:face.inwardContours.slice(0,-2),
            text:GuestInwardPortrait.plan(lines,opening,{quietFace:true}).text
          };
        }""", opening)
        submit(page, device)
        assert device.staged == proof['text'] and proof['sameOutline']
    bounds = []
    for eye in map(np.asarray, proof['eyes']):
        assert len(eye) >= 9
        np.testing.assert_array_equal(eye, eye[::-1])
        bounds.append([eye[:, 0].min(), eye[:, 0].max()])
        # The old drawing connected the eye directly to its spectacle rim.
        for old in map(np.asarray, proof['earlier']):
            edges = np.roll(old, -1, axis=0) - old
            for point in eye:
                fraction = ((point-old)*edges).sum(axis=1) / np.maximum(1e-15, (edges**2).sum(axis=1))
                nearest = old + edges * np.clip(fraction, 0, 1)[:, None]
                assert np.min(np.linalg.norm(nearest-point, axis=1)) > .02
    assert bounds[0][1] < bounds[1][0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('restaurant', type=Path)
    parser.add_argument('redwoods', type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as temp, sync_playwright() as pw:
        assets = Path(temp)
        build_guest_web_assets(Path(__file__).resolve().parents[1]/'web', assets, mini_only=True)
        with pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
            for photo in [args.restaurant, args.redwoods]:
                check(browser, assets, photo)
    print('Both phone downloads contain separately drawn eyes with open space around them.')
