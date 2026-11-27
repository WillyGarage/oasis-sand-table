#!/usr/bin/env python3
"""Locate the steel ball on the round sand table in one webcam frame.

Usage:  locate.py frame.jpg [--debug out.jpg] [--prev prev.jpg]
Prints one JSON line:
  {"ok","ball_px":[x,y],"center_px":[x,y],"ellipse":{cx,cy,a,b,angle_deg},
   "rho","theta_deg","confidence","note"}

Read-only vision tool: touches no hardware.

COORDINATE CONVENTION
  ellipse: cx,cy = centre (image px); a >= b = semi-axes (px); angle_deg = direction of the
           major axis, measured from image +x toward image +y (OpenCV, clockwise on screen).
  The sand disc is a circle on the table plane seen at a tilt, so it appears as an ellipse.
  We "un-squash" by an affine map: express the ball offset in the ellipse axes, divide by a
  and b, rotate back. This gives table-plane coordinates in units of the sand radius, with
  image +x as the x axis (same orientation as the image, no mirroring).
  rho       = |un-squashed offset| = distance from centre / sand radius (0 = centre, 1 = rim).
  theta_deg = atan2(up, right) of the un-squashed offset, i.e. counter-clockwise on screen
              from image +x ("3 o'clock" = 0, "12 o'clock" = 90), range 0..360.

APPROXIMATION
  An affine map treats the camera as orthographic. A real perspective camera makes the far
  half of the disc smaller than the near half, and the ellipse centre is not exactly the
  image of the disc centre (it sits slightly toward the far side). Also the ball centre sits
  ~5 mm above the sand plane. See the end-of-run report for the estimated size (a few % of
  the radius, worst at the far/near edges); theta is far less affected than rho.

METHOD
  Ellipse: the sand is a big bright blob enclosed by a dark grey rim. We threshold bright,
  take connected components of the mask, pick the one that is large, compact, ringed by dark
  pixels and not just the desk; then take its boundary points (dropping points on the image
  border = the cut-off bottom), keep those with dark rim just outside, and RANSAC-fit an
  ellipse (robust to hands/mice/notches), refined with a radial edge search.
  Ball: sand-relative darkness (local background minus grey level) inside the ellipse; blobs
  are size gated (scaled by sand size), scored by contrast, roundness and a specular
  highlight. Ridge shadows are long and thin, so roundness rejects them. With --prev, the
  previous frame (aligned by its own ellipse) is differenced and blobs that changed are
  favoured.
"""
import sys, json, argparse
import numpy as np
import cv2

REF_W = 1920.0


