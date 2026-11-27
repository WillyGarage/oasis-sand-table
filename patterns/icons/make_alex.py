#!/usr/bin/env python3
"""Sand-table icons for Alex (a teacher who loves film and music) plus Thanksgiving: a film clapperboard, an acoustic
guitar, a classroom apple on books, a turkey and a pumpkin. Same filled style and the same machinery as
patterns/creatures/make_creatures.py (imported, not edited): each icon is a list of regions on a 600 x 600 canvas
(y down, disc centre (300, 300), drawing radius 290), filled with lines following each outline inward, holes left as
smooth islands, all loops joined into one line by a tree of one-line-spacing hops.

Brief: captures/icon_brief.md. Differences from make_creatures: rho is kept >= 0.02 (not 0.012), outputs are named
icon_<name> and go to patterns/icons/ and captures/morning/.

  make_alex.py [names]   -> patterns/icons/<name>.thr + <name>.png (clean preview),
                            captures/morning/icon_<name>.jpg (honest, lightened); with no names also the sheet
                            captures/morning/icons_alex.jpg
Written 2026-11-20."""
import math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(HERE + '/../..')
sys.path.insert(0, ROOT + '/patterns/creatures'); sys.path.insert(0, ROOT + '/tools')
import make_creatures as mc
from make_creatures import cs, rim, circle, mirror, ellipse_poly, eye, spline
import thrcommon as tc

mc.RHO_MIN = 0.02            # this brief: stay at least 0.02 from the exact centre (to_pts and check read this)
CX, CY, S = mc.CX, mc.CY, mc.S

def rect(x0, y0, x1, y1): return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

def rot_pts(pts, c, deg):
    a = math.radians(deg); ca, sa = math.cos(a), math.sin(a)
    return [(c[0] + (x - c[0]) * ca - (y - c[1]) * sa, c[1] + (x - c[0]) * sa + (y - c[1]) * ca) for x, y in pts]

def stick(x0, x1, y0, y1, w, gap, slant, frame=15):
    """a clapstick: a one-line frame round a bar (x0..x1, y0..y1) and, inside it, bold slanted parallelogram stripes
    (w wide, gap apart, leaning by `slant`) clipped to the inside, with smooth sand between them.
    Returns (frame polygon, frame hole, [stripe polygons])"""
    ix0, ix1, iy0, iy1 = x0 + frame, x1 - frame, y0 + frame, y1 - frame
    stripes = []; x = ix0 - abs(slant) + 8
    while x < ix1:
        p = [(x + slant, iy0), (x + slant + w, iy0), (x + w, iy1), (x, iy1)]
        p = [(min(max(px, ix0 + 2), ix1 - 2), py) for px, py in p]           # clip to the inside of the frame
        if max(px for px, _ in p) - min(px for px, _ in p) > 14: stripes.append(p)
        x += w + gap
    return rect(x0, y0, x1, y1), rect(ix0 - 1, iy0 - 1, ix1 + 1, iy1 + 1), stripes

