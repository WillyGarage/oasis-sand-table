#!/usr/bin/env python3
"""Rib period per section from the scale at which the band-pass (DoG) energy peaks inside the section (eroded 2 mm), calibrated against
ribs counted by eye on 24 mm crops. Reads v4/trex/section_masks.npz. Writes periods.json (mm).
Calibration (counted by eye): snout ~1.1, chest ~1.2, belly_r ~2.4, throat ~5 (separate grooves)."""
import numpy as np, json, os, sys
from scipy.ndimage import gaussian_filter
from scipy import ndimage as ndi
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = ROOT + '/captures/relief-study/v4/trex/'
PX = 0.2
SIG = np.array([0.2, 0.28, 0.4, 0.56, 0.8, 1.1, 1.6, 2.2, 3.2])

def curves():
    g = np.load(OUT + 'fields.npz')['gray'].astype(np.float32)
    bands = [gaussian_filter(g, s / PX) - gaussian_filter(g, 1.6 * s / PX) for s in SIG]
    M = np.load(OUT + 'section_masks.npz')
    res = {}
    for n in M.files:
        m = ndi.binary_erosion(M[n], iterations=max(1, int(2.0 / PX)))
        if m.sum() < 60: m = M[n]
        E = np.array([np.mean(b[m] ** 2) for b in bands])
        res[n] = E
    return res

if __name__ == '__main__':
    res = curves()
    out = {}
    for n, E in res.items():
        En = E * SIG ** 0.0
        i = int(np.argmax(En))
        # parabola refinement in log sigma
        if 0 < i < len(SIG) - 1:
            y0, y1, y2 = np.log(En[i - 1:i + 2] + 1e-9); d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
            s = float(np.exp(np.log(SIG[i]) + d * np.log(SIG[i + 1] / SIG[i])))
        else: s = float(SIG[i])
        out[n] = dict(sigma=s)
        print('%-10s sigma_peak %.2f  curve %s' % (n, s, ' '.join('%.0f' % (100 * e / E.max()) for e in E)))
    json.dump(out, open(OUT + 'periods_dog.json', 'w'), indent=1)
