#!/usr/bin/env python3
"""photo_sand - photograph -> "stained glass" comb plan for the Oasis Mini, scored in the calibrated real-sand simulator.
SIMULATION / PATH ONLY. Never contacts a table. Outputs go to captures/photo-sand/.

    python3 tools/photo_sand.py palette [--px 0.1]            # simulate the chart of comb patches -> palette_sim_<px>.json
    python3 tools/photo_sand.py run SUBJECT VARIANT.json ...   # build a plan, comb it, simulate, score (see VARIANT keys below)
    python3 tools/photo_sand.py sweep SUBJECT                  # one-knob-at-a-time sweep at the coarse grid (0.15 mm/px)
Subjects: lek, thomas (faces from captures/relief-study/faces/*.pkl, soft oval vignette), axe (target + hatchet cropped from lek.jpg)

The palette file is swappable: palette_real.json with the same layout (see PALETTE FORMAT in palette_build) replaces the sim numbers.
"""
import argparse, json, math, os, sys, time, copy
import numpy as np, cv2
from scipy import ndimage as ndi
from scipy.ndimage import gaussian_filter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'captures', 'photo-sand')
os.makedirs(OUT, exist_ok=True)
G = 0.25                                  # analysis grid, mm per px
NG = 944                                  # grid is NG x NG, centre = table centre, +-118 mm
R_WORK = 114.0

def mm_xy(cols, rows):
    return (np.asarray(cols) + 0.5 - NG / 2) * G, -(np.asarray(rows) + 0.5 - NG / 2) * G

DISC = None
def disc(r=R_WORK):
    yy, xx = np.mgrid[0:NG, 0:NG]
    x, y = mm_xy(xx, yy)
    return np.hypot(x, y) <= r

# ------------------------------------------------------------------ palette (simulated chart)
SPACINGS = [0.0, 0.6, 0.9, 1.2, 1.8, 2.5, 3.5, 5.0, 7.0, 10.0, 14.0]      # 0 = no strokes at all (the erase texture)
DIRS = [0, 45, 90, 135]
PATCH = 18.0          # mm square; measured over the central 8 x 8 mm (lips reach ~5 mm in from the stroke ends)

def _patch_path(cx, cy, sp, ang, half=PATCH / 2, inset=0.5):
    from shapely.geometry import box, LineString
    sq = box(cx - half + inset, cy - half + inset, cx + half - inset, cy + half - inset)
    d = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))]); n = np.array([-d[1], d[0]])
    L = 40.0
    segs = []
    k = np.arange(-int(L / sp), int(L / sp) + 1)
    for i in k:
        c = np.array([cx, cy]) + n * i * sp
        g = LineString([c - d * L, c + d * L]).intersection(sq)
        if g.is_empty or g.geom_type != 'LineString' or g.length < 1: continue
        p = np.array(g.coords)
        segs.append(p)
    out = []
    for j, p in enumerate(segs):
        if j % 2: p = p[::-1]
        out.append(p)
    return np.vstack(out)

def _palette_job(args):
    sp, px = args
    import section_sim as ss, sand_relief_path as rp
    T = ss.WinTable(0.0, 0.0, 56.0, px=px, deposit='real')
    T.erase(0.02, outward=False)
    cen = {0: (-11, 11), 45: (11, 11), 90: (-11, -11), 135: (11, -11)}
    path = []
    for ang in DIRS:
        if sp > 0: path.append(_patch_path(*cen[ang], sp, ang))
    if path:
        tr, _ = rp.to_thr_pts(np.vstack(path), R_WORK, max_step=1.0)
        T.run(tr)
    im = np.asarray(T.render_win_photo().convert('L'), float) / 255.0
    res = {}
    Nn = im.shape[0]
    for ang in DIRS:
        cx, cy = cen[ang]
        c0 = int(round(Nn / 2 + cx / px)); r0 = int(round(Nn / 2 - cy / px)); h = int(4.0 / px)
        sub = im[r0 - h:r0 + h, c0 - h:c0 + h]
        hf = sub - gaussian_filter(im, 2.0 / px)[r0 - h:r0 + h, c0 - h:c0 + h]
        res[str(ang)] = dict(mean=float(sub.mean()), tex=float(hf.std()))
    return sp, res, im

def palette_build(px=0.1, name=None):
    """PALETTE FORMAT: {"source": "sim"|"real", "px":..., "spacings":[...], "dirs":[...],
       "data": {"<spacing>": {"<dir>": {"mean": brightness 0-1 (blurred over the patch), "tex": std of the 2 mm high-pass}}}}
       A real-sand palette is the same file with measured numbers."""
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(8) as p:
        out = p.map(_palette_job, [(s, px) for s in SPACINGS])
    data = {str(sp): res for sp, res, _ in out}
    pal = dict(source='sim', px=px, spacings=SPACINGS, dirs=DIRS, data=data)
    fn = name or os.path.join(OUT, 'palette_sim_%g.json' % px)
    json.dump(pal, open(fn, 'w'), indent=1)
    # chart picture: one column per spacing
    tiles = [cv2.resize((im * 255).astype(np.uint8), (280, 280), interpolation=cv2.INTER_AREA) for _, _, im in out]
    for t, (sp, _, _) in zip(tiles, out):
        cv2.putText(t, '%g mm' % sp, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 4)
    sheet = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
    cv2.imwrite(os.path.join(OUT, 'palette_chart_%g.png' % px), sheet)
    print('palette done %.0f s' % (time.time() - t0))
    return pal