# ---------------------------------------------------------------- 1. clapperboard
def clapper():
    """Film clapperboard, slightly open. The two clapsticks are bars outlined by one line, each holding bold slanted
    stripes (filled) with smooth sand between them, so the stripes read as black-and-white; the slate below is a thick
    frame round a smooth face with two plain rule lines. The open stick hinges at the left on a round pin. The ball
    comes in at the slate's lower-right corner on the rim and ends on the hinge pin."""
    x0, x1 = 104, 496
    slate = rect(x0, 282, x1, 522)
    face = rect(x0 + 50, 282 + 48, x1 - 50, 522 - 50)            # smooth face inside a 3-line frame
    rules = [(((x0 + 44, 388), (x1 - 44, 388)), 12), (((x0 + 44, 440), (x1 - 44, 440)), 12)]
    lf, lh, ls = stick(x0, x1, 176, 276, 66, 48, 50)              # fixed lower clapstick
    H = (x0 + 6, 170)                                             # hinge
    uf, uh, us = stick(x0, x1, 66, 166, 66, 48, -50)             # open upper clapstick, turned up about the hinge
    R = lambda p: rot_pts(p, H, -11)
    pin = dict(poly=circle((x0 + 4, 170), 12), levels=1, name='pin')
    return dict(name='clapper', title='Clapperboard', start=rim(44), final='pin', xf=(0.92, 0, (0, 22)), regions=[
        pin,
        *[dict(poly=R(p), pitch=0.8, name='up%d' % k) for k, p in enumerate(us)],
        dict(poly=R(uf), holes=[R(uh)], name='upper stick'),
        *[dict(poly=p, pitch=0.8, name='low%d' % k) for k, p in enumerate(ls)],
        dict(poly=lf, holes=[lh], name='lower stick'),
        dict(poly=[], strokes=rules, name='rules'),
        dict(poly=slate, holes=[face], name='slate'),
    ])

def clapper_alt():
    """Film reel: a big round reel with five round windows (smooth islands) round a hub, and a film strip running off
    its bottom out to the left rim. The ball comes in along the film strip and
    ends on the hub. (Sprocket holes were tried and read as a scribble at this size.)"""
    C = (330, 262); R = 212
    wins = [circle((C[0] + 132 * math.cos(math.radians(a)), C[1] + 132 * math.sin(math.radians(a))), 52)
            for a in range(-90, 270, 72)]
    hub = dict(poly=circle(C, 20), levels=2, name='hub')
    yb = C[1] + R                                                 # film leaves the bottom of the reel, runs left
    strip = rect(-20, yb - 70, C[0], yb)
    sprockets = []
    return dict(name='clapper_alt', title='Film reel', start=rim(170), final='hub', xf=(1.0, 0, (0, -14)), regions=[
        hub,
        dict(poly=circle(C, R, 90), holes=wins + [circle(C, 36)], name='reel'),
        dict(poly=strip, holes=sprockets, name='film'),
    ])

# ---------------------------------------------------------------- 2. guitar
def guitar():
    """Acoustic guitar drawn upright and turned 45 degrees so it lies diagonally across the disc, headstock to the upper
    right. A wide figure-eight body with a pinched waist, the sound hole a smooth round island with one ring round it,
    the bridge a smooth bar, a broad neck cut by four bold fret gaps, and a headstock with three pegs each side. The
    ball comes in at the bottom of the body on the rim and ends in the sound hole ring."""
    body = cs([(300, 226), (370, 234), (410, 280), (402, 336), (382, 374), (424, 414), (446, 476), (424, 546),
               (300, 586), (176, 546), (154, 476), (176, 414), (218, 374), (198, 336), (190, 280), (230, 234)], 3)
    SH = (300, 342)
    hole = circle(SH, 42)
    ring = dict(poly=circle(SH, 54), holes=[hole], levels=1, name='ring')
    bridge = rect(240, 480, 360, 510)
    neck = rect(274, 70, 326, 234)
    frets = [rect(272, y, 328, y + 14) for y in (104, 144, 182, 216)]
    head = cs([(272, 76), (258, 44), (262, 16), (300, 8), (338, 16), (342, 44), (328, 76)], 2)
    pegs = [(((262, y), (236, y)), 13) for y in (26, 46, 64)] + [(((338, y), (364, y)), 13) for y in (26, 46, 64)]
    return dict(name='guitar', title='Guitar', start=rim(135), final='ring', xf=(0.965, 45, (0, 0)), regions=[
        ring,
        dict(poly=head, name='head'),
        dict(poly=[], strokes=pegs, name='pegs'),
        dict(poly=neck, holes=frets, name='neck'),
        dict(poly=body, holes=[circle(SH, 56), bridge], name='body'),
    ])

