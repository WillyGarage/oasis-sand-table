#!/usr/bin/env python3
"""Decode the maker's dinosaur (rectified photo, v4/trex/maker_topdown.png) into a section plan. Photo-derived inputs only.

Method (details in captures/relief-study/v4/STATUS.md):
  1. ridge map of the rectified photo (lip lines) -> watershed basins -> merged where the boundary is weak (trex_segment.py)
  2. SUBJECT sections = unions of merged basins chosen by eye (SUBJECT); stripes of background glued to a basin are cut off by a
     morphological opening (OPEN_MM); regions that hide two sections are split with hand scribbles + watershed (REGROUP)
  3. background = free area of the disc: GROUND (straight horizontal lines), WEDGE (fan of stripes), RINGS (circles about the table
     centre; the ring centre was fitted from the photo's stripe orientations)
  4. per section: stroke-direction field (structure tensor, normalised convolution inside the section, lips excluded)
     and rib period (peak spacing along the gradient direction); stroke spacing = period / 2 where ribs form once per two strokes
  5. writes plan json, flow fields (npz), decoded.png
All coordinates in the plan are TABLE mm (x right, y up in the photo) after shifting the ring centre to (0, 0).
"""
import numpy as np, cv2, json, os, sys, math
from scipy import ndimage as ndi
from scipy.ndimage import map_coordinates, gaussian_filter
from skimage.segmentation import watershed
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = ROOT + '/captures/relief-study/v4/trex/'
PX = 0.2; C = 625
SHIFT = np.array([0.53, 4.69])          # rectified mm -> table mm (ring centre fitted at (-0.53, -4.69) in the rectified frame)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# name -> merged basin ids (v4/trex/basins.npz), chosen by eye against the photo
SUBJECT = {
    'snout': [73], 'eye': [13, 15, 19], 'jaw_a': [10], 'jaw_b': [21], 'jaw_c': [24], 'neck': [9],
    'throat': [27], 'chest': [29], 'belly_l': [35], 'thigh_l': [45], 'thigh_u': [48], 'belly_r': [42],
    'arm': [44], 'hand_a': [31], 'hand_b': [47], 'toe_a': [66], 'toe_b': [68], 'toe_c': [72],
    'shin': [69], 'foot_leg': [82], 'foot_a': [80], 'foot_b': [83], 'foot_c': [88], 'gap_a': [33], 'gap_b': [46],
    'gap_c': [38], 'gap_d': [63], 'tail': [53], 'tail_end': [51], 'leg_r': [4], 'toe_r_a': [86], 'toe_r_b': [89],
}
# basins with background stripes glued on: opened (radius mm) so thin stripes fall off and return to the background
OPEN_MM = {73: 3.5, 53: 3.5, 51: 3.0, 47: 3.5, 88: 3.0, 4: 3.0, 82: 2.5, 9: 2.0}
# (rectified-frame) scribbles splitting merged sections: sources -> {new name: polyline}
REGROUP = [
    (['tail', 'tail_end'], {
        'tail_arch': [(26, 10), (38, 24), (50, 42), (62, 54), (76, 57), (88, 45), (90, 20), (90, 6)],
        'thigh_r': [(22, -8), (40, -8), (35, -22)],
        'tail_down': [(90, -6), (89, -18)],
        'tail_inner': [(77, 33), (82, 16), (81, 3), (77, -9), (69, -18.5), (58, -25)],
        'tail_low': [(50, -31), (35, -34), (20, -35)],
    }),
]
# drawing / painter's order of subject sections (earlier = drawn earlier; a later section's lip sits on top of an earlier one)
ORDER = ['thigh_r', 'tail_arch', 'tail_down', 'tail_inner', 'tail_low', 'belly_r', 'thigh_u', 'thigh_l', 'belly_l', 'chest',
         'throat', 'gap_a', 'gap_b', 'gap_c', 'gap_d', 'leg_r', 'toe_r_a', 'toe_r_b', 'shin', 'foot_leg', 'foot_a', 'foot_b',
         'foot_c', 'arm', 'hand_a', 'hand_b', 'toe_a', 'toe_b', 'toe_c', 'neck', 'jaw_c', 'jaw_b', 'jaw_a', 'snout', 'eye']
