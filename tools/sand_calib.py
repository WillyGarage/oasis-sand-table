#!/usr/bin/env python3
"""sand_calib - rectify phone photos of real sand to top-down mm, measure ribs/lips/grooves, compare with sand_relief_sim.
OFFLINE ONLY (never contacts a table).  See captures/relief-study/v4/STATUS.md.
"""
import os, sys, json, math, time
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(ROOT, 'captures/relief-study/v4/calib')
R_WORK = 114.0
HALF = 128.0          # rectified canvas covers +-HALF mm

PHOTOS = {
    'p1': dict(img='captures/patchtest/phone/phone_1915.jpg', path='captures/patchtest/patches_path.npy',
               centre=(1417, 1683), ball=(2333, 1150)),
    'p2': dict(img='captures/patchtest2/phone/phone_1955.jpg', path='captures/patchtest2/patches2_path.npy',
               centre=(1640, 1885), ball=(1467, 2867)),
}


def mm_to_rect(mmpx):
    """3x3 matrix: table mm (x, y up) -> rectified canvas px."""
    return np.array([[1 / mmpx, 0, HALF / mmpx], [0, -1 / mmpx, HALF / mmpx], [0, 0, 1.0]])


def init_H(name, mmpx):
    """photo px -> rect px from a similarity through the spiral centre and the parked ball (= last path point)."""
    ph = PHOTOS[name]
    P = np.load(os.path.join(ROOT, ph['path']))
    c = np.array(ph['centre'], float); b = np.array(ph['ball'], float)
    v = b - c
    ang_p = math.atan2(-v[1], v[0])                      # image y is down
    ang_t = math.atan2(P[-1][1], P[-1][0])
    rot = ang_t - ang_p
    s = np.hypot(*P[-1]) / np.hypot(*v)                  # mm per photo px
    ca, sa = math.cos(rot), math.sin(rot)
    # photo px -> mm: x = s*(ca*dx - sa*(-dy)) ... build with y flip
    F = np.array([[1, 0, -c[0]], [0, -1, c[1]], [0, 0, 1.0]])         # photo -> centred, y up
    Rm = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1.0]]) @ np.diag([s, s, 1.0])
    return mm_to_rect(mmpx) @ Rm @ F


def load_photo(name):
    return cv2.imread(os.path.join(ROOT, PHOTOS[name]['img']))


def path_map(name, mmpx, H_rect_from_mm=None, sigma_mm=2.0):
    P = np.load(os.path.join(ROOT, PHOTOS[name]['path']))
    n = int(2 * HALF / mmpx)
    m = np.zeros((n, n), np.float32)
    M = mm_to_rect(mmpx)
    q = (M @ np.c_[P, np.ones(len(P))].T).T[:, :2]
    for a, b in zip(q[:-1], q[1:]):
        cv2.line(m, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), 1.0, 1)
    return cv2.GaussianBlur(m, (0, 0), sigma_mm / mmpx)


def texture_map(rect_gray, mmpx, sigma_mm=2.0):
    g = rect_gray.astype(np.float32)
    hp = g - cv2.GaussianBlur(g, (0, 0), 1.5 / mmpx)
    e = cv2.GaussianBlur(np.abs(hp), (0, 0), sigma_mm / mmpx)
    return e


