#!/usr/bin/env python3
"""Eye-style test at real face size (Nov 23). Path only; played after an OUTWARD erase (ball starts at the rim).
Four pairs of eyes (each eye 22 mm wide, centres 38 mm apart):
  A (top left)     single upper-lid and lower-lid strokes
  B (top right)    upper lid as 3 close passes (1.5 mm), single lower lid
  C (bottom left)  B + iris: tight spiral dot r 4 mm under the upper lid
  D (bottom right) C + outer-corner wing + brow as 3 passes

    python3 tools/eye_test.py captures/eyetest/plate.thr
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_path as rp

R = 114.0
W, HU, HL = 22.0, 7.0, 4.0


def arc(cx, cy, w, h, sign, n=24, off=0.0):
    u = np.linspace(-1, 1, n)
    return [(cx + u_ * w / 2, cy + sign * (h * (1 - u_ ** 2) + off)) for u_ in u]


def spiral(cx, cy, r=4.0, pitch=0.8):
    pts, t = [], 0.0
    while True:
        rr = pitch * t / (2 * math.pi)
        if rr > r:
            break
        pts.append((cx + rr * math.cos(t), cy + rr * math.sin(t)))
        t += 0.35
    return pts


def eye(cx, cy, style, side):
    P = []
    passes = 1 if style == 'A' else 3
    for k in range(passes):
        a = arc(cx, cy, W + k * 0.5, HU, +1, off=k * 1.5)
        P += a if k % 2 == 0 else a[::-1]
    lower = arc(cx, cy, W - 2, HL, -1)
    P += [lower[-1]] + lower[::-1] if passes % 2 == 1 else lower
    if style in 'CD':
        P += spiral(cx, cy + 2.0)[::-1]
    if style == 'D':
        ox = cx + side * W / 2
        P += [(ox, cy + 0.5), (ox + side * 4.0, cy + 3.0), (ox, cy + 0.5)]
        for k in range(3):
            b = arc(cx, cy + 15.0, W + 4, 3.0, +1, off=k * 1.5)
            P += b if k % 2 == 0 else b[::-1]
    return P


def build():
    """Travel runs along lanes 12 mm below each row and down the left and right edges, never across an eye."""
    P = [(-100.0, -45.0), (-100.0, 33.0)]
    rows = [('A', -45.0, 45.0, 1), ('B', 45.0, 45.0, 1), ('D', 45.0, -15.0, -1), ('C', -45.0, -15.0, -1)]
    for style, px, py, direction in rows:
        eyes = [(-1, px - 19.0), (1, px + 19.0)]
        if direction < 0:
            eyes = eyes[::-1]
        for side, ex in eyes:
            e = eye(ex, py, style, side)
            P += [(e[0][0], py - 12.0), e[0]] + e + [(e[-1][0], py - 12.0)]
        if style == 'B':
            P += [(100.0, 33.0), (100.0, -27.0)]
    P += [(-100.0, -27.0), (-100.0, -45.0)]
    return np.array(P, float)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'captures/eyetest/plate.thr'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    P = build()
    np.save(out.replace('.thr', '_path.npy'), P)
    tr, near = rp.to_thr_pts(P, R)
    rp.write_thr(out, tr, 'eye style test')
    print(len(tr), 'points', round(rp.path_len_m(tr, R), 2), 'm', round(rp.mini_minutes(tr), 1), 'min')
