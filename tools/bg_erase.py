#!/usr/bin/env python3
"""bg_erase - erase only what a portrait will not draw over, from the rim inward, then draw the portrait. One file.

Bill's idea (2026-11-20): "erase from the outside, and only erase what won't be drawn over by the portrait".

  bg_erase.py PORTRAIT.thr -o OUT.thr [--pitch 0.02] [--inside-pitch 0.06|0] [--islands|--no-islands]
  bg_erase.py PORTRAIT.thr --report          # timings of every option, no file written

  from bg_erase import combine, background_erase
  pts, info = combine(portrait_pts, pitch=0.02, inside_pitch=0, islands=True)

HOW IT WORKS
1. The portrait's own path is rasterised with the measured groove width (0.042 of the radius) on a 0.004 grid:
   'covered' = sand the portrait will groove. Closing (one groove) + hole filling gives the silhouette. Pockets
   inside the silhouette the path never touches and wider than one groove (an opening by half a groove) are the
   islands: eyes, smile, lenses.
2. Background = the disc minus the silhouette shrunk by one groove (so the erase runs one groove under the
   portrait's outer edge and no crescent of old sand survives between them).
3. Rings at rho = 1, 1-p, 1-2p, ... (p = pitch). Each ring is cut by the region into angular intervals. Intervals
   on neighbouring rings that overlap are linked; a chain with no split or merge is a cell. A cell is swept
   back and forth (boustrophedon): arc along ring k, short radial step, arc back along ring k+1. A ring that is not
   cut at all is a plain spiral turn. Where the next ring's arc is shorter the ball retraces its own fresh groove
   before stepping down, so it never enters clean sand.
4. Between cells (the region splits around the head, a pocket by the neck) the ball travels by a shortest path
   (Dijkstra on a 0.008 grid) that may only use: sand the portrait will draw over (covered, shrunk by half a groove
   so the travel groove is hidden), the rim (rho = 1, which ring 0 already grooved), and not-yet-erased sand of
   the current or a later pass. Finished background is forbidden (a heavy penalty; the report counts any use).
   The next cell is the cheapest one whose outer neighbours are all finished, so the work moves rim -> centre.
5. Optional inside passes: islands=True sweeps each island plus one groove into its outline at the fine pitch;
   inside_pitch>0 sweeps the whole silhouette (minus the islands if they are on) coarsely. Then one last travel,
   again only through covered sand or along the rim, to the portrait's first point, and the portrait unchanged.
6. Every move is split so consecutive points are under 0.02 of the radius and 0.05 rad apart; theta stays
   cumulative; the ball keeps rho >= 0.015 on everything this tool adds. If the file passes 12000 points the
   erase part is re-split with 'thin' rules: a move whose rho barely changes (an arc or a spiral turn, |drho| <=
   0.002 per step) is split by angle only (0.05 rad). That is exact on this table: it interpolates linearly in
   motor space, which is linear in (theta, elbow angle), so a constant-rho move stays on its circle whatever
   the step.

TIME: est_minutes() is thrcommon's estimate (the one the portraits are quoted with; it read 8.4 min for Lek, the
table took about 8). motor_minutes() follows the firmware's kinematics (steps of the faster motor / speed) and gives
17.0 min for the table's own 50-turn erase at 550 steps/s, as measured. The background pass is part of a drawing
file, so it runs at drawing speed (400 steps/s), not erase speed.

CAUTION (firmware v8.9, not changed here): a stored drawing played with erase_first=0 starts from whichever end is
nearer the ball in rho. A combined file starts at rho 1 and ends where the portrait ends; if the ball sits nearer
that end, the table would draw the portrait first and then erase over it. Send it with erase=0 AND with the ball
at the rim (or add a no-reverse flag to the firmware).
"""
import argparse, heapq, math, os, sys
import numpy as np
from scipy import ndimage as ndi
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import thrcommon as tc
from mini_portrait_timing import motor_positions

GROOVE = 0.042          # measured 2026-11-20 on the camera
RES = 0.004             # analysis grid, fraction of the radius per pixel
EXT = 1.06              # grid covers [-EXT, EXT]
NG = int(round(2 * EXT / RES))      # 530
TF = 2                  # travel grid is TF x coarser
RHO_MIN = 0.015         # never closer to the centre than this (added moves only)
MAX_STEP, MAX_DTH = 0.02, 0.05
MAX_POINTS = 12000
MIN_ARC = GROOVE / 2      # shorter arcs on a ring are dropped (the neighbouring rings' grooves cover them)
PEN = 300.0             # cost multiplier for travel over sand it must not touch

