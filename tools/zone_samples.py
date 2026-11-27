#!/usr/bin/env python3
"""Simulation-only layout samples for the 36-inch table (never talks to a table).

Builds simulated-sand pictures of the table split into concentric zones, plus the per-zone times, then a
self-contained phone page.  Outputs go to captures/zone-samples/.

    python3 tools/zone_samples.py            # renders samples + builds captures/zone-samples/oasis-sand-zones.html

Reuses: sandsim (sand look), ring_scene.motif / border_band (icons, borders), patterns/people/*.thr (faces),
web/guest-lettering.js capitals (names, dumped through node).  Everything is a path in millimetres (x right,
y up, centre 0,0); render converts to the theta/rho the simulator wants.
"""
import base64, io, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sandsim
import thrcommon as tc
import ring_scene as rs

OUT = os.path.join(ROOT, 'captures', 'zone-samples')
RT = 355.0            # working radius of the table, mm
GROOVE = 7.0          # mm; the rehearsal value used for the wide table (not yet measured on the real one)
SPEED = 40.0          # ball mm/s
PITCH = 2.5           # smooth erase spacing, mm
SIZE = 1400           # render px (sandsim draws the tray at 0.94 of this)
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------- path helpers (xy in mm)
def length(p):
    p = np.asarray(p, float)
    return float(np.hypot(*np.diff(p, axis=0).T).sum()) if len(p) > 1 else 0.0


def densify(p, step=1.5):
    p = np.asarray(p, float)
    out = [p[0]]
    for a, b in zip(p[:-1], p[1:]):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        out.extend(a + (b - a) * (k / n) for k in range(1, n + 1))
    return np.array(out)


def circle(r, a0=-math.pi / 2, turns=1.0, step=1.5):
    n = max(8, int(2 * math.pi * r * turns / step))
    a = a0 + np.linspace(0, 2 * math.pi * turns, n + 1)
    return np.column_stack((r * np.cos(a), r * np.sin(a)))


def arc(r, a0, a1, step=1.5):
    n = max(2, int(abs(a1 - a0) * r / step))
    a = np.linspace(a0, a1, n + 1)
    return np.column_stack((r * np.cos(a), r * np.sin(a)))


def rot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return np.asarray(p, float) @ np.array([[c, -s], [s, c]]).T


def thr_to_xy(thr, scale_mm):
    thr = np.asarray(thr, float)
    return np.column_stack((thr[:, 1] * np.cos(thr[:, 0]), thr[:, 1] * np.sin(thr[:, 0]))) * scale_mm


def xy_to_thr(p):
    p = np.asarray(p, float)
    th = np.unwrap(np.arctan2(p[:, 1], p[:, 0]))
    return np.column_stack((th, np.hypot(*p.T) / RT))


# ---------------------------------------------------------------- content builders
def face(name, r_zone, margin=9.0):
    """Portrait from patterns/people/NAME.thr (a whole-tray drawing) shrunk into a disc of radius r_zone."""
    thr = tc.read_thr(os.path.join(ROOT, 'patterns', 'people', name.lower() + '.thr'))
    return thr_to_xy(thr, r_zone - margin)


def frame(r):
    """The clean groove that separates zones."""
    return circle(r)


def hang(outline_unit, ang, r_mid, r_icon, r_rail):
    """An icon hung from the rail circle (radius r_rail): rail point -> stem -> closed outline -> back."""
    o = np.asarray(outline_unit, float)
    pts = o[:-1] if np.allclose(o[0], o[-1]) else o
    c = r_mid * np.array([math.cos(ang), math.sin(ang)])
    xy = rot(pts, ang - math.pi / 2) * r_icon + c          # unit art is drawn upright when its centre is at 12 o'clock
    # begin at the icon point nearest the rail so the stem is short
    k = int(np.argmax(np.hypot(*xy.T)))
    xy = np.vstack([xy[k:], xy[:k + 1]])
    rail = r_rail * np.array([math.cos(ang), math.sin(ang)])
    return np.vstack([rail, xy, rail])


