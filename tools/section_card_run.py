#!/usr/bin/env python3
"""Run the section_tests card variants through the windowed simulator. Usage: section_card_run.py NAME [erase]
NAME = card_<order>_<outline> as written by section_tests.py / section_comb.save (in captures/relief-study/v3/sections/tests)"""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_sim as ss, thrcommon as tc
D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'captures/relief-study/v3/sections/tests')
name = sys.argv[1]
erase = float(sys.argv[2]) if len(sys.argv) > 2 else 0.035
t0 = time.time()
T = ss.WinTable(0, 0, 90, px=0.1)
if erase > 0:
    T.erase_window(erase)
T.run(tc.read_thr(os.path.join(D, name + '.thr')))
im = T.render_win()
im.save(os.path.join(D, name + '_sim.png'))
np.save(os.path.join(D, name + '_h.npy'), T.h.astype(np.float32))
print(name, 'done in %.0f s' % (time.time() - t0))
