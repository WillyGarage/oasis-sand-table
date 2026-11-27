#!/usr/bin/env python3
"""Five pie-slice layouts for the 36-inch table. SIMULATION ONLY (never contacts a table).

    python3 tools/sand_slices.py  ->  captures/sand-app/slices/*.png and oasis-sand-slices.html

Reuses sand_table_options (faces, icons, ring zones, lettering).  Wipe time for a zone = area / 2.5 mm / 40 mm/s
(a slice is wiped as back-and-forth arcs inside the slice), then the zone's edge lines and pictures are drawn.
"""
import json, math, os, re, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_table_options as o
import zone_samples as z

RT, G = o.RT, o.G
OUTD = o.OUTD
IMG = os.path.join(OUTD, 'slices')
os.makedirs(IMG, exist_ok=True)

FACE_R, ICON_R = 48.0, 35.0
NAME = {k: v[1].title() for k, v in o.FACES.items()}
NAME['dog'] = 'the dog'
ALLICONS = ['star-wars-1', 'reading-1', 'guitar', 'hiking', 'hot-pot', 'telescope', 'bacteriophages', 'teaching',
            'thai-temples', 'rocket', 'lotus', 'clarinet-playing-3', 'dna', 'crane', 'ship', 'pumpkin',
            'star-wars-2', 'reading-2', 'turkey', 'acorn', 'star-wars-3', 'clarinet-playing-1', 'reading-3', 'clarinet-playing-2']
FACEPOOL = ['bill', 'alex', 'thomas', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'dog']


_EXT = {}


def icon_fit(key, c, rho):
    """Interest picture fitted inside a circle of radius rho (a few pictures have corners out past 1.0)."""
    if key not in _EXT:
        _EXT[key] = max(1.0, float(np.hypot(*np.vstack(o.icon(key, (0, 0), 1.0)).T).max()))
    return o.icon(key, c, rho / _EXT[key])


class Zone(o.OZ):
    kind = 'ring'
    a_lo = a_hi = None
    items = ()
    chip = (0, 0)


# ------------------------------------------------------------------ packing inside a slice
def pack(r_in, r_out, a_lo, a_hi, rhos, seed=1, tries=160):
    """Place circles of radius rhos inside the sector, maximising the smallest gap. Returns (centres, gap)."""
    mid = math.radians((a_lo + a_hi) / 2)
    half = math.radians((a_hi - a_lo) / 2)
    n = len(rhos)
    rng = np.random.default_rng(seed)

    def clamp(R, t, rho):
        R = min(max(R, r_in + rho + 5), r_out - rho - 7)
        lim = max(0.0, half - math.asin(min(1.0, (rho + 8) / R)))
        return R, min(max(t, -lim), lim)

    best, bs = None, -1e9
    for _ in range(tries):
        P = []
        for rho in rhos:
            P.append(list(clamp(rng.uniform(r_in, r_out), rng.uniform(-half, half), rho)))
        for it in range(300):
            xy = [np.array([R * math.cos(mid + t), R * math.sin(mid + t)]) for R, t in P]
            for i in range(n):
                for j in range(i + 1, n):
                    d = xy[j] - xy[i]
                    dist = float(np.hypot(*d)) or 1e-6
                    ov = rhos[i] + rhos[j] + 7 - dist
                    if ov > 0:
                        push = d / dist * ov * 0.5
                        xy[i] = xy[i] - push
                        xy[j] = xy[j] + push
            for i in range(n):
                R, t = math.hypot(*xy[i]), math.atan2(xy[i][1], xy[i][0]) - mid
                t = (t + math.pi) % (2 * math.pi) - math.pi
                P[i] = list(clamp(R, t, rhos[i]))
        xy = [np.array([R * math.cos(mid + t), R * math.sin(mid + t)]) for R, t in P]
        sc = min([float(np.hypot(*(xy[i] - xy[j]))) - rhos[i] - rhos[j] for i in range(n) for j in range(i + 1, n)] or [99.0])
        if sc > bs:
            best, bs = xy, sc
    return best, bs


