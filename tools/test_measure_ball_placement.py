"""Exercise the full camera report and command/photo pairing without moving a table."""
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import calib2
import measure_ball_placement as ball


def pixel(x, y):
    # An oblique camera with a genuine perspective change across the bed.
    w = 1 + 0.0004 * y
    return [(600 + 2 * x + 0.4 * y) / w, (400 - 0.1 * x - 1.5 * y) / w]


class PlacementTest(unittest.TestCase):
    def test_surveyed_coordinates_with_independent_holdout_and_known_errors(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            marks = folder / 'marks.csv'
            with marks.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['role', 'x_px', 'y_px', 'x_mm', 'y_mm'])
                for x, y in [(-80, 80), (80, 80), (80, -80), (-80, -80)]:
                    writer.writerow(['fit', *pixel(x, y), x, y])
                # Independent reference actually 3 mm away from its nominal y value.
                writer.writerow(['check', *pixel(12, 47), 12, 44])
            table = folder / 'targets.csv'
            with table.open('w', newline='') as stream:
                w = csv.writer(stream)
                w.writerow(['theta_rad', 'rho', 'x_px', 'y_px', 'photo', 'receipt'])
                w.writerow([0, 0, *pixel(0, 1), 'a.jpg', 'a'])
                w.writerow([math.pi / 2, .5, *pixel(-2, 53), 'b.jpg', 'b'])
                w.writerow([math.pi / 2, .5, *pixel(-2, 53.4), 'b2.jpg', 'b'])
                w.writerow([0, 1, '', '', '', 'c'])
                w.writerow([math.pi * 2.5, .5, *pixel(-1, 52), 'd.jpg', 'd'])
            layout = folder / 'layout.json'
            layout.write_text(json.dumps({'assumed_working_radius_mm': 100,
                                          'zones': {'center': {'bounds': [0, .5]}, 'outer': {'bounds': [.5, 1]}}}))
            args = [sys.executable, ball.__file__, str(table), '--radius-mm', '100',
                    '--references', str(marks), '--layout', str(layout)]
            d = json.loads(subprocess.check_output(args))
            self.assertAlmostEqual(d['camera']['check']['residual_mm']['max'], 3, places=4)
            self.assertEqual((d['commanded_stops'], d['measured_stops'], d['distinct_measured_targets']), (4, 3, 2))
            self.assertIsNone(d['stops'][0]['outward_mm'])
            self.assertAlmostEqual(d['stops'][1]['outward_mm'], 3, places=4)
            self.assertAlmostEqual(d['stops'][1]['counterclockwise_mm'], 2, places=4)
            self.assertAlmostEqual(d['stops'][1]['stationary_spread_mm'], .4, places=4)
            self.assertAlmostEqual(d['repeated_targets'][0]['max_separation_mm'], math.sqrt(2), places=4)
            self.assertTrue(d['repeated_targets'][0]['previous_targets_on_both_radial_sides'])
            self.assertEqual(d['zones']['outer']['distinct_measured_targets'], 1)
            self.assertEqual(d['zones']['outer']['commanded_stops'], 3)
            self.assertAlmostEqual(d['error_mm']['max'], math.sqrt(13), places=4)
            with self.assertRaisesRegex(ValueError, 'working radius'):
                ball.zone_coverage(d, {'assumed_working_radius_mm': 200})

    def test_missing_measurements_stay_visible(self):
        row = dict(theta_rad='0', rho='1', photo='miss.jpg', x_px='', y_px='')
        report = ball.measure([row], np.eye(3), 114)
        self.assertEqual(report['measured_stops'], 0)
        self.assertIsNone(report['error_mm'])
        with self.assertRaisesRegex(ValueError, 'listed twice'):
            ball.measure([row, row], np.eye(3), 114)
        with self.assertRaisesRegex(ValueError, 'both pixel'):
            ball.measure([dict(row, y_px='20')], np.eye(3), 114)

    def test_command_exposures_survive_a_camera_failure(self):
        record = io.StringIO()
        state = dict(state='idle', cal=dict(rmax=.905), m2h=0, cur1=0, cur2=0, homed=1, fault=0)
        observed = ({'x': .001, 'y': 0, 'score': .8}, True, 'photo.jpg', [])
        with patch.object(calib2, 'load_params', return_value={}), patch.object(calib2.o, 'status', return_value=state), \
                patch.object(calib2.o, 'get') as send, patch.object(calib2.o, 'wait_idle', return_value=state), \
                patch.object(calib2, 'see', side_effect=[observed, OSError('camera')]):
            with self.assertRaisesRegex(OSError, 'camera'):
                calib2.cmd_check(2, record)
            self.assertEqual(send.call_count, 2)
            send.assert_called_with('/goto?th=1.0000&rho=0.0500', retries=1)
        record.seek(0)
        rows = list(csv.DictReader(record))
        self.assertEqual([r['photo'] for r in rows], ['photo.jpg', ''])
        self.assertTrue(all(r['x_px'] == r['y_px'] == '' for r in rows))


if __name__ == '__main__':
    unittest.main()
