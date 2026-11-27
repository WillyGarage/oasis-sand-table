#!/usr/bin/env python3
"""compose - several pictures on one canvas, each in its own sub-disc, drawn as one continuous line; and replace(k),
which redraws an updated composition on a clean table.

  compose.py                 -> captures/variants/compose_two.thr, compose_replace.thr, the previews
                                captures/morning/compose_two.jpg, compose_replace.jpg, compose_route.jpg

  from compose import place, compose, replace
  pics = [place(coarse.phage, 0.48), place(coarse.pumpkin, 0.48)]
  pts, info = compose(pics)                 # erase the background finely, then draw every picture
  pts2, info2 = replace(pics, 1, place(coarse.guitar, 0.48))

LAYOUT. A picture is built on its own 600 x 600 canvas by make_creatures.build (rho_own 1 = its own rim). It is
placed in a sub-disc of radius r (table radii), upright (canvas up = table up, the table's bottom at theta = -pi/2),
with the sub-disc tangent to the real rim exactly at the picture's own entry point: the sub-disc centre is
(1 - r) * (direction of the entry). So the picture enters from the real rim with no extra line. Every region's fill
pitch is multiplied by 1/r, so fill lines stay 0.057 of the TABLE radius apart (the groove is 0.042 wide); feature
sizes come from the coarse variants in patterns/compose/coarse.py (the originals have no scale parameter).

ROUTE (compose). Pictures are ordered round the rim by entry angle, starting after the biggest angular gap, so the
rim runs between them cover less than a full turn and never pass the gap. The first picture is drawn REVERSED (its
inside end -> its rim entry), the middle ones go in and come back out the way they came (build with no 'final'),
the last one is drawn forward (rim entry -> its inside end). Consecutive entries are joined by a run along the rim
(rho = 1). Before that, bg_erase's ring/cell planner (copied as plan_regions) erases everything no picture
grooves, from the rim inward at pitch 0.02, then travels to the first picture's inside end only through sand a
picture will groove over, or along the rim. The pictures' silhouettes are TIGHT (their own grooves plus pockets under
1.5 grooves across), not bg_erase's closed-and-filled outline: open spaces a picture encloses (between the phage's
legs, the notches between pumpkin lobes) are fine-erased too, and the erase runs two grooves under each picture's
outer lines, so the arc ends and their ridges are redrawn over (found in the honest simulator 2026-11-20: at one
groove the ends left a row of dots round the pumpkin; bg_erase's coarse inside and islands passes made the phage's
legs read as solid blocks). Both passes still exist as options (inside_pitch, islands), off by default.

REPLACE(k). Draw an ordinary full-table fine spiral, then redraw the entire composition with the new subject in
place k. The other subjects keep their shapes and positions. Drawing segments follow the rim between subjects.

Drawing moves are split to under 0.02 of the radius and 0.05 rad (bg_erase.densify), theta is cumulative, art stays in
[0.02, 1] and the whole-table spiral reaches zero. Files over 12000 points: the erase part is re-split with bg_erase's thin rule; if still over, the file is
written as _1.thr, _2.thr ... to play back to back.

Play the replacement path forward (/thr then /play): the clear starts at the centre and ends on the rim.
Written 2026-11-20 (offline; nothing sent to the table)."""
import math, os, sys
import numpy as np
from scipy.sparse.csgraph import dijkstra

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(HERE + '/..')
sys.path.insert(0, HERE); sys.path.insert(0, ROOT + '/patterns/creatures'); sys.path.insert(0, ROOT + '/patterns/compose')
import thrcommon as tc
import bg_erase as be
from bg_erase import (GR, DISC, NG, GROOVE, Path, build_cells, sweep_cell, travel_graph, tnode, route, emit_travel,
                      paint_line, dilate, erode, opening, densify, GX, GY)
import make_creatures as mc

RHO_MIN = 0.02
PITCH_TABLE = 0.057          # fill pitch in table radii
MARGIN = 0.03                # minimum clearance between picture edges is twice this


