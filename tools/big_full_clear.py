#!/usr/bin/env python3
"""Clear the whole 36-inch table, alternating direction every time (Bill: "alternate spiral in and spiral out so the
sand stays reasonably distributed"). The last direction is remembered in captures/sand-app/table-clear-state.json;
`--dir in|out` overrides it once. Inward: move to the rim first, settle, spiral in to the centre. Outward: move to the
centre first, settle, spiral out to the rim. Each stage runs under tools/big_watch_job.py (stops on any fault or a
frozen job). Speed is the table's saved vclear; spacing 2.5 mm at the current rmax.
Zone clears (centre circle, each slice) alternate separately, per zone, in the driver's state (captures/sand-app/
driver-state.json "dirs")."""
import sys, os, json, time, subprocess, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from big_lib import status, get, ROOT

STATE = os.path.join(ROOT, 'captures/sand-app/table-clear-state.json')
ap = argparse.ArgumentParser()
ap.add_argument('--dir', choices=('in', 'out'))
ap.add_argument('--dry', action='store_true', help='print what would run, move nothing')
a = ap.parse_args()
st = json.load(open(STATE)) if os.path.exists(STATE) else {'last': 'in', 'history': []}
d = a.dir or ('out' if st.get('last') == 'in' else 'in')
s = status(); m = s['move']; cfg = s['cfg']
mm = cfg['rmax'] / 160.0
pitch = 2.5 / mm
print('whole-table clear %s (last was %s), rho 1 = %.0f mm, vclear %s mm/s' % (d, st.get('last'), mm, cfg.get('vclear')), flush=True)
if a.dry:
    sys.exit(0)
if m['run'] or s['job']['run'] or m['fault'] or not m['arm_homed'] or not m['rad_homed']:
    raise SystemExit('table not ready: %s' % m)


def watch(stall):
    r = subprocess.run(['python3', os.path.join(HERE, 'big_watch_job.py'), str(stall)])
    if r.returncode:
        raise SystemExit('stopped (watcher exit %d)' % r.returncode)


# an inward spiral ends 12 mm from the centre, not at it: its last tight laps scraped a bare disc in the middle (Bill's photo, 2026-11-26)
start, frm, to = ('1', 1, 12.0 / mm) if d == 'in' else (str(1000 / cfg['rmax']), 0, 1)
get('/goto?th=0&rho=%s' % start); watch(5)
time.sleep(1.5)
t0 = time.time()
print(get('/spiral?from=%g&to=%g&pitch=%.6f' % (frm, to, pitch)), flush=True)
watch(3)
st['last'] = d
st.setdefault('history', []).append({'dir': d, 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'minutes': round((time.time() - t0) / 60, 1),
                                     'vclear': cfg.get('vclear'), 'rmax': cfg['rmax']})
os.makedirs(os.path.dirname(STATE), exist_ok=True)
json.dump(st, open(STATE, 'w'), indent=1)
print('done: last direction now %s' % d)
