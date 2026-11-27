"""Test the separated upper-lip bands with synthetic pixels and no private photographs."""

import base64
import unittest

import cv2
import numpy as np

from wide_portrait_moustache import photographed_wings


def make_scene(mode='both', angle=0.):
    width = 118
    origin = np.array([238., 344.])
    across = width * np.array([np.cos(angle), np.sin(angle)])
    down = across[::-1] * [-1, 1]
    def at(u, v):
        return (origin + u * across + v * down).tolist()

    y, x = np.indices((600, 600))
    dx, dy = x - origin[0], y - origin[1]
    u = (dx * across[0] + dy * across[1]) / width**2
    v = (dx * down[0] + dy * down[1]) / width**2
    image = np.empty((600, 600, 3), 'uint8')
    image[:] = [133, 153, 194]
    teeth = (u >= 0) & (u <= 1) & (v > .06 * np.sin(np.pi * u)) & (v < .20 * np.sin(np.pi * u))
    image[teeth] = [193, 210, 218]
    guide = -.038 - .124 * np.clip(np.sin(np.pi * u), 0, 1) - .019 * np.sin(2 * np.pi * u)
    inside = np.abs(v - guide) < .031
    if mode in ('both', 'left'):
        image[(u > -.02) & (u < .46) & inside] = [49, 57, 77]
    if mode == 'both':
        image[(u > .52) & (u < 1.018) & inside] = [44, 53, 73]
    return {'width': 7, 'diameter': 635, 'crop': {
        'png': base64.b64encode(cv2.imencode('.png', image)[1]).decode(),
        'moustache': {'corners': [at(0, 0), at(1, 0)],
                      'nose': [at(.25, -.29), at(.49, -.225), at(.72, -.27)]}}}


class MoustacheTest(unittest.TestCase):
    def test_both_wings_follow_the_photograph_when_the_head_tilts(self):
        for angle in (0, -.18, .24):
            source = make_scene(angle=angle)
            wings = photographed_wings(source)
            self.assertIsNotNone(wings)
            for wing in wings:
                xy = wing * [1, -1] * 600 / source['diameter'] + 300
                p = xy - [238, 344]
                u = (p[:, 0] * np.cos(angle) + p[:, 1] * np.sin(angle)) / 118
                v = (-p[:, 0] * np.sin(angle) + p[:, 1] * np.cos(angle)) / 118
                expected = -.038 - .124 * np.clip(np.sin(np.pi * u), 0, 1) - .019 * np.sin(2 * np.pi * u)
                self.assertLess(np.quantile(np.abs(v - expected), .9), .032)

    def test_single_wing_bare_lip_and_small_table_keep_the_existing_drawing(self):
        for mode in ('left', 'bare'):
            self.assertIsNone(photographed_wings(make_scene(mode)))
        self.assertIsNone(photographed_wings({**make_scene(), 'width': 21}))
        self.assertIsNone(photographed_wings({'crop': None}))


if __name__ == '__main__':
    unittest.main()
