"""Offline checks for signed row numbering, inward-erase coverage, and photograph transfer."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from mini_bed_preview import disk, without_ball
from mini_inward_portrait import compile_portrait
from mini_inward_preview import AmbiguousStage, PITCH, engraving_spans, model_fields, observed_stage, predict, read_parts, relief_features, repeat_texture, shifted_spiral, signed_light, signed_replay, transfer_light
from oasis_player import PlaybackError


def inward_spiral(count=1283, phase=0.):
    fraction = np.linspace(0., 1., count)
    return np.column_stack((phase + (math.tau / PITCH) * fraction, 1. - fraction))


def edge_labels(path, rows, **options):
    labels = np.full(rows - 1, -1, dtype=int)
    cursor = 0
    for start, end, engraving in engraving_spans(path, rows, **options):
        if start != cursor or not start < end <= rows - 1:
            raise AssertionError(f'Noncontiguous span {start}..{end} in {rows} rows')
        labels[start:end] = engraving
        cursor = end
    if cursor != rows - 1:
        raise AssertionError('A signed movement is missing.')
    return labels


class InwardPreviewTest(unittest.TestCase):
    def test_photographed_light_follows_new_grooves_and_preserves_untouched_sand(self):
        x, y = disk((240, 240))
        previous = (np.sin(55*x + 13*y) + .65*np.cos(35*y-6*x)).astype('float32')
        touched = ((x > -.2) & (x < .6) & (abs(y) < .4)).astype('float32')
        current = np.where(touched, np.cos(41*x - 32*y), previous).astype('float32')
        def light(height):
            return 130 + 7*relief_features(height, x, y)[:, :, 1] + 4*x
        opening = light(previous)
        dock = (math.pi, 1.)
        prediction = signed_light(opening, dock, previous, current, touched)
        uncut = touched == 0
        np.testing.assert_array_equal(prediction[uncut], np.rint(without_ball(opening, dock)[0][uncut]))
        interior = (x > 0) & (x < .4) & (abs(y) < .2)
        error = np.mean(abs(prediction[interior]-light(current)[interior]))
        self.assertLess(error, .25*np.mean(abs(opening[interior]-light(current)[interior])))

    def test_repeat_edit_keeps_texture_on_unchanged_sand_and_omits_the_parked_ball(self):
        for size in (210, 480):
            x, y = disk((size, size))
            relief = np.uint8(120 + 9 * np.cos(52 * x) * np.sin(47 * y))
            opening = np.uint8(relief + 9 * np.sin(93 * x + 87 * y))
            opening[(x > .96) & (abs(y) < .04)] = 245
            image = repeat_texture(opening, (0., 1.), relief, relief)
            interior = x*x + y*y < .6
            np.testing.assert_allclose(image[interior], opening[interior], atol=1)
            np.testing.assert_array_equal(image[(x > .96) & (abs(y) < .04)], relief[(x > .96) & (abs(y) < .04)])
            with self.assertRaisesRegex(ValueError, 'registered'):
                repeat_texture(opening, (0., 1.), relief[:-1], relief)

    def test_signed_replay_adds_only_the_requested_moves_to_the_previous_sand(self):
        previous = np.array([[math.pi, 1.], [math.pi, 0.], [0., 0.]])
        drawing = np.array([[0., 0.], [0., .7], [math.pi/2, .7]])
        def render(rows):
            png = signed_replay(previous, drawing, rows)
            return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        start, line, arc = (render(n) for n in (1, 2, 3))
        # At x=-0.5 the preceding radial groove survives every stage.
        np.testing.assert_array_equal(start[370:410, 182:206], arc[370:410, 182:206])
        # A subsequent groove at x=+0.5 appears before the upper-right arc.
        self.assertGreater(np.abs(start[370:410, 570:601].astype(float)-line[370:410, 570:601]).max(), 5)
        np.testing.assert_array_equal(start[185:210, 575:600], line[185:210, 575:600])
        self.assertGreater(np.abs(line[185:210, 575:600].astype(float)-arc[185:210, 575:600]).max(), 5)
        with self.assertRaisesRegex(ValueError, 'meet'):
            signed_replay(previous, drawing[1:], 1)
        with self.assertRaisesRegex(ValueError, 'rows'):
            signed_replay(previous, drawing, 4)

    def test_camera_can_stop_partway_through_a_signed_spiral_segment(self):
        spiral = inward_spiral(1303, phase=-12.5)
        i, fraction = 651, .74
        theta, radius = spiral[i] + fraction*(spiral[i+1]-spiral[i])
        fix = dict(credible=True, range=[i-4, i+4], unit=(radius*np.array([np.cos(theta), np.sin(theta)])).tolist())
        route, rows, fit = observed_stage(spiral, fix)
        self.assertEqual(fit['index'], i)
        self.assertLess(fit['distanceMm'], .06)
        self.assertAlmostEqual(fit['fraction'], fraction, delta=.007)
        self.assertEqual(rows, i+2)
        np.testing.assert_array_equal(np.delete(route, i+1, axis=0), spiral)
        self.assertFalse(edge_labels(route, rows).any())

    def test_camera_ambiguity_and_unsupported_fixes_are_explicit(self):
        route = np.array([[0., .4], [0., .7], [0., .4], [0., 1.]])
        fix = dict(credible=True, range=[0, 2], unit=[.5, 0.])
        with self.assertRaises(AmbiguousStage):
            observed_stage(route, fix)
        for override in ({'range': [-1, 2]}, {'range': [2, 1]}, {'range': [1, 4]},
                         {'credible': False}, {'unit': [float('nan'), 0.]}, {'unit': [0., .5]}):
            with self.subTest(override=override), self.assertRaises(ValueError) as caught:
                observed_stage(route, {**fix, **override})
            self.assertNotIsInstance(caught.exception, AmbiguousStage)
        for i in (0, 3):
            result, count, fit = observed_stage(route, {**fix, 'range': [i, i], 'unit': [route[i, 1], 0.]})
            self.assertIs(result, route)
            self.assertEqual(count, i+1)
            self.assertEqual(fit['distanceMm'], 0.)

    def test_row_count_stops_before_the_next_signed_movement(self):
        rake = inward_spiral()
        anchor = 413
        depart = rake[anchor]
        route = np.vstack((rake[:anchor + 1], depart + [.03, .05], depart, rake[anchor + 1:]))
        expected = np.r_[np.zeros(anchor), [1, 1], np.zeros(len(rake) - anchor - 1)]
        for rows in (1, 2, anchor + 1, anchor + 2, anchor + 3, anchor + 4, len(route)):
            with self.subTest(rows=rows):
                np.testing.assert_array_equal(edge_labels(route, rows), expected[:rows-1])
        for invalid in (0, len(route) + 1):
            with self.assertRaises(ValueError):
                engraving_spans(route, invalid)

    def test_both_motion_export_precisions_preserve_the_rake(self):
        for places in (5, 8):
            with self.subTest(places=places):
                rake = inward_spiral(1877, phase=-2.74).round(places)
                self.assertFalse(edge_labels(rake, len(rake)).any())

    def test_previously_raked_edges_can_be_borrowed_by_a_later_drawing(self):
        rake = inward_spiral(1701, phase=.33)
        # A new feature after the center repeats a short section of an old cut.
        # It does not add another erase or break the one already completed.
        old = rake[490:495].copy()
        old[:, 0] += math.tau * round((rake[-1, 0] - old[0, 0]) / math.tau)
        route = np.vstack([rake, [old[0, 0], 0.], old, [old[-1, 0], .91]])
        actual = edge_labels(route, len(route))
        self.assertFalse(actual[:len(rake)-1].any())
        self.assertTrue(actual[len(rake):].all())

    def test_return_trip_from_rim_feature_keeps_first_rake_in_its_original_rows(self):
        mark = np.array([[1., 0.], [.995, .002]])
        tail = np.array([[0., 0.], [1., 0.]])
        path, (edge, end) = compile_portrait({'edge': mark}, tail, 0., 3.192, spiral_entries=['edge'])
        self.assertEqual(edge['crossingProgress'], 0.)
        full = np.zeros(len(path)-1, dtype=int)
        full[edge['anchor']:edge['back']] = 1
        full[end['atCenter']:] = 1
        for rows in (edge['anchor']+1, edge['last']+1, edge['back']+1, len(path)):
            with self.subTest(rows=rows):
                np.testing.assert_array_equal(edge_labels(path.round(8), rows), full[:rows-1])

    def test_engraving_can_follow_part_of_the_next_rake_edge_then_return(self):
        rake = inward_spiral(1001)
        i = 400
        mid = (rake[i] + rake[i+1]) / 2
        route = np.vstack((rake[:i+1], mid, rake[i], rake[i+1:]))
        actual = edge_labels(route, len(route))
        expected = np.r_[np.zeros(i), [1, 1], np.zeros(len(rake)-i-1)]
        np.testing.assert_array_equal(actual, expected)

    def test_retrace_texture_only_follows_already_cleared_grooves(self):
        rake = inward_spiral(1001, phase=-1.37)
        i = 400
        # Reach forward half an edge on untouched sand, return, then travel
        # backward along the old spiral to a short mark and back to the rake.
        ahead = .5 * (rake[i] + rake[i+1])
        mark = rake[i-1] + [.03, .04]
        route = np.vstack([rake[:i+1], ahead, rake[i], rake[i-1], mark,
                           rake[i-1], rake[i], rake[i+1:]])
        expected = np.r_[np.zeros(i), [1, 1, 0, 1, 1, 0], np.zeros(len(rake)-i-1)]
        for places in (5, 8):
            for stop in (i+2, i+4, i+7, len(route)):
                with self.subTest(places=places, stop=stop):
                    np.testing.assert_array_equal(
                        edge_labels(route.round(places), stop, preserve_retraced_spiral=True), expected[:stop-1])

    def test_incomplete_reset_is_rejected_even_at_an_early_display_row(self):
        rake = inward_spiral(1001)
        # Skip a radial band by a nonspiral route, then resume on a later turn.
        jump = np.vstack((rake[:401], [rake[400, 0], rake[600, 1]], rake[600:]))
        for invalid in (rake[:-300], jump, rake[::-1]):
            with self.assertRaises(ValueError):
                engraving_spans(invalid, 2)

    def test_split_files_rejoin_one_position_and_preserve_signed_local_turns(self):
        original = inward_spiral(1801)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp)/f'portrait-{i}.thr' for i in range(1, 4)]
            for file, left, right, turns in zip(paths, (0, 405, 801), (405, 801, 1800), (0, -3, 5)):
                part = original[left:right+1].copy()
                part[:, 0] += turns * math.tau
                np.savetxt(file, part, fmt='%.8f')
            joined = read_parts(paths)
            self.assertEqual(joined.shape, original.shape)
            np.testing.assert_allclose(joined, original, atol=1.1e-8, rtol=0)
            self.assertFalse(edge_labels(joined, 1300).any())
            with self.assertRaises(PlaybackError):
                read_parts([paths[0], paths[2]])

    def test_zero_radius_turn_after_raking_does_not_engrave_a_dot(self):
        rake = inward_spiral(1201)
        previous = np.array([[0., 0.], [.0, 1.]])
        turning = np.vstack((rake, [rake[-1, 0] + 1, 0.]))
        old_bed, earlier, old_coverage, fresh, partial, touched, art = model_fields(
            117, previous, turning, len(turning), 0.)
        self.assertTrue(np.any(touched > .99))
        np.testing.assert_array_equal(art, 0.)
        np.testing.assert_array_equal(partial[touched == 0], earlier[touched == 0])
        for mask in (old_coverage, touched):
            self.assertEqual(mask.shape, (117, 117))
            self.assertGreaterEqual(float(mask.min()), 0.)
            self.assertLessEqual(float(mask.max()), 1.)

    def test_engraved_fraction_is_bounded_by_total_touch_at_shared_end_caps(self):
        previous = np.array([[0., 0.], [0., 1.]])
        end_radius = .5 - .002 * PITCH / math.tau
        drawing = np.array([[1., .5], [1.03, .5], [1.032, end_radius], [1.07, .5]])
        # Isolate the renderer with a tiny art/rake/art junction. Splitting its
        # overlapping caps into three calls can otherwise count the same sand twice.
        with patch('mini_inward_preview.engraving_spans', return_value=[[0, 1, 1], [1, 2, 0], [2, 3, 1]]):
            *_, touched, art = model_fields(123, previous, drawing, len(drawing), 0.)
        self.assertTrue((art > .8).any())
        self.assertTrue(np.all((art >= 0.) & (art <= touched)))

    def test_unsupported_interior_keeps_the_measured_light_level(self):
        for size in (150, 257):
            with self.subTest(size=size):
                yy, xx = np.indices((size, size))
                half = (size-1)/2
                radius = np.hypot(yy-half, xx-half)/half
                bare = (radius > .84) & (radius < .96)
                clear = np.full((size, size), 140., dtype='float32')
                under_new_light = np.full_like(clear, 80.)
                result = transfer_light(clear, clear, under_new_light, bare)
                np.testing.assert_allclose(result[radius < .90], 80., atol=.05, rtol=0.)

    def test_equivalent_half_turns_shift_the_photographed_spiral_identically(self):
        y, x = np.indices((151, 151), dtype='float32')
        bed = (x + 2*y) / 3
        xx, yy = (a.astype('float32') for a in disk(bed.shape))
        reference = shifted_spiral(bed, math.pi, xx, yy)
        for phase in (-math.pi, 3*math.pi, -3*math.pi, np.float64(math.pi)):
            np.testing.assert_array_equal(shifted_spiral(bed, phase, xx, yy), reference)

    def test_partial_prediction_preserves_untouched_camera_pixels_at_a_smaller_size(self):
        size = 168
        xx, yy = disk((size, size))
        radius = np.hypot(xx, yy)
        clear = np.rint(120 + 8*np.cos(27*radius)).astype('float32')
        previous = np.array([[0., 0.], [0., 1.]])
        earlier = clear + np.float32(10*((xx > 0.) & (abs(yy) < .025)))
        opening = earlier - 25.
        rake = inward_spiral(1601)
        image = predict(clear, earlier, opening, previous, rake, 61)
        self.assertEqual(image.shape, opening.shape)
        self.assertEqual(image.dtype, np.uint8)
        np.testing.assert_array_equal(image[radius < .80], opening[radius < .80])

    def test_previous_inward_clear_leaves_its_bare_bed_available_for_training(self):
        previous = np.vstack([inward_spiral(1103, -8.4), [-8.4+50*math.tau, 1.]])
        drawing = inward_spiral(781, previous[-1, 0])
        size = 123
        old_bed, old_art, surviving, _, untouched, touched, _ = model_fields(
            size, previous, drawing, 1, previous[0, 0])
        _, _, _, _, _, all_moved, earlier_engraving = model_fields(
            size, np.array([[0., 0.], [0., 1.]]), previous, len(previous), 0.)
        np.testing.assert_array_equal(surviving, earlier_engraving)
        xy = disk((size, size))
        interior = np.hypot(*xy) < .93
        self.assertGreater(float((all_moved[interior] > .98).mean()), .95)
        self.assertGreater(float((surviving[interior] < .02).mean()), .90)
        self.assertGreater(int((surviving[interior] > .93).sum()), 75)
        np.testing.assert_array_equal(touched, 0.)
        np.testing.assert_array_equal(untouched, old_art)
        self.assertGreater(abs(old_bed-old_art).max(), .5)

    def test_consecutive_portraits_keep_untouched_photo_in_the_erase_control_too(self):
        phase = 24.31
        previous, _ = compile_portrait({'old lips': np.array([[.1, .22], [.6, .4]])},
                                       np.array([[0., 0.], [1., 0.]]), phase, 3.)
        drawing = inward_spiral(1201, previous[-1, 0])
        x, y = disk((147, 147))
        radius = np.hypot(x, y)
        clear = np.rint(91 + 7*np.cos(15*radius)).astype('float32')
        earlier = clear + np.float32(7*((x > 0) & (abs(y) < .025)))
        opening = earlier + 6
        image, fields = predict(clear, earlier, opening, previous, drawing, 70, comparison=True)
        self.assertEqual(set(fields), {'clear_only', 'touched', 'engraved'})
        self.assertEqual(fields['clear_only'].dtype, np.uint8)
        self.assertFalse(fields['engraved'].any())
        self.assertTrue(fields['touched'].any())
        untouched = radius < .78
        np.testing.assert_array_equal(image[untouched], opening[untouched])
        np.testing.assert_array_equal(fields['clear_only'][untouched], opening[untouched])
        with self.assertRaisesRegex(ValueError, 'clean-bed estimate must match'):
            predict(clear, earlier, opening, previous, drawing, 70, previous_phase=phase+.5)
        with self.assertRaisesRegex(ValueError, 'one continuous fine rake'):
            predict(clear, earlier, opening, previous[[-1, -1]], drawing, 70)
        other_dock = drawing.copy()
        other_dock[:, 0] += .3
        with self.assertRaisesRegex(ValueError, 'new drawing.s rim dock'):
            predict(clear, earlier, opening, previous, other_dock, 70)


if __name__ == '__main__':
    unittest.main()
