"""A wider group head needs both an engraved peak and photographed hair above the former crop."""

import unittest
from types import SimpleNamespace

import numpy as np

import wide_portrait as portrait
from wide_group_crown import eye_frame, place_crown, signed_crown
from wide_group_portrait import face_art, order_marks


def mark(kind, points):
    return {'kind': kind, 'points': points, 'closed': kind == 'head'}


class GroupCrownTest(unittest.TestCase):
    def setUp(self):
        self.source = {'radius': 160., 'width': 3.}
        eyes = [mark('eye', [[15, 10], [21, 10]]), mark('eye', [[35, 10], [41, 10]])]
        self.old_head = mark('head', [[6, 7], [12, 35], [36, 39], [51, 9], [34, -16]])
        full = mark('head', [[6, 7], [12, 35], [25, 50], [29, 51], [40, 38], [51, 9], [34, -16]])
        self.previous = [self.old_head, *eyes]
        self.face = [full, *eyes, mark('shade', [[17, 39], [24, 45], [29, 47]])]

    def download(self, line):
        points = np.asarray(line['points'])
        if line['closed']:
            points = np.vstack([points, points[0]])
        xy = portrait.samples(points, .25)
        return np.column_stack((np.unwrap(np.arctan2(xy[:, 1], xy[:, 0])),
                                np.linalg.norm(xy, axis=1) / self.source['radius']))

    def test_peak_and_a_strand_must_both_survive_export(self):
        paths = {(0, i): self.download(m) for i, m in enumerate(self.face)}
        self.assertTrue(signed_crown(self.previous, self.face, paths, 0, self.source))
        without_strand = {k: v for k, v in paths.items() if k != (0, 3)}
        self.assertFalse(signed_crown(self.previous, self.face, without_strand, 0, self.source))
        paths[0, 0] = self.download(self.old_head)
        self.assertFalse(signed_crown(self.previous, self.face, paths, 0, self.source))

    def test_keep_the_facial_scale_or_leave_the_existing_group(self):
        face = SimpleNamespace(marks=self.face)
        neighbor = mark('head', [[-60, -10], [-40, 0], [-47, 45], [-70, 12]])
        fitted = place_crown(face, self.previous, [neighbor], 100., 3.)
        np.testing.assert_allclose(eye_frame(fitted)[0], eye_frame(self.previous)[0])
        self.assertAlmostEqual(eye_frame(fitted)[1], eye_frame(self.previous)[1])
        with self.assertRaises(ValueError):
            place_crown(face, self.previous, [neighbor], 29., 3.)

    def test_open_hair_keeps_the_jaw_before_optional_shadows(self):
        jaw = dict(mark('hairline', [[0, 0], [18, -28], [28, -4]]), closed=True)
        hair = dict(self.old_head, closed=False)
        features = [hair, *self.previous[1:], mark('nose', [[19, 2], [25, 0]]),
                    mark('smile', [[15, -5], [32, -7]]), mark('shade', [[12, 4], [13, 8]]), jaw]
        events = {'events': [{'source': i} for i in range(len(features))]}
        face = face_art(features, events, {})
        self.assertIn(6, face.required)
        gathered = [((0, i), m) for i, m in enumerate(face.marks)]
        order_marks(gathered, {(0, i) for i in face.required})
        order = [m['kind'] for _, m in gathered]
        self.assertLess(order.index('hairline'), order.index('shade'))
        # A closed head already contains the jaw.
        self.assertNotIn(6, face_art([self.old_head, *features[1:]], events, {}).required)


if __name__ == '__main__':
    unittest.main()
