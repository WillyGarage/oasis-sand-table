#!/usr/bin/env python3
"""section_comb - "stained glass" comb-path generator for the sand table. SIMULATION/PATH ONLY, never contacts a table.

The maker's showcase pictures (see HANDOFF.md, "Drawing like the maker's showcase pictures") are built from separate
SECTIONS. Each section is combed on its own with fine back-and-forth strokes; the stroke ENDS form the section's edge,
and the ball's bow wave piles up as a lip where each stroke turns. Background areas are sections too, with strokes
about 5 mm apart. This tool turns a plan of sections into ONE ball path (mm, table centre 0, y up) plus a .thr file.

PLAN FORMAT (a Python dict, JSON file, or a .py file that defines PLAN = {...}); all lengths in mm
    {
      "r_work": 114.0,            # table working radius (Mini 114)
      "shrink": 1.6,              # subject sections: stroke-end polygon = polygon shrunk by this (gap between
                                  #   neighbours = 2 x shrink, room for the lip). per-section "shrink" overrides.
      "bg_gap": 2.2,              # background keeps this far from subject sections
      "bg_shrink": 1.0,           # background sections shrink (gap between neighbouring bg sections = 2 x this)
      "keep_out": [[x, y, r]],    # optional: discs (mm) no stroke may enter (v3; e.g. the table centre)
      "sections": [ <section>, ... ]      # PAINTER'S ORDER: an earlier section wins where polygons overlap
    }
    <section> = {
      "name": "thigh",
      "kind": "subject" | "background",
      "poly": [[x,y], ...],       # outline in mm. Background: optional, intersected with the free area (disc minus
                                  #   subject sections minus earlier background sections); omit = all remaining area
      "holes": [[[x,y],...], ...],# optional
      "spacing": 2.3,             # stroke spacing, mm (maker: 1.2-2.3 subject, ~5 background)
      "mode": "angle" | "spine" | "rings",
         angle: parallel strokes, direction "angle" (degrees, 0 = +x, CCW)
         spine: strokes perpendicular to the polyline "spine" [[x,y],...], fanning round curves (ribs across a band);
                spacing is measured on the spine and widened on the outer side; on the inner side of a bend it is
                never tighter than ~0.7 x spacing. The spine is extended past its ends so end caps are combed too.
         rings: strokes are circular arcs about "center" [x,y] (concentric arcs, e.g. behind a head)
         flow:  strokes are level sets of a scalar field that follows a measured direction field ("flow": {"file":.npz,"key":..});
                strokes curve with the form, spacing opens up where the ribs fan out (tools/section_flow.py has the method)
      "phase": 0.0                # optional shift of the first stroke line, mm (angle/rings)
      "shrink": 1.6               # optional override
    }

BEHAVIOUR NOTES (v2, 2026-11-22 evening; plan format and function names unchanged):
  * section key "s_range": [s0, s1] (optional, spine mode) limits the strokes to that arclength window of the spine, so one long
    curved spine can be cut into consecutive sections that tile the band (strokes keep fanning round the whole curve).
  * travel cost: footprints still to be drawn now cost 3 (finished 100, lanes/empty 1), so travel follows section boundaries
    and avoids crossing the picture; report has travel_over_finished_where. Tiling: give shrink ~0.9 / bg_gap ~0.9 for sections
    that share edges (gap between neighbours = 2 x shrink; painter's order gives shared boundaries when designs overlap).

ROUTING: sections are drawn one after another (order = plan order within each kind; see comb(order=...)). A section is
combed as one or more chains of strokes; consecutive strokes join with a short move along the edge, and a section that
is not convex falls apart into separate chains (cells) so no stroke leaves the section. Between sections the ball
travels on a 0.5 mm cost grid where finished sections cost 100x (edges excluded), so travel runs through undrawn
sand or along the lanes between sections; each chain of strokes is tried in 2 directions and the cheapest sequence is chosen by dynamic programming. The report counts travel over finished
sections (target ~0).

OPTIONS (comb()): order = 'plan' | 'subject_first' | 'background_first' | 'greedy' | [names];
                  outline = 'none' | 'end' (after everything, trace each subject section's edge once).

CLI:  python3 tools/section_comb.py PLAN.(json|py) --out DIR [--name N] [--order subject_first] [--outline end]
Outputs DIR/N.thr, N_path.npy (mm), N_plan.png (sections coloured, path drawn, travel in red), N_report.json.
API:  res = comb(plan, order=..., outline=...); res['path'] (mm), res['pieces'], res['report'];
      save(res, plan, out_dir, name).
"""
import argparse, json, math, os, runpy, sys
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Polygon, MultiPolygon, LineString, Point
from shapely.ops import unary_union, linemerge
from skimage.graph import MCP_Geometric

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MIN_STROKE = 0.8       # mm; shorter pieces are dropped