class Palette:
    def __init__(self, fn):
        self.d = json.load(open(fn)); self.fn = fn
        self.sp = np.array(self.d['spacings'], float)
        self.mean = np.array([np.mean([self.d['data'][str(s)][str(a)]['mean'] for a in self.d['dirs']]) for s in self.sp])
        self.tex = np.array([np.mean([self.d['data'][str(s)][str(a)]['tex'] for a in self.d['dirs']]) for s in self.sp])
        self.dirstd = np.array([np.std([self.d['data'][str(s)][str(a)]['mean'] for a in self.d['dirs']]) for s in self.sp])
        # monotone (brighter = finer) envelope for inversion
        order = np.argsort(self.sp)
        m = self.mean[order]
        iso = np.minimum.accumulate(m[::-1])[::-1] if False else m
        self.order = order
    def spacing_for(self, t, lo_sp=0.0, hi_sp=99.0, snap=True, curve=1.0, empty=True, tol=0.008, axis='mean'):
        """t = 0 (darkest) .. 1 (lightest) -> spacing whose mean brightness best matches Bmin + (Bmax-Bmin) t^curve,
        restricted to lo_sp <= spacing <= hi_sp (lo_sp bounds the path length: fine strokes are expensive)."""
        ok = ((self.sp >= lo_sp - 1e-9) | (self.sp == 0 if empty else False)) & (self.sp <= hi_sp + 1e-9)
        sp, mu = self.sp[ok], self.mean[ok]
        if axis == 'tex':        # real sand: brightness is flat, DARKNESS = texture contrast (shadow stripes)
            mu = self.tex[ok]
            want = mu.max() - (mu.max() - mu.min()) * np.clip(t, 0, 1) ** curve
            tol = 0.004
        else:
            bmin, bmax = mu.min(), mu.max()
            want = bmin + (bmax - bmin) * np.clip(t, 0, 1) ** curve
        d = np.abs(mu - float(want))
        near = np.flatnonzero(d <= d.min() + tol)
        # among near-ties take the cheapest (no strokes, else the coarsest spacing)
        key = [(0.0 if sp[i] == 0 else 1.0, -sp[i]) for i in near]
        return float(sp[near[min(range(len(near)), key=lambda q: key[q])]])


# ------------------------------------------------------------------ subjects
SUBJECTS = {
    # vignette ellipse in analysis-grid px: (cx, cy, rx, ry); the picture fades to the flat background tone outside it
    'lek': dict(kind='face', pkl='lek', vig=(478, 490, 300, 405)),
    'thomas': dict(kind='face', pkl='thomas', vig=(488, 505, 300, 420)),
    'axe': dict(kind='object', crop=(1500, 650, 960)),
}