def refine_H(name, mmpx=0.25, iters=3):
    img = load_photo(name)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H = init_H(name, mmpx)
    n = int(2 * HALF / mmpx)
    tmpl = path_map(name, mmpx)
    tmpl = (tmpl - tmpl.mean()) / (tmpl.std() + 1e-6)
    for it in range(iters):
        rect = cv2.warpPerspective(gray, H, (n, n), flags=cv2.INTER_AREA)
        tex = texture_map(rect, mmpx)
        tex = (tex - tex.mean()) / (tex.std() + 1e-6)
        W = np.eye(3, dtype=np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
        try:
            cc, W = cv2.findTransformECC(tmpl, tex.astype(np.float32), W, cv2.MOTION_HOMOGRAPHY, crit, None, 5)
        except cv2.error as e:
            print('ECC failed', e); break
        print(name, 'iter', it, 'cc %.3f' % cc)
        # W maps template coords -> input coords (WARP_INVERSE_MAP semantics): rect_new(x) = tex(W x)
        H = np.linalg.inv(W.astype(np.float64)) @ H if False else H
        H = np.linalg.inv(W.astype(np.float64)) @ H
    return H


def overlay(name, H, mmpx, out):
    img = load_photo(name)
    n = int(2 * HALF / mmpx)
    rect = cv2.warpPerspective(img, H, (n, n), flags=cv2.INTER_AREA)
    P = np.load(os.path.join(ROOT, PHOTOS[name]['path']))
    q = (mm_to_rect(mmpx) @ np.c_[P, np.ones(len(P))].T).T[:, :2]
    ov = rect.copy()
    cv2.polylines(ov, [np.round(q).astype(np.int32).reshape(-1, 1, 2)], False, (0, 0, 255), 1)
    cv2.imwrite(out, ov)
    return rect


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'rectify'
    if cmd == 'rectify':
        for name in ('p1', 'p2'):
            H = refine_H(name)
            np.save(os.path.join(CAL, 'H_%s.npy' % name), H)
            overlay(name, H, 0.25, os.path.join(CAL, 'overlay_%s.png' % name))


def mm_crop(rect, mmpx, cx, cy, w_mm, h_mm=None):
    h_mm = h_mm or w_mm
    M = mm_to_rect(mmpx)
    u, v = (M @ [cx, cy, 1])[:2]
    w, h = int(w_mm / mmpx), int(h_mm / mmpx)
    x0, y0 = int(round(u - w / 2)), int(round(v - h / 2))
    return rect[y0:y0 + h, x0:x0 + w].copy(), (x0, y0)


# ---------------------------------------------------------------- patches and real crops
PATCHES = {
    'p1a': dict(photo='p1', cx=-40.0, cy=35.0, w=44, h=64, kind='rect', x=(-50, -30), y=(15, 55), sp=1.2),
    'p1b': dict(photo='p1', cx=0.0, cy=35.0, w=44, h=64, kind='rect', x=(-10, 10), y=(15, 55), sp=2.3),
    'p1c': dict(photo='p1', cx=40.0, cy=35.0, w=44, h=64, kind='rect', x=(30, 50), y=(15, 55), sp=5.0),
    'p2a': dict(photo='p2', cx=-45.0, cy=35.0, w=44, h=64, kind='rect', x=(-55, -35), y=(15, 55), sp=0.6),
    'p2b': dict(photo='p2', cx=45.0, cy=45.0, w=64, h=64, kind='band', sp=1.2),
    'p2c': dict(photo='p2', cx=45.0, cy=-35.0, w=64, h=64, kind='band', sp=0.6),
    'p2lane': dict(photo='p2', cx=-3.0, cy=-72.0, w=48, h=48, kind='lane', sp=0.0),
}
CROP_MM_PX = 0.1


def load_H(name):
    return np.load(os.path.join(CAL, 'H_%s.npy' % name))


_rect_cache = {}


def rectified(name, mmpx=CROP_MM_PX):
    key = (name, mmpx)
    if key not in _rect_cache:
        H = init_H(name, mmpx)
        n = int(2 * HALF / mmpx)
        _rect_cache[key] = cv2.warpPerspective(load_photo(name), H, (n, n), flags=cv2.INTER_AREA)
    return _rect_cache[key]


def real_crop(pk, shift=(0.0, 0.0)):
    """Rectified real photo crop (BGR) of a patch at 0.1 mm/px; returns (img, (x0_mm, y1_mm)) = top-left corner in mm."""
    p = PATCHES[pk]
    rect = rectified(p['photo'])
    c, (x0, y0) = mm_crop(rect, CROP_MM_PX, p['cx'] + shift[0], p['cy'] + shift[1], p['w'], p['h'])
    return c, (x0 * CROP_MM_PX - HALF, HALF - y0 * CROP_MM_PX)


def lum(img_bgr):
    """Luminance float image from BGR."""
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)