GROUND_POLY = [(-130, -62), (-60, -62), (-40, -52), (55, -44), (130, -44), (130, -130), (-130, -130)]
WEDGE_POLY = [(50, -44), (112, -44), (112, -12), (95, -18), (80, -26), (62, -34), (50, -36)]
R_FREE = 114.0


def grid_mm():
    yy, xx = np.mgrid[0:1250, 0:1250]
    return (xx + .5 - C) * PX, -(yy + .5 - C) * PX


def mm_to_px(p):
    p = np.asarray(p, float)
    return np.c_[C + p[:, 0] / PX - 0.5, C - p[:, 1] / PX - 0.5]


def poly_mask(poly):
    m = np.zeros((1250, 1250), np.uint8)
    cv2.fillPoly(m, [np.round(mm_to_px(poly)).astype(np.int32)], 1)
    return m.astype(bool)


def subject_labels():
    d = np.load(OUT + 'basins.npz'); ws, r = d['ws'], d['r']
    names = list(SUBJECT)
    lab = np.zeros(ws.shape, np.int32)
    for i, n in enumerate(names):
        for b in SUBJECT[n]:
            m = ws == b
            if b in OPEN_MM:
                k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(OPEN_MM[b] / PX) + 1,) * 2)
                mo = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, k)
                nl, cl, st, _ = cv2.connectedComponentsWithStats(mo)
                m = np.zeros_like(m)
                for j in range(1, nl):
                    if st[j, 4] * PX * PX > 25: m |= cl == j
            lab[m] = i + 1
    # regroup
    for srcs, scr in REGROUP:
        mask = np.isin(lab, [names.index(s) + 1 for s in srcs])
        mk = np.zeros(lab.shape, np.int32)
        for j, (nm, pl) in enumerate(scr.items()):
            tmp = np.zeros(lab.shape, np.uint8)
            cv2.polylines(tmp, [np.round(mm_to_px(pl)).astype(np.int32)], False, 1, int(2.5 / PX))
            mk[(tmp > 0) & mask] = j + 1
        w = watershed(r, mk, mask=mask)
        for s in srcs:
            if s in names: lab[lab == names.index(s) + 1] = 0
        for j, nm in enumerate(scr):
            if nm not in names: names.append(nm)
            lab[w == j + 1] = names.index(nm) + 1
    # smooth boundaries, drop crumbs
    n = len(names)
    S = np.zeros((n + 1,) + lab.shape, np.float32)
    for i in range(1, n + 1):
        S[i] = gaussian_filter((lab == i).astype(np.float32), 0.5 / PX)
    S[0] = 0.5
    lab2 = np.argmax(S, 0).astype(np.int32)
    for i in range(1, n + 1):
        m = lab2 == i
        nl, cl, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
        for j in range(1, nl):
            if j != 1 + np.argmax(st[1:, 4]) and st[j, 4] * PX * PX < 8: lab2[cl == j] = 0
        if m.sum() * PX * PX < 8: lab2[m] = 0
    return lab2, names


def background_labels(lab):
    X, Y = grid_mm()
    free = (np.hypot(X, Y) <= R_FREE + 4) & (lab == 0)
    ground = poly_mask(GROUND_POLY) & free
    wedge = poly_mask(WEDGE_POLY) & free & ~ground
    rings = free & ~ground & ~wedge
    return dict(ground=ground, wedge=wedge, rings=rings)