def slice_zone(label, r_in, r_out, a_lo, a_hi, items, what, period, seed=1, min_gap=4.0, tries=160):
    """items: list of (kind, key[, rho]); kind 'f' face or 'i' icon.  Drops trailing items if they will not fit."""
    items = list(items)
    while True:
        rhos = [it[2] if len(it) > 2 else (FACE_R if it[0] == 'f' else ICON_R) for it in items]
        cs, gap = pack(r_in, r_out, a_lo, a_hi, rhos, seed, tries)
        if gap >= min_gap or len(items) <= 2:
            break
        print('  %s: dropping %s (gap %.1f)' % (label, items[-1][:2], gap))
        items = items[:-1]
    print('  %s: %d items, smallest gap %.1f mm' % (label, len(items), gap))
    ps = []
    for it, c, rho in zip(items, cs, rhos):
        ps += o.face(it[1], c, rho) if it[0] == 'f' else icon_fit(it[1], c, rho)
    ps.append(np.array([o.pol(r_in + G / 2, a_lo), o.pol(r_out - G / 2, a_lo)]))
    ps.append(np.array([o.pol(r_out - G / 2, a) for a in np.linspace(a_lo, a_hi, max(8, int((a_hi - a_lo) * 1.2)))]))
    area = math.pi * (r_out ** 2 - r_in ** 2) * (a_hi - a_lo) / 360.0
    zn = Zone(label, r_in, r_out, area, what, ps, period)
    zn.kind, zn.a_lo, zn.a_hi, zn.items = 'slice', a_lo, a_hi, items
    zn.chip = (r_out, a_lo)
    return zn


def ring(label, r_in, r_out, what, paths, period, chip_deg=-45.0, items=()):
    zn = Zone(label, r_in, r_out, math.pi * (r_out ** 2 - r_in ** 2), what, list(paths) + [z.frame(r_out - G / 2)], period)
    zn.items = items
    zn.chip = (r_out, chip_deg)
    return zn


def centre(key, r_out, period):
    zn = ring('Centre', 0, r_out, 'Featured person: a large face with the name lettered once on an arc under it',
              o.featured(key, r_out), period, -45.0, items=[('f', key)])
    return zn


def icon_ring(label, r_in, r_out, keys, period, what, phase=90.0, chip_deg=None):
    ri, rc = o.usable(r_in, r_out)
    ps = []
    for k, d in zip(keys, o.slots(len(keys), phase)):
        ps += icon_fit(k, o.pol(rc, d), ri)
    if chip_deg is None:
        chip_deg = phase - 360.0 / len(keys) * (len(keys) * 0.625) - 0  # between two icons, lower right
    return ring(label, r_in, r_out, what, ps, period, chip_deg, items=[('i', k) for k in keys])


def face_ring(label, r_in, r_out, keys, period, what, phase=90.0, chip_deg=-22.5):
    ri, rc = o.usable(r_in, r_out)
    ps = []
    for k, d in zip(keys, o.slots(len(keys), phase)):
        ps += o.face(k, o.pol(rc, d), ri)
    return ring(label, r_in, r_out, what, ps, period, chip_deg, items=[('f', k) for k in keys])


def sector_slices(prefix, r_in, r_out, n, start, content, what, period, seed0=1, **kw):
    out = []
    w = 360.0 / n
    for k in range(n):
        a_lo = start + w * k
        out.append(slice_zone('%s %d' % (prefix, k + 1), r_in, r_out, a_lo, a_lo + w, content[k],
                              what, period, seed0 + k, **kw))
    return out


# ------------------------------------------------------------------ the five layouts
def faces_f(keys):
    return [('f', k) for k in keys]


def icons_i(keys):
    return [('i', k) for k in keys]


def mix(fs, ics):
    return faces_f(fs) + icons_i(ics)


