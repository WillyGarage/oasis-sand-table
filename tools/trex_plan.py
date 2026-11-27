#!/usr/bin/env python3
"""Build the section_comb plan (JSON + flow npz) from the decoded maker dinosaur. python3 tools/trex_plan.py [--out DIR] [--tag v1]
Reads v4/trex/section_masks.npz, section_fields.npz (trex_decode.py). Writes DIR/plan_<tag>.json and DIR/flow_<tag>.npz and
DIR/spacing.json. Coordinates: table mm (ring centre at 0,0)."""
import numpy as np, json, os, sys, math, argparse
from scipy import ndimage as ndi
from scipy.ndimage import gaussian_filter
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trex_decode as D
OUT = D.OUT
PX = D.PX; C = D.C
EYE = (-47.0, 66.6)          # table mm, centre of the purple bead

# stroke spacing (mm) and direction source per section, decided by eye from 24 mm crops of the rectified photo (STATUS.md):
#   ribs form once per two strokes, so spacing = rib period / 2; smooth sections (no ribs visible) get 2.3 (flat tongues), strokes
#   along the shape ('shape'); 'photo' = structure-tensor field measured on the photo
SPEC = {
    'snout': (0.6, 'photo'), 'jaw_a': (1.6, 'photo'), 'jaw_b': (2.0, 'photo'), 'jaw_c': (2.0, 'photo'), 'neck': (2.3, 'shape'),
    'throat': (2.8, 'photo'), 'chest': (0.6, 'photo'), 'belly_l': (1.1, 'photo'), 'thigh_l': (1.0, 'photo'), 'thigh_u': (0.7, 'photo'),
    'belly_r': (1.2, 'photo'), 'arm': (2.3, 'shape'), 'hand_a': (2.3, 'shape'), 'hand_b': (2.3, 'shape'), 'toe_a': (2.3, 'shape'),
    'toe_b': (2.3, 'shape'), 'toe_c': (2.3, 'shape'), 'shin': (0.7, 'photo'), 'foot_leg': (2.3, 'shape'), 'foot_a': (2.3, 'shape'),
    'foot_b': (2.3, 'shape'), 'foot_c': (2.3, 'shape'), 'gap_a': (1.2, 'photo'), 'gap_b': (2.3, 'shape'), 'gap_c': (1.2, 'photo'),
    'gap_d': (2.3, 'shape'), 'leg_r': (2.3, 'shape'), 'toe_r_a': (2.3, 'shape'), 'toe_r_b': (1.3, 'photo'),
    'tail_arch': (0.8, 'photo'), 'thigh_r': (1.2, 'photo'), 'tail_down': (0.9, 'photo'), 'tail_inner': (4.0, 'photo'),
    'tail_low': (0.6, 'photo'), 'eye': (1.8, 'photo'),
}
BG = {'ground': 5.0, 'wedge': 5.0, 'rings': 5.4}


def shape_field(mask):
    """stroke direction along the form: PCA axis for compact sections, else perpendicular to the smoothed distance-transform gradient"""
    area = mask.sum() * PX * PX
    ys, xs = np.nonzero(mask)
    out = np.zeros(mask.shape, np.float32)
    if area < 300:
        pts = np.c_[xs, -ys].astype(float); pts -= pts.mean(0)
        w, v = np.linalg.eigh(np.cov(pts.T)); ax = v[:, np.argmax(w)]
        out[:] = math.degrees(math.atan2(ax[1], ax[0])) % 180
        return out
    d = ndi.distance_transform_edt(mask) * PX
    d = gaussian_filter(d, 1.0 / PX)
    gy, gx = np.gradient(d); gy = -gy
    sg = 3.0 / PX
    w = gaussian_filter(mask.astype(np.float32), sg) + 1e-6
    a = gaussian_filter(gx * gx * mask, sg) / w; b = gaussian_filter(gy * gy * mask, sg) / w; c = gaussian_filter(gx * gy * mask, sg) / w
    th = 0.5 * np.arctan2(2 * c, a - b)                    # across-form direction
    return ((np.degrees(th) + 90) % 180).astype(np.float32)