# ---------------------------------------------------------------- placing one picture
def xy_to_polar(xy, th0=None):
    """xy polyline (table radii) -> (theta, rho) with continuous theta, densified in xy first (0.01) so straight
    lines stay straight, then by bg_erase.densify"""
    xy = np.asarray(xy, float)
    D = [xy[0]]
    for q in xy[1:]:
        a = D[-1]; n = max(1, int(math.ceil(math.hypot(*(q - a)) / 0.01)))
        for i in range(1, n + 1): D.append(a + (q - a) * i / n)
    D = np.array(D)
    th = np.unwrap(np.arctan2(D[:, 1], D[:, 0]))
    if th0 is not None: th += 2 * math.pi * round((th0 - th[0]) / (2 * math.pi))
    r = np.clip(np.hypot(D[:, 0], D[:, 1]), RHO_MIN, 1.0)
    return densify(np.c_[th, r])


def simplify(P, tol):
    import cv2
    a = np.asarray(P, np.float32).reshape(-1, 1, 2)
    return cv2.approxPolyDP(a, tol, False).reshape(-1, 2).astype(float)


def place(fn, r, final=True, name=None):
    """Build picture fn() for a sub-disc of radius r. final=False: no inside end, the walk comes back out to the
    entry. Returns dict(name, r, c (centre xy), ent (entry angle), xy (path, table radii), A (bg_erase analysis))."""
    p = fn()
    if not final: p.pop('final', None)
    for rg in p['regions']:
        rg['pitch'] = rg.get('pitch', 1.0) * (PITCH_TABLE / mc.PITCH) / r
    P, info = mc.build(p)
    P = simplify(P, 0.0012 / r * mc.S)                # 0.0012 table radii
    X = (P[:, 0] - mc.CX) / mc.S; Y = -(P[:, 1] - mc.CY) / mc.S
    ent = math.atan2(Y[0], X[0])
    c = np.array([(1 - r) * math.cos(ent), (1 - r) * math.sin(ent)])
    xy = np.c_[c[0] + r * X, c[1] + r * Y]
    xy[0] = (math.cos(ent), math.sin(ent))            # exactly on the real rim
    if np.hypot(*(xy[-1])) > 0.999: xy[-1] = (math.cos(ent), math.sin(ent))
    pts = xy_to_polar(xy)
    return dict(name=name or p['name'], title=p['title'], r=r, c=c, ent=ent, xy=xy, pts=pts, A=be.analyse(pts),
                loops=info['loops'])


def gap_between(a, b):
    return float(np.hypot(*(a['c'] - b['c'])) - a['r'] - b['r'])


# ---------------------------------------------------------------- the erase planner (bg_erase.plan, generalised)
def plan_regions(passes, hide, rim_ok, target, start=None, groove=GROOVE):
    """bg_erase.plan with explicit passes, travel mask and allowed rim, and an optional fixed start point.
    passes: [(name, region mask, pitch)]. Travel may use hide, rim_ok, and not-yet-erased sand of the current or a
    later pass. target: (theta, rho) the path ends on (the first drawing point)."""
    floor = GR >= RHO_MIN
    done = np.zeros((NG, NG), bool)
    pth0, prho0 = target
    stats = dict(travel_bad=0.0, cells=0)
    path = Path(*start) if start is not None else None
    for pi_, (name, region, p) in enumerate(passes):
        cells = build_cells(region, p)
        left = set(range(len(cells)))
        while left:
            avail = [i for i in left if all(q not in left for q in cells[i]['preds'])]
            if path is None:
                best = None
                for i in avail:
                    I = cells[i]['ivs'][0]
                    for e in (('a', 'b') if not I['full'] else ('a',)):
                        t = I[e] if not I['full'] else pth0
                        da = abs((t - pth0 + math.pi) % (2 * math.pi) - math.pi) + (1 - I['rho']) * 10
                        if best is None or da < best[0]: best = (da, i, t, I['rho'])
                _, ci, t, r = best
                path = Path(t + 2 * math.pi * round((pth0 - t) / (2 * math.pi)), r)
            else:
                future = np.zeros_like(done)
                for (_, reg2, _) in passes[pi_:]: future |= reg2
                near_done = dilate(done, groove) if done.any() else done
                free = (hide | (future & ~near_done)) & floor & DISC
                G, al = travel_graph(free | (rim_ok & floor), rim_ok & ~free)
                x0, y0 = path.rho * math.cos(path.th), path.rho * math.sin(path.th)
                src = tnode(x0, y0)
                dist, pred = dijkstra(G, indices=src, return_predecessors=True)
                best = None
                for i in avail:
                    I = cells[i]['ivs'][0]
                    ends = [(I['a'], I['rho']), (I['b'], I['rho'])] if not I['full'] else [(math.atan2(y0, x0), I['rho'])]
                    for t, r in ends:
                        c = dist[tnode(r * math.cos(t), r * math.sin(t))]
                        if best is None or c < best[0]: best = (c, i, t, r)
                _, ci, t, r = best
                x1, y1 = r * math.cos(t), r * math.sin(t)
                res = route(pred, al, src, tnode(x1, y1), (x0, y0), (x1, y1))
                if res is not None:
                    xy, bad = res; stats['travel_bad'] += bad
                    i0 = len(path.P); emit_travel(path, xy); paint_line(done, np.array(path.P[i0 - 1:]))
                path.to(t + 2 * math.pi * round((path.th - t) / (2 * math.pi)), r, 'travel')
            i0 = len(path.P)
            sweep_cell(path, cells[ci])
            paint_line(done, np.array(path.P[i0 - 1:]))
            for k in range(i0, len(path.P)): path.kind[k] = name
            left.discard(ci); stats['cells'] += 1
    G, al = travel_graph((hide | rim_ok) & floor & DISC, rim_ok & ~hide)
    x0, y0 = path.rho * math.cos(path.th), path.rho * math.sin(path.th)
    x1, y1 = prho0 * math.cos(pth0), prho0 * math.sin(pth0)
    src = tnode(x0, y0)
    dist, pred = dijkstra(G, indices=src, return_predecessors=True)
    res = route(pred, al, src, tnode(x1, y1), (x0, y0), (x1, y1))
    if res is not None:
        xy, bad = res; stats['travel_bad'] += bad; emit_travel(path, xy)
    path.to(pth0 + 2 * math.pi * round((path.th - pth0) / (2 * math.pi)), prho0, 'travel')
    return path, stats


