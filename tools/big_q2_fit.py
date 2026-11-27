#!/usr/bin/env python3
"""Fit the 36-inch table's camera geometry from big_q2_circles.py's log (captures/big-qual/big_q2_circles.jsonl).
Model: the ball sits at rho * (cos th, sin th) on the tray plane, rho = R - c*A + rho0 (radius-motor steps; R, A are the
firmware's raw counters, c the arm-to-radius coupling, rho0 the offset of the firmware's carriage zero from the arm's
rotation centre), th = 2 pi A / 38400; the camera sees it through a homography H. Fits H, c and rho0 together.
Writes firmware-notes/big-camera-calibration.json (H maps table steps -> pixels). Usage: big_q2_fit.py [log]"""
import json, os, sys
import numpy as np, cv2
from scipy.optimize import least_squares

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [x for x in sys.argv[1:] if not x.startswith('--')]
f = args[0] if args else ROOT + '/captures/big-qual/big_q2_circles.jsonl'
rows = [json.loads(l) for l in open(f)]
pts = [r for r in rows if r['what'] in ('circle', 'line', 'circle_back', 'end')]
R = np.array([p['r'] for p in pts], float); A = np.array([p['a'] for p in pts], float)
XY = np.array([p['ball'][:2] for p in pts], float)
kind = np.array([p['what'] for p in pts]); tag = np.array([p['tag'] for p in pts])
use = np.isin(kind, ['circle'])            # fit on the forward circle points only (same backlash state)


def table(c, rho0, R=R, A=A):
    rho = R - c * A + rho0; th = 2 * np.pi * A / 38400.0
    return np.stack([rho * np.cos(th), rho * np.sin(th)], 1) / 30000.0     # scaled so H is well conditioned


def proj(h, t):
    H = np.append(h, 1.0).reshape(3, 3)
    q = np.c_[t, np.ones(len(t))] @ H.T
    return q[:, :2] / q[:, 2:]


def res(p, m=use):
    return (proj(p[:8], table(p[8], p[9])[m]) - XY[m]).ravel()


H0, _ = cv2.findHomography(table(1 / 6, 0)[use], XY[use])
p0 = np.r_[(H0 / H0[2, 2]).ravel()[:8], 1 / 6, 0]
best = None
for fix_c in (True, False):
    if fix_c:
        g = lambda q: res(np.r_[q[:8], 1 / 6, q[8]])
        s = least_squares(g, np.r_[p0[:8], 0], x_scale='jac'); p = np.r_[s.x[:8], 1 / 6, s.x[8]]
    else:
        s = least_squares(res, p, x_scale='jac'); p = s.x
    e = res(p).reshape(-1, 2); rms = np.sqrt((e ** 2).sum(1).mean())
    J = s.jac; cov = np.linalg.inv(J.T @ J) * (s.fun ** 2).sum() / max(1, len(s.fun) - len(s.x))
    sd = np.sqrt(np.diag(cov))
    print('coupling %s: c = %.5f (1/%.3f)%s  rho0 = %.0f steps (sd %.0f)  rms %.2f px  worst %.2f px' % (
        'fixed 1/6' if fix_c else 'free', p[8], 1 / p[8], '' if fix_c else ' sd %.5f' % sd[8], p[9], sd[-1], rms, np.abs(e).max()))
H = np.append(p[:8], 1.0).reshape(3, 3) @ np.diag([1 / 30000.0, 1 / 30000.0, 1])     # table steps -> pixels
Hi = np.linalg.inv(H)


def to_table(xy):
    return cv2.perspectiveTransform(np.asarray(xy, np.float64).reshape(-1, 1, 2), Hi).reshape(-1, 2)


T = to_table(XY); rho_cam = np.hypot(T[:, 0], T[:, 1]); rho_cmd = R - p[8] * A + p[9]
print('\nper circle (camera radius in steps, minus commanded):')
for c in sorted(set(tag[use])):
    m = use & (tag == c); d = rho_cam[m] - rho_cmd[m]
    print('  carriage %5d: mean %+6.0f  spread (sd) %4.0f  min %+5.0f max %+5.0f steps' % (c, d.mean(), d.std(), d.min(), d.max()))
m = kind == 'line'
if m.any():
    print('\nradial line (carriage, inward pass error, outward pass error; steps, along the radius):')
    cs = tag[m]; d = (rho_cam - rho_cmd)[m]; n = len(cs) // 2
    for i in range(n):
        j = 2 * n - 1 - i
        print('  %5d  %+6.0f  %+6.0f' % (cs[i], d[i], d[j]))
    # steps per pixel-independent check: slope of camera radius against commanded
    k = np.polyfit(rho_cmd[m], rho_cam[m], 1)
    print('  camera radius = %.4f x commanded %+.0f steps' % (k[0], k[1]))
m = kind == 'circle_back'
if m.any():
    print('\nafter unwinding one turn backward (camera minus the same spot before): px', np.round(XY[m] - np.array([XY[(kind == 'circle') & (tag == c)][0] for c in tag[m]]), 1).tolist())
out = {'H_table_steps_to_image': H.tolist(), 'coupling': p[8], 'rho0_steps': p[9],
       'note': 'table point = rho*(cos th, sin th) in radius-motor steps, rho = r - coupling*a + rho0, th = 2*pi*a/38400, with r, a the '
               'firmware counters after /homearm and /homeradius; fitted %d points on three circles, rms %.2f px' % (use.sum(), rms)}
if '--save' in sys.argv:
    json.dump(out, open(ROOT + '/firmware-notes/big-camera-calibration.json', 'w'), indent=1)
    print('saved')