def flow_arrays(names_fields, masks, px=0.4):
    """per-section direction arrays (deg) on a 0.4 mm table-frame grid; outside the section filled with the nearest inside value"""
    out = {}
    for n, (fld, m) in names_fields.items():
        ys, xs = np.nonzero(m); pad = int(8 / PX)
        y0, y1, x0, x1 = max(0, ys.min() - pad), min(1250, ys.max() + pad), max(0, xs.min() - pad), min(1250, xs.max() + pad)
        f = fld[y0:y1, x0:x1].astype(np.float32); mm = m[y0:y1, x0:x1]
        # fill outside by nearest inside (on the double-angle representation)
        idx = ndi.distance_transform_edt(~mm, return_distances=False, return_indices=True)
        f = f[idx[0], idx[1]]
        step = int(round(px / PX))
        f = f[::step, ::step]
        xl = (x0 + .5 - C) * PX + D.SHIFT[0]; yt = -(y0 + .5 - C) * PX + D.SHIFT[1]
        out[n] = f.astype(np.float16); out[n + '__org'] = np.array([xl, yt, PX * step])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=OUT); ap.add_argument('--tag', default='v1')
    ap.add_argument('--bg_spacing', type=float, default=None)
    a = ap.parse_args()
    M = np.load(OUT + 'section_masks.npz'); O = np.load(OUT + 'section_fields.npz')
    flows = {}; sections = []; spacing = {}
    # background first
    shift = D.SHIFT
    sh = lambda poly: [[float(x + shift[0]), float(y + shift[1])] for x, y in poly]
    bg_order = [('ground', sh(D.GROUND_POLY)), ('wedge', sh(D.WEDGE_POLY)), ('rings', None)]
    for n, poly in bg_order:
        sp = a.bg_spacing or BG[n]
        s = dict(name=n, kind='background', spacing=sp)
        if poly: s['poly'] = poly
        if n == 'rings':
            s.update(mode='rings', center=[0.0, 0.0])
        else:
            flows[n] = (O[n].astype(np.float32), M[n]); s.update(mode='flow', flow=dict(file=None, key=n))
        sections.append(s); spacing[n] = sp
    done = set()
    for n in D.ORDER:
        if n not in M.files or n not in SPEC:
            continue
        m = M[n]
        sp, src = SPEC[n]
        fld = O[n].astype(np.float32) if src == 'photo' else shape_field(m)
        flows[n] = (fld, m)
        polys = D.to_polys(m)
        spacing[n] = sp
        for k, (ring, holes) in enumerate(polys):
            nm = n if k == 0 else '%s#%d' % (n, k)
            s = dict(name=nm, kind='subject', spacing=sp, mode='flow', poly=ring.round(3).tolist(), holes=[h.round(3).tolist() for h in holes],
                     flow=dict(file=None, key=n), src=src)
            if n == 'eye':
                s.update(mode='rings', center=list(EYE)); s.pop('flow')
            sections.append(s)
    fz = flow_arrays(flows, None)
    fpath = os.path.join(a.out, 'flow_%s.npz' % a.tag)
    np.savez_compressed(fpath, **fz)
    for s in sections:
        if s.get('flow'): s['flow']['file'] = fpath
    plan = dict(r_work=114.0, shrink=0.95, bg_gap=0.95, bg_shrink=0.95, rim=0.6, keep_out=[[0.0, 0.0, 2.0]], eye=list(EYE), sections=sections,
                notes='maker dinosaur decoded from the rectified photo; strokes follow measured direction fields (mode flow)')
    json.dump(plan, open(os.path.join(a.out, 'plan_%s.json' % a.tag), 'w'))
    json.dump(spacing, open(os.path.join(a.out, 'spacing.json'), 'w'), indent=1)
    print('sections', len(sections), 'flow file', fpath)


if __name__ == '__main__':
    main()
