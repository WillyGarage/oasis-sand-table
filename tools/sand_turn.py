#!/usr/bin/env python3
"""One table turn for ANY guest on the 36-inch table (FILES AND SIMULATION ONLY: never contacts a table).

    build_turn(zone_name, kind, name, face_path, interests_strokes, start_file, clear_dir, out_dir, world=None)

builds the same files as tools/sand_zone_swap.py (1-travel, 2-clear, 3-recut, 4-content*) for a person who is not one of the
fixed cartoons: the name is lettered (only A-Z can be lettered, other characters are dropped), the face comes from `face_path`
(0..1 polylines, y down, same format as interest strokes) or, when that is None and the name is Alex, Bill, Lek, Thomas or
Maverick, from that cartoon, else there is no face (name and pictures only).  Up to 3 pictures from `interests_strokes` (a list of
stroke lists, each stroke a list of [x, y] in 0..1, y down).  kind "clear" builds travel + clear + recut only.

Everything is done by importing sand_zone_swap / sand_update_plan and swapping a few of their lookups (face, pictures, centre
layout) for ones that read the guest's own strokes; no existing file is changed and the existing behaviour is untouched
for callers that do not go through this module.

Zone names: centre; inner-1..4 = ring 1 slices 0-90, 90-180, 180-270, 270-360; outer-1..6 = ring 2 slices 0-60 ... 300-360.
"""
import json, math, os, re, sys, itertools
import numpy as np
from shapely.geometry import MultiPoint

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_zone_swap as sz
import sand_update_plan as u

f0 = u.f0
CARTOONS = {'ALEX': 'alex', 'BILL': 'bill', 'LEK': 'lek', 'THOMAS': 'thomas', 'MAVERICK': 'dog'}
MAX_NAME = 16
NAME_LIFT_MM = 6.0                          # name letters stand this far off the frame line (rev3 used 8): stems are at most 6 mm
REG = {}                                   # token -> dict(face=('cartoon', key) | ('strokes', [arrays]) | None, pics=[[arrays]])
_N = [0]


def zone_geometry(zone):
    """-> dict(kind='slice'|'centre', ring, a=(lo, hi), slug_part)"""
    if zone == 'centre':
        return dict(kind='centre', ring=0, a=(0, 360))
    m = re.fullmatch(r'(inner|outer)-(\d+)', zone)
    if not m:
        raise ValueError('unknown zone %r' % zone)
    k = int(m.group(2)) - 1
    if m.group(1) == 'inner' and 0 <= k < 4:
        return dict(kind='slice', ring=1, a=(90 * k, 90 * k + 90))
    if m.group(1) == 'outer' and 0 <= k < 6:
        return dict(kind='slice', ring=2, a=(60 * k, 60 * k + 60))
    raise ValueError('unknown zone %r' % zone)


def letter_name(name):
    """Upper-case, A-Z and single spaces only (the lettering has nothing else; a space is a gap between words), at most MAX_NAME
    characters.  Accents are folded (e with diaeresis -> E).  Empty -> GUEST."""
    import unicodedata
    t = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().upper()
    t = re.sub(r'[^A-Z ]', '', t.replace('-', ' '))
    t = re.sub(r' +', ' ', t).strip()
    return t[:MAX_NAME].strip() or 'GUEST'


_orig_name_local = u.name_local
SPACE_ADV = 0.55                           # a space is a gap this many letter heights wide


def _name_local(text, h):
    """Same as sand_update_plan.name_local, plus gaps for spaces."""
    if ' ' not in text:
        return _orig_name_local(text, h)
    C = u.caps()
    x, out = 0.0, []
    for c in text:
        if c == ' ':
            x += SPACE_ADV * h
            continue
        out.append(u.letter_path(c) * h + np.array([x, 0.0]))
        x += (C[c]['advance'] + u.NAME_SP) * h
    return out, x - u.NAME_SP * h


# ------------------------------------------------------------------ strokes -> local item geometry (mm, y up)
def _clean(strokes):
    out = []
    for s in strokes or []:
        a = np.asarray(s, float).reshape(-1, 2)
        a = a[np.isfinite(a).all(1)]
        if len(a) >= 2:
            out.append(np.column_stack((a[:, 0], -a[:, 1])))        # y down -> y up
    return out


def _simplify(arrs, tol=0.25):                 # tol in the units of the arrays (mm once scaled)
    from shapely.geometry import LineString
    out = []
    for a in arrs:
        ls = LineString(a).simplify(tol)
        c = np.asarray(ls.coords, float)
        if len(c) >= 2 and ls.length > 2 * tol:
            out.append(c)
    return out


def _fit(arrs, fit_fn, tol=0.25):
    """Centre on the bounding box, scale by fit_fn(width, height) -> factor, simplify."""
    allp = np.vstack(arrs)
    lo, hi = allp.min(0), allp.max(0)
    c = (lo + hi) / 2
    w, h = float(hi[0] - lo[0]), float(hi[1] - lo[1])
    s = fit_fn(max(w, 1e-6), max(h, 1e-6), allp - c)
    return _simplify([(a - c) * s for a in arrs], tol)


