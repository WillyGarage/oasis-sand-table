#!/usr/bin/env python3
"""Comparison pictures for the combed-section faces (names hidden: Face A = lek, Face B = thomas). SIMULATION ONLY.
    section_faces_compare.py mini|big|closeups"""
import os, sys
from PIL import Image, ImageDraw, ImageFont
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2, F = ROOT + '/captures/relief-study/v2/', ROOT + '/captures/relief-study/v3/faces/'
FT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
FS = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
W = 760


def disc(path, black=True):
    im = Image.open(path).convert('RGB')
    s = im.width
    return im.resize((W, W), Image.LANCZOS)


def card(im, text):
    c = Image.new('RGB', (W, W + 44), (255, 255, 255))
    c.paste(im, (0, 44)); ImageDraw.Draw(c).text((10, 6), text, fill=(0, 0, 0), font=FS)
    return c


def grid(rows, title):
    gap = 14
    h = sum(r[0].height for r in rows) + gap * len(rows) + 50
    out = Image.new('RGB', (W * 2 + gap, h), (255, 255, 255))
    ImageDraw.Draw(out).text((10, 8), title, fill=(0, 0, 0), font=FT)
    y = 50
    for r in rows:
        out.paste(r[0], (0, y)); out.paste(r[1], (W + gap, y)); y += r[0].height + gap
    return out


def tray_crop(path, frac):
    im = Image.open(path).convert('RGB'); n = im.width
    m = int(n * (1 - frac) / 2)
    return im.crop((m, m, n - m, n - m))


if sys.argv[1] == 'mini':
    rows = []
    for tag, who, cur in (('Face A', 'lek', 'lek_gallery_mini.png'), ('Face B', 'thomas', 'thomas_gallery_mini.png')):
        rows.append((card(disc(F + who + '_mini_whole_sim.png'), tag + ' - new: combed sections'),
                     card(disc(V2 + cur), tag + ' - current gallery')))
    grid(rows, 'Mini, simulated (push rule, depth 2.2, ball r 3.2)').save(F + 'faces_compare_mini.png')
    for who in ('lek', 'thomas'):
        a = Image.open(F + who + '_mini_plan.png').convert('RGB'); a.save(F + who + '_mini_plan_view.png')
elif sys.argv[1] == 'big':
    new = Image.open(F + 'lek_big_win0_0_860_0.4_sim.png').convert('RGB').resize((W, W), Image.LANCZOS)
    cur = disc(V2 + 'lek_relief_big.png')
    grid([(card(new, 'Face A, 36-inch - new: combed sections'), card(cur, 'Face A, 36-inch - first relief study'))],
         '36-inch, simulated').save(F + 'lek_big_compare.png')
    new.save(F + 'lek_big.png')

if sys.argv[1] == 'closeups':
    # same window as the new close-ups (64 mm square at 0.105 mm/px = 610 px), gallery drawing cropped to the same mm
    wins = {'lek': {'eyes': (13.6, 6), 'mouth': (12, -40)}, 'thomas': {'eyes': (-3.7, 6.6), 'mouth': (-4, -40)}}
    gal = {'lek': 'lek_gallery_mini.png', 'thomas': 'thomas_gallery_mini.png'}
    mmpx = (118 + 4 + 2.5) * 2 / 1100.0 if False else 241.0 / 1100
    S = 610
    rows = []
    for tag, who in (('Face A', 'lek'), ('Face B', 'thomas')):
        for part in ('eyes', 'mouth'):
            cx, cy = wins[who][part]
            n = Image.open(F + '%s_mini_win%g_%g_64_0.105_sim.png' % (who, cx, cy)).convert('RGB').resize((S, S), Image.LANCZOS)
            g = Image.open(V2 + gal[who]).convert('RGB')
            px, py = 550 + cx / mmpx, 550 - cy / mmpx
            h = 32 / mmpx
            g = g.crop((int(px - h), int(py - h), int(px + h), int(py + h))).resize((S, S), Image.LANCZOS)
            c1 = Image.new('RGB', (S, S + 40), (255, 255, 255)); c1.paste(n, (0, 40)); ImageDraw.Draw(c1).text((8, 6), '%s %s - new: combed sections' % (tag, part), fill=(0, 0, 0), font=FS)
            c2 = Image.new('RGB', (S, S + 40), (255, 255, 255)); c2.paste(g, (0, 40)); ImageDraw.Draw(c2).text((8, 6), '%s %s - current gallery' % (tag, part), fill=(0, 0, 0), font=FS)
            rows.append((c1, c2))
    gap = 12
    out = Image.new('RGB', (S * 2 + gap, sum(r[0].height + gap for r in rows)), (255, 255, 255))
    y = 0
    for a, b in rows:
        out.paste(a, (0, y)); out.paste(b, (S + gap, y)); y += a.height + gap
    out.save(F + 'faces_closeups_mini.png')

if sys.argv[1] == 'hyb':
    # third column "new: sections + cut features" appended to the v1 pictures (v1 files are kept as *_v1.png)
    def third(src, label):
        return card(disc(src), label)
    v1 = Image.open(F + 'faces_compare_mini_v1.png').convert('RGB')
    rows = []
    for tag, who in (('Face A', 'lek'), ('Face B', 'thomas')):
        rows.append(third(F + who + '_mini_hyb_whole_sim.png', tag + ' - new: sections + cut features'))
    out = Image.new('RGB', (v1.width + 14 + W, v1.height), (255, 255, 255)); out.paste(v1, (0, 0))
    y = 50
    for r in rows:
        out.paste(r, (v1.width + 14, y)); y += r.height + 14
    out.save(F + 'faces_compare_mini.png')
    b1 = Image.open(F + 'lek_big_compare_v1.png').convert('RGB')
    c = card(Image.open(F + 'lek_big_hyb_win0_0_860_0.4_sim.png').convert('RGB').resize((W, W), Image.LANCZOS), 'Face A, 36-inch - new: sections + cut features')
    out = Image.new('RGB', (b1.width + 14 + W, b1.height), (255, 255, 255)); out.paste(b1, (0, 0)); out.paste(c, (b1.width + 14, 50))
    out.save(F + 'lek_big_compare.png')
