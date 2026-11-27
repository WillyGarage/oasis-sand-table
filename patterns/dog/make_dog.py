#!/usr/bin/env python3
"""One-line portrait of Bill's dog (photo 2026-11-20, face crop in face_crop.jpg) and a shaded-spiral version.
Coordinates below are pixels in face_crop.jpg (620 x 500). The disc centre is (290, 235); 295 px = the drawing radius.
  make_dog.py  ->  dog_line.thr, dog_spiral.thr  (+ previews via tools/sandsim.py)"""
import math, sys, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
CX, CY, S = 290.0, 235.0, 295.0

def spline(pts, step=2.0, closed=False):
    """Catmull-Rom through pts, resampled about every `step` px."""
    p = np.array(pts, float)
    if closed: q = np.vstack([p[-1], p, p[0], p[1]])
    else: q = np.vstack([p[0], p, p[-1]])
    out = []
    for i in range(1, len(q) - 2):
        p0, p1, p2, p3 = q[i - 1], q[i], q[i + 1], q[i + 2]
        n = max(2, int(np.linalg.norm(p2 - p1) / step))
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(q[-2])
    return [tuple(x) for x in out]

def line(a, b, step=2.0):
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]

def ring(c, r, start_deg, turns=1.0, step=2.0, r_end=None):
    """circle (or spiral to r_end) about c, starting at start_deg (image angle, 0 = right, clockwise on screen)."""
    n = max(12, int(2 * math.pi * r * abs(turns) / step)); out = []
    for i in range(n + 1):
        f = i / n; rr = r if r_end is None else r + (r_end - r) * f
        a = math.radians(start_deg) + 2 * math.pi * turns * f
        out.append((c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)))
    return out