def sample_profile(img, mmpx, a, b, half_w, trim=0.0, step=0.05):
    """Average a grayscale rect image across the segment a->b (mm), perpendicular offsets -half_w..half_w.
    Returns (offsets_mm, mean_profile, rows). Perpendicular is the left normal of a->b (y-up frame)."""
    from scipy.ndimage import map_coordinates
    a = np.asarray(a, float); b = np.asarray(b, float)
    d = b - a; L = np.hypot(*d); d /= L; nrm = np.array([-d[1], d[0]])
    t = np.arange(trim, L - trim, 0.1)
    o = np.arange(-half_w, half_w + 1e-9, step)
    T, O = np.meshgrid(t, o, indexing='ij')
    X = a[0] + d[0] * T + nrm[0] * O; Y = a[1] + d[1] * T + nrm[1] * O
    u = (X + HALF) / mmpx - 0.5; v = (HALF - Y) / mmpx - 0.5
    V = map_coordinates(img, [v, u], order=1)
    return o, V.mean(0), V


# ---------------------------------------------------------------- simulation of a patch window
THR = {'p1': 'captures/patchtest/patches.thr', 'p2': 'captures/patchtest2/patches2.thr'}


def sim_patch(pk, modname='sand_relief_sim', phys=None, erase=0.02, mmpx=0.1, size=None, preset=None):
    """Simulate patch `pk`: inward erase spiral (clipped to the window) then the real .thr, in a window round the patch.
    Returns the WindowTable (T.h = height in mm; origin/geometry in T.cx, T.cy, T.N, T.px)."""
    import importlib
    mod = importlib.import_module(modname)
    from thrcommon import read_thr
    p = PATCHES[pk]
    size = size or max(p['w'], p['h'])
    ph = dict(preset or {}); ph.update(phys or {})
    T = mod.WindowTable(p['cx'], p['cy'], size, mm_px=mmpx, **ph)
    if erase:
        T.erase(erase, outward=False)
    T.run(read_thr(os.path.join(ROOT, THR[p['photo']])))
    return T


def sim_crop_img(T, pk, **render_kw):
    """Rendered window as a BGR array at the same 0.1 mm/px crop geometry as real_crop (window centre = patch centre)."""
    im = T.render_win_photo(**render_kw) if render_kw.pop('photo', True) else T.render_win(**render_kw)
    a = np.array(im.convert('RGB'))[:, :, ::-1]
    return a


# ---------------------------------------------------------------- metrics (same code for real crops and sim renders)
def _axes(shape, x0, y1, mmpx=CROP_MM_PX):
    x = x0 + (np.arange(shape[1]) + 0.5) * mmpx
    y = y1 - (np.arange(shape[0]) + 0.5) * mmpx
    return x, y


def _detrend(y, v, deg=3):
    c = np.polyfit(y, v, deg)
    return v - np.polyval(c, y)


def rib_metrics(g, x0, y1, patch):
    """Rib period (mm), amplitude (percent of mean grey, 5-95 percentile of the 0.15 mm smoothed profile) and wedge index
    (spread of local rib amplitude along the stroke) for a straight 'rect' patch. g: grey crop at 0.1 mm/px."""
    from scipy.ndimage import gaussian_filter1d
    x, y = _axes(g.shape, x0, y1)
    xa, xb = patch['x']; ya, yb = patch['y']
    ysel = (y > ya + 3) & (y < yb - 3)
    xsel = (x > xa + 4) & (x < xb - 4)
    prof = g[np.ix_(ysel, xsel)].mean(1)
    yy = y[ysel]
    d = _detrend(yy, prof, 3)
    d = gaussian_filter1d(d, 1.5)
    # period from the autocorrelation of the detrended profile (first clear peak) refined by the spectrum
    n = len(d); w = np.hanning(n)
    nfft = 1 << 16
    sp = np.abs(np.fft.rfft(d * w, nfft)); fr = np.fft.rfftfreq(nfft, 0.1)       # cycles per mm
    sel = (fr > 1 / 14.0) & (fr < 1 / 0.5)
    f0 = fr[sel][np.argmax(sp[sel])]
    amp = (np.percentile(d, 95) - np.percentile(d, 5)) / np.mean(prof) * 100
    # wedge: local amplitude in 4 mm bins along x
    cols = []
    xs_in = x[xsel]
    for xc in np.arange(xa + 4, xb - 4 - 3.9, 4.0):
        m = (x >= xc) & (x < xc + 4)
        pr = g[np.ix_(ysel, m)].mean(1)
        dd = gaussian_filter1d(_detrend(yy, pr, 3), 1.5)
        cols.append(np.percentile(dd, 95) - np.percentile(dd, 5))
    cols = np.array(cols)
    wedge = float((cols.max() - cols.min()) / max(cols.mean(), 1e-6))
    return dict(period=float(1 / f0), amp_pct=float(amp), wedge=wedge)