def lay1(change=False):
    z1 = centre('lek', 140, 45)
    z2 = icon_ring('Interest ring', 140, 220, ALLICONS[:12], 180, 'Twelve interest pictures from twelve people')
    fs = [('bill', 'alex'), ('thomas', 'p1'), ('p2', 'p3'), ('p4', 'p5'), ('p6', 'p7'), ('p8',)]
    ics = ALLICONS[12:24]
    spec = []
    for k in range(6):
        if change and k == 5:
            spec.append(mix(('dog', 'lek'), ['star-wars-2', 'teaching']))
        else:
            spec.append(mix(fs[k], ics[2 * k:2 * k + 3 if len(fs[k]) == 1 else 2 * k + 2]))
    # slice 6 has one face and three pictures
    if not change:
        spec[5] = mix(('p8',), ics[10:12] + ['star-wars-2'])
    sl = sector_slices('Slice', 220, RT, 6, 60, spec, 'Faces and interest pictures mixed', 180, 11)
    return [z1, z2] + sl


def lay2():
    z1 = centre('lek', 140, 45)
    z2 = icon_ring('Interest ring', 140, 210, ALLICONS[6:18], 180, 'Twelve interest pictures from twelve people')
    groups = [('star-wars-1', ['bill', 'p1', 'p4'], 'Star Wars (lightsaber)'),
              ('guitar', ['alex', 'p2'], 'Guitar'),
              ('hiking', ['thomas', 'p3', 'dog'], 'Hiking'),
              ('reading-1', ['p5', 'p6'], 'Reading'),
              ('hot-pot', ['p7', 'p8'], 'Hot pot'),
              ('telescope', ['p2', 'p6'], 'Stargazing')]
    out = [z1, z2]
    for k, (ic, fs, nm) in enumerate(groups):
        w = 60.0
        a_lo = 60 + w * k
        zn = slice_zone('Slice %d' % (k + 1), 210, RT, a_lo, a_lo + w, [('i', ic, 32.0)] + [('f', f, 46.0) for f in fs],
                        'Shared interest: %s' % nm, 180, 21 + k, tries=700)
        zn.group = '%s: %s' % (nm, ', '.join(NAME[it[1]] for it in zn.items if it[0] == 'f'))
        out.append(zn)
    return out


def lay3():
    z1 = centre('lek', 140, 45)
    z2 = face_ring('Face ring', 140, 250, ['bill', 'p1', 'alex', 'p2', 'thomas', 'p3', 'dog', 'p4'], 180,
                   'Eight faces (seven people and a dog)', 90, -22.5)
    ics = ALLICONS * 2
    spec, i = [], 0
    for k in range(8):
        n = 3 if k % 2 == 0 else 2
        spec.append(icons_i(ics[i:i + n]))
        i += n
    sl = sector_slices('Slice', 250, RT, 8, 90 - 22.5 + 0, spec, 'Interest pictures', 180, 31)
    return [z1, z2] + sl


def lay4():
    z1 = centre('lek', 140, 45)
    fs = ['bill', 'p1', 'alex', 'p2', 'thomas', 'p3', 'p4', 'p5']
    ics = ALLICONS
    inner = [mix(fs[2 * k:2 * k + 2], [ics[k]]) for k in range(4)]
    outer = [[('f', ['p6', 'p7', 'p8', 'dog', 'bill', 'p1', 'alex', 'p2'][k], 46.0)] + [('i', i, 31.0) for i in ics[4 + 2 * k:6 + 2 * k]] for k in range(8)]
    zi = sector_slices('Inner slice', 140, 250, 4, 0, inner, 'Faces and interest pictures mixed', 180, 41)
    zo = sector_slices('Outer slice', 250, RT, 8, 22.5, outer, 'Faces and interest pictures mixed', 180, 51)
    return [z1] + zi + zo


def lay5():
    z1 = centre('lek', 140, 45)
    pool = [k for k in FACEPOOL] + ['alex']
    spec, fi, ii = [], 0, 0
    for k in range(5):
        nf = 3 if k < 3 else 2
        fs = pool[fi:fi + nf]
        fi += nf
        spec.append(mix(fs, ALLICONS[ii:ii + (5 - nf)]))
        ii += 5 - nf
    sl = sector_slices('Big slice', 140, RT, 5, 90 - 36, spec, 'Faces and interest pictures mixed', 180, 61)
    return [z1] + sl


