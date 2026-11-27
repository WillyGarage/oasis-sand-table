#!/usr/bin/env python3
"""Test card for tools/section_comb.py: three subject sections (a fanned band, a blob, a block) and two background
sections (5 mm arcs, 5 mm horizontal lines) inside a 76 x 76 mm box, Mini size. SIMULATION ONLY."""
import math, os, sys
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely import affinity
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BOX = 38.0


def card_plan():
    arc = [(-24 + 48 * t, -6 - 14 * math.sin(math.pi * t)) for t in np.linspace(0, 1, 40)]    # a curved spine
    band = LineString(arc).buffer(5.5, cap_style=1)
    blob = affinity.rotate(Point(-12, 14).buffer(1, 64), 20)
    blob = affinity.scale(blob, 11, 7)
    block = Polygon([(8, 4), (27, 8), (24, 26), (6, 22)])
    L = lambda g: [list(map(float, c)) for c in g.exterior.coords][:-1]
    return dict(r_work=114.0, shrink=1.6, bg_gap=2.2, bg_shrink=1.0, sections=[
        dict(name='band', kind='subject', poly=L(band), spacing=1.5, mode='spine', spine=[list(p) for p in arc]),
        dict(name='blob', kind='subject', poly=L(blob), spacing=1.2, mode='angle', angle=20),
        dict(name='block', kind='subject', poly=L(block), spacing=2.3, mode='angle', angle=100),
        dict(name='arcs', kind='background', poly=[[-BOX, -BOX + 30], [BOX, -BOX + 30], [BOX, BOX], [-BOX, BOX]], spacing=5.0,
             mode='rings', center=[-30, 40]),
        dict(name='ground', kind='background', poly=[[-BOX, -BOX], [BOX, -BOX], [BOX, -BOX + 30], [-BOX, -BOX + 30]], spacing=5.0,
             mode='angle', angle=0),
    ])
