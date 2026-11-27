#!/usr/bin/env python3
"""Lighten a sand photo or preview so it looks the way the sand does to the eye (pale, almost white), and lift the
relief a little. Bill, 2026-11-20: "the pictures are pretty dark, and much darker than they appear in real life".
  brighten.py IN.jpg [OUT.jpg]     (default: overwrite; the untouched original is kept once as IN_dark.jpg)
The black surround (pixels under 12) is left alone."""
import os, sys, cv2, numpy as np
def brighten(im, target=198, clip=1.6):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY); m = g > 12
    if m.sum() < 100: return im
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32); L = lab[..., 0]
    med = np.median(L[m]); lo = np.percentile(L[m], 1)
    # even out the slow shading across the bowl (dark middle, bright rim), then set the sand's middle tone
    Lf = L.copy(); Lf[~m] = med
    bg = cv2.GaussianBlur(Lf, (0, 0), im.shape[0] / 9.0)
    L2 = (L - bg) * 1.6 + (0.35 * (bg - med) + target)
    L2 = np.clip(L2, 0, 255).astype(np.uint8)
    L2 = cv2.createCLAHE(clipLimit=clip, tileGridSize=(6, 6)).apply(L2)
    lab[..., 0] = L2; lab[..., 1:] = 128 + (lab[..., 1:] - 128) * 0.8
    out = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    out[~m] = im[~m]
    return out
if __name__ == '__main__':
    src = sys.argv[1]; dst = sys.argv[2] if len(sys.argv) > 2 else src
    if dst == src:
        keep = src.replace('.jpg', '_dark.jpg')
        if not os.path.exists(keep): cv2.imwrite(keep, cv2.imread(src), [cv2.IMWRITE_JPEG_QUALITY, 95])
        src = keep
    cv2.imwrite(dst, brighten(cv2.imread(src)), [cv2.IMWRITE_JPEG_QUALITY, 93])