def _grounded(arrs, centre=False):
    """Move so the lowest point is the origin (it stands on the frame line) -> strokes, hull.  centre=True (faces): among the points
    within 2% of the lowest, take the one nearest the middle, so the bust stands on the line at its centre instead of hanging off
    one corner (a corner stand costs half the width to the arc's sag and capped faces near 56 mm)."""
    allp = np.vstack(arrs)
    if centre:
        lo = allp[:, 1].min()
        xc = (allp[:, 0].min() + allp[:, 0].max()) / 2.0
        e = allp[int(np.argmin(np.hypot(allp[:, 0] - xc, allp[:, 1] - lo)))].copy()      # nearest to the bottom centre
    else:
        e = allp[int(np.argmin(allp[:, 1]))].copy()
    arrs = [a - e for a in arrs]
    return arrs, MultiPoint(np.vstack(arrs)[::2]).convex_hull


def custom_face(strokes01, H):
    arrs = _clean(strokes01)
    arrs = _fit(arrs, lambda w, h, p: H / max(h, w / 1.15))
    arrs = [u.dens(a, 1.5) for a in arrs]                  # a vertex at the bottom centre to stand on
    arrs, hull = _grounded(arrs, centre=True)
    return dict(kind='face', strokes=arrs, hull=hull, centred=True)


def custom_icon(strokes01, d):
    arrs = _clean(strokes01)
    arrs = _fit(arrs, lambda w, h, p: (d / 2.0) / max(1e-6, float(np.hypot(*p.T).max())))
    arrs, hull = _grounded(arrs)
    return dict(kind='icon', strokes=arrs, hull=hull)


# ------------------------------------------------------------------ lookups swapped into sand_update_plan / sand_zone_swap
_orig_face_item, _orig_icon_item = u.face_item, u.icon_item
_orig_items_for, _orig_pics_for = u.items_for, u.pics_for
_orig_centre_layout, _orig_content_centre = sz.centre_layout, sz.content_centre
_orig_content_slice = sz.content_slice
_orig_layout_slice = sz.layout_slice
_orig_addx = sz.addx


def _face_item(person, H):
    r = REG.get(person)
    if r is None:
        return _orig_face_item(person, H)
    if r['face'][0] == 'cartoon':
        it = _orig_face_item(r['face'][1], H)
        arrs = [u.dens(a, 1.5) for a in it['strokes']]
        arrs, hull = _grounded(arrs, centre=True)
        return dict(kind='face', strokes=arrs, hull=hull, centred=True)
    return custom_face(r['face'][1], H)


def _icon_item(key, d):
    if isinstance(key, tuple) and key and key[0] in REG:
        return custom_icon(REG[key[0]]['pics'][key[1]], d)
    return _orig_icon_item(key, d)


def _pics_for(zone):
    r = REG.get(zone['person'])
    if r is None:
        return _orig_pics_for(zone)
    return [(zone['person'], i) for i in range(min(len(r['pics']), zone.get('npics', 99)))]


def _items_for(zone, H, d, h):
    r = REG.get(zone['person'])
    if r is None:
        return _orig_items_for(zone, H, d, h)
    items = [u.name_item(zone['name'], h)]
    if r['face'] is not None:
        items.append(u.face_c(zone['person'], H))
    return items + [u.icon_c(k, d) for k in _pics_for(zone)]


# ------------------------------------------------------------------ centre: face as large as it fits, plus two small seasonal pictures
HOLIDAY = 'thanksgiving'
_CTX = dict(holiday=HOLIDAY, turn=None, centre_art=None)
_PENDING_ARCS = []


def _art_turkey():
    import sand_slices as ss
    return [np.asarray(x, float) for x in ss.icon_fit('turkey', (0, 0), 1.0)]


def _art(fn):
    return lambda: [np.asarray(fn(), float)]


def holiday_art():
    """Thanksgiving set, y up, upright: name -> list of stroke arrays (existing art in tools/)."""
    import autumn_leaves, guest_harvest_art, guest_pie_art, guest_pumpkin
    return {'turkey': _art_turkey, 'pumpkin': _art(guest_pumpkin.pumpkin), 'pie': _art(guest_pie_art.pumpkin_pie),
            'maple leaf': _art(autumn_leaves.maple), 'acorn': _art(guest_harvest_art.acorn), 'corn': _art(guest_harvest_art.ear_of_corn),
            'harvest basket': _art(guest_harvest_art.harvest_basket)}


def holiday_pair(turn, name):
    import random
    keys = sorted(holiday_art())
    rnd = random.Random(turn if turn is not None else sum(map(ord, name or '')))
    return rnd.sample(keys, 2)


def _face_unit(r):
    if r['face'][0] == 'cartoon':
        thr = u.tc.read_thr(os.path.join(sz.ROOT, 'patterns', u.THR[r['face'][1]]))
        arrs = [u.z.thr_to_xy(thr, 1.0)]
    else:
        arrs = _clean(r['face'][1])
    return _fit(arrs, lambda w, h_, p: 1.0 / max(h_, w / 1.15), tol=0.25 / 150.0)       # bounding box height <= 1, centred


def _place_picture(arrs, d, side_angles, face_pts, strip, other=None):
    """Upright picture (strokes y up) of diameter d pushed out along each direction until its outermost point touches the centre circle.
    Returns the best candidate (largest clearance, lower is better) as dict(strokes, entry, angle, gap) or None."""
    from shapely.geometry import MultiPoint
    allp = np.vstack(arrs)
    c0 = (allp.min(0) + allp.max(0)) / 2
    rad = float(np.hypot(*(allp - c0).T).max())
    loc = [(a - c0) * (d / 2.0 / rad) for a in arrs]
    pts = np.vstack(loc)
    best = None
    ftree = MultiPoint(face_pts[::3])
    for ang in side_angles:
        e = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
        lo, hi = 0.0, f0
        for _ in range(40):
            mid = (lo + hi) / 2
            if np.hypot(*(pts + e * mid).T).max() <= f0 - 0.05:
                lo = mid
            else:
                hi = mid
        off = e * lo
        w = pts + off
        rr = np.hypot(*w.T)
        k = int(rr.argmax())
        g = min(MultiPoint(w[::2]).distance(ftree), MultiPoint(w[::2]).distance(strip))
        if other is not None:
            g = min(g, MultiPoint(w[::2]).distance(other))
        if g < u.GAP_MIN:
            continue
        score = min(g, 25.0) - 0.04 * float(off[1])
        if best is None or score > best['score']:
            best = dict(score=score, gap=float(g), strokes=[a + off for a in loc], entry=w[k].copy(), angle=math.degrees(math.atan2(w[k][1], w[k][0])) % 360.0, poly=MultiPoint(w[::2]))
    return best


