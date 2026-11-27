#!/usr/bin/env python3
"""sand_comb_sheets - SIMULATION ONLY. Re-renders the saved patch heights of sand_comb_sweep at ~0.105 mm/px (the
scale of the maker's photo crops) and builds contact sheets with a maker crop alongside.

    python3 tools/sand_comb_sheets.py --lab captures/relief-study/v3/lab
"""
import argparse, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_comb_lab as lab

ZOOM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'captures', 'relief-study', 'reference', 'zoom')
T = 300   # tile size px; 300 px x 0.105 mm = 31.5 mm


def font(sz):
    for f in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/mnt/c/Windows/Fonts/arial.ttf'):
        if os.path.exists(f): return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def sim_tile(lab_dir, sp, d, r, what='end'):
    tag = 's%.1f_d%.1f_r%.1f_push' % (sp, d, r)
    h = np.load(os.path.join(lab_dir, tag + '_h.npy')).astype(float)
    pt = lab.Patch(depth=d, ball_r=r)
    pt.h = h
    im = pt.render()
    W, H = im.size
    # 31.5 mm square: the right-hand stroke end (combed area to the left, the lip, then flat sand), centred on y = 0
    n = 315
    c0 = W - n - 12   # stay clear of the 2 px unsanded border at the patch edge
    r0 = H // 2 - n // 2
    return im.crop((c0, r0, c0 + n, r0 + n)).resize((T, T), Image.LANCZOS)


def maker_tile(name, box):
    im = Image.open(os.path.join(ZOOM, name)).convert('RGB')
    return im.crop((box[0], box[1], box[0] + T, box[1] + T))


def label(tile, text, sz=15):
    t = tile.copy()
    d = ImageDraw.Draw(t)
    f = font(sz)
    w = d.textlength(text, font=f)
    d.rectangle((0, 0, w + 8, sz + 7), fill=(255, 255, 255))
    d.text((4, 2), text, fill=(0, 0, 0), font=f)
    return t


def sheet(tiles, cols, title, path):
    rows = (len(tiles) + cols - 1) // cols
    g = 6
    top = 34
    S = Image.new('RGB', (cols * (T + g) + g, top + rows * (T + g) + g), (255, 255, 255))
    ImageDraw.Draw(S).text((g, 6), title, fill=(0, 0, 0), font=font(18))
    for k, t in enumerate(tiles):
        S.paste(t, (g + (k % cols) * (T + g), top + g + (k // cols) * (T + g)))
    S.save(path)
    print(path)


MAKER = dict(head=('head_neck.jpg', (180, 470), 'MAKER head/neck (ribs ~1.2 mm, lip)'),
             tail=('tail_bg.jpg', (330, 480), 'MAKER tail + background lines'))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--lab', required=True)
    a = ap.parse_args()
    mk = [label(maker_tile(n, b), t) for n, b, t in MAKER.values()]
    tiles = [label(sim_tile(a.lab, s, 2.2, 3.2), 'spacing %.1f  depth 2.2  ball r 3.2' % s) for s in (5.5, 3.0, 2.0, 1.5, 1.2, 0.8)]
    sheet(tiles + mk, 4, 'Spacing sweep (simulation, 0.105 mm/px, 31.5 mm tiles) vs maker crops', os.path.join(a.lab, 'sheet_spacing.png'))
    for sp in (1.2, 5.0):
        tiles = []
        for d in (1.5, 2.2, 3.5, 5.0):
            for r in (3.2, 4.3, 5.0, 6.5):
                tiles.append(label(sim_tile(a.lab, sp, d, r), 'spacing %.1f  depth %.1f  r %.1f' % (sp, d, r)))
        sheet(tiles + mk, 6 if False else 4, 'Depth (rows) x ball radius (cols) at spacing %.1f mm vs maker crops' % sp,
              os.path.join(a.lab, 'sheet_grid_s%.1f.png' % sp))
