#!/usr/bin/env python3
"""auto_cartoon: one face crop (JPEG) -> a cartoon bust drawn the way the hand-made people in patterns/people are.

    build/p2s-venv/bin/python tools/auto_cartoon.py CROP.jpg -o OUTBASE        ->  OUTBASE.json  OUTBASE.thr  OUTBASE.png
    from auto_cartoon import cartoon_strokes
    cartoon_strokes('crop.jpg')  ->  {"strokes": [[[x, y], ...]], "ok": True, "note": "...", "info": {...}}

Simulation and files only; never contacts a table. Photos stay on this machine (MediaPipe models run locally).

What it draws (the style of patterns/people/make_people.py, whose fill and loop-joining code it reuses as-is):
a bust (neck and shoulders), a face outline, hair as a filled area, a beard as a filled area (with a clear patch
round the smile), eyes or glasses lenses and a smile as clean islands. Every region is filled with lines that
follow its outline inward; all loops are joined into ONE line that enters and leaves through the shoulders at
the bottom rim. No nose, no brows, no exaggeration: sizes come from the person's own landmarks, clamped to the
range of the approved hand-made four.

How
  1. MediaPipe face landmarks (tools/photo2sand.py's detect) + the multiclass selfie segmenter (hair / skin / clothes /
     glasses frames). The photo is levelled on the eyes and scaled into the 600-unit disc canvas of make_people
     (eyes at y=262, chin at y=441: the approved enlarged size).
  2. Face = symmetric outline from the landmark jaw, with the hairline and ears taken from the segmentation.
  3. Hair = segmentation, smoothed to a cartoon shape. Short hair is kept to a thin band close to the head and
     drawn with almost straight lines; long hair falls past the jaw; curly hair gets a little more waviness.
     Bald heads get no hair region.
  4. Beard (colour test on the chin, as in photo2sand): goatee or full, wavy lines, with a skin patch round the smile.
  5. Glasses from the segmenter's "accessories" around each eye, drawn as two clear rounded lenses; otherwise
     two small clear eye ovals. Smile as the hand-made crescent, sized from the measured mouth.
  6. make_people.build fills everything and joins it into one line.
"""
import argparse, json, math, os, sys, time
import numpy as np
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/patterns/people'); sys.path.insert(0, ROOT + '/tools'); sys.path.insert(0, ROOT + '/patterns/dog')
import make_people as mpp                      # noqa: E402
import photo2sand as p2s                       # noqa: E402

F = mpp.F; W = int(600 * F); S = mpp.S
KX = 1.12                                      # the hand-made faces are about this much wider than a real face (width / height)
EYE_Y, CHIN_Y = 262.0, 441.0                   # final canvas (the hand-made heads, drawn 1.2 x larger about (300,318))
CLS = p2s.CLS


def log(*a): print(*a, file=sys.stderr, flush=True)


def rast(poly):
    m = np.zeros((W, W), np.uint8)
    cv2.fillPoly(m, [np.array([[x * F, y * F] for x, y in poly], np.int32)], 255)
    return m > 0


def smooth_mask(m, sigma):
    if sigma <= 0: return m.copy()
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma * F) > 0.5


def dilate(m, r):
    k = int(2 * r * F) | 1
    return cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0


def close_(m, r):
    k = int(2 * r * F) | 1
    return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0


def keep_big(m, min_area):
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    out = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= min_area * F * F: out |= lab == i
    return out


def fill_holes(m, max_area=400):
    inv = (~m).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    out = m.copy()
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a <= max_area * F * F and x > 0 and y > 0 and x + w < W and y + h < W: out |= lab == i
    return out


def rows_extent(m):
    ys = np.nonzero(m.any(1))[0]
    return ys.min() / F, ys.max() / F


