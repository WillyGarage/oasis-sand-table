#!/usr/bin/env python3
"""section_faces - a face as "combed sections" (stained glass) plan for tools/section_comb.py. SIMULATION/PATH ONLY.

    plan = face_plan('lek', table='mini')            # or 'thomas'; table 'mini' (r 114) | 'big' (r 420)
    res = section_comb.comb(plan, order='background_first')

Design (see captures/relief-study/v3/STATUS.md, faces section): features sit on section boundaries (eye opening, lids,
brows, nose bridge / tip / wings, lips as two sections + teeth), the rest of the face is cut by lines through the form
(forehead, temples, cheekbone, nasolabial fold, chin, jaw, ears), hair is a fan of locks around the crown, beard / body
are sections, and the background is sections at 5 mm (big table 9 mm). Stroke spacing follows the photo tone (tight =
lit, coarse = dark; lightened). Face data (masks, landmarks) come from tools/relief_faces.Portrait; private, local only.
"""
import math, os, sys
import numpy as np
import cv2
from scipy import ndimage as ndi
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, box
from shapely.ops import unary_union, polygonize
from shapely import affinity

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from relief_faces import Portrait
import section_raptor as sr

ROOT = os.path.dirname(HERE)
FACES = ROOT + '/captures/relief-study/faces/'

# MediaPipe face-mesh indices (image-left = the subject's right; "L" below means image left)
EYE_L = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
EYE_R = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
BROW_L_UP, BROW_L_LO = [70, 63, 105, 66, 107], [46, 53, 52, 65, 55]
BROW_R_UP, BROW_R_LO = [300, 293, 334, 296, 336], [276, 283, 282, 295, 285]
LIPS_OUT = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
LIPS_IN = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
WING_L = [129, 49, 48, 64, 98, 97, 2]
WING_R = [358, 279, 278, 294, 327, 326, 2]
BRIDGE = [168, 6, 197, 195, 5]


def geom_to_secs(g, name, **kw):
    """shapely geometry -> list of section dicts (one per polygon)."""
    out = []
    polys = [g] if g.geom_type == 'Polygon' else [p for p in getattr(g, 'geoms', []) if p.geom_type == 'Polygon']
    polys = [p for p in polys if p.area > 1.0]
    for i, p in enumerate(polys):
        d = dict(name=name if len(polys) == 1 else '%s_%d' % (name, i), kind='subject',
                 poly=[list(c) for c in p.exterior.coords][:-1],
                 holes=[[list(c) for c in h.coords][:-1] for h in p.interiors])
        d.update(kw)
        out.append(d)
    return out


