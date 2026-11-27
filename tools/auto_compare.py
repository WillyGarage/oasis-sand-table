#!/usr/bin/env python3
"""Comparison sheet: photo | hand-made gallery sim | automatic sim (names hidden as Face A/B/C), simulation renders only.
    python3 tools/auto_compare.py OUT.png name:autoSim.png [name:autoSim.png ...]"""
import sys, os, cv2, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def gal(n):
    for p in ('%s/captures/portrait-hybrid/%s_gal.png' % (ROOT, n), '%s/captures/auto-portrait/%s_gal.png' % (ROOT, n)):
        if os.path.exists(p): return cv2.imread(p)
def label(im, t):
    cv2.putText(im, t, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 220), 2, cv2.LINE_AA); return im
def crop_tray(im, S=700):
    h = im.shape[0]; return cv2.resize(im, (S, S))
rows = []
for k, arg in enumerate(sys.argv[2:]):
    n, auto = arg.split(':'); S = 700
    ph = cv2.imread('%s/captures/family-source/%s.jpg' % (ROOT, n)); h, w = ph.shape[:2]
    ph = cv2.resize(ph, (int(w * S / h), S)); ph = ph[:, max(0, (ph.shape[1] - S) // 2):][:, :S] if ph.shape[1] > S else ph
    ph = cv2.resize(ph, (S, S)) if ph.shape[1] != S else ph
    f = 'Face ' + 'ABCDEF'[k]
    rows.append(np.hstack([label(ph, f + ' photo'), label(crop_tray(gal(n)), f + ' hand-made'), label(crop_tray(cv2.imread(auto)), f + ' automatic')]))
cv2.imwrite(sys.argv[1], np.vstack(rows))
