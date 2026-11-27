#!/usr/bin/env python3
"""General photo -> sand drawing for the Oasis Mini (SIMULATION ONLY; never contacts a table).

    python3 tools/auto_picture.py cat --rect 0.05,0.0,0.95,0.8 [--v NAME] [--sim]
        reads captures/auto-picture/src/<name>.jpg, writes captures/auto-picture/<name>_<v>_p1.thr .., _plan.png

Rules from DRAWING-LESSONS.md: likeness = clean smooth contour lines (outline + strongest interior edges, >= 15 mm, no
clutter, lines >= ~5 mm apart); big dark masses (>= ~30 mm) as ONE combed mass whose strokes follow the photo's structure
direction, 2.4-3.6 mm, drawn BEFORE the lines and never outlined; nothing finer than ~10 mm; travel only along drawn lines;
enter and leave at the rim (after an outward erase) at the outline point nearest the rim.

Pipeline: subject mask (GrabCut in a rectangle) -> fit the subject's enclosing circle to the tray -> outline + Canny edges
(skeleton -> segments -> smooth -> rank by strength -> prune by spacing) -> dark masses (dark & large, opened) combed with
auto_portrait.comb_flow -> route (auto_portrait.route) -> .thr (<= 11,000 points each) with Mini minutes.
"""
import argparse, math, os, sys
import numpy as np, cv2
from scipy import ndimage as ndi
from skimage import measure, morphology

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import auto_portrait as ap
import animal_face
import sand_relief_path as rp

OUT = ROOT + '/captures/auto-picture'; SRC = OUT + '/src'
ap.OUT = OUT
RES = ap.RES; N = 912; H = (N - 1) * RES / 2.0
resample, smooth, length = ap.resample, ap.smooth, ap.length


class Field:
    """Duck-typed stand-in for auto_portrait.Face (what comb_flow needs)."""
    to_px = ap.Face.to_px; to_mm = ap.Face.to_mm; blur_mask = ap.Face.blur_mask; poly_mask = ap.Face.poly_mask
    def __init__(self, gray, mask):
        self.N = N; self.gray = gray; self.mask = mask


def edt(m): return ndi.distance_transform_edt(m) * RES


def subject_mask(img, rect, mode, core=0.2):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    r = (int(x0 * w), int(y0 * h), int((x1 - x0) * w), int((y1 - y0) * h))
    if mode.startswith('poly:'):                      # rough hand polygon (fractions of the photo), refined by GrabCut
        pts = np.array([[float(v) for v in q.split(',')] for q in mode[5:].split()]) * [w, h]
        pm = np.zeros((h, w), np.uint8); cv2.fillPoly(pm, [np.round(pts).astype(np.int32)], 1)
        sc = 640.0 / max(h, w); sm = cv2.resize(img, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
        pm = cv2.resize(pm, (sm.shape[1], sm.shape[0]), interpolation=cv2.INTER_NEAREST)
        rr = max(3, int(0.025 * max(sm.shape[:2])))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rr + 1,) * 2)
        fg = cv2.erode(pm, k) > 0; pb = cv2.dilate(pm, k) > 0
        gm = np.full(pm.shape, cv2.GC_BGD, np.uint8); gm[pb] = cv2.GC_PR_BGD; gm[pm > 0] = cv2.GC_PR_FGD; gm[fg] = cv2.GC_FGD
        bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
        cv2.grabCut(sm, gm, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
        m = ((gm == 1) | (gm == 3)).astype(np.uint8)
        lab, n = ndi.label(m)
        if n > 1: m = (lab == 1 + int(np.argmax(ndi.sum(m, lab, range(1, n + 1))))).astype(np.uint8)
        m = ndi.binary_fill_holes(m).astype(np.uint8)
        k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)); m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, k2), cv2.MORPH_CLOSE, k2)
        return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR) > 0
    if mode == 'rect':
        m = np.zeros((h, w), np.uint8); m[r[1]:r[1] + r[3], r[0]:r[0] + r[2]] = 1; return m > 0
    s = 640.0 / max(h, w); sm = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    rs = tuple(int(v * s) for v in r)
    gm = np.full(sm.shape[:2], cv2.GC_BGD, np.uint8); bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
    gm[rs[1]:rs[1] + rs[3], rs[0]:rs[0] + rs[2]] = cv2.GC_PR_FGD
    cx_, cy_ = rs[0] + rs[2] // 2, rs[1] + rs[3] // 2; hw, hh = int(rs[2] * core / 2), int(rs[3] * core / 2)
    gm[cy_ - hh:cy_ + hh, cx_ - hw:cx_ + hw] = cv2.GC_FGD
    cv2.grabCut(sm, gm, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    m = ((gm == 1) | (gm == 3)).astype(np.uint8)
    lab, n = ndi.label(m)
    if n > 1:
        sz = ndi.sum(m, lab, range(1, n + 1)); m = (lab == 1 + int(np.argmax(sz))).astype(np.uint8)
    m = ndi.binary_fill_holes(m).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k); m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR) > 0


