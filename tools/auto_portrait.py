#!/usr/bin/env python3
"""Automatic photo -> sand portrait for the Oasis Mini (SIMULATION ONLY; photos and face data stay on this machine).

    python3 tools/auto_portrait.py lek [--v NAME] [--mouth outer|inner|lines] [--no-sim]
        -> captures/auto-portrait/<name>_<v>_p1.thr .. , <name>_<v>_plan.png

Input: captures/relief-study/faces/<name>.pkl (478 MediaPipe landmarks, face/hair/body masks, aligned grey photo).
Rules (DRAWING-LESSONS.md, measured on the real Mini): ball ~9.8 mm; closed shapes >= 16 mm or single open strokes;
likeness = clean smooth contour lines; big dark masses (hair, beard, dark clothes) = ONE combed mass whose strokes follow
the form (2.4-3.6 mm), drawn BEFORE the feature lines; background = the erased sand; travel along lines.

Pipeline: (1) contour lines from landmarks + masks, (2) combed masses (iso-distance arcs from the outer edge), (3) route:
masses first, then lines, each next line chosen for the shortest straight hop from anything already drawn; travel along
drawn lines (Dijkstra), then .thr files (<= 11,500 points each).
"""
import argparse, math, os, sys, pickle
import numpy as np, cv2
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from skimage import measure

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, ROOT + '/patterns/dog')
from relief_faces import Portrait
import sand_relief_path as rp

OUT = ROOT + '/captures/auto-portrait'
RTRAY = 114.0
RES = 0.25

# ---------------------------------------------------------------- geometry helpers
def arclen(P):
    P = np.asarray(P, float)
    return np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]

def resample(P, step, closed=False):
    P = np.asarray(P, float)
    if closed: P = np.vstack([P, P[:1]])
    d = arclen(P)
    if d[-1] < 1e-6: return P[:1]
    n = max(2, int(round(d[-1] / step)) + 1)
    t = np.linspace(0, d[-1], n)
    return np.c_[np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])]

def smooth(P, sigma=1.5, step=0.5, closed=False):
    """Gaussian smoothing along the arc (mm). Open curves keep their end points (odd reflection padding)."""
    Q = resample(P, step, closed)
    if closed: Q = Q[:-1]
    s = sigma / step
    if closed:
        return np.stack([ndi.gaussian_filter1d(Q[:, j], s, mode='wrap') for j in (0, 1)], 1)
    k = int(4 * s) + 1
    pre = 2 * Q[0] - Q[1:k + 1][::-1]; post = 2 * Q[-1] - Q[-k - 1:-1][::-1]
    R = np.vstack([pre, Q, post])
    R = np.stack([ndi.gaussian_filter1d(R[:, j], s) for j in (0, 1)], 1)
    return R[len(pre):len(pre) + len(Q)]

def length(P): return float(arclen(P)[-1])

# ---------------------------------------------------------------- landmark index sets (MediaPipe face mesh)
EYE_A_UP = [33, 246, 161, 160, 159, 158, 157, 173, 133]; EYE_A_LO = [33, 7, 163, 144, 145, 153, 154, 155, 133]
EYE_B_UP = [362, 398, 384, 385, 386, 387, 388, 466, 263]; EYE_B_LO = [362, 382, 381, 380, 374, 373, 390, 249, 263]
BROW_A = (([46, 53, 52, 65, 55]), ([70, 63, 105, 66, 107]))
BROW_B = (([276, 283, 282, 295, 285]), ([300, 293, 334, 296, 336]))
NOSE_A = [55, 193, 122, 188, 217, 126, 209, 129, 64, 98]; NOSE_B = [285, 417, 351, 412, 437, 343, 429, 358, 294, 327]
NOSE_BASE = [98, 97, 2, 326, 327]
FOLD_A = [129, 203, 206, 216, 212, 57]; FOLD_B = [358, 423, 426, 436, 432, 287]
LIP_OUT_UP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]; LIP_OUT_LO = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291]
LIP_IN_UP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308]; LIP_IN_LO = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308]
JAW = [162, 127, 234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361, 323, 454, 356, 389]
OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]


class Face:
    def __init__(self, name, zoom=0.95):
        self.name = name
        self.P = Portrait('%s/captures/relief-study/faces/%s.pkl' % (ROOT, name), zoom=zoom)
        P = self.P; self.cv = P.cv; self.N = P.cv.N
        self.L = P.landmarks()
        self.meas = P.c['meas']
        self.gray = np.clip(P.gray(), 0, 255).astype(np.float32)
        L = self.L
        self.fw = float(np.hypot(*(L[454] - L[234])))
        self.cx = float((L[454, 0] + L[234, 0]) / 2)
        self.chin = L[152].copy()
        self.mouth_open_mm = float(np.hypot(*(L[13] - L[14])))
        self.mouth_w_mm = float(np.hypot(*(L[61] - L[291])))

    # grid <-> mm
    def to_px(self, P):
        P = np.asarray(P, float); N = self.N
        return np.c_[(P[:, 0] + (N - 1) * RES / 2) / RES, ((N - 1) * RES / 2 - P[:, 1]) / RES]
    def to_mm(self, rc):
        N = self.N; rc = np.asarray(rc, float)
        return np.c_[rc[:, 1] * RES - (N - 1) * RES / 2, (N - 1) * RES / 2 - rc[:, 0] * RES]
    def poly_mask(self, P):
        m = np.zeros((self.N, self.N), np.uint8)
        cv2.fillPoly(m, [np.round(self.to_px(P)).astype(np.int32)], 1); return m > 0
    def lm(self, idx): return self.L[idx]

    def blur_mask(self, m, sigma_mm):
        k = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma_mm / RES)
        return k > 0.5

