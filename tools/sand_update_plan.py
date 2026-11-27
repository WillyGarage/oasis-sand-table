#!/usr/bin/env python3
"""Updated drawing plan for the 36-inch table (SIMULATION + FILES ONLY: never contacts a table).

    python3 tools/sand_update_plan.py  ->  patterns/sand-party/update-plan/NN-*.thr, manifest.json, preview*.jpg, page

Same table (R = 355 mm, rho 1 = 355 mm), same equal-area zones 1 + 4 + 6 with ring 2 offset by half a slice, same frame
lines, plus an outer frame arc at 349 mm (nothing is drawn beyond 350 mm).  What is new is HOW things connect:
  * every item stands on a frame line (names: letters stand on the arc itself; faces: bottom of the bust on the line;
    pictures: lowest point on the line), so entering/leaving an item costs no line at all;
  * between items the ball walks the frame lines (drawn anyway);
  * inside an item the ball moves between strokes by retracing, not by crossing open sand;
  * names have no underline: the frame line is the baseline, each letter starts and ends on it.
"""
import json, math, os, sys, heapq, itertools
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, Point, MultiPoint, LineString
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_equal_zones as ez
import sand_slices as ss
import sand_table_options as o
import zone_samples as z
import thrcommon as tc

ROOT = z.ROOT
OUT = os.path.join(ROOT, 'patterns', 'sand-party', 'update-plan')
TONIGHT = os.path.join(ROOT, 'patterns', 'sand-party', 'first-test')
RT = 355.0
SPEED = 40.0
MAXPTS = 11500
G = 4.0
r0, r1 = ez.radii(1)
f0, f1 = r0 - G / 2, r1 - G / 2
RO = 349.0                          # outer frame arc; nothing drawn beyond 350 mm
M = 7.0                             # clearance from a frame line an item does not stand on
FACE_KINDS = ('outer', 'inner')
GAP = 8.0                           # clearance between items
NAME_SP = 0.4
R1A = [90, 180, 270, 0]
R2A = [120, 180, 240, 300, 0, 60]
PEOPLE = {'alex': 'alex', 'bill': 'bill', 'lek': 'lek', 'thomas': 'thomas', 'dog': 'dog'}
THR = {'alex': 'people/alex.thr', 'bill': 'people/bill.thr', 'lek': 'people/lek.thr', 'thomas': 'people/thomas.thr', 'dog': 'dog/dog_line.thr'}
CENTRE = ('alex', 'ALEX')
SLICES = [('lek', 'LEK'), ('bill', 'BILL'), ('thomas', 'THOMAS'), ('dog', 'MAVERICK'),
          ('lek', 'LEK'), ('alex', 'ALEX'), ('bill', 'BILL'), ('thomas', 'THOMAS'), ('dog', 'MAVERICK'), ('lek', 'LEK')]
DOG_ICONS = [['hiking', 'acorn', 'turkey'], ['pumpkin', 'ship', 'star-wars-2']]


def P(r, a):
    return np.array([r * math.cos(math.radians(a)), r * math.sin(math.radians(a))])


def unit(a):
    return P(1.0, a)


def dens(pl, step=1.5):
    pl = np.asarray(pl, float)
    out = [pl[0]]
    for a, b in zip(pl[:-1], pl[1:]):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * k / n)
    return np.array(out)


# ------------------------------------------------------------------ frame lines (fine graph with exact nodes at contacts)
class Fine:
    def __init__(self, extra_arc, extra_seg):
        self.pos, self.adj, self.key, self.eid, self.ed = [], [], {}, {}, []

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
                if a != b and (a, b) not in self.eid:
                    e = len(self.ed)
                    self.ed.append((a, b))
                    self.eid[(a, b)] = self.eid[(b, a)] = e
                    self.adj[a].append((b, e))
                    self.adj[b].append((a, e))

        def arc(r, a, b):
            n = max(2, int((b - a) * math.pi / 180 * r / 1.5))
            angs = set(np.linspace(a, b, n + 1).tolist())
            for e in extra_arc.get(round(r, 3), []):
                for k in (e - 360, e, e + 360):
                    if a - 1e-9 <= k <= b + 1e-9:
                        angs.add(k)
            return [P(r, x) for x in sorted(angs)]

        def seg(a, ra, rb):
            n = max(1, int((rb - ra) / 1.5))
            rs = set(np.linspace(ra, rb, n + 1).tolist())
            for e in extra_seg.get(a % 360, []):
                if ra - 1e-9 <= e <= rb + 1e-9:
                    rs.add(e)
            return [P(r, a) for r in sorted(rs)]
        a1 = sorted({a % 360 for a in R1A})
        a1f = sorted({a % 360 for a in R1A + R2A})
        a2 = sorted({a % 360 for a in R2A})
        for r, angs in ((f0, a1), (f1, a1f), (RO, a2)):
            for k, a in enumerate(angs):
                b = angs[(k + 1) % len(angs)]
                add(arc(r, a, b + 360 if b <= a else b))
        for a in a1:
            add(seg(a, f0, f1))
        for a in a2:
            add(seg(a, f1, RO))
        self.pos = np.array(self.pos)
        self.tree = cKDTree(self.pos)
        self.drawn = np.zeros(len(self.ed), bool)

    def node(self, p):
        d, i = self.tree.query(p)
        assert d < 0.08, ('no frame node at contact', p, d)
        return int(i)

    def dists(self, a):
        dist, prev, h = {a: 0.0}, {}, [(0.0, a)]
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

    def walk(self, a, b):
        if a == b:
            return [a]
        dist, prev = self.dists(a)
        out, u = [b], b
        while u != a:
            u = prev[u]
            out.append(u)
        return out[::-1]


# ------------------------------------------------------------------ letters: one stroke per letter, starting and ending on the baseline
_C = None


def caps():
    global _C
    if _C is None:
        _C = z.caps()
    return _C


def letter_path(c):
    P_ = np.asarray(caps()[c]['points'], float)
    on = np.where(P_[:, 1] < 1e-6)[0]
    s_on, e_on = P_[0, 1] < 1e-6, P_[-1, 1] < 1e-6
    if s_on and e_on:
        return P_
    if e_on and not s_on:
        P_ = P_[::-1]
        on = np.where(P_[:, 1] < 1e-6)[0]
        s_on, e_on = True, False
    if s_on:                                             # end off the baseline: retrace back to the last foot
        b = on[-1]
        return np.vstack([P_, P_[b:-1][::-1]])
    b, b2 = on[0], on[-1]                                # neither end on it: go back to the start, then forward, then back to a foot
    return np.vstack([P_[:b + 1][::-1], P_[1:], P_[b2:-1][::-1]])


def name_local(text, h):
    """[(letter polyline in mm, x of its first point, x of its last point)], total width.  Baseline y = 0, x from 0."""
    C = caps()
    x, out = 0.0, []
    for c in text:
        lp = letter_path(c) * h + np.array([x, 0.0])
        out.append(lp)
        x += (C[c]['advance'] + NAME_SP) * h
    return out, x - NAME_SP * h


class Line:
    """A frame line an item can stand on.  contact(s) -> (C, u); the item's x axis is t = u turned 90 degrees clockwise."""
    def __init__(self, kind, zone):
        self.kind, self.zone = kind, zone
        a_lo, a_hi = zone['a_lo'], zone['a_hi']
        self.r_in, self.r_out = zone['r_in'], zone['r_out']
        if kind == 'outer':
            self.r, self.up_in, self.sgn = self.r_out, True, 1
        elif kind == 'inner':
            self.r, self.up_in, self.sgn = self.r_in, False, -1
        elif kind == 'lo':
            self.a, self.u = a_lo, unit(a_lo + 90)
        else:
            self.a, self.u = a_hi, unit(a_hi - 90)

    def params(self):
        z_ = self.zone
        if self.kind in ('outer', 'inner'):
            return list(np.arange(z_['a_lo'] + 0.5, z_['a_hi'], 1.0))
        return list(np.arange(self.r_in, self.r_out + 0.01, 3.0))

    def contact(self, s):
        if self.kind in ('outer', 'inner'):
            c = P(self.r, s)
            u = -c / self.r if self.up_in else c / self.r
            return c, u
        return P(s, self.a), self.u

    def extra(self, s):
        """('arc', r, deg) or ('seg', angle, rho) so the frame graph gets a node exactly there."""
        if self.kind in ('outer', 'inner'):
            return ('arc', round(self.r, 3), s % 360)
        return ('seg', self.a % 360, s)

    def name_world(self, phi_s, text_local):
        """Map name letters (baseline y=0) onto this line, starting at parameter phi_s (deg for arcs, rho for dividers)."""
        out = []
        for lp in text_local:
            lp = dens(lp, 1.2)
            if self.kind in ('outer', 'inner'):
                phi = phi_s + self.sgn * np.degrees(lp[:, 0] / self.r)
                rr = self.r - lp[:, 1] if self.up_in else self.r + lp[:, 1]
                out.append(np.column_stack((rr * np.cos(np.radians(phi)), rr * np.sin(np.radians(phi)))))
            else:
                C = P(phi_s, self.a)
                u = self.u
                t = np.array([u[1], -u[0]])
                out.append(C + np.outer(lp[:, 0], t) + np.outer(lp[:, 1], u))
        return out

    def name_extras(self, phi_s, text_local):
        ex = []
        for lp in text_local:
            for x in (lp[0, 0], lp[-1, 0]):
                if self.kind in ('outer', 'inner'):
                    ex.append(('arc', round(self.r, 3), (phi_s + self.sgn * math.degrees(x / self.r)) % 360))
                else:
                    sg = 1.0 if self.kind == 'lo' else -1.0
                    ex.append(('seg', self.a % 360, phi_s + sg * x))
        return ex

    def name_poly(self, phi_s, W, h):
        hh = h + 1.0
        if self.kind in ('outer', 'inner'):
            n = max(4, int(W / 4))
            xs = np.linspace(-1.0, W + 1.0, n)
            ph = phi_s + self.sgn * np.degrees(xs / self.r)
            rb = self.r + (0.0)
            rt = self.r - hh if self.up_in else self.r + hh
            A = [P(rb, p) for p in ph]
            B = [P(rt, p) for p in ph[::-1]]
            return Polygon(A + B)
        C = P(phi_s, self.a)
        u = self.u
        t = np.array([u[1], -u[0]])
        return Polygon([C - t * 1.0, C + t * (W + 1.0), C + t * (W + 1.0) + u * hh, C - t * 1.0 + u * hh])


def halfplane(n, off):
    n = np.asarray(n, float)
    t = np.array([-n[1], n[0]])
    b = n * off
    return Polygon([b + t * 2000, b - t * 2000, b - t * 2000 + n * 2000, b + t * 2000 + n * 2000])


def region(zone, standing):
    ri = zone['r_in'] + (0 if standing == 'inner' else M)
    ro = zone['r_out'] - (0 if standing == 'outer' else M)
    ann = Point(0, 0).buffer(ro, 128).difference(Point(0, 0).buffer(ri, 128))
    lo = halfplane(unit(zone['a_lo'] + 90), 0 if standing == 'lo' else M)
    hi = halfplane(unit(zone['a_hi'] - 90), 0 if standing == 'hi' else M)
    return ann.intersection(lo).intersection(hi)


# ------------------------------------------------------------------ items (local frame: origin at the entry point on the frame line, y up)
FACE_CACHE = {}


def face_item(person, H):
    thr = tc.read_thr(os.path.join(ROOT, 'patterns', THR[person]))
    p = z.thr_to_xy(thr, 1.0)
    p = p * (H / float(p[:, 1].max() - p[:, 1].min()))
    i = int(np.argmin(p[:, 1]))
    p = p - p[i]
    return dict(kind='face', strokes=[p], hull=MultiPoint(p[::3]).convex_hull)


def icon_item(key, d):
    st = ss.icon_fit(key, (0, 0), d / 2.0)
    st = [np.asarray(s, float) for s in st if len(s) > 1]
    allp = np.vstack(st)
    i = int(np.argmin(allp[:, 1]))
    e = allp[i].copy()
    st = [s - e for s in st]
    return dict(kind='icon', strokes=st, hull=MultiPoint(np.vstack(st)[::2]).convex_hull)


def name_item(text, h):
    lets, W = name_local(text, h)
    return dict(kind='name', text=text, h=h, letters=lets, W=W)


def tmat(u):
    return np.array([u[1], -u[0]]), np.asarray(u, float)


def place_poly(hull, C, u):
    t, u = tmat(u)
    xy = np.asarray(hull.exterior.coords)
    w = C + np.outer(xy[:, 0], t) + np.outer(xy[:, 1], u)
    return Polygon(w)


def world_strokes(strokes, C, u):
    t, u = tmat(u)
    return [C + np.outer(s[:, 0], t) + np.outer(s[:, 1], u) for s in strokes]


def poses_for(item, zone, regs, lines, kinds):
    out = []
    for L in lines:
        if L.kind not in kinds:
            continue
        reg = regs[L.kind].buffer(0.5)
        if item['kind'] == 'name':
            for s in L.params():
                poly = L.name_poly(s, item['W'], item['h'])
                if reg.contains(poly):
                    out.append(dict(L=L, s=s, poly=poly))
        else:
            for s in L.params():
                C, u = L.contact(s)
                poly = place_poly(item['hull'], C, u)
                if reg.contains(poly):
                    out.append(dict(L=L, s=s, poly=poly, C=C, u=u))
    return out


def make_zone(kind, ring, a_lo, a_hi):
    if ring == 1:
        return dict(kind=kind, ring=1, a_lo=a_lo, a_hi=a_hi, r_in=f0, r_out=f1)
    return dict(kind=kind, ring=2, a_lo=a_lo, a_hi=a_hi, r_in=f1, r_out=RO)


