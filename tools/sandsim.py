#!/usr/bin/env python3
"""sandsim - approximate how a .thr drawing will look in the sand.

Model: white sand disc (a height field, 0 = flat). Every stamp along the ball's
path writes a groove profile (dark floor, raised ridges either side) and
REPLACES what was under it, so later strokes overwrite earlier ones. The height
field is then lit from the upper left at a low angle so ridges read as relief.
The groove is 4% of the tray radius wide (thrcommon.GROOVE).

    sandsim.py pattern.thr -o out.png [--size 900]
    sandsim.py a.thr b.thr --stack -o both.png     # b drawn over a, same sand
    sandsim.py --contact-sheet sheet.png *.thr     # labelled thumbnails

--real switches to the honest model: the table's erase spiral (pitch 0.035) as the background, a wider and
softer groove fitted to a photo of a real drawing, and the photo's soft low-contrast light. Use it to judge
legibility; the default look is the clean mockup.

Flat sand is always the starting state (--erase-first, the default). Continuing
from an earlier picture is deliberately not supported; use --stack with the
earlier .thr files instead.

Known limits: no sand physics (ridges never slump or pile up, crossing lines do
not push each other), orientation of theta (CCW, y up) is assumed, and the light
is a fixed direction. It is a preview, not a prediction.
"""
import argparse, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thrcommon as tc

SAND = np.array([240.0, 235.0, 222.0])
BG = np.array([46.0, 43.0, 41.0])
LUT_N = 512
U_MAX = 2.3     # stamp support radius in groove half-widths


# Groove shape: floor = width of the dark floor and floor_k its sharpness (both in groove half-widths), ridge =
# height of the raised shoulders at ridge_at half-widths from the centre line. MOCK is the original preview look.
MOCK = dict(groove=tc.GROOVE, floor=0.72, floor_k=4, ridge=0.42, ridge_at=1.5, ridge_w=0.42)
# REAL: fitted on 2026-11-20 against the photo of Lek's portrait (captures/morning/lek_sand.jpg) with
# patterns/people/lek.thr as the known input (see fit notes in README, "Honest simulator"). Wider, rounder groove,
# low ridges, everything softened, lit softly and drawn over the erase spiral the table always lays down first.
REAL = dict(groove=0.042, floor=1.15, floor_k=3, ridge=0.12, ridge_at=1.6, ridge_w=0.5,
            soft=0.45, light=(-0.91, 0.41), contrast=0.42, rim_gain=3.2, ao=0.0, erase_pitch=0.035, erase_phase=0.4)


def _profile_luts(floor=0.72, floor_k=4, ridge=0.42, ridge_at=1.5, ridge_w=0.42, **_):
    u = np.linspace(0, U_MAX, LUT_N)
    groove = -np.exp(-(u / floor) ** floor_k)            # dark floor
    ridge = ridge * np.exp(-((u - ridge_at) / ridge_w) ** 2)     # raised shoulders
    p = groove + ridge
    m = np.where(u < 1.7, 1.0, 0.5 * (1 + np.cos(np.pi * np.clip((u - 1.7) / (U_MAX - 1.7), 0, 1))))
    m[-1] = 0.0
    return p.astype(np.float32), m.astype(np.float32)


