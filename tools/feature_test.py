#!/usr/bin/env python3
"""Feature-size test for faces (Nov 23). Path only; played after an inward erase (ball starts at the centre).
Left half: features cut as single grooves on erased sand. Right half: a smooth 0.6 mm combed patch first
(x 5..75, y -30..40), then the same features cut on top of it.
Features per side (column at x0): circles of diameter 8, 12, 16, 20 mm; an almond 'eye' 14 x 7 mm; a 12 mm arc 'smile'.

    python3 tools/feature_test.py captures/featuretest/plate.thr
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_path as rp

R = 114.0


def circle(cx, cy, d, start=-90):
    t = np.radians(np.linspace(start, start + 360, 73))
    return [(cx + d / 2 * math.cos(a), cy + d / 2 * math.sin(a)) for a in t]


def almond(cx, cy, w=14.0, h=7.0):
    t = np.linspace(0, 1, 25)
    top = [(cx - w / 2 + w * u, cy + h / 2 * math.sin(math.pi * u)) for u in t]
    bot = [(cx + w / 2 - w * u, cy - h / 2 * math.sin(math.pi * u)) for u in t]
    return top + bot[1:]


def smile(cx, cy, w=12.0):
    t = np.linspace(200, 340, 20)
    r = w / 2 / math.sin(math.radians(70))
    return [(cx + r * math.cos(math.radians(a)), cy + r * 0.6 + r * math.sin(math.radians(a))) for a in t]


def features(x0):
    """Column of features; travel between them goes straight down the column's left side (x0 - 14)."""
    P = []
    items = [lambda: circle(x0, 32, 8), lambda: circle(x0, 18, 12), lambda: circle(x0, 1, 16), lambda: circle(x0, -20, 20),
             lambda: almond(x0 + 20, 25), lambda: smile(x0 + 20, 5)]
    for f in items:
        pts = f()
        lane = x0 - 16
        if P:
            P += [(lane, P[-1][1])]
        P += [(lane, pts[0][1]), pts[0]]
        P += pts
    return P


def comb_patch(xa, xb, ya, yb, sp=0.6):
    P, k, y = [], 0, ya
    while y <= yb:
        P += [(xa, y), (xb, y)] if k % 2 == 0 else [(xb, y), (xa, y)]
        y += sp; k += 1
    return P


def build():
    P = [(0.0, 0.0), (0.0, -45.0), (-70.0, -45.0), (-70.0, 45.0)]
    P += features(-55.0)
    P += [(P[-1][0], -45.0), (5.0, -45.0), (5.0, -30.0)]
    P += comb_patch(5.0, 75.0, -30.0, 40.0)
    P += [(P[-1][0], 47.0), (12.0, 47.0)]
    P += features(28.0)
    end = P[-1]
    P += [(end[0], -60.0), (0.0, -108.0)]
    return np.array(P, float)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'captures/featuretest/plate.thr'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    P = build()
    np.save(out.replace('.thr', '_path.npy'), P)
    tr, near = rp.to_thr_pts(P, R)
    rp.write_thr(out, tr, 'feature size test')
    print(len(tr), 'points', round(rp.path_len_m(tr, R), 2), 'm', round(rp.mini_minutes(tr), 1), 'min; near centre', near)
