#!/usr/bin/env python3
"""Over-segment the rectified maker photo into basins between lip lines (watershed on a ridge map). Helper for trex_decode.py."""
import numpy as np, cv2, os
from skimage.feature import hessian_matrix, hessian_matrix_eigvals
from skimage.morphology import h_minima
from skimage.segmentation import watershed
from scipy import ndimage as ndi
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PX = 0.2; C = 625

def ridge(g, sig_mm=1.6):
    s = sig_mm / PX
    H = hessian_matrix(g, sigma=s, order='rc', use_gaussian_derivatives=True)
    ev = hessian_matrix_eigvals(H)
    r = np.clip(-ev[1], 0, None) * s * s
    return r / np.percentile(r, 99.5)

def basins(h=0.06, sig_mm=1.6, rmax_mm=117.0):
    F = np.load(ROOT + '/captures/relief-study/v4/trex/fields.npz'); g = F['gray']
    r = np.clip(ridge(g, sig_mm), 0, 1.5)
    yy, xx = np.mgrid[0:g.shape[0], 0:g.shape[1]]
    X = (xx + 0.5 - C) * PX; Y = -(yy + 0.5 - C) * PX
    disc = np.hypot(X, Y) <= rmax_mm
    mk = h_minima(r, h) & disc
    lab, n = ndi.label(mk)
    ws = watershed(r, lab, mask=disc)
    return ws, r, disc, n

if __name__ == '__main__':
    ws, r, disc, n = basins()
    print(n)
    np.savez_compressed(ROOT + '/captures/relief-study/v4/trex/basins.npz', ws=ws.astype(np.int32), r=r.astype(np.float32))