def load(name, a):
    img = cv2.imread('%s/%s.jpg' % (SRC, name))
    s = 1200.0 / max(img.shape[:2])
    if s < 1: img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    rect = [float(v) for v in a.rect.split(',')]
    m = subject_mask(img, rect, a.mask, a.core)
    crop = np.zeros(m.shape, bool); c0 = [float(v) for v in a.crop.split(',')]
    crop[int(c0[1] * m.shape[0]):int(c0[3] * m.shape[0]), int(c0[0] * m.shape[1]):int(c0[2] * m.shape[1])] = True
    m &= crop
    g8 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if a.clahe: g8 = cv2.createCLAHE(clipLimit=a.clahe, tileGridSize=(6, 6)).apply(g8)
    ys, xs = np.nonzero(m)
    (cx, cy), rad = cv2.minEnclosingCircle(np.c_[xs[::7], ys[::7]].astype(np.float32))
    sc = a.fit / rad                                         # mm per source pixel
    Mx = np.array([[sc / RES, 0, (H - cx * sc) / RES], [0, sc / RES, (H + cy * sc) / RES - 2 * cy * sc / RES + 0]], np.float64)
    # col = ((x-cx)*sc + H)/RES ; row = (H + (y-cy)*sc)/RES
    Mx = np.array([[sc / RES, 0, (H - cx * sc) / RES], [0, sc / RES, (H - cy * sc) / RES]], np.float64)
    gray = cv2.warpAffine(g8.astype(np.float32), Mx, (N, N), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
    mk = cv2.warpAffine(m.astype(np.float32), Mx, (N, N), flags=cv2.INTER_LINEAR) > 0.5
    F_valid = cv2.warpAffine(crop.astype(np.float32), Mx, (N, N), flags=cv2.INTER_LINEAR) > 0.99
    bgr = cv2.warpAffine(img, Mx, (N, N), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
    Fd = Field(gray, mk); Fd.valid = F_valid; Fd.det = None
    if a.animal:                                             # eyes + nose of a front-facing animal, in tray millimetres
        d = animal_face.detect(img)
        if d:
            mm_ = lambda x, y: np.array([(x - cx) * sc, -(y - cy) * sc])
            Fd.det = dict(eyes=[mm_(x, y) for x, y, r in d['eyes']], nose=mm_(*d['nose'][:2]), box=d['box'], sc=sc, px0=(cx, cy), face_w=d['box'][2] * sc)
    return Fd, bgr


def outline_of(F, sig):
    m = cv2.GaussianBlur(F.mask.astype(np.float32), (0, 0), sig / RES)
    cs = measure.find_contours(m, 0.5); c = max(cs, key=len)
    P = smooth(F.to_mm(c), sig, 0.5, closed=True)
    ve = cv2.erode(F.valid.astype(np.uint8), np.ones((int(3 / RES) | 1,) * 2, np.uint8)) > 0
    q = np.clip(np.round(F.to_px(P)).astype(int), 0, N - 1); ok = ve[q[:, 1], q[:, 0]]
    if ok.all(): return [np.vstack([P, P[:1]])], True
    k0 = int(np.argmin(ok)); P = np.roll(P, -k0, 0); ok = np.roll(ok, -k0)       # start in a dropped stretch
    out = []; i = 0
    while i < len(P):
        if ok[i]:
            j = i
            while j + 1 < len(P) and ok[j + 1]: j += 1
            if length(P[i:j + 1]) >= 15: out.append(P[i:j + 1])
            i = j + 1
        else: i += 1
    return out, False


def edge_lines(F, a, outl):
    g = cv2.GaussianBlur(F.gray, (0, 0), a.edge_sigma / RES)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    inner = cv2.erode(F.mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * a.edge_in / RES) | 1,) * 2)) > 0
    ref = np.percentile(mag[inner], 97) if inner.any() else 1.0
    lv = np.percentile(g[inner], np.arange(a.lev_lo, a.lev_hi + 1, a.lev_step))
    cands = []
    for L_ in lv:
        for c in measure.find_contours(g, L_, mask=inner):
            if len(c) < 20: continue
            rr = np.clip(np.round(c[:, 0]).astype(int), 0, N - 1); cc = np.clip(np.round(c[:, 1]).astype(int), 0, N - 1)
            st = mag[rr, cc] / ref
            ok = ndi.uniform_filter1d(st, 9) >= a.min_strength
            i = 0
            while i < len(c):
                if ok[i]:
                    j = i
                    while j + 1 < len(c) and ok[j + 1]: j += 1
                    P = F.to_mm(c[i:j + 1])
                    if len(P) > 8 and length(P) >= a.min_len:
                        Ps = smooth(P, a.line_smooth, 0.5)
                        cands.append((float(st[i:j + 1].mean()) * length(Ps) ** a.len_pow, float(st[i:j + 1].mean()), Ps))
                    i = j + 1
                else: i += 1
    cands.sort(key=lambda t: -t[0])
    taken = np.zeros((N, N), np.uint8)
    for o_ in outl: cv2.polylines(taken, [np.round(F.to_px(o_)).astype(np.int32).reshape(-1, 1, 2)], False, 1, 1)
    dist_t = edt(taken == 0)
    out = []
    for sc, st, P in cands:
        if len(out) >= a.max_lines: break
        pp = np.round(F.to_px(P)).astype(int); pp = np.clip(pp, 0, N - 1)
        ok = dist_t[pp[:, 1], pp[:, 0]] >= a.sep
        # keep longest run
        best = None; i = 0
        while i < len(ok):
            if ok[i]:
                j = i
                while j + 1 < len(ok) and ok[j + 1]: j += 1
                if best is None or j - i > best[1] - best[0]: best = (i, j)
                i = j + 1
            else: i += 1
        if best is None: continue
        Q = P[best[0]:best[1] + 1]
        if length(Q) < a.min_len: continue
        out.append((Q, st))
        cv2.polylines(taken, [np.round(F.to_px(Q)).astype(np.int32).reshape(-1, 1, 2)], False, 1, 1)
        dist_t = edt(taken == 0)
    return out


