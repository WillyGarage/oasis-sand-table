#!/usr/bin/env python3
"""Sand pictures of creatures: a T. rex, a velociraptor and a bacteriophage, in the filled style of the dog and the
portraits (patterns/dog/make_dog.py, patterns/people/make_people.py).

Canvas: 600 x 600, y down, disc centre (300, 300), drawing radius 290 (rho 1). Every creature is a list of regions.
A region is a filled shape (closed splines, plus optional thick strokes for thin parts such as claws and legs) that is
filled with lines following its outline inward, one groove spacing apart. Regions are listed in priority order: an
earlier region owns its area and later regions are cut away there, so overlapping parts (a leg in front of the body)
fill once and their shared edge shows as a line. Holes are left as smooth islands (eyes). A region can be 'wavy' (the
fill lines wiggle: feathers) or limited to a few 'levels' (an outline band instead of a solid fill).

All loops are joined into one line by a tree of neighbouring loops (Prim on loop-to-loop gaps, so every hop is about
one line spacing long), walked depth first. The ball comes in from the rim at `start` (a point where the creature
touches the rim) and the branch leading to the `final` region is walked last, so the drawing ends there (an eye).

Differences from make_people.build (which is not edited, other work is going on there): region priority, strokes,
start on the rim at a chosen angle, rho kept >= 0.012, and moves densified so no step turns more than 1.5 degrees or
moves rho more than 0.01.

  make_creatures.py [names]   -> <name>.thr + <name>.png (clean thumbnail) here,
                                 captures/morning/creature_<name>.jpg (honest, lightened), creatures_sheet.jpg
Written 2026-11-20 for Bill's request (T. rex, velociraptor, "biophage" read as bacteriophage)."""
import math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(HERE + '/../..')
sys.path.insert(0, HERE + '/../dog'); sys.path.insert(0, ROOT + '/tools')
from make_dog import spline, zigzag
import thrcommon as tc

CX, CY, S = 300.0, 300.0, 290.0
F = 2.0                     # mask pixels per canvas unit
PITCH = 0.057               # fill line spacing in rho (0.055-0.06 reads cleanly in real sand)
RHO_MIN = 0.012

# ---------------------------------------------------------------- shape helpers
def cs(pts, step=3.0): return spline(pts, step=step, closed=True)
def rim(deg, r=S):
    """point on a circle about the disc centre; deg in screen angle (0 = right, 90 = down)"""
    return (CX + r * math.cos(math.radians(deg)), CY + r * math.sin(math.radians(deg)))
def circle(c, r, n=48): return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
def mirror(pts, x0=300.0): return [(2 * x0 - x, y) for x, y in pts]

def teeth(a, b, n, h, sign=1):
    """n triangular teeth from a to b, tips h to the right of the direction of travel (sign=-1: to the left)"""
    dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy); nx, ny = -dy / L * sign, dx / L * sign
    out = []
    for i in range(n):
        p0 = (a[0] + dx * i / n, a[1] + dy * i / n); pm = (a[0] + dx * (i + .5) / n, a[1] + dy * (i + .5) / n)
        out += [p0, (pm[0] - nx * h, pm[1] - ny * h)]
    return out + [b]

def ellipse_poly(c, rx, ry, rot=0.0, n=36):
    a = math.radians(rot)
    return [(c[0] + rx * math.cos(t) * math.cos(a) - ry * math.sin(t) * math.sin(a),
             c[1] + rx * math.cos(t) * math.sin(a) + ry * math.sin(t) * math.cos(a)) for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]

def eye(c, r_hole, r_pupil=6):
    """returns (hole polygon, pupil region): a smooth ring round a dot where the drawing ends"""
    return circle(c, r_hole), dict(poly=circle(c, r_pupil), levels=1, name='pupil')

