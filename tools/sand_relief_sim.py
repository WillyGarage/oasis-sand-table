#!/usr/bin/env python3
"""sand_relief_sim - physical height-field simulation of the ball ploughing sand, plus a low ring-light renderer.

Unlike tools/sandsim.py (which paints a fixed groove profile and REPLACES the sand), this moves sand:

  * height grid in mm, sand starts at uniform depth `depth`; the ball (radius `ball_r`) rests on the tray floor.
  * the ball marches along the path in steps of ~ball_r/4. Each step: h = min(h, ball surface) inside the
    footprint; the removed volume is deposited in a ring just outside the footprint, biased to the forward half
    (it is re-ploughed as the ball advances, which leaves side berms naturally); then the local window is relaxed
    to the angle of repose with a few slope-limiting iterations (volume-conserving transfers).
  * volume is conserved exactly (up to float error): `python3 tools/sand_relief_sim.py --selftest`.

Renderer: Lambert shading from the height normals, lit by `n_lights` point lights on the rim a few mm above the
sand (the table's LED ring) with soft cast shadows and distance falloff, plus ambient light scaled by a cavity
(ambient-occlusion) term. `light='dir'` uses one directional light instead, to match our own desk-camera photos.

CALIBRATED SIM (v4, 2026-11-22): Table(kind, mm_px, deposit='real') (or **PHYS_REAL) = physics fitted to phone photos of real sand
(capsule carve, ball r 4.9 mm, normal push, two-angle repose, 0.6 mm track offset), render(light='photo') = phone-photo look,
simulate_parallel(pts_list, erase=0.02, mm_px=0.1) = whole tray in parallel windows. See captures/relief-study/v4/STATUS.md.

Usage (simulation only - this never talks to the table):
    python3 tools/sand_relief_sim.py drawing.thr -o out.png [--table mini|big] [--erase 0.035] [--light ring|dir]
    python3 tools/sand_relief_sim.py --selftest

theta/rho convention as everywhere in this repo (tools/thrcommon.py): x = rho cos(theta), y = rho sin(theta), y up.
"""
import argparse, math, os, sys, time
import numpy as np
from numba import njit, prange

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- parameters
# Fitted 2026-11-22 against photos of known drawings on our Mini (lek.thr / raptor.thr on an erase spiral of
# pitch 0.035). See fit notes in the report; the ball diameter is not recorded, so ball_r and depth are fitted.
MINI = dict(r_work=114.0, tray_extra=4.0, mm_px=0.25)
BIG = dict(r_work=420.0, tray_extra=10.0, mm_px=0.5)
PHYS_REAL = dict(ball_r=4.9, depth=0.5, ball_z=0.0, repose_deg=26.0, repose_dyn=16.0, fwd=0.0, lat=0.0, trk_off=0.6, dep_w=0.25,
                 step_frac=0.1, taper=0.6, av_tol=0.01, deposit='real', relax_iter=0)
# v4 calibration (2026-11-22, phone photos): ball_r measured (9.7-10 mm ball); depth = how far the ball bottom sits below the
# smooth sand surface (fitted); trk_off = ball track lies 0.6 mm right of travel (fitted from alternating stroke gaps).
LOOK_REAL = dict(az=0.0, el=35.0, kd=0.35, ka=0.65, sky_mm=2.0, sky_pow=1.5, soft_mm=0.3, gamma=1.0)
PHYS = dict(ball_r=3.2, depth=2.2, repose_deg=32.0, fwd=0.6, dep_w=0.55, relax_iter=6, step_frac=0.25, deposit='ring',
            av_tol=0.03, av_scale=1.0)   # avalanche tolerance (fraction of one cell's repose step) and slope scale; 'push' exact: 0.03, 1.0; fast: 0.5, 0.5


# ---------------------------------------------------------------- numba kernels
@njit(cache=True)
def _relax_window(h, tray, i0, i1, j0, j1, maxd, maxdd, n_it):
    """Gauss-Seidel slope limiting on h[i0:i1, j0:j1]. Every transfer moves sand from one cell to a neighbour, so
    the total is conserved exactly. maxd / maxdd: allowed height step to an axial / diagonal neighbour."""
    for it in range(n_it):
        for i in range(i0, i1):
            for j in range(j0, j1):
                if not tray[i, j]:
                    continue
                for k in range(8):
                    if k == 0: di, dj, md = 0, 1, maxd
                    elif k == 1: di, dj, md = 1, 0, maxd
                    elif k == 2: di, dj, md = 0, -1, maxd
                    elif k == 3: di, dj, md = -1, 0, maxd
                    elif k == 4: di, dj, md = 1, 1, maxdd
                    elif k == 5: di, dj, md = 1, -1, maxdd
                    elif k == 6: di, dj, md = -1, 1, maxdd
                    else: di, dj, md = -1, -1, maxdd
                    a, b = i + di, j + dj
                    if not tray[a, b]:
                        continue
                    ex = h[i, j] - h[a, b] - md
                    if ex > 0.0:
                        m = 0.2 * ex
                        if m > h[i, j]:
                            m = h[i, j]
                        h[i, j] -= m
                        h[a, b] += m


@njit(cache=True)
def _topple(h, tray, inq, qi, qj, i0, i1, j0, j1, maxd, maxdd, tol):
    """Avalanche to the angle of repose, unbounded in space (v3 fix). The windowed sweeps above stop at the window
    edge, so a pile several mm tall (tight combing piles sand at every stroke end) stood as a near-vertical wall
    just outside the window. Here every cell of the window that is steeper than repose (by more than tol mm) spills
    half the excess to its neighbour, and any cell that changed is queued again, wherever it is. Volume-conserving.
    inq: uint8 scratch grid (all 0 on entry and exit); qi, qj: int32 scratch queues of size h.size."""
    n0, n1 = h.shape
    cap = qi.shape[0]
    head = 0; tail = 0; count = 0
    for i in range(i0, i1):
        for j in range(j0, j1):
            if tray[i, j] and inq[i, j] == 0:
                inq[i, j] = 1
                qi[tail] = i; qj[tail] = j; tail = (tail + 1) % cap; count += 1
    while count > 0:
        i = qi[head]; j = qj[head]; head = (head + 1) % cap; count -= 1
        inq[i, j] = 0
        for k in range(8):
            if k == 0: di, dj, md = 0, 1, maxd
            elif k == 1: di, dj, md = 1, 0, maxd
            elif k == 2: di, dj, md = 0, -1, maxd
            elif k == 3: di, dj, md = -1, 0, maxd
            elif k == 4: di, dj, md = 1, 1, maxdd
            elif k == 5: di, dj, md = 1, -1, maxdd
            elif k == 6: di, dj, md = -1, 1, maxdd
            else: di, dj, md = -1, -1, maxdd
            a, b = i + di, j + dj
            if a < 0 or b < 0 or a >= n0 or b >= n1 or not tray[a, b]:
                continue
            ex = h[i, j] - h[a, b] - md
            if ex > tol:
                m = 0.5 * ex
                if m > h[i, j]:
                    m = h[i, j]
                h[i, j] -= m
                h[a, b] += m
                if inq[a, b] == 0 and count < cap - 2:
                    inq[a, b] = 1; qi[tail] = a; qj[tail] = b; tail = (tail + 1) % cap; count += 1
                if inq[i, j] == 0 and count < cap - 2:
                    inq[i, j] = 1; qi[tail] = i; qj[tail] = j; tail = (tail + 1) % cap; count += 1