class FacePlan:
    def __init__(self, who, table='mini', bg_sp=None, k_sp=None, light=22.0, bold=None):
        self.who, self.table = who, table
        self.P = P = Portrait(FACES + who + '.pkl', table=table)
        self.R = P.cv.R
        self.big = table == 'big'
        self.sc = P.s / 102.6                      # feature scale vs Mini
        self.k_sp = k_sp if k_sp else (1.0 if not self.big else 2.2)
        self.bg_sp = bg_sp if bg_sp else (5.0 if not self.big else 9.0)
        self.light = light
        self.bold = (table == 'mini') if bold is None else bold     # Mini: fewer, bigger feature sections (a 6.4 mm ball cannot resolve lids + sockets)
        self.gray = P.gray().astype(np.float32)
        self.L = P.landmarks()
        L = self.L
        # local frame: origin between the eyes, u along the eye line, v up
        self.O = (L[133] + L[362]) / 2
        d = L[263] - L[33]
        self.roll = math.atan2(d[1], d[0])
        c, s = math.cos(self.roll), math.sin(self.roll)
        self.Rm = np.array([[c, -s], [s, c]])
        self.rolldeg = math.degrees(self.roll)

    # --- frame
    def uv(self, pts):
        return (np.asarray(pts, float) - self.O) @ self.Rm            # rotate by -roll
    def xy(self, uv):
        return np.asarray(uv, float) @ self.Rm.T + self.O
    def poly(self, idx):
        return Polygon(self.L[idx]).buffer(0)
    def lm(self, i):
        return self.uv(self.L[i])

    # --- masks -> shapely
    def mask_geom(self, m, fill=True, smooth=0.8):
        cv = self.P.cv
        m = m.astype(bool)
        if fill:
            m = ndi.binary_fill_holes(m)
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        polys = []
        for c in cs:
            if len(c) < 12:
                continue
            p = Polygon(cv.to_mm(c[:, 0, :].astype(float))).buffer(0)
            if p.area > 6:
                polys.append(p)
        g = unary_union(polys)
        sm = smooth * self.sc ** 0.5
        return g.buffer(sm, 12).buffer(-sm, 12).simplify(0.25)

    def tone(self, g):
        """mean photo grey (0..255), lightened"""
        if g.is_empty:
            return 150.0
        cv = self.P.cv
        m = np.zeros((cv.N, cv.N), np.uint8)
        for p in ([g] if g.geom_type == 'Polygon' else [q for q in g.geoms if q.geom_type == 'Polygon']):
            for ring, val in [(p.exterior, 1)] + [(h, 0) for h in p.interiors]:
                cv2.fillPoly(m, [np.round(cv.to_px(np.array(ring.coords)) * 16).astype(np.int32)], val, shift=4) if val else \
                    cv2.fillPoly(m, [np.round(cv.to_px(np.array(ring.coords)) * 16).astype(np.int32)], 0, shift=4)
        mm = m > 0
        v = float(self.gray[mm].mean()) if mm.sum() > 3 else 150.0
        return min(255.0, v + self.light)

    def spacing(self, g, dark_gain=1.0, lo=1.2, hi=3.8):
        m = self.tone(g)
        t = np.clip((178.0 - m) / 150.0, 0, 1) * dark_gain
        sp = lo + (hi - lo) * min(1.0, t)
        return round(float(sp * self.k_sp), 2)

    # --- build
    def build(self):
        P, L, sc = self.P, self.L, self.sc
        sec = []
        mk = lambda n: P.mask(n)
        hair_m, face_m, body_m = mk('hair'), mk('face'), mk('body')
        beard_m, mouthp = mk('beard'), mk('mouth patch')
        S = self.mask_geom(hair_m | face_m | body_m | beard_m | mk('earring') | mouthp)
        self.S = S
        hair = self.mask_geom(hair_m, fill=False, smooth=1.0)
        beard = self.mask_geom(beard_m, fill=False) if beard_m.any() else Polygon()
        body = self.mask_geom(body_m & ~hair_m & ~face_m, fill=False) if body_m.any() else Polygon()
        skin = self.mask_geom(face_m | mouthp).difference(hair).difference(beard)
        skin = skin.buffer(0)

        feats = []          # (name, geom, kwargs)
        def add(name, g, **kw):
            g = g.buffer(0)
            if not g.is_empty:
                feats.append((name, g, kw))

        e_sc = max(1.0, sc ** 0.5)
        # ---- eyes: opening (own section), upper/lower lid, brows, socket
        for tag, E, side in (('L', EYE_L, -1), ('R', EYE_R, 1)):
            eye = self.poly(E)
            ec = np.array(eye.centroid.coords[0])
            if self.bold:
                blob = eye.buffer(2.4 * e_sc)
                add('eye' + tag, blob, spacing=round(2.0 * self.k_sp, 2), mode='angle', angle=self.rolldeg, shrink=0.6)
                continue
            add('eye' + tag, eye, spacing=round(1.0 * max(1.0, self.k_sp * 0.9), 2), mode='angle', angle=self.rolldeg, shrink=0.35, phase=0.0)
            lid_ring = eye.buffer(3.2 * e_sc)
            add('lid' + tag, lid_ring, spacing=round(1.4 * self.k_sp, 2), mode='rings', center=list(ec), shrink=0.7)
        for tag, U, Lw in (('L', BROW_L_UP, BROW_L_LO), ('R', BROW_R_UP, BROW_R_LO)):
            br = Polygon(np.vstack([L[U], L[Lw][::-1]])).buffer((1.5 if self.bold else 0.9) * e_sc)
            a = L[U[-1]] - L[U[0]]
            add('brow' + tag, br, spacing=self.spacing(br, 1.0, 2.0 if self.bold else 1.6, 3.2), mode='angle', angle=math.degrees(math.atan2(a[1], a[0])), shrink=0.6)
        for tag, E in (('L', EYE_L), ('R', EYE_R)):
            if self.bold:
                break
            eye = self.poly(E)
            ec = np.array(eye.centroid.coords[0])
            sock = eye.buffer(9.0 * e_sc)
            add('sock' + tag, sock, spacing=self.spacing(sock, 1.0, 1.5, 3.2), mode='angle',
                angle=self.rolldeg + (35 if tag == 'L' else -35), shrink=0.9)
        # ---- nose
        if self.bold:
            nb_ = unary_union([self.poly(WING_L), self.poly(WING_R), Polygon(L[[5, 4, 1, 2, 98, 327]]).convex_hull]).convex_hull.buffer(1.2 * e_sc)
            add('nose', nb_, spacing=round(2.2 * self.k_sp, 2), mode='angle', angle=self.rolldeg, shrink=0.8)
        else:
            wl, wr = self.poly(WING_L).buffer(1.2 * e_sc), self.poly(WING_R).buffer(1.2 * e_sc)
            for tag, w in (('L', wl), ('R', wr)):
                add('wing' + tag, w, spacing=self.spacing(w, 1.0, 1.2, 3.0), mode='angle', angle=self.rolldeg + (60 if tag == 'L' else 120), shrink=0.7)
            tip = Polygon(L[[5, 4, 1, 2, 98, 327]]).convex_hull.buffer(2.0 * e_sc)
            add('noseTip', tip, spacing=round(1.2 * self.k_sp, 2), mode='rings', center=list(L[4]), shrink=0.8)
        bsp = [tuple(L[i]) for i in BRIDGE]
        bridge = Polygon(sr.band(bsp, [3.4 * e_sc] * len(bsp), flat=True))
        add('bridge', bridge, spacing=round(1.2 * self.k_sp, 2), mode='spine', spine=[list(p) for p in bsp], shrink=0.8)
        # ---- mouth: teeth / inside, upper lip, lower lip
        out_, in_ = self.poly(LIPS_OUT), self.poly(LIPS_IN)
        c1, c2 = L[61], L[291]
        mid = (c1 + c2) / 2
        up_h = affinity.translate(affinity.rotate(box(-400, 0, 400, 400), self.rolldeg, origin=(0, 0)), mid[0], mid[1])
        dn_h = affinity.translate(affinity.rotate(box(-400, -400, 400, 0), self.rolldeg, origin=(0, 0)), mid[0], mid[1])
        lips = out_.difference(in_)
        add('teeth', in_, spacing=round(self.spacing(in_, 0.6, 1.0, 2.4), 2), mode='angle', angle=self.rolldeg, shrink=0.5)
        ul, ll = lips.intersection(up_h), lips.intersection(dn_h)
        add('lipU', ul, spacing=self.spacing(ul, 1.0, 1.2, 2.6), mode='angle', angle=self.rolldeg + 90 - 10, shrink=0.55)
        add('lipL', ll, spacing=self.spacing(ll, 1.0, 1.2, 2.6), mode='angle', angle=self.rolldeg + 90 + 10, shrink=0.55)
        # ---- ears + earring first so cuts do not swallow them
        feat_union = unary_union([g for _, g, _ in feats])

        # ---- hair: fan of locks round a crown point (hair strokes run along the lock)
        hair_secs = []
        if not hair.is_empty:
            hb = hair.bounds
            cx = float(self.O[0] + 0.0)
            ytop = hb[3]
            crown = self.xy([0, self.lm(10)[1] + 60 * sc])
            hrest = hair.difference(feat_union)
            nw = 9 if self.bold else 16
            wedges = []
            ang0 = -180.0
            # wedge angles measured round the crown, full circle
            for i in range(nw):
                a0, a1 = math.radians(i * 360 / nw), math.radians((i + 1) * 360 / nw)
                pts = [crown] + [crown + 900 * np.array([math.cos(a), math.sin(a)]) for a in np.linspace(a0, a1, 6)]
                wedges.append((i, Polygon(pts), (a0 + a1) / 2))
            band_len = 70.0 * sc
            for i, w, am in wedges:
                piece = hrest.intersection(w)
                if piece.is_empty:
                    continue
                # radial bands
                rs = [Point(*crown).buffer(r, 64) for r in np.arange(0, 2000, band_len)]
                prev = None
                for bi, ring in enumerate(rs[1:], 1):
                    sub = piece.intersection(ring) if prev is None else piece.intersection(ring).difference(prev)
                    prev = ring if prev is None else prev.union(ring)
                    if sub.is_empty:
                        continue
                    ad = math.degrees(am) + (0 if bi % 2 else 6)
                    hair_secs += geom_to_secs(sub, 'hair%d_%d' % (i, bi), spacing=self.spacing(sub, 1.0, 1.5, 2.8), mode='angle',
                                              angle=ad, shrink=1.1)
            self.crown = crown
        # ---- beard
        beard_secs = []
        if not beard.is_empty:
            bg = beard.difference(feat_union)
            ch = self.lm(152)
            mid_u = self.lm(0)[0]
            ctr = self.xy([mid_u, ch[1] + 20 * sc])
            for nm, hpbox in (('L', box(-1000, -1000, 0, 1000)), ('R', box(0, -1000, 1000, 1000))):
                hp = affinity.translate(affinity.rotate(hpbox, self.rolldeg, origin=(0, 0)), self.xy([mid_u, 0])[0], self.xy([mid_u, 0])[1])
                g = bg.intersection(hp)
                beard_secs += geom_to_secs(g, 'beard' + nm, spacing=self.spacing(g, 1.0, 1.5, 2.8), mode='angle',
                                           angle=self.rolldeg + (75 if nm == 'L' else 105), shrink=1.1)

        # ---- skin zones cut by lines through the form
        skin_rest = skin.difference(feat_union)
        u = lambda i: self.lm(i)[0]; v = lambda i: self.lm(i)[1]
        vb = max(v(70), v(105), v(334), v(300), v(107), v(336)) + 3 * sc
        ve = min(v(145), v(374)) - 7 * sc
        vnb = v(2); vcor = (v(61) + v(291)) / 2; vml = v(17); vch = v(152)
        uwl, uwr = u(129), u(358); uml, umr = u(61), u(291)
        uel, uer = u(33) - 2 * sc, u(263) + 2 * sc
        ufl, ufr = u(234), u(454)
        BIGV = 2000
        cuts = [
            [(-BIGV, vb), (BIGV, vb)],
            # cheek pad: top vertical at the outer eye corner, then across to the mouth corner (L = image left)
            [(uel, BIGV), (uel, vb), (uel + 0.5, ve), (uel - 1 * sc, vnb + 4 * sc), (uml - 3 * sc, vcor + 1 * sc), (uml - 40 * sc, vcor - 14 * sc)],
            [(uer, BIGV), (uer, vb), (uer - 0.5, ve), (uer + 1 * sc, vnb + 4 * sc), (umr + 3 * sc, vcor + 1 * sc), (umr + 40 * sc, vcor - 14 * sc)],
            # nasolabial fold continued down to the jaw
            [(uwl - 2.5 * sc, ve), (uwl - 2.5 * sc, vnb + 3 * sc), (uml - 2 * sc, vcor + 3 * sc), (uml - 5 * sc, vml - 2 * sc), (uml - 9 * sc, vch + 8 * sc), (uml - 22 * sc, vch - 14 * sc)],
            [(uwr + 2.5 * sc, ve), (uwr + 2.5 * sc, vnb + 3 * sc), (umr + 2 * sc, vcor + 3 * sc), (umr + 5 * sc, vml - 2 * sc), (umr + 9 * sc, vch + 8 * sc), (umr + 22 * sc, vch - 14 * sc)],
            [(uml - 12 * sc, vml - 4 * sc), (umr + 12 * sc, vml - 4 * sc)],        # lower lip / chin groove
        ]
        # ears: skin outside the face-edge landmarks between eye and mouth level
        ears = []
        for tag, side in (('L', -1), ('R', 1)):
            ue = ufl + 3 * sc if side < 0 else ufr - 3 * sc
            far = ue + side * 60 * sc
            ring = [(ue, vnb + 10 * sc), (far, vnb + 10 * sc), (far, vcor - 14 * sc), (ue, vcor - 14 * sc)]
            eg = skin_rest.intersection(Polygon(self.xy(ring)))
            if eg.area > 20:
                ears.append((tag, eg))
        for tag, eg in ears:
            skin_rest = skin_rest.difference(eg)
        lines = [LineString(self.xy(c)) for c in cuts]
        lines = [LineString([tuple(p) for p in ln.coords]).buffer(0.0) if False else ln for ln in lines]
        bound = skin_rest.boundary
        pieces = list(polygonize(unary_union([bound] + lines)))
        zone_secs = []
        for i, pz in enumerate(pieces):
            if not skin_rest.buffer(0.01).contains(pz.representative_point()):
                continue
            g = pz.intersection(skin_rest)
            if g.is_empty or g.area < 2:
                continue
            cu, cvv = self.uv(np.array(g.representative_point().coords[0]))
            side = -1 if cu < u(2) else 1
            # classify
            if cvv > vb:
                nm, ang, rg = 'forehead', 0, 0
                if cu < uel - 6 * sc or cu > uer + 6 * sc:
                    nm, ang = 'foreheadSide', (78 if cu < 0 else 102)
            elif cu < ufl + 3 * sc or cu > ufr - 3 * sc:
                nm = 'ear'; ang = None
            elif cvv < vch + 18 * sc and cvv < vml - 4 * sc and uml < cu < umr:
                nm, ang = 'chin', 0
            elif cvv < vml - 4 * sc:
                nm, ang = 'jaw', (50 if side < 0 else 130)
            elif cu < uel or cu > uer:
                nm, ang = 'cheekOuter' if cvv < vnb + 4 * sc else 'temple', (-40 if side < 0 else 40)
                if cvv >= vnb + 4 * sc:
                    ang = 78 if side < 0 else 102
            elif uwl - 2.5 * sc < cu < uwr + 2.5 * sc:
                nm, ang = 'muzzle', 0 if cvv > vml - 4 * sc else 0
            else:
                nm, ang = 'cheek', (-30 if side < 0 else 30)
            nm = '%s%s%d' % (nm, 'L' if side < 0 else 'R', i)
            kw = dict(spacing=self.spacing(g, 1.0, 1.2, 2.4), shrink=1.3)
            if ang is None:
                cen = np.array(g.centroid.coords[0])
                kw.update(mode='rings', center=list(cen))
            else:
                kw.update(mode='angle', angle=self.rolldeg + ang)
            zone_secs += geom_to_secs(g, nm, **kw)
        for tag, eg in ears:
            zone_secs += geom_to_secs(eg, 'ear' + tag, spacing=round(1.5 * self.k_sp, 2), mode='rings',
                                      center=list(eg.centroid.coords[0]), shrink=0.9)
        # ---- body: three columns
        body_secs = []
        if not body.is_empty:
            bb = body.bounds
            xs = np.linspace(bb[0], bb[2], 4)
            for i in range(3):
                g = body.intersection(box(xs[i] - (0 if i else 5), bb[1] - 5, xs[i + 1] + (0 if i < 2 else 5), bb[3] + 5))
                body_secs += geom_to_secs(g, 'body%d' % i, spacing=self.spacing(g, 1.0, 1.5, 2.6), mode='angle', angle=(60, 90, 120)[i], shrink=1.3)
        # ---- whatever of the silhouette is still unclaimed (earring, gaps) goes into a catch-all section
        claimed = unary_union([g for _, g, _ in feats] + [Polygon(s['poly']).buffer(0) for s in hair_secs + beard_secs + zone_secs + body_secs])
        rest = S.difference(claimed.buffer(0.02))
        rest = rest.buffer(-0.3).buffer(0.3)
        rest_secs = geom_to_secs(rest, 'rest', spacing=round(2.2 * self.k_sp, 2), mode='angle', angle=45.0, shrink=1.0)
        rest_secs = [s for s in rest_secs if Polygon(s['poly']).area > 8]

        subj = []
        for n, g, kw in feats:
            subj += geom_to_secs(g, n, **kw)
        subj += hair_secs + beard_secs + zone_secs + body_secs + rest_secs
        # ---- background: five wedges about an off-centre point, directions differ
        R = self.R
        bgc = np.array([0.0, 0.0])
        bgs = []
        angs = [100, 15, 150, 55, 120]
        for i in range(5):
            a0, a1 = math.radians(18 + i * 72), math.radians(18 + (i + 1) * 72)
            pts = [bgc] + [bgc + 3 * R * np.array([math.cos(a), math.sin(a)]) for a in np.linspace(a0, a1, 8)]
            bgs.append(dict(name='bg%d' % i, kind='background', poly=[list(p) for p in pts], spacing=self.bg_sp, mode='angle',
                            angle=float(angs[i]), phase=float(i)))
        plan = dict(r_work=R, shrink=1.4, bg_gap=2.2, bg_shrink=1.0, sections=subj + bgs)
        self.plan = plan
        return plan


def face_plan(who, table='mini', **kw):
    fp = FacePlan(who, table, **kw)
    plan = fp.build()
    return plan, fp


if __name__ == '__main__':
    import json
    who, table = sys.argv[1], sys.argv[2]
    plan, fp = face_plan(who, table)
    print(len(plan['sections']), 'sections')