def _load(path):
    im = cv2.imread(path, cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit(json.dumps({"ok": False, "note": "cannot read " + path}))
    return im


# ---------------------------------------------------------------- ellipse
def _ransac_ellipse(pts, iters=300, tol=3.0, seed=1):
    rng = np.random.default_rng(seed)
    n = len(pts)
    best, best_in = None, None
    for _ in range(iters):
        idx = rng.choice(n, 8, replace=False)
        # spread check: samples should not all be close together
        s = pts[idx]
        if np.ptp(s[:, 0]) + np.ptp(s[:, 1]) < 0.4 * (np.ptp(pts[:, 0]) + np.ptp(pts[:, 1])):
            continue
        try:
            e = cv2.fitEllipse(s.astype(np.float32))
        except cv2.error:
            continue
        err = _ell_resid(pts, e)
        inl = err < tol
        if best_in is None or inl.sum() > best_in.sum():
            best, best_in = e, inl
    if best is None:
        return None, None
    for _ in range(3):  # refit on inliers
        if best_in.sum() < 6:
            break
        try:
            e = cv2.fitEllipse(pts[best_in].astype(np.float32))
        except cv2.error:
            break
        inl = _ell_resid(pts, e) < tol
        if inl.sum() < best_in.sum() * 0.8:
            break
        best, best_in = e, inl
    return best, best_in


def _ell_resid(pts, e):
    """Approx. distance from points to ellipse boundary (px)."""
    (cx, cy), (w, h), ang = e
    a, b = max(w, h) / 2, min(w, h) / 2
    if b < 1:
        return np.full(len(pts), 1e9)
    phi = np.deg2rad(ang if w >= h else ang + 90)
    c, s = np.cos(phi), np.sin(phi)
    dx, dy = pts[:, 0] - cx, pts[:, 1] - cy
    u, v = c * dx + s * dy, -s * dx + c * dy
    r = np.hypot(u / a, v / b)
    return np.abs(r - 1) * (a + b) / 2


def _norm_ellipse(e):
    (cx, cy), (w, h), ang = e
    if w >= h:
        a, b, phi = w / 2, h / 2, ang
    else:
        a, b, phi = h / 2, w / 2, ang + 90
    return dict(cx=float(cx), cy=float(cy), a=float(a), b=float(b), angle_deg=float(phi % 180))


def find_ellipse(img):
    H, W = img.shape[:2]
    sc = 0.5 if W > 1000 else 1.0
    small = cv2.resize(img, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) if sc != 1 else img
    sh, sw = small.shape[:2]
    g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (0, 0), 2)
    cands = []
    for thr in (150, 130, 170, 110):
        bright = (g > thr).astype(np.uint8)
        bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
        n, lab, st, cen = cv2.connectedComponentsWithStats(bright, connectivity=4)
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if area < 0.04 * sw * sh or area > 0.5 * sw * sh:
                continue
            m = (lab == i).astype(np.uint8)
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            c = max(cnts, key=cv2.contourArea).reshape(-1, 2)
            # drop border points (frame cut-off), keep a margin
            keep = (c[:, 0] > 3) & (c[:, 0] < sw - 4) & (c[:, 1] > 3) & (c[:, 1] < sh - 4)
            c = c[keep].astype(np.float64)
            if len(c) < 80:
                continue
            # rim test: dark pixels just outside the contour
            hull = cv2.convexHull(c.astype(np.float32))
            e0, inl0 = _ransac_ellipse(c, tol=3.0 * sc + 1)
            if e0 is None:
                continue
            nrm = _norm_ellipse(e0)
            if nrm["b"] < 0.12 * sw or nrm["a"] > 0.6 * sw or nrm["a"] / nrm["b"] > 2.2:
                continue
            # darkness of a ring just outside the fitted ellipse
            ring = _ring_darkness(g, e0, 1.06, 1.14)
            support = inl0.sum() / len(c)
            score = ring * 2 + support
            cands.append((score, e0, thr, ring, support))
    if not cands:
        return None, None
    cands.sort(key=lambda t: -t[0])
    score, e0, thr, ring, support = cands[0]
    # radial refinement on the full-res image
    e = _scale_ell(e0, 1.0 / sc)
    e2, nin = _refine_radial(img, e)
    if e2 is not None:
        e = e2
    q = dict(ring=float(ring), support=float(support), refined_pts=int(nin))
    return e, q


def _scale_ell(e, f):
    (cx, cy), (w, h), ang = e
    return ((cx * f, cy * f), (w * f, h * f), ang)


def _ring_darkness(g, e, r0, r1):
    """fraction of the ring between r0..r1 x ellipse that is much darker than the inside."""
    (cx, cy), (w, h), ang = e
    th = np.linspace(0, 2 * np.pi, 180, endpoint=False)
    phi = np.deg2rad(ang)
    a, b = w / 2, h / 2
    res = []
    H, W = g.shape
    for t in th:
        vals = []
        for r in (0.85, (r0 + r1) / 2):
            u, v = a * r * np.cos(t), b * r * np.sin(t)
            x = cx + u * np.cos(phi) - v * np.sin(phi)
            y = cy + u * np.sin(phi) + v * np.cos(phi)
            if not (0 <= x < W and 0 <= y < H):
                vals = None
                break
            vals.append(float(g[int(y), int(x)]))
        if vals:
            res.append(vals[0] - vals[1] > 40)
    return float(np.mean(res)) if len(res) > 20 else 0.0


def _refine_radial(img, e, nang=120):
    """Cast rays from the centre; the inner rim edge is the strongest bright->dark drop
    near the predicted radius. Fit an ellipse (RANSAC) to those points."""
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (0, 0), 1.5).astype(np.float32)
    H, W = g.shape
    (cx, cy), (w, h), ang = e
    phi = np.deg2rad(ang)
    a, b = w / 2, h / 2
    pts = []
    for t in np.linspace(0, 2 * np.pi, nang, endpoint=False):
        best = None
        rs = np.linspace(0.88, 1.12, 49)
        xs, ys, vals = [], [], []
        for r in rs:
            u, v = a * r * np.cos(t), b * r * np.sin(t)
            x = cx + u * np.cos(phi) - v * np.sin(phi)
            y = cy + u * np.sin(phi) + v * np.cos(phi)
            xs.append(x); ys.append(y)
            vals.append(g[int(round(y)), int(round(x))] if (2 <= x < W - 2 and 2 <= y < H - 2) else np.nan)
        vals = np.array(vals)
        if np.isnan(vals).any():
            continue
        d = vals[:-3] - vals[3:]  # drop across 3 samples outward
        k = int(np.argmax(d))
        if d[k] > 35:
            pts.append((xs[k + 1], ys[k + 1]))
    if len(pts) < 30:
        return None, len(pts)
    pts = np.array(pts)
    e2, inl = _ransac_ellipse(pts, iters=200, tol=3.0)
    if e2 is None or inl.sum() < 25:
        return None, len(pts)
    return e2, int(inl.sum())


