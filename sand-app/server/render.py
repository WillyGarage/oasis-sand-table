"""Icon SVGs and face stand-in previews."""
import io
import math
import textwrap
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

SAND = '#e8dcb8'
DARK = '#8f7a45'
LIGHT = '#f7efd6'
INK = '#6b5a2e'


def _smooth_path(pts):
    """Catmull-Rom through the points as cubic beziers. pts are (x, y) in pixels."""
    if len(pts) == 1:
        x, y = pts[0]
        return 'M%.2f %.2f l0.01 0' % (x, y)
    d = ['M%.2f %.2f' % pts[0]]
    if len(pts) == 2:
        d.append('L%.2f %.2f' % pts[1])
        return ' '.join(d)
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else pts[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        d.append('C%.2f %.2f %.2f %.2f %.2f %.2f' % (c1 + c2 + p2))
    return ' '.join(d)


def icon_svg_ready(strokes):
    paths = []
    for s in strokes:
        pts = [(x * 200.0, y * 200.0) for x, y in s]
        if pts:
            paths.append(_smooth_path(pts))
    d = ' '.join(paths)
    common = 'fill="none" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"'
    body = ('<g clip-path="url(#c)">'
            '<path transform="translate(1.5 1.5)" d="%s" stroke="%s" %s/>'
            '<path d="%s" stroke="%s" %s/></g>') % (d, LIGHT, common, d, DARK, common)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
            '<defs><clipPath id="c"><circle cx="100" cy="100" r="96"/></clipPath></defs>'
            '<circle cx="100" cy="100" r="96" fill="%s"/>%s</svg>') % (SAND, body)


def _wrap_label(label):
    lines = textwrap.wrap(label, width=14, break_long_words=True) or [label]
    if len(lines) > 3:
        lines = lines[:3]
        lines[2] = lines[2][:13] + '…'
    return lines


