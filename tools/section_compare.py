#!/usr/bin/env python3
"""Side-by-side pictures: our simulated raptor vs the maker's photos at the same scale. SIMULATION vs PHOTO."""
import os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = ROOT + '/captures/relief-study/v3/sections'
REF = ROOT + '/captures/relief-study/reference'
try:
    F = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 26)
except Exception:
    F = ImageFont.load_default()


def label(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, im.width, 38], fill=(255, 255, 255))
    d.text((8, 4), text, fill=(0, 0, 0), font=F)
    return im


def crop_win(png, win_mm, cx, cy, wpx_mm, w_mm, h_mm, out_mm_px=0.105, px=0.1):
    """crop w_mm x h_mm centred at (cx,cy) mm from a window render of size win_mm centred at win centre, rescale to out_mm_px"""
    im = Image.open(png)
    wc = win_mm
    c = im.width / 2.0
    x0 = c + (cx - wc[0] - w_mm / 2) / px; x1 = c + (cx - wc[0] + w_mm / 2) / px
    y0 = c - (cy - wc[1] + h_mm / 2) / px; y1 = c - (cy - wc[1] - h_mm / 2) / px
    cr = im.crop((int(x0), int(y0), int(x1), int(y1)))
    return cr.resize((int(round(w_mm / out_mm_px)), int(round(h_mm / out_mm_px))), Image.LANCZOS)


def stack_h(a, b, gap=16):
    h = max(a.height, b.height)
    out = Image.new('RGB', (a.width + b.width + gap, h), (255, 255, 255))
    out.paste(a, (0, 0)); out.paste(b, (a.width + gap, 0))
    return out


def stack_v(rows, gap=16):
    w = max(r.width for r in rows)
    out = Image.new('RGB', (w, sum(r.height for r in rows) + gap * (len(rows) - 1)), (255, 255, 255))
    y = 0
    for r in rows:
        out.paste(r, (0, y)); y += r.height + gap
    return out


def whole(name='raptor_sections', out='raptor_vs_maker_whole.png'):
    ours = Image.open('%s/%s_whole_sim.png' % (D, name)).convert('RGB')
    # our tray (r 118.5 incl. wall) is 1211 px at 0.2 mm/px; in the maker photo the tray is ~790 px wide (0.29 mm/px)
    ours = ours.resize((int(ours.width * 0.2 / 0.29), int(ours.height * 0.2 / 0.29)), Image.LANCZOS)
    mk = Image.open(REF + '/maker-dinosaur-mini.webp').convert('RGB').resize((1000, 1000), Image.LANCZOS)
    a = label(ours.copy(), 'simulation (ours)'); b = label(mk, "maker's photo (angled view)")
    stack_h(a, b).save('%s/%s' % (D, out))


def closeups(name='raptor_sections', out='raptor_vs_maker_closeups.png'):
    head = '%s/%s_head_sim.png' % (D, name)
    tail = '%s/%s_tail_sim.png' % (D, name)
    rows = []
    zoom = REF + '/zoom/'
    spec = [(head, (-55, 52), (-58, 62), 'head_neck.jpg', 'our head and neck'),
            (tail, (36, 0), (22, -6), 'body_thigh.jpg', 'our thigh and body'),
            (tail, (36, 0), (48, 6), 'tail_bg.jpg', 'our tail and background')]
    for png, wc, c, mk, lab in spec:
        if not os.path.exists(png):
            continue
        m = Image.open(zoom + mk).convert('RGB')
        W, H = 724, 610                      # same field for both: 76 x 64 mm at 0.105 mm/px (fits inside the 100 mm windows)
        m = m.crop(((m.width - W) // 2, (m.height - H) // 2, (m.width - W) // 2 + W, (m.height - H) // 2 + H))
        o = crop_win(png, wc, c[0], c[1], None, W * 0.105, H * 0.105).convert('RGB')
        rows.append(stack_h(label(o, 'simulation: ' + lab), label(m, "maker's photo: " + mk[:-4] + ' (centre crop)')))
    stack_v(rows).save('%s/%s' % (D, out))


def thumbs(name='raptor_v2', out='raptor_vs_maker_thumb.png'):
    ours = Image.open('%s/%s_whole_sim.png' % (D, name)).convert('RGB').resize((300, 300), Image.LANCZOS)
    mk = Image.open(REF + '/maker-dinosaur-mini.webp').convert('RGB').resize((1000, 1000), Image.LANCZOS).crop((90, 100, 910, 810)).resize((300, 260), Image.LANCZOS)
    im = Image.new('RGB', (616, 330), (255, 255, 255))
    im.paste(label(ours, 'simulation'), (0, 0)); im.paste(label(mk, "maker's photo"), (316, 0))
    im.save('%s/%s' % (D, out))


if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else 'raptor_sections'
    whole(name); closeups(name)
