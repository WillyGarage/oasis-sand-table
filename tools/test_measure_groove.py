"""Offline optical-width checks. The synthetic image defines the two ridge positions in millimeters."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

import measure_groove as groove


class GrooveMeasurementTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.outline = self.folder / 'line.thr'
        # Travel straight across center, changing angle only when the ball is stationary.
        np.savetxt(self.outline, [[np.pi, 0.58], [np.pi, 0], [0, 0], [0, 0.58]])
        self.route = groove.motion_mm(self.outline, 60)
        self.center = np.array([220, 220])
        self.scale = 3.5
        yy, xx = np.indices((440, 440))
        self.y = (yy - self.center[1]) / self.scale
        self.x = (xx - self.center[0]) / self.scale
        self.light = 115 + self.y * 0.09 + self.x * 0.06
        self.blank = self.photo(1901)

    def photo(self, seed, width=None, one_shoulder=False):
        signal = self.light.copy()
        if width is not None:
            floor = -38 * np.exp(-0.5 * (self.y / 0.65) ** 2)
            shoulder = 34 * np.exp(-0.5 * ((self.y - width / 2) / 0.46) ** 2)
            if not one_shoulder:
                shoulder += 34 * np.exp(-0.5 * ((self.y + width / 2) / 0.46) ** 2)
            signal += (floor + shoulder) * (abs(self.x) < 35)
        noise = np.random.default_rng(seed).normal(0, 1.5, signal.shape)
        return np.rint(signal + noise).clip(0, 255).astype(np.uint8)

    def measure(self, after, repeat=None, native_scale=3.5):
        return groove.measure(
            self.blank,
            after,
            repeat,
            self.route,
            self.route,
            self.center,
            self.scale,
            native_px_per_mm=native_scale,
        )[0]

    def test_measures_independent_known_widths_under_noise(self):
        for width in (3.8, 8.4):
            with self.subTest(width=width):
                result = self.measure(self.photo(1801, width), self.photo(1912, width))
                self.assertEqual(result['status'], 'measured')
                self.assertAlmostEqual(result['visible_ridge_spacing_mm']['median'], width, delta=0.15)
                self.assertEqual(result['blank_control_detections'], 0)
                self.assertEqual(result['single_pass_count'], result['sections_accepted'])
                self.assertGreater(result['repeat_pairs_detected'], 8)
                self.assertAlmostEqual(result['repeat_minus_first_width_mm']['median'], 0, delta=0.10)

    def test_requires_two_new_shoulders_and_enough_source_pixels(self):
        for frame in (self.photo(1902), self.photo(1903, 4.2, one_shoulder=True)):
            result = self.measure(frame)
            self.assertEqual(result['status'], 'insufficient_evidence')
            self.assertEqual(result['sections_accepted'], 0)
            self.assertIsNone(result['visible_ridge_spacing_mm'])
        coarse = self.measure(self.photo(1903, 4.2), native_scale=1)
        self.assertGreaterEqual(coarse['sections_accepted'], 8)
        self.assertLess(coarse['native_pixels_across_median'], 6)
        self.assertEqual(coarse['status'], 'insufficient_evidence')

    def test_empty_and_excessive_routes(self):
        # A stationary ball offers no cross-section. Both output files must still be useful.
        np.savetxt(self.outline, [[0.5, 0.1], [0.5, 0.1]])
        image = self.folder / 'blank.png'
        self.assertTrue(cv2.imwrite(str(image), self.blank))
        args = [
            sys.executable,
            groove.__file__,
            '--before',
            str(image),
            '--after',
            str(image),
            '--outline',
            str(self.outline),
            '--center',
            '220',
            '220',
            '--radius-mm',
            '60',
            '--radius-px',
            '210',
            '--out',
            str(self.folder),
        ]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        report = json.loads((self.folder / 'measurement.json').read_text())
        self.assertEqual(report['status'], 'insufficient_evidence')
        self.assertEqual(report['sections_tested'], 0)
        self.assertIsNone(report['visible_ridge_spacing_mm'])
        self.assertIsNotNone(cv2.imread(str(self.folder / 'width-evidence.png')))
        np.savetxt(self.outline, [[0, 1], [1e120, 0.2]])
        with self.assertRaisesRegex(ValueError, 'exceed two million samples'):
            groove.motion_mm(self.outline, 60)
        with self.assertRaisesRegex(ValueError, 'positive and finite'):
            groove.motion_mm(self.outline, float('nan'))


if __name__ == '__main__':
    unittest.main()
