#!/usr/bin/env python3
"""Qualification 2: camera calibration data. The ball traces circles at three carriage radii (arm turns with the
radius held), 16 stops per turn with a camera frame at each, then a radial line out and back at one arm angle.
Logs counters, camera pixels and the home-sensor edges seen on each circle. Fit with big_q2_fit.py.
Usage: big_q2_circles.py [hz_arm=2000] [hz_radius=1500]"""
import sys
from big_lib import *

hza = float(sys.argv[1]) if len(sys.argv) > 1 else 2000
hzr = float(sys.argv[2]) if len(sys.argv) > 2 else 1500
RADII = [12000, 30000, 48000]             # carriage steps from the firmware's zero (10 mm inside its homing point)
s = precheck()
if not (mv(s)['arm_homed'] and mv(s)['rad_homed']):
    raise SystemExit('home first')


def shot(kind, tag):
    m = mv()
    p = ball('q2_last')
    log({'what': kind, 'tag': tag, 'r': m['r'], 'a': m['a'], 'carriage': m['carriage'], 'ball': p, 'fault': m['fault']})
    if m['fault']:
        raise SystemExit('fault')


def go_radius(c):
    d = c - mv()['carriage']
    if d:
        move(d, 0, hzr, 3000)


for c in RADII:
    go_radius(c)
    edges()
    shot('circle', c)
    for k in range(16):
        turn(ARM_TURN // 16, hza, 3000)
        shot('circle', c)
    log({'what': 'edges', 'tag': c, 'dir': 1, 'edges': [[x[1] % ARM_TURN, x[2]] for x in edges()]})
    turn(-ARM_TURN, hza, 3000)             # unwind so the arm counter stays small, and log the reverse edges
    log({'what': 'edges', 'tag': c, 'dir': -1, 'edges': [[x[1] % ARM_TURN, x[2]] for x in edges()]})
    shot('circle_back', c)
line = list(range(6000, 50001, 4000))
for c in line[::-1] + line:
    go_radius(c)
    shot('line', c)
go_radius(32000)
shot('end', 32000)
log({'what': 'done2'})