class Sand:
    def __init__(self, size=900, real=False, **prof):
        """real=True: the honest model (REAL groove, erase-spiral background, photo-like light). Any key of
        MOCK / REAL passed here overrides that one value."""
        self.size = size
        self.real = real
        self.prof = dict(REAL if real else MOCK, **prof)
        self.R = size / 2 * 0.94                 # tray radius in px
        self.hw = self.prof['groove'] * self.R / 2         # groove half-width px
        self.pad = int(math.ceil(U_MAX * self.hw)) + 2
        n = size + 2 * self.pad
        self.h = np.zeros((n, n), np.float32)
        self.P, self.M = _profile_luts(**self.prof)
        w = self.pad
        self.ox, self.oy = np.meshgrid(np.arange(-w, w + 1), np.arange(-w, w + 1))

    def draw(self, pts):
        """Carve one drawing. pts: (N,2) theta, rho."""
        pts = np.asarray(pts, float)
        if len(pts) < 2:
            return
        th, r = pts[:, 0], pts[:, 1]
        dth, dr = np.diff(th), np.diff(r)
        rm = (r[:-1] + r[1:]) / 2
        L = np.hypot(rm * dth, dr) * self.R             # px per segment (approx)
        step = max(0.3 * self.hw, 1.0)
        n = np.maximum(1, np.ceil(L / step).astype(int))
        seg = np.repeat(np.arange(len(n)), n)
        first = np.cumsum(n) - n
        s = (np.arange(len(seg)) - first[seg]) / n[seg]
        T = th[seg] + s * dth[seg]
        Rr = np.clip(r[seg] + s * dr[seg], 0, 1)
        cx = self.size / 2 + self.pad + Rr * self.R * np.cos(T)
        cy = self.size / 2 + self.pad - Rr * self.R * np.sin(T)
        # Process the path in overlapping chunks. Within a chunk the groove
        # profile is a function of the minimum distance to the chunk's samples
        # (no scalloping); the chunk then REPLACES what was in the sand there.
        # Overlap hides the chunk-end caps inside already-carved territory.
        h, P, M = self.h, self.P, self.M
        w, ox, oy = self.pad, self.ox, self.oy
        k = (LUT_N - 1) / U_MAX / self.hw
        chunk, overlap = 56, 20
        trim = overlap // 2
        n_s = len(cx)
        i = 0
        while i < n_s:
            j = min(n_s, i + chunk)
            xs, ys = cx[i:j], cy[i:j]
            x0, x1 = int(xs.min()) - w, int(xs.max()) + w + 1
            y0, y1 = int(ys.min()) - w, int(ys.max()) + w + 1
            dmin = np.full((y1 - y0 + 1, x1 - x0 + 1), 1e9, np.float32)
            imin = np.zeros(dmin.shape, np.int32)
            for q, (x, y) in enumerate(zip(xs.tolist(), ys.tolist())):
                ix, iy = int(round(x)), int(round(y))
                d = np.sqrt((ox - (x - ix)) ** 2 + (oy - (y - iy)) ** 2).astype(np.float32)
                sl = (slice(iy - w - y0, iy + w + 1 - y0), slice(ix - w - x0, ix + w + 1 - x0))
                sub, isub = dmin[sl], imin[sl]
                better = d < sub
                sub[better] = d[better]
                isub[better] = q
            idx = np.minimum(dmin * k, LUT_N - 1).astype(np.int32)
            m = M[idx]
            lo = 0 if i == 0 else trim
            hi = (j - i) if j >= n_s else (j - i) - trim
            m = m * ((imin >= lo) & (imin < hi))
            sub = h[y0:y1 + 1, x0:x1 + 1]
            sub += m * (P[idx] - sub)
            if j >= n_s:
                break
            i = j - overlap

    def erase(self, pitch=None, outward=True, phase=0.0):
        """Lay down the table's erase: an Archimedean spiral from the centre to the rim (rho = pitch * turns),
        computed directly per pixel. Arms are applied inner to outer (outward erase), each REPLACING the sand
        under it, the same rule as draw()."""
        pitch = pitch or self.prof.get('erase_pitch', 0.035)
        phase = phase or self.prof.get('erase_phase', 0.0)
        n, w = self.h.shape[0], self.pad
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        X = (xx - n / 2 + 0.5) / self.R
        Y = -(yy - n / 2 + 0.5) / self.R
        r = np.hypot(X, Y)
        th = (np.arctan2(Y, X) / (2 * np.pi)) % 1.0
        q = r / pitch - th - phase                       # arm k passes where q == k
        k0 = np.floor(q)
        h = np.zeros_like(r)
        k = (LUT_N - 1) / U_MAX / self.hw * self.R * pitch
        span = int(math.ceil(U_MAX * self.hw / (self.R * pitch))) + 1
        order = range(-span, span + 1) if outward else range(span, -span - 1, -1)
        for o in order:
            arm = k0 + o
            arm_r = (arm + th + phase) * pitch           # that arm's radius at this angle
            ok = (arm_r >= 0) & (arm_r <= 1.0)
            idx = np.minimum(np.abs(q - arm) * k, LUT_N - 1).astype(np.int32)
            m = self.M[idx] * ok
            h += m * (self.P[idx] - h)
        self.h = h.astype(np.float32)

    def coverage(self):
        """Fraction of the tray area that has been disturbed (|height| > 0.05)."""
        n, w = self.size, self.pad
        yy, xx = np.mgrid[0:n, 0:n]
        disc = np.hypot(xx - n / 2 + 0.5, yy - n / 2 + 0.5) < self.R * 0.97
        return float((np.abs(self.h[w:w + n, w:w + n]) > 0.05)[disc].mean())

    def image(self, contrast=1.0):
        if self.real:
            return self.image_real(contrast)
        w, n = self.pad, self.size
        h = self.h
        try:
            from scipy.ndimage import gaussian_filter
            hs = gaussian_filter(h, 0.7)
        except Exception:
            hs = h
        gy, gx = np.gradient(hs)
        light = 1.0 * (gx + gy) * (self.hw * 1.1) * contrast   # light from upper left
        ao = 0.20 * np.clip(-h, 0, 1) * contrast
        shade = 1.0 + 0.42 * light - ao
        shade = np.clip(shade, 0.45, 1.10)[w:w + n, w:w + n]
        img = SAND[None, None, :] * shade[:, :, None]
        yy, xx = np.mgrid[0:n, 0:n]
        d = np.hypot(xx - n / 2 + 0.5, yy - n / 2 + 0.5)
        inside = np.clip(self.R + 0.5 - d, 0, 1)[:, :, None]
        # soft vignette at the wall of the tray
        wall = np.clip((d - (self.R - 0.02 * self.R)) / (0.02 * self.R), 0, 1)[:, :, None]
        img = img * (1 - 0.25 * wall)
        out = BG[None, None, :] * (1 - inside) + img * inside
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


    def image_real(self, contrast=1.0):
        """Photo-like look: soft diffuse light, low contrast, sand darker in the middle than at the rim (as the
        camera sees it on the desk)."""
        from scipy.ndimage import gaussian_filter
        pr = self.prof
        w, n = self.pad, self.size
        hs = gaussian_filter(self.h, max(0.5, pr['soft'] * self.hw))
        gy, gx = np.gradient(hs)
        lx, ly = pr['light']
        light = (lx * gx + ly * gy) / math.hypot(lx, ly) * self.hw * 1.1 * pr['contrast'] * contrast
        ao = pr['ao'] * np.clip(-hs, 0, 1) * contrast
        yy, xx = np.mgrid[0:n + 2 * w, 0:n + 2 * w]
        rg = np.hypot(xx - n / 2 - w + 0.5, yy - n / 2 - w + 0.5) / self.R
        gain = 1.0 + pr['rim_gain'] * np.clip(rg, 0, 1) ** 6        # the photo shows relief far more strongly near the wall
        shade = np.clip(1.0 + 0.42 * light * gain - ao, 0.5, 1.5)[w:w + n, w:w + n]
        yy, xx = np.mgrid[0:n, 0:n]
        d = np.hypot(xx - n / 2 + 0.5, yy - n / 2 + 0.5)
        rr = np.clip(d / self.R, 0, 1)[:, :, None]
        vert = ((yy - n / 2) / self.R)[:, :, None]
        mid, rim = np.array([88.0, 80.0, 73.0]), np.array([118.0, 118.0, 124.0])
        base = mid + (rim - mid) * rr ** 2.2 + np.clip(vert, 0, 1) ** 2 * rr * np.array([18.0, 22.0, 28.0])
        img = base * shade[:, :, None]
        wall = np.clip((d - self.R) / (0.03 * self.R), 0, 1)[:, :, None]       # the bright tray wall
        img = img * (1 - wall) + np.array([150.0, 150.0, 156.0]) * wall
        inside = np.clip(self.R * 1.03 + 0.5 - d, 0, 1)[:, :, None]
        out = np.zeros(3)[None, None, :] * (1 - inside) + img * inside
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def render(files_or_pts, size=900, stack=True, real=False, **prof):
    """Render one drawing (array) or a list of arrays carved in order. real=True: the honest model, which
    starts from the erase spiral the table lays down before every drawing."""
    s = Sand(size, real=real, **prof)
    if real:
        s.erase()
    items = files_or_pts if isinstance(files_or_pts, (list, tuple)) else [files_or_pts]
    for it in items:
        s.draw(tc.read_thr(it) if isinstance(it, str) else it)
    return s.image()