def lip_metrics(g, x0, y1, patch):
    """Lip width at the two stroke ends: separation (mm) of the brightest and darkest point of the 0.25 mm smoothed
    mean x-profile within 10 mm of the stroke end; also its contrast (percent of mean grey)."""
    from scipy.ndimage import gaussian_filter1d
    x, y = _axes(g.shape, x0, y1)
    xa, xb = patch['x']; ya, yb = patch['y']
    ysel = (y > ya + 4) & (y < yb - 4)
    prof = gaussian_filter1d(g[ysel].mean(0), 2.5)
    out = {}
    for nm, lo, hi in (('L', xa - 10, xa + 2), ('R', xb - 2, xb + 10)):
        m = (x > lo) & (x < hi)
        xi, pi = x[m], prof[m]
        out[nm] = (abs(float(xi[np.argmax(pi)] - xi[np.argmin(pi)])), float((pi.max() - pi.min()) / prof.mean() * 100))
    return dict(lip_sep=(out['L'][0] + out['R'][0]) / 2, lip_con=(out['L'][1] + out['R'][1]) / 2, lipL=out['L'], lipR=out['R'])


def patch_metrics(g, x0, y1, pk):
    p = PATCHES[pk]
    if p['kind'] != 'rect':
        return {}
    d = rib_metrics(g, x0, y1, p); d.update(lip_metrics(g, x0, y1, p)); d['strokes'] = p['sp']
    d['period_strokes'] = d['period'] / p['sp']
    return d


# ---------------------------------------------------------------- batch simulation of all windows
SIMDIR = os.path.join(CAL, 'sims')


def _sim_job(a):
    pk, modname, phys, tag, mmpx = a
    t0 = time.time()
    T = sim_patch(pk, modname, phys, mmpx=mmpx)
    d = os.path.join(SIMDIR, tag); os.makedirs(d, exist_ok=True)
    np.save(os.path.join(d, pk + '.npy'), T.h.astype(np.float32))
    return pk, time.time() - t0


def run_sims(phys, tag, modname='sand_relief_sim', keys=None, mmpx=0.1, procs=10):
    from multiprocessing import Pool
    keys = keys or list(PATCHES)
    with Pool(min(procs, len(keys))) as pool:
        res = pool.map(_sim_job, [(k, modname, phys, tag, mmpx) for k in keys])
    return dict(res)


def load_sim(pk, tag, modname='sand_relief_sim', phys=None, mmpx=0.1):
    """Rebuild the WindowTable for patch pk with the saved heights."""
    import importlib
    mod = importlib.import_module(modname)
    p = PATCHES[pk]
    size = max(p['w'], p['h'])
    T = mod.WindowTable(p['cx'], p['cy'], size, mm_px=mmpx, **(phys or {}))
    T.h = np.load(os.path.join(SIMDIR, tag, pk + '.npy')).astype(np.float64)
    return T


