"""The route into a new strand must fit the photograph and stay clear of the existing engraving."""

import unittest

import numpy as np
from scipy.spatial import cKDTree

import wide_portrait as portrait
from wide_group_locks import PhotoLocks, inside_hair


class GroupLocksTest(unittest.TestCase):
    def setUp(self):
        self.source = {'width': 3., 'radius': 100., 'diameter': 180.}
        self.position = np.array([-10., 5.])
        self.scale = .6
        self.curve = np.array([[30., 0.], [30., 40.]])
        self.points = self.curve * self.scale + self.position
        # The edge of this sitter's measured hair is the x=0 line in the
        # solo portrait. The remaining clearance is in source-photo pixels.
        clearance = np.broadcast_to(np.arange(180) - 90, (180, 180))
        self.photo = PhotoLocks([], clearance, np.zeros(2), np.zeros((180, 180), np.uint8))

    def accepted(self, approach, earlier):
        points = portrait.samples(np.vstack([approach, self.points, self.points[::-1], approach]), .1)
        path = np.column_stack([np.unwrap(np.arctan2(points[:, 1], points[:, 0])),
                                np.linalg.norm(points, axis=1) / self.source['radius']])
        return inside_hair(self.photo, [self.curve], {(0, 4): path}, 0, 4, self.source,
                           self.position, self.scale, occupied=[cKDTree([earlier])])

    def test_full_stroke_in_hair_with_clear_approach(self):
        self.assertTrue(self.accepted([6., 4.], [-30., 0.]))

    def test_complete_strand_with_approach_across_a_face(self):
        self.assertFalse(self.accepted([-11., 2.], [-30., 0.]))

    def test_approach_into_an_earlier_stroke(self):
        self.assertFalse(self.accepted([6., 4.], [5., 4.]))


if __name__ == '__main__':
    unittest.main()
