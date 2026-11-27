#!/usr/bin/env python3
"""First real drawing for the 36-inch table: 1 + 4 + 6 equal-area zones, ring 2 staggered. FILES ONLY: never contacts a table.

    python3 tools/sand_first_test.py   ->  patterns/sand-party/first-test/NN-*.thr, manifest.json, preview.png

One .thr per zone (11), in drawing order, continuous (file k starts where file k-1 ended; file 01 starts at rho 0).
Inside a zone: name first, then the face, then three interest pictures.  Between zones the ball travels ONLY along frame
lines (circle r0, circle r1, radial dividers), which are drawn as part of that travel.  Theta/rho mapping is the one
patterns/creatures/make_creatures.py uses (theta = atan2(y, x), y up; rho = r / 355 mm).
"""
import heapq, json, math, os, sys
import numpy as np
import cv2
from scipy.spatial import cKDTree
from skimage.graph import route_through_array

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_equal_zones as ez
import sand_slices as ss
import sand_table_options as o
import zone_samples as z
import thrcommon as tc

ROOT = z.ROOT
RT, G = 355.0, ss.G
OUT = os.path.join(ROOT, 'patterns', 'sand-party', 'first-test')
RMAX = 345.0                       # nothing drawn beyond this radius
MAXPTS = 11500
KEEP = '/tmp/claude-1000/-home-bill-dev-WillyGarage-oasis/ba7b51f6-a35b-4dc1-984c-c8c5dff5bf72/scratchpad/first-test-v3'   # copy of files 01-03 as they went to the table
FACEPOS = {}
SPEED = 40.0
GRID = 2.0                         # planner grid, mm
GN = int(2 * 362 / GRID)           # cells per side
OFF = 362.0

CENTRE = ('alex', 'ALEX')
# 02 Lek and 03 Bill (early hand-made cartoon, style a) are already on the table. 04-11: people Bill knows, one style each.
SLICES = [('lek', 'LEK'), ('bill', 'BILL'), ('thomas', 'THOMAS'), ('dog', 'MAVERICK'), ('lek', 'LEK'), ('alex', 'ALEX'),
          ('bill', 'BILL'), ('bill', 'BILL'), ('lek', 'LEK'), ('alex', 'ALEX')]
ZSTYLE = {3: ('a', 56), 4: ('j1', 56), 5: ('d', 49), 6: ('h', 49), 7: ('c', 49), 8: ('a2', 60), 9: ('a2', 60), 10: ('a2', 55)}   # index into zones


# ------------------------------------------------------------------ geometry
r0, r1 = ez.radii(1)
f0, f1 = r0 - G / 2, r1 - G / 2
R1A = [90, 180, 270, 0]                                  # ring 1 boundaries
R2A = [120, 180, 240, 300, 0, 60]                        # ring 2 boundaries (staggered)


def P(r, a):
    return np.array([r * math.cos(math.radians(a)), r * math.sin(math.radians(a))])


def arc(r, a0, a1, step=1.5):
    n = max(2, int(abs(a1 - a0) * math.pi / 180 * r / step))
    return np.array([P(r, a) for a in np.linspace(a0, a1, n + 1)])


def seg(p, q, step=1.5):
    n = max(1, int(np.hypot(*(np.asarray(q) - p)) / step))
    return np.array([p + (np.asarray(q) - p) * i / n for i in range(n + 1)])


class Fine:
    """Frame lines as a fine graph (a node about every 1.5 mm). Travel walks it and draws what it walks."""
    def __init__(self):
        self.pos, self.adj, self.ed, self.key, self.eid = [], [], [], {}, {}

        def nid(p):
            k = (round(p[0] / 0.05), round(p[1] / 0.05))
            if k not in self.key:
                self.key[k] = len(self.pos)
                self.pos.append(np.asarray(p, float))
                self.adj.append([])
            return self.key[k]

        def add(pl):
            ids = [nid(p) for p in pl]
            for a, b in zip(ids[:-1], ids[1:]):
                if a != b:
                    e = len(self.ed)
                    self.ed.append((a, b))
                    self.eid[(a, b)] = self.eid[(b, a)] = e
                    self.adj[a].append((b, e))
                    self.adj[b].append((a, e))
        a1 = sorted({a % 360 for a in R1A})
        a1f = sorted({a % 360 for a in R1A + R2A})
        for r, angs in ((f0, a1), (f1, a1f)):
            for k, a in enumerate(angs):
                b = angs[(k + 1) % len(angs)]
                add(arc(r, a, b + 360 if b <= a else b))
        for a in a1:
            add(seg(P(f0, a), P(f1, a)))
        for a in sorted({x % 360 for x in R2A}):
            add(seg(P(f1, a), P(RMAX, a)))
        self.pos = np.array(self.pos)
        self.drawn = np.zeros(len(self.ed), bool)
        self.R = np.hypot(self.pos[:, 0], self.pos[:, 1])
        self.A = np.degrees(np.arctan2(self.pos[:, 1], self.pos[:, 0])) % 360

    def zone_nodes(self, zone):
        r, a = self.R, self.A
        if zone['kind'] == 'centre':
            return np.where(np.abs(r - f0) < 0.6)[0]
        lo, hi = zone['a_lo'] % 360, zone['a_hi'] % 360
        span = zone['a_hi'] - zone['a_lo']
        da = (a - lo) % 360
        inang = (da <= span + 0.02) | (da >= 359.98)
        rin, rout = (f0, f1) if zone['ring'] == 1 else (f1, RMAX)
        arcs = (np.abs(r - rin) < 0.6) & inang
        if zone['ring'] == 1:
            arcs |= (np.abs(r - rout) < 0.6) & inang
        rad = (r >= rin - 0.6) & (r <= rout + 0.6) & ((np.abs(da) < 0.02) | (np.abs(da - span) < 0.02) | (da >= 359.98))
        return np.where(arcs | rad)[0]

    def walk(self, a, b):
        """Shortest node path a -> b (list of nodes)."""
        if a == b:
            return [a]
        dist, prev, h = {a: 0.0}, {}, [(0.0, a)]
        while h:
            d, u = heapq.heappop(h)
            if u == b:
                break
            if d > dist.get(u, 1e18):
                continue
            for v, e in self.adj[u]:
                nd = d + float(np.hypot(*(self.pos[u] - self.pos[v])))
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(h, (nd, v))
        out, u = [b], b
        while u != a:
            u = prev[u]
            out.append(u)
        return out[::-1]

    def dists(self, a):
        dist, h = {a: 0.0}, [(0.0, a)]
        prev = {}
        while h:
            d, u = heapq.heappop(h)
            if d > dist.get(u, 1e18):
                continue
            for v, e in self.adj[u]:
                nd = d + float(np.hypot(*(self.pos[u] - self.pos[v])))
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(h, (nd, v))
        return dist, prev