def icon_ring(names, r_in, r_out, phase=math.pi / 2, rail='outer'):
    """Icons spread round a ring; they hang from the ring's outer frame line. Returns (paths, outer_icon_radius)."""
    width = r_out - r_in
    margin = GROOVE * 1.2
    r_icon = min((width - 2 * margin) / 2 * 0.98, 0.5 * (2 * math.pi * (r_in + r_out) / 2 / len(names)) * 0.8)
    r_mid = r_out - margin - r_icon - 3
    rail_r = r_out - GROOVE / 2
    paths = []
    n = len(names)
    for i, nm in enumerate(names):
        ang = phase - 2 * math.pi * i / n
        paths.append(hang(rs.motif(nm), ang, r_mid, r_icon, rail_r))
    return paths, r_icon


_CAPS = None


def caps():
    global _CAPS
    f = os.path.join(OUT, 'caps.json')
    if not os.path.exists(f):
        js = ("const fs=require('fs');let s=fs.readFileSync(%r,'utf8');"
              "s=s.replace('return {design,inHeart,rimName};','return {design,inHeart,rimName,glyph};');"
              "global.window={};eval(s);const G=window.GuestLettering,o={};"
              "for(const c of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'){const g=G.glyph(c,true);o[c]={advance:g.advance,points:g.points};}"
              "fs.writeFileSync(%r,JSON.stringify(o));") % (os.path.join(ROOT, 'web', 'guest-lettering.js'), f)
        subprocess.run(['node', '-e', js], check=True)
    if _CAPS is None:
        _CAPS = json.load(open(f))
    return _CAPS


def arc_name(text, r_base, height, center_ang, flip=False, spacing=0.38):
    """Capital letters (the table's own single-stroke lettering) along a circle. Upright on top (flip=False);
    flip=True reads right way up for someone on the opposite side. Each letter retraces its own stroke."""
    C = caps()
    text = text.upper()
    adv = [C[c]['advance'] for c in text]
    total = (sum(adv) + spacing * (len(text) - 1)) * height
    r_mid = r_base + height / 2
    paths, x = [], -total / 2
    for c, a in zip(text, adv):
        pts = np.asarray(C[c]['points'], float)
        s = (x + a * height / 2) / r_mid            # arc angle of letter centre
        ang = center_ang - s if not flip else center_ang + s
        # letter local frame: u along reading direction, v radial (outward)
        u = (pts[:, 0] - a / 2) * height
        v = (pts[:, 1] - 0.5) * height + (0 if True else 0)
        nx, ny = math.cos(ang), math.sin(ang)       # outward normal at the letter
        if not flip:
            tx, ty = ny, -nx                        # clockwise along the top = reading direction
            r = r_mid + v
        else:
            tx, ty = -ny, nx
            r = r_mid - v                           # upside down relative to the table, upright for the far side
        xy = np.column_stack((r * 0 + nx * (r_mid + (v if not flip else -v)) + tx * u,
                              ny * (r_mid + (v if not flip else -v)) + ty * u))
        path = np.vstack([xy, xy[-2:0:-1]]) if len(xy) > 2 else xy
        paths.append(path)
        x += (a + spacing) * height
    return paths


def link(paths):
    """Chain separate strokes into one path; jumps are crossed by the ball so they are drawn too (honest)."""
    out = [np.asarray(paths[0], float)]
    for p in paths[1:]:
        out.append(np.asarray(p, float))
    return out


def border(r_in, r_out, variant):
    """Decorative border ring from ring_scene.border_band (theta/rho in table fractions)."""
    low, high = r_in / RT, r_out / RT
    thr = rs.border_band(low, high, variant)
    return thr_to_xy(thr, RT)


# ---------------------------------------------------------------- rendering
def render(paths, size=SIZE):
    s = sandsim.Sand(size, real=False, groove=GROOVE / RT)
    for p in paths:
        p = densify(p, 1.2)
        s.draw(xy_to_thr(p))
    return s.image()


