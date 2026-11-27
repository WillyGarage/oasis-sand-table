#!/usr/bin/env python3
"""sand_relief_path - one continuous ball path that draws a picture as bas-relief by negative space.

The subject is sand LEFT STANDING (a raised plateau). Everything else is carved:
  * an outline groove half a groove outside every subject shape (it piles a bright crest on the plateau edge),
  * a rim circle,
  * background lines (arcs about a focus, straight parallel lines, or any scalar field's iso-lines) that END at the
    outline groove or the rim,
  * optional rib regions inside the subject (finer parallel lines: a second, mid tone) with their own frame groove,
  * interior detail lines (single grooves on the plateau).

Routing: every frame loop (outline, rim, rib frame), fill line and detail line is an edge of a graph whose nodes are
the points where lines meet. Odd nodes are paired by shortest retraces along existing grooves, and an Euler circuit
from a rim node gives ONE closed path that starts and ends at the rim. Nothing moves over untouched sand except the
'links' needed when a part is not reachable along grooves; each one is reported (length, and whether it crosses the
raised subject).

Coordinates: mm, origin at the table centre, y up. Output .thr: theta/rho as tools/thrcommon.py (rho = r / r_work).

API (used by tools/relief_showcase.py, tools/relief_testcard.py, tools/relief_faces.py):
    cv = Canvas(r_work=114, groove=5.3, res=0.25)
    plan = cv.plan(subject_mask, fills=[Fill(...)], details=[polyline_mm, ...], ribs=[Fill(...)])
    plan['pts_xy'], plan['thr'], plan['report']
"""
import heapq, math, os, sys
import numpy as np
import cv2
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GROOVE_MINI = 5.3          # measured visible groove width on the Mini, mm (one pass on flat sand)


# ---------------------------------------------------------------- small geometry helpers
def resample(pts, step, closed=False):
    pts = np.asarray(pts, float)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    if d[-1] < 1e-9:
        return pts[:1].copy()
    n = max(2, int(math.ceil(d[-1] / step)) + 1)
    s = np.linspace(0, d[-1], n)
    out = np.c_[np.interp(s, d, pts[:, 0]), np.interp(s, d, pts[:, 1])]
    return out[:-1] if closed else out


def smooth_poly(pts, sigma_pts, closed):
    if sigma_pts <= 0 or len(pts) < 5:
        return pts
    mode = 'wrap' if closed else 'nearest'
    out = np.c_[ndi.gaussian_filter1d(pts[:, 0], sigma_pts, mode=mode), ndi.gaussian_filter1d(pts[:, 1], sigma_pts, mode=mode)]
    if not closed:                    # keep the end points where they were
        out[0], out[-1] = pts[0], pts[-1]
    return out


def poly_len(pts, closed=False):
    pts = np.asarray(pts, float)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    return float(np.hypot(*np.diff(pts, axis=0).T).sum())


def offset_open(pts, d):
    """Offset an open polyline sideways by d (left of the direction of travel)."""
    pts = np.asarray(pts, float)
    t = np.gradient(pts, axis=0)
    t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
    return pts + d * np.c_[-t[:, 1], t[:, 0]]


class Fill:
    """A family of carved lines inside a region.
    kind: 'arcs' (focus=(x, y) mm), 'lines' (angle=deg, direction of the lines), 'rays' (focus, r_ref: spacing is
    `pitch` at distance r_ref), 'offset' (lines parallel to the region outline), 'field' (phi: a scalar grid).
    mask: where the lines may go (bool grid; for the background None = everything outside the subject)."""
    def __init__(self, kind='arcs', pitch=7.0, mask=None, focus=(0.0, 0.0), angle=0.0, r_ref=50.0, phase=0.5,
                 phi=None, name='fill', min_len=None, smooth=1.0, wave=None):
        self.kind, self.pitch, self.mask, self.focus, self.angle = kind, pitch, mask, focus, angle
        self.r_ref, self.phase, self.phi, self.name, self.min_len, self.smooth = r_ref, phase, phi, name, min_len, smooth
        self.wave = wave           # (amplitude mm, wavelength mm): wiggle the lines (hair strands, beard)


