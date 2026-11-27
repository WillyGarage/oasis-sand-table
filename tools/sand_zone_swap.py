#!/usr/bin/env python3
"""Zone swaps for the 36-inch table, built on revision 3 (SIMULATION AND FILES ONLY: never contacts a table).

    python3 tools/sand_zone_swap.py                        # all three swaps, chained, starting from rev3's last file
    python3 tools/sand_zone_swap.py --start-from FILE.thr  # start where FILE's last line says the ball is
    python3 tools/sand_zone_swap.py --swaps 2 --start-from patterns/sand-party/swaps/01-.../4-content-b.thr

Frame is revision 3's, unchanged: design mm with R = 355, exported rho = mm / 355 (the table now maps rho 1 to 385 mm, so
reality is 1.0845 times larger; rho is kept identical to rev3).  Physical clearing pitch 2.5 mm = 2.3 design mm.

Each swap goes to patterns/sand-party/swaps/NN-<zone>-<person>/ :
    1-travel.thr    from the start point to the zone's boundary, along frame lines only
    2-clear.thr     boustrophedon arcs (centre: straight in, then spiral) inside the zone, 2 design mm inside every boundary line
    3-recut.thr     redraws the zone's own boundary lines
    4-content*.thr  name first, then face, then pictures (rev3 rules), split at 11,500 points
    manifest.json, preview.png (sand simulation of the whole table after the swap), preview-paths.png (the swap paths in colour)
Every file starts exactly on the last row of the file before it.
"""
import argparse, json, math, os, sys, itertools
import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
from shapely.geometry import Point, MultiPoint, Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_update_plan as u
import thrcommon as tc
import zone_samples as z

ROOT = u.ROOT
REV3 = u.OUT3
OUTROOT = os.path.join(ROOT, 'patterns', 'sand-party', 'swaps-v2')       # (the swaps already drawn stay in patterns/sand-party/swaps)
RT = 355.0
SCALE = 385.0 / 355.0                      # the real table is this much larger than the design mm
CLEAR_SPEED, DRAW_SPEED = 850.0, 400.0    # physical mm/s
PITCH = 2.3                                # design mm (physical 2.5)
MARG = 2.0                                 # clear stays this far inside every boundary line
# inward spirals end this far from the centre (Bill's photo, 2026-11-26: ending at 7.5 mm left a bare, scraped disc ~28 mm across in the
# middle; the groove is ~13 mm wide, so the last tight laps ploughed the gathered sand back out. 12 mm: the last lap still passes
# within half a groove of the centre, and the sand it gathers stays in the middle)
IN_END_MM = 12.0
MAXPTS = 11500
f0, f1, RO = u.f0, u.f1, u.RO
P = u.P

u.HULL_STEP = 1                            # item outlines from every point (the rev3 fix)
u.WIDTH_MAX = 12.0
u.ORIENT_RADIAL = True                     # rev4 rule: pictures face the way the face and name do (base toward the outside), tilt <= 15 deg
u.FACE_LINES = ('outer',)                  # faces and names stand with their base toward the outside

SWAPS = {
    1: dict(slug='01-ring2-alex-maverick', kind='slice', ring=2, a=(120, 180), old='ALEX', person='dog', name='MAVERICK', dir='in', turn=0, rev3_file='12-ring2-alex.thr'),
    2: dict(slug='02-ring1-bill-alex', kind='slice', ring=1, a=(180, 270), old='BILL', person='alex', name='ALEX', dir='out', turn=1, rev3_file='06-ring1-bill.thr'),
    3: dict(slug='03-centre-alex-bill', kind='centre', ring=0, a=(0, 360), old='ALEX', person='bill', name='BILL', dir='out', turn=0, rev3_file='01-02'),
    # upright-picture demo on the real table, after swaps 1-3 (start from swaps/03-centre-alex-bill/4-content.thr)
    4: dict(slug='04-ring2-thomas-lek', kind='slice', ring=2, a=(240, 300), old='THOMAS', person='lek', name='LEK', dir='in', turn=1, rev3_file='14-ring2-thomas.thr'),
    5: dict(slug='05-ring1-maverick-thomas', kind='slice', ring=1, a=(0, 90), old='MAVERICK', person='thomas', name='THOMAS', dir='in', turn=1, rev3_file='08-ring1-maverick.thr'),
}


# ------------------------------------------------------------------ rows <-> geometry
def read_rows(path):
    return np.loadtxt(path, ndmin=2)


def rows_xy(rows):
    return np.column_stack((rows[:, 1] * np.cos(rows[:, 0]), rows[:, 1] * np.sin(rows[:, 0]))) * RT


def row_len(rows):
    """Path length (design mm) following (theta, rho) straight lines."""
    L = 0.0
    for a, b in zip(rows[:-1], rows[1:]):
        n = max(1, int(math.ceil(max(abs(b[0] - a[0]) / 0.02, abs(b[1] - a[1]) / 0.01))))
        t = np.linspace(0, 1, n + 1)
        th, ro = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        L += float(np.hypot(np.diff(ro * np.cos(th)), np.diff(ro * np.sin(th))).sum()) * RT
    return L


