#!/usr/bin/env python3
"""Builds the comparison page for tools/auto_cartoon.py (simulation only; private crops are embedded, page is tailnet-only).
   build/p2s-venv/bin/python tools/auto_cartoon_page.py  ->  captures/auto-cartoon/oasis-auto-cartoon.html"""
import base64, glob, io, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
from PIL import Image
import auto_cartoon as ac, sandsim, thrcommon as tc
ROOT = ac.ROOT; OUT = ROOT + '/captures/auto-cartoon/'
def uri(im, fmt='JPEG', size=420):
    im = im.convert('RGB').resize((size, size), Image.LANCZOS); b = io.BytesIO(); im.save(b, fmt, quality=85)
    return 'data:image/%s;base64,%s' % (fmt.lower(), base64.b64encode(b.getvalue()).decode())
people = ['bill', 'lek', 'alex', 'thomas']; T = {}
for n in people:
    t0 = time.time(); r = ac.cartoon(cv2.imread(OUT + 'crops/%s.jpg' % n)); T[n] = time.time() - t0
    import make_people as mpp
    mpp.to_thr(r['P'], OUT + n + '.thr'); ac.json.dump(dict(strokes=ac.to_strokes(r['P']), ok=True), open(OUT + n + '.json', 'w'))
    sandsim.render(tc.read_thr(OUT + n + '.thr'), 700).save(OUT + n + '.png')
def card(src, cap): return '<figure><img src="%s"><figcaption>%s</figcaption></figure>' % (src, cap)
rows = ''
for n in people:
    rows += '<h3>%s</h3><div class="row">%s%s%s</div>' % (n.capitalize(),
        card(uri(Image.open(OUT + 'crops/%s.jpg' % n)), 'Photo crop'),
        card(uri(sandsim.render(tc.read_thr(ROOT + '/patterns/people/%s.thr' % n), 700), 'PNG'), 'Hand-made'),
        card(uri(Image.open(OUT + n + '.png'), 'PNG'), 'Automatic (%.1f s)' % T[n]))
order = [2, 0, 3, 1]; lab = 'ABCD'
hid = '<div class="row4">' + ''.join(card(uri(Image.open(OUT + people[o] + '.png'), 'PNG', 300), str(i + 1)) for i, o in enumerate(order)) + '</div>'
hid += '<div class="row4">' + ''.join(card(uri(Image.open(OUT + 'crops/%s.jpg' % people[o]), 'JPEG', 300), lab[i]) for i, o in enumerate([1, 3, 0, 2])) + '</div>'
ex = ''
for f in sorted(glob.glob(OUT + 'extra/*.jpg')):
    b = f[:-4]; ex += '<div class="row">%s%s</div>' % (card(uri(Image.open(f), 'JPEG', 300), 'Photo crop'), card(uri(Image.open(b + '.png'), 'PNG', 300), 'Automatic'))
html = '''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Automatic cartoon faces (simulation)</title>
<style>body{font:16px/1.45 system-ui,sans-serif;background:#fff;color:#222;max-width:1000px;margin:0 auto;padding:12px}
h1{font-size:22px}h3{margin:22px 0 6px}.sim{background:#fff6d6;border:1px solid #e3c96a;padding:8px;border-radius:6px}
.row,.row4{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.row4{grid-template-columns:repeat(4,1fr);margin-bottom:8px}
figure{margin:0;text-align:center}img{width:100%%;border-radius:6px;display:block}figcaption{font-size:13px;color:#555}
@media(max-width:600px){.row{grid-template-columns:1fr 1fr}.row4 figcaption{font-size:11px}}</style>
<h1>Photo to cartoon face, automatically</h1>
<p class=sim><b>Simulation only.</b> Nothing here has been drawn on a table. The sand pictures are computer renderings of the line each face would make. Family photos stay on the laptop and this private page.</p>
<p>Each person: the photo, the hand-made cartoon from earlier, and the automatic one made from the photo alone. Same size, one continuous line, in and out through the shoulders.</p>
%s
<h2>Names hidden</h2><p>Top row: automatic cartoons 1 to 4. Bottom row: photos A to D, in a different order. Which cartoon goes with which photo?</p>%s
<h2>Other faces (no hand-made version)</h2><p>Tests on other photos. Long hair is the weak spot: it takes over the picture and the face shrinks.</p>%s
<p style="font-size:13px;color:#555">Built %s.</p>''' % (rows, hid, ex, time.strftime('%Y-%m-%d'))
open(OUT + 'oasis-auto-cartoon.html', 'w').write(html); print('ok', T)
