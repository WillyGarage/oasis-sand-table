"""Check measured-groove transfers for identity, locality and matched signed strokes."""
import unittest

import numpy as np

from mini_photo_transfer import signed_pixels, stroke, transfer


def polar(xy):
    x, y = np.asarray(xy, dtype=float).T
    return np.column_stack((np.arctan2(y, x), np.hypot(x, y)))


class PhotoTransferTest(unittest.TestCase):
    def setUp(self):
        # A narrow dark stroke extends right from the center, then retraces.
        self.original = polar([(0, 0), (.15, 0), (.30, 0), (.45, 0), (.30, 0), (.15, 0), (0, 0)])
        self.revised = polar([(0, 0), (.15, .015), (.30, .03), (.45, .045),
                              (.30, .03), (.15, .015), (0, 0)])
        # Preserve the nominal signed angle at the center when the edited stroke leaves.
        self.photo = np.full((201, 201), 160, np.uint8)
        self.photo[100, 100:146] = 40
        self.edits = [(0, 6, 0, 6)]

    def test_measured_stroke_moves_to_the_revised_route(self):
        result = transfer(self.photo, self.original, self.revised, self.edits)
        self.assertLess(result[97, 130], 70)
        self.assertGreater(result[100, 130], 100)
        np.testing.assert_array_equal(result[:80], self.photo[:80])
        np.testing.assert_array_equal(result[120:], self.photo[120:])
        np.testing.assert_array_equal(result[:, :80], self.photo[:, :80])

    def test_retracing_preserves_the_outbound_line(self):
        full = stroke(signed_pixels(self.revised, 100))
        outbound = stroke(signed_pixels(self.revised[:4], 100))
        np.testing.assert_allclose(full, outbound, atol=1e-8)

    def test_identical_route_returns_original_pixels(self):
        for edits in ([], self.edits):
            result = transfer(self.photo, self.original, self.original, edits)
            np.testing.assert_array_equal(result, self.photo)

    def test_undeclared_change_is_rejected(self):
        extra = np.vstack((self.revised, [.2, .3]))
        with self.assertRaisesRegex(ValueError, 'outside'):
            transfer(self.photo, self.original, extra, self.edits)

    def test_invalid_spans_and_routes_are_rejected(self):
        for edits in ([(0, 10, 0, 6)], [(0, 6, 0, 6), (0, 2, 0, 2)]):
            with self.assertRaisesRegex(ValueError, 'spans'):
                transfer(self.photo, self.original, self.revised, edits)
        for point in ([np.inf, .4], [1., 1.01]):
            invalid = self.revised.copy()
            invalid[2] = point
            with self.assertRaisesRegex(ValueError, 'finite route'):
                transfer(self.photo, self.original, invalid, self.edits)


if __name__ == '__main__':
    unittest.main()