# ---------------------------------------------------------------- 3. classroom
def pencil(foot, top, w=34):
    """a pencil from its eraser end `foot` to its point `top`: eraser, smooth ferrule gap, body, sharpened wood cone
    drawn as an outline, lead tip filled. Returns region dicts, tip first."""
    L = math.hypot(top[0] - foot[0], top[1] - foot[1]); ang = math.degrees(math.atan2(top[1] - foot[1], top[0] - foot[0]))
    R = lambda p: rot_pts([(foot[0] + x, foot[1] + y) for x, y in p], foot, ang)
    h = w / 2
    cone0 = L - 70
    return [dict(poly=R([(L - 22, -h * 0.34), (L, 0), (L - 22, h * 0.34)]), name='lead'),
            dict(poly=R([(cone0, -h), (L - 4, 0), (cone0, h)]), levels=1, name='cone'),
            dict(poly=R(rect(46, -h, cone0 - 2, h)), name='pencil body'),
            dict(poly=R(rect(0, -h, 30, h)), name='eraser')]

def classroom():
    """A big apple sitting on a stack of two books, with a pencil standing point-up beside the stack, all on a desk line
    that runs rim to rim. The apple has a smooth highlight, a stem and a leaf; each book is a thick cover round a smooth
    page edge with one line through it. The ball comes in at the left end of the desk and ends on the leaf."""
    ax, ay = 262, 226                                     # apple centre
    apple = cs([(ax, ay - 106), (ax + 50, ay - 116), (ax + 112, ay - 100), (ax + 142, ay - 40), (ax + 136, ay + 34),
                (ax + 100, ay + 92), (ax + 50, ay + 114), (ax, ay + 112), (ax - 50, ay + 114), (ax - 100, ay + 92),
                (ax - 136, ay + 34), (ax - 142, ay - 40), (ax - 112, ay - 100), (ax - 50, ay - 116)], 3)
    shine = cs([(ax - 104, ay - 62), (ax - 116, ay - 18), (ax - 106, ay + 30), (ax - 88, ay + 48), (ax - 92, ay + 14),
                (ax - 96, ay - 26), (ax - 84, ay - 66)], 2)       # smooth crescent of light along the left edge
    stem = [(((ax, ay - 102), (ax + 4, ay - 128), (ax + 16, ay - 150)), 13)]
    leaf = dict(poly=cs([(ax + 16, ay - 132), (ax + 54, ay - 166), (ax + 108, ay - 168), (ax + 88, ay - 130),
                         (ax + 44, ay - 118)], 2), name='leaf')
    t1, b1 = 340, 404                                     # top book
    t2, b2 = 408, 476                                     # bottom book
    book1 = rect(118, t1, 410, b1); pages1 = rect(118, t1 + 18, 392, b1 - 18)
    book2 = rect(84, t2, 438, b2);  pages2 = rect(102, t2 + 18, 438, b2 - 18)
    page_lines = [(((118, (t1 + b1) / 2), (386, (t1 + b1) / 2)), 8), (((108, (t2 + b2) / 2), (438, (t2 + b2) / 2)), 8)]
    desk = [(-20, 480), (620, 480), (620, 496), (-20, 496)]
    return dict(name='classroom', title='Apple, books, pencil', start=rim(137), final='leaf', xf=(1.0, 0, (6, 18)),
                regions=[
        leaf,
        dict(poly=[], strokes=stem, name='stem'),
        dict(poly=apple, holes=[shine], name='apple'),
        *pencil((486, 478), (468, 196)),
        dict(poly=[], strokes=page_lines, name='pages'),
        dict(poly=book1, holes=[pages1], name='book1'),
        dict(poly=book2, holes=[pages2], name='book2'),
        dict(poly=desk, name='desk'),
    ])

