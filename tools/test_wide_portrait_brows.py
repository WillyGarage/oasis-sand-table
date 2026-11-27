"""The brow search must distinguish photographed hair from nearby eyes and shadows."""

import unittest

import numpy as np

from wide_portrait import overlapping_brow_shadows, shadows_following_brow
from wide_portrait_brows import brow_stroke, darker_than_earlier_brow


class BrowTest(unittest.TestCase):
    def scene(self, angle, sign, band=True, exposure=1):
        y, x = np.indices((180, 180))
        across = sign * np.array([np.cos(angle), np.sin(angle)])
        down = np.array([-np.sin(angle), np.cos(angle)])
        xy = np.stack([x - 90, y - 77], axis=-1)
        u, v = xy @ across, xy @ down
        arch = .0023 * u**2
        light = 180 + .12 * v
        if band:
            light -= 90 * np.exp(-.5 * ((v - arch) / 3.0)**2)
        light -= 120 * np.exp(-.5 * ((v - 26) / 2.5)**2)
        span = np.linspace(-31, 31, 5)
        brow = [90, 77] + span[:, None]*across + (.0023*span**2 - 6)[:, None]*down
        eye = [90, 77] + span[:, None]*across + 26*down
        pixels = np.clip(exposure * light, 0, 255).astype('uint8')
        return pixels, brow, eye, across, down

    def test_tilted_brow_tracks_the_band_on_both_sides(self):
        for angle, sign, exposure in ((.46, -1, 1), (-.23, 1, .68)):
            im, brow, eye, across, down = self.scene(angle, sign, exposure=exposure)
            stroke = brow_stroke(im, brow, eye, 4)
            self.assertIsNotNone(stroke)
            local = stroke - [90, 77]
            self.assertLess(np.max(np.abs(local @ down - .0023*(local @ across)**2)), 1.6)

    def test_lid_and_uneven_light_do_not_create_a_brow(self):
        im, brow, eye, _, _ = self.scene(.27, 1, band=False)
        for broad in (True, False):
            self.assertIsNone(brow_stroke(im, brow, eye, 4, broad=broad))

    def test_a_line_already_on_the_hair_is_retained(self):
        im, brow, eye, _, down = self.scene(-.24, 1)
        self.assertIsNone(brow_stroke(im, brow + 6*down, eye, 4))

    def test_independent_guide_needs_a_darker_brow_at_the_same_columns(self):
        for tilt, sign in ((.31, 1), (-.32, -1)):
            im, old, eye, _, down = self.scene(tilt, sign)
            line = brow_stroke(im, old + 6 * down, eye, 4, anatomy=True)
            self.assertIsNotNone(line)
            self.assertTrue(darker_than_earlier_brow(im, line, old, 4))
            self.assertFalse(darker_than_earlier_brow(im, line, line, 4))
            self.assertFalse(darker_than_earlier_brow(np.full_like(im, 100), line, old, 4))

    def test_only_a_drawn_parallel_shadow_can_be_shortened(self):
        brow = dict(kind='brow', closed=False, points=[[20., 5.], [60., 5.]])
        def shade(points):
            return dict(kind='shade', points=points, closed=False)

        marks = [shade([[22., 5.5], [47., 5.5], [52., -11.]]),
                 shade([[40., -13.], [40., 19.]]),
                 shade([[31., 5.8], [40., 5.8]]),
                 shade([[22., 5.8], [52., 5.8]]),
                 shade([[38., 5.4], [38., 5.4]])]
        paths, events = [], {}
        for i, mark in enumerate(marks):
            q = np.asarray(mark['points'])
            if i == 3:  # The planner skipped the close end of this line.
                q = np.array([[49., 5.8], [52., 5.8]])
            line = np.concatenate([np.linspace(a, b, 50) for a, b in zip(q, q[1:])])
            polar = np.column_stack([np.arctan2(line[:, 1], line[:, 0]), np.linalg.norm(line, axis=1) / 100.])
            start = sum(len(path) for path in paths)
            events[i] = dict(first=start, last=start + len(line) - 1)
            paths.append(polar)
        self.assertEqual(shadows_following_brow(brow, marks, events, np.vstack(paths), 100., 4.), {0})

    def test_only_a_shadow_following_the_same_brow_can_merge(self):
        brow = {'kind': 'brow', 'closed': False, 'points': [[0, 0], [20, 4], [40, 1]]}
        same_hair = {'kind': 'shade', 'closed': False, 'points': [[6, 3], [18, 5], [29, 4]]}
        cross = {**same_hair, 'points': [[19, -10], [20, 4], [21, 16]]}
        short_lid = {**same_hair, 'kind': 'eye'}
        beard = {**same_hair, 'facialHair': True}
        lines = [brow, same_hair, cross, short_lid, beard]
        self.assertEqual(overlapping_brow_shadows(brow, lines, range(len(lines)), 7), {1})


if __name__ == '__main__':
    unittest.main()