FR = Fine()


def allowed(zone, X, Y):
    """Cells a travel path may use inside a zone (inset from its frame lines)."""
    r = np.hypot(X, Y)
    if zone['kind'] == 'centre':
        return r <= f0 - 4
    a = np.degrees(np.arctan2(Y, X)) % 360
    rin = (f0 if zone['ring'] == 1 else f1) + 4
    rout = (f1 - 4) if zone["ring"] == 1 else RMAX - 1.5
    lo = zone['a_lo'] % 360
    span = zone['a_hi'] - zone['a_lo']
    da = (a - lo) % 360
    inset = np.degrees(4.0 / np.maximum(r, 1))
    return (r >= rin) & (r <= rout) & (da >= inset) & (da <= span - inset)


# ------------------------------------------------------------------ packing a slice with its name
def name_paths(text, cx, cy, h):
    """Single-stroke letters, upright, centred on (cx, cy); returns (paths, width)."""
    C = z.caps()
    sp = 0.4
    adv = [C[c]['advance'] for c in text]
    W = (sum(adv) + sp * (len(text) - 1)) * h
    return o.text_line(text, cx, cy - h / 2, h, sp), W


def sector_ok(R, ang, rho, r_in, r_out, a_lo, a_hi):
    """Circle (polar centre R, ang degrees) of radius rho fits the sector with margins."""
    if R < r_in + rho + 5 or R > r_out - rho - 7:
        return False
    for edge in (a_lo, a_hi):
        d = abs(math.radians(ang - edge))
        if d < math.pi / 2 and R * math.sin(d) < rho + 7:
            return False
        if d >= math.pi / 2:
            return False
    return True


def circ_ok(x, y, rho, r_in, r_out, a_lo, a_hi):
    R = math.hypot(x, y)
    ang = math.degrees(math.atan2(y, x))
    while ang < a_lo - 1e-9:
        ang += 360
    while ang > a_lo + 360:
        ang -= 360
    return sector_ok(R, ang, rho, r_in, r_out, a_lo, a_hi)


def rot_about(pl, c, th):
    return z.rot(np.asarray(pl, float) - c, th) + c


def name_item(text, cx, cy, h, th):
    letters, W = name_paths(text, cx, cy, h)
    c = np.array([cx, cy])
    return [rot_about(l, c, th) for l in letters], W


