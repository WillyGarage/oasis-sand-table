#!/usr/bin/env python3
"""Engraving-style photo drawing for the Mini (Nov 23): one family of back-and-forth lines across the whole disc whose
local spacing follows the photo's tone (light = fine 0.6 mm -> smooth sand, dark = coarse up to S_MAX -> shadowed
grooves). Real-sand basis (DRAWING-LESSONS.md rounds 6-7): spacing ramps read as smooth gradients; tone in sand is
texture contrast, not average grey.

Lines are level sets of phi(x, y) = integral of 1/spacing along y (per column), so each line is y_k(x) and the spacing
between neighbours equals the local target spacing. Lines alternate direction and join along the rim.

    python3 tools/engrave.py captures/engrave/lek captures/relief-study/faces/lek.pkl [--smax 5] [--gamma 1.0] [--angle 0]
    (image input: any image file, or a faces .pkl whose 'gray' is an aligned square face crop)
"""
import argparse, math, os, pickle, sys
import numpy as np
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_path as rp

R = 114.0


def load_gray(src):
    if src.endswith('.pkl'):
        g = pickle.load(open(src, 'rb'))['gray']
    else:
        g = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
        h, w = g.shape; s = min(h, w)
        g = g[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    return np.asarray(g, np.float32)


def tone_map(g, n, clahe=2.0, blur_mm=1.5, px=0.25):
    g = cv2.resize(g, (n, n), interpolation=cv2.INTER_AREA)
    g8 = np.clip(g, 0, 255).astype(np.uint8)
    if clahe > 0:
        g8 = cv2.createCLAHE(clipLimit=clahe, tileGridSize=(6, 6)).apply(g8)
    t = cv2.GaussianBlur(g8.astype(np.float32) / 255.0, (0, 0), blur_mm / px)
    return t


def lines_from_tone(t, px, smin, smax, gamma, rad):
    n = t.shape[0]
    sp = smin + (smax - smin) * np.clip(1.0 - t, 0, 1) ** gamma          # mm
    phi = np.cumsum(px / sp, axis=0)                                     # rows go downwards (y decreasing)
    phi = phi - phi[0:1, :]
    xs = (np.arange(n) + 0.5) * px - n * px / 2
    ys = n * px / 2 - (np.arange(n) + 0.5) * px
    lines = []
    for k in range(1, int(phi.max())):
        pts = []
        for j in range(n):
            col = phi[:, j]
            i = np.searchsorted(col, k)
            if i <= 0 or i >= n:
                continue
            f = (k - col[i - 1]) / max(col[i] - col[i - 1], 1e-9)
            y = ys[i - 1] + (ys[i] - ys[i - 1]) * f
            x = xs[j]
            if x * x + y * y <= rad * rad:
                pts.append((x, y))
        if len(pts) > 4:
            P = np.array(pts)
            # keep the longest run of consecutive columns (one chord)
            gaps = np.where(np.diff(P[:, 0]) > 2 * px)[0]
            if len(gaps):
                segs = np.split(P, gaps + 1); P = max(segs, key=len)
            lines.append(P[::2])
    return lines


def rot(P, ang):
    a = math.radians(ang); c, s = math.cos(a), math.sin(a)
    return np.c_[P[:, 0] * c - P[:, 1] * s, P[:, 0] * s + P[:, 1] * c]


def build(src, smin=0.6, smax=5.0, gamma=1.0, angle=0.0, rad=108.0, px=0.25):
    n = int(round(2 * rad / px))
    t = tone_map(load_gray(src), n, px=px)
    lines = lines_from_tone(t, px, smin, smax, gamma, rad)
    path = [np.array([[0.0, 0.0]])]
    for k, L in enumerate(lines):
        L = L if k % 2 == 0 else L[::-1]
        path.append(L)
    P = np.vstack(path)
    P[1:] = rot(P[1:], angle)
    end = P[-1]; a = math.atan2(end[1], end[0])
    P = np.vstack([P, [[0.97 * R * math.cos(a), 0.97 * R * math.sin(a)]]])
    return P, t, len(lines)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('src')
    ap.add_argument('--smin', type=float, default=0.6); ap.add_argument('--smax', type=float, default=5.0)
    ap.add_argument('--gamma', type=float, default=1.0); ap.add_argument('--angle', type=float, default=0.0)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    P, t, nl = build(a.src, a.smin, a.smax, a.gamma, a.angle)
    tr, near = rp.to_thr_pts(P, R)
    parts = [tr[i:i + 11500] for i in range(0, len(tr), 11500)]
    for i, part in enumerate(parts):
        rp.write_thr('%s_part%d.thr' % (a.out, i + 1), part, 'engrave %s' % os.path.basename(a.src))
    cv2.imwrite(a.out + '_tone.png', (t * 255).astype(np.uint8))
    print(nl, 'lines', len(tr), 'points', len(parts), 'files', round(rp.path_len_m(tr, R), 1), 'm',
          round(sum(rp.mini_minutes(p) for p in parts), 1), 'min; near centre', near)