def _centre_layout(person, name, nb=None):
    r = REG.get(person)
    if r is None:
        return _orig_centre_layout(person, name, nb)
    h = 25.0
    lets, W = u.name_local(name, h)
    L = u.Line.__new__(u.Line)
    L.kind, L.r, L.up_in, L.sgn, L.r_in, L.r_out = 'outer', f0, True, 1, 0, f0
    phi_s = -90.0 - math.degrees(W / 2 / f0)
    strip = u.name_poly_l(L, phi_s, W, h, u.NAME_LIFT)
    nbm = MultiPoint(nb[::2]) if nb is not None and len(nb) else None
    if nbm is not None and strip.distance(nbm) < 8.0:
        raise SystemExit('the name strip would be too close to a neighbouring drawing')
    base = dict(H=0.0, s=0, cy=0, name_h=h, phi_s=phi_s, W=W, letters=lets, line=L, person=person, custom=True, holiday=[], pic_items=[])
    if r['face'] is None:
        return dict(base, face=np.array([[0.0, f0 - 1.0]] * 2), crown=0, face_strokes=None)
    unit = _face_unit(r)
    allu = np.vstack([u.dens(a, 1.5 / 180.0) for a in unit])          # dense enough for the distance tests below
    feas = {}                                                        # hh -> [cy, ...]
    for hh in np.arange(180.0, 50.0, -2.0):
        for cy in np.arange(-30.0, 40.0, 1.0):
            pp = allu * hh + np.array([0.0, cy])
            if np.hypot(*pp.T).max() > f0 - 0.3 or MultiPoint(pp[::7]).distance(strip) < u.GAP_MIN:
                continue
            if nbm is not None and MultiPoint(pp[::5]).distance(nbm) < 8.0:
                continue
            feas.setdefault(float(hh), []).append(float(cy))
        if feas and hh < max(feas) * 0.8:
            break
    if not feas:
        raise RuntimeError('no room for this face in the centre')
    best_hh = max(feas)
    pick = (best_hh, feas[best_hh][0], [])
    pics = []
    given = _CTX.get('centre_art')
    if given is not None:                                              # the app chose them: draw exactly those (none if the list is empty)
        art = {'a%d' % i: (lambda st=st: _clean(st)) for i, st in enumerate(given[:2]) if _clean(st)}
        keys = list(art)
        keys = keys + [None] * (2 - len(keys))
    elif _CTX.get('holiday') == 'thanksgiving':
        art = holiday_art()
        keys = holiday_pair(_CTX.get('turn'), name)
    else:
        art, keys = {}, []
    if keys and any(keys):
        found = None
        for hh in sorted(feas, reverse=True):
            if hh < 0.9 * best_hh - 1e-9:
                break
            for cy in feas[hh]:
                pp = allu * hh + np.array([0.0, cy])
                for d in (60.0, 55.0, 50.0, 45.0):
                    left = _place_picture(art[keys[0]](), d, range(150, 266, 3), pp, strip) if keys[0] else None
                    right = _place_picture(art[keys[1]](), d, range(275, 391, 3), pp, strip, other=left['poly'] if left else None) if keys[1] else None
                    if (left or not keys[0]) and (right or not keys[1]):
                        found = (hh, cy, [(k_, d, c_) for k_, c_ in ((keys[0], left), (keys[1], right)) if c_])
                        break
                if found:
                    break
            if found:
                break
        if found:
            pick = found
    hh, cy, pics = pick
    strokes = [a * hh + np.array([0.0, cy]) for a in unit]
    allp = np.vstack(strokes)
    k = int(np.argmax(np.hypot(*allp.T)))
    for key, d, cand in pics:
        _PENDING_ARCS.append(cand['angle'])
    out = dict(base, H=float(hh), s=float(hh), cy=cy, face=allp, crown=k, face_strokes=strokes, best_hh=float(best_hh),
               holiday=[(key, d) for key, d, _ in pics], pic_items=[c for _, _, c in pics])
    _CTX['centre'] = out
    return out


def _content_centre(run, FR, c):
    if not c.get('custom'):
        return _orig_content_centre(run, FR, c)
    a0 = len(run.ev)
    u.draw_name_r2(run, FR, c['line'], c['phi_s'], c['letters'], u.NAME_LIFT, from_centre=False)
    run.items.append((0, 'name', a0, len(run.ev)))
    if c['face_strokes'] is None:
        return
    entry = c['face'][c['crown']]
    node = FR.node(u.P(f0, math.degrees(math.atan2(entry[1], entry[0]))))
    run.walk(FR, node)
    run.ev.append(('stem', np.array([FR.pos[node], entry])))
    run.pos = np.array(entry, float)
    a0 = len(run.ev)
    for kind, pl in u.item_walk(c['face_strokes'], entry, 'face'):
        run.line(kind, pl)
    run.items.append((0, 'face', a0, len(run.ev)))
    run.ev.append(('stem', np.array([run.pos, FR.pos[node]])))
    run.pos = FR.pos[node].copy()
    run.node = node
    for cand in c['pic_items']:
        e = cand['entry']
        n2 = FR.node(u.P(f0, cand['angle']))
        run.walk(FR, n2)
        a0 = len(run.ev)
        for kind, pl in u.item_walk(cand['strokes'], e, 'icon'):
            run.line(kind, pl)
        run.items.append((0, 'icon', a0, len(run.ev)))
        run.pos = FR.pos[n2].copy() if np.hypot(*(run.pos - FR.pos[n2])) < 0.6 else run.pos
        run.node = n2


