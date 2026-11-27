#!/usr/bin/env python3
"""Sand-table icons, group "thomas": a DNA double helix, a Moon rocket lifting off, an Aztec sun stone, and the family
name "Hunt" as one continuous cursive line. Brief: captures/icon_brief.md (2026-11-20).

The filled pictures reuse the machinery of patterns/creatures/make_creatures.py (imported, not edited): regions in
priority order filled with iso-lines following the outline inward, holes left as smooth islands, every loop joined by a
tree walk with hops about one line spacing long, the ball coming in from the rim where the subject touches it.
Canvas 600 x 600, y down, disc centre (300, 300), radius 290 = rho 1.

"Hunt" is not a filled picture: it is one hand-placed cursive path (splines through control points), drawn as a
ribbon (the path traced three times, forward, back and forward again, a little apart) so the word reads as a bold line.

  make_thomas.py [names]   -> patterns/icons/<name>.thr + <name>.png (clean preview),
                              captures/morning/icon_<name>.jpg (honest preview, lightened), icons_thomas.jpg (sheet)"""
import math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(HERE + '/../..')
sys.path.insert(0, ROOT + '/patterns/creatures'); sys.path.insert(0, ROOT + '/patterns/dog'); sys.path.insert(0, ROOT + '/tools')
import make_creatures as mc
from make_creatures import cs, rim, circle, ellipse_poly, build, CX, CY, S
from make_dog import spline
import thrcommon as tc
mc.RHO_MIN = 0.02            # the brief: keep rho >= 0.02 (to_pts and check read this module global)

def sausage(line, hw):
    """closed polygon round a centre line (list of points), half-width hw: a thick stroke with round-ish ends"""
    p = np.array(line, float); L, R = [], []
    for i in range(len(p)):
        a, b = p[max(0, i - 1)], p[min(len(p) - 1, i + 1)]
        t = b - a; t /= (np.linalg.norm(t) or 1); n = np.array([-t[1], t[0]])
        L.append(p[i] + n * hw); R.append(p[i] - n * hw)
    return [tuple(q) for q in L + R[::-1]]

def offset(line, d):
    """the centre line moved sideways by d (left of the direction of travel for d > 0)"""
    p = np.array(line, float); out = []
    for i in range(len(p)):
        a, b = p[max(0, i - 2)], p[min(len(p) - 1, i + 2)]
        t = b - a; t /= (np.linalg.norm(t) or 1)
        out.append(tuple(p[i] + np.array([t[1], -t[0]]) * d))
    return out

# ---------------------------------------------------------------- 1. DNA double helix
def dna():
    """A double helix on the diagonal from the lower-left rim to the upper-right rim. Two bold backbone strands cross
    over each other, alternately in front (the strand behind stops short of the one in front, so it twists), with a few
    thick base-pair rungs between them; at each end the two strands close into one tip that touches the rim. The ball
    comes in at the lower-left tip and leaves there."""
    A, Lp, hw = 104.0, 360.0, 26.0                 # helix half-width, period along the axis, strand half-width
    ang = math.radians(-45)                         # axis direction (screen): up and to the right
    ax, ay = math.cos(ang), math.sin(ang); nx, ny = -ay, ax
    def P(u, v): return (CX + u * ax + v * nx, CY + u * ay + v * ny)
    U = np.arange(-300, 301, 3.0)
    def env(u):                                     # the twist closes to a single tip that touches the rim at each end
        t = min(1.0, max(0.0, (292 - abs(u)) / 100.0)); return t * t * (3 - 2 * t)
    va = lambda u: A * env(u) * math.sin(2 * math.pi * u / Lp)   # crossings at u = 0 and +-Lp/2
    sa = [P(u, va(u)) for u in U]; sb = [P(u, -va(u)) for u in U]
    cross = [(k * Lp / 2, k) for k in (-1, 0, 1)]   # strand a in front at the middle crossing, b at the two beside it
    gap = 10.0
    hole_a, hole_b = [], []
    for u0, k in cross:
        seg = np.arange(u0 - 70, u0 + 71, 3.0)
        if k % 2 == 0: hole_b.append(sausage([P(u, va(u)) for u in seg], hw + gap))     # a in front: cut b
        else: hole_a.append(sausage([P(u, -va(u)) for u in seg], hw + gap))
    rungs = []
    # two bold rungs in each full gap between crossings, one in each part-gap running off to the rim (kept well
    # inside the disc: rungs near the rim tangle with the clipped strand ends)
    for u in (-Lp / 4 - 34, -Lp / 4 + 34, Lp / 4 - 34, Lp / 4 + 34, -Lp / 2 - 42, Lp / 2 + 42):
        v = va(u); rungs.append(sausage([P(u, -v), P(u, v)], 15))
    return dict(name='dna', title='DNA', start=rim(135), regions=[
        dict(poly=sausage(sa, hw), holes=hole_a, name='strand a'),
        dict(poly=sausage(sb, hw), holes=hole_b, name='strand b'),
        dict(poly=rungs, name='rungs'),
    ])

