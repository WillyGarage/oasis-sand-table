#!/usr/bin/env python3
"""Draw the decoded picture: sections coloured on the rectified photo, direction ticks, spacing labels. python3 tools/trex_render.py [x0 y0 x1 y1 scale out]"""
import numpy as np, cv2, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = ROOT + '/captures/relief-study/v4/trex/'
PX = 0.2; C = 625

def render(spacing=None, x0=-125, y0=-125, x1=125, y1=125, s=1.0, out=OUT + 'decoded.png', tick_mm=5.0, fill=0.35):
    M = np.load(OUT + 'section_masks.npz'); O = np.load(OUT + 'section_fields.npz')
    im = cv2.imread(OUT + 'maker_topdown.png')
    a = int(C + x0 / PX); b = int(C - y1 / PX); c = int(C + x1 / PX); d = int(C - y0 / PX)
    rng = np.random.RandomState(5)
    o = im.astype(np.float32).copy()
    names = list(M.files)
    cols = {n: rng.randint(70, 255, 3) for n in names}
    lab = np.full(im.shape[:2], -1, np.int32)
    for i, n in enumerate(names):
        m = M[n]; o[m] = o[m] * (1 - fill) + cols[n] * fill; lab[m] = i
    o = o.astype(np.uint8)
    e = (lab != np.roll(lab, 1, 0)) | (lab != np.roll(lab, 1, 1))
    o[e & (lab >= 0)] = (0, 0, 255)
    o = cv2.resize(o[b:d, a:c], None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    for n in names:
        m = M[n]; ori = O[n].astype(np.float32)
        step = int(tick_mm / PX)
        ys, xs = np.nonzero(m[::step, ::step] & True)
        for yy, xx in zip(ys * step, xs * step):
            if not (b <= yy < d and a <= xx < c): continue
            if not m[max(0, yy - 6):yy + 7, max(0, xx - 6):xx + 7].all(): continue
            th = np.radians(ori[yy, xx]); L = tick_mm * 0.4 / PX
            p0 = ((xx - a) * s - L * s * np.cos(th), (yy - b) * s + L * s * np.sin(th))
            p1 = ((xx - a) * s + L * s * np.cos(th), (yy - b) * s - L * s * np.sin(th))
            cv2.line(o, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), (0, 0, 0), 2, cv2.LINE_AA)
            cv2.line(o, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), (255, 255, 0), 1, cv2.LINE_AA)
    for n in names:
        m = M[n]
        dt = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3); k = np.argmax(dt); cy, cx = divmod(k, m.shape[1])
        if not (b <= cy < d and a <= cx < c): continue
        txt = n + ('' if not spacing or n not in spacing else ' %.1f' % spacing[n])
        p = (int((cx - a) * s) - 25, int((cy - b) * s))
        cv2.putText(o, txt, p, 0, 0.45 * max(s, 0.8), (0, 0, 0), 2, cv2.LINE_AA); cv2.putText(o, txt, p, 0, 0.45 * max(s, 0.8), (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(out, o)

if __name__ == '__main__':
    sp = None
    if os.path.exists(OUT + 'spacing.json'): sp = json.load(open(OUT + 'spacing.json'))
    if len(sys.argv) > 1:
        x0, y0, x1, y1, s = map(float, sys.argv[1:6]); render(sp, x0, y0, x1, y1, s, sys.argv[6])
    else:
        render(sp)
