#!/usr/bin/env python3
"""Test (c): is an erase spiral still needed before a combed picture?  Pre-state = our old raptor.thr drawn on an erased
tray (window run). Then the card is combed either (1) after a normal erase spiral (pitch 0.035) or (2) directly on top.
Usage: section_card_c.py erase|noerase   (writes card_c_<arg>_sim.png in captures/relief-study/v3/sections/tests)"""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_sim as ss, thrcommon as tc
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = ROOT + '/captures/relief-study/v3/sections/tests'
arg = sys.argv[1]
t0 = time.time()
T = ss.WinTable(0, 0, 90, px=0.1)
T.erase_window(0.035)
T.run(tc.read_thr(ROOT + '/patterns/creatures/raptor.thr'))
T.render_win().save(D + '/card_c_pre_sim.png')
if arg == 'erase':
    T.erase_window(0.035)
T.run(tc.read_thr(D + '/card_subject_first_none.thr'))
T.render_win().save(D + '/card_c_%s_sim.png' % arg)
print(arg, 'done %.0f s' % (time.time() - t0))
