#!/usr/bin/env python3
"""section_faces_hybrid WHO TABLE : few large combed sections (bg first, then subject), then the gallery's feature lines (eyes, brows,
nose, mouth from Portrait.features()) cut LAST as single grooves, nearest-neighbour ordered. SIMULATION/PATH ONLY.
Writes captures/relief-study/v3/faces/<who>_<table>_hyb.{thr,_plan.png,_report.json,_path.npy}."""
import json, math, os, sys
import numpy as np
from shapely.geometry import Polygon, box
from shapely import affinity
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_comb as sc, section_faces as sf
import sand_relief_path as rp

who, table = sys.argv[1], sys.argv[2]
fp = sf.FacePlan(who, table)
big = table == 'big'
k = 2.2 if big else 1.0
P, L = fp.P, fp.L
mk = P.mask
hair_m, face_m, body_m, beard_m, mouthp = mk('hair'), mk('face'), mk('body'), mk('beard'), mk('mouth patch')
S = fp.mask_geom(hair_m | face_m | body_m | beard_m | mk('earring') | mouthp)
hair = fp.mask_geom(hair_m, fill=False, smooth=1.0)
beard = fp.mask_geom(beard_m, fill=False) if beard_m.any() else sf.Polygon()
body = fp.mask_geom(body_m & ~hair_m & ~face_m, fill=False) if body_m.any() else sf.Polygon()
skin = fp.mask_geom(face_m | mouthp).difference(hair).difference(beard).buffer(0)
secs = []
def add(g, name, sp, ang, shrink):
    secs.extend(sf.geom_to_secs(g.buffer(0), name, spacing=round(sp * k, 2), mode='angle', angle=ang, shrink=shrink))
# skin: split down the nose line (forehead top 10 -> chin 152)
a, b = L[10], L[152]
d = (b - a) / np.hypot(*(b - a)); n = np.array([-d[1], d[0]])
big_ = 2000
left = sf.Polygon([a + d * -big_, a + d * big_, a + d * big_ + n * big_, a + d * -big_ + n * big_]).buffer(0)
right = sf.Polygon([a + d * -big_, a + d * big_, a + d * big_ - n * big_, a + d * -big_ - n * big_]).buffer(0)
sk = []
for nm, h in (('skinA', left), ('skinB', right)):
    g = skin.intersection(h); sk.append((nm, g, fp.tone(g)))
lit = max(sk, key=lambda t: t[2])[0]
for nm, g, t in sk:
    add(g, nm, 1.2 if nm == lit else 1.8, fp.rolldeg + (90 if nm == lit else 20), 1.4)
# hair: 3 masses as wedges round a crown above the head, strokes along the flow
if not hair.is_empty:
    crown = fp.xy([0, fp.lm(10)[1] + 60 * fp.sc])
    for i in range(3):
        a0, a1 = math.radians(i * 120 - 30 + 90 - 60 + 60 - 60), None
    # wedge limits measured from straight down (-90 deg): hair left / top / right of the crown
    cuts = [math.radians(x) for x in (200, 250, 290, 340)]
    wedges = [(cuts[0], cuts[1]), (cuts[1], cuts[2]), (cuts[2], cuts[3])]
    ext = [(math.radians(100), cuts[0]), (cuts[3], math.radians(440))]
    parts = [(wedges[0][0] - math.radians(100), wedges[0][1])]
    def wedge(a0, a1):
        pts = [crown] + [crown + 3000 * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a0, a1, 12)]
        return sf.Polygon(pts).buffer(0)
    for i, (a0, a1) in enumerate([(math.radians(95), math.radians(250)), (math.radians(250), math.radians(290)), (math.radians(290), math.radians(445))]):
        g = hair.intersection(wedge(a0, a1))
        if not g.is_empty:
            add(g, 'hair%d' % i, 2.7, math.degrees((a0 + a1) / 2) % 180, 1.4)
