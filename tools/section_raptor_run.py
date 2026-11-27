#!/usr/bin/env python3
"""Simulate a section-combed .thr (whole tray at 0.2 mm/px, or a window at 0.1 mm/px). SIMULATION ONLY.
    section_raptor_run.py NAME whole|head|tail [--erase 0.035] [--out DIR]
NAME = file stem in captures/relief-study/v3/sections/ ; writes NAME_<view>_sim.png and NAME_<view>_h.npy"""
import argparse, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_sim as ss, thrcommon as tc
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS = dict(whole=(0, 0, None, 0.2), head=(-55, 52, 100, 0.1), tail=(36, 0, 100, 0.1))
ap = argparse.ArgumentParser()
ap.add_argument('name'); ap.add_argument('view')
ap.add_argument('--erase', type=float, default=0.035)
ap.add_argument('--dir', default=ROOT + '/captures/relief-study/v3/sections')
ap.add_argument('--tag', default='')
ap.add_argument('--pre', default=None, help='a .thr already on the tray (after a normal erase) before this picture; --erase then applies before the picture')
ap.add_argument('--depth', type=float, default=None)
ap.add_argument('--ball_r', type=float, default=None)
a = ap.parse_args()
cx, cy, size, px = VIEWS[a.view]
phys = {k: v for k, v in (('depth', a.depth), ('ball_r', a.ball_r)) if v is not None}
t0 = time.time()
T = ss.WinTable(cx, cy, size, px=px, **phys)
if a.pre:
    T.erase_window(0.035)
    T.run(tc.read_thr(a.pre))
if a.erase > 0:
    T.erase_window(a.erase)
T.run(tc.read_thr(os.path.join(a.dir, a.name + '.thr')))
out = os.path.join(a.dir, '%s_%s%s' % (a.name, a.view, a.tag))
T.render_win().save(out + '_sim.png')
np.save(out + '_h.npy', T.h.astype(np.float32))
print(a.name, a.view, 'done %.0f s' % (time.time() - t0), T.p)