def _addx(e, ea, es):
    _orig_addx(e, ea, es)
    if _PENDING_ARCS and e[0] == 'arc':
        while _PENDING_ARCS:
            _orig_addx(('arc', round(f0, 3), _PENDING_ARCS.pop() % 360), ea, es)


def _content_slice(run, FR, items, lay):
    """The original needs a name plus at least one more item (it fixes the first two); a name on its own (clear turns, guests with no
    face and no pictures) is drawn here the same way."""
    if len(items) >= 2:
        return _orig_content_slice(run, FR, items, lay)
    it, pz = items[0], lay[0]
    a, b, _ = u.name_phis(pz['L'], pz['s'], it['letters'])
    run.walk(FR, FR.node(u.P(pz['L'].r, a)))
    a0 = len(run.ev)
    u.draw_name_r2(run, FR, pz['L'], pz['s'], it['letters'], u.NAME_LIFT)
    run.items.append((1, it['kind'], a0, len(run.ev)))
    return (0,)


TILTS_FACE = (-3.0, 3.0)      # degrees; a small tilt makes exactly one shoulder corner touch the arc


def _face_poses(item, zone, regs, lines, zl):
    """Faces stand upright with their base outward, ORIENTED BY THEIR OWN CENTRE (radial there), and are pushed out until one shoulder
    corner touches the outer arc.  Touch point = entry = exit: no stem at all.  Local strokes have the bottom centre as origin (y up)."""
    from shapely.geometry import MultiPoint
    L = [l for l in lines if l.kind == 'outer'][0]
    r = L.r
    reg = regs['outer'].buffer(0.5)
    S = item['strokes']
    pts = np.vstack(S)
    hp = pts[::2]
    mid = (zone['a_lo'] + zone['a_hi']) / 2.0
    others = [k for k in zl if k != 'outer']
    out = []
    for s_ in np.arange(zone['a_lo'] + 0.5, zone['a_hi'], 1.0):
        e = np.array([math.cos(math.radians(s_)), math.sin(math.radians(s_))])
        for tilt in TILTS_FACE:
            up = -e
            c_, s2 = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
            up = np.array([c_ * up[0] - s2 * up[1], s2 * up[0] + c_ * up[1]])
            t = np.array([up[1], -up[0]])
            Wl = np.outer(pts[:, 0], t) + np.outer(pts[:, 1], up)
            lo, hi = 0.0, r
            if np.hypot(*(Wl + e * hi).T).max() < r - 1e-6:
                continue
            for _ in range(36):
                m = (lo + hi) / 2
                if np.hypot(*(Wl + e * m).T).max() <= r:
                    lo = m
                else:
                    hi = m
            Wd = Wl + e * lo
            rad = np.hypot(*Wd.T)
            j = int(rad.argmax())
            C = Wd[j].copy()
            near = Wd[rad > r - 0.7]
            if len(near) and float(np.hypot(*(near - C).T).max()) > 3.0:
                continue                                       # would touch the arc at two places
            poly = MultiPoint(Wd[::2]).convex_hull
            if not reg.contains(poly):
                continue
            phi = math.degrees(math.atan2(C[1], C[0]))
            phi += 360.0 * round((mid - phi) / 360.0)
            out.append(dict(L=L, s=phi, poly=poly, C=C, u=up, org=C, var=dict(strokes=[a - pts[j] for a in S], hull=None, width=0.0), lift=0.0,
                            theta=tilt, edge=min(poly.distance(zl[k]) for k in others)))
    return out


_orig_poses_r2 = u.poses_r2


def _poses_r2(item, zone, regs, lines, kinds, zl):
    if item.get('kind') == 'face' and item.get('centred'):
        return _face_poses(item, zone, regs, lines, zl)
    return _orig_poses_r2(item, zone, regs, lines, kinds, zl)


MIN_PIC = 60.0           # pictures may shrink this far (design mm) to buy a bigger face
MAX_PIC = 75.0
DROP_GAIN = 1.15         # drop to 2 pictures only if the face gets at least this much bigger
MIN_GAP = 9.0


