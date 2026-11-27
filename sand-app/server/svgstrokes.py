"""Turn a small icon SVG (Lucide/Feather style, stroke only) into sand strokes.

The SVG comes from a model that read text typed by strangers, so it is treated as hostile: only a short list of
elements is accepted, anything that could load, run or reference something is rejected, sizes are capped, and
nothing is ever rendered by a browser from it. We only read geometry and flatten it to polylines.

    svg_to_strokes(svg_text)  -> strokes on the 24 grid (list of lists of (x, y)), raises SvgError
    fit_strokes(strokes)      -> API strokes: 0..1, y down, centred and scaled to fit the disc
"""
import math
import re
import xml.etree.ElementTree as ET

from svgelements import Arc, Close, CubicBezier, Line, Matrix, Move, Path, QuadraticBezier

MAX_SVG_CHARS = 24000
MAX_ELEMENTS = 80
MAX_D_CHARS = 6000
MAX_STROKES = 40
MAX_POINTS = 3000          # on the way in; the API allows 4000 per picture
STEP = 0.4                 # flattening step on the 24 grid, curves are sampled about this far apart
FIT_HALF = 0.40            # half the picture's longest side, in 0..1
FIT_RADIUS = 0.45          # nothing further than this from the centre (the disc is 0.5, lips need room)
ALLOWED = {'svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon'}
SHAPES = ALLOWED - {'svg', 'g'}
_BAD_VALUE = re.compile(r'url\s*\(|javascript:|data:|@import|<!|&#|expression\s*\(', re.I)
_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


class SvgError(ValueError):
    pass


def _tag(el):
    t = el.tag
    if not isinstance(t, str):
        raise SvgError('odd node')
    if t.startswith('{'):
        ns, _, t = t[1:].partition('}')
        if ns != 'http://www.w3.org/2000/svg':
            raise SvgError('foreign namespace')
    return t


def _num(el, name, default=0.0):
    v = el.get(name)
    if v is None or v.strip() == '':
        return default
    m = _NUM.fullmatch(re.sub(r'(px)?$', '', v.strip()))
    if not m:
        raise SvgError('bad number %s' % name)
    x = float(m.group(0))
    if not math.isfinite(x) or abs(x) > 1e5:
        raise SvgError('number out of range')
    return x


def _matrix(parent, el):
    t = el.get('transform')
    if not t:
        return parent
    if len(t) > 300 or not re.fullmatch(r'[\sa-zA-Z0-9.,()+\-eE]*', t):
        raise SvgError('bad transform')
    try:
        m = Matrix(t)
    except Exception:
        raise SvgError('bad transform')
    return Matrix(m) * parent if parent is not None else m


def _apply(m, pts):
    if m is None:
        return [(float(x), float(y)) for x, y in pts]
    return [(m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f) for x, y in pts]