# ---------------------------------------------------------------- 4. turkey
def turkey():
    """Front view. A wide fan of nine big rounded tail feathers behind the body, out to the rim (filled with wavy lines:
    the textured part), a round plain-filled body, a head on a neck above it with two eyes, a short beak, a long red
    wattle hanging from the beak, and two legs with three-toed feet. The ball comes in at the tip of the leftmost
    feather on the rim and ends in an eye."""
    C = (300, 350)                                       # fan centre
    feathers = []
    for k in range(9):
        a = math.radians(180 + 22.5 * k)                 # 180..360 deg: left, over the top, right
        ca, sa = math.cos(a), math.sin(a); nx, ny = -sa, ca
        P = lambda r, off: (C[0] + r * ca + nx * off, C[1] + r * sa + ny * off)
        feathers.append(dict(poly=cs([P(70, 0), P(170, 34), P(250, 36), P(292, 0), P(250, -36), P(170, -34)], 3),
                             wavy=(3.5, 26), wavy_from=1, name='feather%d' % k))
    body = ellipse_poly((300, 392), 120, 126, 0, 60)
    head = cs([(300, 168), (334, 180), (342, 216), (330, 252), (324, 290), (276, 290), (270, 252), (258, 216),
               (266, 180)], 2)
    e1, p1 = eye((284, 208), 11, 5); e2, p2 = eye((316, 208), 11, 5)
    p2['name'] = 'pupil2'
    beak = [(286, 228), (314, 228), (300, 250)]
    wattle = cs([(300, 246), (314, 256), (318, 290), (308, 312), (296, 296), (294, 264)], 2)
    legs = [(((266, 506), (258, 552)), 15), (((334, 506), (342, 552)), 15),
            (((258, 552), (226, 574)), 13), (((258, 552), (258, 584)), 13), (((258, 552), (288, 574)), 13),
            (((342, 552), (312, 574)), 13), (((342, 552), (342, 584)), 13), (((342, 552), (374, 574)), 13)]
    return dict(name='turkey', title='Turkey', start=rim(180), final='pupil', xf=(1.0, 0, (0, 0)), regions=[
        p1, p2,
        dict(poly=beak, name='beak'),
        dict(poly=wattle, name='wattle'),
        dict(poly=head, holes=[e1, e2], name='head'),
        dict(poly=body, name='body'),
        dict(poly=[], strokes=legs, name='legs'),
        *feathers,
    ])

# ---------------------------------------------------------------- 5. pumpkin
def pumpkin():
    """A big round pumpkin made of five overlapping oval lobes (the middle one in front, the outer ones shorter and
    behind), each filled with lines following its own outline, so the fill draws the curved ribs. A thick curved stem
    on top, a vine tendril curling off to the left, and a pointed leaf to the right with a smooth central vein. The
    ball comes in where the pumpkin's right side meets the rim and ends at the tip of the tendril curl."""
    cy = 376
    mid = ellipse_poly((300, cy), 96, 178, 0, 60)
    l1, r1 = ellipse_poly((206, cy + 4), 104, 168, 0, 60), ellipse_poly((394, cy + 4), 104, 168, 0, 60)
    l2, r2 = ellipse_poly((126, cy + 12), 84, 142, 0, 60), ellipse_poly((474, cy + 12), 84, 142, 0, 60)
    stem = cs([(280, 214), (282, 168), (294, 128), (318, 100), (340, 108), (324, 138), (318, 172), (322, 214)], 2)
    tendril = [(286 - 110 * s, 172 - 30 * s - 22 * math.sin(math.pi * s)) for s in np.linspace(0, 1, 14)]
    cc = (tendril[-1][0], tendril[-1][1] - 26)
    curl = [(cc[0] - 26 * (1 - 0.55 * s) * math.sin(math.pi * 2.1 * s), cc[1] + 26 * (1 - 0.55 * s) * math.cos(math.pi * 2.1 * s))
            for s in np.linspace(0, 1, 34)]
    tip = dict(poly=[], strokes=[(tuple(tendril + curl), 11)], name='tendril')
    leaf = cs([(330, 160), (352, 108), (396, 70), (452, 50), (482, 60), (486, 104), (466, 150), (420, 186), (362, 192)], 2)
    vein = rot_pts(rect(-64, -9, 56, 9), (0, 0), -40)
    vein = [(x + 414, y + 124) for x, y in vein]
    return dict(name='pumpkin', title='Pumpkin', start=rim(19), final='tendril', xf=(0.965, 0, (4, -4)), regions=[
        tip,
        dict(poly=stem, name='stem'),
        dict(poly=leaf, holes=[vein], name='leaf'),
        dict(poly=mid, name='mid'),
        dict(poly=l1, name='l1'), dict(poly=r1, name='r1'),
        dict(poly=l2, name='l2'), dict(poly=r2, name='r2'),
    ])

