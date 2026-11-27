#!/usr/bin/env python3
"""section_sim - run tools/sand_relief_sim.py on a WINDOW of the Mini tray (or the whole tray) so close-ups can be
simulated at 0.1 mm/px without simulating 240 x 240 mm. SIMULATION ONLY. Does not edit sand_relief_sim.py.

    T = WinTable(cx, cy, size_mm, px=0.1, deposit='push')      # window centred at (cx, cy) mm, square
    T.erase_window(pitch_frac)                                  # the table's erase spiral, clipped to the window
    T.run(tr)                                                   # a theta/rho path (tools/thrcommon.py)
    im = T.render_win()                                         # PIL image of the window, maker-like light
"""
import math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sand_relief_sim as sim

LOOK = dict(tint=(0.90, 0.95, 1.0))      # same look as tools/relief_showcase.py


class WinTable(sim.Table):
    def __init__(self, cx=0.0, cy=0.0, size=None, px=0.1, kind='mini', **phys):
        g = dict(sim.MINI if kind == 'mini' else sim.BIG)
        self.kind = kind
        self.r_work, self.px = g['r_work'], px
        self.p = sim._merge_phys(dict(dict(deposit='push'), **phys)) if hasattr(sim, '_merge_phys') else dict(sim.PHYS, **dict(dict(deposit='push'), **phys))
        self.r_tray = self.r_work + g['tray_extra']
        self.cx, self.cy = cx, cy
        size = size or 2 * (self.r_tray + 3)
        self.N = int(math.ceil(size / px)) | 1
        self.c = self.N / 2.0
        yy, xx = np.mgrid[0:self.N, 0:self.N]
        wx = cx + (xx + 0.5 - self.c) * px
        wy = cy - (yy + 0.5 - self.c) * px
        self.rr = np.hypot(wx, wy)
        self.tray = self.rr <= self.r_tray
        if self.p.get('deposit') == 'real':          # the v4 avalanche needs a 2-px wall round the window
            self.tray[:2, :] = False; self.tray[-2:, :] = False; self.tray[:, :2] = False; self.tray[:, -2:] = False
        self.h = np.where(self.tray, self.p['depth'], 0.0).astype(np.float64)

    def to_px(self, x_mm, y_mm):
        return self.c + (x_mm - self.cx) / self.px - 0.5, self.c - (y_mm - self.cy) / self.px - 0.5

    def erase_window(self, pitch_frac=0.035):
        self.erase(pitch_frac)          # Table.erase builds the spiral as theta/rho and calls self.run: fine in a window

    def render_win(self, **kw):
        k = dict(LOOK); k.update(kw)
        crop = (self.N / 2.0 * self.px) / (self.r_tray + 2.5)     # makes Table.render crop exactly the window
        return self.render(light=k.pop('light', 'ring'), crop=crop, **k)


def thr_window(tr, cx, cy, half, r_work=114.0, margin=12.0):
    """Keep only the parts of a theta/rho path within `half + margin` mm of (cx, cy) (several pieces would be cut and
    their ends are not joined, so use this for the pre-existing drawing, not for the path under test)."""
    tr = np.asarray(tr, float)
    x, y = tr[:, 1] * r_work * np.cos(tr[:, 0]), tr[:, 1] * r_work * np.sin(tr[:, 0])
    ok = (np.abs(x - cx) < half + margin) & (np.abs(y - cy) < half + margin)
    return tr[ok]