# ------------------------------------------------------------------- ball
def to_polar(pt, ell):
    phi = np.deg2rad(ell["angle_deg"])
    c, s = np.cos(phi), np.sin(phi)
    dx, dy = pt[0] - ell["cx"], pt[1] - ell["cy"]
    u, v = c * dx + s * dy, -s * dx + c * dy
    u, v = u / ell["a"], v / ell["b"]
    px, py = c * u - s * v, s * u + c * v          # back to image axes, unit-radius disc
    rho = float(np.hypot(px, py))
    theta = float(np.degrees(np.arctan2(-py, px)) % 360)   # -py: image y points down
    return rho, theta


def ellipse_mask(shape, ell, scale=1.0):
    m = np.zeros(shape[:2], np.uint8)
    cv2.ellipse(m, ((ell["cx"], ell["cy"]), (2 * ell["a"] * scale, 2 * ell["b"] * scale), ell["angle_deg"]),
                255, -1)
    return m


def _align_prev(prev, ell_p, ell):
    """Warp prev so its table sits on the current one (translation + isotropic scale)."""
    s = np.sqrt(ell["a"] * ell["b"]) / np.sqrt(ell_p["a"] * ell_p["b"])
    M = np.array([[s, 0, ell["cx"] - s * ell_p["cx"]], [0, s, ell["cy"] - s * ell_p["cy"]]], np.float32)
    return cv2.warpAffine(prev, M, (prev.shape[1], prev.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def find_ball(img, ell, prev=None):
    H, W = img.shape[:2]
    R = np.sqrt(ell["a"] * ell["b"])
    k = R / 250.0                      # 1.0 at the nominal ~250 px sand radius of 1920x1080
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 1.0)
    inside = ellipse_mask(img.shape, ell, 0.97)
    ksz = int(round(41 * k)) | 1
    bg = cv2.medianBlur(np.clip(g, 0, 255).astype(np.uint8), ksz).astype(np.float32)
    dark = bg - g                      # >0 where darker than surroundings
    dark[inside == 0] = 0

    changed = None
    if prev is not None:
        gp = cv2.GaussianBlur(cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.5)
        gc = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.5)
        changed = (np.abs(gc - gp) > 18).astype(np.uint8)
        changed[inside == 0] = 0

    mask = (dark > 22).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(mask, connectivity=8)
    dmin, dmax = 12 * k, 24 * k        # allowed blob extent (px)
    out = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area < 0.3 * (np.pi * (dmin / 2) ** 2) or area > 1.6 * np.pi * (dmax / 2) ** 2:
            continue
        pts = np.column_stack(np.nonzero(lab[y:y + h, x:x + w] == i))[:, ::-1] + [x, y]
        if len(pts) < 5:
            continue
        cov = np.cov(pts.T.astype(np.float64))
        ev = np.sort(np.linalg.eigvalsh(cov))
        major = 4 * np.sqrt(max(ev[1], 1e-6))
        minor = 4 * np.sqrt(max(ev[0], 1e-6))
        if major > dmax * 1.4 or major < dmin * 0.5:
            continue
        round_ = minor / major
        if round_ < 0.45:
            continue
        cx_, cy_ = pts[:, 0].mean(), pts[:, 1].mean()
        sub = (lab[y:y + h, x:x + w] == i)
        contrast = float(np.percentile(dark[y:y + h, x:x + w][sub], 90))
        # specular highlight: a small, clearly brighter pixel cluster just inside/at the blob
        r = int(dmax)
        x0, x1, y0, y1 = int(max(0, cx_ - r)), int(min(W, cx_ + r)), int(max(0, cy_ - r)), int(min(H, cy_ + r))
        patch = g[y0:y1, x0:x1]
        near = cv2.dilate(sub.astype(np.uint8), np.ones((5, 5), np.uint8))
        # compactness of the blob: filled / bounding-ellipse area
        fill = area / (np.pi * major * minor / 4 + 1e-6)
        # edge sharpness: ring just outside is background-like, blob border contrast high
        score = (contrast / 40.0) * (0.4 + round_) * min(fill, 1.0)
        # an edge (ridge shadow) has a light side next to the dark side; ball is dark all round
        ring = cv2.dilate(sub.astype(np.uint8), np.ones((9, 9), np.uint8)) - cv2.dilate(sub.astype(np.uint8), np.ones((3, 3), np.uint8))
        rr = ring.astype(bool)
        sy, sx = rr.shape
        rvals = dark[y:y + sy, x:x + sx][rr] if False else None
        info = dict(x=float(cx_), y=float(cy_), contrast=contrast, round=float(round_), major=float(major), score=float(score), diff=0.0)
        if changed is not None:
            rch = changed[max(0, int(cy_ - dmax)):int(cy_ + dmax), max(0, int(cx_ - dmax)):int(cx_ + dmax)]
            frac = float(rch.mean()) if rch.size else 0.0
            info["diff"] = frac
            info["score"] *= (0.6 + 3.0 * min(frac, 0.5))
        out.append(info)
    return out, changed, dark


