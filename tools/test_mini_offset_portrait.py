import io
import math
from pathlib import Path
import unittest

import numpy as np
from scipy.spatial import cKDTree

from mini_bed_preview import RADIUS_MM
from mini_inward_portrait import movement_files
from mini_offset_portrait import compile_offset_portrait
from wide_portrait import excursion_cloud, samples


class OffsetPortraitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gallery = Path(__file__).resolve().parents[1] / 'patterns/portrait-gallery/drawings/boardwalk-in-the-mini'
        with np.load(cls.gallery/'cheek-inward-strokes.npz', allow_pickle=False) as stored:
            cls.marks = dict(stored)
        marks = {name: points for name, points in cls.marks.items() if name != 'exit'}
        cls.dock = np.loadtxt(cls.gallery/'grain.thr')[-1]
        route, cls.record = compile_offset_portrait(marks, cls.marks['exit'], cls.dock[0])
        cls.part, = movement_files(route)
        cls.signed = np.loadtxt(io.StringIO(cls.part['text']))

    def test_reproduces_one_signed_file_from_the_previous_physical_dock(self):
        self.assertEqual(self.part['text'].encode('ascii'), (self.gallery/'cheek-inward.thr').read_bytes())
        np.testing.assert_array_equal(self.signed[0], self.dock)
        self.assertEqual(self.signed[-1, 1], 1.)
        self.assertAlmostEqual(self.signed[-1, 0]-self.dock[0], math.tau, places=7)
        self.assertEqual(len(self.signed), 9850)
        self.assertLessEqual(np.abs(np.diff(self.signed[:, 0])).max(), .055001)
        self.assertEqual(self.signed[:, 1].min(), 0.)
        self.assertEqual(self.signed[:, 1].max(), 1.)

    def test_signed_art_matches_every_measured_mark_in_both_directions(self):
        self.assertCountEqual([event['label'] for event in self.record['events']], self.marks)
        for event in self.record['events']:
            with self.subTest(mark=event['label']):
                original = samples(self.marks[event['label']]*RADIUS_MM, .1)
                cut = excursion_cloud(self.signed, event, RADIUS_MM, .1)
                self.assertLess(cKDTree(cut).query(original)[0].max(), .1)
                self.assertLess(cKDTree(original).query(cut)[0].max(), .1)

    def test_every_non_art_move_follows_the_offset_spiral_or_the_rim(self):
        center = np.array(self.record['center'])*RADIUS_MM
        extent = RADIUS_MM+np.linalg.norm(center)
        pitch = self.record['spacingMm']
        covered = np.zeros(len(self.signed)-1, dtype=bool)
        for a, b in self.record['eraseSpans']:
            covered[a:b] = True
            cut = excursion_cloud(self.signed, {'first': a, 'last': b}, RADIUS_MM, .12)-center
            radius = np.linalg.norm(cut, axis=1)
            bearing = np.arctan2(cut[:, 1], cut[:, 0])
            phase = bearing-self.record['opening']-math.tau*(extent-radius)/pitch
            radial_error = abs((phase+math.pi) % math.tau-math.pi)*pitch/math.tau
            # The spiral ends at the cheek. Very near its tip, the distance
            # back to that endpoint also bounds the geometric error.
            self.assertLess(np.minimum(radial_error, radius).max(), .08)
        for event in self.record['events']:
            covered[event['first']:event['last']] = True
        self.assertTrue(np.any(~covered))
        np.testing.assert_array_equal(self.signed[:-1, 1][~covered], 1.)
        np.testing.assert_array_equal(self.signed[1:, 1][~covered], 1.)

    def test_requires_an_interior_offset_origin_and_a_real_rim_exit(self):
        for outline in ([[0., 0.], [1., 0.]], [[.5, .3], [.9, .0]], [[1., 0.], [0., 1.]]):
            with self.subTest(outline=outline), self.assertRaisesRegex(ValueError, 'outline'):
                compile_offset_portrait({}, outline, 0.)
        with self.assertRaisesRegex(ValueError, 'spacing'):
            compile_offset_portrait({}, [[.2, .2], [1., 0.]], 0., spacing_mm=6.)


if __name__ == '__main__':
    unittest.main()
