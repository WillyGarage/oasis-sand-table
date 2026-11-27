"""Check offline Mini estimates against two completed gallery portraits."""
from pathlib import Path
import unittest

import numpy as np

from mini_portrait_timing import elapsed_seconds


DRAWINGS = Path(__file__).resolve().parents[1] / 'patterns/portrait-gallery/drawings'
# Relevant fields from the Mini status during both physical runs, Nov 22.
SETTINGS = dict(vmax=400, vj=200, acc=200, accc=2000,
                cal=dict(l=.46, rmax=.905, a=.000552233, a1=.000306796, b1=.000613592, b2=.000122718))


class MiniTimingTest(unittest.TestCase):
    def test_two_real_portraits_end_within_four_seconds(self):
        for name, measured in [('boardwalk-in-the-mini/grain.thr', 1716.06), ('inward-guest-portrait/flowing.thr', 1616.92)]:
            with self.subTest(name=name):
                route = np.loadtxt(DRAWINGS / name)
                clock = elapsed_seconds(route, SETTINGS)
                self.assertEqual(len(clock), len(route))
                self.assertTrue(np.all(np.diff(clock) >= 0))
                self.assertLess(abs(clock[-1] - measured), 4.)

    def test_pure_turn_at_center_takes_time_and_duplicate_points_do_not(self):
        route = [[0., 0.], [0., 0.], [np.pi, 0.], [np.pi, 0.]]
        clock = elapsed_seconds(route, SETTINGS)
        self.assertEqual(clock[0], clock[1])
        self.assertGreater(clock[2], 1.)
        self.assertEqual(clock[-1], clock[-2])
        self.assertEqual(elapsed_seconds([[.5, 1.]], SETTINGS).tolist(), [0.])


if __name__ == '__main__':
    unittest.main()
