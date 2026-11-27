#!/usr/bin/env python3
"""Five whole-table designs with many people on the table at once. SIMULATION ONLY (never contacts a table).

    python3 tools/sand_table_options.py   ->  captures/sand-app/options/*.png and oasis-sand-table-options.html

Uses 4 mm lines, 2.5 mm wipe spacing, 40 mm/s.  Reuses sand_table_mockup (icons), zone_samples (sand renderer,
lettering, frames), patterns/people + captures/guest-photo portraits (faces).
"""
import io, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_table_mockup as stm          # sets zone_samples.GROOVE = 4 mm
import zone_samples as z
import ring_scene as rs
import autumn_leaves
import sandsim
import thrcommon as tc

ROOT, RT, G, SPEED, PITCH = z.ROOT, z.RT, z.GROOVE, z.SPEED, z.PITCH
OUTD = os.path.join(ROOT, 'captures', 'sand-app')
IMG = os.path.join(OUTD, 'options')
os.makedirs(IMG, exist_ok=True)
P_, GP = os.path.join(ROOT, 'patterns') + '/', os.path.join(ROOT, 'captures', 'guest-photo') + '/'

# face key -> (thr file, label for small names).  Photo faces are public-domain test portraits standing in for
# guests; their labels are placeholders.
FACES = {
    'bill': (P_ + 'people/bill.thr', 'BILL'), 'lek': (P_ + 'people/lek.thr', 'LEK'),
    'alex': (P_ + 'people/alex.thr', 'ALEX'), 'thomas': (P_ + 'people/thomas.thr', 'THOMAS'),
    'p1': (GP + 'bowman-rich.thr', 'BEN'), 'p2': (GP + 'chari-rich.thr', 'RAJ'), 'p3': (GP + 'gabbard-rich.thr', 'ANA'),
    'p4': (GP + 'huffman-rich.thr', 'DEV'), 'p5': (GP + 'koch-rich.thr', 'CARA'), 'p6': (GP + 'ohara-rich.thr', 'FAY'),
    'p7': (GP + 'pocan-rich.thr', 'GUS'), 'p8': (GP + 'watkins-rich.thr', 'HAL'),
    'dog': (P_ + 'dog/dog_line.thr', 'DOG'),
}
_thr = {}

# extra interest pictures (the closed outlines used by the guest rings), added to the icons made earlier
for key, motif in (('pumpkin', 'pumpkin_ribbed'), ('telescope', 'telescope'), ('lotus', 'lotus_blossom'), ('rocket', 'rocket'),
                   ('dna', 'dna_open'), ('turkey', 'roast_turkey'), ('acorn', 'acorn'), ('crane', 'origami_crane'),
                   ('ship', 'mayflower_ship')):
    stm.ICONS[key] = (lambda m=motif: stm.motif1(m))
INTERESTS = ['reading-1', 'star-wars-2', 'clarinet-playing-3', 'thai-temples', 'hot-pot', 'guitar', 'teaching',
             'bacteriophages', 'hiking', 'telescope', 'rocket', 'lotus', 'pumpkin', 'dna', 'crane', 'ship']


def face(key, c, r):
    if key not in _thr:
        _thr[key] = tc.read_thr(FACES[key][0])
    return [z.thr_to_xy(_thr[key], r * 0.97) + np.array(c, float)]


def icon(key, c, r):
    return stm.icon_strokes(key, math.pi / 2, c, r)


def pol(r, deg):
    a = math.radians(deg)
    return np.array([r * math.cos(a), r * math.sin(a)])


def slots(n, start=90.0):
    return [start - 360.0 * i / n for i in range(n)]


def text_line(text, cx, y_base, h, sp=0.4):
    C = z.caps()
    adv = [C[c]['advance'] for c in text]
    total = (sum(adv) + sp * (len(text) - 1)) * h
    x, out = cx - total / 2, []
    for c, a in zip(text, adv):
        pts = np.asarray(C[c]['points'], float)
        xy = np.column_stack((x + pts[:, 0] * h, y_base + pts[:, 1] * h))
        out.append(np.vstack([xy, xy[-2:0:-1]]) if len(xy) > 2 else xy)
        x += (a + sp) * h
    return out