def render_steps(steps, size=900, real=True, **prof):
    """Render a sequence on the same sand, starting from flat: each step is ('erase', pitch) for the table's full
    outward erase spiral (replaces everything), or an (N,2) array / .thr path carved on top. Use it to start from an
    older picture: [('erase', 0.035), 'alex.thr', partial_erase_plus_portrait]."""
    s = Sand(size, real=real, **prof)
    for st in steps:
        if isinstance(st, tuple) and st and st[0] == 'erase':
            s.erase(pitch=st[1])
        else:
            s.draw(tc.read_thr(st) if isinstance(st, str) else st)
    return s.image()


def _font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def contact_sheet(items, out, thumb=300, cols=5, real=False):
    """items: list of (label, minutes, pts or path)."""
    from concurrent.futures import ProcessPoolExecutor
    jobs = [(it[2], thumb, real) for it in items]
    with ProcessPoolExecutor() as ex:
        ims = list(ex.map(_thumb_job, jobs))
    cols = min(cols, len(items))
    rows = math.ceil(len(items) / cols)
    lab = 38
    cw, ch = thumb + 12, thumb + lab + 8
    sheet = Image.new("RGB", (cols * cw + 12, rows * ch + 12), (34, 32, 31))
    dr = ImageDraw.Draw(sheet)
    f1, f2 = _font(15), _font(13)
    for i, ((name, minutes, _), im) in enumerate(zip(items, ims)):
        x, y = 12 + (i % cols) * cw, 12 + (i // cols) * ch
        sheet.paste(im, (x, y))
        dr.text((x + 2, y + thumb + 3), name, fill=(235, 235, 235), font=f1)
        dr.text((x + 2, y + thumb + 21), f"{minutes:.1f} min", fill=(170, 170, 170), font=f2)
    sheet.save(out)


def _thumb_job(args):
    it, thumb = args[:2]
    real = args[2] if len(args) > 2 else False
    return render(tc.read_thr(it) if isinstance(it, str) else it, size=thumb, real=real)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help=".thr files")
    ap.add_argument("-o", "--out", help="output PNG (single render)")
    ap.add_argument("--size", type=int, default=900)
    ap.add_argument("--stack", action="store_true", help="draw all files in order onto the same sand")
    ap.add_argument("--erase-first", action=argparse.BooleanOptionalAction, default=True,
                    help="start from flat sand (default; the only supported start)")
    ap.add_argument("--contact-sheet", metavar="OUT.png", help="tile labelled thumbnails of FILES")
    ap.add_argument("--thumb", type=int, default=300)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--real", action="store_true",
                    help="honest model: erase-spiral background, groove fitted to a real photo, photo-like light")
    a = ap.parse_args()
    if a.contact_sheet:
        items = []
        for f in a.files:
            pts = tc.read_thr(f)
            items.append((os.path.splitext(os.path.basename(f))[0], tc.est_minutes(pts), f))
        contact_sheet(items, a.contact_sheet, a.thumb, a.cols, a.real)
        print("wrote", a.contact_sheet)
        return
    if not a.files or not a.out:
        ap.error("need FILE.thr and -o out.png (or --contact-sheet)")
    if a.stack:
        im = render([tc.read_thr(f) for f in a.files], a.size, real=a.real)
    else:
        if len(a.files) != 1:
            ap.error("several files need --stack")
        im = render(tc.read_thr(a.files[0]), a.size, real=a.real)
    im.save(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