# ---------------------------------------------------------------- geometry helpers
def _polys(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    if hasattr(g, 'geoms'):
        return [p for x in g.geoms for p in _polys(x)]
    return []


def _pieces(g, minlen=MIN_STROKE, merge=False):
    if g.is_empty:
        return []
    t = g.geom_type
    if t == 'LineString':
        gs = [g]
    elif t == 'MultiLineString':
        gs = [linemerge(g)] if merge else list(g.geoms)
        gs = [y for x in gs for y in (x.geoms if x.geom_type == 'MultiLineString' else [x])]
    elif t == 'GeometryCollection':
        gs = [x for x in g.geoms if x.geom_type == 'LineString']
    else:
        gs = []
    return [np.array(x.coords) for x in gs if x.length >= minlen]


def make_geoms(plan):
    """Stroke-end polygons. Subject: poly shrunk; earlier sections win overlaps. Background: free area clipped."""
    R = plan.get('r_work', 114.0)
    disc = Point(0, 0).buffer(R - plan.get('rim', 0.6), 160)
    shrink = plan.get('shrink', 1.6)
    bg_gap, bg_shrink = plan.get('bg_gap', 2.2), plan.get('bg_shrink', 1.0)
    secs = plan['sections']
    full = {}
    taken = Polygon()
    for s in secs:
        if s['kind'] != 'subject':
            continue
        g = Polygon(s['poly'], [h for h in s.get('holes', [])])
        if not g.is_valid:
            g = g.buffer(0)
        g = g.difference(taken)
        full[s['name']] = g
        s['_geom'] = g.buffer(-s.get('shrink', shrink)).intersection(disc)
        taken = taken.union(g)
    free = disc.difference(taken.buffer(bg_gap))
    bgt = Polygon()
    for s in secs:
        if s['kind'] != 'background':
            continue
        reg = free
        if s.get('poly'):
            reg = reg.intersection(Polygon(s['poly']).buffer(0))
        reg = reg.difference(bgt)
        bgt = bgt.union(reg)
        s['_geom'] = reg.buffer(-s.get('shrink', bg_shrink))
    for x, y, r in plan.get('keep_out', []):          # v3: no stroke through these discs (e.g. the table centre, theta jump)
        ko = Point(x, y).buffer(r, 32)
        for s in secs:
            s['_geom'] = s['_geom'].difference(ko)
    return disc


# ---------------------------------------------------------------- stroke families
def _line_pieces(ln, geom, merge=False):
    return _pieces(ln.intersection(geom), merge=merge)


def strokes_angle(sec, geom):
    a = math.radians(sec.get('angle', 0.0))
    u, n = np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])
    xs = np.vstack([np.array(p.exterior.coords) for p in _polys(geom)])
    d = xs @ n
    sp = sec['spacing']
    offs = list(np.arange(d.min() + 0.35 + sec.get('phase', 0.0), d.max() - 0.2, sp))
    if not offs or d.max() - 0.35 - offs[-1] > 0.4 * sp:
        offs.append(d.max() - 0.35)
    c = np.array(geom.centroid.coords[0])
    L = math.hypot(*(geom.bounds[2:] - np.array(geom.bounds[:2]))) + 5
    out = []
    for k, o in enumerate(offs):
        base = n * o + u * (c @ u)
        for p in _line_pieces(LineString([base - u * L, base + u * L]), geom):
            out.append(dict(line=k, pts=p, ds=sp))
    return out