def dark_mass(F, a):
    D = cv2.GaussianBlur(F.gray, (0, 0), a.dark_sigma / RES)
    inner = cv2.erode(F.mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * a.mass_in / RES) | 1,) * 2)) > 0
    thr = np.percentile(D[F.mask], 100 * a.dark)
    M = (D < thr) & inner
    r = int(a.mass_open / RES) | 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))
    M = cv2.morphologyEx(M.astype(np.uint8), cv2.MORPH_OPEN, k); M = cv2.morphologyEx(M, cv2.MORPH_CLOSE, k) > 0
    M = cv2.GaussianBlur(M.astype(np.float32), (0, 0), 2.0 / RES) > 0.5
    lab, n = ndi.label(M); masses = []
    e = edt(M)
    for i in range(1, n + 1):
        c = lab == i
        if e[c].max() * 2 >= a.mass_min and c.sum() * RES * RES >= a.mass_area: masses.append(c)
    return masses


def dark_dots(F, a, masses):
    """very dark compact blobs 7-22 mm (pupils, nostrils, windows): drawn as a tight spiral, which reads as a dark dot."""
    D = cv2.GaussianBlur(F.gray, (0, 0), 1.2 / RES)
    inner = cv2.erode(F.mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * a.dot_in / RES) | 1,) * 2)) > 0
    thr = np.percentile(D[F.mask], 100 * a.dot_pct)
    B = (D < thr) & inner
    for M in masses: B &= ~(cv2.dilate(M.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)
    k = int(2.0 / RES) | 1; B = cv2.morphologyEx(B.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    k2 = int(3.0 / RES) | 1; B = ndi.binary_fill_holes(cv2.morphologyEx(B.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k2, k2))) > 0)
    lab, n = ndi.label(B); dots = []
    for i in range(1, n + 1):
        c = lab == i
        ring = (cv2.dilate(c.astype(np.uint8), np.ones((int(14 / RES) | 1,) * 2, np.uint8)) > 0) & ~(cv2.dilate(c.astype(np.uint8), np.ones((int(4 / RES) | 1,) * 2, np.uint8)) > 0) & F.mask
        if ring.sum() < 50: continue
        contrast = float(np.median(F.gray[ring]) - np.median(F.gray[c]))
        if contrast < a.dot_contrast: continue
        area = c.sum() * RES * RES; d = 2 * math.sqrt(area / math.pi)
        if not (a.dot_min <= d <= a.dot_max): continue
        cnts, _ = cv2.findContours(c.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE); per = cv2.arcLength(cnts[0], True) * RES
        if 4 * math.pi * area / max(per * per, 1e-6) < a.dot_round: continue           # not round enough
        ys, xs = np.nonzero(c); ctr = F.to_mm(np.array([[ys.mean(), xs.mean()]]))[0]
        dots.append((ctr, min(d / 2, a.dot_rmax), d, contrast))
    dots.sort(key=lambda t: -t[3] * t[2]); return [t[:3] for t in dots[:a.dot_n]]