def crop_for_face(photo_bgr, pick=0):
    """helper for tests: a square head-and-shoulders crop like the app uploads (pick = n-th face from the left)"""
    faces, _ = p2s.detect(photo_bgr)
    faces.sort(key=lambda f: f[0][1][0]); L = faces[pick][0]
    em = (L[p2s.EYE_A['iris']] + L[p2s.EYE_B['iris']]) / 2; ec = np.linalg.norm(L[p2s.CHIN] - em)
    side = int(3.9 * ec); x0 = int(em[0] - side / 2); y0 = int(em[1] + 0.7 * ec - side / 2)
    pad = cv2.copyMakeBorder(photo_bgr, side, side, side, side, cv2.BORDER_CONSTANT, value=(128, 128, 128))
    c = pad[y0 + side:y0 + 2 * side, x0 + side:x0 + 2 * side]
    return cv2.resize(c, (800, 800), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------------------------------------ analysis
def analyse(bgr):
    H0, W0 = bgr.shape[:2]
    if max(H0, W0) > 1000:
        k = 1000 / max(H0, W0); bgr = cv2.resize(bgr, (int(W0 * k), int(H0 * k)), interpolation=cv2.INTER_AREA)
    H, Wp = bgr.shape[:2]
    faces, conf = p2s.detect(bgr)
    if not faces: return None
    faces.sort(key=lambda f: -np.ptp(f[0][:, 0]) * np.ptp(f[0][:, 1]))
    L, bs = faces[0]
    ea, eb = L[p2s.EYE_A['iris']], L[p2s.EYE_B['iris']]
    cen = (ea + eb) / 2; roll = math.degrees(math.atan2(eb[1] - ea[1], eb[0] - ea[0]))
    ec = float(np.linalg.norm(L[p2s.CHIN] - cen))
    sc = (CHIN_Y - EYE_Y) / ec
    def mk(rr):
        R = cv2.getRotationMatrix2D((float(cen[0]), float(cen[1])), rr, sc); R[:, 2] += (300 - cen[0], EYE_Y - cen[1]); return R
    R = mk(roll)
    def tc(p): p = np.atleast_2d(np.asarray(p, float)); return p @ R[:, :2].T + R[:, 2]
    Lc = tc(L)
    if abs(Lc[p2s.EYE_A['iris']][1] - Lc[p2s.EYE_B['iris']][1]) > 1.5:      # rotation sign guard
        R = mk(-roll); Lc = tc(L)
    AF = R * F
    pad = int(max(H, Wp) * 1.5); stack = []
    for c in range(6):
        m = cv2.copyMakeBorder(conf[c], 0, pad, pad, pad, cv2.BORDER_REPLICATE)
        m = cv2.copyMakeBorder(m, pad, 0, 0, 0, cv2.BORDER_CONSTANT, value=1.0 if c == 0 else 0.0)
        Ap = AF.copy(); Ap[:, 2] = AF[:, 2] - AF[:, :2] @ [pad, pad]
        stack.append(cv2.warpAffine(m, Ap, (W, W), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                    borderValue=1.0 if c == 0 else 0.0))
    stack = np.stack([cv2.GaussianBlur(s, (0, 0), 1.2 * F) for s in stack]); cls = np.argmax(stack, 0)
    ys = np.arange(W)[:, None] / F; xs = np.arange(W)[None, :] / F
    inside = np.hypot(xs - 300, ys - 300) <= 0.985 * S
    return dict(bgr=bgr, L=L, bs=bs, Lc=Lc, R=R, tc=tc, conf=conf, cls=cls, ys=ys, xs=xs, inside=inside)


def jaw_ratio(bgr, L, fh):
    """colour of the skin on the jaw sides (where a full beard grows) against the person's own cheeks; low = beard"""
    H, Wp = bgr.shape[:2]
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    def patch(idx, r=0.03):
        m = np.zeros((H, Wp), np.uint8)
        for i in idx: cv2.circle(m, tuple(int(v) for v in L[i]), max(2, int(fh * r)), 1, -1)
        x = lab[m > 0]; return float(np.median(np.hypot(x[:, 1] - 128, x[:, 2] - 128)))
    return min(patch([58, 172, 136]), patch([288, 397, 365])) / max(patch([50, 280, 205, 425]), 1)


def build_regions(A, hair='auto', beard='auto', glasses='auto'):
    L, Lc, cls, ys, xs, inside = A['L'], A['Lc'], A['cls'], A['ys'], A['xs'], A['inside']
    info = {}
    nose_y = float(Lc[p2s.NOSE_BOT][1]); chin_y = float(Lc[p2s.CHIN][1])
    mouth_y = float(Lc[[61, 291], 1].mean())
    fh = float(np.linalg.norm(L[p2s.CHIN] - L[p2s.FOREHEAD]))
    # -- symmetric jaw/cheek silhouette from the landmark oval
    om = rast(Lc[p2s.OVAL].tolist()); top, bot = rows_extent(om)
    hw = np.zeros(W)
    for r in range(int(top * F), int(bot * F) + 1):
        xx = np.nonzero(om[r])[0]
        if len(xx): hw[r] = (xx.max() - xx.min()) / 2 / F
    k = np.exp(-0.5 * (np.arange(-9, 10) / (3.0 * F)) ** 2); k /= k.sum()
    hw = np.convolve(hw, k, 'same') * KX                          # the oval sits inside the cheek; the hand-made heads are rounder
    hwmax = float(hw.max())
    sym = np.abs(xs - 300) <= hw[:, None]
    skin = np.isin(cls, [CLS['face'], CLS['body'], CLS['acc']])
    hairseg = cls == CLS['hair']
    upper_rows = ys < nose_y + 4
    upper = skin & upper_rows & (np.abs(xs - 300) < 1.16 * hwmax)         # keeps the ears and the real hairline
    face = (sym | upper) & ~(hairseg & upper_rows) & inside
    face = cv2.morphologyEx(face.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(6 * F),) * 2)) > 0
    face = fill_holes(keep_big(face, 2000), 900)
    face = smooth_mask(face, 3.0)
    face = np.where(ys >= nose_y + 4, sym & (face | sym), face)      # below the nose: symmetric like the hand-made heads
    face = smooth_mask(face, 4.5) & inside
    # -- hair
    hm = smooth_mask(close_(hairseg & inside, 6), 4.0) & ~face
    hm_raw = hm.copy()
    face_d = dilate(face, 7)
    n, lab, st, _ = cv2.connectedComponentsWithStats(hm.astype(np.uint8), connectivity=8)
    hm2 = np.zeros_like(hm)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] > 300 * F * F and (face_d & (lab == i)).any(): hm2 |= lab == i
    hm = hm2
    face_a = float(face.sum()) / F / F
    below = float((hm & (ys > mouth_y)).sum()) / F / F / face_a
    hair_area = float(hm.sum()) / F / F / face_a
    crown = float((hm & (ys < float(Lc[p2s.FOREHEAD][1]))).sum()) / F / F / face_a
    coh, _ = p2s.hair_texture(A['bgr'], A['conf'], L, fh, float(L[p2s.CHIN][1]), A['conf'][CLS['hair']])
    if hair == 'auto':
        if crown < 0.05 and hair_area < 0.25: htype = 'bald'
        elif below > 0.12: htype = 'long'
        elif coh < 0.5 and hair_area > 0.6: htype = 'curly'
        else: htype = 'short'
    else: htype = hair
    info['hair'] = dict(type=htype, auto=hair == 'auto', area_vs_face=round(hair_area, 2), below_mouth=round(below, 2),
                        crown=round(crown, 2), coherence=round(float(coh), 2))
    dtf = cv2.distanceTransform((~face).astype(np.uint8), cv2.DIST_L2, 5) / F
    if htype in ('short', 'curly'): hm = (hm | hm[:, ::-1]) & ~face                # the hand-made heads are symmetric
    eyey0 = float((Lc[p2s.EYE_A['iris']][1] + Lc[p2s.EYE_B['iris']][1]) / 2)
    hm &= ~((ys > eyey0 - 36) & (np.abs(xs - 300) < 0.8 * hwmax))      # a fringe stops above the brows, like the hand-made Thomas
    # Short and straight hair is a thin, clean band close to the head (the hand-made Bill): an even offset of the
    # face outline over the crown and temples, kept only where the photo has hair, drawn with almost straight lines.
    # Long hair is that same band plus a calm fall on the side(s) where the photo has hair below the ears.
    ear_y = eyey0 + 12
    top_hair = hm & (ys < ear_y)
    T = float(np.clip(0.8 * np.percentile(dtf[top_hair], 90), 30, 46)) if top_hair.sum() > 100 * F * F else 36.0
    band = dilate(face, T) & ~face & (ys < ear_y) & dilate(hm, 8) & inside
    fall = np.zeros_like(band); sides = []
    if htype == 'long':
        lo = hm_raw & (ys >= ear_y) & (dtf <= 200) & (np.abs(xs - 300) < hwmax + 150) & (ys < 560)
        left, right = lo & (xs < 300), lo & (xs >= 300)
        ext = {nm: (float(np.nonzero(m.any(1))[0].max()) / F if m.any() else 0.0) for nm, m in (('left', left), ('right', right))}
        for nm, m in (('left', left), ('right', right)):
            if ext[nm] >= 0.9 * max(ext.values()) and m.sum() > 300 * F * F: fall |= m; sides.append(nm)   # the side where the hair hangs lowest
    hm = band | fall
    if htype == 'bald': hm[:] = False
    hm = keep_big(smooth_mask(close_(hm, 6), 4.0), 400) & ~face
    info['hair']['band'] = round(T, 1); info['hair']['fall_sides'] = sides
    wavy = {'short': (0.9, 31), 'long': (1.0, 46), 'curly': (1.8, 34), 'bald': None}[htype]
    # -- beard
    bscore = p2s.beard_test(A['bgr'], L, fh)
    b_auto = bscore['chin_colour_ratio'] < 0.72
    jaw = jaw_ratio(A['bgr'], L, fh)
    info_jaw = round(jaw, 3)
    style = (('full' if jaw < 0.35 else 'goatee') if b_auto else 'no') if beard == 'auto' else beard
    lip_top, lip_bot = float(Lc[0][1]), float(Lc[17][1]); mw = float(Lc[291][0] - Lc[61][0])
    moustache = bool(style != 'no' and (style == 'full' or bscore['upper_lip_colour_ratio'] < 0.69))
    beardm = np.zeros((W, W), bool)
    if style != 'no':
        if style == 'full':
            cheek = nose_y - 4 - 55 * (np.abs(xs - 300) / max(hwmax, 1)) ** 2       # sideburns rise toward the ears, across the top lip in the middle
            zone = ys > np.maximum(cheek, float(Lc[p2s.EYE_A['iris']][1]) + 24)
            if not moustache: zone &= ~((ys < lip_top) & (np.abs(xs - 300) < 0.62 * mw))
        else:
            moustache = False                                     # a goatee is the chin tuft only, as on the hand-made Thomas
            zone = (ys > lip_bot + 6) & (np.abs(xs - 300) < 0.36 * mw + 14)
        beardm = dilate(face, 12) & zone & (ys < chin_y + 14)
        beardm = keep_big(smooth_mask(beardm, 3.0), 800)
    info['beard'] = dict(jaw_ratio=info_jaw, style=style, found=bool(b_auto), moustache=moustache, chin_ratio=bscore['chin_colour_ratio'])
    # -- features
    holes = []
    ea, eb = Lc[p2s.EYE_A['iris']], Lc[p2s.EYE_B['iris']]
    eyey = float((ea[1] + eb[1]) / 2); dx = float(np.clip((eb[0] - ea[0]) / 2 * KX, 48, 62))
    wid = float(np.mean([np.linalg.norm(Lc[e['outer']] - Lc[e['inner']]) for e in (p2s.EYE_A, p2s.EYE_B)]))
    acc = A['conf'][CLS['acc']]; lens = []
    for e in (p2s.EYE_A, p2s.EYE_B):
        c, w, _, _ = p2s.eye_info(L, e); poly, _sc = p2s.lens_from_acc(acc, c, w); lens.append(poly)
    g_auto = all(l is not None for l in lens)
    use_g = g_auto if glasses == 'auto' else glasses == 'yes'
    info['glasses'] = dict(found=bool(g_auto), used=bool(use_g))
    if use_g:
        if g_auto:
            boxes = [A['tc'](l) for l in lens]
            lw = float(np.clip(np.mean([np.ptp(b[:, 0]) for b in boxes]), 80, 102)); lh = float(np.clip(np.mean([np.ptp(b[:, 1]) for b in boxes]), 54, 68))
            cy = float(np.mean([(b[:, 1].min() + b[:, 1].max()) / 2 for b in boxes]))
        else: lw, lh, cy = 90.0, 60.0, eyey
        dxl = float(np.clip(0.5 * (lw + 12), 52, 62))
        holes += [mpp.rrect((300 - dxl, cy), lw, lh, 0.28 * lh), mpp.rrect((300 + dxl, cy), lw, lh, 0.28 * lh)]
    else:
        rx = float(np.clip(0.72 * wid / 2, 15, 20)); ry = 0.6 * rx
        holes += [mpp.ellipse((300 - dx, eyey), rx, ry), mpp.ellipse((300 + dx, eyey), rx, ry)]
    # smile: the hand-made crescent, sized from the measured mouth
    inner_gap = float(Lc[14][1] - Lc[13][1])
    sw = float(np.clip(mw * 1.2, 100, 134))
    th = float(np.clip(inner_gap * 1.0 + 12, 19, 32))
    corner_y = float(0.5 * (Lc[61][1] + Lc[291][1]))
    depth = float(lip_bot - corner_y) * 0.9
    curve = float(np.clip(depth - th, 6, 18))
    sm = mpp.smile((300, corner_y + 2), sw, th, curve)
    info['smile'] = dict(width=round(sw, 1), thickness=round(th, 1), curve=round(curve, 1), y=round(corner_y, 1))
    return dict(face=face, hair=hm, beard=beardm, holes=holes, smile=sm, wavy=wavy, htype=htype, style=style,
                mouth=(300.0, corner_y + th * 0.9), sw=sw, info=info, hwmax=hwmax)


