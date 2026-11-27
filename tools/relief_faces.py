#!/usr/bin/env python3
"""Relief portraits (v2), SIMULATION ONLY: head, neck and shoulders left standing as a raised plateau, background
carved with arcs, hair and beard as a second tone (fine ribbing), features as thin grooves on the smooth face.

Input: the masks and feature shapes tools/photo2sand.py already makes (MediaPipe, run locally). They are captured
by a small wrapper that runs photo2sand in build/p2s-venv and pickles its intermediate regions (face, hair, body,
beard, mouth patch), the face holes (eyes, brows, nose, mouth) and the photo warped onto the 600-unit canvas:

    build/p2s-venv/bin/python <wrapper> captures/family-source/lek.jpg <dir>/lek       -> <dir>/lek.pkl
    python3 tools/relief_faces.py <dir>/lek.pkl --table mini [--hair offset|rays|strands|none] [--shade]

Photos and the pickles are private and never leave this machine.
"""
import argparse, json, math, os, pickle, sys, time
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE) + '/patterns/dog')
import sand_relief_path as rp
from relief_showcase import run_plan, TABLE, OUT


class Portrait:
    def __init__(self, pkl, table='mini', head_mm=None, zoom=0.9):
        self.c = pickle.load(open(pkl, 'rb'))
        tb = TABLE[table]
        self.cv = cv = rp.Canvas(tb['r'], res=tb['res'])
        self.table = table
        # mm per canvas radius: the Mini keeps today's framing (canvas radius = table radius); the big table gets
        # a head (top to chin = 1.6 canvas radii) of head_mm
        # big table: head + neck + shoulders fill ~75% of the tray height (head top at y = +0.5 R)
        self.s = cv.R * zoom if table == 'mini' else 300.0 * cv.R / 420.0
        self.F, self.S = self.c['F'], self.c['S']
        # grid -> canvas px maps for remap
        self.dy = 0.0 if table == 'mini' else 0.5 * cv.R - 0.88 * self.s
        u = 300 + cv.X / self.s * self.S
        v = 300 - (cv.Y - self.dy) / self.s * self.S
        self.mx, self.my = (u * self.F).astype(np.float32), (v * self.F).astype(np.float32)
        self.reg = {r['name']: r for r in self.c['regions']}

    def mask(self, name):
        if name not in self.reg:
            return np.zeros((self.cv.N, self.cv.N), bool)
        m = cv2.remap(self.reg[name]['mask'], self.mx, self.my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return m > 0

    def gray(self):
        return cv2.remap(self.c['gray'], self.mx, self.my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def mm(self, pts):
        pts = np.asarray(pts, float)
        return np.c_[(pts[:, 0] - 300) / self.S * self.s, -(pts[:, 1] - 300) / self.S * self.s + self.dy]

    def landmarks(self):
        L, A = self.c['L'], self.c['A']
        return self.mm(L @ A[:, :2].T + A[:, 2])

    def features(self):
        f = self.c['meas']['features']
        holes = self.reg['face'].get('holes', [])
        nb = f['brows_drawn']
        out = dict(eyes=[self.mm(h) for h in holes[:2]], brows=[self.mm(h) for h in holes[2:2 + nb]],
                   nose=self.mm(holes[2 + nb]) if len(holes) > 2 + nb else None)
        if 'mouth patch' in self.reg:
            out['mouth'] = self.mm(self.reg['mouth patch']['holes'][0])
        else:
            out['mouth'] = self.mm(holes[3 + nb]) if len(holes) > 3 + nb else None
        out['glasses'] = bool(f['glasses']['used'])
        return out


def upper_lid(eye, g, lift=0.35):
    """Top half of an eye outline (between its two horizontal extremes), lifted by lift*g: a second, adjacent pass
    that makes the upper lash line twice as heavy."""
    e = rp.resample(eye, 0.5, True)
    i0, i1 = int(np.argmin(e[:, 0])), int(np.argmax(e[:, 0]))
    a, b = sorted((i0, i1))
    seg1, seg2 = e[a:b + 1], np.vstack([e[b:], e[:a + 1]])
    top = seg1 if seg1[:, 1].mean() > seg2[:, 1].mean() else seg2
    return top + [0, lift * g]


def ring_offset(loop, d):
    """Offset a closed loop outward (d > 0) or inward by d mm (via its normals; fine for smooth convex-ish loops)."""
    p = rp.resample(loop, 0.5, True)
    t = np.roll(p, -1, 0) - np.roll(p, 1, 0)
    t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
    n = np.c_[t[:, 1], -t[:, 0]]
    area = np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
    if area < 0:
        n = -n
    return p + d * n


def mouth_mid(m):
    """The line where the lips meet: midway between the upper and lower halves of the outer lip loop, a little
    above the middle, from corner to corner (the corners themselves are on the loop already)."""
    m = rp.resample(m, 0.5, True)
    i0, i1 = int(np.argmin(m[:, 0])), int(np.argmax(m[:, 0]))
    a, b = sorted((i0, i1))
    s1, s2 = m[a:b + 1], np.vstack([m[b:], m[:a + 1]])
    if s1[0, 0] > s1[-1, 0]: s1 = s1[::-1]
    if s2[0, 0] > s2[-1, 0]: s2 = s2[::-1]
    top, bot = (s1, s2) if s1[:, 1].mean() > s2[:, 1].mean() else (s2, s1)
    xs = np.linspace(m[i0, 0], m[i1, 0], 60)
    yt, yb = np.interp(xs, top[:, 0], top[:, 1]), np.interp(xs, bot[:, 0], bot[:, 1])
    return np.c_[xs, 0.72 * yt + 0.28 * yb]


def connectors(F, g, shadow_side=0):
    """Sketch lines that join the features into one reachable network, so the ball reaches them along lines a
    portrait artist would draw anyway: eye to brow (a short crease), brow to nose wing (the side of the nose
    bridge), nose wing to mouth corner (the smile fold)."""
    out = []
    eyes = sorted(F['eyes'], key=lambda e: e[:, 0].mean())
    brows = sorted(F['brows'], key=lambda b: b[:, 0].mean())
    nose, mouth = F['nose'], F['mouth']
    cx = np.mean([e[:, 0].mean() for e in eyes]) if eyes else 0.0

    def near(a, b):
        from scipy.spatial import cKDTree
        d, k = cKDTree(b).query(a)
        i = int(np.argmin(d))
        return a[i], b[int(k[i])]

    def curve(a, b, bulge):
        a, b = np.asarray(a, float), np.asarray(b, float)
        m = (a + b) / 2
        n = np.array([-(b - a)[1], (b - a)[0]]) / max(np.hypot(*(b - a)), 1e-9)
        if np.dot(n, m - [cx, m[1]]) < 0:
            n = -n
        c = m + bulge * np.hypot(*(b - a)) * n
        t = np.linspace(0, 1, 30)[:, None]
        return (1 - t) ** 2 * a + 2 * (1 - t) * t * c + t ** 2 * b
    for side in (0, 1):
        e = eyes[side] if side < len(eyes) else None
        b = brows[side] if len(brows) == 2 else None
        if e is not None and b is not None:
            a, q = near(e, b)
            out.append(np.vstack([a, q]))
        if nose is not None:
            wing = nose[np.argmin(nose[:, 0])] if side == 0 else nose[np.argmax(nose[:, 0])]
            if side != shadow_side:
                pass
            elif b is not None:
                inner = b[np.argmax(b[:, 0])] if side == 0 else b[np.argmin(b[:, 0])]
                out.append(curve(inner, wing, 0.08))
            elif e is not None:
                inner = e[np.argmax(e[:, 0])] if side == 0 else e[np.argmin(e[:, 0])]
                out.append(curve(inner, wing, 0.08))
            if mouth is not None:
                corner = mouth[np.argmin(mouth[:, 0])] if side == 0 else mouth[np.argmax(mouth[:, 0])]
                out.append(curve(wing, corner, 0.15))
    return out


def mid_line(loop, w_top=0.5):
    """Line between the upper and lower halves of a closed outline, from its left to its right extreme."""
    m = rp.resample(loop, 0.5, True)
    i0, i1 = int(np.argmin(m[:, 0])), int(np.argmax(m[:, 0]))
    a, b = sorted((i0, i1))
    s1, s2 = m[a:b + 1], np.vstack([m[b:], m[:a + 1]])
    if s1[0, 0] > s1[-1, 0]: s1 = s1[::-1]
    if s2[0, 0] > s2[-1, 0]: s2 = s2[::-1]
    top, bot = (s1, s2) if s1[:, 1].mean() > s2[:, 1].mean() else (s2, s1)
    xs = np.linspace(m[i0, 0], m[i1, 0], 60)
    yt, yb = np.interp(xs, top[:, 0], top[:, 1]), np.interp(xs, bot[:, 0], bot[:, 1])
    return np.c_[xs, w_top * yt + (1 - w_top) * yb], top, bot


def shoulders(cv, body, face, g):
    """A simple bust: below the chin the neck widens into shoulders that slope out and run down to the rim."""
    if not face.any():
        return np.zeros_like(face)
    fx, fy = cv.X[face], cv.Y[face]
    fw = fx.max() - fx.min()
    chin = fy.min()
    cx = float(np.median(fx))
    nw = 0.36 * fw
    y0 = chin - 0.22 * fw
    from make_dog import spline
    half = [(cx - nw, chin + 0.3 * fw), (cx - nw, y0), (cx - 0.75 * fw, y0 - 0.16 * fw), (cx - 1.15 * fw, y0 - 0.35 * fw),
            (cx - 1.35 * fw, y0 - 0.8 * fw), (cx - 1.4 * fw, -cv.R - 30)]
    pts = half + [(2 * cx - x, y) for x, y in half[::-1]]
    return cv.fill_polys([np.asarray(spline(pts, 1.0, closed=True))])


def hair_strands(cv, P, hm, pitch, g, min_len=None):
    """Evenly spaced streamlines along the hair direction measured in the photo (structure tensor of the
    grey image: strands run along the edges, across the brightness gradient)."""
    gr = P.gray().astype(np.float32)
    sig = 0.6 * g / cv.res
    gx = cv2.Sobel(gr, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(gr, cv2.CV_32F, 0, 1, ksize=3)
    big = 2.5 * g / cv.res
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), big); jyy = cv2.GaussianBlur(gy * gy, (0, 0), big); jxy = cv2.GaussianBlur(gx * gy, (0, 0), big)
    ang = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2           # along the strands (image axes, rows down)
    vx, vy = np.cos(ang), -np.sin(ang)                                # to mm axes (y up)
    taken = np.zeros_like(hm)
    step = 0.5
    min_len = min_len or 2.5 * g
    lines = []
    ys, xs = np.nonzero(hm)
    order = np.random.default_rng(0).permutation(len(xs))[: max(1, len(xs) // 40)]
    seeds = cv.to_mm(np.c_[xs[order], ys[order]])

    def ok(p):
        q = cv.to_px(p[None])[0].astype(int)
        if not (0 <= q[0] < cv.N and 0 <= q[1] < cv.N):
            return False
        return hm[q[1], q[0]] and not taken[q[1], q[0]]

    def trace(p0, sgn):
        pts = [p0]; d = None
        for _ in range(4000):
            q = cv.to_px(pts[-1][None])[0].astype(int)
            v = np.array([vx[q[1], q[0]], vy[q[1], q[0]]])
            if d is None:
                v = v * sgn
            elif np.dot(v, d) < 0:
                v = -v
            nxt = pts[-1] + step * v
            if not ok(nxt):
                break
            pts.append(nxt); d = v
        return pts
    for s0 in seeds:
        if not ok(s0):
            continue
        a = trace(s0, 1); b = trace(s0, -1)
        line = np.array(b[::-1] + a[1:])
        if rp.poly_len(line) < min_len:
            continue
        line = rp.smooth_poly(rp.resample(line, 0.5), 2.0, False)
        lines.append(line)
        taken |= cv.stroke(line, 2 * 0.85 * pitch)
    return lines


def relief_portrait(P, hair='strands', shade=False, bg_pitch=1.3, beard_pitch=1.0, hair_pitch=None, rich=None):
    """rich (default: the big table): separate upper and lower lids, iris, full brow shapes, lips outline plus the
    line between the lips. Otherwise (the Mini): one upper-lid arc and one brow arc per eye, a short curve at the nose
    tip, an upper-lip line and a lower-lip arc."""
    cv, g = P.cv, P.cv.g
    rich = (P.table == 'big') if rich is None else rich
    hair_pitch = hair_pitch or (1.25 if rich else 1.5)
    face, hairm, body, beard = P.mask('face'), P.mask('hair'), P.mask('body'), P.mask('beard')
    patch, ear = P.mask('mouth patch'), P.mask('earring')
    if beard.any() and P.c['meas']['beard']['used'] == 'full':
        # the measured full-beard mask is lopsided (one cheek starts lower): mirror it about the face's centre line
        cols = np.nonzero(face.any(0))[0]
        cxp = 0.5 * (cols.min() + cols.max())
        j = np.clip(np.round(2 * cxp - np.arange(cv.N)).astype(int), 0, cv.N - 1)
        both = beard | beard[:, j]
        beard = both & (face | beard | hairm | patch | (cv2.dilate(both.astype(np.uint8), cv.disk_k(1.0 * g)) > 0))
        face &= ~beard
    subj = face | hairm | body | beard | patch | ear
    subj |= shoulders(cv, body, face | beard, g) & cv.disc()
    subj = cv2.morphologyEx(subj.astype(np.uint8), cv2.MORPH_CLOSE, cv.disk_k(3.0 * g)).astype(bool)
    subj = cv.simplify(subj & cv.disc())
    din = cv.dist_in(subj)
    F = P.features()
    Lm = P.landmarks()
    gr = P.gray()
    fx = cv.X[face].mean()
    shadow = 0 if gr[face & (cv.X < fx)].mean() < gr[face & (cv.X >= fx)].mean() else 1
    eyes = sorted(F['eyes'], key=lambda e: e[:, 0].mean())
    brows = sorted(F['brows'], key=lambda b: b[:, 0].mean())
    details = []
    lids = []
    for e in eyes:
        _, top, bot = mid_line(e)
        lids.append(top)
        details.append(top)
        if rich:
            details.append(bot)
    if rich:                                                  # iris edges
        for c_i, ring in ((468, (469, 470, 471, 472)), (473, (474, 475, 476, 477))):
            c = Lm[c_i]; r = float(np.mean([np.hypot(*(Lm[k] - c)) for k in ring]))
            r = max(r, 0.6 * g)
            t = np.linspace(0, 2 * math.pi, 48, endpoint=False)
            details.append(('closed', np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t)]))
    brow_lines = []
    for k, b in enumerate(brows):
        if rich:
            details.append(('closed', b)); brow_lines.append(b)
            continue
        ml, _, _ = mid_line(b)
        lid = lids[k] if k < len(lids) else None
        if lid is not None:                                   # keep 1.5 grooves above the lid
            from scipy.spatial import cKDTree
            d = cKDTree(lid).query(ml)[0].min()
            if d < 1.5 * g:
                ml = ml + [0, 1.5 * g - d]
        details.append(ml); brow_lines.append(ml)
    nose = F['nose']
    if nose is not None:
        nl, ntop, _ = mid_line(nose, 1.0)
        details.append(nl)
    mouth = F['mouth']
    if mouth is not None:
        ml, top, bot = mid_line(mouth, 0.72)
        details.append(ml)
        details.append(bot)
        if rich:
            details.append(top)
    # connectors: eye to brow at the outer corner (a short crease), one nose side on the shadow side (eye inner
    # corner to the nose wing), and the smile fold from that nose wing to the mouth corner
    for k, lid in enumerate(lids):
        outer = lid[0] if k == 0 else lid[-1]
        if k < len(brow_lines):
            bl = brow_lines[k]
            q = bl[np.argmin(np.hypot(*(bl - outer).T))]
            details.append(np.vstack([outer, q]))
    if nose is not None and len(lids) == 2:
        lid = lids[shadow]
        inner = lid[-1] if shadow == 0 else lid[0]
        wing = nl[0] if shadow == 0 else nl[-1]
        t = np.linspace(0, 1, 30)[:, None]
        mid = (inner + wing) / 2 + [(-1 if shadow == 0 else 1) * 0.15 * g, 0]
        details.append((1 - t) ** 2 * inner + 2 * (1 - t) * t * mid + t ** 2 * wing)
        if mouth is not None:
            corner = ml[0] if shadow == 0 else ml[-1]
            mid = (wing + corner) / 2 + [(-1 if shadow == 0 else 1) * 0.35 * g, 0]
            details.append((1 - t) ** 2 * wing + 2 * (1 - t) * t * mid + t ** 2 * corner)
    if len(brow_lines) == 2:
        k = 1 - shadow
        bl = brow_lines[k]
        outer = bl[0] if k == 0 else bl[-1]
        edge = ~face | hairm
        q = cv.to_px(outer[None])[0].astype(int)
        dist, lab = cv2.distanceTransformWithLabels((~edge).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ys_, xs_ = np.nonzero(edge)
        idx = np.zeros(lab.max() + 1, int); idx[lab[ys_, xs_]] = np.arange(len(ys_))
        j = idx[lab[q[1], q[0]]]
        tgt = cv.to_mm(np.c_[[xs_[j]], [ys_[j]]])[0]
        details.append(np.vstack([outer, tgt]))
    ribs, frames = [], []
    if hairm.any() and hair != 'none':
        hm = hairm & (din >= 0.6 * g)
        hm = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, cv.disk_k(1.0 * g)).astype(bool)
        if hair == 'strands':
            frames += cv.loops(cv.dist_in(hm) >= 0.5 * g)
            inner = cv.dist_in(hm) >= 1.2 * g
            details += hair_strands(cv, P, inner, hair_pitch * g, g)
        else:
            ribs.append(rp.Fill('rays', 1.1 * g, mask=hm, focus=(fx, cv.Y[hairm].max() + 2 * g), r_ref=0.45 * P.s, name='hair'))
    if beard.any():
        bm = (beard | patch) & (din >= 0.6 * g)
        if mouth is not None:
            mmask = cv.fill_polys([mouth])
            bm &= ~(cv2.dilate(mmask.astype(np.uint8), cv.disk_k(1.4 * g)) > 0)
        ribs.append(rp.Fill('lines', beard_pitch * g, mask=bm, angle=90.0, name='beard', wave=(0.2 * g, 4 * g)))
    if shade:
        grs = cv2.GaussianBlur(gr, (0, 0), 1.5 * g / cv.res)
        fm = face & (din >= 0.8 * g)
        thr = np.percentile(grs[fm], 30)
        dark = fm & (grs < thr)
        feat = np.zeros_like(fm)
        for d in details:
            feat |= cv.stroke(d[1] if isinstance(d, tuple) else d, 3.5 * g)
        dark &= ~feat
        dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, cv.disk_k(2.5 * g)).astype(bool)
        if dark.any():
            ribs.append(rp.Fill('lines', 1.05 * g, mask=dark, angle=70.0, name='shadow'))
    ys, xs = np.nonzero(face)
    fc = cv.to_mm(np.c_[[xs.mean()], [ys.mean()]])[0]
    fills = [rp.Fill('arcs', bg_pitch * g, focus=(float(fc[0]), float(fc[1])), name='background')]
    # hair frames are drawn as 'frame' grooves (via extra_frames)
    return cv.plan(subj, fills, details=details, ribs=ribs, simplify=False, extra_frames=frames)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pkl')
    ap.add_argument('--table', default='mini', choices=['mini', 'big'])
    ap.add_argument('--hair', default='strands', choices=['rays', 'strands', 'none'])
    ap.add_argument('--shade', action='store_true')
    ap.add_argument('--no-lash', action='store_true')
    ap.add_argument('--no-connect', action='store_true')
    ap.add_argument('--pitch', type=float, default=1.3)
    ap.add_argument('--head-mm', type=float, default=250.0)
    ap.add_argument('--name', required=True)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    t0 = time.time()
    P = Portrait(a.pkl, a.table, a.head_mm)
    plan = relief_portrait(P, hair=a.hair, shade=a.shade, bg_pitch=a.pitch)
    rep, _ = run_plan(P.cv, plan, a.name, a.table, out=a.out, title='relief portrait')
    print(a.name, json.dumps({k: rep[k] for k in ('path_m', 'points', 'links', 'retrace_m') if k in rep}),
          'min', rep.get('mini_minutes'), 'links over raised:', [(l['mm'], l['between']) for l in rep['links_over_subject']],
          '%.0fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