def rot(P, ang):
    c, s_ = math.cos(ang), math.sin(ang); return np.asarray(P, float) @ np.array([[c, s_], [-s_, c]])

def eye_shapes(det, a):
    """Per eye: an almond outline (>= 16 mm) + a dark dot, or an upper-lid arc with the dot hanging under it (one stroke)."""
    e0, e1 = det['eyes']; tilt = math.atan2(e1[1] - e0[1], e1[0] - e0[0]); out = []
    for k, c in enumerate((e0, e1)):
        W, Hh = a.eye_w, a.eye_h; u = np.linspace(-1, 1, 41)
        up = np.c_[u * W / 2, (Hh / 2) * (1 - u ** 2)]; lo = np.c_[u * W / 2, -(Hh / 2) * 0.8 * (1 - u ** 2)]
        if a.eye_style == 'almond':
            ring = smooth(rot(np.vstack([up, lo[::-1][1:-1]]), -tilt) + c, 0.9, 0.5, closed=True)
            out.append(('eye%d' % k, ring, True))
            out.append(('eyedot%d' % k, ap.iris_spiral(c + [0, -0.0], a.eye_dot, a.dot_pitch, 1.0), False))
        else:
            lid = smooth(rot(up + [0, Hh * 0.1], -tilt) + c, 0.9, 0.5)
            out.append(('eye%d' % k, ap.eye_lid_dot(None, lid, c, a.eye_dot, a.dot_pitch, 1, 2.4), False))
    return out

def nose_shape(det, a):
    """Small inverted triangle (apex down) with a short stem: the cat nose / philtrum Y."""
    e0, e1 = det['eyes']; tilt = math.atan2(e1[1] - e0[1], e1[0] - e0[0]); c = det['nose']; W = a.nose_w
    tri = np.array([[0, -0.45 * W], [-W / 2, 0.25 * W], [W / 2, 0.25 * W], [0, -0.45 * W], [0, -0.45 * W - a.nose_stem]])
    pts = np.vstack([resample(np.array([tri[i], tri[i + 1]]), 0.5) for i in range(len(tri) - 1)])
    return smooth(rot(pts, -tilt) + c, 0.6, 0.5)