@njit(cache=True)
def _topple_flat(hf, tf, inqf, qf, n1, i0, i1, j0, j1, maxd, maxdd, tol):
    """Same avalanche as _topple (same visiting order, same result) on flat views, with the neighbour offsets
    precomputed and no per-neighbour bounds tests. Needs the outermost rows/columns of the grid to be outside the
    tray (checked by _march). hf, tf, inqf: h, tray, inq raveled; qf: int32 queue of size h.size + 1024."""
    cap = qf.shape[0]
    off = np.array([1, n1, -1, -n1, n1 + 1, n1 - 1, 1 - n1, -n1 - 1])
    mdv = np.array([maxd, maxd, maxd, maxd, maxdd, maxdd, maxdd, maxdd])
    head = 0; tail = 0; count = 0
    for i in range(i0, i1):
        for j in range(j0, j1):
            c = i * n1 + j
            if tf[c] and inqf[c] == 0:
                inqf[c] = 1
                qf[tail] = c; tail += 1
                if tail == cap: tail = 0
                count += 1
    lim = cap - 2
    while count > 0:
        c = qf[head]; head += 1
        if head == cap: head = 0
        count -= 1
        inqf[c] = 0
        for k in range(8):
            a = c + off[k]
            if not tf[a]:
                continue
            ex = hf[c] - hf[a] - mdv[k]
            if ex > tol:
                m = 0.5 * ex
                if m > hf[c]:
                    m = hf[c]
                hf[c] -= m
                hf[a] += m
                if inqf[a] == 0 and count < lim:
                    inqf[a] = 1; qf[tail] = a; tail += 1
                    if tail == cap: tail = 0
                    count += 1
                if inqf[c] == 0 and count < lim:
                    inqf[c] = 1; qf[tail] = c; tail += 1
                    if tail == cap: tail = 0
                    count += 1


@njit(cache=True)
def _carve_deposit(h, tray, cx, cy, dx, dy, rp, R, px, dwp, fwd):
    """Carve the ball footprint at (cx, cy) px, put the removed volume in the ring rp..rp+dwp px, forward-biased.
    Returns the volume moved (mm * px^2)."""
    n0, n1 = h.shape
    rr = rp + dwp + 1.0
    i0 = max(1, int(cy - rr)); i1 = min(n0 - 1, int(cy + rr) + 2)
    j0 = max(1, int(cx - rr)); j1 = min(n1 - 1, int(cx + rr) + 2)
    removed = 0.0
    for i in range(i0, i1):
        for j in range(j0, j1):
            ddx = j - cx; ddy = i - cy
            d2 = ddx * ddx + ddy * ddy
            if d2 < rp * rp:
                dm2 = d2 * px * px
                zb = R - math.sqrt(max(R * R - dm2, 0.0))
                if h[i, j] > zb:
                    removed += h[i, j] - zb
                    h[i, j] = zb
    if removed <= 0.0:
        return 0.0
    wsum = 0.0
    for i in range(i0, i1):
        for j in range(j0, j1):
            if not tray[i, j]:
                continue
            ddx = j - cx; ddy = i - cy
            d = math.sqrt(ddx * ddx + ddy * ddy)
            if d >= rp and d < rp + dwp:
                c = (ddx * dx + ddy * dy) / max(d, 1e-6)
                w = 1.0 + fwd * c
                if w > 0:
                    # taper across the ring: most sand right at the ball's edge
                    w *= 1.0 - 0.6 * (d - rp) / dwp
                    wsum += w
    if wsum <= 0.0:
        # nowhere to put it (cannot happen inside the tray); put it back
        return 0.0
    for i in range(i0, i1):
        for j in range(j0, j1):
            if not tray[i, j]:
                continue
            ddx = j - cx; ddy = i - cy
            d = math.sqrt(ddx * ddx + ddy * ddy)
            if d >= rp and d < rp + dwp:
                c = (ddx * dx + ddy * dy) / max(d, 1e-6)
                w = 1.0 + fwd * c
                if w > 0:
                    w *= 1.0 - 0.6 * (d - rp) / dwp
                    h[i, j] += removed * w / wsum
    return removed