# ---------------------------------------------------------------- masses (hair, beard, clothes) as one combed mass
def edt_mm(m): return ndi.distance_transform_edt(m) * RES

def comb_mass(F, M, inner_ref, spacing=3.2, first=1.4, erode=1.2, step=2.4, min_piece=6.0, sp_fn=None, outer_far=3.0):
    """Strokes follow the form: iso-distance arcs from the mass's outer edge (the edge that is not next to skin), cut to the
    mass, traversed back and forth. Returns (polyline, list of arcs)."""
    M = F.blur_mask(M, 1.2)
    lab, n = ndi.label(M)
    if n > 1:
        sizes = ndi.sum(M, lab, range(1, n + 1)); keep = [i + 1 for i, s in enumerate(sizes) if s > 0.15 * sizes.max()]
        M = np.isin(lab, keep)
    er = cv2.erode(M.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * erode / RES) | 1,) * 2)) > 0
    edge = M & ~ndi.binary_erosion(M)
    far = edt_mm(~inner_ref) > outer_far
    ob = edge & far
    if ob.sum() < 20: return [], []
    f = edt_mm(~ob)
    arcs = []; c = first; k = 0
    fmax = f[M].max()
    while c < fmax:
        cs = measure.find_contours(f, c)
        pieces = []
        for q in cs:
            rr = np.clip(np.round(q[:, 0]).astype(int), 0, F.N - 1); cc = np.clip(np.round(q[:, 1]).astype(int), 0, F.N - 1)
            ins = er[rr, cc]
            i = 0
            while i < len(q):
                if ins[i]:
                    j = i
                    while j + 1 < len(q) and ins[j + 1]: j += 1
                    seg = F.to_mm(q[i:j + 1])
                    if len(seg) > 3 and length(seg) > min_piece:
                        pieces.append(smooth(seg, 1.0, 0.5))
                    i = j + 1
                else: i += 1
        arcs.append((k, c, pieces))
        sp = sp_fn(c / max(fmax, 1e-6)) if sp_fn else spacing
        c += sp; k += 1
    # chain pieces level by level, alternating direction naturally by nearest end
    path = []; cur = None
    for k, c, pieces in arcs:
        left = list(pieces)
        while left:
            if cur is None:
                p = max(left, key=length); left = [q for q in left if q is not p]
            else:
                best = None
                for p in left:
                    for rev in (False, True):
                        s = p[-1] if rev else p[0]; d = np.hypot(*(s - cur))
                        if best is None or d < best[0]: best = (d, p, rev)
                _, p, rev = best; left = [q for q in left if q is not p]
                if rev: p = p[::-1]
            p = resample(p, step); path.extend(map(tuple, p)); cur = p[-1]
    return path, [p for _, _, ps in arcs for p in ps]

# ---------------------------------------------------------------- masks from the photo
def skin_ref(F):
    return F.blur_mask(F.P.mask('face'), 0.8)

def hair_mask(F):
    H = F.P.mask('hair') & ~F.P.mask('face')
    return F.blur_mask(H, 2.0)

def beard_mask(F, thr=0.62, a_open=8.0):
    """dark region of the lower face (below the nose), from the photo; moustache included, lips excluded."""
    L = F.L
    oval = F.poly_mask(L[OVAL])
    N = F.N; yy = F.cv.Y
    below = yy < (L[2, 1] - 3.0)
    skin_pts = np.vstack([L[[50, 101, 118]], L[[280, 330, 347]]])
    px = np.round(F.to_px(skin_pts)).astype(int)
    skin = np.median(F.gray[px[:, 1], px[:, 0]])
    g = cv2.GaussianBlur(F.gray, (0, 0), 1.5 / RES)
    m = oval & below & (g < thr * skin)
    lips = F.poly_mask(np.vstack([L[LIP_OUT_UP], L[LIP_OUT_LO][::-1]]))
    lips = cv2.dilate(lips.astype(np.uint8), np.ones((int(2.0 / RES) | 1,) * 2, np.uint8)) > 0
    m &= ~lips
    m = ndi.binary_fill_holes(cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((int(4 / RES) | 1,) * 2, np.uint8)) > 0) & ~lips
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((int(a_open / RES) | 1,) * 2, np.uint8)) > 0
    if F.meas['beard'].get('used') == 'goatee':          # a goatee: a patch under the lower lip, about 0.6 mouth widths wide
        m = (F.cv.Y < F.L[17, 1] - 2.0) & oval & ~lips & (np.abs(F.cv.X - F.L[17, 0]) < 0.30 * F.mouth_w_mm)
    lab, n = ndi.label(m)
    if n == 0: return None, lips
    sizes = ndi.sum(m, lab, range(1, n + 1)); m = lab == (1 + int(np.argmax(sizes)))
    area = m.sum() * RES * RES
    return (m if area > 250 else None), lips

# ---------------------------------------------------------------- the lines
def L_(F, idx, sigma=1.6, closed=False): return smooth(F.lm(idx), sigma, 0.5, closed)

