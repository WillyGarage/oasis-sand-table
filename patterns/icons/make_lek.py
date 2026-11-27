#!/usr/bin/env python3
"""Sand-table icons for Lek (Bill's wife, Thai, a teacher): a Thai elephant, a hot pot, a Thai temple roofline and the
map of Thailand. Same filled style and the same machinery as patterns/creatures/make_creatures.py (imported, not
edited): regions filled with lines following their outline inward, smooth islands, one tree walk joining all loops
with one-spacing hops, densified theta-rho output.

Canvas: 600 x 600, y down, disc centre (300, 300), drawing radius 290 (rho 1).

  make_lek.py [names]   -> patterns/icons/<name>.thr + <name>.png (clean preview),
                           captures/morning/icon_<name>.jpg (honest preview on a flat erase, lightened),
                           captures/morning/icons_lek.jpg (sheet, when run with no names)
Written 2026-11-20 from captures/icon_brief.md."""
import math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(HERE + '/../..')
sys.path.insert(0, ROOT + '/patterns/creatures'); sys.path.insert(0, ROOT + '/tools')
import make_creatures as mc
mc.RHO_MIN = 0.02            # the brief's floor (make_creatures uses 0.012); to_pts and check read it from there
from make_creatures import cs, rim, circle, mirror, teeth, ellipse_poly, eye, spline
from make_dog import zigzag
import thrcommon as tc

# ---------------------------------------------------------------- local helpers
def tube(center, w0, w1, step=3.0, taper_from=0.0):
    """closed outline of a stroke along a spline centreline: width w0 up to fraction taper_from of its length, then
    tapering to w1 at the end"""
    c = np.array(spline(center, step=step))
    n = len(c); out_l, out_r = [], []
    for i in range(n):
        a, b = c[max(0, i - 1)], c[min(n - 1, i + 1)]
        t = b - a; t = t / (np.linalg.norm(t) or 1); nrm = np.array([-t[1], t[0]])
        f = max(0.0, (i / (n - 1) - taper_from) / (1 - taper_from)) if taper_from < 1 else 0.0
        w = (w0 + (w1 - w0) * f) / 2
        out_l.append(tuple(c[i] + nrm * w)); out_r.append(tuple(c[i] - nrm * w))
    return out_l + out_r[::-1]

def wave_line(x0, y0, y1, amp, per, phase=0.0, drift=0.0):
    """centreline of a rising steam curl: a sine wiggle going up from (x0, y0) to y1, amplitude growing upward"""
    pts = []
    for y in np.linspace(y0, y1, 60):
        f = (y0 - y) / (y0 - y1)
        pts.append((x0 + drift * f + amp * (0.4 + 0.6 * f) * math.sin(2 * math.pi * (y0 - y) / per + phase), y))
    return pts

def diamond(c, rx, ry): return [(c[0], c[1] - ry), (c[0] + rx, c[1]), (c[0], c[1] + ry), (c[0] - rx, c[1])]

def star(c, r_out, r_in, n=5, rot=-90):
    return [(c[0] + (r_out if i % 2 == 0 else r_in) * math.cos(math.radians(rot + 180 * i / n)),
             c[1] + (r_out if i % 2 == 0 else r_in) * math.sin(math.radians(rot + 180 * i / n))) for i in range(2 * n)]