def radial_mass(F, M, centre, exclude, sp=3.2, r0=9.0, tilt=0.0, step=0.6):
    """The face mass combed in rays from the nose outward (the way fur grows on a face). Every second ray starts further out
    so the comb density stays about even; rays are cut by the mass edge and by the exclusion discs (eyes, nose)."""
    M = F.blur_mask(M, 1.2)
    er = cv2.erode(M.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * 1.5 / RES) | 1,) * 2)) > 0
    ys, xs = np.nonzero(er); P = F.to_mm(np.c_[ys, xs]); rmax = float(np.hypot(*(P - centre).T).max())
    rmid = 0.5 * rmax; dth = sp / max(rmid, 1.0); n = int(round(2 * math.pi / dth)); pieces = []
    for i in range(n):
        th = 2 * math.pi * i / n; r_start = r0 if i % 2 == 0 else r0 + 0.35 * (rmax - r0)
        rs = np.arange(r_start, rmax, step); q = centre + np.c_[rs * math.cos(th), rs * math.sin(th)]
        rc = np.clip(np.round(F.to_px(q)).astype(int), 0, N - 1); ok = er[rc[:, 1], rc[:, 0]]
        for ec, er_ in exclude: ok &= np.hypot(*(q - ec).T) > er_
        j = 0
        while j < len(q):
            if ok[j]:
                k = j
                while k + 1 < len(q) and ok[k + 1]: k += 1
                if length(q[j:k + 1]) > 5: pieces.append((i, q[j:k + 1]))
                j = k + 1
            else: j += 1
    chains = [[]]; cur = None; flip = False; left = list(pieces)
    left.sort(key=lambda t: t[0])
    while left:
        if cur is None: k = 0; rev = False
        else:
            best = None
            for ii, (i, q) in enumerate(left[:12]):
                for rv in (False, True):
                    d = np.hypot(*((q[-1] if rv else q[0]) - cur))
                    if best is None or d < best[0]: best = (d, ii, rv)
            d, k, rev = best
            if d > 7.0: chains.append([])
        i, q = left.pop(k); q = q[::-1] if rev else q
        chains[-1].extend(map(tuple, q)); cur = q[-1]
    return [c for c in chains if len(c) > 2], [np.array(q) for _, q in pieces]