# firmware v8.9 model constants (our-fw.ino line 186), for motor_minutes()
GL, RMAX = 0.465, 0.88
GB1, GB2, GA, GA1 = 6.09e-4, 1.10e-4, 5.59e-4, 3.045e-4

_yy, _xx = np.mgrid[0:NG, 0:NG]
GX = (_xx + 0.5) * RES - EXT
GY = EXT - (_yy + 0.5) * RES
GR = np.hypot(GX, GY)
DISC = GR <= 1.0


# ---------------------------------------------------------------- geometry helpers
def densify(pts, step=MAX_STEP, dth=MAX_DTH, thin=False):
    """Split every move (linear in theta, rho) so steps stay under `step` of the radius and `dth` rad.
    thin=True: moves with |drho| <= 0.002 per resulting step are split by angle only."""
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return pts
    th, r = pts[:, 0], pts[:, 1]
    d_th, d_r = np.diff(th), np.diff(r)
    rm = np.maximum(r[:-1], r[1:])
    L = np.hypot(rm * d_th, d_r)
    n_dist = np.ceil(L / step)
    n_ang = np.ceil(np.abs(d_th) / dth)
    n_rad = np.ceil(np.abs(d_r) / step)
    n = np.maximum(n_dist, n_ang)
    if thin:
        flat = np.abs(d_r) <= 0.002 * np.maximum(1, n_ang)
        n = np.where(flat, np.maximum(n_ang, n_rad), n)
    n = np.maximum(1, n).astype(int)
    seg = np.repeat(np.arange(len(n)), n)
    first = np.cumsum(n) - n
    s = (np.arange(len(seg)) - first[seg]) / n[seg]
    out = np.c_[th[seg] + s * d_th[seg], r[seg] + s * d_r[seg]]
    return np.vstack([out, pts[-1:]])


def to_px(x, y):
    return (x + EXT) / RES - 0.5, (EXT - y) / RES - 0.5


def polar_xy(pts):
    pts = np.asarray(pts, float)
    return pts[:, 1] * np.cos(pts[:, 0]), pts[:, 1] * np.sin(pts[:, 0])


def paint_line(mask, pts):
    """Mark the pixels along a polar path (fine steps) in a boolean mask."""
    d = densify(pts, step=RES * 0.7, dth=0.02)
    x, y = polar_xy(d)
    c, rw = to_px(x, y)
    c = np.clip(np.round(c).astype(int), 0, NG - 1)
    rw = np.clip(np.round(rw).astype(int), 0, NG - 1)
    mask[rw, c] = True


def dist_out(m):
    """distance (radii) from each pixel outside m to m"""
    return ndi.distance_transform_edt(~m) * RES


def dist_in(m):
    """distance (radii) from each pixel inside m to the outside of m"""
    return ndi.distance_transform_edt(m) * RES


def dilate(m, r): return dist_out(m) <= r
def erode(m, r): return dist_in(m) > r
def close(m, r): return erode(dilate(m, r), r)
def opening(m, r): return dilate(erode(m, r), r)


# ---------------------------------------------------------------- analysis of the portrait
def analyse(port, groove=GROOVE, overlap=None, close_r=None):
    overlap = groove * 1.07 if overlap is None else overlap
    line = np.zeros((NG, NG), bool)
    paint_line(line, port)
    covered = dist_out(line) <= groove / 2
    covc = close(covered, 0.012)                            # the tiny slivers between neighbouring fill lines
    sil = ndi.binary_fill_holes(close(covered, close_r or groove)) & (GR <= 1.0 + groove)
    out = GR > 1.0
    sil_o = sil | out
    gaps = sil & ~covc & DISC
    islands = opening(gaps, groove / 2)
    lab, nl = ndi.label(islands)
    if nl:
        area = ndi.sum(islands, lab, range(1, nl + 1)) * RES * RES
        keep = np.r_[False, area >= math.pi * (groove / 2) ** 2 * 1.5]
        islands = keep[lab]
    hide = erode(covc, groove / 2 + RES * 0.6) & DISC
    inner = erode(sil_o, groove / 2) & DISC & (GR >= RHO_MIN)
    # opening by half a groove: no slivers narrower than a groove (they only make the rings stutter, and the
    # grooves either side cover them)
    bg = opening(DISC & ~erode(sil_o, overlap) & (GR >= RHO_MIN), groove / 2)
    isl = opening(dilate(islands, overlap) & inner, groove / 4)
    return dict(line=line, covered=covered, covc=covc, sil=sil & DISC, islands=islands, hide=hide, bg=bg,
                isl=isl, inner=inner, groove=groove)


