#!/usr/bin/env python3
"""Enlarge a portrait .thr about a point near the top of the head and clip it at the rim.
  scale_thr.py IN.thr OUT.thr [K=1.25]   (the 25% bigger Lek drawn at 12:30pm on 2026-11-20 used K=1.25)
y' = 0.97 + K*(y - 0.9), x' = K*x; points beyond the rim are pulled back onto it; theta stays cumulative."""
import math, sys
def scale(pts, K=1.25):
    out = []; prev = None
    for t, r in pts:
        x, y = r * math.cos(t) * K, 0.97 + K * (r * math.sin(t) - 0.9)
        rr = min(math.hypot(x, y), 1.0); a = math.atan2(y, x)
        th = a if prev is None else prev[0] + ((a - prev[1] + math.pi) % (2 * math.pi) - math.pi)
        prev = (th, a); out.append((th, rr))
    return out
if __name__ == '__main__':
    pts = [tuple(map(float, l.split())) for l in open(sys.argv[1]) if l.strip() and l[0] != '#']
    out = scale(pts, float(sys.argv[3]) if len(sys.argv) > 3 else 1.25)
    open(sys.argv[2], 'w').write(''.join('%.5f %.5f\n' % p for p in out))
    print(len(out), 'points; start', out[0], 'end', out[-1])
