#!/usr/bin/env python3
"""Relief showcase (v2): our own velociraptor (patterns/creatures/make_creatures.py shapes) as bas-relief by
negative space, simulated with tools/sand_relief_sim.py. SIMULATION ONLY; never contacts the table.

    python3 tools/relief_showcase.py [--table mini|big] [--out captures/relief-study/v2]

Writes raptor_relief_<table>.thr / .png, raptor_relief_<table>_plan.png and raptor_thin_<table>.png (today's
thin-line raptor.thr in the same simulator) and a JSON report.
"""
import argparse, json, math, os, sys, time
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, ROOT + '/patterns/creatures'); sys.path.insert(0, ROOT + '/patterns/dog')
import sand_relief_path as rp
import sand_relief_sim as sim
import thrcommon as tc

OUT = ROOT + '/captures/relief-study/v2'
TABLE = dict(mini=dict(r=114.0, res=0.25), big=dict(r=420.0, res=0.4))
LOOK = dict(tint=(0.90, 0.95, 1.0))          # the maker's photos: white LEDs, slightly cool


def run_plan(cv, plan, name, table, erase=0.012, title='relief', save_overlay=True, out=OUT, light='ring', **rk):
    """plan -> .thr, timing, simulated sand picture. Returns (report dict, PIL image)."""
    tr, near = rp.to_thr_pts(plan['pts_xy'], cv.R)
    rp.write_thr(os.path.join(out, name + '.thr'), tr, title)
    rep = dict(plan['report'])
    rep['points'] = len(tr)
    rep['points_near_centre'] = near
    rep['path_m'] = round(rp.path_len_m(tr, cv.R), 2)
    if table == 'mini':
        rep['mini_minutes'] = round(rp.mini_minutes(tr), 1)
    if save_overlay:
        rp.overlay(cv, plan, os.path.join(out, name + '_plan.png'), 900)
    t0 = time.time()
    T = sim.Table(table)
    if erase:
        T.erase(erase * 114.0 / cv.R)       # erase pitch given as a fraction of the Mini radius: same mm on both tables
    T.run(tr)
    im = T.render(light=light, out_px=1100, **dict(LOOK, **rk))
    im.save(os.path.join(out, name + '.png'))
    rep['sim_seconds'] = round(time.time() - t0, 1)
    json.dump(rep, open(os.path.join(out, name + '.json'), 'w'), indent=1, default=str)
    return rep, im


# ---------------------------------------------------------------- the T. rex (generic make_creatures design)
def trex_plan(cv, bg_pitch=0.9, scale=1.12, shift=(4.0, -2.0), limb=2.6, ribs=True):
    """T. rex from make_creatures.trex(): regions rasterised in their priority order, strokes fattened to `limb`
    grooves, holes (the eye) become a small closed groove, part edges inside the body become detail lines."""
    import make_creatures as mc
    from make_dog import spline
    p = mc.trex()
    R, g = cv.R, cv.g

    def T(pts):
        pts = np.asarray(pts, float)
        return np.c_[(pts[:, 0] - 300) / 290 * R * scale + shift[0] * R / 114, -(pts[:, 1] - 300) / 290 * R * scale + shift[1] * R / 114]
    parts, holes = [], []
    for rg in p['regions']:
        if rg.get('name') == 'pupil':
            continue
        m = np.zeros((cv.N, cv.N), bool)
        if rg['poly']:
            m |= cv.fill_polys([T(rg['poly'])])
        for st, w in rg.get('strokes', []):
            m |= cv.stroke(T(spline(list(st), 2) if len(st) > 2 else st), max(limb * g, w))
        for h in rg.get('holes', []):
            holes.append(T(h))
        parts.append((rg.get('name', '?'), m))
    subject = np.zeros((cv.N, cv.N), bool)
    for _, m in parts:
        subject |= m
    subject &= cv.disc()
    subject = cv.simplify(subject)
    details = part_details(cv, parts, subject)
    for h in holes[:1]:
        c = h.mean(0); t = np.linspace(0, 2 * math.pi, 40, endpoint=False)
        details.append(('closed', np.c_[c[0] + 0.5 * g * np.cos(t), c[1] + 0.5 * g * np.sin(t)]))
    gy = -0.72 * R
    fills = [rp.Fill('arcs', bg_pitch * g, mask=cv.Y > gy, focus=(0.15 * R, 0.25 * R), name='sky'),
             rp.Fill('lines', 0.85 * g, mask=cv.Y <= gy, angle=0.0, name='ground')]
    rib = []
    if ribs:      # fine ribbing along the back and tail: a band inside the top edge of the body
        body = dict(parts)['body']
        din = cv.dist_in(subject)
        band = body & (din >= 0.6 * g) & (din <= 3.2 * g) & (cv.Y > -0.05 * R) & (cv.X < 0.25 * R)
        for n_, m in parts:
            if n_ != 'body':
                band &= ~(cv.dist_in(~m) < 1.0 * g)
        rib.append(rp.Fill('offset', 0.95 * g, mask=band, name='back ribs'))
    return cv.plan(subject, fills, details=details, ribs=rib)


