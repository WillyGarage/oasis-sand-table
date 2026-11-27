#!/usr/bin/env python3
"""ROUND 3 (2026-11-26, not live; promote by replacing tools/face_small.py after Bill approves).
Changes from round 2: open smiles at their TRUE opening (round 2 opened slice mouths to 9 mm; Bill: no exaggerated
features); the mouth hangs from a short smile crease from the nostril wing to the mouth corner instead of a line from the
nose base into the middle of the mouth (glasses wearers keep that line: their nose starts free under the bridge); slice
faces stand on a neck instead of a collar (the head about 8% bigger again in the same zone; the centre keeps v1 shoulders);
slice faces get their brows back (Bill's real-sand photos of v1, 15:00 PT: brow + lid + pit come out as a clean brow bar
over two deep dark eye holes, the best-reading part of those faces).
ROUND 2 notes:
Changes from v1: collar bust (head 10-20% bigger in the same zone); slice faces drop the brows (they merged with the
lid into one bar) so the two eyes read as separate dots, the nose starts at the inner corner of an eye; open smiles are a
closed crescent, opened to 0.9 groove (slices) / 1.1 (centre) at the middle so they read as an open smile; centre faces
(>= BIG grooves wide, keeping v1's shoulders) keep brows and get almond eyes (upper + lower lid round the pupil pit).

Groove-aware face drawings for the 36-inch table's zones (photo -> unit-square strokes, same format as the app's
sand-app/server/face_art.face_strokes, so tools/sand_turn.build_turn takes them as `face_path` unchanged).

    face_strokes_groove(jpeg_bytes, zone='outer') -> {"strokes": [[[x, y], ...], ...], "ok": bool, "note": str, "info": {...}}
    build/p2s-venv/bin/python tools/face_small.py PHOTO.jpg --zone outer -o OUT.json      (MediaPipe: needs that venv)

Why (2026-11-26, Bill: "the faces in the non-pie zones are not excellent ... too much detail"): face_art spaces separate
lines MIN_GAP = 0.075 face widths apart, "about one 4 mm ball width".  On the 36-inch table one drawn line is about
10 mm wide crest to crest (measured off Bill's photos of the real sand, 2026-11-26: letter S 11 mm, a shoulder line
9.7 mm, scale 11.3-11.5 px/mm from the 2.43 mm clearing ripples).  A slice face is only 44-58 mm wide (4.3-5.8 lines),
the centre face 72-82 mm (7-8 lines), so the app's 4 mm spacing packs lids, pupils, brows, nose and mouth into grooves
that merge into ridged mush, and its doubled "bold" passes and 1-ball hair lines add more.  Here every spacing is set
from the real groove G at the real drawn size (BOX_MM per zone kind):

  * every line is one pass (one groove is already a fifth of a slice face's width);
  * features keep true positions; separate lines stay SEP*G apart or the lower-priority one is trimmed (the nose stops
    short of the mouth); brows are drawn where they are and merge with the lid and pupil pit into one eye mass (at these
    sizes a brow is only 0.5-0.8 G above the lid; Mini Round 15: the brow is what makes the blob read as an eye);
  * hair and beard are masses: lines mass_sep*G apart following the hair outline / the jaw, allowed to merge with the
    face line (ridged texture), never within a groove of the mouth (the smile stays visible inside a beard);
  * shoulders are shorter (0.8 face widths from the middle instead of 1.08);
  * the parts are built to touch, so the tour (tools/face_route.py) needs no stray lines: neck lines start ON the jaw,
    hair lines join the hair outline at one end, a brow's tail runs on to the outline at the temple, the nose starts at
    the inner end of its brow, a short philtrum joins the base of the nose to the middle of the mouth, beard lines
    join the jaw; anything still apart gets a short join from one of its END points (_join), never across the middle.

Same models and measurements as face_art (MediaPipe landmarks + selfie segmentation); its helpers are imported, its file
is not changed.
"""
import json, math, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP_SERVER = os.path.join(HERE, '..', 'sand-app', 'server')
if APP_SERVER not in sys.path:
    sys.path.insert(0, APP_SERVER)
import face_art as fa                                     # noqa: E402  (read-only use of the app's face code)
from face_art import (resample, smooth, length, normals, runs, closed_runs, mask_contour, sample_mask, Gap,  # noqa: E402
                      lens_from_acc, beard_mask, EYE_A_UP, EYE_A_LO, EYE_B_UP, EYE_B_LO, BROW_A, BROW_B, LIP_OUT_LO,
                      LIP_IN_UP, LIP_IN_LO, NOSE_A, NOSE_B, IRIS_A, IRIS_B, FACE, HAIR, ACC, BG)

