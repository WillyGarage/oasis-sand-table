#!/usr/bin/env python3
"""photo2sand: turn a photo of a person or group into a sand portrait in the approved style of patterns/people/make_people.py.

    build/p2s-venv/bin/python tools/photo2sand.py PHOTO.jpg [--group] -o OUT     ->  OUT.thr  OUT_preview.jpg  OUT_debug.jpg  OUT.json

Everything runs on this machine. Photos are never sent anywhere.
  * MediaPipe Face Landmarker (478 face points + 52 expression scores) finds the face, eyes, lips, jaw and smile.
  * MediaPipe multiclass selfie segmenter labels every pixel: background, hair, body skin, face skin, clothes,
    accessories (glasses frames and earrings come out as "accessories").
  Models live in ~/.cache/photo2sand (downloaded once from storage.googleapis.com/mediapipe-models).
  Environment: `uv venv build/p2s-venv --python 3.10 && VIRTUAL_ENV=build/p2s-venv uv pip install mediapipe==0.10.21 scipy pillow`
  (mediapipe 1.x needs the system libGLESv2, which this WSL does not have; 0.10.21 does not).

Method
  1. Landmarks -> roll angle (line through the two irises), chin, jaw line, eye centres and widths, outer lip outline,
     smile score. One similarity transform (rotate level, scale, shift) maps the photo into the 600 x 600 disc canvas
     make_people uses (centre 300,300, radius 290), already at the bigger drawing size: top of the head at
     y = +0.88 of the radius, chin at -0.72 (the proportions of the approved enlarged portraits), face centred.
  2. The six segmentation confidence maps are warped into the canvas, smoothed by about half a groove width and
     turned into regions: face (face skin + bald scalp above the jaw line), hair, body (neck, shoulders, clothes),
     beard (pixels in the lower face whose colour is far from the person's own cheek/forehead skin), earring.
  3. Clear islands follow the measured eyelids and outer lip. Glasses, eyebrows and the curve across the tip of
     the nose follow their measured width, position and tilt. Inside a beard
     the mouth gets a clear patch one line wide, as in Alex's portrait, so the smile stays visible.
  4. make_people.build fills every region with lines following its outline inward (pitch 0.059 of the radius =
     0.047 before the 1.25 enlargement) and joins all loops into one line by a tree walk with one-line-spacing hops;
     make_people.to_thr writes the file. In and out at the bottom rim, through the shoulders.
  5. Checks on the result, the honest sand preview (tools/sandsim.py real=True, lightened by tools/brighten.py),
     a debug overlay on the photo and a JSON of everything measured.

Overrides for things a photo cannot settle: --glasses yes|no|auto, --beard auto|no|goatee|full, --hair auto|short|long|curly|bald,
--smile yes|no|auto (only changes the mouth when no smile was measured), --end auto|rim|earring-left|earring-right.
With --group, the segmentation preserves the people's positions and head sizes, including turned heads with no face landmarks.
Exit code 2 = no single face found (debug image and measurement JSON only).
"""
import argparse, json, math, os, sys, time
import numpy as np
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/patterns/people'); sys.path.insert(0, ROOT + '/tools')
import make_people as mpp                     # noqa: E402  (fill + tree walk + .thr writer, shared with the approved four)

MODELS = os.path.expanduser('~/.cache/photo2sand')
F = mpp.F; W = int(600 * F); S = mpp.S
PITCH_FINAL = mpp.PITCH * 1.25                # 0.059 of the radius
UNIT_PITCH = PITCH_FINAL * S                  # canvas units between lines (~17)
GROOVE_U = 0.042 * S                          # real groove width in canvas units (~12)
TOP_Y, CHIN_Y = 0.88, -0.72                   # where the head top and the chin land (fractions of the radius, y up)
DISC_R = 0.985

# MediaPipe face mesh indices
OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
        150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LIPS_OUT = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
