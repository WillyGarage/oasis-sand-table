#!/usr/bin/env python3
"""section_faces_run WHO TABLE [--k_sp x] [--bg_sp y] [--tag t] : plan -> comb -> .thr/report/plan png in captures/relief-study/v3/faces. SIMULATION ONLY."""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_comb as sc, section_faces as sf
ap = argparse.ArgumentParser(); ap.add_argument('who'); ap.add_argument('table')
ap.add_argument('--k_sp', type=float, default=None); ap.add_argument('--bg_sp', type=float, default=None); ap.add_argument('--tag', default=''); ap.add_argument('--max_step', type=float, default=8.0); ap.add_argument('--tol', type=float, default=0.1)
a = ap.parse_args()
t0 = time.time()
plan, fp = sf.face_plan(a.who, a.table, k_sp=a.k_sp, bg_sp=a.bg_sp)
out = sf.ROOT + '/captures/relief-study/v3/faces'
name = '%s_%s%s' % (a.who, a.table, a.tag)
json.dump(plan, open('/tmp/claude-1000/-home-bill-dev-WillyGarage-oasis/2353fa79-52d1-46e2-91bd-9ca566be13d4/scratchpad/%s_plan.json' % name, 'w'))
print('plan', len(plan['sections']), 'sections %.0fs' % (time.time() - t0), flush=True)
res = sc.comb(plan, order='background_first')
rep, tr = sc.save(res, plan, out, name, r_max_step=a.max_step)
import sand_relief_path as rp
R = plan['r_work']
tr, near = rp.to_thr_pts(res['path'], R, tol=a.tol, max_step=a.max_step)
rp.write_thr(os.path.join(out, name + '.thr'), tr, name)
rep.update(thr_points=len(tr), thr_tol_mm=a.tol, path_m_thr=round(rp.path_len_m(tr, R), 2))
if R == 114.0: rep['mini_minutes_est'] = round(rp.mini_minutes(tr), 1)
json.dump(rep, open(os.path.join(out, name + '_report.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in rep.items() if k != 'per_section'}, indent=1), '%.0fs' % (time.time() - t0))