def _layout_slice(zone, world, seed):
    """Faces first: as large as the zone allows with the name (same letter size) and the pictures at their smallest; then the pictures
    grow back as far as they fit without taking face size; then pack3 spreads everything evenly (same as sand_zone_swap.layout_slice).
    Guests with no face use the original layout."""
    r = REG.get(zone['person'])
    if r is None or r['face'] is None:
        return _orig_layout_slice(zone, world, seed)
    zpoly = u.zone_poly(zone)
    nb = sz.neighbour_points(world, zpoly)
    ob = MultiPoint(nb[::2]) if len(nb) else None
    rng = np.random.default_rng(seed)
    nph = len(r['pics'])
    name_h = 22.0
    cache = {}
    lift0 = u.FACE_LIFT

    def set_lift(H):
        pass                                              # faces now touch the outer arc at a shoulder corner: no stand-off, no stem

    def try_(H, d, npics, tries=120, passes=6):
        key = (round(H, 1), round(d, 1), npics)
        if key not in cache:
            zone['npics'] = npics
            set_lift(H)
            items = u.items_for(zone, H, d, name_h)
            lay, mg = u.pack2(zone, items, rng, tries=tries, passes=passes, keep=3, obst=ob)
            cache[key] = (items, lay, mg)
        items, lay, mg = cache[key]
        return (lay is not None and mg >= MIN_GAP), items, lay

    def biggest_face(npics, dmin=None):
        dmin = MIN_PIC if dmin is None else dmin
        hi = 170.0
        lo = next((c for c in (60.0, 80.0, 40.0, 30.0, 100.0) if try_(c, dmin, npics)[0]), None)    # tiny faces can fail the one-touch test
        if lo is None:
            return None
        while hi - lo > 2.0:
            mid = round((lo + hi) / 2.0 / 2.0) * 2.0
            if try_(mid, dmin, npics)[0]:
                lo = mid
            else:
                hi = mid
        return lo
    try:
        return _layout_slice_inner(zone, rng, ob, nb, r, nph, name_h, try_, biggest_face, set_lift)
    finally:
        u.FACE_LIFT = lift0


def _layout_slice_inner(zone, rng, ob, nb, r, nph, name_h, try_, biggest_face, set_lift):
    dmin = MIN_PIC
    H3 = biggest_face(nph)
    for dm in (52.0, 45.0):                         # the zone cannot hold the pictures at full legibility size: let them shrink
        if H3 is not None:
            break
        H3, dmin = biggest_face(nph, dm), dm
    use = nph
    H = H3
    if nph == 3:
        H2 = biggest_face(2, dmin)
        if H2 is not None and (H3 is None or H2 >= DROP_GAIN * H3):
            use, H = 2, H2
    for npc in (2, 1, 0):                           # still nothing: fewer pictures
        if H is not None:
            break
        H, use, dmin = biggest_face(npc, 45.0), npc, 45.0
    if H is None:
        raise RuntimeError('no face size fits this zone')
    d = dmin
    for dd in np.arange(dmin + 3.0, MAX_PIC + 0.1, 3.0):
        if try_(H, dd, use)[0]:
            d = float(dd)
        else:
            break
    set_lift(H)
    ok, items, lay0 = try_(H, d, use, tries=300, passes=10)
    if not ok:
        zone['npics'] = use
        items = u.items_for(zone, H, d, name_h)
        lay0, mg = u.pack2(zone, items, rng, tries=300, passes=10, keep=6, obst=ob)
        if lay0 is None or mg < MIN_GAP:
            H, d = H - 2, d
            set_lift(H)
            items = u.items_for(zone, H, d, name_h)
            lay0, mg = u.pack2(zone, items, rng, tries=300, passes=10, keep=6, obst=ob)
            if lay0 is None:
                raise RuntimeError('face layout did not settle')
    zone['npics'] = use
    lay = u.pack3(zone, items, rng, start=lay0, obst=ob)
    a = u.zone_ratios(lay)
    att = 0
    while a[0] > 1.5 and att < 12:
        att += 1
        l0, _ = u.pack2(zone, items, np.random.default_rng(100 + att), tries=300, passes=3, keep=3, obst=ob)
        if l0 is None:
            continue
        l2 = u.pack3(zone, items, rng, start=l0, tries=600, keep=14, passes=20, sub=900, obst=ob)
        a2 = u.zone_ratios(l2)
        if a2[0] < a[0]:
            lay, a = l2, a2
    zone['H'], zone['d'] = H, d
    zone['pictures_used'] = use
    _CTX['lay'] = (items, lay)
    return items, lay, a, nb


def _install():
    sz.layout_slice = _layout_slice
    u.poses_r2 = _poses_r2
    u.name_local = _name_local
    sz.content_slice = _content_slice
    u.face_item, u.icon_item, u.items_for, u.pics_for = _face_item, _icon_item, _items_for, _pics_for
    sz.centre_layout, sz.content_centre = _centre_layout, _content_centre
    sz.addx = _addx


_install()


# ------------------------------------------------------------------ progress map
PCT_W = dict(clear=30.0, name=15.0, face=30.0, interests=25.0)