def pull_steps(P, kinds, names=('background',), reach=0.035):
    """Move each ring-to-ring step of the boustrophedon `reach` (table radii) back inside the swept cell: the ball
    retraces its own arc, steps down there, and runs back out to the edge on the new ring. At the edge of the erased
    area only the rounded arc ends remain, not a step groove across the old texture."""
    P = [tuple(p) for p in P]; kinds = list(kinds)
    out, ok = [P[0]], [kinds[0]]
    n = len(P)
    for i in range(1, n):
        a, b = P[i - 1], P[i]
        if (kinds[i] in names and 0 < i - 1 and i + 1 < n and kinds[i + 1] == kinds[i] and abs(b[0] - a[0]) < 1e-9
                and 0 < a[1] - b[1] <= 0.03 and abs(P[i + 1][1] - b[1]) < 1e-9 and abs(P[i - 1][1] - P[i - 2][1]) < 1e-9):
            s_next = math.copysign(1.0, P[i + 1][0] - b[0])
            d = reach / max(b[1], 0.05)
            if abs(P[i + 1][0] - b[0]) > 2 * d and abs(a[0] - P[i - 2][0]) > d:
                th = a[0] + s_next * d
                out += [(th, a[1]), (th, b[1])]; ok += [kinds[i]] * 2
        out.append(b); ok.append(kinds[i])
    return out, ok


def union(As):
    out = {}
    for k in ('line', 'covered', 'covc', 'sil', 'islands', 'hide', 'inner', 'isl'):
        out[k] = np.logical_or.reduce([A[k] for A in As])
    return out


def tight_sil(A, groove=GROOVE):
    """the picture's own grooves (covc) plus enclosed pockets too small to sweep (under 1.5 groove across). Unlike
    bg_erase.analyse's silhouette, open spaces a picture encloses (between the phage's legs, the notches between the
    pumpkin's lobes, eyes) stay background and get the fine erase, with arc ends hidden under the lines round them."""
    from scipy import ndimage as ndi
    filled = ndi.binary_fill_holes(A['covc'])
    holes = filled & ~A['covc']
    big = opening(holes, groove * 0.75)
    return (filled & ~big) & DISC


def bg_of(sil, region=None, groove=GROOVE, under=2.0):
    """bg_erase.analyse's background rule for a given silhouette, limited to region"""
    sil_o = sil | (GR > 1.0)
    reg = DISC if region is None else region & DISC
    return opening(reg & ~erode(sil_o, groove * under) & (GR >= RHO_MIN), groove / 2)


