"""Check the local contrast adjustment against known light and dark sections of one bed."""
import unittest
from unittest.mock import patch

import numpy as np

import mini_bed_preview as preview


class BedContrastTest(unittest.TestCase):
    def setUp(self):
        size = 260
        y, x = np.indices((size, size))
        # One side has a faint rake. The other has the same rake in stronger light.
        self.photo = (135 + np.where(x < size / 2, 2., 22.) * np.cos(y * .85)).astype(np.float32)
        self.route = np.array([[0., 1.], [np.pi, 1.]])
        self.profile = dict(version=2, radius_mm=preview.RADIUS_MM, groove_mm=preview.GROOVE_MM,
                            radii=[.2, .8], gain=[1., 1.], groove_softness_mm=.45)
        self.bright = np.s_[88:168, 170:195]
        self.dim = np.s_[88:168, 65:90]
        before = np.full((size, size), 135., np.float32)
        coverage = ((y > 50) & (y < 200)).astype(np.float32)
        after = before + 20. * coverage * np.cos(x / 3.).astype(np.float32)
        self.patched = patch.object(preview, 'fields', return_value=(before, after, coverage))
        self.patched.start()
        self.addCleanup(self.patched.stop)

    def render(self, profile):
        return preview.predict(self.photo, self.route, .020, profile)

    def test_gain_changes_the_new_groove_and_preserves_the_bed(self):
        profile = dict(self.profile, version=3, bed_contrast_levels=[3., 8.],
                       bed_contrast_gains=[.5, 1.5])
        old = self.render(self.profile)
        new = self.render(profile)
        surviving, *_ = preview.photographed_bed(self.photo, self.route, .020, profile, None, None)
        for region, gain in [(self.dim, .5), (self.bright, 1.5)]:
            reference = (old[region].astype(float) - surviving[region])
            change = new[region].astype(float) - surviving[region]
            self.assertGreater(np.std(reference), 5.)
            np.testing.assert_allclose(change, gain * reference, atol=1.5)
        np.testing.assert_array_equal(new[10:30], old[10:30])

    def test_unit_gain_reproduces_the_older_profile(self):
        profile = dict(self.profile, version=3, bed_contrast_levels=[3., 8.],
                       bed_contrast_gains=[1., 1.])
        np.testing.assert_array_equal(self.render(self.profile), self.render(profile))
        with self.assertRaises(ValueError):
            self.render(dict(profile, bed_contrast_levels=[8., 3.]))


class RouteComparisonTest(unittest.TestCase):
    def test_signed_color_difference_preserves_ball_and_accepts_a_full_extra_turn(self):
        bed = np.zeros((51, 51), dtype=np.float32)
        photo = np.zeros((51, 51, 3), dtype=np.uint8)
        photo[:] = [2, 100, 250]
        route = np.array([[1., 0.], [0., 1.]])
        candidate = route + [2 * np.pi, 0.]
        old = np.full(bed.shape, 124, np.uint8)
        new = old.copy()
        new[10, 25], new[25, 10], new[25, -1] = 112, 139, 0
        with patch.object(preview, 'predict', side_effect=[old, new]) as render:
            projected = preview.compare_routes(bed, photo, route, candidate, .02, {})
        self.assertTrue(all(c.kwargs['local_grooves'] for c in render.call_args_list))
        expected = photo.copy()
        expected[10, 25], expected[25, 10] = [0, 88, 238], [17, 115, 255]
        np.testing.assert_array_equal(projected, expected)
        with patch.object(preview, 'predict', side_effect=[old, new]), self.assertRaisesRegex(ValueError, 'positions'):
            preview.compare_routes(bed, photo, route, route + [np.pi, 0.], .02, {})


if __name__ == '__main__':
    unittest.main()