# ---------------------------------------------------------------- the raptor
def raptor_parts(cv, scale=1.08, shift=(6.0, 4.0), limb=3.0):
    """Masks of the raptor's parts (front first), from make_creatures' design, flipped to face left, scaled to fill
    ~80% of the tray, limbs fattened to `limb` groove widths. Returns list of (name, mask), plus a mm transform."""
    import make_creatures as mc
    from make_dog import spline
    R = cv.R

    def T(pts):
        pts = np.asarray(pts, float)
        x = 600 - pts[:, 0]                                            # designed facing right, drawn facing left
        return np.c_[(x - 300) / 290 * R * scale + shift[0] * R / 114, -(pts[:, 1] - 300) / 290 * R * scale + shift[1] * R / 114]
    E = (426, 182)
    head_top = spline([(340, 246), (358, 218), (372, 194), (390, 172), (420, 156), (470, 156), (520, 162), (550, 172),
                       (556, 184)], 3)
    head_under = spline([(556, 190), (540, 206), (520, 226), (480, 232), (440, 234), (418, 246), (406, 268), (390, 300),
                         (350, 300)], 3)
    head = mc.cs(head_top + head_under)
    body = mc.cs([(226, 236), (280, 232), (330, 240), (366, 262), (382, 296), (360, 326), (300, 334), (250, 324), (226, 300)])
    tail = [(-60, 128), (60, 162), (150, 196), (232, 226), (244, 312), (150, 252), (60, 222), (-60, 206)]
    front_thigh = mc.cs([(246, 276), (296, 276), (326, 312), (334, 350), (312, 366), (274, 342), (246, 316)])
    back_thigh = mc.cs([(218, 284), (264, 292), (268, 340), (250, 372), (226, 368), (212, 324)])
    front_leg = [((320, 356), (300, 424)), ((300, 424), (334, 490)), ((334, 490), (392, 492))]
    sickle = [((338, 488), (342, 456), (362, 436), (392, 440))]
    back_leg = [((242, 364), (200, 400)), ((200, 400), (164, 440)), ((164, 440), (140, 470)), ((164, 440), (178, 474))]
    arm = [((360, 296), (390, 336)), ((390, 336), (438, 328)), ((438, 328), (470, 340), (478, 362)),
           ((438, 328), (452, 350), (452, 374))]
    w = limb * cv.g

    def strokes(lst, width):
        m = np.zeros((cv.N, cv.N), bool)
        for s in lst:
            pts = T(spline(list(s), 2) if len(s) > 2 else s)
            m |= cv.stroke(pts, width)
        return m
    parts = [('front leg', strokes(front_leg, w) | strokes(sickle, 0.9 * w)),
             ('arm', strokes(arm, 0.95 * w)),
             ('front thigh', cv.fill_polys([T(front_thigh)])),
             ('head', cv.fill_polys([T(head)])),
             ('body', cv.fill_polys([T(body)])),
             ('tail', cv.fill_polys([T(tail)])),
             ('back thigh', cv.fill_polys([T(back_thigh)])),
             ('back leg', strokes(back_leg, w))]
    return parts, T, dict(eye=T([E])[0], gape=T([(552, 188), (520, 200), (480, 206), (446, 208)]),
                          tail_axis=T([(232, 268), (-60, 167)]))