# ---------------------------------------------------------------- small faces (about 90 mm across)
def _ell(cx, cy, rx, ry, a0=0.0, a1=2 * math.pi, n=60):
    a = np.linspace(a0, a1, n)
    return np.column_stack((cx + rx * np.cos(a), cy + ry * np.sin(a)))


def mini_face(who, r):
    """A head drawn with a few strokes that still read at 7 mm grooves. A full portrait cannot survive at this size
    (tested: the whole-tray portraits turn to mush at 46 mm radius), so each face keeps only its head and its traits."""
    k = r / 40.0
    S = []
    head = _ell(0, 0, 27 * k, 33 * k)
    if who == 'bill':
        S += [head, _ell(0, 36 * k, 25 * k, 9 * k, 0.15, math.pi - 0.15, 30)]            # hair
        S += [_ell(-11 * k, 6 * k, 8 * k, 6 * k), _ell(11 * k, 6 * k, 8 * k, 6 * k)]       # glasses
        S += [np.array([[-3 * k, 6 * k], [3 * k, 6 * k]])]
        S += [_ell(0, -9 * k, 12 * k, 8 * k, math.pi * 1.1, math.pi * 1.9, 20)]           # smile
    elif who == 'lek':
        S += [head, _ell(0, 36 * k, 25 * k, 9 * k, 0.15, math.pi - 0.15, 30)]
        S += [np.array([[26 * k, 12 * k], [32 * k, -10 * k], [30 * k, -34 * k], [34 * k, -34 * k]])]  # long braid
        S += [_ell(-10 * k, 6 * k, 0.8 * k, 0.8 * k, n=8), _ell(10 * k, 6 * k, 0.8 * k, 0.8 * k, n=8)]
        S += [_ell(0, -6 * k, 13 * k, 9 * k, math.pi * 1.05, math.pi * 1.95, 20)]
    elif who == 'alex':
        S += [_ell(0, 4 * k, 27 * k, 32 * k, math.pi * 1.0, 2 * math.pi, 40)]
        S += [_ell(0, 4 * k, 31 * k, 32 * k, math.pi * 1.0, 2 * math.pi, 40)]           # beard outline
        S += [_ell(0, 10 * k, 26 * k, 28 * k, 0.1, math.pi - 0.1, 30)]
        S += [_ell(-10 * k, 8 * k, 0.8 * k, 0.8 * k, n=8), _ell(10 * k, 8 * k, 0.8 * k, 0.8 * k, n=8)]
        S += [_ell(0, -8 * k, 10 * k, 7 * k, math.pi * 1.1, math.pi * 1.9, 20)]
    elif who == 'thomas':
        S += [head, _ell(0, 34 * k, 26 * k, 12 * k, 0.1, math.pi - 0.1, 30)]
        S += [_ell(-10 * k, 7 * k, 0.8 * k, 0.8 * k, n=8), _ell(10 * k, 7 * k, 0.8 * k, 0.8 * k, n=8)]
        S += [np.array([[-10 * k, -4 * k], [10 * k, -4 * k]])]                          # moustache
        S += [_ell(0, -12 * k, 9 * k, 6 * k, math.pi * 1.1, math.pi * 1.9, 20)]
    else:    # a fourth guest: swept-up hair
        S += [head, np.array([[-20 * k, 28 * k], [-8 * k, 38 * k], [8 * k, 34 * k], [20 * k, 42 * k]])]
        S += [_ell(-10 * k, 6 * k, 0.8 * k, 0.8 * k, n=8), _ell(10 * k, 6 * k, 0.8 * k, 0.8 * k, n=8)]
        S += [_ell(0, -6 * k, 12 * k, 9 * k, math.pi * 1.1, math.pi * 1.9, 20)]
    return S


def place_small_faces(whos, r_in, r_out, phase=math.pi / 2):
    r_mid = (r_in + r_out) / 2
    rf = (r_out - r_in) / 2 - GROOVE * 1.3
    out = []
    for i, w in enumerate(whos):
        ang = phase - 2 * math.pi * i / len(whos)
        c = r_mid * np.array([math.cos(ang), math.sin(ang)])
        for s in mini_face(w, rf):
            out.append(rot(s, ang - math.pi / 2) + c)      # upright toward the centre (heads point outward)
    return out


