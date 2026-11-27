#!/usr/bin/env python3
"""Rake sand across the bowl: parallel straight strokes that advance in one direction, like a plough, so the ridge
each stroke throws up is pushed further by the next one.

  level.py --toward DEG [--pitch 0.035] [--reach 0.98] -o out.thr

--toward: direction the sand should be moved, degrees, theta convention (0 = right as the camera sees it, 180 = left).
Strokes are chords at right angles to that direction, starting on the far side and advancing toward it. rho is in
drawing units (1 = edge of the drawing area)."""
import argparse, math, sys
ap = argparse.ArgumentParser()
ap.add_argument('--toward', type=float, default=180); ap.add_argument('--pitch', type=float, default=0.035)
ap.add_argument('--reach', type=float, default=0.98); ap.add_argument('-o', required=True)
a = ap.parse_args()
al = math.radians(a.toward); R = a.reach
n = int(2 * R / a.pitch)
pts = []; up = True
for i in range(n + 1):
    s = -R + 0.5 * a.pitch + i * a.pitch              # position along the push direction, from far side to near side
    if abs(s) < 0.012: s = 0.012 if s >= 0 else -0.012    # never straight through the exact centre (theta undefined)
    if abs(s) >= R: continue
    h = math.sqrt(R * R - s * s)
    m = max(2, int(2 * h / 0.01))
    ts = [(-h + 2 * h * k / m) for k in range(m + 1)]
    if not up: ts = ts[::-1]
    for t in ts:                                      # (s along push, t across) -> x, y
        x = s * math.cos(al) - t * math.sin(al); y = s * math.sin(al) + t * math.cos(al)
        pts.append((x, y))
    up = not up
out = []; th_prev = None
for x, y in pts:
    r = math.hypot(x, y); th = math.atan2(y, x)
    if th_prev is not None:
        while th - th_prev > math.pi: th -= 2 * math.pi
        while th - th_prev < -math.pi: th += 2 * math.pi
    th_prev = th; out.append((th, min(1.0, r)))
open(a.o, 'w').write('# rake sand toward %g deg, pitch %g\n' % (a.toward, a.pitch) + ''.join('%.5f %.5f\n' % p for p in out))
print(len(out), 'points', n + 1, 'strokes')