# ---------------------------------------------------------------- 2. Moon rocket
def rocket(moon=False):
    """A heavy-lift Moon rocket lifting off, in the spirit of Artemis: a tall solid core stage whose top narrows into
    the crew capsule, the escape tower spike on top, two slim solid side boosters with pointed noses, a teardrop flame
    (a two-line outline) and round billows
    of smoke along the bottom of the disc out to the rim on both sides. The ball comes in at the smoke on the lower
    left and leaves there. moon=True adds a crescent Moon on the upper left, reached along the rim (the alternate)."""
    tower = dict(poly=[], strokes=[(((300, 26), (300, 92)), 10)], name='tower')
    body = cs([(300, 88), (318, 104), (330, 134), (334, 170), (334, 300), (334, 446), (266, 446), (266, 300),
               (266, 170), (270, 134), (282, 104)], 2)                    # core stage and capsule as one bullet
    def booster(x0):
        return cs([(x0, 452), (x0, 300), (x0, 236), (x0 + 3, 208), (x0 + 21, 172), (x0 + 39, 208), (x0 + 42, 236),
                   (x0 + 42, 300), (x0 + 42, 452)], 2)
    bl, br = booster(214), booster(344)
    flame = cs([(226, 462), (300, 456), (374, 462), (366, 506), (336, 546), (300, 574), (264, 546), (234, 506)], 2)
    puffs = [circle(c, r, 40) for c, r in (((222, 560), 40), ((378, 560), 40), ((162, 548), 38),
                                           ((438, 548), 38), ((104, 530), 38), ((496, 530), 38), ((52, 500), 36),
                                           ((548, 500), 36), ((150, 588), 40), ((450, 588), 40), ((300, 600), 40))]
    regs = [tower,
            dict(poly=body, name='core'),
            dict(poly=bl, name='left booster'),
            dict(poly=br, name='right booster'),
            dict(poly=flame, name='flame', levels=2),
            dict(poly=puffs, name='smoke', levels=2)]
    out = dict(name='rocket', title='Moon rocket', start=rim(160), regions=regs)
    if moon:
        # crescent touching the rim on the upper left: the ball draws it first, then runs a short way along the rim
        out.update(name='rocket_alt', title='Moon rocket with Moon', moon=dict(
            poly=[(x, y) for x, y in circle((118, 128), 62, 60)],
            hole=circle((146, 114), 56, 60)))
    return out

def rocket_alt(): return rocket(moon=True)

# ---------------------------------------------------------------- 3. Aztec sun stone
def aztec():
    """A sun stone made for a round table: a big sun face in the middle (eyes and an open mouth as smooth islands), a
    ring of eight glyph blocks each holding a smooth square, a narrow solid ring, eight big sun rays pointing out with
    eight smaller rays between them, and an outer band of wavy lines (the fire serpents) out to the rim. The ball
    comes in at the outer band and leaves there."""
    face = circle((300, 300), 88, 90)
    eyes = [ellipse_poly((268, 278), 20, 13), ellipse_poly((332, 278), 20, 13)]
    mouth = ellipse_poly((300, 332), 32, 13)
    def sector(r0, r1, a0, a1, n=24):
        A = np.linspace(math.radians(a0), math.radians(a1), n)
        return [(CX + r0 * math.cos(a), CY + r0 * math.sin(a)) for a in A] + \
               [(CX + r1 * math.cos(a), CY + r1 * math.sin(a)) for a in A[::-1]]
    blocks, glyphs = [], []
    for k in range(8):
        a = 22.5 + 45 * k
        blocks.append(sector(96, 152, a - 19, a + 19))
        c = rim(a, 124); glyphs.append(ellipse_poly(c, 15, 15, a + 45, 4))       # a smooth square, turned square-on
    ring = circle((300, 300), 172, 120); ring_in = circle((300, 300), 158, 120)
    rays = []
    for k in range(16):
        a = 22.5 * k; big = k % 2 == 0
        h = 92 if big else 50; w = 14 if big else 8
        rays.append([rim(a - w, 170), rim(a, 170 + h), rim(a + w, 170)])
    outer = circle((300, 300), 320, 120); outer_in = circle((300, 300), 262, 160)
    return dict(name='aztec', title='Aztec sun stone', start=rim(200), regions=[
        dict(poly=face, holes=eyes + [mouth], name='face'),
        dict(poly=blocks, holes=glyphs, name='glyph blocks'),
        dict(poly=ring, holes=[ring_in], name='ring'),
        dict(poly=rays, name='rays'),
        dict(poly=outer, holes=[outer_in], name='fire band', wavy=(3.5, 30)),
    ])