def bottom_name(text, r_base, h, sp=0.4):
    """Name along the lower arc, upright for someone looking at the table from the bottom of the picture."""
    C = z.caps()
    adv = [C[c]['advance'] for c in text]
    total = (sum(adv) + sp * (len(text) - 1)) * h
    rm = r_base - h / 2
    x, out = -total / 2, []
    for c, a in zip(text, adv):
        pts = np.asarray(C[c]['points'], float)
        th = -math.pi / 2 + (x + a * h / 2) / rm
        n, t = np.array([math.cos(th), math.sin(th)]), np.array([-math.sin(th), math.cos(th)])
        u, v = (pts[:, 0] - a / 2) * h, pts[:, 1] * h
        xy = np.outer(r_base - v, n) + np.outer(u, t)
        out.append(np.vstack([xy, xy[-2:0:-1]]) if len(xy) > 2 else xy)
        x += (a + sp) * h
    return out


def leaf(kind, deg, r_base, size):
    u = autumn_leaves.maple() if kind == 'maple' else autumn_leaves.oak()
    a = math.radians(deg)
    return z.rot(u * size, a - math.pi / 2) + r_base * np.array([math.cos(a), math.sin(a)])


class OZ:
    """One zone that is cleared and redrawn as a whole."""
    def __init__(self, label, r_in, r_out, area, what, paths, period):
        self.label, self.r_in, self.r_out, self.area, self.what, self.period = label, r_in, r_out, area, what, period
        self.paths = [np.asarray(p, float) for p in paths]

    @property
    def wipe(self):
        return self.area / PITCH / SPEED / 60

    @property
    def draw(self):
        return sum(z.length(p) for p in self.paths) / SPEED / 60


def ring_zone(label, r_in, r_out, what, paths, period):
    return OZ(label, r_in, r_out, math.pi * (r_out ** 2 - r_in ** 2), what, list(paths) + [z.frame(r_out - G / 2)], period)


def usable(r_in, r_out):
    lo, hi = r_in + 3.0, r_out - 6.5
    return (hi - lo) / 2, (hi + lo) / 2          # item radius, centre radius


# ---------------------------------------------------------------- the five options
def featured(key, r_out, name_h=20):
    """Featured face with its name once, on an arc under the face."""
    r = r_out - 38
    paths = face(key, (0, 14), r) + bottom_name(FACES[key][1], r_out - 9, name_h)
    return paths


def opt_A():
    z1 = ring_zone('Centre', 0, 155, 'Featured guest: a large face with the name once on an arc under it',
                   featured('alex', 155), 30)
    ri, rc = usable(155, 285)
    fa = ['bill', 'lek', 'thomas', 'p1', 'p4', 'p6']
    ps = []
    for k, d in zip(fa, slots(6)):
        c = pol(rc, d)
        ps += face(k, c + [0, 8], 38) + text_line(FACES[k][1], c[0], c[1] - 38, 13)
    z2 = ring_zone('Face ring', 155, 285, 'Six smaller faces of other guests, each with a small first name underneath', ps, 150)
    ri, rc = usable(285, 355)
    ic = [icon(k, pol(rc, d), ri) for k, d in zip(INTERESTS[:12], slots(12))]
    z3 = ring_zone('Interest ring', 285, 355, 'Twelve interest pictures from twelve guests', [p for q in ic for p in q], 180)
    return [z1, z2, z3], 19