def region_list(R):
    body = rast(mpp.body()) & ~dilate(R['face'] | R['beard'], 8)
    if R['hair'].any(): body &= ~dilate(R['hair'], 6)
    regs = [dict(mask=body.astype(np.uint8) * 255, levels=2)]
    face = R['face'] & ~R['beard']
    holes = list(R['holes'])
    if R['beard'].any():
        # skin island round the smile, as in Alex's portrait; the beard lines stop at its edge
        mx, my = R['mouth']
        pm = rast(mpp.ellipse((mx, my), R['sw'] * 0.5 + 16, 31.0)) & R['face']
        face = face & ~pm
        regs.append(dict(mask=face.astype(np.uint8) * 255, holes=holes))
        regs.append(dict(mask=(R['beard'] & ~pm).astype(np.uint8) * 255, wavy=(4.2, 20), pitch=0.9))
        regs.append(dict(mask=pm.astype(np.uint8) * 255, holes=[R['smile']]))
    else:
        regs.append(dict(mask=face.astype(np.uint8) * 255, holes=holes + [R['smile']]))
    if R['hair'].any():
        regs.append(dict(mask=R['hair'].astype(np.uint8) * 255, wavy=R['wavy'], pitch=0.8))
    return regs


def debug_image(R, regs):
    d = np.full((W, W, 3), 245, np.uint8)
    for rg in regs:
        pass
    d[regs[0]['mask'] > 0] = (150, 150, 150)
    for rg in regs[1:]: d[rg['mask'] > 0] = (200, 170, 140)
    d[R['hair'] > 0] = (60, 90, 200)
    d[R['beard'] > 0] = (170, 60, 60)
    for h in R['holes'] + [R['smile']]: cv2.fillPoly(d, [np.array([[x * F, y * F] for x, y in h], np.int32)], (255, 255, 255))
    return cv2.resize(d, (600, 600), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------------------------------------ public
def cartoon(bgr, hair='auto', beard='auto', glasses='auto', debug=False):
    t0 = time.time()
    A = analyse(bgr)
    if A is None: return None
    R = build_regions(A, hair, beard, glasses)
    regs = region_list(R)
    P, nloops = mpp.build(dict(regions=regs))
    info = R['info']; info['loops'] = nloops; info['seconds'] = round(time.time() - t0, 2)
    out = dict(P=P, info=info)
    if debug: out['debug'] = debug_image(R, regs)
    return out


def to_strokes(P, max_points=None):
    pts = [[round(x / 600.0, 5), round(y / 600.0, 5)] for x, y in P]
    if max_points and len(pts) > max_points:                         # thin by even steps, keep both ends
        idx = np.unique(np.linspace(0, len(pts) - 1, max_points).astype(int)); pts = [pts[i] for i in idx]
    return [pts]


def cartoon_strokes(path_or_bytes, **kw):
    """crop path (or JPEG bytes) -> {"strokes": [[[x, y], ...]], "ok": bool, "note": str, "info": {...}}; y down, 0..1"""
    if isinstance(path_or_bytes, (bytes, bytearray)): bgr = cv2.imdecode(np.frombuffer(path_or_bytes, np.uint8), cv2.IMREAD_COLOR)
    else: bgr = cv2.imread(path_or_bytes)
    if bgr is None: return dict(strokes=[], ok=False, note='cannot read the image')
    r = cartoon(bgr, **kw)
    if r is None: return dict(strokes=[], ok=False, note='no human face found')
    return dict(strokes=to_strokes(r['P']), ok=True, note='cartoon bust', info=r['info'])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('crop'); ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--hair', default='auto', choices=['auto', 'short', 'long', 'curly', 'bald'])
    ap.add_argument('--beard', default='auto', choices=['auto', 'no', 'goatee', 'full'])
    ap.add_argument('--glasses', default='auto', choices=['auto', 'yes', 'no'])
    ap.add_argument('--no-preview', action='store_true')
    a = ap.parse_args()
    bgr = cv2.imread(a.crop)
    if bgr is None: sys.exit('cannot read %s' % a.crop)
    r = cartoon(bgr, a.hair, a.beard, a.glasses, debug=True)
    if r is None: log('auto_cartoon: no human face found'); sys.exit(2)
    P = r['P']
    json.dump(dict(strokes=to_strokes(P), ok=True, note='cartoon bust', info=r['info']), open(a.out + '.json', 'w'))
    n = mpp.to_thr(P, a.out + '.thr')
    cv2.imwrite(a.out + '_debug.png', r['debug'])
    if not a.no_preview:
        import sandsim, thrcommon as tc
        sandsim.render(tc.read_thr(a.out + '.thr'), 700).save(a.out + '.png')
    log('auto_cartoon: %s  %d points  %s' % (os.path.basename(a.crop), n, json.dumps(r['info'])))


if __name__ == '__main__':
    main()
