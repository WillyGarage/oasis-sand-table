#!/usr/bin/env python3
"""Our velociraptor redone as stained-glass sections (plan for tools/section_comb.py), Mini size (r 114 mm).

Our own design: the pose of patterns/creatures/make_creatures.py raptor() (S-neck, long snout, long arm with three
claws, running legs with the raised sickle claw, long straight tail out to the rim) with a fuller body. Designed
facing right on that file's 600-unit canvas, mirrored to face left (like the old drawing), 1 unit ~ 0.41 mm.
Not a trace of the maker's dinosaur. SIMULATION/PATH ONLY.

    plan = raptor_plan()           # dict for section_comb.comb()
"""
import math, os, sys
import numpy as np
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def band(pts, hw, flat=False, n=60):
    """A band along a polyline (mm) with half-widths hw (mm, one per point). Round ends unless flat."""
    P = np.array(pts, float)
    hw = np.array(hw, float)
    seg = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    t = np.linspace(0, seg[-1], n)
    Q = np.c_[np.interp(t, seg, P[:, 0]), np.interp(t, seg, P[:, 1])]
    W = np.interp(t, seg, hw)
    if flat:
        tan = np.gradient(Q, axis=0)
        tan /= np.hypot(*tan.T)[:, None]
        nr = np.c_[-tan[:, 1], tan[:, 0]]
        poly = np.vstack([Q + nr * W[:, None], (Q - nr * W[:, None])[::-1]])
        return poly.tolist()
    g = unary_union([Point(*q).buffer(w, 24) for q, w in zip(Q, W)])
    return [list(c) for c in g.exterior.coords][:-1]


def _spine_len(spine):
    P = np.array(spine, float)
    return float(np.hypot(*np.diff(P, axis=0).T).sum())


def bsec(name, spine, hw, spacing, flat=False, s_range=None, **kw):
    """band section combed with ribs across the band (spine mode). s_range=(f0, f1): fractions of the spine length -> the
    section is only that stretch of the band (consecutive pieces tile the band exactly)."""
    poly = Polygon(band(spine, hw, flat))
    d = dict(name=name, kind='subject', spacing=spacing, mode='spine', spine=[list(p) for p in spine], **kw)
    if s_range is not None:
        Lt = _spine_len(spine)
        a, b = s_range[0] * Lt, s_range[1] * Lt
        P = np.array(spine, float)
        sg = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
        def at(t):
            t = min(max(t, 0), Lt)
            i = min(np.searchsorted(sg, t, side='right') - 1, len(P) - 2)
            u = (P[i + 1] - P[i]); u = u / np.hypot(*u)
            return P[i] + u * (t - sg[i]), u
        big = 400.0
        keep = poly
        for t, side in ((a, 1), (b, -1)):
            if (side == 1 and s_range[0] <= 0) or (side == -1 and s_range[1] >= 1):
                continue
            p0, u = at(t)
            n = np.array([-u[1], u[0]])
            half = Polygon([p0 - n * big, p0 + n * big, p0 + n * big + u * side * big, p0 - n * big + u * side * big])
            keep = keep.intersection(half)
        poly = keep
        d['s_range'] = [(s_range[0] * Lt) if s_range[0] > 0 else -1e3, (s_range[1] * Lt) if s_range[1] < 1 else 1e3]
    d['poly'] = [list(c) for c in poly.exterior.coords][:-1]
    return d