# ---------------------------------------------------------------- 1. elephant
def elephant():
    """Thai elephant, side view facing right, standing on a ground line that runs from rim to rim. Big domed head,
    a large ear flap over the neck (its own fill, so its edge shows), a trunk hanging and curling forward at the tip,
    a tusk drawn as a smooth shape with one outline groove, and a decorated blanket on the back: wavy fill with three
    smooth diamond islands and a tasselled lower edge. The ball comes in at the left end of the ground line and ends
    in the eye."""
    E = (498, 152)
    hole, pupil = eye(E, 16, 6)
    back = spline([(122, 268), (138, 210), (180, 172), (250, 154), (318, 156), (360, 166), (382, 150)], 3)
    head = spline([(382, 150), (402, 104), (444, 74), (494, 66), (536, 84), (558, 124), (564, 170), (558, 210)], 3)
    under = spline([(540, 262), (512, 288), (478, 300), (446, 318), (420, 348), (380, 362), (300, 370), (226, 362),
                    (168, 342), (130, 308)], 3)
    body = back + head + under
    # blanket: tasselled cloth over the back, wavy field round a diamond medallion of nested diamonds
    blanket_top = [q for q in back if 206 <= q[0] <= 344]
    blanket = blanket_top + [(348, 212), (352, 290)] + teeth((352, 294), (202, 294), 6, 16, sign=1)[1:] + [(200, 230)]
    medallion = diamond((276, 228), 46, 56)
    trunk = tube([(546, 180), (556, 250), (556, 330), (546, 392), (532, 432), (542, 458), (566, 458), (576, 438),
                  (566, 420)], 84, 22)
    tusk = tube([(482, 268), (510, 300), (548, 320), (590, 310)], 36, 10)
    # Asian elephant ear: a hanging flap behind the eye, rounded at the top and narrowing to a lobe at the bottom
    ear = cs([(384, 128), (430, 116), (458, 146), (462, 204), (446, 254), (420, 284), (400, 324), (380, 288),
              (368, 226), (370, 168)])
    near_front = cs([(392, 330), (446, 324), (450, 400), (452, 476), (390, 476), (392, 400)])
    near_back = cs([(150, 300), (222, 330), (226, 400), (230, 476), (166, 476), (162, 400)])
    far_front = cs([(352, 350), (392, 346), (394, 420), (396, 476), (350, 476), (350, 420)])
    far_back = cs([(222, 340), (264, 346), (266, 420), (268, 476), (226, 476), (226, 420)])
    tail = [(((124, 270), (106, 306), (100, 350)), 11)]
    tuft = ellipse_poly((99, 360), 10, 15)
    ground = [(-20, 474), (620, 474), (620, 490), (-20, 490)]
    return dict(name='elephant', title='Thai elephant', start=rim(142), final='pupil', xf=(0.93, 0, (-30, 10)), regions=[
        pupil,
        dict(poly=tusk, levels=1, name='tusk'),
        dict(poly=trunk, name='trunk'),
        dict(poly=ear, name='ear'),
        dict(poly=medallion, name='medallion'),
        dict(poly=blanket, wavy=(3.5, 26), name='blanket'),
        dict(poly=near_front, name='near front leg'),
        dict(poly=near_back, name='near back leg'),
        dict(poly=body, holes=[hole], name='body'),
        dict(poly=far_front, name='far front leg'),
        dict(poly=far_back, name='far back leg'),
        dict(poly=tuft, strokes=tail, name='tail'),
        dict(poly=ground, name='ground')])

# ---------------------------------------------------------------- 2. hot pot
def hotpot():
    """A wide hot pot seen slightly from above: the opening is an ellipse split by an S-shaped divider into two broths
    (wavy fill on the left for the spicy side, plain fill with three smooth pieces on the right), a lip band round it,
    a deep bowl with loop handles on both sides and a small stand. Two chopsticks dip into the pot and cross on their
    way up to the upper-right rim; three wavy steam curls rise from the broth. The ball comes in where the chopsticks
    meet the rim and leaves there."""
    C = (290, 300); RX, RY = 182, 62
    opening = ellipse_poly(C, RX, RY, n=90)
    lip = ellipse_poly(C, RX + 16, RY + 14, n=90)
    # S divider: the left broth is the part of the opening left of an S curve through the centre
    yt = RY * math.sqrt(1 - (30 / RX) ** 2)
    s_curve = spline([(C[0] + 30, C[1] - yt), (C[0] - 16, C[1] - 24), (C[0] + 16, C[1] + 24), (C[0] - 30, C[1] + yt)], 3)
    a0 = math.atan2(yt / RY, -30 / RX); a1 = math.atan2(-yt / RY, 30 / RX) + 2 * math.pi   # bottom point -> top point via the left
    left_side = s_curve + [(C[0] + RX * math.cos(t), C[1] + RY * math.sin(t)) for t in np.linspace(a0, a1, 50)[1:-1]]
    left_broth = dict(poly=left_side, wavy=(3.2, 22), name='spicy broth')
    pieces = [circle((C[0] + 84, C[1] - 20), 17), circle((C[0] + 128, C[1] + 18), 15)]
    bowl = spline([(C[0] - RX - 14, C[1] + 6), (C[0] - RX + 8, C[1] + 92), (C[0] - 110, C[1] + 150), (C[0], C[1] + 166),
                   (C[0] + 110, C[1] + 150), (C[0] + RX - 8, C[1] + 92), (C[0] + RX + 14, C[1] + 6)], 3)
    handles = [(((C[0] - RX - 8, C[1] + 26), (C[0] - RX - 46, C[1] + 20), (C[0] - RX - 52, C[1] + 50),
                 (C[0] - RX - 22, C[1] + 66)), 14)]
    handles.append((tuple(mirror(handles[0][0], C[0])), 14))
    stand = [(C[0] - 92, C[1] + 156), (C[0] + 92, C[1] + 156), (C[0] + 112, C[1] + 190), (C[0] - 112, C[1] + 190)]
    # the two sticks cross at X, their tips spread apart in the broth and their tops spread apart at the rim
    X = (438, 178)
    def stick(tip, through=X, to=330.0):
        d = np.array(through) - np.array(tip); d = d / np.linalg.norm(d)
        return ((tip, tuple(np.array(tip) + d * to)), 15)
    sticks = [stick((C[0] + 46, C[1] + 8)), stick((C[0] + 160, C[1] + 16))]
    steam = [(wave_line(x, C[1] - 30, y1, 12, 64, ph, dr), 16) for x, y1, ph, dr in
             ((C[0] - 112, 96, 0.0, -10), (C[0] - 40, 48, 2.2, 0), (C[0] + 30, 112, 4.0, 6))]
    return dict(name='hotpot', title='Hot pot', start=rim(-46), xf=(1.0, 0, (0, -6)), regions=[
        dict(poly=[], strokes=sticks, name='chopsticks'),
        dict(poly=[], strokes=steam, name='steam'),
        left_broth,
        dict(poly=opening, holes=pieces, name='broth'),
        dict(poly=lip, levels=1, name='lip'),
        dict(poly=bowl, strokes=handles, name='pot'),
        dict(poly=stand, name='stand')])

