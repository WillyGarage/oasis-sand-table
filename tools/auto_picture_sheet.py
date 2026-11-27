#!/usr/bin/env python3
"""Compare sheet for tools/auto_picture.py: photo (grey, as fitted to the tray) | plan | simulated sand, plus a 150 px thumbnail row.
    python3 tools/auto_picture_sheet.py cat_a [more tags]  -> captures/auto-picture/<tag>_sheet.png"""
import sys, os, cv2, numpy as np
O = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/captures/auto-picture/'

def crop_tray(im):
    h, w = im.shape[:2]; c = min(h, w)
    y0 = (h - c) // 2; x0 = (w - c) // 2
    return im[y0:y0 + c, x0:x0 + c]

for tag in sys.argv[1:]:
    name = tag.split('_')[0]
    ph = cv2.imread(O + name + '_photo.png'); pl = cv2.imread(O + tag + '_plan.png'); sim = cv2.imread(O + tag + '.png')
    if sim is None: print('no sim for', tag); continue
    S = 640
    def r(x): return cv2.resize(crop_tray(x), (S, S), interpolation=cv2.INTER_AREA)
    def lab(x, t): x = x.copy(); cv2.putText(x, t, (8, 24), 0, 0.7, (0, 0, 255), 2); return x
    row = np.hstack([lab(r(ph), 'photo'), lab(r(pl), 'plan'), lab(r(sim), 'sim')])
    th = [cv2.resize(crop_tray(x), (150, 150), interpolation=cv2.INTER_AREA) for x in (ph, sim)]
    strip = np.full((170, row.shape[1], 3), 255, np.uint8); strip[10:160, 10:160] = th[0]; strip[10:160, 180:330] = th[1]
    cv2.putText(strip, 'thumbnails 150 px: photo, sim', (360, 90), 0, 0.7, (0, 0, 0), 2)
    cv2.imwrite(O + tag + '_sheet.png', np.vstack([row, strip]))
    print('wrote', tag + '_sheet.png')