def raptor_sections():
    """Our running raptor as ONE silhouette: designed as overlapping smooth bands, painter's order (earlier wins) so the
    sections share edges and tile the silhouette without gaps. Long bands (neck, tail, legs) are cut into pieces with s_range.
    Drawing order is SUBJECT_ORDER, not this list. Faces left, y up, mm."""
    S = []
    EYE = (-52.0, 71.0)
    ring = lambda c, r, n=40: [[c[0] + r * math.cos(a), c[1] + r * math.sin(a)] for a in np.linspace(0, 2 * math.pi, n, endpoint=False)]
    # head: eye, jaw, snout, skull
    S.append(dict(name='eye', kind='subject', poly=ring(EYE, 6.5), holes=[ring(EYE, 1.2, 12)], spacing=1.3, mode='rings', center=list(EYE), shrink=0.5))
    S.append(bsec('jaw', [(-54, 52), (-76, 50), (-94, 53)], [8, 5.5, 3.2], 1.3))
    S.append(bsec('snout', [(-50, 68), (-72, 65), (-96, 56)], [14, 10.5, 5], 1.2))
    S.append(bsec('skull', [(-34, 72), (-50, 68)], [14, 12.5], 1.2))
    # neck: one long S band, two pieces
    neck = [(-40, 66), (-37, 48), (-28, 30), (-14, 12), (-2, 0)]
    nh = [10, 9, 10, 12, 14]
    S.append(bsec('neck_a', neck, nh, 1.4, s_range=(0, 0.45)))
    S.append(bsec('neck_b', neck, nh, 1.6, s_range=(0.45, 1)))
    # arm and fingers
    S.append(bsec('upper_arm', [(-24, 10), (-38, -4)], [8.5, 6.5], 1.5))
    S.append(bsec('forearm', [(-38, -4), (-58, -2)], [6.5, 4.5], 1.4))
    for i, e in enumerate([(-78, -13), (-82, -4), (-77, 6)]):
        S.append(bsec('finger%d' % (i + 1), [(-56, -2), e], [3.6, 1.8], 1.1))
    # torso (one big section, combed diagonally)
    t = np.linspace(0, 2 * math.pi, 80, endpoint=False)
    el = np.c_[41 * np.cos(t), 22 * np.sin(t)]
    c, s_ = math.cos(math.radians(18)), math.sin(math.radians(18))
    el = el @ np.array([[c, s_], [-s_, c]]) + [0, -2]
    S.append(dict(name='torso', kind='subject', poly=el.tolist(), spacing=2.0, mode='angle', angle=55))
    # legs: thigh+shin one long tapering band (2 pieces), foot band, 3 toes
    for side, (leg, lh, foot, fh, toes) in dict(
            front=([(-10, -8), (-22, -30), (-32, -52), (-32, -70)], [17, 12, 7, 6],
                   [(-32, -72), (-50, -76), (-66, -78)], [6.5, 5, 4],
                   [[(-62, -77), (-82, -69)], [(-64, -79), (-87, -80)], [(-62, -81), (-81, -88)]]),
            back=([(18, -10), (32, -30), (40, -52), (38, -68)], [16, 11, 6.5, 5.5],
                  [(38, -70), (56, -75), (70, -77)], [6.5, 5, 4],
                  [[(66, -76), (86, -68)], [(68, -78), (91, -79)], [(66, -80), (85, -87)]])).items():
        S.append(bsec(side + '_thigh', leg, lh, 2.3, s_range=(0, 0.4)))
        S.append(bsec(side + '_shin', leg, lh, 1.7, s_range=(0.4, 1)))
        S.append(bsec(side + '_foot', foot, fh, 1.5))
        for i, tp in enumerate(toes):
            S.append(bsec('%s_toe%d' % (side, i + 1), tp, [3.8, 1.8], 1.1))
    # tail: one long curved band, three pieces, ribs fan round the curve
    tail = [(26, -2), (54, -8), (80, -2), (98, 16), (108, 38), (106, 58)]
    th = [16, 14, 11, 8, 5.5, 3.5]
    S.append(bsec('tail_a', tail, th, 1.7, s_range=(0, 0.33)))
    S.append(bsec('tail_b', tail, th, 1.6, s_range=(0.33, 0.66)))
    S.append(bsec('tail_c', tail, th, 1.5, s_range=(0.66, 1)))
    return S


def background_sections():
    """Few, large sections tiling everything outside the animal: a halo of arcs about the head, long slanted lines above the
    tail, big flat arcs below it, horizontal ground. (Design coordinates; raptor_plan applies the same scale/shift as the animal.)"""
    B = []
    tail_top = [[106, 58], [98, 16], [80, -2], [54, -8], [26, -2]]
    B.append(dict(name='bg_halo', kind='background', spacing=5.0, mode='rings', center=[-52, 71],
                  poly=[[-220, -92], [-24, -92], [-24, -30], [8, -22], [14, 24], [-6, 220], [-220, 220]]))
    B.append(dict(name='bg_sky', kind='background', spacing=5.0, mode='angle', angle=14.0,
                  poly=[[-6, 220], [220, 220], [220, 70]] + tail_top + [[14, 24]]))
    B.append(dict(name='bg_under', kind='background', spacing=5.0, mode='rings', center=[10, -210],
                  poly=[[-24, -92], [220, -92], [220, 70]] + tail_top + [[14, 24], [8, -22], [-24, -30]]))
    B.append(dict(name='bg_ground', kind='background', spacing=5.0, mode='angle', angle=0.0,
                  poly=[[-220, -220], [220, -220], [220, -92], [-220, -92]]))
    return B


def xf(secs, f=0.9, dx=3.0, dy=7.0):
    """scale about the origin and shift all geometry (mm); strokes spacing unchanged"""
    T = lambda pts: [[x * f + dx, y * f + dy] for x, y in pts]
    out = []
    for d in secs:
        d = dict(d)
        d['poly'] = T(d['poly'])
        if 'holes' in d: d['holes'] = [T(h) for h in d['holes']]
        if 'spine' in d: d['spine'] = T(d['spine'])
        if 'center' in d: d['center'] = T([d['center']])[0]
        if 's_range' in d: d['s_range'] = [v * f if abs(v) < 900 else v for v in d['s_range']]
        out.append(d)
    return out


def raptor_plan(bg=True):
    secs = xf(raptor_sections()) + (xf(background_sections()) if bg else [])
    return dict(r_work=114.0, shrink=0.9, bg_gap=0.9, bg_shrink=0.8, sections=secs)


SUBJECT_ORDER = ['eye', 'skull', 'snout', 'jaw', 'neck_a', 'neck_b', 'upper_arm', 'forearm', 'finger1', 'finger2', 'finger3',
                 'torso',
                 'front_thigh', 'front_shin', 'front_foot', 'front_toe1', 'front_toe2', 'front_toe3',
                 'back_thigh', 'back_shin', 'back_foot', 'back_toe1', 'back_toe2', 'back_toe3',
                 'tail_a', 'tail_b', 'tail_c']


if __name__ == '__main__':
    import section_comb as sc
    plan = raptor_plan()
    res = sc.comb(plan, order=[x['name'] for x in background_sections()] + SUBJECT_ORDER)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'captures/relief-study/v3/sections')
    rep, tr = sc.save(res, plan, out, 'raptor_v2')
    import json; print({k: v for k, v in rep.items() if k not in ('per_section', 'travel_over_finished_where')})
    print({k: v for k, v in rep.items() if k != 'per_section'})
