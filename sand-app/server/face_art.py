"""Face crop -> sand line drawing (simple cartoon portrait), CPU only.

    face_strokes(jpeg_bytes) -> {"strokes": [[[x, y], ...], ...], "ok": bool, "note": str}

Strokes are polylines in the unit square (x right, y down, face upright), drawing centred and filling most of the
square, ordered for a ball that draws them one after another: face outline, hair, neck and shoulders, then the
features, each next stroke starting near where the previous one ended. At most 60 strokes and 6000 points.

Style (the approved mockup previews, captures/sand-app/assets/preview-*.png, and DRAWING-LESSONS.md rounds 13-19):
  * face outline traced from the photo's face-skin silhouette (ears included, beard included), hair as its outer
    shape plus a few flow strokes running parallel to it, neck, collar and shoulders from the body silhouette;
  * brows one stroke each, eyes = upper lid with a dark pupil dot wound on the way (no spur) + a short lower lid,
    glasses as lens rings + bridge, nose = one side line hooked round the nostril and along the base,
    mouth = an open-smile crescent or a lip line + lower lip, beard = a few strokes following the jaw (no outline);
  * true proportions (everything comes from the person's own landmarks and segmentation, nothing enlarged);
  * no two separate lines closer than about one ball width at drawn size (MIN_GAP of the face width), so the
    fine detail does not merge in sand.

Models (vendored in models/, see models/README.md): MediaPipe face_landmarker.task (478 landmarks) and
selfie_multiclass_256x256.tflite (background / hair / body skin / face skin / clothes / accessories).
Geometry helpers, landmark index sets, the glasses-lens finder and the beard test are adapted from
tools/auto_portrait.py and tools/photo2sand.py.
"""
import io
import math
import os
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, 'models')
MAX_STROKES, MAX_POINTS = 60, 6000
WORK_PX = 640                 # analysis size of the crop
MIN_GAP = 0.075               # minimum spacing between separate lines, in face widths (~one 4 mm ball width)

# MediaPipe face-mesh landmark index sets (from tools/auto_portrait.py)
EYE_A_UP = [33, 246, 161, 160, 159, 158, 157, 173, 133]; EYE_A_LO = [33, 7, 163, 144, 145, 153, 154, 155, 133]
EYE_B_UP = [362, 398, 384, 385, 386, 387, 388, 466, 263]; EYE_B_LO = [362, 382, 381, 380, 374, 373, 390, 249, 263]
BROW_A = ([46, 53, 52, 65, 55], [70, 63, 105, 66, 107])
BROW_B = ([276, 283, 282, 295, 285], [300, 293, 334, 296, 336])
LIP_OUT_UP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]; LIP_OUT_LO = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291]
LIP_IN_UP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308]; LIP_IN_LO = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308]
OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150,
        136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
NOSE_A = [196, 3, 51, 115, 48, 64, 98, 97, 2, 326, 327, 294]
NOSE_B = [419, 248, 281, 344, 278, 294, 327, 326, 2, 97, 98, 64]
IRIS_A, IRIS_B = 468, 473
BG, HAIR, BODY, FACE, CLOTHES, ACC = range(6)

_lock = threading.Lock()
_debug = None
_models = {}


# ---------------------------------------------------------------------------------------------- models
def _get_models():
    with _lock:
        if not _models:
            from mediapipe.tasks.python import vision, BaseOptions
            _models['lm'] = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=os.path.join(MODELS, 'face_landmarker.task')),
                num_faces=3, min_face_detection_confidence=0.4, min_face_presence_confidence=0.4))
            _models['seg'] = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=os.path.join(MODELS, 'selfie_multiclass_256x256.tflite')),
                output_category_mask=False, output_confidence_masks=True))
        return _models['lm'], _models['seg']


def _detect(rgb):
    import mediapipe as mp
    lm, seg = _get_models()
    H, W = rgb.shape[:2]
    im = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    with _lock:
        res = lm.detect(im)
        faces = [np.array([[p.x * W, p.y * H] for p in f]) for f in res.face_landmarks]
        if not faces:
            return None, None
        sr = seg.segment(im)
        conf = np.stack([m.numpy_view().astype(np.float32).reshape(H, W) for m in sr.confidence_masks])

    # the guest's face: big and near the centre of the crop
    def score(L):
        w = np.ptp(L[:, 0]); c = L[:, :2].mean(0)
        return w - 0.8 * np.hypot(c[0] - W / 2, c[1] - H / 2)
    return max(faces, key=score), conf


