#!/usr/bin/env python3
"""Does the arm reach the centre from the OTHER side of full extension?
Holds m2, steps m1 outward past full stretch (u = pi) and on toward u = 2*pi, measuring the ball's
radius about the centre of rotation C after each step. Output: captures/center_probe.jsonl"""
import json, math, sys
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o, calibrate as c
P = json.load(open('/home/bill/dev/WillyGarage/oasis/firmware-notes/calibration.json'))['params']
st = o.status(); m2 = st['cur2']; m1 = st['cur1']
out = open('/home/bill/dev/WillyGarage/oasis/captures/center_probe.jsonl', 'w')
targets = list(range(m1 - 600, -12400, -600))
prev_r = None; stuck = 0
for t in targets:
    o.raw(t, m2)
    m = o.measure()
    b = m.get('best')
    if not b: rec = dict(m1=t, ok=False)
    else:
        x, y = c.undistort(P, b['X'], b['Y'])
        dx, dy = x - P['Cx'], y - P['Cy']
        r = math.hypot(dx, dy); u = P['u0'] - P['b1'] * t
        rec = dict(m1=t, u=round(u, 3), r=round(r, 3), ang=round(math.degrees(math.atan2(dy, dx)), 1),
                   r_model=round(abs(2 * P['L'] * math.sin(u / 2)), 3), score=b['score'], photo=m['photo'])
        if prev_r is not None and abs(r - prev_r) < 0.006: stuck += 1
        else: stuck = 0
        prev_r = r
    out.write(json.dumps(rec) + '\n'); out.flush(); print(rec, flush=True)
    if stuck >= 3: print('ball stopped moving for 3 steps: stop'); break
print('DONE')
