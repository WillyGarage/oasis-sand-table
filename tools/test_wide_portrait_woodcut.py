"""Protect the selected person's face and the actual hair in a guest woodcut."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from wide_portrait_hair import FACE_OVAL
from wide_portrait_woodcut import hair_field, hatches, verify_hatches, woodcut_version


class WoodcutTest(unittest.TestCase):
    def field(self, angle=0.):
        size, groove = 190, 4.
        mesh = np.full((478, 2), 95.)
        origin = np.array([95., 98.])
        co, si = np.cos(angle), np.sin(angle)
        basis = np.array([[co, -si], [si, co]])

        def px(u, v):
            return origin + np.stack(np.broadcast_arrays(u, v), axis=-1) @ basis.T

        theta = np.linspace(-np.pi/2, 1.5*np.pi, len(FACE_OVAL), endpoint=False)
        mesh[FACE_OVAL] = px(38*np.cos(theta), 51*np.sin(theta))
        mesh[[468, 473]] = px([-20., 20.], [-8., -8.])
        mesh[[1, 13, 14]] = px([1., 0., 0.], [5., 23., 24.])
        yy, xx = np.indices((size, size))
        x, y = ((np.stack((xx, yy), axis=-1) - origin) @ basis).transpose(2,0,1)
        head = ((x / 50)**2 + ((y+7) / 68)**2 < 1)
        # The same color is used for the hair, a region on the lower cheek
        # and a neighboring person's disconnected hair outside this head.
        hair = head & (y < -27)
        confidence = ((hair | ((abs(x-22)<6) & (abs(y-18)<8)) |
                        ((abs(x-70)<6) & (abs(y+38)<12))).astype('float32') * .92)
        return mesh, confidence, head, groove, px, basis

    def test_selected_scalp_turns_with_the_head_and_excludes_the_face(self):
        for angle in (0., np.pi/3):
            mesh, conf, head, groove, px, basis = self.field(angle)
            core, scalp, strict, photographed, direction = hair_field(conf, head, mesh, groove)
            self.assertTrue(np.all(core <= head))
            self.assertTrue(np.all(scalp <= core))
            for point in (px(22,18), px(70,-38)):
                x, y = point.round().astype(int)
                self.assertFalse(photographed[y,x])
            expected = basis @ np.array([1., .45])
            np.testing.assert_allclose(direction, expected / np.linalg.norm(expected), atol=1e-6)
            lines = list(hatches(core, direction, groove))
            self.assertGreater(len(lines), 4)
            for line in lines:
                x,y = line.round().astype(int).T
                self.assertTrue(strict[y,x].all())

    def test_small_tuft_of_long_hair_does_not_qualify_as_a_woodcut(self):
        mesh, _, head, groove, px, _ = self.field()
        conf = np.zeros_like(head, dtype='float32')
        conf[10:64, 12:182] = .92
        small = np.zeros_like(head)
        small[27:64, 85:108] = True
        with self.assertRaises(ValueError):
            hair_field(conf, small, mesh, groove)

    def test_round_trip_checks_hair_entries_and_hidden_features(self):
        # The original mark's physical number was 3. A hidden mark 2 must
        # not appear when the missing old hair is replaced.
        groove, radius, size = 5., 160., 145
        box = np.zeros((size,size), dtype='uint8')
        box[49:114,39:127] = 1
        clearance = cv2.distanceTransform(box, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        safe_mark = dict(kind='eye', closed=False, points=[[22.,33.],[27.,36.]])
        segments = [np.asarray(safe_mark['points'])]
        marks = [safe_mark]
        for y in [58.,68.,78.,88.,98., 104.]:
            marks.append(dict(kind='shade',closed=False,points=[[54.,y],[112.,y]]))
            segments.append(np.array([[50.,y],[54.,y],[112.,y],[54.,y],[50.,y]]))
        segments[-1][0] = [29.,104.]  # Its body is safe, but its entrance starts outside the hair.
        route_xy = np.vstack(segments)
        route = np.column_stack((np.arctan2(route_xy[:,1],route_xy[:,0]),np.linalg.norm(route_xy,axis=1)/radius))
        end = np.cumsum([len(q) for q in segments])
        events = [dict(source=i,first=int(hi-len(segment)),last=int(hi-1)) for i,(hi,segment) in enumerate(zip(end,segments))]
        base = dict(events=[dict(source=3,first=0,last=1)])
        source = dict(width=groove,radius=radius,dock=[0.,0.])
        args = (None,source,base,route[:2],[3],marks,dict(events=events),clearance,box,lambda q:q,groove)
        with patch('wide_portrait_woodcut.downloaded_route',return_value=route):
            safe,unsafe = verify_hatches(*args)
            self.assertEqual(safe,[1,2,3,4,5])
            self.assertEqual(unsafe,[6])
            wrong = route[:2].copy()
            wrong[1,1] += .02
            with self.assertRaisesRegex(ValueError,'move an existing stroke'):
                verify_hatches(*args[:3], wrong, *args[4:])
            dense_hair = np.ones_like(box)
            with self.assertRaisesRegex(ValueError,'cover too little'):
                verify_hatches(*args[:8], dense_hair, *args[9:])

    def test_curved_strands_count_only_where_the_signed_route_follows_the_bend(self):
        groove, radius = 3., 200.
        angle = np.linspace(0., np.pi, 70)
        arcs = [np.column_stack((80 + r*np.cos(angle), 25 + r*np.sin(angle)))
                for r in (22, 33, 44, 55)]
        hair = np.zeros((145, 160), 'uint8')
        for arc in arcs:
            cv2.polylines(hair, [arc.round().astype('int32')], False, 1, 13)
        clearance = cv2.distanceTransform(hair, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        points = np.vstack(arcs)
        route = np.c_[np.arctan2(points[:,1], points[:,0]), np.linalg.norm(points,axis=1)/radius]
        events = [dict(source=i, first=i*len(angle), last=(i+1)*len(angle)-1) for i in range(4)]
        source = dict(width=groove, radius=radius, dock=[0.,0.])
        def check(lines):
            marks = [dict(points=line) for line in lines]
            return verify_hatches(None, source, {'events':[]}, [], [], marks, {'events':events},
                                  clearance, hair, lambda q:q, groove)
        with patch('wide_portrait_woodcut.downloaded_route', return_value=route):
            self.assertEqual(check(arcs), ([0, 1, 2, 3], []))
            with self.assertRaisesRegex(ValueError, 'cover too little'):
                check([arc[[0,-1]] for arc in arcs])

    def test_unused_old_marks_do_not_return_and_beard_stays(self):
        mesh,conf,head,groove,px,_ = self.field()
        size=len(conf)
        def mark(kind, points, **extra):
            return dict(kind=kind,closed=kind=='head',points=((points-size/2)*[1,-1]).tolist(),**extra)
        boundary=cv2.findContours(head.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0][0][:,0]
        eye0,eye1=mesh[[468,473]]
        mesh[[61,291]]=px([-7,7],[23,23])
        marks=[mark('head',boundary),mark('eye',eye0+[[-3,0],[3,0]]),mark('eye',eye1+[[-3,0],[3,0]]),
               mark('smile',mesh[[61,291]]),mark('shade',px([-15,15],[-42,-42]),facialHair=True),
               mark('shade',px([18,25],[15,20]),facialHair=True),
               mark('shade',px([4,10],[12,13]))]  # Old proposal omitted from the baseline download.
        base={'events':[dict(source=i) for i in range(6)]}
        class Page:
            def evaluate(self, _, revised):
                return dict(events=[dict(source=i) for i in range(len(revised))])
        with patch('wide_portrait_woodcut.downloaded_route',return_value=[]), patch(
            'wide_portrait_woodcut.verify_hatches',return_value=([5,6,7,8],[])):
            revised,_,_=woodcut_version(Page(),dict(width=groove,diameter=size,dock=[0,0]),
                                         marks,base,(conf,[mesh],[conf]),None)
        self.assertEqual(revised[:5],marks[:4]+[marks[5]])
        self.assertNotIn(marks[4],revised)
        self.assertNotIn(marks[6],revised)


if __name__ == '__main__':
    unittest.main()