def try_pack(zone, kd, r_in, r_out, a_lo, a_hi, text, h, rf, ri, rng, hop_max, ncand=10, tries=6):
    """Name (a rigid chain of circles, maybe tilted along an edge) plus a face and three pictures, every item within
    hop_max mm of one of the slice's frame lines. Returns (name centre, name angle, centres, gap) or None."""
    C = z.caps()
    W = (sum(C[c]['advance'] for c in text) + 0.4 * (len(text) - 1)) * h
    rc = h / 2 + 2.0
    n = max(2, int(math.ceil((W - 2 * rc) / rc)) + 1)
    ts = np.linspace(-W / 2 + rc, W / 2 - rc, n)

    def up(a):                                    # keep text upright-ish
        a = a % 180
        return a - 180 if a > 90 else a
    angs = [0.0]                                  # names are always horizontal and upright
    cands = []
    for _ in range(1500):
        R = rng.uniform(r_in, r_out)
        a = math.radians(rng.uniform(a_lo, a_hi))
        cx, cy = R * math.cos(a), R * math.sin(a)
        th = math.radians(angs[int(rng.integers(len(angs)))])
        if not all(circ_ok(cx + t * math.cos(th), cy + t * math.sin(th), rc + (3 if zone['ring'] == 2 else 0), r_in, r_out, a_lo, a_hi) for t in ts):
            continue
        L, _ = name_item(text, cx, cy, h, th)
        if kd.query(L[0][0])[0] <= hop_max + 15 and kd.query(L[-1][-1])[0] <= hop_max + 15:
            cands.append((cx, cy, th))
        if len(cands) >= ncand:
            break
    best = None
    rhos = [rf] + [ri] * 3
    midd = (a_lo + a_hi) / 2
    for (cx, cy, th) in cands:
        obst = [(cx + t * math.cos(th), cy + t * math.sin(th), rc) for t in ts]
        for _ in range(tries):
            pts = []
            for rho in rhos:
                for _k in range(40):
                    R = rng.uniform(r_in, r_out)
                    a = rng.uniform(a_lo, a_hi)
                    if sector_ok(R, a, rho, r_in, r_out, a_lo, a_hi):
                        break
                pts.append(np.array([R * math.cos(math.radians(a)), R * math.sin(math.radians(a))]))
            for it in range(120):
                for i in range(len(pts)):
                    for j in range(i + 1, len(pts)):
                        d = pts[j] - pts[i]
                        dist = float(np.hypot(*d)) or 1e-6
                        ov = rhos[i] + rhos[j] + 7 - dist
                        if ov > 0:
                            pts[i] = pts[i] - d / dist * ov * 0.5
                            pts[j] = pts[j] + d / dist * ov * 0.5
                    for (ox, oy, orr) in obst:
                        d = pts[i] - np.array([ox, oy])
                        dist = float(np.hypot(*d)) or 1e-6
                        ov = rhos[i] + orr + 5 - dist
                        if ov > 0:
                            pts[i] = pts[i] + d / dist * ov
                    dd, k = kd.query(pts[i])                      # pull toward the nearest frame line
                    gap = dd - rhos[i]
                    if gap > 12:
                        pts[i] = pts[i] + (kd.data[k] - pts[i]) / dd * (gap - 12) * 0.5
                for i in range(len(pts)):
                    R = math.hypot(*pts[i])
                    ang = math.degrees(math.atan2(pts[i][1], pts[i][0]))
                    ang = (ang - midd + 180) % 360 - 180 + midd
                    R = min(max(R, r_in + rhos[i] + 5), r_out - rhos[i] - 7)
                    lim = (a_hi - a_lo) / 2 - math.degrees(math.asin(min(1.0, (rhos[i] + 8) / R)))
                    ang = min(max(ang, midd - max(lim, 0)), midd + max(lim, 0))
                    pts[i] = np.array([R * math.cos(math.radians(ang)), R * math.sin(math.radians(ang))])
            if any(kd.query(pts[i])[0] - rhos[i] > hop_max for i in range(len(pts))):
                continue
            gap = 99.0
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    gap = min(gap, float(np.hypot(*(pts[i] - pts[j]))) - rhos[i] - rhos[j])
                for (ox, oy, orr) in obst:
                    gap = min(gap, float(np.hypot(*(pts[i] - np.array([ox, oy])))) - rhos[i] - orr)
            if best is None or gap > best[3]:
                best = ((cx, cy), th, [p.copy() for p in pts], gap)
            if best[3] >= 7.0:
                return best
    return best