def polar_profile(g, x0, y1, phi_deg, dphi_deg, r0, r1, mmpx=CROP_MM_PX, dr=0.05):
    """Mean radial profile (about the table centre) of a grey crop, over azimuths phi +- dphi/2 (degrees, y up)."""
    from scipy.ndimage import map_coordinates
    r = np.arange(r0, r1, dr)
    ph = np.radians(np.linspace(phi_deg - dphi_deg / 2, phi_deg + dphi_deg / 2, 40))
    R, P = np.meshgrid(r, ph, indexing='ij')
    X, Y = R * np.cos(P), R * np.sin(P)
    u = (X - x0) / mmpx - 0.5; v = (y1 - Y) / mmpx - 0.5
    V = map_coordinates(g, [v, u], order=1, mode='nearest')
    return r, V.mean(1)


def ring_metrics(g, x0, y1, phi=258.0, dphi=6.0, r0=68.0, r1=86.0, pitch=2.28):
    """Erase-ring texture: period (mm), amplitude (5-95 percentile of the detrended profile, percent of mean grey) and
    skew (positive: bright narrow crests) of the radial profile."""
    from scipy.ndimage import gaussian_filter1d
    r, p = polar_profile(g, x0, y1, phi, dphi, r0, r1)
    d = gaussian_filter1d(_detrend(r, p, 2), 1.5)
    n = len(d); nfft = 1 << 16
    sp = np.abs(np.fft.rfft(d * np.hanning(n), nfft)); fr = np.fft.rfftfreq(nfft, 0.05)
    sel = (fr > 1 / 6.0) & (fr < 1 / 1.0)
    per = 1 / fr[sel][np.argmax(sp[sel])]
    amp = (np.percentile(d, 95) - np.percentile(d, 5)) / np.mean(p) * 100
    sk = float(((d - d.mean()) ** 3).mean() / (d.std() ** 3 + 1e-9))
    return dict(ring_period=float(per), ring_amp_pct=float(amp), ring_skew=sk)


def lane_profile(g, x0, y1, a=(-1.4, -34.0), b=(-4.5, -110.5), t0=30.0, t1=60.0, half=14.0):
    """Mean profile across the long travel lane of photo 2 (the lane that ends at the parked ball)."""
    from scipy.ndimage import map_coordinates
    a = np.asarray(a); b = np.asarray(b); d = (b - a) / np.hypot(*(b - a)); nrm = np.array([-d[1], d[0]])
    t = np.arange(t0, t1, 0.1); o = np.arange(-half, half + 1e-9, 0.05)
    T_, O_ = np.meshgrid(t, o, indexing='ij')
    X = a[0] + d[0] * T_ + nrm[0] * O_; Y = a[1] + d[1] * T_ + nrm[1] * O_
    V = map_coordinates(g, [(y1 - Y) / CROP_MM_PX - 0.5, (X - x0) / CROP_MM_PX - 0.5], order=1, mode='nearest')
    return o, V.mean(0)


def lane_metrics(g, x0, y1):
    from scipy.ndimage import gaussian_filter1d
    o, m = lane_profile(g, x0, y1)
    m = gaussian_filter1d(m, 3)
    bg = np.median(np.r_[m[:100], m[-100:]])
    dev = m - bg
    thr = 0.35 * np.abs(dev).max()
    idx = np.flatnonzero(np.abs(dev) > thr)
    lo, hi = o[idx.min()], o[idx.max()]
    return dict(lane_width=float(hi - lo), lane_depth_pct=float(abs(dev).max() / bg * 100),
                lane_pp_pct=float((m.max() - m.min()) / bg * 100))


def flat_field(g, mmpx=CROP_MM_PX, sigma_mm=5.0):
    b = cv2.GaussianBlur(g.astype(np.float32), (0, 0), sigma_mm / mmpx)
    return g / np.maximum(b, 1e-3)


def sim_gray_crop(T, pk, **render_kw):
    """Render window T and cut the patch's crop (same size/position as real_crop). Returns (grey float32, x0_mm, y1_mm)."""
    p = PATCHES[pk]
    a = sim_crop_img(T, pk, **render_kw)
    g = lum(a)
    n = g.shape[0]
    w, h = int(p['w'] / T.px), int(p['h'] / T.px)
    r0 = (n - h) // 2; c0 = (n - w) // 2
    g = g[r0:r0 + h, c0:c0 + w]
    return g, p['cx'] - p['w'] / 2, p['cy'] + p['h'] / 2


