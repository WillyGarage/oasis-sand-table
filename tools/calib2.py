#!/usr/bin/env python3
"""Camera + arm calibration for firmware v6 (working side of the arm: rim .. exact centre).

  calib2.py collect [N]   visit N (default 70) poses over the working side and a full arm turn, photograph each,
                          append to captures/calib3.jsonl. Run in the background (about 7 s per pose).
  calib2.py fit [--write] [--camera] [--since=HH:MM:SS]      (--camera: refit only the camera after the table was moved)
                          fit the camera (a homography from the sand plane to image pixels) and the arm (EF, B1, B2,
                          residual backlash) together. --write saves firmware-notes/calibration.json and sends the
                          arm constants to the table (/cal ... save=1).
  calib2.py check [N] [--record FILE.csv]   go to N polar targets with /goto and report the camera error for each.
                          Record the exact transmitted coordinates and source photo for independent measurement.

Arm model (same as the firmware header): e = EF - B1*m1 + B2*(m2 - M2H); r = 2L sin(e/2); phi = c0 + G*m2 - e/2.
B1 = G = 2*pi/10240 and B2 = G/5 exactly (whole-number gearing); only EF (where the home stop is) is fitted.
Plane coordinates are centred on the arm's rotation centre, in units where the arm's full reach 2L is 0.92.
L, G and c0 are held fixed: L sets the unit, G comes from the arm sensor (10240 steps per turn), and c0 only sets
which way theta = 0 points (the homography absorbs any rotation).
Camera model: pixel = H * (x, y, 1). A homography is exact for a flat sand surface seen by a pinhole camera; the
earlier 3-number perspective model left 5-10% errors toward the rim.
The table must be homed (/home) first."""
import json, math, sys, time, random
import numpy as np
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o
D = o.D
LOG = D + '/captures/calib3.jsonl'
CAL = D + '/firmware-notes/calibration.json'
GFIX = 2 * math.pi / 10240.0     # motor-2 steps per arm turn, from the GPIO13 sensor
# The gearing is whole numbers (found 2026-11-20): both motors are 2048 full steps per turn; motor 2 drives the disc 5:1
# (10240.0 steps per arm turn, measured over 22 sensor passes); motor 1 turns the centre pulley 1:1 and the elbow pulley
# is 5:1 on it. So B1 = G and B2 = G/5 EXACTLY. They are not fitted: a 1% error in B2/B1 pulls the ball inward by
# 0.5 rad of elbow per 33 arm turns (that is why the first erase stopped short of the rim).
ARM0 = dict(L=0.46, EF=0.3108799, B1=GFIX, B2=GFIX / 5, G=GFIX, c0=2.4662713, lam1=0.0, lam2=0.0)

def _h0_from_old(old):
    """starting homography from the previous ellipse-based camera constants"""
    import cv2
    ell = o.ref_ellipse(); th = np.radians(ell['angle_deg']); c, s = np.cos(th), np.sin(th)
    src, dst = [], []
    for x in np.linspace(-0.9, 0.9, 7):
        for y in np.linspace(-0.9, 0.9, 7):
            xx, yy = old['Cx'] + x, old['Cy'] + y
            d = 1 + old['gx'] * xx + old['gy'] * yy
            X, Y = xx / d, yy * (1 + old['s']) / d
            px, py = X, -Y
            u = (c * px + s * py) * ell['a']; v = (-s * px + c * py) * ell['b']
            src.append((x, y)); dst.append((ell['cx'] + c * u - s * v, ell['cy'] + s * u + c * v))
    H, _ = cv2.findHomography(np.array(src, np.float64), np.array(dst, np.float64))
    return (H / H[2, 2]).tolist()

def load_params():
    j = json.load(open(CAL))
    if j.get('model') == 'v6h':
        p = j['params']; p.update(B1=GFIX, B2=GFIX / 5, G=GFIX); return p
    p = dict(ARM0)
    old = j['params']
    for k in ('EF', 'c0'):
        if k in old: p[k] = old[k]
    p['H'] = _h0_from_old(old)
    return p