# ---------------------------------------------------------------------------------------------- geometry
def arclen(P):
    P = np.asarray(P, float)
    return np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]


def resample(P, step, closed=False):
    P = np.asarray(P, float)
    if closed:
        P = np.vstack([P, P[:1]])
    d = arclen(P)
    if d[-1] < 1e-9:
        return P[:1]
    n = max(2, int(round(d[-1] / step)) + 1)
    t = np.linspace(0, d[-1], n)
    return np.c_[np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])]


def smooth(P, sigma, step, closed=False):
    """Gaussian smoothing along the arc (same units as P). Open curves keep their end points."""
    from scipy import ndimage as ndi
    Q = resample(P, step, closed)
    if closed:
        Q = Q[:-1]
    if len(Q) < 4:
        return Q
    s = sigma / step
    if closed:
        return np.stack([ndi.gaussian_filter1d(Q[:, j], s, mode='wrap') for j in (0, 1)], 1)
    k = min(int(4 * s) + 1, len(Q) - 1)
    pre = 2 * Q[0] - Q[1:k + 1][::-1]; post = 2 * Q[-1] - Q[-k - 1:-1][::-1]
    R = np.vstack([pre, Q, post])
    R = np.stack([ndi.gaussian_filter1d(R[:, j], s) for j in (0, 1)], 1)
    return R[len(pre):len(pre) + len(Q)]


def length(P):
    return float(arclen(P)[-1]) if len(P) > 1 else 0.0


def normals(p):
    t = np.gradient(p, axis=0)
    t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
    return np.c_[-t[:, 1], t[:, 0]]


def runs(mask):
    """index runs [a, b) where mask is True"""
    m = np.r_[False, np.asarray(mask, bool), False].astype(np.int8)
    d = np.diff(m)
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def closed_runs(mask):
    """runs on a closed loop, wrapping round the end (returned as index arrays)"""
    mask = np.asarray(mask, bool); n = len(mask)
    if mask.all():
        return [np.arange(n)]
    if not mask.any():
        return []
    k = int(np.argmin(mask))                 # start at a False
    rolled = np.roll(mask, -k)
    return [(np.arange(a, b) + k) % n for a, b in runs(rolled)]


def mask_contour(m, min_area=0):
    """largest outer contour of a binary mask as (N,2) float px, or None"""
    import cv2
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cs = [c for c in cs if cv2.contourArea(c) >= min_area]
    if not cs:
        return None
    return max(cs, key=cv2.contourArea)[:, 0, :].astype(float)


def sample_mask(m, P):
    P = np.round(np.asarray(P)).astype(int)
    H, W = m.shape
    ok = (P[:, 0] >= 0) & (P[:, 0] < W) & (P[:, 1] >= 0) & (P[:, 1] < H)
    out = np.zeros(len(P), bool)
    out[ok] = m[P[ok, 1], P[ok, 0]]
    return out


class Gap:
    """Distance from points to everything already accepted (for the minimum-spacing rule)."""
    def __init__(self):
        self.pts = []
        self.tree = None

    def add(self, P):
        self.pts.append(np.asarray(P, float)); self.tree = None

    def dist(self, P):
        if not self.pts:
            return np.full(len(P), np.inf)
        if self.tree is None:
            from scipy.spatial import cKDTree
            self.tree = cKDTree(np.vstack(self.pts))
        return self.tree.query(np.asarray(P, float))[0]


def keep_clear(P, gap, d, min_len, closed=False):
    """pieces of P further than d from the accepted lines, each at least min_len long"""
    P = np.asarray(P, float)
    ok = gap.dist(P) > d
    pieces = [P[i] for i in closed_runs(ok)] if closed else [P[a:b] for a, b in runs(ok)]
    if closed and ok.all():
        return [np.vstack([P, P[:1]])]
    return [q for q in pieces if len(q) > 1 and length(q) >= min_len]