def part_details(cv, parts, subject, min_in=0.9, gap_front=0.6, only=None):
    """Interior detail lines = each part's outline where it lies inside the picture (min_in grooves from its edge) and
    is not hidden by a part in front of it."""
    g = cv.g
    din = cv.dist_in(subject)
    front = np.zeros_like(subject)
    out = []
    for name, m in parts:
        if only is not None and name not in only:
            front |= m
            continue
        for loop in cv.loops(m, sigma=1.5, step=0.5, min_len=2 * g):
            px = np.clip(cv.to_px(loop).astype(int), 0, cv.N - 1)
            ok = (din[px[:, 1], px[:, 0]] >= min_in * g)
            dfront = cv.dist_in(front)[px[:, 1], px[:, 0]] if front.any() else np.zeros(len(loop))
            ok &= dfront < gap_front * g
            # runs of ok along the closed loop
            if ok.all():
                out.append(('closed', loop)); continue
            k = int(np.argmin(ok))
            ok = np.roll(ok, -k); L = np.roll(loop, -k, axis=0)
            i = 0
            while i < len(ok):
                if ok[i]:
                    j = i
                    while j < len(ok) and ok[j]:
                        j += 1
                    if (j - i) * 0.5 >= 1.5 * g:
                        out.append(L[i:j])
                    i = j
                else:
                    i += 1
        front |= m
    return out


def raptor_plan(cv, ribs=True, bg_pitch=1.3, ground=True, focus=None, fatten=1.3):
    g = cv.g
    parts, T, ref = raptor_parts(cv)
    subject = np.zeros((cv.N, cv.N), bool)
    for _, m in parts:
        subject |= m
    subject = cv2.dilate(subject.astype(np.uint8), cv.disk_k(fatten * cv.g)).astype(bool)   # fatten thin parts
    subject &= cv.disc()
    subject = cv.simplify(subject)
    details = part_details(cv, parts, subject, only=('front thigh', 'back thigh'))
    details.append(ref['gape'])
    e = ref['eye']
    t = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    details.append(('closed', np.c_[e[0] + 0.45 * g * np.cos(t), e[1] + 0.45 * g * np.sin(t)]))
    R = cv.R
    fills = []
    gy = -0.70 * R
    if ground:
        fills.append(rp.Fill('arcs', bg_pitch * g, mask=cv.Y > gy, focus=focus or (0.10 * R, 0.05 * R), name='sky'))
        fills.append(rp.Fill('lines', 0.85 * g, mask=cv.Y <= gy, angle=0.0, name='ground', phase=0.5))
    else:
        fills.append(rp.Fill('arcs', bg_pitch * g, focus=focus or (0.10 * R, 0.05 * R), name='sky'))
    rib = []
    if ribs:
        _, tail = parts[5]
        a, b = ref['tail_axis']
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        others = np.zeros_like(subject)
        for n_, m in parts:
            if n_ != 'tail':
                others |= m
        din = cv.dist_in(subject)
        tm = tail & (din >= 0.6 * g) & ~(cv.dist_in(~others) < 1.0 * g)
        rib.append(rp.Fill('lines', 1.05 * g, mask=tm, angle=ang, name='tail ribs', phase=0.5))
    plan = cv.plan(subject, fills, details=details, ribs=rib)
    return plan