def progress_knots(spec, run, kind, has_face, has_pics):
    """-> (files [name], knots [(position, percent)]) where position = file_index + fraction (0..1) within that file.
    Steps without content are dropped and the rest re-spread to 100, like the app's own step split."""
    names = [s[0] for s in spec]
    if kind == 'clear':
        mins = [m for m in _minutes(spec)]
        tot = sum(mins)
        kn, acc = [(0.0, 0.0)], 0.0
        for i, m in enumerate(mins):
            acc += m
            kn.append((i + 1.0, 100.0 * acc / tot))
        return names, kn
    ph = ['clear', 'name'] + (['face'] if has_face else []) + (['interests'] if has_pics else [])
    tw = sum(PCT_W[p] for p in ph)
    pct = {}
    acc = 0.0
    for p in ph:
        pct[p] = (acc, acc + 100.0 * PCT_W[p] / tw)
        acc += 100.0 * PCT_W[p] / tw
    # clear stage: every file that is not content, by estimated minutes
    nc = [i for i, n in enumerate(names) if not n.startswith('4')]
    cont = [i for i, n in enumerate(names) if n.startswith('4')]
    mins = _minutes(spec)
    tot = sum(mins[i] for i in nc)
    kn, acc = [(0.0, 0.0)], 0.0
    for i in nc:
        acc += mins[i]
        kn.append((i + 1.0, pct['clear'][1] * acc / tot))
    # content stage: boundaries by path length along the events, mapped to files by point count
    L = [float(np.hypot(*np.diff(pl, axis=0).T).sum()) for k, pl in run.ev]
    cum = np.concatenate([[0.0], np.cumsum(L)])
    total = cum[-1] or 1.0
    npts = [len(s[2]) for s in spec if s[0].startswith('4')]
    ntot = float(sum(npts) - (len(npts) - 1))

    def pos_of(x):                       # content fraction -> file position
        row = x * (ntot - 1)
        base = 0.0
        for j, n in enumerate(npts):
            span = n - 1
            if row <= base + span + 1e-9 or j == len(npts) - 1:
                return cont[j] + min(1.0, max(0.0, (row - base) / max(span, 1)))
            base += span
    ends = {}
    for zi, k, a, b in run.items:
        if k == 'name':
            ends['name'] = b
        elif k == 'face':
            ends['face'] = b
    ev_end = len(run.ev)
    bound = [('name', ends['name'])] + ([('face', ends['face'])] if has_face else []) + ([('interests', ev_end)] if has_pics else [])
    bound[-1] = (bound[-1][0], ev_end)                    # the last step runs to the end of the content
    for p, e in bound:
        x = cum[e] / total
        kn.append((pos_of(x), pct[p][1]))
    # make strictly non-decreasing
    out, last = [], (-1, -1)
    for pos, pc in kn:
        pos = max(pos, last[0])
        pc = max(pc, last[1])
        out.append((pos, pc))
        last = (pos, pc)
    out[-1] = (out[-1][0], 100.0)
    return names, out


def percent_at(knots, pos):
    xs = [k[0] for k in knots]
    ys = [k[1] for k in knots]
    return float(np.interp(pos, xs, ys))


# Effective speeds MEASURED on the real table (swap_run.jsonl, November 24 evening: 914 mm travel in 8.2 s, 15,893 mm clear in 78 s,
# 17,000 mm clear in 113 s, 911 mm recut in 5.5 s, 4,102 mm of content in 68.5 s, 6,441 mm in 152 s).  The planner's own estimate
# (length / vball) is 5 to 8 times too fast because of corner and acceleration limits.
EFF_MM_S = dict(travel=110.0, clear=170.0, recut=160.0, content=50.0)
FILE_OVERHEAD_S = 3.0


def est_seconds(name, length_physical_mm):
    k = 'travel' if name.startswith('1') else 'clear' if name.startswith('2') else 'recut' if name.startswith('3') else 'content'
    return FILE_OVERHEAD_S + length_physical_mm / EFF_MM_S[k]


def _minutes(spec):
    return [est_seconds(nm, sz.row_len(rws) * sz.SCALE) / 60.0 for nm, spd, rws, note in spec]