def pack(zone, items, rng, tries=250):
    """Random greedy packing on frame lines; returns the best layout (list of poses in item order) or None."""
    lines = [Line(k, zone) for k in ('outer', 'inner', 'lo', 'hi')]
    regs = {k: region(zone, k) for k in ('outer', 'inner', 'lo', 'hi')}
    cand = []
    for it in items:
        kinds = ('outer',) if it['kind'] == 'name' else (FACE_KINDS if it['kind'] == 'face' else ('outer', 'inner', 'lo', 'hi'))
        c = poses_for(it, zone, regs, lines, kinds)
        if not c:
            return None
        cand.append(c)
    best, bs = None, -1e9
    for _ in range(tries):
        order = [0] + list(1 + rng.permutation(len(items) - 1)) if rng.random() < 0.5 else list(rng.permutation(len(items)))
        placed = {}
        ok = True
        for i in order:
            cs = cand[i]
            for k in rng.permutation(len(cs))[:80]:
                pz = cs[k]
                if all(pz['poly'].distance(q['poly']) >= GAP for q in placed.values()):
                    placed[i] = pz
                    break
            else:
                ok = False
                break
        if not ok:
            continue
        ps = [placed[i] for i in range(len(items))]
        mg = min(ps[i]['poly'].distance(ps[j]['poly']) for i in range(len(ps)) for j in range(i + 1, len(ps)))
        pen = 0.0
        for it, pz in zip(items, ps):
            if it['kind'] == 'face':
                pen += {'outer': 0, 'inner': 4, 'lo': 6, 'hi': 6}[pz['L'].kind]
            elif it['kind'] == 'icon':
                pen += {'outer': 0, 'inner': 1, 'lo': 2, 'hi': 2}[pz['L'].kind]
        score = min(mg, 25.0) - pen + rng.random()
        if score > bs:
            best, bs = ps, score
    return best


# ------------------------------------------------------------------ the centre
def centre_layout(H_try=None):
    h = 25.0
    lets, W = name_local('ALEX', h)
    L = Line.__new__(Line)
    L.kind, L.r, L.up_in, L.sgn, L.r_in, L.r_out = 'outer', f0, True, 1, 0, f0
    phi_s = -90.0 - math.degrees(W / 2 / f0)
    strip = L.name_poly(phi_s, W, h)
    thr = tc.read_thr(os.path.join(ROOT, 'patterns', THR['alex']))
    u = z.thr_to_xy(thr, 1.0)
    bh = float(u[:, 1].max() - u[:, 1].min())
    best = None
    pts_s = MultiPoint(u[::7])
    for hh in np.arange(180.0, 120.0, -2.0):
        s = hh / bh
        for cy in np.arange(-30.0, 40.0, 1.0):
            p = u * s + np.array([0.0, cy])
            if np.hypot(*p.T).max() > f0 - 0.3:
                continue
            if MultiPoint(p[::7]).distance(strip) < GAP:
                continue
            best = (hh, s, cy)
            break
        if best:
            break
    hh, s, cy = best
    return dict(H=hh, s=s, cy=cy, name_h=h, phi_s=phi_s, W=W, letters=lets, line=L)


