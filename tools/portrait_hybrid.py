#!/usr/bin/env python3
"""Hybrid sand portraits: the gallery's clean line structure (patterns/people/make_people.py, same canvas and shapes) plus a
few large smooth tonal masses: hair combed along its flow, face loops whose spacing is graded toward the shadow side
(eccentric rings, like the sphere test), an optional background / clothing mass.  Feature islands (eyes, mouth) are
drawn last with the face.  Simulation only.

    python3 tools/portrait_hybrid.py lek|thomas A|B|C [--plan]  -> captures/portrait-hybrid/<name>_<v>_p1.thr, _p2.thr, ...
Units are the 600 x 600 canvas of make_people.py (centre 300,300; 290 units = 114 mm, 1 unit = 0.393 mm).
  A  hair (and ponytail) as combed masses, gallery face and body as they were
  B  A + face drawn with spacing graded from fine (lit) to coarse (shadow), from the photo's blurred tone
  C  B + a background mass (Lek: dark wall at the left; Thomas: black shirt)"""
import math, os, sys, pickle, argparse
import numpy as np, cv2
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT + '/patterns/people'); sys.path.insert(0, ROOT + '/patterns/dog'); sys.path.insert(0, HERE)
import make_people as mp
from make_dog import spline
MM = 114.0 / 290.0; U = 1 / MM          # mm per unit, units per mm
OUT = ROOT + '/captures/portrait-hybrid'
F = 2.0; W = 1200; S = 290.0
big, mir = mp.big, mp.mir

def fill(poly, val=255, img=None):
    m = np.zeros((W, W), np.uint8) if img is None else img
    cv2.fillPoly(m, [np.array([[x * F, y * F] for x, y in poly], np.int32)], val); return m

# ------------------------------------------------------------------ photo tone, registered by eyes + mouth
FEAT = dict(lek=([(287, 284), (394, 284), (335, 416)], [(246, 264), (354, 264), (300, 364)]),
            thomas=([(231, 280), (347, 280), (284, 370)], [(248, 266), (352, 266), (300, 359)]))
def photo_tone(name):
    """photo gray (0-255) on the gallery canvas (W px): eyes and mouth of the photo moved onto the gallery's"""
    c = pickle.load(open(ROOT + '/captures/relief-study/faces/%s.pkl' % name, 'rb'))
    src, dst = FEAT[name]
    A = cv2.getAffineTransform(np.float32(src), np.float32(dst)); M = A.copy(); M[:, 2] *= F
    return cv2.warpAffine(c['gray'].astype(np.float32), M, (W, W), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

def skin_spacing(name, face_poly, holes, lo_mm=1.0, hi_mm=4.5, sigma_u=22, grad=1.0):
    """smooth stroke-spacing map in units (W x W): coarse where the photo's skin is dark, fine where it is light"""
    g = photo_tone(name)
    m = fill(face_poly); fill_h = np.zeros_like(m)
    for h in holes: fill(h, 255, fill_h)
    fill_h = cv2.dilate(fill_h, np.ones((int(14 * F) | 1,) * 2, np.uint8))
    ok = ((m > 0) & (fill_h == 0)).astype(np.float32)
    sg = sigma_u * F
    T = cv2.GaussianBlur(g * ok, (0, 0), sg) / np.maximum(cv2.GaussianBlur(ok, (0, 0), sg), 1e-3)
    v = T[ok > 0]; lo, hi = np.percentile(v, 4), np.percentile(v, 96)
    t = np.clip((T - lo) / (hi - lo), 0, 1)
    sp = (lo_mm + (hi_mm - lo_mm) * (1 - t) ** grad) * U
    return sp.astype(np.float32), t

# ------------------------------------------------------------------ fills
def loops_for(poly, holes, spacing=None, base_mm=5.4, lv_first=2.0, maxlev=999, region=0):
    """nested loops inside poly (holes removed). spacing None: even pitch; else a W x W map of local spacing in units, and the
    loops are level sets of dist * (cref / spacing), i.e. eccentric rings whose pitch follows the map."""
    mask = fill(poly)
    for h in holes: fill(h, 0, mask)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5) / F          # units
    if spacing is None:
        cref = base_mm * U; f = dist
    else:
        cref = 2.0 * U; f = dist * (cref / spacing)
    out = []; lv = 0; level = lv_first / F
    while f.max() >= level and lv < maxlev:
        cs_, _ = cv2.findContours((f >= level).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        for c in cs_:
            c = c[:, 0, :].astype(float)
            if len(c) < 36: continue
            c = c[::4]; k = np.array([1, 4, 6, 4, 1], float); k /= k.sum()
            c = np.stack([np.convolve(np.r_[c[-2:, j], c[:, j], c[:2, j]], k, 'valid') for j in (0, 1)], 1) / F
            out.append((region, lv, c))
        lv += 1; level = lv * cref
    return out

def arclen(P):
    P = np.asarray(P, float); d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]; return d