# ---------------------------------------------------------------- output
def make(fn, previews=True):
    import cv2
    import sandsim
    from brighten import brighten
    p = fn(); P, info = mc.build(p); pts = mc.to_pts(P); mc.check(pts)
    name = p['name']
    with open('%s/%s.thr' % (HERE, name), 'w') as f:
        f.write('# %s (patterns/icons/make_alex.py)\n' % p['title'])
        f.write(''.join('%.5f %.5f\n' % (a, b) for a, b in pts))
    info.update(name=name, title=p['title'], points=len(pts), length=mc.path_len(pts), minutes=tc.est_minutes(pts))
    if previews:
        sandsim.render(pts, size=700).save('%s/%s.png' % (HERE, name))
        im = np.array(sandsim.render(pts, size=900, real=True, erase_pitch=0.016))[:, :, ::-1].copy()
        cv2.imwrite('%s/captures/morning/icon_%s.jpg' % (ROOT, name), brighten(im), [cv2.IMWRITE_JPEG_QUALITY, 93])
    s, e = info['start'], info['end']
    print('%-12s %6d pts  %5.1f min  loops %3d  max hop %.3f  entry %.3f  start %s  end %s' % (
        name, len(pts), info['minutes'], info['loops'], info['max_hop'], info['entry'],
        '(%.0f,%.0f)' % s, '(%.0f,%.0f)' % e), flush=True)
    return info

def sheet(infos, out):
    """main icons on the top row, alternates (name ends in _alt) on a second row; labels with draw minutes"""
    from PIL import Image, ImageDraw
    import sandsim
    T = 420; lab = 58
    rows = [[i for i in infos if not i['name'].endswith('_alt')], [i for i in infos if i['name'].endswith('_alt')]]
    rows = [r for r in rows if r]
    cols = max(len(r) for r in rows)
    sh = Image.new('RGB', (cols * (T + 16) + 16, len(rows) * (T + lab + 16) + 16), (34, 32, 31)); dr = ImageDraw.Draw(sh)
    f1, f2 = sandsim._font(22), sandsim._font(17)
    for rr, row in enumerate(rows):
        for k, i in enumerate(row):
            im = Image.open('%s/captures/morning/icon_%s.jpg' % (ROOT, i['name'])).resize((T, T), Image.LANCZOS)
            x, y = 16 + k * (T + 16), 16 + rr * (T + lab + 16); sh.paste(im, (x, y))
            dr.text((x + 4, y + T + 6), i['title'] + (', alternate' if rr else ''), fill=(236, 236, 236), font=f1)
            dr.text((x + 4, y + T + 32), '%.1f min to draw' % i['minutes'], fill=(176, 176, 176), font=f2)
    sh.save(out, quality=92)

ALL = [clapper, guitar, classroom, turkey, pumpkin, clapper_alt]
if __name__ == '__main__':
    want = sys.argv[1:]
    infos = [make(fn) for fn in ALL if not want or fn.__name__ in want]
    if not want: sheet(infos, ROOT + '/captures/morning/icons_alex.jpg')