@njit(cache=True)
def _carve_push(h, tray, cx, cy, dx, dy, rp, R, px, dwp, fwd):
    """Deposit rule 'push' (2026-11-22, v3): the sphere pushes sand along its surface normal, so the sand removed at
    bearing phi from the ball centre is put back in the ring just outside the footprint AT THE SAME BEARING (32
    bearing bins, smoothed over the neighbouring bins), instead of being spread round the whole ring. A ball
    cutting a thin crescent on one side (tight combing) therefore piles sand on that side and ahead of it, not on
    the already-combed side behind it. `fwd` adds a mild forward lean (the moving ball drags the sand along).
    Volume is conserved exactly. Returns the volume moved (mm * px^2)."""
    NB = 32
    n0, n1 = h.shape
    rr = rp + dwp + 1.0
    i0 = max(1, int(cy - rr)); i1 = min(n0 - 1, int(cy + rr) + 2)
    j0 = max(1, int(cx - rr)); j1 = min(n1 - 1, int(cx + rr) + 2)
    rem = np.zeros(NB)
    removed = 0.0
    for i in range(i0, i1):
        for j in range(j0, j1):
            ddx = j - cx; ddy = i - cy
            d2 = ddx * ddx + ddy * ddy
            if d2 < rp * rp:
                dm2 = d2 * px * px
                zb = R - math.sqrt(max(R * R - dm2, 0.0))
                if h[i, j] > zb:
                    v = h[i, j] - zb
                    removed += v
                    h[i, j] = zb
                    # bearing of the pushed sand: radial, leaned towards the direction of travel
                    d = math.sqrt(d2) + 1e-6
                    ux = ddx / d + fwd * dx; uy = ddy / d + fwd * dy
                    a = math.atan2(uy, ux)
                    b = int((a + math.pi) / (2 * math.pi) * NB) % NB
                    rem[b] += 0.5 * v
                    rem[(b + 1) % NB] += 0.25 * v
                    rem[(b - 1) % NB] += 0.25 * v
    if removed <= 0.0:
        return 0.0
    wb = np.zeros(NB)
    for i in range(i0, i1):
        for j in range(j0, j1):
            if not tray[i, j]:
                continue
            ddx = j - cx; ddy = i - cy
            d = math.sqrt(ddx * ddx + ddy * ddy)
            if d >= rp and d < rp + dwp:
                b = int((math.atan2(ddy, ddx) + math.pi) / (2 * math.pi) * NB) % NB
                wb[b] += 1.0 - 0.6 * (d - rp) / dwp
    # bins with no room (tray wall) hand their sand to the whole ring
    spill = 0.0
    wtot = 0.0
    for b in range(NB):
        if wb[b] <= 0.0:
            spill += rem[b]; rem[b] = 0.0
        else:
            wtot += wb[b]
    if wtot <= 0.0:
        return 0.0
    for i in range(i0, i1):
        for j in range(j0, j1):
            if not tray[i, j]:
                continue
            ddx = j - cx; ddy = i - cy
            d = math.sqrt(ddx * ddx + ddy * ddy)
            if d >= rp and d < rp + dwp:
                b = int((math.atan2(ddy, ddx) + math.pi) / (2 * math.pi) * NB) % NB
                w = 1.0 - 0.6 * (d - rp) / dwp
                h[i, j] += w * (rem[b] / wb[b] + spill / wtot)
    return removed