def draw_rows(polys, start_row):
    """Cartesian polylines (mm) -> rows of (theta, rho), continuous with start_row (its theta is kept), densified like rev3."""
    pts = [np.asarray(p, float) for p in polys if len(p) > 1]
    d = []
    for pl in pts:
        for a, b in zip(pl[:-1], pl[1:]):
            r = max(4.3, min(math.hypot(*a), math.hypot(*b)))
            step = min(1.5, r * math.radians(1.2))
            m = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
            for k in range(m):
                d.append(a + (b - a) * k / m)
        d.append(pl[-1])
    if not d:                                  # already at the target (no travel): the file is just the start point
        return np.array([[start_row[0], start_row[1]], [start_row[0], start_row[1]]])
    D = np.array(d)
    r = np.hypot(D[:, 0], D[:, 1])
    th = np.empty(len(D))
    prev = start_row[0]
    for i, (x, y) in enumerate(D):
        g = math.atan2(y, x)
        prev = prev + (g - prev + math.pi) % (2 * math.pi) - math.pi if r[i] > 1e-6 else prev
        th[i] = prev
    ro = np.maximum(r, 4.3) / RT
    fine = [np.array([start_row[0], start_row[1]])]
    allr = np.column_stack((th, ro))
    allr[0] = start_row                       # the first point is the start row, exactly
    for i in range(1, len(allr)):
        a, b = fine[-1], allr[i]
        m = int(math.ceil(max(abs(b[0] - a[0]) / math.radians(1.4), abs(b[1] - a[1]) / 0.009, 1)))
        for k in range(1, m + 1):
            fine.append(a + (b - a) * k / m)
    return np.array(fine)


def write_rows(path, rows):
    open(path, 'w').write(''.join('%.5f %.5f\n' % (a, b) for a, b in rows))
    return read_rows(path)                    # what was written, rounded, so the next file starts on exactly these numbers


def split_points(rows, limit=MAXPTS):
    """Cut a long row array into pieces of at most `limit` rows; piece k+1 starts on the last row of piece k."""
    out, i = [], 0
    while i < len(rows) - 1:
        j = min(i + limit - 1, len(rows) - 1)
        out.append((i, j))
        i = j
    return out or [(0, len(rows) - 1)]


# ------------------------------------------------------------------ frame graph
def start_extras(xy0, ea, es):
    r = math.hypot(*xy0)
    ang = math.degrees(math.atan2(xy0[1], xy0[0])) % 360
    for rr in (f0, f1, RO):
        if abs(r - rr) < 0.6:
            ea.setdefault(round(rr, 3), []).append(ang)
            return
    for a in sorted({x % 360 for x in u.R1A + u.R2A}):
        if abs(((ang - a) + 180) % 360 - 180) < 0.3:
            es.setdefault(a, []).append(r)
            return
    raise SystemExit('the start point (r = %.2f mm, %.2f deg) is not on a frame line, so travel along frame lines is not possible' % (r, ang))


def addx(e, ea, es):
    (ea if e[0] == 'arc' else es).setdefault(e[1], []).append(e[2])


# ------------------------------------------------------------------ clearing
def clear_slice(zone, dirn, start_row, corner):
    """Boustrophedon arcs at constant rho, 2 design mm inside every boundary line, stepping PITCH.
    corner = (r, angle deg) of the boundary corner the ball is standing on."""
    r_in, r_out, a_lo, a_hi = zone['r_in'], zone['r_out'], zone['a_lo'], zone['a_hi']
    n = int(math.ceil((r_out - r_in - 2 * MARG) / PITCH)) + 1
    rs = np.linspace(r_out - MARG, r_in + MARG, n) if dirn == 'in' else np.linspace(r_in + MARG, r_out - MARG, n)
    d = lambda r: math.degrees(math.asin(MARG / r))
    from_lo = abs(corner[1] - a_lo) < abs(corner[1] - a_hi)
    seq = [corner]
    for k, r in enumerate(rs):
        lo, hi = a_lo + d(r), a_hi - d(r)
        a, b = (lo, hi) if (k % 2 == 0) == from_lo else (hi, lo)
        seq += [(r, a), (r, b)]
    th0 = start_row[0]
    rows = [start_row.copy()]
    for r, a in seq[1:]:
        rows.append([th0 + math.radians(a - corner[1]), r / RT])
    rows = np.array(rows)
    # radial steps between arcs are single short segments (2.3 mm = 0.0065 rho); arcs need only their endpoints
    return rows, seq[-1]


def clear_centre(zone, start_row, node_angle):
    """Straight in from the boundary node to rho 0.02, then (second file) a spiral out to 2 mm inside the circle."""
    th0 = start_row[0]
    ro = np.arange(start_row[1], 0.02, -0.009)
    inward = np.vstack([np.column_stack((np.full(len(ro), th0), ro)), [th0, 0.02]])
    inward[0] = start_row
    r_c = 0.02 * RT
    r_max = f0 - MARG
    phi_end = (r_max - r_c) / PITCH * 2 * math.pi
    phi = np.arange(0.0, phi_end, math.radians(5.0))
    phi = np.append(phi, phi_end)
    r = r_c + PITCH * phi / (2 * math.pi)
    spiral = np.column_stack((th0 + phi, r / RT))
    spiral[0] = inward[-1]
    return inward, spiral


