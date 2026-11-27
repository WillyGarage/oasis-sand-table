"""Photographed rake illumination, its phase, and preservation of untouched sand."""
import math
import unittest

import numpy as np

from mini_inward_preview import signed_replay
from mini_ripple_render import photograph_ripples


class PhotographRipplesTest(unittest.TestCase):
    def test_horizontal_and_vertical_ridges_follow_the_new_signed_positions(self):
        y, x = np.indices((390, 390))
        for axis in (x, y):
            with self.subTest(ridges='vertical' if axis is x else 'horizontal'):
                old_angle = 2*np.pi*axis/5
                new_angle = old_angle + 1.9
                old, new = np.cos(old_angle), np.cos(new_angle)
                opening = 130 + 14*np.sin(old_angle+.3)
                actual = 130 + 14*np.sin(new_angle+.3)
                base = np.rint(130 + .9*new).astype('uint8')
                touched = np.ones_like(new)
                touched[:, :122] = 0
                result = photograph_ripples(old, new, opening, base, touched, (math.pi, 1))
                interior = np.s_[115:270, 138:270]
                error = abs(result[interior] - actual[interior]).mean()
                self.assertLess(error, .42*abs(base[interior]-actual[interior]).mean())
                self.assertGreater(np.corrcoef(result[interior].ravel(), actual[interior].ravel())[0,1], .95)
                np.testing.assert_array_equal(result[:, :122], base[:, :122])
                np.testing.assert_array_equal(result[:12, :12], base[:12, :12])

    def test_single_engraved_line_keeps_its_existing_light(self):
        y, x = np.indices((390, 390))
        previous = np.cos(2*np.pi*x/6)
        current = np.exp(-.5*((x-195)/5)**2)
        opening = 130 + 8*previous
        base = np.rint(130 - 22*current).astype('uint8')
        result = photograph_ripples(previous, current, opening, base, np.ones_like(current), (0,1))
        np.testing.assert_array_equal(result[100:290, 188:203], base[100:290, 188:203])

    def test_moving_ripples_preserve_the_partially_cut_front_and_the_opening_art(self):
        y, x = np.indices((390, 390))
        old = np.cos(2*np.pi*x/6)
        current = np.cos(2*np.pi*x/6 + 1.7)
        opening = 130 + 10*old
        base = np.uint8(np.rint(130 + current))
        contact = np.ones_like(old)
        contact[:, :150] = 0
        contact[:, 150:200] = .98
        base[:, :200] = np.uint8(np.rint(120 + 30*np.sin(y[:, :200]/24)))
        result = photograph_ripples(old, current, opening, base, contact, (0,1), moving=True)
        np.testing.assert_array_equal(result[:, :201], base[:, :201])
        region = np.s_[120:270, 225:280]
        expected = 130 + 10*current[region]
        self.assertLess(np.abs(result[region]-expected).mean(), .5*np.abs(base[region]-expected).mean())

    def test_partial_or_unphotographed_render_cannot_request_a_finished_ripple_picture(self):
        route = np.array([[0,1], [.01,1]])
        with self.assertRaisesRegex(ValueError, 'complete signed drawing'):
            signed_replay(route, route, 2, photographic_ripples=True)
        with self.assertRaisesRegex(ValueError, 'complete signed drawing'):
            signed_replay(route, route, 1, opening=np.zeros((780,780)), photographic_ripples=True)
        with self.assertRaisesRegex(ValueError, 'partial signed drawing'):
            signed_replay(route, route, 2, opening=np.zeros((780,780)), moving_ripples=True)


if __name__ == '__main__':
    unittest.main()