GROOVE_MM = 10.0          # crest-to-crest width of one drawn line on the 36-inch table (measured, see above)
SEP = 1.3                 # separate lines: centre lines at least this many grooves apart (leaves a ~3 mm ridge)
HOP = 0.45                # parts further apart than this many grooves get a join line (the tour, tools/face_route.py, hops up to ~0.6)
# physical size of the drawing's box (max(height, width / 1.15), what sand_turn.custom_face scales to), by zone kind;
# measured from builds on 2026-11-26 with the app's faces: inner slices 121 mm, outer 103 mm, centre 170 mm
BOX_MM = dict(inner=121.0, outer=103.0, centre=170.0)
BIG = 7.0                 # faces at least this many grooves wide (the centre) get brows, almond eyes, a lighter smile
DEFAULTS = dict(
    shoulder=0.80,        # shoulder ends this many face widths from the middle (face_art 1.08)
    hair_lines=4,         # at most this many hair lines inside the hair outline
    mass_sep=1.05,        # hair and beard are masses: their lines are this many grooves apart (ridged texture, not separate lines)
    beard_lines=3,
    pit=0.30,             # pupil pit radius, grooves
    pit_pitch=0.07,       # pupil pit spiral pitch, grooves per turn
    wing=False,           # True: upper lids run out to the outline at the temple (reads as glasses: not used)
    nose_from='auto',     # 'brow' / 'eye' / None; auto: the brow where brows are drawn, else the inner corner of the eye
    philtrum=True,        # the mouth is reached from the base of the nose
    brows='auto',         # True / False; auto: only on faces at least BIG grooves wide (the centre), where they clear the lid
    eye='auto',           # 'lid': upper lid with the pupil pit wound on it; 'almond': upper + lower lid round the pit;
                          # 'pit': the pit alone; auto: almond on BIG faces, lid otherwise
    nose_base=True,       # False: the nose line stops at the nostril wing (no base line)
    bust='auto',          # 'collar': neck and a short collar (the head 10-20% bigger in the same zone); 'compact'; 'v1';
                          # auto: collar in the slices, v1 shoulders in the centre (with the collar, sand_turn's centre layout,
                          # which samples the drawing every ~10 mm, put faces 1-4 mm too close to the name or the ring)
    eye_open=0.0,         # 'almond' eyes: the opening is at least this many grooves (0 = true opening)
    mouth='crescent',     # 'crescent': an open smile as a closed loop (inner upper + lower lip); closed mouths and
                          # 'line': one smile curve; 'lower': the open smile's lower edge
    mouth_open='auto',    # 'crescent': the opening is at least this many grooves at the middle; auto: 1.1 on BIG faces
                          # (shows a light sliver, like the app's teeth), 0.9 on slice faces (a dark open smile)
    mouth_join='auto',      # auto (round 3): 'wingcrease', or 'philtrum' when there are glasses (the nose starts free under
                            # the bridge and a crease would make a Z);  # 'crease': no philtrum; the nose stops at its wing and a smile crease runs from there to the
                            # mouth corner on that side, so nothing enters the middle of the mouth
)


def face_strokes_groove(jpeg_bytes, zone='outer', box_mm=None, groove_mm=GROOVE_MM, opt=None, debug=None):
    box_mm = float(box_mm or BOX_MM['centre' if zone == 'centre' else ('inner' if str(zone).startswith('inner') else 'outer')])
    try:
        rgb = fa._decode(jpeg_bytes)
    except Exception:
        return dict(strokes=[], ok=False, note='not a readable image')
    if rgb is None or min(rgb.shape[:2]) < 48:
        return dict(strokes=[], ok=False, note='image too small')
    try:
        L, conf = fa._detect(rgb)
    except Exception as e:
        return dict(strokes=[], ok=False, note='face finder unavailable: %s' % type(e).__name__)
    if L is None:
        return dict(strokes=[], ok=False, note='no face found')
    o = dict(DEFAULTS, **(opt or {}))
    if o['bust'] == 'auto':
        o['bust'] = 'v1' if zone == 'centre' else 'neck'
    strokes, note, info = _draw(rgb, L, conf, box_mm, groove_mm, o, debug)
    if not strokes:
        return dict(strokes=[], ok=False, note=note)
    return dict(strokes=strokes, ok=True, note=note, info=info)


def _near_pt(P, Q):
    """index in Q of the point nearest to P (one point), and the distance"""
    d = np.hypot(*(Q - P).T)
    i = int(d.argmin())
    return i, float(d[i])