EYE_A = dict(outer=33, inner=133, top=159, bot=145, iris=468)      # the eye on the image's left
EYE_B = dict(outer=263, inner=362, top=386, bot=374, iris=473)
CHIN, NOSE_TIP, NOSE_BOT, BROW_MID, FOREHEAD = 152, 1, 2, 168, 10
CLS = dict(bg=0, hair=1, body=2, face=3, clothes=4, acc=5)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------------------------- detection
def detect(bgr, group=False):
    import mediapipe as mp
    from mediapipe.tasks.python import vision, BaseOptions
    fl = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODELS + '/face_landmarker.task'),
        output_face_blendshapes=True, num_faces=12, min_face_detection_confidence=0.5))
    sg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=MODELS + '/selfie_multiclass_256x256.tflite'),
        output_category_mask=False, output_confidence_masks=True))
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    im = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    H, Wp = bgr.shape[:2]
    faces = []

    def add_faces(result, width, height, x0=0, y0=0):
        for k, lm in enumerate(result.face_landmarks):
            pts = np.array([[x0 + pt.x * width, y0 + pt.y * height] for pt in lm])
            if any(np.linalg.norm(old[NOSE_TIP] - pts[NOSE_TIP]) < .38 * np.ptp(pts[OVAL, 0])
                   for old, _ in faces):
                continue
            bs = {c.category_name: c.score for c in result.face_blendshapes[k]} if result.face_blendshapes else {}
            faces.append((pts, bs))

    try:
        add_faces(fl.detect(im), Wp, H)
        if group:
            # The landmark model sees large nearby faces. Look for smaller heads at several
            # scales, then re-run the same model on each crop to recover precise coordinates.
            finder = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            for x, y, w, h in finder.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=4):
                if any(x < L[NOSE_TIP, 0] < x+w and y < L[NOSE_TIP, 1] < y+h for L, _ in faces):
                    continue
                x0, y0 = max(0, x-w//2), max(0, y-h//2)
                x1, y1 = min(Wp, x+w+w//2), min(H, y+h+h//2)
                crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
                closeup = mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)
                add_faces(fl.detect(closeup), x1-x0, y1-y0, x0, y0)
        seg = sg.segment(im)
        conf = np.stack([m.numpy_view().astype(np.float32).reshape(H, Wp) for m in seg.confidence_masks])
    finally:
        fl.close()
        sg.close()
    return faces, conf


# ----------------------------------------------------------------------------------------------- measuring
def eye_info(L, e):
    c = L[e['iris']]; w = np.linalg.norm(L[e['outer']] - L[e['inner']])
    h = np.linalg.norm(L[e['top']] - L[e['bot']])
    ang = math.degrees(math.atan2(L[e['outer']][1] - L[e['inner']][1], L[e['outer']][0] - L[e['inner']][0]))
    return c, w, h, ang


def lens_from_acc(acc, eye_c, eye_w):
    """Filled outline of one glasses lens from the accessory mask around one eye (photo px), or None."""
    H, Wp = acc.shape; r = int(1.5 * eye_w)
    x0, y0 = max(0, int(eye_c[0] - r)), max(0, int(eye_c[1] - r)); x1, y1 = min(Wp, int(eye_c[0] + r)), min(H, int(eye_c[1] + r))
    win = (acc[y0:y1, x0:x1] > 0.5).astype(np.uint8)
    if win.sum() < 0.6 * eye_w:                      # too little frame to be glasses
        return None, float(win.sum()) / max(1.0, eye_w * eye_w)
    k = max(3, int(eye_w * 0.08) | 1)
    win = cv2.morphologyEx(win, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    # the lens is the hole the frame encloses round the eye: flood the background from the window border
    inv = (1 - win).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv)
    ex, ey = int(eye_c[0] - x0), int(eye_c[1] - y0)
    if not (0 <= ey < lab.shape[0] and 0 <= ex < lab.shape[1]):
        return None, 0.0
    li = lab[ey, ex]
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    if li == 0 or li in border:                      # frame does not close round the eye: use the frame's box
        ys, xs = np.nonzero(win)
        sel = (np.abs(xs - ex) < 1.2 * eye_w) & (np.abs(ys - ey) < 0.9 * eye_w)
        if sel.sum() < 0.6 * eye_w: return None, float(win.sum()) / (eye_w * eye_w)
        bx0, bx1, by0, by1 = xs[sel].min(), xs[sel].max(), ys[sel].min(), ys[sel].max()
        poly = mpp.rrect(((bx0 + bx1) / 2 + x0, (by0 + by1) / 2 + y0), bx1 - bx0, by1 - by0, min(bx1 - bx0, by1 - by0) * 0.25)
        return np.array(poly), float(win.sum()) / (eye_w * eye_w)
    lens = ((lab == li) | win.astype(bool)).astype(np.uint8)  # lens plus its own frame
    lens = cv2.morphologyEx(lens, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n2, lab2 = cv2.connectedComponents(lens)
    lens = (lab2 == lab2[ey, ex]).astype(np.uint8)
    cs, _ = cv2.findContours(lens, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)[:, 0, :].astype(float)
    # keep the lens from swallowing the temple arm: clip to 1.25 eye widths sideways of the eye
    c[:, 0] = np.clip(c[:, 0], ex - 1.25 * eye_w, ex + 1.25 * eye_w)
    hull = cv2.convexHull(c.astype(np.float32))[:, 0, :]
    return hull + [x0, y0], float(win.sum()) / (eye_w * eye_w)


def beard_test(bgr, L, fh):
    """Is there a beard? Compare small patches on the chin and upper lip with the person's own cheeks.
    Hair of any colour (grey, black, brown) is much less colourful than skin under the same light; shadows and
    stubble keep most of the skin's colour. Measured on 8 test photos: chin ratio 0.53 / 0.63 with a beard, >= 0.82 without."""
    H, Wp = bgr.shape[:2]
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    def patch(idx, r=0.03):
        m = np.zeros((H, Wp), np.uint8)
        for i in idx: cv2.circle(m, tuple(int(v) for v in L[i]), max(2, int(fh * r)), 1, -1)
        x = lab[m > 0]; return float(np.median(x[:, 0])), float(np.median(np.hypot(x[:, 1] - 128, x[:, 2] - 128)))
    ck = patch([50, 280, 205, 425]); ch = patch([199, 175, 428, 208]); mo = patch([164, 167, 393])
    return dict(chin_colour_ratio=round(ch[1] / max(ck[1], 1), 3), upper_lip_colour_ratio=round(mo[1] / max(ck[1], 1), 3),
                chin_lightness_diff=round(ch[0] - ck[0], 1))


def hair_texture(bgr, conf, L, fh, chin_y_lvl, hair_lvl):
    """Curl and length measured in the photo. Curl: how consistently the hair's fine edges point one way
    (structure-tensor coherence; straight or smooth hair > 0.6, curls < 0.5). Length: hair below the chin."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), max(0.7, fh * 0.004))
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1); w = fh * 0.03
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), w); jyy = cv2.GaussianBlur(gy * gy, (0, 0), w); jxy = cv2.GaussianBlur(gx * gy, (0, 0), w)
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
    hm = cv2.erode((conf[CLS['hair']] > 0.5).astype(np.uint8), np.ones((int(fh * 0.04) | 1,) * 2, np.uint8)) > 0
    coherence = float(np.median(coh[hm])) if hm.sum() > 50 else 1.0
    hl = cv2.erode((hair_lvl > 0.5).astype(np.uint8), np.ones((int(fh * 0.04) | 1,) * 2, np.uint8))
    below = float(hl[int(max(0, chin_y_lvl)):].sum()) / (fh * fh * 0.8)
    return coherence, below


# ----------------------------------------------------------------------------------------------- the engine
def run(photo, out, glasses='auto', beard='auto', hair='auto', smile='auto', end='auto', group=False):
    t0 = time.time()
    bgr = cv2.imread(photo)
    if bgr is None:
        raise SystemExit('cannot read %s' % photo)
    H0, W0 = bgr.shape[:2]
    if max(H0, W0) > 1600:                            # landmarks do not need more; keeps runtime flat
        k = 1600 / max(H0, W0); bgr = cv2.resize(bgr, (int(W0 * k), int(H0 * k)), interpolation=cv2.INTER_AREA)
    H, Wp = bgr.shape[:2]
    faces, conf = detect(bgr, group=group)
    if group:
        import group_portrait
        try:
            return group_portrait.run(photo, out, bgr, faces, conf, t0)
        except ValueError as e:
            log(str(e))
            return 2
    meas = dict(photo=os.path.basename(photo), photo_px=[Wp, H])
    if not faces:
        dbg = bgr.copy(); cv2.putText(dbg, 'no human face found', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        cv2.imwrite(out + '_debug.jpg', dbg)
        meas['error'] = 'no human face found'
        json.dump(meas, open(out + '.json', 'w'), indent=1)
        log('photo2sand: no human face found in %s (the face model only knows people). Nothing drawn.' % photo)
        return 2
    # main face = the biggest
    faces.sort(key=lambda f: -np.ptp(f[0][:, 0]) * np.ptp(f[0][:, 1]))
    L, bs = faces[0]
    meas['faces_found'] = len(faces)
    ea, eb = eye_info(L, EYE_A), eye_info(L, EYE_B)
    roll = math.degrees(math.atan2(eb[0][1] - ea[0][1], eb[0][0] - ea[0][0]))
    fh = float(np.linalg.norm(L[CHIN] - (ea[0] + eb[0]) / 2)) * 1.9   # face height, hairline to chin, roughly
    meas['roll_deg'] = round(roll, 1)

    # -- roll-normalise and measure in the levelled photo frame
    cen = (ea[0] + eb[0]) / 2
    R = cv2.getRotationMatrix2D(tuple(cen), roll, 1.0)                      # rotate so the eyes are level
    def rot(p): p = np.atleast_2d(p); return p @ R[:, :2].T + R[:, 2]
    Lr = rot(L)
    big = 3 * max(H, Wp)
    def warp_lvl(img, interp=cv2.INTER_LINEAR, border=cv2.BORDER_REPLICATE):
        return cv2.warpAffine(img, R, (Wp, H), flags=interp, borderMode=border)
    head_conf = conf[CLS['hair']] + conf[CLS['face']] + conf[CLS['body']] * 0 + conf[CLS['acc']]
    head_r = warp_lvl(head_conf, border=cv2.BORDER_CONSTANT)
    hair_r = warp_lvl(conf[CLS['hair']], border=cv2.BORDER_CONSTANT)
    face_r = warp_lvl(conf[CLS['face']] + conf[CLS['body']], border=cv2.BORDER_CONSTANT)
    chin_y = Lr[CHIN][1]; oval = Lr[OVAL]
    fx0, fx1 = oval[:, 0].min(), oval[:, 0].max(); fw = fx1 - fx0
    # head top: highest row where hair/face/scalp is present within the face's column span
    colband = slice(int(max(0, fx0 + 0.15 * fw)), int(min(Wp, fx1 - 0.15 * fw)))
    rows = np.nonzero((head_r[:, colband] + face_r[:, colband] > 0.5).any(1))[0]
    rows = rows[rows < chin_y]
    top_y = float(rows.min()) if len(rows) else float(Lr[FOREHEAD][1] - 0.15 * fh)
    cut_top = top_y <= 2
    face_top = float(Lr[FOREHEAD][1])
    meas['head_cut_off_at_top'] = bool(cut_top)

    # -- mapping levelled photo -> canvas (600 units, y down), in final bigger size
    y_top_c, y_chin_c = 300 - TOP_Y * S, 300 - CHIN_Y * S
    sc = (y_chin_c - y_top_c) / (chin_y - top_y)
    head_cx = (fx0 + fx1) / 2
    tx, ty = 300 - sc * head_cx, y_top_c - sc * top_y
    A_lvl = np.array([[sc, 0, tx], [0, sc, ty]])                           # levelled photo -> canvas units
    A = np.vstack([A_lvl, [0, 0, 1]]) @ np.vstack([R, [0, 0, 1]])           # photo -> canvas units
    A = A[:2]; AF = A * F                                                   # photo -> canvas mask px
    def tc(p): p = np.atleast_2d(np.asarray(p, float)); return p @ A[:, :2].T + A[:, 2]
    Lc = tc(L)
    meas['scale_canvas_units_per_photo_px'] = round(sc, 4)

    # -- segmentation into the canvas: pad bottom and sides by repeating the edge (shoulders continue), top = background
    pad = int(max(H, Wp) * 1.5)
    stack = []
    for c in range(6):
        m = cv2.copyMakeBorder(conf[c], 0, pad, pad, pad, cv2.BORDER_REPLICATE)
        m = cv2.copyMakeBorder(m, pad, 0, 0, 0, cv2.BORDER_CONSTANT, value=1.0 if c == 0 else 0.0)
        Ap = AF.copy(); Ap[:, 2] = AF[:, 2] - AF[:, :2] @ [pad, pad]
        stack.append(cv2.warpAffine(m, Ap, (W, W), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                    borderValue=1.0 if c == 0 else 0.0))
    stack = np.stack(stack)
    sig = 0.22 * GROOVE_U * F
    stack = np.stack([cv2.GaussianBlur(s, (0, 0), sig) for s in stack])
    cls = np.argmax(stack, 0)
    yy, xx = np.mgrid[0:W, 0:W]
    inside = np.hypot(xx / F - 300, yy / F - 300) <= DISC_R * S
    # jaw line in canvas: lower half of the face oval, extended flat beyond its ends
    ovc = Lc[OVAL]; low = ovc[ovc[:, 1] > Lc[NOSE_TIP][1]]
    low = low[np.argsort(low[:, 0])]
    jaw_y = np.interp(xx[0] / F, low[:, 0], low[:, 1])                       # per column, canvas units
    above_jaw = (yy / F) < (jaw_y[None, :] + 0.02 * S)
    face = ((cls == CLS['face']) | (cls == CLS['body']) | (cls == CLS['acc'])) & above_jaw
    face_w_c = float(np.ptp(ovc[:, 0])); face_h_c = float(Lc[CHIN][1] - Lc[FOREHEAD][1])
    hairm = (cls == CLS['hair'])
    body = ((cls == CLS['body']) & ~above_jaw) | (cls == CLS['clothes']) | ((cls == CLS['acc']) & ~above_jaw)

    # -- beard: a colour test on the chin decides; the shape comes from the landmarks (goatee or full)
    bscore = beard_test(bgr, L, fh)
    beard_auto = bscore['chin_colour_ratio'] < 0.72
    style = ('goatee' if beard_auto else 'no') if beard == 'auto' else beard
    has_beard = style in ('goatee', 'full')
    meas['beard'] = dict(found=bool(beard_auto), used=style, moustache=bool(has_beard and (style == 'full' or bscore['upper_lip_colour_ratio'] < 0.69)), **bscore)
    beardm = np.zeros_like(face)
    if has_beard:
        bz = np.zeros((W, W), np.uint8)
        oc = ovc.mean(0); low_oval = oc + (ovc - oc) * [1.0, 1.05]               # a beard reaches a little below the jaw outline
        cv2.fillPoly(bz, [(low_oval * F).astype(np.int32)], 1)
        nose_y, lip_top, lip_bot = Lc[NOSE_BOT][1], Lc[0][1], Lc[17][1]
        mx0, mx1 = Lc[61][0], Lc[291][0]; mwid = mx1 - mx0
        if style == 'full':                                                  # from the sideburns, under the cheekbones
            ys = (yy / F)
            cheek_line = Lc[NOSE_TIP][1] + (np.abs(xx / F - Lc[NOSE_TIP][0]) / (0.5 * face_w_c)) * -0.18 * face_h_c
            bz[ys < np.maximum(cheek_line, Lc[EYE_A['iris']][1] + 0.12 * face_h_c)] = 0
            bz[(ys < lip_top) & (np.abs(xx / F - Lc[NOSE_TIP][0]) < 0.6 * mwid) & (ys < nose_y + 0.25 * (lip_top - nose_y))] = 0
        else:                                                                # goatee: round the mouth and on the chin
            top = nose_y + 0.3 * (lip_top - nose_y) if meas['beard']['moustache'] else lip_bot - 0.1 * (lip_bot - lip_top)
            bz[: int(top * F)] = 0
            xs = xx[0] / F
            bz[:, (xs < mx0 - 0.18 * mwid) | (xs > mx1 + 0.18 * mwid)] = 0
        beardm = (bz > 0) & (face | hairm)

    # -- hair type
    hair_px = hairm & inside
    hair_above = float(Lc[FOREHEAD][1] - y_top_c) / face_h_c                   # hair+scalp above the forehead point
    colmask = np.zeros(W, bool); colmask[int((Lc[FOREHEAD][0] - 0.25 * face_w_c) * F):int((Lc[FOREHEAD][0] + 0.25 * face_w_c) * F)] = True
    hair_on_top = float(hair_px[:, colmask][: int(Lc[FOREHEAD][1] * F)].sum()) / (colmask.sum() * F) / face_h_c  # hair thickness over the crown
    below = hair_px[int(Lc[CHIN][1] * F):].sum() / (F * F) / (face_w_c * face_h_c)
    eye_row = int(Lc[[EYE_A['iris'], EYE_B['iris']], 1].mean() * F)
    hx = np.nonzero(hair_px[eye_row - 4:eye_row + 4].any(0) | face[eye_row - 4:eye_row + 4].any(0))[0]
    width_eye = (np.ptp(hx) / F / face_w_c) if len(hx) else 1.0
    # outline roughness of the hair (curls make a ragged outline): perimeter vs perimeter of a smoothed copy
    hm8 = hair_px.astype(np.uint8)
    rough = 0.0
    if hm8.sum() > 200:
        c1, _ = cv2.findContours(hm8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        sm = cv2.GaussianBlur(hm8.astype(np.float32), (0, 0), 6 * F) > 0.5
        c2, _ = cv2.findContours(sm.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        p1 = sum(cv2.arcLength(c, True) for c in c1); p2 = sum(cv2.arcLength(c, True) for c in c2) or 1
        rough = p1 / p2
    hair_area = hair_px.sum() / (F * F) / (face_w_c * face_h_c)
    coherence, below_ph = hair_texture(bgr, conf, L, fh, chin_y, hair_r)
    if hair_on_top < 0.05 and hair_area < 0.35: htype = 'bald'
    elif coherence < 0.52: htype = 'curly'
    elif below_ph > 0.02: htype = 'long'
    else: htype = 'short'
    meas['hair'] = dict(type_found=htype, type_used=hair if hair != 'auto' else htype, thickness_over_crown=round(hair_on_top, 3),
                        area_vs_face=round(float(hair_area), 3), below_chin_in_photo_vs_face=round(below_ph, 3),
                        strand_coherence=round(coherence, 3), width_at_eyes_vs_face=round(float(width_eye), 3),
                        outline_roughness=round(rough, 3))
    htype = hair if hair != 'auto' else htype

    # -- features (canvas units)
    holes_face = []; feat = {}
    eyes = []
    for e in (EYE_A, EYE_B):
        c, w, h, ang = eye_info(Lc, e)
        rx = 0.72 * w / 2; ry = 0.6 * rx
        eyes.append(dict(c=c, rx=rx, ry=ry, ang=ang, open_ratio=h / w))
    feat['eyes'] = [dict(centre=[round(v, 1) for v in e['c']], rx=round(e['rx'], 1), ry=round(e['ry'], 1),
                         open_ratio=round(e['open_ratio'], 2)) for e in eyes]
    # glasses
    acc = conf[CLS['acc']]
    lens_ph, frame_scores = [], []
    for e in (EYE_A, EYE_B):
        c, w, _, _ = eye_info(L, e); poly, sc_ = lens_from_acc(acc, c, w); lens_ph.append(poly); frame_scores.append(round(sc_, 3))
    g_auto = all(p is not None for p in lens_ph)
    use_glasses = g_auto if glasses == 'auto' else glasses == 'yes'
    lenses = []
    if use_glasses:
        for k, (e, poly) in enumerate(zip(eyes, lens_ph)):
            if poly is not None and g_auto:
                lenses.append(tc(poly))
            else:                                                            # forced: a rounded rectangle round the eye
                w = e['rx'] / 0.72 * 2
                lenses.append(np.array(mpp.rrect(tuple(e['c']), 1.55 * w, 1.05 * w, 0.25 * w)))
    feat['glasses'] = dict(found=bool(g_auto), used=bool(use_glasses), frame_pixels_vs_eye=frame_scores,
                           lens_boxes=[[round(float(v), 1) for v in (l[:, 0].min(), l[:, 1].min(), np.ptp(l[:, 0]), np.ptp(l[:, 1]))] for l in lenses])
    if use_glasses:
        holes_face += [l.tolist() for l in lenses]
    else:
        lids = [[33, 160, 159, 158, 133, 153, 145, 144], [263, 387, 386, 385, 362, 380, 374, 373]]
        for indices in lids:
            outline = Lc[indices].copy()
            middle = outline.mean(axis=0)
            outline[:, 0] = middle[0] + 0.86 * (outline[:, 0] - middle[0])
            depth = max(np.ptp(outline[:, 1]), 1.0)
            outline[:, 1] = middle[1] + max(1.0, 1.1 * GROOVE_U / depth) * (outline[:, 1] - middle[1])
            holes_face.append(mpp.spline(outline.tolist(), step=2.5, closed=True))
    # Use each actual eyebrow arch when there is room between it and the eye or frame.
    brow_count = 0
    for side, indices in enumerate([[70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
                                    [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]]):
        brow = Lc[indices].copy()
        eye_top = min(p[1] for p in holes_face[side])
        if eye_top - brow[:, 1].max() >= 0.65 * GROOVE_U:
            holes_face.append(mpp.spline(brow.tolist(), step=2.5, closed=True))
            brow_count += 1
    # A single shallow curve from wing to wing retains the nose width and the offset of a turned head.
    # Drawing a full nose outline at this scale overwhelms the other features.
    nose = Lc[[98, 97, 2, 326, 327]].copy()
    nose_hole = np.vstack((nose, nose[::-1] + [0.0, 0.65 * GROOVE_U]))
    holes_face.append(mpp.spline(nose_hole.tolist(), step=2.5, closed=True))
    feat['brows_drawn'] = brow_count
    feat['nose_width_vs_face'] = round(float(np.ptp(nose[:, 0]) / face_w_c), 3)
    # mouth
    sm_score = (bs.get('mouthSmileLeft', 0) + bs.get('mouthSmileRight', 0)) / 2
    smiling = sm_score > 0.4 if smile == 'auto' else smile == 'yes'
    lips = Lc[LIPS_OUT].copy(); mc = lips.mean(0)
    mw = float(np.ptp(lips[:, 0])); mh = float(np.ptp(lips[:, 1]))
    min_h = 1.6 * GROOVE_U
    if mh < min_h: lips[:, 1] = mc[1] + (lips[:, 1] - mc[1]) * (min_h / max(mh, 1e-3))
    if smile == 'yes' and sm_score <= 0.4:
        # A hand-requested smile that is absent from the photo uses the approved crescent.
        cy = float(Lc[[61, 291], 1].mean())
        cx = float(Lc[[61, 291], 0].mean())
        curve = 0.25 * GROOVE_U / 0.45
        mouth = np.array(mpp.spline(mpp.smile((cx, cy), mw, 2.6 * GROOVE_U - curve, curve),
                                    step=3.0, closed=True))
    else:
        mouth = np.array(mpp.spline([tuple(p) for p in lips], step=3.0, closed=True))
    corner_lift = float(((Lc[61][1] + Lc[291][1]) / 2 - Lc[0][1]))           # >0: corners lower than the lip centre
    feat['mouth'] = dict(centre=[round(v, 1) for v in mc], width=round(mw, 1), height=round(mh, 1),
                         width_vs_face=round(mw / face_w_c, 3), smile_score=round(sm_score, 2), smiling=bool(smiling),
                         corners_below_upper_lip=round(corner_lift, 1))
    patch = None
    if has_beard:
        patch = np.array(mpp.ellipse(tuple(mc), mw / 2 + 0.9 * UNIT_PITCH, max(mh, min_h) / 2 + 0.9 * UNIT_PITCH))
    # earring
    acc_c = cv2.warpAffine(acc, AF, (W, W), flags=cv2.INTER_LINEAR) > 0.5
    earrings = []
    n, lab, st, cen_ = cv2.connectedComponentsWithStats(acc_c.astype(np.uint8))
    for i in range(1, n):
        x, y = cen_[i] / F; a = st[i, cv2.CC_STAT_AREA] / (F * F)
        side = 'left' if x < Lc[NOSE_TIP][0] else 'right'
        if Lc[NOSE_TIP][1] < y < Lc[CHIN][1] + 0.35 * face_h_c and abs(x - Lc[NOSE_TIP][0]) > 0.42 * face_w_c and a < 0.02 * face_w_c * face_h_c:
            if cv2.pointPolygonTest(ovc.astype(np.float32), (float(x), float(y)), False) < 0:
                earrings.append(dict(side=side, centre=[round(float(x), 1), round(float(y), 1)], area=round(float(a), 1)))
    feat['earrings'] = earrings
    # ears: face skin reaching beyond the face outline at eye-to-nose height
    band = slice(int(Lc[EYE_A['iris']][1] * F), int(Lc[NOSE_BOT][1] * F))
    fx = np.nonzero(face[band].any(0))[0]
    ear_l = (ovc[:, 0].min() - fx.min() / F) / face_w_c if len(fx) else 0
    ear_r = (fx.max() / F - ovc[:, 0].max()) / face_w_c if len(fx) else 0
    feat['ears_visible'] = dict(left=bool(ear_l > 0.04), right=bool(ear_r > 0.04), left_out=round(float(ear_l), 3), right_out=round(float(ear_r), 3))

    # -- clean regions
    def clean(m, open_u=0.45, min_area_u=None, keep_touching=None):
        m = (m & inside).astype(np.uint8)
        k = int(open_u * GROOVE_U * F) | 1
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m)
        keep = np.zeros_like(m)
        min_a = (min_area_u if min_area_u is not None else (1.5 * UNIT_PITCH) ** 2) * F * F
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] < min_a: continue
            comp = lab == i
            if keep_touching is not None and not (cv2.dilate(comp.astype(np.uint8), np.ones((9, 9), np.uint8)) & keep_touching).any(): continue
            keep[comp] = 1
        return keep.astype(bool)
    facem = face & ~beardm
    facem = clean(facem)
    # the face is the component under the eyes
    n, lab = cv2.connectedComponents(facem.astype(np.uint8))
    ci = lab[int(Lc[BROW_MID][1] * F), int(Lc[BROW_MID][0] * F)]
    if ci: facem = lab == ci
    beardm = clean(beardm & ~facem, keep_touching=facem.astype(np.uint8)) if has_beard else beardm
    headm = (facem | beardm).astype(np.uint8)
    hairm = clean(hairm & ~facem & ~beardm, min_area_u=(2.0 * UNIT_PITCH) ** 2, keep_touching=headm)
    if htype == 'bald':
        hairm &= (yy / F) > Lc[FOREHEAD][1]                                # a bald head: only side hair, no cap
        hairm = clean(hairm, min_area_u=(2.0 * UNIT_PITCH) ** 2)
    # approved style: below the chin only the neck and the top of the shoulders, nothing beside the head
    body &= (yy / F) > Lc[CHIN][1] + 0.01 * S
    body &= np.abs(xx / F - Lc[CHIN][0]) < 0.42 * face_w_c                 # neck and collar, a stub as in the approved ones
    body = clean(body & ~facem & ~hairm & ~beardm, open_u=0.8, min_area_u=(3 * UNIT_PITCH) ** 2)
    # the line enters at the bottom rim: make sure the body reaches it there (a neck column if needed)
    entry = (300.0, 300.0 + S)
    if not body[int((entry[1] - 0.03 * S) * F) - 1, int(entry[0] * F)]:
        col = np.zeros_like(body); w_ = 0.35 * face_w_c
        col[int(Lc[CHIN][1] * F):, int((300 - w_ / 2) * F):int((300 + w_ / 2) * F)] = True
        body |= col & inside & ~facem & ~hairm & ~beardm
    # one connected picture: a piece of body or hair that does not reach the rest within a line spacing would
    # need a long travel line across empty sand, so it is left out
    reach = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(1.2 * UNIT_PITCH * F) | 1,) * 2)
    def linked(m, base):
        n, lab = cv2.connectedComponents(m.astype(np.uint8)); keep = np.zeros_like(m)
        grown = cv2.dilate(base.astype(np.uint8), reach) > 0
        for i in range(1, n):
            comp = lab == i
            if (comp & grown).any(): keep |= comp
        return keep
    for _ in range(2):
        hairm = linked(hairm, facem | beardm | body)
        body = linked(body, facem | beardm | hairm | ((yy / F) > 300 + 0.9 * S))
    # earring end point
    end_ring = None
    want = None
    if end in ('earring-left', 'earring-right'):
        want = end.split('-')[1]
        cand = [e for e in earrings if e['side'] == want]
        if cand: end_ring = cand[0]['centre']
        else:                                                               # not seen: just under the ear lobe on that side
            j = ovc[np.argmin(ovc[:, 0])] if want == 'left' else ovc[np.argmax(ovc[:, 0])]
            end_ring = [float(j[0] + (-0.04 if want == 'left' else 0.04) * face_w_c), float(Lc[NOSE_BOT][1] + 0.12 * face_h_c)]
    elif end == 'auto' and earrings:
        end_ring = earrings[0]['centre']
    if end_ring:                                                            # the end island must touch the drawing
        allm = (facem | hairm | body | beardm).astype(np.uint8)
        dist_out = cv2.distanceTransform(1 - allm, cv2.DIST_L2, 5) / F
        ex_, ey_ = int(end_ring[0] * F), int(end_ring[1] * F)
        if dist_out[ey_, ex_] > 0.8 * UNIT_PITCH:
            if end == 'auto': end_ring = None; feat['earring_ignored'] = 'not touching the drawing'
            else:
                ys_, xs_ = np.nonzero(allm); k_ = np.argmin((xs_ - ex_) ** 2 + (ys_ - ey_) ** 2)
                end_ring = [float(xs_[k_] / F), float(ys_[k_] / F)]
    ring_poly = mpp.ellipse(tuple(end_ring), 0.55 * UNIT_PITCH, 0.55 * UNIT_PITCH) if end_ring else None

    # -- regions for make_people.build (region 0 must be the body: the line starts there)
    def M(m): return (m.astype(np.uint8) * 255)
    rk = 1.25                                                               # make_people pitch -> final pitch
    regions = [dict(mask=M(body), levels=2, pitch=rk, name='body')]
    regions.append(dict(mask=M(facem), holes=holes_face + ([patch.tolist()] if patch is not None else [mouth.tolist()]),
                        pitch=rk, name='face'))
    wav = dict(short=((0.9 * 1.5, 26 * 1.5), 0.8), long=((1.6 * 1.5, 44 * 1.5), 1.0), curly=((2.6 * 1.5, 22 * 1.5), 1.0),
               bald=((0.9 * 1.5, 26 * 1.5), 0.8))[htype]
    if hairm.sum() > 0:
        regions.append(dict(mask=M(hairm), wavy=wav[0], pitch=rk * wav[1], name='hair'))
    if has_beard and beardm.sum() > 0:
        regions.append(dict(mask=M(beardm), wavy=(2.4, 24), holes=[patch.tolist()], pitch=rk, name='beard'))
        pm = np.zeros((W, W), np.uint8); cv2.fillPoly(pm, [(patch * F).astype(np.int32)], 255)
        regions.append(dict(mask=pm, holes=[mouth.tolist()], pitch=rk, name='mouth patch'))
    if ring_poly is not None:
        rm = np.zeros((W, W), np.uint8); cv2.fillPoly(rm, [(np.array(ring_poly) * F).astype(np.int32)], 255)
        for r_ in regions: r_['mask'] = r_['mask'] & ~rm
        regions.append(dict(mask=rm, levels=1, name='earring'))
    p = dict(name='photo', regions=regions)
    if ring_poly is not None: p['final'] = len(regions) - 1
    feat['end'] = 'earring at %s' % end_ring if ring_poly is not None else 'bottom rim'
    meas['features'] = feat
    meas['regions'] = {r_['name']: round(float((r_['mask'] > 0).sum()) / (F * F) / (math.pi * S * S), 4) for r_ in regions}
    meas['head'] = dict(top_y=TOP_Y, chin_y=CHIN_Y, face_width=round(face_w_c / S, 3), face_height=round(face_h_c / S, 3),
                        face_width_vs_height=round(face_w_c / face_h_c, 3), hair_above_forehead_vs_face=round(hair_above, 3))

    # -- fill and route (shared with the approved portraits), write .thr
    P, nloops = mpp.build(p)
    hops = [math.dist(P[i], P[i + 1]) for i in range(1, len(P) - 1)]
    npts = write_thr(P, out + '.thr')
    with open(out + '.thr') as fh_:
        lines = fh_.read().splitlines()
    lines[0] = '# portrait from %s by tools/photo2sand.py' % os.path.basename(photo)
    open(out + '.thr', 'w').write('\n'.join(lines) + '\n')
    pts = np.array([list(map(float, l.split())) for l in lines if l and l[0] != '#'])
    meas['loops'] = nloops
    meas['checks'] = checks(pts, P, hops, ring_poly is not None)
    meas['seconds'] = dict(analyse_and_route=round(time.time() - t0, 1))

    # -- previews
    import sandsim, brighten, thrcommon
    meas['draw_minutes_est'] = round(thrcommon.est_minutes(pts), 1)
    im = sandsim.render(pts, size=900, real=True)
    prev = brighten.brighten(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR))
    cv2.imwrite(out + '_preview.jpg', prev, [cv2.IMWRITE_JPEG_QUALITY, 92])
    debug_image(bgr, conf, L, lens_ph if use_glasses else [], None, A, regions, meas, out + '_debug.jpg')
    meas['seconds']['total'] = round(time.time() - t0, 1)
    json.dump(meas, open(out + '.json', 'w'), indent=1)
    bad = [k for k, v in meas['checks'].items() if isinstance(v, dict) and not v.get('ok', True)]
    log('%s: %d points, %d loops, hair %s, glasses %s, beard %s, smile %.2f, %.1fs%s' % (
        os.path.basename(out), npts, nloops, htype, use_glasses, has_beard, sm_score, meas['seconds']['total'],
        ('  FAILED CHECKS: ' + ', '.join(bad)) if bad else ''))
    return 1 if bad else 0


RHO_MIN = 0.02


def write_thr(P, path):
    """make_people.to_thr (densify every 2.5 units, cumulative theta), then keep the line RHO_MIN off the exact centre:
    points closer are pushed out and the turn round the centre is laid as a small arc with short theta steps, so the
    arm never swings a large angle in one move. 0.02 of the radius is a third of a groove: invisible in the sand."""
    mpp.to_thr(P, path)
    pts = np.loadtxt(path, comments='#', ndmin=2)
    out = [pts[0]]
    for th, r in pts[1:]:
        r = max(r, RHO_MIN); th0, r0 = out[-1]
        n = int(abs(th - th0) / 0.12) if min(r, r0) < 0.06 else 0
        for i in range(1, n):
            out.append((th0 + (th - th0) * i / n, max(RHO_MIN, r0 + (r - r0) * i / n)))
        out.append((th, r))
    open(path, 'w').write('# portrait\n' + ''.join('%.5f %.5f\n' % (a, b) for a, b in out))
    return len(out)


def checks(pts, P, hops, ends_inside):
    th, r = pts[:, 0], pts[:, 1]
    x, y = r * np.cos(th), r * np.sin(th)
    step = np.hypot(np.diff(x), np.diff(y))
    dth = np.abs(np.diff(th))
    hop = max(hops) / S if hops else 0
    c = {}
    c['points'] = dict(n=int(len(pts)), ok=bool(len(pts) < 12000))
    c['rho_range'] = dict(min=round(float(r.min()), 4), max=round(float(r.max()), 4), ok=bool(r.min() >= 0 and r.max() <= 1))
    # theta continuous: no wrap jumps; big theta steps only allowed very near the centre (where a step is short)
    jump = dth > 0.7
    c['theta_continuous'] = dict(max_dtheta=round(float(dth.max()), 3), ok=bool(not jump.any()))
    c['max_step'] = dict(radius_fraction=round(float(step.max()), 4), ok=bool(step.max() < 0.025))
    c['largest_hop_between_lines'] = dict(radius_fraction=round(hop, 4), pitches=round(hop / PITCH_FINAL, 2), ok=bool(hop < 2.2 * PITCH_FINAL))
    a0 = math.atan2(y[0], x[0]); a1 = math.atan2(y[-1], x[-1])
    c['start_bottom_rim'] = dict(rho=round(float(r[0]), 3), ok=bool(r[0] > 0.99 and abs(a0 + math.pi / 2) < 0.3))
    c['end'] = dict(rho=round(float(r[-1]), 3), ok=bool(ends_inside or (r[-1] > 0.99 and abs(a1 + math.pi / 2) < 0.3)))
    c['centre_clearance'] = dict(min_rho=round(float(r.min()), 4), ok=bool(r.min() >= 0.01))
    c['top_of_drawing'] = dict(y=round(float(y.max()), 3))
    return c


def debug_image(bgr, conf, L, lenses, beard, A, regions, meas, path):
    H, Wp = bgr.shape[:2]
    cols = np.array([[0, 0, 0], [0, 200, 255], [255, 170, 110], [110, 110, 255], [90, 200, 90], [220, 0, 220]], np.float32)
    cm = np.argmax(conf, 0)
    ov = (0.55 * bgr + 0.45 * cols[cm]).astype(np.uint8)
    ov[cm == 0] = bgr[cm == 0]
    if beard is not None:
        ov[beard > 0] = (0.4 * ov[beard > 0] + 0.6 * np.array([40, 40, 160])).astype(np.uint8)
    t = max(1, int(round(max(H, Wp) / 500)))
    def pl(idx, col, closed=True): cv2.polylines(ov, [L[idx].astype(np.int32)], closed, col, t, cv2.LINE_AA)
    pl(OVAL, (255, 255, 255)); pl(LIPS_OUT, (0, 0, 255))
    for e in (EYE_A, EYE_B):
        cv2.circle(ov, tuple(L[e['iris']].astype(int)), 3 * t, (0, 255, 0), -1)
        cv2.line(ov, tuple(L[e['outer']].astype(int)), tuple(L[e['inner']].astype(int)), (0, 255, 0), t)
    cv2.line(ov, tuple(L[EYE_A['iris']].astype(int)), tuple(L[EYE_B['iris']].astype(int)), (0, 255, 255), t)
    for l in lenses:
        if l is not None: cv2.polylines(ov, [l.astype(np.int32)], True, (255, 0, 255), 2 * t, cv2.LINE_AA)
    # inset: the regions as laid out in the disc
    sz = min(H, Wp) // 2
    reg = np.full((W, W, 3), 245, np.uint8)
    rc = {'body': (90, 200, 90), 'face': (110, 110, 255), 'hair': (0, 200, 255), 'beard': (40, 40, 160), 'mouth patch': (200, 200, 255), 'earring': (220, 0, 220)}
    for r_ in regions: reg[r_['mask'] > 0] = rc.get(r_['name'], (128, 128, 128))
    for r_ in regions:
        for h in r_.get('holes', []):
            cv2.fillPoly(reg, [(np.array(h) * F).astype(np.int32)], (245, 245, 245))
    cv2.circle(reg, (W // 2, W // 2), int(S * F), (0, 0, 0), 3)
    reg = cv2.resize(reg, (sz, sz), interpolation=cv2.INTER_AREA)
    ov[H - sz:H, Wp - sz:Wp] = reg
    f = meas['features']; hr = meas['hair']
    txt = ['roll %.1f deg' % meas['roll_deg'], 'hair: %s' % hr['type_used'], 'glasses: %s' % ('yes' if f['glasses']['used'] else 'no'),
           'beard: %s' % meas['beard']['used'], 'smile %.2f' % f['mouth']['smile_score'],
           'end: %s' % ('earring' if 'earring' in f['end'] else 'rim')]
    fs = max(0.5, max(H, Wp) / 1400)
    for i, s in enumerate(txt):
        y = int((i + 1) * 34 * fs) + 6
        cv2.putText(ov, s, (10, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), 4 * t, cv2.LINE_AA)
        cv2.putText(ov, s, (10, y), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), t + 1, cv2.LINE_AA)
    cv2.imwrite(path, ov, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('photo')
    ap.add_argument('-o', '--out', help='output prefix (default: photo name without extension)')
    ap.add_argument('--group', action='store_true', help='draw all people together, preserving their positions in the photo')
    ap.add_argument('--glasses', choices=['auto', 'yes', 'no'], default='auto')
    ap.add_argument('--beard', choices=['auto', 'no', 'goatee', 'full'], default='auto',
                    help='auto finds a beard by colour and draws it as a goatee; say full for a full beard')
    ap.add_argument('--hair', choices=['auto', 'short', 'long', 'curly', 'bald'], default='auto')
    ap.add_argument('--smile', choices=['auto', 'yes', 'no'], default='auto')
    ap.add_argument('--end', choices=['auto', 'rim', 'earring-left', 'earring-right'], default='auto',
                    help='where the ball stops: auto = at a detected earring, else back out at the bottom rim')
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.photo)[0]
    sys.exit(run(a.photo, out, a.glasses, a.beard, a.hair, a.smile, a.end, a.group))


if __name__ == '__main__':
    main()
