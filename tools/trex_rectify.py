#!/usr/bin/env python3
"""Rectify the maker's dinosaur photo to a top-down view in table mm. Reads the photo only.
Fits an ellipse to the bright sand-edge boundary, maps it to a circle of radius R_EDGE (affine; the photo looks telephoto,
perspective not modelled). Output: v4/trex/maker_topdown.png (0.2 mm/px, +-125 mm, +x right, +y up = up in the photo)
and maker_topdown_grid.png; also exposes to_mm_map() for other tools."""
import os, cv2, numpy as np, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = ROOT + '/captures/relief-study/reference/maker-dinosaur-mini.webp'
OUT = ROOT + '/captures/relief-study/v4/trex/'
R_EDGE = 118.0     # mm, radius assumed for the fitted bright sand-edge ellipse (Mini tray r_tray = 114 + 4)
PX = 0.2; HALF = 125.0

def fit():
    im = cv2.imread(SRC)
    g = cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (0, 0), 6)
    m = (g > 150).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    m = (lab == 1 + np.argmax(st[1:, 4])).astype(np.uint8)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return im, cv2.fitEllipse(max(cs, key=len))

def maps(e, px=PX, half=HALF, R=R_EDGE):
    (cx, cy), (w, h), ang = e
    a = np.radians(ang)
    e1 = np.array([np.cos(a), np.sin(a)]); e2 = np.array([np.cos(a + np.pi / 2), np.sin(a + np.pi / 2)])
    # e1 has semi-length w/2, e2 semi-length h/2 ; choose signs so +x = right, +y = up in the photo
    if e2[0] < 0: e2 = -e2
    if e1[1] > 0: e1 = -e1
    n = int(round(2 * half / px))
    xs = (np.arange(n) + 0.5) * px - half
    X, Y = np.meshgrid(xs, -xs)
    # unit circle coords: major axis (h) lies near x
    mx = X / R * (h / 2); my = Y / R * (w / 2)
    P = np.array([cx, cy])[:, None, None] + mx[None] * e2[:, None, None] + my[None] * e1[:, None, None]
    return P[0].astype(np.float32), P[1].astype(np.float32)

def rectify(img=None):
    im, e = fit()
    mx, my = maps(e)
    return cv2.remap(im, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT), e

def grid(img, px=PX, half=HALF):
    o = img.copy(); n = o.shape[0]; c = n / 2
    for v in range(-120, 121, 10):
        col = (0, 0, 255) if v == 0 else (255, 160, 0) if v % 50 == 0 else (150, 150, 150)
        p = int(round(c + v / px)); t = 2 if v % 50 == 0 or v == 0 else 1
        cv2.line(o, (p, 0), (p, n - 1), col, t); cv2.line(o, (0, p), (n - 1, p), col, t)
        if v % 20 == 0: cv2.putText(o, str(v), (p + 2, int(c) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 200), 1)
    for r, col in ((114, (0, 200, 0)), (118, (0, 0, 255)), (60, (0, 200, 200))):
        cv2.circle(o, (int(c), int(c)), int(r / px), col, 2)
    return o

if __name__ == '__main__':
    import math
    img, e = rectify()
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(OUT + 'maker_topdown.png', img)
    cv2.imwrite(OUT + 'maker_topdown_grid.png', grid(img))
    json.dump(dict(ellipse=[list(map(float, e[0])), list(map(float, e[1])), float(e[2])], R_EDGE=R_EDGE, px=PX, half=HALF),
              open(OUT + 'rectify.json', 'w'))
    print(e)