def build(name, a):
    F, bgr = load(name, a)
    outl, closed = outline_of(F, a.out_smooth)
    outline = outl[0] if closed else np.vstack(outl)
    lines = edge_lines(F, a, outl)
    masses = dark_mass(F, a) if a.dark > 0 else []
    items = {}; strokes = []
    dummy = np.zeros((N, N), bool); dummy[0, 0] = True
    det = F.det; fexcl = []; aextra = []
    if det:
        fexcl = [(c, a.eye_w * 0.5 + a.eye_gap) for c in det['eyes']] + [(det['nose'], a.nose_w * 0.5 + a.eye_gap)]
    for i, M in enumerate(masses):
        if det and a.radial and M[tuple(np.clip(np.round(F.to_px(det['nose'][None])[0][::-1]).astype(int), 0, N - 1))]:
            chains, arcs = radial_mass(F, M, det['nose'] + [0, a.nose_dy], fexcl, sp=a.sep_mass)
            for j, c in enumerate(chains): items['mass%d_%d' % (i, j)] = dict(path=np.asarray(c), closed=False)
            strokes += arcs; continue
        chains, arcs = ap.comb_flow(F, M, dummy, photo_w=a.photo_w, sep=a.sep_mass, first=1.4, erode=1.2, step=0.6, min_len=a.mass_min_stroke)
        for j, c in enumerate(chains): items['mass%d_%d' % (i, j)] = dict(path=np.asarray(c), closed=False)
        strokes += arcs
    r = np.hypot(*outline.T); k = int(np.argmax(r)); p0 = outline[k]; u = p0 / np.hypot(*p0); rim = u * 113.0
    if not a.no_outline:
        if closed: items['outline'] = dict(path=outl[0], closed=True)
        else:                                       # open pieces: split the one holding the entry point so both halves start there
            n_ = 0
            for o_ in outl:
                d = np.hypot(*(o_ - p0).T); kk = int(np.argmin(d))
                if d[kk] < 1e-6 and 0 < kk < len(o_) - 1:
                    parts = [o_[:kk + 1][::-1], o_[kk:]]
                else: parts = [o_]
                for q_ in parts:
                    if len(q_) > 3: items['outline%d' % n_] = dict(path=q_, closed=False); n_ += 1
    if det:                                                  # no tone-contour lines inside the face box (the features replace them)
        x0, y0, w_, h_ = det['box']; sc = det['sc']
        c0 = np.array([(x0 + w_ / 2 - det['px0'][0]) * sc, -(y0 + h_ / 2 - det['px0'][1]) * sc])
        def inbox(Q): return np.mean([abs(q[0] - c0[0]) < 0.55 * w_ * sc and abs(q[1] - c0[1]) < 0.55 * h_ * sc for q in Q]) > 0.4
        lines = [(Q, st) for Q, st in lines if not inbox(Q)]
        feats = eye_shapes(det, a) + [('nose', nose_shape(det, a), False)]
        for n_, p_, c_ in feats: items[n_] = dict(path=p_, closed=c_)
    for i, (Q, st) in enumerate(lines): items['line%d' % i] = dict(path=Q, closed=False)
    # entry: the outline point nearest the rim, reached by a short radial stub from the rim
    dots = dark_dots(F, a, masses) if a.dots else []
    allp = np.vstack([outline] + [Q for Q, _ in lines])
    for i, (ctr, rr, d) in enumerate(dots):
        sp = ap.iris_spiral(ctr, rr, a.dot_pitch, 1.0); j = int(np.argmin(np.hypot(*(allp - ctr).T))); ang = math.atan2(*(allp[j] - ctr)[::-1])
        ex_r = np.hypot(*(sp[0] - ctr)); sp = np.array(ap.iris_spiral(ctr, rr, a.dot_pitch, 1.0))
        c, sn = math.cos(ang), math.sin(ang); R = np.array([[c, -sn], [sn, c]]); sp = (sp - ctr) @ R.T + ctr
        items['dot%d' % i] = dict(path=sp, closed=False)
    items['entry'] = dict(path=np.array([rim, p0]), closed=False, fixed=True)
    tiers = [['entry'], ['outline*'], ['mass*'], ['line*'], ['dot*'], ['eye*'], ['nose']]
    path, hops = ap.route(items, tiers, start=tuple(rim), end_to=rim)
    return F, bgr, path, hops, dict(dots=dots, outl=outl, outline=outline, closed=closed, lines=lines, masses=masses, strokes=strokes)