def strokes_rings(sec, geom):
    c = np.array(sec['center'], float)
    xs = np.vstack([np.array(p.exterior.coords) for p in _polys(geom)])
    rr = np.hypot(*(xs - c).T)
    sp = sec['spacing']
    rmin = max(geom.distance(Point(*c)), 0.0)
    r0 = rmin + 0.35 + sec.get('phase', 0.0)
    radii = list(np.arange(r0, rr.max() - 0.2, sp))
    if not radii or rr.max() - 0.35 - radii[-1] > 0.4 * sp:
        radii.append(rr.max() - 0.35)
    out = []
    for k, r in enumerate(radii):
        n = max(24, int(2 * math.pi * r / 0.4))
        t = np.linspace(0, 2 * math.pi, n + 1)
        ring = LineString(np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t)])
        for p in _line_pieces(ring, geom, merge=True):
            out.append(dict(line=k, pts=p, ds=sp))
    return out


def _spine(pts, ext=60.0, step=0.25, sigma_mm=1.5):
    P = np.asarray(pts, float)
    seg = np.hypot(*np.diff(P, axis=0).T)
    s = np.r_[0, np.cumsum(seg)]
    n = int(s[-1] / step) + 1
    t = np.linspace(0, s[-1], n)
    Q = np.c_[np.interp(t, s, P[:, 0]), np.interp(t, s, P[:, 1])]
    Q = np.c_[gaussian_filter1d(Q[:, 0], sigma_mm / step, mode='nearest'), gaussian_filter1d(Q[:, 1], sigma_mm / step, mode='nearest')]
    t0, t1 = Q[1] - Q[0], Q[-1] - Q[-2]
    t0, t1 = t0 / np.hypot(*t0), t1 / np.hypot(*t1)
    m = int(ext / step)
    pre = Q[0] - t0 * step * np.arange(m, 0, -1)[:, None]
    post = Q[-1] + t1 * step * np.arange(1, m + 1)[:, None]
    E = np.vstack([pre, Q, post])
    tan = np.gradient(E, step, axis=0)
    tan /= np.hypot(*tan.T)[:, None]
    nrm = np.c_[-tan[:, 1], tan[:, 0]]
    head = np.unwrap(np.arctan2(tan[:, 1], tan[:, 0]))
    kap = np.gradient(head, step)
    return E, nrm, kap, step


def strokes_spine(sec, geom):
    E, nrm, kap, step = _spine(sec['spine'])
    sp = sec['spacing']
    L = math.hypot(*(np.array(geom.bounds[2:]) - np.array(geom.bounds[:2]))) + 10

    m0 = int(60.0 / step)                        # index of the spine start inside E (extension length / step)
    s_rng = sec.get('s_range')                   # optional [s0, s1] arclength window along the given spine (mm)

    def stroke_at(i):
        if s_rng is not None and not (s_rng[0] <= (i - m0) * step <= s_rng[1]):
            return None
        p, n = E[i], nrm[i]
        ps = _line_pieces(LineString([p - n * L, p + n * L]), geom)
        if not ps:
            return None
        best = min(ps, key=lambda q: LineString(q).distance(Point(*p)))
        return best

    fine = np.arange(0, len(E), 2)               # scan at 2 x step = 0.5 mm
    ok = np.array([stroke_at(i) is not None for i in fine])
    if not ok.any():
        return []
    ia, ib = fine[np.argmax(ok)], fine[len(ok) - 1 - np.argmax(ok[::-1])]
    sa, sb = ia * step + 0.3, ib * step - 0.3
    out, k, s = [], 0, sa
    while s <= sb + 1e-9:
        i = min(len(E) - 1, int(round(s / step)))
        q = stroke_at(i)
        ds = sp
        if q is not None:
            out.append(dict(line=k, pts=q, ds=sp))
            kk = kap[i]
            if abs(kk) > 1e-4:
                t = (q - E[i]) @ nrm[i]
                w_in = max(0.0, float((np.sign(kk) * t).max()))
                f = max(1.0 - abs(kk) * w_in, 0.15)
                ds = sp * min(3.0, max(1.0, 0.7 / f))
            out[-1]['ds'] = ds
            k += 1
        s += ds
    if s - ds < sb - 0.4 * sp:                   # close the far cap
        q = stroke_at(min(len(E) - 1, int(round(sb / step))))
        if q is not None:
            out.append(dict(line=k, pts=q, ds=sp))
    return out


FAMILY = dict(angle=strokes_angle, rings=strokes_rings, spine=strokes_spine)
try:                                             # v3 (2026-11-22, trex): strokes follow a direction field, see tools/section_flow.py
    import section_flow as _sf
    FAMILY['flow'] = _sf.strokes_flow
except ImportError:                              # pragma: no cover
    pass