# ---------------------------------------------------------------- raptor v2: redrawn from simple fat shapes
def raptor2_plan(cv, bg_pitch=1.3):
    """Our velociraptor pose (after make_creatures.raptor: facing left, long stiff tail to the rim, S neck, long
    snout, forward arm, running legs) redrawn from simple shapes in Mini mm and scaled to the table. Every part is
    at least 2.5 grooves wide; the near leg, arm and thigh are separate parts whose edges become detail lines; the
    tail is ribbed along its length; eye, jaw line and a belly line are interior grooves."""
    from make_dog import spline
    g = cv.g
    k = cv.R / 114.0

    def P(pts):
        return np.asarray(pts, float) * k

    def blob(pts):
        return cv.fill_polys([P(spline([tuple(q) for q in pts], 1.0, closed=True))])

    def limb(pts, w):
        return cv.stroke(P(spline([tuple(q) for q in pts], 1.0) if len(pts) > 2 else pts), w * k)
    head = blob([(-100, 50), (-92, 60), (-72, 70), (-52, 72), (-40, 64), (-42, 48), (-60, 42), (-84, 40)])
    neck = limb([(-46, 56), (-38, 40), (-34, 22), (-24, 8)], 19)
    body = blob([(-34, 14), (-10, 24), (20, 26), (44, 22), (54, 8), (40, -8), (10, -16), (-20, -12), (-36, 0)])
    tail = blob([(36, 26), (70, 38), (100, 48), (118, 54), (118, 36), (98, 26), (70, 10), (46, -8)])
    arm = limb([(-28, 0), (-46, -12), (-62, -14)], 12) | limb([(-62, -14), (-72, -8)], 9) | limb([(-62, -14), (-70, -24)], 9)
    near_thigh = blob([(-4, 10), (18, 12), (30, -8), (24, -30), (6, -36), (-8, -20)])
    near_leg = limb([(16, -30), (2, -52), (-8, -66)], 13) | limb([(-6, -68), (-34, -72)], 12)
    far_leg = limb([(40, -6), (48, -34), (52, -58)], 13) | limb([(52, -62), (30, -72)], 12)
    parts = [('arm', arm), ('near thigh', near_thigh), ('near leg', near_leg), ('head', head), ('neck', neck),
             ('body', body), ('tail', tail), ('far leg', far_leg)]
    subject = np.zeros((cv.N, cv.N), bool)
    for _, m in parts:
        subject |= m
    subject &= cv.disc()
    subject = cv.simplify(subject)
    details = part_details(cv, parts, subject, only=('arm', 'near thigh', 'near leg', 'far leg'))
    t = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    e = P([(-60, 60)])[0]
    details.append(('closed', np.c_[e[0] + 0.5 * g * np.cos(t), e[1] + 0.5 * g * np.sin(t)]))
    details.append(P(spline([(-101, 49), (-84, 49), (-66, 50)], 1.0)))              # jaw line from the snout tip
    details.append(P(spline([(-30, -8), (-8, -14), (8, -16)], 1.0)))                # belly line
    details.append(P(spline([(-40, 46), (-30, 30), (-22, 18)], 1.0)))               # front of the neck
    a, b = P([(44, 10)])[0], P([(112, 44)])[0]
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    din = cv.dist_in(subject)
    others = np.zeros_like(subject)
    for n_, m in parts:
        if n_ not in ('tail', 'body'):
            others |= m
    tm = (tail | (body & (cv.X > 30 * k) if cv.R < 200 else tail)) & (din >= 0.5 * g) & ~(cv.dist_in(~others) < 0.8 * g)
    rib = [rp.Fill('lines', 0.95 * g, mask=tm, angle=ang, name='tail ribs', phase=0.5)]
    gy = -0.66 * cv.R
    fills = [rp.Fill('arcs', bg_pitch * g, mask=cv.Y > gy, focus=(0.05 * cv.R, 0.12 * cv.R), name='sky'),
             rp.Fill('lines', 0.85 * g, mask=cv.Y <= gy, angle=0.0, name='ground')]
    return cv.plan(subject, fills, details=details, ribs=rib)


