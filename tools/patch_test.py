#!/usr/bin/env python3
"""Combing patch test for the real Mini (November 22). Writes the path only; playing it is done by hand with
POST /thr + /play after an inward erase leaves the ball at the centre.

Three patches side by side, each combed back and forth with strokes 20 mm long (along x), advancing 40 mm (along y):
stroke spacing 1.2 mm (maker's head), 2.3 mm (maker's thigh), 5.0 mm (maker's background). Patch centres at
x = -40, 0, +40 mm, y from 15 to 55 mm. Travel between patches runs 7 mm outside them; at the end the ball goes
straight out to the rim, away from the patches.

    python3 tools/patch_test.py captures/patchtest/patches.thr
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_path as rp

R = 114.0
PATCHES = [(-40.0, 1.2), (0.0, 2.3), (40.0, 5.0)]
Y0, Y1, HALF = 15.0, 55.0, 10.0


def patch(xc, s, upward):
    ys = Y0 + s * np.arange(int(math.floor((Y1 - Y0) / s + 1e-9)) + 1)
    if not upward:
        ys = ys[::-1]
    pts = []
    for k, y in enumerate(ys):
        xa, xb = (xc - HALF, xc + HALF) if k % 2 == 0 else (xc + HALF, xc - HALF)
        pts += [(xa, y), (xb, y)]
    return pts


def build():
    P = [(0.0, 0.0)]
    up = True
    for i, (xc, s) in enumerate(PATCHES):
        pp = patch(xc, s, up)
        if i > 0:                                     # travel outside the patches: lane 7 mm above or below
            lane = Y1 + 7 if not up else Y0 - 7
            P += [(P[-1][0], lane), (pp[0][0], lane)]
        else:
            P += [(pp[0][0], Y0 - 7)]
        P += pp
        up = not up
    last = P[-1]
    lane = Y1 + 7 if last[1] > (Y0 + Y1) / 2 else Y0 - 7
    P += [(last[0], lane), (last[0] + 15, lane)]
    a = math.atan2(P[-1][1], P[-1][0])
    P += [(0.97 * R * math.cos(a), 0.97 * R * math.sin(a))]
    return np.array(P)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'captures/patchtest/patches.thr'
    P = build()
    np.save(out.replace('.thr', '_path.npy'), P)
    tr, near = rp.to_thr_pts(P, R)
    rp.write_thr(out, tr, 'patch test 1.2 / 2.3 / 5.0 mm')
    print(len(tr), 'points', round(rp.path_len_m(tr, R), 2), 'm', round(rp.mini_minutes(tr), 1), 'min est', 'near centre', near)
