"""Regression for a tilted nose whose model crosses the skin above a second shadow edge."""

import unittest

import numpy as np
from scipy.special import expit

from wide_portrait_nose import ambiguous_underside


class NoseBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.groove = 7.
        self.center = np.array([80., 80.])
        self.y, self.x = np.indices((161, 161))

    def competing_edge(self, angle, mirror, patch_width, old_depth=1.8):
        c, s = np.cos(angle), np.sin(angle)
        lateral = np.array([c, s]) * (-1 if mirror else 1)
        down = np.array([-s, c])
        coords = np.stack([self.x - self.center[0], self.y - self.center[1]], axis=-1)
        across = coords @ lateral
        below = coords @ down
        # Both source boundaries have the same polarity. The lower one is
        # visible only within a lateral patch beside the tip.
        competing = np.abs(across - 10) < patch_width / 2
        intensity = (210 - 43 * expit(below / 1.1)
                     - 44 * competing * expit((below - 1.8 * self.groove) / 1.1))
        line = self.center + np.linspace(-32, 32, 15)[:, None] * lateral
        old = line + old_depth * self.groove * down
        return ambiguous_underside(intensity.astype('float32'), old, line, lateral, down, self.groove)

    def test_clear_lower_edge_survives_tilt_and_reflection(self):
        for angle in (-.6, .37):
            for mirror in (True, False):
                with self.subTest(angle=angle, mirror=mirror):
                    self.assertTrue(self.competing_edge(angle, mirror, 3.2 * self.groove))
                    self.assertFalse(self.competing_edge(angle, mirror, .35 * self.groove))

    def test_a_clear_edge_or_two_already_matching_routes_are_kept(self):
        self.assertFalse(self.competing_edge(-.6, False, 0))
        self.assertFalse(self.competing_edge(-.6, False, 4 * self.groove, old_depth=.45))


if __name__ == '__main__':
    unittest.main()