# ---------------------------------------------------------------- the drawing part
def rim_arc(a0, a1, direction):
    """xy points along the rim from angle a0 to a1 going in `direction` (+1 ccw, -1 cw)"""
    d = (a1 - a0) % (2 * math.pi) if direction > 0 else -((a0 - a1) % (2 * math.pi))
    n = max(2, int(abs(d) / 0.01))
    t = a0 + d * np.arange(n + 1) / n
    return np.c_[np.cos(t), np.sin(t)]


def order_round_rim(pics):
    """indices in ccw entry order, starting just after the biggest gap between consecutive entries"""
    idx = sorted(range(len(pics)), key=lambda i: pics[i]['ent'] % (2 * math.pi))
    a = [pics[i]['ent'] % (2 * math.pi) for i in idx]
    gaps = [(a[(j + 1) % len(a)] - a[j]) % (2 * math.pi) or 2 * math.pi for j in range(len(a))]
    j = int(np.argmax(gaps))
    return idx[j + 1:] + idx[:j + 1]


def drawing_xy(pics, order):
    """first picture reversed, middle ones in-and-out, last forward, joined by rim runs (ccw)"""
    segs, kinds = [], []
    for n, i in enumerate(order):
        xy = pics[i]['xy']
        if n == 0 and len(order) > 1: xy = xy[::-1]
        if n > 0:
            prev = pics[order[n - 1]]
            segs.append(rim_arc(prev['ent'], pics[i]['ent'], +1)); kinds.append('rim')
        segs.append(xy); kinds.append(pics[i]['name'])
    return segs, kinds


def assemble(pre, kinds_pre, draw_segs, draw_kinds, port_th0=None):
    """erase plan + drawing segments -> one array, plus per-point labels"""
    pre = np.asarray(pre, float)
    er = densify(pre)
    th = er[-1, 0]
    parts, lab = [er[:-1]], [np.array(['erase'] * (len(er) - 1))]
    for xy, k in zip(draw_segs, draw_kinds):
        p = xy_to_polar(xy, th)
        if len(parts) > 1: p = p[1:]
        parts.append(p); lab.append(np.array([k] * len(p))); th = p[-1, 0]
    out = np.vstack(parts)
    if len(out) > be.MAX_POINTS:                       # thin the erase part (exact for arcs on this table)
        er2 = densify(pre, thin=True)
        parts[0] = er2[:-1]; lab[0] = np.array(['erase'] * (len(er2) - 1)); out = np.vstack(parts)
    return out, np.concatenate(lab)


def stray_check(out, lab, allowed, groove=GROOVE):
    """length (table radii) of DRAWING moves (not erase) that groove sand outside `allowed` (the pictures' covered
    sand, the rim): each would be a stray line on clean background"""
    m = lab != 'erase'
    p = out[m]
    x, y = p[:, 1] * np.cos(p[:, 0]), p[:, 1] * np.sin(p[:, 0])
    c, r = be.to_px(x, y)
    ok = allowed[np.clip(np.round(r).astype(int), 0, NG - 1), np.clip(np.round(c).astype(int), 0, NG - 1)]
    seg = np.hypot(np.diff(x), np.diff(y))
    return float(seg[~ok[1:]].sum())


def validate(out):
    d = np.abs(np.diff(out, axis=0))
    rm = np.maximum(out[:-1, 1], out[1:, 1])
    return dict(points=len(out), max_step=float(np.hypot(rm * d[:, 0], d[:, 1]).max()), max_dth=float(d[:, 0].max()),
                rho_lo=float(out[:, 1].min()), rho_hi=float(out[:, 1].max()))


# ---------------------------------------------------------------- the two entry points
def compose(pics, pitch=0.02, inside_pitch=0, islands=False):
    for a in range(len(pics)):
        for b in range(a + 1, len(pics)):
            assert gap_between(pics[a], pics[b]) > 2 * MARGIN, ('sub-discs too close', pics[a]['name'], pics[b]['name'])
    order = order_round_rim(pics)
    U = union([p['A'] for p in pics])
    U['sil'] = np.logical_or.reduce([tight_sil(p['A']) for p in pics])
    bg = bg_of(U['sil'])
    passes = [('background', bg, pitch)]
    if inside_pitch: passes.append(('inside', U['inner'] & ~(dilate(U['isl'], GROOVE / 2) if islands else np.zeros_like(U['isl'])), inside_pitch))
    if islands: passes.append(('islands', U['isl'], pitch))
    segs, kinds = drawing_xy(pics, order)
    first = xy_to_polar(segs[0])[0]
    rim = (GR >= 0.985) & DISC
    path, stats = plan_regions(passes, U['hide'], rim, first)
    path.P, path.kind = pull_steps(path.P, path.kind)
    out, lab = assemble(path.P, path.kind, segs, kinds)
    allowed = dilate(U['covered'], 0.004) | (GR >= 0.975)
    info = dict(stats, order=[pics[i]['name'] for i in order], pre=np.array(path.P), kinds=np.array(path.kind),
                stray=stray_check(out, lab, allowed), minutes=tc.est_minutes(out),
                erase_min=tc.est_minutes(out[lab == 'erase']), lab=lab, **validate(out))
    return out, info