def load_subject(name):
    """-> dict(gray float32 NGxNG 0..1 (source photo, grayscale, on the tray grid), vig weight map or None)"""
    spec = SUBJECTS[name]
    if spec['kind'] == 'face':
        import relief_faces as rf
        P = rf.Portrait(os.path.join(ROOT, 'captures/relief-study/faces/%s.pkl' % spec['pkl']))
        g = np.clip(P.gray(), 0, 255).astype(np.float32) / 255.0
        pad = (NG - g.shape[0]) // 2
        g = np.pad(g, pad, mode='edge')
        cx, cy, rx, ry = spec['vig']
        yy, xx = np.mgrid[0:NG, 0:NG]
        rr = np.hypot((xx - cx) / rx, (yy - cy) / ry)
        w = np.clip((1.12 - rr) / 0.30, 0, 1); w = w * w * (3 - 2 * w)
        return dict(gray=g, vig=w.astype(np.float32))
    cx, cy, side = spec['crop']
    im = cv2.imread(os.path.join(ROOT, 'captures/family-source/lek.jpg'), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
    h = side // 2
    crop = im[cy - h:cy + h, cx - h:cx + h]
    s = int(round(2 * R_WORK / G))
    crop = cv2.resize(crop, (s, s), interpolation=cv2.INTER_AREA)
    pad = (NG - s) // 2
    return dict(gray=np.pad(crop, pad, mode='edge'), vig=None)

# ------------------------------------------------------------------ tone image
DEFAULTS = dict(sub='lek', cell=11.0, compact=0.0008, merge=0.07, edge_w=1.0, wmin=9.0, amin=60.0, seg_blur=1.0, smooth_mm=1.2,
                bilat=0.06, lc=0.3, gamma=1.0, curve=1.0, bg_tone=0.25, lo_sp=1.2, hi_sp=14.0, snap=True, empty=True, axis='tex',
                sigma_t=4.0, dir_beta=0.5, cmin=0.25, bg_mode='rings', shrink=0.55, order='bg_first', start_center=True,
                features=False, feat_thr=0.10, feat_len=14.0, px=0.15, merge_same=True, palette='palette_real.json', tag='v')

def prep_tone(S, p):
    g = S['gray'].copy()
    m = disc(116.0)
    gb = g
    for _ in range(2):
        gb = cv2.bilateralFilter(gb.astype(np.float32), 0, p['bilat'], 2.0 / G)
    w = S['vig']
    ref = m & ((w > 0.5) if w is not None else True)
    lo, hi = np.percentile(gb[ref], [2, 98])
    t = np.clip((gb - lo) / (hi - lo + 1e-6), 0, 1)
    if p['lc']:
        t = t + p['lc'] * (t - gaussian_filter(t, 12.0 / G))
    t = np.clip(t, 0, 1) ** p['gamma']
    if w is not None:
        t = p['bg_tone'] + w * (t - p['bg_tone'])
    # reference picture for scoring: the source photo (grayscale) with the same background treatment, no contrast tricks
    src = (g - lo) / (hi - lo + 1e-6)
    src = np.clip(src, 0, 1)
    if w is not None:
        src = p['bg_tone'] + w * (src - p['bg_tone'])
    return t.astype(np.float32), src.astype(np.float32), w

# ------------------------------------------------------------------ segmentation into sections
def _pairs(lab):
    a = np.r_[lab[:, :-1].ravel(), lab[:-1, :].ravel()]; b = np.r_[lab[:, 1:].ravel(), lab[1:, :].ravel()]
    return a, b

def segment(t, p, w=None):
    from skimage.segmentation import watershed
    D = disc(117.0)
    ts = gaussian_filter(t, p['seg_blur'] / G)
    gx, gy = cv2.Sobel(ts, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(ts, cv2.CV_32F, 0, 1, ksize=3)
    gm = np.hypot(gx, gy); gm = gm / (np.percentile(gm[D], 95) + 1e-6)
    # markers on a hex grid, nudged to the quietest spot nearby
    c = p['cell'] / G
    gq = gaussian_filter(gm, c / 5)
    mk = np.zeros((NG, NG), np.int32); n = 0
    row = 0
    y = c / 2
    while y < NG:
        x = (c / 2) + (c / 2 if row % 2 else 0)
        while x < NG:
            xi, yi = int(x), int(y)
            if 0 <= xi < NG and 0 <= yi < NG and D[yi, xi]:
                r = int(c / 3)
                y0, y1, x0, x1 = max(0, yi - r), min(NG, yi + r + 1), max(0, xi - r), min(NG, xi + r + 1)
                sub = gq[y0:y1, x0:x1] + 0.0 * D[y0:y1, x0:x1]
                j = np.unravel_index(np.argmin(sub), sub.shape)
                n += 1; mk[y0 + j[0], x0 + j[1]] = n
            x += c
        y += c * 0.866; row += 1
    lab = watershed(gm, mk, mask=D, compactness=p['compact'])
    lab = _merge(lab, ts, gm, p)
    lab = _clean(lab, ts, p, D)
    return lab, ts

def _merge(lab, ts, gm, p, tau=None):
    tau = p['merge'] if tau is None else tau
    ids = np.unique(lab[lab > 0]); K = ids.max() + 1
    A = np.bincount(lab.ravel(), minlength=K).astype(float)
    mu = np.bincount(lab.ravel(), ts.ravel(), minlength=K) / np.maximum(A, 1)
    a, b = _pairs(lab); ok = (a != b) & (a > 0) & (b > 0)
    gmv = np.r_[np.maximum(gm[:, :-1], gm[:, 1:]).ravel(), np.maximum(gm[:-1, :], gm[1:, :]).ravel()]
    C = np.zeros((K, K)); Gs = np.zeros((K, K))
    np.add.at(C, (a[ok], b[ok]), 1); np.add.at(Gs, (a[ok], b[ok]), gmv[ok])
    C = C + C.T; Gs = Gs + Gs.T
    alive = A > 0; alive[0] = False
    parent = np.arange(K)
    while True:
        Cm = np.where(C > 0, 1.0, 0.0)
        cost = np.abs(mu[:, None] - mu[None, :]) + p['edge_w'] * tau * np.divide(Gs, C, out=np.zeros_like(Gs), where=C > 0)
        cost = np.where(Cm > 0, cost, 9.0)
        # small regions merge more eagerly
        small = (A < p['amin'] / G / G)
        cost = cost - 0.5 * tau * (small[:, None] | small[None, :]) * (Cm > 0)
        cost[~alive, :] = 9; cost[:, ~alive] = 9
        np.fill_diagonal(cost, 9)
        i, j = np.unravel_index(np.argmin(cost), cost.shape)
        if cost[i, j] > tau: break
        if i > j: i, j = j, i
        mu[i] = (mu[i] * A[i] + mu[j] * A[j]) / (A[i] + A[j]); A[i] += A[j]; A[j] = 0; alive[j] = False
        C[i, :] += C[j, :]; C[:, i] += C[:, j]; C[j, :] = 0; C[:, j] = 0; C[i, i] = 0
        Gs[i, :] += Gs[j, :]; Gs[:, i] += Gs[:, j]; Gs[j, :] = 0; Gs[:, j] = 0; Gs[i, i] = 0
        parent[parent == j] = i
    return parent[lab] * (lab > 0)

def _clean(lab, ts, p, D):
    """smooth boundaries, drop parts narrower than wmin (they join the neighbour that reaches them), drop tiny pieces"""
    K = lab.max() + 1
    rw = max(1, int(round(p['wmin'] / 2 / G)))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rw + 1,) * 2)
    for rnd in range(3):
        # smooth: one-hot gaussian + argmax
        ids = np.unique(lab[lab > 0])
        best = np.full((NG, NG), -1.0, np.float32); out = np.zeros((NG, NG), np.int32)
        for k in ids:
            m = gaussian_filter((lab == k).astype(np.float32), p['smooth_mm'] / G)
            u = m > best; best[u] = m[u]; out[u] = k
        lab = out * D
        # narrow parts
        keep = np.zeros_like(lab)
        for k in np.unique(lab[lab > 0]):
            m = (lab == k).astype(np.uint8)
            op = cv2.morphologyEx(m, cv2.MORPH_OPEN, ker)
            keep[op > 0] = k
        # tiny pieces
        cl, nc = ndi.label(keep > 0)  # touching regions are one blob here; label per id instead
        for k in np.unique(keep[keep > 0]):
            l2, n2 = ndi.label(keep == k)
            if n2 == 0: continue
            sizes = ndi.sum(np.ones_like(l2), l2, range(1, n2 + 1))
            for q, s_ in enumerate(sizes):
                if s_ * G * G < p['amin']: keep[l2 == q + 1] = 0
        hole = (keep == 0) & D
        if hole.any():
            idx = ndi.distance_transform_edt(keep == 0, return_distances=False, return_indices=True)
            keep = keep[idx[0], idx[1]] * D
        lab = keep
    return lab

def relabel_components(lab):
    out = np.zeros_like(lab); n = 0; parent = {}
    for k in np.unique(lab[lab > 0]):
        l2, n2 = ndi.label(lab == k)
        for q in range(1, n2 + 1):
            n += 1; out[l2 == q] = n; parent[n] = int(k)
    return out, parent

