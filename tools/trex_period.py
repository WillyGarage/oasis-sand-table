#!/usr/bin/env python3
"""Rib period per section of the decoded maker picture: dominant spatial frequency (FFT) of brightness profiles taken along the
gradient direction (across the ribs) at random points inside each section. Reads v4/trex/section_masks.npz, section_fields.npz.
Prints/saves median period, IQR and the fraction of profiles with a clear peak."""
import numpy as np, json, os, sys, math
from scipy.ndimage import map_coordinates, gaussian_filter
from scipy import ndimage as ndi
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = ROOT + '/captures/relief-study/v4/trex/'
PX = 0.2

def measure(g_bp, mask, ori, n=500, half=8.0, seed=1, pmin=0.8, pmax=9.0):
    rng = np.random.RandomState(seed)
    er = ndi.binary_erosion(mask, iterations=max(1, int(2.0 / PX)))
    if er.sum() < 100: er = mask
    ys, xs = np.nonzero(er)
    if len(ys) == 0: return None
    sel = rng.choice(len(ys), min(n, len(ys)), replace=False)
    st = 0.05
    t = np.arange(-half, half + 1e-9, st) / PX
    per = []; tried = 0; ACN = int(pmax / st); acc = np.zeros(ACN); cnt = np.zeros(ACN)
    mf = mask.astype(np.float32)
    for k in sel:
        y, x = ys[k], xs[k]
        o = math.radians(ori[y, x] + 90)
        dx, dy = math.cos(o), -math.sin(o)
        px_, py_ = x + t * dx, y + t * dy
        if px_.min() < 0 or px_.max() > 1249 or py_.min() < 0 or py_.max() > 1249: continue
        ins = map_coordinates(mf, [py_, px_], order=0) > 0.5
        c = len(t) // 2; a = b = c
        while a > 0 and ins[a - 1]: a -= 1
        while b < len(t) - 1 and ins[b + 1]: b += 1
        v = map_coordinates(g_bp, [py_, px_], order=1)[a:b + 1]
        if len(v) * st < 5.0: continue
        tried += 1
        v = gaussian_filter(v - np.polyval(np.polyfit(np.arange(len(v)), v, 1), np.arange(len(v))), 0.12 / st)
        n_ = len(v); nl = int(min(n_ * 0.7, pmax / st))
        ac = np.array([np.dot(v[:n_ - L], v[L:]) / (n_ - L) for L in range(nl)]) / (np.dot(v, v) / n_ + 1e-12)
        if nl > ACN: ac = ac[:ACN]
        acc[:len(ac)] += ac; cnt[:len(ac)] += 1
        per.append(0)
    if len(per) < 5: return dict(period=float('nan'), iqr=float('nan'), n=len(per), tried=tried)
    ac = acc / np.maximum(cnt, 1); ac = gaussian_filter(ac, 2)
    pks = [(L * st, float(ac[L])) for L in range(int(pmin / st), ACN - 2) if ac[L] > ac[L - 1] and ac[L] >= ac[L + 1] and ac[L] > 0.02]
    z = np.nonzero(ac < 0)[0]
    first = next(((l, a) for l, a in pks if len(z) and l > z[0] * st), (float('nan'), 0))
    return dict(period=float(first[0]), ac=float(first[1]), peaks=[(round(l, 2), round(a, 2)) for l, a in pks[:4]], n=len(per), tried=tried)
    p = np.array(per)
    # mode via log-histogram (robust to harmonics)
    lp = np.log(p); h, e = np.histogram(lp, bins=30); m = np.argmax(h)
    mode = float(np.exp(0.5 * (e[m] + e[m + 1])))
    near = p[(p > mode * 0.8) & (p < mode * 1.25)]
    return dict(period=float(np.median(near)), iqr=float(np.subtract(*np.percentile(near, [75, 25]))), n=len(per), tried=tried, median_all=float(np.median(p)))

if __name__ == '__main__':
    import cv2
    F = np.load(OUT + 'fields.npz'); g = F['gray'].astype(np.float32)
    g_bp = gaussian_filter(g, 0.15 / PX) - gaussian_filter(g, 3.0 / PX)
    M = np.load(OUT + 'section_masks.npz'); O = np.load(OUT + 'section_fields.npz')
    res = {}
    only = sys.argv[1:]
    for n in M.files:
        if only and n not in only: continue
        r = measure(g_bp, M[n], O[n].astype(np.float32))
        res[n] = r
        print('%-10s %s' % (n, r))
    if not only: json.dump(res, open(OUT + 'periods.json', 'w'), indent=1)
