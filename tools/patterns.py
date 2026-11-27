#!/usr/bin/env python3
"""patterns - parametric theta-rho generators for the Oasis Mini sand table.

    patterns.py --list
    patterns.py <name> [--param value ...] -o out.thr
    patterns.py --all outdir          # whole library: .thr, manifest.json, previews, contact.png

<name> is a library preset (see --list); --param overrides any generator
argument of that preset (numbers, tuples and True/False are parsed as Python
literals, e.g. --pitch 0.05 --turns 12).

Design rules every generator obeys (enforced in finish()):
  * rho is clamped to 0..1, theta is cumulative (unwrapped, may run backwards
    where a design needs it).
  * Starts at the centre (rho 0) or the rim (rho 1) and ends at the centre or
    the rim, via an automatic smooth lead-in / lead-out spiral if the design
    itself does not already begin/end there. Recorded as start/end in metadata
    so a playlist can chain "ends centre" into "starts centre".
  * At most thrcommon.MAX_POINTS (12000) points. The resampler keeps steps
    under 1.5 deg of theta / 0.01 of rho where the curve needs it, uses
    longer chords only where the (theta,rho) chord stays within 0.0015 rho
    units (about a third of a pixel on a 900px preview) of the true curve, and
    relaxes the step caps (never beyond 3.5 deg) only if the point budget needs it.
  * Line spacing is designed for a groove 4% of the radius wide: neighbouring
    lines are kept >= ~0.035 apart wherever a crisp line is wanted; deliberate
    merging (dense centres, tonal build-up) is a design choice noted per pattern.
  * Randomness only through an explicit `seed`.

Time estimates come from thrcommon.est_seconds (constants live there).
Draw time is dominated by total theta travel: about 36 s per full turn of the
arm at the provisional constants, so ~50 turns is ~30 minutes.
"""
import argparse, ast, json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thrcommon as tc

TAU = 2 * math.pi
DENSE_STEP = math.radians(0.2)     # sampling density of generators' raw curves


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
class Path:
    """Raw dense path plus where it is meant to start/end ('centre' or 'rim')."""
    def __init__(self, th, rho, start, end):
        self.th = np.asarray(th, float)
        self.rho = np.asarray(rho, float)
        self.start, self.end = start, end


def lin(a, b, step=DENSE_STEP):
    n = max(2, int(math.ceil(abs(b - a) / step)) + 1)
    return np.linspace(a, b, n)


def smoothstep(s):
    s = np.clip(s, 0, 1)
    return s * s * (3 - 2 * s)


def xy_to_tr(x, y):
    """Cartesian polyline (dense) -> unwrapped theta, rho."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    rho = np.hypot(x, y)
    th = np.arctan2(y, x)
    bad = rho < 1e-9
    if bad.all():
        return np.zeros_like(rho), rho
    idx = np.where(~bad, np.arange(len(th)), 0)
    idx = np.maximum.accumulate(idx)
    first = np.argmax(~bad)
    idx[:first] = first
    th = np.unwrap(th[idx])
    return th, rho


def dense_xy(x, y, step=0.002):
    """Densify a Cartesian polyline so no gap exceeds `step`."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    seg = np.hypot(np.diff(x), np.diff(y))
    n = np.maximum(1, np.ceil(seg / step).astype(int))
    idx = np.repeat(np.arange(len(seg)), n)
    first = np.cumsum(n) - n
    s = (np.arange(len(idx)) - first[idx] + 1) / n[idx]
    X = np.concatenate([x[:1], x[idx] + s * (x[idx + 1] - x[idx])])
    Y = np.concatenate([y[:1], y[idx] + s * (y[idx + 1] - y[idx])])
    return X, Y


def link(th_a, r_a, th_b, r_b, kind="smooth"):
    """Connecting stretch between two (theta, rho) points (exclusive of ends)."""
    d = abs(th_b - th_a)
    n = max(2, int(d / DENSE_STEP) + 2, int(abs(r_b - r_a) / 0.003) + 2)
    s = np.linspace(0, 1, n)[1:-1]
    e = smoothstep(s) if kind == "smooth" else s
    return th_a + s * (th_b - th_a), r_a + e * (r_b - r_a)


