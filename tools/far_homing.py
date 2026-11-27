#!/usr/bin/env python3
"""Far-stop homing repeatability: from several start poses (both halves of the arm, several m2 rotations) run /home
(m1 NEGATIVE into the far stop) and measure with the camera where the ball rests. Log: captures/far_homing.jsonl
Needs firmware v5 (/home = far stop), table idle, camera, LED ring solid."""
import json, math, sys, time
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import numpy as np, oasislib as o
OLD = json.load(open(o.D + '/firmware-notes/calibration.json'))['params']
Cx, Cy = OLD['Cx'], OLD['Cy']
def und(X, Y):
    d = 1.0 / (1 - OLD['gx'] * X - OLD['gy'] * Y / (1 + OLD['s'])); return X * d, Y * d / (1 + OLD['s'])
def polar(b):
    x, y = und(b['X'], b['Y']); dx, dy = x - Cx, y - Cy
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))
st = o.status(); cal = st['cal']
EF, B1, B2 = cal['ef'], cal['b1'], cal['b2']
def home_wait():
    o.get('/home?wrap=0'); return o.wait_idle(timeout=200)
# (target elbow angle, m2 offset from previous home)
STARTS = [(5.6, 0), (4.5, 5000), (2.0, -3000), (1.2, 9000), (0.7, -6000), (5.0, 12000), (3.9, -9000), (1.6, 15000), (6.0, -4000)]
home_wait()
out = open(o.D + '/captures/far_homing.jsonl', 'a'); rows = []
m = o.measure(); b = m['best']; print('first home: r=%.3f ang=%.1f' % polar(b), flush=True)
rows.append(dict(i=-1, **dict(zip(('r', 'ang'), polar(b))), m2h=o.status()['cur2'], photo=m['photo']))
for i, (e, d) in enumerate(STARTS):
    s = o.status(); m2h = s['m2h']
    m1 = int(round((EF + B2 * d - e) / B1)); m2 = m2h + d
    t0 = time.time(); o.raw(m1, m2)
    a = o.measure(); ra = polar(a['best']) if a['best'] else (None, None)
    s = home_wait(); t1 = time.time() - t0
    h = o.measure(); hb = h['best']; r, ang = polar(hb)
    rec = dict(i=i, e_start=e, m1_start=m1, m2_start=m2, r_start=ra[0], ang_start=ra[1], r=r, ang=ang, m2h=s['cur2'], score=hb['score'], photo=h['photo'], start_photo=a['photo'], secs=round(t1))
    rows.append(rec); out.write(json.dumps(rec) + '\n'); out.flush()
    print('start e=%.1f m1=%d dm2=%+d (meas r %.3f) -> home r=%.3f ang=%.1f m2h=%d score %.2f' % (e, m1, d, ra[0] or -1, r, ang, s['cur2'], hb['score']), flush=True)
rs = np.array([r['r'] for r in rows]); print('radius about C: mean %.4f sd %.4f range %.3f..%.3f' % (rs.mean(), rs.std(ddof=1), rs.min(), rs.max()))
# angle vs m2h: linear fit, residual = position scatter at the stop
m2h = np.array([r['m2h'] for r in rows], float); ang = np.unwrap(np.radians([r['ang'] for r in rows]))
k = np.polyfit(m2h, ang, 1); res = ang - np.polyval(k, m2h)
print('angle slope %.4e rad/step (A+K ~ 6.1e-4); residual sd %.2f deg, max %.2f deg' % (k[0], np.degrees(res.std(ddof=2)), np.degrees(abs(res).max())))