def plan_png(F, path, ex, fn, size=900):
    k = size / (2 * ap.RTRAY)
    im = np.full((size, size, 3), 255, np.uint8)
    def px(P): return np.round(np.c_[P[:, 0] * k + size / 2, size / 2 - P[:, 1] * k]).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(im, [px(np.asarray(path))], False, (150, 150, 150), 1, cv2.LINE_AA)
    for o_ in ex['outl']: cv2.polylines(im, [px(o_)], False, (0, 0, 160), 1, cv2.LINE_AA)
    for Q, st in ex['lines']: cv2.polylines(im, [px(Q)], False, (0, 0, 200), 2, cv2.LINE_AA)
    cv2.circle(im, (size // 2, size // 2), int(ap.RTRAY * k), (0, 160, 0), 1)
    cv2.imwrite(fn, im)


def debug_png(F, ex, fn):
    im = cv2.cvtColor(np.clip(F.gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR); im[~F.valid] = 255
    for M in ex['masses']: im[M] = (0.5 * im[M] + 0.5 * np.array([255, 120, 0])).astype(np.uint8)
    def px(P): return np.round(F.to_px(P)).astype(np.int32).reshape(-1, 1, 2)
    for o_ in ex['outl']: cv2.polylines(im, [px(o_)], False, (0, 255, 255), 2)
    for Q, st in ex['lines']: cv2.polylines(im, [px(Q)], False, (0, 0, 255), 2)
    for c_, r_, d_ in ex['dots']: cv2.circle(im, tuple(np.round(F.to_px(c_[None])[0]).astype(int)), int(r_ / RES), (0, 255, 0), 2)
    cv2.imwrite(fn, im)


# per-photo input: rough subject polygon / crop (the only manual input; everything else is automatic)
PRESETS = {
    'cat': dict(mask='poly:0.25,0.02 0.34,0.12 0.45,0.1 0.57,0.1 0.68,0.06 0.73,0.04 0.72,0.2 0.76,0.3 0.82,0.45 0.84,0.62 0.3,0.62 0.28,0.48 0.2,0.4 0.2,0.28 0.23,0.17',
                crop='0.12,0.0,0.9,0.62', max_lines=10, dots=0),
    'owl': dict(mask='poly:0.07,0.1 0.12,0.08 0.19,0.13 0.3,0.13 0.5,0.12 0.6,0.1 0.75,0.1 0.97,0.13 0.96,0.2 0.8,0.2 0.9,0.35 1.0,0.55 1.0,1.0 0.1,1.0 0.1,0.75 0.12,0.6 0.17,0.5 0.14,0.4 0.17,0.3 0.12,0.2',
                max_lines=10, len_pow=1.0, sep=6.0, dark=0.0, dot_round=0.35, dot_rmax=7.0, dot_n=2),
    'lighthouse': dict(mask='poly:0.455,0.16 0.50,0.16 0.515,0.22 0.525,0.235 0.58,0.66 0.35,0.66 0.405,0.235 0.415,0.22', crop='0.2,0.1,0.72,0.7', edge_sigma=1.8, min_strength=0.3, min_len=12.0, dark=0.0, dot_n=3),
}


def argparser():
    p = argparse.ArgumentParser(); p.add_argument('name'); p.add_argument('--v', default='a')
    p.add_argument('--rect', default='0.05,0.05,0.95,0.95'); p.add_argument('--mask', default='grabcut'); p.add_argument('--core', type=float, default=0.2); p.add_argument('--crop', default='0,0,1,1', help='keep only this part of the photo (fractions x0,y0,x1,y1); cut edges are not outlined')
    p.add_argument('--fit', type=float, default=106.0, help='radius (mm) of the circle the subject is fitted into')
    p.add_argument('--clahe', type=float, default=2.0)
    p.add_argument('--out-smooth', dest='out_smooth', type=float, default=2.0)
    p.add_argument('--edge-sigma', dest='edge_sigma', type=float, default=2.5); p.add_argument('--edge-in', dest='edge_in', type=float, default=4.0)
    p.add_argument('--canny-lo', dest='canny_lo', type=float, default=85); p.add_argument('--canny-hi', dest='canny_hi', type=float, default=95)
    p.add_argument('--min-len', dest='min_len', type=float, default=15.0); p.add_argument('--line-smooth', dest='line_smooth', type=float, default=2.0)
    p.add_argument('--max-lines', dest='max_lines', type=int, default=25); p.add_argument('--min-strength', dest='min_strength', type=float, default=0.45)
    p.add_argument('--lev-lo', dest='lev_lo', type=float, default=8); p.add_argument('--lev-hi', dest='lev_hi', type=float, default=92); p.add_argument('--lev-step', dest='lev_step', type=float, default=6)
    p.add_argument('--sep', type=float, default=5.0, help='min gap between lines (mm)')
    p.add_argument('--dark', type=float, default=0.30, help='fraction of the subject that counts as dark (0 = no masses)')
    p.add_argument('--dark-sigma', dest='dark_sigma', type=float, default=3.0); p.add_argument('--mass-in', dest='mass_in', type=float, default=2.0)
    p.add_argument('--mass-open', dest='mass_open', type=float, default=8.0); p.add_argument('--mass-min', dest='mass_min', type=float, default=24.0)
    p.add_argument('--mass-area', dest='mass_area', type=float, default=700.0); p.add_argument('--sep-mass', dest='sep_mass', type=float, default=3.0)
    p.add_argument('--mass-min-stroke', dest='mass_min_stroke', type=float, default=10.0); p.add_argument('--photo-w', dest='photo_w', type=float, default=0.5)
    p.add_argument('--dots', type=int, default=1); p.add_argument('--dot-round', dest='dot_round', type=float, default=0.55); p.add_argument('--dot-contrast', dest='dot_contrast', type=float, default=50); p.add_argument('--dot-n', dest='dot_n', type=int, default=4); p.add_argument('--dot-pct', dest='dot_pct', type=float, default=0.06); p.add_argument('--dot-in', dest='dot_in', type=float, default=2.0)
    p.add_argument('--dot-min', dest='dot_min', type=float, default=6.0); p.add_argument('--dot-max', dest='dot_max', type=float, default=22.0); p.add_argument('--dot-rmax', dest='dot_rmax', type=float, default=5.0); p.add_argument('--dot-pitch', dest='dot_pitch', type=float, default=1.9)
    p.add_argument('--len-pow', dest='len_pow', type=float, default=0.5)
    p.add_argument('--animal', action='store_true'); p.add_argument('--radial', type=int, default=1); p.add_argument('--eye-style', dest='eye_style', default='almond')
    p.add_argument('--eye-w', dest='eye_w', type=float, default=18.0); p.add_argument('--eye-h', dest='eye_h', type=float, default=10.0); p.add_argument('--eye-dot', dest='eye_dot', type=float, default=3.0)
    p.add_argument('--eye-gap', dest='eye_gap', type=float, default=3.0); p.add_argument('--nose-w', dest='nose_w', type=float, default=14.0); p.add_argument('--nose-stem', dest='nose_stem', type=float, default=7.0)
    p.add_argument('--nose-dy', dest='nose_dy', type=float, default=0.0)
    p.add_argument('--no-outline', dest='no_outline', action='store_true'); p.add_argument('--sim', action='store_true')
    return p


if __name__ == '__main__':
    pa = argparser(); nm = [x for x in sys.argv[1:] if not x.startswith('-')][:1]
    if nm and nm[0] in PRESETS: pa.set_defaults(**PRESETS[nm[0]])
    a = pa.parse_args()
    F, bgr, path, hops, ex = build(a.name, a)
    tag = '%s_%s' % (a.name, a.v)
    files, tr = ap.to_files(F, path, tag, maxpts=11000)
    plan_png(F, path, ex, '%s/%s_plan.png' % (OUT, tag))
    debug_png(F, ex, '%s/%s_dbg.png' % (OUT, tag))
    ph = cv2.cvtColor(np.clip(F.gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR); ph[~F.valid] = 255; cv2.imwrite('%s/%s_photo.png' % (OUT, a.name), ph)
    print('dots %d;' % len(ex['dots']), 'lines %d (%.0f mm), masses %d, strokes %d; hops>5mm: %s' % (len(ex['lines']), sum(length(q) for q, _ in ex['lines']), len(ex['masses']), len(ex['strokes']), [h for h in hops if h[1] > 5]))
    tot = 0
    for f in files:
        t = np.loadtxt(f, ndmin=2); m = rp.mini_minutes(t); tot += m
        print(os.path.basename(f), len(t), 'points', '%.1f min' % m)
    print('total %.1f min' % tot)
    if a.sim:
        import subprocess
        subprocess.run([sys.executable, HERE + '/auto_sim.py', '%s/%s.png' % (OUT, tag)] + files + ['--outward'])