def eye_lines(F, up, lo, sigma=1.4, lo_trim=0.12, lo_drop=0.6, heavy=0.0, wing=0.0):
    u = smooth(F.lm(up), sigma, 0.5)
    if wing > 0:                                   # follow the lash line past the outer corner with a slight upward flick
        io = 0 if abs(u[0, 0] - F.cx) > abs(u[-1, 0] - F.cx) else -1
        d = u[io] - u[3 * (1 if io == 0 else -1) + io] if io == 0 else u[io] - u[io - 3]
        d = d / max(np.hypot(*d), 1e-9); tip = u[io] + wing * d + [0, 0.35 * wing]
        ext = np.array([u[io], u[io] + 0.5 * wing * d + [0, 0.1 * wing], tip])
        u = np.vstack([tip[None], ext[1:2], u]) if io == 0 else np.vstack([u, ext[1:2], tip[None]])
        u = smooth(u, 0.9, 0.5)
    l = smooth(F.lm(lo), sigma, 0.5)
    n = len(l); a, b = int(lo_trim * n), int(n * (1 - lo_trim))
    l = l[a:b] + [0, -lo_drop]
    if heavy: u = np.vstack([u, (u + [0, heavy])[::-1]])       # second pass back along the lid: a heavier lash line
    return u, l

def brow_line(F, pair, sigma=1.6):
    lo = F.lm(pair[0]); up = F.lm(pair[1]); mid = (lo + up) / 2
    if mid[0, 0] > mid[-1, 0]: mid = mid[::-1]
    return smooth(mid, sigma, 0.5)

def mouth_lines(F, mode):
    L = F.L
    smile_open = F.mouth_open_mm > 5.0
    out = []
    if mode == 'outer' and smile_open:
        loop = np.vstack([L[LIP_OUT_UP], L[LIP_OUT_LO][::-1][1:-1]])
        out.append(('mouth', smooth(loop, 1.2, 0.5, closed=True), True))
    elif mode == 'inner' and smile_open:
        loop = np.vstack([L[LIP_IN_UP], L[LIP_IN_LO][::-1][1:-1]])
        out.append(('mouth', smooth(loop, 1.0, 0.5, closed=True), True))
    else:
        mid = (L[LIP_IN_UP] + L[LIP_IN_LO]) / 2 if not smile_open else L[LIP_OUT_UP]
        out.append(('lipline', smooth(mid, 1.4, 0.5), False))
        lo = L[LIP_OUT_LO][2:-2] + [0, -1.0]
        if mode == 'lines':
            out.append(('lowerlip', smooth(L[LIP_OUT_LO] + [0, -1.0], 1.4, 0.5), False))
    return out

def ear_lines(F, side):
    L = F.L; fw = F.fw
    if side == 'L': ref, sgn, top_i, bot_i = 234, -1, 70, 2
    else: ref, sgn, top_i, bot_i = 454, 1, 300, 2
    ytop = L[top_i, 1] - 1.0; ybot = L[bot_i, 1] + 1.0
    # face x at those heights: take the oval's x near the ear heights
    oval = L[JAW];
    def xat(y):
        d = np.abs(oval[:, 1] - y); w = np.exp(-(d / 4.0) ** 2) * (np.sign(oval[:, 0] - F.cx) == sgn)
        return float((oval[:, 0] * w).sum() / max(w.sum(), 1e-6)) if w.sum() > 1e-6 else L[ref, 0]
    xa, xb = xat(ytop), xat(ybot)
    out = 0.10 * fw
    pts = [(xa, ytop), (xa + sgn * out * 0.75, ytop - 0.12 * (ytop - ybot)), (xa + sgn * out * 1.15, (ytop + ybot) / 2 + 3),
           (xb + sgn * out * 0.7, ybot + 2), (xb, ybot)]
    return smooth(np.array(pts), 1.8, 0.5)

def neck_lines(F, jaw):
    fw, cx, yc = F.fw, F.cx, F.chin[1]
    out = []
    for sgn in (-1, 1):
        x0 = cx + sgn * 0.33 * fw
        d = np.hypot(*(jaw - np.array([x0, yc + 0.15 * fw])).T); s = jaw[int(np.argmin(d))]
        pts = [s, (x0 + sgn * 0.01 * fw, yc - 0.10 * fw), (cx + sgn * 0.52 * fw, yc - 0.17 * fw), (cx + sgn * 0.85 * fw, yc - 0.21 * fw),
               (cx + sgn * 1.25 * fw, yc - 0.34 * fw)]
        p = smooth(np.array(pts), 2.5, 0.5)
        r = np.hypot(*p.T); k = np.nonzero(r > 108)[0]
        if len(k): p = p[:k[0]]
        out.append(p)
    return out