def plane_to_px(p, x, y):
    H = np.asarray(p['H']); w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
    return (H[0, 0] * x + H[0, 1] * y + H[0, 2]) / w, (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / w
def px_to_plane(p, u, v):
    Hi = np.linalg.inv(np.asarray(p['H'])); w = Hi[2, 0] * u + Hi[2, 1] * v + Hi[2, 2]
    return (Hi[0, 0] * u + Hi[0, 1] * v + Hi[0, 2]) / w, (Hi[1, 0] * u + Hi[1, 1] * v + Hi[1, 2]) / w

def model(p, m1, m2, m2h, d1=0, d2=0):
    """-> plane x, y (about the rotation centre), r, phi. d1/d2 = last direction of each motor (residual backlash)."""
    m1 = m1 + d1 * p['lam1'] / 2; m2 = m2 + d2 * p['lam2'] / 2
    e = p['EF'] - p['B1'] * m1 + p['B2'] * (m2 - m2h)
    r = 2 * p['L'] * np.sin(e / 2)
    phi = p['c0'] + p['G'] * m2 - e / 2
    return r * np.cos(phi), r * np.sin(phi), r, phi

def fw_consts(p):
    return dict(l=p['L'], ef=p['EF'], b1=p['B1'], b2=p['B2'], a=p['G'] - p['B2'] / 2, a1=p['B1'] / 2, k=p['B2'] / 2,
                phi0=p['c0'] - p['EF'] / 2)

def see(p, m1, m2, m2h, tol=0.10):
    """photo; pick the ball candidate nearest the model prediction (within tol sand radii), else the top score.
    -> (candidate with px, x, y (plane), score), near?, photo, first candidates"""
    m = o.measure(prev_rel=None)
    cs = m.get('cands') or []
    mx, my, _, _ = model(p, m1, m2, m2h)
    for c in cs:
        c['x'], c['y'] = [round(float(v), 4) for v in px_to_plane(p, c['px'][0], c['px'][1])]
    near = sorted([c for c in cs if math.hypot(c['x'] - mx, c['y'] - my) <= tol and c['score'] > 0.3],
                  key=lambda c: -c['score'])
    b = near[0] if near else (cs[0] if cs else None)
    return b, bool(near), m.get('photo'), cs[:4]

def cmd_collect(n=70):
    p = load_params(); st = o.status()
    assert st['homed'] == 1, 'home the table first'
    m2h = st['m2h']; rng = random.Random(int(time.time()))
    e = 5.0; m2 = float(st['cur2']); last = [st['cur1'], st['cur2']]; dirs = [-1, 1]
    for i in range(n):
        e = e + rng.uniform(-1.3, 1.3)
        if i % 9 == 0: e = rng.uniform(6.0, 6.27)                    # near the centre
        if i % 9 == 4: e = rng.uniform(3.25, 3.6)                    # near the rim
        while not 3.25 <= e <= 6.27: e = 6.5 - e if e < 3.25 else 12.54 - e
        m2 = m2 + (rng.uniform(300, 1500) if rng.random() > 0.25 else -rng.uniform(200, 800))
        m1 = round((p['EF'] - e + p['B2'] * (m2 - m2h)) / p['B1']); m2 = round(m2)
        t0 = time.time()
        o.raw(m1, m2)
        st = o.status()
        if st.get('fault') or not st.get('homed'): print('FAULT', st.get('fault')); break
        for k, t in enumerate((m1, m2)):
            if t != last[k]: dirs[k] = 1 if t > last[k] else -1
        last = [m1, m2]
        b, near, photo, cs = see(p, m1, m2, m2h, tol=0.15)
        rec = dict(i=i, m1=m1, m2=m2, m2h=m2h, d1=dirs[0], d2=dirs[1], e_plan=round(e, 3), near=near, photo=photo,
                   best=b, cands=cs, heard=o.heard(t0).get('bangs'), t=time.strftime('%H:%M:%S'))
        open(LOG, 'a').write(json.dumps(rec) + '\n')
        print(i, m1, m2, 'near' if near else 'FAR', b and (b['px'], b['score']), rec['heard'], flush=True)
    print('DONE')

def load_rows(since=None):
    rows = []
    for l in open(LOG):
        d = json.loads(l)
        if d.get('cands') and (since is None or d['t'] >= since): rows.append(d)
    return rows

def cmd_fit(write=False, since=None, camera_only=False):
    from scipy.optimize import least_squares
    rows = load_rows(since)
    m1 = np.array([r['m1'] for r in rows], float); m2 = np.array([r['m2'] for r in rows], float)
    m2h = np.array([r['m2h'] for r in rows], float)
    d1 = np.array([r['d1'] for r in rows], float); d2 = np.array([r['d2'] for r in rows], float)
    p0 = load_params()
    names = [] if camera_only else ['EF', 'lam1', 'lam2']          # camera_only: the table was moved, the arm constants are fine
    scale = np.concatenate([[1, 1, 100, 1, 1, 100, 1e-3, 1e-3], [.05, 20, 20][:len(names)]])
    def unpack(v):
        p = dict(p0); H = np.append(v[:8], 1.0).reshape(3, 3); p['H'] = H.tolist()
        p.update(zip(names, v[8:])); return p
    def choose(p):
        x, y, _, _ = model(p, m1, m2, m2h, d1, d2); u, w = plane_to_px(p, x, y)
        out = []
        for i, r in enumerate(rows):
            cs = [c for c in r['cands'] if c['score'] > 0.3] or r['cands']
            c = min(cs, key=lambda c: (c['px'][0] - u[i]) ** 2 + (c['px'][1] - w[i]) ** 2)
            out.append(c['px'])
        return np.array(out, float)
    v = np.concatenate([np.asarray(p0['H']).ravel()[:8], [p0[k] for k in names]])
    keep = np.ones(len(rows), bool)
    for it in range(5):
        obs = choose(unpack(v))
        def res(uu):
            p = unpack(uu * scale); x, y, _, _ = model(p, m1[keep], m2[keep], m2h[keep], d1[keep], d2[keep])
            u, w = plane_to_px(p, x, y)
            return np.concatenate([u - obs[keep, 0], w - obs[keep, 1]])
        sol = least_squares(res, v / scale, loss='soft_l1', f_scale=2.0)
        v = sol.x * scale
        p = unpack(v); x, y, rm, phim = model(p, m1, m2, m2h, d1, d2); u, w = plane_to_px(p, x, y)
        err = np.hypot(u - obs[:, 0], w - obs[:, 1])
        keep = err < max(6.0, 3 * np.median(err))
    ox, oy = px_to_plane(p, obs[:, 0], obs[:, 1])
    perr = np.hypot(ox - x, oy - y)                       # error in sand radii
    dr = np.hypot(ox, oy) - np.abs(rm)
    stats = dict(n=len(rows), used=int(keep.sum()), rms_px=float(np.sqrt((err[keep] ** 2).mean())), max_px=float(err[keep].max()),
                 rms_mm=float(np.sqrt((perr[keep] ** 2).mean()) * 117 / 0.93), max_mm=float(perr[keep].max() * 117 / 0.93),
                 rms_radial_mm=float(np.sqrt((dr[keep] ** 2).mean()) * 117 / 0.93),
                 m1_centre=float((p['EF'] - 2 * math.pi) / p['B1']), steps_per_elbow_turn=float(2 * math.pi / p['B1']))
    print(json.dumps({k: (round(float(x), 7) if not isinstance(x, list) else '...') for k, x in p.items()}))
    print(json.dumps({k: round(x, 3) if isinstance(x, float) else x for k, x in stats.items()}))
    print('firmware:', json.dumps({k: float('%.7g' % x) for k, x in fw_consts(p).items()}))
    if write:
        old = {}
        try: old = json.load(open(CAL))
        except Exception: pass
        j = dict(model='v6h', date=time.strftime('%Y-%m-%d %H:%M'), params=p, stats=stats, firmware=fw_consts(p),
                 note='plane units: arm full reach 2L = 0.92; bowl wall is at about 0.93. 1 unit is about 126 mm.',
                 previous_v6=old.get('params') if old.get('model') == 'v6' else old.get('previous_v6'))
        json.dump(j, open(CAL, 'w'), indent=1)
        if camera_only: return p
        q = '&'.join('%s=%.8g' % kv for kv in fw_consts(p).items())
        print(o.get('/cal?' + q + '&save=1'))
        st = o.status()
        print('backlash now %.1f, %.1f -> suggested %.1f, %.1f (not applied)' % (st['bl1'], st['bl2'], max(0, st['bl1'] - p['lam1']), max(0, st['bl2'] - p['lam2'])))
    return p

def cmd_check(n=10, record=None):
    import csv
    p = load_params(); st = o.status(); rmax = st['cal']['rmax']; m2h = st['m2h']
    if st['state'] != 'idle' or not st['homed'] or st.get('fault'):
        raise RuntimeError('The table must be idle, homed and clear of faults before checking placement.')
    if n < 1:
        raise ValueError('Select at least one stop.')
    if record is not None:
        observations = csv.writer(record)
        observations.writerow(['theta_rad', 'rho', 'x_px', 'y_px', 'photo'])
        record.flush()
    rng = random.Random(7); errs = []
    tg = [(0.0, 0.0), (1.0, 0.05), (2.5, 0.1), (4.0, 0.2), (5.5, 1.0), (0.8, 0.97)] + [(rng.uniform(0, 6.28), rng.uniform(0.25, 1.0)) for _ in range(max(0, n - 6))]
    for th, rho in tg[:n]:
        command = ('%.4f' % th, '%.4f' % rho)
        o.get('/goto?th=%s&rho=%s' % command, retries=1)
        s = o.wait_idle()
        if not s['homed'] or s.get('fault'):
            raise RuntimeError('The table lost its position during the placement check.')
        photo = None
        try:
            b, near, photo, cs = see(p, s['cur1'], s['cur2'], m2h, tol=0.15)
        finally:
            if record is not None:
                # A separate reading supplies x_px and y_px. A failed
                # photograph still counts as an attempted observation.
                observations.writerow([*command, '', '', photo])
                record.flush()
        if not b: print(th, rho, 'no ball'); continue
        tx, ty = rho * rmax * math.cos(th), rho * rmax * math.sin(th)
        err = math.hypot(b['x'] - tx, b['y'] - ty); errs.append(err)
        print('th %.2f rho %.2f -> r %.3f (want %.3f) err %.1f mm  score %.2f%s' % (th, rho, math.hypot(b['x'], b['y']), rho * rmax, err * 126, b['score'], '' if near else '  (far from model)'), flush=True)
    if errs: print('median %.1f mm, worst %.1f mm' % (np.median(errs) * 126, max(errs) * 126))

if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'collect': cmd_collect(int(a[1]) if len(a) > 1 else 70)
    elif a[0] == 'fit': cmd_fit('--write' in a, next((x.split('=')[1] for x in a if x.startswith('--since=')), None), '--camera' in a)
    elif a[0] == 'check':
        import argparse
        cli = argparse.ArgumentParser(description='Move to polar targets and photograph the settled ball.')
        cli.add_argument('n', type=int, nargs='?', default=10)
        cli.add_argument('--record', help='Create a new CSV of command/photo pairs for measure_ball_placement.py.')
        args = cli.parse_args(a[1:])
        if args.record:
            with open(args.record, 'x', newline='') as record:
                cmd_check(args.n, record)
        else:
            cmd_check(args.n)