# ---------------------------------------------------------------- chains and section routes
def build_chains(strokes, geom):
    """Zigzag chains (cells). Lines are processed in order; each open chain tail takes the nearest unclaimed stroke of
    the next line (or the one after, if a line is missing there) through its exit end, provided the short connector
    stays inside the section. A stroke nobody can reach starts a new chain, so a section that is not convex splits
    into cells and no stroke leaves it. Returns chains as lists of (stroke index, entry end 0/1)."""
    gb = geom.buffer(0.5)
    by_line = {}
    for i, s in enumerate(strokes):
        by_line.setdefault(s['line'], []).append(i)
    chains = []                 # each: list of [stroke, entry or None]
    last_line = []              # line index of each chain's last stroke
    for k in sorted(by_line):
        cands = []
        for ci, ch in enumerate(chains):
            if k - last_line[ci] > 2 or last_line[ci] == k:
                continue
            a, en = ch[-1]
            for ea in ((0, 1) if en is None else (1 - en,)):
                pa = strokes[a]['pts'][-ea]
                for b in by_line[k]:
                    for ib in (0, 1):
                        pb = strokes[b]['pts'][-ib]
                        d = math.hypot(*(pa - pb))
                        if d > 2.5 * max(strokes[a]['ds'], strokes[b]['ds']) + 1.0:
                            continue
                        if not gb.contains(LineString([pa, pb])):
                            continue
                        cands.append((d + (100 if k - last_line[ci] > 1 else 0), ci, ea, b, ib))
        cands.sort()
        used_c, used_b = set(), set()
        for d, ci, ea, b, ib in cands:
            if ci in used_c or b in used_b:
                continue
            used_c.add(ci); used_b.add(b)
            if chains[ci][-1][1] is None:
                chains[ci][-1][1] = 1 - ea
            chains[ci].append([b, ib])
            last_line[ci] = k
        for b in by_line[k]:
            if b not in used_b:
                chains.append([[b, None]])
                last_line.append(k)
    return [[(i, 0 if en is None else en) for i, en in ch] for ch in chains]


def _walk(strokes, chain):
    parts = []
    for i, en in chain:
        p = strokes[i]['pts']
        parts.append(p[::-1] if en == 1 else p)
    return np.vstack(parts)


def section_units(sec, geom):
    """Split a section into units (one per chain of strokes). Each unit has 4 candidate routes (start at either end of
    its first or last stroke), a footprint polygon (the area it combs, used to keep travel off finished work) and its
    stroke count. Returns units in a nearest-first order."""
    strokes = FAMILY[sec['mode']](sec, geom)
    if not strokes:
        return []
    sp = sec['spacing']
    chains = build_chains(strokes, geom)
    units = []
    for c in chains:
        r = _walk(strokes, c)
        routes = [r, r[::-1]]
        lines = unary_union([LineString(strokes[i]['pts']) for i, _ in c])
        fp = lines.buffer(0.55 * sp + 0.3).buffer(-0.9)
        if fp.is_empty:
            fp = lines.buffer(0.3)
        units.append(dict(name=sec['name'], kind=sec['kind'], routes=routes, fp=fp, nstrokes=len(c),
                          spacing=sp, mode=sec['mode'], geom=geom, cen=np.array(lines.centroid.coords[0])))
    # order the chains: start with the largest, then nearest centroid
    if len(units) > 1:
        left = sorted(units, key=lambda u: -u['nstrokes'])
        seq = [left.pop(0)]
        while left:
            j = int(np.argmin([math.hypot(*(u['cen'] - seq[-1]['cen'])) for u in left]))
            seq.append(left.pop(j))
        units = seq
    for k, u in enumerate(units):
        if len(units) > 1:
            u['name'] = '%s#%d' % (sec['name'], k)
    return units