def chain(parts):
    """Join (theta, rho) parts: each later part's theta is shifted by a multiple
    of 2pi so its first point sits closest (in theta) to the previous end, and a
    smooth link is inserted between them."""
    th_all, r_all = [parts[0][0]], [parts[0][1]]
    for th, r in parts[1:]:
        last_t, last_r = th_all[-1][-1], r_all[-1][-1]
        k = round((last_t - th[0]) / TAU)
        th = th + k * TAU
        if abs(th[0] - last_t) > 1e-6 or abs(r[0] - last_r) > 1e-4:
            lt, lr = link(last_t, last_r, th[0], r[0])
            th_all.append(lt); r_all.append(lr)
        th_all.append(th); r_all.append(r)
    return np.concatenate(th_all), np.concatenate(r_all)


def _lead(th0, r0, target, sgn, into):
    """Spiral from `target` radius to (th0, r0) (into=True) or the reverse."""
    gap = abs(r0 - target)
    turns = 0.3 + 1.3 * gap
    n = int(turns * TAU / DENSE_STEP) + 2
    s = np.linspace(0, 1, n)
    e = smoothstep(s)
    if into:    # runs target -> r0, theta ends at th0
        return th0 - sgn * turns * TAU * (1 - s), target + (r0 - target) * e
    return th0 + sgn * turns * TAU * s, r0 + (target - r0) * e


def _direction(th):
    d = th[min(len(th) - 1, 50)] - th[0]
    return 1.0 if d >= 0 else -1.0