if not beard.is_empty:
    add(beard, 'beard', 2.4, fp.rolldeg + 90, 1.4)
if not body.is_empty:
    bb = body.bounds; xm = (bb[0] + bb[2]) / 2
    add(body.intersection(box(bb[0] - 5, bb[1] - 5, xm, bb[3] + 5)), 'bodyL', 2.0, 70, 1.4)
    add(body.intersection(box(xm, bb[1] - 5, bb[2] + 5, bb[3] + 5)), 'bodyR', 2.0, 110, 1.4)
claimed = sf.unary_union([sf.Polygon(s['poly']).buffer(0) for s in secs])
rest = S.difference(claimed.buffer(0.02)).buffer(-0.4).buffer(0.4)
secs += [s for s in sf.geom_to_secs(rest, 'rest', spacing=round(2.0 * k, 2), mode='angle', angle=45.0, shrink=1.2) if sf.Polygon(s['poly']).area > 15]
bg_sp = 9.0 if big else 5.0
R = fp.R
for i, a0 in enumerate([20, 110, 200, 290]):
    pts = [[0, 0]] + [[3 * R * math.cos(t), 3 * R * math.sin(t)] for t in np.linspace(math.radians(a0), math.radians(a0 + 90), 10)]
    secs.append(dict(name='bg%d' % i, kind='background', poly=pts, spacing=bg_sp, mode='angle', angle=float([100, 15, 150, 55][i]), phase=float(i)))
plan = dict(r_work=R, shrink=1.4, bg_gap=2.2, bg_shrink=1.0, sections=secs)
res = sc.comb(plan, order='background_first')
path = res['path']
# feature grooves, last
F = P.features()
loops = [np.asarray(x, float) for x in F['eyes'] + F['brows'] + ([F['nose']] if F['nose'] is not None else []) + ([F['mouth']] if F['mouth'] is not None else [])]
cur = path[-1]; feat = []; trav = 0.0; fl = 0.0
while loops:
    j = int(np.argmin([np.hypot(*(lp - cur).T).min() for lp in loops]))
    lp = loops.pop(j); i0 = int(np.argmin(np.hypot(*(lp - cur).T)))
    lp = np.roll(lp, -i0, axis=0); lp = np.vstack([lp, lp[:1]])
    trav += float(np.hypot(*(lp[0] - cur))); fl += float(np.hypot(*np.diff(lp, axis=0).T).sum())
    feat.append(lp); cur = lp[-1]
full = np.vstack([path] + feat)
res['path'] = full
out = sf.ROOT + '/captures/relief-study/v3/faces'; name = '%s_%s_hyb' % (who, table)
rep, _ = sc.save(res, plan, out, name)
tr, near = rp.to_thr_pts(full, R, tol=0.1, max_step=8.0)
rp.write_thr(os.path.join(out, name + '.thr'), tr, name)
seg = np.diff(full, axis=0); ln = np.hypot(*seg.T); m = ln > 0.3
v = seg[m]; ang = np.degrees(np.abs(np.arctan2(v[:-1, 0] * v[1:, 1] - v[:-1, 1] * v[1:, 0], (v[:-1] * v[1:]).sum(1))))
rep.update(thr_points=len(tr), path_m=round(float(ln.sum()) / 1000, 2), feature_groove_mm=round(fl, 1), feature_travel_mm=round(trav, 1),
           turns_over_60deg_final=int((ang > 60).sum()), sections=len(secs))
if R == 114.0: rep['mini_minutes_est'] = round(rp.mini_minutes(tr), 1)
json.dump(rep, open(os.path.join(out, name + '_report.json'), 'w'), indent=1)
print({k_: rep[k_] for k_ in ['sections', 'strokes', 'path_m', 'turns_over_60deg', 'turns_over_60deg_final', 'reversals', 'thr_points', 'feature_groove_mm', 'feature_travel_mm', 'travel_over_finished_mm'] + (['mini_minutes_est'] if R == 114 else [])})