@njit(cache=True)
def _march(h, tray, xs, ys, rp, R, px, dwp, fwd, maxd, maxdd, n_it, mode=0, tolm=0.03, sc=1.0):
    """mode 0: the v2 'ring' deposit rule (_carve_deposit), windowed relaxation only; mode 1: the v3 'push' rule
    (_carve_push) plus the unbounded avalanche (_topple)."""
    n0, n1 = h.shape
    dx, dy = 1.0, 0.0
    moved = 0.0
    rr = rp + dwp + 3.0
    inq = np.zeros((n0, n1), np.uint8)
    qi = np.zeros(n0 * n1 // 4 + 1024, np.int32); qj = np.zeros(n0 * n1 // 4 + 1024, np.int32)
    edge_ok = not (tray[0, :].any() or tray[n0 - 1, :].any() or tray[:, 0].any() or tray[:, n1 - 1].any())
    hf = h.ravel(); tf = tray.ravel(); inqf = inq.ravel()
    qf = np.zeros(n0 * n1 + 1024, np.int32)
    tol = tolm * maxd
    for k in range(len(xs)):
        if k > 0:
            ex = xs[k] - xs[k - 1]; ey = ys[k] - ys[k - 1]
            L = math.sqrt(ex * ex + ey * ey)
            if L > 1e-9:
                dx = ex / L; dy = ey / L
        cx, cy = xs[k], ys[k]
        if mode == 1:
            moved += _carve_push(h, tray, cx, cy, dx, dy, rp, R, px, dwp, fwd)
        else:
            moved += _carve_deposit(h, tray, cx, cy, dx, dy, rp, R, px, dwp, fwd)
        i0 = max(1, int(cy - rr)); i1 = min(n0 - 1, int(cy + rr) + 2)
        j0 = max(1, int(cx - rr)); j1 = min(n1 - 1, int(cx + rr) + 2)
        _relax_window(h, tray, i0, i1, j0, j1, maxd, maxdd, n_it)
        if mode == 1:
            if edge_ok:
                _topple_flat(hf, tf, inqf, qf, n1, i0, i1, j0, j1, maxd * sc, maxdd * sc, tol)
            else:
                _topple(h, tray, inq, qi, qj, i0, i1, j0, j1, maxd, maxdd, tol)
        # relaxation may have let sand slide under the ball: push it out again (no relax, next step handles it)
        if mode == 1:
            _carve_push(h, tray, cx, cy, dx, dy, rp, R, px, dwp, fwd)
        else:
            _carve_deposit(h, tray, cx, cy, dx, dy, rp, R, px, dwp, fwd)
    return moved



# ---------------------------------------------------------------- deposit 'real' (v4, calibrated on phone photos)
@njit(cache=True)
def _avalanche_real(hf, tf, fpf, inqf, qf, n1, i0, i1, j0, j1, md_s, mdd_s, md_d, mdd_d, tol):
    """Local avalanche with TWO angles. A cell stays put while its drop to every neighbour is below the STATIC limit
    (md_s axial, mdd_s diagonal, mm per cell); once a drop exceeds it by `tol`, the sand slides until that drop equals
    the DYNAMIC limit (md_d, mdd_d). Only cells near the ball are seeded; changed cells are queued again.
    Cells under the ball (fpf == 1) neither give nor receive. Volume conserved. Edge rows/cols must be non-tray."""
    cap = qf.shape[0]
    off = np.array([1, n1, -1, -n1, n1 + 1, n1 - 1, 1 - n1, -n1 - 1])
    mss = np.array([md_s, md_s, md_s, md_s, mdd_s, mdd_s, mdd_s, mdd_s])
    mdd = np.array([md_d, md_d, md_d, md_d, mdd_d, mdd_d, mdd_d, mdd_d])
    head = 0; tail = 0; count = 0
    for i in range(i0, i1):
        for j in range(j0, j1):
            c = i * n1 + j
            if (not tf[c]) or fpf[c] == 1:
                continue
            for k in range(8):
                a = c + off[k]
                if tf[a] and fpf[a] == 0 and hf[c] - hf[a] - mss[k] > tol:
                    inqf[c] = 1; qf[tail] = c; tail += 1
                    if tail == cap: tail = 0
                    count += 1
                    break
    lim = cap - 2
    while count > 0:
        c = qf[head]; head += 1
        if head == cap: head = 0
        count -= 1
        inqf[c] = 0
        for k in range(8):
            a = c + off[k]
            if (not tf[a]) or fpf[a] == 1:
                continue
            d = hf[c] - hf[a]
            if d - mss[k] > tol:
                m = 0.5 * (d - mdd[k])
                if m > hf[c]:
                    m = hf[c]
                if m <= 0.0:
                    continue
                hf[c] -= m
                hf[a] += m
                if inqf[a] == 0 and count < lim:
                    inqf[a] = 1; qf[tail] = a; tail += 1
                    if tail == cap: tail = 0
                    count += 1
                if inqf[c] == 0 and count < lim:
                    inqf[c] = 1; qf[tail] = c; tail += 1
                    if tail == cap: tail = 0
                    count += 1


@njit(cache=True)
def _step_real(h, tray, fp, x0, y0, x1, y1, hx, hy, rp, R, z0, px, dwp, fwd, lat, taper, NB, rem, wb):
    """One ball step: carve the capsule swept from (x0, y0) to (x1, y1) px, push the removed sand outward along the
    ball surface normal (bearing of the cell from the nearest point of the track, leaned forward by `fwd`) into the
    ring rp..rp+dwp round the capsule, same bearing. Marks the footprint in fp (1). Returns (volume moved, i0, i1, j0, j1)."""
    n0, n1 = h.shape
    ex = x1 - x0; ey = y1 - y0
    L2 = ex * ex + ey * ey
    rr = rp + dwp + 1.0
    i0 = max(1, int(min(y0, y1) - rr)); i1 = min(n0 - 1, int(max(y0, y1) + rr) + 2)
    j0 = max(1, int(min(x0, x1) - rr)); j1 = min(n1 - 1, int(max(x0, x1) + rr) + 2)
    for b in range(NB):
        rem[b] = 0.0; wb[b] = 0.0
    removed = 0.0
    R2 = R * R
    for i in range(i0, i1):
        for j in range(j0, j1):
            t = 0.0
            if L2 > 1e-12:
                t = ((j - x0) * ex + (i - y0) * ey) / L2
                if t < 0.0: t = 0.0
                elif t > 1.0: t = 1.0
            qx = x0 + t * ex; qy = y0 + t * ey
            ddx = j - qx; ddy = i - qy
            d2 = ddx * ddx + ddy * ddy
            if d2 < rp * rp:
                fp[i, j] = 1
                dm2 = d2 * px * px
                zb = z0 + R - math.sqrt(max(R2 - dm2, 0.0))
                if tray[i, j] and h[i, j] > zb:
                    v = h[i, j] - zb
                    removed += v
                    h[i, j] = zb
                    d = math.sqrt(d2)
                    if d < 1e-6:
                        ux = hx; uy = hy
                    else:
                        ux = ddx / d; uy = ddy / d
                    a = math.atan2(uy + fwd * hy + lat * hx, ux + fwd * hx - lat * hy)
                    bf = (a + math.pi) / (2 * math.pi) * NB
                    b = int(bf) % NB
                    rem[b] += 0.5 * v
                    rem[(b + 1) % NB] += 0.25 * v
                    rem[(b - 1) % NB] += 0.25 * v
    if removed <= 0.0:
        return 0.0, i0, i1, j0, j1
    for i in range(i0, i1):
        for j in range(j0, j1):
            if not tray[i, j]:
                continue
            t = 0.0
            if L2 > 1e-12:
                t = ((j - x0) * ex + (i - y0) * ey) / L2
                if t < 0.0: t = 0.0
                elif t > 1.0: t = 1.0
            ddx = j - (x0 + t * ex); ddy = i - (y0 + t * ey)
            d = math.sqrt(ddx * ddx + ddy * ddy)
            if d >= rp and d < rp + dwp:
                b = int((math.atan2(ddy, ddx) + math.pi) / (2 * math.pi) * NB) % NB
                wb[b] += 1.0 - taper * (d - rp) / dwp
    spill = 0.0; wtot = 0.0
    for b in range(NB):
        if wb[b] <= 0.0:
            spill += rem[b]; rem[b] = 0.0
        else:
            wtot += wb[b]
    if wtot <= 0.0:
        return 0.0, i0, i1, j0, j1
    for i in range(i0, i1):
        for j in range(j0, j1):
            if not tray[i, j]:
                continue
            t = 0.0
            if L2 > 1e-12:
                t = ((j - x0) * ex + (i - y0) * ey) / L2
                if t < 0.0: t = 0.0
                elif t > 1.0: t = 1.0
            ddx = j - (x0 + t * ex); ddy = i - (y0 + t * ey)
            d = math.sqrt(ddx * ddx + ddy * ddy)
            if d >= rp and d < rp + dwp:
                b = int((math.atan2(ddy, ddx) + math.pi) / (2 * math.pi) * NB) % NB
                w = 1.0 - taper * (d - rp) / dwp
                h[i, j] += w * (rem[b] / wb[b] + spill / wtot)
    return removed, i0, i1, j0, j1


@njit(cache=True)
def _march_real(h, tray, xs, ys, hx0, hy0, rp, R, z0, px, dwp, fwd, lat, off_px, taper, tan_s, tan_d, tol_mm, marg_px):
    """Ball along the polyline (xs, ys) px with the v4 physics: capsule carve, normal push, two-angle avalanche."""
    n0, n1 = h.shape
    NB = 24
    fp = np.zeros((n0, n1), np.uint8)
    inq = np.zeros((n0, n1), np.uint8)
    qf = np.zeros(n0 * n1 + 1024, np.int32)
    rem = np.zeros(NB); wb = np.zeros(NB)
    hf = h.ravel(); tf = tray.ravel(); fpf = fp.ravel(); inqf = inq.ravel()
    md_s = tan_s * px; mdd_s = md_s * math.sqrt(2.0)
    md_d = tan_d * px; mdd_d = md_d * math.sqrt(2.0)
    hx, hy = hx0, hy0
    moved = 0.0
    ox0 = 0.0; oy0 = 0.0
    for k in range(len(xs)):
        k0 = k - 1 if k > 0 else 0
        ex = xs[k] - xs[k0]; ey = ys[k] - ys[k0]
        L = math.sqrt(ex * ex + ey * ey)
        if L > 1e-9:
            hx = ex / L; hy = ey / L
        ox1 = -hy * off_px; oy1 = hx * off_px                 # the ball's real track lies off_px to the right of the commanded one
        if k == 0:
            ox0 = ox1; oy0 = oy1
        x0 = xs[k0] + ox0; y0 = ys[k0] + oy0; x1 = xs[k] + ox1; y1 = ys[k] + oy1
        ox0 = ox1; oy0 = oy1
        v, i0, i1, j0, j1 = _step_real(h, tray, fp, x0, y0, x1, y1, hx, hy, rp, R, z0, px, dwp, fwd, lat, taper, NB, rem, wb)
        moved += v
        ia = max(1, i0 - int(marg_px)); ib = min(n0 - 1, i1 + int(marg_px))
        ja = max(1, j0 - int(marg_px)); jb = min(n1 - 1, j1 + int(marg_px))
        _avalanche_real(hf, tf, fpf, inqf, qf, n1, ia, ib, ja, jb, md_s, mdd_s, md_d, mdd_d, tol_mm)
        for i in range(i0, i1):
            for j in range(j0, j1):
                fp[i, j] = 0
    return moved


@njit(parallel=True, cache=True)
def _shade(h, tray, nx, ny, nz, lights, px, max_t, soft, fall0, out):
    """lights: (L, 5) rows x_px, y_px, z_mm, power, directional(0/1; then x,y = unit dir, z = tan(elevation))."""
    n0, n1 = h.shape
    for i in prange(n0):
        for j in range(n1):
            if not tray[i, j]:
                continue
            acc = 0.0
            h0 = h[i, j]
            for l in range(lights.shape[0]):
                if lights[l, 4] > 0.5:
                    ux = lights[l, 0]; uy = lights[l, 1]; tanel = lights[l, 2]
                    D = 1e9
                    fall = 1.0
                else:
                    ux = lights[l, 0] - j; uy = lights[l, 1] - i
                    Dp = math.sqrt(ux * ux + uy * uy)
                    if Dp < 1e-6:
                        continue
                    ux /= Dp; uy /= Dp
                    D = Dp * px
                    tanel = (lights[l, 2] - h0) / D
                    fall = 1.0 / (1.0 + (D / fall0)) ** 2
                # Lambert with the light vector (ux, uy, tanel) normalised; image rows grow downwards
                lx, ly, lz = ux, -uy, tanel
                ln = math.sqrt(lx * lx + ly * ly + lz * lz)
                ndl = (nx[i, j] * lx + ny[i, j] * ly + nz[i, j] * lz) / ln
                if ndl <= 0.0:
                    continue
                # soft cast shadow: how far below the light ray the terrain stays along the way to the light
                vis = 1.0
                tmax = min(max_t, D / px)
                t = 1.0
                while t < tmax:
                    a = int(i + uy * t + 0.5); b = int(j + ux * t + 0.5)
                    if a < 0 or b < 0 or a >= n0 or b >= n1:
                        break
                    if tray[a, b]:
                        ray = h0 + tanel * t * px
                        m = (ray - h[a, b]) / soft + 1.0
                        if m < vis:
                            vis = m
                            if vis <= 0.0:
                                vis = 0.0
                                break
                    t += 1.0 if t < 12 else 2.0
                acc += lights[l, 3] * fall * ndl * vis
            out[i, j] = acc


@njit(parallel=True, cache=True)
def _skyvis(h, tray, px, reach_px, out):
    """Fraction of the overhead sky each point sees (light scattered down from the glass cover): 16 azimuths, the
    highest horizon within reach_px; visibility per azimuth = 1 - sin(horizon angle)."""
    n0, n1 = h.shape
    for i in prange(n0):
        for j in range(n1):
            if not tray[i, j]:
                continue
            h0 = h[i, j]
            acc = 0.0
            for k in range(16):
                a = 2.0 * math.pi * k / 16.0
                ux = math.cos(a); uy = math.sin(a)
                best = 0.0
                t = 1.0
                while t <= reach_px:
                    ai = int(i + uy * t + 0.5); bj = int(j + ux * t + 0.5)
                    if ai < 0 or bj < 0 or ai >= n0 or bj >= n1 or not tray[ai, bj]:
                        break
                    s = (h[ai, bj] - h0) / (t * px)
                    if s > best:
                        best = s
                    t += 1.0
                acc += 1.0 - best / math.sqrt(1.0 + best * best)
            out[i, j] = acc / 16.0


# ---------------------------------------------------------------- the table
def _merge_phys(phys):
    p = dict(PHYS)
    if phys.get('deposit') == 'real':
        p.update(PHYS_REAL)
    p.update(phys)
    return p


class Table:
    def __init__(self, kind='mini', mm_px=None, **phys):
        g = dict(MINI if kind == 'mini' else BIG)
        if mm_px: g['mm_px'] = mm_px
        self.kind = kind
        self.r_work, self.px = g['r_work'], g['mm_px']
        self.p = _merge_phys(phys)
        self.r_tray = self.r_work + g['tray_extra']
        self.N = int(math.ceil(2 * (self.r_tray + 2) / self.px)) | 1
        c = self.N / 2.0
        yy, xx = np.mgrid[0:self.N, 0:self.N]
        self.rr = np.hypot((xx + 0.5 - c) * self.px, (yy + 0.5 - c) * self.px)
        self.tray = self.rr <= self.r_tray
        self.h = np.where(self.tray, self.p['depth'], 0.0).astype(np.float64)
        self.c = c

    # ---- geometry
    def to_px(self, x_mm, y_mm):
        return self.c + x_mm / self.px - 0.5, self.c - y_mm / self.px - 0.5

    def path_px(self, pts):
        """theta/rho (N,2) -> densified pixel coords; straight lines in theta-rho as the table moves."""
        pts = np.asarray(pts, float)
        th, r = pts[:, 0], np.clip(pts[:, 1], 0, 1)
        step = self.p['ball_r'] * self.p['step_frac']
        dth, dr = np.diff(th), np.diff(r)
        rm = np.maximum(r[:-1], r[1:])
        L = np.hypot(rm * dth, dr) * self.r_work
        n = np.maximum(1, np.ceil(L / step).astype(int))
        seg = np.repeat(np.arange(len(n)), n)
        first = np.cumsum(n) - n
        s = (np.arange(len(seg)) - first[seg]) / n[seg]
        T = np.r_[th[seg] + s * dth[seg], th[-1]]
        Rr = np.r_[r[seg] + s * dr[seg], r[-1]] * self.r_work
        return self.to_px(Rr * np.cos(T), Rr * np.sin(T))

    # ---- physics
    def run(self, pts):
        """Drag the ball along a theta/rho path. Parts of the path outside the grid are skipped (a window table
        only simulates what happens inside it); the pieces inside run in order."""
        xs, ys = self.path_px(pts)
        xs = xs.astype(np.float64); ys = ys.astype(np.float64)
        p = self.p
        rp = p['ball_r'] / self.px
        dwp = max(1.5, p['dep_w'] * p['ball_r'] / self.px)
        tn = math.tan(math.radians(p['repose_deg']))
        maxd, maxdd = tn * self.px, tn * self.px * math.sqrt(2)
        m = rp + dwp + 4.0
        n0, n1 = self.h.shape
        inside = (xs > -m) & (xs < n1 + m) & (ys > -m) & (ys < n0 + m)
        idx = np.flatnonzero(inside)
        moved = 0.0
        if len(idx) == 0:
            return 0.0
        for piece in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
            a = piece[0]
            if p['deposit'] == 'real':
                hx0, hy0 = 1.0, 0.0
                if a > 0:
                    ex, ey = xs[a] - xs[a - 1], ys[a] - ys[a - 1]
                    L = math.hypot(ex, ey)
                    if L > 1e-9: hx0, hy0 = ex / L, ey / L
                moved += self._march_piece(xs[a:piece[-1] + 1], ys[a:piece[-1] + 1], rp, dwp, maxd, maxdd, hx0, hy0)
            else:
                a = max(a - 1, 0)                          # one earlier point gives the heading at the piece start
                moved += self._march_piece(xs[a:piece[-1] + 1], ys[a:piece[-1] + 1], rp, dwp, maxd, maxdd)
        return moved

    def _march_piece(self, xs, ys, rp, dwp, maxd, maxdd, hx0=1.0, hy0=0.0):
        p = self.p
        if p['deposit'] == 'real':
            pd = dict(PHYS_REAL, **{k: v for k, v in p.items() if k in PHYS_REAL})
            return _march_real(self.h, self.tray, np.ascontiguousarray(xs), np.ascontiguousarray(ys), hx0, hy0, rp, p['ball_r'], float(pd['ball_z']), self.px, dwp, float(pd['fwd']), float(pd['lat']), float(pd['trk_off']) / self.px,
                               float(pd['taper']), math.tan(math.radians(pd['repose_deg'])),
                               math.tan(math.radians(pd['repose_dyn'])), float(pd['av_tol']), 3.0 / self.px * 1.0)
        return _march(self.h, self.tray, xs, ys, rp, p['ball_r'], self.px, dwp, p['fwd'], maxd, maxdd,
                      int(p['relax_iter']), 1 if p['deposit'] == 'push' else 0, float(p['av_tol']), float(p['av_scale']))

    def erase(self, pitch_frac=0.035, outward=True):
        """The table's erase: an Archimedean spiral centre -> rim (rho = pitch * turns)."""
        turns = 1.0 / pitch_frac
        n = int(turns * 360)
        t = np.linspace(0, turns * 2 * math.pi, n)
        pts = np.c_[t, t / (turns * 2 * math.pi)]
        if not outward:
            pts = pts[::-1]
        self.run(pts)

    def volume(self):
        return float(self.h[self.tray].sum() * self.px * self.px)

    # ---- rendering
    def render(self, light='ring', n_lights=16, light_h=4.0, exposure=1.0, ambient=0.10, ao=0.9,
               dir_az=160.0, dir_el=14.0, tint=(0.93, 0.96, 1.0), out_px=None, crop=1.0, fall0=35.0, direct=0.6, sky=1.6, sky_mm=4.0, gamma=0.8, soft_mm=0.45):
        """light='ring': n_lights point lights on the tray wall light_h mm above the sand surface (the LED ring).
        light='dir': one directional light from azimuth dir_az (deg, 0 = +x, CCW) at elevation dir_el (deg)."""
        if light == 'photo':
            return self.render_photo(out_px=out_px, crop=crop, **dict(LOOK_REAL))
        from scipy.ndimage import gaussian_filter
        h = gaussian_filter(self.h, max(0.5, soft_mm / self.px))   # grain-scale smoothing of what the eye sees
        gy, gx = np.gradient(h, self.px)
        # image rows grow downwards: world dz/dy = -gy
        nz = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
        nx, ny = -gx * nz, gy * nz
        if light == 'ring':
            ang = np.arange(n_lights) * 2 * math.pi / n_lights + 0.1
            lx, ly = self.to_px(self.r_tray * np.cos(ang), self.r_tray * np.sin(ang))
            L = np.c_[lx, ly, np.full(n_lights, self.p['depth'] + light_h), np.full(n_lights, 1.0), np.zeros(n_lights)]
            norm = 6.0 / n_lights
        else:
            a, e = math.radians(dir_az), math.radians(dir_el)
            L = np.array([[math.cos(a), -math.sin(a), math.tan(e), 1.0, 1.0]])
            norm = 1.0
        out = np.zeros_like(h)
        _shade(h, self.tray, nx, ny, nz, L.astype(np.float64), self.px, 28.0 / self.px, 0.10, fall0 * (self.r_work / 114.0), out)
        # cavity: below the local mean height (trough floors) gets less ambient light
        mean = gaussian_filter(h, 1.6 / self.px)
        cav = np.clip(1.0 - ao * np.clip(mean - h, 0, None) / max(self.p['depth'], 0.3), 0.15, 1.0)
        v = direct * norm * out + ambient * cav
        if sky:
            sv = np.zeros_like(h)
            _skyvis(h, self.tray, self.px, sky_mm / self.px, sv)
            v = v + sky * sv ** 2
        v = v * exposure
        img = 1.0 - np.exp(-1.6 * v)                       # soft tone curve
        img = np.clip(img, 0, 1) ** (1 / gamma)
        rgb = img[..., None] * np.array(tint)[None, None, :]
        # tray wall (bright diffuser) and outside (dark)
        wall = (self.rr > self.r_tray) & (self.rr <= self.r_tray + 2.5)
        rgb[wall] = np.array([0.97, 0.98, 1.0])
        rgb[self.rr > self.r_tray + 2.5] = 0.06
        out8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        from PIL import Image
        im = Image.fromarray(out8)
        if crop < 1.0 or True:
            half = (self.r_tray + 2.5) / self.px * crop
            im = im.crop((int(self.c - half), int(self.c - half), int(self.c + half), int(self.c + half)))
        if out_px:
            im = im.resize((out_px, out_px), Image.LANCZOS)
        return im

    def render_photo(self, az=0.0, el=35.0, kd=0.45, ka=0.55, sky_mm=2.0, sky_pow=1.5, soft_mm=0.2, gamma=1.0,
                     out_px=None, crop=1.0, tint=(1.0, 1.0, 1.0), **_ignored):
        """Phone-photo look (calibrated 2026-11-22 on real sand): mostly diffuse light - an overhead sky term damped by a
        small-scale sky-visibility (crease/cavity darkening, reach sky_mm) plus one directional light (az degrees from +x,
        CCW, the direction the light comes from; el degrees above the horizon) on the slopes. Returns a PIL image."""
        from scipy.ndimage import gaussian_filter
        h = gaussian_filter(self.h, max(0.5, soft_mm / self.px))
        gy, gx = np.gradient(h, self.px)
        nz = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
        nx, ny = -gx * nz, gy * nz            # world normal (x right, y up): image rows grow downwards
        a, e = math.radians(az), math.radians(el)
        lx, ly, lz = math.cos(a) * math.cos(e), math.sin(a) * math.cos(e), math.sin(e)
        ndl = np.clip(nx * lx + ny * ly + nz * lz, 0, None) / math.sin(e)
        sv = np.zeros_like(h)
        _skyvis(h, self.tray, self.px, sky_mm / self.px, sv)
        v = kd * ndl * np.clip(0.4 + 0.6 * sv, 0, 1) + ka * sv ** sky_pow * (0.5 + 0.5 * nz)
        img = np.clip(v / 1.1, 0, 1) ** (1 / gamma)
        rgb = img[..., None] * np.array(tint)[None, None, :]
        rgb[~self.tray] = 0.06
        out8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
        from PIL import Image
        im = Image.fromarray(out8)
        half = (self.r_tray + 2.5) / self.px * crop
        im = im.crop((int(self.c - half), int(self.c - half), int(self.c + half), int(self.c + half)))
        if out_px:
            im = im.resize((out_px, out_px), Image.LANCZOS)
        return im

    def render_win_photo(self, **kw):
        crop = (self.N / 2.0 * self.px) / (self.r_tray + 2.5)
        return self.render_photo(crop=crop, **kw)




class WindowTable(Table):
    """A square window of the tray (centre cx, cy mm; size mm) at mm_px. Paths and erases are clipped to it.
    Rendering the window: render_win(). Same physics as Table (the preset is chosen with **phys)."""
    def __init__(self, cx=0.0, cy=0.0, size=None, mm_px=0.1, kind='mini', **phys):
        g = dict(MINI if kind == 'mini' else BIG)
        self.kind = kind
        self.r_work, self.px = g['r_work'], mm_px
        self.p = _merge_phys(phys)
        self.r_tray = self.r_work + g['tray_extra']
        self.cx, self.cy = cx, cy
        size = size or 2 * (self.r_tray + 3)
        self.N = int(math.ceil(size / mm_px)) | 1
        self.c = self.N / 2.0
        yy, xx = np.mgrid[0:self.N, 0:self.N]
        wx = cx + (xx + 0.5 - self.c) * mm_px
        wy = cy - (yy + 0.5 - self.c) * mm_px
        self.rr = np.hypot(wx, wy)
        self.tray = self.rr <= self.r_tray
        self.tray[:2, :] = False; self.tray[-2:, :] = False; self.tray[:, :2] = False; self.tray[:, -2:] = False   # wall
        self.h = np.where(self.tray, self.p['depth'], 0.0).astype(np.float64)

    def to_px(self, x_mm, y_mm):
        return self.c + (x_mm - self.cx) / self.px - 0.5, self.c - (y_mm - self.cy) / self.px - 0.5

    def render_win(self, **kw):
        crop = (self.N / 2.0 * self.px) / (self.r_tray + 2.5)
        return self.render(crop=crop, **kw)


# ---------------------------------------------------------------- whole tray in parallel windows
def _tile_job(a):
    cx, cy, size, mm_px, kind, pts_list, erase, erase_outward, phys = a
    T = WindowTable(cx, cy, size, mm_px=mm_px, kind=kind, **phys)
    if erase:
        T.erase(erase, outward=erase_outward)
    for p in pts_list:
        T.run(p)
    return T.h


def simulate_parallel(pts_list, kind='mini', erase=0.0, erase_outward=False, mm_px=0.1, tile_mm=48.0, margin_mm=36.0,
                      procs=10, verbose=False, **phys):
    """Simulate the whole tray as square windows of tile_mm (+ margin_mm each side) run in parallel processes. Each window
    runs the erase spiral and every path piece that falls inside it, in order; only its core (tile_mm square) is kept,
    so the stitched result is exact except for sand that would travel further than margin_mm across a tile edge.
    Returns a full-tray Table with .h filled (volume is conserved per window, not globally across tiles: check .volume())."""
    from multiprocessing import Pool
    t0 = time.time()
    if 'deposit' not in phys:
        phys = dict(phys, deposit='real')
    base = Table(kind, mm_px=mm_px, **phys)
    px = base.px
    if not isinstance(pts_list, (list, tuple)):
        pts_list = [pts_list]
    pts_list = [np.asarray(p, float) for p in pts_list]
    ntile = int(math.ceil(2 * (base.r_tray + 2) / tile_mm))
    size = tile_mm + 2 * margin_mm
    tiles = []
    for ti in range(ntile):
        for tj in range(ntile):
            cx = (-ntile / 2.0 + tj + 0.5) * tile_mm; cy = (ntile / 2.0 - ti - 0.5) * tile_mm
            cx = round(cx / px) * px; cy = round(cy / px) * px
            # skip tiles whose core is wholly outside the tray
            dx = max(abs(cx) - tile_mm / 2, 0); dy = max(abs(cy) - tile_mm / 2, 0)
            if math.hypot(dx, dy) > base.r_tray + 1:
                continue
            tiles.append((cx, cy))
    # heavy tiles first: estimate work by path length (mm) inside the window
    def work(cx, cy):
        w = 0.0
        for p in pts_list:
            r = np.clip(p[:, 1], 0, 1) * base.r_work
            x, y = r * np.cos(p[:, 0]), r * np.sin(p[:, 0])
            m = (np.abs(x - cx) < size / 2) & (np.abs(y - cy) < size / 2)
            w += float(np.hypot(np.diff(x[m]), np.diff(y[m])).sum()) if m.sum() > 1 else 0.0
        if erase:
            w += size * size / (erase * base.r_work)
        return w
    order = sorted(tiles, key=lambda t: -work(*t))
    args = [(cx, cy, size, mm_px, kind, pts_list, erase, erase_outward, phys) for cx, cy in order]
    with Pool(min(procs, len(args))) as pool:
        hs = pool.map(_tile_job, args, chunksize=1)
    for (cx, cy), h in zip(order, hs):
        n = h.shape[0]; cw = n / 2.0
        k = int(round(tile_mm / px)); m0 = (n - k) // 2
        oj = int(round(cx / px + base.c - cw)); oi = int(round(base.c - cw - cy / px))   # window (i, j) -> global (i + oi, j + oj)
        i0, i1 = max(m0, -oi), min(m0 + k, base.N - oi)
        j0, j1 = max(m0, -oj), min(m0 + k, base.N - oj)
        if i1 > i0 and j1 > j0:
            tr = base.tray[i0 + oi:i1 + oi, j0 + oj:j1 + oj]
            base.h[i0 + oi:i1 + oi, j0 + oj:j1 + oj] = np.where(tr, h[i0:i1, j0:j1], 0.0)
    if verbose:
        print('simulate_parallel: %d tiles, %.1f s' % (len(order), time.time() - t0))
    base.elapsed = time.time() - t0
    return base


def simulate(pts_list, kind='mini', erase=0.035, light='ring', out_px=None, **kw):
    """pts_list: one (N,2) theta-rho array or a list carved in order. Returns (Table, PIL image)."""
    t = Table(kind, **{k: v for k, v in kw.items() if k in PHYS or k == 'mm_px'})
    if erase:
        t.erase(erase)
    if not isinstance(pts_list, (list, tuple)):
        pts_list = [pts_list]
    for p in pts_list:
        t.run(p)
    rk = {k: v for k, v in kw.items() if k in ('n_lights', 'light_h', 'exposure', 'ambient', 'ao', 'dir_az', 'dir_el', 'fall0', 'tint', 'direct', 'sky', 'sky_mm', 'gamma', 'soft_mm')}
    return t, t.render(light=light, out_px=out_px, **rk)


# ---------------------------------------------------------------- self tests
def groove_profile(kind='mini', **phys):
    """One straight pass across flat sand; returns (x_mm, h_mm) across the groove and the crest-to-crest width."""
    t = Table(kind, **phys)
    L = 60.0 / t.r_work
    pts = np.array([[math.pi / 2, L], [math.pi / 2, 0.0], [-math.pi / 2, 0.0], [-math.pi / 2, L]])
    # a straight vertical line through the centre (theta flips through rho = 0)
    xs = np.zeros(400); ys = np.linspace(60, -60, 400)
    px, py = t.to_px(xs, ys)
    p = t.p
    tn = math.tan(math.radians(p['repose_deg']))
    _march(t.h, t.tray, px, py, p['ball_r'] / t.px, p['ball_r'], t.px, max(1.5, p['dep_w'] * p['ball_r'] / t.px),
           p['fwd'], tn * t.px, tn * t.px * math.sqrt(2), int(p['relax_iter']))
    row = int(round(t.c))
    prof = t.h[row - 3:row + 4].mean(0)
    x = (np.arange(t.N) + 0.5 - t.c) * t.px
    sel = np.abs(x) < 15
    x, prof = x[sel], prof[sel]
    left, right = x < 0, x > 0
    cl = x[left][np.argmax(prof[left])]; cr = x[right][np.argmax(prof[right])]
    below = x[prof < p['depth'] - 0.05]
    w_level = (below.max() - below.min()) if len(below) else 0.0
    return x, prof, dict(crest_to_crest=cr - cl, width_below_level=w_level, crest_h=float(prof.max() - p['depth']),
                         floor=float(prof.min()))


def selftest():
    t = Table('mini')
    v0 = t.volume()
    t0 = time.time()
    t.erase(0.035)
    v1 = t.volume()
    rng = np.random.default_rng(1)
    pts = np.c_[np.cumsum(rng.normal(0, 0.05, 3000)), np.clip(0.5 + np.cumsum(rng.normal(0, 0.01, 3000)), 0, 1)]
    t.run(pts)
    v2 = t.volume()
    print('volume  start %.3f  after erase %.3f  after random path %.3f mm^3  (rel err %.2e)  %.1fs' % (
        v0, v1, v2, abs(v2 - v0) / v0, time.time() - t0))
    assert abs(v1 - v0) / v0 < 1e-6 and abs(v2 - v0) / v0 < 1e-6, 'volume not conserved'
    assert (t.h >= -1e-9).all(), 'negative sand'
    tr = Table('mini', mm_px=0.25, deposit='real'); vr0 = tr.volume(); tr.erase(0.02); tr.run(pts); vr = tr.volume()
    print('deposit=real: volume rel err %.2e' % (abs(vr - vr0) / vr0))
    assert abs(vr - vr0) / vr0 < 1e-6 and (tr.h >= -1e-9).all(), 'real: volume not conserved'
    x, prof, m = groove_profile()
    print('single pass on flat sand:', {k: round(v, 2) for k, v in m.items()})
    print('selftest OK')


def main():
    import thrcommon as tc
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*')
    ap.add_argument('-o', '--out')
    ap.add_argument('--table', default='mini', choices=['mini', 'big'])
    ap.add_argument('--erase', type=float, default=0.035, help='erase spiral pitch (fraction of radius), 0 = none')
    ap.add_argument('--light', default='ring', choices=['ring', 'dir'])
    ap.add_argument('--size', type=int, default=None)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    t0 = time.time()
    t, im = simulate([tc.read_thr(f) for f in a.files], a.table, a.erase, a.light, out_px=a.size)
    im.save(a.out)
    print('wrote %s (%.1fs)' % (a.out, time.time() - t0))


if __name__ == '__main__':
    main()