def clear_centre_in(start_row, cl):
    """The centre's INWARD clear (Bill, 2026-11-24: every clear alternates in/out, the centre included; until 2026-11-25 the
    centre always spiralled OUT, which thinned the middle). Returns (spiral_rows, exit_poly, crown_xy) or None if there is no
    face to leave by.
    Step 2 mm in from the boundary node, spiral in to rho 0.02 (pitch <= PITCH, stretched so it ends at the angle of Q), then
    leave the middle WITHOUT a new line across the fresh sand: Q is the point of the face's own drawing walk (the same
    u.item_walk tour the content step draws from the crown) closest to the spiral's end radius; the exit follows that tour from
    Q to the crown, so the only new mark is the short step from the spiral end to Q. The content step later draws the whole tour
    over it."""
    r_c = IN_END_MM / 375.0 * RT                  # physical mm -> design mm (rho 1 = 375 mm on the table, RT design mm)
    r_max = f0 - MARG
    th0 = start_row[0]
    if not cl or not cl.get('custom') or cl.get('face_strokes') is None:
        # no face to leave by (Bill, 2026-11-26: ALWAYS clear the centre inward): leave straight up at 90 degrees, where a centre
        # without a face has nothing (the name is at the bottom, the pictures left and right): one plain line in the empty top half
        a90 = math.pi / 2
        S = (r_max - r_c) / PITCH * 2 * math.pi
        S += (a90 - (th0 + S)) % (2 * math.pi)
        s = np.append(np.arange(0.0, S, math.radians(5.0)), S)
        rr = r_max - (r_max - r_c) * s / S
        spiral = np.vstack([start_row, np.column_stack((th0 + s, rr / RT))])
        top = np.array([0.0, f0 - 0.5])
        return spiral, np.array([[0.0, r_c], top]), top
    entry = np.asarray(cl['face'][cl['crown']], float)
    tour = [np.asarray(pl, float) for _, pl in u.item_walk(cl['face_strokes'], entry, 'face')]
    path = [entry]
    for pl in tour:
        for a, b in zip(pl[:-1], pl[1:]):
            m = max(1, int(math.ceil(np.hypot(*(b - a)) / 0.5)))
            path += [a + (b - a) * k / m for k in range(1, m + 1)]
    path = np.array(path)
    if np.hypot(*(path[-1] - entry)) > 0.5:                 # item_walk tours end where they start; anything else: do not rely on it
        return None
    j = int(np.argmin(np.abs(np.hypot(*path.T) - r_c)))
    seg = np.r_[0, np.cumsum(np.hypot(*np.diff(path, axis=0).T))]
    exit_poly = path[j:] if seg[-1] - seg[j] < seg[j] else path[:j + 1][::-1]      # the shorter way round the tour to the crown
    q = path[j]
    S = (r_max - r_c) / PITCH * 2 * math.pi
    S += (math.atan2(q[1], q[0]) - (th0 + S)) % (2 * math.pi)                   # end at Q's angle: a slightly finer pitch
    s = np.append(np.arange(0.0, S, math.radians(5.0)), S)
    rr = r_max - (r_max - r_c) * s / S
    spiral = np.vstack([start_row, np.column_stack((th0 + s, rr / RT))])
    return spiral, exit_poly, entry


def perimeter(zone, c0):
    """Closed loop of the zone's own boundary lines starting and ending at corner c0 = (r, angle)."""
    r_in, r_out, a_lo, a_hi = zone['r_in'], zone['r_out'], zone['a_lo'], zone['a_hi']
    corners = [(r_in, a_lo), (r_out, a_lo), (r_out, a_hi), (r_in, a_hi)]
    i0 = min(range(4), key=lambda i: math.hypot(*(P(*corners[i]) - P(*c0))))
    seq = [corners[(i0 + k) % 4] for k in range(5)]
    out = []
    for p, q in zip(seq[:-1], seq[1:]):
        if abs(p[0] - q[0]) < 1e-6:                          # an arc
            n = max(2, int(abs(q[1] - p[1]) * math.pi / 180 * p[0] / 1.5))
            out.append(np.array([P(p[0], a) for a in np.linspace(p[1], q[1], n + 1)]))
        else:
            n = max(2, int(abs(q[0] - p[0]) / 1.5))
            out.append(np.array([P(r, p[1]) for r in np.linspace(p[0], q[0], n + 1)]))
    return out, corners[i0]


# ------------------------------------------------------------------ content
def neighbour_points(world, zone_poly):
    """Drawn points around the zone that are not frame lines and not inside the zone (what new items must keep away from)."""
    box = zone_poly.buffer(40).bounds
    sel = world[(world[:, 0] > box[0]) & (world[:, 0] < box[2]) & (world[:, 1] > box[1]) & (world[:, 1] < box[3])]
    fl = u.frame_geoms()
    fp = np.vstack([np.array([g.interpolate(t).coords[0] for t in np.arange(0, g.length, 0.6)]) for _, g in fl])
    d = cKDTree(fp).query(sel)[0]
    sel = sel[d > 1.0]
    zp = zone_poly.buffer(0.3)
    keep = [i for i, p in enumerate(sel) if not zp.contains(Point(p))]
    return sel[keep]


