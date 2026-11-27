#!/usr/bin/env python3
"""sand_comb_lab - SIMULATION ONLY. Back-and-forth combing on a small flat patch of sand, to test how the maker's
fine 'combed' texture and the piles along limb edges are made (v3 study, 2026-11-22).

A patch (default 50 x 70 mm at 0.1 mm/px) starts flat at `depth`. The ball combs strokes 20 mm long along x,
advancing along +y by `spacing` after each stroke (a zig-zag), over 36 mm. Measured per run (heights relative to the
original level): mean height of the combed area, rib height, the piles at the two stroke ends, the pile in front
of the final stroke and behind the first, and where every cubic millimetre of moved sand ended up.

    python3 tools/sand_comb_lab.py --spacing 5.5 3 2 1.5 1.1 0.8 --out captures/relief-study/v3/lab
    python3 tools/sand_comb_lab.py --grid --out captures/relief-study/v3/lab       # depth x ball radius
"""
import argparse, json, math, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_sim as sim


class Patch:
    def __init__(self, w=50.0, hgt=70.0, px=0.1, **phys):
        self.p = dict(sim.PHYS, **phys)
        self.px = px
        self.n1, self.n0 = int(round(w / px)), int(round(hgt / px))
        self.tray = np.ones((self.n0, self.n1), bool)
        self.tray[:2, :] = self.tray[-2:, :] = False
        self.tray[:, :2] = self.tray[:, -2:] = False
        self.h = np.where(self.tray, self.p['depth'], 0.0)
        self.x = (np.arange(self.n1) + 0.5) * px - w / 2          # mm, centre of the patch = 0
        self.y = hgt / 2 - (np.arange(self.n0) + 0.5) * px         # mm, y up (row 0 at the top)

    def to_px(self, P):
        P = np.asarray(P, float)
        return (P[:, 0] + self.x[-1] + self.px / 2) / self.px - 0.5, (self.y[0] + self.px / 2 - P[:, 1]) / self.px - 0.5

    def run(self, P_mm):
        """Drag the ball along a polyline in mm (densified to steps of ball_r * step_frac)."""
        P = np.asarray(P_mm, float)
        step = self.p['ball_r'] * self.p['step_frac']
        out = [P[:1]]
        for a, b in zip(P[:-1], P[1:]):
            n = max(1, int(math.ceil(math.hypot(*(b - a)) / step)))
            t = np.arange(1, n + 1)[:, None] / n
            out.append(a + (b - a) * t)
        Q = np.vstack(out)
        xs, ys = self.to_px(Q)
        p = self.p
        rp = p['ball_r'] / self.px
        dwp = max(1.5, p['dep_w'] * p['ball_r'] / self.px)
        tn = math.tan(math.radians(p['repose_deg']))
        return sim._march(self.h, self.tray, xs.astype(np.float64), ys.astype(np.float64), rp, p['ball_r'], self.px,
                          dwp, p['fwd'], tn * self.px, tn * self.px * math.sqrt(2), int(p['relax_iter']),
                          1 if p['deposit'] == 'push' else 0, float(p['av_tol']), float(p['av_scale']))

    def volume(self):
        return float(self.h[self.tray].sum() * self.px ** 2)

    def render(self, lights=((90, 14, 1.0), (60, 12, 0.5), (120, 12, 0.5)), soft_mm=0.12, sky=1.4, sky_mm=4.0,
               ambient=0.10, exposure=1.0, direct=0.9, tint=(0.90, 0.95, 1.0), gamma=0.8):
        """Low raking light from the rim side (azimuth deg, 90 = from the top of the picture, elevation deg, power),
        like the table's LED ring seen near one edge, plus the soft overhead light from the glass."""
        from scipy.ndimage import gaussian_filter
        from PIL import Image
        h = gaussian_filter(self.h, max(0.5, soft_mm / self.px))
        gy, gx = np.gradient(h, self.px)
        nz = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
        nx, ny = -gx * nz, gy * nz
        L = np.array([[math.cos(math.radians(a)), -math.sin(math.radians(a)), math.tan(math.radians(e)), pw, 1.0]
                      for a, e, pw in lights])
        out = np.zeros_like(h)
        sim._shade(h, self.tray, nx, ny, nz, L, self.px, 20.0 / self.px, 0.10, 1e9, out)
        sv = np.zeros_like(h)
        sim._skyvis(h, self.tray, self.px, sky_mm / self.px, sv)
        v = (direct * out / sum(l[2] for l in lights) + ambient + sky * sv ** 2) * exposure
        img = np.clip(1.0 - np.exp(-1.6 * v), 0, 1) ** (1 / gamma)
        rgb = (np.clip(img[..., None] * np.array(tint), 0, 1) * 255).astype(np.uint8)
        return Image.fromarray(rgb)


def comb_path(spacing, length=20.0, advance=36.0, y0=-18.0):
    """Zig-zag: strokes along x from -length/2 to +length/2, stepping +y by spacing at each end."""
    n = int(round(advance / spacing)) + 1
    P = []
    for k in range(n):
        y = y0 + k * spacing
        xa, xb = (-length / 2, length / 2) if k % 2 == 0 else (length / 2, -length / 2)
        P += [(xa, y), (xb, y)]
    return np.array(P), y0 + (n - 1) * spacing