# ---------------------------------------------------------------- T. rex
def trex(stripes=False):
    """Side view facing right, the classic balanced pose: back level, heavy tail out to the left rim (the ball comes in
    at the tail tip), huge head with the jaws open and big triangular teeth, a tiny two-fingered arm, a massive near
    thigh and a far leg stepping back. Ends in the eye."""
    E = (470, 178)
    hole, pupil = eye(E, 15)
    # body outline, clockwise from the tail (which starts past the rim and is cut off by it)
    top = spline([(-20, 340), (40, 306), (110, 272), (180, 242), (240, 222), (300, 214), (346, 220), (378, 228),
                  (400, 206), (414, 168), (440, 144), (488, 132), (534, 136), (560, 150), (570, 172), (566, 204)], 3)
    upper_jaw = teeth((560, 208), (452, 234), 4, 21, sign=-1)       # big teeth pointing down into the gape
    lower_jaw = teeth((454, 250), (536, 290), 3, 19, sign=-1)       # and up
    under = spline([(544, 298), (538, 322), (500, 336), (452, 330), (418, 322), (396, 328), (388, 350), (374, 378),
                    (338, 400), (290, 408), (240, 396), (200, 374), (150, 358), (90, 352), (30, 352), (-20, 360)], 3)
    body = top + upper_jaw + [(444, 240)] + lower_jaw + under
    near_leg = cs([(200, 300), (250, 272), (306, 282), (342, 326), (346, 384), (334, 424), (316, 468), (310, 498),
                   (344, 510), (374, 520), (368, 536), (300, 538), (270, 530), (266, 498), (270, 462), (258, 424),
                   (222, 396), (198, 352)])
    far_leg = cs([(196, 372), (236, 384), (246, 420), (226, 462), (218, 494), (250, 514), (270, 524), (264, 538),
                  (204, 538), (188, 520), (190, 470), (190, 420)])
    arm = [((378, 338), (402, 352), (420, 368)), ((420, 368), (436, 372)), ((420, 368), (428, 384))]
    # stripes (alternative): slanted smooth bands across the back and tail, left as islands in the body fill
    bars = [ellipse_poly((x, y), 9, 34, a) for x, y, a in ((330, 246, 20), (286, 240, 14), (240, 246, 8), (192, 262, 4),
                                                          (144, 282, 0), (96, 302, -4))] if stripes else []
    return dict(name='trex_alt' if stripes else 'trex', title='T. rex' + (' (striped)' if stripes else ''),
                start=rim(166), final='pupil', xf=(1.02, 4, (-40, 12)), regions=[
        pupil,
        dict(poly=[], strokes=[(a, 13) for a in arm], name='arm'),
        dict(poly=near_leg, name='near leg'),
        dict(poly=body, holes=[hole] + bars, name='body'),
        dict(poly=far_leg, name='far leg'),
    ])

# ---------------------------------------------------------------- velociraptor
def raptor(feathers=True):
    """Side view, designed facing right and drawn mirrored (facing left) so it never looks like the T. rex: slim body,
    long straight stiff tail out to the rim (the ball comes in at the tail tip), S-shaped neck, small head with a long
    narrow snout, long arms reaching forward with three hooked fingers, long running legs, and the big raised sickle
    claw on the front foot. feathers=True: the tail and a fringe under the forearm are drawn with wavy lines."""
    E = (426, 182)
    hole, pupil = eye(E, 11, 5)
    # long flat snout, slightly open, small teeth on the upper jaw: reads as a reptile, not a bird's beak
    head_top = spline([(340, 246), (358, 218), (372, 194), (390, 172), (420, 156), (470, 156), (520, 162), (550, 172),
                       (556, 184)], 3)
    gape = teeth((552, 190), (452, 204), 4, 10, sign=-1) + [(446, 208)] + [(456, 212), (530, 214)]
    head_under = spline([(534, 220), (520, 228), (480, 232), (440, 234), (418, 246), (406, 268), (390, 300),
                         (350, 300)], 3)
    head_neck = head_top + gape + head_under
    body = cs([(226, 236), (280, 232), (330, 240), (366, 262), (382, 296), (360, 326), (300, 334), (250, 324),
               (226, 300)])
    tail = [(-40, 146), (60, 176), (150, 206), (232, 234), (240, 302), (150, 238), (60, 208), (-40, 184)]   # straight edges
    front_thigh = cs([(246, 276), (296, 276), (326, 312), (334, 350), (312, 366), (274, 342), (246, 316)])
    back_thigh = cs([(218, 284), (264, 292), (268, 340), (250, 372), (226, 368), (212, 324)])
    front_leg = [((320, 356), (300, 424)), ((300, 424), (334, 490)), ((332, 492), (382, 494))]
    sickle = ((338, 488), (340, 458), (356, 438), (382, 436), (398, 452))      # the raised killing claw, hooked forward
    back_leg = [((242, 364), (200, 400)), ((200, 400), (170, 432)), ((170, 432), (150, 458)), ((170, 432), (180, 462))]
    arm = [((360, 296), (384, 338)), ((384, 338), (430, 330)), ((430, 330), (456, 338), (462, 356)),
           ((430, 330), (446, 346), (446, 366)), ((430, 330), (434, 350), (428, 368))]
    fringe = cs([(362, 300), (384, 340), (430, 334), (412, 358), (390, 372), (364, 366), (352, 340)])    # wing feathers
    regs = [pupil,
            dict(poly=[], strokes=[(a, 11) for a in arm], name='arm'),
            dict(poly=[], strokes=[(sickle, 12)] + [(s, 15) for s in front_leg], name='front leg'),
            dict(poly=front_thigh, name='front thigh'),
            dict(poly=head_neck, holes=[hole], name='head'),
            dict(poly=body, name='body'),
            dict(poly=tail, name='tail', **(dict(wavy=(3.5, 30)) if feathers else {})),
            dict(poly=back_thigh, name='back thigh'),
            dict(poly=[], strokes=[(s, 14) for s in back_leg], name='back leg')]
    if feathers: regs.insert(2, dict(poly=fringe, wavy=(3.0, 22), name='wing'))
    return dict(name='raptor' if feathers else 'raptor_alt', title='Velociraptor' + ('' if feathers else ' (plain)'),
                start=rim(-20), final='pupil', flip=True, xf=(1.05, 0, (8, 24)), regions=regs)

