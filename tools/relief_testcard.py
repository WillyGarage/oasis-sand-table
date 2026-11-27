#!/usr/bin/env python3
"""Relief test card (v2), SIMULATION ONLY: raised bars 1, 2, 3 and 5 groove-widths wide, a smooth and a ribbed square
plateau, carved background at pitch 1.0 / 1.3 / 1.6 grooves (straight lines) and 1.0 (arcs). Uses
tools/sand_relief_path.py and tools/sand_relief_sim.py.

    python3 tools/relief_testcard.py [--table mini]   -> captures/relief-study/v2/card_<variant>_<table>.png + sheet
"""
import argparse, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_relief_path as rp
from relief_showcase import run_plan, TABLE, OUT

VARIANTS = [('lines10', 'lines', 1.0), ('lines13', 'lines', 1.3), ('lines16', 'lines', 1.6), ('arcs10', 'arcs', 1.0)]


def card(table, kind, pitch, name):
    tb = TABLE[table]
    cv = rp.Canvas(tb['r'], res=tb['res'])
    g, R = cv.g, cv.R
    X, Y = cv.X, cv.Y
    subj = np.zeros((cv.N, cv.N), bool)
    x = -0.62 * R
    for w in (1, 2, 3, 5):                                   # vertical bars, top half
        subj |= (X >= x) & (X <= x + w * g) & (Y > 0.08 * R) & (Y < 0.72 * R)
        x += w * g + 0.26 * R
    sq = 0.36 * R
    smooth = (X > -0.55 * R) & (X < -0.55 * R + sq) & (Y < -0.12 * R) & (Y > -0.12 * R - sq)
    ribbed = (X > 0.12 * R) & (X < 0.12 * R + sq) & (Y < -0.12 * R) & (Y > -0.12 * R - sq)
    subj |= smooth | ribbed
    rib_mask = (X > 0.12 * R + 0.8 * g) & (X < 0.12 * R + sq - 0.8 * g) & (Y < -0.12 * R - 0.8 * g) & (Y > -0.12 * R - sq + 0.8 * g)
    f = rp.Fill(kind, pitch * g, focus=(0.0, 0.0), angle=0.0, name='bg')
    plan = cv.plan(subj, [f], ribs=[rp.Fill('lines', 1.0 * g, mask=rib_mask, angle=90.0, name='ribs')], simplify=False)
    rep, _ = run_plan(cv, plan, name, table, title='relief test card ' + name)
    return name, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--table', default='mini', choices=['mini', 'big'])
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(card, *zip(*[(a.table, k, p, 'card_%s_%s' % (v, a.table)) for v, k, p in VARIANTS])))
    for name, rep in res:
        print(name, rep['path_m'], 'm', rep.get('mini_minutes'), 'min', 'links over raised', rep['links_over_subject'])
    from PIL import Image
    ims = [Image.open(os.path.join(OUT, n + '.png')).resize((700, 700)) for n, _ in res]
    W = Image.new('RGB', (1400, 1400))
    for k, im in enumerate(ims):
        W.paste(im, ((k % 2) * 700, (k // 2) * 700))
    W.save(os.path.join(OUT, 'card_sheet_%s.png' % a.table))


if __name__ == '__main__':
    main()