# ---------------------------------------------------------------- 4. "Hunt" in one cursive line
def hunt_path():
    """The centre line of the word, left rim to right rim, as a list of canvas points. Baseline y=384, x-height line
    y=300, the H and the t rise to about y=180. One stroke, with retraces (the ball going back along its own groove,
    which leaves no extra mark): a swash in from the upper-left rim into the top of the H's left stem, down the stem,
    back up it to the crossbar, across, up the right stem and back down it, then joined u and n; the t is an upstroke
    and its stem; part way down the stem the line runs out along the cross and back on each side (retraces again, so
    there is no loop), then finishes the stem and sweeps out to the right rim."""
    B, X = 384.0, 300.0
    seq = [
        [(30, 196), (60, 180), (92, 172), (118, 176)],                                   # swash in from the rim
        [(118, 176), (116, 230), (114, 300), (110, 360), (102, 384), (86, 388)],          # left stem, little foot
        [(86, 388), (102, 384), (110, 360), (113, 296)],                                  # back up it (retrace)
        [(113, 296), (150, 292), (190, 288), (204, 286)],                                 # crossbar
        [(204, 286), (206, 230), (208, 180)],                                             # up the right stem
        [(208, 180), (206, 230), (204, 300), (202, 360), (210, 382), (228, 384), (242, 368), (248, 340), (250, X)],
        [(250, X), (248, 340), (252, 370), (268, 386), (288, 382), (300, 362), (306, 330), (308, X)],   # u
        [(308, X), (306, 340), (308, 368), (320, 384), (338, 380), (350, 360), (356, 330), (358, X)],   # into n
        [(358, X), (356, 340), (354, B)],                                                 # n stem (retrace)
        [(354, B), (358, 340), (374, 308), (396, 298), (414, 312), (420, 340), (420, 370), (430, 386), (448, 382),
         (458, 360), (470, 300), (482, 240), (490, 190)],                                 # n hump, upstroke of t
        [(490, 190), (488, 222), (486, 256)],                                             # t stem, down to the cross
        [(486, 256), (466, 257), (446, 258)], [(446, 258), (466, 257), (486, 256)],        # cross, left and back
        [(486, 256), (508, 255), (530, 254)], [(530, 254), (508, 255), (486, 256)],        # cross, right and back
        [(486, 256), (482, 320), (480, 364), (490, 384), (510, 386), (536, 372), (562, 346), (588, 326)],  # out
    ]
    path = []
    for pts in seq:
        seg = spline(pts, 2)
        path += seg if not path else seg[1:]
    return path

def hunt(passes=3, gap=7.0):
    """the cursive word as a ribbon: the centre line traced `passes` times, alternate passes reversed, offset by `gap`
    canvas units each side (so the passes merge into one broad groove)"""
    c = hunt_path()
    if passes == 1: P = c
    else:
        offs = [(-gap, gap)[0]] if passes == 1 else ([0, gap, -gap] if passes == 3 else [-gap / 2, gap / 2])
        P = []
        for i, d in enumerate(offs):
            seg = offset(c, d) if d else list(c)
            if i % 2: seg = seg[::-1]
            P += seg
    return dict(name='hunt' if passes == 3 else 'hunt_alt', title='Hunt' + ('' if passes == 3 else ' (single line)'),
                path=P)

