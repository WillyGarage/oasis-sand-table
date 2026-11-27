#!/usr/bin/env python3
"""Table artwork + page for the sand.example.com mockups.  SIMULATION ONLY: never contacts a table.

    python3 tools/sand_table_mockup.py

Writes captures/sand-app/assets/*.png, manifest.json, times.json and captures/sand-app/oasis-sand-table.html.
Builds on tools/zone_samples.py (sand renderer, lettering, faces, borders).
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zone_samples as z
import ring_scene as rs
import sandsim

ROOT = z.ROOT
OUTD = os.path.join(ROOT, 'captures', 'sand-app')
ASSETS = os.path.join(OUTD, 'assets')
os.makedirs(ASSETS, exist_ok=True)
z.GROOVE = 4.0     # measured: the 36-inch ball's line is narrower than 4 mm
RT, G, SPEED, PITCH = z.RT, z.GROOVE, z.SPEED, z.PITCH
FACE_R, BAND_R, RING_R = 150.0, 200.0, 285.0
ICON_R = 35.0
BG = z.BG

# ------------------------------------------------------------------ hand-made icons (unit radius ~1, y up)
def P(*pts):
    return np.array(pts, float)


def ell(cx, cy, rx, ry, a0=0, a1=2 * math.pi, n=48):
    return z._ell(cx, cy, rx, ry, a0, a1, n)


def rect(x0, y0, x1, y1):
    return P((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


def tilt(strokes, deg):
    return [z.rot(s, math.radians(deg)) for s in strokes]


def motif1(name):
    return [rs.motif(name)]


def icon_lightsaber():
    hilt = rect(-.17, -.98, .17, -.4)
    guard = P((-.3, -.4), (.3, -.4))
    blade = np.vstack([P((-.15, -.4)), P((-.15, .8)), ell(0, .8, .15, .17, math.pi, 0, 14)[::-1][::-1], P((.15, -.4))])
    return tilt([hilt, guard, blade], -35)


def icon_starfighter():
    return [P((0, .98), (.2, .45), (.95, -.55), (.95, -.88), (.32, -.6), (.2, -.9), (-.2, -.9), (-.32, -.6),
              (-.95, -.88), (-.95, -.55), (-.2, .45), (0, .98))]


def icon_planet():
    ang = math.radians(-22)
    th = np.linspace(0, 2 * math.pi, 120)
    ring = np.column_stack((1.0 * np.cos(th), .3 * np.sin(th)))
    keep = (np.hypot(*ring.T) > .6) | (ring[:, 1] < 0)             # the far side of the ring hides behind the planet
    segs, cur = [], []
    for pt, k in zip(ring, keep):
        if k:
            cur.append(pt)
        elif cur:
            segs.append(np.array(cur)); cur = []
    if cur:
        segs.append(np.array(cur))
    return tilt([ell(0, 0, .5, .5)] + segs, -22) + [P((.72, .78), (.72, .98)), P((.62, .88), (.82, .88))]


def clar(cx=0, cy=0, deg=0, s=1.0):
    body = P((-.04, 1.0), (.04, 1.0), (.12, .78), (.12, -.6), (.34, -.98), (-.34, -.98), (-.12, -.6), (-.12, .78), (-.04, 1.0))
    keys = [ell(.27 if i % 2 == 0 else -.27, y, .09, .09, n=12) for i, y in enumerate((.5, .2, -.1, -.38))]
    return [z.rot(q * s, math.radians(deg)) + [cx, cy] for q in [body] + keys]


def icon_clarinet_diag():
    return clar(deg=-40, s=.97)


def note(x, y, s=1.0):
    return [ell(x, y, .2 * s, .14 * s, n=16), P((x + .2 * s, y), (x + .2 * s, y + .85 * s))]


def icon_clarinet_notes():
    return clar(-.42, -.02, -18, .8) + note(.5, -.45, .85) + note(.72, .12, .85)


def icon_clarinet_upright():
    heads = [ell(-.55, -.5, .27, .19, n=16), ell(.3, -.68, .27, .19, n=16)]
    stems = [P((-.28, -.5), (-.28, .6)), P((.57, -.68), (.57, .45))]
    beams = [P((-.28, .6), (.57, .45)), P((-.28, .3), (.57, .15))]
    return heads + stems + beams


def icon_book_stack():
    return [rect(-.9, -.92, .9, -.52), rect(-.72, -.27, .98, .13), rect(-.85, .38, .8, .78)]


def icon_book_ribbon():
    return [rect(-.55, -.8, .55, .8), rect(-.35, -.55, .35, .55)[:], P((.2, -.8), (.2, -1.0), (.1, -.92), (0, -1.0), (0, -.8))]


def icon_hiking():
    boot = P((-.55, .95), (.05, .95), (.05, .25), (.55, -.05), (.98, -.2), (.98, -.55), (-.7, -.55), (-.7, .0), (-.55, .95))
    sole = P((-.78, -.95), (1.0, -.95))
    return [boot, sole]


def icon_chalkboard():
    board = rect(-.95, -.35, .95, .85)
    lines = [P((-.55, .45), (.1, .45)), P((-.55, 0), (.45, 0))]
    easel = [P((-.55, -.35), (-.8, -.95)), P((.55, -.35), (.8, -.95))]
    return [board] + lines + easel


def icon_hotpot():
    body = np.vstack([P((-.8, .0)), ell(0, 0, .8, .8, math.pi, 2 * math.pi, 30), P((.8, 0), (-.8, 0))])
    handles = [P((-.8, .0), (-1, .1)), P((.8, .0), (1, .1))]
    steam = [np.column_stack((x + .1 * np.sin(np.linspace(0, 2 * math.pi, 14)), np.linspace(.3, .95, 14))) for x in (-.4, 0, .4)]
    return [body] + handles + steam


ICONS = {
    'reading-1': lambda: motif1('books_open'), 'reading-2': icon_book_stack, 'reading-3': icon_book_ribbon,
    'star-wars-1': icon_lightsaber, 'star-wars-2': icon_starfighter, 'star-wars-3': icon_planet,
    'clarinet-playing-1': icon_clarinet_diag, 'clarinet-playing-2': icon_clarinet_notes,
    'clarinet-playing-3': icon_clarinet_upright,
    'thai-temples': lambda: motif1('temple_gable'), 'hot-pot': icon_hotpot, 'guitar': lambda: motif1('guitar_silhouette'),
    'teaching': icon_chalkboard, 'bacteriophages': lambda: motif1('phage_faceted'), 'hiking': icon_hiking,
}


def icon_strokes(key, ang=math.pi / 2, centre=(0, 0), r=ICON_R, rail=None):
    """Icon placed at `centre`, upright for a ring position at angle `ang` (turned with the ring)."""
    out = []
    for s in ICONS[key]():
        out.append(z.rot(np.asarray(s, float) * r, ang - math.pi / 2) + np.array(centre))
    if rail is not None:
        far = max((p for s in out for p in s), key=lambda p: math.hypot(*p))
        rp = rail * np.array([math.cos(ang), math.sin(ang)])
        stem = np.array([rp, far])
        out = [stem] + out + [stem[::-1]]
    return out


# ------------------------------------------------------------------ table pieces
def spot_angle(i):
    return math.radians(90 - 360.0 * i / 9)


SPOT_ORDER = [0, 4, 2, 6, 8, 1, 5, 3, 7]
R_MID = (RING_R + BAND_R) / 2 - .5
RAIL = RING_R - G / 2


def ring_icon_paths(key, spot):
    return icon_strokes(key, spot_angle(spot), R_MID * np.array([math.cos(spot_angle(spot)), math.sin(spot_angle(spot))]), ICON_R, RAIL)


def face_band(person):
    name = person
    paths = [z.face(person, FACE_R), z.frame(FACE_R - G / 2)]
    h = 38.0
    base = FACE_R + 4
    paths += z.name_paths(name, base, h, True, 0.5)
    paths += [z.frame(BAND_R - G / 2)]
    return paths


def border_paths(variant):
    return [z.border(RING_R + 5, RT - 8, variant), z.frame(RT - G / 2)]


class Z:
    def __init__(self, r_out, paths=()):
        self.r_out, self.r_in, self.paths = r_out, 0, list(paths)


def erase_min(r_in, r_out):
    return math.pi * (r_out ** 2 - r_in ** 2) / PITCH / SPEED / 60


def draw_min(paths):
    return sum(z.length(p) for p in paths) / SPEED / 60


LEAVES, WHEAT, LOTUS, WAVES = 4, 0, 3, 1

TURNS = [  # person, [(icon, spot_slot)], clears_ring
    ('Lek', ['thai-temples', 'hot-pot'], False),
    ('Bill', ['reading-1', 'star-wars-1', 'clarinet-playing-1'], False),
    ('Alex', ['guitar', 'teaching'], False),
    ('Thomas', ['bacteriophages', 'hiking'], False),
    ('Lek', ['thai-temples'], True),
]
CAPTIONS = [
    'Turn 1, Lek: a new face and name, and two interests join the ring.',
    'Turn 2, Bill: three interests join. The ring is getting busy.',
    'Turn 3, Alex: two more interests.',
    'Turn 4, Thomas: the ring is now full.',
    "Turn 5, Lek again: the ring is wiped and starts over with one new picture.",
]


def simulate_turns(border=LEAVES):
    b = border_paths(border)
    ring_frame = [z.frame(RING_R - G / 2)]
    state, used, res = [], 0, []
    for i, (person, icons, clear_ring) in enumerate(TURNS):
        clear = erase_min(0, BAND_R)
        fb = face_band(person)
        draw = draw_min(fb)
        if clear_ring:
            clear += erase_min(BAND_R, RING_R)
            state, used = [], 0
            draw += draw_min(ring_frame)
        new = []
        for ic in icons:
            new += ring_icon_paths(ic, SPOT_ORDER[used]); used += 1
        state = state + new
        draw += draw_min(new)
        zs = [Z(RT, fb + ring_frame + state + b)]
        res.append(dict(turn=i + 1, person=person, icons=icons, clear=clear, draw=draw, total=clear + draw,
                        spots_used=used, paths=zs))
    return res


def crop_disc(im_full, size, r_mm, out_px, ring=True):
    R = size / 2 * 0.94
    c = size / 2
    rr = r_mm / RT * R
    im = im_full.crop((int(c - rr * 1.03), int(c - rr * 1.03), int(c + rr * 1.03), int(c + rr * 1.03)))
    s = im.size[0]
    mask = Image.new('L', (s, s), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, s - 1, s - 1), fill=255)
    cv = Image.new('RGB', (s, s), BG)
    cv.paste(im, (0, 0), mask)
    ImageDraw.Draw(cv).ellipse((1, 1, s - 2, s - 2), outline=(92, 81, 67), width=max(3, s // 120))
    return cv.resize((out_px, out_px), Image.LANCZOS)


def render_window(paths, half_mm, out_px):
    """Render paths at true scale and crop a square window of +-half_mm around the table centre."""
    size = int(out_px * RT / (2 * half_mm * 0.47))
    s = sandsim.Sand(size, real=False, groove=G / RT)
    for p in paths:
        s.draw(z.xy_to_thr(z.densify(p, 1.2)))
    im = s.image()
    c = size / 2
    w = half_mm / RT * size * 0.47
    return im.crop((int(c - w), int(c - w), int(c + w), int(c + w))).resize((out_px, out_px), Image.LANCZOS)


def write_assets():
    man = []

    def save(im, name):
        im.save(os.path.join(ASSETS, name)); man.append(name)
    for who in ('Bill', 'Lek', 'Alex', 'Thomas'):
        size = 1400
        s = sandsim.Sand(size, real=False, groove=G / RT)
        for p in face_band(who):
            s.draw(z.xy_to_thr(z.densify(p, 1.2)))
        save(crop_disc(s.image(), size, BAND_R + 6, 700), 'preview-%s.png' % who.lower())
    for key in ICONS:
        im = render_window(icon_strokes(key), 50, 300)
        save(im, 'icon-%s.png' % key)
    res = simulate_turns()
    for r in res:
        im = z.tray_image(r['paths'], tags=False, size=1400, out_px=900)
        save(im, 'table-turn-%d.png' % r['turn'])
    for nm, v in (('leaves', LEAVES), ('wheat', WHEAT), ('lotus', LOTUS), ('waves', WAVES)):
        s = sandsim.Sand(1400, real=False, groove=G / RT)
        for p in border_paths(v):
            s.draw(z.xy_to_thr(z.densify(p, 1.2)))
        im = crop_disc(s.image(), 1400, RT, 600)
        # clear the middle so only the ring shows
        d = ImageDraw.Draw(im)
        rin = RING_R / RT * 300 * 0.97
        d.ellipse((300 - rin, 300 - rin, 300 + rin, 300 + rin), fill=BG)
        save(im.resize((300, 300), Image.LANCZOS), 'border-%s.png' % nm)
    json.dump(sorted(man), open(os.path.join(ASSETS, 'manifest.json'), 'w'), indent=1)
    times = [{k: (round(r[k], 1) if isinstance(r[k], float) else r[k]) for k in ('turn', 'person', 'icons', 'clear', 'draw', 'total', 'spots_used')}
             for r in res]
    for t in times:
        t['clear_minutes'], t['draw_minutes'], t['total_minutes'] = t.pop('clear'), t.pop('draw'), t.pop('total')
    json.dump(times, open(os.path.join(ASSETS, 'times.json'), 'w'), indent=1)
    return res


def uri_of(path, q=80, maxpx=None):
    im = Image.open(path).convert('RGB')
    if maxpx:
        im = im.resize((maxpx, maxpx), Image.LANCZOS)
    return z.jpeg_uri(im, q)[0]


def fmt(m):
    return '%.1f min' % m


def clock(t):
    t = int(round(t))
    h, m = divmod(t, 60)
    h24 = 19 + h
    return '%d:%02d pm' % ((h24 - 12) if h24 > 12 else h24, m)


def build_page(res):
    face_draw = [draw_min(face_band(p)) for p in ('Lek', 'Bill', 'Alex', 'Thomas')]
    face_avg = sum(face_draw) / 4
    face_only = sum(draw_min([z.face(p, FACE_R), z.frame(FACE_R - G / 2)]) for p in ('Lek', 'Bill', 'Alex', 'Thomas')) / 4
    one_icon = draw_min(ring_icon_paths('reading-1', 0))
    zs = [Z(FACE_R, res[3]['paths'][0].paths), Z(BAND_R), Z(RING_R), Z(RT)]
    lay_uri = z.jpeg_uri(z.tray_image(zs, tags=True, size=1400, out_px=900))[0]
    face_clear = erase_min(0, BAND_R)
    bands = [
        ('Face', '0 to 150 mm', 'The guest\'s photo, drawn as a line portrait.', 'Redrawn every turn together with the name.',
         'wipe %s + draw about %s (with the name)' % (fmt(erase_min(0, FACE_R)), fmt(face_only))),
        ('Name band', '150 to 200 mm', 'The guest\'s first name, lettered round the circle (once on each side).',
         'Cleared and redrawn with the face each turn.',
         'face and name together: wipe %s + draw about %s' % (fmt(face_clear), fmt(face_avg))),
        ('Interests ring', '200 to 285 mm', 'Nine spots. Each turn adds that guest\'s pictures (up to 3) into empty spots, with no wiping.',
         'When it is full, the next turn wipes the whole ring and starts filling again.',
         'adding a picture: draw roughly %s each. Wiping a full ring: %s' % (fmt(one_icon), fmt(erase_min(BAND_R, RING_R)))),
        ('Border', '285 to 355 mm', 'A decorative theme chosen by the host. It rarely changes.',
         'Default for the party: autumn leaves.',
         'changing the theme: wipe %s + draw about %s' % (fmt(erase_min(RING_R, RT)), fmt(draw_min(border_paths(LEAVES))))),
    ]
    band_html = ''.join(
        '<li><span class="chip">%d</span><div><b>%s</b> <span class="dim">(%s)</span><br>%s %s<br><span class="t">%s</span></div></li>'
        % (i + 1, n, r, d, d2, t) for i, (n, r, d, d2, t) in enumerate(bands))
    t = 0.0
    turns_html = ''
    for r in res:
        a, b = t, t + r['total']
        t = b
        turns_html += ('<section class="turn"><h3>%s</h3><p class="clock">%s to %s <span class="dim">(%s: wipe %s + draw %s)</span></p>'
                       '<img src="%s" alt="Table after turn %d"></section>'
                       % (CAPTIONS[r['turn'] - 1], clock(a), clock(b), fmt(r['total']), fmt(r['clear']), fmt(r['draw']),
                          uri_of(os.path.join(ASSETS, 'table-turn-%d.png' % r['turn']), 80), r['turn']))
    borders = ''.join('<figure><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>'
                      % (uri_of(os.path.join(ASSETS, 'border-%s.png' % k), 85), n, n)
                      for k, n in (('leaves', 'Autumn leaves (party default)'), ('wheat', 'Wheat'), ('lotus', 'Lotus'), ('waves', 'Waves')))
    ics = ''.join('<figure><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>'
                  % (uri_of(os.path.join(ASSETS, 'icon-%s.png' % k), 85), k, cap)
                  for k, cap in (('reading-1', 'reading 1'), ('reading-2', 'reading 2'), ('reading-3', 'reading 3'),
                                 ('star-wars-1', 'star wars 1'), ('star-wars-2', 'star wars 2'), ('star-wars-3', 'star wars 3'),
                                 ('clarinet-playing-1', 'clarinet 1'), ('clarinet-playing-2', 'clarinet 2'), ('clarinet-playing-3', 'clarinet 3')))
    page = PAGE2.replace('@@LAYOUT@@', lay_uri).replace('@@BANDS@@', band_html).replace('@@TURNS@@', turns_html) \
        .replace('@@BORDERS@@', borders).replace('@@ICONS@@', ics)
    out = os.path.join(OUTD, 'oasis-sand-table.html')
    open(out, 'w').write(page)
    print('wrote', out, len(page) // 1024, 'KB')


PAGE2 = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>The 36-inch table: layout and an evening (simulation)</title>
<style>
:root { color-scheme: light; background: #f5f2e9; color: #242c24; font: 16px/1.5 "DM Sans", system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; }
main { max-width: 760px; margin: auto; padding: 18px 14px 60px; }
h1 { font: normal 2rem/1.1 Georgia, serif; letter-spacing: -.02em; margin: .2em 0 .3em; }
h2 { font: normal 1.5rem/1.2 Georgia, serif; margin: 34px 0 6px; padding-top: 18px; border-top: 1px solid #d6d4c7; }
h3 { font: normal 1.15rem/1.3 Georgia, serif; margin: 0 0 2px; }
.sim { background: #fff7d6; border: 2px solid #c9a227; border-radius: 10px; padding: 10px 12px; margin: 10px 0 16px; }
.sim b { color: #7a5a00; }
img { width: 100%; height: auto; display: block; border-radius: 6px; }
.big { max-width: 700px; margin: 8px auto; }
ol.zones { list-style: none; padding: 0; margin: 12px 0 0; }
ol.zones li { display: flex; gap: 10px; padding: 9px 0; border-bottom: 1px solid #e4e1d4; }
.chip { flex: none; width: 26px; height: 26px; border-radius: 50%; background: #334c3c; color: #fff; text-align: center; font: 700 .9rem/26px system-ui, sans-serif; }
.dim { color: #6b7468; font-size: .9em; }
.t { color: #334c3c; font-weight: 600; }
.turn { margin: 22px 0; max-width: 700px; margin-left: auto; margin-right: auto; }
.clock { margin: 0 0 6px; font-weight: 600; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
figure { margin: 0; } figcaption { text-align: center; font-size: .85em; color: #505b50; margin-top: 3px; }
</style></head><body><main>
<h1>The 36-inch table: the layout and an evening</h1>
<div class="sim"><b>This is a computer simulation, not a photo of the table.</b> Nothing here was drawn in real sand or sent to either table.</div>
<h2>The layout</h2>
<p>Four rings. The numbers on the picture match the list. Times assume the ball moves at 40 mm per second and a smooth wipe with lines 2.5 mm apart.</p>
<img class="big" src="@@LAYOUT@@" alt="Table layout with four numbered rings">
<ol class="zones">@@BANDS@@</ol>
<h2>An evening on the table</h2>
<p>Five turns, starting at 7:00 pm Pacific, each turn starting as soon as the last one ends. Every turn wipes and redraws the face and name; the interests ring only gets wiped when it is full.</p>
@@TURNS@@
<p><b>When nobody is in line,</b> the table replays earlier guests: it redraws their faces and names, one at a time.</p>
<h2>Border themes</h2>
<p>The host picks one. Changing it is a rare, longer job.</p>
<div class="grid">@@BORDERS@@</div>
<h2>Free-text interests</h2>
<p>A guest types any interest and the app offers three drawings to pick from. Examples for one guest (these pictures were drawn by hand for this mockup):</p>
<div class="grid">@@ICONS@@</div>
<p class="dim">Lines are drawn 4 mm wide (the real ball's line is a little narrower, from today's first erase). The small pictures are about 70 mm across, so they stay simple.</p>
</main></body></html>
'''


if __name__ == '__main__':
    r = write_assets()
    build_page(r)
    for x in r:
        print(x['turn'], x['person'], round(x['clear'], 1), round(x['draw'], 1), round(x['total'], 1))
