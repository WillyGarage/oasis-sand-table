"""A cropped hairstyle needs actual strands on both sides of the selected face."""

import unittest
from unittest.mock import patch

import numpy as np

from wide_portrait_hair import FACE_OVAL
from wide_portrait_locks import cropped_strands, nearby_faces
from wide_portrait_woodcut import at_pixels, guest_woodcut


class CroppedLocksTest(unittest.TestCase):
    def scene(self, angle=0., mirrored=1, texture=True):
        size = 240
        center = np.array([120., 112.])
        across = mirrored * np.array([np.cos(angle), np.sin(angle)])
        down = np.array([-np.sin(angle), np.cos(angle)])
        basis = np.column_stack((across, down))
        yy, xx = np.indices((size, size))
        u, v = ((np.stack((xx, yy), axis=-1) - center) @ basis).transpose(2, 0, 1)
        def px(x, y):
            return np.stack(np.broadcast_arrays(x, y), axis=-1) @ basis.T + center

        mesh = np.broadcast_to(center, (478, 2)).copy()
        angles = np.linspace(-np.pi/2, 1.5*np.pi, len(FACE_OVAL), endpoint=False)
        mesh[FACE_OVAL] = px(46.*np.cos(angles), 68.*np.sin(angles))
        mesh[[468, 473]] = px([-26., 26.], [-9., -9.])
        mesh[[1, 13, 14]] = px([0., 1., 1.], [3., 21., 24.])
        skin = (u/44.)**2 + (v/68.)**2 < 1
        head = (u/53.)**2 + ((v+1.)/78.)**2 < 1
        hair = ((u/118.)**2 + ((v+2.)/176.)**2 < 1) & ~skin & ((np.abs(u) > 40.) | (v < -45.))
        light = np.full((size, size), 169.)
        grain = np.sin(.54 * (u - 4.*np.sin(v/26.) - .09*v))
        light[hair] = 71 + (25 * grain[hair] if texture else 0)
        return light.astype('uint8'), .94*hair.astype('float32'), skin.astype('float32'), mesh, head

    def test_long_curves_follow_observed_hair_under_tilt_and_mirroring(self):
        for angle, mirror in ((.13, 1), (-.19, -1)):
            with self.subTest(angle=angle):
                gray, confidence, skin, mesh, head = self.scene(angle, mirror)
                strands, _, attached = cropped_strands(gray, confidence, skin, mesh, head, 3.,
                                                       np.array([120., 120.]), np.zeros_like(head))
                for side in (-1, 1):
                    self.assertGreaterEqual(sum(s == side for s, _ in strands), 2)
                for _, strand in strands:
                    self.assertTrue(at_pixels(attached, strand).all())
                    self.assertLess(np.linalg.norm(strand-120, axis=1).max(), 120-2.8*3.)
                    self.assertGreater(np.linalg.norm(np.diff(strand, axis=0), axis=1).sum(), 8*3.)

    def test_plain_hair_color_does_not_invent_internal_strands(self):
        gray, hair, skin, mesh, head = self.scene(texture=False)
        strands, _, _ = cropped_strands(gray, hair, skin, mesh, head, 3.,
                                        np.array([120., 120.]), np.zeros_like(head))
        self.assertEqual(strands, [])

    def test_a_head_with_no_missing_hair_keeps_its_drawing(self):
        gray, hair, skin, mesh, head = self.scene()
        with self.assertRaises(ValueError):
            cropped_strands(gray, hair, skin, mesh, np.ones_like(head), 3.,
                            np.array([120., 120.]), np.zeros_like(head))

    def test_foreign_head_or_face_box_touching_this_hair_prevents_attribution(self):
        _, hair, _, mesh, _ = self.scene()
        other = mesh + [93., -3.]
        self.assertTrue(nearby_faces({}, [mesh, other], mesh, hair > .5))
        self.assertFalse(nearby_faces({}, [mesh], mesh, hair > .5))
        selected = dict(x=120., y=120., w=80.)
        box = dict(x=216., y=118., w=65.)
        source = dict(selected=selected, boxes=[selected, box], crop={'area':dict(x=120., y=120., radius=120.)})
        self.assertTrue(nearby_faces(source, [mesh], mesh, hair > .5))
        box['x'] = 340.
        self.assertFalse(nearby_faces(source, [mesh], mesh, hair > .5))

    def test_existing_signed_woodcut_wins_and_locks_use_the_completed_face(self):
        earlier, complete = (['old marks'], 'old plan'), (['final marks'], 'final plan')
        with (patch('wide_portrait_woodcut.woodcut_version', return_value=('same', 'plan', 9)) as old,
              patch('wide_portrait_locks.cropped_woodcut', return_value=('locks', 'new plan', 5)) as new):
            style = guest_woodcut(None, {}, None, None, earlier, complete)
            self.assertEqual(style[:3], ('same', 'plan', 9))
            new.assert_not_called()
            old.side_effect = ValueError('First style unavailable.')
            self.assertEqual(guest_woodcut(None, {}, None, None, earlier, complete)[:3], ('locks','new plan',5))
            new.assert_called_once_with(None, {}, *complete, None, None)
            new.side_effect = ValueError('Cropped hair was ambiguous.')
            with self.assertRaisesRegex(ValueError, 'First style unavailable'):
                guest_woodcut(None, {}, None, None, earlier, complete)


if __name__ == '__main__':
    unittest.main()
