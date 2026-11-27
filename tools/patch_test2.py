#!/usr/bin/env python3
"""Second combing test for the real Mini (November 22, evening). Path only; played by hand after an inward erase.

Why: the first test (tools/patch_test.py, phone photo) showed one rib per TWO strokes: 1.2 mm strokes gave ribs about
2.3 mm apart, matching the maker's thigh. The maker's head ribs are about 1.2 mm, so this tries 0.6 mm strokes. Bill
also noted the maker's fills are rarely straight; the two bands here are combed ACROSS a curved band (strokes fan
round the curve, as on the maker's tail and limbs).

  A: rectangle 20 x 40 mm (x -55..-35, y 15..55), straight strokes 0.6 mm apart
  B: curved band 18 mm wide round an arc (centre (35, 20), radius 30, upper half), strokes across it 1.2 mm apart
  C: the same band shape below (centre (35, -20), lower half), strokes 0.6 mm apart

    python3 tools/patch_test2.py captures/patchtest2/patches2.thr
"""
import math, os, sys
import numpy as np
from shapely.geometry import LineString, box
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_comb as sc
import sand_relief_path as rp

R = 114.0


def arc(cx, cy, r, a0, a1, n=60):
    t = np.radians(np.linspace(a0, a1, n))
    return [[cx + r * math.cos(a), cy + r * math.sin(a)] for a in t]


def band(spine, half):
    return [list(p) for p in LineString(spine).buffer(half, cap_style=2).exterior.coords]


SPB = arc(35, 20, 30, 160, 20)
SPC = arc(35, -20, 30, 200, 340)
PLAN = dict(r_work=R, shrink=0.0, bg_gap=0.0, sections=[
    dict(name='A_straight_0.6', kind='subject', poly=[list(p) for p in box(-55, 15, -35, 55).exterior.coords],
         spacing=0.6, mode='angle', angle=0.0),
    dict(name='B_band_1.2', kind='subject', poly=band(SPB, 9.0), spacing=1.2, mode='spine', spine=SPB),
    dict(name='C_band_0.6', kind='subject', poly=band(SPC, 9.0), spacing=0.6, mode='spine', spine=SPC),
])

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'captures/patchtest2/patches2.thr'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    res = sc.comb(PLAN, order='plan')
    P = np.asarray(res['path'], float)
    # start from the centre (where the inward erase leaves the ball), end straight out to the rim away from the patches
    end = P[-1]
    a = math.atan2(end[1], end[0])
    st = P[0]                                     # enter patch A from outside it, not across it
    entry = [[0.0, 0.0], [-25.0, 8.0], [-62.0, 8.0], [-62.0, st[1]]] if st[0] < -45 else [[0.0, 0.0], [-25.0, 8.0], [st[0], 8.0]]
    P = np.vstack([entry, P, [[0.97 * R * math.cos(a), 0.97 * R * math.sin(a)]]])
    np.save(out.replace('.thr', '_path.npy'), P)
    tr, near = rp.to_thr_pts(P, R)
    rp.write_thr(out, tr, 'patch test 2: 0.6 straight, 1.2 and 0.6 curved bands')
    name = os.path.splitext(os.path.basename(out))[0]
    sc.plan_png(res, os.path.join(os.path.dirname(out), name + '_plan.png'))
    print(len(tr), 'points', round(rp.path_len_m(tr, R), 2), 'm', round(rp.mini_minutes(tr), 1), 'min est; near centre',
          near, '; travel over finished', res['report'].get('travel_over_finished_mm'))