# ------------------------------------------------------------------ direction field
def direction_field(t, p, centroid):
    """stroke direction (doubled-angle unit vector field, cos2a, sin2a) following the isophotes of the tone image, smoothed;
    falls back to a coarser smoothing, then to tangential (around centroid)"""
    ts = gaussian_filter(t, 1.2 / G)
    gx, gy = cv2.Sobel(ts, cv2.CV_32F, 1, 0, ksize=3), -cv2.Sobel(ts, cv2.CV_32F, 0, 1, ksize=3)   # y up
    jxx, jyy, jxy = gx * gx, gy * gy, gx * gy
    def field(sig):
        a, b, c = [gaussian_filter(x, sig / G) for x in (jxx, jyy, jxy)]
        vx, vy = a - b, 2 * c; e = a + b + 1e-9
        coh = np.hypot(vx, vy) / e
        ang = 0.5 * np.arctan2(vy, vx) + math.pi / 2           # strokes run ALONG isophotes (perpendicular to gradient)
        return ang, coh, e
    a1, c1, e1 = field(p['sigma_t']); a2, c2, e2 = field(3 * p['sigma_t'])
    yy, xx = np.mgrid[0:NG, 0:NG]; x, y = mm_xy(xx, yy)
    at = np.arctan2(y - centroid[1], x - centroid[0]) + math.pi / 2      # tangential about the centroid
    en = np.percentile(e1[disc()], 60) + 1e-9
    def wgt(c, e): return np.clip((c - 0.15) / 0.35, 0, 1) * np.clip(e / en, 0, 1)
    w1, w2 = wgt(c1, e1), wgt(c2, e2)
    cx_ = w1 * np.cos(2 * a1) + (1 - w1) * (w2 * np.cos(2 * a2) + (1 - w2) * np.cos(2 * at))
    sx_ = w1 * np.sin(2 * a1) + (1 - w1) * (w2 * np.sin(2 * a2) + (1 - w2) * np.sin(2 * at))
    coh = np.clip(w1 + (1 - w1) * w2, 0, 1)
    return cx_.astype(np.float32), sx_.astype(np.float32), coh.astype(np.float32)


# ------------------------------------------------------------------ feature lines (eyes, brows, mouth, nostrils, jaw)
def feature_lines(t, w, p):
    """thin dark structures: local darkness (6 mm blur minus 1 mm blur) above feat_thr, skeletonised, longest path per piece"""
    from skimage.morphology import skeletonize
    ts = gaussian_filter(t, 0.9 / G)
    dk = gaussian_filter(t, 5.0 / G) - ts
    m = (dk > p['feat_thr']) & disc(108.0)
    if w is not None: m &= gaussian_filter(w, 2.0 / G) > 0.6
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
    sk = skeletonize(m)
    lab, n = ndi.label(sk, structure=np.ones((3, 3)))
    lines = []
    for q in range(1, n + 1):
        ys, xs = np.nonzero(lab == q)
        if len(ys) * G < p['feat_len']: continue
        pts = {(y, x) for y, x in zip(ys, xs)}
        nb = lambda a: [(a[0] + dy, a[1] + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx) and (a[0] + dy, a[1] + dx) in pts]
        def bfs(src):
            dist = {src: 0}; par = {src: None}; qu = [src]
            for a in qu:
                for b in nb(a):
                    if b not in dist: dist[b] = dist[a] + 1; par[b] = a; qu.append(b)
            far = qu[-1]; return far, par
        a0 = next(iter(pts)); e1, _ = bfs(a0); e2, par = bfs(e1)
        path = []; a = e2
        while a is not None: path.append(a); a = par[a]
        path = np.array(path, float)
        if len(path) * G < p['feat_len']: continue
        x, y = mm_xy(path[:, 1], path[:, 0]); P = np.c_[x, y]
        from scipy.ndimage import gaussian_filter1d
        P = np.c_[gaussian_filter1d(P[:, 0], 3, mode='nearest'), gaussian_filter1d(P[:, 1], 3, mode='nearest')]
        lines.append(P.round(2).tolist())
    return lines, m

# ------------------------------------------------------------------ plan
def smooth_ring(r, n=2):
    r = np.asarray(r, float)
    for _ in range(n):
        q = np.roll(r, -1, 0)
        o = np.empty((2 * len(r), 2)); o[0::2] = 0.75 * r + 0.25 * q; o[1::2] = 0.25 * r + 0.75 * q; r = o
    return r

def polys_of(mask):
    cs, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None: return []
    hier = hier[0]; out = []
    def conv(c):
        c = cv2.approxPolyDP(c, 0.6, True)[:, 0, :].astype(float)
        if len(c) < 3: return None
        x, y = mm_xy(c[:, 0], c[:, 1]); return np.c_[x, y]
    for i, c in enumerate(cs):
        if hier[i][3] != -1: continue
        ring = conv(c)
        if ring is None: continue
        holes = []
        j = hier[i][2]
        while j != -1:
            h = conv(cs[j])
            if h is not None: holes.append(smooth_ring(h).round(2).tolist())
            j = hier[j][0]
        out.append((smooth_ring(ring).round(2).tolist(), holes))
    return out

