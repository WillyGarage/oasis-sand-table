#!/usr/bin/env python3
"""Simulate the trex .thr parts in order on a clean tray (no erase), whole tray or a window, with the push rule (depth 2.2, ball r 3.2)
unless --depth/--ball_r. SIMULATION ONLY (never contacts a table).
    python3 tools/trex_sim.py DIR NAME VIEW [--tag v1]      VIEW = whole | head | body | tail | feet | cx,cy,size,px
writes DIR/NAME_<view>_sim.png and _h.npy"""
import argparse, glob, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_sim as ss, thrcommon as tc
VIEWS = dict(whole=(0, 0, None, 0.2), head=(-30, 62, 90, 0.1), body=(-15, -8, 90, 0.1), tail=(55, 15, 90, 0.1), feet=(10, -72, 100, 0.1))
ap = argparse.ArgumentParser()
ap.add_argument('dir'); ap.add_argument('name'); ap.add_argument('view')
ap.add_argument('--depth', type=float, default=None); ap.add_argument('--ball_r', type=float, default=None)
a = ap.parse_args()
v = VIEWS.get(a.view) or tuple(float(x) for x in a.view.split(','))
cx, cy, size, px = v
phys = {k: x for k, x in (('depth', a.depth), ('ball_r', a.ball_r)) if x is not None}
t0 = time.time()
T = ss.WinTable(cx, cy, size, px=px, **phys)
for f in sorted(glob.glob(os.path.join(a.dir, a.name + '_part*.thr'))):
    T.run(tc.read_thr(f))
out = os.path.join(a.dir, '%s_%s' % (a.name, a.view))
T.render_win().save(out + '_sim.png')
np.save(out + '_h.npy', T.h.astype(np.float32))
print(a.name, a.view, 'done %.0f s' % (time.time() - t0), T.p)