# ------------------------------------------------------------------ rendering
def relabel(zs):
    for i, zz in enumerate(zs):
        if zz.kind == 'slice':
            zz.label = re.sub(r'\d+$', str(i + 1), zz.label)


def render(zs, out_px=900, tags=True):
    class W: pass
    objs = []
    for zz in zs:
        w = W(); w.paths = zz.paths; w.r_in = zz.r_in; w.r_out = zz.r_out; objs.append(w)
    im = z.tray_image(objs, tags=False, size=1400, out_px=out_px)
    if tags:
        d = ImageDraw.Draw(im)
        c = out_px / 2
        s = 0.94 * c / RT
        f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', out_px // 50)
        rr = out_px // 62
        for i, zz in enumerate(zs):
            r, a = zz.chip
            a = math.radians(a)
            x, y = c + r * s * math.cos(a), c - r * s * math.sin(a)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(51, 76, 60), outline=(255, 255, 255), width=2)
            d.text((x, y), str(i + 1), fill='white', font=f, anchor='mm')
    return im


def tint_slices(im, zs, color=(80, 190, 120), alpha=90):
    out_px = im.size[0]
    c = out_px / 2
    s = 0.94 * c / RT
    mask = Image.new('L', im.size, 0)
    md = ImageDraw.Draw(mask)
    for zz in zs:
        pts = []
        for r, a in ([(zz.r_out, a) for a in np.linspace(zz.a_lo, zz.a_hi, 40)] +
                     [(zz.r_in, a) for a in np.linspace(zz.a_hi, zz.a_lo, 40)]):
            ar = math.radians(a)
            pts.append((c + r * s * math.cos(ar), c - r * s * math.sin(ar)))
        md.polygon(pts, fill=alpha)
    return Image.composite(Image.new('RGB', im.size, color), im.convert('RGB'), mask)


def people(zs):
    ks = {it[1] for zz in zs for it in zz.items if it[0] == 'f'}
    return len([k for k in ks if k != 'dog']), ('dog' in ks)


LAYOUTS = [
    ('1', 'Bill\'s example: centre, interest ring, six outer slices',
     'A featured person in the middle, a ring of interest pictures, and six outer slices that each mix faces and pictures.', lay1),
    ('2', 'Shared-interest slices',
     'Same centre and ring, but each outer slice is one interest picture with the faces of the people who share it.', lay2),
    ('3', 'Face ring and eight picture slices',
     'Featured person in the middle, a ring of faces, and eight outer slices of interest pictures.', lay3),
    ('4', 'Bricks',
     'Inner ring in four slices, outer ring in eight slices, offset so the slice lines never line up. Each slice mixes faces and pictures.', lay4),
    ('5', 'Five big slices',
     'Featured person in the middle and five large slices straight out to the rim, with the most room per picture.', lay5),
]

PERIODS = {}


def zone_times(zs):
    rows, busy = [], 0.0
    for zz in zs:
        busy += (zz.wipe + zz.draw) / zz.period
        rows.append(zz)
    return busy


def fmt(m):
    return '%.1f min' % m


def per(m):
    return 'every %d min' % m if m < 90 else ('every %g hours' % (m / 60.0))


def span(zz):
    return ('0 to %d mm' % zz.r_out) if zz.r_in == 0 else ('%d to %d mm' % (zz.r_in, zz.r_out))


def zone_html(zs, key):
    rows, i = '', 0
    if key == '2':
        pass
    nsl = len([zz for zz in zs if zz.kind == 'slice'])
    for i, zz in enumerate(zs):
        if zz.kind == 'ring':
            what = zz.what
            if zz.r_in == 0:
                nm = 'Centre'
            else:
                nm = zz.label
            sp = span(zz)
            rows += ('<li><span class="chip">%d</span><div><b>%s</b> <span class="dim">(%s)</span><br>%s.<br>'
                     '<span class="t">Refreshes %s, %s to redo (wipe %s + draw %s).</span></div></li>'
                     % (i + 1, nm, sp, what, per(zz.period), fmt(zz.wipe + zz.draw), fmt(zz.wipe), fmt(zz.draw)))
        else:
            nf = len([1 for it in zz.items if it[0] == 'f'])
            ni = len(zz.items) - nf
            if hasattr(zz, 'group'):
                what = 'Group: <b>%s</b>' % zz.group
            else:
                what = '%d faces and %d pictures' % (nf, ni)
            rows += ('<li><span class="chip">%d</span><div><b>%s</b> <span class="dim">(%d to %d mm, %d degrees)</span><br>%s.<br>'
                     '<span class="t">Refreshes %s, %s to redo (wipe %s + draw %s).</span></div></li>'
                     % (i + 1, zz.label, zz.r_in, zz.r_out, round(zz.a_hi - zz.a_lo), what, per(zz.period),
                        fmt(zz.wipe + zz.draw), fmt(zz.wipe), fmt(zz.draw)))
    return rows