def layout_slice(zone, world, seed):
    zpoly = u.zone_poly(zone)
    nb = neighbour_points(world, zpoly)
    ob = MultiPoint(nb[::2]) if len(nb) else None
    H, d = (116, 75) if zone['ring'] == 1 else (92, 75)
    if zone['person'] == 'dog':
        H = 84 if zone['ring'] == 1 else 80
    rng = np.random.default_rng(seed)
    while True:
        items = u.items_for(zone, H, d, 22.0)
        lay0, mg = u.pack2(zone, items, rng, tries=300, passes=10, keep=6, obst=ob)
        if lay0 is not None and mg >= 9.0:
            break
        H, d = H - 2, max(d - 1, 55)
    lay = u.pack3(zone, items, rng, start=lay0, obst=ob)
    a = u.zone_ratios(lay)
    att = 0
    while a[0] > 1.5 and att < 16:
        att += 1
        l0, _ = u.pack2(zone, items, np.random.default_rng(100 + att), tries=300, passes=3, keep=3, obst=ob)
        if l0 is None:
            continue
        l2 = u.pack3(zone, items, rng, start=l0, tries=600, keep=14, passes=20, sub=900, obst=ob)
        a2 = u.zone_ratios(l2)
        if a2[0] < a[0]:
            lay, a = l2, a2
    zone['H'], zone['d'] = H, d
    return items, lay, a, nb


def centre_layout(person, name, nb=None):
    h = 25.0
    lets, W = u.name_local(name, h)
    L = u.Line.__new__(u.Line)
    L.kind, L.r, L.up_in, L.sgn, L.r_in, L.r_out = 'outer', f0, True, 1, 0, f0
    phi_s = -90.0 - math.degrees(W / 2 / f0)
    strip = u.name_poly_l(L, phi_s, W, h, u.NAME_LIFT)
    nbm = MultiPoint(nb[::2]) if nb is not None and len(nb) else None
    if nbm is not None and strip.distance(nbm) < 8.0:
        raise SystemExit('the name strip would be too close to a neighbouring drawing')
    uu = z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', u.THR[person])), 1.0)
    bh = float(uu[:, 1].max() - uu[:, 1].min())
    best = None
    for hh in np.arange(180.0, 120.0, -2.0):
        s_ = hh / bh
        for cy in np.arange(-30.0, 40.0, 1.0):
            pp = uu * s_ + np.array([0.0, cy])
            if np.hypot(*pp.T).max() > f0 - 0.3 or MultiPoint(pp[::7]).distance(strip) < u.GAP_MIN:
                continue
            if nbm is not None and MultiPoint(pp[::5]).distance(nbm) < 8.0:
                continue
            best = (hh, s_, cy)
            break
        if best:
            break
    hh, s_, cy = best
    face = z.thr_to_xy(tc.read_thr(os.path.join(ROOT, 'patterns', u.THR[person])), s_) + np.array([0.0, cy])
    k = int(np.argmax(np.hypot(*face.T)))
    return dict(H=hh, s=s_, cy=cy, name_h=h, phi_s=phi_s, W=W, letters=lets, line=L, face=face, crown=k, person=person)


def slice_extras(items, lay, ea, es):
    for it, pz in zip(items, lay):
        if it['kind'] == 'name':
            a, b, _ = u.name_phis(pz['L'], pz['s'], it['letters'])
            addx(('arc', round(pz['L'].r, 3), a % 360), ea, es)
            addx(('arc', round(pz['L'].r, 3), b % 360), ea, es)
        else:
            addx(pz['L'].extra(pz['s']), ea, es)


def content_slice(run, FR, items, lay):
    ents = []
    for it, pz in zip(items, lay):
        if it['kind'] == 'name':
            a, b, _ = u.name_phis(pz['L'], pz['s'], it['letters'])
            ents.append((FR.node(P(pz['L'].r, a)), FR.node(P(pz['L'].r, b))))
        else:
            n = FR.node(pz['C'])
            ents.append((n, n))
    dc = {}

    def D(a_, b_):
        if a_ not in dc:
            dc[a_] = FR.dists(a_)[0]
        return dc[a_][b_]
    best = None
    for perm in itertools.permutations(range(len(ents))):
        if perm[0] != 0 or perm[1] != 1:                # name first, then the face, then the pictures
            continue
        cost = D(run.node, ents[perm[0]][0]) + sum(D(ents[a_][1], ents[b_][0]) for a_, b_ in zip(perm[:-1], perm[1:]))
        if best is None or cost < best[0]:
            best = (cost, perm)
    for kk in best[1]:
        it, pz = items[kk], lay[kk]
        a0 = len(run.ev)
        if it['kind'] == 'name':
            u.draw_name_r2(run, FR, pz['L'], pz['s'], it['letters'], u.NAME_LIFT)
        else:
            enter = ents[kk][0]
            run.walk(FR, enter)
            if pz['lift'] > 0:
                run.line('stem', np.array([FR.pos[enter], pz['org']]))
            for kind, pl in u.item_walk(u.world_strokes(pz['var']['strokes'], pz['org'], pz['u']), pz['org'], it['kind']):
                run.line(kind, pl)
            if pz['lift'] > 0:
                run.line('retrace', np.array([pz['org'], FR.pos[enter]]))
            run.node = enter
        run.items.append((1, it['kind'], a0, len(run.ev)))
    return best[1]


