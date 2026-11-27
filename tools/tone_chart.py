#!/usr/bin/env python3
"""Tone chart for the real Mini (November 22): which brightness and texture each comb spacing gives in real sand.
4 x 4 grid of 18 mm square patches, pitch 24 mm, centred on the table:
  row 1 (top):    spacing 0.6, 0.9, 1.2, 1.8 mm, strokes along x
  row 2:          the same, strokes along y
  row 3:          spacing 2.5, 3.5, 5.0, 7.0 mm, strokes along x
  row 4 (bottom): the same, strokes along y
Gaps between patches keep the erase spiral (pitch 0.02) as the reference tone. Path only; played after an inward erase.

    python3 tools/tone_chart.py captures/tonechart/chart.thr
"""
import json, math, os, sys
import numpy as np
from shapely.geometry import box
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_comb as sc
import sand_relief_path as rp

R = 114.0
ROWS = [([0.6, 0.9, 1.2, 1.8], 0.0), ([0.6, 0.9, 1.2, 1.8], 90.0), ([2.5, 3.5, 5.0, 7.0], 0.0), ([2.5, 3.5, 5.0, 7.0], 90.0)]
PITCH, HALF = 24.0, 9.0


def chart():
    secs, cells = [], []
    for i, (sp, ang) in enumerate(ROWS):
        cy = (1.5 - i) * PITCH
        cols = range(4) if i % 2 == 0 else range(3, -1, -1)      # snake order keeps travel short
        for j in cols:
            cx = (j - 1.5) * PITCH
            name = 'r%d_s%.1f_a%d' % (i + 1, sp[j], ang)
            secs.append(dict(name=name, kind='subject', poly=[list(p) for p in box(cx - HALF, cy - HALF, cx + HALF, cy + HALF).exterior.coords],
                             spacing=sp[j], mode='angle', angle=ang))
            cells.append(dict(name=name, cx=cx, cy=cy, spacing=sp[j], angle=ang))
    return dict(r_work=R, shrink=0.0, bg_gap=0.0, sections=secs), cells


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'captures/tonechart/chart.thr'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    plan, cells = chart()
    res = sc.comb(plan, order='plan')
    P = np.asarray(res['path'], float)
    end = P[-1]; a = math.atan2(end[1], end[0])
    P = np.vstack([[[0.0, 0.0], [0.0, 24.0], [-60.0, 24.0], [-60.0, P[0][1]]], P, [[0.97 * R * math.cos(a), 0.97 * R * math.sin(a)]]])
    np.save(out.replace('.thr', '_path.npy'), P)
    json.dump(cells, open(out.replace('.thr', '_cells.json'), 'w'), indent=1)
    tr, near = rp.to_thr_pts(P, R)
    rp.write_thr(out, tr, 'tone chart 4x4')
    sc.plan_png(res, out.replace('.thr', '_plan.png'))
    print(len(tr), 'points', round(rp.path_len_m(tr, R), 2), 'm', round(rp.mini_minutes(tr), 1), 'min; travel over finished',
          res['report'].get('travel_over_finished_mm'))