def measure(pt, spacing, y_end, length=20.0, y0=-18.0):
    d = pt.p['depth']
    H = pt.h - d
    X, Y = np.meshgrid(pt.x, pt.y)
    A = pt.px ** 2
    half = length / 2
    inner = (np.abs(X) <= half - 2) & (Y >= y0 + 2) & (Y <= y_end - 2)
    res = dict(spacing=spacing, depth=d, ball_r=pt.p['ball_r'], deposit=pt.p['deposit'])
    res['combed_mean_mm'] = float(H[inner].mean())
    # ribs: profile along the advance direction through the middle, minus its own running mean over 2 spacings
    from scipy.ndimage import uniform_filter1d
    band = np.abs(pt.x) <= 3
    rows = (pt.y >= y0 + 3) & (pt.y <= y_end - 3)
    prof = H[:, band].mean(1)[rows]
    det = prof - uniform_filter1d(prof, max(3, int(round(2 * spacing / pt.px))))
    res['rib_pp_mm'] = float(2 * math.sqrt(2) * det.std())
    # stroke-end piles: profile along x averaged over the combed rows
    ry = (pt.y >= y0 + 3) & (pt.y <= y_end - 3)
    px_prof = H[ry, :].mean(0)

    def pile(xs, prof, sel):
        p = prof[sel]; x = xs[sel]
        k = int(np.argmax(p))
        above = x[p > 0.1]
        return dict(peak_mm=round(float(p[k]), 2), at_mm=round(float(x[k]), 1),
                    width_mm=round(float(above.max() - above.min()), 1) if len(above) else 0.0,
                    vol_per_mm=round(float(np.clip(p, 0, None).sum() * pt.px), 2))
    res['end_pile_right'] = pile(pt.x, px_prof, pt.x > 0)
    res['end_pile_left'] = pile(pt.x, px_prof, pt.x < 0)
    cx = np.abs(pt.x) <= half - 3
    py_prof = H[:, cx].mean(1)
    res['final_pile'] = pile(pt.y, py_prof, pt.y > y_end - 1)
    res['first_side_pile'] = pile(pt.y, py_prof, pt.y < y0 + 1)
    # where the sand went: deficit (below original) vs surplus by zone
    dug = float(-np.clip(H, None, 0)[pt.tray].sum() * A)
    pos = np.clip(H, 0, None) * pt.tray
    zones = dict(stroke_ends=(np.abs(X) > half) & (Y >= y0 - 1) & (Y <= y_end + 1),
                 front_of_final_stroke=(np.abs(X) <= half) & (Y > y_end + 1),
                 behind_first_stroke=(np.abs(X) <= half) & (Y < y0 - 1),
                 inside_combed=(np.abs(X) <= half) & (Y >= y0 - 1) & (Y <= y_end + 1))
    zones['corners'] = pt.tray & ~(zones['stroke_ends'] | zones['front_of_final_stroke'] | zones['behind_first_stroke']
                                   | zones['inside_combed'])
    res['dug_mm3'] = round(dug, 1)
    res['dug_level_equiv_mm'] = round(dug / ((length) * (y_end - y0)), 2)
    res['surplus_share'] = {k: round(float(pos[m].sum() * A) / max(dug, 1e-9), 3) for k, m in zones.items()}
    res['profile_advance'] = [pt.y.tolist()[::2], H[:, band].mean(1).tolist()[::2]]
    yi = np.argmin(np.abs(pt.y - (y0 + y_end) / 2))
    res['profile_stroke'] = [pt.x.tolist()[::2], H[yi - 2:yi + 3, :].mean(0).tolist()[::2]]
    return res


def run_case(spacing, out=None, tag=None, **phys):
    pt = Patch(**phys)
    v0 = pt.volume()
    P, y_end = comb_path(spacing)
    t0 = time.time()
    pt.run(P)
    res = measure(pt, spacing, y_end)
    res['volume_err'] = abs(pt.volume() - v0) / v0
    res['seconds'] = round(time.time() - t0, 1)
    if out:
        tag = tag or 's%.1f_d%.1f_r%.1f_%s' % (spacing, pt.p['depth'], pt.p['ball_r'], pt.p['deposit'])
        pt.render().save(os.path.join(out, tag + '.png'))
        np.save(os.path.join(out, tag + '_h.npy'), pt.h.astype(np.float32))
        json.dump(res, open(os.path.join(out, tag + '.json'), 'w'))
    return res, pt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spacing', type=float, nargs='*', default=[5.5, 3, 2, 1.5, 1.1, 0.8])
    ap.add_argument('--grid', action='store_true')
    ap.add_argument('--depths', type=float, nargs='*', default=[1.5, 2.2, 3.5, 5.0])
    ap.add_argument('--deposit', default='push')
    ap.add_argument('--step_frac', type=float, default=0.1)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cases = []
    if a.grid:
        for s in (1.1, 5.5):
            for d in a.depths:
                for r in (3.2, 5.0, 6.5):
                    cases.append(dict(spacing=s, depth=d, ball_r=r))
    else:
        cases = [dict(spacing=s) for s in a.spacing]
    for c in cases:
        s = c.pop('spacing')
        res, _ = run_case(s, a.out, deposit=a.deposit, step_frac=a.step_frac, **c)
        print(json.dumps({k: v for k, v in res.items() if not k.startswith('profile')}), flush=True)


if __name__ == '__main__':
    main()
