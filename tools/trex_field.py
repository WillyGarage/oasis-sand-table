#!/usr/bin/env python3
"""Rib orientation and rib period fields on the rectified maker photo (0.2 mm/px, +-125 mm).
orientation: direction (deg, mod 180, table frame, 0 = +x, CCW, y up) the ribs RUN along (= stroke direction).
period: local rib spacing in mm (rib to rib); stroke spacing = period / 2 (ribs form once per two strokes)."""
import numpy as np, cv2, os
from scipy.ndimage import gaussian_filter
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PX = 0.2; HALF = 125.0

def load():
    im = cv2.imread(ROOT + '/captures/relief-study/v4/trex/maker_topdown.png')
    return im

def fields(sig_grad_mm=0.5, sig_win_mm=2.5, lo_mm=0.35, hi_mm=3.0):
    im = load().astype(np.float32)
    g = im[..., 1] * 0.6 + im[..., 2] * 0.3 + im[..., 0] * 0.1
    bp = gaussian_filter(g, lo_mm / PX) - gaussian_filter(g, hi_mm / PX)      # band-pass: ribs, not lips/shading
    gy, gx = np.gradient(gaussian_filter(g, sig_grad_mm / PX))
    sw = sig_win_mm / PX
    Jxx = gaussian_filter(gx * gx, sw); Jyy = gaussian_filter(gy * gy, sw); Jxy = gaussian_filter(gx * gy, sw)
    # gradient direction (image coords, y down) -> convert to table frame (y up): flip sign of gy
    th_g = 0.5 * np.arctan2(2 * -Jxy, Jxx - Jyy)           # dominant gradient angle in table frame
    coh = np.sqrt((Jxx - Jyy) ** 2 + 4 * Jxy ** 2) / (Jxx + Jyy + 1e-9)
    ori = (np.degrees(th_g) + 90) % 180                    # ribs run perpendicular to gradient
    by, bx = np.gradient(bp)
    num = gaussian_filter(bx * bx + by * by, sw); den = gaussian_filter(bp * bp, sw) + 1e-9
    k = np.sqrt(num / den) / PX                             # rad per mm
    period = 2 * np.pi / np.maximum(k, 1e-3)
    energy = gaussian_filter(bp * bp, sw)
    return dict(ori=ori, coh=coh, period=period, energy=energy, gray=g)

if __name__ == '__main__':
    F = fields()
    np.savez_compressed(ROOT + '/captures/relief-study/v4/trex/fields.npz', **{k: v.astype(np.float32) for k, v in F.items()})
    p = F['period']; print(np.percentile(p, [5, 25, 50, 75, 95]))