# ---------------------------------------------------------------------------------------------- measuring
def lens_from_acc(acc, eye_c, eye_w):
    """Outline of one glasses lens from the accessory mask around one eye (px), or None (from tools/photo2sand.py)."""
    import cv2
    H, Wp = acc.shape; r = int(1.5 * eye_w)
    x0, y0 = max(0, int(eye_c[0] - r)), max(0, int(eye_c[1] - r))
    x1, y1 = min(Wp, int(eye_c[0] + r)), min(H, int(eye_c[1] + r))
    win = (acc[y0:y1, x0:x1] > 0.5).astype(np.uint8)
    if win.sum() < 0.6 * eye_w:
        return None
    k = max(3, int(eye_w * 0.08) | 1)
    win = cv2.morphologyEx(win, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    inv = (1 - win).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv)
    ex, ey = int(eye_c[0] - x0), int(eye_c[1] - y0)
    if not (0 <= ey < lab.shape[0] and 0 <= ex < lab.shape[1]):
        return None
    li = lab[ey, ex]
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    if li == 0 or li in border:            # the frame does not close round the eye: use the frame's box near the eye
        ys, xs = np.nonzero(win)
        sel = (np.abs(xs - ex) < 1.2 * eye_w) & (np.abs(ys - ey) < 0.9 * eye_w)
        if sel.sum() < 0.6 * eye_w:
            return None
        bx0, bx1, by0, by1 = xs[sel].min(), xs[sel].max(), ys[sel].min(), ys[sel].max()
        if bx1 - bx0 < 0.9 * eye_w or by1 - by0 < 0.35 * eye_w:
            return None
        return rrect(((bx0 + bx1) / 2 + x0, (by0 + by1) / 2 + y0), bx1 - bx0, by1 - by0, min(bx1 - bx0, by1 - by0) * 0.3)
    lens = ((lab == li) | win.astype(bool)).astype(np.uint8)
    lens = cv2.morphologyEx(lens, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n2, lab2 = cv2.connectedComponents(lens)
    lens = (lab2 == lab2[ey, ex]).astype(np.uint8)
    cs, _ = cv2.findContours(lens, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)[:, 0, :].astype(float)
    c[:, 0] = np.clip(c[:, 0], ex - 1.25 * eye_w, ex + 1.25 * eye_w)
    hull = cv2.convexHull(c.astype(np.float32))[:, 0, :].astype(float)
    return hull + [x0, y0]


def rrect(c, w, h, r, n=6):
    out = []
    for (sx, sy, a0) in ((1, -1, -90), (1, 1, 0), (-1, 1, 90), (-1, -1, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            out.append((c[0] + sx * (w / 2 - r) + r * math.cos(a), c[1] + sy * (h / 2 - r) + r * math.sin(a)))
    return np.array(out)


def beard_mask(rgb, L, face, fw):
    """Facial hair below the nose: pixels much less colourful (or much darker) than the person's own cheeks.
    Hair of any colour is far less saturated than skin under the same light (tools/photo2sand.py beard_test)."""
    import cv2
    from scipy import ndimage as ndi
    H, W = face.shape
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (0, 0), max(1.0, 0.012 * fw))
    chroma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128); lig = lab[..., 0]
    ck = np.zeros((H, W), np.uint8)
    for i in (50, 280, 205, 425, 118, 347):
        cv2.circle(ck, tuple(int(v) for v in L[i]), max(2, int(0.04 * fw)), 1, -1)
    ck = ck > 0
    c0, l0 = float(np.median(chroma[ck])), float(np.median(lig[ck]))
    hairy = (chroma < 0.62 * c0) | (lig < 0.55 * l0)
    yy = np.mgrid[0:H, 0:W][0]
    region = face & (yy > L[2, 1] - 0.02 * fw)
    lips = np.zeros((H, W), np.uint8)
    cv2.fillPoly(lips, [np.round(np.vstack([L[LIP_OUT_UP], L[LIP_OUT_LO][::-1]])).astype(np.int32)], 1)
    lips = cv2.dilate(lips, np.ones((int(0.05 * fw) | 1,) * 2, np.uint8)) > 0
    m = hairy & region & ~lips
    k = int(0.06 * fw) | 1
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)) > 0
    lab_, n = ndi.label(m)
    if n == 0:
        return None
    sizes = ndi.sum(m, lab_, range(1, n + 1))
    m = lab_ == (1 + int(np.argmax(sizes)))
    # chin patch ratio: is it a real beard? (photo2sand: 0.53 / 0.63 with a beard, >= 0.82 without)
    chin = np.zeros((H, W), np.uint8)
    for i in (199, 175, 428, 208):
        cv2.circle(chin, tuple(int(v) for v in L[i]), max(2, int(0.04 * fw)), 1, -1)
    ratio = float(np.median(chroma[chin > 0])) / max(c0, 1.0)
    dark = float(np.median(lig[chin > 0])) / max(l0, 1.0)
    if m.sum() < 0.04 * fw * fw or (ratio > 0.78 and dark > 0.75):
        return None
    return m


