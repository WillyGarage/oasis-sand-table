"""Phase-independent contrast in bare Mini sand, tested without a camera or table."""
import unittest

import numpy as np

from mini_ripple_contrast import forecast, RippleSpectrum


class RippleContrastTest(unittest.TestCase):
    def test_predicts_changed_spacing_in_one_area_from_the_opening_photo(self):
        y, x = np.indices((780, 780))
        # A narrower pitch has less visible relief in this photographed bed.
        # The exposure also contains sensor pattern perpendicular to the rake.
        fast = 2*np.pi*x/6
        slow = 2*np.pi*x/12
        noise = 1.2*np.sin(2*np.pi*y/6)
        previous = np.where(y < 390, np.cos(slow), np.cos(fast))
        opening = 100 + noise + np.where(y < 390, 18*np.cos(slow+1.7), 4*np.cos(fast+1.7))
        # The tighter spacing now fills what was previously a strip of slow
        # turns. Its brightness phase need not match any phase in the photo.
        current = np.where(y < 320, np.cos(slow), np.cos(fast+.8))
        rendered = 100 + .5*current
        final = 100 + noise + np.where(y < 320, 18*np.cos(slow-1.9), 4*np.cos(fast-1.9))
        regions = dict(tighter=(x > 200) & (x < 560) & (y > 350) & (y < 383),
                       unchanged=(x > 200) & (x < 560) & (y > 160) & (y < 260),
                       tiny=(x == 370) & (y == 370))
        report = forecast(previous, current, opening, rendered, regions, observed=[final])
        for key in ('tighter', 'unchanged'):
            value = report[key]
            self.assertGreater(value['patches'], 10)
            self.assertLess(abs(value['forecastRms'] - value['observedRms'][0]), .45)
            self.assertLess(value['renderedRms'], .5)
        self.assertGreater(report['unchanged']['forecastRms'], 4*report['tighter']['forecastRms'])
        self.assertEqual(report['tiny'], dict(patches=0, regionPatches=0))

    def test_unrelated_texture_does_not_masquerade_as_rake_contrast(self):
        y, x = np.indices((390, 390))
        relief = np.sin(2*np.pi*x/6)
        photo = 120 + 15*np.cos(2*np.pi*y/6+.6)
        spectrum = RippleSpectrum(relief)
        self.assertLess(np.median(spectrum.contrast(photo)), .1)
        strength = spectrum.contrast(120 + 15*np.cos(2*np.pi*x/6+.6))
        self.assertGreater(np.median(strength), 8)

    def test_an_empty_bed_has_no_calibration(self):
        bed = np.zeros((220, 220))
        with self.assertRaisesRegex(ValueError, 'Too little periodic sand'):
            forecast(bed, bed, bed, bed, {'region': bed.astype(bool)})


if __name__ == '__main__':
    unittest.main()