def trex_rich_plan(cv, bg_pitch=1.3, scale=1.12, shift=(4.0, -2.0)):
    """The T. rex with what the maker's dinosaur has and ours lacked: ribbed belly, neck and tail (three
    directions), teeth hinted as short grooves along both jaws, a thigh muscle line and knee crease, limbs at least
    3 grooves wide, ground lines."""
    import make_creatures as mc
    from make_dog import spline
    p = mc.trex()
    R, g = cv.R, cv.g

    def T(pts):
        pts = np.asarray(pts, float)
        return np.c_[(pts[:, 0] - 300) / 290 * R * scale + shift[0] * R / 114, -(pts[:, 1] - 300) / 290 * R * scale + shift[1] * R / 114]
    parts, holes = [], []
    for rg in p['regions']:
        if rg.get('name') == 'pupil':
            continue
        m = np.zeros((cv.N, cv.N), bool)
        if rg['poly']:
            m |= cv.fill_polys([T(rg['poly'])])
        for st, w in rg.get('strokes', []):
            m |= cv.stroke(T(spline(list(st), 2) if len(st) > 2 else st), 3.1 * g)
        holes += [T(h) for h in rg.get('holes', [])]
        parts.append((rg.get('name', '?'), m))
    pd = dict(parts)
    subject = np.zeros((cv.N, cv.N), bool)
    for _, m in parts:
        subject |= m
    subject = cv.simplify(subject & cv.disc())
    din = cv.dist_in(subject)
    details = part_details(cv, parts, subject)
    c = holes[0].mean(0); t = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    details.append(('closed', np.c_[c[0] + 0.55 * g * np.cos(t), c[1] + 0.55 * g * np.sin(t)]))
    details.append(T(spline([(452, 168), (476, 160), (500, 166)], 2)))                 # brow ridge over the eye
    # teeth: short grooves from each jaw edge into the head
    for (a, b, sgn) in (((556, 210), (456, 232), -1), ((458, 252), (532, 288), 1)):
        a, b = T([a])[0], T([b])[0]
        d = (b - a) / np.hypot(*(b - a)); n = np.array([-d[1], d[0]]) * sgn
        L = np.hypot(*(b - a))
        for f in np.arange(0.12, 0.95, 1.7 * g / L):
            q = a + d * f * L
            details.append(np.vstack([q - n * 0.3 * g, q + n * 1.3 * g]))
    # thigh muscle line and knee crease on the near leg
    details.append(T(spline([(236, 300), (282, 296), (318, 330), (322, 380)], 2)))
    details.append(T(spline([(276, 452), (300, 444), (322, 452)], 2)))
    gy = -0.72 * R
    fills = [rp.Fill('arcs', bg_pitch * g, mask=cv.Y > gy, focus=(0.15 * R, 0.25 * R), name='sky'),
             rp.Fill('lines', 0.85 * g, mask=cv.Y <= gy, angle=0.0, name='ground')]
    body = pd['body']
    front = np.zeros_like(subject)
    for n_, m in parts:
        if n_ != 'body':
            front |= m
    clear = ~(cv.dist_in(~front) < 0.8 * g)
    tailx = T([(150, 300)])[0][0]
    neckx = T([(372, 300)])[0][0]
    ys = cv.Y[body]
    belly_y = np.percentile(ys, 45)
    rib = [rp.Fill('lines', 0.95 * g, mask=body & clear & (din >= 0.6 * g) & (cv.X < tailx), angle=-22.0, name='tail ribs'),
           rp.Fill('lines', 0.95 * g, mask=body & clear & (din >= 0.6 * g) & (cv.X > tailx + 2 * g) & (cv.X < neckx - 2 * g)
                   & (cv.Y < belly_y), angle=-8.0, name='belly ribs')]
    return cv.plan(subject, fills, details=details, ribs=rib)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--table', default='mini', choices=['mini', 'big'])
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--no-ribs', action='store_true')
    ap.add_argument('--no-ground', action='store_true')
    ap.add_argument('--pitch', type=float, default=0.9)
    ap.add_argument('--name', default=None)
    ap.add_argument('--subject', default='raptor', choices=['raptor', 'raptor2', 'trex', 'trex_rich'])
    ap.add_argument('--thin', action='store_true', help='also simulate today\'s thin-line raptor.thr')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tb = TABLE[a.table]
    cv = rp.Canvas(tb['r'], res=tb['res'])
    t0 = time.time()
    if a.subject == 'trex_rich':
        plan = trex_rich_plan(cv, bg_pitch=a.pitch)
    elif a.subject == 'raptor2':
        plan = raptor2_plan(cv, bg_pitch=a.pitch)
    elif a.subject == 'trex':
        plan = trex_plan(cv, bg_pitch=a.pitch, ribs=not a.no_ribs)
    else:
        plan = raptor_plan(cv, ribs=not a.no_ribs, bg_pitch=a.pitch, ground=not a.no_ground)
    print('plan %.1fs' % (time.time() - t0), plan['report'], flush=True)
    name = a.name or '%s_relief_%s' % (a.subject, a.table)
    rep, _ = run_plan(cv, plan, name, a.table, out=a.out, title='relief velociraptor', erase=0.012)
    print(json.dumps({k: v for k, v in rep.items() if k not in ('links_over_subject',)}, default=str))
    print('links over raised sand:', rep['links_over_subject'])
    if a.thin:
        T = sim.Table(a.table)
        T.erase(0.035)
        T.run(tc.read_thr(ROOT + '/patterns/creatures/raptor.thr'))
        T.render(out_px=1100, **LOOK).save(os.path.join(a.out, 'raptor_thin_%s.png' % a.table))
    print('done %.1fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