def side_by_side(pk, tag, out=None, flat=True, T=None, **render_kw):
    c, (x0, y1) = real_crop(pk)
    gr = lum(c)
    T = T or load_sim(pk, tag, phys=dict(deposit='real'))
    gs, xs0, ys1 = sim_gray_crop(T, pk, **render_kw)
    if gs.shape != gr.shape:
        gs = cv2.resize(gs, (gr.shape[1], gr.shape[0]))
    def nrm(g):
        f = flat_field(g) if flat else g / g.mean()
        f = (f - 1) * 2.2 + 0.62 if flat else f
        return (np.clip(f, 0, 1) * 255).astype(np.uint8)
    pair = np.vstack([nrm(gr), np.full((6, gr.shape[1]), 255, np.uint8), nrm(gs)])
    if out:
        cv2.imwrite(out, pair)
    return pair


def ring_fold(g, x0, y1, pitch=2.28, phis=(250.0, 266.0), r0=62.0, r1=90.0, nb=57):
    """Average ring shape over one pitch: the spiral r = pitch * phi / 2pi (+ n pitch) is used to fold every sample."""
    from scipy.ndimage import map_coordinates
    ph = np.radians(np.linspace(phis[0], phis[1], 60)); r = np.arange(r0, r1, 0.05)
    R_, P_ = np.meshgrid(r, ph, indexing='ij')
    X, Y = R_ * np.cos(P_), R_ * np.sin(P_)
    V = map_coordinates(g, [(y1 - Y) / CROP_MM_PX - 0.5, (X - x0) / CROP_MM_PX - 0.5], order=1, mode='nearest')
    V = V / V.mean()
    s = np.mod(R_ - pitch * P_ / (2 * np.pi), pitch)
    b = np.minimum((s / pitch * nb).astype(int), nb - 1)
    prof = np.array([V[b == i].mean() for i in range(nb)])
    return (np.arange(nb) + 0.5) / nb * pitch, prof


# ---------------------------------------------------------------- real-vs-sim metrics table and fit cost
RECT = ('p1a', 'p1b', 'p1c', 'p2a')
LOOK = dict(az=0.0, el=35.0, kd=0.35, ka=0.65, sky_mm=2.0, sky_pow=1.5, soft_mm=0.3, gamma=1.0)


def all_metrics(getter):
    """getter(pk) -> (grey crop, x0, y1). Returns flat dict of metrics for every window."""
    out = {}
    for k in RECT:
        g, x0, y1 = getter(k)
        m = patch_metrics(g, x0, y1, k)
        for a in ('period_strokes', 'amp_pct', 'lip_sep', 'lip_con', 'wedge'):
            out['%s.%s' % (k, a)] = m[a]
    g, x0, y1 = getter('p2lane')
    out.update({'lane.' + a: b for a, b in lane_metrics(g, x0, y1).items()})
    out.update({'ring.' + a: b for a, b in ring_metrics(g, x0, y1).items()})
    return out


def real_getter(pk):
    c, (x0, y1) = real_crop(pk)
    return lum(c), x0, y1


def sim_getter(tag, look=None, modname='sand_relief_sim', phys=None):
    cache = {}
    def get(pk):
        T = load_sim(pk, tag, modname, phys=phys or dict(deposit='real'))
        return sim_gray_crop(T, pk, **(look or LOOK))
    return get


# (key, real value is measured; tol is the scale of "one unit of error")
TOL = {'period_strokes': 0.15, 'amp_pct': 0.35, 'lip_sep': 0.6, 'lip_con': 0.35, 'wedge': 0.5}