# ---------------------------------------------------------------- router
def route(items, tiers, start=(0.0, 0.0), step=1.0, end_to=None):
    """items: name -> dict(path, closed, fixed). tiers: list of lists of name prefixes, drawn in that order; inside a tier the
    next item is the one with the shortest straight hop from anything already drawn (travel along drawn lines, Dijkstra).
    'nose' first and the brow nearest the hair start give the walk from the table centre something useful to follow."""
    path = [tuple(start)]; hops = []; drawn = []; cur = np.asarray(start, float)
    todo = dict(items)
    hair_start = np.asarray(items['hair0']['path'][0], float) if 'hair0' in items else None
    for tier in tiers:
        cnt = 0
        lim = 1 if tier == ['brow*'] or tier == ['nose'] or tier == ['neck*#1'] else 999
        tier = ['neck*'] if tier == ['neck*#1'] else tier
        while cnt < lim:
            cnt += 1
            names = [n for n in todo if any(n == t or (t.endswith('*') and n.startswith(t[:-1])) for t in tier)]
            if not names: break
            pts = np.vstack([resample(d, step) for d in drawn]) if drawn else cur[None, :]
            tree = cKDTree(pts); best = None
            for n in names:
                p = np.asarray(todo[n]['path'], float)
                if todo[n]['closed']: cands = [np.vstack([p[k:], p[:k + 1]]) for k in range(0, len(p), 6)]
                elif todo[n].get('fixed'): cands = [p]
                else: cands = [p, p[::-1]]
                for pp in cands:
                    d, jn = tree.query(pp[0]); cost = d
                    if n.startswith('brow') and hair_start is not None and tier == ['brow*']: cost = d + np.hypot(*(pp[-1] - hair_start))
                    if best is None or cost < best[0]: best = (cost, n, pp, jn, d)
            _, n, pp, jn, d = best; todo.pop(n)
            if drawn: path.extend(shortest_path(drawn, cur, pts[jn], step))
            if d > 0.3: path.append(tuple(pp[0]))
            hops.append((n, round(float(d), 1)))
            if drawn and d > 0.3: drawn.append(np.array([pts[jn], pp[0]]))
            elif not drawn: drawn.append(np.array([cur, pp[0]]) if d > 0.3 else np.array([pp[0], pp[0]]))
            path.extend(map(tuple, pp)); drawn.append(pp); cur = np.asarray(pp[-1])
    if end_to is not None and drawn:                  # park the ball off the face: travel along drawn lines to the rim
        path.extend(shortest_path(drawn, cur, np.asarray(end_to, float), step)); path.append(tuple(np.asarray(end_to, float) / np.hypot(*end_to) * 113.0))
    return np.asarray(path), hops

def shortest_path(drawn, a, b, step):
    segs = [resample(d, step) for d in drawn]
    pts = np.vstack(segs); idx = np.cumsum([0] + [len(s) for s in segs])
    rows, cols, w = [], [], []
    for k, s in enumerate(segs):
        for i in range(len(s) - 1):
            u, v = idx[k] + i, idx[k] + i + 1; d = np.hypot(*(s[i + 1] - s[i]))
            rows += [u, v]; cols += [v, u]; w += [d, d]
    tree = cKDTree(pts)
    for u, v in tree.query_pairs(1.5):
        rows += [u, v]; cols += [v, u]; w += [1.0, 1.0]
    G = coo_matrix((w, (rows, cols)), shape=(len(pts), len(pts))).tocsr()
    ia = int(tree.query(a)[1]); ib = int(tree.query(b)[1])
    if ia == ib: return [tuple(b)]
    dist, pred = dijkstra(G, indices=ia, return_predecessors=True)
    if not np.isfinite(dist[ib]): return [tuple(b)]
    seq = [ib]
    while seq[-1] != ia: seq.append(pred[seq[-1]])
    return [tuple(pts[q]) for q in seq[::-1]]

# ---------------------------------------------------------------- round 2 additions
def patch_mean(F, c, r=3.0):
    m = (F.cv.X - c[0]) ** 2 + (F.cv.Y - c[1]) ** 2 < r * r
    return float(F.gray[m].mean())

def normals(p):
    t = np.gradient(p, axis=0); t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
    return np.c_[-t[:, 1], t[:, 0]]

def band(p, n=3, sp=1.6, up=True):
    """n close parallel passes (sp mm apart) joined serpentine: a bold band. up=True: offsets on the +y side only, else centred."""
    nn = normals(p); nn = np.where(nn[:, 1:2] < 0, -nn, nn)         # normals point up the page
    offs = [k * sp for k in range(n)] if up else [(k - (n - 1) / 2) * sp for k in range(n)]
    out = []
    for k, o in enumerate(offs):
        q = p + o * nn; out.append(q if k % 2 == 0 else q[::-1])
    return np.vstack(out)

def iris_spiral(c, r=4.2, pitch=1.9, step=1.0):
    """tight spiral from the rim of the iris to its centre (a dark blob is what we want)"""
    pts = []; th = 0.0; rr = r
    while rr > 0.3:
        pts.append((c[0] + rr * math.cos(th), c[1] + rr * math.sin(th)))
        dth = step / max(rr, 1.0); th += dth; rr -= pitch * dth / (2 * math.pi)
    return np.array(pts)

def eye_lid_dot(F, u, ic, r, pitch, n=1, sp=2.4):
    """Eye = ONE upper-lid stroke with the dark iris dot made on the way: at the iris x the ball turns into a tight spiral hanging
    under the lid, winds to the centre, and unwinds the same groove back to the lid (no spur). n=2 adds a second, wider lid pass."""
    k = int(np.argmin(np.abs(u[:, 0] - ic[0]))); p = u[k]
    c = p - [0, 0.95 * r]; pts = []; th = math.pi / 2; rr = r
    while rr > 0.3:
        pts.append((c[0] + rr * math.cos(th), c[1] + rr * math.sin(th))); dth = 1.0 / max(rr, 1.0); th += dth; rr -= pitch * dth / (2 * math.pi)
    sp_in = np.array(pts)
    a = np.vstack([u[:k + 1], sp_in, sp_in[::-1][1:], u[k + 1:]])
    if n > 1:
        b = u + sp * np.where(normals(u)[:, 1:2] < 0, -1, 1) * normals(u)
        a = np.vstack([a, b[::-1]])
    return a