def content_centre(run, FR, c):
    a0 = len(run.ev)
    u.draw_name_r2(run, FR, c['line'], c['phi_s'], c['letters'], u.NAME_LIFT, from_centre=False)
    run.items.append((0, 'name', a0, len(run.ev)))
    uu = c['face']
    k = c['crown']
    node = FR.node(P(f0, math.degrees(math.atan2(uu[k, 1], uu[k, 0]))))
    run.walk(FR, node)
    face = np.vstack([uu[k:], uu[1:k + 1]])
    run.ev.append(('stem', np.array([FR.pos[node], face[0]])))
    run.pos = face[0].copy()
    a0 = len(run.ev)
    run.line('face', face)
    run.items.append((0, 'face', a0, len(run.ev)))
    run.ev.append(('stem', np.array([run.pos, FR.pos[node]])))
    run.pos = FR.pos[node].copy()
    run.node = node


# ------------------------------------------------------------------ one swap
def do_swap(n, sw, start_file, world, outdir_root, seed=5):
    out = os.path.join(outdir_root, sw['slug'])
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.endswith('.thr') or f.endswith('.json') or f.endswith('.png'):
            os.remove(os.path.join(out, f))
    start = read_rows(start_file)[-1].copy()
    xy0 = rows_xy(start[None])[0]
    zone = dict(kind=sw['kind'], ring=sw['ring'], a_lo=sw['a'][0], a_hi=sw['a'][1], person=sw['person'], name=sw['name'], turn=sw['turn'])
    if sw['kind'] == 'slice':
        zone.update(u.make_zone('slice', sw['ring'], sw['a'][0], sw['a'][1]))
        zone['person'], zone['name'], zone['turn'] = sw['person'], sw['name'], sw['turn']
        items, lay, ratio, nb = layout_slice(zone, world, seed)
        cl = None
    else:
        zone.update(r_in=0.0, r_out=f0)
        cl = centre_layout(sw['person'], sw['name'], neighbour_points(world, u.zone_poly(dict(kind='centre'))))
        items = lay = None
        ratio = None
    zpoly = u.zone_poly(zone if sw['kind'] == 'slice' else dict(kind='centre'))
    ea, es = {}, {}
    start_extras(xy0, ea, es)
    # where the clear begins, and the nodes the later steps need
    if sw['kind'] == 'slice':
        slice_extras(items, lay, ea, es)
    else:
        a, b, _ = u.name_phis(cl['line'], cl['phi_s'], cl['letters'])
        addx(('arc', round(f0, 3), a % 360), ea, es)
        addx(('arc', round(f0, 3), b % 360), ea, es)
        kk = cl['crown']
        addx(('arc', round(f0, 3), math.degrees(math.atan2(cl['face'][kk, 1], cl['face'][kk, 0])) % 360), ea, es)
    # spiral end angle for the centre (so the recut and the content can use a node there)
    node_angle = None
    FR0 = u.Fine(ea, es)
    n_start = FR0.node(xy0)
    if sw['kind'] == 'slice':
        r_edge = zone['r_out'] if sw['dir'] == 'in' else zone['r_in']
        cands = [(r_edge, zone['a_lo']), (r_edge, zone['a_hi'])]
    else:
        cands = [(f0, a) for a in (0, 90, 180, 270)]
    dist = FR0.dists(n_start)[0]
    corner = min(cands, key=lambda c: dist[FR0.node(P(*c))])
    # spiral end angle (centre) is known once the clear is built: do the clear first with the start row
    files, spec = [], []
    # ---- 1 travel (frame lines only)
    run = u.Run()
    run.items = []
    run.pos = xy0.copy()
    run.node = n_start
    run.walk(FR0, FR0.node(P(*corner)))
    travel_polys = [pl for _, pl in run.ev]
    rows = draw_rows(travel_polys, start)
    last = write_rows(os.path.join(out, '1-travel.thr'), rows)
    spec.append(('1-travel.thr', 'draw', last, 'travel along frame lines to the zone boundary'))
    cur_rows = last
    # ---- 2 clear (skipped when the zone is already blank: Bill, 2026-11-25 - never re-clear freshly cleared sand)
    clears = []
    cin = clear_centre_in(cur_rows[-1], cl) if (sw['kind'] != 'slice' and sw['dir'] == 'in' and not sw.get('skip_clear')) else None
    sw['dir_used'] = sw['dir'] if sw['kind'] == 'slice' else ('in' if cin is not None else 'out')
    if sw.get('skip_clear'):
        end_xy = rows_xy(cur_rows[-1:])[0]
        if sw['kind'] != 'slice':
            node_angle = math.degrees(math.atan2(end_xy[1], end_xy[0])) % 360
            addx(('arc', round(f0, 3), node_angle), ea, es)
    elif sw['kind'] == 'slice':
        crow, endpt = clear_slice(zone, sw['dir'], cur_rows[-1], corner)
        crow = np.array(crow)
        wr = write_rows(os.path.join(out, '2-clear.thr'), crow)
        spec.append(('2-clear.thr', 'clear', wr, 'clear %s' % sw['dir']))
        cur_rows = wr
        clears.append(wr)
        c0_end = endpt
        end_xy = rows_xy(wr[-1:])[0]
    elif cin is not None:
        spiral, exit_poly, crown_xy = cin
        w1 = write_rows(os.path.join(out, '2a-clear-spiral-in.thr'), spiral)
        spec.append(('2a-clear-spiral-in.thr', 'clear', w1, 'spiral in from the boundary to the centre'))
        end_c = rows_xy(w1[-1:])[0]
        node_angle = math.degrees(math.atan2(crown_xy[1], crown_xy[0])) % 360
        end_xy = P(f0, node_angle)                  # out to the boundary along the content's own crown stem, so the recut starts on its line
        w2 = write_rows(os.path.join(out, '2b-leave-along-the-face.thr'),
                        draw_rows([np.array([end_c, exit_poly[0]]), exit_poly, np.array([crown_xy, end_xy])], w1[-1]))
        spec.append(('2b-leave-along-the-face.thr', 'draw', w2, 'leave the middle along lines the face drawing retraces'))
        cur_rows = w2
        clears += [w1]
        addx(('arc', round(f0, 3), node_angle), ea, es)
    else:
        inward, spiral = clear_centre(zone, cur_rows[-1], corner[1])
        w1 = write_rows(os.path.join(out, '2a-clear-in-to-centre.thr'), inward)
        spiral[0] = w1[-1]
        w2 = write_rows(os.path.join(out, '2b-clear-spiral-out.thr'), spiral)
        spec.append(('2a-clear-in-to-centre.thr', 'clear', w1, 'straight in from the boundary to the centre'))
        spec.append(('2b-clear-spiral-out.thr', 'clear', w2, 'spiral out'))
        cur_rows = w2
        clears += [w1, w2]
        end_xy = rows_xy(w2[-1:])[0]
        node_angle = math.degrees(math.atan2(end_xy[1], end_xy[0])) % 360
        addx(('arc', round(f0, 3), node_angle), ea, es)
    # ---- 3 recut (the zone's own boundary lines only)
    if sw['kind'] == 'slice':
        polys, c_used = perimeter(zone, c0_end if False else (math.hypot(*end_xy), math.degrees(math.atan2(end_xy[1], end_xy[0])) % 360))
        polys = [np.array([end_xy, polys[0][0]])] + polys
        rc_node_pos = P(*c_used)
    else:
        a_ = math.radians(node_angle)
        circ = np.array([P(f0, node_angle + t) for t in np.linspace(0, 360, 361)])
        polys = ([np.array([end_xy, P(f0, node_angle)])] if np.hypot(*(end_xy - P(f0, node_angle))) > 0.01 else []) + [circ]
        rc_node_pos = P(f0, node_angle)
    rows = draw_rows(polys, cur_rows[-1])
    wr = write_rows(os.path.join(out, '3-recut.thr'), rows)
    spec.append(('3-recut.thr', 'draw', wr, 'redraw the zone boundary lines'))
    cur_rows = wr
    recut_polys = polys
    # ---- 4 content, continuing from the recut's last point (a corner / node on the zone boundary)
    FR = u.Fine(ea, es)
    run = u.Run()
    run.items = []
    run.node = FR.node(rc_node_pos)
    run.pos = FR.pos[run.node].copy()
    if sw['kind'] == 'slice':
        order = content_slice(run, FR, items, lay)
    else:
        content_centre(run, FR, cl)
    # the recut ended on rc_node_pos; the content walk starts there (<= 0.1 mm from the recut's last point)
    polys = [pl for _, pl in run.ev]
    rows = draw_rows([np.array([rows_xy(cur_rows[-1:])[0], polys[0][0]])] + polys if np.hypot(*(rows_xy(cur_rows[-1:])[0] - polys[0][0])) > 0.01 else polys, cur_rows[-1])
    parts = split_points(rows)
    for k, (i, j) in enumerate(parts):
        nm = '4-content.thr' if len(parts) == 1 else '4-content-%s.thr' % 'abcd'[k]
        piece = rows[i:j + 1].copy()
        if k > 0:
            piece[0] = cur_rows[-1]
        wr = write_rows(os.path.join(out, nm), piece)
        spec.append((nm, 'draw', wr, 'content (name, face, pictures)' if sw['kind'] == 'slice' else 'content (name, face)'))
        cur_rows = wr
    # ---- continuity, manifest
    man, prev = [], None
    for nm, spd, rws, note in spec:
        if prev is not None:
            assert np.allclose(rws[0], prev, atol=1e-5), ('gap before', nm)
        prev = rws[-1]
        L = row_len(rws)
        man.append(dict(file=nm, play_speed=spd, points=int(len(rws)), length_design_mm=round(L, 1), length_physical_mm=round(L * SCALE, 1),
                        minutes=round(L * SCALE / (CLEAR_SPEED if spd == 'clear' else DRAW_SPEED) / 60.0, 2), note=note))
        assert len(rws) <= MAXPTS, (nm, len(rws))
    assert np.allclose(read_rows(os.path.join(out, spec[0][0]))[0], start, atol=1e-5), 'first file does not start at the start point'
    # ---- the checks
    chk = swap_checks(zone, sw, spec, run, items, lay, world)
    summ = dict(swap=n, zone=sw['slug'], old=sw['old'], new=sw['name'], last_clear_direction=sw['dir'], start_point_row=[float(start[0]), float(start[1])],
                start_from=os.path.relpath(start_file, ROOT), end_row=[float(prev[0]), float(prev[1])], files=man,
                total_minutes=round(sum(m['minutes'] for m in man), 1), gap_ratio=None if ratio is None else round(float(ratio[0]), 2),
                sizes=dict(face_mm=float(zone.get('H', cl['H'] if cl else 0)), pictures_mm=float(zone.get('d', 0))), checks=chk)
    json.dump(summ, open(os.path.join(out, 'manifest.json'), 'w'), indent=1)
    new_world = update_world(world, zpoly, run, sw)
    return summ, out, spec, run, zone, new_world