# ---------------------------------------------------------------- canvas: rasters <-> mm
class Canvas:
    def __init__(self, r_work=114.0, groove=GROOVE_MINI, res=0.25):
        self.R, self.g, self.res = float(r_work), float(groove), float(res)
        self.N = int(math.ceil(2 * (self.R + 2) / res))
        self.c = self.N / 2.0
        jj, ii = np.meshgrid(np.arange(self.N), np.arange(self.N))
        self.X = (jj + 0.5 - self.c) * res
        self.Y = (self.c - ii - 0.5) * res
        self.Rg = np.hypot(self.X, self.Y)

    # conversions
    def to_px(self, pts):
        pts = np.asarray(pts, float)
        return np.c_[self.c + pts[:, 0] / self.res - 0.5, self.c - pts[:, 1] / self.res - 0.5]

    def to_mm(self, px):
        px = np.asarray(px, float)
        return np.c_[(px[:, 0] + 0.5 - self.c) * self.res, (self.c - px[:, 1] - 0.5) * self.res]

    def disc(self, r=None):
        return self.Rg <= (self.R if r is None else r)

    def fill_polys(self, polys, mask=None, value=1):
        """Rasterise closed polylines (mm) with the even-odd rule (holes work)."""
        m = np.zeros((self.N, self.N), np.uint8) if mask is None else mask.astype(np.uint8)
        arr = [np.round(self.to_px(p) * 16).astype(np.int32) for p in polys if len(p) >= 3]
        if arr:
            cv2.fillPoly(m, arr, int(value), lineType=cv2.LINE_8, shift=4)
        return m.astype(bool)

    def stroke(self, polyline, width, mask=None):
        m = np.zeros((self.N, self.N), np.uint8) if mask is None else mask.astype(np.uint8)
        p = np.round(self.to_px(polyline) * 16).astype(np.int32)
        cv2.polylines(m, [p], False, 1, max(1, int(round(width / self.res))), lineType=cv2.LINE_8, shift=4)
        return m.astype(bool)

    def dist_in(self, mask):
        """Distance (mm) from each pixel inside mask to the nearest pixel outside."""
        return cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5) * self.res

    def disk_k(self, diam_mm):
        k = max(1, int(round(diam_mm / self.res))) | 1
        return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    def loops(self, mask, sigma=1.2, step=0.5, min_len=None):
        """Smooth closed boundary loops (mm) of a mask. Returns list of (N,2) arrays."""
        cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        out = []
        min_len = 2.5 * self.g if min_len is None else min_len
        for c in cs:
            c = c[:, 0, :].astype(float)
            if len(c) < 8:
                continue
            p = resample(self.to_mm(c), self.res, closed=True)
            p = smooth_poly(p, sigma / self.res, True)
            if poly_len(p, True) < min_len:
                continue
            out.append(resample(p, step, closed=True))
        return out

    # ------------------------------------------------------------ simplify a subject to what the ball can make
    def simplify(self, subject, min_part=2.0, min_gap=1.2):
        """Remove raised parts narrower than min_part grooves and fill background gaps narrower than min_gap grooves
        (the ball cannot enter them, so they stay raised)."""
        s = subject.astype(np.uint8)
        s = cv2.morphologyEx(s, cv2.MORPH_CLOSE, self.disk_k(min_gap * self.g))
        s = cv2.morphologyEx(s, cv2.MORPH_OPEN, self.disk_k(min_part * self.g))
        return s.astype(bool)

    # ------------------------------------------------------------ line families
    def phi(self, f, region):
        X, Y = self.X, self.Y
        if f.kind == 'arcs':
            return np.hypot(X - f.focus[0], Y - f.focus[1])
        if f.kind == 'lines':
            a = math.radians(f.angle)
            return -X * math.sin(a) + Y * math.cos(a)
        if f.kind == 'rays':          # angle measured from straight down, cut straight up from the focus
            ang = np.arctan2(X - f.focus[0], -(Y - f.focus[1]))
            return ang * f.r_ref
        if f.kind == 'offset':
            return self.dist_in(region)
        if f.kind == 'field':
            return f.phi
        raise ValueError(f.kind)

    def fill_lines(self, f, allowed):
        import contourpy
        phi = self.phi(f, allowed).astype(np.float64)
        inner = cv2.erode(allowed.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        if f.kind == 'rays':       # keep away from the cut above the focus
            inner &= ~((np.abs(self.X - f.focus[0]) < 2 * self.res + 0.3) & (self.Y > f.focus[1]))
        if not inner.any():
            return []
        lo, hi = phi[inner].min(), phi[inner].max()
        k0 = math.floor(lo / f.pitch - f.phase) - 1
        levels = [(k + f.phase) * f.pitch for k in range(k0, int(hi / f.pitch) + 2)]
        levels = [l for l in levels if lo < l < hi]
        if f.kind == 'offset':
            levels = [l for l in levels if l >= f.pitch * 0.5]
        gen = contourpy.contour_generator(z=np.ma.array(phi, mask=~inner), line_type='Separate', name='serial')
        out = []
        min_len = f.min_len if f.min_len is not None else 1.0 * self.g
        for lv in levels:
            for ln in gen.lines(lv):
                if len(ln) < 3:
                    continue
                p = self.to_mm(ln)
                closed = bool(np.hypot(*(p[0] - p[-1])) < 1e-6)
                if closed:
                    p = p[:-1]
                p = resample(p, 0.5 * self.res, closed)
                p = smooth_poly(p, f.smooth / (0.5 * self.res), closed)
                if f.wave and len(p) >= 3:
                    amp, wl = f.wave
                    s = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
                    p = offset_open(p, 0) + 0  # copy
                    t = np.gradient(p, axis=0); t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
                    w = amp * np.sin(2 * math.pi * s / wl)
                    if not closed:
                        w *= np.clip(np.minimum(s, s[-1] - s) / (0.5 * wl), 0, 1)
                    p = p + w[:, None] * np.c_[-t[:, 1], t[:, 0]]
                if poly_len(p, closed) < min_len:
                    continue
                out.append((resample(p, 0.5, closed), closed))
        return out

    # ------------------------------------------------------------ the whole plan
    def plan(self, subject, fills, details=(), ribs=(), simplify=True, start_angle=-90.0, frame_sigma=1.2,
             detail_snap=None, extra_frames=(), log=print):
        """subject: bool grid (raised sand). fills: background Fill list (each with its own mask, or mask=None for
        'all background'); several fills split the background (their frames meet along their common edge).
        ribs: Fill list inside the subject (mask required). details: open polylines (mm) or ('closed', pts)."""
        g = self.g
        disc = self.disc()
        subj = self.simplify(subject & disc) if simplify else (subject & disc)
        dout = cv2.distanceTransform((~subj).astype(np.uint8), cv2.DIST_L2, 5) * self.res
        bg_allowed = (dout >= g / 2) & disc
        elems = []                    # dict(pts, closed, kind, name)

        def add(pts, closed, kind, name):
            elems.append(dict(pts=np.asarray(pts, float), closed=closed, kind=kind, name=name))
            return len(elems) - 1

        frame_ids = []                # (elem id, owner fill index or 'bg')
        regions = []
        # background fills: each region's allowed set = bg_allowed & its mask; frames = its boundary loops
        for fi, f in enumerate(fills):
            m = bg_allowed if f.mask is None else (bg_allowed & f.mask)
            m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, self.disk_k(0.6 * g)).astype(bool)
            loops = self.loops(m, sigma=frame_sigma)
            m2 = self.fill_polys(loops)
            regions.append((f, m2, [add(l, True, 'frame', f.name + ' frame') for l in loops]))
        # rib fills inside the subject: allowed = mask shrunk by half a groove
        for f in ribs:
            m = (f.mask & subj)
            m = self.dist_in(m) >= g / 2
            m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, self.disk_k(0.8 * g)).astype(bool)
            loops = self.loops(m, sigma=frame_sigma)
            m2 = self.fill_polys(loops)
            regions.append((f, m2, [add(l, True, 'ribframe', f.name + ' frame') for l in loops]))
        for pts in extra_frames:
            add(pts, True, 'frame', 'extra')
        # frames of neighbouring background regions run side by side along their common edge: join them there
        # with short pieces of groove (both sides are carved, so these never cross untouched sand)
        joints = []
        fr = [i for i, el in enumerate(elems) if el['kind'] == 'frame']
        for ai in range(len(fr)):
            for bi in range(ai + 1, len(fr)):
                A, B = elems[fr[ai]]['pts'], elems[fr[bi]]['pts']
                d, k = cKDTree(B).query(A)
                close = d < 0.8 * g
                if not close.any():
                    continue
                # one joint per stretch of closeness
                idx = np.nonzero(close)[0]
                runs = np.split(idx, np.nonzero(np.diff(idx) > 4)[0] + 1)
                for r_ in runs:
                    m = r_[np.argmin(d[r_])]
                    joints.append((fr[ai], int(m), fr[bi], int(k[m])))
        # fill lines
        attach = {}                   # (eid, vertex) -> list of (eid2, vertex2) it is joined to
        trees = {}

        def tree(eid):
            if eid not in trees:
                trees[eid] = cKDTree(elems[eid]['pts'])
            return trees[eid]

        def nearest_frame(p, fids):
            best = (1e18, None, None)
            for e in fids:
                d, k = tree(e).query(p)
                if d < best[0]:
                    best = (d, e, int(k))
            return best

        joins = []                    # ((e1, v1), (e2, v2))
        for ea, va, eb, vb in joints:
            a, b = elems[ea]['pts'][va], elems[eb]['pts'][vb]
            je = add(resample(np.vstack([a, b]), 0.5), False, 'frame', 'joint')
            joins.append(((je, 0), (ea, va)))
            joins.append(((je, len(elems[je]['pts']) - 1), (eb, vb)))
        n_fill = 0
        for f, m2, fids in regions:
            for pts, closed in self.fill_lines(f, m2):
                e = add(pts, closed, 'fill', f.name)
                n_fill += 1
                if closed or not fids:
                    continue
                for end, v in ((pts[0], 0), (pts[-1], len(pts) - 1)):
                    d, fe, k = nearest_frame(end, fids)
                    if d < 3 * self.res + 1.0:
                        elems[e]['pts'][v] = elems[fe]['pts'][k]
                        joins.append(((e, v), (fe, k)))
        # details: snap ends that come close to any groove (frame or fill) by extending them along their own line
        snap = detail_snap if detail_snap is not None else 1.7 * g
        all_frames = [i for i, el in enumerate(elems) if el['kind'] in ('frame', 'ribframe')]
        for di, d in enumerate(details):
            closed = isinstance(d, tuple) and d[0] == 'closed'
            pts = np.asarray(d[1] if closed else d, float)
            pts = resample(pts, 0.5, closed)
            if closed:
                add(pts, True, 'detail', 'detail%d' % di)
                continue
            ends = []
            for side in (0, 1):
                end = pts[0] if side == 0 else pts[-1]
                dd, fe, k = nearest_frame(end, all_frames)
                if fe is not None and dd <= snap:
                    q = elems[fe]['pts'][k]
                    ext = resample(np.vstack([end, q]), 0.5)
                    pts = np.vstack([ext[::-1][:-1], pts]) if side == 0 else np.vstack([pts, ext[1:]])
                    ends.append((side, fe, k))
            e = add(pts, False, 'detail', 'detail%d' % di)
            for side, fe, k in ends:
                joins.append(((e, 0 if side == 0 else len(pts) - 1), (fe, k)))
        # ---- connectivity between elements; links (straight moves over untouched sand) where needed
        parent = list(range(len(elems)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        for (e1, _), (e2, _) in joins:
            parent[find(e1)] = find(e2)
        # crossing elements also connect (a detail crossing a frame or fill line meets it)
        sub = [np.asarray(el['pts'])[::2] for el in elems]
        for i in range(len(elems)):
            if elems[i]['kind'] not in ('detail',):
                continue
            for j in range(len(elems)):
                if i == j or find(i) == find(j):
                    continue
                d, k = cKDTree(sub[j]).query(sub[i])
                if d.min() < 0.6:
                    a = int(np.argmin(d)) * 2
                    b = int(k[int(np.argmin(d))]) * 2
                    b = min(b, len(elems[j]['pts']) - 1); a = min(a, len(elems[i]['pts']) - 1)
                    joins.append(((i, a), (j, b)))
                    parent[find(i)] = find(j)
        links = []
        while True:
            comps = {}
            for i in range(len(elems)):
                comps.setdefault(find(i), []).append(i)
            if len(comps) <= 1:
                break
            keys = list(comps)
            # MST step (Boruvka-ish): connect the component of the rim to its nearest other component, repeat
            pts_c = {}
            for c in keys:
                P, idx = [], []
                for e in comps[c]:
                    pp = elems[e]['pts']
                    P.append(pp); idx += [(e, v) for v in range(len(pp))]
                pts_c[c] = (np.vstack(P), idx)
            best = (1e18, None)
            base = find(0)
            tb = cKDTree(pts_c[base][0])
            for c in keys:
                if c == base:
                    continue
                d, k = tb.query(pts_c[c][0])
                m = int(np.argmin(d))
                if d[m] < best[0]:
                    best = (float(d[m]), (pts_c[base][1][int(k[m])], pts_c[c][1][m]))
            (ea, va), (eb, vb) = best[1]
            a, b = elems[ea]['pts'][va], elems[eb]['pts'][vb]
            lp = resample(np.vstack([a, b]), 0.5)
            le = add(lp, False, 'link', 'link')
            parent.append(le)
            joins.append(((le, 0), (ea, va)))
            joins.append(((le, len(lp) - 1), (eb, vb)))
            parent[find(le)] = find(ea)
            parent[find(eb)] = find(ea)
            # does it cross raised sand?
            pp = self.to_px(lp).astype(int)
            pp = np.clip(pp, 0, self.N - 1)
            on = subj[pp[:, 1], pp[:, 0]]
            links.append(dict(length=best[0], over_subject_mm=float(on.sum() * 0.5), a=a.tolist(), b=b.tolist(),
                              between=(elems[ea]['name'], elems[eb]['name'])))
        # ---- graph
        nodes = {}
        uf = {}

        def key(e, v):
            n = len(elems[e]['pts'])
            return (e, v % n) if elems[e]['closed'] else (e, v)

        def kf(a):
            while uf.setdefault(a, a) != a:
                uf[a] = uf[uf[a]]
                a = uf[a]
            return a
        att = {i: set() for i in range(len(elems))}
        for (e1, v1), (e2, v2) in joins:
            a, b = key(e1, v1), key(e2, v2)
            att[e1].add(a[1]); att[e2].add(b[1])
            uf[kf(a)] = kf(b)
        for i, el in enumerate(elems):
            if not el['closed']:
                att[i] |= {0, len(el['pts']) - 1}
            elif not att[i]:
                att[i].add(0)
        # rim start node: on the outermost frame, nearest to start_angle
        sa = math.radians(start_angle)
        target = np.array([self.R * math.cos(sa), self.R * math.sin(sa)])
        bestd = (1e18, None)
        for i, el in enumerate(elems):
            if el['kind'] == 'frame':
                d, k = tree(i).query(target)
                if d < bestd[0]:
                    bestd = (d, (i, int(k)))
        se, sv = bestd[1]
        att[se].add(sv)
        edges = []                    # (u, v, pts)
        for i, el in enumerate(elems):
            P = el['pts']; n = len(P)
            vs = sorted(att[i])
            if el['closed']:
                for a_i, a in enumerate(vs):
                    b = vs[(a_i + 1) % len(vs)]
                    if len(vs) == 1:
                        seg = np.vstack([P[a:], P[:a + 1]])
                    elif b > a:
                        seg = P[a:b + 1]
                    else:
                        seg = np.vstack([P[a:], P[:b + 1]])
                    edges.append([kf(key(i, a)), kf(key(i, b)), seg, el['kind']])
            else:
                for a, b in zip(vs[:-1], vs[1:]):
                    edges.append([kf(key(i, a)), kf(key(i, b)), P[a:b + 1], el['kind']])
        nid = {}
        for u, v, _, _ in edges:
            nid.setdefault(u, len(nid)); nid.setdefault(v, len(nid))
        start = nid[kf(key(se, sv))]
        E = [(nid[u], nid[v], p, k, poly_len(p)) for u, v, p, k in edges]
        nn = len(nid)
        adj = [[] for _ in range(nn)]
        for ei, (u, v, p, k, L) in enumerate(E):
            adj[u].append((v, ei)); adj[v].append((u, ei))
        deg = np.zeros(nn, int)
        for u, v, *_ in E:
            deg[u] += 1; deg[v] += 1
        odd = [i for i in range(nn) if deg[i] % 2]
        # pair odd nodes by greedy nearest retrace (Dijkstra with early stop)
        matched = np.zeros(nn, bool)
        is_odd = np.zeros(nn, bool); is_odd[odd] = True
        dup = []
        for u in odd:
            if matched[u]:
                continue
            dist = {u: 0.0}; prev = {}
            pq = [(0.0, u)]
            found = None
            while pq:
                d, x = heapq.heappop(pq)
                if d > dist.get(x, 1e18):
                    continue
                if x != u and is_odd[x] and not matched[x]:
                    found = x
                    break
                for y, ei in adj[x]:
                    nd = d + E[ei][4]
                    if nd < dist.get(y, 1e18):
                        dist[y] = nd; prev[y] = (x, ei); heapq.heappush(pq, (nd, y))
            if found is None:
                raise RuntimeError('graph not connected')
            matched[u] = matched[found] = True
            x = found
            while x != u:
                px_, ei = prev[x]
                dup.append(ei)
                x = px_
        retrace = sum(E[ei][4] for ei in dup)
        allE = list(range(len(E))) + dup
        adj2 = [[] for _ in range(nn)]
        for slot, ei in enumerate(allE):
            u, v = E[ei][0], E[ei][1]
            adj2[u].append((v, slot)); adj2[v].append((u, slot))
        used = np.zeros(len(allE), bool)
        ptr = [0] * nn
        # Hierholzer
        stack = [(start, None, None)]
        circuit = []
        while stack:
            x, slot, frm = stack[-1]
            while ptr[x] < len(adj2[x]) and used[adj2[x][ptr[x]][1]]:
                ptr[x] += 1
            if ptr[x] == len(adj2[x]):
                stack.pop()
                if slot is not None:
                    circuit.append((slot, frm, x))
            else:
                y, s2 = adj2[x][ptr[x]]
                used[s2] = True
                stack.append((y, s2, x))
        circuit.reverse()
        path = [E[allE[circuit[0][0]]][2][0] if E[allE[circuit[0][0]]][0] == circuit[0][1] else E[allE[circuit[0][0]]][2][-1]]
        kinds_len = {}
        for slot, frm, to in circuit:
            u, v, p, k, L = E[allE[slot]]
            seg = p if u == frm else p[::-1]
            if u == v and u == frm:
                seg = p
            path.append(seg[1:] if len(seg) > 1 else seg)
            kinds_len[k] = kinds_len.get(k, 0.0) + L
        P = np.vstack(path)
        total = poly_len(P)
        rep = dict(length_m=total / 1000, retrace_m=retrace / 1000, fill_lines=n_fill,
                   frames=sum(1 for e in elems if e['kind'] in ('frame', 'ribframe')),
                   details=sum(1 for e in elems if e['kind'] == 'detail'),
                   links=len(links), links_mm=round(sum(l['length'] for l in links), 1),
                   links_over_subject=[dict(mm=round(l['length'], 1), over_raised_mm=round(l['over_subject_mm'], 1),
                                            between=l['between']) for l in links if l['over_subject_mm'] > 0.5],
                   by_kind_m={k: round(v / 1000, 2) for k, v in kinds_len.items()},
                   odd_nodes=len(odd))
        return dict(pts_xy=P, subject=subj, report=rep, elems=elems, links=links)


# ---------------------------------------------------------------- output
def to_thr_pts(P, r_work, tol=0.05, max_dth=math.radians(1.5), max_step=1.0, rho_min=0.012):
    """mm path -> theta/rho rows. Removes redundant points (Douglas-Peucker in mm, tol), then densifies so no
    move turns more than max_dth or is longer than max_step mm. Reports points closer to the centre than rho_min."""
    P = np.asarray(P, float)
    P = P[np.r_[True, np.hypot(*np.diff(P, axis=0).T) > 1e-6]]
    keep = cv2.approxPolyDP(np.round(P * 100).astype(np.int32).reshape(-1, 1, 2), tol * 100, False)[:, 0, :] / 100.0
    out = [keep[0]]
    for q in keep[1:]:
        a = out[-1]
        ta, tb = math.atan2(a[1], a[0]), math.atan2(q[1], q[0])
        dth = abs((tb - ta + math.pi) % (2 * math.pi) - math.pi)
        n = max(1, int(math.ceil(max(math.hypot(*(q - a)) / max_step, dth / max_dth))))
        for i in range(1, n + 1):
            out.append(a + (q - a) * i / n)
    out = np.array(out)
    r = np.hypot(out[:, 0], out[:, 1]) / r_work
    th = np.unwrap(np.arctan2(out[:, 1], out[:, 0]))
    near = int((r < rho_min).sum())
    return np.c_[th, np.clip(r, 0, 1)], near


def write_thr(path, tr, title='relief'):
    with open(path, 'w') as f:
        f.write('# %s (tools/sand_relief_path.py)\n' % title)
        for th, r in tr:
            f.write('%.5f %.5f\n' % (th, r))


def mini_minutes(tr):
    """Estimated Mini drawing time with the firmware speed model of tools/mini_portrait_timing.py and the v8.9
    constants used by tools/bg_erase.py (vmax 400, junction 200, accel 200, corner 2000)."""
    from mini_portrait_timing import elapsed_seconds
    status = dict(vmax=400, vj=200, acc=200, accc=2000,
                  cal=dict(rmax=0.88, l=0.465, a=5.59e-4, a1=3.045e-4, b1=6.09e-4, b2=1.10e-4))
    return float(elapsed_seconds(np.asarray(tr, float), status)[-1]) / 60


def path_len_m(tr, r_work):
    tr = np.asarray(tr, float)
    x, y = tr[:, 1] * np.cos(tr[:, 0]), tr[:, 1] * np.sin(tr[:, 0])
    return float(np.hypot(np.diff(x), np.diff(y)).sum() * r_work / 1000)


def overlay(cv, plan, out, size=900):
    """Debug picture: subject grey, path coloured by kind, links red."""
    from PIL import Image, ImageDraw
    img = np.full((cv.N, cv.N, 3), 255, np.uint8)
    img[plan['subject']] = (215, 215, 205)
    img[~cv.disc(cv.R + 3)] = (60, 60, 60)
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    col = dict(frame=(30, 90, 200), ribframe=(150, 60, 160), fill=(90, 90, 90), detail=(20, 150, 60), link=(230, 20, 20))
    for el in plan['elems']:
        p = cv.to_px(el['pts'])
        pts = [tuple(q) for q in p] + ([tuple(p[0])] if el['closed'] else [])
        dr.line(pts, fill=col[el['kind']], width=3 if el['kind'] == 'link' else 1)
    im.resize((size, size), Image.LANCZOS).save(out)


if __name__ == '__main__':
    # tiny demo: a disc subject with arcs
    cv = Canvas()
    subj = np.hypot(cv.X - 10, cv.Y) < 40
    pl = cv.plan(subj, [Fill('arcs', 7.0, focus=(10, 0))], details=[np.array([[-20, 0], [40, 0]])])
    print(pl['report'])