# ---------------------------------------------------------------- zones, samples, times
class Zone:
    def __init__(self, label, r_in, r_out, what, paths, frame_r=None):
        self.label, self.r_in, self.r_out, self.what = label, r_in, r_out, what
        fr = r_out - GROOVE / 2 if frame_r is None else frame_r
        self.paths = [np.asarray(p, float) for p in paths] + [frame(fr)]

    @property
    def draw_mm(self):
        return sum(length(p) for p in self.paths)

    @property
    def erase_s(self):
        return math.pi * (self.r_out ** 2 - self.r_in ** 2) / PITCH / SPEED

    @property
    def draw_s(self):
        return self.draw_mm / SPEED


def name_paths(name, r_base, height, both=True, spacing=0.38):
    top = arc_name(name, r_base, height, math.pi / 2, spacing=spacing)
    ps = list(top)
    if both:
        ps += [rot(p, math.pi) for p in top]
    return ps


def ring_icons(names, angles_deg, r_in, r_out):
    """Icons hung from the ring's outer frame groove, sized to the room between the two frame grooves."""
    lo, hi = r_in + 2.0, r_out - GROOVE
    r_icon = (hi - lo) / 2 * 0.97
    r_mid = (hi + lo) / 2
    return [hang(rs.motif(n), math.radians(a), r_mid, r_icon, r_out - GROOVE / 2) for n, a in zip(names, angles_deg)], r_icon


def even(n, start=90.0):
    return [start - 360.0 * i / n for i in range(n)]


def lettering(name, r_in, r_out, both, height=None, spacing=0.38):
    """The name between two frame grooves (upright on top; a second copy turned round for the far side)."""
    h = height or (r_out - r_in) - 2 * GROOVE * 0.55
    base = (r_in + r_out) / 2 - h / 2
    return name_paths(name, base, h, both, spacing)


zone = Zone


def sample_A():
    pic = zone('Portrait', 0, 230, 'Alex, from a photo', [face('Alex', 230)])
    r_in, r_out = 230, RT
    ic, ri = ring_icons(['guitar_silhouette', 'books_open', 'guitar_silhouette', 'books_open'], [20, -50, -130, 160], r_in, r_out)
    nm = lettering('Alex', r_in + 40, r_out - 10, False, 46)
    return [pic, zone('Name and interests', r_in, r_out, 'Name along the top, four interest pictures', nm + ic)]


def sample_B():
    pic = zone('Portrait', 0, 150, 'Lek, from a photo', [face('Lek', 150)])
    ic, ri = ring_icons(['temple_gable', 'hotpot', 'lotus_blossom', 'temple_gable', 'hotpot', 'lotus_blossom'], even(6), 150, 255)
    mid = zone('Interests', 150, 255, 'Six interest pictures (Thai temple, hot pot, lotus)', ic)
    out = zone('Border', 255, RT, 'Decorative wheat garland', [border(258, 343, 0)])
    return [pic, mid, out]


def sample_C(person='Thomas', keep=None):
    pic = zone('Portrait', 0, 150, person + ', from photo', [face(person, 150)])
    band = zone('Name band', 150, 185, person + ' lettered round the circle, twice', lettering(person, 150, 185, True, 25, 0.62))
    if keep:
        return pic, band, keep
    ic, ri = ring_icons(['phage_faceted', 'dna_open', 'phage_faceted', 'dna_open'], even(4), 185, 275)
    ints = zone('Interests', 185, 275, 'Four interest pictures (phage and DNA)', ic)
    bor = zone('Border', 275, RT, 'Decorative lotus-bud border', [border(278, 343, 3)])
    return pic, band, ints, bor