def update_world(world, zpoly, run, sw):
    keep = np.array([not zpoly.buffer(-0.3).contains(Point(p)) for p in world]) if len(world) else np.zeros(0, bool)
    pts = [dens(pl) for k, pl in run.ev if k in ('name', 'join', 'face', 'icon', 'bridge', 'stem')]
    return np.vstack([world[keep]] + pts)


def dens(pl):
    return u.dens(pl, 1.5)


def swap_checks(zone, sw, spec, run, items, lay, world):
    fl = u.frame_geoms()
    fp = np.vstack([np.array([g.interpolate(t).coords[0] for t in np.arange(0, g.length, 0.4)]) for _, g in fl])
    ftree = cKDTree(fp)
    zp = u.zone_poly(zone if sw['kind'] == 'slice' else dict(kind='centre'))
    res = {}
    by = {nm: rows_xy(rws) for nm, spd, rws, note in spec}
    # travel: only on frame lines
    t = by['1-travel.thr']
    res['travel_max_distance_from_frame_line_mm'] = round(float(ftree.query(t)[0].max()), 2)
    # clear: inside the zone, 2 mm from every boundary (the very first step leaves the boundary corner)
    outside_clear = 0
    mind = 99.0
    for nm in by:
        if nm.startswith('2'):
            pts = by[nm]
            xy = np.vstack([dense_polar_path(spec, nm)])
            inside = np.array([zp.buffer(0.2).contains(Point(p)) for p in xy[1:]])
            outside_clear += int((~inside).sum())
            dd = ftree.query(xy[1:])[0]
            mind = min(mind, float(dd.min()))
    res['clear_points_outside_zone'] = outside_clear
    res['clear_min_distance_to_a_boundary_line_mm'] = round(mind, 2)
    # recut: on the zone's own boundary lines only
    r = dense_polar_path(spec, '3-recut.thr')
    zb = zp.exterior
    res['recut_max_distance_from_zone_boundary_mm'] = round(float(max(zb.distance(Point(p)) for p in r[3:])), 2)
    # content: inside the zone, clear of neighbours
    cont = np.vstack([dens(pl) for k, pl in run.ev if k in ('name', 'join', 'face', 'icon', 'bridge', 'stem', 'retrace')])
    res['content_points_outside_zone'] = int(sum(not zp.buffer(0.5).contains(Point(p)) for p in cont[::2]))
    zs_ = [dict(kind='centre', name=sw['name'])] if sw['kind'] == 'centre' else [dict(kind='centre'), zone]
    viol = u.geometry_check(run, zs_, verbose=False)
    if True:
        nb = neighbour_points(world, zp)
        items_pts = np.vstack([dens(pl) for k, pl in run.ev if k in ('name', 'join', 'face', 'icon', 'bridge')])
        if len(nb):
            dmin = float(cKDTree(nb).query(items_pts)[0].min())
            res['closest_to_a_neighbour_drawing_mm'] = round(dmin, 1)
            if dmin < 6.0:
                viol.append('too close (%.1f mm) to a neighbouring zone drawing' % dmin)
    angs = [float(pz['angle']) for it, pz in zip(items or [], lay or []) if it['kind'] == 'icon']
    res['picture_angles_deg'] = [round(a, 1) for a in angs]
    res['picture_angle_max_deg'] = round(max(angs), 1) if angs else None
    res['overlap_violations'] = len(viol)
    res['overlap_violation_list'] = viol
    res['touched_outside_zone_and_boundary_lines'] = int(outside_clear + res['content_points_outside_zone'] + (res['travel_max_distance_from_frame_line_mm'] > 0.8) +
                                                       (res['recut_max_distance_from_zone_boundary_mm'] > 0.8))
    return res


