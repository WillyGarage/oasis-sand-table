"""Check the iris, empty eye corners and later ball travel independently of the photograph model."""
import unittest

import numpy as np

from wide_portrait import samples, verify_eye_opening


class EyeRouteTest(unittest.TestCase):
    def setUp(self):
        # A rectangular test aperture has a clear interior on both sides of the iris edge.
        self.aperture = np.array([[10., 0.], [40., 0.], [40., 12.], [10., 12.]])
        self.iris = np.array([[25., 0.], [25., 12.]])
        self.mark = np.vstack((self.aperture[0], self.iris, self.iris[0], self.aperture[1:], self.aperture[0]))
        self.eye = {'aperture': self.aperture, 'iris': self.iris,
                    'mark': {'points': self.mark.tolist(), 'closed': True}}
        self.stroke = samples(self.mark, .1)
        self.other = np.array([[10., 30.], [40., 30.]])
        self.after = np.array([[0., .8], [0., 1.]])

    def check(self, actual=None, others=None, later=None):
        verify_eye_opening(self.eye, {'last': 0}, self.stroke if actual is None else actual,
                           self.other if others is None else others, self.after if later is None else later,
                           100., 5.)

    def test_eye_and_own_retraced_iris_fit(self):
        self.check()

    def test_lids_alone_do_not_prove_the_iris_was_engraved(self):
        with self.assertRaisesRegex(ValueError, 'iris edge'):
            self.check(actual=samples(np.vstack((self.aperture, self.aperture[0])), .1))

    def test_cuts_across_either_white_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'across'):
            self.check(actual=np.vstack((self.stroke, [16., 6.])))
        with self.assertRaisesRegex(ValueError, 'across'):
            self.check(others=np.array([[34., 7.]]))
        with self.assertRaisesRegex(ValueError, 'later movement'):
            self.check(later=np.array([[.2, .01], [.2, .95]]))


if __name__ == '__main__':
    unittest.main()