# ---------------------------------------------------------------- rings and cells
def ring_intervals(region, rho):
    M = max(64, int(math.ceil(2 * math.pi * rho / (RES * 0.6))))
    a = np.arange(M) * 2 * math.pi / M
    rs = min(rho, 1.0 - 1.5 * RES)                          # the rim ring is judged just inside the disc mask
    c, r = to_px(rs * np.cos(a), rs * np.sin(a))
    inside = region[np.clip(np.round(r).astype(int), 0, NG - 1), np.clip(np.round(c).astype(int), 0, NG - 1)]
    if inside.all():
        return [dict(a=0.0, b=2 * math.pi, full=True, rho=rho)]
    if not inside.any():
        return []
    k0 = int(np.argmin(inside))                             # start the scan on an outside sample: no wrap issues
    ins = np.roll(inside, -k0)
    ang = np.roll(a, -k0)
    ang = np.unwrap(ang)
    out, i = [], 0
    while i < M:
        if ins[i]:
            j = i
            while j + 1 < M and ins[j + 1]:
                j += 1
            if (ang[j] - ang[i]) * rho >= MIN_ARC:
                out.append(dict(a=float(ang[i]), b=float(ang[j]), full=False, rho=rho))
            i = j + 1
        else:
            i += 1
    return out


def ang_overlap(I, J):
    """best shift (multiple of 2pi) of J onto I and the overlap length; full intervals overlap everything"""
    if I['full'] or J['full']:
        return 0.0, 1.0
    best = (None, 0.0)
    for s in (-2 * math.pi, 0.0, 2 * math.pi):
        ov = min(I['b'], J['b'] + s) - max(I['a'], J['a'] + s)
        if ov >= 0 and (best[0] is None or ov > best[1]):
            best = (s, ov)
    return best


def build_cells(region, pitch, rho_top=1.0):
    rings = []
    k = 0
    while True:
        rho = rho_top - k * pitch
        if rho < RHO_MIN - 1e-9:
            break
        rings.append(ring_intervals(region, rho))
        k += 1
    nodes = [(k, i) for k in range(len(rings)) for i in range(len(rings[k]))]
    succ = {n: [] for n in nodes}
    pred = {n: [] for n in nodes}
    for k in range(len(rings) - 1):
        for i, I in enumerate(rings[k]):
            for j, J in enumerate(rings[k + 1]):
                s, ov = ang_overlap(I, J)
                if s is not None:
                    succ[(k, i)].append(((k + 1, j), s))
                    pred[(k + 1, j)].append((k, i))
    cell_of, cells = {}, []
    for n in nodes:                                         # nodes are in ring order
        if n in cell_of:
            continue
        chain = [dict(rings[n[0]][n[1]])]
        cell_of[n] = len(cells)
        cur = n
        acc = 0.0                                           # shift already applied to the previous ring's interval
        while len(succ[cur]) == 1 and len(pred[succ[cur][0][0]]) == 1:
            nx, s = succ[cur][0]
            J = dict(rings[nx[0]][nx[1]])
            prev = chain[-1]
            if not J['full'] and not prev['full']:
                acc += s                                    # s lines J up with the UNshifted previous interval
                J['a'] += acc; J['b'] += acc
            else:
                acc = 0.0
            chain.append(J)
            cell_of[nx] = len(cells)
            cur = nx
        cells.append(dict(ivs=chain, top=n, bottom=cur))
    for c in cells:
        c['preds'] = sorted({cell_of[p] for p in pred[c['top']]})
    return cells


# ---------------------------------------------------------------- emitting the path
class Path:
    def __init__(self, th, rho):
        self.P = [(th, rho)]
        self.kind = ['start']

    @property
    def th(self): return self.P[-1][0]

    @property
    def rho(self): return self.P[-1][1]

    def to(self, th, rho, kind):
        self.P.append((float(th), float(rho)))
        self.kind.append(kind)