def dense_polar_path(spec, nm):
    rws = [s[2] for s in spec if s[0] == nm][0]
    out = [rows_xy(rws[:1])[0]]
    for a, b in zip(rws[:-1], rws[1:]):
        n = max(1, int(math.ceil(max(abs(b[0] - a[0]) / 0.01, abs(b[1] - a[1]) / 0.005))))
        t = np.linspace(0, 1, n + 1)[1:]
        th, ro = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        out += list(np.column_stack((ro * np.cos(th), ro * np.sin(th))) * RT)
    return np.array(out)


# ------------------------------------------------------------------ pictures
def sector_mask_poly(zone, sw, size, inset=1.5):
    sc = size / 2 * 0.94 / RT
    c = size / 2
    if sw['kind'] == 'centre':
        r = f0 - inset
        return [(c + r * sc * math.cos(math.radians(a)), c - r * sc * math.sin(math.radians(a))) for a in np.linspace(0, 360, 200)]
    a = np.linspace(zone['a_lo'], zone['a_hi'], 80)
    pts = [P(zone['r_out'] - inset, x) for x in a] + [P(zone['r_in'] + inset, x) for x in a[::-1]]
    return [(c + p[0] * sc, c - p[1] * sc) for p in pts]


def preview(outdir_root, results, upto):
    """Sand simulation of rev3 plus swaps 1..upto: outside each swapped zone the rev3 drawing (plus travel and recut lines),
    inside it the new content on flat sand."""
    base = u.load_xy(REV3)
    extra, pasted = [], []
    for summ, out, spec, run, zone, sw in results[:upto]:
        for nm, spd, rws, note in spec:
            if nm.startswith('1') or nm.startswith('3'):
                extra.append(rows_xy(rws))
        pasted.append((zone, sw, np.vstack([pl for k, pl in run.ev if k not in ('frame',)] or [np.zeros((1, 2))]), run))
    A = np.vstack([base] + extra)
    size, outpx = 1400, 1000
    imA = u.render_sim(A, size, outpx).convert('RGB')
    for zone, sw, _, run in pasted:
        pls = [pl for k, pl in run.ev if k in ('name', 'join', 'face', 'icon', 'bridge', 'stem', 'retrace', 'frame')]
        B = np.vstack([dens(pl) for pl in pls])
        imB = u.render_sim(B, size, outpx).convert('RGB')
        m = Image.new('L', (outpx, outpx), 0)
        ImageDraw.Draw(m).polygon(sector_mask_poly(zone, sw, outpx), fill=255)
        imA.paste(imB, (0, 0), m)
    return imA


