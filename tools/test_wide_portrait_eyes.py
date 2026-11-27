"""Check local eye tracing on synthetic photos with known, unexaggerated gaze."""

import unittest

import cv2
import numpy as np

from wide_portrait_eyes import EYES, dark_iris_center, lower_iris_return, measured_eyes, measured_lens_eyes


class EyesTest(unittest.TestCase):
    def scene(self, angle=0., mirror=1, period=1, empty=False, mixed=False, short=False, catchlight=False):
        size, groove = 280, 6.
        diameter, translation = 350., np.array([9., -14.])
        scale = np.array([1., -1.]) * size / diameter
        across = mirror * np.array([np.cos(angle), np.sin(angle)])
        down = np.array([-np.sin(angle), np.cos(angle)])
        basis = np.column_stack((across, down))
        middle = np.array([139., 126.])
        y, x = np.indices((size, size))
        xy = np.stack((x, y), axis=-1)
        light = np.full(x.shape, 123.)
        mesh = np.full((478, 2), 135.)
        marks, truth = [], []

        def mark(kind, points, closed=True):
            return dict(kind=kind, points=((points - size / 2) / scale + translation).tolist(), closed=closed)

        for side, (upper, lower, ring) in enumerate(EYES):
            start = middle + (-77. + 96 * side) * across
            width = 55. + 3 * side
            depth = 3.5 if short else 15.
            cx, cy = (.55 + .035 * side) * width, -1.
            rx, ry = 10., 11.
            u, v = ((xy - start) @ basis).transpose(2, 0, 1)
            taper = 4 * u / width * (1 - u / width)
            aperture = (u >= 0) & (u <= width) & (v >= -.62 * depth * taper) & (v <= .38 * depth * taper)
            real_sign = 1 if mixed and side == 1 else -1
            if not empty:
                light[aperture] = 53.
                outside = ((u - cx) / rx)**2 + ((v - cy) / ry)**2 > 1
                light[aperture & outside & ((u - cx) * real_sign > 0)] = 183.
                light[aperture & ~outside] = 45.
            if catchlight:
                light[(u - cx + 5)**2 + (v - cy)**2 < 1.8**2] = 250.
            def px(u, v):
                return start + np.stack(np.broadcast_arrays(u,v), axis=-1) @ basis.T
            xs = np.linspace(0,width,len(upper))
            arch = 4 * xs / width * (1 - xs / width)
            mesh[upper], mesh[lower] = px(xs,-.62 * depth * arch), px(xs,.38 * depth * arch)
            mesh[ring] = px(cx + np.array([0, rx, 0, -rx, 0]) - 1.0,
                            cy + np.array([0, 0, -ry, 0, ry]))
            marks.append(mark('eye', np.concatenate((mesh[upper][[0,3,5,8]], mesh[lower][[5,3]])) - 4 * down))
            truth.append((start,basis,cx,cy,rx,ry,real_sign))
        mesh[[61,291]] = middle + [[-15,59],[15,59]]
        mouth = mesh[[61,291]].mean(axis=0)
        marks = [marks[1], mark('smile',mouth + [[-15,0],[0,-3],[15,0],[0,3]]), marks[0]]
        image = cv2.GaussianBlur(np.clip(light * period, 0, 255).astype('uint8'),(0,0),.65)
        args = [image,[mesh],marks,diameter,groove,translation]
        def pixels(mm):
            return (np.asarray(mm) - translation) * scale + size / 2
        return args, truth, pixels

    def glasses(self, **options):
        args, truth, pixels = self.scene(**options)
        image, meshes, marks, diameter, _, shift = args
        scale = np.array([1., -1.]) * len(image) / diameter
        lenses = []
        for start, basis, *_ in truth:
            rectangle = np.array([[-10,-19],[67,-19],[67,21],[-10,21]])
            points = rectangle @ basis.T + start
            lenses.append(dict(kind='glasses',closed=True,points=((points - len(image)/2)/scale+shift).tolist()))
        args[2] = [lenses[1], marks[1], lenses[0]]
        return args, truth, pixels

    def test_eyes_inside_spectacles_follow_photo_without_closing_both_lids(self):
        args, truth, pixels = self.glasses(angle=.22,mirror=-1,catchlight=True)
        initial = repr(args[2])
        pair = measured_lens_eyes(*args)
        self.assertIsNotNone(pair)
        self.assertEqual(repr(args[2]),initial)
        for side,(result,(start,basis,cx,cy,rx,ry,sign)) in enumerate(zip(pair,truth)):
            mark = result['mark']
            self.assertFalse(mark['closed'])
            iris = (pixels(result['iris']) - start) @ basis
            target = cx + sign * rx * np.sqrt(1-((iris[:,1]-cy)/ry)**2)
            self.assertLess(np.max(abs(iris[:,0]-target)),1.7)
            # All proposed ink is on the upper lid or measured iris. No invented
            # return across the bottom of a partly obscured eye.
            trace = (pixels(mark['points']) - start) @ basis
            width = 55. + 3*side
            upper = -.62*15*4*trace[:,0]/width*(1-trace[:,0]/width)
            gap = np.linalg.norm(trace[:,None]-iris,axis=2).min(axis=1)
            self.assertLess(np.max(np.minimum(gap,abs(trace[:,1]-upper))),1.6)

    def test_dark_center_needs_light_on_both_sides_and_a_full_groove_of_depth(self):
        x = np.linspace(20., 80., 41)
        opening = np.sin((x - x[0]) * np.pi / (x[-1] - x[0]))
        feature = {'upper': np.column_stack((x, 33 - 5 * opening)),
                   'lower': np.column_stack((x, 33 + 8 * opening)),
                   'center': np.array([50., 34.])}
        _, cols = np.indices((70, 100))
        image = np.full(cols.shape, 130., np.float32)
        image[:, 43:58] = 27
        image[:, 48:53] = 12
        _, stroke = dark_iris_center(image, feature, 6.)
        self.assertTrue(np.all((stroke[:,0] >= 48) & (stroke[:,0] < 53)))
        image[:, :43] = 27
        image[:, 48:53] = 27
        self.assertIsNone(dark_iris_center(image, feature, 6.))

    def test_partly_reflected_iris_needs_a_visible_lower_edge_and_two_upper_flanks(self):
        x = np.arange(20., 81.)
        upper = np.column_stack((x, np.full_like(x, 25.)))
        lower = np.column_stack((x, np.full_like(x, 40.)))
        for side in (-1, 1):
            with self.subTest(side=side):
                # The reflection hides one flank in the lower half of the
                # aperture. The other three edges remain clear in the photo.
                flank = 50 + 10 * side
                feature = dict(upper=upper, lower=lower, center=np.array([50., 32.]),
                               iris=np.array([[flank, 25.], [flank, 40.]]), top_join=flank - 20)
                image = np.full((70, 100), 130., np.float32)
                image[25:41] = 28
                image[25:32, :40] = image[25:32, 61:] = 145
                visible_side = slice(None, 40) if side < 0 else slice(61, None)
                image[25:41, visible_side] = 145
                self.assertIsNone(dark_iris_center(image, feature, 6.))
                _, core = lower_iris_return(image, feature, 6.)
                np.testing.assert_allclose(core[-1], [50, 40], atol=1.5)

                # With no lower edge the dark stripe cannot locate an iris.
                image[41:] = 28
                self.assertIsNone(lower_iris_return(image, feature, 6.))

    def test_empty_or_unresolved_eye_and_wrong_lens_keep_first_drawing(self):
        for opts in (dict(empty=True),dict(short=True),dict(mixed=True)):
            with self.subTest(opts=opts):
                args, _, _ = self.glasses(**opts)
                self.assertIsNone(measured_lens_eyes(*args))
        args, _, _ = self.glasses()
        args[2][0]['points'] = args[2][2]['points']
        self.assertIsNone(measured_lens_eyes(*args))

    def test_edges_follow_measured_gaze_with_both_lids_and_no_line_across_white(self):
        for angle, mirror, level in ((.51,1,1.),(-.34,-1,.53)):
            with self.subTest(angle=angle):
                args, truth, pixels = self.scene(angle,mirror,level,catchlight=True)
                variants = measured_eyes(*args)
                self.assertEqual(len(variants),2)
                for pair in variants:
                    self.assertEqual([e['index'] for e in pair],[2,0])
                    for obs,(start,basis,cx,cy,rx,ry,sign) in zip(pair,truth):
                        center = (pixels(obs['center']) - start) @ basis
                        self.assertLess(np.linalg.norm(center - [cx,cy]),1.7)
                        iris = (pixels(obs['iris']) - start) @ basis
                        expected_x = cx + sign * rx * np.sqrt(1 - ((iris[:,1] - cy)/ry)**2)
                        self.assertLess(np.abs(iris[:,0]-expected_x).max(),1.7)
                        self.assertTrue(obs['mark']['closed'])
                        # Each vertex lies either on the measured aperture or on
                        # this actual iris flank, including both retraced joins.
                        edge = np.concatenate((pixels(obs['aperture']),pixels(obs['iris'])))
                        line = pixels(obs['mark']['points'])
                        self.assertLess(np.linalg.norm(line[:,None] - edge,axis=2).min(axis=1).max(),1e-5)
                        # Check both joins, so skipping from the far corner across
                        # the light part of the eye cannot pass a vertex-only test.
                        mids = (line + np.roll(line,-1,axis=0))/2
                        self.assertLess(np.linalg.norm(mids[:,None] - edge,axis=2).min(axis=1).max(),1.7)

    def test_faint_or_unresolved_pair_keeps_first_drawing(self):
        for options in (dict(empty=True),dict(empty=True,catchlight=True),dict(short=True),dict(mixed=True)):
            with self.subTest(options=options):
                args, *_ = self.scene(**options)
                self.assertFalse(measured_eyes(*args))

    def test_previously_drawn_iris_and_other_person_keep_first_drawing(self):
        args, *_ = self.scene()
        first = measured_eyes(*args)[0]
        args[2][first[0]['index']] = first[0]['mark']
        self.assertFalse(measured_eyes(*args))
        args, *_ = self.scene()
        args[1][0] += [30,90]
        self.assertFalse(measured_eyes(*args))


if __name__ == '__main__':
    unittest.main()