def sweep_cell(path, cell, d=1):
    """Boustrophedon over one cell, starting where the path stands (on an end of the top interval, or anywhere on
    a full top ring). Returns the last sweep direction."""
    ivs = cell['ivs']
    # where on the top interval are we? (side a or b), in the cell's frame: off = cumulative - frame angle
    I = ivs[0]
    if I['full']:
        off = 0.0
        f = path.th
    else:
        da = (path.th - I['a']) / (2 * math.pi); db = (path.th - I['b']) / (2 * math.pi)
        ea, eb = abs(da - round(da)), abs(db - round(db))
        side = 'a' if ea <= eb else 'b'
        off = 2 * math.pi * round(da if side == 'a' else db)
        f = I[side]
    for idx, I in enumerate(ivs):
        J = ivs[idx + 1] if idx + 1 < len(ivs) else None
        if I['full']:
            if J is not None and J['full']:
                path.to(path.th + d * 2 * math.pi, J['rho'], 'erase')        # a spiral turn
                continue
            path.to(path.th + d * 2 * math.pi, I['rho'], 'erase')            # one circle
            if J is None:
                return d
            # carry on round the circle to the first end of J we meet, step down, sweep J to its other end
            th = path.th
            best = None
            for e in ('a', 'b'):
                t = J[e] + 2 * math.pi * math.floor((th - J[e]) / (2 * math.pi))
                while d * (t - th) < 0: t += d * 2 * math.pi
                while d * (t - th) >= 2 * math.pi: t -= d * 2 * math.pi
                if best is None or abs(t - th) < abs(best[1] - th): best = (e, t)
            e, t = best
            path.to(t, I['rho'], 'erase')
            path.to(t, J['rho'], 'erase')
            off = t - J[e]
            f = J[e]
            continue
        # cut interval: sweep to the far end
        side = 'a' if abs(f - I['a']) <= abs(f - I['b']) else 'b'
        far = 'b' if side == 'a' else 'a'
        d = 1 if far == 'b' else -1
        path.to(I[far] + off, I['rho'], 'erase')
        f = I[far]
        if J is None:
            return d
        if J['full']:
            path.to(path.th, J['rho'], 'erase')
            off = path.th
            f = 0.0
            # J handled as a full ring on the next pass: put the frame where we stand
            ivs[idx + 1] = dict(J, a=0.0, b=2 * math.pi)
            continue
        # cut -> cut: J is already shifted into I's frame
        if far == 'b':
            if J['b'] <= I['b']:
                path.to(J['b'] + off, I['rho'], 'erase')                     # retrace our own groove
                path.to(J['b'] + off, J['rho'], 'erase')
            else:
                path.to(I['b'] + off, J['rho'], 'erase')
                path.to(J['b'] + off, J['rho'], 'erase')
            f = J['b']
        else:
            if J['a'] >= I['a']:
                path.to(J['a'] + off, I['rho'], 'erase')
                path.to(J['a'] + off, J['rho'], 'erase')
            else:
                path.to(I['a'] + off, J['rho'], 'erase')
                path.to(J['a'] + off, J['rho'], 'erase')
            f = J['a']
    return d


# ---------------------------------------------------------------- travel
NT = NG // TF
_ty, _tx = np.mgrid[0:NT, 0:NT]
TXg = (_tx + 0.5) * RES * TF - EXT
TYg = EXT - (_ty + 0.5) * RES * TF


def _grid_edges():
    idx = np.arange(NT * NT).reshape(NT, NT)
    E = []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        b = idx[max(0, dy):NT + min(0, dy), max(0, dx):NT + min(0, dx)]
        a = idx[max(0, -dy):NT - max(0, dy), max(0, -dx):NT - max(0, dx)]
        E.append((a.ravel(), b.ravel(), math.hypot(dx, dy)))
    return E


_EDGES = _grid_edges()


RIM_COST = 5.0          # the rim is allowed but not free: re-cutting it scuffs the next rings in by about a groove


def travel_graph(allowed_f, rim_only=None):
    """allowed (fine grid) -> csr graph on the travel grid, plus the coarse allowed mask. rim_only: pixels that are
    allowed only because they are on the rim; they cost RIM_COST per unit length."""
    blk = lambda m: m[:NT * TF, :NT * TF].reshape(NT, TF, NT, TF)
    al = blk(allowed_f).all(axis=(1, 3)).ravel()
    pen = np.where(al, 0.0, PEN)
    if rim_only is not None:
        pen = np.where(al & blk(rim_only).any(axis=(1, 3)).ravel(), RIM_COST - 1, pen)
    rows, cols, data = [], [], []
    for a, b, L in _EDGES:
        w = L * (1 + np.maximum(pen[a], pen[b]))
        rows += [a, b]; cols += [b, a]; data += [w, w]
    G = csr_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(NT * NT, NT * NT))
    return G, al.reshape(NT, NT)


def tnode(x, y):
    c = int(np.clip(round((x + EXT) / (RES * TF) - 0.5), 0, NT - 1))
    r = int(np.clip(round((EXT - y) / (RES * TF) - 0.5), 0, NT - 1))
    return r * NT + c