# ---------------------------------------------------------------------------------------------- drawing
def face_strokes(jpeg_bytes):
    try:
        rgb = _decode(jpeg_bytes)
    except Exception:
        return dict(strokes=[], ok=False, note='not a readable image')
    if rgb is None or min(rgb.shape[:2]) < 48:
        return dict(strokes=[], ok=False, note='image too small')
    try:
        L, conf = _detect(rgb)
    except Exception as e:                                       # model missing or broken install
        return dict(strokes=[], ok=False, note='face finder unavailable: %s' % type(e).__name__)
    if L is None:
        return dict(strokes=[], ok=False, note='no face found')
    try:
        strokes, note = _draw(rgb, L, conf)
    except Exception as e:
        return dict(strokes=[], ok=False, note='could not draw this face (%s)' % type(e).__name__)
    if not strokes:
        return dict(strokes=[], ok=False, note='no face found')
    return dict(strokes=strokes, ok=True, note=note)


def _decode(data):
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert('RGB')
    w, h = im.size
    k = WORK_PX / max(w, h)
    if k < 1:
        im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    return np.asarray(im)


def _draw(rgb, L, conf):
    import cv2
    from scipy import ndimage as ndi
    L = L[:, :2]
    fw = float(np.hypot(*(L[454] - L[234])))
    # pad the crop (sand colour, label background) so a head cut by the crop edge still gets a closed, rounded outline
    H0, W0 = rgb.shape[:2]
    P0 = int(0.12 * max(H0, W0))
    rgb = cv2.copyMakeBorder(rgb, P0, P0, P0, P0, cv2.BORDER_CONSTANT, value=(232, 220, 184))
    bgc = np.zeros((6,) + rgb.shape[:2], np.float32); bgc[BG] = 1.0
    bgc[:, P0:P0 + H0, P0:P0 + W0] = conf
    conf = bgc
    L = L + P0
    H, W = rgb.shape[:2]
    D = MIN_GAP * fw                                           # one ball width in px
    B = 0.42 * D                                               # offset of the second pass of a bold line
    st = 0.25 * D                                              # working point step
    cx = float((L[454, 0] + L[234, 0]) / 2)
    chin = L[152]
    eye_y = float((L[IRIS_A, 1] + L[IRIS_B, 1]) / 2)
    fh = float(chin[1] - L[10, 1])
    turn = float((L[1, 0] - cx) / fw)                           # >0: nose to the viewer's right
    y_bottom = chin[1] + 0.5 * fh                              # neck, shoulders and hair stop here

    blur = cv2.GaussianBlur(conf.transpose(1, 2, 0), (0, 0), max(1.0, 0.02 * fw)).transpose(2, 0, 1)
    lab = blur.argmax(0)
    yy, xx = np.mgrid[0:H, 0:W]

    def comp_near(m, pts, grow=0):
        m = m.astype(np.uint8)
        if grow:
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((grow | 1, grow | 1), np.uint8))
        n, cl = cv2.connectedComponents(m)
        keep = set(int(cl[int(np.clip(p[1], 0, H - 1)), int(np.clip(p[0], 0, W - 1))]) for p in pts) - {0}
        return np.isin(cl, list(keep)) if keep else np.zeros_like(m, bool)

    def disk(r):
        r = max(1, int(r)) | 1
        return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))

    oval = np.zeros((H, W), np.uint8)
    cv2.fillPoly(oval, [np.round(L[OVAL]).astype(np.int32)], 1)
    oval = oval > 0
    # face skin silhouette: face class + the landmark oval; holes (glasses, eyes, mouth) filled
    near = cv2.dilate(oval.astype(np.uint8), disk(0.2 * fw)) > 0
    face = (lab == FACE) | ((lab == ACC) & near)
    face = comp_near(face | oval, [L[1], L[152], L[10]])
    face = ndi.binary_fill_holes(face)
    beard = beard_mask(rgb, L, face, fw)
    # the face never runs far below the jaw (a neck classified as face skin); a beard may go a little lower
    face &= yy < chin[1] + (0.16 if beard is not None else 0.05) * fw
    face &= (cv2.dilate(oval.astype(np.uint8), disk((0.3 if beard is not None else 0.08) * fw)) > 0) | (yy < L[2, 1])
    face = cv2.morphologyEx(face.astype(np.uint8), cv2.MORPH_OPEN, disk(0.05 * fw)) > 0
    face = comp_near(face, [L[1]])

    hair = (lab == HAIR) & ~face
    hair = cv2.morphologyEx(hair.astype(np.uint8), cv2.MORPH_OPEN, disk(0.04 * fw)) > 0
    touch = cv2.dilate(face.astype(np.uint8), disk(0.06 * fw)) > 0
    n, cl = cv2.connectedComponents(hair.astype(np.uint8))
    keep = set(np.unique(cl[touch & hair])) - {0}
    hair = np.isin(cl, list(keep)) & (yy < y_bottom)
    has_hair = hair.sum() > 0.03 * fw * fw

    if _debug is not None:
        _debug.update(face=face, hair=hair, L=L, P0=P0)
    items = []          # (tier, name, polyline px, closed)
    gap = Gap()

    def accept(tier, name, P, closed=False):
        P = np.asarray(P, float)
        if len(P) < 2:
            return
        items.append((tier, name, P, closed)); gap.add(resample(P, st, closed))

    def smooth_contour(m, sigma):
        m2 = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma) > 0.5
        c = mask_contour(m2, min_area=0.02 * fw * fw)
        if c is None:
            return None
        return smooth(c, sigma, st, closed=True)

    def cut_bottom(P):
        """points that are not on the bottom cut (crop edge or the shoulder limit) or the crop's side edges low down"""
        low = P[:, 1] > y_bottom - 2
        e = 0.06 * fw
        side = ((P[:, 0] < P0 + e) | (P[:, 0] > P0 + W0 - e) | (P[:, 1] > P0 + H0 - e)) & (P[:, 1] > L[2, 1])
        return low | side

    def bold(P, closed, inward=None):
        """the line plus a second pass B beside it (towards `inward`, a point, or the curve's left), drawn as one stroke"""
        P = resample(P, st, closed)
        nn = normals(P)
        if inward is not None:
            s = np.sign(((np.asarray(inward) - P) * nn).sum(1).mean()) or 1.0
            nn = nn * s
        Q = P + B * nn
        if closed:
            return np.vstack([P, Q])
        return np.vstack([P, Q[::-1]])

    # 1. face outline (closed: forehead/hairline, ears, jaw or beard edge), bold
    fc = smooth_contour(face, 0.035 * fw)
    if fc is None:
        return [], 'no face outline'
    fcen = np.array([cx, (L[10, 1] + chin[1]) / 2])
    accept(0, 'face', bold(fc, True, fcen), closed=False)
    face_line = resample(fc, st, True)

    # 2. hair: outer shape (hair outline minus the part shared with the face), then fill lines parallel to it
    if has_hair:
        hm = cv2.GaussianBlur(hair.astype(np.float32), (0, 0), 0.04 * fw) > 0.5
        hc = smooth_contour(hm, 0.03 * fw)
        if hc is not None:
            ok = (gap.dist(hc) > 1.0 * D) & ~cut_bottom(hc)
            for idx in sorted(closed_runs(ok), key=len, reverse=True):
                p = hc[idx]
                if length(p) >= 0.2 * fw:
                    accept(1, 'hair', p)
            # fill: offsets of the outer silhouette inward every ~1.1 ball widths, clear of the face line
            outside = ~(hm | face)
            d_out = ndi.distance_transform_edt(~outside)
            d_face = ndi.distance_transform_edt(~face)
            for k in range(1, 7):
                lev = k * 1.12 * D
                m = hm & (d_out >= lev)
                if m.sum() < 0.01 * fw * fw:
                    break
                cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
                for c in cs:
                    c = c[:, 0, :].astype(float)
                    if len(c) < 12:
                        continue
                    c = smooth(c, 0.03 * fw, st, closed=True)
                    ci = np.clip(np.round(c).astype(int), 0, [W - 1, H - 1])
                    ok = (d_face[ci[:, 1], ci[:, 0]] > 1.0 * D) & ~cut_bottom(c)
                    for idx in closed_runs(ok):
                        p = c[idx]
                        if length(p) < 0.3 * fw:
                            continue
                        # a gentle wave so the lines read as hair, not as a contour map
                        nn = normals(p); s_ = arclen(p)
                        p = p + (0.13 * D * np.sin(2 * np.pi * s_ / (2.2 * D) + k))[:, None] * nn
                        for q in keep_clear(p, gap, 0.85 * D, 0.25 * fw):
                            accept(2, 'hairflow', q)

    # 3. neck and shoulders, drawn like the approved hand-made busts: two neck lines down from the jaw, then the
    #    shoulders sloping out to the bottom edge. Sized from the face (the photo's clothes and backgrounds are too
    #    varied to trace reliably); where long hair covers them they are left out.
    roll = 0.3 * math.atan2(L[263, 1] - L[33, 1], L[263, 0] - L[33, 0])   # shoulders follow a head tilt only a little
    ux = np.array([math.cos(roll), math.sin(roll)]); uy = np.array([-math.sin(roll), math.cos(roll)])
    base = np.array([0.5 * cx + 0.5 * chin[0], chin[1]]) - 0.1 * fh * uy
    hair_d = cv2.dilate(hair.astype(np.uint8), disk(0.9 * D)) > 0
    for sgn in (-1, 1):
        def at(x, y):
            return base + sgn * x * fw * ux + y * fh * uy
        pts = [at(0.28, -0.05), at(0.28, 0.20), at(0.32, 0.28), at(0.58, 0.36), at(0.82, 0.40), at(0.98, 0.46), at(1.08, 0.52)]
        p = smooth(np.array(pts), 0.04 * fw, st)
        # start where the neck line leaves the face, stop at the shoulder limit
        inside = sample_mask(face, p) | sample_mask(hair_d, p)
        p = p[~inside & (p[:, 1] < y_bottom)]
        for q in keep_clear(p, gap, 0.9 * D, 0.2 * fw):
            accept(3, 'body', q)

    # 4. features
    feats = []
    lenses = []
    acc = conf[ACC]
    band_ = acc[max(0, int(eye_y - 0.3 * fw)):int(eye_y + 0.3 * fw)]
    if band_.size and band_.max() > 0.5:
        for up, ir in ((EYE_A_UP, IRIS_A), (EYE_B_UP, IRIS_B)):
            ew = float(np.hypot(*(L[up[0]] - L[up[-1]])))
            ln = lens_from_acc(acc, L[ir], ew)
            if ln is not None:
                ln = smooth(ln, 0.03 * fw, st, closed=True)
                if 1.1 * ew < np.ptp(ln[:, 0]) < 2.8 * ew:
                    lenses.append(ln)
        if len(lenses) != 2:
            lenses = []
    if lenses:
        lenses.sort(key=lambda p: p[:, 0].mean())
        for ln in lenses:
            # lens ring a little outside the eye; bold inward
            feats.append(('lens', bold(ln, True, ln.mean(0)), False))
        a, b = lenses
        ia = a[np.argmax(a[:, 0] - 0.5 * np.abs(a[:, 1] - eye_y))]
        ib = b[np.argmin(b[:, 0] + 0.5 * np.abs(b[:, 1] - eye_y))]
        top = np.array([(ia[0] + ib[0]) / 2, min(ia[1], ib[1]) - 0.03 * fw])
        if ib[0] - ia[0] > 0.03 * fw:
            feats.append(('bridge', smooth(np.array([ia, (ia + top) / 2 + [-0.01 * fw, 0], top, (ib + top) / 2 + [0.01 * fw, 0], ib]), 0.02 * fw, st), False))
        for ln, sgn in ((a, -1), (b, 1)):
            o = ln[np.argmax(sgn * ln[:, 0] - 0.5 * np.abs(ln[:, 1] - eye_y))]
            xs = o[0] + sgn * np.arange(1, int(0.5 * fw))
            Pa = np.c_[xs, np.full(len(xs), o[1] - 0.01 * fw)]
            inside = sample_mask(face, Pa)
            k = int(np.argmin(inside)) if not inside.all() else len(Pa) - 1
            if length(Pa[:k]) > 0.5 * D:
                feats.append(('arm', Pa[:k], False))

    # brows: bold stroke along the brow middle
    for lo, up in (BROW_A, BROW_B):
        mid = (L[lo] + L[up]) / 2
        if mid[0, 0] > mid[-1, 0]:
            mid = mid[::-1]
        feats.append(('brow', bold(smooth(mid, 0.03 * fw, st), False, mid.mean(0) + [0, -fw]), False))

    # eyes: almond (upper lid, lower lid) with a dark pupil dot wound under the upper lid (no spur)
    for up, lo, ir in ((EYE_A_UP, EYE_A_LO, IRIS_A), (EYE_B_UP, EYE_B_LO, IRIS_B)):
        u = smooth(L[up], 0.02 * fw, st)
        lw = smooth(L[lo], 0.02 * fw, st)
        ew = length(u)
        eh = float(np.hypot(*(L[up[4]] - L[lo[4]])))
        need = 0.85 * D                                       # the almond must open at least this much to read
        if eh < need:
            t_ = np.linspace(0, 1, len(lw)); lw = lw + np.c_[np.zeros(len(lw)), (need - eh) * np.sin(np.pi * t_)]
            eh = need
        ic = L[ir]
        r = float(np.clip(0.45 * eh, 0.3 * D, 0.5 * D))
        k = int(np.argmin(np.abs(u[:, 0] - ic[0])))
        c = np.array([ic[0], u[k, 1] + 0.9 * r])
        pts = []; th = -math.pi / 2; rr = r
        while rr > 0.08 * D:
            pts.append((c[0] + rr * math.cos(th), c[1] + rr * math.sin(th)))
            dth = 0.25 * D / max(rr, 0.25 * D); th += dth; rr -= 0.1 * D * dth / (2 * math.pi)
        sp = np.array(pts)
        lid = np.vstack([u[:k + 1], sp, sp[::-1][1:], u[k + 1:]])
        if np.hypot(*(lw[0] - u[-1])) < np.hypot(*(lw[-1] - u[-1])):
            lw = lw[::-1]
        feats.append(('eye', np.vstack([lid, lw]), False))

    # nose: one side line hooked round the nostril wing and along the base
    nose = NOSE_B if turn > 0.04 else NOSE_A
    feats.append(('nose', smooth(L[nose], 0.025 * fw, st), False))

    # mouth: open smile = crescent (bold); closed = bold lip line + lower lip
    mw = float(np.hypot(*(L[61] - L[291])))
    gap_in = float(np.hypot(*(L[13] - L[14])))
    mc = (L[13] + L[14]) / 2
    if gap_in > 0.07 * mw:
        top = L[LIP_IN_UP].copy(); top[0], top[-1] = L[61], L[291]
        bot = (L[LIP_IN_LO] + L[LIP_OUT_LO]) / 2; bot[0], bot[-1] = L[61], L[291]
        loop = smooth(np.vstack([top, bot[::-1][1:-1]]), 0.02 * fw, st, closed=True)
        feats.append(('mouth', bold(loop, True, mc), False))
    else:
        mid = (L[LIP_IN_UP] + L[LIP_IN_LO]) / 2; mid[0], mid[-1] = L[61], L[291]
        feats.append(('mouth', bold(smooth(mid, 0.02 * fw, st), False, mc + [0, -fw]), False))
        lo = smooth(L[LIP_OUT_LO], 0.02 * fw, st); n = len(lo)
        feats.append(('lowlip', lo[int(0.3 * n):int(0.7 * n)] + [0, 0.15 * D], False))

    # features in priority order; secondary ones are trimmed to stay a ball width clear
    prio = ['lens', 'eye', 'brow', 'nose', 'mouth', 'bridge', 'arm', 'lowlip']
    feats.sort(key=lambda f: prio.index(f[0]))
    fgap = Gap()
    for name, P, closed in feats:
        P = resample(P, st)
        if name == 'brow' and lenses:                     # brows just above the frames: lift them clear if a small lift does it
            lift = 1.0 * D - float(fgap.dist(P).min())
            if 0 < lift < 0.9 * D:
                P = P - [0, lift]
        if name in ('eye', 'lens', 'mouth', 'nose'):
            pieces = [P]
        else:
            pieces = [q for q in [P[a:b] for a, b in runs(fgap.dist(P) > 0.9 * D)] if len(q) > 1 and length(q) > 0.06 * fw]
        for q in pieces:
            items.append((4, name, q, False)); fgap.add(q); gap.add(q)

    # 5. beard: strokes following the jaw line inside the beard, no outline
    if beard is not None:
        seg = face_line[face_line[:, 1] > L[2, 1]]
        if len(seg) > 10:
            # keep the lower arc only (ear to ear under the chin)
            seg = seg[np.argsort(np.arctan2(seg[:, 1] - L[2, 1], seg[:, 0] - cx))]
            nn = normals(seg)
            sgn = np.sign(((np.array([cx, L[14, 1]]) - seg) * nn).sum(1).mean()) or 1.0
            bm = cv2.dilate(beard.astype(np.uint8), disk(0.06 * fw)) > 0
            xs_ = np.nonzero(beard.any(0))[0]
            if len(xs_) and xs_.max() - xs_.min() < 0.7 * fw:     # a goatee: strokes parallel to the lower lip instead
                lo = smooth(L[LIP_OUT_LO], 0.03 * fw, st)
                lc = lo.mean(0); seg = lc + 1.6 * (lo - lc)
                nn = np.tile([0.0, 1.0], (len(seg), 1)); sgn = 1.0
            for kk in range(1, 7):
                q = seg + sgn * (B + kk * 1.05 * D) * nn
                ins = sample_mask(bm, q) & (gap.dist(q) > 0.95 * D)
                for a, b in runs(ins):
                    if length(q[a:b]) > 0.09 * fw:
                        p = smooth(q[a:b], 0.03 * fw, st)
                        items.append((5, 'beard', p, False)); gap.add(p)

    # ---------------------------------------------------------------- to the unit square
    allp = np.vstack([p for _, _, p, _ in items])
    x0, y0 = allp.min(0); x1, y1 = allp.max(0)
    s = 0.92 / max(x1 - x0, y1 - y0)
    off = np.array([0.5 - s * (x0 + x1) / 2, 0.5 - s * (y0 + y1) / 2])
    out = [(tier, name, p * s + off, closed) for tier, name, p, closed in items]
    if _debug is not None:
        _debug['items'] = out
    strokes = _caps(_order(out))
    note = 'face drawn: %d strokes%s%s%s' % (len(strokes), ', glasses' if lenses else '', ', beard' if beard is not None else '',
                                           '' if has_hair else ', no hair found')
    return strokes, note


