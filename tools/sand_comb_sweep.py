#!/usr/bin/env python3
"""sand_comb_sweep - SIMULATION ONLY. Runs the sand_comb_lab patch experiment for many (spacing, depth, ball radius)
cases in parallel (one process per case) and writes the same files as sand_comb_lab.run_case.

    python3 tools/sand_comb_sweep.py --out captures/relief-study/v3/lab --jobs 9        # all cases of the v3 study
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool
import sand_comb_lab as lab


def go(c):
    sp, d, r, out = c
    tag = 's%.1f_d%.1f_r%.1f_push' % (sp, d, r)
    if os.path.exists(os.path.join(out, tag + '.json')):
        return tag, None
    res, _ = lab.run_case(sp, out, tag, deposit='push', step_frac=0.1, depth=d, ball_r=r)
    return tag, res


def cases(out):
    c = [(s, 2.2, 3.2) for s in (5.5, 3.0, 2.0, 1.5, 1.2, 0.8)]
    for sp in (1.2, 5.0):
        c += [(sp, d, r) for d in (1.5, 2.2, 3.5, 5.0) for r in (3.2, 4.3, 5.0, 6.5)]
    seen = []
    for x in c:
        if x not in seen: seen.append(x)
    # slowest first: big ball, deep sand, tight spacing
    seen.sort(key=lambda x: -(x[2] ** 2 * x[1] / x[0]))
    return [(s, d, r, out) for s, d, r in seen]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--jobs', type=int, default=9)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with Pool(a.jobs) as p:
        for tag, res in p.imap_unordered(go, cases(a.out)):
            print(tag, 'skipped' if res is None else json.dumps({k: v for k, v in res.items() if not k.startswith('profile')}), flush=True)