# ---------------------------------------------------------------- routing between sections
class Router:
    def __init__(self, R, res=0.5):
        self.res, self.o = res, -(R + 5.0)
        self.n = int(2 * (R + 5.0) / res) + 1
        xs = self.o + res * np.arange(self.n)
        X, Y = np.meshgrid(xs, xs)
        base = np.ones((self.n, self.n), np.float32)
        base[np.hypot(X, Y) > R + 0.8] = 1000.0
        self.base = base

    def cell(self, p):
        return (int(round((p[1] - self.o) / self.res)), int(round((p[0] - self.o) / self.res)))

    def mm(self, rc):
        return np.array([self.o + rc[1] * self.res, self.o + rc[0] * self.res])

    def _fill(self, c, geoms, erode, val):
        for g in geoms:
            for p in _polys(g.buffer(-erode) if erode else g):
                m = np.zeros((self.n, self.n), np.uint8)
                pts = ((np.array(p.exterior.coords) - self.o) / self.res).round().astype(np.int32)
                cv2.fillPoly(m, [pts], 1)
                for h in p.interiors:
                    hp = ((np.array(h.coords) - self.o) / self.res).round().astype(np.int32)
                    cv2.fillPoly(m, [hp], 0)
                c[(m == 1) & (c < val)] = val

    def cost_map(self, done, erode=1.0, pending=None, pending_cost=3.0):
        """finished footprints cost 100; footprints still to be drawn cost pending_cost (3); lanes between
        sections and empty sand cost 1, so travel prefers section boundaries (v2 behaviour)."""
        c = self.base.copy()
        if pending:
            self._fill(c, pending, 0.0, pending_cost)
        self._fill(c, done, erode, 100.0)
        return c

    def _cost_map_old(self, done, erode=1.0):
        c = self.base.copy()
        for g in done:
            for p in _polys(g.buffer(-erode)):
                for ring, val in [(p.exterior, 100.0)]:
                    m = np.zeros((self.n, self.n), np.uint8)
                    pts = ((np.array(ring.coords) - self.o) / self.res).round().astype(np.int32)
                    cv2.fillPoly(m, [pts], 1)
                    for h in p.interiors:
                        hp = ((np.array(h.coords) - self.o) / self.res).round().astype(np.int32)
                        cv2.fillPoly(m, [hp], 0)
                    c[(m == 1) & (c < 100)] = 100.0
        return c

    def from_point(self, cost, a, targets):
        """-> (list of costs in mm-equivalents, function path(j))"""
        mcp = MCP_Geometric(cost, fully_connected=True)
        tg = [self.cell(t) for t in targets]
        cum, _ = mcp.find_costs([self.cell(a)], ends=tg)
        costs = [float(cum[t]) * self.res for t in tg]

        def path(j):
            rc = mcp.traceback(tg[j])
            pts = np.array([self.mm(x) for x in rc])
            if len(pts) > 2:
                k = cv2.approxPolyDP((pts * 100).astype(np.float32).reshape(-1, 1, 2), 35.0, False)[:, 0, :] / 100.0
                pts = k
            pts = pts.copy()
            pts[0], pts[-1] = a, targets[j]
            return pts
        return costs, path