# ---------------------------------------------------------------- fields
def tensor_fields(lo=0.35, hi=2.5):
    F = np.load(OUT + 'fields.npz'); g = F['gray'].astype(np.float32)
    g = gaussian_filter(g, lo / PX) - gaussian_filter(g, hi / PX)      # band-pass: ribs, not shading or lips
    gy, gx = np.gradient(g)
    gy = -gy                                           # table frame (y up)
    return gx * gx, gy * gy, gx * gy, g


def section_field(mask, J, sig_mm=3.5, erode_mm=2.5):
    """orientation (deg, mod 180; stroke direction = rib direction) over the whole mask by normalised convolution of the
    structure tensor on the eroded mask (lips excluded); falls back to wider smoothing where there is no data."""
    Jxx, Jyy, Jxy, _ = J
    core = ndi.binary_erosion(mask, iterations=max(1, int(erode_mm / PX)))
    if core.sum() < 200: core = ndi.binary_erosion(mask, iterations=max(1, int(1.0 / PX)))
    if core.sum() < 50: core = mask
    w0 = core.astype(np.float32)
    out = np.zeros(mask.shape, np.float32); done = np.zeros(mask.shape, bool); coh = np.zeros(mask.shape, np.float32)
    # work on a crop for speed
    ys, xs = np.nonzero(mask); pad = int(40 / PX)
    y0, y1, x0, x1 = max(0, ys.min() - pad), min(1250, ys.max() + pad), max(0, xs.min() - pad), min(1250, xs.max() + pad)
    sl = (slice(y0, y1), slice(x0, x1))
    comps = [a[sl] * w0[sl] for a in (Jxx, Jyy, Jxy)]
    wm = w0[sl]
    res_o = np.zeros(wm.shape, np.float32); res_ok = np.zeros(wm.shape, bool); res_c = np.zeros(wm.shape, np.float32)
    for s in (sig_mm, sig_mm * 2, sig_mm * 4, sig_mm * 10):
        sg = s / PX
        den = gaussian_filter(wm, sg)
        a, b, c = [gaussian_filter(x, sg) for x in comps]
        ok = (den > 0.02) & ~res_ok
        th = 0.5 * np.arctan2(2 * -c, a - b)             # gradient direction (table frame)
        co = np.sqrt((a - b) ** 2 + 4 * c ** 2) / (a + b + 1e-9)
        o = (np.degrees(th) + 90) % 180
        res_o[ok] = o[ok]; res_c[ok] = co[ok]; res_ok |= ok
    out[sl] = res_o; coh[sl] = res_c
    return out, coh


def peaks_period(g_bp, mask, ori, n=400, half=7.0, seed=1):
    """rib period (mm): median spacing of crest peaks along the gradient direction at random points inside the section"""
    rng = np.random.RandomState(seed)
    er = ndi.binary_erosion(mask, iterations=max(1, int(2.0 / PX)))
    if er.sum() < 100: er = mask
    ys, xs = np.nonzero(er)
    if len(ys) == 0: return np.nan, np.nan, 0
    sel = rng.choice(len(ys), min(n, len(ys)), replace=False)
    t = np.arange(-half, half + 1e-9, 0.05) / PX
    gaps = []
    for k in sel:
        y, x = ys[k], xs[k]
        o = math.radians(ori[y, x] + 90)                # gradient direction, table frame
        dx, dy = math.cos(o), -math.sin(o)              # image coords (y down)
        px_, py_ = x + t * dx, y + t * dy
        if px_.min() < 0 or px_.max() > 1249 or py_.min() < 0 or py_.max() > 1249: continue
        ins = map_coordinates(mask.astype(np.float32), [py_, px_], order=0) > 0.5
        v = map_coordinates(g_bp, [py_, px_], order=1)
        if not ins.all():                               # keep the run of the profile that contains the centre and stays inside
            c = len(t) // 2; a = c; b = c
            while a > 0 and ins[a - 1]: a -= 1
            while b < len(t) - 1 and ins[b + 1]: b += 1
            v = v[a:b + 1]
        if len(v) < 60: continue
        v = gaussian_filter(v, 0.18 / 0.05)
        thr = 0.25 * v.std()
        pk = [i for i in range(1, len(v) - 1) if v[i] > v[i - 1] and v[i] >= v[i + 1] and v[i] > thr]
        # merge peaks closer than 0.35 mm
        pp = []
        for i in pk:
            if pp and (i - pp[-1]) * 0.05 < 0.35:
                if v[i] > v[pp[-1]]: pp[-1] = i
            else: pp.append(i)
        if len(pp) >= 3:
            gaps.append(np.median(np.diff(pp)) * 0.05)
    if not gaps: return np.nan, np.nan, 0
    return float(np.median(gaps)), float(np.subtract(*np.percentile(gaps, [75, 25]))), len(gaps)