def build_plan(S, p, tag):
    t, src, w = prep_tone(S, p)
    pal = Palette(os.path.join(OUT, p['palette']) if not os.path.isabs(p['palette']) else p['palette'])
    lab, ts = segment(t, p, w)
    # per-region tone -> spacing; same-spacing neighbours merge
    def region_sp(lab):
        sp = {}
        for k in np.unique(lab[lab > 0]):
            tone = float(np.median(ts[lab == k]))
            sp[k] = float(pal.spacing_for(tone, p['lo_sp'], p['hi_sp'], p['snap'], p['curve'], p['empty'], axis=p['axis']))
        return sp
    sp = region_sp(lab)
    if p['merge_same']:
        for _ in range(3):
            lab2, par = relabel_components(lab)
            sp2 = {}
            for k in np.unique(lab2[lab2 > 0]): sp2[k] = sp[par[k]] if par[k] in sp else None
            # union adjacent comps with same spacing
            a, b = _pairs(lab2); ok = (a != b) & (a > 0) & (b > 0)
            pairs = set(zip(a[ok].tolist(), b[ok].tolist()))
            uf = {k: k for k in sp2}
            def f(x):
                while uf[x] != x: uf[x] = uf[uf[x]]; x = uf[x]
                return x
            for x, y in pairs:
                if sp2[x] == sp2[y]: uf[f(x)] = f(y)
            lut = np.zeros(lab2.max() + 1, np.int32)
            for k in sp2: lut[k] = f(k)
            lab = lut[lab2]
            sp = region_sp(lab)
            break
    lab, par = relabel_components(lab)
    sp = {}
    for k in np.unique(lab[lab > 0]):
        sp[k] = float(pal.spacing_for(float(np.median(ts[lab == k])), p['lo_sp'], p['hi_sp'], p['snap'], p['curve'], p['empty'], axis=p['axis']))
    # subject centroid (for tangential defaults, bg rings)
    ww = (w if w is not None else np.ones_like(t)) * disc()
    ys, xs = np.nonzero(ww > 0.5)
    cxm, cym = mm_xy(xs.mean(), ys.mean())
    cxs, sxs, coh = direction_field(t, p, (float(cxm), float(cym)))
    # section-mean regularisation of the direction (doubled-angle)
    cxe, sxe = cxs.copy(), sxs.copy()
    if p['dir_beta'] > 0:
        for k in sp:
            m = lab == k
            mc, ms = cxs[m].mean(), sxs[m].mean(); n = math.hypot(mc, ms) + 1e-9
            cxe[m] = (1 - p['dir_beta']) * cxs[m] + p['dir_beta'] * mc / n * np.maximum(coh[m], 0.3)
            sxe[m] = (1 - p['dir_beta']) * sxs[m] + p['dir_beta'] * ms / n * np.maximum(coh[m], 0.3)
    ang = np.degrees(0.5 * np.arctan2(sxe, cxe)) % 180
    ffile = os.path.join(OUT, 'work', 'flow_%s.npz' % tag); os.makedirs(os.path.dirname(ffile), exist_ok=True)
    np.savez_compressed(ffile, F=ang[::2, ::2].astype(np.float16), F__org=np.array([(0.5 - NG / 2) * G, -(0.5 - NG / 2) * G, 2 * G]))
    secs = []; meta = {}
    for k in sorted(sp):
        m = lab == k
        isbg = (w is not None) and float((w[m]).mean()) < 0.15
        coh_m = float(coh[m].mean())
        for j, (ring, holes) in enumerate(polys_of(m) if sp[k] > 0 else []):
            s = dict(name='s%03d%s' % (k, '' if j == 0 else '#%d' % j), kind='subject', spacing=sp[k], poly=ring, holes=holes)
            if isbg:
                if p['bg_mode'] == 'rings': s.update(mode='rings', center=[float(cxm), float(cym)])
                else: s.update(mode='angle', angle=float(p['bg_mode']))
            elif coh_m > p['cmin'] and m.sum() * G * G > 150:
                s.update(mode='flow', flow=dict(file=ffile, key='F'))
            else:
                a_ = math.degrees(0.5 * math.atan2(sxe[m].mean(), cxe[m].mean())) % 180
                s.update(mode='angle', angle=a_)
            secs.append(s)
        meta[k] = dict(spacing=sp[k], tone=float(np.median(ts[m])), area=float(m.sum() * G * G), bg=bool(isbg), coh=coh_m)
    if p['features']:
        lines, fm = feature_lines(t, w, p)
        info_lines = lines
        if lines:
            secs.append(dict(name='features', kind='background', spacing=2.0, mode='polyline', lines=lines, _bg=False))
    else:
        info_lines = []
    plan = dict(r_work=R_WORK, shrink=p['shrink'], bg_gap=p['shrink'], bg_shrink=p['shrink'], rim=0.6, keep_out=[[0.0, 0.0, 2.0]], sections=secs)
    return plan, dict(t=t, src=src, w=w, lab=lab, ts=ts, meta=meta, flines=info_lines, centroid=(float(cxm), float(cym)), pal=pal)

# ------------------------------------------------------------------ order, comb, thr
def order_names(plan, p):
    from shapely.geometry import Polygon, Point
    secs = plan['sections']
    info = []
    for s in secs:
        if s['name'] == 'features':
            info.append(('features', 2.0, False, Point(0, 0), False)); continue
        pg = Polygon(s['poly'], s.get('holes', [])).buffer(0)
        info.append((s['name'], s['spacing'], s.get('mode') == 'rings' or s.get('_bg', False), pg.centroid, pg.contains(Point(0, 0))))
    pol = p['order']
    if pol == 'greedy': return 'greedy'
    if pol == 'bg_first': key = lambda i: (0 if i[2] else 1, -i[1])
    elif pol == 'dark_first': key = lambda i: (-i[1], 0)
    elif pol == 'light_first': key = lambda i: (i[1], 0)
    elif pol == 'subject_first': key = lambda i: (1 if i[2] else 0, -i[1])
    elif pol == 'center_out': key = lambda i: (math.hypot(i[3].x, i[3].y), 0)
    elif pol == 'center_in': key = lambda i: (-math.hypot(i[3].x, i[3].y), 0)
    else: raise ValueError(pol)
    names = [i[0] for i in sorted([i for i in info if i[0] != 'features'], key=key)]
    if any(i[0] == 'features' for i in info): names.append('features')
    if p.get('start_center'):
        c = [i[0] for i in info if i[4]]
        if c: names.remove(c[0]); names.insert(0, c[0])
    return names

def comb_plan(plan, p):
    import section_comb as sc
    res = sc.comb(plan, order=order_names(plan, p))
    path = np.asarray(res['path'], float)
    return res, np.vstack([[1.0, 0.0], path])

def to_chunks(path, limit=11500):
    import sand_relief_path as rp
    from trex_make import split_chunks
    tr, near = rp.to_thr_pts(path, R_WORK, max_step=4.0)
    return tr, split_chunks(tr, limit)

def write_play(tr, chunks, outdir, name):
    import sand_relief_path as rp
    files = []
    for k, ch in enumerate(chunks):
        fn = os.path.join(outdir, '%s_part%d.thr' % (name, k + 1))
        rp.write_thr(fn, ch, '%s part %d of %d' % (name, k + 1, len(chunks)))
        x = ch[:, 1] * R_WORK * np.cos(ch[:, 0]); y = ch[:, 1] * R_WORK * np.sin(ch[:, 0])
        files.append(dict(file=os.path.basename(fn), points=int(len(ch)), minutes=round(rp.mini_minutes(ch), 1),
                          start_xy=[round(float(x[0]), 1), round(float(y[0]), 1)], end_xy=[round(float(x[-1]), 1), round(float(y[-1]), 1)]))
    return files

