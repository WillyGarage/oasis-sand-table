#!/usr/bin/env python3
"""section_faces_sim NAME cx cy size px [--table mini|big] : simulate captures/relief-study/v3/faces/NAME.thr in a window (push rule,
depth 2.2, ball r 3.2). Writes NAME_win<cx>_<cy>_<size>_<px>_sim.png and _h.npy. SIMULATION ONLY."""
import argparse, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_sim as ss, thrcommon as tc
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument('name')
for k in ('cx', 'cy', 'size', 'px'): ap.add_argument(k, type=float)
ap.add_argument('--table', default='mini'); ap.add_argument('--clip', action='store_true', help='simulate only the runs of path inside the window (+margin), each run on its own'); ap.add_argument('--dir', default=ROOT + '/captures/relief-study/v3/faces')
a = ap.parse_args()
t0 = time.time()
T = ss.WinTable(a.cx, a.cy, a.size, px=a.px, kind=a.table)
tr = tc.read_thr(os.path.join(a.dir, a.name + '.thr'))
if a.clip:
    R = 114.0 if a.table == 'mini' else 420.0
    x, y = tr[:, 1] * R * np.cos(tr[:, 0]), tr[:, 1] * R * np.sin(tr[:, 0])
    h = a.size / 2 + 10
    ok = (np.abs(x - a.cx) < h) & (np.abs(y - a.cy) < h)
    idx = np.flatnonzero(np.diff(np.r_[0, ok.astype(int), 0]))
    for i0, i1 in zip(idx[::2], idx[1::2]):
        T.run(tr[max(i0 - 1, 0):min(i1 + 1, len(tr))])
else:
    T.run(tr)
out = os.path.join(a.dir, '%s_win%g_%g_%g_%g' % (a.name, a.cx, a.cy, a.size, a.px))
T.render_win().save(out + '_sim.png'); np.save(out + '_h.npy', T.h.astype(np.float32))
print('done %.0f s' % (time.time() - t0))