# ---------------------------------------------------------------- main entry
def comb(plan, order='plan', outline='none', router_res=0.5, verbose=False):
    R = plan.get('r_work', 114.0)
    plan = json.loads(json.dumps(plan))          # private copy
    make_geoms(plan)
    secs = [s for s in plan['sections'] if not s['_geom'].is_empty]
    byname = {s['name']: s for s in secs}
    units_of = {s['name']: section_units(s, s['_geom']) for s in secs}
    secs = [s for s in secs if units_of[s['name']]]
    rt = Router(R, router_res)
    allunits = lambda ss: [u for s in ss for u in units_of[s['name']]]

    def pick_order():
        if isinstance(order, (list, tuple)):
            return allunits([byname[n] for n in order])
        subj = [s for s in secs if s['kind'] == 'subject']
        bg = [s for s in secs if s['kind'] == 'background']
        if order == 'plan':
            return allunits(secs)
        if order == 'subject_first':
            return allunits(subj + bg)
        if order == 'background_first':
            return allunits(bg + subj)
        if order == 'greedy':
            left, seq, cur = allunits(secs), [], None
            while left:
                if cur is None:
                    u, v = left[0], 0
                else:
                    cm = rt.cost_map([x['fp'] for x in seq])
                    tg = [r[0] for x in left for r in x['routes']]
                    costs, _ = rt.from_point(cm, cur, tg)
                    j = int(np.argmin(costs))
                    u, v = left[j // 2], j % 2
                left.remove(u); seq.append(u)
                cur = u['routes'][v][-1]
            return seq
        raise ValueError(order)
    seq = pick_order()

    # dynamic programming over the 2 directions of each unit
    m = len(seq)
    INF = 1e18
    best = [np.zeros(2)] + [None] * (m - 1)
    back = [None] * m
    trans = {}
    for i in range(m - 1):
        cm = rt.cost_map([u['fp'] for u in seq[:i + 1]], erode=0.0, pending=[u['fp'] for u in seq[i + 1:]])
        nxt = np.full(2, INF)
        bk = [0] * 2
        starts = [seq[i + 1]['routes'][w][0] for w in range(2)]
        for v in range(2):
            a = seq[i]['routes'][v][-1]
            costs, pathf = rt.from_point(cm, a, starts)
            trans[(i, v)] = (costs, pathf)
            for w in range(2):
                c = best[i][v] + costs[w]
                if c < nxt[w]:
                    nxt[w], bk[w] = c, v
        best[i + 1], back[i + 1] = nxt, bk
    v = int(np.argmin(best[-1])) if m else 0
    chosen = [0] * m
    for i in range(m - 1, -1, -1):
        chosen[i] = v
        if i:
            v = back[i][v]

    pieces = []                        # (kind, name, pts)
    travel_over = 0.0
    link_out = 0.0
    over_by = {}
    for i, u in enumerate(seq):
        v = chosen[i]
        if i:
            costs, pathf = trans[(i - 1, chosen[i - 1])]
            tp = pathf(v)
            pieces.append(('travel', u['name'], tp))
            fin = unary_union([x['fp'] for x in seq[:i]])
            ov = LineString(tp).intersection(fin).length if len(tp) > 1 else 0.0
            travel_over += ov
            if ov > 1.0:
                over_by['%s (arriving, after %s)' % (u['name'], seq[i - 1]['name'])] = round(ov, 1)
        r = u['routes'][v]
        link_out += _outside_len(r, u['geom'])
        pieces.append(('comb', u['name'], r))
    cur = pieces[-1][2][-1]
    n_outline = 0
    if outline == 'end':
        loops = []
        for s in secs:
            if s['kind'] == 'subject':
                for p in _polys(s['_geom']):
                    loops.append((s['name'], np.array(p.exterior.coords)[:-1]))
        cm = rt.cost_map([u['fp'] for u in seq], erode=0.0)
        fin = unary_union([u['fp'] for u in seq])
        while loops:
            tg = [lp[int(np.argmin(np.hypot(*(lp - cur).T)))] for nm, lp in loops]
            costs, pathf = rt.from_point(cm, cur, tg)
            k = int(np.argmin(costs))
            nm, lp = loops.pop(k)
            tp = pathf(k)
            pieces.append(('travel', nm, tp))
            travel_over += LineString(tp).intersection(fin).length if len(tp) > 1 else 0.0
            j = int(np.argmin(np.hypot(*(lp - tg[k]).T)))
            lp = np.roll(lp, -j, axis=0)
            pieces.append(('outline', nm, np.vstack([lp, lp[:1]])))
            cur = lp[0]
            n_outline += 1
    path = np.vstack([p[2] for p in pieces])
    rep = report(pieces, path, secs, seq, travel_over, link_out, n_outline, order, outline)
    rep['travel_over_finished_where'] = over_by
    return dict(path=path, pieces=pieces, report=rep, sections=secs, units=seq)


def _outside_len(r, geom):
    ls = LineString(r)
    return float(ls.difference(geom.buffer(0.6)).length)


def count_reversals(P, thresh=120.0):
    P = P[np.r_[True, np.hypot(*np.diff(P, axis=0).T) > 1e-3]]
    d = np.diff(P, axis=0)
    h = np.arctan2(d[:, 1], d[:, 0])
    dh = np.abs((np.diff(h) + math.pi) % (2 * math.pi) - math.pi)
    return int((dh > math.radians(thresh)).sum())


def report(pieces, path, secs, seq, travel_over, link_out, n_outline, order, outline):
    L = lambda k: float(sum(np.hypot(*np.diff(p[2], axis=0).T).sum() for p in pieces if p[0] == k))
    per = {}
    for u in seq:
        d = per.setdefault(u['name'].split('#')[0], dict(kind=u['kind'], spacing=u['spacing'], mode=u['mode'], strokes=0, chains=0))
        d['strokes'] += u['nstrokes']; d['chains'] += 1
    return dict(order=order if isinstance(order, str) else 'list', outline=outline, sections=len(secs), units=len(seq),
                strokes=int(sum(u['nstrokes'] for u in seq)),
                path_len_mm=round(float(np.hypot(*np.diff(path, axis=0).T).sum()), 1),
                comb_len_mm=round(L('comb'), 1), travel_len_mm=round(L('travel'), 1), outline_len_mm=round(L('outline'), 1),
                reversals=count_reversals(path), turns_over_60deg=count_reversals(path, 60.0),
                travel_over_finished_mm=round(travel_over, 1),
                stroke_joins_outside_section_mm=round(link_out, 1), outline_loops=n_outline, per_section=per)


# ---------------------------------------------------------------- outputs
PALETTE_S = [(244, 200, 150), (150, 200, 230), (190, 225, 160), (240, 170, 190), (205, 185, 235), (240, 225, 140),
             (160, 220, 215), (235, 190, 130)]
PALETTE_B = [(222, 232, 245), (232, 240, 222), (245, 232, 232), (240, 240, 218)]


def plan_png(res, out, size=1000, R=114.0, strokes=True, view=None):
    """view = (xmin, ymin, xmax, ymax) mm to zoom; default whole table."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = view or (-R - 3, -R - 3, R + 3, R + 3)
    sc = size / max(x1 - x0, y1 - y0)
    T = lambda p: [((x - x0) * sc, (y1 - y) * sc) for x, y in p]
    im = Image.new('RGB', (int((x1 - x0) * sc), int((y1 - y0) * sc)), (60, 60, 60))
    dr = ImageDraw.Draw(im)
    dr.ellipse(T([(-R, R), (R, -R)]) and [(-R - x0) * sc, (y1 - R) * sc, (R - x0) * sc, (y1 + R) * sc], fill=(255, 255, 255))
    si = bi = 0
    cols = {}
    for s in res['sections']:
        if s['kind'] == 'subject':
            cols[s['name']] = PALETTE_S[si % len(PALETTE_S)]; si += 1
        else:
            cols[s['name']] = PALETTE_B[bi % len(PALETTE_B)]; bi += 1
    for kind in ('background', 'subject'):
        for s in res['sections']:
            if s['kind'] == kind:
                for p in _polys(s['_geom']):
                    dr.polygon(T(np.array(p.exterior.coords)), fill=cols[s['name']], outline=(120, 120, 120))
    if strokes:
        for kind, nm, pts in res['pieces']:
            c = dict(comb=(30, 30, 30), travel=(230, 20, 20), outline=(20, 70, 220))[kind]
            dr.line(T(pts), fill=c, width=2 if kind != 'comb' else 1)
    im.save(out)


def save(res, plan, out_dir, name, r_max_step=4.0, view=None):
    import sand_relief_path as rp
    os.makedirs(out_dir, exist_ok=True)
    R = plan.get('r_work', 114.0)
    np.save(os.path.join(out_dir, name + '_path.npy'), res['path'])
    tr, near = rp.to_thr_pts(res['path'], R, max_step=r_max_step)
    rp.write_thr(os.path.join(out_dir, name + '.thr'), tr, name)
    rep = dict(res['report'])
    rep.update(thr_points=len(tr), thr_points_near_centre=near, firmware_point_limit=12000)
    if R == 114.0:
        rep['mini_minutes_est'] = round(rp.mini_minutes(tr), 1)
    rep['path_m_thr'] = round(rp.path_len_m(tr, R), 2)
    json.dump(rep, open(os.path.join(out_dir, name + '_report.json'), 'w'), indent=1)
    plan_png(res, os.path.join(out_dir, name + '_plan.png'), R=R, view=view)
    return rep, tr


def load_plan(path):
    if path.endswith('.json'):
        return json.load(open(path))
    ns = runpy.run_path(path)
    return ns['PLAN'] if 'PLAN' in ns else ns['make_plan']()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plan')
    ap.add_argument('--out', required=True)
    ap.add_argument('--name', default=None)
    ap.add_argument('--order', default='plan')
    ap.add_argument('--outline', default='none')
    a = ap.parse_args()
    plan = load_plan(a.plan)
    res = comb(plan, order=a.order, outline=a.outline)
    name = a.name or os.path.splitext(os.path.basename(a.plan))[0]
    rep, _ = save(res, plan, a.out, name)
    print(json.dumps({k: v for k, v in rep.items() if k != 'per_section'}, indent=1))


if __name__ == '__main__':
    main()
