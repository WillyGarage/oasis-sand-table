#!/usr/bin/env python3
"""Watch whatever the table is drawing until it is idle with an empty queue, without sending it any motion command,
then (if it finished cleanly) take the straightened portrait photo.
  watch_piece.py NAME OUT.jpg      e.g. watch_piece.py lek captures/morning/lek_sand.jpg
Prints the timeline and the final state. Never sends /stop."""
import sys, time
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o
name, out = sys.argv[1], sys.argv[2]
t0 = time.time(); last = None
while True:
    try: s = o.status()
    except Exception: time.sleep(5); continue
    key = (s['job'], s['state'], tuple(s.get('queue', [])), s.get('paused'), s.get('fault'))
    if key != last: print(time.strftime('%H:%M:%S'), s['job'], s['state'], s.get('queue'), s.get('now'), 'paused' if s.get('paused') else '', 'fault %s' % s.get('fault'), flush=True); last = key
    if s['state'] == 'idle' and not s.get('queue') and time.time() - t0 > 30: break
    time.sleep(3)
print('final', {k: s.get(k) for k in ('now', 'progress', 'fault', 'homed', 'idx_err', 'rho', 'auto')}, flush=True)
if s.get('now') == name and s.get('progress', 0) > 0.99 and not s.get('fault'):
    o.portrait(o.D + '/' + out); print('photo taken', out)
else: print('NOT finished cleanly: no photo')