def goatee_strokes(F, M, jaw, sp=3.0, first=2.2):
    """A goatee as a few strokes parallel to the chin line (offsets of the jaw going up), clipped to the dark patch, no outline."""
    Mb = F.blur_mask(M, 1.0)
    xs = np.nonzero(Mb.any(0))[0]; xc = F.to_mm(np.array([[0, xs.min()], [0, xs.max()]], float))[:, 0]
    seg = jaw[(jaw[:, 0] > xc[0] - 2) & (jaw[:, 0] < xc[1] + 2) & (jaw[:, 1] < F.L[17, 1] + 6)]
    if len(seg) < 4: return []
    seg = resample(seg, 0.5); nn = normals(seg); nn = np.where(nn[:, 1:2] < 0, -nn, nn)
    out = []; k = 0; d = first
    while d < 40:
        q = seg + d * nn; rc = np.round(F.to_px(q)).astype(int)
        ok = (rc[:, 0] >= 0) & (rc[:, 0] < F.N) & (rc[:, 1] >= 0) & (rc[:, 1] < F.N)
        ins = np.zeros(len(q), bool); ins[ok] = Mb[rc[ok, 1], rc[ok, 0]]
        idx = np.nonzero(ins)[0]
        if len(idx) < 8:
            if d > first + 6: break
            d += sp; continue
        q = q[idx[0]:idx[-1] + 1]; out.append(q if k % 2 == 0 else q[::-1]); k += 1; d += sp
    return np.vstack(out) if out else []

def shirt_mask(F, thr=0.5):
    L = F.L
    skin_pts = np.vstack([L[[50, 101, 118]], L[[280, 330, 347]]]); px = np.round(F.to_px(skin_pts)).astype(int)
    skin = np.median(F.gray[px[:, 1], px[:, 0]])
    g = cv2.GaussianBlur(F.gray, (0, 0), 1.0 / RES)
    X, Y = F.cv.X, F.cv.Y
    m = (Y < F.chin[1] - 5.0) & (X ** 2 + Y ** 2 < 106 ** 2) & (g < thr * skin)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((int(6 / RES) | 1,) * 2, np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((int(6 / RES) | 1,) * 2, np.uint8)) > 0
    m = ndi.binary_fill_holes(m)
    lab, n = ndi.label(m)
    if n == 0: return None
    sizes = ndi.sum(m, lab, range(1, n + 1)); m = lab == (1 + int(np.argmax(sizes)))
    return m if m.sum() * RES * RES > 1000 else None

def hair_hairline(F, H):
    """Smooth hairline from landmarks: the face-oval top lifted (or lowered) so its centre meets the hair mask's lower edge there,
    fading to the temples. Returns (polyline left->right, mask of everything below the curve inside the face span)."""
    L = F.L; top = L[[162, 21, 54, 103, 67, 109, 10, 338, 297, 332, 284, 251, 389]]
    x10, y10 = L[10]
    cols = np.nonzero(np.abs(F.cv.X[0] - x10) < 8)[0]
    ys = []
    for c in cols:
        col = H[:, c]; r = np.nonzero(col)[0]
        rr = r[F.cv.Y[r, 0] > y10 - 25]
        if len(rr):
            k = rr.max()          # lowest hair row of the topmost run
            run = k
            while run + 1 < F.N and H[run + 1, c]: run += 1
            if F.cv.Y[run, 0] > y10 - 25: ys.append(F.cv.Y[run, 0])
    yh = float(np.median(ys)) if ys else y10 + 8
    delta = float(np.clip(yh - y10, -4, 30))
    w = np.cos(np.clip((top[:, 0] - F.cx) / (0.5 * F.fw), -1, 1) * np.pi / 2) * 0.65 + 0.35
    cur = top + np.c_[np.zeros(len(top)), delta * w]
    cur = smooth(cur, 3.0, 0.5)
    return cur

