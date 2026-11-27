#!/usr/bin/env python3
"""Plan JSON -> comb path -> .thr chunks (<= 11,500 points each, each chunk starts where the previous ended) + report.
    python3 tools/trex_make.py captures/relief-study/v4/trex/v1/plan_v1.json --out DIR --name trex_v1
The ball is parked at the eye (the purple bead of the maker's photo) at the very end. SIMULATION/PATH ONLY."""
import argparse, json, math, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_comb as sc, sand_relief_path as rp

LIMIT = 11500


def split_chunks(tr, limit=LIMIT):
    """tr: (n,2) theta/rho rows. chunks where chunk k+1's first row equals chunk k's last row (the ball is already there)"""
    chunks = []; i = 0
    while i < len(tr) - 1:
        j = min(len(tr), i + limit)
        chunks.append(tr[i:j]); i = j - 1
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plan'); ap.add_argument('--out', required=True); ap.add_argument('--name', default='trex')
    ap.add_argument('--order', default='background_first')
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    t0 = time.time()
    res = sc.comb(plan, order=a.order)
    path = np.asarray(res['path'], float)
    eye = np.array(plan['eye'], float)
    # park at the eye: straight there from the last point of the path (the eye section is drawn last, so it is a short move)
    gap = float(np.hypot(*(path[-1] - eye)))
    path = np.vstack([path, eye])
    res['path'] = path
    os.makedirs(a.out, exist_ok=True)
    R = plan.get('r_work', 114.0)
    tr, near = rp.to_thr_pts(path, R, max_step=4.0)
    chunks = split_chunks(tr)
    rep = dict(res['report'])
    rep.pop('per_section', None)
    files = []
    for k, ch in enumerate(chunks):
        fn = os.path.join(a.out, '%s_part%d.thr' % (a.name, k + 1))
        rp.write_thr(fn, ch, '%s part %d of %d' % (a.name, k + 1, len(chunks)))
        x = ch[:, 1] * R * np.cos(ch[:, 0]); y = ch[:, 1] * R * np.sin(ch[:, 0])
        files.append(dict(file=os.path.basename(fn), points=len(ch), minutes=round(rp.mini_minutes(ch), 1), path_m=round(float(np.hypot(np.diff(x), np.diff(y)).sum() / 1000), 2),
                          start_xy=[round(float(x[0]), 2), round(float(y[0]), 2)], end_xy=[round(float(x[-1]), 2), round(float(y[-1]), 2)]))
    rep.update(thr_points_total=int(len(tr)), thr_points_near_centre=int(near), chunks=files, total_minutes_est=round(sum(f['minutes'] for f in files), 1),
               total_minutes_if_one_file=round(rp.mini_minutes(tr), 1), park_move_mm=round(gap, 1), eye_xy=eye.tolist(),
               path_m_thr=round(rp.path_len_m(tr, R), 2), firmware_point_limit=12000, seconds_to_generate=round(time.time() - t0))
    # untouched sand: free disc area not within 3 mm of any stroke (rough, 0.5 mm grid)
    import cv2
    G = 0.5; n = int(2 * 118 / G)
    img = np.zeros((n, n), np.uint8)
    pts = np.round((path + 118) / G).astype(np.int32)
    cv2.polylines(img, [pts.reshape(-1, 1, 2)], False, 255, 1)
    from scipy import ndimage as ndi
    dist = ndi.distance_transform_edt(img == 0) * G
    yy, xx = np.mgrid[0:n, 0:n]; rr = np.hypot((xx + .5) * G - 118, (yy + .5) * G - 118)
    free = (rr < 114.0) & (dist > 3.2)
    rep['untouched_area_mm2_beyond_3p2mm_of_path'] = round(float(free.sum() * G * G), 1)
    lab, nl = ndi.label(free)
    rep['untouched_patches'] = [dict(area_mm2=round(float((lab == i).sum() * G * G), 1), centre_xy=[round(float(np.mean(((np.nonzero(lab == i)[1] + .5) * G - 118))), 1), round(float(-np.mean(((np.nonzero(lab == i)[0] + .5) * G - 118))), 1)])
                               for i in range(1, nl + 1) if (lab == i).sum() * G * G > 15]
    rep['untouched_ring_114_to_118'] = 'not combed (beyond the drawable radius)'
    json.dump(rep, open(os.path.join(a.out, a.name + '_report.json'), 'w'), indent=1)
    np.save(os.path.join(a.out, a.name + '_path.npy'), path)
    sc.plan_png(res, os.path.join(a.out, a.name + '_plan.png'), R=R, size=1600)
    print(json.dumps({k: v for k, v in rep.items() if k not in ('untouched_patches',)}, indent=1))
    print('untouched patches:', rep['untouched_patches'])


if __name__ == '__main__':
    main()