def seg_ok(al, p, q):
    n = int(math.hypot(q[0] - p[0], q[1] - p[1]) / (RES * TF * 0.5)) + 2
    for t in np.linspace(0, 1, n):
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        c = int(np.clip(round((x + EXT) / (RES * TF) - 0.5), 0, NT - 1))
        r = int(np.clip(round((EXT - y) / (RES * TF) - 0.5), 0, NT - 1))
        if not al[r, c]:
            return False
    return True


def route(pred, al, src, dst, p0, p1):
    """shortest-path nodes src->dst as xy, string-pulled where the straight segment stays allowed"""
    nodes = [dst]
    while nodes[-1] != src:
        nodes.append(pred[nodes[-1]])
        if nodes[-1] < 0:
            return None
    nodes = nodes[::-1]
    xy = [p0] + [(TXg.flat[n], TYg.flat[n]) for n in nodes[1:-1]] + [p1]
    out, i = [xy[0]], 0
    while i < len(xy) - 1:
        j = len(xy) - 1
        while j > i + 1 and not seg_ok(al, xy[i], xy[j]):
            j -= 1
        out.append(xy[j]); i = j
    bad = sum(1 for n in nodes[2:-2] if not al.flat[n]) * RES * TF
    return out, bad


def emit_travel(path, xy, rim_snap=True, hide=None):
    """append a travel polyline (xy) in polar with continuous theta; densified in xy so it follows the route"""
    pts = []
    for (x0, y0), (x1, y1) in zip(xy[:-1], xy[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.01))
        for t in np.arange(1, n + 1) / n:
            pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    th = path.th
    for x, y in pts[:-1]:
        r = math.hypot(x, y)
        a = math.atan2(y, x)
        a += 2 * math.pi * round((th - a) / (2 * math.pi))
        th = a
        if rim_snap and r > 0.985:
            r = 1.0
        path.to(a, max(RHO_MIN, min(1.0, r)), 'travel')


# ---------------------------------------------------------------- the planner
def plan(port, pitch=0.02, inside_pitch=0.06, islands=True, groove=GROOVE, A=None, verbose=False):
    port = np.asarray(port, float)
    A = A or analyse(port, groove)
    passes = [('background', A['bg'], pitch)]
    if inside_pitch and inside_pitch > 0:
        reg = A['inner'] & ~(dilate(A['isl'], groove / 2) if islands else np.zeros_like(A['inner']))
        passes.append(('inside', reg, inside_pitch))
    if islands:
        passes.append(('islands', A['isl'], pitch))
    rim = (GR >= 0.985) & DISC
    floor = GR >= RHO_MIN
    done = np.zeros((NG, NG), bool)
    pth0, prho0 = port[0]
    stats = dict(travel_bad=0.0, cells=0)
    path = None
    for pi_, (name, region, p) in enumerate(passes):
        cells = build_cells(region, p)
        stats['cells_' + name] = len(cells)
        left = set(range(len(cells)))
        while left:
            avail = [i for i in left if all(q not in left for q in cells[i]['preds'])]
            if path is None:
                # start on the rim ring at the end nearest the portrait's first point
                best = None
                for i in avail:
                    I = cells[i]['ivs'][0]
                    for e in (('a', 'b') if not I['full'] else ('a',)):
                        t = I[e] if not I['full'] else pth0
                        da = abs((t - pth0 + math.pi) % (2 * math.pi) - math.pi) + (1 - I['rho']) * 10
                        if best is None or da < best[0]: best = (da, i, t, I['rho'])
                _, ci, t, r = best
                t = t + 2 * math.pi * round((pth0 - t) / (2 * math.pi))
                path = Path(t, r)
            else:
                future = np.zeros_like(done)
                for (_, reg2, _) in passes[pi_:]:
                    future |= reg2
                near_done = dilate(done, groove) if done.any() else done
                free = (A['hide'] | (future & ~near_done)) & floor & DISC
                allowed = free | (rim & floor)
                G, al = travel_graph(allowed, rim & ~free)
                x0, y0 = path.rho * math.cos(path.th), path.rho * math.sin(path.th)
                src = tnode(x0, y0)
                dist, pred = dijkstra(G, indices=src, return_predecessors=True)
                best = None
                for i in avail:
                    I = cells[i]['ivs'][0]
                    ends = [(I['a'], I['rho']), (I['b'], I['rho'])] if not I['full'] else \
                        [(math.atan2(y0, x0), I['rho'])]
                    for t, r in ends:
                        x1, y1 = r * math.cos(t), r * math.sin(t)
                        c = dist[tnode(x1, y1)]
                        if best is None or c < best[0]: best = (c, i, t, r)
                _, ci, t, r = best
                x1, y1 = r * math.cos(t), r * math.sin(t)
                res = route(pred, al, src, tnode(x1, y1), (x0, y0), (x1, y1))
                if res is not None:
                    xy, bad = res
                    stats['travel_bad'] += bad
                    i0 = len(path.P)
                    emit_travel(path, xy)
                    paint_line(done, np.array(path.P[i0 - 1:]))
                t = t + 2 * math.pi * round((path.th - t) / (2 * math.pi))
                path.to(t, r, 'travel')
            i0 = len(path.P)
            sweep_cell(path, cells[ci])
            paint_line(done, np.array(path.P[i0 - 1:]))
            for k in range(i0, len(path.P)):
                path.kind[k] = name
            left.discard(ci)
            stats['cells'] += 1
    # last travel: to the portrait's first point through covered sand or along the rim
    allowed = (A['hide'] | rim) & floor & DISC
    G, al = travel_graph(allowed, rim & ~A['hide'])
    x0, y0 = path.rho * math.cos(path.th), path.rho * math.sin(path.th)
    x1, y1 = prho0 * math.cos(pth0), prho0 * math.sin(pth0)
    src = tnode(x0, y0)
    dist, pred = dijkstra(G, indices=src, return_predecessors=True)
    res = route(pred, al, src, tnode(x1, y1), (x0, y0), (x1, y1))
    if res is not None:
        xy, bad = res
        stats['travel_bad'] += bad
        emit_travel(path, xy)
    # the portrait's own first point, with its theta shifted by whole turns to continue ours
    shift = 2 * math.pi * round((path.th - pth0) / (2 * math.pi))
    path.to(pth0 + shift, prho0, 'travel')
    return path, shift, stats, A