# ------------------------------------------------------------------ simulate + score
def simulate(tr, px):
    import sand_relief_sim as s
    T = s.simulate_parallel([tr], erase=0.02, mm_px=px, deposit='real')
    im = np.asarray(T.render(light='photo').convert('L'), np.float32) / 255.0
    c = im.shape[0] / 2.0; h = 118.0 / px
    crop = im[int(round(c - h)):int(round(c + h)), int(round(c - h)):int(round(c + h))]
    return cv2.resize(crop, (NG, NG), interpolation=cv2.INTER_AREA), T

def _norm(x, m):
    lo, hi = np.percentile(x[m], [2, 98]); return np.clip((x - lo) / (hi - lo + 1e-6), 0, 1)

def score_mean(sim, ref, sigma_mm=3.5):
    """tone: Pearson r of both images blurred by sigma_mm; ssim: SSIM on 1 mm/px grayscale (each normalised to its own 2-98 percentile
    range, blurred 1.5 mm); edge: Pearson r of gradient magnitudes of the 2 mm-blurred images. Inside r < 108 mm."""
    from skimage.metrics import structural_similarity
    m = disc(108.0)
    a, b = gaussian_filter(sim, sigma_mm / G), gaussian_filter(ref, sigma_mm / G)
    tone = float(np.corrcoef(a[m], b[m])[0, 1])
    a1, b1 = _norm(gaussian_filter(sim, 1.5 / G), m), _norm(gaussian_filter(ref, 1.5 / G), m)
    k = int(round(1.0 / G))
    ss = structural_similarity(a1[::k, ::k], b1[::k, ::k], data_range=1.0, win_size=9, full=True)[1]
    ssim = float(ss[m[::k, ::k]].mean())
    def gmag(x):
        x = gaussian_filter(x, 2.0 / G); return np.hypot(*np.gradient(x))
    edge = float(np.corrcoef(gmag(_norm(sim, m))[m], gmag(_norm(ref, m))[m])[0, 1])
    return dict(tone=round(tone, 3), ssim=round(ssim, 3), edge=round(edge, 3), score=round((tone + ssim + edge) / 3, 3))

def texmap(sim, sig=3.5, path=None):
    """local contrast map. The sim's erase rings are ~5x stronger than the real erase texture (real std 4.4/255 vs sim 0.09), so where the
    ball never went (farther than 5 mm from the path) the high-pass is replaced by the real smooth-sand level."""
    hp = sim - gaussian_filter(sim, 2.0 / G)
    if path is not None:
        im = np.zeros((NG, NG), np.uint8)
        pts = np.round(np.c_[path[:, 0] / G + NG / 2 - 0.5, -path[:, 1] / G + NG / 2 - 0.5]).astype(np.int32)
        cv2.polylines(im, [pts.reshape(-1, 1, 2)], False, 255, 1)
        near = cv2.dilate(im, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(10 / G) | 1,) * 2)) > 0
        hp = np.where(near, hp, hp * 0.2)
    return np.sqrt(gaussian_filter(hp * hp, sig / G))

def score(sim, ref, path=None):
    """Real sand shows tone as TEXTURE CONTRAST (mean brightness is flat), so the primary metrics compare the photo's darkness
    (1 - 3.5 mm blur) with the sim's local-contrast map E (std of the 2 mm high-pass over a 3.5 mm window):
    tex = Pearson r(E, darkness); ssim = SSIM of the two normalised maps at 1 mm/px; edge = r of gradient magnitudes of the 2 mm-blurred
    renders (lips and creases at real image edges). score = mean of the three. mean = old brightness correlation (kept for reference)."""
    from skimage.metrics import structural_similarity
    m = disc(108.0)
    E = texmap(sim, path=path); Dk = 1 - gaussian_filter(ref, 3.5 / G)
    tex = float(np.corrcoef(E[m], Dk[m])[0, 1])
    k = int(round(1.0 / G))
    En, Dn = _norm(E, m), _norm(Dk, m)
    ssim = float(structural_similarity(En[::k, ::k], Dn[::k, ::k], data_range=1.0, win_size=9, full=True)[1][m[::k, ::k]].mean())
    def gmag(x):
        x = gaussian_filter(x, 2.0 / G); return np.hypot(*np.gradient(x))
    edge = float(np.corrcoef(gmag(_norm(sim, m))[m], gmag(_norm(ref, m))[m])[0, 1])
    mean = float(score_mean(sim, ref)['tone'])
    return dict(tex=round(tex, 3), ssim=round(ssim, 3), edge=round(edge, 3), mean=round(mean, 3), score=round((tex + ssim + edge) / 3, 3))

# ------------------------------------------------------------------ pictures
def to8(x): return (np.clip(x, 0, 1) * 255).astype(np.uint8)

def disc_mask_img(g, bgv=255):
    out = g.copy(); out[~disc(117.0)] = bgv; return out

def plan_image(info, plan):
    lab, pal = info['lab'], info['pal']
    img = np.full((NG, NG), 255, np.uint8)
    for k, m in info['meta'].items():
        v = 250 if m['spacing'] == 0 else 255 - int(255 * (np.log(min(m['spacing'], 8)) - np.log(0.5)) / (np.log(8) - np.log(0.5)) * 0.8)
        img[lab == k] = v
    im = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for k in info['meta']:
        cs, _ = cv2.findContours((lab == k).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(im, cs, -1, (60, 60, 200), 1)
    for L in info.get('flines', []):
        L = np.array(L); c = (L[:, 0] / G + NG / 2 - 0.5), (-L[:, 1] / G + NG / 2 - 0.5)
        cv2.polylines(im, [np.round(np.c_[c]).astype(np.int32).reshape(-1, 1, 2)], False, (200, 60, 0), 2)
    return im

def sheet(images, labels, h=520):
    tiles = []
    for im, lb in zip(images, labels):
        if im.ndim == 2: im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        im = cv2.resize(im, (h, h), interpolation=cv2.INTER_AREA)
        cv2.putText(im, lb, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 160), 2)
        tiles.append(im)
    return np.hstack(tiles)