def fit_cost(real, sim, verbose=False):
    c = 0.0
    parts = {}
    for k, rv in real.items():
        sv = sim[k]
        a = k.split('.')[-1]
        if a in ('amp_pct', 'lip_con', 'lane_depth_pct', 'lane_pp_pct', 'ring_amp_pct'):
            e = (math.log(max(sv, 0.3) / max(rv, 0.3))) / 0.35
        elif a == 'period_strokes':
            e = (sv - rv) / 0.15
        elif a == 'lip_sep':
            e = (sv - rv) / 0.6
        elif a == 'wedge':
            e = max(0.0, sv - max(rv, 0.35)) / 0.5
        elif a == 'lane_width':
            e = (sv - rv) / 1.0
        elif a == 'ring_period':
            e = (sv - rv) / 0.1
        else:
            continue
        parts[k] = e
        c += e * e
    return (c, parts) if verbose else c


# ---------------------------------------------------------------- sheets
def _norm8(g, gain=2.2, mid=0.62):
    f = flat_field(g)
    return (np.clip((f - 1) * gain + mid, 0, 1) * 255).astype(np.uint8)


def _label(img, text, y=18):
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img.copy()
    cv2.rectangle(img, (0, 0), (img.shape[1], y + 6), (255, 255, 255), -1)
    cv2.putText(img, text, (4, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def patch_sheet(tag, out, look=None, modname='sand_relief_sim', phys=None, scale=0.8, keys=None):
    """Every patch, real above sim, same mm/px scale, labelled. Both flat-fielded to the same grey scale."""
    keys = keys or list(PATCHES)
    cols = []
    for k in keys:
        c, (x0, y1) = real_crop(k); gr = lum(c)
        T = load_sim(k, tag, modname, phys=phys or dict(deposit='real'))
        gs, _, _ = sim_gray_crop(T, k, **(look or LOOK))
        if gs.shape != gr.shape:
            gs = cv2.resize(gs, (gr.shape[1], gr.shape[0]))
        a = _label(_norm8(gr), 'REAL %s (%.1f mm strokes)' % (k, PATCHES[k]['sp']) if PATCHES[k]['sp'] else 'REAL %s' % k)
        b = _label(_norm8(gs), 'SIM  %s  [%s]' % (k, tag[:28]))
        col = np.vstack([a, np.full((6, a.shape[1], 3), 255, np.uint8), b])
        cols.append(col)
    H = max(c.shape[0] for c in cols)
    cols = [np.pad(c, ((0, H - c.shape[0]), (0, 8), (0, 0)), constant_values=255) for c in cols]
    sheet = np.hstack(cols)
    sheet = cv2.resize(sheet, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(out, sheet)
    return sheet


def whole_test_view(ph, h_path, out, box, look=None, modname='sand_relief_sim', mmpx=0.1):
    """Real rectified photo (left) and full-tray simulation (right), cropped to box=(x0, x1, y0, y1) mm; same scale."""
    import importlib
    mod = importlib.import_module(modname)
    T = mod.Table('mini', mm_px=mmpx, deposit='real')
    T.h = np.load(h_path).astype(np.float64)
    im = T.render_photo(**(look or LOOK))
    g = lum(np.array(im.convert('RGB'))[:, :, ::-1])
    half = (T.r_tray + 2.5) / mmpx
    # crop() in render_photo cut a square around the centre of side 2*half; world mm -> px
    def win(x0, x1, y0, y1):
        c = g.shape[0] / 2.0
        return slice(int(c - y1 / mmpx), int(c - y0 / mmpx)), slice(int(c + x0 / mmpx), int(c + x1 / mmpx))
    rs, cs = win(*box)
    gs = g[rs, cs]
    rect = lum(rectified(ph, mmpx))
    n = rect.shape[0]
    c = n / 2.0
    gr = rect[int(c - box[3] / mmpx):int(c - box[2] / mmpx), int(c + box[0] / mmpx):int(c + box[1] / mmpx)]
    h = min(gr.shape[0], gs.shape[0]); w = min(gr.shape[1], gs.shape[1])
    a = _label(_norm8(gr[:h, :w]), 'REAL (%s photo, rectified)' % ph); b = _label(_norm8(gs[:h, :w]), 'SIM (PHYS_REAL, full tray, parallel tiles)')
    sheet = np.vstack([a, np.full((6, w, 3), 255, np.uint8), b])
    sheet = cv2.resize(sheet, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    cv2.imwrite(out, sheet)