def comb_flow(F, M, inner_ref, photo_w=0.4, sep=3.4, first=1.4, erode=1.2, step=0.6, min_len=10.0):
    """Hair as streamlines of a flow field = outline tangent blended with the photo's own strand direction (structure
    tensor of the grey picture inside the hair mask); evenly spaced; chained back and forth, outer strokes first."""
    M = F.blur_mask(M, 1.2)
    lab, n = ndi.label(M)
    if n > 1:
        sizes = ndi.sum(M, lab, range(1, n + 1)); M = np.isin(lab, [i + 1 for i, q in enumerate(sizes) if q > 0.15 * sizes.max()])
    er = cv2.erode(M.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * erode / RES) | 1,) * 2)) > 0
    edge = M & ~ndi.binary_erosion(M); ob = edge & (edt_mm(~inner_ref) > 3.0)
    if ob.sum() < 20: return [], []
    f = edt_mm(~ob); fs = cv2.GaussianBlur(f.astype(np.float32), (0, 0), 3.0 / RES)
    gy, gx = np.gradient(fs); gn = np.maximum(np.hypot(gx, gy), 1e-6); tx, ty = -gy / gn, gx / gn      # outline tangent
    gr = cv2.GaussianBlur(F.gray, (0, 0), 0.8 / RES); sy, sx = np.gradient(gr)
    win = 3.0 / RES
    jxx = cv2.GaussianBlur(sx * sx, (0, 0), win); jyy = cv2.GaussianBlur(sy * sy, (0, 0), win); jxy = cv2.GaussianBlur(sx * sy, (0, 0), win)
    tr = np.maximum(jxx + jyy, 1e-6); coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / tr
    ang = 0.5 * np.arctan2(2 * jxy, jxx - jyy)                       # gradient direction (image axes)
    px_, py_ = -np.sin(ang), np.cos(ang)                              # perpendicular = along strands (image axes)
    wph = photo_w * coh
    Sxx = wph * px_ ** 2 + (1 - wph) * tx ** 2; Syy = wph * py_ ** 2 + (1 - wph) * ty ** 2; Sxy = wph * px_ * py_ + (1 - wph) * tx * ty
    th = 0.5 * np.arctan2(2 * Sxy, Sxx - Syy); vx, vy = np.cos(th), np.sin(th)     # image axes (rows down, so gy->-y later)
    vy = -vy                                                           # to mm axes (y up)
    taken = np.zeros(M.shape, np.uint8)
    ys, xs = np.nonzero(er); order = np.lexsort((xs, np.round(f[ys, xs] / 1.0))); ys, xs = ys[order][::3], xs[order][::3]
    strands = []
    def at(p):
        q = F.to_px(p[None])[0]; return int(round(q[1])), int(round(q[0]))
    def trace(p0, sgn):
        pts = [p0]; d = None
        for _ in range(2500):
            r, c = at(pts[-1])
            if not (0 <= r < F.N and 0 <= c < F.N): break
            v = np.array([vx[r, c], vy[r, c]])
            if d is None: v = v * sgn
            elif np.dot(v, d) < 0: v = -v
            nxt = pts[-1] + step * v; r2, c2 = at(nxt)
            if not (0 <= r2 < F.N and 0 <= c2 < F.N) or not er[r2, c2] or taken[r2, c2]: break
            pts.append(nxt); d = v
        return pts
    for r, c in zip(ys, xs):
        if taken[r, c] or not er[r, c]: continue
        p0 = F.to_mm(np.array([[r, c]], float))[0]
        a = trace(p0, 1); b = trace(p0, -1)
        line = np.array(b[::-1] + a[1:])
        if len(line) < 3 or length(line) < min_len: continue
        line = smooth(line, 1.2, 0.5); strands.append((float(np.mean(f[np.clip(np.round(F.to_px(line)[:, 1]).astype(int), 0, F.N - 1), np.clip(np.round(F.to_px(line)[:, 0]).astype(int), 0, F.N - 1)])), line))
        pxl = np.round(F.to_px(line)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(taken, [pxl], False, 1, int(max(1, round(0.85 * sep / RES))))
    strands.sort(key=lambda t: t[0])
    left = [l for _, l in strands]; fl = [q for q, _ in strands]; chains = [[]]; cur = None; fcur = 0.0
    while left:
        if cur is None: k, rev = 0, False
        else:
            best = None
            for i, l in enumerate(left):
                for rev in (False, True):
                    d = np.hypot(*((l[-1] if rev else l[0]) - cur)) + 1.5 * abs(fl[i] - fcur)
                    if best is None or d < best[0]: best = (d, i, rev)
            d, k, rev = best
            if d > 9.0: chains.append([])                      # too far to join inside the mass: a separate stroke group
        l = left.pop(k); fcur = fl.pop(k); l = l[::-1] if rev else l
        l = resample(l, 2.4); chains[-1].extend(map(tuple, l)); cur = l[-1]
    return [c for c in chains if len(c) > 2], [l for _, l in strands]

# ---------------------------------------------------------------- build
def build(name, v, a):
    F = Face(name, zoom=a.zoom)
    L = F.L; meas = F.meas
    skin = skin_ref(F); H = hair_mask(F)
    hl_curve = hair_hairline(F, H)
    # cut hair that hangs below the smooth hairline inside the face span (fringe) so the forehead is clean
    cut = F.poly_mask(np.vstack([hl_curve, [hl_curve[-1, 0], -150], [hl_curve[0, 0], -150]]))
    H2 = H & ~cut
    hchains = None
    if a.flow: hchains, harcs = comb_flow(F, H2, skin, photo_w=a.photo_w, sep=a.hair_sp, first=a.first)
    else: hp, harcs = comb_mass(F, H2, skin, spacing=a.hair_sp, first=a.first, sp_fn=lambda t: a.hair_sp - 0.8 * t)
    bp = []; beard = None
    bm, lips = beard_mask(F, a.beard_thr, a.beard_open)
    if bm is not None and not a.no_beard:
        ref = skin & ~F.blur_mask(bm, 1.0)
        bp, _ = comb_mass(F, bm, ref, spacing=a.beard_sp, first=1.2, outer_far=2.0); beard = bm
    sp_, sm = [], None
    sm = None if a.no_shirt else shirt_mask(F, a.shirt_thr)
    if sm is not None and F.meas['features'].get('glasses', {}) is not None:
        disc = F.cv.X ** 2 + F.cv.Y ** 2 < 104 ** 2
        sp_, _ = comb_mass(F, sm, ~disc, spacing=a.shirt_sp, first=1.4, outer_far=3.0)
    lines = []
    if beard is not None and F.meas['beard'].get('used') == 'goatee' and a.goatee_strokes:
        bp = goatee_strokes(F, beard, smooth(L[JAW], 2.0, 0.5), a.goatee_sp)      # strokes along the chin, no outline
    elif beard is not None and F.meas['beard'].get('used') == 'goatee':
        cs, _ = cv2.findContours(F.blur_mask(beard, 1.0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        c = max(cs, key=len)[:, 0, :].astype(float); bo = smooth(F.to_mm(c[:, ::-1]), 1.6, 0.5, closed=True)
        lines.append(('beardline', bo, True)); lines.append(('beardline2', ring_off(bo, -1.6), True))
        mu = smooth(L[LIP_OUT_UP] + [0, 2.0], 1.4, 0.5); lines.append(('mous', band(mu, 2, 1.6), False))
    jaw = smooth(L[JAW], 2.0, 0.5)
    ic = int(np.argmin(np.abs(jaw[:, 0] - F.chin[0]) + 3 * (jaw[:, 1] - jaw[:, 1].min())))
    HL = [hl_curve]
    ends = [q for p in HL for q in (p[0], p[-1])]
    necks = neck_lines(F, jaw)
    kL = int(np.argmin(np.hypot(*(jaw[:ic + 1] - necks[0][0]).T))); kR = ic + int(np.argmin(np.hypot(*(jaw[ic:] - necks[1][0]).T)))
    def extend(j):
        e = j[0]; k = int(np.argmin([np.hypot(*(q - e)) for q in ends])); h = ends[k]
        if np.hypot(*(h - e)) > 45 or np.hypot(*(h - e)) < 1.5: return j
        d = h - e; n = np.array([d[1], -d[0]]) / np.hypot(*d); n = n if np.dot(n, e - np.array([F.cx, e[1]])) > 0 else -n
        return np.vstack([smooth(np.array([h, (e + h) / 2 + 1.5 * n, e]), 1.5, 0.5), j[1:]])
    pieces = [extend(jaw[:kL + 1]), jaw[kL:ic + 1], jaw[ic:kR + 1], extend(jaw[kR:][::-1])]
    for i, p in enumerate(pieces):
        if len(p) > 3: lines.append(('jaw%d' % i, p, False))
    lines.append(('hline0', hl_curve, False))
    irises = []
    for tag, up, lo, ic_ in (('eyeA', EYE_A_UP, EYE_A_LO, 468), ('eyeB', EYE_B_UP, EYE_B_LO, 473)):
        u, l = eye_lines(F, up, lo, lo_trim=a.lo_trim, wing=a.wing)
        if a.eye4:
            lines.append((tag + 'up', eye_lid_dot(F, u, L[ic_], a.iris_r, a.iris_pitch, a.lid_n, a.lid_sp), False))
            if not a.no_lower: lines.append((tag + 'lo', l, False))
            continue
        if a.band_n > 1: u = band(u, a.band_n, a.band_sp)
        lines += [(tag + 'up', u, False), (tag + 'lo', l, False)]
        if a.iris:
            rr = float(np.hypot(*(L[ic_ + 1] - L[ic_ + 3]))) / 2
            lines.append((tag + 'iris', iris_spiral(L[ic_] + [0, a.iris_lift], r=min(max(rr, a.iris_r), 4.8), pitch=a.iris_pitch), False))
    for nm, pr in (('browA', BROW_A), ('browB', BROW_B)):
        b = brow_line(F, pr)
        lines.append((nm, band(b, a.band_n, a.band_sp, up=False) if a.band_n > 1 else b, False))
    if a.nose2:
        gA = patch_mean(F, L[217]); gB = patch_mean(F, L[437])
        side = NOSE_A if gA < gB else NOSE_B                           # the darker (shadow) side of the nose
        lines.append(('nose', smooth(L[side][1:], 1.6, 0.5), False))
        lines.append(('nosetip', smooth(L[[97, 2, 326]], 1.0, 0.5), False))
        for nm, idx in (('nostrilA', [129, 64, 98]), ('nostrilB', [358, 294, 327])):
            if (nm == 'nostrilA') != (side is NOSE_A): lines.append((nm, smooth(L[idx], 0.8, 0.5), False))
    else:
        nose = smooth(np.vstack([L[NOSE_A][2:], L[NOSE_BASE][1:-1], L[NOSE_B][2:][::-1]]), 1.6, 0.5)
        lines.append(('nose', nose, False))
    if a.folds and meas['features']['mouth']['smiling']:
        lines += [('foldA', smooth(L[FOLD_A][1:], 2.0, 0.5), False), ('foldB', smooth(L[FOLD_B][1:], 2.0, 0.5), False)]
    for n_, p_, c_ in mouth_lines(F, a.mouth):
        lines.append((n_, p_, c_))
        if a.mouth_bold and c_:
            lines.append((n_ + '2', ring_off(p_, a.mouth_bold), True))
    ev = meas['features']['ears_visible']
    if ev['left_out'] > 0.03 and not a.no_ears: lines.append(('earL', ear_lines(F, 'L'), False))
    if ev['right_out'] > 0.03 and not a.no_ears: lines.append(('earR', ear_lines(F, 'R'), False))
    for i, n in enumerate(necks): lines.append(('neck%d' % i, n, False))
    items = {n: dict(path=p, closed=c) for n, p, c in lines}
    if hchains is not None:
        for i, c in enumerate(hchains): items['hair%d' % i] = dict(path=np.asarray(c), closed=False)
    elif len(hp): items['hair0'] = dict(path=np.asarray(hp), closed=False)
    if len(bp): items['beard'] = dict(path=np.asarray(bp), closed=False)
    if len(sp_): items['shirt'] = dict(path=np.asarray(sp_), closed=False)
    if a.outward:
        nk = [p for n_, p, c_ in lines if n_ == 'neck0'][0]; e = nk[-1]; start = tuple(e / np.hypot(*e) * 113.0)
        tiers = [['shirt'], ['neck*#1'], ['jaw*'], ['neck*'], ['hair*'], ['beard'], ['*']]
    else:
        start = (0.0, 0.0)
        tiers = [['nose'], ['hair*'], ['jaw*', 'beard'], ['shirt'], ['*']]
    path, hops = route(items, tiers, start=start, end_to=necks[0][-1] if a.end_rim else None)
    return F, path, hops, dict(hair=harcs, lines=lines, beard=beard, H=H, shirt=sm)

def ring_off(loop, d):
    p = resample(loop, 0.5, True)[:-1]; t = np.roll(p, -1, 0) - np.roll(p, 1, 0); t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
    n = np.c_[t[:, 1], -t[:, 0]]; area = np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
    if area < 0: n = -n
    return p + d * n

def to_files(F, path, tag, maxpts=11000):
    tr, near = rp.to_thr_pts(path, RTRAY, tol=0.05, max_step=2.5)
    e = np.asarray(path[-1], float)                       # keep the final point (the rim parking spot) exactly
    if abs(np.hypot(*e) / RTRAY - tr[-1, 1]) > 0.003:
        th = math.atan2(e[1], e[0]); th += 2 * math.pi * round((tr[-1, 0] - th) / (2 * math.pi))
        k = int(math.ceil(abs(np.hypot(*e) / RTRAY - tr[-1, 1]) / 0.01))
        tr = np.vstack([tr] + [[tr[-1, 0] + (th - tr[-1, 0]) * i / k, tr[-1, 1] + (np.hypot(*e) / RTRAY - tr[-1, 1]) * i / k] for i in range(1, k + 1)])
    n = int(math.ceil(len(tr) / maxpts)); per = int(math.ceil(len(tr) / n)); files = []
    for k in range(n):
        fn = '%s/%s_p%d.thr' % (OUT, tag, k + 1)
        rp.write_thr(fn, tr[k * per:(k + 1) * per], title='auto portrait ' + tag); files.append(fn)
    return files, tr

def plan_png(F, path, extra, fn, size=1000):
    k = size / (2 * RTRAY)
    im = np.full((size, size, 3), 255, np.uint8)
    def px(P): return np.round(np.c_[P[:, 0] * k + size / 2, size / 2 - P[:, 1] * k]).astype(np.int32)
    cv2.polylines(im, [px(np.asarray(path)).reshape(-1, 1, 2)], False, (90, 90, 90), 1, cv2.LINE_AA)
    for n, p, c in extra['lines']:
        cv2.polylines(im, [px(p).reshape(-1, 1, 2)], c, (0, 0, 200), 1, cv2.LINE_AA)
    cv2.circle(im, (size // 2, size // 2), int(RTRAY * k), (0, 160, 0), 1)
    cv2.imwrite(fn, im)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--v', default='a')
    ap.add_argument('--zoom', type=float, default=0.95); ap.add_argument('--mouth', default='outer')
    ap.add_argument('--hair-sp', dest='hair_sp', type=float, default=3.4); ap.add_argument('--beard-sp', dest='beard_sp', type=float, default=3.0)
    ap.add_argument('--first', type=float, default=1.4); ap.add_argument('--beard-thr', dest='beard_thr', type=float, default=0.62)
    ap.add_argument('--lo-trim', dest='lo_trim', type=float, default=0.12)
    ap.add_argument('--beard-open', dest='beard_open', type=float, default=8.0); ap.add_argument('--eye-heavy', dest='eye_heavy', type=float, default=0.0); ap.add_argument('--no-beard', action='store_true'); ap.add_argument('--no-ears', action='store_true')
    ap.add_argument('--folds', action='store_true'); ap.add_argument('--hairline', action='store_true')
    ap.add_argument('--sim', action='store_true'); ap.add_argument('--flow', action='store_true'); ap.add_argument('--photo-w', dest='photo_w', type=float, default=0.4); ap.add_argument('--band-n', dest='band_n', type=int, default=1); ap.add_argument('--band-sp', dest='band_sp', type=float, default=1.6); ap.add_argument('--iris', action='store_true'); ap.add_argument('--iris-pitch', dest='iris_pitch', type=float, default=1.9); ap.add_argument('--mouth-bold', dest='mouth_bold', type=float, default=0.0); ap.add_argument('--no-shirt', dest='no_shirt', action='store_true'); ap.add_argument('--shirt-thr', dest='shirt_thr', type=float, default=0.5); ap.add_argument('--shirt-sp', dest='shirt_sp', type=float, default=3.6); ap.add_argument('--outward', action='store_true'); ap.add_argument('--end-rim', dest='end_rim', action='store_true'); ap.add_argument('--wing', type=float, default=0.0); ap.add_argument('--iris-r', dest='iris_r', type=float, default=3.2); ap.add_argument('--iris-lift', dest='iris_lift', type=float, default=0.0); ap.add_argument('--nose2', action='store_true'); ap.add_argument('--eye4', action='store_true'); ap.add_argument('--lid-n', dest='lid_n', type=int, default=1); ap.add_argument('--lid-sp', dest='lid_sp', type=float, default=2.4); ap.add_argument('--no-lower', dest='no_lower', action='store_true'); ap.add_argument('--goatee-strokes', dest='goatee_strokes', action='store_true'); ap.add_argument('--goatee-sp', dest='goatee_sp', type=float, default=3.0); ap.add_argument('--pre-brow', dest='pre_brow', action='store_true')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    F, path, hops, ex = build(a.name, a.v, a)
    tag = '%s_%s' % (a.name, a.v)
    files, tr = to_files(F, path, tag)
    plan_png(F, path, ex, '%s/%s_plan.png' % (OUT, tag))
    print('hops (mm):', hops); print('total hop %.0f mm, travel points %d' % (sum(h for _, h in hops), len(path)))
    for f in files:
        t = np.loadtxt(f, ndmin=2)
        print(os.path.basename(f), len(t), 'points', '%.1f min' % rp.mini_minutes(t))
    if a.sim:
        import subprocess
        subprocess.run([sys.executable, HERE + '/auto_sim.py', '%s/%s.png' % (OUT, tag)] + files + (['--outward'] if a.outward else []))