def resample(P, n):
    P = np.asarray(P, float); d = arclen(P); t = np.linspace(0, d[-1], n)
    return np.stack([np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])], 1)

def ruled_comb(A, B, sp_mm, t0=0.04, t1=0.96, u0=0.0, u1=1.0, step=2.5, parity=None):
    """strokes P_t(u) = (1-t) A(u) + t B(u): back-and-forth along the flow, advancing from curve A to curve B.
    sp_mm(t) = stroke spacing (mm) at advance t."""
    n = 400; A = resample(A, n); B = resample(B, n)
    wbar = float(np.mean(np.hypot(*(B - A).T))) * MM
    ts = []; t = t0
    while t <= t1: ts.append(t); t += sp_mm(t) / wbar
    if parity is not None and len(ts) % 2 != parity: ts.pop()
    path = []; idx = np.arange(int(u0 * (n - 1)), int(u1 * (n - 1)) + 1)
    for k, t in enumerate(ts):
        P = (1 - t) * A + t * B; P = P[idx]
        P = resample(P, max(4, int(arclen(P)[-1] / step)))
        path.extend(map(tuple, P if k % 2 == 0 else P[::-1]))
    return path

def hatch(mask, angle_deg, sp_mm, inset_u=1.0, step=2.5):
    """straight serpentine strokes clipped to a mask; spacing sp_mm(v) with v = 0..1 across the mask along the advance direction"""
    a = math.radians(angle_deg); ca, sa = math.cos(a), math.sin(a)
    ys, xs = np.nonzero(mask); X = xs / F; Y = ys / F
    along = X * ca + Y * sa; across = -X * sa + Y * ca
    lo, hi = across.min(), across.max(); path = []; c = lo + 0.5 * sp_mm(0) * U; k = 0
    while c <= hi:
        s = np.arange(along.min(), along.max(), 0.5)
        px = (s * ca - c * sa) * F; py = (s * sa + c * ca) * F
        inb = (px >= 0) & (px < W) & (py >= 0) & (py < W)
        ok = np.zeros(len(s), bool); ok[inb] = mask[py[inb].astype(int), px[inb].astype(int)] > 0
        segs = []; i = 0
        while i < len(s):
            if ok[i]:
                j = i
                while j + 1 < len(s) and ok[j + 1]: j += 1
                if (j - i) * 0.5 > 2 * inset_u + 6:
                    ss = np.arange(s[i] + inset_u, s[j] - inset_u, step); segs.append([(q * ca - c * sa, q * sa + c * ca) for q in ss])
                i = j + 1
            else: i += 1
        if k % 2: segs = [sg[::-1] for sg in segs[::-1]]
        for sg in segs: path.extend(sg)
        c += sp_mm((c - lo) / max(hi - lo, 1e-6)) * U; k += 1
    return path

def smooth_mask(m, r_mm=3.0):
    r = r_mm * U * F; k = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), r * 0.6)
    return (k > 0.5).astype(np.uint8) * 255