def layout_slice(zone, person, name, seed):
    rng = np.random.default_rng(seed)
    r_in = f0 + G / 2 if zone['ring'] == 1 else f1 + G / 2
    r_out = r1 if zone['ring'] == 1 else RMAX + 7
    depth = r_out - r_in
    rmax = int((depth - 12) // 2)
    kd = cKDTree(FR.pos[FR.zone_nodes(zone)])
    for hop in (25, 32, 40):
        for h in (25, 22, 20, 18):
            for rf in (list(range(zone['rf_fixed'], 45, -2)) if zone.get('rf_fixed') else sorted({min(60, rmax), min(56, rmax), min(52, rmax), 50, 48}, reverse=True)):
                for ri in (31, 27, 24):
                    res = try_pack(zone, kd, r_in, r_out, zone['a_lo'], zone['a_hi'], name, h, rf, ri, rng, hop)
                    if res and res[3] >= 3.0:
                        print('    %-6s hop<=%d h=%d face %d mm pictures %d mm gap %.1f' % (name, hop, h, 2 * rf, 2 * ri, res[3]), flush=True)
                        return dict(h=h, rf=rf, ri=ri, hop=hop, ncentre=res[0], nth=res[1], pts=res[2], gap=res[3])
    raise RuntimeError('no fit for ' + name)


# ------------------------------------------------------------------ routing
class Canvas:
    """Everything drawn so far, on a 2 mm planner grid and a 1 mm check grid."""
    def __init__(self):
        self.g = np.zeros((GN, GN), np.uint8)
        self.c = np.zeros((724, 724), np.uint8)

    def cell(self, p):
        return int(round((p[1] + OFF) / GRID)), int(round((p[0] + OFF) / GRID))

    def add(self, pl):
        pl = np.asarray(pl, float)
        a = np.array([[(x + OFF) / GRID, (y + OFF) / GRID] for x, y in pl], np.float32).round().astype(np.int32)
        cv2.polylines(self.g, [a.reshape(-1, 1, 2)], False, 255, 3)
        b = np.array([[x + 362, y + 362] for x, y in pl], np.float32).round().astype(np.int32)
        cv2.polylines(self.c, [b.reshape(-1, 1, 2)], False, 255, 3)

    def crossing(self, pl, skip=4.0):
        """Length of a travel path lying on already-drawn lines (ignoring its first and last `skip` mm)."""
        pl = np.asarray(pl, float)
        if len(pl) < 2:
            return 0.0
        d = np.r_[0, np.cumsum(np.hypot(*np.diff(pl, axis=0).T))]
        tot = d[-1]
        if tot <= 2 * skip:
            return 0.0
        s = np.arange(skip, tot - skip, 0.5)
        x = np.interp(s, d, pl[:, 0])
        y = np.interp(s, d, pl[:, 1])
        ix = np.clip((x + 362).round().astype(int), 0, 723)
        iy = np.clip((y + 362).round().astype(int), 0, 723)
        return float((self.c[iy, ix] > 0).sum() * 0.5)


XX, YY = np.meshgrid(np.arange(GN) * GRID - OFF, np.arange(GN) * GRID - OFF)


def simplify(pl, tol=0.8):
    pl = np.asarray(pl, np.float32).reshape(-1, 1, 2)
    return cv2.approxPolyDP(pl, tol, False).reshape(-1, 2).astype(float)


def travel(cv, zone, a, b):
    """Weighted shortest path a -> b inside a zone, avoiding what is drawn (crossing costs 40x)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if np.hypot(*(b - a)) < 6:
        return np.array([a, b])
    cost = np.ones((GN, GN), float)
    cost[cv.g > 0] = 40.0
    cost[~allowed(zone, XX, YY)] = 1e4
    for p in (a, b):
        i, j = cv.cell(p)
        cost[max(i - 2, 0):i + 3, max(j - 2, 0):j + 3] = np.minimum(cost[max(i - 2, 0):i + 3, max(j - 2, 0):j + 3], 1.0)
    (i0, j0), (i1, j1) = cv.cell(a), cv.cell(b)

    def clear(p, q):
        n = max(2, int(np.hypot(*(q - p)) / 1.0))
        xs = np.linspace(p[0], q[0], n)
        ys = np.linspace(p[1], q[1], n)
        ii = np.clip(np.round((ys + OFF) / GRID).astype(int), 0, GN - 1)
        jj = np.clip(np.round((xs + OFF) / GRID).astype(int), 0, GN - 1)
        return bool((cost[ii, jj] < 40).all())
    if clear(a, b):
        return np.array([a, b])
    path, _ = route_through_array(cost, (i0, j0), (i1, j1), fully_connected=True, geometric=True)
    pts = np.array([[j * GRID - OFF, i * GRID - OFF] for i, j in path])
    pts[0], pts[-1] = a, b
    out, i = [pts[0]], 0                       # pull the path taut: longest clear straight hops
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not clear(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return np.array(out)


class Run:
    """The growing drawing: a list of (kind, polyline) events plus bookkeeping."""
    def __init__(self):
        self.ev, self.cv, self.cross, self.cross_list = [], Canvas(), 0.0, []
        self.pos = np.array([0.0, 0.0])
        self.node = None

    def line(self, kind, pl):
        pl = np.asarray(pl, float)
        if len(pl) < 2:
            return
        if np.hypot(*(pl[0] - self.pos)) > 0.05:
            pl = np.vstack([self.pos, pl])
        if kind in ('travel', 'hop'):
            c = self.cv.crossing(pl)
            self.cross += c
            self.cross_list.append((c, kind, pl[0].round(0).tolist(), pl[-1].round(0).tolist()))
        self.ev.append((kind, pl))
        self.cv.add(pl)
        self.pos = pl[-1].copy()

    def walk(self, b):
        """Walk the frame lines from the current frame node to node b, drawing what has not been drawn."""
        if self.node == b:
            return
        nodes = FR.walk(self.node, b)
        for u, v in zip(nodes[:-1], nodes[1:]):
            FR.drawn[FR.eid[(u, v)]] = True
        self.line('frame', FR.pos[nodes])
        self.node = b

    def jump(self, zone, p):
        p = np.asarray(p, float)
        if np.hypot(*(p - self.pos)) < 0.05:
            return
        self.line('travel', travel(self.cv, zone, self.pos, p))


def orient_item(strokes, kd, keep_order=False):
    """Order and orient an item's strokes: start at the point nearest a frame line, close loops where they began."""
    strokes = [np.asarray(s, float) for s in strokes if len(s) > 1]
    if keep_order:
        return strokes
    closed = [float(np.hypot(*(s[0] - s[-1]))) < 0.8 for s in strokes]
    dmin = [float(kd.query(s)[0].min()) for s in strokes]
    first = int(np.argmin(dmin))
    out = []
    left = list(range(len(strokes)))
    cur = None
    while left:
        if cur is None:
            k = first
        else:
            k = min(left, key=lambda q: min(np.hypot(*(strokes[q][0] - cur)), np.hypot(*(strokes[q][-1] - cur))))
        left.remove(k)
        s = strokes[k]
        if cur is None:
            if closed[k]:
                i0 = int(np.argmin(kd.query(s)[0]))
                s = np.vstack([s[i0:], s[1:i0 + 1]])
            elif kd.query(s[-1])[0] < kd.query(s[0])[0]:
                s = s[::-1]
        else:
            if closed[k]:
                i0 = int(np.argmin(np.hypot(*(s - cur).T)))
                s = np.vstack([s[i0:], s[1:i0 + 1]])
            elif np.hypot(*(s[-1] - cur)) < np.hypot(*(s[0] - cur)):
                s = s[::-1]
        out.append(s)
        cur = s[-1]
    return out


def draw_item(run, zone, znodes, kd, kind, strokes, first_in_zone, marks):
    strokes = orient_item(strokes, kd, keep_order=(kind == 'name'))
    S, T = strokes[0][0], strokes[-1][-1]
    bS = int(znodes[kd.query(S)[1]])
    if run.node is None:                           # very first move: from the table centre
        run.line('travel', [run.pos, S])
    else:
        run.walk(bS)
        run.line('hop', [FR.pos[bS], S])
    for s in strokes:
        run.jump(zone, s[0])
        run.line(kind, s)
    bT = int(znodes[kd.query(T)[1]])
    run.line('hop', [T, FR.pos[bT]])
    run.node = bT


def E(cx, cy, rx, ry, a0=0.0, a1=2 * math.pi, n=48):
    a = np.linspace(a0, a1, n)
    return np.column_stack((cx + rx * np.cos(a), cy + ry * np.sin(a)))


def S2(*pts):
    return np.array(pts, float)


PI = math.pi
STYLES = {
    'a': 'Early hand-made cartoon (patterns/people): filled areas, the style already on the table for Lek and Bill (and Alex in the centre).',
    'a2': 'Early hand-made cartoon, drawn larger (about 120 mm) to compare size.',
    'b': 'Minimal emoji-like head: an oval, line eyes, a smile and a small goatee.',
    'c': 'Minimal head with glasses: an oval, rectangular glasses, a smile.',
    'd': 'Long-hair line face: an oval with a ponytail loop, line eyes, a smile.',
    'e': 'Cues only, no head outline: cap line, full beard band, eyes, smile.',
    'f': 'Head, neck and shoulders outline with a swept fringe zigzag, eyes, smile.',
    'g': 'Bold single line: an oval, a zigzag of curly hair, round glasses, a smile.',
    'h': 'Beard cues: an oval head, line eyes, a full beard arc.',
    'j1': 'Maverick, plain line drawing (patterns/dog/dog_line).',
    'j2': 'Maverick, filled drawing (patterns/dog/dog_filled).',
}
DOGS = {'j1': 'dog_line.thr', 'j2': 'dog_filled.thr'}


def _ear(x, y, h=0.09):
    return S2((x, y - h), (x, y + h), (x, y - h))


def _smile(cx=0.0, cy=-0.12, rx=0.34, ry=0.3):
    return E(cx, cy, rx, ry, 1.12 * PI, 1.88 * PI, 20)                    # left -> right


def _rect(cx, cy, w, h):
    return S2((cx - w / 2, cy + h / 2), (cx + w / 2, cy + h / 2), (cx + w / 2, cy - h / 2), (cx - w / 2, cy - h / 2), (cx - w / 2, cy + h / 2))


def _eyes(y=0.18, dx=0.25):
    sm = _smile()
    return np.vstack([_ear(-dx, y), S2((-dx, y - 0.09), (dx, y - 0.09)), _ear(dx, y), S2((dx, y - 0.09)), sm[::-1]])    # eyes, then down to the smile (right -> left)


def face_unit(v):
    """(closed outline O, open chain C) in unit coordinates; the face is O rolled to start nearest the frame line, a jump, then C,
    then all of it again backwards, so the ball finishes where it started (next to the frame line)."""
    head = lambda cx, cy, rx, ry, a0=1.5 * PI, a1=3.5 * PI, n=72: E(cx, cy, rx, ry, a0, a1, n)
    if v == 'b':
        return head(0, 0.05, 0.62, 0.74), np.vstack([_eyes(), E(0, -0.46, 0.13, 0.1, 1.5 * PI, 3.5 * PI, 16)])
    if v == 'c':
        return head(0, 0.05, 0.62, 0.74), np.vstack([_rect(-0.27, 0.2, 0.4, 0.28), S2((-0.07, 0.2), (0.07, 0.2)), _rect(0.27, 0.2, 0.4, 0.28),
                                                      S2((0.27, 0.06)), _smile()[::-1]])
    if v == 'd':
        pt = E(0, 0.05, 0.62, 0.74, 0.1 * PI, 0.1 * PI + 1e-9, 2)[0]
        pony = np.vstack([pt[None], S2((0.92, -0.1), (0.98, -0.8), (0.72, -0.9), (0.74, -0.3), (0.58, 0.02)), pt[None]])
        O = np.vstack([head(0, 0.05, 0.62, 0.74, 1.5 * PI, 2.1 * PI, 30), pony[1:], head(0, 0.05, 0.62, 0.74, 2.1 * PI, 3.5 * PI, 50)[1:]])
        return O, _eyes()
    if v == 'e':
        outer = E(0, -0.05, 0.68, 0.72, 1.02 * PI, 1.98 * PI, 40)
        inner = E(0, 0.0, 0.5, 0.5, 1.9 * PI, 1.1 * PI, 30)
        O = np.vstack([outer, inner, outer[:1]])
        cap = E(0, 0.1, 0.68, 0.78, 0.05 * PI, 0.95 * PI, 30)
        return O, np.vstack([cap, S2((-0.25, 0.2), (-0.25, 0.4)), S2((0.25, 0.4), (0.25, 0.2)), S2((0.0, -0.15)), E(0, -0.2, 0.2, 0.12, 1.15 * PI, 1.85 * PI, 14)])
    if v == 'f':
        h = head(0, 0.28, 0.5, 0.58)
        bust = S2((-0.2, -0.42), (-0.7, -0.62), (-0.92, -0.86), (0.92, -0.86), (0.7, -0.62), (0.2, -0.42), (0, -0.3))
        z_ = [(-0.45, 0.5)] + [(-0.45 + 0.9 * k / 6.0, 0.72 if k % 2 else 0.52) for k in range(1, 6)] + [(0.45, 0.5)]
        sm = E(0, 0.14, 0.26, 0.22, 1.12 * PI, 1.88 * PI, 16)
        return np.vstack([h, bust]), np.vstack([S2(*z_), _ear(0.2, 0.32), S2((0.2, 0.23), (-0.2, 0.23)), _ear(-0.2, 0.32), S2((-0.2, 0.23)), sm])
    if v == 'h':
        return head(0, 0.05, 0.62, 0.74), np.vstack([_eyes(0.2, 0.24), S2((-0.58, -0.05)), E(0, -0.05, 0.62, 0.7, 1.05 * PI, 1.95 * PI, 36)])
    if v == 'g':
        z_ = [(-0.5, 0.45)] + [(-0.5 + 1.0 * k / 8.0, 0.8 if k % 2 else 0.55) for k in range(1, 8)] + [(0.5, 0.45)]
        lens = lambda cx: E(cx, 0.18, 0.2, 0.2, PI, 3 * PI, 24)
        return head(0, 0.05, 0.62, 0.74), np.vstack([S2(*z_), lens(-0.27), S2((-0.07, 0.18), (0.07, 0.18)), lens(0.27), S2((0.27, -0.02)), _smile()[::-1]])
    raise KeyError(v)


def face_path(v, to_edge):
    """One continuous, out-and-back line for variant v. to_edge: unit vector from the face centre toward the nearest frame line."""
    O, C = face_unit(v)
    Oc = O[:-1] if np.hypot(*(O[0] - O[-1])) < 1e-6 else O
    k = int(np.argmin(np.hypot(*(Oc - 0.9 * np.asarray(to_edge)).T)))
    Or = np.vstack([Oc[k:], Oc[:k + 1]])
    X = np.vstack([Or, C])
    full = np.vstack([X, X[::-1][1:]])
    m = max(float(np.hypot(*full.T).max()), 0.97)
    return full * (0.97 / m)


def zone_content(zone, lay):
    """Ordered items of a zone: name, face, pictures (strokes lists)."""
    items = []
    if zone['kind'] == 'centre':
        letters = o.text_line(zone['name'], 0.0, -48 - 17.5, 35)      # horizontal, below the face, inside the circle
        items.append(('name', letters))
        items.append(('face', o.face(zone['person'], (0, 52), 47.0)))
        return items
    (cx, cy) = lay['ncentre']
    letters, W = name_item(zone['name'], cx, cy, lay['h'], lay['nth'])
    items.append(('name', letters))
    pf, pi = lay['pts'][0], lay['pts'][1:]
    v = zone.get('style')
    if v in DOGS:
        items.append(('face', [z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', 'dog', DOGS[v])), lay['rf'] * 0.97) + np.asarray(pf)]))
    elif v and v not in ('a', 'a2'):
        kd = cKDTree(FR.pos[FR.zone_nodes(zone)])
        dd, kk = kd.query(pf)
        d = (kd.data[kk] - np.asarray(pf)) / max(dd, 1e-6)
        items.append(('face', [np.asarray(pf) + lay['rf'] * face_path(v, d)]))
    else:
        items.append(('face', o.face(zone['person'], pf, lay['rf'])))
    for ic, c in zip(ez.triple(zone['person'], zone.get('turn', 0)), pi):
        items.append(('icon', ss.icon_fit(ic, c, lay['ri'])))
    return items


def build_zones():
    zs = [dict(kind='centre', ring=0, name=CENTRE[1], person=CENTRE[0], a_lo=0, a_hi=360)]
    for k in range(4):
        zs.append(dict(kind='slice', ring=1, idx=k, a_lo=90 + 90 * k, a_hi=180 + 90 * k))
    order2 = [5, 0, 1, 2, 3, 4]
    for k in order2:
        zs.append(dict(kind='slice', ring=2, idx=k, a_lo=120 + 60 * k, a_hi=180 + 60 * k))
    for z_, (p, n) in zip(zs[1:], SLICES):
        z_['person'], z_['name'] = p, n
    # 02 Lek and 03 Bill (style a, the early hand-made cartoon) are already on the table; the other eight each get their own style
    seen = {}
    for k, z_ in enumerate(zs):
        if k >= 1:
            z_['turn'] = seen.get(z_['person'], 0)         # a person who appears again gets a different three pictures
            seen[z_['person']] = z_['turn'] + 1
        if k in ZSTYLE:
            z_['style'], z_['rf_fixed'] = ZSTYLE[k]
    return zs


def main():
    os.makedirs(OUT, exist_ok=True)
    zs = build_zones()
    lays = {}
    for i, zn in enumerate(zs):
        if zn['kind'] == 'centre':
            continue
        print('layout zone', i + 1, zn['name'], flush=True)
        lays[i] = layout_slice(zn, zn['person'], zn['name'], 500 + i)
        FACEPOS[i] = (lays[i]['pts'][0], lays[i]['rf'])
    run = Run()
    marks, names = [], []
    for i, zn in enumerate(zs):
        znodes = FR.zone_nodes(zn)
        kd = cKDTree(FR.pos[znodes])
        todo = zone_content(zn, lays.get(i))
        first = True
        while todo:
            if todo[0][0] in ('name', 'face'):
                kind, strokes = todo.pop(0)
            else:                                   # pictures: nearest first
                j = min(range(len(todo)), key=lambda q: min(np.hypot(*(np.asarray(st)[0] - run.pos)) for st in todo[q][1]))
                kind, strokes = todo.pop(j)
            draw_item(run, zn, znodes, kd, kind, strokes, first, marks)
            first = False
        if i + 1 < len(zs):
            marks.append(len(run.ev))                # this file ends on the zone's own frame line
        names.append('%02d-%s-%s' % (i + 1, 'centre' if zn['kind'] == 'centre' else 'ring%d' % zn['ring'], zn['name'].lower()))
    # frame lines that travel did not already draw (own file, to stay under the point limit)
    marks.append(len(run.ev))
    lims = [(0, 106)] + [(f0 - 2, f1 + 2)] * 4 + [(f1 - 2, RMAX + 0.5)] * 6
    prev = 0
    for k, m in enumerate(marks[:11]):
        rr = np.concatenate([np.hypot(*pl.T) for kd_, pl in run.ev[prev:m] if kd_ != 'frame'])
        print('  zone %2d non-frame radius %.1f to %.1f (allowed %s)' % (k + 1, rr.min(), rr.max(), lims[k]))
        for kd_, pl in run.ev[prev:m]:
            if kd_ != "frame" and np.hypot(*pl.T).max() > lims[k][1] + 0.01:
                print("   over limit:", kd_, round(float(np.hypot(*pl.T).max()), 1), pl[np.argmax(np.hypot(*pl.T))].round(1), len(pl))
        assert rr.max() <= lims[k][1] + 0.01 and (k == 0 or rr.min() >= lims[k][0] - 0.01), (k, rr.min(), rr.max())
        prev = m
    names.append('12-frame-lines')
    zs = zs + [dict(name='frame lines')]
    while not FR.drawn.all():
        dist, prev = FR.dists(run.node)
        und = [e for e in range(len(FR.ed)) if not FR.drawn[e]]
        e = min(und, key=lambda e: min(dist.get(FR.ed[e][0], 1e18), dist.get(FR.ed[e][1], 1e18)))
        a = FR.ed[e][0] if dist.get(FR.ed[e][0], 1e18) <= dist.get(FR.ed[e][1], 1e18) else FR.ed[e][1]
        run.walk(a)
        while True:                                 # follow undrawn lines from here
            nxt = [(v, ee) for v, ee in FR.adj[run.node] if not FR.drawn[ee]]
            if not nxt:
                break
            v, ee = nxt[0]
            FR.drawn[ee] = True
            run.line('frame', [FR.pos[run.node], FR.pos[v]])
            run.node = v
    # merge the many tiny frame steps of a run into single polylines is not needed: export densifies anyway
    open_sand = sum(float(np.hypot(*np.diff(pl, axis=0).T).sum()) for k, pl in run.ev if k in ('travel', 'hop')) / 1000.0
    hops = [float(np.hypot(*np.diff(pl, axis=0).T).sum()) for k, pl in run.ev if k == 'hop']
    print('open-sand travel m', round(open_sand, 2), 'hops', len(hops), 'max hop', round(max(hops), 1), 'hops>25', sum(h > 25 for h in hops), flush=True)
    print('top crossings', sorted(run.cross_list, key=lambda t: -t[0])[:6])
    export(run, marks, names, zs, open_sand, hops)
    make_styles(names, zs)


# ------------------------------------------------------------------ export
def to_thr(xy_list):
    """xy polylines (mm) -> one dense (theta, rho) array, unwrapped, plus the index where each input polyline starts."""
    D, starts = [], []
    for pl in xy_list:
        pl = np.asarray(pl, float)
        starts.append(len(D))
        for a, b in zip(pl[:-1], pl[1:]):
            r = max(4.3, min(math.hypot(*a), math.hypot(*b)))
            step = min(1.5, r * math.radians(1.2))
            m = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
            for k in range(m):
                D.append(a + (b - a) * k / m)
        D.append(pl[-1])
    D = np.array(D)
    r = np.hypot(D[:, 0], D[:, 1])
    th = np.arctan2(D[:, 1], D[:, 0])
    rho = np.maximum(r, 4.3) / RT
    rho[0] = 0.0
    th[0] = th[1]
    th = np.unwrap(th)
    return np.column_stack((th, rho)), starts


def export(run, marks, names, zs, open_sand=0.0, hops=()):
    # one polyline per event, joined into a global dense path
    pls = [pl for _, pl in run.ev]
    thr, starts = to_thr(pls)
    # motor-space refinement: no step bigger than 1.4 deg or 0.009 rho
    fin, idx = [thr[0]], {0: 0}
    for i in range(1, len(thr)):
        a, b = fin[-1], thr[i]
        m = int(math.ceil(max(abs(b[0] - a[0]) / math.radians(1.4), abs(b[1] - a[1]) / 0.009, 1)))
        for k in range(1, m + 1):
            fin.append(a + (b - a) * k / m)
        idx[i] = len(fin) - 1
    fin = np.array(fin)
    # cut points: the start of the first event of each following file
    cuts = [0] + [idx[starts[m]] if m < len(starts) else len(fin) - 1 for m in marks] + [len(fin) - 1]
    files, man = [], []
    tot_len = tot_min = 0.0
    for k, name in enumerate(names):
        seg = fin[cuts[k]:cuts[k + 1] + 1]
        assert len(seg) <= MAXPTS, (name, len(seg))
        d = np.abs(np.diff(seg, axis=0))
        assert d[:, 0].max() <= math.radians(1.5) + 1e-6 and d[:, 1].max() <= 0.0101
        if k < 3:                                       # files 01-03 are already on the table: keep them byte for byte
            old = np.loadtxt(os.path.join(KEEP, name + '.thr'))
            print('  keep %s: regenerated copy %s the table copy' % (name, 'matches' if old.shape == seg.shape and np.allclose(old, seg, atol=1e-5) else 'DIFFERS from'))
            seg = old
        path = os.path.join(OUT, name + '.thr')
        with open(path, 'w') as f:
            f.write(''.join('%.5f %.5f\n' % (a, b) for a, b in seg))
        # read back, so lengths and continuity are of what was written
        back = np.loadtxt(path)
        x, y = back[:, 1] * np.cos(back[:, 0]) * RT, back[:, 1] * np.sin(back[:, 0]) * RT
        L = float(np.hypot(np.diff(x), np.diff(y)).sum()) / 1000.0
        files.append(back)
        man.append(dict(file=name + '.thr', name=zs[k]['name'], points=int(len(back)), path_length_m=round(L, 2), minutes_at_40mm_s=round(L * 1000 / SPEED / 60, 1),
                        max_r_mm=round(float(np.hypot(x, y).max()), 1)))
        tot_len += L
        tot_min += L * 1000 / SPEED / 60
    import glob
    for f_ in glob.glob(os.path.join(OUT, '[0-9]*.thr')):
        if os.path.basename(f_)[:-4] not in names:
            os.remove(f_)                                # files of earlier versions with other names
    for k in range(1, len(files)):
        assert np.allclose(files[k][0], files[k - 1][-1], atol=1e-5), ('gap between files', k)
    assert abs(files[0][0, 1]) < 1e-9
    kinds = {}
    for kd, pl in run.ev:
        kinds[kd] = kinds.get(kd, 0.0) + float(np.hypot(*np.diff(pl, axis=0).T).sum()) / 1000.0
    summary = dict(files=man, total_points=sum(m['points'] for m in man), total_length_m=round(tot_len, 2), total_minutes_at_40mm_s=round(tot_min, 1),
                   travel_crossing_drawn_lines_mm=round(run.cross, 1), length_by_kind_m={k: round(v, 2) for k, v in kinds.items()},
                   open_sand_travel_m=round(open_sand, 2), hops_over_25mm=int(sum(h > 25 for h in hops)), max_hop_mm=round(max(hops), 1) if len(hops) else 0,
                   notes='travel runs along frame lines; items are entered by short hops; rim circle skipped; centre has name and face only')
    json.dump(summary, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    # preview rendered from the exported files
    full = np.vstack([f[:-1] for f in files[:-1]] + [files[-1]])
    xy = np.column_stack((full[:, 1] * np.cos(full[:, 0]), full[:, 1] * np.sin(full[:, 0]))) * RT

    class W:
        pass
    w = W()
    w.paths, w.r_in, w.r_out = [xy], 0, RT
    im = z.tray_image([w], tags=False, size=1400, out_px=900)
    im.save(os.path.join(OUT, 'preview.png'))
    print(json.dumps(summary, indent=1))




def make_styles(names, zs):
    """styles.json and styles.png, from the exported files, grouped by person."""
    from PIL import Image, ImageDraw, ImageFont
    groups = {}
    for k in range(0, 11):
        groups.setdefault(zs[k]['name'], []).append(k)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 22)
    by_file, by_person, tiles = {}, {}, {}
    FACEPOS[0] = (np.array([0.0, 52.0]), 47.0)
    for k in range(0, 11):
        zn = zs[k]
        st = zn.get('style', 'a')
        by_file[names[k] + '.thr'] = {zn['name']: dict(style=st, description=STYLES[st])}
        by_person.setdefault(zn['name'], []).append(dict(file=names[k] + '.thr', style=st, description=STYLES[st]))
        back = np.loadtxt(os.path.join(OUT, names[k] + '.thr'))
        xy = np.column_stack((back[:, 1] * np.cos(back[:, 0]), back[:, 1] * np.sin(back[:, 0]))) * RT

        class W:
            pass
        w = W()
        w.paths, w.r_in, w.r_out = [xy], 0, RT
        im = z.tray_image([w], tags=False, size=1400, out_px=1400)
        c, rho = FACEPOS[k]
        sc = 700 * 0.94 / RT
        cx, cy = 700 + c[0] * sc, 700 - c[1] * sc
        half = (rho + 16) * sc
        crop = im.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half))).resize((360, 360))
        t = Image.new('RGB', (360, 410), (245, 242, 233))
        t.paste(crop, (0, 50))
        ImageDraw.Draw(t).text((8, 10), '%s  style %s  (%s)' % (zn['name'], st, names[k][:2]), fill=(40, 50, 40), font=font)
        tiles[k] = t
    rows = list(groups.values())
    cols = max(len(r) for r in rows)
    sheet = Image.new('RGB', (cols * 360, len(rows) * 410), (245, 242, 233))
    for r, ks in enumerate(rows):
        for c_, k in enumerate(ks):
            sheet.paste(tiles[k], (c_ * 360, r * 410))
    sheet.save(os.path.join(OUT, 'styles.png'))
    json.dump(dict(by_file=by_file, by_person=by_person, note='01 is the centre (Alex); 02 and 03 are already on the table; 04-11 are the style test'),
              open(os.path.join(OUT, 'styles.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