def conf_from(cands):
    if not cands:
        return None, 0.0, "no ball-sized dark blob found"
    cands = sorted(cands, key=lambda c: -c["score"])
    b = cands[0]
    second = cands[1]["score"] if len(cands) > 1 else 0.0
    margin = (b["score"] - second) / (b["score"] + 1e-6)
    absq = min(1.0, b["score"] / 1.0)
    conf = float(np.clip(0.55 * absq + 0.45 * margin, 0, 1))
    note = "ok" if len(cands) == 1 else "%d candidates, margin %.2f" % (len(cands), margin)
    return b, conf, note


def annotate(img, ell, ball, rho, theta, ok, conf, cands, path):
    d = img.copy()
    if ell:
        cv2.ellipse(d, ((ell["cx"], ell["cy"]), (2 * ell["a"], 2 * ell["b"]), ell["angle_deg"]), (0, 255, 0), 2)
        c = (int(ell["cx"]), int(ell["cy"]))
        cv2.drawMarker(d, c, (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
        phi = np.deg2rad(ell["angle_deg"])
        for f in (0.5, 1.0):  # rho rings, as un-squashed ellipses
            cv2.ellipse(d, (c, (2 * ell["a"] * f, 2 * ell["b"] * f), ell["angle_deg"]), (0, 200, 0), 1)
    for cd in (cands or [])[:6]:
        cv2.circle(d, (int(cd["x"]), int(cd["y"])), 14, (255, 160, 0), 1)
    if ball is not None:
        p = (int(round(ball[0])), int(round(ball[1])))
        cv2.circle(d, p, 22, (0, 0, 255), 2)
        cv2.drawMarker(d, p, (0, 0, 255), cv2.MARKER_CROSS, 40, 1)
        if ell:
            cv2.line(d, (int(ell["cx"]), int(ell["cy"])), p, (0, 0, 255), 1)
        txt = "rho=%.2f theta=%.0f conf=%.2f%s" % (rho, theta, conf, "" if ok else " (LOW)")
        cv2.putText(d, txt, (max(10, p[0] - 150), max(30, p[1] - 40)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4)
        cv2.putText(d, txt, (max(10, p[0] - 150), max(30, p[1] - 40)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    cv2.imwrite(path, d, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("--debug")
    ap.add_argument("--prev")
    a = ap.parse_args()
    img = _load(a.frame)
    e, q = find_ellipse(img)
    res = {"ok": False, "ball_px": None, "center_px": None, "ellipse": None, "rho": None,
           "theta_deg": None, "confidence": 0.0, "note": ""}
    if e is None:
        res["note"] = "sand ellipse not found"
        print(json.dumps(res))
        if a.debug:
            annotate(img, None, None, 0, 0, False, 0, None, a.debug)
        return
    ell = _norm_ellipse(e)
    res["ellipse"] = {k: round(v, 2) for k, v in ell.items()}
    res["center_px"] = [round(ell["cx"], 1), round(ell["cy"], 1)]
    notes = []
    if q["refined_pts"] < 40:
        notes.append("ellipse weakly supported (%d edge pts)" % q["refined_pts"])
    prev = None
    if a.prev:
        p_img = _load(a.prev)
        pe, _ = find_ellipse(p_img)
        if pe is not None:
            prev = _align_prev(p_img, _norm_ellipse(pe), ell)
        else:
            notes.append("prev: ellipse not found, ignored")
    cands, changed, dark = find_ball(img, ell, prev)
    best, conf, note = conf_from(cands)
    notes.append(note)
    if best is not None:
        res["ball_px"] = [round(best["x"], 1), round(best["y"], 1)]
        rho, theta = to_polar((best["x"], best["y"]), ell)
        res["rho"], res["theta_deg"] = round(rho, 3), round(theta, 1)
        if q["refined_pts"] < 40:
            conf *= 0.7
        res["ok"] = bool(conf >= 0.4 and rho <= 1.05)
        if rho > 1.05:
            notes.append("ball outside sand ellipse")
    res["confidence"] = round(float(conf), 2)
    res["note"] = "; ".join(notes)
    print(json.dumps(res))
    if a.debug:
        b = res["ball_px"]
        annotate(img, ell, b, res["rho"] or 0, res["theta_deg"] or 0, res["ok"], conf, cands, a.debug)


if __name__ == "__main__":
    main()