def combine(port, pitch=0.02, inside_pitch=0.06, islands=True, groove=GROOVE, thin=None, A=None):
    """-> (combined (N,2) array, info). The portrait is appended unchanged apart from a whole-turn theta shift.
    thin=None: thin the erase part only if the total passes 12000 points."""
    port = np.asarray(port, float)
    path, shift, stats, A = plan(port, pitch, inside_pitch, islands, groove, A)
    pre = np.array(path.P)
    kinds = np.array(path.kind)
    er = densify(pre, thin=bool(thin))
    total = len(er) - 1 + len(port)
    thinned = bool(thin)
    if thin is None and total > MAX_POINTS:
        er = densify(pre, thin=True); thinned = True
        total = len(er) - 1 + len(port)
    out = np.vstack([er[:-1], port + [shift, 0.0]])
    # bookkeeping per pass (lengths in radii, on the dense path)
    info = dict(stats)
    for name in ('background', 'inside', 'islands', 'travel'):
        m = kinds[1:] == name
        seg = np.diff(pre, axis=0)
        rm = np.maximum(pre[:-1, 1], pre[1:, 1])
        L = np.hypot(rm * seg[:, 0], seg[:, 1])
        info['len_' + name] = float(L[m].sum())
    info.update(points=len(out), erase_points=len(er) - 1, portrait_points=len(port), thinned=thinned,
                erase_min=tc.est_minutes(er), portrait_min=tc.est_minutes(port), total_min=tc.est_minutes(out),
                erase_motor_min=motor_minutes(er), portrait_motor_min=motor_minutes(port),
                erase_len=path_len(er), shift=shift, pre=pre, kinds=kinds)
    return out, info


def background_erase(port, **kw):
    """For other generators: just the erase part (ends on the portrait's first point, theta shifted by whole
    turns: add info['shift'] to the portrait's theta when appending)."""
    out, info = combine(port, **kw)
    return out[:info['erase_points'] + 1], info


# ---------------------------------------------------------------- checks and timing
def path_len(pts):
    pts = np.asarray(pts, float)
    d = np.diff(pts, axis=0)
    rm = (pts[:-1, 1] + pts[1:, 1]) / 2
    return float(np.hypot(rm * d[:, 0], d[:, 1]).sum())


