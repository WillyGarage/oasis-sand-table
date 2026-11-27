#!/usr/bin/env python3
"""Side-by-side: the maker's photo rectified into TABLE mm (same window, same scale) and our simulation.
    python3 tools/trex_compare.py DIR NAME VIEW [--out FILE]      VIEW as in trex_sim.py (needs DIR/NAME_<view>_sim.png)"""
import argparse, json, math, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trex_rectify as R
import trex_decode as D
VIEWS = dict(whole=(0, 0, None, 0.2), head=(-30, 62, 90, 0.1), body=(-15, -8, 90, 0.1), tail=(55, 15, 90, 0.1), feet=(10, -72, 100, 0.1))

_cache = {}
def maker_window(cx, cy, n, px):
    """maker photo resampled on a table-mm window: n x n pixels of px mm centred at (cx, cy) (table frame, y up)"""
    if 'im' not in _cache:
        _cache['im'], _cache['e'] = R.fit()
    im, e = _cache['im'], _cache['e']
    (ex, ey), (w, h), ang = e
    a = np.radians(ang)
    e1 = np.array([np.cos(a), np.sin(a)]); e2 = np.array([np.cos(a + np.pi / 2), np.sin(a + np.pi / 2)])
    if e2[0] < 0: e2 = -e2
    if e1[1] > 0: e1 = -e1
    c = n / 2.0
    xs = (np.arange(n) + 0.5 - c) * px + cx; ys = -((np.arange(n) + 0.5 - c) * px) + cy
    X, Y = np.meshgrid(xs, ys)
    Xr = X - D.SHIFT[0]; Yr = Y - D.SHIFT[1]                  # table -> rectified frame
    mx = Xr / R.R_EDGE * (h / 2); my = Yr / R.R_EDGE * (w / 2)
    Px = ex + mx * e2[0] + my * e1[0]; Py = ey + mx * e2[1] + my * e1[1]
    return cv2.remap(im, Px.astype(np.float32), Py.astype(np.float32), cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)

def grid(img, cx, cy, px, step=10):
    o = img.copy(); n = o.shape[0]; c = n / 2.0
    for v in range(-130, 131, step):
        for (vv, horiz) in ((v, False), (v, True)):
            p = (vv - (cy if horiz else cx)) / px
            q = int(round(c + (-p if horiz else p)))
            if 0 <= q < n:
                if horiz: cv2.line(o, (0, q), (8, q), (0, 0, 255), 1)
                else: cv2.line(o, (q, 0), (q, 8), (0, 0, 255), 1)
    return o

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dir'); ap.add_argument('name'); ap.add_argument('view'); ap.add_argument('--out', default=None)
    a = ap.parse_args()
    v = VIEWS.get(a.view) or tuple(float(x) for x in a.view.split(','))
    cx, cy, size, px = v
    sim = cv2.imread(os.path.join(a.dir, '%s_%s_sim.png' % (a.name, a.view)))
    n = sim.shape[0]
    mk = maker_window(cx, cy, n, px * (sim.shape[0] / n))
    simg = cv2.cvtColor(sim, cv2.COLOR_BGR2RGB) if False else sim
    cv2.putText(mk, 'maker (rectified)', (10, 30), 0, 0.9, (0, 0, 255), 2); cv2.putText(simg, 'ours (simulation)', (10, 30), 0, 0.9, (0, 0, 255), 2)
    both = np.hstack([mk, simg])
    s = min(1.0, 2400 / both.shape[1])
    if s < 1: both = cv2.resize(both, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    cv2.imwrite(a.out or os.path.join(a.dir, 'ours_vs_maker_%s.png' % a.view), both)