# ------------------------------------------------------------------ route the loops (tree walk as in make_people.build)
def route(loops, root_region, start, final_region=None):
    sys.setrecursionlimit(20000)
    L = [l[2] for l in loops]; trees = [cKDTree(c) for c in L]; n = len(L); gapc = {}
    def gap(i, j):
        if (i, j) not in gapc:
            d, k = trees[j].query(L[i]); m = int(np.argmin(d)); gapc[(i, j)] = (float(d[m]), m, int(k[m]))
        return gapc[(i, j)]
    area = [abs(np.sum(c[:, 0] * np.roll(c[:, 1], 1) - c[:, 1] * np.roll(c[:, 0], 1))) / 2 for c in L]
    root = max((i for i in range(n) if loops[i][0] == root_region and loops[i][1] == 0), key=lambda i: area[i])
    parent = {root: None}; hop = {}; left = set(range(n)) - {root}
    best_to = {j: (gap(root, j), root) for j in left}
    while left:
        j = min(left, key=lambda j: best_to[j][0][0]); (d, a_i, a_j), i = best_to[j]
        parent[j] = i; hop[j] = (a_i, a_j); left.discard(j)
        for k in left:
            g = gap(j, k)
            if g[0] < best_to[k][0][0]: best_to[k] = (g, j)
    kids = {}
    for j, i in parent.items():
        if i is not None: kids.setdefault(i, []).append(j)
    special = set()
    if final_region is not None:
        k = next(i for i in range(n) if loops[i][0] == final_region and loops[i][1] == 0)
        while k is not None: special.add(k); k = parent[k]
    P = [start]
    def visit(i, i0):
        c = L[i]; m = len(c)
        mine = sorted(kids.get(i, []), key=lambda j: (hop[j][0] - i0) % m)
        nxt = next((j for j in mine if j in special), None); at = {}
        for j in mine:
            if j != nxt: at.setdefault((hop[j][0] - i0) % m, []).append(j)
        for step in range(m + 1):
            idx = (i0 + step) % m; P.append(tuple(c[idx]))
            for j in at.get(step, []) if step < m else []:
                visit(j, hop[j][1]); P.append(tuple(c[idx]))
        if nxt is not None:
            for step in range(1, (hop[nxt][0] - i0) % m + 1): P.append(tuple(c[(i0 + step) % m]))
            visit(nxt, hop[nxt][1])
    i0 = int(np.argmin((L[root][:, 0] - start[0]) ** 2 + (L[root][:, 1] - start[1]) ** 2))
    visit(root, i0)
    return P

# ------------------------------------------------------------------ the portraits (shapes from make_people.py)
def curve(pts, closed=False, step=2.0): return np.array(spline(pts, step=step, closed=closed))

def lek_masses():
    cap = [(300, 114), (244, 122), (202, 152), (184, 200), (190, 246), (206, 266)]
    hairline = [(300, 190), (262, 190), (228, 206), (206, 244)]
    A = big(cap[::-1] + mir(cap)[1:]); B = big(hairline[::-1] + mir(hairline)[1:])
    pony = [(398, 250), (424, 258), (444, 310), (452, 380), (446, 450), (430, 512), (412, 538)]
    pin = [(404, 286), (410, 320), (416, 380), (414, 440), (404, 500), (412, 538)]
    return dict(hair=(curve(A), curve(B)), pony=(curve(big(pony)), curve(big(pin))))

def thomas_masses():
    cap = [(300, 128), (244, 134), (202, 160), (184, 214), (184, 278), (194, 304)]
    fringe = [(202, 300), (204, 258), (228, 234), (258, 244), (292, 228), (322, 242), (352, 232), (378, 244), (396, 262), (398, 300)]
    A = big(cap[::-1] + mir(cap)[1:]); B = big(fringe)
    return dict(hair=(curve(A), curve(B)))

def end_at(path, pt):
    """make a comb path end at the end nearer pt (reverse the whole path if needed)"""
    a, b = np.array(path[0]), np.array(path[-1]); p = np.array(pt)
    return path[::-1] if np.hypot(*(a - p)) < np.hypot(*(b - p)) else path