def motor_minutes(pts, v=400.0, v_erase=None):
    """firmware kinematics: steps of the faster motor per move / speed. v_erase: erase-speed taper (550 inside 0.6
    of the radius, down to 400 at the rim), as the table's own erase runs."""
    pts = np.asarray(pts, float)
    motors = motor_positions(pts, dict(rmax=RMAX, l=GL, a=GA, a1=GA1, b1=GB1, b2=GB2))
    steps = np.max(np.abs(np.diff(motors, axis=0)), axis=1)
    if v_erase:
        rm = (pts[:-1, 1] + pts[1:, 1]) / 2
        vv = np.where(rm <= 0.6, v_erase, v + (v_erase - v) * (1 - rm) / 0.4)
    else:
        vv = v
    return float((steps / vv).sum() / 60)


def check(pts, port_n):
    pts = np.asarray(pts, float)
    d = np.diff(pts, axis=0)
    rm = np.maximum(pts[:-1, 1], pts[1:, 1])
    L = np.hypot(rm * d[:, 0], d[:, 1])
    n = len(pts) - port_n
    return dict(max_step=float(L[:n].max()), max_dth=float(np.abs(d[:n, 0]).max()),
                max_jump=float(np.abs(d[:, 0]).max()), rho_lo=float(pts[:n, 1].min()),
                rho_hi=float(pts[:, 1].max()), rho_lo_all=float(pts[:, 1].min()))


def full_erase(pitch=0.02, turns=50):
    t = np.linspace(0, turns * 2 * math.pi, 20001)
    return np.c_[t, t / (turns * 2 * math.pi)]


def write(path, pts, note):
    with open(path, 'w') as f:
        f.write('# %s\n' % note)
        for th, r in pts:
            f.write('%.5f %.5f\n' % (th, min(1.0, max(0.0, r))))


OPTIONS = (('background only', 0, False), ('bg + coarse inside', 0.06, False),
           ('bg + islands', 0, True), ('bg + coarse + islands', 0.06, True))


def _sim_job(args):
    import sandsim
    steps, size = args
    return np.array(sandsim.render_steps(steps, size=size, real=True))


