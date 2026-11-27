#!/usr/bin/env python3
"""Map LED index -> screen angle. For each index: /led?mode=idx&i=N, photo, difference against an all-off photo,
brightest blob centroid -> angle about the sand ellipse centre (CCW on screen from +x, like the locator).
Restores solid warm white at the end. Output: captures/ledmap.json"""
import sys, json, time
sys.path.insert(0, "/home/bill/dev/WillyGarage/oasis/tools")
from oasislib import *
ell = ref_ellipse()
def frame():
    time.sleep(1.2); return cv2.GaussianBlur(cv2.cvtColor(cv2.imread(D + "/" + snap()), cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 3)
get("/led?mode=off"); base = frame()
out = {}
for i in range(43):
    get("/led?mode=idx&i=%d&c=FFFFFF&b=255" % i)
    d = frame() - base
    # restrict to a band around the rim: 0.8 .. 1.25 of the ellipse
    H, W = d.shape
    m = locate.ellipse_mask(d.shape[:2] + (3,), ell, 1.25) & ~locate.ellipse_mask(d.shape[:2] + (3,), ell, 0.75) if False else None
    yy, xx = np.mgrid[0:H, 0:W]
    rho = np.array([0.0])
    phi = np.deg2rad(ell["angle_deg"]); c, s = np.cos(phi), np.sin(phi)
    u = ((xx - ell["cx"]) * c + (yy - ell["cy"]) * s) / ell["a"]; v = (-(xx - ell["cx"]) * s + (yy - ell["cy"]) * c) / ell["b"]
    rr = np.hypot(u, v); band = (rr > 0.85) & (rr < 1.3)
    w = np.where(band, np.clip(d - 8, 0, None), 0)
    if w.sum() < 1000: out[i] = None; print(i, "no glow", flush=True); continue
    y0, x0 = np.unravel_index(np.argmax(cv2.GaussianBlur(w, (0, 0), 6)), w.shape)
    sel = (np.hypot(xx - x0, yy - y0) < 60) & band
    cx = (w * sel * xx).sum() / (w * sel).sum(); cy = (w * sel * yy).sum() / (w * sel).sum()
    rho_, th = locate.to_polar((cx, cy), ell)
    out[i] = dict(px=[round(float(cx), 1), round(float(cy), 1)], theta_deg=round(th, 1), rho=round(rho_, 2), strength=float(w[sel].sum()))
    print(i, out[i]["theta_deg"], out[i]["rho"], int(out[i]["strength"]), flush=True)
get("/led?mode=solid&c=fff4e0&b=150")
json.dump(out, open(D + "/captures/ledmap.json", "w"), indent=1)