def raptor_alt(): return raptor(False)
def trex_alt(): return trex(True)

# ---------------------------------------------------------------- bacteriophage
def phage():
    """Front view, symmetric: a tall hexagonal head whose six triangular facets are each filled with their own
    shrinking triangles, a collar, a banded tail sheath, a baseplate and six bent legs (out and up to a knee, then down)
    standing on a ground line that runs from rim to rim. The ball comes in at the left end of the ground line and
    leaves at the same place."""
    C = (300, 122)
    hexa = [(300, 18), (398, 66), (398, 178), (300, 226), (202, 178), (202, 66)]
    facets = [dict(poly=[C, hexa[i], hexa[(i + 1) % 6]], name='facet%d' % i) for i in range(6)]
    collar = cs([(232, 230), (368, 230), (372, 246), (228, 246)], 2)
    bands = [dict(poly=[(270, 246 + 22 * k), (330, 246 + 22 * k), (330, 268 + 22 * k), (270, 268 + 22 * k)], name='band%d' % k)
             for k in range(6)]
    plate = [(238, 378), (362, 378), (378, 392), (362, 406), (238, 406), (222, 392)]
    legs_l = [((254, 396), (126, 316), (100, 502)), ((262, 402), (172, 364), (166, 502)), ((270, 406), (222, 424), (238, 502))]
    legs = legs_l + [tuple(mirror(l)) for l in legs_l]
    ground = [(-20, 500), (620, 500), (620, 516), (-20, 516)]
    return dict(name='phage', title='Bacteriophage', start=rim(134), xf=(1.0, 0, (0, 0)), regions=[
        dict(poly=ground, name='ground'),
        dict(poly=[], strokes=[(l, 12) for l in legs], name='legs'),
        dict(poly=plate, name='plate'),
        *bands,
        dict(poly=collar, name='collar'),
        *facets])