def resample(th, rho, tol=0.0015, cap_t=tc.MAX_DTHETA, cap_r=tc.MAX_DRHO):
    """Greedy longest-chord simplification in (theta, rho) space.
    A chord from sample i to j is accepted if dtheta <= cap_t, drho <= cap_r and
    every skipped sample lies within `tol` (Cartesian) of the chord."""
    th = np.asarray(th); rho = np.asarray(rho)
    d = np.maximum(np.abs(np.diff(th)) / cap_t, np.abs(np.diff(rho)) / cap_r)
    u = np.concatenate([[0], np.cumsum(d)])
    x, y = rho * np.cos(th), rho * np.sin(th)
    n = len(th)
    keep = [0]
    i = 0
    while i < n - 1:
        # farthest j with (theta,rho) step within caps: need per-axis check, use
        # a monotone search on the max-norm distance from i
        jmax = int(np.searchsorted(u, u[i] + 1.0, side="right")) - 1
        jmax = max(jmax, i + 1)
        # per-axis caps (the cumulative u overestimates when axes alternate)
        while jmax > i + 1 and (abs(th[jmax] - th[i]) > cap_t * 1.0001
                                or abs(rho[jmax] - rho[i]) > cap_r * 1.0001):
            jmax -= max(1, (jmax - i) // 8)
        lo, hi = i + 1, jmax
        def ok(j):
            if j == i + 1:
                return True
            ks = np.arange(i + 1, j)
            s = (u[ks] - u[i]) / max(u[j] - u[i], 1e-12)
            tc_ = th[i] + s * (th[j] - th[i])
            rc_ = rho[i] + s * (rho[j] - rho[i])
            err = np.hypot(rc_ * np.cos(tc_) - x[ks], rc_ * np.sin(tc_) - y[ks])
            return err.max() <= tol
        if ok(hi):
            j = hi
        else:
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if ok(mid):
                    lo = mid
                else:
                    hi = mid
            j = lo
        keep.append(j)
        i = j
    return np.column_stack([th[keep], rho[keep]])


def refine(th, rho, max_dth=math.radians(0.25), min_rho=0.03):
    """Subdivide dense samples whose theta gap is too big (polylines drawn in
    x,y can have large theta steps at small radius). Gaps near the centre
    (rho < min_rho) are left alone: a big theta step there moves the ball
    almost nowhere."""
    dth = np.abs(np.diff(th))
    rm = (rho[:-1] + rho[1:]) / 2
    n = np.where(rm > min_rho, np.ceil(dth / max_dth).astype(int), 1)
    n = np.maximum(n, 1)
    if (n == 1).all():
        return th, rho
    idx = np.repeat(np.arange(len(dth)), n)
    first = np.cumsum(n) - n
    s = (np.arange(len(idx)) - first[idx] + 1) / n[idx]
    return (np.concatenate([th[:1], th[idx] + s * (th[idx + 1] - th[idx])]),
            np.concatenate([rho[:1], rho[idx] + s * (rho[idx + 1] - rho[idx])]))


def finish(path, tol=0.0015):
    """Clamp, add lead-in/out, resample under the point budget. -> (N,2) array."""
    th, rho = path.th.copy(), np.clip(path.rho, 0.0, 1.0)
    sgn = _direction(th)
    tgt = {"centre": 0.0, "rim": 1.0}
    parts = []
    if abs(rho[0] - tgt[path.start]) > 0.004:
        parts.append(_lead(th[0], rho[0], tgt[path.start], sgn, True))
    parts.append((th, rho))
    sgn_e = 1.0 if th[-1] - th[max(0, len(th) - 51)] >= 0 else -1.0
    if abs(rho[-1] - tgt[path.end]) > 0.004:
        parts.append(_lead(th[-1], rho[-1], tgt[path.end], sgn_e, False))
    th = np.concatenate([p[0] for p in parts])
    rho = np.clip(np.concatenate([p[1] for p in parts]), 0, 1)
    th, rho = refine(th, rho)
    f = 1.0
    while True:
        pts = resample(th, rho, tol, tc.MAX_DTHETA * f, tc.MAX_DRHO * f)
        if len(pts) <= tc.MAX_POINTS:
            break
        f *= 1.12
        if f > 2.4:
            raise ValueError(f"cannot fit {len(pts)} points under {tc.MAX_POINTS}")
    pts[0, 1] = tgt[path.start] if abs(pts[0, 1] - tgt[path.start]) < 0.004 else pts[0, 1]
    pts[-1, 1] = tgt[path.end] if abs(pts[-1, 1] - tgt[path.end]) < 0.004 else pts[-1, 1]
    return pts


# ----------------------------------------------------------------------------
# generators. Each returns a Path.
# ----------------------------------------------------------------------------
def erase(direction="out", pitch=0.03):
    """Reset pass: tight Archimedean spiral, pitch ~0.03 (groove 0.04 so each
    pass overlaps the last and flattens it). 'out' = centre to rim."""
    turns = 1.0 / pitch
    th = lin(0, turns * TAU)
    rho = th / (turns * TAU)
    if direction == "in":
        return Path(th, 1 - rho, "rim", "centre")
    return Path(th, rho, "centre", "rim")


def spiral_breath(pitch=0.06, amp=0.014, waves=6.5, r0=0.02):
    """Archimedean spiral whose radius breathes in and out. With half-integer
    `waves` per turn, successive turns are in antiphase so lines pinch and
    swell like woven ribbon. amp must stay < pitch/4 to keep lines apart."""
    turns = (0.97 - r0) / pitch
    th = lin(0, turns * TAU)
    base = r0 + (0.97 - r0) * th / th[-1]
    env = np.clip(base / 0.25, 0, 1)
    rho = base + amp * env * np.sin(waves * th)
    return Path(th, rho, "centre", "rim")


def rhodonea(p=7, q=3, scale=0.97):
    """Rose r = cos(p/q * theta): classic rhodonea, one closed curve through the
    centre. Petals all meet at the centre (dense hub is part of the look)."""
    k = p / q
    period = math.pi if (p * q) % 2 == 1 else TAU
    t = lin(0, period * q)
    r = scale * np.cos(k * t)
    x, y = r * np.cos(t), r * np.sin(t)
    th, rho = xy_to_tr(*dense_xy(x, y, 0.002))
    return Path(th, rho, "rim", "rim")


def rose_layers(k=5, layers=6, shrink=0.14, twist=None, scale=0.97):
    """Several roses with k petals, each smaller than the last and rotated half
    a petal-step, linked tip to tip: a layered flower."""
    twist = (math.pi / k) / 1.0 if twist is None else twist
    parts = []
    for j in range(layers):
        s = scale * (1 - shrink * j)
        t = lin(0, math.pi if k % 2 else TAU)
        # rose phased so its tip sits at angle j*twist
        r = s * np.cos(k * t)
        a = t + j * twist
        th, rho = xy_to_tr(*dense_xy(r * np.cos(a), r * np.sin(a), 0.002))
        parts.append((th, rho))
    th, rho = chain(parts)
    return Path(th, rho, "rim", "rim")


def spirograph(R=1.0, r=0.3125, d=0.55, kind="hypo", scale=0.97, copies=1, copy_shrink=0.0):
    """Hypotrochoid (kind='hypo') or epitrochoid ('epi') with rolling circle r
    (as a fraction of R) and pen offset d. Closed curve, normalised to touch
    rho=`scale`. copies>1 repeats it shrunk by copy_shrink each time."""
    from fractions import Fraction
    fr = Fraction(r / R).limit_denominator(200)
    p, q = fr.numerator, fr.denominator        # r/R = p/q  -> closes after p turns
    rr = R * fr
    parts = []
    for c in range(copies):
        t = lin(0, TAU * p)
        if kind == "hypo":
            x = (R - rr) * np.cos(t) + d * np.cos((R - rr) / rr * t)
            y = (R - rr) * np.sin(t) - d * np.sin((R - rr) / rr * t)
            m = (R - rr) + d
        else:
            x = (R + rr) * np.cos(t) - d * np.cos((R + rr) / rr * t)
            y = (R + rr) * np.sin(t) - d * np.sin((R + rr) / rr * t)
            m = (R + rr) + d
        s = scale / m * (1 - copy_shrink * c)
        th, rho = xy_to_tr(*dense_xy(x * s, y * s, 0.002))
        parts.append((th, rho))
    th, rho = chain(parts) if len(parts) > 1 else parts[0]
    return Path(th, rho, "rim", "rim")


def _sf(phi, m, n1, n2, n3):
    return (np.abs(np.cos(m * phi / 4)) ** n2 + np.abs(np.sin(m * phi / 4)) ** n3) ** (-1 / n1)


def superformula(m=7, turns=17, inner=0.1, n1=(1.2, 1.2), n2=(1.7, 1.7), n3=(1.7, 1.7),
                 twist=0.0, ring_gap=None):
    """Superformula bloom drawn as one inward spiral of shrinking copies. n1,n2,n3
    are (start, end) exponent pairs so the flower morphs as it shrinks. Between
    turns the lines pinch at the notches (tonal shading) and open at the tips."""
    th = lin(0, turns * TAU)
    s = th / th[-1]
    base = 0.97 - (0.97 - inner) * s
    nn = [a[0] + (a[1] - a[0]) * s for a in (n1, n2, n3)]
    # normalise by max over angle for each morph step (table of 64 morph values)
    tab = np.linspace(0, 1, 64)
    ph = np.linspace(0, TAU, 720, endpoint=False)
    mx = np.array([_sf(ph, m, *(a[0] + (a[1] - a[0]) * u for a in (n1, n2, n3))).max() for u in tab])
    norm = np.interp(s, tab, mx)
    phi = th + twist * s * TAU
    r = base * _sf(phi, m, *nn) / norm
    return Path(th, r, "rim", "centre")


def sunflower(turns=13.0, golden_waves=21.618, amp=0.012, r0=0.0):
    """Fermat spiral (rho ~ sqrt(theta), the sunflower head profile) with a
    ripple whose wave count has the golden fractional part, so ripples on each
    turn step by the golden angle and line up into the familiar crossing
    parastichy spirals."""
    th = lin(0, turns * TAU)
    s = th / th[-1]
    base = 0.97 * np.sqrt(s)
    env = np.clip(base / 0.2, 0, 1)
    rho = base + amp * env * np.sin(golden_waves * th)
    return Path(th, rho, "centre", "rim")


def polygon_vortex(n=6, step=1, circuits=19, inner=0.06, twist=0.0, tilt=0.0):
    """One straight-line polyline: each vertex a little nearer the centre than the
    last, vertices stepping `step` corners round an n-gon. step=1 gives a nested
    shrinking polygon vortex; step=2 on n=5 is a shrinking pentagram, n=7 step=3
    a heptagram. `twist` adds extra rotation per circuit (radians)."""
    m = n * circuits
    j = np.arange(m + 1)
    ang = tilt + j * TAU * step / n + twist * (j / n)
    rad = 0.97 - (0.97 - inner) * (j / m)
    x, y = rad * np.cos(ang), rad * np.sin(ang)
    th, rho = xy_to_tr(*dense_xy(x, y, 0.002))
    return Path(th, rho, "rim", "centre")


def ripple_rings(rings=14, r_in=0.08, r_out=0.95, wavelength=0.22, amp=0.012, phase_step=math.pi, hop=0.3):
    """Concentric rings, each carrying ripples of constant arc `wavelength`
    (so wave count grows with radius), joined by a smooth radial hop over the
    last `hop` of each turn, during which the old and new ripple cross-fade.
    Each ring's ripples are shifted by `phase_step` (half a wave by default)
    so crests meet troughs and the field reads as interference.
    Keep amp < (ring gap - 0.035) / 2."""
    gap = (r_out - r_in) / (rings - 1)
    th = lin(0, TAU * (rings - 1 + (1 - hop)))
    tt = th / TAU
    k = np.floor(tt).astype(int)
    f = tt - k
    e = smoothstep((f - (1 - hop)) / hop)
    base = r_in + gap * (k + e)
    def wave(kk):
        rk = r_in + gap * kk
        w = max(4, int(round(TAU * rk / wavelength)))
        return w
    wk = np.array([wave(i) for i in range(rings + 1)])
    w0, w1 = wk[k], wk[k + 1]
    wv = (1 - e) * np.sin(w0 * th + phase_step * k) + e * np.sin(w1 * th + phase_step * (k + 1))
    env = 0.35 + 0.65 * np.sin(np.pi * (base - r_in) / (r_out - r_in)) ** 0.5
    return Path(th, base + amp * env * wv, "centre", "rim")


def dunes(sweeps=90, r_in=0.55, r_out=0.97, wobble=0.05, cycles=2.0, drift=2.0):
    """A ring of radial sweeps: the ball runs rim -> r_in -> rim, stepping a
    little round the tray each time. Each sweep wobbles sideways (`wobble` in
    radius units, `cycles` waves along the sweep) and the wobble's phase slides
    by `drift` full cycles over the whole drawing, so neighbouring lines flow
    together like combed dunes. The middle stays calm smooth sand."""
    dth = TAU / sweeps
    parts = []
    for k in range(sweeps):
        rr = np.linspace(r_out, r_in, 260)
        if k % 2:
            rr = rr[::-1]
        ph = TAU * drift * k / sweeps
        w = np.sin(TAU * cycles * (rr - r_in) / (r_out - r_in) + ph)
        w += 0.35 * np.sin(TAU * 2.3 * cycles * (rr - r_in) / (r_out - r_in) + 1.7 * ph)
        parts.append((k * dth + wobble * w / rr, rr))
    th, rho = chain(parts)
    end = "rim" if sweeps % 2 == 0 else "rim"
    return Path(th, rho, "rim", "rim")


def taiji(pitch=0.045, eye=0.13, scale=0.95, outline=True):
    """Bold two-tone disc: the 'yin' half (an S-shaped region) is filled with
    concentric arcs traced back and forth, the 'yang' half is left as smooth
    sand. A small round hole stays smooth in the filled half. Reads from
    across the room; the S edge is drawn by the arcs' turn-arounds."""
    rs = np.arange(0.02, scale, pitch)
    ec = np.array([0.0, -0.5 * scale])           # hole centre (in yin area)
    er = eye * scale
    parts = []
    for i, r in enumerate(rs):
        a0 = math.pi - math.asin(min(1, r / scale))      # yin interval at this radius
        ang = np.linspace(a0, a0 + math.pi, int(max(60, math.pi * r * 600)))
        if i % 2:
            ang = ang[::-1]
        x, y = r * np.cos(ang), r * np.sin(ang)
        # push points that fall inside the hole out to its rim so lines wrap around it
        dx, dy = x - ec[0], y - ec[1]
        dd = np.hypot(dx, dy)
        inside = dd < er * 1.0 + 0.0
        k = np.where(inside, (er + 0.0) / np.maximum(dd, 1e-9), 1.0)
        x, y = ec[0] + dx * k, ec[1] + dy * k
        parts.append((x, y))
    X = np.concatenate([p[0] for p in parts]); Y = np.concatenate([p[1] for p in parts])
    X, Y = dense_xy(X, Y, 0.002)
    th, rho = xy_to_tr(X, Y)
    return Path(th, rho, "centre", "rim" if False else "rim")


def moire(role="a", pitch=0.09, offset=0.2):
    """One half of a moire pair. Draw 'a' (centred spiral, centre -> rim) and
    then 'b' (spiral about a point shifted by `offset`, rim -> centre) over it.
    Where the two line families cross they make the interference pattern, so
    the pitch must be wide (>= 0.08): at 0.06 the second pass just overwrites
    the first. A bigger offset gives bigger crescent bands. Preview both:
        sandsim.py moire_a.thr moire_b.thr --stack -o pair.png"""
    if role == "a":
        n = 0.97 / pitch
        t = lin(0, n * TAU)
        return Path(t, 0.97 * t / t[-1], "centre", "rim")
    n = (0.97 - offset) / pitch
    t = lin(0, n * TAU)
    rr = (0.97 - offset) * (1 - t / t[-1])
    x = offset + rr * np.cos(t)       # starts at x = 0.97 on the rim
    y = rr * np.sin(t)
    th, rho = xy_to_tr(*dense_xy(x, y, 0.002))
    return Path(th, rho, "rim", "centre")


def lissajous(a=5, b=6, delta=math.pi / 2, scale=0.955, copies=1, rot=0.0):
    """Lissajous figure x=sin(a t + delta), y=sin(b t) mapped square->disc so
    the figure fills the circle and touches the rim at its extremes."""
    t0 = (math.pi / 2 - delta) / a            # first time x = +1 (on the rim)
    parts = []
    for c in range(copies):
        t = lin(t0, t0 + TAU, 0.002)
        x, y = np.sin(a * t + delta), np.sin(b * t)
        X = x * np.sqrt(1 - y * y / 2); Y = y * np.sqrt(1 - x * x / 2)
        ang = rot * c
        Xr, Yr = X * math.cos(ang) - Y * math.sin(ang), X * math.sin(ang) + Y * math.cos(ang)
        parts.append(xy_to_tr(*dense_xy(scale * Xr, scale * Yr, 0.002)))
    th, rho = chain(parts) if copies > 1 else parts[0]
    return Path(th, rho, "rim", "rim")


def galaxy(arms=5, strands=4, spread=0.13, winding=1.15, core=0.05, scale=0.96, pitch_b=None):
    """Logarithmic-spiral galaxy: `arms` arms, each a bundle of `strands` lines
    fanned by `spread` rad, drawn out and back in (so each arm ends at the core).
    The strands converge toward the centre and merge into a bright core."""
    b = math.log(scale / core) / (winding * TAU)    # rho = core * exp(b * phi)
    phi = np.linspace(0, winding * TAU, 1400)
    rho_out = core * np.exp(b * phi)
    parts = []
    for a in range(arms):
        base = a * TAU / arms
        for s in range(strands):
            off = (s - (strands - 1) / 2) * spread
            ang = base + off + phi
            if s % 2 == 0:
                parts.append((ang, rho_out))
            else:
                parts.append((ang[::-1], rho_out[::-1]))
    th, rho = chain(parts)
    return Path(th, rho, "centre", "centre")


def mandala(zones=((6, 0.0, 0.26), (12, 0.26, 0.52), (18, 0.52, 0.76), (30, 0.76, 0.97)),
            pitch=0.052, amp=0.035, sharp=0.6):
    """Mirrored petals: one outward spiral whose radius is pushed in and out by
    a zone-wise petal wave, N petals per turn in each zone with the wave fading
    to zero at the zone edges (so counts can change without a seam). `sharp`
    < 1 makes pointed petals."""
    turns = 0.97 / pitch
    th = lin(0, turns * TAU)
    base = 0.97 * th / th[-1]
    mod = np.zeros_like(th)
    for N, a, b in zones:
        z = (base >= a) & (base < b)
        env = np.sin(np.pi * (base[z] - a) / (b - a)) ** 1.3
        w = np.abs(np.sin(N * th[z] / 2)) ** sharp          # mirrored arch, cusp at the valleys
        mod[z] = amp * env * (w - 0.5)
    return Path(th, base + mod, "centre", "rim")


def harmonograph(f=(2.0, 3.01, 3.0, 2.0), phase=(0.0, 1.2, 2.1, 0.4), decay=0.045, turns=46, scale=0.97):
    """Two-pendulum harmonograph, damped so the figure spirals in from the rim
    to a point near the centre. Lines are thin lacy loops that pile up
    gently toward the middle."""
    t = np.linspace(0, turns * TAU, int(turns * 2200))
    e = np.exp(-decay * t / TAU)
    x = e * (0.5 * np.sin(f[0] * t / 4 + phase[0]) + 0.5 * np.sin(f[1] * t / 4 + phase[1]))
    y = e * (0.5 * np.sin(f[2] * t / 4 + phase[2]) + 0.5 * np.sin(f[3] * t / 4 + phase[3]))
    th, rho = xy_to_tr(*dense_xy(x * scale, y * scale, 0.002))
    return Path(th, rho, "rim", "centre")


# ----------------------------------------------------------------------------
# registry: presets (the library)
# ----------------------------------------------------------------------------
GENS = {f.__name__: f for f in (erase, spiral_breath, rhodonea, rose_layers, spirograph,
                                superformula, sunflower, polygon_vortex, ripple_rings, dunes,
                                taiji, moire, lissajous, galaxy, mandala, harmonograph)}

# name -> (generator, params, one-line description)
PRESETS = {}


def preset(name, gen, params, desc):
    PRESETS[name] = (gen, params, desc)


# --- reset passes -------------------------------------------------------------
preset("erase_out", "erase", dict(direction="out", pitch=0.03), "Reset: tight spiral centre to rim (pitch 0.03). Leaves flat sand, ball at the rim.")
preset("erase_in", "erase", dict(direction="in", pitch=0.03), "Reset: tight spiral rim to centre. Leaves flat sand, ball at the centre.")
# --- library ------------------------------------------------------------------
preset("ribbon_spiral", "spiral_breath", dict(pitch=0.05, amp=0.012), "Spiral whose lines pinch and swell like woven ribbon.")
preset("rose_7_3", "rhodonea", dict(p=7, q=3), "Seven-petal rose, one open line through the centre. Quick test.")
preset("rose_9_4", "rhodonea", dict(p=9, q=4), "Nine-lobed rose with doubled petals; the hub fills in gently.")
preset("rose_layers", "rose_layers", dict(), "Five-petal roses nested and rotated, like a layered flower.")
preset("spiro_hypo", "spirograph", dict(r=0.3125, d=0.7), "Spirograph (hypotrochoid) lace ring.")
preset("spiro_epi", "spirograph", dict(r=5 / 12, d=0.8, kind="epi"), "Epitrochoid lace with a looped inner garland.")
preset("bloom_star", "superformula", dict(m=6, n1=(0.8, 0.8), n2=(1.0, 1.0), n3=(1.0, 1.0), turns=16), "Six-pointed star made of nested lines, shrinking into the centre.")
preset("bloom_ruffle", "superformula", dict(m=12, n1=(1.5, 0.6), n2=(3, 1), n3=(3, 1), turns=16), "Twelve-lobed ruffled flower that sharpens toward the middle.")
preset("sunflower", "sunflower", dict(), "Fermat spiral with golden-angle ripple: crossing sunflower spirals.")
preset("hex_vortex", "polygon_vortex", dict(n=6, step=1, circuits=19, twist=0.06), "Hexagon spiralling inward, one straight-line vortex.")
preset("square_vortex", "polygon_vortex", dict(n=4, step=1, circuits=24, twist=0.1), "Square spiralling inward into a whirl.")
preset("star_pinwheel", "polygon_vortex", dict(n=8, step=3, circuits=14, twist=0.04), "Eight-point star that twists into a pinwheel. The long one (~29 min).")
preset("ripple_rings", "ripple_rings", dict(), "Concentric rings with phase-shifted ripples: pond interference.")
preset("dunes", "dunes", dict(wobble=0.06, cycles=0.75, drift=1.0, sweeps=84, r_in=0.5), "Ring of wavy radial sweeps, like combed dunes around a calm eye.")
preset("taiji", "taiji", dict(), "Bold yin-yang: striped S-shaped half against smooth sand.")
preset("moire_a", "moire", dict(role="a"), "Moire pair, part 1: centred spiral. Draw first (ends rim).")
preset("moire_b", "moire", dict(role="b"), "Moire pair, part 2: off-centre spiral drawn over part 1 (starts rim).")
preset("lissajous", "lissajous", dict(a=7, b=9), "Lissajous basket weave filling the disc. Quick test.")
preset("lissajous_weave", "lissajous", dict(a=3, b=4, copies=3, rot=0.35), "Three rotated Lissajous loops: bold crossing bands.")
preset("galaxy", "galaxy", dict(), "Five-armed logarithmic spiral galaxy with a bright core.")
preset("mandala", "mandala", dict(zones=((8, 0, .35), (12, .35, .7), (16, .7, .97)), pitch=.058, amp=.07, sharp=0.7), "Mirrored petal rings of changing count.")
preset("harmonograph", "harmonograph", dict(f=(2, 3, 3, 2.02), phase=(0, 0, 1.57, 0), decay=0.06, turns=40), "Damped pendulum drawing spiralling in from the rim.")


# layering advice that the coverage heuristic cannot know
LAYERING = {
    "erase_out": "any state: this is the reset pass",
    "erase_in": "any state: this is the reset pass",
    "moire_a": "erase first; then draw moire_b straight over it",
    "moire_b": "draw straight over moire_a, no erase between",
    "taiji": "erase first: the smooth half must start clean",
}


def build(name, overrides=None):
    """Generate a preset (or a bare generator name). -> (pts, meta dict)."""
    if name in PRESETS:
        gname, params, desc = PRESETS[name]
    elif name in GENS:
        gname, params, desc = name, {}, GENS[name].__doc__.split("\n")[0]
    else:
        raise KeyError(f"unknown pattern {name!r}")
    params = dict(params)
    params.update(overrides or {})
    path = GENS[gname](**params)
    pts = finish(path)
    d = np.abs(np.diff(pts, axis=0))
    meta = {
        "name": name, "generator": gname, "params": {k: v for k, v in params.items()},
        "points": int(len(pts)), "start": path.start, "end": path.end,
        "estimated_minutes": round(tc.est_minutes(pts), 1),
        # largest theta step away from the centre (steps at rho < 0.05 move the ball almost nowhere)
        "max_dtheta_deg": round(float(np.degrees(d[(pts[:-1, 1] + pts[1:, 1]) / 2 > 0.05, 0].max())), 2),
        "max_drho": round(float(d[:, 1].max()), 4),
        "description": desc,
    }
    # actual start/end of the final points
    meta["start"] = "centre" if pts[0, 1] < 0.01 else "rim" if pts[0, 1] > 0.99 else f"rho {pts[0,1]:.2f}"
    meta["end"] = "centre" if pts[-1, 1] < 0.01 else "rim" if pts[-1, 1] > 0.99 else f"rho {pts[-1,1]:.2f}"
    return pts, meta


def _jsonable(o):
    if isinstance(o, (tuple, list)):
        return [_jsonable(i) for i in o]
    if isinstance(o, np.generic):
        return o.item()
    return o


def _parse_val(s):
    try:
        return ast.literal_eval(s)
    except Exception:
        return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--all", metavar="OUTDIR", help="generate the whole library into OUTDIR")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="with --all: skip PNG previews")
    a, rest = ap.parse_known_args()
    over = {}
    i = 0
    while i < len(rest):
        if not rest[i].startswith("--") or i + 1 >= len(rest):
            ap.error(f"bad argument {rest[i]!r}")
        over[rest[i][2:].replace("-", "_")] = _parse_val(rest[i + 1]); i += 2
    if a.list:
        for n, (g, p, d) in PRESETS.items():
            print(f"{n:18s} {g:15s} {d}")
        return
    if a.all:
        os.makedirs(a.all, exist_ok=True)
        manifest, items = [], []
        for n in PRESETS:
            pts, meta = build(n)
            path = os.path.join(a.all, n + ".thr")
            tc.write_thr(path, pts)
            manifest.append(_jsonable(meta)); items.append((n, meta["estimated_minutes"], path))
            print(f"{n:18s} {meta['points']:6d} pts {meta['estimated_minutes']:6.1f} min  {meta['start']}->{meta['end']}")
        if not a.no_render:
            import sandsim
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor() as ex:
                covs = list(ex.map(_render_one, [(p, p[:-4] + ".png") for _, _, p in items]))
            for m, c in zip(manifest, covs):
                m["coverage"] = round(c, 2)
                m["layering"] = LAYERING.get(m["name"]) or (
                    "over a previous drawing is fine (dense, repaints most of the tray)" if c > 0.8
                    else "erase first (sparse lines would mix with old art)")
            sandsim.contact_sheet(items, os.path.join(a.all, "contact.png"))
        with open(os.path.join(a.all, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=1)
        return
    if not a.name or not a.out:
        ap.error("need a pattern name and -o out.thr (or --all / --list)")
    pts, meta = build(a.name, over)
    tc.write_thr(a.out, pts)
    print(json.dumps(_jsonable(meta)))


def _render_one(args):
    import sandsim
    src, dst = args
    s = sandsim.Sand(900)
    s.draw(tc.read_thr(src))
    s.image().save(dst)
    return s.coverage()


if __name__ == "__main__":
    main()