# ---------------------------------------------------------------- 3. temple
def temple():
    """Thai temple, front view, symmetric: a tall steep front gable (a bold bargeboard band round a wavy-filled
    pediment with a smooth diamond in it) with a tall upswept chofa finial at the apex, and on each side two lower,
    wider roof tiers stepping out and down behind it, every eave end finished with a big hook curling up and out
    (the hang hong). Below: the hall with a pointed doorway and two windows as smooth islands, a stepped base, and
    a ground line from rim to rim. The ball comes in at the left end of the ground line and leaves there."""
    X = 300
    apex, gl = (X, 90), (176, 290)
    gable = [apex, (2 * X - gl[0], gl[1]), gl]
    ped = [(X, 142), (X + 92, 272), (X - 92, 272)]
    chofa = tube([(X, 100), (X, 66), (X - 4, 44), (X + 4, 26), (X + 22, 16)], 18, 6, taper_from=0.4)
    # each roof tier (left half; mirrored for the right) is one stroke: it starts tucked behind the tier above, runs
    # down a little shallower than the gable, and its eave end flicks out and up into a tapering hook (hang hong)
    gable_hook = tube([(gl[0] + 10, gl[1] - 6), (164, 292), (148, 284), (140, 260)], 18, 6, taper_from=0.2)
    tier1 = tube([(268, 170), (140, 338), (118, 356), (96, 360), (80, 346), (74, 320)], 40, 7, taper_from=0.62)
    tier2 = tube([(222, 262), (92, 420), (72, 438), (50, 440), (34, 424), (30, 398)], 40, 7, taper_from=0.62)
    hall = [(160, 290), (440, 290), (440, 446), (160, 446)]
    door = [(X - 28, 446), (X - 28, 372), (X, 330), (X + 28, 372), (X + 28, 446)]
    windows = [[(x - 15, 412), (x - 15, 368), (x, 348), (x + 15, 368), (x + 15, 412)] for x in (212, 388)]
    base = [(110, 446), (490, 446), (506, 466), (94, 466)]
    ground = [(-20, 466), (620, 466), (620, 482), (-20, 482)]
    return dict(name='temple', title='Thai temple', start=rim(142), xf=(0.93, 0, (0, 4)), regions=[
        dict(poly=chofa, name='chofa'),
        dict(poly=[gable_hook, mirror(gable_hook)], name='gable hooks'),
        dict(poly=ped, holes=[diamond((X, 222), 22, 32)], wavy=(3.0, 22), name='pediment'),
        dict(poly=gable, name='gable'),
        dict(poly=[tier1, mirror(tier1)], name='tier 1'),
        dict(poly=[tier2, mirror(tier2)], name='tier 2'),
        dict(poly=hall, holes=[door] + windows, name='hall'),
        dict(poly=base, name='base'),
        dict(poly=ground, name='ground')])

