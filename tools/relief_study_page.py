#!/usr/bin/env python3
"""Build the study page https://preview.example.com/oasis-relief-study.html from a JSON spec (SIMULATION study; never
contacts a table). Images are embedded as JPEG data URIs so the page works offline on a phone.

    python3 tools/relief_study_page.py captures/relief-study/v3/page.json /tmp/out.html
    scp /tmp/out.html previewhost:~/mockups/oasis-relief-study.html

Spec: {"title": str, "intro_html": str, "sections": [{"id", "h", "html", "figs": [{"src", "cap", "w", "crop"}]}]}
crop = [x0, y0, x1, y1] in source pixels (optional); w = max width in px the image is resized to (default 1400).
"""
import base64, io, json, os, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_uri(src, w=1400, crop=None, q=82):
    im = Image.open(os.path.join(ROOT, src)).convert('RGB')
    if crop:
        im = im.crop(tuple(crop))
    if im.size[0] > w:
        im = im.resize((w, round(im.size[1] * w / im.size[0])), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=q)
    return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()


CSS = """
body{font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#fafafa;color:#222}
main{max-width:1100px;margin:auto;padding:16px}
h1{font-size:24px;margin:8px 0}
h2{font-size:20px;margin:32px 0 8px;border-top:1px solid #ddd;padding-top:16px}
figure{margin:12px 0}
figure img{width:100%;height:auto;border:1px solid #ddd;border-radius:4px;background:#fff}
figcaption{font-size:14px;color:#555}
.tag{display:inline-block;font-size:12px;padding:1px 6px;border-radius:8px;margin-right:4px}
.sim{background:#e3eefc;color:#124}.maker{background:#fdeedd;color:#521}.est{background:#eee;color:#333}
table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}
nav a{margin-right:12px;font-size:14px}
.box{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px 14px}
"""


def build(spec):
    out = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
           'initial-scale=1"><title>%s</title><style>%s</style></head><body><main>' % (spec['title'], CSS)]
    out.append('<h1>%s</h1>' % spec['title'])
    out.append('<nav>' + ''.join('<a href="#%s">%s</a>' % (s['id'], s.get('nav', s['h'])) for s in spec['sections'])
               + '</nav>')
    out.append(spec.get('intro_html', ''))
    for s in spec['sections']:
        out.append('<h2 id="%s">%s</h2>%s' % (s['id'], s['h'], s.get('html', '')))
        for f in s.get('figs', []):
            out.append('<figure><img loading="lazy" src="%s"><figcaption>%s</figcaption></figure>'
                       % (data_uri(f['src'], f.get('w', 1400), f.get('crop')), f.get('cap', '')))
        out.append(s.get('after_html', ''))
    out.append('</main></body></html>')
    return '\n'.join(out)


if __name__ == '__main__':
    spec = json.load(open(sys.argv[1]))
    html = build(spec)
    open(sys.argv[2], 'w').write(html)
    print('wrote', sys.argv[2], len(html) // 1024, 'KB')