def _order(items):
    """Tier by tier (outline, hair, body, features, beard); inside a tier the next stroke is the one whose start
    (either end, or any point of a closed loop) is nearest to where the ball is."""
    from scipy.spatial import cKDTree
    res = []
    cur = None
    for tier in sorted(set(t for t, _, _, _ in items)):
        todo = [(n, p, c) for t, n, p, c in items if t == tier]
        while todo:
            if cur is None:
                j = 0; best = (todo[0][1], 0)
                bi = int(np.argmax(todo[0][1][:, 1])) if todo[0][2] else 0
                p = todo[0][1]
                best = (np.vstack([p[bi:-1], p[:bi + 1]]) if todo[0][2] and bi else p)
            else:
                bd, j, best = np.inf, 0, None
                for i, (n, p, c) in enumerate(todo):
                    if c:
                        d, k = cKDTree(p[:-1]).query(cur)
                        if d < bd:
                            bd, j, best = d, i, np.vstack([p[k:-1], p[:k + 1]])
                    else:
                        for q in (p, p[::-1]):
                            d = float(np.hypot(*(q[0] - cur)))
                            if d < bd:
                                bd, j, best = d, i, q
            res.append(best)
            cur = best[-1]
            todo.pop(j)
    return res


def _caps(strokes):
    strokes = [np.clip(p, 0.0, 1.0) for p in strokes if len(p) > 1]
    strokes = strokes[:MAX_STROKES]
    total = sum(length(p) for p in strokes)
    step = max(0.004, total / (MAX_POINTS - 2 * len(strokes) - 10))
    out = []
    for p in strokes:
        q = resample(p, step)
        out.append([[round(float(x), 4), round(float(y), 4)] for x, y in q])
    while sum(len(p) for p in out) > MAX_POINTS:            # never expected; belt and braces
        out = [p[::2] if len(p) > 4 else p for p in out]
    return out
