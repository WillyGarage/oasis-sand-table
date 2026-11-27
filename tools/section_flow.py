#!/usr/bin/env python3
"""section_flow - "flow" stroke family for tools/section_comb.py: strokes follow a direction FIELD inside a section instead of
straight lines. SIMULATION/PATH ONLY.

Section keys (mode "flow"):
    "flow": {"file": "x.npz", "key": "thigh_r"}      direction field: arrays "<key>" (deg, 0 = +x, CCW, y up, mod 180; the direction
                                                      the strokes run, i.e. the direction of the ribs) and "<key>__org" = [x0, y_top, px]
                                                      (mm of the array's top-left cell centre and mm per cell; rows go down)
    "spacing": s                                      stroke spacing (mm)
    "flow_w": 0.35                                    weight of the unit-spacing term (default 0.35); "flow_h": 0.4 grid mm

Method. Strokes are level sets of a scalar field phi over the section. With t = stroke direction and n = its normal (signs aligned
by a flood fill so n varies smoothly; orientation is only defined mod 180), phi minimises
        sum |t . grad(phi)|^2  +  w^2 sum (n . grad(phi) - 1)^2
(first term: level curves run along t; second term: neighbouring levels about 1 unit apart). Levels phi = phi0 + k*s are cut out with
marching squares and clipped to the section, so s is the stroke spacing where |grad phi| = 1; where the ribs fan out the spacing opens
up, where they converge it closes (the realised spacing is reported in FLOW_STATS[name]). Consecutive levels are joined at alternating
ends along the section edge by section_comb.build_chains (boustrophedon); a section that is not convex or whose level sets split
falls apart into separate chains there.
"""
import math, os
import numpy as np
import cv2
from collections import deque
from scipy import sparse
from scipy.sparse.linalg import lsmr
from scipy.ndimage import gaussian_filter1d, map_coordinates
from shapely.geometry import LineString, MultiPolygon, Polygon
from skimage import measure

FLOW_STATS = {}
_cache = {}


def load_field(spec):
    key = (spec['file'], spec['key'])
    if key not in _cache:
        z = np.load(spec['file'])
        arr = z[spec['key']].astype(np.float64)
        org = z[spec['key'] + '__org'].astype(np.float64)
        th = np.radians(arr)
        _cache[key] = (np.cos(2 * th), np.sin(2 * th), org)
    return _cache[key]


def sample_orientation(spec, X, Y):
    c2, s2, (x0, ytop, px) = load_field(spec)
    cc = (X - x0) / px
    rr = (ytop - Y) / px
    c = map_coordinates(c2, [rr, cc], order=1, mode='nearest')
    s = map_coordinates(s2, [rr, cc], order=1, mode='nearest')
    return 0.5 * np.arctan2(s, c)


def _align_signs(nx, ny, mask, score):
    """flood fill from the best-scoring cell: flip each cell's normal so it agrees with the already-aligned neighbour"""
    H, W = mask.shape
    done = np.zeros(mask.shape, bool)
    order = np.argsort(-np.where(mask, score, -1).ravel())
    for start in order:
        r0, c0 = divmod(int(start), W)
        if not mask[r0, c0]:
            break
        if done[r0, c0]:
            continue
        done[r0, c0] = True
        dq = deque([(r0, c0)])
        while dq:
            r, c = dq.popleft()
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < H and 0 <= cc < W and mask[rr, cc] and not done[rr, cc]:
                    if nx[r, c] * nx[rr, cc] + ny[r, c] * ny[rr, cc] < 0:
                        nx[rr, cc] *= -1; ny[rr, cc] *= -1
                    done[rr, cc] = True
                    dq.append((rr, cc))
    return nx, ny


def solve_phi(mask, tx, ty, nx, ny, h, w):
    """least-squares phi on the masked grid (x = columns to the right, y = rows going UP, so d/dy = -d/drow)"""
    H, W = mask.shape
    idx = -np.ones(mask.shape, np.int64)
    idx[mask] = np.arange(mask.sum())
    N = int(mask.sum())
    rr, cc = np.nonzero(mask)
    me = idx[rr, cc]

    def op(dr, dc):
        a = np.full(N, -1, np.int64); b = np.full(N, -1, np.int64)
        pr, pc = rr + dr, cc + dc
        mr, mc = rr - dr, cc - dc
        okp = (pr >= 0) & (pr < H) & (pc >= 0) & (pc < W)
        okm = (mr >= 0) & (mr < H) & (mc >= 0) & (mc < W)
        ip = np.where(okp, idx[np.clip(pr, 0, H - 1), np.clip(pc, 0, W - 1)], -1)
        im = np.where(okm, idx[np.clip(mr, 0, H - 1), np.clip(mc, 0, W - 1)], -1)
        both = (ip >= 0) & (im >= 0)
        rows, cols, vals = [], [], []
        k = np.nonzero(both)[0]
        rows += [k, k]; cols += [ip[k], im[k]]; vals += [np.full(len(k), 0.5 / h), np.full(len(k), -0.5 / h)]
        k = np.nonzero(~both & (ip >= 0))[0]
        rows += [k, k]; cols += [ip[k], me[k]]; vals += [np.full(len(k), 1 / h), np.full(len(k), -1 / h)]
        k = np.nonzero(~both & (ip < 0) & (im >= 0))[0]
        rows += [k, k]; cols += [me[k], im[k]]; vals += [np.full(len(k), 1 / h), np.full(len(k), -1 / h)]
        return sparse.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N)).tocsr()

    Gx = op(0, 1)                    # d/dcol  = d/dx
    Gy = -op(1, 0)                   # d/drow = -d/dy  -> d/dy
    dg = lambda v: sparse.diags(v[mask])
    A1 = dg(tx) @ Gx + dg(ty) @ Gy
    A2 = (dg(nx) @ Gx + dg(ny) @ Gy) * w
    A = sparse.vstack([A1, A2]).tocsr()
    b = np.concatenate([np.zeros(N), np.full(N, w)])
    sol = lsmr(A, b, atol=1e-7, btol=1e-7, maxiter=4000)[0]
    phi = np.full(mask.shape, np.nan)
    phi[mask] = sol
    return phi, Gx, Gy


