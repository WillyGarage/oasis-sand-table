#!/usr/bin/env python3
"""Shading test plate for the real Mini (Nov 23). Path only; played after an inward erase (ball starts at the centre).

  A  tone ramp: strip x -45..45, y 51..69; strokes across the strip (along y), spacing growing 0.6 -> 6 mm along x.
  B  direction fan: 8 patches 16 x 16 mm, spacing 3.5 mm, stroke angle 0, 22.5, ... 157.5 deg
     (row y=28: 0..67.5, row y=6: 90..157.5; x centres -33, -11, 11, 33).
  C  shaded sphere: circle centre (0, -45), radius 25; horizontal strokes, spacing 0.6 mm at the top growing to 5 mm
     at the bottom (light from the top).
Travel between parts runs through erased sand (it is a test plate).

    python3 tools/shade_test.py captures/shadetest/plate.thr
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_path as rp

R = 114.0


def comb_positions(a, b, sp_fn):
    """Positions from a to b with local spacing sp_fn(t) (t = position)."""
    out, t = [], a
    while t <= b + 1e-9:
        out.append(t)
        t += sp_fn(t)
    return out


def zigzag(lines):
    """lines: list of (p, q) segment endpoints; returns a boustrophedon polyline."""
    P = []
    for k, (p, q) in enumerate(lines):
        P += [p, q] if k % 2 == 0 else [q, p]
    return P


def ramp():
    xs = comb_positions(-45, 45, lambda x: 0.6 + (6.0 - 0.6) * (x + 45) / 90)
    return zigzag([((x, 51.0), (x, 69.0)) for x in xs])


def patch(cx, cy, ang, sp=3.5, half=8.0):
    a = math.radians(ang); d = np.array([math.cos(a), math.sin(a)]); n = np.array([-d[1], d[0]])
    lines = []
    for s in np.arange(-half * 1.42, half * 1.42 + 1e-9, sp):
        # clip line c + s n + t d to the square |x-cx|,|y-cy| <= half
        lo, hi = -1e9, 1e9
        base = np.array([cx, cy]) + s * n
        for i in range(2):
            if abs(d[i]) < 1e-9:
                if abs(base[i] - (cx, cy)[i]) > half:
                    lo, hi = 1, 0
                continue
            t1 = ((cx, cy)[i] - half - base[i]) / d[i]; t2 = ((cx, cy)[i] + half - base[i]) / d[i]
            lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
        if hi - lo > 1.0:
            lines.append((tuple(base + lo * d), tuple(base + hi * d)))
    return zigzag(lines)


def sphere(cx=0.0, cy=-45.0, r=25.0):
    ys = comb_positions(cy - r + 0.5, cy + r - 0.5, lambda y: 0.6 + (5.0 - 0.6) * ((cy + r) - y) / (2 * r))
    ys = ys[::-1]                                   # top (fine) first
    lines = []
    for y in ys:
        h = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
        if h > 1.0:
            lines.append(((cx - h, y), (cx + h, y)))
    return zigzag(lines)


def build():
    P = [(0.0, 0.0), (0.0, -10.0), (-50.0, -10.0)]          # start: centre, go round the patch rows
    P += [(-50.0, 6.0)]
    for k, ang in enumerate([90, 112.5, 135, 157.5]):         # row y=6
        pp = patch(-33 + 22 * k, 6.0, ang)
        P += [(pp[0][0], -4.0 if k == 0 else P[-1][1]), pp[0]] if k == 0 else [(P[-1][0], 17.0), (pp[0][0], 17.0), pp[0]]
        P += pp
    P += [(P[-1][0], 17.0), (50.0, 17.0), (50.0, 28.0)]
    for k, ang in enumerate([67.5, 45, 22.5, 0]):              # row y=28, right to left
        pp = patch(33 - 22 * k, 28.0, ang)
        P += [(P[-1][0], 39.0), (pp[0][0], 39.0), pp[0]]
        P += pp
    P += [(P[-1][0], 44.0), (-50.0, 44.0), (-50.0, 51.0)]
    P += ramp()
    P += [(P[-1][0], 75.0), (60.0, 75.0), (60.0, -45.0), (30.0, -45.0)]
    sp = sphere()
    P += [(30.0, sp[0][1]), sp[0]] + sp
    end = P[-1]
    P += [(end[0], -80.0), (0.0, -108.0)]
    return np.array(P, float)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'captures/shadetest/plate.thr'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    P = build()
    np.save(out.replace('.thr', '_path.npy'), P)
    tr, near = rp.to_thr_pts(P, R)
    rp.write_thr(out, tr, 'shade test plate: ramp, direction fan, sphere')
    print(len(tr), 'points', round(rp.path_len_m(tr, R), 2), 'm', round(rp.mini_minutes(tr), 1), 'min; near centre', near)