# ------------------------------------------------------------------ the entry point
def _build_turn_inner(zone_name, kind, name, face_path, interests_strokes, start_file, clear_dir, out_dir, world=None, seed=5, _name_h=22.0, allow_cartoon=True, holiday='thanksgiving', turn=None, centre_art=None, skip_clear=False):
    """Build one turn into out_dir (created; old .thr/.json/.png in it are removed).  Returns the manifest dict (also written to
    out_dir/manifest.json) with extra keys: 'dir', 'file_paths', 'last_file', 'progress' (files + knots), 'has_face', 'pictures',
    'lettered_name', 'world' (numpy array for the next call), 'zone_layer' (dense mm paths for previews)."""
    geo = zone_geometry(zone_name)
    if kind not in ('draw', 'clear'):
        raise ValueError(kind)
    if clear_dir not in ('in', 'out'):
        raise ValueError(clear_dir)
    _N[0] += 1
    nl0 = u.NAME_LIFT
    u.NAME_LIFT = NAME_LIFT_MM if geo['kind'] == 'slice' else nl0      # (the centre name sits close to its neighbours: keep 8 there)
    _CTX['holiday'], _CTX['turn'], _CTX['centre_art'] = holiday, turn, centre_art
    del _PENDING_ARCS[:]
    _CTX.pop('centre', None)
    _CTX.pop('lay', None)
    tok = 'g:%d' % _N[0]
    u._FACE.clear(); u._ICON.clear()
    lettered = letter_name(name) if kind == 'draw' else 'X'
    pics = []
    if kind == 'draw':
        for st in (interests_strokes or []):
            if len(pics) >= 3:
                break
            if _clean(st) and sum(len(s) for s in _clean(st)) >= 2 and np.ptp(np.vstack(_clean(st)), axis=0).max() > 1e-3:
                pics.append(st)
    face = None
    if kind == 'draw':
        if face_path and _clean(face_path):
            face = ('strokes', face_path)
        elif allow_cartoon and lettered in CARTOONS and name and name.strip().upper() == lettered:
            face = ('cartoon', CARTOONS[lettered])
    REG[tok] = dict(face=face, pics=pics)
    if world is None:
        world = u.load_xy(sz.REV3)
    out_dir = os.path.abspath(out_dir)
    sw = dict(slug=os.path.basename(out_dir), kind=geo['kind'], ring=geo['ring'], a=geo['a'], old='-', person=tok, name=lettered, dir=clear_dir, turn=0)
    sw['skip_clear'] = bool(skip_clear)
    last_err = None
    try:
        for h in (_name_h, 18.0, 15.0, 12.0):
            try:
                if h != 22.0:
                    lettered = lettered[:max(4, int(len(lettered) * 22.0 / h * 0.8))] if h < 22.0 and len(lettered) > 8 else lettered
                    sw['name'] = lettered
                summ, outp, spec, run, zone, new_world = _do_swap(sw, start_file, world, os.path.dirname(out_dir), seed, h)
                break
            except (RuntimeError, ValueError, SystemExit, ZeroDivisionError, AssertionError) as e:   # e.g. no room for a long name
                last_err = e
        else:
            raise RuntimeError('could not lay out this turn: %r' % (last_err,))
    finally:
        REG.pop(tok, None)
        u.NAME_LIFT = nl0
    names = [s[0] for s in spec]
    zpoly = u.zone_poly(zone if geo['kind'] == 'slice' else dict(kind='centre'))
    if kind == 'clear':
        for s in list(spec):
            if s[0].startswith('4'):
                spec.remove(s)
                os.remove(os.path.join(out_dir, s[0]))
        summ['files'] = [m for m in summ['files'] if not m['file'].startswith('4')]
        summ['total_minutes'] = round(sum(m['minutes'] for m in summ['files']), 1)
        summ['kind'] = 'clear'
        summ['new'] = None
        for k in ('gap_ratio', 'sizes'):
            summ[k] = None
        summ['end_row'] = [float(spec[-1][2][-1][0]), float(spec[-1][2][-1][1])]
        summ['checks'] = {k: v for k, v in summ['checks'].items() if not (k.startswith('content') or k.startswith('picture') or k.startswith('overlap') or k.startswith('closest'))}
        summ['checks']['overlap_violations'] = 0
        summ['checks']['touched_outside_zone_and_boundary_lines'] = int(summ['checks']['clear_points_outside_zone'] + (summ['checks']['travel_max_distance_from_frame_line_mm'] > 0.8) +
                                                                       (summ['checks']['recut_max_distance_from_zone_boundary_mm'] > 0.8))
        class _Empty: ev = []; items = []
        run = _Empty()
        new_world = sz.update_world(world, zpoly, run, sw)
    else:
        summ['kind'] = 'draw'
    has_pics = kind == 'draw' and len(pics) > 0
    fnames, knots = progress_knots(spec, run, kind, kind == 'draw' and face is not None, has_pics)
    pics_used = (zone.get('pictures_used', len(pics)) if geo['kind'] == 'slice' else len(_CTX.get('centre', {}).get('holiday', []))) if kind == 'draw' else 0
    summ['holiday_pictures'] = [list(x) for x in _CTX.get('centre', {}).get('holiday', [])] if geo['kind'] == 'centre' and kind == 'draw' else []
    summ['centre_best_face_mm'] = round(_CTX['centre']['best_hh'] * sz.SCALE) if geo['kind'] == 'centre' and kind == 'draw' and 'centre' in _CTX else None
    cons = [(float(np.hypot(*np.diff(pl, axis=0).T).sum()) * sz.SCALE, k) for k, pl in run.ev if k in ('stem', 'bridge')]
    summ['longest_connector_mm'] = round(max(cons)[0], 1) if cons else 0.0
    summ['longest_connector_kind'] = max(cons)[1] if cons else None
    summ['orientation_check'] = orientation_check(zone, geo) if (kind == 'draw' and geo['kind'] == 'slice' and 'lay' in _CTX) else []
    summ['dir'] = out_dir
    summ['face_height_physical_mm'] = None if kind == 'clear' or not summ['sizes'] else round(float(summ['sizes'].get('face_mm', 0)) * sz.SCALE, 0)
    summ['pictures_used'] = pics_used
    summ['est_seconds'] = {n: round(est_seconds(n, m['length_physical_mm']), 1) for n, m in zip(fnames, [m for m in summ['files']])}
    summ['est_total_seconds'] = round(sum(summ['est_seconds'].values()), 1)
    summ['file_paths'] = [os.path.join(out_dir, n) for n in fnames]
    summ['last_file'] = summ['file_paths'][-1]
    summ['progress'] = dict(files=fnames, knots=[[round(a, 4), round(b, 2)] for a, b in knots])
    summ['has_face'] = bool(kind == 'draw' and face is not None)
    summ['face_source'] = None if not summ['has_face'] else face[0]
    summ['pictures'] = pics_used
    summ['lettered_name'] = lettered if kind == 'draw' else None
    summ['zone_name'] = zone_name
    summ['clear_dir'] = sw.get('dir_used') or clear_dir      # the centre falls back to an outward clear when it has no face to leave by
    lines = [sz.dense_polar_path([s], s[0]) for s in spec if s[0][0] in '13']
    layer = [sz.dens(pl) for k, pl in run.ev if k in ('name', 'join', 'face', 'icon', 'bridge', 'stem', 'retrace', 'frame')] if kind == 'draw' else []
    json.dump({k: v for k, v in summ.items()}, open(os.path.join(out_dir, 'manifest.json'), 'w'), indent=1)
    summ['world'] = new_world
    summ['zone_layer'] = dict(lines=lines, content=layer, geo=geo, zone=zone, zone_name=zone_name)
    return summ


