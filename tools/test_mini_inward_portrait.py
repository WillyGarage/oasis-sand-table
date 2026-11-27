import io
import math
from pathlib import Path
import unittest

import numpy as np

from mini_inward_portrait import PITCH, RADIUS_MM, compile_portrait, movement_files
from thrcommon import to_xy


class InwardPortraitTest(unittest.TestCase):
    def exported_excursion(self, mark):
        tail = np.array([[0., 0.], [-.08, -.2], [-1., 0.]])
        start = -17*math.tau + math.pi - .000013
        path, events = compile_portrait({'test mark': mark}, tail, start, 3.192)
        part, = movement_files(path)
        signed = np.loadtxt(io.StringIO(part['text']))
        event = events[0]
        return signed[event['first']:event['last']+1]

    def test_closed_mark_at_center_makes_one_lap_in_the_source_direction(self):
        shape = np.array([[0., 0.], [.38, 0.], [.31, .32], [.04, .28], [0., 0.]])
        for mark in (shape, shape[::-1]):
            with self.subTest(outgoing=tuple(mark[1])):
                cut = self.exported_excursion(mark)
                xy = np.column_stack(to_xy(cut))
                self.assertAlmostEqual(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum(),
                                       np.linalg.norm(np.diff(mark, axis=0), axis=1).sum(), places=4)
                def signed_area(line):
                    x, y = line.T
                    return .5*np.sum(x[:-1]*y[1:] - y[:-1]*x[1:])
                self.assertAlmostEqual(signed_area(xy), signed_area(mark), places=4)

    def test_two_lenses_return_to_the_bridge_before_leaving_for_the_rim(self):
        tail = np.array([[0., 0.], [.2, .1], [.3, -.1], [0., 0.],
                         [-.26, -.13], [-.31, .18], [0., 0.], [0., 0.], [0., 1.]])
        route, (event,) = compile_portrait({}, tail, 2., 3.192)
        part, = movement_files(route)
        signed = np.loadtxt(io.StringIO(part['text']))[event['first']:event['last']+1]
        at_center = signed[:, 1] == 0
        self.assertEqual(np.count_nonzero(at_center[1:] & ~at_center[:-1]), 2)
        xy = np.column_stack(to_xy(signed))
        self.assertAlmostEqual(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum(),
                               np.linalg.norm(np.diff(tail, axis=0), axis=1).sum(), places=4)

    def test_diameter_turns_at_zero_before_drawing_its_other_half(self):
        for angle, left, right in [(0., .37, .37), (.22682979448301754, .987, .843), (-1.83, .31, .9)]:
            with self.subTest(angle=angle):
                unit = np.array([math.cos(angle), math.sin(angle)])
                cut = self.exported_excursion(np.array([-left*unit, right*unit]))
                # Between signed positions the controller interpolates both axes.
                # Every segment that changes the bearing must stay at zero radius.
                turning = np.abs(np.diff(cut[:, 0])) > 1e-5
                self.assertTrue(turning.any())
                self.assertTrue(np.all(cut[:-1, 1][turning] == 0.))
                self.assertTrue(np.all(cut[1:, 1][turning] == 0.))
                xy = np.column_stack(to_xy(cut))
                np.testing.assert_allclose(xy @ [-unit[1], unit[0]], 0., atol=1e-7)
                self.assertAlmostEqual(np.ptp(xy @ unit), left+right, places=6)

    def test_archived_guest_portraits_rebuild_byte_for_byte(self):
        archive = Path(__file__).resolve().parents[1] / 'patterns/portrait-gallery/drawings/inward-guest-portrait'
        with np.load(archive/'strokes.npz') as doc:
            for name in ('open', 'flowing'):
                marks = {k: doc[k] for k in doc if k != 'exit' and (name == 'flowing' or not k.startswith('hair-'))}
                path, _ = compile_portrait(marks, doc['exit'], 16.05972, 3.192)
                part, = movement_files(path)
                self.assertEqual(part['text'].encode('ascii'), (archive/(name+'.thr')).read_bytes())

    def test_named_open_mark_uses_only_the_previous_spiral_for_access(self):
        phase = 334.56500776
        clearance = 3.192
        lid = np.array([[.25, .11], [.58, .19]])
        ordinary = np.array([[.21, .05], [.13, .07]])
        tail = np.array([[0., 0.], [0., 1.]])
        path, events = compile_portrait({'lid': lid, 'ordinary': ordinary}, tail, phase, clearance,
                                        spiral_entries=['lid'])
        part, = movement_files(path)
        signed = np.loadtxt(io.StringIO(part['text']))
        event, other, end = events
        self.assertEqual([e['label'] for e in events], ['lid', 'ordinary', 'exit'])
        self.assertEqual(event['entryKind'], 'spiral')
        self.assertNotIn('entryKind', other)
        a, f, l, b = [event[key] for key in ('anchor', 'first', 'last', 'back')]
        self.assertLess(a, f)
        self.assertLess(l, b)
        self.assertAlmostEqual(1-event['crossingProgress'], signed[f, 1], places=7)
        self.assertAlmostEqual((signed[f:l+1, 1].min()-signed[a, 1])*RADIUS_MM, clearance, places=5)
        np.testing.assert_allclose(signed[a], signed[b], atol=1e-8, rtol=0)

        # Check the signed endpoints after eight-decimal export. Between them
        # the controller interpolates both polar axes, so each edge belongs
        # to the same Archimedean spiral if its two residuals are identical.
        for start, stop, direction in [(0, a, -1), (a, f, 1), (l, b, -1),
                                       (b, other['anchor'], -1), (other['back'], end['atCenter'], -1)]:
            section = signed[start:stop+1]
            residual = section[:, 0] - phase - math.tau/PITCH*(1-section[:, 1])
            np.testing.assert_allclose(residual, 0., atol=2e-6)
            self.assertTrue(np.all(np.diff(section[:, 1])*direction > 0))
        radial = signed[other['anchor']:other['first']+1]
        self.assertGreater(len(radial), 1)
        np.testing.assert_allclose(radial[:, 0], radial[0, 0], atol=1e-8, rtol=0)

        cut = np.column_stack(to_xy(signed[f:l+1]))
        np.testing.assert_allclose(cut[0], cut[-1], atol=1e-8)
        unit = (lid[1]-lid[0])/np.linalg.norm(lid[1]-lid[0])
        offset = cut-lid[0]
        self.assertLess(np.max(abs(offset @ [-unit[1], unit[0]]))*RADIUS_MM, .01)
        along = offset @ unit
        self.assertAlmostEqual(along.min(), 0., places=6)
        self.assertAlmostEqual(along.max(), np.linalg.norm(lid[1]-lid[0]), places=6)
        self.assertTrue(0 < along[0] < along.max())

    def test_spiral_access_preserves_both_windings_and_resumes_at_same_front(self):
        angle = np.linspace(0., math.tau, 251)
        ring = .62*np.column_stack([np.cos(angle), np.sin(angle)])
        tail = np.array([[0., 0.], [1., 0.]])
        phase = -18*math.tau + .71
        for mark, direction in [(ring, 1), (ring[::-1], -1)]:
            with self.subTest(direction=direction):
                path, (e, end) = compile_portrait({'ring': mark}, tail, phase, 3.192, spiral_entries={'ring'})
                part, = movement_files(path)
                signed = np.loadtxt(io.StringIO(part['text']))
                a, f, l, b = [e[key] for key in ('anchor', 'first', 'last', 'back')]
                self.assertAlmostEqual(signed[l, 0]-signed[f, 0], direction*math.tau, places=7)
                self.assertAlmostEqual(signed[b, 0]-signed[a, 0], direction*math.tau, places=7)
                self.assertEqual(signed[b, 1], signed[a, 1])
                for section, winding in [(signed[a:f+1], 0), (signed[l:b+1], direction),
                                         (signed[b:end['atCenter']+1], direction)]:
                    residual = section[:, 0] - phase - (1-section[:, 1])*math.tau/PITCH
                    np.testing.assert_allclose(residual, winding*math.tau, atol=2e-6, rtol=0)

    def test_spiral_access_handles_center_endpoint_and_missing_crossing(self):
        tail = np.array([[0., 0.], [1., 0.]])
        diameter = np.array([[-.19, 0.], [.13, 0.]])
        path, (e, _) = compile_portrait({'center': diameter}, tail, -12.2, 3., spiral_entries={'center'})
        self.assertEqual(e['crossingProgress'], 1.)
        self.assertTrue(np.all(path[e['anchor']:e['first']+1, 1] == 0.))
        self.assertTrue(np.all(path[e['last']:e['back']+1, 1] == 0.))
        xy = np.column_stack(to_xy(path[e['first']:e['last']+1]))
        np.testing.assert_allclose([xy[:, 0].min(), xy[:, 0].max()], [-.19, .13], atol=1e-7)
        np.testing.assert_allclose(xy[:, 1], 0., atol=1e-7)

        endpoint = np.array([[.60, 0.], [.61, 0.]])
        path, (e, _) = compile_portrait({'tip': endpoint}, tail, 0., 0., spiral_entries=['tip'])
        self.assertAlmostEqual(path[e['first'], 1], .60, places=7)
        self.assertEqual(e['anchor'], e['first'])
        self.assertEqual(e['last'], e['back'])

        short = np.array([[.51, 0.], [.51, .001]])
        with self.assertRaisesRegex(ValueError, 'No inward spiral crossing.*lid'):
            compile_portrait({'lid': short}, tail, 0., 3., spiral_entries=['lid'])
        with self.assertRaisesRegex(ValueError, 'Unknown spiral-entry strokes: typo'):
            compile_portrait({'lid': short}, tail, 0., 3., spiral_entries=['typo'])

    def test_clear_resumes_at_same_spiral_after_winding_and_center_turns(self):
        phase = 2.4
        angle = np.linspace(0, math.tau, 231)
        ring = .68*np.column_stack([np.cos(angle), np.sin(angle)])
        nose = np.array([[0, 0], [-.08, .03], [-.12, .01]])
        tail = np.array([[0, 0], [.06, .01], [.3, -.02], [1, 0]])
        route, events = compile_portrait({'ring': ring, 'nose': nose}, tail, phase, 3.)
        self.assertTrue(np.array_equal(route[0], [phase, 1]))
        self.assertAlmostEqual(route[-1, 1], 1.)
        self.assertLessEqual(np.abs(np.diff(route[:, 0])).max(), .05500001)
        self.assertGreaterEqual(route[:, 1].min(), 0)
        last = 0
        for event in events:
            end = event.get('anchor', event.get('atCenter'))
            rake = route[last:end+1]
            # After wrapping a closed stroke, points on the rake still have
            # the opening phase. A center-only turn can set the next bearing.
            rake = rake[rake[:, 1] > 1e-8]
            if len(rake):
                residual = rake[:, 0]-phase-math.tau*(1-rake[:, 1])/PITCH
                np.testing.assert_allclose(np.sin(residual/2), 0, atol=1e-7)
                self.assertTrue(np.all(np.diff(rake[:, 1]) <= 1e-9))
            if event['label'] == 'exit':
                break
            first, finished = route[event['first']], route[event['last']]
            np.testing.assert_allclose(to_xy(np.array([first])), to_xy(np.array([finished])), atol=1e-7)
            self.assertAlmostEqual(route[event['anchor'], 1], route[event['back'], 1])
            last = event['back']
        self.assertEqual([e['label'] for e in events], ['ring', 'nose', 'exit'])
        self.assertTrue(np.any(route[:, 1] == 0))

    def test_export_keeps_exact_joint_across_mini_limit(self):
        original = np.column_stack([np.linspace(0, 5, 12023), np.linspace(1, 0, 12023)])
        parts = movement_files(original)
        self.assertEqual(len(parts), 2)
        left, right = (np.loadtxt(io.StringIO(p['text'])) for p in parts)
        np.testing.assert_array_equal(left[-1], right[0])
        np.testing.assert_allclose(np.vstack([left, right[1:]]), original, atol=5.1e-9, rtol=0)