def replace(pics, k, new, pitch=0.02):
    """Full-table fine erase followed by the updated composition, drawn from the rim."""
    old = pics[k]
    if new['r'] != old['r'] or abs(math.remainder(new['ent'] - old['ent'], math.tau)) >= 0.06:
        raise ValueError("The replacement must fit the original place")
    if not 0.012 <= pitch <= 0.06:
        raise ValueError("Erase spacing is outside the table's supported range")
    updated = list(pics)
    updated[k] = new
    order = order_round_rim(updated)
    first_gate = updated[order[0]]['ent']
    spiral = np.array([[first_gate - math.tau / pitch, 0.0], [first_gate, 1.0]])
    segments, kinds = [], []
    for i, slot in enumerate(order):
        pic = updated[slot]
        if i:
            segments.append(rim_arc(updated[order[i - 1]]['ent'], pic['ent'], +1))
            kinds.append('rim')
        xy = pic['xy']
        if i < len(order) - 1 and not np.allclose(xy[-1], xy[0]):
            xy = np.vstack([xy, xy[-2::-1]])
        segments.append(xy)
        kinds.append(pic['name'])
    out, lab = assemble(spiral, ['background'] * 2, segments, kinds)
    allowed = dilate(union([p['A'] for p in updated])['covered'], 0.004) | (GR >= 0.975)
    info = dict(order=[updated[i]['name'] for i in order], pre=spiral, kinds=['background'] * 2,
                travel_bad=0.0, stray=stray_check(out, lab, allowed), minutes=tc.est_minutes(out),
                erase_min=tc.est_minutes(out[lab == 'erase']), lab=lab, **validate(out))
    return out, info


# ---------------------------------------------------------------- output
def write_split(base, pts, note):
    """write base.thr, or base_1.thr, base_2.thr ... if over 12000 points (consecutive files share their joint)"""
    if len(pts) < be.MAX_POINTS:
        be.write(base + '.thr', pts, note); return [base + '.thr']
    names, i, n = [], 0, 1
    while i < len(pts) - 1:
        j = min(len(pts), i + be.MAX_POINTS - 1)
        be.write('%s_%d.thr' % (base, n), pts[i:j], note + ' (part %d)' % n); names.append('%s_%d.thr' % (base, n))
        i, n = j - 1, n + 1
    return names


def _sim(args):
    import sandsim
    steps, size = args
    return np.array(sandsim.render_steps(steps, size=size, real=True))


def save_lit(arr, path):
    import cv2
    from brighten import brighten
    cv2.imwrite(path, brighten(np.ascontiguousarray(arr[:, :, ::-1])), [cv2.IMWRITE_JPEG_QUALITY, 93])