def _ellipse_pts(cx, cy, rx, ry, a0=0.0, a1=2 * math.pi):
    n = max(12, int(math.ceil(abs(a1 - a0) * max(rx, ry) / STEP)))
    n = min(n, 120)
    return [(cx + rx * math.cos(a0 + (a1 - a0) * i / n), cy + ry * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def _rect_pts(x, y, w, h, rx, ry):
    rx, ry = min(rx, w / 2), min(ry, h / 2)
    if rx <= 0 or ry <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    pts = []
    for cx, cy, a0 in ((x + w - rx, y + ry, -math.pi / 2), (x + w - rx, y + h - ry, 0.0),
                       (x + rx, y + h - ry, math.pi / 2), (x + rx, y + ry, math.pi)):
        pts += _ellipse_pts(cx, cy, rx, ry, a0, a0 + math.pi / 2)
    return pts + [pts[0]]


def _path_strokes(d):
    if len(d) > MAX_D_CHARS:
        raise SvgError('path too long')
    try:
        path = Path(d)
    except Exception:
        raise SvgError('bad path')
    out, cur = [], None
    for seg in path:
        if isinstance(seg, Move):
            if cur and len(cur) > 1:
                out.append(cur)
            if seg.end is None or seg.end.x is None:
                raise SvgError('bad path')
            cur = [(seg.end.x, seg.end.y)]
        elif cur is None:
            raise SvgError('bad path')
        elif isinstance(seg, Close):
            if seg.end is not None and seg.end.x is not None:
                cur.append((seg.end.x, seg.end.y))
        elif isinstance(seg, Line):
            cur.append((seg.end.x, seg.end.y))
        elif isinstance(seg, (QuadraticBezier, CubicBezier, Arc)):
            probe = seg.npoint([i / 8.0 for i in range(9)])
            length = sum(math.hypot(probe[i + 1][0] - probe[i][0], probe[i + 1][1] - probe[i][1]) for i in range(8))
            n = min(60, max(3, int(math.ceil(length / STEP))))
            pts = seg.npoint([i / float(n) for i in range(n + 1)])
            cur.extend((float(x), float(y)) for x, y in pts[1:])
        else:
            raise SvgError('unknown segment')
    if cur and len(cur) > 1:
        out.append(cur)
    return out


def svg_to_strokes(text):
    """Flatten the SVG into polylines on its own coordinate grid (24 x 24 for Lucide style icons)."""
    if not isinstance(text, str) or not text.strip():
        raise SvgError('empty')
    if len(text) > MAX_SVG_CHARS:
        raise SvgError('too long')
    if _BAD_VALUE.search(text):
        # no DOCTYPE, comments, CDATA or entities, no url() / javascript: / data: anywhere
        raise SvgError('forbidden content')
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        raise SvgError('not xml')
    if _tag(root) != 'svg':
        raise SvgError('root is not svg')
    strokes, count = [], [0]

    def walk(el, m, depth):
        if depth > 6:
            raise SvgError('too deep')
        count[0] += 1
        if count[0] > MAX_ELEMENTS:
            raise SvgError('too many elements')
        name = _tag(el)
        if name not in ALLOWED:
            raise SvgError('element not allowed: %s' % name[:20])
        for k, v in el.attrib.items():
            kl = k.lower()
            if kl.startswith('on') or 'href' in kl or kl in ('style',) or _BAD_VALUE.search(v):
                raise SvgError('attribute not allowed: %s' % k[:20])
        m = _matrix(m, el)
        if name in ('svg', 'g'):
            for ch in el:
                walk(ch, m, depth + 1)
            return
        if len(el):
            raise SvgError('shape with children')
        if name == 'path':
            raw = _path_strokes(el.get('d') or '')
        elif name == 'circle':
            r = _num(el, 'r')
            raw = [_ellipse_pts(_num(el, 'cx'), _num(el, 'cy'), r, r)] if r > 0 else []
        elif name == 'ellipse':
            rx, ry = _num(el, 'rx'), _num(el, 'ry')
            raw = [_ellipse_pts(_num(el, 'cx'), _num(el, 'cy'), rx, ry)] if rx > 0 and ry > 0 else []
        elif name == 'rect':
            w, h = _num(el, 'width'), _num(el, 'height')
            rx, ry = _num(el, 'rx', None), _num(el, 'ry', None)
            rx = ry if rx is None else rx
            ry = rx if ry is None else ry
            raw = [_rect_pts(_num(el, 'x'), _num(el, 'y'), w, h, rx or 0.0, ry or 0.0)] if w > 0 and h > 0 else []
        elif name == 'line':
            raw = [[(_num(el, 'x1'), _num(el, 'y1')), (_num(el, 'x2'), _num(el, 'y2'))]]
        else:  # polyline, polygon
            pts = el.get('points') or ''
            if len(pts) > MAX_D_CHARS:
                raise SvgError('points too long')
            nums = [float(x) for x in _NUM.findall(pts)]
            if any(not math.isfinite(x) or abs(x) > 1e5 for x in nums):
                raise SvgError('number out of range')
            line = list(zip(nums[0::2], nums[1::2]))
            if name == 'polygon' and line:
                line.append(line[0])
            raw = [line] if len(line) > 1 else []
        for pts in raw:
            strokes.append(_apply(m, pts))
            if len(strokes) > MAX_STROKES:
                raise SvgError('too many strokes')
        if sum(len(s) for s in strokes) > MAX_POINTS:
            raise SvgError('too many points')

    walk(root, None, 0)
    out = []
    for s in strokes:
        pts = [s[0]]
        for p in s[1:]:
            if math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
                pts.append(p)
        if len(pts) >= 2:
            out.append(pts)
    if not out:
        raise SvgError('no strokes')
    return out


def fit_strokes(strokes, half=FIT_HALF, radius=FIT_RADIUS, ndigits=4):
    """Centre the picture's bounding box on (0.5, 0.5) and scale so it fits: longest side 2 * half and nothing
    further than `radius` from the centre. Returns API strokes (0..1, y down, rounded)."""
    xs = [x for s in strokes for x, _ in s]
    ys = [y for s in strokes for _, y in s]
    if not xs:
        raise SvgError('no points')
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    side = max(max(xs) - min(xs), max(ys) - min(ys)) / 2.0
    far = max(math.hypot(x - cx, y - cy) for s in strokes for x, y in s)
    if side < 2.0 or far < 2.0:
        raise SvgError('drawing too small')
    k = min(half / side, radius / far)
    return [[[round(0.5 + (x - cx) * k, ndigits), round(0.5 + (y - cy) * k, ndigits)] for x, y in s]
            for s in strokes]