# ------------------------------------------------------------------ OPTIONAL, DEFAULT OFF: groove-aware face routing (2026-11-26)
# face_route=True tours the FACE (slices and centre, content and the centre's inward-clear exit, which reuses the same tour)
# with tools/face_route.face_walk instead of sand_update_plan.item_walk: strokes can be entered anywhere, the ball moves
# between strokes along anything already drawn, and hops longer than ~6 mm are a last resort.  Meant for faces from
# tools/face_small.py (parts built to touch); with the app's face_art strokes it still shortens the stray lines a lot.
# Off (the default) = byte-for-byte the old behaviour: item_walk is not touched.
def build_turn(zone_name, kind, name, face_path, interests_strokes, start_file, clear_dir, out_dir, world=None, seed=5, _name_h=22.0, allow_cartoon=True, holiday='thanksgiving', turn=None, centre_art=None, skip_clear=False, face_route=False):
    """See _build_turn_inner.  face_route: see the note above (default off)."""
    args = (zone_name, kind, name, face_path, interests_strokes, start_file, clear_dir, out_dir)
    kw = dict(world=world, seed=seed, _name_h=_name_h, allow_cartoon=allow_cartoon, holiday=holiday, turn=turn, centre_art=centre_art,
              skip_clear=skip_clear)
    if not face_route:
        return _build_turn_inner(*args, **kw)
    import face_route as fr
    orig = u.item_walk

    def walk(strokes, entry, kind_):
        return fr.face_walk(strokes, entry, kind_) if kind_ == 'face' else orig(strokes, entry, kind_)
    u.item_walk = walk
    try:
        return _build_turn_inner(*args, **kw)
    finally:
        u.item_walk = orig


def orientation_check(zone, geo):
    """Per item of a slice: angle between the item's 'down' and the outward radial direction at its position (must be <= 15 deg) and, for
    the face, the distance from its nearest point to the outer arc (must be ~0)."""
    items, lay = _CTX['lay']
    out = []
    for it, pz in zip(items, lay):
        if it['kind'] == 'name':
            out.append(dict(item='name', angle_deg=0.0, note='letters follow the outer arc'))
            continue
        c = np.array(pz['poly'].centroid.coords[0])
        rhat = c / math.hypot(*c)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float((-pz['u']) @ rhat)))))
        d = dict(item=it['kind'], angle_deg=round(ang, 1))
        if it['kind'] == 'face':
            w = u.world_strokes(pz['var']['strokes'], pz['org'], pz['u'])
            rr = np.hypot(*np.vstack(w).T)
            d['distance_to_outer_arc_mm'] = round(float(zone['r_out'] - rr.max()), 2)
            d['touch_line'] = pz['L'].kind
        else:
            d['touch_line'] = pz['L'].kind
        out.append(d)
    return out


def _do_swap(sw, start_file, world, outroot, seed, name_h):
    old = u.name_item
    # the name height is the one thing layout_slice fixes at 22 mm: lower it for long names through a wrapper
    if name_h != 22.0:
        def ni(text, h):
            return old(text, name_h)
        u.name_item = ni
    try:
        return sz.do_swap(0, sw, start_file, world, outroot, seed=seed)
    finally:
        u.name_item = old


def preview_image(layers_by_zone_in_order, extra_lines=None, size=1400, outpx=1000):
    """Sand simulation: revision 3 plus every turn's travel/recut lines, then each swapped zone's own content on flat sand.
    layers_by_zone_in_order: list of zone_layer dicts (later ones paste over earlier ones in the same zone)."""
    from PIL import Image, ImageDraw
    base = u.load_xy(sz.REV3)
    lines = [np.vstack(L['lines']) for L in layers_by_zone_in_order if len(L['lines'])]
    imA = u.render_sim(np.vstack([base] + lines), size, outpx).convert('RGB')
    latest = {}
    for L in layers_by_zone_in_order:
        latest[L['zone_name'] if 'zone_name' in L else str(L['geo'])] = L
    for L in latest.values():
        pts = [np.asarray(p) for p in L['content']] or [np.array([[0.0, -1e3], [0.0, -1e3 - 1]])]
        imB = u.render_sim(np.vstack(pts), size, outpx).convert('RGB')
        m = Image.new('L', (outpx, outpx), 0)
        zone = L['zone']
        ImageDraw.Draw(m).polygon(sz.sector_mask_poly(zone, L['geo'], outpx), fill=255)
        imA.paste(imB, (0, 0), m)
    return imA


def write_centre_art(path):
    """The Thanksgiving set in the app's register format: 0..1, y down, upright, each fitted to ~90% of the unit square."""
    out = []
    for key, fn in sorted(holiday_art().items()):
        arrs = [np.asarray(a, float) for a in fn()]
        allp = np.vstack(arrs)
        lo, hi = allp.min(0), allp.max(0)
        sc = 0.9 / float(max(hi - lo))
        c = (lo + hi) / 2
        st = []
        for a in _simplify([(a - c) * sc for a in arrs], tol=0.002):
            st.append([[round(0.5 + x, 4), round(0.5 - y, 4)] for x, y in a])
        out.append(dict(key=key.replace(' ', '-'), label=key.title(), strokes=st))
    json.dump(dict(items=out), open(path, 'w'))
    return out


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='build one turn offline')
    ap.add_argument('zone'); ap.add_argument('name'); ap.add_argument('out')
    ap.add_argument('--kind', default='draw'); ap.add_argument('--dir', default='in')
    ap.add_argument('--start', default=os.path.join(sz.REV3, '19-frame-lines.thr'))
    a = ap.parse_args()
    s = build_turn(a.zone, a.kind, a.name, None, [], a.start, None, a.out) if False else build_turn(a.zone, a.kind, a.name, None, [], a.start, a.dir, a.out)
    print(json.dumps({k: v for k, v in s.items() if k not in ('world', 'zone_layer')}, indent=1)[:3000])