def plot_routes(items, out_jpg):
    """items: (title, out, lab, info). Erase passes in blue/orange/green, travel red, rim runs black, pictures grey."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, len(items), figsize=(8.5 * len(items), 9.2), dpi=110)
    col = {'background': '#1f4e9a', 'inside': '#e08a00', 'islands': '#1a9a3a', 'travel': '#d62020'}
    for ax, (title, out, lab, info) in zip(np.atleast_1d(axs), items):
        ax.set_aspect('equal'); ax.axis('off')
        t = np.linspace(0, 2 * np.pi, 400); ax.plot(np.cos(t), np.sin(t), color='k', lw=1)
        if 'region' in info:
            ax.contour(GX, GY, info['region'].astype(float), [0.5], colors='#9a9a9a', linewidths=1, linestyles='--')
        pre, kinds = info['pre'], info['kinds']
        for i in range(1, len(pre)):
            x, y = be.polar_xy(densify(pre[i - 1:i + 1], 0.005, 0.02))
            ax.plot(x, y, color=col.get(kinds[i], 'k'), lw=0.6 if kinds[i] != 'travel' else 1.6)
        m = lab != 'erase'
        d = out[m]; L = lab[m]
        x, y = d[:, 1] * np.cos(d[:, 0]), d[:, 1] * np.sin(d[:, 0])
        for name in dict.fromkeys(L):
            s = L == name
            ax.plot(x[s], y[s], color='k' if name == 'rim' else '#8a8a8a', lw=2.4 if name == 'rim' else 0.7)
        x0, y0 = be.polar_xy(out[:1]); x1, y1 = be.polar_xy(out[-1:])
        ax.plot(x0, y0, 'o', color='#1f4e9a', ms=11); ax.plot(x1, y1, 's', color='k', ms=9)
        ax.set_title(title, fontsize=13)
    from matplotlib.lines import Line2D
    h = [Line2D([0], [0], color=c, lw=2) for c in col.values()] + [Line2D([0], [0], color='#8a8a8a', lw=1),
                                                                    Line2D([0], [0], color='k', lw=2.4)]
    fig.legend(h, ['fine erase (outside pictures)', 'coarse erase (inside pictures)', 'islands erase', 'travel',
                   'pictures', 'run along the rim'], loc='lower center', ncol=6, fontsize=11)
    fig.tight_layout(rect=(0, 0.04, 1, 1)); fig.savefig(out_jpg, pil_kwargs=dict(quality=92)); plt.close(fig)


def main():
    import coarse
    from concurrent.futures import ProcessPoolExecutor
    R = 0.48
    pics = [place(coarse.phage, R, final=False), place(coarse.pumpkin, R)]
    for p in pics:
        print('%-8s r %.2f centre (%+.3f, %+.3f) entry %+.1f deg, loops %d, picture %d pts %.1f min' % (
            p['name'], p['r'], p['c'][0], p['c'][1], math.degrees(p['ent']), p['loops'], len(p['pts']),
            tc.est_minutes(p['pts'])))
    print('gap between sub-discs %.3f' % gap_between(*pics))
    out1, i1 = compose(pics)
    new = place(coarse.guitar, R, final=False)
    print('%-8s entry %+.1f deg, %d pts' % (new['name'], math.degrees(new['ent']), len(new['pts'])))
    out2, i2 = replace(pics, 1, new)
    var = ROOT + '/captures/variants'; mor = ROOT + '/captures/morning'
    f1 = write_split(var + '/compose_two', out1, 'compose: %s (tools/compose.py)' % ' + '.join(i1['order']))
    f2 = write_split(var + '/compose_replace', out2, 'compose replace: %s -> %s (tools/compose.py)' % (pics[1]['name'], new['name']))
    for nm, i, f in (('two', i1, f1), ('replace', i2, f2)):
        print('%-8s %6d pts  %.1f min (erase %.1f)  max step %.4f  max dtheta %.4f  rho %.3f..%.3f  bad travel %.3f R  '
              'stray drawing %.3f R%s  -> %s' % (nm, i['points'], i['minutes'], i['erase_min'], i['max_step'],
              i['max_dth'], i['rho_lo'], i['rho_hi'], i['travel_bad'], i['stray'],
              ('  touches neighbours %d pts' % i['touches_neighbours']) if 'touches_neighbours' in i else '', ', '.join(f)))
    old = ROOT + '/patterns/people/alex.thr'
    jobs = [([('erase', 0.035), old, out1], 900), ([('erase', 0.035), old, out1, out2], 900)]
    with ProcessPoolExecutor() as ex: ims = list(ex.map(_sim, jobs))
    save_lit(ims[0], mor + '/compose_two.jpg'); save_lit(ims[1], mor + '/compose_replace.jpg')
    plot_routes([('compose_two: %s (%d pts, %.0f min)' % (' then '.join(i1['order']), i1['points'], i1['minutes']), out1, i1['lab'], i1),
                 ('compose_replace: %s -> %s (%d pts, %.0f min)' % (pics[1]['name'], new['name'], i2['points'], i2['minutes']), out2, i2['lab'], i2)],
                mor + '/compose_route.jpg')
    print('wrote', mor + '/compose_two.jpg', mor + '/compose_replace.jpg', mor + '/compose_route.jpg')


if __name__ == '__main__':
    main()