VERDICT = {
    '1': 'Works and matches the idea. Faces are the full 96 mm. A slice that size only holds two faces and one or two pictures, so "3 to 5 items" ends up mostly 3. The twelve ring pictures read well at 70 mm.',
    '2': 'The easiest to understand at a glance, since each slice tells one story. One catch: the picture plus three faces does not fit in a 60 degree slice at readable size, so the lightsaber and hiking slices show two faces each. A third sharer needs a bigger slice. Ring pictures are 60 mm here, a little small.',
    '3': 'Calm and tidy, with the biggest face ring (100 mm faces). Outer slices are only pictures, so fewer people appear (8), and the two-picture slices look a little empty. Cheapest slices to redo.',
    '4': 'The most people and the most variety, and the staggered lines look good. Outer slices are tight with three items, and it has the most straight slice edges (12 lines) to keep clean in real sand.',
    '5': 'Looks the best. Five items per slice with room between them, and only five slice lines to keep clean. The cost: each slice takes about 13 minutes to redo, the longest of the five.',
}


def main():
    meta = {}
    secs = ''
    built = {}
    for key, title, idea, fn in LAYOUTS:
        print('layout', key)
        zs = fn()
        relabel(zs)
        built[key] = zs
        im = render(zs)
        im.save(os.path.join(IMG, 'layout-%s.png' % key))
        busy = zone_times(zs)
        npeople, dog = people(zs)
        sl = [zz for zz in zs if zz.kind == 'slice']
        meta[key] = dict(busy=round(busy * 100), people=npeople, dog=dog,
                         zones=[(zz.label, zz.r_in, zz.r_out, round(zz.wipe, 1), round(zz.draw, 1), zz.period) for zz in zs])
        print('  people %d dog %s busy %d%%' % (npeople, dog, round(busy * 100)))
        for zz in zs:
            print('   %-14s wipe %5.1f draw %5.1f total %5.1f' % (zz.label, zz.wipe, zz.draw, zz.wipe + zz.draw))
    json.dump(meta, open(os.path.join(IMG, 'times.json'), 'w'), indent=1)
    # before / after
    before, after = built['1'], lay1(change=True)
    ib = render(before)
    ia = tint_slices(render(after), [after[7]])
    ib.save(os.path.join(IMG, 'change-before.png'))
    ia.save(os.path.join(IMG, 'change-after.png'))
    build_page(built, meta, after)