LO, HI = 2.5, 7.0
def build(name, variant, lo=None, hi=None):
    p = dict(lek=mp.lek, thomas=mp.thomas)[name]()
    regs = p['regions']; body, face = regs[0], regs[1]
    masses = dict(lek=lek_masses, thomas=thomas_masses)[name]()
    part1 = []
    subj = np.zeros((W, W), np.uint8)
    for r in regs: fill(r['poly'], 255, subj)
    if name == 'lek':
        if variant == 'C':          # dark wall at the left
            disc = np.zeros((W, W), np.uint8); cv2.circle(disc, (W // 2, W // 2), int(280 * F), 255, -1)
            keep = cv2.dilate(subj, np.ones((int(18 * F) | 1,) * 2, np.uint8))
            m = disc.copy(); m[keep > 0] = 0; m[:, int(215 * F):] = 0; m[:int(140 * F), :] = 0
            m = smooth_mask(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((int(30 * F),) * 2, np.uint8)), 14)
            part1 += end_at(hatch(m, 96, lambda v: 5.0), (187, 238))
        A, B = masses['hair']; part1 += ruled_comb(A, B, lambda t: 3.6 - 1.2 * t, parity=1)
        A, B = masses['pony']; part1 += ruled_comb(A, B, lambda t: 3.2, parity=0)
    else:
        A, B = masses['hair']; part1 += ruled_comb(A, B, lambda t: 3.6 - 1.0 * t, parity=1)
        if variant == 'C':
            m = fill(body['poly']); m = cv2.erode(m, np.ones((int(2.5 * U * F),) * 2, np.uint8))
            part1 += hatch(m, 8, lambda v: 4.5)
    holes = list(face['holes']); loops = []
    if variant == 'D' and name == 'lek':          # brows and nose from the photo's own feature shapes, moved onto the gallery face
        c = pickle.load(open(ROOT + '/captures/relief-study/faces/lek.pkl', 'rb')); fr = [r for r in c['regions'] if r['name'] == 'face'][0]
        src, dst = FEAT['lek']; Aff = cv2.getAffineTransform(np.float32(src), np.float32(dst))
        for h in fr['holes'][2:5]:
            q = np.array(h, float); holes.append([tuple(v) for v in (q @ Aff[:, :2].T + Aff[:, 2])])
    if variant == 'D': lo, hi = 3.5, 6.5
    if variant == 'A': loops += loops_for(face['poly'], holes, None, 5.4, region=1)
    else:
        sp, _ = skin_spacing(name, face['poly'], holes, lo_mm=lo or LO, hi_mm=hi or HI); loops += loops_for(face['poly'], holes, sp, region=1)
    if not (name == 'thomas' and variant == 'C'): loops += loops_for(body['poly'], [], None, 5.4, maxlev=2, region=0)
    if name == 'lek': loops += loops_for(regs[3]['poly'], [], None, 5.4, maxlev=1, region=3)
    if name == 'thomas': loops += loops_for(regs[2]['poly'], [], None, 3.0, region=2)           # goatee
    last = part1[-1] if part1 else (300.0, 300.0)
    P2 = route(loops, 1, last, 3 if name == 'lek' else None)
    return [(300.0, 300.0)] + part1, P2, None

def write_files(name, variant, P1, P2, maxpts=11000):
    """resample as make_people.to_thr, split into files of at most maxpts points; return file list and per-file thr arrays"""
    import tempfile
    files = []; allthr = []
    for tag, P in (('p1', P1), ('p2', P2)):
        tmp = '%s/%s_%s_%s.thr' % (OUT, name, variant, tag); mp.to_thr(P, tmp)
        rows = open(tmp).read().split('\n')[1:]; rows = [r for r in rows if r.strip()]
        n = int(math.ceil(len(rows) / maxpts)); per = int(math.ceil(len(rows) / n))
        os.remove(tmp)
        for k in range(n):
            fn = '%s/%s_%s_%s%s.thr' % (OUT, name, variant, tag, '' if n == 1 else chr(97 + k))
            open(fn, 'w').write('# portrait hybrid %s %s\n' % (name, variant) + '\n'.join(rows[k * per:(k + 1) * per]) + '\n'); files.append(fn)
    return files

def plan_image(P1, P2, path, size=1000):
    im = np.full((size, size, 3), 255, np.uint8); k = size / 600.0
    for P, col in ((P1, (60, 60, 200)), (P2, (30, 30, 30))):
        pts = np.array([[x * k, y * k] for x, y in P], np.int32); cv2.polylines(im, [pts.reshape(-1, 1, 2)], False, col, 1, cv2.LINE_AA)
    cv2.circle(im, (size // 2, size // 2), int(290 * k), (0, 160, 0), 1); cv2.imwrite(path, im)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('variant'); a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    P1, P2, _ = build(a.name, a.variant)
    plan_image(P1, P2, '%s/%s_%s_plan.png' % (OUT, a.name, a.variant))
    fs = write_files(a.name, a.variant, P1, P2)
    from sand_relief_path import mini_minutes
    import thrcommon as tc
    for f in fs:
        tr = np.asarray(tc.read_thr(f), float); print(os.path.basename(f), len(tr), 'points', '%.1f min' % mini_minutes(tr))