def preview_paths(results, upto):
    base = u.render_sim(u.load_xy(REV3), 1400, 1000).convert('RGB')
    base = Image.blend(base, Image.new('RGB', base.size, (255, 255, 255)), 0.55)
    d = ImageDraw.Draw(base)
    sc = 1000 / 2 * 0.94 / RT
    c = 500
    col = {'1': (30, 90, 220), '2': (60, 170, 80), '3': (220, 40, 40), '4': (20, 20, 20)}
    for summ, out, spec, run, zone, sw in results[:upto]:
        for nm, spd, rws, note in spec:
            xy = dense_polar_path([(nm, spd, rws, note)], nm)
            d.line([(c + x * sc, c - y * sc) for x, y in xy], fill=col[nm[0]], width=1 if nm[0] != '1' else 2)
    d.text((12, 12), 'blue travel, green clear, red recut, black new content', fill=(0, 0, 0))
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start-from', default=os.path.join(REV3, '19-frame-lines.thr'))
    ap.add_argument('--swaps', default='1,2,3')
    ap.add_argument('--out', default=OUTROOT)
    ap.add_argument('--dir', default=None, help='override the clear direction for every swap (in or out)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    world = u.load_xy(REV3)
    start_file = a.start_from
    results = []
    for n in [int(x) for x in a.swaps.split(',')]:
        sw = dict(SWAPS[n])
        if a.dir:
            sw['dir'] = a.dir
        print('swap %d: %s -> %s, clear %s, starting from %s' % (n, sw['old'], sw['name'], sw['dir'], os.path.relpath(start_file, ROOT)), flush=True)
        summ, out, spec, run, zone, world = do_swap(n, sw, start_file, world, a.out)
        results.append((summ, out, spec, run, zone, sw))
        start_file = os.path.join(out, spec[-1][0])
        for m in summ['files']:
            print('   %-28s %-5s %6d points  %7.0f mm  %5.2f min' % (m['file'], m['play_speed'], m['points'], m['length_physical_mm'], m['minutes']))
        print('   total %.1f min; checks %s' % (summ['total_minutes'], {k: v for k, v in summ['checks'].items() if 'list' not in k}), flush=True)
        im = preview(a.out, results, len(results))
        im.save(os.path.join(out, 'preview.png'))
        preview_paths(results, len(results)).save(os.path.join(out, 'preview-paths.png'))
    return results


if __name__ == '__main__':
    main()