def icon_svg_pending(label, variant=0):
    rings = ['<circle cx="100" cy="100" r="70" fill="none" stroke="#b9a86b" stroke-width="3"/>',
             '<path d="M30 100 Q65 60 100 100 T170 100" fill="none" stroke="#b9a86b" stroke-width="3"/>',
             '<path d="M100 30 L170 100 L100 170 L30 100 Z" fill="none" stroke="#b9a86b" stroke-width="3"/>'][variant % 3]
    lines = _wrap_label(label)
    size = 17 if len(lines) < 3 else 15
    lh = size + 3
    y0 = 100 - (len(lines) - 1) * lh / 2.0 + size * 0.35
    tspans = ''.join('<tspan x="100" y="%.1f">%s</tspan>' % (y0 + i * lh, escape(ln)) for i, ln in enumerate(lines))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
            '<circle cx="100" cy="100" r="96" fill="%s"/>%s'
            '<text text-anchor="middle" font-family="Georgia,serif" font-size="%d" fill="%s">%s</text></svg>'
            ) % (SAND, rings, size, INK, tspans)


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def face_standin(jpeg_bytes, size=400):
    """Pencil-sketch look in sand tones, circular, as JPEG bytes (Pillow only)."""
    im = Image.open(io.BytesIO(jpeg_bytes))
    im = ImageOps.exif_transpose(im).convert('RGB')
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((size, size), Image.LANCZOS)
    gray = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=1)
    blur = ImageChops.invert(gray).filter(ImageFilter.GaussianBlur(size / 40.0))
    # colour dodge: min(255, gray * 255 / (255 - blur))
    dodged = Image.new('L', gray.size)
    dodged.putdata([255 if b >= 255 else min(255, a * 255 // (255 - b))
                    for a, b in zip(gray.getdata(), blur.getdata())])
    sketch = ImageOps.colorize(ImageOps.autocontrast(dodged, cutoff=1), black=INK, white='#efe5c6')
    bg = Image.new('RGB', (size, size), _hex(SAND))
    mask = Image.new('L', (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    bg.paste(sketch, (0, 0), mask)
    out = io.BytesIO()
    bg.save(out, 'JPEG', quality=88)
    return out.getvalue()


# ---------- sand relief (the look of the approved mockup icons) ----------
# Same groove model as tools/sandsim.py (MOCK profile): a dark rounded floor with a raised lip each side, lit softly
# from the upper left. Pictures are made from stroke geometry only, so overlapping grooves take the later stroke.

SAND_RGB = np.array([240.0, 235.0, 222.0])
PAGE_RGB = (0xf5, 0xf2, 0xe9)
LINE_FRAC = 0.045          # groove width as a fraction of the picture width (approved assets: 0.04 at 70% fill)
_U_MAX = 2.3               # profile reaches this many groove half-widths from the centre line
_LUT_N = 512


def _profile_luts(floor=0.72, floor_k=4, ridge=0.42, ridge_at=1.5, ridge_w=0.42):
    u = np.linspace(0, _U_MAX, _LUT_N)
    prof = -np.exp(-(u / floor) ** floor_k) + ridge * np.exp(-((u - ridge_at) / ridge_w) ** 2)
    mask = np.where(u < 1.7, 1.0, 0.5 * (1 + np.cos(np.pi * np.clip((u - 1.7) / (_U_MAX - 1.7), 0, 1))))
    mask[-1] = 0.0
    return prof.astype(np.float32), mask.astype(np.float32)


_PROF, _MASK = _profile_luts()


def _resample(pts, min_gap):
    """Drop points closer than min_gap to the last kept one (keeps the last point). pts: list of (x, y) px."""
    out = [pts[0]]
    for p in pts[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_gap:
            out.append(p)
    if len(pts) > 1:
        out.append(pts[-1])
    return out


def _height_map(strokes, size, hw):
    """Height of the sand, float32 size x size. Later strokes replace earlier ones where they overlap."""
    h = np.zeros((size, size), np.float32)
    reach = _U_MAX * hw
    k = (_LUT_N - 1) / _U_MAX / hw
    big = np.float32(1e9)
    for stroke in strokes:
        pts = [(float(x) * size, float(y) * size) for x, y in stroke]
        if not pts:
            continue
        pts = _resample(pts, hw * 0.3)
        xs_all = [p[0] for p in pts]
        ys_all = [p[1] for p in pts]
        bx0, bx1 = max(0, int(min(xs_all) - reach) - 1), min(size, int(max(xs_all) + reach) + 2)
        by0, by1 = max(0, int(min(ys_all) - reach) - 1), min(size, int(max(ys_all) + reach) + 2)
        if bx1 <= bx0 or by1 <= by0:
            continue
        dmin = np.full((by1 - by0, bx1 - bx0), big, np.float32)
        segs = list(zip(pts[:-1], pts[1:])) if len(pts) > 1 else [(pts[0], pts[0])]
        for (ax, ay), (bx, by) in segs:
            x0, x1 = max(bx0, int(min(ax, bx) - reach) - 1), min(bx1, int(max(ax, bx) + reach) + 2)
            y0, y1 = max(by0, int(min(ay, by) - reach) - 1), min(by1, int(max(ay, by) + reach) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            gx = np.arange(x0, x1, dtype=np.float32)[None, :]
            gy = np.arange(y0, y1, dtype=np.float32)[:, None]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            if l2 > 1e-9:
                t = np.clip(((gx - ax) * dx + (gy - ay) * dy) / l2, 0.0, 1.0)
                d = np.hypot(gx - (ax + t * dx), gy - (ay + t * dy))
            else:
                d = np.hypot(gx - ax, gy - ay)
            sub = dmin[y0 - by0:y1 - by0, x0 - bx0:x1 - bx0]
            np.minimum(sub, d, out=sub)
        idx = np.minimum(dmin * k, _LUT_N - 1).astype(np.int32)
        m = _MASK[idx]
        hs = h[by0:by1, bx0:bx1]
        hs += m * (_PROF[idx] - hs)
    return h


def _blur(a, sigma):
    r = max(1, int(math.ceil(sigma * 2.5)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    ker = np.exp(-x * x / (2 * sigma * sigma))
    ker /= ker.sum()
    for axis in (0, 1):
        p = np.pad(a, [(r, r) if i == axis else (0, 0) for i in range(2)], mode='edge')
        n = a.shape[axis]
        a = sum(w * np.take(p, np.arange(i, i + n), axis=axis) for i, w in enumerate(ker))
    return a


def relief_image(strokes, size=240, disc=True, line_frac=None, bg=None):
    """Strokes (0..1 polylines, y down) carved into smooth sand, lit from the upper left. Returns a PIL image:
    RGBA with a transparent outside when disc and bg is None, otherwise RGB (outside the disc is `bg`, default
    #f5f2e9; without a disc the whole square is sand)."""
    size = int(size)
    hw = (line_frac or LINE_FRAC) * size / 2.0
    h = _height_map(strokes, size, hw)
    hs = _blur(h, max(0.5, 0.7 * size / 300.0))
    gy, gx = np.gradient(hs)
    light = (gx + gy) * (hw * 1.1)
    shade = np.clip(1.0 + 0.42 * light - 0.32 * np.clip(-h, 0, 1), 0.45, 1.10)
    rgb = SAND_RGB[None, None, :] * shade[:, :, None]
    if disc:
        yy, xx = np.mgrid[0:size, 0:size]
        d = np.hypot(xx - size / 2 + 0.5, yy - size / 2 + 0.5)
        rad = size / 2.0 - 0.5
        inside = np.clip(rad - d + 0.5, 0, 1)
        edge = np.clip(1 - np.abs(d - rad + size * 0.006) / max(1.0, size * 0.006), 0, 1)[:, :, None] * 0.18
        rgb = rgb * (1 - edge)
        if bg is None:
            a = np.dstack([np.clip(rgb, 0, 255), inside[:, :, None] * 255])
            return Image.fromarray(a.astype(np.uint8), 'RGBA')
        back = np.array(bg if not isinstance(bg, str) else _hex(bg), np.float32)[None, None, :]
        rgb = back * (1 - inside[:, :, None]) + rgb * inside[:, :, None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB')


def relief_png(strokes, size=240, disc=True, line_frac=None, bg=None):
    """PNG bytes of `relief_image`. About 20 ms at 240 px."""
    out = io.BytesIO()
    relief_image(strokes, size, disc, line_frac, bg).save(out, 'PNG', compress_level=3)
    return out.getvalue()


# ---------- the whole table (the keepsake picture) ----------
# Everything in "table frame": x = rho*cos(theta), y = rho*sin(theta), rho 1.0 = the table's full reach, theta
# counter-clockwise from 0 degrees pointing right, y UP. The picture is a top view of the sand disc.

TABLE_ROT_DEG = 0                  # turns the whole picture (counter-clockwise), once we know which side is the front
REACH_MM = 385.0
R_DESIGN = 0.9831                  # outer arc, in full-reach units (table session's measured frame, 2026-11-25)
R_RING = 0.6688                    # boundary between the inner and the outer ring
R_CENTRE = 0.2959                  # the centre circle
INNER_DEG = 90                     # inner ring: 4 slices, inner-1 is 0-90 degrees (counter-clockwise)
OUTER_DEG = 60                     # outer ring: 6 slices, outer-1 is 0-60 degrees
TABLE_LINE_FRAC = 0.011            # groove width / picture width: the 9.8 mm ball on a 770 mm circle is 0.0127
FINE_LINE_FRAC = 0.0062            # the app's own layout (not what the table cut): finer so faces stay readable
TABLE_ZONES = ['centre'] + ['inner-%d' % i for i in range(1, 5)] + ['outer-%d' % i for i in range(1, 7)]
ZONE_MARGIN = 0.05                 # clear gap between a layout item and the zone lines (rho)
_RIM = 0.017                       # width of the table's rim, as a fraction of the picture width


def zone_geom(zone):
    """{'r0','r1','a0','a1'} in rho and degrees (counter-clockwise). The centre has a0 = a1 = None."""
    if zone == 'centre':
        return {'r0': 0.0, 'r1': R_CENTRE, 'a0': None, 'a1': None}
    ring, k = zone.split('-')
    k = int(k) - 1
    if ring == 'inner':
        return {'r0': R_CENTRE, 'r1': R_RING, 'a0': INNER_DEG * k, 'a1': INNER_DEG * (k + 1)}
    return {'r0': R_RING, 'r1': R_DESIGN, 'a0': OUTER_DEG * k, 'a1': OUTER_DEG * (k + 1)}


def design_frame():
    """The zone lines as strokes in table frame: three circles and the radial lines between the slices."""
    out = []
    for r in (R_DESIGN, R_RING, R_CENTRE):
        out.append([[r * math.cos(a), r * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 241)])
    for deg in range(0, 360, INNER_DEG):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        out.append([[R_CENTRE * c, R_CENTRE * s], [R_RING * c, R_RING * s]])
    for deg in range(0, 360, OUTER_DEG):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        out.append([[R_RING * c, R_RING * s], [R_DESIGN * c, R_DESIGN * s]])
    return out


# ---- lettering: matplotlib's DejaVu Sans outlines, flattened to closed rings ----

_TEXT_CACHE = {}


def text_rings(text):
    """Closed rings (lists of (x, y), y up, em = 1, baseline 0) of the name in DejaVu Sans Bold."""
    if text in _TEXT_CACHE:
        return _TEXT_CACHE[text]
    import logging
    import warnings
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        tp = TextPath((0, 0), text, size=100, prop=FontProperties(family='DejaVu Sans', weight='bold'))
        polys = tp.to_polygons(closed_only=True)
    rings = [(np.asarray(p, np.float32) / 100.0) for p in polys if len(p) >= 3]
    if len(_TEXT_CACHE) > 400:
        _TEXT_CACHE.clear()
    _TEXT_CACHE[text] = rings
    return rings


# ---- the app's own layout of one zone (used when the table has not told us what it cut) ----

def _bbox(strokes):
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    return min(xs), min(ys), max(xs), max(ys)


class _Frame:
    """A place on the table with its own up and right: local (a, b) = a to the right, b up."""

    def __init__(self, ox, oy, ux, uy):
        self.o, self.u, self.r = (ox, oy), (ux, uy), (uy, -ux)

    def pt(self, a, b):
        return (self.o[0] + a * self.r[0] + b * self.u[0], self.o[1] + a * self.r[1] + b * self.u[1])


def _slice_frame(angle_rad, rho):
    """Item standing at polar position (angle, rho) with its top toward the table centre."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return _Frame(rho * c, rho * s, -c, -s)


def _put_strokes(strokes, frame, cx, cy, d, fit=True):
    """Unit-square strokes (y down) scaled to fit a box d x d centred at local (cx, cy). Returns table-frame strokes."""
    if not strokes:
        return []
    x0, y0, x1, y1 = _bbox(strokes)
    k = d / max(x1 - x0, y1 - y0, 1e-6)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return [[frame.pt(cx + (x - mx) * k, cy - (y - my) * k) for x, y in st] for st in strokes]


def _put_text(text, frame, cx, cy, max_w, max_h):
    """The name as closed rings in table frame, centred at local (cx, cy), at most max_w wide and max_h tall."""
    rings = text_rings(text)
    if not rings:
        return []
    allp = np.concatenate(rings)
    x0, x1 = float(allp[:, 0].min()), float(allp[:, 0].max())
    y0, y1 = float(allp[:, 1].min()), float(allp[:, 1].max())
    k = min(max_w / max(x1 - x0, 1e-6), max_h / max(y1 - y0, 1e-6))
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return [[frame.pt(cx + (x - mx) * k, cy + (y - my) * k) for x, y in r] for r in rings]


def _faces_item(face_list):
    """One or two face drawings side by side in a box twice as wide as tall. Returns (strokes in 0..1 box, aspect)."""
    if len(face_list) < 2:
        return (face_list[0] if face_list else None), 1.0
    out = []
    for i, f in enumerate(face_list[:2]):
        x0, y0, x1, y1 = _bbox(f)
        k = 1.0 / max(x1 - x0, y1 - y0, 1e-6)
        out += [[[(x - (x0 + x1) / 2) * k * 0.5 + 0.25 + 0.5 * i, (y - (y0 + y1) / 2) * k * 0.5 + 0.5]
                 for x, y in st] for st in f]
    return out, 2.0


def layout_zone(zone, name, faces=(), interests=(), art=()):
    """Where the app thinks things are in a zone: the name, the face, up to 3 interests (and in the centre the
    pictures beside the face), filling the zone with a clear gap to the zone lines, the name smaller than the face.
    Returns (lines, rings): drawing strokes and closed lettering rings, both in table frame."""
    g = zone_geom(zone)
    m = ZONE_MARGIN
    faces = [f for f in faces if f]
    interests = [s for s in list(interests)[:3] if s]
    art = [s for s in list(art)[:2] if s]
    face, aspect = _faces_item(faces)
    lines, rings = [], []
    if zone == 'centre':
        fr = _Frame(0, 0, 0, 1)
        R = g['r1'] - m                                        # usable radius
        n_i = len(interests)
        top = 0.62 * R if face or art else 0.0                 # name band centre
        if face is None and not art:
            rings += _put_text(name, fr, 0, 0.18 * R if n_i else 0, 1.5 * R, 0.5 * R)
        else:
            rings += _put_text(name, fr, 0, 0.70 * R, 1.25 * R, 0.30 * R)
        fy = (0.02 if n_i else -0.02) * R
        if face is not None:
            fd = (0.74 if art else 0.9) * R
            if aspect > 1:
                fd = min(fd * aspect, 1.5 * R) / aspect
            fw = fd * aspect
            lines += _put_strokes(face, fr, 0, fy, fd) if aspect == 1 else _put_strokes(face, fr, 0, fy, fw)
            span = fw / 2
        else:
            span = 0.2 * R
        for i, a in enumerate(art):
            sgn = -1 if i == 0 else 1
            if len(art) == 1:
                sgn = 1
            ad = 0.46 * R
            lines += _put_strokes(a, fr, sgn * (span + 0.06 * R + ad / 2), fy, ad)
        for i, s in enumerate(interests):
            idd = 0.30 * R
            lines += _put_strokes(s, fr, (i - (n_i - 1) / 2) * 0.38 * R, -0.70 * R, idd)
        return lines, rings
    # a slice: top toward the table centre; name first (near the centre), the row of face and interests below it
    a0, a1 = math.radians(g['a0']), math.radians(g['a1'])
    mid, span = (a0 + a1) / 2, a1 - a0
    top_r, bot_r = g['r0'] + m, g['r1'] - m
    hu = bot_r - top_r
    nh = 0.16 * hu
    rowh = 0.69 * hu
    n_name_r = top_r + nh / 2
    row_r = bot_r - rowh / 2
    nf = _slice_frame(mid, n_name_r)
    chord = lambda rho, h: max(0.05, (rho - h / 2) * span - 2 * m)           # room at the narrow side
    rings += _put_text(name, nf, 0, 0, chord(n_name_r, nh) * 0.92, nh)
    items = []                                                   # (strokes, width, d)
    fd = rowh
    idd = 0.74 * rowh
    if face is not None:
        items.append((face, fd * aspect, fd))
    for s in interests:
        items.append((s, idd, idd))
    if items:
        gap = 0.14 * rowh
        need = sum(w for _, w, _ in items) + gap * (len(items) - 1)
        k = min(1.0, chord(row_r, rowh) / need)
        x = -need * k / 2
        for s, w, d in items:
            w, d = w * k, d * k
            xc = x + w / 2
            fr = _slice_frame(mid + xc / row_r, row_r)
            lines += _put_strokes(s, fr, 0, 0, w if (s is face and aspect > 1) else d)
            x += w + gap * k
    return lines, rings


# ---- raster: distance to the ink, then the groove profile ----

def _sand_noise(size, seed=7):
    """Fine grain plus slow undulation, deterministic, float32 in about -1..1."""
    rng = np.random.RandomState(seed)
    fine = rng.standard_normal((size, size)).astype(np.float32)
    mid = _blur(rng.standard_normal((size, size)).astype(np.float32), 1.3)
    mid /= max(1e-6, float(mid.std()))
    slow = _blur(rng.standard_normal((size // 8 + 2, size // 8 + 2)).astype(np.float32), 3.0)
    slow = np.array(Image.fromarray(slow).resize((size, size), Image.BICUBIC), np.float32)
    slow /= max(1e-6, float(slow.std()))
    return fine, mid, slow


def _px(strokes, size, ss, rot_deg):
    """Table-frame strokes -> pixel-space float arrays at ss x size. 1.0 rho = the sand's radius."""
    c = size * ss / 2.0
    r = (size / 2.0 - _RIM * size) * ss
    cs, sn = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    out = []
    for s in strokes:
        a = np.asarray(s, np.float32).reshape(-1, 2)
        x = a[:, 0] * cs - a[:, 1] * sn
        y = a[:, 0] * sn + a[:, 1] * cs
        out.append(np.stack([c + x * r, c - y * r], 1))
    return out


def _ink_lines(strokes, size, ss, rot_deg):
    import cv2
    n = size * ss
    mask = np.zeros((n, n), np.uint8)
    polys, dots = [], []
    for a in _px(strokes, size, ss, rot_deg):
        if not np.isfinite(a).all():
            continue
        a = np.clip(a, -4 * n, 5 * n)
        if len(a) == 1:
            dots.append(a[0])
        else:
            polys.append(np.rint(a * 16).astype(np.int32).reshape(-1, 1, 2))
    if polys:
        cv2.polylines(mask, polys, False, 1, 1, cv2.LINE_8, 4)
    for d in dots:
        x, y = int(round(d[0])), int(round(d[1]))
        if 0 <= x < n and 0 <= y < n:
            mask[y, x] = 1
    return mask


def _ink_fill(rings, size, ss, rot_deg):
    """Closed rings filled (even-odd per glyph is approximated by xor of the rings)."""
    import cv2
    n = size * ss
    mask = np.zeros((n, n), np.uint8)
    for a in _px(rings, size, ss, rot_deg):
        if len(a) < 3 or not np.isfinite(a).all():
            continue
        x0, y0 = np.floor(a.min(0)).astype(int) - 1
        x1, y1 = np.ceil(a.max(0)).astype(int) + 2
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(n, x1), min(n, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        tmp = np.zeros((y1 - y0, x1 - x0), np.uint8)
        pts = np.rint((a - np.array([x0, y0], np.float32)) * 16).astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(tmp, [pts], 1, cv2.LINE_8, 4)
        mask[y0:y1, x0:x1] ^= tmp
    return mask


_PROF_T, _MASK_T = _profile_luts(floor=0.8, floor_k=3, ridge=0.26, ridge_at=1.55, ridge_w=0.5)   # softer than the icons


def _groove_from_ink(ink, hw_px, ss):
    """Groove height (float32, size x size) from an ink mask at ss x size: the same profile as the icons."""
    from scipy import ndimage
    if not ink.any():
        return np.zeros((ink.shape[0] // ss, ink.shape[1] // ss), np.float32)
    d = ndimage.distance_transform_edt(ink == 0).astype(np.float32)
    k = (_LUT_N - 1) / _U_MAX / (hw_px * ss)
    idx = np.minimum(d * k, _LUT_N - 1).astype(np.int32)
    h = _MASK_T[idx] * _PROF_T[idx]
    if ss > 1:
        n = h.shape[0] // ss
        h = h.reshape(n, ss, n, ss).mean(axis=(1, 3))
    return h.astype(np.float32)


def _hex2(h):
    return np.array(_hex(h), np.float32)


def table_image(lines, fine=(), rings=(), size=1000, rot_deg=None, line_frac=TABLE_LINE_FRAC,
                fine_frac=FINE_LINE_FRAC, ss=2):
    """The round sand table seen from above, as an RGB PIL image. `lines` are grooves of the real width, `fine`
    narrower grooves (the app's own layout), `rings` filled lettering (engraved letters). All in table frame."""
    size = int(size)
    rot = TABLE_ROT_DEG if rot_deg is None else rot_deg
    layers = []
    if lines:
        layers.append((_groove_from_ink(_ink_lines(lines, size, ss, rot), line_frac * size / 2.0, ss), line_frac * size / 2.0))
    if fine:
        layers.append((_groove_from_ink(_ink_lines(fine, size, ss, rot), fine_frac * size / 2.0, ss), fine_frac * size / 2.0))
    if rings:
        hw = fine_frac * size / 2.0 * 0.62
        layers.append((_groove_from_ink(_ink_fill(rings, size, ss, rot), hw, ss), hw))
    grain, mid, slow = _sand_noise(size)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = size / 2.0 - 0.5
    rad = np.hypot(xx - c, yy - c)
    r_sand = size / 2.0 - _RIM * size                         # rho 1.0
    # height field: grooves plus the sand's own grain
    h_g = np.zeros((size, size), np.float32)
    light = np.zeros((size, size), np.float32)
    for h, hw in layers:
        hb = _blur(h, 0.8)
        gy, gx = np.gradient(hb)
        light += (gx + gy) * (hw * 0.8)
        h_g += h
    h_g = np.clip(h_g, -1.0, 0.6)
    grain_h = 0.025 * grain + 0.04 * mid
    gy, gx = np.gradient(_blur(grain_h, 0.6))
    light += (gx + gy) * 1.6
    shade = 1.0 + 0.40 * light - 0.20 * np.clip(-h_g, 0, 1)
    shade += 0.008 * slow + 0.006 * grain
    shade += 0.007 * np.sin(rad * (2 * math.pi / 5.5) + 3.0 * slow)      # faint rake rings left by the erase
    # a soft light fall-off toward the rim, and the rim itself
    t = np.clip(rad / r_sand, 0, 1.2)
    shade *= 1.0 - 0.10 * np.clip((t - 0.7) / 0.3, 0, 1) ** 2
    shade *= 1.03 - 0.06 * ((xx - c) + (yy - c)) / size
    sand = _hex2('#efe7cc')
    rgb = sand[None, None, :] * np.clip(shade, 0.35, 1.18)[:, :, None]
    rgb[:, :, 2] *= 0.985
    # rim: a dark wooden ring around the sand with a lit inner edge
    rim_in, rim_out = r_sand, size / 2.0 - 0.5
    wood = _hex2('#5b4630')
    rim_t = np.clip((rad - rim_in) / max(1.0, rim_out - rim_in), 0, 1)
    lit = 1.0 + 0.22 * np.clip(-(xx - c + yy - c) / (2 * size / 2.0), -1, 1) * (1 - 2 * np.abs(rim_t - 0.5))
    rim_rgb = wood[None, None, :] * (lit * (0.8 + 0.3 * (1 - rim_t)))[:, :, None]
    glow = np.clip(1 - rim_t / 0.45, 0, 1)[:, :, None]                      # the table's light ring, just inside the rim
    rim_rgb = rim_rgb * (1 - glow) + _hex2('#f7f4fb')[None, None, :] * glow
    # sand sinks slightly in shadow right next to the rim
    shadow = np.clip(1 - (rim_in - rad) / (0.012 * size), 0, 1) ** 2 * 0.22
    rgb *= (1 - shadow)[:, :, None]
    in_rim = np.clip(rad - rim_in + 0.5, 0, 1)[:, :, None]
    rgb = rgb * (1 - in_rim) + rim_rgb * in_rim
    outside = np.clip(rad - rim_out + 0.5, 0, 1)[:, :, None]
    bg = _hex2('#f5f2e9')[None, None, :]
    rgb = rgb * (1 - outside) + bg * outside
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB')


def render_table(zones, frame=None, size=1000, rot_deg=None):
    """Compose the whole table. `zones`: {zone: item} where item is
    {'strokes': [...]} (what the table cut, table frame) or {'name', 'faces', 'interests', 'art'} (the app's own layout
    from 0..1 drawings) or None/missing (plain sand). `frame`: strokes for the zone lines, None for the design."""
    lines = list(frame) if frame else design_frame()
    fine, rings = [], []
    for z in TABLE_ZONES:
        it = zones.get(z)
        if not it:
            continue
        if 'strokes' in it:
            lines += it['strokes']
        else:
            ln, rg = layout_zone(z, it.get('name') or '', it.get('faces') or (), it.get('interests') or (),
                                 it.get('art') or ())
            fine += ln
            rings += rg
    return table_image(lines, fine, rings, size, rot_deg)


def table_png(zones, frame=None, size=1000, rot_deg=None):
    out = io.BytesIO()
    render_table(zones, frame, size, rot_deg).save(out, 'PNG', compress_level=4)
    return out.getvalue()