# ------------------------------------------------------------------ one variant end to end
def run_variant(sub, over, outdir=None, finalist=False, px=None, quiet=False):
    p = dict(DEFAULTS); p.update(over); p['sub'] = sub
    if px: p['px'] = px
    tag = '%s_%s' % (sub, p['tag'])
    outdir = outdir or os.path.join(OUT, 'work'); os.makedirs(outdir, exist_ok=True)
    t0 = time.time()
    S = load_subject(sub)
    plan, info = build_plan(S, p, tag)
    t1 = time.time()
    res, path = comb_plan(plan, p)
    t2 = time.time()
    tr, chunks = to_chunks(path)
    files = write_play(tr, chunks, outdir, tag)
    mins = sum(f['minutes'] for f in files)
    sim, T = simulate(tr, p['px'])
    t3 = time.time()
    sc_src = score(sim, info['src'], path); sc_tone = score(sim, info['t'], path)
    rep = dict(tag=tag, params=p, sections=len(plan['sections']), spacings={str(k): v for k, v in sorted(
        ((s, sum(1 for m in info['meta'].values() if m['spacing'] == s)) for s in sorted(set(m['spacing'] for m in info['meta'].values()))))},
        score_vs_photo=sc_src, score_vs_enhanced=sc_tone, minutes=round(mins, 1), parts=files, path_m=round(float(np.hypot(*np.diff(path, axis=0).T).sum() / 1000), 2),
        travel_over_finished_mm=round(float(res['report'].get('travel_over_finished_mm', res['report'].get('travel_over_finished', 0)) or 0), 1) if isinstance(res['report'], dict) else None,
        secs=dict(plan=round(t1 - t0), comb=round(t2 - t1), sim=round(t3 - t2)))
    cv2.imwrite(os.path.join(outdir, tag + '_sim.png'), to8(disc_mask_img(sim, 0.06)))
    cv2.imwrite(os.path.join(outdir, tag + '_plan.png'), plan_image(info, plan))
    cv2.imwrite(os.path.join(outdir, tag + '_side.png'), sheet(
        [to8(disc_mask_img(info['src'], 1.0)), to8(disc_mask_img(sim, 0.06)), plan_image(info, plan)], ['photo (gray)', 'sim %s' % tag, 'sections']))
    np.save(os.path.join(outdir, tag + '_path.npy'), path)
    json.dump(rep, open(os.path.join(outdir, tag + '_report.json'), 'w'), indent=1, default=str)
    if not quiet: print(tag, rep['score_vs_photo'], 'sections', rep['sections'], 'min', rep['minutes'], rep['secs'])
    return rep, sim, info

BASE = dict(cell=7, merge=0.05, wmin=8, amin=40, lo_sp=1.2, features=False)
SWEEP = [('base', {}),
    ('coarse_sections', dict(cell=12, merge=0.08, wmin=12, amin=100)), ('fine_sections', dict(cell=5, merge=0.04, wmin=6.5, amin=25)),
    ('merge03', dict(merge=0.03)), ('merge09', dict(merge=0.09)),
    ('shrink03', dict(shrink=0.3)), ('shrink10', dict(shrink=1.0)), ('shrink16', dict(shrink=1.6)),
    ('ord_dark', dict(order='dark_first')), ('ord_light', dict(order='light_first')), ('ord_subject', dict(order='subject_first')),
    ('ord_greedy', dict(order='greedy')), ('ord_centre', dict(order='center_out')),
    ('lo06', dict(lo_sp=0.6)), ('lo18', dict(lo_sp=1.8)), ('noempty', dict(empty=False)),
    ('curve06', dict(curve=0.6)), ('curve16', dict(curve=1.6)),
    ('bg00', dict(bg_tone=0.0)), ('bg50', dict(bg_tone=0.5)), ('bg80', dict(bg_tone=0.8)),
    ('beta0', dict(dir_beta=0.0)), ('beta1', dict(dir_beta=1.0)), ('sigt8', dict(sigma_t=8.0)),
    ('bg_angle0', dict(bg_mode=0)), ('bg_angle90', dict(bg_mode=90)),
    ('features', dict(features=True)), ('feat_low', dict(features=True, feat_thr=0.06)),
    ('lc0', dict(lc=0.0)), ('lc08', dict(lc=0.8))]

BASE2 = dict(BASE, bg_tone=0.8, dir_beta=1.0, shrink=1.0)
SWEEP2 = [('r2_base', {}), ('r2_coarse', dict(cell=12, merge=0.08, wmin=12, amin=100)), ('r2_sigt8', dict(sigma_t=8.0)),
    ('r2_features', dict(features=True)), ('r2_ord_subject', dict(order='subject_first')), ('r2_ord_dark', dict(order='dark_first')),
    ('r2_bg95', dict(bg_tone=0.95)), ('r2_bg65', dict(bg_tone=0.65)), ('r2_lo06', dict(lo_sp=0.6)), ('r2_lc06', dict(lc=0.6)),
    ('r2_merge07', dict(merge=0.07)), ('r2_cell9', dict(cell=9, merge=0.06, wmin=10, amin=60)), ('r2_bgang0', dict(bg_mode=0))]

BASE3 = dict(BASE2, cell=12, merge=0.08, wmin=12, amin=100, sigma_t=8.0, lc=0.6)
SWEEP3 = [('r3_base', {}), ('r3_merge10', dict(merge=0.10)), ('r3_lo09', dict(lo_sp=0.9)), ('r3_light_first', dict(order='light_first')),
    ('r3_center_out', dict(order='center_out')), ('r3_big', dict(cell=14, wmin=16, amin=150)), ('r3_features', dict(features=True)),
    ('r3_bg90', dict(bg_tone=0.9)), ('r3_beta07', dict(dir_beta=0.7)), ('r3_shrink07', dict(shrink=0.7))]