def opt_B():
    z1 = ring_zone('Centre', 0, 170, 'Featured guest: a large face with the name once under it', featured('lek', 170), 45)
    ri, rc = usable(170, 270)
    seq = [('f', 'bill'), ('i', 'reading-1'), ('f', 'alex'), ('i', 'guitar'), ('f', 'thomas'), ('i', 'bacteriophages'), ('f', 'p6'), ('i', 'telescope')]
    ps = []
    for (k, v), d in zip(seq, slots(8)):
        ps += face(v, pol(rc, d), ri) if k == 'f' else icon(v, pol(rc, d), ri * 0.95)
    z2 = ring_zone('Pairs ring', 170, 270, 'Face, interest, face, interest: four guests, each next to one of their own interests', ps, 90)
    ri, rc = usable(270, 355)
    ps = []
    ics = ['hot-pot', 'star-wars-2', 'thai-temples', 'rocket', 'clarinet-playing-3', 'hiking', 'crane', 'teaching']
    for i, d in enumerate(slots(16, 90)):
        if i % 2 == 0:
            ps.append(leaf('maple' if (i // 2) % 2 == 0 else 'oak', d, 282, 58))
        else:
            ps += icon(ics[i // 2], pol(rc + 2, d), 28)
    z3 = ring_zone('Leaves ring', 270, 355, 'Autumn leaves with eight interest pictures tucked between them', ps, 240)
    return [z1, z2, z3], 13


def opt_C():
    ps = []
    for k, d in zip(['bill', 'lek', 'alex'], slots(3)):
        ps += face(k, pol(74, d), 62)
    z1 = ring_zone('Centre', 0, 140, 'Three faces sharing the centre, no single star', ps, 60)
    ri, rc = usable(140, 250)
    ps = []
    for k, d in zip(['thomas', 'p1', 'p2', 'p4', 'p5', 'p6', 'p7', 'dog'], slots(8, 112.5)):
        ps += face(k, pol(rc, d), ri)
    z2 = ring_zone('Face ring', 140, 250, 'Eight more faces (seven people and a dog)', ps, 90)
    ri, rc = usable(250, 355)
    ic = [icon(k, pol(rc, d), ri) for k, d in zip(INTERESTS[:12], slots(12, 75))]
    z3 = ring_zone('Interest ring', 250, 355, 'Twelve interest pictures', [p for q in ic for p in q], 120)
    return [z1, z2, z3], 23


def opt_D():
    ps = face('bill', (-75, 0), 74) + face('lek', (75, 0), 74)
    z1 = ring_zone('Centre', 0, 150, 'Two faces side by side', ps, 45)
    ri, rc = usable(150, 225)
    ic = [icon(k, pol(rc, d), ri) for k, d in zip(INTERESTS[:8], slots(8, 90))]
    z2 = ring_zone('Interest ring', 150, 225, 'Eight interest pictures', [p for q in ic for p in q], 120)
    ri, rc = usable(225, 355)
    ps = []
    for k, d in zip(['alex', 'thomas', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7'], slots(9)):
        ps += face(k, pol(rc, d), ri)
    z3 = ring_zone('Face ring', 225, 355, 'Nine faces, the biggest ring has the most room', ps, 150)
    return [z1, z2, z3], 19


def opt_E():
    """Six pie slices round a small hub: each slice is one guest (face plus two interests) and is redone on its own."""
    hub_r = 80.0
    hub = OZ('Hub', 0, hub_r, math.pi * hub_r ** 2, 'Featured guest face', face('alex', (0, 0), hub_r - 4) + [z.frame(hub_r - G / 2)], 30)
    zs = [hub]
    guests = ['bill', 'lek', 'thomas', 'p1', 'p4', 'p6']
    ints = [('reading-1', 'star-wars-2'), ('thai-temples', 'hot-pot'), ('bacteriophages', 'hiking'),
            ('guitar', 'teaching'), ('telescope', 'rocket'), ('lotus', 'crane')]
    area = math.pi * (RT ** 2 - hub_r ** 2) / 6
    for k in range(6):
        mid = 90 - 60 * k
        ps = face(guests[k], pol(228, mid), 56) + icon(ints[k][0], pol(131, mid), 29) + icon(ints[k][1], pol(319, mid), 29)
        lo = mid - 30      # one radial line and one rim arc per slice
        ps += [np.array([pol(hub_r + 2, lo), pol(RT - G, lo)])]
        ps += [z.arc(RT - G / 2, math.radians(mid + 30), math.radians(mid - 30)) if False else
               np.array([pol(RT - G / 2, a) for a in np.linspace(mid - 30, mid + 30, 40)])]
        zs.append(OZ('Slice %d' % (k + 1), hub_r, RT, area, 'One guest: face and two interest pictures', ps, 120))
    return zs, 6 + 12 + 1


OPTIONS = [
    ('A', 'Featured guest and gallery', 'One featured face with its name, a ring of smaller named faces, and an outer ring of interests.', opt_A),
    ('B', 'Pairs', 'Each guest shows a face next to one of their interests; autumn leaves with more interests tucked in around the edge.', opt_B),
    ('C', 'No single star', 'Three faces share the centre, then a ring of eight faces and a ring of interests.', opt_C),
    ('D', 'Faces on the outside', 'A pair of faces in the middle, interests in a ring, and the big outer ring full of faces.', opt_D),
    ('E', 'Pie slices', 'Six wedges, one guest each (a face and two interests) round a small hub. Each wedge is redone on its own, so every change is short.', opt_E),
]


def render_option(key, zs, tags=True):
    class Zs:
        pass
    objs = []
    for zz in zs:
        o = Zs(); o.paths = zz.paths; o.r_in = zz.r_in; o.r_out = zz.r_out; objs.append(o)
    return z.tray_image(objs, tags=tags, size=1400, out_px=900)


def main():
    data = {}
    sections = []
    for key, title, idea, fn in OPTIONS:
        zs, n = fn()
        im = render_option(key, zs, tags=(key != 'E'))
        im.save(os.path.join(IMG, 'option-%s.png' % key))
        busy = 0.0
        rows = []
        for i, zz in enumerate(zs):
            t = zz.wipe + zz.draw
            data.setdefault(key, []).append(dict(zone=zz.label, r_in=zz.r_in, r_out=zz.r_out, wipe=round(zz.wipe, 1),
                                                 draw=round(zz.draw, 1), total=round(t, 1), period=zz.period))
        if key == 'E':
            # hub every 30 min; each of the six slices every 90 min (one slice about every 15 min)
            busy = (zs[0].wipe + zs[0].draw) / zs[0].period + sum((s.wipe + s.draw) / s.period for s in zs[1:])
        else:
            busy = sum((zz.wipe + zz.draw) / zz.period for zz in zs)
        data[key + '_busy'] = round(busy * 100)
        print(key, [(zz.label, round(zz.wipe, 1), round(zz.draw, 1), zz.period) for zz in zs][:4], 'busy %d%%' % round(busy * 100), 'N', n)
    json.dump(data, open(os.path.join(IMG, 'times.json'), 'w'), indent=1)


def size_sheet():
    radii = [60, 50, 40, 32, 26]
    rows = [('Bill', 'bill'), ('Lek', 'lek'), ('Alex', 'alex'), ('Thomas', 'thomas'), ('Photo 1', 'p1'), ('Photo 2', 'p2'), ('Photo 3', 'p6')]
    tile = 200
    sh = Image.new('RGB', (len(radii) * tile + 90, len(rows) * tile), z.BG)
    d = ImageDraw.Draw(sh)
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15)
    for r, (lab, k) in enumerate(rows):
        d.text((6, r * tile + tile // 2), lab, fill=(40, 50, 40), font=f)
        for c, rad in enumerate(radii):
            sh.paste(stm.render_window(face(k, (0, 0), rad), 64, tile), (90 + c * tile, r * tile))
    for c, rad in enumerate(radii):
        d.text((90 + c * tile + 6, 4), '%d mm across' % (2 * rad), fill=(160, 40, 40), font=f)
    sh.save(os.path.join(IMG, 'face-sizes.png'))


def fmt(m):
    return '%.1f min' % m


def per(m):
    return 'every %d min' % m if m < 90 else ('about every %g hours' % (m / 60.0))


VERDICT = {
    'A': 'Works. The big face and its name read well. The small names read at 4 mm lines but only just (13 mm tall letters). The four hand-drawn small faces read as people; the photo-based ones are mushier. Outer pictures are on the small side.',
    'B': 'Works and looks the most finished. Only four faces, so fewer people appear. Leaves and pictures together are a little busy, but each picture stays clean.',
    'C': 'Works, and shows the most faces of any option. The three shared centre faces are close together, so the centre feels crowded. Its ring faces are 96 mm across, right at the limit for the photo-based faces.',
    'D': 'Works best for faces: the big outer ring gives them room, so even the photo-based ones read. The face ring is the slowest ring to redo.',
    'E': 'Works, and is the most different: changes are the shortest (about 12 minutes) so something new can appear every 20 minutes. One catch: it needs a new kind of wipe, one wedge at a time, instead of full rings. Faces are a bit smaller than in D.',
}


def build_page(data):
    secs = ''
    for key, title, idea, fn in OPTIONS:
        zs, n = fn()
        uri = z.jpeg_uri(Image.open(os.path.join(IMG, 'option-%s.png' % key)))[0]
        rows = ''
        for i, zz in enumerate(zs):
            if key == 'E' and i > 1:
                continue
            if key == 'E' and i == 1:
                rows += ('<li><span class="chip">2</span><div><b>Six slices</b> <span class="dim">(80 to 355 mm, 60 degrees each)</span><br>'
                         'Each slice is one guest: a face plus two interest pictures.<br>'
                         '<span class="t">Each slice: about every 2 hours, %s to redo (wipe %s + draw %s). With six slices, one slice changes about every 20 minutes.</span></div></li>'
                         % (fmt(zz.wipe + zz.draw), fmt(zz.wipe), fmt(zz.draw)))
                continue
            span = ('0 to %d mm' % zz.r_out) if zz.r_in == 0 else ('%d to %d mm' % (zz.r_in, zz.r_out))
            rows += ('<li><span class="chip">%d</span><div><b>%s</b> <span class="dim">(%s)</span><br>%s.<br>'
                     '<span class="t">Refreshes %s, %s to redo (wipe %s + draw %s).</span></div></li>'
                     % (i + 1, zz.label, span, zz.what, per(zz.period), fmt(zz.wipe + zz.draw), fmt(zz.wipe), fmt(zz.draw)))
        busy = data[key + '_busy']
        secs += ('<section><h2><span class="k">%s</span> %s</h2><p class="desc">%s</p><img class="big" src="%s" alt="Option %s">'
                 '<ol class="zones">%s</ol><p class="tot">Content from up to %d people visible at once. The ball is busy about %d%% of the time at this schedule.</p>'
                 '<p class="note"><b>My read:</b> %s</p></section>' % (key, title, idea, uri, key, rows, n, busy, VERDICT[key]))
    sizes = z.jpeg_uri(Image.open(os.path.join(IMG, 'face-sizes.png')))[0]
    page = PAGE3.replace('@@SECTIONS@@', secs).replace('@@SIZES@@', sizes)
    out = os.path.join(OUTD, 'oasis-sand-table-options.html')
    open(out, 'w').write(page)
    print('wrote', out, len(page) // 1024, 'KB')


PAGE3 = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>36-inch table: five designs with many people (simulation)</title>
<style>
:root { color-scheme: light; background: #f5f2e9; color: #242c24; font: 16px/1.5 "DM Sans", system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; }
main { max-width: 760px; margin: auto; padding: 18px 14px 60px; }
h1 { font: normal 2rem/1.1 Georgia, serif; letter-spacing: -.02em; margin: .2em 0 .3em; }
h2 { font: normal 1.5rem/1.2 Georgia, serif; margin: 0 0 4px; }
section { margin: 34px 0 0; padding-top: 20px; border-top: 1px solid #d6d4c7; }
.k { display: inline-block; background: #334c3c; color: #fff; border-radius: 6px; padding: 0 .45em; margin-right: .25em; font: 700 1rem/1.5 system-ui, sans-serif; }
.sim { background: #fff7d6; border: 2px solid #c9a227; border-radius: 10px; padding: 10px 12px; margin: 10px 0 16px; }
.sim b { color: #7a5a00; }
.desc { margin: 0 0 8px; color: #3a463a; }
img { width: 100%; height: auto; display: block; border-radius: 6px; }
.big { max-width: 700px; margin: 6px auto; }
ol.zones { list-style: none; padding: 0; margin: 10px 0 0; }
ol.zones li { display: flex; gap: 10px; padding: 9px 0; border-bottom: 1px solid #e4e1d4; }
.chip { flex: none; width: 26px; height: 26px; border-radius: 50%; background: #334c3c; color: #fff; text-align: center; font: 700 .9rem/26px system-ui, sans-serif; }
.dim { color: #6b7468; font-size: .9em; }
.t { color: #334c3c; }
.tot { margin: 10px 0 4px; font-weight: 600; }
.note { background: #fffdf7; border: 1px solid #d6d4c7; border-radius: 8px; padding: 8px 10px; margin: 8px 0 0; font-size: .95em; }
.basis { font-size: .9em; color: #505b50; }
</style></head><body><main>
<h1>Five table designs with many people on it at once</h1>
<div class="sim"><b>This is a computer simulation, not a photo of the table.</b> Nothing here was drawn in real sand or sent to either table.</div>
<p>The goal: the table shows content from lots of guests at the same time. Each ring (a "zone") is wiped and redrawn as a whole,
on its own schedule, while the other rings stay on display. The numbered dots on each picture match the list under it.</p>
<p class="basis">Lines 4 mm wide, wipe lines 2.5 mm apart, ball at 40 mm per second. Wipe time = area / 2.5 mm / 40 mm per second;
draw time = length of the lines / 40 mm per second. "Ball busy" adds up each ring's redo time divided by how often it refreshes; under 100% means it can keep up.
Faces: Bill, Lek, Alex and Thomas are the hand-drawn portraits. The other faces are real test photos (US government and NASA portraits)
converted the same way, standing in for guests, with placeholder first names. Inside one design every face is a different person; the same faces reappear in other designs.</p>
@@SECTIONS@@
<section><h2>How small can a face be?</h2>
<p>The same portraits shrunk, drawn with 4 mm lines. Each column is the width of the whole picture (bust included).</p>
<img class="big" src="@@SIZES@@" alt="Faces at five sizes">
<p class="note">The four hand-drawn faces still read as the right person down to about 80 mm across (hair, glasses, beard, braid all visible). At 64 mm only the glasses and braid survive, and at 52 mm they are blobs. The photo-based faces need about 100 mm across to read as a person; below 80 mm they are not recognizable. The head itself is about 60% of that width.</p></section>
</main></body></html>
'''


def main_all():
    main()
    size_sheet()
    data = json.load(open(os.path.join(IMG, 'times.json')))
    build_page(data)


if __name__ == '__main__':
    main_all()
