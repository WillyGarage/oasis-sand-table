#!/usr/bin/env python3
"""Generative pieces: the same formulas the firmware's /auto mode uses (keep the two in step).

Every piece is an inward spiral from the rim to the centre whose outline is modulated: u runs 0 -> 1,
theta = 2*pi*T*u, s = 1 - u, rho = s * shape(theta, u). It is drawn after an outward erase (centre -> rim), so pieces
chain forever: erase out, piece in, erase out, piece in.

  gen.py bloom  --n 6 --d 0.45 --g 0.6 --T 20 [--w 0]   star / petals; w = total twist in radians (pinwheel)
  gen.py vortex --n 6 --T 18 --w 2.1                    polygon turning as it shrinks
  gen.py arms   --n 5 --d 0.5 --g 1.0 --T 20 --w 1.5    galaxy arms: like bloom, but the twist grows toward the centre
  gen.py weave  --n 9 --q 2 --e 0.10 --T 22             wavy spiral whose waves shift each turn (woven look)
  gen.py random [--seed N]                              pick a kind and parameters the way the firmware does
  ... -o out.thr [--ppt 360]"""
import argparse, math, random, sys

def shape(kind, P, th, u):
    if kind == 'bloom':
        c = abs(math.cos(P['n'] * (th + P['w'] * u) / 2.0))
        return 1.0 - P['d'] * (1.0 - c ** P['g'])
    if kind == 'vortex':
        seg = 2 * math.pi / P['n']
        ph = (th + P['w'] * u) % seg
        return math.cos(math.pi / P['n']) / math.cos(ph - math.pi / P['n'])
    if kind == 'arms':                                  # galaxy: n curved arms that wind tighter toward the centre
        c = abs(math.cos(P['n'] * (th + P['w'] * math.log(1.0 / (1.0 - u + 0.04))) / 2.0))
        return 1.0 - P['d'] * (1.0 - c ** P['g'])
    if kind == 'super':                                 # rounded squares and soft stars (superellipse), turning as they shrink
        ph = P['n'] * (th + P['w'] * u) / 4.0; g = P['g']
        r = (abs(math.cos(ph)) ** g + abs(math.sin(ph)) ** g) ** (-1.0 / g)
        return r / max(1.0, 2 ** (0.5 - 1.0 / g))
    if kind == 'ripple':                                # petals whose depth swells and fades in q rings
        return 1.0 - P['d'] * (0.5 + 0.5 * math.cos(P['n'] * th)) * (0.5 - 0.5 * math.cos(2 * math.pi * P['q'] * u))
    if kind == 'lotus':                                 # q rings of petals, two more petals in each ring going outward
        B = P['q']; x = (1 - u) * B; b = min(int(x), B - 1); f = x - b
        nb = P['n'] + 2 * b
        c = abs(math.cos(nb * th / 2.0))
        return 1.0 - P['d'] * math.sqrt(max(0.0, math.sin(math.pi * f))) * (1.0 - c ** P['g'])
    if kind == 'weave':
        m = P['n'] + 1.0 / P['q']
        return (1.0 + P['e'] * math.sin(m * th)) / (1.0 + P['e'])
    raise ValueError(kind)

def points(kind, P, ppt=360):
    N = int(P['T'] * ppt)
    out = []
    for k in range(N + 1):
        u = k / N; th = 2 * math.pi * P['T'] * u
        out.append((th, max(0.0, min(1.0, (1 - u) * shape(kind, P, th, u)))))
    return out

def pick(rng):
    """random piece, same ranges as the firmware's pickRandom()"""
    fam = rng.choice([0, 0, 1, 2, 3, 4, 5, 6])
    if fam == 0:
        return 'bloom', dict(n=rng.randint(3, 9), d=rng.uniform(0.25, 0.55), g=rng.choice([0.5, 0.7, 1.0, 1.6, 2.5]),
                             T=rng.randint(16, 22), w=rng.choice([0, 0, 0.8, 1.6, -1.2, 3.1]))
    if fam == 1: return 'vortex', dict(n=rng.randint(3, 7), T=rng.randint(15, 20), w=rng.uniform(1.2, 4.0) * rng.choice([1, -1]))
    if fam == 2: return 'weave', dict(n=rng.randint(5, 13), q=rng.choice([2, 2, 3, -3, 4]), e=rng.uniform(0.06, 0.13), T=rng.randint(18, 24))
    if fam == 3: return 'arms', dict(n=rng.randint(4, 8), d=rng.uniform(0.35, 0.55), g=rng.choice([1.0, 1.6, 2.0]), T=rng.randint(18, 22),
                                     w=rng.uniform(0.8, 1.8) * rng.choice([1, -1]))
    if fam == 4: return 'super', dict(n=rng.choice([4, 6, 8]), g=rng.choice([1.2, 1.5, 3.0, 4.0]), T=rng.randint(18, 22),
                                      w=rng.uniform(0.8, 2.5) * rng.choice([1, -1]))
    if fam == 5: return 'ripple', dict(n=rng.randint(6, 12), d=rng.uniform(0.35, 0.55), q=rng.randint(2, 4), T=rng.randint(20, 24))
    return 'lotus', dict(n=rng.randint(5, 8), d=rng.uniform(0.35, 0.5), g=rng.choice([0.6, 1.0, 2.0]), q=rng.randint(3, 5), T=rng.randint(21, 25))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('kind'); ap.add_argument('-o', required=True); ap.add_argument('--ppt', type=int, default=360)
    ap.add_argument('--seed', type=int, default=None)
    for k, d in dict(n=6, d=0.45, g=0.6, T=20, w=0.0, q=2, e=0.10).items(): ap.add_argument('--' + k, type=float, default=d)
    a = ap.parse_args()
    if a.kind == 'random':
        kind, P = pick(random.Random(a.seed))
    else:
        kind, P = a.kind, dict(n=int(a.n), d=a.d, g=a.g, T=a.T, w=a.w, q=int(a.q), e=a.e)
    pts = points(kind, P, a.ppt)
    open(a.o, 'w').write('# gen %s %s\n' % (kind, P) + ''.join('%.5f %.5f\n' % p for p in pts))
    print(kind, P, len(pts), 'points')
