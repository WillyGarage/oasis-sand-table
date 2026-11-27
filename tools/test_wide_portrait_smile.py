"""Check the photographed smile against known lip openings without using private photos."""

import unittest

import cv2
import numpy as np

from wide_portrait_smile import LOWER, UPPER, loop_sections, measured_smile
from wide_portrait import crosses_opening, cut_nearby_shadow


class SmileTest(unittest.TestCase):
    def scene(self, angle=0., mirror=1, height=23., mode='teeth', exposure=1.):
        size, diameter, groove, width = 240, 360., 7.5, 108.
        translation = np.array([13., -9.])
        scale = np.array([1., -1.]) * size / diameter
        across = mirror * np.array([np.cos(angle), np.sin(angle)])
        down = np.array([-np.sin(angle), np.cos(angle)])
        basis = np.column_stack((across, down))
        origin = np.array([119., 145.]) - .5 * width * across

        def pixels(x, y):
            return np.stack(np.broadcast_arrays(x, y), axis=-1) @ basis.T + origin

        def margins(x):
            u = x / width
            bow = 4 * u * (1 - u)
            top = bow * (2. - 4. * np.sin(1.8 * np.pi * u))
            bottom = top + height * bow * (1 - .2 * u)
            return top, bottom

        y, x = np.indices((size, size))
        uv = (np.stack((x, y), axis=-1) - origin) @ basis
        x, y = uv[..., 0], uv[..., 1]
        top, bottom = margins(x)
        mouth = (x >= 0) & (x <= width) & (y >= top) & (y <= bottom)
        light = np.full(x.shape, 116.)
        if mode == 'teeth':
            light[mouth] = 225.
            # Narrow tooth divisions disappear at the groove width. Their
            # presence must not add any vertical strokes to the lip opening.
            light[mouth] -= (np.cos(.48 * x[mouth])**36) * 62
        elif mode == 'dark':
            light[mouth] = 28.
        elif mode == 'one_edge':
            light[y < top] = 52.
        elif mode == 'one_side':
            light[mouth & (x < width * .5)] = 220.
        elif mode == 'obscured':
            light[mouth & (np.abs(x - .5 * width) > .10 * width)] = 220.
        image = cv2.GaussianBlur((light * exposure).astype('uint8'), (0, 0), .85)
        mesh = np.full((478, 2), 120.)
        xs = np.linspace(0, width, len(UPPER))
        ts, bs = margins(xs)
        bow = 4 * xs / width * (1 - xs / width)
        mesh[UPPER] = pixels(xs, ts + 1.3 * bow)
        mesh[LOWER] = pixels(xs, bs - 1.6 * bow)
        mesh[[61, 291]] = mesh[[78, 308]]
        mesh[[468, 473]] = pixels([.15 * width, .85 * width], -50.)
        def mark(kind, points, closed):
            return dict(kind=kind, points=((points - size / 2) / scale + translation).tolist(), closed=closed)

        marks = [mark('eye', mesh[[i]] + [[-2, 0], [2, 0]], False) for i in [468, 473]]
        oldx = np.array([0., .30 * width, .56 * width, .70 * width, width])
        old_top, old_bottom = margins(oldx)
        bow = 4 * oldx / width * (1 - oldx / width)
        old = np.concatenate([pixels(oldx, old_top - 7 * bow), pixels(oldx, old_bottom - 8 * bow)[-2:0:-1]])
        marks.append(mark('smile', old, True))
        args = [image, [mesh], marks, diameter, groove, translation]
        def read(mark):
            return ((np.asarray(mark['points']) - translation) * scale + size / 2 - origin) @ basis
        return args, width, margins, read

    def test_closed_outline_follows_both_edges_under_tilt_and_mirroring(self):
        for angle, mirror, mode, exposure in ((.40, 1, 'teeth', 1), (-.32, -1, 'dark', .73)):
            with self.subTest(mode=mode):
                args, width, margins, read = self.scene(angle, mirror, mode=mode, exposure=exposure)
                proposal = measured_smile(*args)
                self.assertIsNotNone(proposal)
                self.assertTrue(proposal['closed'])
                self.assertEqual(proposal['kind'], 'smile')
                samples = np.linspace(.12, .88, 19) * width
                sections = loop_sections(read(proposal), samples)
                self.assertIsNotNone(sections)  # Exactly two intersections, even between bright teeth.
                self.assertLess(np.max(np.abs(sections - margins(samples))), 2.1)
                self.assertLess(abs(np.ptp(read(proposal)[:, 0]) - width), 1.)
                args[2][-1] = proposal
                self.assertIsNone(measured_smile(*args))

    def gum_scene(self, angle, mirror):
        args, width, margins, read = self.scene(angle, mirror)
        gray, meshes, _, _, _, _ = args
        mesh = meshes[0]
        start, end = mesh[[78, 308]]
        across = (end - start) / width
        down = np.array([-np.sin(angle), np.cos(angle)])

        def pixels(x, y):
            return start + x[..., None] * across + y[..., None] * down

        def bowl(x):
            return np.clip(4 * x / width * (1 - x / width), 0, 1)

        y, x = np.indices(gray.shape)
        coords = np.stack((x, y), axis=-1) - start
        x, y = coords @ across, coords @ down
        top, bottom = margins(x)
        lip = np.full((*gray.shape, 3), (100, 98, 185), dtype=np.uint8)
        opened = (x >= 0) & (x <= width) & (y > top) & (y < bottom)
        lip[opened] = (47, 49, 105)  # Exposed gum behind the upper lip.
        white = opened & (y > top + .39 * (bottom - top)) & (x > .08 * width) & (x < .92 * width)
        lip[white] = (187, 207, 221)
        lip[white & (np.cos(.32 * x) > .97)] = (135, 151, 172)
        # At either end, the open mouth darkens while the lip stays bright.
        lip[opened & ((x < .08 * width) | (x > .92 * width))] = (25, 26, 45)
        image = cv2.GaussianBlur(lip, (0, 0), .8)
        xs = np.linspace(0, width, len(UPPER))
        top, bottom = margins(xs)
        mesh[UPPER] = pixels(xs, top + .23 * (bottom - top))
        mesh[LOWER] = pixels(xs, bottom + 3 * bowl(xs))
        outer = np.linspace(0, width, 7)
        mesh[[61, 40, 37, 0, 267, 270, 291]] = pixels(outer, margins(outer)[0] - 4. * bowl(outer))
        return args, image, width, margins, read

    def test_colored_gum_and_teeth_trace_preserves_the_opening(self):
        for angle, mirror in ((.37, 1), (-.43, -1)):
            with self.subTest(angle=angle):
                args, image, width, margins, read = self.gum_scene(angle, mirror)
                proposal = measured_smile(*args, color=image)
                self.assertIsNotNone(proposal)
                x = np.linspace(.18, .82, 25) * width
                sections = loop_sections(read(proposal), x)
                self.assertIsNotNone(sections)
                self.assertLess(np.max(np.abs(sections - margins(x))), 2.)

    def test_color_trace_requires_both_teeth_and_a_distinct_gum_band(self):
        args, image, *_ = self.gum_scene(.22, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self.assertIsNone(measured_smile(*args, color=cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)))
        for color in ((47, 49, 105), (187, 207, 221)):
            self.assertIsNone(measured_smile(*args, color=np.full_like(image, color)))
        no_gum = image.copy()
        no_gum[no_gum[:, :, 1] < 95] = (100, 98, 185)
        self.assertIsNone(measured_smile(*args, color=no_gum))
        bright = image[:, :, 1] > 140
        image[bright] = (47, 49, 105)
        self.assertIsNone(measured_smile(*args, color=image))

    def test_no_opening_from_flat_light_one_edge_or_partial_occlusion(self):
        for mode in ('flat', 'one_edge', 'one_side', 'obscured'):
            with self.subTest(mode=mode):
                args, *_ = self.scene(.18, mode=mode)
                self.assertIsNone(measured_smile(*args))

    def test_short_corner_extends_only_into_visible_opening(self):
        for side, angle, mirror in ((0, .23, 1), (1, -.32, -1)):
            with self.subTest(side=side):
                args, width, _, read = self.scene(angle, mirror, height=40., mode='dark')
                gray, meshes, marks, diameter, groove, _ = args
                mesh = meshes[0]
                across = (mesh[308] - mesh[78]) / width
                initial = np.array(marks[-1]['points'])
                scale = np.array([1., -1.]) * len(gray) / diameter
                initial[0 if side == 0 else 4] += (1 if side == 0 else -1) * 15 * across / scale
                marks[-1]['points'] = initial.tolist()
                proposal = measured_smile(*args, corners_only=True)
                self.assertIsNotNone(proposal)
                corners = np.sort(read(proposal)[:, 0])[[0, -1]]
                self.assertLess(abs(corners[side] - side * width), groove * abs(scale[0]))
                self.assertAlmostEqual(corners[1 - side], (1 - side) * width, places=3)
                unchanged = np.linspace(.55, .96, 13) if side == 0 else np.linspace(.04, .45, 13)
                np.testing.assert_allclose(loop_sections(read(proposal), unchanged * width),
                                           loop_sections(read(marks[-1]), unchanged * width), atol=.65)
                args[0] = np.full_like(gray, 95)
                self.assertIsNone(measured_smile(*args, corners_only=True))
                args[0] = gray
                marks[-1]['points'].insert(1, ((initial[0] + initial[1]) / 2).tolist())
                self.assertIsNone(measured_smile(*args, corners_only=True))

    def test_small_or_closed_mouth_keeps_its_first_stroke(self):
        args, *_ = self.scene(height=4.0)
        self.assertIsNone(measured_smile(*args))
        args, *_ = self.scene()
        args[2][-1]['closed'] = False
        self.assertIsNone(measured_smile(*args))

    def test_another_face_cannot_supply_the_mouth(self):
        args, *_ = self.scene()
        args[1][0] += [73., 17.]
        self.assertIsNone(measured_smile(*args))

    def test_incomplete_or_nonfinite_mesh_keeps_the_original(self):
        args, *_ = self.scene()
        mesh = args[1][0]
        args[1] = [mesh[:468]]
        self.assertIsNone(measured_smile(*args))
        mesh[468] = np.nan
        args[1] = [mesh]
        self.assertIsNone(measured_smile(*args))

    def test_mouth_interior_excludes_access_strokes_even_far_from_lips(self):
        loop = np.array([[-30., 0.], [0., 12.], [30., 0.], [0., -12.]])
        self.assertTrue(crosses_opening(np.array([[-2., 0.], [2., 0.]]), loop, .42))
        self.assertFalse(crosses_opening(np.array([[0., 11.95], [0., 12.]]), loop, .42))
        self.assertTrue(crosses_opening(np.array([[0., 11.95]]), loop, 0))
        self.assertFalse(crosses_opening(np.array([[-22., 9.], [33., 0.]]), loop, 0))

    def test_keep_the_connected_distant_cheek_without_bridging_a_gap(self):
        mark = {'kind': 'shade', 'points': [[0., 0.], [35., 0.], [70., 0.]]}
        positions = np.arange(71)
        self.assertEqual(cut_nearby_shadow(mark, positions >= 20, 7)['points'],
                         [[20., 0.], [35., 0.], [70., 0.]])
        self.assertIs(cut_nearby_shadow(mark, (positions < 25) | (positions > 40), 7), mark)


if __name__ == '__main__':
    unittest.main()
