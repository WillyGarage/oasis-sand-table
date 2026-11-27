#!/usr/bin/env python3
"""sand_comb_repose - SIMULATION ONLY. Patch experiment at several angles of repose (spacing 1.2 and 5.0, depth 2.2, r 3.2)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool
import sand_comb_lab as lab
OUT = 'captures/relief-study/v3/lab'

def go(c):
    sp, ang = c
    tag = 's%.1f_d2.2_r3.2_a%d_push' % (sp, ang)
    res, _ = lab.run_case(sp, OUT, tag, deposit='push', step_frac=0.1, repose_deg=float(ang))
    res['repose_deg'] = ang
    json.dump(res, open(os.path.join(OUT, tag + '.json'), 'w'))
    return tag, {k: v for k, v in res.items() if not k.startswith('profile')}

if __name__ == '__main__':
    cs = [(s, a) for s in (1.2, 5.0) for a in (38, 42, 45)]
    with Pool(6) as p:
        for t, r in p.imap_unordered(go, cs): print(t, json.dumps(r), flush=True)