def build_page(built, meta, after):
    secs = ''
    for key, title, idea, fn in LAYOUTS:
        zs = built[key]
        uri = z.jpeg_uri(Image.open(os.path.join(IMG, 'layout-%s.png' % key)))[0]
        busy, n, dog = meta[key]['busy'], meta[key]['people'], meta[key]['dog']
        sl = [zz for zz in zs if zz.kind == 'slice']
        if sl:
            avg = sum(zz.wipe + zz.draw for zz in sl) / len(sl)
            mx = max(zz.wipe + zz.draw for zz in sl)
            sched = ('Suggested schedule: centre changes every 45 min, one person at a time. Any full ring about every 3 hours. '
                     'Each slice %s; with %d slices, a new slice is redone about every %d min. A slice takes %s to %s to redo.'
                     % (per(sl[0].period), len(sl), sl[0].period // len(sl), fmt(min(zz.wipe + zz.draw for zz in sl)), fmt(mx)))
        secs += ('<section><h2><span class="k">%s</span> %s</h2><p class="desc">%s</p><img class="big" src="%s" alt="Layout %s">'
                 '<ol class="zones">%s</ol><p class="sched">%s</p>'
                 '<p class="tot">Content from %d people%s visible at once. The ball is busy about %d%% of the time at this schedule.</p>'
                 '<p class="note"><b>My read:</b> %s</p></section>'
                 % (key, title, idea, uri, key, zone_html(zs, key), sched, n, ' and a dog' if dog else '', busy, VERDICT.get(key, '')))
    sl = after[7]
    ub = z.jpeg_uri(Image.open(os.path.join(IMG, 'change-before.png')))[0]
    ua = z.jpeg_uri(Image.open(os.path.join(IMG, 'change-after.png')))[0]
    chg = ('<section><h2>Changing one slice</h2><p class="desc">Layout 1 before and after one outer slice (the one with dot 8) is wiped and redrawn. '
           'The changed slice is tinted green on the right. Nothing else on the table is touched.</p>'
           '<div class="pair"><figure><img src="%s" alt="Before"><figcaption>Before</figcaption></figure>'
           '<figure><img src="%s" alt="After"><figcaption>After (changed slice in green)</figcaption></figure></div>'
           '<p class="tot">Time for the change: %s (wipe %s + draw %s). The wipe sweeps back and forth in arcs across the slice only (%d mm^2 at 2.5 mm spacing), then the two edge lines and the new faces and pictures are drawn.</p>'
           '<p class="note">The new slice shows the dog and Lek (Lek repeats from the centre here; in real use a newly arrived guest would go there).</p></section>'
           % (ub, ua, fmt(sl.wipe + sl.draw), fmt(sl.wipe), fmt(sl.draw), round(sl.area)))
    page = PAGE.replace('@@SECTIONS@@', secs).replace('@@CHANGE@@', chg)
    out = os.path.join(OUTD, 'oasis-sand-slices.html')
    open(out, 'w').write(page)
    print('wrote', out, len(page) // 1024, 'KB')


PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sand_table_options.py')).read().split("PAGE3 = '''")[1].split("'''")[0]
PAGE = PAGE.replace('five designs with many people (simulation)', 'pie-slice layouts (simulation)')
PAGE = PAGE.split('<h1>')[0] + '''<h1>Five pie-slice layouts for the big table</h1>
<div class="sim"><b>This is a computer simulation, not a photo of the table.</b> Nothing here was drawn in real sand or sent to either table.
Wiping a single slice has not been tried in real sand yet, and the simulation cannot judge how clean the straight slice edges will look.</div>
<p>Each zone (a ring or a slice) is wiped and redrawn as a whole, on its own schedule, while every other zone stays on display. The centre circle
shows one person at a time with the name lettered once under the face. The numbered dots on each picture match the list under it.</p>
<p class="basis">Lines 4 mm wide, wipe lines 2.5 mm apart, ball at 40 mm per second. A slice wipe = slice area / 2.5 mm / 40 mm per second, done as back-and-forth arcs
inside the slice; then the slice's edge lines are redrawn. Faces are about 96 mm across, pictures about 70 mm. Faces: Bill, Lek, Alex and Thomas are the hand-drawn portraits;
the others are public test photos converted the same way, standing in for guests, with placeholder first names. Where there are more face spots than people, a few repeat.
Slices have no name lettering, only the centre does. The interest ring is 140 to 220 mm in layout 1 (70 mm pictures) and 140 to 210 mm in layout 2 (60 mm pictures, to leave the slices more room). "Ball busy" adds up each zone's redo time divided by how often it refreshes.</p>
@@SECTIONS@@
@@CHANGE@@
</main></body></html>
'''
PAGE = PAGE.replace('</style>', '.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; } figure { margin: 0; } figcaption { font-size: .85em; color: #505b50; text-align: center; } .sched { margin: 8px 0 0; color: #334c3c; }\n@media (max-width: 560px) { .pair { grid-template-columns: 1fr; } }\n</style>', 1)

if __name__ == '__main__':
    main()