def _smooth(P, sigma_mm=0.8, step=0.3):
    if len(P) < 4:
        return P
    seg = np.hypot(*np.diff(P, axis=0).T)
    s = np.r_[0, np.cumsum(seg)]
    if s[-1] < 1e-6:
        return P
    n = max(4, int(s[-1] / step) + 1)
    t = np.linspace(0, s[-1], n)
    Q = np.c_[np.interp(t, s, P[:, 0]), np.interp(t, s, P[:, 1])]
    sg = sigma_mm / (s[-1] / (n - 1))
    if sg > 0.3:
        Q = np.c_[gaussian_filter1d(Q[:, 0], sg, mode='nearest'), gaussian_filter1d(Q[:, 1], sg, mode='nearest')]
        Q[0], Q[-1] = P[0], P[-1]
    return Q


def strokes_flow(sec, geom, pieces_fn=None):
    from section_comb import _pieces, _polys
    sp = sec['spacing']
    h = sec.get('flow_h', 0.4)
    w = sec.get('flow_w', 0.35)
    gpad = geom.buffer(1.2)
    x0, y0, x1, y1 = gpad.bounds
    W = int((x1 - x0) / h) + 3
    H = int((y1 - y0) / h) + 3
    xs = x0 + np.arange(W) * h
    ys = y1 - np.arange(H) * h
    X, Y = np.meshgrid(xs, ys)
    m8 = np.zeros((H, W), np.uint8)
    for p in _polys(gpad):
        cv2.fillPoly(m8, [np.round(np.c_[(np.array(p.exterior.coords)[:, 0] - x0) / h, (y1 - np.array(p.exterior.coords)[:, 1]) / h]).astype(np.int32)], 1)
        for hole in p.interiors:
            cv2.fillPoly(m8, [np.round(np.c_[(np.array(hole.coords)[:, 0] - x0) / h, (y1 - np.array(hole.coords)[:, 1]) / h]).astype(np.int32)], 0)
    mask = m8 > 0
    if mask.sum() < 20:
        return []
    th = sample_orientation(sec['flow'], X, Y)
    tx, ty = np.cos(th), np.sin(th)
    nx, ny = -ty.copy(), tx.copy()
    dt = cv2.distanceTransform(m8, cv2.DIST_L2, 3)
    nx, ny = _align_signs(nx, ny, mask, dt)
    phi, Gx, Gy = solve_phi(mask, tx, ty, nx, ny, h, w)
    inside = np.zeros((H, W), np.uint8)
    for p in _polys(geom):
        cv2.fillPoly(inside, [np.round(np.c_[(np.array(p.exterior.coords)[:, 0] - x0) / h, (y1 - np.array(p.exterior.coords)[:, 1]) / h]).astype(np.int32)], 1)
    inside = (inside > 0) & mask
    if inside.sum() < 10:
        return []
    # realised spacing
    gxv = (Gx @ phi[mask]); gyv = (Gy @ phi[mask])
    gm = np.full((H, W), np.nan); gm[mask] = np.hypot(gxv, gyv)
    sr = sp / np.maximum(gm[inside], 1e-3)
    FLOW_STATS[sec['name']] = dict(spacing=sp, p5=float(np.percentile(sr, 5)), p50=float(np.median(sr)), p95=float(np.percentile(sr, 95)),
                                   frac_in_0p7_1p4=float(((sr > 0.7 * sp) & (sr < 1.4 * sp)).mean()))
    lo, hi = float(np.nanmin(phi[inside])), float(np.nanmax(phi[inside]))
    levels = list(np.arange(lo + 0.35 + sec.get('phase', 0.0), hi - 0.2, sp))
    if not levels or hi - 0.35 - levels[-1] > 0.4 * sp:
        levels.append(hi - 0.35)
    pm = np.where(mask, phi, np.nanmean(phi))
    out = []
    for k, lv in enumerate(levels):
        cs = measure.find_contours(pm, lv, mask=mask)
        for c in cs:
            P = np.c_[x0 + c[:, 1] * h, y1 - c[:, 0] * h]
            if len(P) < 3:
                continue
            P = _smooth(P)
            for q in _pieces(LineString(P).intersection(geom)):
                out.append(dict(line=k, pts=q, ds=sp * 1.3))
    return out
