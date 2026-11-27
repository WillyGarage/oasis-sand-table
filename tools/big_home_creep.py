#!/usr/bin/env python3
"""Find the 36-inch table's radius from an UNKNOWN position without long pushes into the centre stop.
  big_home_creep.py [--max-cycles 12]
/homeradius from an unknown position searches the whole 62,480-step travel; on 2026-11-25 it once missed the touch
from far out and pushed into the stop for 10-20 s (thumps). Here the counter is relabelled to a small value before each
short touch search, so a missed touch costs at most ~4,000 steps of pushing (2.5 s) instead of the whole travel:
  enable, /homearm; then repeat: /setcarriage?c=3000, /goto inward to 800 (2,200 steps in), /homeradius (searches at
  most carriage + 3,200 = 4,000 steps); stop as soon as homing reports success (state 2).
Each cycle covers about 6,200 steps (39 mm). Prints every step. Never runs if anything is moving."""
import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from big_lib import status, get

ap = argparse.ArgumentParser(); ap.add_argument('--max-cycles', type=int, default=12); a = ap.parse_args()


def wait(limit=120):
    t = time.time()
    while time.time() - t < limit:
        s = status(); m = s['move']
        if not m['run'] and not s['job']['run'] and not s['pulse']['run'] and m.get('home') != 1:
            return s
        time.sleep(0.3)
    get('/stop'); raise SystemExit('timeout; stopped')


s = status(); m = s['move']
if m['run'] or s['job']['run'] or s['pulse']['run']:
    raise SystemExit('table is moving')
print(get('/enable?on=1'))
if m['fault']:
    print(get('/fault?clear=1'))
print('homearm:', get('/homearm', timeout=90)); s = wait()
if not s['move']['arm_homed']:
    raise SystemExit('arm did not home: %s' % s['move'])
v0 = s['cfg']['vball']; get('/cfg?vball=100')
try:
    for k in range(a.max_cycles):
        print(get('/setcarriage?c=3000'))
        get('/goto?rho=%.6f' % (800 / s['cfg']['rmax'])); s = wait()
        if s['move']['fault']:
            raise SystemExit('fault during the creep: %s' % s['move'])
        r = get('/homeradius'); s = wait(); m = s['move']
        print('cycle %d: home state %d, went %d, carriage %d, rad_homed %d' % (k + 1, m['home'], m['home_went'], m['carriage'], m['rad_homed']), flush=True)
        if m['home'] == 2 and m['rad_homed']:
            print('radius homed after %d cycle(s)' % (k + 1)); break
        if m['home'] != 15:
            raise SystemExit('homing failed in an unexpected state %d: %s (%s)' % (m['home'], m, r))
    else:
        raise SystemExit('no touch within %d cycles' % a.max_cycles)
finally:
    get('/cfg?vball=%g' % v0)