# ---------------------------------------------------------------- 4. Thailand
# outline in (longitude E, latitude N), clockwise from the northern tip; drawn from memory of the map, simplified,
# and the peninsula widened a little where it is thinner than two grooves
THAI = [
    (99.90, 20.42), (100.10, 20.35), (100.50, 20.10), (100.55, 19.55), (101.20, 19.55), (101.25, 19.00),
    (101.05, 18.40), (101.10, 17.55), (101.60, 17.80), (102.10, 18.15), (102.70, 17.90), (103.30, 18.30),
    (103.90, 18.35), (104.45, 17.90), (104.80, 17.35), (104.75, 16.55), (105.05, 16.05), (105.40, 15.75),
    (105.62, 15.05), (105.20, 14.35), (104.40, 14.40), (103.60, 14.40), (102.95, 14.25), (102.55, 13.60),
    (102.35, 13.00), (102.65, 12.30), (102.95, 11.70), (102.60, 11.95), (102.25, 12.20), (101.70, 12.70),
    (101.10, 12.65), (100.90, 12.85), (100.95, 13.35), (100.55, 13.55), (100.05, 13.40), (99.98, 12.80),
    (99.92, 12.30), (99.82, 11.70), (99.50, 11.05), (99.20, 10.40), (99.22, 9.70), (99.55, 9.25),
    (99.95, 9.20), (100.20, 8.60), (100.38, 7.80), (100.60, 7.20), (101.20, 6.90), (101.75, 6.55),
    (102.05, 6.15), (101.70, 5.85), (101.20, 5.65), (100.85, 6.20), (100.35, 6.50), (100.05, 6.55),
    (99.75, 6.95), (99.40, 7.45), (99.00, 7.95), (98.55, 8.25), (98.30, 8.60), (98.30, 9.10),
    (98.55, 9.80), (98.75, 10.45), (98.85, 11.00), (99.20, 11.60), (99.25, 12.20), (99.20, 12.90),
    (99.05, 13.50), (98.65, 14.20), (98.30, 14.95), (98.55, 15.40), (98.65, 16.00), (98.55, 16.70),
    (97.90, 17.50), (97.70, 18.10), (97.40, 18.55), (97.75, 19.20), (97.90, 19.75), (98.40, 19.75),
    (99.00, 19.90), (99.50, 20.15)]
BKK = (100.60, 14.25)

def thailand():
    """The map of Thailand, north up, as large as the disc allows: the broad north and the Isan plateau, the Gulf
    coast and the long peninsula running south (the "elephant's head and trunk"). Filled with lines that follow the
    coast and borders inward; Bangkok is a smooth round island with a dot where the drawing ends. The ball comes in at the
    southern tip, where the peninsula nearly touches the rim."""
    lon0, lat0 = 101.5, 13.0
    k = math.cos(math.radians(13.0))
    raw = [((lo - lon0) * k, -(la - lat0)) for lo, la in THAI]
    # fit: largest scale and offset that keep every point inside radius 282 of the centre
    best = None
    pts = np.array(raw)
    for oy in np.linspace(-1.0, 1.0, 41):
        for ox in np.linspace(-1.0, 1.0, 41):
            r = np.hypot(pts[:, 0] + ox, pts[:, 1] + oy).max()
            if best is None or r < best[0]: best = (r, ox, oy)
    r, ox, oy = best; sc = 282.0 / r
    T = lambda p: (300 + sc * ((p[0] - lon0) * k + ox), 300 + sc * (-(p[1] - lat0) + oy))
    outline = spline([T(p) for p in THAI], step=3, closed=True)
    b = T(BKK)
    hole = circle(b, 19)
    south = max(outline, key=lambda q: q[1])
    sa = math.degrees(math.atan2(south[1] - 300, south[0] - 300))
    return dict(name='thailand', title='Thailand', start=rim(sa), final='bangkok', xf=(1.0, 0, (0, 0)), clip=0.99,
                regions=[dict(poly=circle(b, 6), levels=1, name='bangkok'),
                         dict(poly=outline, holes=[hole], name='land')])

# ---------------------------------------------------------------- output (own paths; same pipeline as make_creatures)
def make(fn):
    import cv2
    import sandsim
    from brighten import brighten
    p = fn(); P, info = mc.build(p); pts = mc.to_pts(P); mc.check(pts)
    name = p['name']
    with open('%s/%s.thr' % (HERE, name), 'w') as f:
        f.write('# %s (patterns/icons/make_lek.py)\n' % p['title'])
        f.write(''.join('%.5f %.5f\n' % (a, b) for a, b in pts))
    info.update(name=name, title=p['title'], points=len(pts), length=mc.path_len(pts), minutes=tc.est_minutes(pts))
    sandsim.render(pts, size=700).save('%s/%s.png' % (HERE, name))
    im = np.array(sandsim.render(pts, size=900, real=True, erase_pitch=0.016))[:, :, ::-1].copy()
    cv2.imwrite('%s/captures/morning/icon_%s.jpg' % (ROOT, name), brighten(im), [cv2.IMWRITE_JPEG_QUALITY, 93])
    s, e = info['start'], info['end']
    print('%-12s %6d pts  %5.1f min  loops %3d  max hop %.3f  entry %.3f  start rho %.2f  end (%.0f,%.0f)' % (
        name, len(pts), info['minutes'], info['loops'], info['max_hop'], info['entry'],
        math.hypot(s[0] - 300, s[1] - 300) / 290, e[0], e[1]), flush=True)
    return info

def sheet(infos, out):
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

ALL = [elephant, hotpot, temple, thailand]
if __name__ == '__main__':
    want = sys.argv[1:]
    infos = [make(fn) for fn in ALL if not want or fn.__name__ in want]
    if not want: sheet(infos, ROOT + '/captures/morning/icons_lek.jpg')
