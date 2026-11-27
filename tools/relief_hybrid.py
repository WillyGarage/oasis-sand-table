#!/usr/bin/env python3
"""Hybrid relief portrait (SIMULATION ONLY): the measured feature strokes of a portrait-gallery drawing
(patterns/portrait-gallery/drawings/*.oasisportrait: JSON, format oasis-prepared-portrait-v1, marks in mm on a table
of diameterMm, y up; kinds head / hairline / eye / brow / nose / smile / shade) placed on a raised head:

  * the 'head' outline (plus simple shoulders) is left standing as a plateau; the background around it is carved with
    arcs (tools/sand_relief_path.py);
  * the hair (head minus the 'hairline' face outline, or the part of the head above the brows when there is no
    hairline) gets a second tone: fine ribbing following its outline;
  * eyes, brows, nose and smile are kept as single grooves; 'shade' strokes are kept where they lie on the smooth
    skin (beard hairs, cheek folds) and dropped in the hair tone or in the carved background.

    python3 tools/relief_hybrid.py DRAWING.oasisportrait --name NAME [--table mini|big] [--fill 0.95]
"""
import argparse, json, math, os, sys
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE) + '/patterns/dog')
import sand_relief_path as rp
from relief_showcase import run_plan, TABLE, OUT
from relief_faces import shoulders


def load_marks(path, R, fill=1.0, shift=(0.0, 0.0)):
    o = json.load(open(path))
    k = R / (o['diameterMm'] / 2) * fill
    return [dict(kind=m['kind'], closed=bool(m.get('closed')), pts=np.asarray(m['points'], float) * k + np.asarray(shift) * R / 114.0) for m in o['marks']]


def hybrid_plan(cv, marks, bg_pitch=1.3, hair_pitch=1.1, face_ellipse=False):
    g = cv.g
    heads = [m for m in marks if m['kind'] == 'head']
    head = np.zeros((cv.N, cv.N), bool)
    for m in heads:
        p = m['pts'] if m['closed'] else np.vstack([m['pts'], m['pts'][:1]])
        head |= cv.fill_polys([p])
    hl = [m for m in marks if m['kind'] == 'hairline' and m['closed']]
    face = cv.fill_polys([hl[0]['pts']]) if hl else None
    if face is not None:
        head |= face
    feats = [m for m in marks if m['kind'] in ('eye', 'brow', 'nose', 'smile')]
    if face is None and face_ellipse:         # long hair framing the face: the face is an oval round the features
        E = np.vstack([m['pts'] for m in marks if m['kind'] == 'eye'])
        span = E[:, 0].max() - E[:, 0].min()
        cx, cy = E[:, 0].mean(), E[:, 1].mean() - 0.35 * span
        face = head & (((cv.X - cx) / (0.78 * span)) ** 2 + ((cv.Y - cy) / (1.15 * span)) ** 2 <= 1)
    if face is None:                          # no hairline: hair = the head above the brows (keeps the fringe)
        brow_top = max(m['pts'][:, 1].max() for m in marks if m['kind'] == 'brow')
        face = head & (cv.Y < brow_top + 0.6 * g)
    hair = head & ~face
    subj = head | (shoulders(cv, None, face, g) & cv.disc())
    subj = cv2.morphologyEx(subj.astype(np.uint8), cv2.MORPH_CLOSE, cv.disk_k(2.5 * g)).astype(bool)
    subj = cv.simplify(subj & cv.disc())
    din = cv.dist_in(subj)
    hm = hair & (din >= 0.6 * g)
    hm = cv2.morphologyEx(hm.astype(np.uint8), cv2.MORPH_OPEN, cv.disk_k(1.0 * g)).astype(bool)
    hair_zone = cv.dist_in(hm) > 0   # where the hair tone goes
    details, dropped = [], 0
    for m in feats:
        details.append(('closed', m['pts']) if m['closed'] else m['pts'])
    for m in marks:
        if m['kind'] != 'shade':
            continue
        q = np.clip(cv.to_px(m['pts']).astype(int), 0, cv.N - 1)
        on_skin = (din[q[:, 1], q[:, 0]] >= 0.6 * g) & ~hair_zone[q[:, 1], q[:, 0]]
        if on_skin.mean() >= 0.7:
            details.append(m['pts'])
        else:
            dropped += 1
    ribs = [rp.Fill('offset', hair_pitch * g, mask=hm, name='hair', wave=(0.25 * g, 6 * g))] if hm.any() else []
    fy = cv.Y[face].mean() if face.any() else 0.0
    fx = cv.X[face].mean() if face.any() else 0.0
    plan = cv.plan(subj, [rp.Fill('arcs', bg_pitch * g, focus=(fx, fy), name='background')], details=details,
                   ribs=ribs, simplify=False)
    plan['report']['shade_strokes_dropped'] = dropped
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('drawing')
    ap.add_argument('--name', required=True)
    ap.add_argument('--table', default='mini', choices=['mini', 'big'])
    ap.add_argument('--fill', type=float, default=1.0, help='scale of the drawing relative to its own table')
    ap.add_argument('--shift', type=float, nargs=2, default=(0.0, 0.0), help='move the drawing (Mini mm)')
    ap.add_argument('--face-ellipse', action='store_true', help='no hairline: the face is an oval round the features')
    a = ap.parse_args()
    tb = TABLE[a.table]
    cv = rp.Canvas(tb['r'], res=tb['res'])
    plan = hybrid_plan(cv, load_marks(a.drawing, cv.R, a.fill, a.shift), face_ellipse=a.face_ellipse)
    rep, _ = run_plan(cv, plan, a.name, a.table, title='hybrid relief portrait')
    print(a.name, rep['path_m'], 'm', rep.get('mini_minutes'), 'min', 'links', rep['links'], 'dropped shade strokes',
          rep['shade_strokes_dropped'], 'over raised:', [(l['mm'], l['between']) for l in rep['links_over_subject']])


if __name__ == '__main__':
    main()