def sample_D():
    pic = zone('Featured portrait', 0, 150, 'Thomas, from a photo', [face('Thomas', 150)])
    fac = zone('Earlier guests', 150, 255, 'Four small faces (Bill, Lek, Alex, a fourth guest)',
               place_small_faces(['bill', 'lek', 'alex', 'guest'], 150, 255))
    ic, ri = ring_icons(['phage_faceted', 'dna_open'] * 3, even(6, 90), 255, RT)
    out = zone('Featured interests', 255, RT, 'Six pictures of what Thomas likes (phage, DNA)', ic)
    return [pic, fac, out]


# ---------------------------------------------------------------- pictures
BG = (245, 242, 233)


def tray_image(paths_zones, tags=True, size=SIZE, out_px=1400):
    paths = [p for z in paths_zones for p in z.paths]
    im = render(paths, size)
    R = size / 2 * 0.94
    ring = R * 1.035
    c = size / 2
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((c - ring, c - ring, c + ring, c + ring), fill=255)
    canvas = Image.new('RGB', (size, size), BG)
    canvas.paste(im, (0, 0), mask)
    d = ImageDraw.Draw(canvas)
    d.ellipse((c - ring, c - ring, c + ring, c + ring), outline=(92, 81, 67), width=max(4, size // 180))
    if tags:
        f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', size // 38)
        for i, z in enumerate(paths_zones):
            rm = z.r_out - GROOVE / 2
            a = math.radians(-42)
            x, y = c + rm / RT * R * math.cos(a), c - rm / RT * R * math.sin(a)
            rr = size // 52
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(51, 76, 60), outline=(255, 255, 255), width=3)
            d.text((x, y), str(i + 1), fill='white', font=f, anchor='mm')
    return canvas.resize((out_px, out_px), Image.LANCZOS) if out_px != size else canvas


def jpeg_uri(im, q=80):
    b = io.BytesIO()
    im.convert('RGB').save(b, 'JPEG', quality=q, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode(), len(b.getvalue())


# ---------------------------------------------------------------- the page
def mins(s):
    return '%.1f min' % (s / 60.0)


def inches(mm):
    return '%.1f in' % (mm / 25.4)


def tint(im, zones, color=(80, 160, 110), alpha=70, size=SIZE):
    """Light green wash over the zones that changed (used for the 'next person' picture)."""
    R = size / 2 * 0.94
    sc = im.size[0] / size
    c = size / 2 * sc
    mask = Image.new('L', im.size, 0)
    md = ImageDraw.Draw(mask)
    for z in zones:
        ro, ri = z.r_out / RT * R * sc, z.r_in / RT * R * sc
        md.ellipse((c - ro, c - ro, c + ro, c + ro), fill=alpha)
        md.ellipse((c - ri, c - ri, c + ri, c + ri), fill=0)
    wash = Image.new('RGB', im.size, color)
    return Image.composite(wash, im.convert('RGB'), mask)


def build_samples():
    A = sample_A()
    B = sample_B()
    Cz = list(sample_C('Thomas'))
    pic_l, band_l, _ = sample_C('Lek', keep=True)
    Ez = [pic_l, band_l, Cz[2], Cz[3]]
    D = sample_D()
    return A, B, Cz, Ez, D


def main():
    A, B, Cz, Ez, D = build_samples()
    whole_s = math.pi * RT ** 2 / PITCH / SPEED
    meta = [
        ('A', 'Spotlight: 2 zones', A,
         'A big portrait in the middle. The name and four interest pictures share the outer ring.',
         'The face reads clearly at this size. The name is large and easy to read. The four small pictures look a bit lost in such a wide ring.'),
        ('B', 'Classic: 3 zones', B,
         'Portrait in the middle, a ring of interest pictures, and a decorative border around the edge.',
         'The face is still recognizable. The pictures are simple but readable (temple, hot pot, lotus). The border frames everything neatly. No name in this layout.'),
        ('C', 'Four bands', Cz,
         'Portrait, a thin name ring, an interests ring, and a decorative border.',
         'The name ring is the weak spot: 35 mm is only about 3.5 line-widths tall, so the letters are cramped. Everything else reads fine. The most to look at, and the busiest.'),
        ('D', 'Family ring: 3 zones', D,
         'The featured person in the middle, small faces of earlier guests in a ring, and the featured person\'s interests outside.',
         'The small faces do NOT work at this size: with 7 mm lines you only get an oval with dots, not a likeness of Bill, Lek or Alex. They would need a bigger ring, fewer faces, or a different idea (initials, names).'),
    ]
    html_sections = []
    for key, title, zs, desc, note in meta:
        im = tray_image(zs, out_px=1400)
        uri, n = jpeg_uri(im)
        print(key, 'jpeg KB', n // 1024)
        html_sections.append(section(key, title, desc, uri, zs, note))
    # E: C beside E
    ic = tray_image(Cz, out_px=1000, tags=False)
    ie = tint(tray_image(Ez, out_px=1000, tags=False), Ez[:2], size=1000)
    u1, n1 = jpeg_uri(ic)
    u2, n2 = jpeg_uri(ie)
    print('E jpeg KB', (n1 + n2) // 1024)
    chg = Ez[0].erase_s + Ez[1].erase_s, Ez[0].draw_s + Ez[1].draw_s
    html_sections.append(section_e(u1, u2, Cz, Ez, chg))
    page = PAGE.replace('@@WHOLE@@', mins(whole_s)).replace('@@SECTIONS@@', '\n'.join(html_sections))
    out = os.path.join(OUT, 'oasis-sand-zones.html')
    open(out, 'w').write(page)
    print('wrote', out, len(page) // 1024, 'KB')
    json.dump({k: [dict(zone=z.label, r_in=z.r_in, r_out=z.r_out, erase_min=round(z.erase_s / 60, 1),
                        draw_min=round(z.draw_s / 60, 1)) for z in zs] for k, _, zs, _, _ in meta},
              open(os.path.join(OUT, 'times.json'), 'w'), indent=1)


def zone_rows(zs):
    rows = []
    for i, z in enumerate(zs):
        span = ('middle to %d mm' % z.r_out) if z.r_in == 0 else ('%d to %d mm' % (z.r_in, z.r_out))
        rows.append(
            '<li><span class="chip">%d</span><div><b>%s</b> <span class="dim">(%s, %s out)</span><br>%s<br>'
            '<span class="t">To change this zone: erase <b>%s</b> + draw <b>%s</b></span></div></li>'
            % (i + 1, z.label, span, inches(z.r_out), z.what, mins(z.erase_s), mins(z.draw_s)))
    return '\n'.join(rows)


def section(key, title, desc, uri, zs, note):
    te = sum(z.erase_s for z in zs)
    td = sum(z.draw_s for z in zs)
    return ('<section id="%s"><h2><span class="k">%s</span> %s</h2><p class="desc">%s</p>'
            '<div class="bowl"><img src="%s" alt="Simulated sand, layout %s"></div>'
            '<ol class="zones">%s</ol><p class="tot">Redrawing every zone: erase %s + draw %s.</p>'
            '<p class="note"><b>How it looks:</b> %s</p></section>'
            % (key, key, title, desc, uri, key, zone_rows(zs), mins(te), mins(td), note))


def section_e(u1, u2, Cz, Ez, chg):
    return ('<section id="E"><h2><span class="k">E</span> Next person on the four bands</h2>'
            '<p class="desc">Left: Thomas (layout C). Right: the next guest, Lek. Only the green rings change; '
            'the interests ring and the border stay on display.</p>'
            '<div class="pair"><figure><img src="%s" alt="Before: Thomas"><figcaption>Before: Thomas</figcaption></figure>'
            '<figure><img src="%s" alt="After: Lek"><figcaption>After: Lek (green = redrawn)</figcaption></figure></div>'
            '<ol class="zones">%s</ol>'
            '<p class="tot">Changing the person = zones 1 and 2 only: erase <b>%s</b> + draw <b>%s</b>. '
            'Zones 3 and 4 are not touched.</p>'
            '<p class="note"><b>How it looks:</b> This is the point of the four-band idea: the person changes in about %s '
            'and the rest of the table keeps looking finished. Lek\'s interests would only appear when her own turn '
            'comes round to the interests ring. Zones 1 and 2 above are the ones that were redrawn.</p></section>'
            % (u1, u2, zone_rows(Ez[:2]), mins(chg[0]), mins(chg[1]), mins(chg[0] + chg[1])))


PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>36-inch table: how many zones? (simulation)</title>
<style>
:root { color-scheme: light; background: #f5f2e9; color: #242c24; font: 16px/1.5 "DM Sans", system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; }
main { max-width: 760px; margin: auto; padding: 18px 14px 60px; }
h1 { font: normal 2rem/1.1 Georgia, serif; letter-spacing: -.02em; margin: .2em 0 .3em; }
h2 { font: normal 1.45rem/1.2 Georgia, serif; margin: 0 0 .2em; }
.k { display: inline-block; background: #334c3c; color: #fff; border-radius: 6px; padding: 0 .45em; margin-right: .25em; font: 700 1rem/1.5 system-ui, sans-serif; }
.sim { background: #fff7d6; border: 2px solid #c9a227; border-radius: 10px; padding: 10px 12px; margin: 10px 0 16px; }
.sim b { color: #7a5a00; }
section { margin: 34px 0 0; padding-top: 22px; border-top: 1px solid #d6d4c7; }
.desc { margin: 0 0 10px; color: #3a463a; }
.bowl img, .pair img { width: 100%; max-width: 700px; display: block; margin: 0 auto; height: auto; border-radius: 6px; }
.pair { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
.pair figure { margin: 0; flex: 1 1 300px; max-width: 480px; }
.pair figcaption { text-align: center; font-size: .9em; color: #505b50; margin-top: 4px; }
ol.zones { list-style: none; padding: 0; margin: 12px 0 0; }
ol.zones li { display: flex; gap: 10px; padding: 9px 0; border-bottom: 1px solid #e4e1d4; }
.chip { flex: none; width: 26px; height: 26px; border-radius: 50%; background: #334c3c; color: #fff; text-align: center; font: 700 .9rem/26px system-ui, sans-serif; }
.dim { color: #6b7468; font-size: .9em; }
.t { color: #334c3c; }
.tot { margin: 10px 0 4px; font-weight: 600; }
.note { background: #fffdf7; border: 1px solid #d6d4c7; border-radius: 8px; padding: 8px 10px; margin: 8px 0 0; font-size: .95em; }
.basis { font-size: .9em; color: #505b50; border-top: 1px solid #d6d4c7; margin-top: 40px; padding-top: 12px; }
</style></head><body><main>
<h1>How many zones for the public table?</h1>
<div class="sim"><b>This is a computer simulation, not a photo of the table.</b> Nothing here was drawn in real sand or sent to either table.
The pictures show roughly what the 36-inch table would look like.</div>
<p>Each person's turn is their face (from a photo), their name, and pictures of what they like. A <b>zone</b> is a ring of the table
that can be wiped and redrawn by itself while the other rings stay on display. More zones means smaller changes and a shorter wait,
but each zone gets less room. Pick the layout you like and I will build it. The numbered dots on each picture match the numbered list under it.</p>
<p><b>Whole-table wipe: @@WHOLE@@</b> (about 355 mm, 14 inches, from the middle out).</p>
@@SECTIONS@@
<p class="basis"><b>How the times are worked out.</b> The ball moves at 40 mm per second. Wiping uses lines 2.5 mm apart for a smooth bed, so
wipe time = ring area / 2.5 mm / 40 mm per second. Draw time = length of the lines in that ring / 40 mm per second, including the thin
line that separates it from its neighbour. Travel between pictures is not counted. The ball's line is assumed 7 mm wide;
the big table's real width has not been measured yet, so details could look better or worse. Radii are from the middle of the table (usable edge 355 mm).</p>
</main></body></html>
'''


if __name__ == '__main__':
    main()