def hunt_alt(): return hunt(passes=1)

# ---------------------------------------------------------------- output
def make(fn):
    import cv2, sandsim
    from brighten import brighten
    p = fn()
    if 'path' in p:
        P = list(p['path'])
        # come in from / leave to the rim along the line's own direction (the ends are at the rim already)
        info = dict(loops=1, max_hop=0.0, entry=0.0)
    else:
        P, info = build(p)
        if p.get('moon'):
            # draw the crescent first (in from the rim beside it and out again), then slide along the rim to the start
            m = p["moon"]
            ma = math.degrees(math.atan2(np.mean([q[1] for q in m['poly']]) - CY, np.mean([q[0] for q in m['poly']]) - CX))
            Pm, _ = build(dict(start=rim(ma), regions=[dict(poly=m['poly'], holes=[m['hole']], name='moon')]))
            a0 = math.atan2(Pm[-1][1] - CY, Pm[-1][0] - CX); a1 = math.atan2(P[0][1] - CY, P[0][0] - CX)
            while a1 - a0 > math.pi: a1 -= 2 * math.pi
            while a1 - a0 < -math.pi: a1 += 2 * math.pi
            arc = [(CX + S * math.cos(t), CY + S * math.sin(t)) for t in np.linspace(a0, a1, 60)]
            info['rim_run_deg'] = abs(math.degrees(a1 - a0))
            P = Pm + arc + P
    pts = mc.to_pts(P); mc.check(pts)
    name = p['name']
    with open('%s/%s.thr' % (HERE, name), 'w') as f:
        f.write('# %s (patterns/icons/make_thomas.py)\n' % p['title'])
        f.write(''.join('%.5f %.5f\n' % (a, b) for a, b in pts))
    info.update(name=name, title=p['title'], points=len(pts), minutes=tc.est_minutes(pts),
                start=pts[0], end=pts[-1])
    sandsim.render(pts, size=700).save('%s/%s.png' % (HERE, name))
    im = np.array(sandsim.render([pts], size=900, real=True, erase_pitch=0.016))[:, :, ::-1].copy()
    cv2.imwrite('%s/captures/morning/icon_%s.jpg' % (ROOT, name), brighten(im), [cv2.IMWRITE_JPEG_QUALITY, 93])
    print('%-10s %6d pts  %5.1f min  loops %3d  max hop %.3f  entry %.3f  start (th %.2f, rho %.2f)  end (th %.2f, rho %.2f)' % (
        name, len(pts), info['minutes'], info['loops'], info['max_hop'], info['entry'],
        pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]), flush=True)
    return info

def sheet(infos, out):
    """main icons on the top row, alternates (name ends in _alt) on a second row"""
    from PIL import Image, ImageDraw
    import sandsim
    T = 460; lab = 58
    rows = [[i for i in infos if not i['name'].endswith('_alt')], [i for i in infos if i['name'].endswith('_alt')]]
    rows = [r for r in rows if r]; cols = max(len(r) for r in rows)
    sh = Image.new('RGB', (cols * (T + 16) + 16, len(rows) * (T + lab + 16) + 16), (34, 32, 31)); dr = ImageDraw.Draw(sh)
    f1, f2 = sandsim._font(22), sandsim._font(17)
    for rr, row in enumerate(rows):
        for k, i in enumerate(row):
            im = Image.open('%s/captures/morning/icon_%s.jpg' % (ROOT, i['name'])).resize((T, T), Image.LANCZOS)
            x, y = 16 + k * (T + 16), 16 + rr * (T + lab + 16); sh.paste(im, (x, y))
            dr.text((x + 4, y + T + 6), i['title'] + (', alternate' if rr else ''), fill=(236, 236, 236), font=f1)
            dr.text((x + 4, y + T + 32), '%.1f min to draw' % i['minutes'], fill=(176, 176, 176), font=f2)
    sh.save(out, quality=92)

ALL = [dna, rocket, aztec, hunt, rocket_alt, hunt_alt]
if __name__ == '__main__':
    want = sys.argv[1:]
    infos = [make(fn) for fn in ALL if not want or fn.__name__ in want]
    if not want: sheet(infos, ROOT + '/captures/morning/icons_thomas.jpg')