# ------------------------------------------------------------------ walking a stroke set with retracing
def item_walk(strokes, entry, kind):
    """Strokes (world) -> [(kind, polyline)] that starts and ends at `entry`, moving between strokes only by retracing."""
    todo = []
    for s in strokes:
        s = np.asarray(s, float)
        d = np.hypot(*(s - entry).T)
        i = int(d.argmin())
        closed = np.hypot(*(s[0] - s[-1])) < 1.2
        if d[i] < 0.2 and not closed and 0 < i < len(s) - 1:
            todo += [s[i:], s[:i + 1][::-1]]
        else:
            todo.append(s)
    T = np.asarray(entry, float)[None].copy()
    seq = []
    while todo:
        tree = cKDTree(T)
        cum = np.r_[0, np.cumsum(np.hypot(*np.diff(T, axis=0).T))]
        best = None
        for j, s in enumerate(todo):
            closed = np.hypot(*(s[0] - s[-1])) < 1.2
            idx = list(range(0, len(s), max(1, len(s) // 60))) if closed else [0, len(s) - 1]
            for e in idx:
                dd, kk = tree.query(s[e], k=min(8, len(T)))
                dd, kk = np.atleast_1d(dd), np.atleast_1d(kk)
                cost = dd * 6 + (cum[-1] - cum[kk])
                m = int(cost.argmin())
                if best is None or cost[m] < best[0]:
                    best = (cost[m], j, e, int(kk[m]), float(dd[m]))
        _, j, e, k, dd = best
        s = todo.pop(j)
        closed = np.hypot(*(s[0] - s[-1])) < 1.2
        if k < len(T) - 1:
            seq.append(('retrace', T[k:][::-1]))
        T = T[:k + 1]
        if dd > 0.2:
            seq.append(('bridge', np.array([T[-1], s[e]])))
            T = np.vstack([T, s[e]])
        if closed:
            s = np.vstack([s[e:], s[1:e + 1]])
        elif e == len(s) - 1:
            s = s[::-1]
        seq.append((kind, s))
        T = np.vstack([T, s[1:]])
    d = np.hypot(*(T - entry).T)
    q = int(np.where(d < 0.3)[0][-1])
    if q < len(T) - 1:
        seq.append(('retrace', T[q:][::-1]))
    return seq


class Run:
    def __init__(self):
        self.ev, self.pos, self.node = [], np.array([0.0, 0.0]), None

    def line(self, kind, pl):
        pl = np.asarray(pl, float)
        if len(pl) < 2:
            return
        g = float(np.hypot(*(pl[0] - self.pos)))
        assert g < 0.6, ('gap in the path', kind, g, pl[0], self.pos)
        if g > 0.01:
            pl = np.vstack([self.pos, pl])
        self.ev.append((kind, pl))
        self.pos = pl[-1].copy()

    def walk(self, FR, b):
        if self.node == b:
            return
        nodes = FR.walk(self.node, b)
        for u_, v_ in zip(nodes[:-1], nodes[1:]):
            FR.drawn[FR.eid[(u_, v_)]] = True
        self.line('frame', FR.pos[nodes])
        self.node = b


# ------------------------------------------------------------------ zones and sizes
_ICON = {}
_FACE = {}


def icon_c(key, d):
    k = (key, round(d, 1))
    if k not in _ICON:
        _ICON[k] = icon_item(key, d)
    return _ICON[k]


def face_c(person, H):
    k = (person, round(H, 1))
    if k not in _FACE:
        _FACE[k] = face_item(person, H)
    return _FACE[k]


def build_zones():
    zs = [dict(kind='centre', ring=0, name=CENTRE[1], person=CENTRE[0], a_lo=0, a_hi=360)]
    for k in range(4):
        zs.append(make_zone('slice', 1, 90 + 90 * k, 180 + 90 * k))
        zs[-1]['idx'] = k
    for k in [5, 0, 1, 2, 3, 4]:
        zs.append(make_zone('slice', 2, 120 + 60 * k, 180 + 60 * k))
        zs[-1]['idx'] = k
    seen = {}
    for z_, (p, n) in zip(zs[1:], SLICES):
        z_['person'], z_['name'] = p, n
        z_['turn'] = seen.get(p, 0)
        seen[p] = z_['turn'] + 1
    return zs


def pics_for(zone):
    if zone['person'] == 'dog':
        return DOG_ICONS[zone['turn'] % 2]
    return ez.triple(zone['person'], zone['turn'])


def items_for(zone, H, d, h):
    return [name_item(zone['name'], h), face_c(zone['person'], H)] + [icon_c(k, d) for k in pics_for(zone)]


def fit_ring(zones, label):
    rng = np.random.default_rng(7)
    combos = sorted(((H, d) for H in range(140, 66, -4) for d in range(75, 50, -3)), key=lambda c: -(c[0] + 1.5 * c[1]))
    people = [z_ for z_ in zones if z_['person'] != 'dog']
    for H, d in combos:
        if all(pack(z_, items_for(z_, H, d, 22.0), rng, tries=40) for z_ in people):
            print('ring %s common size: face %d mm tall, pictures %d mm' % (label, H, d), flush=True)
            return H, d
    raise RuntimeError('no common size')


def fit_dog(zone, H, d):
    rng = np.random.default_rng(8)
    for Hd in range(H, 40, -4):
        if pack(zone, items_for(zone, Hd, d, 22.0), rng, tries=40):
            return Hd
    raise RuntimeError('dog')


# ------------------------------------------------------------------ plan -> events
def poly_len(pl):
    return float(np.hypot(*np.diff(pl, axis=0).T).sum())


def plan():
    zs = build_zones()
    sizes = {}
    for ring in (1, 2):
        Z = [z_ for z_ in zs if z_['ring'] == ring]
        H, d = fit_ring(Z, ring)
        sizes[ring] = (H, d)
        for z_ in Z:
            z_['H'], z_['d'] = H, d
            if z_['person'] == 'dog':
                z_['H'] = fit_dog(z_, H, d)
    rng = np.random.default_rng(11)
    for i, z_ in enumerate(zs[1:], 1):
        items = items_for(z_, z_['H'], z_['d'], 22.0)
        lay = pack(z_, items, rng, tries=500)
        assert lay, ('no layout', z_['name'])
        z_['items'], z_['lay'] = items, lay
        print('  zone %2d %-8s face %3d mm  pictures %d mm  name on %s, face on %s' % (i + 1, z_['name'], z_['H'], z_['d'], lay[0]['L'].kind, lay[1]['L'].kind), flush=True)
    zs[0]['c'] = centre_layout()
    return zs, sizes


def build_frame(zs):
    ea, es = {}, {}

    def addx(e):
        (ea if e[0] == 'arc' else es).setdefault(e[1], []).append(e[2])
    for z_ in zs[1:]:
        for it, pz in zip(z_['items'], z_['lay']):
            if it['kind'] == 'name':
                for e in pz['L'].name_extras(pz['s'], it['letters']):
                    addx(e)
            else:
                addx(pz['L'].extra(pz['s']))
    c = zs[0]['c']
    for e in c['line'].name_extras(c['phi_s'], c['letters']):
        addx(e)
    u = z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', THR['alex'])), c['s']) + np.array([0.0, c['cy']])
    c['face'] = u
    k = int(np.argmax(np.hypot(*u.T)))
    c['crown'] = k
    addx(('arc', round(f0, 3), math.degrees(math.atan2(u[k, 1], u[k, 0])) % 360))
    addx(('arc', round(f0, 3), 270.0))
    return Fine(ea, es)


def run_plan(zs, FR):
    run = Run()
    marks, names, name_ev, fz = [], [], [], []
    cur = [0]
    # --- centre: name first (standing on the circle), then the face, which starts and ends where it touches the circle
    c = zs[0]['c']
    u = c['face']
    n0 = FR.node(P(f0, 270.0))
    run.ev.append(('stem', np.array([[0.0, 0.0], FR.pos[n0]])))     # the one unavoidable line: from the table centre to the circle
    run.pos = FR.pos[n0].copy()
    run.node = n0
    idx = []
    for lw in c['line'].name_world(c['phi_s'], c['letters']):
        run.walk(FR, FR.node(lw[0]))
        idx.append(len(run.ev))
        run.line('name', lw)
        run.node = FR.node(lw[-1])
    name_ev.append((0, idx, f0))
    marks.append(len(run.ev))
    fz.append(0)
    k = c['crown']
    cr = u[k]
    node = FR.node(P(f0, math.degrees(math.atan2(cr[1], cr[0]))))
    run.walk(FR, node)
    face = np.vstack([u[k:], u[1:k + 1]]) if np.hypot(*(u[0] - u[-1])) < 1.2 else u
    run.ev.append(('stem', np.array([FR.pos[node], face[0]])))
    run.pos = face[0].copy()
    run.line('face', face)
    run.ev.append(('stem', np.array([run.pos, FR.pos[node]])))
    run.pos = FR.pos[node].copy()
    run.node = node
    marks.append(len(run.ev))
    fz.append(0)
    # --- slices
    for zi, z_ in enumerate(zs[1:], 1):
        ents = []
        for it, pz in zip(z_['items'], z_['lay']):
            if it['kind'] == 'name':
                wl = pz['L'].name_world(pz['s'], it['letters'])
                ents.append((FR.node(wl[0][0]), FR.node(wl[-1][-1]), wl))
            else:
                n = FR.node(pz['C'])
                ents.append((n, n, None))
        dcache = {}

        def D(a, b):
            if a not in dcache:
                dcache[a] = FR.dists(a)[0]
            return dcache[a][b]
        best = None
        for perm in itertools.permutations(range(len(ents))):
            if perm[0] != 0 or perm[1] != 1:                 # the name is always drawn first, then the face, then the pictures
                continue
            cost = D(run.node, ents[perm[0]][0]) + sum(D(ents[a][1], ents[b][0]) for a, b in zip(perm[:-1], perm[1:]))
            if best is None or cost < best[0]:
                best = (cost, perm)
        cur[0] = 0
        for k in best[1]:
            it, pz = z_['items'][k], z_['lay'][k]
            enter, leave, wl = ents[k]
            if it['kind'] == 'name':
                est = sum(to_thr([lw])[0].shape[0] for lw in wl) + 400
            else:
                est = sum(to_thr([pl])[0].shape[0] for _, pl in item_walk(world_strokes(it['strokes'], pz['C'], pz['u']), pz['C'], it['kind'])) + 400
            if cur[0] and cur[0] + est > 10600:          # too many points for one file: cut here, between items (the ball is on a frame line)
                marks.append(len(run.ev))
                fz.append(zi)
                cur[0] = 0
            cur[0] += est
            if it['kind'] == 'name':
                idx = []
                for lw in wl:
                    run.walk(FR, FR.node(lw[0]))
                    idx.append(len(run.ev))
                    run.line('name', lw)
                    run.node = FR.node(lw[-1])
                name_ev.append((zi, idx, pz['L'].r if pz['L'].kind in ('outer', 'inner') else None))
            else:
                run.walk(FR, enter)
                st = world_strokes(it['strokes'], pz['C'], pz['u'])
                for kind, pl in item_walk(st, pz['C'], it['kind']):
                    run.line(kind, pl)
                run.node = enter
        z_['order'] = best[1]
        if zi < len(zs) - 1:
            marks.append(len(run.ev))
        fz.append(zi)
    marks.append(len(run.ev))
    fz.append(-1)
    while not FR.drawn.all():
        dist, prev = FR.dists(run.node)
        und = [e for e in range(len(FR.ed)) if not FR.drawn[e]]
        e = min(und, key=lambda e: min(dist.get(FR.ed[e][0], 1e18), dist.get(FR.ed[e][1], 1e18)))
        a = FR.ed[e][0] if dist.get(FR.ed[e][0], 1e18) <= dist.get(FR.ed[e][1], 1e18) else FR.ed[e][1]
        run.walk(FR, a)
        while True:
            nxt = [(v, ee) for v, ee in FR.adj[run.node] if not FR.drawn[ee]]
            if not nxt:
                break
            v, ee = nxt[0]
            FR.drawn[ee] = True
            run.line('frame', [FR.pos[run.node], FR.pos[v]])
            run.node = v
    cnt = {k: fz.count(k) for k in set(fz)}
    seen = {}
    titles = []
    for n_, zi in enumerate(fz):
        seen[zi] = seen.get(zi, 0) + 1
        suf = '' if cnt[zi] == 1 else '-' + 'abcd'[seen[zi] - 1]
        if zi == -1:
            names.append('%02d-frame-lines' % (n_ + 1))
            titles.append('frame lines')
        elif zi == 0:
            names.append('%02d-centre-alex-%s' % (n_ + 1, 'name' if seen[zi] == 1 else 'face'))
            titles.append('ALEX middle, ' + ('name' if seen[zi] == 1 else 'face'))
        else:
            names.append('%02d-ring%d-%s%s' % (n_ + 1, zs[zi]['ring'], zs[zi]['name'].lower(), suf))
            titles.append(zs[zi]['name'] + (' (part %d of %d)' % (seen[zi], cnt[zi]) if suf else ''))
    return run, marks, names, name_ev, titles


# ------------------------------------------------------------------ checks
def check(run, zs, name_ev):
    ev = run.ev
    nonframe = [pl for k, pl in ev if k != 'frame']
    rmax = max(float(np.hypot(*pl.T).max()) for pl in nonframe)
    rall = max(float(np.hypot(*pl.T).max()) for k, pl in ev)
    # name letters: moves between consecutive letters must be frame-line walks along the baseline
    bad = pairs = 0
    for zi, idx, rl in name_ev:
        for a, b in zip(idx[:-1], idx[1:]):
            pairs += 1
            mid = ev[a + 1:b]
            ok = all(k == 'frame' for k, _ in mid)
            if ok and rl is not None:
                ok = all(abs(np.hypot(*pl.T) - rl).max() < 0.3 for _, pl in mid)
            ok = ok and np.hypot(*(ev[a][1][-1] - (mid[0][1][0] if mid else ev[b][1][0]))) < 0.6
            bad += (not ok)
    # clearance between items of a zone
    mind = 99.0
    for z_ in zs[1:]:
        ps = [pz['poly'] for pz in z_['lay']]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                mind = min(mind, ps[i].distance(ps[j]))
    return dict(max_item_r=round(rmax, 2), max_any_r=round(rall, 2), letter_pairs=pairs, letter_jumps_off_baseline=bad, min_item_gap_mm=round(mind, 1))


# ------------------------------------------------------------------ export (same scheme as tonight's files)
def to_thr(xy_list):
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
    if not START_RIM:                     # the ball starts at the centre
        rho[0] = 0.0
        th[0] = th[1]
    return np.column_stack((np.unwrap(th), rho)), starts


def export(run, marks, names, zs, titles):
    thr, starts = to_thr([pl for _, pl in run.ev])
    fin, idx = [thr[0]], {0: 0}
    for i in range(1, len(thr)):
        a, b = fin[-1], thr[i]
        m = int(math.ceil(max(abs(b[0] - a[0]) / math.radians(1.4), abs(b[1] - a[1]) / 0.009, 1)))
        for k in range(1, m + 1):
            fin.append(a + (b - a) * k / m)
        idx[i] = len(fin) - 1
    fin = np.array(fin)
    cuts = [0] + [idx[starts[m]] if m < len(starts) else len(fin) - 1 for m in marks]
    cuts.append(len(fin) - 1)
    os.makedirs(OUT, exist_ok=True)
    import glob
    for f_ in glob.glob(os.path.join(OUT, '[0-9]*.thr')):
        os.remove(f_)
    files, man = [], []
    for k, name in enumerate(names):
        seg = fin[cuts[k]:cuts[k + 1] + 1]
        assert len(seg) <= MAXPTS, (name, len(seg))
        d = np.abs(np.diff(seg, axis=0))
        assert d[:, 0].max() <= math.radians(1.5) + 1e-6 and d[:, 1].max() <= 0.0101
        path = os.path.join(OUT, name + '.thr')
        open(path, 'w').write(''.join('%.5f %.5f\n' % (a, b) for a, b in seg))
        back = np.loadtxt(path)
        x, y = back[:, 1] * np.cos(back[:, 0]) * RT, back[:, 1] * np.sin(back[:, 0]) * RT
        L = float(np.hypot(np.diff(x), np.diff(y)).sum()) / 1000.0
        files.append(back)
        man.append(dict(file=name + '.thr', name=(titles[k]), points=int(len(back)), path_length_m=round(L, 2),
                        minutes_at_40mm_s=round(L * 1000 / SPEED / 60, 1), max_r_mm=round(float(np.hypot(x, y).max()), 1)))
    for k in range(1, len(files)):
        assert np.allclose(files[k][0], files[k - 1][-1], atol=1e-5), ('gap between files', k)
    assert abs(files[0][0, 1] - (1.0 if START_RIM else 0.0)) < 1e-9
    return files, man


def kinds_stats(run):
    k = {}
    for kd, pl in run.ev:
        k[kd] = k.get(kd, 0.0) + poly_len(pl) / 1000.0
    vis = [poly_len(pl) for kd, pl in run.ev if kd in ('stem', 'bridge', 'rim')]
    return {a: round(b, 2) for a, b in k.items()}, vis


def main():
    zs, sizes = plan()
    FR = build_frame(zs)
    run, marks, names, name_ev, titles = run_plan(zs, FR)
    chk = check(run, zs, name_ev)
    print(chk)
    files, man = export(run, marks, names, zs, titles)
    by_kind, vis = kinds_stats(run)
    c = zs[0]['c']
    summ = dict(radius_mm=RT, r0=round(r0, 1), r1=round(r1, 1), outer_frame_arc_mm=RO, files=man,
                total_points=sum(m['points'] for m in man), total_length_m=round(sum(m['path_length_m'] for m in man), 2),
                total_minutes_at_40mm_s=round(sum(m['minutes_at_40mm_s'] for m in man), 1), length_by_kind_m=by_kind,
                open_sand_connector_m=round(sum(vis) / 1000.0, 3), open_sand_connector_count=len(vis), longest_connector_mm=round(max(vis), 1) if vis else 0.0,
                sizes=dict(centre_face_mm=float(c['H']), centre_name_mm=c['name_h'], ring1_face_mm=sizes[1][0], ring1_pictures_mm=sizes[1][1],
                           ring2_face_mm=sizes[2][0], ring2_pictures_mm=sizes[2][1], name_letters_mm=22.0),
                checks=chk)
    json.dump(summ, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    json.dump([dict(name=z_['name'], ring=z_['ring'], H=float(z_.get('H', 0)), d=float(z_.get('d', 0)),
                    items=[dict(kind=it['kind'], line=pz['L'].kind, s=float(pz['s']), bounds=[round(v, 1) for v in pz['poly'].bounds]) for it, pz in zip(z_.get('items', []), z_.get('lay', []))])
               for z_ in zs], open(os.path.join(OUT, 'layout.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != 'files'}, indent=1))
    return files


# ------------------------------------------------------------------ pictures from the exported files
def load_xy(d):
    import glob
    fs = sorted(glob.glob(os.path.join(d, '[0-9]*.thr')))
    arrs = [np.loadtxt(f) for f in fs]
    full = np.vstack([a[:-1] for a in arrs[:-1]] + [arrs[-1]])
    return np.column_stack((full[:, 1] * np.cos(full[:, 0]), full[:, 1] * np.sin(full[:, 0]))) * RT


def render_sim(xy, size, out_px):
    class W_:
        pass
    w = W_()
    w.paths, w.r_in, w.r_out = [xy], 0, RT
    return z.tray_image([w], tags=False, size=size, out_px=out_px)


def previews(size=1400):
    for tag, d in (('tonight', TONIGHT), ('update', OUT)):
        im = render_sim(load_xy(d), size, 1000)
        im.convert('RGB').save(os.path.join(OUT, 'preview-%s.jpg' % tag), quality=88)
        print('saved preview', tag, flush=True)


def crop_mm(im, size, box):
    """box = (x0, y0, x1, y1) in mm, y up."""
    sc = size / 2 * 0.94 / RT
    c = size / 2
    return im.crop((int(c + box[0] * sc), int(c - box[3] * sc), int(c + box[2] * sc), int(c - box[1] * sc)))


def crops(size=2800):
    lay = json.load(open(os.path.join(OUT, 'layout.json')))
    mav = [z_ for z_ in lay if z_['name'] == 'MAVERICK'][0]
    nb = [it for it in mav['items'] if it['kind'] == 'name'][0]['bounds']
    cx, cy = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
    half = max(nb[2] - nb[0], nb[3] - nb[1]) / 2 + 14
    new_box = (cx - half, cy - half, cx + half, cy + half)
    old_box = (90 - 112, 140 - 40, 90 + 112, 140 + 40)          # tonight's MAVERICK sat here (read off tonight's preview)
    ims = {}
    for tag, d in (('tonight', TONIGHT), ('update', OUT)):
        im = render_sim(load_xy(d), size, size).convert('RGB')
        ims[tag] = im
    r = 118
    th = math.degrees(math.atan2(cy, cx))
    R_ = half * 1.7
    big = crop_mm(ims['update'], size, (cx - R_, cy - R_, cx + R_, cy + R_)).rotate(-90 - th, resample=3)
    sc = size / 2 * 0.94 / RT
    wpx, hpx = int((230) * sc), int(64 * sc)
    bw, bh = big.size
    nu = big.crop((bw // 2 - wpx // 2, bh // 2 - hpx // 2, bw // 2 + wpx // 2, bh // 2 + hpx // 2))
    out = {'name-tonight': crop_mm(ims['tonight'], size, old_box), 'name-update': nu,
           'centre-tonight': crop_mm(ims['tonight'], size, (-r, -r, r, r)), 'centre-update': crop_mm(ims['update'], size, (-r, -r, r, r))}
    for k, im in out.items():
        w = 900 if 'centre' in k else 1000
        im = im.resize((w, int(im.size[1] * w / im.size[0])))
        im.save(os.path.join(OUT, 'crop-%s.jpg' % k), quality=88)
        print(k, im.size)

# ------------------------------------------------------------------ the page
def jpeg_uri(path, w=None, q=84):
    import base64, io
    from PIL import Image
    im = Image.open(path).convert('RGB')
    if w and im.size[0] > w:
        im = im.resize((w, int(im.size[1] * w / im.size[0])), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=q, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sand table: updated drawing plan</title><style>
:root { color-scheme: light; }
body { margin: 0; background: #f6f3ea; color: #26302a; font: 16px/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 16px 14px 40px; }
h1 { font-size: 1.5em; margin: 6px 0 4px; } h2 { font-size: 1.15em; margin: 26px 0 8px; }
.sim { display: inline-block; background: #fff4d6; border: 1px solid #e0cd8f; color: #5a4a12; border-radius: 6px; padding: 2px 8px; font-size: .85em; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
.card { background: #fff; border: 1px solid #ddd8c8; border-radius: 10px; padding: 10px; }
.card h3 { margin: 0 0 6px; font-size: 1.05em; }
img { width: 100%; height: auto; display: block; border-radius: 6px; }
figure { margin: 0 0 10px; } figcaption { font-size: .85em; color: #4f5a52; margin-top: 4px; }
ul { margin: 6px 0; padding-left: 20px; } li { margin: 4px 0; }
table { border-collapse: collapse; width: 100%; } td { padding: 5px 6px; border-bottom: 1px solid #e6e1d2; vertical-align: top; }
td:first-child { color: #4f5a52; width: 46%; }
@media (max-width: 760px) { .cols { grid-template-columns: 1fr; } main { padding: 10px 10px 30px; } }
</style></head><body><main>
<h1>Updated drawing plan for the 36-inch table</h1>
<p><span class="sim">Simulation</span> The previews below are computer simulations of the sand, drawn from the exact files the table would run. Nothing was sent to either table.</p>

<h2>Tonight against the update, same scale</h2>
<div class="cols">
 <div class="card"><h3>As drawn tonight</h3>
  <figure><img src="@PREV_T@" alt="Simulation of tonight's files"><figcaption><span class="sim">Simulation</span> of tonight's files.</figcaption></figure></div>
 <div class="card"><h3>Updated plan</h3>
  <figure><img src="@PREV_U@" alt="Simulation of the updated plan"><figcaption><span class="sim">Simulation</span> of the updated files. Names and pictures stand on the lines, faces are bigger, content reaches out to the rim.</figcaption></figure></div>
</div>
<div class="cols" style="margin-top:14px">
 <div class="card"><h3>As drawn tonight: the real sand</h3>
  <figure><img src="@PHOTO@" alt="Overhead photo of the table after tonight's drawing"><figcaption>Overhead photo of the table, not a simulation.</figcaption></figure></div>
 <div class="card"><h3>At a glance</h3><table>@NUMS@</table></div>
</div>

<h2>Close-up: a name, before and after</h2>
<div class="cols">
 <div class="card"><h3>Tonight: MAVERICK</h3><img src="@C_NAME_T@" alt="MAVERICK tonight"><figcaption><span class="sim">Simulation</span>. Each letter was drawn on its own, and the ball jumped across open sand from one letter to the next, often from the middle of one letter to the top of another.</figcaption></div>
 <div class="card"><h3>Updated: MAVERICK</h3><img src="@C_NAME_U@" alt="MAVERICK updated"><figcaption><span class="sim">Simulation</span>. The letters stand on the frame line. Each letter starts and ends on that line, and the ball walks along the line from one letter to the next, so the word reads as one piece.</figcaption></div>
</div>

<h2>Close-up: the middle face, before and after</h2>
<div class="cols">
 <div class="card"><h3>Tonight</h3><img src="@C_CEN_T@" alt="Middle tonight"><figcaption><span class="sim">Simulation</span>. About 94 mm tall, name large and crossing the middle.</figcaption></div>
 <div class="card"><h3>Updated</h3><img src="@C_CEN_U@" alt="Middle updated"><figcaption><span class="sim">Simulation</span>. About @CH@ mm tall, name @CN@ mm letters standing on the circle under the face. At this size the simulation's wide grooves blur the letters; the real grooves are narrower.</figcaption></div>
</div>

<h2>What changed, in plain words</h2>
<ul>
<li>Everything now ends at the same place it starts, on a frame line. Tonight the ball crossed open sand about @T_OPEN@ m between and inside items. The update crosses open sand about @U_OPEN@ m in total, and the longest single crossing is @U_LONG@ mm (tonight @T_LONG@ mm).</li>
<li>Names have no underline and no jumps. The frame line is the baseline, every letter is one stroke that starts and ends on it, and the ball moves between letters along the line. Letter-to-letter moves across open sand: @T_JUMPS@ tonight, @U_JUMPS@ in the update (@PAIRS@ letter gaps checked).</li>
<li>Faces stand on a frame line by the base of the shoulders. Pictures stand on a frame line like objects on a shelf. The ball enters and leaves each one at the point where it touches the line.</li>
<li>Inside a picture, the ball goes from one stroke to the next by retracing lines it already drew. The few short bridges that remain total @BR@ m.</li>
<li>Content now reaches 349 mm, inside the 355 mm the table reaches. No firmware change is needed. A new frame arc at 349 mm gives the outer names a line to stand on.</li>
<li>Only the early hand-made cartoon faces and the dog drawing are used. Names are lettered as Lek, Bill, Thomas, Maverick, Alex.</li>
<li>Faces and pictures are larger (sizes below). In every zone the order is name, then face, then pictures. In the middle the one unavoidable line is the first move from the table centre out to the circle, a straight 105 mm line that the face is drawn around.</li>\n<li><b>Drawing order:</b> middle name, middle face, then ring 1 (slices upper left, lower left, lower right, upper right) and ring 2 (top, then counter-clockwise), each slice as name, face, picture, picture, picture, and last any frame lines still undrawn.</li>
</ul>

<h2>Numbers</h2>
<table>@NUMS2@</table>

<h2>What did not fit</h2>
<ul>
<li>Faces in the slices are @R1F@ mm (inner ring) and @R2F@ mm (outer ring), under the 130 to 140 asked for. The rings are only about 130 and 110 mm deep, and a face standing upright on a line uses nearly all of that. Faces turned sideways would reach 128 mm in the outer ring, but sideways faces look wrong, so they are not used.</li>
<li>The middle face is @CH@ mm, not 190 to 200. A taller face leaves no clear sand for the name inside the circle.</li>
<li>Names read correctly from outside the table (tops point to the middle). Seen from the other side, names near the top of the picture look upside down.</li>
<li>The three Lek zones would be over the 11,500-point file limit as one file each, so the Lek zones are split into parts at gaps between items (the middle is name and face as two files) (@NF@ files in all). The Lek face is an open line, so the ball retraces all of it to get back to the frame line, which adds time but draws nothing.</li>
</ul>
</main></body></html>"""


def page():
    m = json.load(open(os.path.join(OUT, 'manifest.json')))
    st = json.load(open(os.path.join(OUT, 'tonight-connectors.json'))) if os.path.exists(os.path.join(OUT, 'tonight-connectors.json')) else None
    mt = json.load(open(os.path.join(TONIGHT, 'manifest.json')))
    sz = m['sizes']
    from PIL import Image
    ph = Image.open(os.path.join(ROOT, 'captures', 'sand-app', 'first-test', 'shots', '12-12-frame-lines.jpg'))
    w_, h_ = ph.size
    ph.crop((int(w_ * 0.08), 0, int(w_ * 0.72), h_)).save(os.path.join(OUT, 'photo-crop.jpg'), quality=88)
    rows = lambda L: ''.join('<tr><td>%s</td><td>%s</td></tr>' % t for t in L)
    nums = rows([('Total drawing time', '%.1f min (tonight %.1f min), ball at 40 mm/s' % (m['total_minutes_at_40mm_s'], mt['total_minutes_at_40mm_s'])),
                 ('Open-sand lines', '%.2f m (tonight %.2f m)' % (m['open_sand_connector_m'], st['open_total_m']))])
    nums2 = rows([('Zone radii (unchanged)', 'middle circle 107.0 mm, ring 1 out to 239.3 mm, ring 2 out to the sand edge, 355 mm. Every zone has the same area.'),
                  ('Outer frame arc', '349 mm. Nothing is drawn beyond 350 mm.'),
                  ('Middle face', '%d mm tall, name %d mm letters' % (sz['centre_face_mm'], sz['centre_name_mm'])),
                  ('Inner ring (4 slices)', 'faces %d mm tall (Maverick %d mm), pictures %d mm, names 22 mm' % (sz['ring1_face_mm'], [z_ for z_ in json.load(open(os.path.join(OUT, 'layout.json'))) if z_['name'] == 'MAVERICK'][0]['H'], sz['ring1_pictures_mm'])),
                  ('Outer ring (6 slices)', 'faces %d mm tall (Maverick %d mm), pictures %d mm, names 22 mm' % (sz['ring2_face_mm'], [z_ for z_ in json.load(open(os.path.join(OUT, 'layout.json'))) if z_['name'] == 'MAVERICK'][1]['H'], sz['ring2_pictures_mm'])),
                  ('Total drawing time', '%.1f min at 40 mm/s (tonight %.1f min)' % (m['total_minutes_at_40mm_s'], mt['total_minutes_at_40mm_s'])),
                  ('Files', '%d, each continuous, 11,500 points or fewer (largest %d)' % (len(m['files']), max(f['points'] for f in m['files']))),
                  ('Open-sand lines', 'tonight %.2f m in %d pieces, longest %.0f mm. Update %.2f m in %d pieces, longest %.0f mm.' % (st['open_total_m'], st['count'], st['longest_mm'], m['open_sand_connector_m'], m['open_sand_connector_count'], m['longest_connector_mm']))])
    html = PAGE
    rep = dict(PHOTO=jpeg_uri(os.path.join(OUT, 'photo-crop.jpg'), 900), PREV_T=jpeg_uri(os.path.join(OUT, 'preview-tonight.jpg'), 900), PREV_U=jpeg_uri(os.path.join(OUT, 'preview-update.jpg'), 900),
               C_NAME_T=jpeg_uri(os.path.join(OUT, 'crop-name-tonight.jpg'), 900), C_NAME_U=jpeg_uri(os.path.join(OUT, 'crop-name-update.jpg'), 900),
               C_CEN_T=jpeg_uri(os.path.join(OUT, 'crop-centre-tonight.jpg'), 800), C_CEN_U=jpeg_uri(os.path.join(OUT, 'crop-centre-update.jpg'), 800),
               NUMS=nums, NUMS2=nums2, CH=str(int(sz['centre_face_mm'])), CN=str(int(sz['centre_name_mm'])), T_OPEN='%.1f' % st['open_total_m'], U_OPEN='%.2f' % m['open_sand_connector_m'], U_LONG='%.0f' % m['longest_connector_mm'],
               T_LONG='%.0f' % st['longest_mm'], T_JUMPS='36 of 36', U_JUMPS=str(m['checks']['letter_jumps_off_baseline']), PAIRS=str(m['checks']['letter_pairs']),
               BR='%.2f' % m['length_by_kind_m']['bridge'], R1F=str(sz['ring1_face_mm']), R2F=str(sz['ring2_face_mm']), NF=str(len(m['files'])))
    for k, v in rep.items():
        html = html.replace('@' + k + '@', v)
    open(os.path.join(OUT, 'oasis-sand-update-plan.html'), 'w').write(html)
    print('page', len(html) // 1024, 'KB')



# ================================================================== REVISION 2  (python3 tools/sand_update_plan.py rev2)
# Names lifted 8 mm off the zone line, joined letter to letter on their own baseline, touching the line only by a short stem at
# the start and end.  Pictures touch the line at one point only.  Faces keep their way up, lifted 6 mm on a short stem.
# Items are then spread so that the smallest white space (between items and to the zone edges) is as large as it can be.
SPLIT_AT = 10600
HULL_STEP = 3
WIDTH_MAX = 12.0
START_RIM = False
ORIENT_RADIAL = False
FACE_LINES = ('outer', 'inner')
OUT1 = OUT
OUT2 = os.path.join(OUT1, 'rev2')
NAME_LIFT, FACE_LIFT = 8.0, 6.0
THETAS = (0.0, 12.0, -12.0, 24.0, -24.0)
GAP_MIN, GAP_TARGET = 8.0, 10.0


def name_world_l(L, phi_s, letters, lift):
    out = []
    for lp in letters:
        lp = dens(lp, 1.2)
        phi = phi_s + L.sgn * np.degrees(lp[:, 0] / L.r)
        rr = L.r - lift - lp[:, 1] if L.up_in else L.r + lift + lp[:, 1]
        out.append(np.column_stack((rr * np.cos(np.radians(phi)), rr * np.sin(np.radians(phi)))))
    return out


def name_phis(L, phi_s, letters):
    f = lambda x: (phi_s + L.sgn * math.degrees(x / L.r))
    return f(letters[0][0, 0]), f(letters[-1][-1, 0]), [(f(lp[0, 0]), f(lp[-1, 0])) for lp in letters]


def name_poly_l(L, phi_s, W, h, lift):
    hh = h + 1.0
    n = max(4, int(W / 4))
    xs = np.linspace(-1.0, W + 1.0, n)
    ph = phi_s + L.sgn * np.degrees(xs / L.r)
    rb = L.r - lift if L.up_in else L.r + lift
    rt = rb - hh if L.up_in else rb + hh
    return Polygon([P(rb, a) for a in ph] + [P(rt, a) for a in ph[::-1]])


def zone_lines(zone):
    a = np.linspace(zone['a_lo'], zone['a_hi'], 80)
    return {'outer': LineString([P(zone['r_out'], x) for x in a]), 'inner': LineString([P(zone['r_in'], x) for x in a]),
            'lo': LineString([P(zone['r_in'], zone['a_lo']), P(zone['r_out'], zone['a_lo'])]),
            'hi': LineString([P(zone['r_in'], zone['a_hi']), P(zone['r_out'], zone['a_hi'])])}


def variant(item, theta):
    v = item.setdefault('var', {})
    if theta not in v:
        c, s_ = math.cos(math.radians(theta)), math.sin(math.radians(theta))
        R = np.array([[c, -s_], [s_, c]])
        st = [x @ R.T for x in item['strokes']]
        allp = np.vstack(st)
        e = allp[int(np.argmin(allp[:, 1]))].copy()
        st = [x - e for x in st]
        wid = 0.0
        if item['kind'] == 'icon':
            dense = np.vstack([dens(x, 1.0) for x in st])
            near = dense[dense[:, 1] < 0.6]
            wid = float(near[:, 0].max() - near[:, 0].min())
        v[theta] = dict(strokes=st, hull=MultiPoint(np.vstack(st)[::HULL_STEP]).convex_hull, width=wid)
    return v[theta]


def poses_r2(item, zone, regs, lines, kinds, zl):
    if ORIENT_RADIAL and item['kind'] == 'icon':
        return poses_r4(item, zone, regs, lines, kinds, zl)
    out = []
    for L in lines:
        if L.kind not in kinds:
            continue
        reg = regs[L.kind].buffer(0.5)
        others = [k for k in zl if k != L.kind]
        if item['kind'] == 'name':
            for s_ in L.params():
                poly = name_poly_l(L, s_, item['W'], item['h'], NAME_LIFT)
                if reg.contains(poly):
                    out.append(dict(L=L, s=s_, poly=poly, edge=min(poly.distance(zl[k]) for k in others), lift=NAME_LIFT))
            continue
        lift = FACE_LIFT if item['kind'] == 'face' else 0.0
        for th in ((0.0,) if item['kind'] == 'face' else THETAS):
            var = variant(item, th)
            if item['kind'] == 'icon' and var['width'] > WIDTH_MAX:
                continue                                   # its bottom would lie along the line: not a single touch point
            for s_ in L.params():
                C, u = L.contact(s_)
                org = C + u * lift
                poly = place_poly(var['hull'], org, u)
                if reg.contains(poly):
                    out.append(dict(L=L, s=s_, poly=poly, C=C, u=u, org=org, var=var, lift=lift, theta=th,
                                    edge=min(poly.distance(zl[k]) for k in others)))
    return out


def layout_gaps(ps):
    n = len(ps)
    g = [p['edge'] for p in ps]
    for i in range(n):
        for j in range(i + 1, n):
            d = ps[i]['poly'].distance(ps[j]['poly'])
            g[i], g[j] = min(g[i], d), min(g[j], d)
    return np.array(g)


def layout_score(ps):
    g = layout_gaps(ps)
    return float(g.min() + 0.3 * np.minimum(g, 30.0).mean())


def pack2(zone, items, rng, tries=200, passes=4, keep=4, obst=None):
    lines = [Line(k, zone) for k in ('outer', 'inner', 'lo', 'hi')]
    regs = {k: region(zone, k) for k in ('outer', 'inner', 'lo', 'hi')}
    zl = zone_lines(zone)
    cand = []
    for it in items:
        kinds = ('outer',) if it['kind'] == 'name' else (FACE_LINES if it['kind'] == 'face' else ('outer', 'inner', 'lo', 'hi'))
        c = poses_r2(it, zone, regs, lines, kinds, zl)
        if obst is not None:
            c = [pz for pz in c if pz['poly'].distance(obst) >= OBST_GAP]
        if not c:
            return None, 0.0
        cand.append(c)
    starts = []
    for _ in range(tries):
        order = list(rng.permutation(len(items)))
        placed, ok = {}, True
        for i in order:
            for k in rng.permutation(len(cand[i]))[:100]:
                pz = cand[i][k]
                if all(pz['poly'].distance(q['poly']) >= GAP_MIN for q in placed.values()):
                    placed[i] = pz
                    break
            else:
                ok = False
                break
        if ok:
            ps = [placed[i] for i in range(len(items))]
            starts.append((layout_score(ps), ps))
    if not starts:
        return None, 0.0
    starts.sort(key=lambda t: -t[0])
    best = None
    for sc, ps in starts[:keep]:
        ps = list(ps)
        cur = sc
        for _ in range(passes):
            moved = False
            for i in rng.permutation(len(items)):
                bj, bs = None, cur
                for pz in cand[i]:
                    if any(pz['poly'].distance(ps[j]['poly']) < GAP_MIN for j in range(len(ps)) if j != i):
                        continue
                    old = ps[i]
                    ps[i] = pz
                    sc2 = layout_score(ps)
                    ps[i] = old
                    if sc2 > bs + 1e-6:
                        bj, bs = pz, sc2
                if bj is not None:
                    ps[i], cur, moved = bj, bs, True
            if not moved:
                break
        if best is None or cur > best[0]:
            best = (cur, ps)
    return best[1], float(layout_gaps(best[1]).min())


def fit_ring_r2(zones, label):
    rng = np.random.default_rng(7)
    combos = sorted(((H, d) for H in range(140, 66, -4) for d in range(75, 50, -3)), key=lambda c: -(c[0] + 1.5 * c[1]))
    people = [z_ for z_ in zones if z_['person'] != 'dog']
    for H, d in combos:
        ok = True
        for z_ in people:
            ps, mg = pack2(z_, items_for(z_, H, d, 22.0), rng, tries=30, passes=1, keep=1)
            if ps is None or mg < GAP_TARGET:
                ok = False
                break
        if ok:
            print('ring %s common size: face %d mm tall, pictures %d mm' % (label, H, d), flush=True)
            return H, d
    raise RuntimeError('no common size')


def fit_dog_r2(zone, H, d):
    rng = np.random.default_rng(8)
    for Hd in range(H, 40, -4):
        ps, mg = pack2(zone, items_for(zone, Hd, d, 22.0), rng, tries=30, passes=1, keep=1)
        if ps is not None and mg >= GAP_TARGET:
            return Hd
    raise RuntimeError('dog')


def centre_layout_r2():
    h = 25.0
    lets, W = name_local('ALEX', h)
    L = Line.__new__(Line)
    L.kind, L.r, L.up_in, L.sgn, L.r_in, L.r_out = 'outer', f0, True, 1, 0, f0
    phi_s = -90.0 - math.degrees(W / 2 / f0)
    strip = name_poly_l(L, phi_s, W, h, NAME_LIFT)
    u = z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', THR['alex'])), 1.0)
    bh = float(u[:, 1].max() - u[:, 1].min())
    best = None
    for hh in np.arange(180.0, 120.0, -2.0):
        s_ = hh / bh
        for cy in np.arange(-30.0, 40.0, 1.0):
            pp = u * s_ + np.array([0.0, cy])
            if np.hypot(*pp.T).max() > f0 - 0.3 or MultiPoint(pp[::7]).distance(strip) < GAP_MIN:
                continue
            best = (hh, s_, cy)
            break
        if best:
            break
    hh, s_, cy = best
    return dict(H=hh, s=s_, cy=cy, name_h=h, phi_s=phi_s, W=W, letters=lets, line=L)


def plan_r2():
    zs = build_zones()
    sizes = {}
    for ring in (1, 2):
        Z = [z_ for z_ in zs if z_['ring'] == ring]
        H, d = fit_ring_r2(Z, ring)
        sizes[ring] = (H, d)
        for z_ in Z:
            z_['H'], z_['d'] = H, d
            if z_['person'] == 'dog':
                z_['H'] = fit_dog_r2(z_, H, d)
    rng = np.random.default_rng(11)
    for i, z_ in enumerate(zs[1:], 1):
        items = items_for(z_, z_['H'], z_['d'], 22.0)
        lay, mg = pack2(z_, items, rng, tries=300, passes=10, keep=6)
        assert lay, ('no layout', z_['name'])
        z_['items'], z_['lay'] = items, lay
        g = layout_gaps(lay)
        print('  zone %2d %-8s face %3d  smallest gap %.1f  per-item nearest gaps %s' % (i + 1, z_['name'], z_['H'], mg, np.round(g, 0).tolist()), flush=True)
    zs[0]['c'] = centre_layout_r2()
    return zs, sizes


def build_frame_r2(zs):
    ea, es = {}, {}

    def addx(e):
        (ea if e[0] == 'arc' else es).setdefault(e[1], []).append(e[2])
    for z_ in zs[1:]:
        for it, pz in zip(z_['items'], z_['lay']):
            if it['kind'] == 'name':
                a, b, _ = name_phis(pz['L'], pz['s'], it['letters'])
                addx(('arc', round(pz['L'].r, 3), a % 360))
                addx(('arc', round(pz['L'].r, 3), b % 360))
            else:
                addx(pz['L'].extra(pz['s']))
    c = zs[0]['c']
    a, b, _ = name_phis(c['line'], c['phi_s'], c['letters'])
    addx(('arc', round(f0, 3), b % 360))
    addx(('arc', round(f0, 3), a % 360))
    u = z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', THR['alex'])), c['s']) + np.array([0.0, c['cy']])
    c['face'] = u
    k = int(np.argmax(np.hypot(*u.T)))
    c['crown'] = k
    addx(('arc', round(f0, 3), math.degrees(math.atan2(u[k, 1], u[k, 0])) % 360))
    return Fine(ea, es)


def draw_name_r2(run, FR, L, phi_s, letters, lift, from_centre=False):
    world = name_world_l(L, phi_s, letters, lift)
    a, b, pairs = name_phis(L, phi_s, letters)
    rb = L.r - lift if L.up_in else L.r + lift
    n1 = FR.node(P(L.r, b))
    if from_centre:
        mid = P(rb, 270.0)
        run.ev.append(('stem', np.array([[0.0, 0.0], mid])))
        run.pos = mid.copy()
        a270 = 270.0 + ((a - 270.0 + 180.0) % 360.0 - 180.0)
        run.line('join', np.array([P(rb, x) for x in np.linspace(270.0, a270, 12)]))
    else:
        n0 = FR.node(P(L.r, a))
        run.walk(FR, n0)
        run.line('stem', np.array([FR.pos[n0], world[0][0]]))
    idx = []
    for i, lw in enumerate(world):
        if i > 0:
            pa, pb = pairs[i - 1][1], pairs[i][0]
            run.line('join', np.array([P(rb, x) for x in np.linspace(pa, pb, max(3, int(abs(pb - pa) * math.pi / 180 * rb / 1.2)))]))
        idx.append(len(run.ev))
        run.line('name', lw)
    run.line('stem', np.array([world[-1][-1], FR.pos[n1]]))
    run.node = n1
    return idx, rb


def run_plan_r2(zs, FR):
    run = Run()
    run.items = []
    marks, names, name_ev, fz = [], [], [], []
    cur = [0]
    c = zs[0]['c']
    u = c['face']
    a0 = len(run.ev)
    if START_RIM:                                  # the ball is at the rim: in along the 0-degree divider, then round the centre circle
        run.ev.append(('rim', np.array([[RT, 0.0], [RO, 0.0]])))
        run.pos = np.array([RO, 0.0])
        run.node = FR.node(P(RO, 0.0))
        run.walk(FR, FR.node(P(f0, 0.0)))
    idx, rb = draw_name_r2(run, FR, c['line'], c['phi_s'], c['letters'], NAME_LIFT, from_centre=not START_RIM)
    run.items.append((0, 'name', a0, len(run.ev)))
    name_ev.append((0, idx, rb))
    marks.append(len(run.ev))
    fz.append(0)
    k = c['crown']
    cr = u[k]
    node = FR.node(P(f0, math.degrees(math.atan2(cr[1], cr[0]))))
    run.walk(FR, node)
    face = np.vstack([u[k:], u[1:k + 1]])
    run.ev.append(('stem', np.array([FR.pos[node], face[0]])))
    run.pos = face[0].copy()
    a0 = len(run.ev)
    run.line('face', face)
    run.items.append((0, 'face', a0, len(run.ev)))
    run.ev.append(('stem', np.array([run.pos, FR.pos[node]])))
    run.pos = FR.pos[node].copy()
    run.node = node
    marks.append(len(run.ev))
    fz.append(0)
    for zi, z_ in enumerate(zs[1:], 1):
        ents = []
        for it, pz in zip(z_['items'], z_['lay']):
            if it['kind'] == 'name':
                a, b, _ = name_phis(pz['L'], pz['s'], it['letters'])
                ents.append((FR.node(P(pz['L'].r, a)), FR.node(P(pz['L'].r, b))))
            else:
                n = FR.node(pz['C'])
                ents.append((n, n))
        dcache = {}

        def D(a_, b_):
            if a_ not in dcache:
                dcache[a_] = FR.dists(a_)[0]
            return dcache[a_][b_]
        best = None
        for perm in itertools.permutations(range(len(ents))):
            if perm[0] != 0 or perm[1] != 1:
                continue
            cost = D(run.node, ents[perm[0]][0]) + sum(D(ents[a_][1], ents[b_][0]) for a_, b_ in zip(perm[:-1], perm[1:]))
            if best is None or cost < best[0]:
                best = (cost, perm)
        cur[0] = 0
        for kk in best[1]:
            it, pz = z_['items'][kk], z_['lay'][kk]
            if it['kind'] == 'name':
                est = sum(len(l_) for l_ in name_world_l(pz['L'], pz['s'], it['letters'], NAME_LIFT)) + 400
            else:
                st = world_strokes(pz['var']['strokes'], pz['org'], pz['u'])
                est = sum(to_thr([pl])[0].shape[0] for _, pl in item_walk(st, pz['org'], it['kind'])) + 400
            if cur[0] and cur[0] + est > SPLIT_AT:
                marks.append(len(run.ev))
                fz.append(zi)
                cur[0] = 0
            cur[0] += est
            if it['kind'] == 'name':
                a0 = len(run.ev)
                idx, rb = draw_name_r2(run, FR, pz['L'], pz['s'], it['letters'], NAME_LIFT)
                run.items.append((zi, 'name', a0, len(run.ev)))
                name_ev.append((zi, idx, rb))
            else:
                enter = ents[kk][0]
                run.walk(FR, enter)
                if pz['lift'] > 0:
                    run.line('stem', np.array([FR.pos[enter], pz['org']]))
                a0 = len(run.ev)
                seqw = item_walk(world_strokes(pz['var']['strokes'], pz['org'], pz['u']), pz['org'], it['kind'])
                big = est > 10300                          # a single item too big for one file: cut between its drawing and its retrace
                for q_, (kind, pl) in enumerate(seqw):
                    run.line(kind, pl)
                    if big and q_ + 1 < len(seqw) and seqw[q_ + 1][0] == 'retrace' and kind != 'retrace':
                        marks.append(len(run.ev))
                        fz.append(zi)
                        cur[0] = 0
                        big = False
                if pz['lift'] > 0:
                    run.line('retrace', np.array([pz['org'], FR.pos[enter]]))
                run.items.append((zi, it['kind'], a0, len(run.ev)))
                run.node = enter
        z_['order'] = best[1]
        if zi < len(zs) - 1:
            marks.append(len(run.ev))
        fz.append(zi)
    marks.append(len(run.ev))
    fz.append(-1)
    while not FR.drawn.all():
        dist, prev = FR.dists(run.node)
        und = [e for e in range(len(FR.ed)) if not FR.drawn[e]]
        e = min(und, key=lambda e: min(dist.get(FR.ed[e][0], 1e18), dist.get(FR.ed[e][1], 1e18)))
        a_ = FR.ed[e][0] if dist.get(FR.ed[e][0], 1e18) <= dist.get(FR.ed[e][1], 1e18) else FR.ed[e][1]
        run.walk(FR, a_)
        while True:
            nxt = [(v, ee) for v, ee in FR.adj[run.node] if not FR.drawn[ee]]
            if not nxt:
                break
            v, ee = nxt[0]
            FR.drawn[ee] = True
            run.line('frame', [FR.pos[run.node], FR.pos[v]])
            run.node = v
    cnt = {k_: fz.count(k_) for k_ in set(fz)}
    seen = {}
    titles = []
    for n_, zi in enumerate(fz):
        seen[zi] = seen.get(zi, 0) + 1
        suf = '' if cnt[zi] == 1 else '-' + 'abcd'[seen[zi] - 1]
        if zi == -1:
            names.append('%02d-frame-lines' % (n_ + 1))
            titles.append('frame lines')
        elif zi == 0:
            names.append('%02d-centre-alex-%s' % (n_ + 1, 'name' if seen[zi] == 1 else 'face'))
            titles.append('ALEX middle, ' + ('name' if seen[zi] == 1 else 'face'))
        else:
            names.append('%02d-ring%d-%s%s' % (n_ + 1, zs[zi]['ring'], zs[zi]['name'].lower(), suf))
            titles.append(zs[zi]['name'] + (' (part %d of %d)' % (seen[zi], cnt[zi]) if suf else ''))
    return run, marks, names, name_ev, titles


def check_r2(run, zs, name_ev):
    ev = run.ev
    rall = max(float(np.hypot(*pl.T).max()) for k, pl in ev)
    bad = pairs = 0
    for zi, idx, rb in name_ev:
        for a, b in zip(idx[:-1], idx[1:]):
            pairs += 1
            mid = ev[a + 1:b]
            ok = len(mid) == 1 and mid[0][0] == 'join' and abs(np.hypot(*mid[0][1].T) - rb).max() < 0.3
            ok = ok and np.hypot(*(ev[a][1][-1] - mid[0][1][0])) < 0.6 if mid else False
            bad += (not ok)
    ring = {1: [], 2: []}
    edges = {1: [], 2: []}
    for z_ in zs[1:]:
        ps = z_['lay']
        for i in range(len(ps)):
            nn = min(ps[i]['poly'].distance(ps[j]['poly']) for j in range(len(ps)) if j != i)
            ring[z_['ring']].append(nn)
            edges[z_['ring']].append(ps[i]['edge'])
    pair_min = min(min(v) for v in ring.values())
    return dict(max_any_r=round(rall, 2), letter_pairs=pairs, letter_jumps_off_baseline=bad,
                ring1_nearest_gap_min=round(min(ring[1]), 1), ring1_nearest_gap_max=round(max(ring[1]), 1),
                ring2_nearest_gap_min=round(min(ring[2]), 1), ring2_nearest_gap_max=round(max(ring[2]), 1),
                ring1_edge_gap_min=round(min(edges[1]), 1), ring2_edge_gap_min=round(min(edges[2]), 1),
                letter_gap_mm=round(NAME_SP * 22.0, 1), name_lift_mm=NAME_LIFT)


def main_r2():
    global OUT
    OUT = OUT2
    os.makedirs(OUT, exist_ok=True)
    zs, sizes = plan_r2()
    FR = build_frame_r2(zs)
    run, marks, names, name_ev, titles = run_plan_r2(zs, FR)
    chk = check_r2(run, zs, name_ev)
    print(chk)
    files, man = export(run, marks, names, zs, titles)
    by_kind, vis = kinds_stats(run)
    joins = [poly_len(pl) for kd, pl in run.ev if kd == 'join']
    c = zs[0]['c']
    summ = dict(radius_mm=RT, files=man, total_points=sum(m['points'] for m in man), total_length_m=round(sum(m['path_length_m'] for m in man), 2),
                total_minutes_at_40mm_s=round(sum(m['minutes_at_40mm_s'] for m in man), 1), length_by_kind_m=by_kind,
                open_sand_connector_m=round(sum(vis) / 1000.0, 3), open_sand_connector_count=len(vis), longest_connector_mm=round(max(vis), 1),
                join_m=round(sum(joins) / 1000.0, 3), joins=len(joins),
                sizes=dict(centre_face_mm=float(c['H']), centre_name_mm=c['name_h'], ring1_face_mm=sizes[1][0], ring1_pictures_mm=sizes[1][1],
                           ring2_face_mm=sizes[2][0], ring2_pictures_mm=sizes[2][1], name_letters_mm=22.0), checks=chk)
    json.dump(summ, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    json.dump([dict(name=z_['name'], ring=z_['ring'], H=float(z_.get('H', 0)), d=float(z_.get('d', 0)),
                    items=[dict(kind=it['kind'], line=pz['L'].kind, s=float(pz['s']), bounds=[round(v, 1) for v in pz['poly'].bounds]) for it, pz in zip(z_.get('items', []), z_.get('lay', []))])
               for z_ in zs], open(os.path.join(OUT, 'layout.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != 'files'}, indent=1))


def crops_r2(size=2800):
    lay = json.load(open(os.path.join(OUT2, 'layout.json')))
    mav = [z_ for z_ in lay if z_['name'] == 'MAVERICK'][0]
    nb = [it for it in mav['items'] if it['kind'] == 'name'][0]['bounds']
    cx, cy = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
    half = max(nb[2] - nb[0], nb[3] - nb[1]) / 2 + 14
    im = render_sim(load_xy(OUT2), size, size).convert('RGB')
    th = math.degrees(math.atan2(cy, cx))
    R_ = half * 1.7
    big = crop_mm(im, size, (cx - R_, cy - R_, cx + R_, cy + R_)).rotate(-90 - th, resample=3)
    sc = size / 2 * 0.94 / RT
    wpx, hpx = int(230 * sc), int(64 * sc)
    bw, bh = big.size
    nu = big.crop((bw // 2 - wpx // 2, bh // 2 - hpx // 2, bw // 2 + wpx // 2, bh // 2 + hpx // 2))
    r = 118
    for k, c_ in (('name-rev2', nu), ('centre-rev2', crop_mm(im, size, (-r, -r, r, r)))):
        w = 1000 if 'name' in k else 900
        c_ = c_.resize((w, int(c_.size[1] * w / c_.size[0])))
        c_.save(os.path.join(OUT2, 'crop-%s.jpg' % k), quality=88)
        print(k, c_.size)
    im.resize((1000, 1000)).save(os.path.join(OUT2, 'preview-rev2.jpg'), quality=88)


PAGE3 = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sand table: drawing plans compared</title><style>
:root { color-scheme: light; }
body { margin: 0; background: #f6f3ea; color: #26302a; font: 16px/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding: 16px 14px 40px; }
h1 { font-size: 1.5em; margin: 6px 0 4px; } h2 { font-size: 1.15em; margin: 26px 0 8px; }
.sim { display: inline-block; background: #fff4d6; border: 1px solid #e0cd8f; color: #5a4a12; border-radius: 6px; padding: 2px 8px; font-size: .85em; }
.cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; align-items: start; }
.two { display: grid; grid-template-columns: 1fr 2fr; gap: 14px; align-items: start; }
.card { background: #fff; border: 1px solid #ddd8c8; border-radius: 10px; padding: 10px; }
.card.new { border-color: #7aa886; box-shadow: 0 0 0 2px #dcebe0; }
.card h3 { margin: 0 0 6px; font-size: 1.05em; }
img { width: 100%; height: auto; display: block; border-radius: 6px; }
figure { margin: 0; } figcaption { font-size: .85em; color: #4f5a52; margin-top: 4px; }
ul { margin: 6px 0; padding-left: 20px; } li { margin: 4px 0; }
table { border-collapse: collapse; width: 100%; } td, th { padding: 5px 6px; border-bottom: 1px solid #e6e1d2; vertical-align: top; text-align: left; font-weight: normal; }
td:first-child { color: #4f5a52; width: 34%; } thead th { font-weight: 600; }
@media (min-width: 901px) { .r3two { grid-template-columns: 1fr 1fr; } }
@media (max-width: 900px) { .cols, .two { grid-template-columns: 1fr; } main { padding: 10px 10px 30px; } }
</style></head><body><main>
<h1>Drawing plans for the 36-inch table, compared</h1>
<p><span class="sim">Simulation</span> Every picture below except the photo is a computer simulation of the sand, drawn from the exact files the table would run. Nothing was sent to either table.</p>

<h2>Tonight, update 1 and revision 2, same scale</h2>
<div class="cols">
 <div class="card"><h3>As drawn tonight</h3><figure><img src="@PREV_T@" alt="Tonight"><figcaption><span class="sim">Simulation</span> of tonight's files.</figcaption></figure></div>
 <div class="card"><h3>Update 1</h3><figure><img src="@PREV_1@" alt="Update 1"><figcaption><span class="sim">Simulation</span>. Names and pictures stand on the lines.</figcaption></figure></div>
 <div class="card new"><h3>Revision 2</h3><figure><img src="@PREV_2@" alt="Revision 2"><figcaption><span class="sim">Simulation</span>. Names lifted off the line, pictures touch it at one point, items spread evenly.</figcaption></figure></div>
</div>
<div class="two" style="margin-top:14px">
 <div class="card"><h3>The real sand tonight</h3><figure><img src="@PHOTO@" alt="Overhead photo"><figcaption>Overhead photo, not a simulation.</figcaption></figure></div>
 <div class="card"><h3>At a glance</h3><table><thead><tr><th></th><th>Tonight</th><th>Update 1</th><th>Revision 2</th></tr></thead>@GLANCE@</table></div>
</div>

<h2>Close-up: MAVERICK in all three</h2>
<div class="cols">
 <div class="card"><h3>Tonight</h3><img src="@N_T@" alt=""><figcaption><span class="sim">Simulation</span>. Letters drawn one by one with jumps between them.</figcaption></div>
 <div class="card"><h3>Update 1</h3><img src="@N_1@" alt=""><figcaption><span class="sim">Simulation</span>. Letters stand on the zone line and look part of it.</figcaption></div>
 <div class="card new"><h3>Revision 2</h3><img src="@N_2@" alt=""><figcaption><span class="sim">Simulation</span>. The word floats 8 mm off the zone line. Short joins link the letters along their own baseline. The word meets the zone line only by a short stem at each end.</figcaption></div>
</div>

<h2>Close-up: the middle in all three</h2>
<div class="cols">
 <div class="card"><h3>Tonight</h3><img src="@C_T@" alt=""><figcaption><span class="sim">Simulation</span>.</figcaption></div>
 <div class="card"><h3>Update 1</h3><img src="@C_1@" alt=""><figcaption><span class="sim">Simulation</span>.</figcaption></div>
 <div class="card new"><h3>Revision 2</h3><img src="@C_2@" alt=""><figcaption><span class="sim">Simulation</span>. About @CH@ mm tall, the name lifted off the circle.</figcaption></div>
</div>

<h2>What revision 2 changes</h2>
<ul>
<li>Every name floats 8 mm off its zone line, with the letters joined to each other by short lines along their own baseline. The word touches the zone line only by a short stem at its start and end. Moves between letters that cross open sand from random parts of a letter: @JUMPS@ of @PAIRS@.</li>
<li>Each picture is turned a little, if needed, so that one point of it just meets the line. It is entered and left at that point. A picture whose bottom would lie along the line is not used in that position.</li>
<li>Faces keep the way up they have now. Each is lifted 6 mm off the line and reached by a short stem, so the shoulders do not lie along the line.</li>
<li>Spacing: each zone's items are spread to make the smallest white space as big as possible. The gap from each item to its nearest neighbour is @G1MIN@ to @G1MAX@ mm in the inner ring and @G2MIN@ to @G2MAX@ mm in the outer ring. The smallest gap to a zone edge is @E1@ mm inner and @E2@ mm outer.</li>
<li>Order in every zone is still name, then face, then pictures. The whole drawing: middle name, middle face, inner ring (upper left, lower left, lower right, upper right), outer ring (top, then counter-clockwise), then any frame lines left.</li>
</ul>

<h2>Numbers</h2>
<table><thead><tr><th></th><th>Update 1</th><th>Revision 2</th></tr></thead>@NUMS@</table>

<h2>What gave a little</h2>
<ul>
<li>To get even gaps, faces came out smaller than update 1: @R1F@ mm in the inner ring and @R2F@ mm in the outer ring (update 1 had 124 and 104). Pictures stay at 75 mm. Allowing a smaller gap would give bigger faces.</li>
<li>The middle face is @CH@ mm (update 1 had 174), because the name now floats inside the circle.</li>
<li>The first line from the table centre to the middle name is a straight @LONG@ mm line, the longest single connector. It cannot be avoided because the ball starts at the centre.</li>
</ul>
</main></body></html>"""


def page_r2():
    m1 = json.load(open(os.path.join(OUT1, 'manifest.json')))
    m2 = json.load(open(os.path.join(OUT2, 'manifest.json')))
    mt = json.load(open(os.path.join(TONIGHT, 'manifest.json')))
    st = json.load(open(os.path.join(OUT1, 'tonight-connectors.json')))
    from PIL import Image
    ph = Image.open(os.path.join(ROOT, 'captures', 'sand-app', 'first-test', 'shots', '12-12-frame-lines.jpg'))
    w_, h_ = ph.size
    ph.crop((int(w_ * 0.08), 0, int(w_ * 0.72), h_)).save(os.path.join(OUT1, 'photo-crop.jpg'), quality=88)
    row3 = lambda a, b, c_, d: '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (a, b, c_, d)
    row2 = lambda a, b, c_: '<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (a, b, c_)
    glance = (row3('Drawing time', '%.1f min' % mt['total_minutes_at_40mm_s'], '%.1f min' % m1['total_minutes_at_40mm_s'], '%.1f min' % m2['total_minutes_at_40mm_s']) +
              row3('Open-sand lines', '%.2f m' % st['open_total_m'], '%.2f m' % m1['open_sand_connector_m'], '%.2f m' % m2['open_sand_connector_m']) +
              row3('Longest one', '%.0f mm' % st['longest_mm'], '%.0f mm' % m1['longest_connector_mm'], '%.0f mm' % m2['longest_connector_mm']) +
              row3('Letter jumps', '36 of 36', '0 of 42', '%d of %d' % (m2['checks']['letter_jumps_off_baseline'], m2['checks']['letter_pairs'])))
    s1, s2 = m1['sizes'], m2['sizes']
    nums = (row2('Middle face / name', '%d / %d mm' % (s1['centre_face_mm'], s1['centre_name_mm']), '%d / %d mm' % (s2['centre_face_mm'], s2['centre_name_mm'])) +
            row2('Inner ring faces / pictures', '%d / %d mm' % (s1['ring1_face_mm'], s1['ring1_pictures_mm']), '%d / %d mm' % (s2['ring1_face_mm'], s2['ring1_pictures_mm'])) +
            row2('Outer ring faces / pictures', '%d / %d mm' % (s1['ring2_face_mm'], s1['ring2_pictures_mm']), '%d / %d mm' % (s2['ring2_face_mm'], s2['ring2_pictures_mm'])) +
            row2('Slice name letters', '22 mm', '22 mm, gap between letters 8.8 mm, lifted 8 mm') +
            row2('Short joins between letters', 'none', '%d joins, %.2f m (along the baseline, not open sand)' % (m2['joins'], m2['join_m'])) +
            row2('Open-sand lines', '%.2f m in %d pieces' % (m1['open_sand_connector_m'], m1['open_sand_connector_count']), '%.2f m in %d pieces (stems and bridges)' % (m2['open_sand_connector_m'], m2['open_sand_connector_count'])) +
            row2('Zone radii', 'middle 107.0, ring 1 to 239.3, ring 2 to 355 mm', 'same; outer frame arc 349 mm, nothing beyond 350') +
            row2('Files', '%d' % len(m1['files']), '%d, each continuous, 11,500 points or fewer' % len(m2['files'])))
    ck = m2['checks']
    rep = dict(PREV_T=jpeg_uri(os.path.join(OUT1, 'preview-tonight.jpg'), 800), PREV_1=jpeg_uri(os.path.join(OUT1, 'preview-update.jpg'), 800), PREV_2=jpeg_uri(os.path.join(OUT2, 'preview-rev2.jpg'), 800),
               PHOTO=jpeg_uri(os.path.join(OUT1, 'photo-crop.jpg'), 800), N_T=jpeg_uri(os.path.join(OUT1, 'crop-name-tonight.jpg'), 800), N_1=jpeg_uri(os.path.join(OUT1, 'crop-name-update.jpg'), 800),
               N_2=jpeg_uri(os.path.join(OUT2, 'crop-name-rev2.jpg'), 800), C_T=jpeg_uri(os.path.join(OUT1, 'crop-centre-tonight.jpg'), 700), C_1=jpeg_uri(os.path.join(OUT1, 'crop-centre-update.jpg'), 700),
               C_2=jpeg_uri(os.path.join(OUT2, 'crop-centre-rev2.jpg'), 700), GLANCE=glance, NUMS=nums, CH=str(int(s2['centre_face_mm'])), JUMPS=str(ck['letter_jumps_off_baseline']), PAIRS=str(ck['letter_pairs']),
               G1MIN='%.0f' % ck['ring1_nearest_gap_min'], G1MAX='%.0f' % ck['ring1_nearest_gap_max'], G2MIN='%.0f' % ck['ring2_nearest_gap_min'], G2MAX='%.0f' % ck['ring2_nearest_gap_max'],
               E1='%.0f' % ck['ring1_edge_gap_min'], E2='%.0f' % ck['ring2_edge_gap_min'], R1F=str(s2['ring1_face_mm']), R2F=str(s2['ring2_face_mm']), LONG='%.0f' % m2['longest_connector_mm'])
    html = PAGE3
    rep.update(EXTRA)
    for k, v in rep.items():
        html = html.replace('@' + k + '@', v)
    open(os.path.join(OUT1, 'oasis-sand-update-plan.html'), 'w').write(html)
    print('page', len(html) // 1024, 'KB')


# ================================================================== REVISION 3: even gaps  (python3 tools/sand_update_plan.py rev3)
OUT3 = os.path.join(OUT1, 'rev3')
GAP3 = 9.0
OBST_GAP = 7.5
EXTRA = {}


def dist_matrix(ps):
    n = len(ps)
    Dm = np.full((n, n), 1e9)
    for i in range(n):
        for j in range(i + 1, n):
            Dm[i, j] = Dm[j, i] = ps[i]['poly'].distance(ps[j]['poly'])
    return Dm


def nbr_set(Dm):
    pr = set()
    for i in range(len(Dm)):
        for j in np.argsort(Dm[i])[:2]:
            pr.add((min(i, int(j)), max(i, int(j))))
    return sorted(pr)


def ratios(Dm, edges):
    g = [Dm[i, j] for i, j in nbr_set(Dm)]
    r_items = max(g) / min(g)
    allg = g + list(edges)
    return r_items, max(allg) / min(allg), min(allg), g


def obj3(Dm, edges):
    r, ra, mn, g = ratios(Dm, edges)
    pen = 0.0 if mn >= GAP3 else 50.0 + (GAP3 - mn)
    return max(0.0, r - 1.25) * 12.0 - mn - 0.2 * float(np.mean(g)) + pen


def zone_ratios(ps):
    Dm = dist_matrix(ps)
    return ratios(Dm, [p['edge'] for p in ps])[:3]


def pack3(zone, items, rng, start=None, tries=300, keep=8, passes=14, sub=450, obst=None):
    lines = [Line(k, zone) for k in ('outer', 'inner', 'lo', 'hi')]
    regs = {k: region(zone, k) for k in ('outer', 'inner', 'lo', 'hi')}
    zl = zone_lines(zone)
    cand = []
    for it in items:
        kinds = ('outer',) if it['kind'] == 'name' else (FACE_LINES if it['kind'] == 'face' else ('outer', 'inner', 'lo', 'hi'))
        c = poses_r2(it, zone, regs, lines, kinds, zl)
        if obst is not None:
            c = [pz for pz in c if pz['poly'].distance(obst) >= OBST_GAP]
        cand.append(c)
    n = len(items)
    inits = []
    if start is not None:
        inits.append(list(start))
    for _ in range(tries):
        placed, ok = {}, True
        for i in rng.permutation(n):
            for k in rng.permutation(len(cand[i]))[:100]:
                pz = cand[i][k]
                if all(pz['poly'].distance(q['poly']) >= GAP3 for q in placed.values()):
                    placed[i] = pz
                    break
            else:
                ok = False
                break
        if ok:
            inits.append([placed[i] for i in range(n)])
    scored = sorted(((obj3(dist_matrix(ps), [p['edge'] for p in ps]), k, ps) for k, ps in enumerate(inits)), key=lambda t: t[0])
    best = None
    for cur, _, ps in scored[:keep]:
        ps = list(ps)
        Dm = dist_matrix(ps)
        for _ in range(passes):
            moved = False
            for i in rng.permutation(n):
                bj, bs, bd = None, cur, None
                cs = cand[i] if len(cand[i]) <= sub else [cand[i][k] for k in rng.choice(len(cand[i]), sub, replace=False)]
                for pz in cs:
                    row = np.array([pz['poly'].distance(ps[j]['poly']) if j != i else 1e9 for j in range(n)])
                    if row.min() < GAP3:
                        continue
                    D2 = Dm.copy()
                    D2[i, :] = row
                    D2[:, i] = row
                    ed = [p['edge'] for p in ps]
                    ed[i] = pz['edge']
                    sc = obj3(D2, ed)
                    if sc < bs - 1e-6:
                        bj, bs, bd = pz, sc, D2
                if bj is not None:
                    ps[i], cur, Dm, moved = bj, bs, bd, True
            if not moved:
                break
        if best is None or cur < best[0]:
            best = (cur, ps)
    return best[1]


def main_r3():
    global OUT, SPLIT_AT
    SPLIT_AT = 9800
    zs, sizes = plan_r2()                      # same sizes and the revision 2 layouts (seeded, so identical)
    before = {}
    for i, z_ in enumerate(zs[1:], 1):
        before[i] = zone_ratios(z_['lay'])
    OUT = OUT3
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(31)
    rows = []
    for i, z_ in enumerate(zs[1:], 1):
        lay = pack3(z_, z_['items'], rng, start=z_['lay'])
        b, a = before[i], zone_ratios(lay)
        tries = 0
        while a[0] > 1.5 and tries < 3:
            lay = pack3(z_, z_['items'], rng, start=lay, tries=500, keep=12)
            a = zone_ratios(lay)
            tries += 1
        z_['lay'] = lay
        rows.append(dict(zone=i + 1, ring=z_['ring'], name=z_['name'], before=round(b[0], 2), after=round(a[0], 2), after_with_edges=round(a[1], 2), min_gap_after=round(a[2], 1),
                         before_min_gap=round(b[2], 1)))
        print('  zone %2d %-8s ratio before %.2f  after %.2f (with edges %.2f, smallest gap %.1f)' % (i + 1, z_['name'], b[0], a[0], a[1], a[2]), flush=True)
    FR = build_frame_r2(zs)
    run, marks, names, name_ev, titles = run_plan_r2(zs, FR)
    chk = check_r2(run, zs, name_ev)
    print(chk)
    files, man = export(run, marks, names, zs, titles)
    by_kind, vis = kinds_stats(run)
    joins = [poly_len(pl) for kd, pl in run.ev if kd == 'join']
    c = zs[0]['c']
    summ = dict(radius_mm=RT, files=man, total_points=sum(m['points'] for m in man), total_length_m=round(sum(m['path_length_m'] for m in man), 2),
                total_minutes_at_40mm_s=round(sum(m['minutes_at_40mm_s'] for m in man), 1), length_by_kind_m=by_kind,
                open_sand_connector_m=round(sum(vis) / 1000.0, 3), open_sand_connector_count=len(vis), longest_connector_mm=round(max(vis), 1),
                join_m=round(sum(joins) / 1000.0, 3), joins=len(joins), zone_gap_ratios=rows,
                sizes=dict(centre_face_mm=float(c['H']), centre_name_mm=c['name_h'], ring1_face_mm=sizes[1][0], ring1_pictures_mm=sizes[1][1],
                           ring2_face_mm=sizes[2][0], ring2_pictures_mm=sizes[2][1], name_letters_mm=22.0), checks=chk)
    json.dump(summ, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    json.dump([dict(name=z_['name'], ring=z_['ring'], H=float(z_.get('H', 0)), d=float(z_.get('d', 0)),
                    items=[dict(kind=it['kind'], line=pz['L'].kind, s=float(pz['s']), bounds=[round(v, 1) for v in pz['poly'].bounds]) for it, pz in zip(z_.get('items', []), z_.get('lay', []))])
               for z_ in zs], open(os.path.join(OUT, 'layout.json'), 'w'), indent=1)
    im = render_sim(load_xy(OUT3), 1400, 1000).convert('RGB')
    im.save(os.path.join(OUT3, 'preview-rev3.jpg'), quality=88)
    print(json.dumps({k: v for k, v in summ.items() if k not in ('files', 'zone_gap_ratios')}, indent=1))


SEC3 = """<h2>Revision 3: even spacing</h2>
<div class="cols r3two">
 <div class="card"><h3>Bill's marks on revision 2</h3><img src="@R3_MARK@" alt="Revision 2 with red and green marks"><figcaption>Red marks items too close, green marks gaps too wide.</figcaption></div>
 <div class="card new"><h3>Revision 3</h3><img src="@R3_PREV@" alt="Revision 3"><figcaption><span class="sim">Simulation</span>. Same sizes, letters, corner touches, orientation and name-first order. Only the positions along each zone moved.</figcaption></div>
</div>
<div class="card" style="margin-top:14px"><h3>Gap evenness per zone</h3>
<p>For each zone: largest neighbour gap divided by smallest neighbour gap (neighbour means each item's two nearest items). 1.0 is perfectly even, the target is 1.5 or less.</p>
<table><thead><tr><th>Zone</th><th>Revision 2</th><th>Revision 3</th><th>Smallest gap (r3)</th></tr></thead>@R3_ROWS@</table>
<p>Automatic check over the drawn paths (items at least 6 mm apart, nothing crossing or running along a zone line, pictures and faces touching the zone lines at one point at most, names not touching): @R3_V1@ violations in the first revision 3, @R3_V2@ now.</p>
<p>Worst zone: @R3_WB@ before, @R3_WA@ after. @R3_MET@ The distance from an item to the zone edges is not made equal to the gaps between items: edges stay at least @R3_E@ mm away, and many items sit farther from the far edge of the zone.</p></div>
"""


def page_r3():
    m3 = json.load(open(os.path.join(OUT3, 'manifest.json')))
    from PIL import Image
    Image.open('/tmp/claude-1000/-home-bill-dev-WillyGarage-oasis/ba7b51f6-a35b-4dc1-984c-c8c5dff5bf72/images/1.png').convert('RGB').save(os.path.join(OUT3, 'bill-marked.jpg'), quality=88)
    rows = ''.join('<tr><td>%s, %s</td><td>%.2f</td><td>%.2f</td><td>%.1f mm</td></tr>' % ('inner ring' if r['ring'] == 1 else 'outer ring', r['name'].title() + (' (zone %d)' % r['zone']), r['before'], r['after'], r['min_gap_after']) for r in m3['zone_gap_ratios'])
    wb = max(r['before'] for r in m3['zone_gap_ratios'])
    wa = max(r['after'] for r in m3['zone_gap_ratios'])
    bad = [r for r in m3['zone_gap_ratios'] if r['after'] > 1.5]
    EXTRA.update(R3_MARK=jpeg_uri(os.path.join(OUT3, 'bill-marked.jpg'), 800), R3_PREV=jpeg_uri(os.path.join(OUT3, 'preview-rev3.jpg'), 800), R3_ROWS=rows, R3_WB='%.2f' % wb, R3_WA='%.2f' % wa,
                 R3_MET='Every zone is at 1.5 or less.' if not bad else 'Zones above 1.5: %s.' % ', '.join(str(r['zone']) for r in bad),
                 R3_V1=str(m3['checks']['geometry_violations_before']), R3_V2=str(m3['checks']['geometry_violations_after']), R3_E='%.0f' % min(m3['checks']['ring1_edge_gap_min'], m3['checks']['ring2_edge_gap_min']))
    global PAGE3
    PAGE3 = PAGE3.replace('<h2>Close-up: MAVERICK in all three</h2>', SEC3 + '\n<h2>Close-up: MAVERICK in all three</h2>', 1)
    page_r2()


# ------------------------------------------------------------------ automatic check over the drawn paths
def frame_geoms():
    out = []
    a = np.linspace(0, 360, 721)
    for r in (f0, f1, RO):
        out.append(('circle %.0f' % r, LineString([P(r, x) for x in a])))
    for ang in sorted({x % 360 for x in R1A}):
        out.append(('divider %d (ring 1)' % ang, LineString([P(f0, ang), P(f1, ang)])))
    for ang in sorted({x % 360 for x in R2A}):
        out.append(('divider %d (ring 2)' % ang, LineString([P(f1, ang), P(RO, ang)])))
    return out


def zone_poly(z_):
    if z_['kind'] == 'centre':
        return Point(0, 0).buffer(f0, 128)
    a = np.linspace(z_['a_lo'], z_['a_hi'], 120)
    return Polygon([P(z_['r_out'], x) for x in a] + [P(z_['r_in'], x) for x in a[::-1]])


def geometry_check(run, zs, verbose=True):
    """Violations: items closer than 6 mm to another item; an item outside its own zone or crossing a zone line; a picture/face
    that touches the zone lines at more than one point or runs along one; a name that touches any zone line."""
    from shapely.geometry import MultiLineString
    from scipy.spatial import cKDTree as KD
    items = []
    for zi, kind, a, b in run.items:
        pls = [pl for k, pl in run.ev[a:b] if k in ('name', 'join', 'face', 'icon', 'bridge')]
        dense = np.vstack([dens(pl, 0.6) for pl in pls])
        items.append(dict(zi=zi, kind=kind, geom=MultiLineString([LineString(pl) for pl in pls]), pts=dense))
    viol = []
    lab = lambda it: '%s %s' % (zs[it['zi']]['name'] if it['zi'] else 'middle', it['kind'])
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            A, B = items[i], items[j]
            ba, bb = A['geom'].bounds, B['geom'].bounds
            if ba[0] > bb[2] + 8 or bb[0] > ba[2] + 8 or ba[1] > bb[3] + 8 or bb[1] > ba[3] + 8:
                continue
            d = A['geom'].distance(B['geom'])
            if d < 6.0:
                viol.append('too close (%.1f mm): %s and %s' % (d, lab(A), lab(B)))
    fl = frame_geoms()
    fpts = np.vstack([np.array([g.interpolate(t).coords[0] for t in np.arange(0, g.length, 0.6)]) for _, g in fl])
    ftree = KD(fpts)
    for it in items:
        z_ = zs[it['zi']]
        poly = zone_poly(z_).buffer(0.8)
        outside = [p for p in it['pts'][::2] if not poly.contains(Point(p))]
        if outside:
            viol.append('outside its zone or crossing a zone line: %s (%d points, e.g. at radius %.0f)' % (lab(it), len(outside), np.hypot(*outside[0])))
        near = it['pts'][ftree.query(it['pts'])[0] < 0.6]
        if it['kind'] == 'name':
            if len(near):
                viol.append('name touches a zone line: %s' % lab(it))
            continue
        if len(near):
            lbl = KD(near).query_ball_tree(KD(near), 3.0)
            seen, clusters = set(), []
            for k in range(len(near)):
                if k in seen:
                    continue
                stack, comp = [k], []
                while stack:
                    q = stack.pop()
                    if q in seen:
                        continue
                    seen.add(q)
                    comp.append(q)
                    stack += [r for r in lbl[q] if r not in seen]
                clusters.append(near[comp])
            if it['zi'] != 0 and len(clusters) > 1:
                viol.append('touches the zone lines at %d points: %s' % (len(clusters), lab(it)))
            for cl in clusters:
                ext = float(np.hypot(*(cl.max(0) - cl.min(0))))
                if ext > 16.0 and it['zi'] != 0:
                    viol.append('runs along a zone line (%.0f mm): %s' % (ext, lab(it)))
    if verbose:
        print('geometry check: %d violations' % len(viol))
        for v in viol:
            print('   ', v)
    return viol


def plan_fixed(fixed):
    zs = build_zones()
    for z_ in zs[1:]:
        z_['H'], z_['d'] = fixed[z_['name'], z_['ring']]
    rng = np.random.default_rng(11)
    for i, z_ in enumerate(zs[1:], 1):
        H, d = z_['H'], z_['d']
        while True:
            items = items_for(z_, H, d, 22.0)
            lay, mg = pack2(z_, items, rng, tries=300, passes=10, keep=6)
            if lay is not None and mg >= 9.0:
                break
            H, d = H - 2, d - (1 if H % 4 == 0 else 0)
        z_['H'], z_['d'], z_['items'], z_['lay'] = H, d, items, lay
    zs[0]['c'] = centre_layout_r2()
    return zs


def solve_r3(fixed=None):
    obst_polys = []
    if fixed is None:
        zs, sizes = plan_r2()
    else:
        zs = build_zones()
        for z_ in zs[1:]:
            z_['H'], z_['d'] = fixed[z_['name'], z_['ring']]
        zs[0]['c'] = centre_layout_r2()
        c_ = zs[0]['c']
        fp = z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', THR['alex'])), c_['s']) + np.array([0.0, c_['cy']])
        obst_polys = [MultiPoint(fp[::3]).convex_hull, name_poly_l(c_['line'], c_['phi_s'], c_['W'], c_['name_h'], NAME_LIFT)]
        sizes = {1: (zs[1]['H'], zs[1]['d']), 2: (zs[5]['H'], zs[5]['d'])}
    rng0 = np.random.default_rng(11)
    before = {}
    if fixed is not None:
        pass
    else:
        before = {i: zone_ratios(z_['lay']) for i, z_ in enumerate(zs[1:], 1)}
    rng = np.random.default_rng(31)
    rows = []
    order = [9, 10, 4, 1, 2, 3, 5, 6, 7, 8] if fixed is not None else list(range(1, 11))   # the tightest zones first, the others fit around them
    for i in order:
        z_ = zs[i]
        ob = unary_union(obst_polys) if fixed is not None else None
        if fixed is not None:
            H, d = z_['H'], z_['d']
            while True:
                items = items_for(z_, H, d, 22.0)
                lay0, mg = pack2(z_, items, rng0, tries=300, passes=10, keep=6, obst=ob)
                if lay0 is not None and mg >= 9.0:
                    break
                print('    zone %d: shrinking to fit (%d, %d)' % (i + 1, H, d))
                H, d = H - 2, d - 1
            z_['H'], z_['d'], z_['items'], z_['lay'] = H, d, items, lay0
            before[i] = zone_ratios(lay0)
        lay = pack3(z_, z_['items'], rng, start=z_['lay'], obst=ob)
        a = zone_ratios(lay)
        k = 0
        while a[0] > 1.5 and k < 3:
            lay = pack3(z_, z_['items'], rng, start=lay, tries=500, keep=12, obst=ob)
            a = zone_ratios(lay)
            k += 1
        att = 0
        while a[0] > 1.5 and att < 24 and fixed is not None:          # a zone that is still uneven: start again from a fresh random layout
            att += 1
            lay0, mg0 = pack2(z_, z_['items'], np.random.default_rng(100 + att), tries=300, passes=3, keep=3, obst=ob)
            if lay0 is None:
                continue
            lay2 = pack3(z_, z_['items'], rng, start=lay0, tries=600, keep=14, passes=20, sub=900, obst=ob)
            a2 = zone_ratios(lay2)
            if a2[0] < a[0]:
                lay, a = lay2, a2
        obst_polys += [pz['poly'] for pz in lay]
        z_['lay'] = lay
        rows.append(dict(zone=i + 1, ring=z_['ring'], name=z_['name'], before=round(before[i][0], 2), after=round(a[0], 2), after_with_edges=round(a[1], 2),
                         min_gap_after=round(a[2], 1), before_min_gap=round(before[i][2], 1)))
        print('  zone %2d %-8s ratio before %.2f  after %.2f (smallest gap %.1f)' % (i + 1, z_['name'], before[i][0], a[0], a[2]), flush=True)
    FR = build_frame_r2(zs)
    out = run_plan_r2(zs, FR)
    rows.sort(key=lambda r: r['zone'])
    return zs, sizes, rows, out


def main_r3():
    global OUT, SPLIT_AT, HULL_STEP, WIDTH_MAX, START_RIM
    SPLIT_AT = 9800
    START_RIM = True
    WIDTH_MAX = 12.0
    # pass 1: the revision 3 layout as it was (hull sampled every 3rd point), only checked
    HULL_STEP = 3
    zs0, sz0, rows0, (run0, *_r) = solve_r3()
    print('BEFORE the fix:')
    v_before = geometry_check(run0, zs0)
    fixed = {(z_['name'], z_['ring']): (z_['H'], z_['d']) for z_ in zs0[1:]}
    rows_before = {r['zone']: r for r in rows0}
    # pass 2: item outlines from every point; same sizes
    HULL_STEP = 1
    WIDTH_MAX = 12.0
    _ICON.clear()
    _FACE.clear()
    zs, sizes, rows, (run, marks, names, name_ev, titles) = solve_r3(fixed)
    for r in rows:
        r['before'] = rows_before[r['zone']]['before']
        r['before_min_gap'] = rows_before[r['zone']]['before_min_gap']
    print('AFTER the fix:')
    v_after = geometry_check(run, zs)
    OUT = OUT3
    os.makedirs(OUT, exist_ok=True)
    chk = check_r2(run, zs, name_ev)
    chk.update(geometry_violations_before=len(v_before), geometry_violations_after=len(v_after), geometry_violations_before_list=v_before, geometry_violations_after_list=v_after)
    print({k: v for k, v in chk.items() if 'list' not in k})
    files, man = export(run, marks, names, zs, titles)
    by_kind, vis = kinds_stats(run)
    joins = [poly_len(pl) for kd, pl in run.ev if kd == 'join']
    c = zs[0]['c']
    summ = dict(radius_mm=RT, files=man, total_points=sum(m['points'] for m in man), total_length_m=round(sum(m['path_length_m'] for m in man), 2),
                total_minutes_at_40mm_s=round(sum(m['minutes_at_40mm_s'] for m in man), 1), length_by_kind_m=by_kind,
                open_sand_connector_m=round(sum(vis) / 1000.0, 3), open_sand_connector_count=len(vis), longest_connector_mm=round(max(vis), 1),
                join_m=round(sum(joins) / 1000.0, 3), joins=len(joins), zone_gap_ratios=rows,
                sizes=dict(centre_face_mm=float(c['H']), centre_name_mm=c['name_h'], ring1_face_mm=sizes[1][0], ring1_pictures_mm=sizes[1][1],
                           ring2_face_mm=sizes[2][0], ring2_pictures_mm=sizes[2][1], name_letters_mm=22.0,
                           zone_faces={'%d %s' % (z_['ring'], z_['name']): z_['H'] for z_ in zs[1:]}), checks=chk)
    json.dump(summ, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    json.dump([dict(name=z_['name'], ring=z_['ring'], H=float(z_.get('H', 0)), d=float(z_.get('d', 0)),
                    items=[dict(kind=it['kind'], line=pz['L'].kind, s=float(pz['s']), bounds=[round(v, 1) for v in pz['poly'].bounds]) for it, pz in zip(z_.get('items', []), z_.get('lay', []))])
               for z_ in zs], open(os.path.join(OUT, 'layout.json'), 'w'), indent=1)
    im = render_sim(load_xy(OUT3), 1400, 1000).convert('RGB')
    im.save(os.path.join(OUT3, 'preview-rev3.jpg'), quality=88)
    print(json.dumps({k: v for k, v in summ.items() if k not in ('files', 'zone_gap_ratios')}, indent=1)[:1500])


# ================================================================== REVISION 4: every picture faces the way the face and name do
# base toward the outside of the table (radially), tilt at most 15 degrees, touching a zone edge at exactly one point
OUT4 = os.path.join(OUT1, 'rev4')
TILTS = (-12.0, -6.0, 0.0, 6.0, 12.0)
MAX_TILT = 15.0
TOUCH_WIDTH = 14.0


def _rot(v, deg):
    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([c * v[0] - s_ * v[1], s_ * v[0] + c * v[1]])


def poses_r4(item, zone, regs, lines, kinds, zl):
    if 'D' not in item:
        allp = np.vstack(item['strokes'])
        item['D'] = np.vstack([dens(x, 1.0) for x in item['strokes']])
        hull = MultiPoint(allp).convex_hull
        item['hv'] = np.asarray(hull.exterior.coords)[:-1]
    D, hv = item['D'], item['hv']
    out = []
    for L in lines:
        if L.kind not in kinds:
            continue
        reg = regs[L.kind].buffer(0.5)
        others = [k for k in zl if k != L.kind]
        ls = zl[L.kind]
        ltree = cKDTree(np.array([ls.interpolate(t_).coords[0] for t_ in np.arange(0, ls.length, 0.4)]))
        for s_ in L.params():
            C, uL = L.contact(s_)
            n = -uL                                          # across the line, out of the zone
            pn = np.array([-n[1], n[0]])
            for tilt in TILTS:
                g = C + uL * 30.0
                for _ in range(3):
                    din = -g / math.hypot(*g)                  # toward the table centre = "up" for the picture
                    ui = _rot(din, tilt)
                    t = np.array([ui[1], -ui[0]])
                    W = np.outer(hv[:, 0], t) + np.outer(hv[:, 1], ui)
                    e = int(np.argmax(W @ n))
                    wp = C + W - W[e]
                    poly = Polygon(wp)
                    g = np.array(poly.centroid.coords[0])
                ang = math.degrees(math.acos(max(-1.0, min(1.0, float((-ui) @ (g / math.hypot(*g)))))))
                if ang > MAX_TILT or not reg.contains(poly):
                    continue
                Pw = C + (np.outer(D[:, 0], t) + np.outer(D[:, 1], ui)) - W[e]
                near = Pw[ltree.query(Pw)[0] < 0.6]
                if len(near) == 0:
                    continue
                proj = np.sort(near @ pn)
                width = float(proj[-1] - proj[0])
                if width > TOUCH_WIDTH or (len(proj) > 1 and float(np.diff(proj).max()) > 3.0):
                    continue                                   # its bottom would lie along the zone border, or it would touch twice
                strokes_e = [x - hv[e] for x in item['strokes']]
                out.append(dict(L=L, s=s_, poly=poly, C=C, u=ui, org=C, var=dict(strokes=strokes_e, hull=None, width=width), lift=0.0, theta=tilt, angle=ang,
                                edge=min(poly.distance(zl[k]) for k in others)))
    return out


def picture_angles(zs):
    """Angle between each picture's 'down' and the outward direction at the picture's centre (degrees)."""
    res = []
    for z_ in zs[1:]:
        for it, pz in zip(z_['items'], z_['lay']):
            if it['kind'] == 'icon':
                res.append((z_['name'], float(pz['angle'])))
    return res


def main_r4():
    global OUT, SPLIT_AT, HULL_STEP, WIDTH_MAX, START_RIM, ORIENT_RADIAL, FACE_LINES
    SPLIT_AT = 9800
    START_RIM = True
    HULL_STEP = 1
    WIDTH_MAX = 12.0
    ORIENT_RADIAL = True
    FACE_LINES = ('outer',)
    lay3 = json.load(open(os.path.join(OUT3, 'layout.json')))
    fixed = {(z_['name'], z_['ring']): (z_['H'], z_['d']) for z_ in lay3 if z_['ring'] in (1, 2)}
    zs, sizes, rows, (run, marks, names, name_ev, titles) = solve_r3(fixed)
    viol = geometry_check(run, zs)
    OUT = OUT4
    os.makedirs(OUT, exist_ok=True)
    chk = check_r2(run, zs, name_ev)
    angs = picture_angles(zs)
    chk.update(geometry_violations=len(viol), geometry_violation_list=viol, picture_angle_max_deg=round(max(a for _, a in angs), 1), picture_angles=[(n_, round(a, 1)) for n_, a in angs])
    print({k: v for k, v in chk.items() if 'list' not in k and k != 'picture_angles'})
    files, man = export(run, marks, names, zs, titles)
    by_kind, vis = kinds_stats(run)
    joins = [poly_len(pl) for kd, pl in run.ev if kd == 'join']
    c = zs[0]['c']
    summ = dict(radius_mm=RT, files=man, total_points=sum(m['points'] for m in man), total_length_m=round(sum(m['path_length_m'] for m in man), 2),
                total_minutes_at_40mm_s=round(sum(m['minutes_at_40mm_s'] for m in man), 1), length_by_kind_m=by_kind,
                open_sand_connector_m=round(sum(vis) / 1000.0, 3), open_sand_connector_count=len(vis), longest_connector_mm=round(max(vis), 1),
                join_m=round(sum(joins) / 1000.0, 3), joins=len(joins), zone_gap_ratios=rows,
                sizes=dict(centre_face_mm=float(c['H']), centre_name_mm=c['name_h'], zone_faces={'%d %s' % (z_['ring'], z_['name']): z_['H'] for z_ in zs[1:]},
                           zone_pictures={'%d %s' % (z_['ring'], z_['name']): z_['d'] for z_ in zs[1:]}, name_letters_mm=22.0), checks=chk)
    json.dump(summ, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
    json.dump([dict(name=z_['name'], ring=z_['ring'], H=float(z_.get('H', 0)), d=float(z_.get('d', 0)),
                    items=[dict(kind=it['kind'], line=pz['L'].kind, s=float(pz['s']), bounds=[round(v, 1) for v in pz['poly'].bounds]) for it, pz in zip(z_.get('items', []), z_.get('lay', []))])
               for z_ in zs], open(os.path.join(OUT, 'layout.json'), 'w'), indent=1)
    im = render_sim(load_xy(OUT4), 1400, 1000).convert('RGB')
    im.save(os.path.join(OUT4, 'preview-rev4.jpg'), quality=88)
    print('rev4: %d files, %.1f min at 40 mm/s, max picture angle %.1f deg, violations %d' % (len(man), summ['total_minutes_at_40mm_s'], chk['picture_angle_max_deg'], len(viol)))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'rev4':
        main_r4()
    elif len(sys.argv) > 1 and sys.argv[1] == 'page3':
        page_r3()
    elif len(sys.argv) > 1 and sys.argv[1] == 'rev3':
        main_r3()
    elif len(sys.argv) > 1 and sys.argv[1] == 'rev2':
        main_r2()
    elif len(sys.argv) > 1 and sys.argv[1] == 'crops2':
        crops_r2()
    elif len(sys.argv) > 1 and sys.argv[1] == 'page2':
        page_r2()
    elif len(sys.argv) > 1 and sys.argv[1] == 'page':
        page()
    elif len(sys.argv) > 1 and sys.argv[1] == 'crops':
        crops()
    elif len(sys.argv) > 1 and sys.argv[1] == 'previews':
        previews(int(sys.argv[2]) if len(sys.argv) > 2 else 1400)
    else:
        main()