# ---------------------------------------------------------------- shared routing + output
def build(p):
    import cv2
    from scipy.spatial import cKDTree
    sys.setrecursionlimit(20000)
    W = int(600 * F)
    sc, rot, (tx, ty) = p.get('xf', (1.0, 0.0, (0, 0)))         # place the design: scale and turn about the centre, shift
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    fl = p.get('flip', False)                                     # flip: designed facing right, drawn facing left
    def T(pts):
        if fl: pts = [(600 - x, y) for x, y in pts]
        return [(CX + sc * ((x - CX) * ca - (y - CY) * sa) + tx, CY + sc * ((x - CX) * sa + (y - CY) * ca) + ty) for x, y in pts]
    disc = np.zeros((W, W), np.uint8); cv2.circle(disc, (int(CX * F), int(CY * F)), int(p.get('clip', 0.975) * S * F), 255, -1)
    taken = np.zeros((W, W), np.uint8)
    loops = []                                           # (region index, level, points)
    names = []
    for ri, rg in enumerate(p['regions']):
        names.append(rg.get('name', str(ri)))
        mask = np.zeros((W, W), np.uint8)
        polys = rg['poly'] if (rg['poly'] and isinstance(rg['poly'][0][0], (list, tuple))) else ([rg['poly']] if rg['poly'] else [])
        for poly in polys:
            cv2.fillPoly(mask, [np.array([[x * F, y * F] for x, y in T(poly)], np.int32)], 255)
        for pts, w in rg.get('strokes', []):
            pts = T(pts); w = w * sc
            cv2.polylines(mask, [np.array([[x * F, y * F] for x, y in pts], np.int32)], False, 255, int(w * F))
            for q in (pts[0], pts[-1]): cv2.circle(mask, (int(q[0] * F), int(q[1] * F)), int(w * F / 2), 255, -1)
        mask &= disc                                     # anything past the rim is cut off by it
        full = mask.copy()
        mask[taken > 0] = 0
        for h in rg.get('holes', []): cv2.fillPoly(mask, [np.array([[x * F, y * F] for x, y in T(h)], np.int32)], 0)
        taken |= full
        dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        pp = PITCH * rg.get('pitch', 1.0) * S * F
        lv = 0; d = 2.0
        while dist.max() >= d and lv < rg.get('levels', 99):
            cs_, _ = cv2.findContours((dist >= d).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
            for c in cs_:
                c = c[:, 0, :].astype(float)
                if len(c) < rg.get('min_len', 36): continue
                c = c[::4]
                k = np.array([1, 4, 6, 4, 1], float); k /= k.sum()
                c = np.stack([np.convolve(np.r_[c[-2:, j], c[:, j], c[:2, j]], k, 'valid') for j in (0, 1)], 1) / F
                if rg.get('wavy') and lv >= rg.get('wavy_from', 0):
                    amp, per = rg['wavy']; c = np.array(zigzag([tuple(q) for q in c], amp, per))
                loops.append((ri, lv, c))
            lv += 1; d = pp * lv
    L = [l[2] for l in loops]; trees = [cKDTree(c) for c in L]; n = len(L)
    gapc = {}
    def gap(i, j):
        if (i, j) not in gapc:
            d, k = trees[j].query(L[i]); m = int(np.argmin(d)); gapc[(i, j)] = (float(d[m]), m, int(k[m]))
        return gapc[(i, j)]
    # entry: p['start'] is a rough spot on the rim; take the outermost loop nearest it, the point of that loop nearest
    # the spot, and come in from the rim straight beside that point (the entry move is only the outline-to-rim gap)
    sx, sy = p['start']
    root = min((i for i in range(n) if loops[i][1] == 0),
               key=lambda i: np.min((L[i][:, 0] - sx) ** 2 + (L[i][:, 1] - sy) ** 2))
    q = L[root][int(np.argmin((L[root][:, 0] - sx) ** 2 + (L[root][:, 1] - sy) ** 2))]
    a = math.atan2(q[1] - CY, q[0] - CX); start = (CX + S * math.cos(a), CY + S * math.sin(a))
    parent = {root: None}; hop = {}; left = set(range(n)) - {root}
    best_to = {j: (gap(root, j), root) for j in left}    # Prim's algorithm on loop-to-loop gaps
    while left:
        j = min(left, key=lambda j: best_to[j][0][0]); (d, a_i, a_j), i = best_to[j]
        parent[j] = i; hop[j] = (a_i, a_j, d); left.discard(j)
        for k in left:
            g = gap(j, k)
            if g[0] < best_to[k][0][0]: best_to[k] = (g, j)
    kids = {}
    for j, i in parent.items():
        if i is not None: kids.setdefault(i, []).append(j)
    special = set()
    if p.get('final'):
        fi = names.index(p['final'])
        fin = next(i for i in range(n) if loops[i][0] == fi and loops[i][1] == 0); k = fin
        while k is not None: special.add(k); k = parent[k]
    P = [start]
    def visit(i, i0):
        c = L[i]; m = len(c)
        mine = sorted(kids.get(i, []), key=lambda j: (hop[j][0] - i0) % m)
        nxt = next((j for j in mine if j in special), None)
        at = {}
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
    if not special: P.append(start)                      # out the way it came
    info = dict(start=start, end=P[-1], loops=n, max_hop=max([h[2] for h in hop.values()] + [0]) / S,
                entry=math.hypot(P[1][0] - start[0], P[1][1] - start[1]) / S)
    return P, info

def to_pts(P):
    """canvas path -> (theta, rho) array: densified (<= 2.5 canvas units, <= 1.5 deg turn, <= 0.01 rho per step),
    theta continuous, rho in [RHO_MIN, 1]"""
    D = [P[0]]
    for q in P[1:]:
        a = D[-1]; r = max(1.0, min(math.hypot(a[0] - CX, a[1] - CY), math.hypot(q[0] - CX, q[1] - CY)))
        step = min(2.5, r * math.radians(1.2))
        m = int(math.hypot(q[0] - a[0], q[1] - a[1]) / step)
        for i in range(1, m): D.append((a[0] + (q[0] - a[0]) * i / m, a[1] + (q[1] - a[1]) * i / m))
        D.append(q)
    out = []; prev = None
    for x, y in D:
        X, Y = (x - CX) / S, -(y - CY) / S
        r = min(1.0, max(RHO_MIN, math.hypot(X, Y))); th = math.atan2(Y, X)
        if prev is not None:
            while th - prev > math.pi: th -= 2 * math.pi
            while th - prev < -math.pi: th += 2 * math.pi
        prev = th; out.append((th, r))
    fin = [out[0]]                                       # last pass in motor space: split any step still too big
    for q in out[1:]:
        a = fin[-1]; m = int(math.ceil(max(abs(q[0] - a[0]) / math.radians(1.4), abs(q[1] - a[1]) / 0.009, 1)))
        for i in range(1, m + 1): fin.append((a[0] + (q[0] - a[0]) * i / m, a[1] + (q[1] - a[1]) * i / m))
    return np.array(fin)

def path_len(pts):
    x, y = tc.to_xy(pts); return float(np.hypot(np.diff(x), np.diff(y)).sum())

def check(pts):
    d = np.abs(np.diff(pts, axis=0))
    assert len(pts) < tc.MAX_POINTS, len(pts)
    assert pts[:, 1].min() >= RHO_MIN - 1e-9 and pts[:, 1].max() <= 1.0
    assert d[:, 0].max() <= math.radians(1.5) + 1e-6, math.degrees(d[:, 0].max())
    assert d[:, 1].max() <= 0.0101, d[:, 1].max()

def make(fn, previews=True):
    import cv2
    import sandsim
    from brighten import brighten
    p = fn(); P, info = build(p); pts = to_pts(P); check(pts)
    name = p['name']
    with open('%s/%s.thr' % (HERE, name), 'w') as f:
        f.write('# %s (patterns/creatures/make_creatures.py)\n' % p['title'])
        f.write(''.join('%.5f %.5f\n' % (a, b) for a, b in pts))
    info.update(name=name, title=p['title'], points=len(pts), length=path_len(pts), minutes=tc.est_minutes(pts))
    if previews:
        sandsim.render(pts, size=700).save('%s/%s.png' % (HERE, name))
        im = np.array(sandsim.render(pts, size=700, real=True))[:, :, ::-1].copy()
        cv2.imwrite('%s/captures/morning/creature_%s.jpg' % (ROOT, name), brighten(im), [cv2.IMWRITE_JPEG_QUALITY, 93])
    print('%-12s %6d pts  len %6.1f R  %5.1f min  loops %3d  max hop %.3f  entry %.3f' % (
        name, len(pts), info['length'], info['minutes'], info['loops'], info['max_hop'], info['entry']), flush=True)
    return info

def sheet(infos, out):
    """main pictures on the top row, alternates (name ends in _alt) on a second row"""
    from PIL import Image, ImageDraw
    import sandsim
    T = 460; lab = 58
    rows = [[i for i in infos if not i['name'].endswith('_alt')], [i for i in infos if i['name'].endswith('_alt')]]
    rows = [r for r in rows if r]
    cols = max(len(r) for r in rows)
    sh = Image.new('RGB', (cols * (T + 16) + 16, len(rows) * (T + lab + 16) + 16), (34, 32, 31)); dr = ImageDraw.Draw(sh)
    f1, f2 = sandsim._font(22), sandsim._font(17)
    for rr, row in enumerate(rows):
        for k, i in enumerate(row):
            im = Image.open('%s/captures/morning/creature_%s.jpg' % (ROOT, i['name'])).resize((T, T), Image.LANCZOS)
            x, y = 16 + k * (T + 16), 16 + rr * (T + lab + 16); sh.paste(im, (x, y))
            dr.text((x + 4, y + T + 6), i['title'] + (', alternate' if rr else ''), fill=(236, 236, 236), font=f1)
            dr.text((x + 4, y + T + 32), '%.1f min to draw' % i['minutes'], fill=(176, 176, 176), font=f2)
    sh.save(out, quality=92)

ALL = [trex, raptor, phage, trex_alt, raptor_alt]
if __name__ == '__main__':
    want = sys.argv[1:]
    infos = [make(fn) for fn in ALL if not want or fn.__name__ in want]
    if not want: sheet(infos, ROOT + '/captures/morning/creatures_sheet.jpg')
