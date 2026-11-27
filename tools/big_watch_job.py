#!/usr/bin/env python3
"""Watch a running job on the 36-inch table and stop it at the first sign of trouble: any firmware fault, or the job's
point counter not advancing for STALL seconds while the job claims to be running (the table stepped nothing for minutes
while grinding on 2026-11-25 without reporting a fault). Prints progress every 60 s. Exit 0 when the job ends cleanly."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from big_lib import status, get
STALL = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
t0 = time.time(); last_pt, last_change, last_print = -1, time.time(), 0
while True:
    s = status(); m, j = s['move'], s['job']
    if m['fault']:
        get('/stop'); print('FAULT %d: %s' % (m['fault'], json.dumps(m)), flush=True); sys.exit(1)
    if not j['run'] and not m['run']:
        print('job ended: end %d, pt %d/%d, %.1f min, carriage %d, slip %d' % (j['end'], j['pt'], j['n'], (time.time() - t0) / 60, m['carriage'], m['slip_err']), flush=True)
        sys.exit(0 if j['end'] == 1 else 2)
    if j['pt'] != last_pt:
        last_pt, last_change = j['pt'], time.time()
    elif j['run'] and not j['paused'] and time.time() - last_change > STALL:
        get('/stop'); print('STALLED: point %d did not advance for %.0f s; stopped. move=%s' % (j['pt'], STALL, json.dumps(m)), flush=True); sys.exit(3)
    if time.time() - last_print > 60:
        print('%4.0f s  %d/%d  carriage %d  slip %d' % (time.time() - t0, j['pt'], j['n'], m['carriage'], m['slip_err']), flush=True); last_print = time.time()
    time.sleep(0.5)