SWEEP4 = [('r4_base', {}), ('r4_bg100', dict(bg_tone=1.0)), ('r4_bg60', dict(bg_tone=0.6)), ('r4_features', dict(features=True)),
    ('r4_cell9', dict(cell=9, merge=0.06, wmin=10, amin=60)), ('r4_merge05', dict(merge=0.05)), ('r4_lc03', dict(lc=0.3)),
    ('r4_curve07', dict(curve=0.7)), ('r4_curve14', dict(curve=1.4)), ('r4_lo09', dict(lo_sp=0.9)), ('r4_shrink06', dict(shrink=0.6)),
    ('r4_light_first', dict(order='light_first')), ('r4_dark_first', dict(order='dark_first')), ('r4_beta05', dict(dir_beta=0.5)),
    ('r4_nobg_vig', dict(bg_tone=1.0, features=True))]

BASE5 = dict(BASE3, bg_tone=1.0)
SWEEP5 = [('r5_base', {}), ('r5_features', dict(features=True)), ('r5_cell9', dict(cell=9, merge=0.06, wmin=10, amin=60)),
    ('r5_cell7', dict(cell=7, merge=0.05, wmin=8, amin=40)), ('r5_curve07', dict(curve=0.7)), ('r5_curve05', dict(curve=0.5)),
    ('r5_lc03', dict(lc=0.3)), ('r5_lo09', dict(lo_sp=0.9)), ('r5_shrink06', dict(shrink=0.6)), ('r5_beta07', dict(dir_beta=0.7)),
    ('r5_light_first', dict(order='light_first')), ('r5_dark_first', dict(order='dark_first')), ('r5_sigt4', dict(sigma_t=4.0)),
    ('r5_c07_feat', dict(curve=0.7, features=True)), ('r5_merge05', dict(merge=0.05)), ('r5_lo18', dict(lo_sp=1.8))]

BASE6 = dict(BASE5, shrink=0.6, dir_beta=0.7, order='light_first', sigma_t=4.0)
FINE = dict(cell=7, merge=0.05, wmin=8, amin=40)
SWEEP6 = [('r6_a', {}), ('r6_cell7', FINE), ('r6_cell6', dict(cell=6, merge=0.04, wmin=7, amin=30)), ('r6_feat', dict(features=True)),
    ('r6_cell7_feat', dict(FINE, features=True)), ('r6_cell7_featlow', dict(FINE, features=True, feat_thr=0.06)), ('r6_c05', dict(curve=0.5)),
    ('r6_cell7_c07', dict(FINE, curve=0.7)), ('r6_cell7_lo06', dict(FINE, lo_sp=0.6))]

def sweep(sub, names=None, base=None, tag='sw', px=None, table=None):
    table = table or SWEEP
    base = dict(BASE, **(base or {})); rows = []
    fn = os.path.join(OUT, 'sweep_%s_%s.json' % (sub, tag))
    if os.path.exists(fn): rows = json.load(open(fn))
    done = {r['name'] for r in rows}
    for name, ov in table:
        if (names and name not in names) or name in done: continue
        try:
            rep, _, _ = run_variant(sub, dict(base, **ov, tag=name), px=px, quiet=True)
            rows.append(dict(name=name, over=ov, **rep['score_vs_photo'], minutes=rep['minutes'], sections=rep['sections'], secs=rep['secs']))
        except Exception as e:
            rows.append(dict(name=name, over=ov, error=repr(e)))
        print(rows[-1], flush=True)
        json.dump(rows, open(fn, 'w'), indent=1)
    return rows

def final(sub, over, px=0.1):
    outdir = os.path.join(OUT, sub); os.makedirs(outdir, exist_ok=True)
    rep, sim, info = run_variant(sub, dict(over, tag=over.get('tag', 'final')), outdir=outdir, px=px)
    ims = [to8(disc_mask_img(info['src'], 1.0)), to8(disc_mask_img(sim, 0.06))]
    lb = ['photo (gray)', 'sim, 0.1 mm/px']
    g = os.path.join(ROOT, 'captures/relief-study/v2/%s_gallery_mini.png' % sub)
    if os.path.exists(g):
        gi = cv2.imread(g, 0); h = gi.shape[0] // 2; c = gi.shape[0] // 2; k = int(round(h * 118.0 / 120.5))
        gi = gi[c - k:c + k, c - k:c + k]
        ims.append(gi); lb.append('current gallery drawing (line art, sim)')
    cv2.imwrite(os.path.join(outdir, '%s_%s_compare.png' % (sub, over.get('tag', 'final'))), sheet(ims, lb, 620))
    print(json.dumps({k: rep[k] for k in ('score_vs_photo', 'minutes', 'parts', 'sections')}, default=str))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd'); ap.add_argument('sub', nargs='?'); ap.add_argument('--set', nargs='*', default=[])
    ap.add_argument('--px', type=float, default=None); ap.add_argument('--final', action='store_true'); ap.add_argument('--tag', default='v')
    a = ap.parse_args()
    over = {'tag': a.tag}
    for kv in a.set:
        k, v = kv.split('='); 
        try: v = json.loads(v)
        except Exception: pass
        over[k] = v
    if a.cmd == 'palette': palette_build(a.px or 0.1)
    elif a.cmd == 'final': final(a.sub, dict(BASE6, **over), px=a.px or 0.1)
    elif a.cmd == 'sweep6': sweep(a.sub, None, base=BASE6, tag='sw6', px=a.px, table=SWEEP6)
    elif a.cmd == 'sweep5': sweep(a.sub, None, base=BASE5, tag='sw5', px=a.px, table=SWEEP5)
    elif a.cmd == 'sweep4': sweep(a.sub, None, base=BASE3, tag='sw4', px=a.px, table=SWEEP4)
    elif a.cmd == 'sweep3': sweep(a.sub, None, base=BASE3, tag='sw3', px=a.px, table=SWEEP3)
    elif a.cmd == 'sweep2': sweep(a.sub, None, base=BASE2, tag='sw2', px=a.px, table=SWEEP2)
    elif a.cmd == 'sweep': sweep(a.sub, a.set or None, tag=a.tag if a.tag != 'v' else 'sw', px=a.px)
    elif a.cmd == 'run': run_variant(a.sub, over, finalist=a.final, px=a.px)

if __name__ == '__main__':
    main()
