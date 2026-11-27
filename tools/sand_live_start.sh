#!/usr/bin/env bash
# Supervised live run (Bill's go, 2026-11-25): after a whole-table clear (ends at the centre or the rim), park the ball on the
# centre circle's edge at theta 0, write that point as the driver's start file, reset the live app's table to empty,
# and start the driver in REAL mode against the live site for N turns (default 4). Stops on any table fault.
set -euo pipefail
D=/home/bill/dev/WillyGarage/oasis; T=http://10.0.0.149; BASE=https://sand.example.com
N=${1:-4}
cd "$D"
TOKEN=$(cat secrets/sand-worker-token)
python3 - <<'EOF'
import sys, time
sys.path.insert(0, 'tools')
from big_lib import status, get
s = status(); m = s['move']
assert not m['run'] and not s['job']['run'] and not m['fault'] and m['arm_homed'] and m['rad_homed'], m
def wait():
    t = time.time()
    while time.time() - t < 60:
        s = status()
        if not s['move']['run'] and not s['job']['run']: return
        time.sleep(0.3)
rho_now = m['carriage'] / s['cfg']['rmax']
# after an outward clear the ball is at the rim: go round the rim to 0 deg first, then straight in along the 0-degree
# slice line (a frame line in both rings), so no curve is dragged across the fresh sand
get('/goto?th=0&rho=%.5f' % max(rho_now, 0.0132)); wait()
get('/goto?th=0&rho=0.29588'); wait()
print('parked on the centre circle edge: carriage', status()['move']['carriage'])
EOF
mkdir -p captures/sand-app/driver
printf '0.00000 0.29588\n' > captures/sand-app/driver/start.thr
# the table was just cleared: forget what the zones held (keep each zone's last clear direction so they keep alternating)
python3 - <<'EOF2'
import json, os
p = 'captures/sand-app/driver-state.json'
if os.path.exists(p):
    d = json.load(open(p)); d['holds'] = {}; d['recover_zone'] = None; json.dump(d, open(p, 'w'), indent=1)
for f in ('captures/sand-app/driver-state-world.npy', 'captures/sand-app/driver-state-layers.pkl'):
    if os.path.exists(f): os.remove(f)
EOF2
curl -s -X POST -H "X-Worker-Token: $TOKEN" "$BASE/api/worker/reset" | head -c 300; echo
exec python3 tools/sand_driver.py --real --allow-live --base "$BASE" --token "$TOKEN" \
     --start-file captures/sand-app/driver/start.thr --max-turns "$N"