def _draw(rgb, L, conf, box_mm, groove_mm, o, debug=None):
    import cv2
    from scipy import ndimage as ndi
    L = L[:, :2]
    fw = float(np.hypot(*(L[454] - L[234])))
    H0, W0 = rgb.shape[:2]
    P0 = int(0.12 * max(H0, W0))
    rgb = cv2.copyMakeBorder(rgb, P0, P0, P0, P0, cv2.BORDER_CONSTANT, value=(232, 220, 184))
    bgc = np.zeros((6,) + rgb.shape[:2], np.float32); bgc[BG] = 1.0
    bgc[:, P0:P0 + H0, P0:P0 + W0] = conf
    conf = bgc
    L = L + P0
    H, W = rgb.shape[:2]
    st = 0.012 * fw                                            # working point step
    cx = float((L[454, 0] + L[234, 0]) / 2)
    chin = L[152]
    eye_y = float((L[IRIS_A, 1] + L[IRIS_B, 1]) / 2)
    fh = float(chin[1] - L[10, 1])
    turn = float((L[1, 0] - cx) / fw)

    blur = cv2.GaussianBlur(conf.transpose(1, 2, 0), (0, 0), max(1.0, 0.02 * fw)).transpose(2, 0, 1)
    lab = blur.argmax(0)
    yy, xx = np.mgrid[0:H, 0:W]

    def comp_near(m, pts):
        n, cl = cv2.connectedComponents(m.astype(np.uint8))
        keep = set(int(cl[int(np.clip(p[1], 0, H - 1)), int(np.clip(p[0], 0, W - 1))]) for p in pts) - {0}
        return np.isin(cl, list(keep)) if keep else np.zeros(m.shape, bool)

    def disk(r):
        r = max(1, int(r)) | 1
        return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))

    # ------------------------------------------------ masks (as face_art._draw)
    oval = np.zeros((H, W), np.uint8)
    cv2.fillPoly(oval, [np.round(L[fa.OVAL]).astype(np.int32)], 1)
    oval = oval > 0
    near = cv2.dilate(oval.astype(np.uint8), disk(0.2 * fw)) > 0
    face = (lab == FACE) | ((lab == ACC) & near)
    face = comp_near(face | oval, [L[1], L[152], L[10]])
    face = ndi.binary_fill_holes(face)
    beard = beard_mask(rgb, L, face, fw)
    face &= yy < chin[1] + (0.16 if beard is not None else 0.05) * fw
    face &= (cv2.dilate(oval.astype(np.uint8), disk((0.3 if beard is not None else 0.08) * fw)) > 0) | (yy < L[2, 1])
    face = cv2.morphologyEx(face.astype(np.uint8), cv2.MORPH_OPEN, disk(0.05 * fw)) > 0
    face = comp_near(face, [L[1]])
    y_bottom = chin[1] + dict(compact=0.32, collar=0.24, neck=0.16).get(o['bust'], 0.45) * fh
    hair = (lab == HAIR) & ~face
    hair = cv2.morphologyEx(hair.astype(np.uint8), cv2.MORPH_OPEN, disk(0.04 * fw)) > 0
    touch = cv2.dilate(face.astype(np.uint8), disk(0.06 * fw)) > 0
    n, cl = cv2.connectedComponents(hair.astype(np.uint8))
    keep = set(np.unique(cl[touch & hair])) - {0}
    hair = np.isin(cl, list(keep)) & (yy < y_bottom)
    has_hair = hair.sum() > 0.03 * fw * fw

    def contour_of(m, sigma):
        m2 = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma) > 0.5
        c = mask_contour(m2, min_area=0.02 * fw * fw)
        return None if c is None else smooth(c, sigma, st, closed=True)

    # ------------------------------------------------ shoulders (short), then the drawing's box -> the groove in px
    roll = 0.3 * math.atan2(L[263, 1] - L[33, 1], L[263, 0] - L[33, 0])
    ux = np.array([math.cos(roll), math.sin(roll)]); uy = np.array([-math.sin(roll), math.cos(roll)])
    base = np.array([0.5 * cx + 0.5 * chin[0], chin[1]]) - 0.1 * fh * uy
    sx = o['shoulder']
    shoulders = []
    for sgn in (-1, 1):
        if o['bust'] == 'compact':
            sx = 0.62
            knots = ((0.28, -0.05), (0.28, 0.13), (0.33, 0.20), (0.46, 0.24), (sx - 0.07, 0.27), (sx, 0.33))
        elif o['bust'] == 'neck':                            # neck lines with a slight flare and no collar
            sx = 0.38
            knots = ((0.28, -0.05), (0.28, 0.06), (0.30, 0.10), (0.34, 0.13), (sx - 0.02, 0.15), (sx, 0.17))
        elif o['bust'] == 'collar':                          # neck and a short collar line: the head as big as it can be
            sx = 0.50
            knots = ((0.28, -0.05), (0.28, 0.10), (0.32, 0.16), (0.42, 0.20), (sx - 0.04, 0.22), (sx, 0.25))
        else:
            knots = ((0.28, -0.05), (0.28, 0.20), (0.33, 0.29), (0.52, 0.35), (sx - 0.12, 0.40), (sx, 0.47))
        pts = [base + sgn * x * fw * ux + y * fh * uy for x, y in knots]
        shoulders.append(smooth(np.array(pts), 0.04 * fw, st))
    fc0 = contour_of(face, 0.035 * fw)
    if fc0 is None:
        return [], 'no face outline', {}
    ext = [fc0] + shoulders
    if has_hair:
        hm0 = cv2.GaussianBlur(hair.astype(np.float32), (0, 0), 0.04 * fw) > 0.5
        hc0 = mask_contour(hm0, min_area=0.02 * fw * fw)
        if hc0 is not None:
            ext.append(hc0[hc0[:, 1] < y_bottom])
    allp = np.vstack([e for e in ext if len(e)])
    bw, bh = np.ptp(allp[:, 0]), np.ptp(allp[:, 1])
    mm_px = box_mm / max(bh, bw / 1.15)
    G = groove_mm / mm_px                                       # one groove in px at the drawn size
    S = o.get('sep', SEP) * G
    HOPpx = HOP * G
    info = dict(face_width_mm=round(fw * mm_px, 1), groove_px=round(G, 1), face_width_grooves=round(fw / G, 2), box_mm=box_mm)
    big = bool(fw / G >= BIG)
    o = dict(o)
    if o['brows'] == 'auto':
        o['brows'] = True        # round 3, after Bill's photos of v1: brow, lid and pupil pit merge into a clean brow bar with
                                 # two dark eye holes under it, which reads well; round 2 had dropped slice brows
    o['_big'] = big
    if o['eye'] == 'auto':
        o['eye'] = 'almond' if big else 'lid'
    if o['nose_from'] == 'auto':
        o['nose_from'] = 'brow' if o['brows'] else 'eye'
    if o['mouth_open'] == 'auto':
        o['mouth_open'] = 0.0                                  # round 3: true opening everywhere (Bill: no exaggerated features)
    info['style'] = dict((k, o[k]) for k in ('bust', 'brows', 'eye', 'nose_from', 'mouth', 'mouth_open'))

    items = []          # (tier, name, polyline px, closed)
    gap = Gap()

    def accept(tier, name, P, closed=False):
        P = np.asarray(P, float)
        if len(P) < 2:
            return
        items.append((tier, name, P, closed)); gap.add(resample(P, st, closed))

    def cut_bottom(P):
        low = P[:, 1] > y_bottom - 2
        e = 0.06 * fw
        side = ((P[:, 0] < P0 + e) | (P[:, 0] > P0 + W0 - e) | (P[:, 1] > P0 + H0 - e)) & (P[:, 1] > L[2, 1])
        return low | side

    def snap_ends(P, targets, reach, ends=(0, 1)):
        """extend an open line's ends to the nearest point of `targets` (polylines) when that is within `reach`"""
        if not targets:
            return P
        T = np.vstack([resample(t, st) for t in targets])
        out = P
        if 0 in ends:
            i, d = _near_pt(out[0], T)
            if 0.05 * G < d <= reach:
                out = np.vstack([resample(np.array([T[i], out[0]]), st)[:-1], out])
        if 1 in ends:
            i, d = _near_pt(out[-1], T)
            if 0.05 * G < d <= reach:
                out = np.vstack([out, resample(np.array([out[-1], T[i]]), st)[1:]])
        return out

    # 1. face outline: one pass, smoothed at about a third of a groove (ears and small bumps cannot show anyway)
    fc = contour_of(face, max(0.035 * fw, 0.3 * G))
    if fc is None:
        return [], 'no face outline', info
    face_line = resample(fc, st, True)
    accept(0, 'face', face_line, closed=True)
    face_d = ndi.distance_transform_edt(~face)

    # 2. hair: outer shape, then up to hair_lines lines inside it, SEP grooves apart, each ending on a drawn line
    hair_lines = []
    if has_hair:
        hm = cv2.GaussianBlur(hair.astype(np.float32), (0, 0), max(0.04 * fw, 0.25 * G)) > 0.5
        hc = contour_of(hm, max(0.03 * fw, 0.25 * G))
        if hc is not None:
            ok = (gap.dist(hc) > 0.6 * G) & ~cut_bottom(hc)
            for idx in sorted(closed_runs(ok), key=len, reverse=True):
                p = hc[idx]
                if length(p) >= 1.5 * S:
                    p = snap_ends(p, [face_line], 1.6 * S)
                    accept(1, 'hair', p)
                    hair_lines.append(p)
            outside = ~(hm | face)
            d_out = ndi.distance_transform_edt(~outside)
            nl = 0
            for k in range(1, 8):
                if nl >= o['hair_lines']:
                    break
                lev = (k - 0.1) * o['mass_sep'] * G
                m = hm & (d_out >= lev)
                if m.sum() < 0.01 * fw * fw:
                    break
                cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
                for c in cs:
                    c = c[:, 0, :].astype(float)
                    if len(c) < 12:
                        continue
                    c = smooth(c, max(0.03 * fw, 0.25 * G), st, closed=True)
                    ci = np.clip(np.round(c).astype(int), 0, [W - 1, H - 1])
                    ok = (face_d[ci[:, 1], ci[:, 0]] > 0.55 * o['mass_sep'] * G) & ~cut_bottom(c)
                    for idx in closed_runs(ok):
                        p = c[idx]
                        if length(p) < 4 * G:                  # short pieces read as boxes, not hair
                            continue
                        for q in fa.keep_clear(p, gap, 0.55 * o['mass_sep'] * G, 4 * G):
                            # join ONE end to the hair line beside it (both ends joined make a box)
                            T_ = np.vstack([resample(t, st) for t in hair_lines]) if hair_lines else None
                            if T_ is not None:
                                e_ = 0 if _near_pt(q[0], T_)[1] <= _near_pt(q[-1], T_)[1] else 1
                                q = snap_ends(q, hair_lines, 1.2 * G, ends=(e_,))
                            accept(2, 'hairflow', q)
                            hair_lines.append(q)
                            nl += 1
    # 3. neck and shoulders, starting ON the jaw (or the hair, where long hair hides the neck)
    hair_d = cv2.dilate(hair.astype(np.uint8), disk(0.5 * G)) > 0
    for p in shoulders:
        inside = sample_mask(face, p) | sample_mask(hair_d, p)
        p = p[~inside & (p[:, 1] < y_bottom)]
        if len(p) < 2 or length(p) < 0.15 * fw:
            continue
        p = snap_ends(p, [face_line] + hair_lines, 1.5 * S, ends=(0,))
        accept(3, 'body', p)

    # 4. features
    feats = []                                              # (name, polyline, attach-info)
    lenses = []
    acc = conf[ACC]
    band_ = acc[max(0, int(eye_y - 0.3 * fw)):int(eye_y + 0.3 * fw)]
    if band_.size and band_.max() > 0.5:
        for up, ir in ((EYE_A_UP, IRIS_A), (EYE_B_UP, IRIS_B)):
            ew = float(np.hypot(*(L[up[0]] - L[up[-1]])))
            ln = lens_from_acc(acc, L[ir], ew)
            if ln is not None:
                ln = smooth(ln, max(0.03 * fw, 0.2 * G), st, closed=True)
                if 1.1 * ew < np.ptp(ln[:, 0]) < 2.8 * ew:
                    lenses.append(ln)
        if len(lenses) != 2:
            lenses = []

    def pit_at(c, r):
        """a small spiral wound in and back out (a dark dot), starting and ending at its top point"""
        pts, th, rr = [], -math.pi / 2, r
        while rr > 0.06 * G:
            pts.append((c[0] + rr * math.cos(th), c[1] + rr * math.sin(th)))
            dth = 0.2 * G / max(rr, 0.2 * G); th += dth; rr -= o['pit_pitch'] * G * dth / (2 * math.pi)
        sp = np.array(pts)
        return np.vstack([sp, sp[::-1][1:]])

    eye_pts = {}
    if lenses:
        lenses.sort(key=lambda p: p[:, 0].mean())
        for ln in lenses:
            # the ring alone: a pupil inside it could only be reached by a line across the lens
            feats.append(('lens', resample(ln, st, True), None))
        a, b = lenses
        ia = a[np.argmax(a[:, 0] - 0.5 * np.abs(a[:, 1] - eye_y))]
        ib = b[np.argmin(b[:, 0] + 0.5 * np.abs(b[:, 1] - eye_y))]
        if ib[0] - ia[0] > 0.2 * G:
            top = np.array([(ia[0] + ib[0]) / 2, min(ia[1], ib[1]) - 0.03 * fw])
            feats.append(('bridge', smooth(np.array([ia, top, ib]), 0.02 * fw, st), None))
        for ln, sgn in ((a, -1), (b, 1)):                    # temple arms out to the outline (they also join the lens to it)
            o_ = ln[np.argmax(sgn * ln[:, 0] - 0.5 * np.abs(ln[:, 1] - eye_y))]
            i, d = _near_pt(o_, face_line)
            if d > 0.3 * G and d < 3 * S:
                feats.append(('arm', resample(np.array([o_, face_line[i]]), st), None))
    else:
        for up, ir, outer_first in ((EYE_A_UP, IRIS_A, True), (EYE_B_UP, IRIS_B, False)):
            u = smooth(L[up], 0.02 * fw, st)
            if not outer_first:
                u = u[::-1]                                   # u runs outer corner -> inner corner
            ic = L[ir]
            r = o['pit'] * G
            k = int(np.argmin(np.abs(u[:, 0] - ic[0])))
            c = np.array([ic[0], u[k, 1] + 0.9 * r])
            lid = np.vstack([u[:k + 1], pit_at(c, r), u[k + 1:]])
            if o['eye'] == 'pit':
                lid = pit_at(np.array([ic[0], ic[1]]), r)
            elif o['eye'] == 'almond':
                lo_ids = EYE_A_LO if up is EYE_A_UP else EYE_B_LO
                lw = smooth(L[lo_ids], 0.02 * fw, st)
                if not outer_first:
                    lw = lw[::-1]                             # outer -> inner, like u
                eh = float(np.hypot(*(L[up[4]] - L[lo_ids[4]])))
                need = o['eye_open'] * G
                if eh < need:                                 # open the almond to `need` at its middle, corners fixed
                    t_ = np.linspace(0, 1, len(lw))
                    lw = lw + np.c_[np.zeros(len(lw)), (need - eh) * np.sin(np.pi * t_)]
                    c = np.array([ic[0], (u[k, 1] + np.interp(ic[0], lw[:, 0] if lw[0, 0] < lw[-1, 0] else lw[::-1, 0],
                                                              lw[:, 1] if lw[0, 0] < lw[-1, 0] else lw[::-1, 1])) / 2])
                lid = np.vstack([u[:k + 1], pit_at(c, r), u[k + 1:], lw[::-1][1:]])     # outer corner round and back to it
            if o['wing']:
                i, d = _near_pt(u[0], face_line)
                if d > 0.05 * G:
                    tang = u[0] - u[min(len(u) - 1, 3)]
                    tang /= max(1e-9, np.hypot(*tang))
                    tgt = face_line[i]
                    mid = u[0] + tang * 0.5 * d
                    wing = smooth(np.array([tgt, (tgt + mid) / 2, mid, u[0]]), 0.15 * G, st)
                    lid = np.vstack([wing[:-1], lid])
            feats.append(('eye', lid, None))
            eye_pts[ir] = (u[0], u[-1])                       # outer, inner corner

    # brows (true position).  At slice size a brow is only about half a groove above the lid, so brow, lid and pupil
    # merge into one dark eye mass (Round 15 on the Mini: a brow above is what makes the blob read as an eye).  The
    # brow's tail runs on to the outline at the temple when it is within a groove of it (that joins the eye to the
    # outline with no extra line), and its inner end is where the nose line starts.
    brow_pts = {}
    if o['brows']:
        for (lo, up), side in ((BROW_A, 'A'), (BROW_B, 'B')):
            m_ = smooth((L[lo] + L[up]) / 2, 0.03 * fw, st)          # outer end first (46 / 276)
            i, d = _near_pt(m_[0], face_line)
            if 0.05 * G < d <= 1.5 * G:
                m_ = np.vstack([resample(np.array([face_line[i], m_[0]]), st)[:-1], m_])
            brow_pts[side] = (m_[0], m_[-1])
            feats.append(('brow', m_, None))

    # mouth: one curve.  Open smile: the opening's lower two-thirds line; closed: the lip line.
    mw = float(np.hypot(*(L[61] - L[291])))
    gap_in = float(np.hypot(*(L[13] - L[14])))
    if gap_in > 0.07 * mw and o['mouth'] == 'lower':
        mid = 0.15 * L[LIP_IN_UP] + 0.85 * L[LIP_IN_LO]          # the open smile's lower edge: the U that says "smile"
    elif gap_in > 0.07 * mw:
        mid = 0.4 * L[LIP_IN_UP] + 0.6 * L[LIP_IN_LO]
    else:
        mid = (L[LIP_IN_UP] + L[LIP_IN_LO]) / 2
    mid[0], mid[-1] = L[61], L[291]
    mouth = smooth(mid, 0.02 * fw, st)
    if o['mouth'] == 'crescent' and gap_in > 0.07 * mw:
        top = L[LIP_IN_UP].copy(); top[0], top[-1] = L[61], L[291]
        bot = L[LIP_IN_LO].copy(); bot[0], bot[-1] = L[61], L[291]
        need = o['mouth_open'] * G
        if gap_in < need:                                    # lower the bottom lip line at the middle, corners fixed
            t_ = np.linspace(0, 1, len(bot))
            bot = bot + np.c_[np.zeros(len(bot)), (need - gap_in) * np.sin(np.pi * t_)]
        loop = np.vstack([smooth(top, 0.02 * fw, st), smooth(bot, 0.02 * fw, st)[::-1][1:]])
        mouth = loop
    feats.append(('mouth', mouth, None))

    # nose: the side line round the nostril to the middle of its base (a J).  It starts at the inner end of the brow on
    # its side (the classic brow-to-nose line), or of the eye when there are no brows; with glasses it starts free.
    nose_ids = NOSE_B if turn > 0.04 else NOSE_A
    nose_ids = nose_ids[:nose_ids.index(2) + 1] if (o['nose_base'] and o['mouth_join'] != 'crease') else nose_ids[:6]
    nose = smooth(L[nose_ids], 0.025 * fw, st)
    side = 'B' if nose_ids is NOSE_B else 'A'
    start = None
    if not lenses and o['nose_from'] == 'brow' and side in brow_pts:
        start = brow_pts[side][1]
    elif not lenses and o['nose_from'] in ('brow', 'eye'):
        ir = IRIS_B if side == 'B' else IRIS_A
        start = eye_pts[ir][1] if ir in eye_pts else None
    if start is not None:
        j = int(np.argmin(np.hypot(*(nose - start).T)[:max(2, len(nose) // 3)]))
        nose = np.vstack([smooth(np.array([start, (start + nose[j]) / 2, nose[j]]), 0.02 * fw, st)[:-1], nose[j:]])
    feats.append(('nose', nose, None))

    prio = ['lens', 'eye', 'brow', 'mouth', 'nose', 'bridge', 'arm']
    feats.sort(key=lambda f: prio.index(f[0]))
    fgap = Gap()
    for name, P, _ in feats:
        P = resample(P, st)
        if name in ('lens', 'eye', 'mouth', 'bridge', 'arm', 'brow'):
            pieces = [P]
        else:                                                   # nose: clear of the mouth (the philtrum joins them)
            mg = Gap(); mg.add(resample(mouth, st))
            ok = mg.dist(P) > (0.7 * G if o['philtrum'] else S)
            k = len(P) if ok.all() else int(np.argmin(ok))
            pieces = [P[:k]] if k > 1 and length(P[:k]) > 0.6 * G else []
        for q in pieces:
            items.append((4, name, q, False)); fgap.add(q); gap.add(q)

    if o['mouth_join'] == 'auto':
        o['mouth_join'] = 'philtrum' if lenses else 'wingcrease'
    info['style']['mouth_join'] = o['mouth_join']
    # wing crease: the nose keeps its hook; a short smile crease runs from the nostril wing on the nose's side down to
    # the mouth corner on that side (the nasolabial line a smile makes), so nothing enters the middle of the mouth
    if o['mouth_join'] == 'wingcrease':
        noses = [p for t, n_, p, c in items if n_ == 'nose']
        if noses:
            wing_lm = L[64] if side == 'A' else L[294]
            nz = noses[-1]
            nb = nz[int(np.argmin(np.hypot(*(nz - wing_lm).T)))]
            mc = min((L[61], L[291]), key=lambda q: float(np.hypot(*(q - nb))))
            mc = mouth[int(np.argmin(np.hypot(*(mouth - mc).T)))]
            mcen = mouth.mean(0)
            mid_ = (nb + mc) / 2
            away = mid_ - mcen; away = away / max(1e-9, np.hypot(*away))
            cr = smooth(np.array([nb, mid_ + away * 0.12 * float(np.hypot(*(mc - nb))), mc]), 0.15 * G, st)
            cr[0], cr[-1] = nb, mc
            items.append((4, 'crease', cr, False))
    # crease: from the end of the nose (its wing) round to the mouth corner on that side, bowed away from the mouth
    if o['mouth_join'] == 'crease':
        noses = [p for t, n_, p, c in items if n_ == 'nose']
        if noses:
            nb = noses[-1][-1]
            mc = min((L[61], L[291]), key=lambda q: float(np.hypot(*(q - nb))))
            mc = mouth[int(np.argmin(np.hypot(*(mouth - mc).T)))]
            mcen = mouth.mean(0)
            mid_ = (nb + mc) / 2
            away = mid_ - mcen; away = away / max(1e-9, np.hypot(*away))
            bow = 0.15 * float(np.hypot(*(mc - nb)))
            cr = smooth(np.array([nb, mid_ + away * bow, mc]), 0.15 * G, st)
            cr[0], cr[-1] = nb, mc
            items.append((4, 'crease', cr, False))
    # philtrum: base of the nose -> middle of the mouth, only if that is a hidden hop or close to one
    if o['philtrum'] and o['mouth_join'] not in ('crease', 'wingcrease'):
        noses = [p for t, n_, p, c in items if n_ == 'nose']
        if noses:
            nb = noses[-1][-1]
            j = int(np.argmin(np.abs(mouth[:, 0] - nb[0]) + 0.3 * np.hypot(*(mouth - nb).T)))   # straight down, not to a corner
            d = float(np.hypot(*(mouth[j] - nb)))
            if d > 0.3 * G and d < 1.6 * S:              # drawn even when short: the tour must not have to find its own way in
                items.append((4, 'philtrum', resample(np.array([nb, mouth[j]]), st), False))

    # 5. beard: a mass.  Strokes following the jaw (a goatee: the lower lip) inside the beard, mass_sep grooves apart,
    # allowed to merge with the jaw line (a dark, ridged band is what reads as beard), never closer than a groove to the
    # mouth (the smile must stay visible) or to the other features.
    if beard is not None and o['beard_lines']:
        seg = face_line[face_line[:, 1] > L[2, 1]]
        if len(seg) > 10:
            seg = seg[np.argsort(np.arctan2(seg[:, 1] - L[2, 1], seg[:, 0] - cx))]
            nn = normals(seg)
            sgn = np.sign(((np.array([cx, L[14, 1]]) - seg) * nn).sum(1).mean()) or 1.0
            bm = cv2.dilate(beard.astype(np.uint8), disk(0.06 * fw)) > 0
            xs_ = np.nonzero(beard.any(0))[0]
            goatee = len(xs_) and xs_.max() - xs_.min() < 0.7 * fw
            if goatee:
                lo = smooth(L[LIP_OUT_LO], 0.03 * fw, st)
                lc = lo.mean(0); seg = lc + 1.6 * (lo - lc)
                nn = np.tile([0.0, 1.0], (len(seg), 1)); sgn = 1.0
            nb_ = 0
            mg = Gap(); mg.add(resample(mouth, st))
            bgap = Gap()
            for kk in range(8):
                if nb_ >= o['beard_lines']:
                    break
                q = seg + sgn * ((0.35 if goatee else 0.55) + kk * 0.95 * o['mass_sep']) * G * nn
                ins = sample_mask(bm, q) & (fgap.dist(q) > 0.8 * G) & (mg.dist(q) > 0.9 * G) & (bgap.dist(q) > 0.75 * G)
                for a_, b_ in runs(ins):
                    if length(q[a_:b_]) > 1.0 * G:
                        p = smooth(q[a_:b_], 0.03 * fw, st)
                        e_ = 0 if _near_pt(p[0], face_line)[1] <= _near_pt(p[-1], face_line)[1] else 1
                        p = snap_ends(p, [face_line], 1.3 * G, ends=(e_,))       # the beard joins the jaw line it lies along
                        items.append((5, 'beard', p, False)); gap.add(p); bgap.add(p); nb_ += 1

    # 6. joins: every part must be reachable along drawn lines with hops of at most HOP grooves.  Parts still apart are
    #    joined, nearest first, by a short line from one of their END points (it reads as the part running on: a brow
    #    tail to the temple, the outer corner of an eye to its brow, a beard line to the jaw), never across the middle.
    items[:] = _join(items, G, HOPpx, o.get('join_max', 2.0) * G, st, info)

    # ------------------------------------------------ to the unit square (same framing as face_art)
    allp = np.vstack([p for _, _, p, _ in items])
    x0, y0 = allp.min(0); x1, y1 = allp.max(0)
    s = 0.92 / max(x1 - x0, y1 - y0)
    off = np.array([0.5 - s * (x0 + x1) / 2, 0.5 - s * (y0 + y1) / 2])
    out = [(tier, name, p * s + off, closed) for tier, name, p, closed in items]
    info.update(names=[n for _, n, _, _ in out], unit_per_px=s, groove_unit=G * s)
    if debug is not None:
        debug.update(items=out, face=face, hair=hair, L=L, P0=P0, G=G)
    strokes = fa._caps(fa._order(out))
    note = 'groove face: %d strokes, face %.0f mm wide = %.1f grooves%s%s' % (
        len(strokes), info['face_width_mm'], info['face_width_grooves'], ', glasses' if lenses else '', ', beard' if beard is not None else '')
    return strokes, note, info


def _join(items, G, hop, jmax, st, info):
    from scipy.spatial import cKDTree
    parts = [(t, n, np.asarray(p, float), c) for t, n, p, c in items]
    dense = [resample(p, st) for _, _, p, _ in parts]
    conn = [n == 'face' for _, n, _, _ in parts]
    joins = []
    while not all(conn):
        tree = cKDTree(np.vstack([d for d, c in zip(dense, conn) if c]))
        pts = np.vstack([d for d, c in zip(dense, conn) if c])
        best = None
        for i, (d, c) in enumerate(zip(dense, conn)):
            if c:
                continue
            dd, kk = tree.query(d)                           # any point of the part (hops may land anywhere)
            j = int(dd.argmin())
            if dd[j] <= hop:
                best = (0.0, i, None, None)
                break
            for e in (0, len(d) - 1):                          # joins only from an end point
                if best is None or dd[e] < best[0]:
                    best = (float(dd[e]), i, d[e], pts[kk[e]])
        dist, i, a, b = best
        conn[i] = True
        if a is None or dist > jmax:
            continue                                           # within a hop, or too far to join (the tour bridges it)
        seg = resample(np.array([a, b]), st)
        parts.append((4, 'join', seg, False)); dense.append(seg); conn.append(True)
        joins.append(round(dist / G, 2))
    info['joins_grooves'] = joins
    return parts


# ------------------------------------------------------------------ for tools/sand_driver.py (runs in the driver's own python)
VENV_PY = os.path.join(HERE, '..', 'build', 'p2s-venv', 'bin', 'python')      # MediaPipe works there, not in the system python


def zone_kind(zone):
    return 'centre' if zone == 'centre' else ('inner' if str(zone).startswith('inner') else 'outer')


def driver_strokes(app, pid, n, face_v, zone, cache_root, timeout=120):
    """The groove-aware strokes for this person's face photo at the size of `zone`, or None (no photo, no face found,
    converter failed: the caller keeps the app's own strokes).  Downloads the crop through the worker API
    (GET /api/worker/face/{pid}/{n}), converts it in build/p2s-venv, caches by person, photo version and zone kind."""
    import subprocess
    kind = zone_kind(zone)
    d = os.path.join(cache_root, 'groove-faces-v3')            # not v1's cache: same file names, different drawings
    os.makedirs(d, exist_ok=True)
    base = os.path.join(d, 'p%s-n%s-v%s' % (pid, n, face_v))
    out = '%s-%s.json' % (base, kind)
    if not os.path.exists(out):
        if not os.path.exists(base + '.jpg'):
            data = app.raw('/api/worker/face/%d/%d' % (int(pid), int(n)))
            open(base + '.jpg.tmp', 'wb').write(data)
            os.replace(base + '.jpg.tmp', base + '.jpg')
        r = subprocess.run([VENV_PY, os.path.abspath(__file__), base + '.jpg', '--zone', kind, '-o', out + '.tmp'],
                           capture_output=True, text=True, timeout=timeout)
        if not os.path.exists(out + '.tmp'):
            raise RuntimeError('groove face converter failed: %s' % (r.stderr or r.stdout)[-300:])
        os.replace(out + '.tmp', out)
    js = json.load(open(out))
    return js['strokes'] if js.get('ok') and js.get('strokes') else None


STYLE = 'groove-3'


def groove_inputs(inp, cur, app, outroot, log=print):
    """For tools/sand_driver.py: take make_inputs()'s dict and, for a draw turn whose face comes from the app's photo
    strokes, swap in this module's strokes for the zone's size and ask build_turn for face_route=True.  Returns a new dict
    (the key changes, so cached prebuilds of the old style are not reused).  Any failure: the input unchanged."""
    if inp.get('kind') != 'draw' or not inp.get('face_path') or not (cur.get('face_strokes') or []):
        return inp
    fs0 = cur['face_strokes'][0]
    if inp['face_path'] is not fs0 and inp['face_path'] != fs0:          # a posted cartoon face_path: leave it alone
        return inp
    try:
        st = driver_strokes(app, cur['person_id'], 1, cur.get('face_v'), inp['zone'], outroot)
    except Exception as e:
        log('  groove face for person %s failed, keeping the app face: %r' % (cur.get('person_id'), e))
        return inp
    if not st:
        return inp
    import hashlib
    out = dict(inp, face_path=st, face_route=True)
    out['key'] = hashlib.sha1((inp['key'] + STYLE + zone_kind(inp['zone'])).encode()).hexdigest()[:20]
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('photo')
    ap.add_argument('--zone', default='outer', help='inner, outer or centre (sets the drawn size)')
    ap.add_argument('--box-mm', type=float, default=None)
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    r = face_strokes_groove(open(a.photo, 'rb').read(), a.zone, a.box_mm)
    json.dump(r, open(a.out, 'w'))
    print(r['note'])
    return 0 if r['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