def compare(port, old, out_jpg, size=620, pitch=0.02, options=OPTIONS, label=''):
    """Honest-renderer sheet: the old picture, then the full fine erase + portrait, then each partial option
    (all starting from `old` drawn over the table's 0.035 erase). Each panel is lightened (brighten.py)."""
    import cv2
    from concurrent.futures import ProcessPoolExecutor
    from PIL import Image, ImageDraw
    from brighten import brighten
    import sandsim
    port = np.asarray(port, float)
    A = analyse(port)
    fe = full_erase(pitch)
    jobs = [([('erase', 0.035), old], size), ([('erase', 0.035), old, ('erase', pitch), port], size)]
    labs = [('old picture (start)', 'Alex over a 0.035 erase'),
            ('full fine erase + portrait', '%.0f min erase (table erase speed) + %.1f' % (
                motor_minutes(fe, v_erase=550), tc.est_minutes(port)))]
    infos = []
    for name, ip, isl in options:
        pts, info = combine(port, pitch, ip, isl, A=A)
        infos.append((name, info))
        jobs.append(([('erase', 0.035), old, pts], size))
        labs.append((name, '%.1f min erase (%.1f thr est) + %.1f, %d pts' % (
            info['erase_motor_min'], info['erase_min'], info['portrait_min'], info['points'])))
    with ProcessPoolExecutor() as ex:
        ims = list(ex.map(_sim_job, jobs))
    cols = 3
    rows = math.ceil(len(ims) / cols)
    lab = 46
    sheet = Image.new('RGB', (cols * (size + 10) + 10, rows * (size + lab + 10) + 10 + (30 if label else 0)),
                      (34, 32, 31))
    dr = ImageDraw.Draw(sheet)
    f1, f2 = sandsim._font(18), sandsim._font(14)
    y0 = 10
    if label:
        dr.text((12, 8), label, fill=(235, 235, 235), font=f1); y0 = 40
    for i, (im, (t1, t2)) in enumerate(zip(ims, labs)):
        bgr = brighten(np.ascontiguousarray(im[:, :, ::-1]))
        x, y = 10 + (i % cols) * (size + 10), y0 + (i // cols) * (size + lab + 10)
        sheet.paste(Image.fromarray(np.ascontiguousarray(bgr[:, :, ::-1])), (x, y))
        dr.text((x + 4, y + size + 4), t1, fill=(240, 240, 240), font=f1)
        dr.text((x + 4, y + size + 26), t2, fill=(175, 175, 175), font=f2)
    sheet.save(out_jpg, quality=92)
    return infos


def plot_route(items, out_jpg):
    """items: list of (title, portrait pts, combine info). The erase route alone as a plain line plot, coloured
    by pass, travel in red, the portrait as a faint grey line, silhouette shaded."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, len(items), figsize=(8.5 * len(items), 9), dpi=110)
    axs = np.atleast_1d(axs)
    col = {'background': '#1f4e9a', 'inside': '#e08a00', 'islands': '#1a9a3a', 'travel': '#d62020'}
    for ax, (title, port, info, A) in zip(axs, items):
        ax.set_aspect('equal'); ax.axis('off')
        ext = [-EXT, EXT, -EXT, EXT]
        shade = np.ones((NG, NG, 3))
        shade[A['sil']] = (0.88, 0.88, 0.88)
        shade[A['islands']] = (0.80, 0.90, 1.0)
        ax.imshow(shade, extent=ext, origin='upper')
        t = np.linspace(0, 2 * np.pi, 400)
        ax.plot(np.cos(t), np.sin(t), color='k', lw=1)
        x, y = polar_xy(densify(port, 0.01, 0.05))
        ax.plot(x, y, color='#b0b0b0', lw=0.5)
        pre, kinds = info['pre'], info['kinds']
        for k in range(1, len(pre)):
            seg = densify(pre[k - 1:k + 1], 0.005, 0.02)
            x, y = polar_xy(seg)
            ax.plot(x, y, color=col.get(kinds[k], 'k'), lw=0.8 if kinds[k] != 'travel' else 1.4)
        x0, y0 = polar_xy(pre[:1]); x1, y1 = polar_xy(pre[-1:])
        ax.plot(x0, y0, 'o', color='#1f4e9a', ms=9); ax.plot(x1, y1, 's', color='k', ms=8)
        ax.set_title(title, fontsize=13)
    from matplotlib.lines import Line2D
    h = [Line2D([0], [0], color=c, lw=2) for c in col.values()] + [Line2D([0], [0], color='#b0b0b0', lw=1)]
    fig.legend(h, ['background pass', 'coarse inside pass', 'islands pass', 'travel', 'portrait (drawn last)'],
               loc='lower center', ncol=5, fontsize=12)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out_jpg, pil_kwargs=dict(quality=92))
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('thr')
    ap.add_argument('-o', '--out')
    ap.add_argument('--pitch', type=float, default=0.02)
    ap.add_argument('--inside-pitch', type=float, default=0.06)
    ap.add_argument('--islands', action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument('--report', action='store_true', help='time every option, write nothing')
    a = ap.parse_args()
    port = tc.read_thr(a.thr)
    if a.report:
        A = analyse(port)
        fe = full_erase(a.pitch)
        print('%-26s %7s %7s %7s %7s' % ('option', 'len R', 'tc min', 'mot min', 'points'))
        print('%-26s %7.1f %7.1f %7.1f %7s   (table erase speed: %.1f min)' % (
            'full fine erase, 50 turns', path_len(fe), tc.est_minutes(fe), motor_minutes(fe),
            '-', motor_minutes(fe, v_erase=550)))
        for lab, ip, isl in (('background only', 0, False), ('bg + coarse inside', a.inside_pitch, False),
                             ('bg + islands', 0, True), ('bg + coarse + islands', a.inside_pitch, True)):
            out, info = combine(port, a.pitch, ip, isl, A=A)
            print('%-26s %7.1f %7.1f %7.1f %7d  bad travel %.3f R, cells %d%s' % (
                lab, info['erase_len'], info['erase_min'], info['erase_motor_min'], info['points'],
                info['travel_bad'], info['cells'], ', thinned' if info['thinned'] else ''))
        print('portrait itself: %.1f tc min, %.1f motor min, %d points' % (
            tc.est_minutes(port), motor_minutes(port), len(port)))
        return
    out, info = combine(port, a.pitch, a.inside_pitch, a.islands)
    if a.out:
        write(a.out, out, 'bg_erase pitch %.3f inside %.3f islands %d + %s' % (
            a.pitch, a.inside_pitch, a.islands, os.path.basename(a.thr)))
    c = check(out, len(port))
    print('points %d (erase %d + portrait %d)%s, erase %.1f R, %.1f tc min (%.1f motor min), total %.1f tc min' % (
        info['points'], info['erase_points'], info['portrait_points'], ' thinned' if info['thinned'] else '',
        info['erase_len'], info['erase_min'], info['erase_motor_min'], info['total_min']))
    print('checks', {k: round(v, 4) for k, v in c.items()}, 'bad travel %.3f R' % info['travel_bad'])
    if a.out:
        print('wrote', a.out)


if __name__ == '__main__':
    main()