def to_polys(mask, eps=0.12):
    """mask -> list of (outer ring, [holes]) in TABLE mm"""
    m = gaussian_filter(mask.astype(np.float32), 0.35 / PX) > 0.5
    cs, hier = cv2.findContours(m.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    for i, c in enumerate(cs):
        if hier[0][i][3] != -1: continue
        if cv2.contourArea(c) * PX * PX < 6: continue
        def conv(cc):
            a = cv2.approxPolyDP(cc, eps / PX, True)[:, 0, :].astype(float)
            return np.c_[(a[:, 0] + .5 - C) * PX, -(a[:, 1] + .5 - C) * PX] + SHIFT
        holes = []
        j = hier[0][i][2]
        while j != -1:
            if cv2.contourArea(cs[j]) * PX * PX > 6: holes.append(conv(cs[j]))
            j = hier[0][j][0]
        out.append((conv(c), holes))
    return out


def main():
    lab, names = subject_labels()
    np.save(OUT + 'subject_lab.npy', lab)
    J = tensor_fields(); Jbg = tensor_fields(0.5, 6.0)
    F = np.load(OUT + 'fields.npz'); g = F['gray'].astype(np.float32)
    g_bp = gaussian_filter(g, 0.2 / PX) - gaussian_filter(g, 3.0 / PX)
    secs = []; fields = {}
    allf = np.zeros((1250, 1250), np.float32)
    for n in names:
        i = names.index(n) + 1
        m = lab == i
        if m.sum() * PX * PX < 8: continue
        ori, coh = section_field(m, J)
        per, iqr, nn = 0, 0, 0
        fields[n] = ori
        allf[m] = ori[m]
        secs.append(dict(name=n, kind='subject', mask=m, period=per, iqr=iqr, n_prof=nn, coh=float(np.median(coh[m])), area=float(m.sum() * PX * PX)))
    bg = background_labels(lab)
    for n, m in bg.items():
        ori, coh = section_field(m, Jbg, sig_mm=5.0, erode_mm=3.0)
        per, iqr, nn = 0, 0, 0
        fields[n] = ori
        allf[m] = ori[m]
        secs.append(dict(name=n, kind='background', mask=m, period=per, iqr=iqr, n_prof=nn, coh=float(np.median(coh[m])), area=float(m.sum() * PX * PX)))
    np.savez_compressed(OUT + 'section_fields.npz', **{k: v.astype(np.float16) for k, v in fields.items()})
    np.save(OUT + 'all_ori.npy', allf)
    np.savez_compressed(OUT + 'section_masks.npz', **{s['name']: s['mask'] for s in secs})
    info = [{k: v for k, v in s.items() if k != 'mask'} for s in secs]
    json.dump(info, open(OUT + 'decode_stats.json', 'w'), indent=1)
    for s in info:
        print('%-10s %-10s area %6.0f  period %5.2f (iqr %4.2f, n=%d)  coh %.2f' % (s['name'], s['kind'], s['area'], s['period'], s['iqr'], s['n_prof'], s['coh']))


if __name__ == '__main__':
    main()