def zigzag(path, amp, period):
    """wiggle a path sideways: scruffy fur"""
    out = []; d = 0.0
    for i, pnt in enumerate(path):
        a = path[max(0, i - 1)]; b = path[min(len(path) - 1, i + 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]; L = math.hypot(tx, ty) or 1
        if i: d += math.hypot(pnt[0] - path[i - 1][0], pnt[1] - path[i - 1][1])
        w = amp * math.sin(2 * math.pi * d / period)
        out.append((pnt[0] - ty / L * w, pnt[1] + tx / L * w))
    return out

def arc(c, r, a0, a1, step=2.0):
    n = max(6, int(abs(math.radians(a1 - a0)) * r / step))
    return [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]

def portrait(droop=1.0):
    """droop 1.0 = ears hang like a terrier's; 0.0 = ears straight out sideways as in the photo."""
    P = []
    chin = (290, 434); nose_c = (290, 372)
    eyeL = (236, 222); eyeR = (366, 222)
    P += line((290, 529), chin)                                   # in from the rim: the neck
    P += line(chin, (290, 410))                                   # mouth line up to the nose
    P += ring(nose_c, 38, 90, 1.0)                                # nose outline (starts and ends at its bottom)
    P += ring(nose_c, 38, 90, 1.75, r_end=9)                      # wind inward: a solid dark nose
    P += line(P[-1], (290, 334)); P += line((290, 334), (290, 258))   # up the middle of the muzzle to between the eyes
    P += line((290, 258), (290, 410)); P += line((290, 410), chin)    # and back down through the nose to the chin
    beardL = spline([chin, (258, 430), (228, 414), (206, 386), (196, 350)])
    P += zigzag(beardL, 13, 27)
    P += spline([(196, 350), (186, 312), (179, 272), (176, 238)]) # left cheek up to eye height
    # left eye: a short patch line in from the cheek, the eye ring, a scruffy brow over it, and back out
    P += line((176, 238), (eyeL[0] - 24, eyeL[1] + 2))
    P += ring(eyeL, 24, 175, 1.0)
    P += line((eyeL[0] - 24, eyeL[1]), (eyeL[0] - 40, eyeL[1] - 8))
    browL = arc(eyeL, 41, 192, 318)
    P += zigzag(browL, 5, 16); P += browL[::-1]
    P += line((eyeL[0] - 40, eyeL[1] - 8), (176, 238))
    P += spline([(176, 238), (173, 214), (172, 194)])             # on up to the bottom of the ear
    dy = 34 * droop
    P += spline([(172, 194), (140, 192 + dy * .5), (96, 184 + dy), (54, 160 + dy)])                 # under the left ear to its tip
    P += spline([(54, 160 + dy), (70, 124 + dy * .4), (104, 100), (150, 86), (196, 98)])            # over the top of the ear
    P += spline([(196, 98), (166, 118), (136, 140 + dy * .4), (112, 156 + dy * .7)])                # the fold
    P += spline([(112, 156 + dy * .7), (136, 140 + dy * .4), (166, 118), (196, 98)])
    top = spline([(196, 98), (224, 72), (258, 57), (290, 52), (326, 55), (364, 67), (398, 90)])
    P += zigzag(top, 12, 29)
    P += spline([(398, 90), (430, 110), (462, 134 + dy * .4), (488, 150 + dy * .7)])                # right fold, out and back
    P += spline([(488, 150 + dy * .7), (462, 134 + dy * .4), (430, 110), (398, 90)])
    P += spline([(398, 90), (446, 78), (494, 92), (530, 118 + dy * .4), (568, 156 + dy)])           # over the right ear to its tip
    P += spline([(568, 156 + dy), (524, 180 + dy), (482, 188 + dy * .5), (442, 188)])               # back under it
    P += spline([(442, 188), (434, 210), (428, 236)])
    P += line((428, 236), (eyeR[0] + 24, eyeR[1] + 2))            # right eye, the same way
    P += ring(eyeR, 24, 5, -1.0)
    P += line((eyeR[0] + 24, eyeR[1]), (eyeR[0] + 40, eyeR[1] - 8))
    browR = arc(eyeR, 41, -12, -138)
    P += zigzag(browR, 5, 16); P += browR[::-1]
    P += line((eyeR[0] + 40, eyeR[1] - 8), (428, 236))
    P += spline([(428, 236), (424, 272), (412, 312), (392, 350)]) # right cheek down
    beardR = spline([(392, 350), (376, 386), (352, 414), (322, 430), chin])
    P += zigzag(beardR, 13, 27)
    P += line(chin, (290, 529))                                   # out the way it came
    return P

def outline(droop=1.0):
    """closed head outline (crop px), symmetric about x = 290, starting and ending at the left ear tip"""
    dy = 34 * droop; chin = (290, 434)
    tipL = (54, 160 + dy)
    half = []                                            # left half, from the top centre round to the chin
    half += zigzag(spline([(290, 52), (258, 57), (224, 72), (196, 98)]), 10, 29)                    # tufted top
    half += spline([(196, 98), (150, 86), (104, 100), (70, 124 + dy * .4), tipL])                   # over the ear to its tip
    half += spline([tipL, (96, 184 + dy), (140, 192 + dy * .5), (172, 194)])                        # back under the ear
    half += spline([(172, 194), (173, 214), (176, 238), (179, 272), (186, 312), (196, 350)])        # cheek
    half += zigzag(spline([(196, 350), (206, 386), (228, 414), (258, 430), chin]), 11, 27)          # beard
    right = [(580 - x, y) for x, y in half[::-1]]        # mirror: chin up the right side to the top centre
    P = half + right
    i0 = min(range(len(P)), key=lambda i: (P[i][0] - tipL[0]) ** 2 + (P[i][1] - tipL[1]) ** 2)
    return P[i0:] + P[:i0 + 1]

FCX, FCY, FS = 290.0, 243.0, 252.0      # the filled version is drawn larger: ear tips almost at the rim
def filled(droop=1.0, pitch=0.047):
    """Head filled with lines that follow its outline inward; eyes left as smooth islands; ends as a spiral in the nose.
    Enters from the rim at the left ear tip, so there is no line across the face."""
    import cv2
    F = 2.0; W, H = int(620 * F), int(560 * F)
    nose_c = (290, 372); eyeL = (234, 222); eyeR = (346, 222); R_EYE, R_NOSE = 22, 36
    poly = np.array([[x * F, y * F] for x, y in outline(droop)], np.int32)
    mask = np.zeros((H, W), np.uint8); cv2.fillPoly(mask, [poly], 255)
    for c, r in ((eyeL, R_EYE), (eyeR, R_EYE), (nose_c, R_NOSE)): cv2.circle(mask, (int(c[0] * F), int(c[1] * F)), int(r * F), 0, -1)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    pp = pitch * FS * F
    loops = []                                         # (level, is_nose_ring, points in crop px)
    lv = 0; d = 2.0
    while dist.max() >= d:
        cs, hier = cv2.findContours((dist >= d).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        for i, c in enumerate(cs):
            c = c[:, 0, :].astype(float)
            if len(c) < 40: continue
            c = c[::4]                                  # resample, then smooth round the loop
            k = np.array([1, 4, 6, 4, 1], float); k /= k.sum()
            c = np.stack([np.convolve(np.r_[c[-2:, j], c[:, j], c[:2, j]], k, 'valid') for j in (0, 1)], 1) / F
            cen = c.mean(0); hole = hier[0][i][3] >= 0
            nose_ring = hole and math.hypot(cen[0] - nose_c[0], cen[1] - nose_c[1]) < 30
            loops.append((lv, nose_ring, c))
        lv += 1; d = pp * lv
    # Join the loops into one line with only tiny hops: a tree of neighbouring loops (each hop is one line-spacing long),
    # walked depth-first. The branch that leads to the nose is taken last and not returned from, so the line ends there.
    from scipy.spatial import cKDTree
    import sys as _sys; _sys.setrecursionlimit(10000)
    L = [l[2] for l in loops]; trees = [cKDTree(c) for c in L]
    def nearest(c, pt): return int(np.argmin((c[:, 0] - pt[0]) ** 2 + (c[:, 1] - pt[1]) ** 2))
    def gap(i, j):                                       # closest approach of two loops: (distance, index on i, index on j)
        d, k = trees[j].query(L[i]); m = int(np.argmin(d)); return float(d[m]), m, int(k[m])
    area = [abs(np.sum(c[:, 0] * np.roll(c[:, 1], 1) - c[:, 1] * np.roll(c[:, 0], 1))) / 2 for c in L]
    root = max((i for i in range(len(L)) if loops[i][0] == 0), key=lambda i: area[i])
    nose_i = min((i for i in range(len(L)) if loops[i][0] == 0 and i != root), key=lambda i: math.hypot(L[i][:, 0].mean() - nose_c[0], L[i][:, 1].mean() - nose_c[1]))
    parent = {root: None}; hop = {}; frontier = [root]; left = set(range(len(L))) - {root}
    while left:                                          # grow the tree: always attach the loop closest to the tree so far
        best = None
        for j in left:
            for i in frontier if len(frontier) < 12 else list(parent):
                if abs(loops[i][0] - loops[j][0]) > 1 and not (loops[i][0] <= 1 and loops[j][0] <= 1): continue
                d, a_i, a_j = gap(i, j)
                if best is None or d < best[0]: best = (d, i, j, a_i, a_j)
        if best is None:
            for j in left:
                for i in parent:
                    d, a_i, a_j = gap(i, j)
                    if best is None or d < best[0]: best = (d, i, j, a_i, a_j)
        _, i, j, a_i, a_j = best
        parent[j] = i; hop[j] = (a_i, a_j); left.discard(j); frontier = list(parent)
    kids = {}
    for j, i in parent.items():
        if i is not None: kids.setdefault(i, []).append(j)
    special = set(); k = nose_i
    while k is not None: special.add(k); k = parent[k]
    dy = 34 * droop; tip = np.array([54.0, 160 + dy])
    th = math.atan2(-(tip[1] - FCY), tip[0] - FCX)
    P = [(FCX + FS * math.cos(th), FCY - FS * math.sin(th))]               # on the rim, beside the left ear tip
    def visit(i, i0):
        c = L[i]; n = len(c)
        mine = sorted(kids.get(i, []), key=lambda j: (hop[j][0] - i0) % n)
        nxt = next((j for j in mine if j in special), None)
        at = {}
        for j in mine:
            if j != nxt: at.setdefault((hop[j][0] - i0) % n, []).append(j)
        for step in range(n + 1):
            idx = (i0 + step) % n; P.append(tuple(c[idx]))
            for j in at.get(step, []) if step < n else []:
                visit(j, hop[j][1]); P.append(tuple(c[idx]))
        if nxt is not None:                              # go on round to where the nose branch leaves, and do not come back
            for step in range(1, (hop[nxt][0] - i0) % n + 1): P.append(tuple(c[(i0 + step) % n]))
            visit(nxt, hop[nxt][1])
    visit(root, nearest(L[root], tip))
    cur = P[-1]
    a0 = math.degrees(math.atan2(cur[1] - nose_c[1], cur[0] - nose_c[0]))
    P += ring(nose_c, R_NOSE - 5, a0, 3.2, r_end=3)                        # solid nose, ending in its middle
    return P

def to_thr(P, path, cx=CX, cy=CY, sc=S):
    D = [P[0]]
    for q in P[1:]:
        a = D[-1]; n = int(math.hypot(q[0] - a[0], q[1] - a[1]) / 2.5)
        for i in range(1, n): D.append((a[0] + (q[0] - a[0]) * i / n, a[1] + (q[1] - a[1]) * i / n))
        D.append(q)
    out = []; prev = None
    for x, y in D:
        X, Y = (x - cx) / sc, -(y - cy) / sc
        r = min(1.0, math.hypot(X, Y)); th = math.atan2(Y, X)
        if prev is not None:
            while th - prev > math.pi: th -= 2 * math.pi
            while th - prev < -math.pi: th += 2 * math.pi
        if r < 0.004 and prev is not None: th = prev               # through the centre: keep the angle
        prev = th; out.append((th, r))
    open(path, 'w').write('# dog portrait\n' + ''.join('%.5f %.5f\n' % p for p in out))
    return len(out)

def shaded_spiral(path, pitch=0.034):
    import cv2
    g = cv2.cvtColor(cv2.imread(HERE + '/face_crop.jpg'), cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 5)
    lo, hi = np.percentile(g, 4), np.percentile(g, 96)
    dark = np.clip((hi - g) / (hi - lo), 0, 1) ** 1.3                # 1 = darkest
    out = []; turns = 0.97 / pitch; N = int(turns * 420)
    ph = 0.0
    for k in range(N + 1):
        u = k / N; th = 2 * math.pi * turns * u; r = 0.97 * u
        x = CX + S * r * math.cos(th); y = CY - S * r * math.sin(th)
        xi, yi = int(round(min(max(x, 0), g.shape[1] - 1))), int(round(min(max(y, 0), g.shape[0] - 1)))
        d = dark[yi, xi] if (0 <= x < g.shape[1] and 0 <= y < g.shape[0]) else 0.0
        ph += 2 * math.pi * (0.97 * 2 * math.pi * turns / N) * max(r, 0.05) / 0.035   # wiggle wavelength about one pitch along the line
        out.append((th, min(1.0, max(0.0, r + 0.5 * pitch * d * math.sin(ph)))))
    open(path, 'w').write('# dog, shaded spiral\n' + ''.join('%.5f %.5f\n' % p for p in out))
    return len(out)

if __name__ == '__main__':
    print('filled, droopy ears', to_thr(filled(1.0), HERE + '/dog_filled.thr', FCX, FCY, FS))
    print('line version', to_thr(portrait(1.0), HERE + '/dog_line.thr'))
