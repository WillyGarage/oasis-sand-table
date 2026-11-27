#!/usr/bin/env python3
"""Simulate one or more consecutive .thr files on the Mini with the calibrated real-sand physics (simulation only).
    python3 tools/sim_thr.py OUT.png part1.thr [part2.thr ...] [--erase 0.02] [--px 0.1]
Writes OUT.png (phone-photo look, whole tray) and OUT_h.npy (heights)."""
import argparse, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_sim as s, thrcommon as tc
ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('files', nargs='+')
ap.add_argument('--erase', type=float, default=0.02); ap.add_argument('--px', type=float, default=0.1)
ap.add_argument('--size', type=int, default=2000)
a = ap.parse_args()
t0 = time.time()
pts = np.vstack([np.asarray(tc.read_thr(f), float) for f in a.files])
T = s.simulate_parallel([pts], erase=a.erase, mm_px=a.px, deposit='real')
np.save(a.out.replace('.png', '_h.npy'), T.h.astype(np.float32))
T.render(light='photo', out_px=a.size).save(a.out)
print('done %.0f s' % (time.time() - t0))
