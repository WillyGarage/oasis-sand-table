#!/usr/bin/env python3
"""Power-cut recovery test on the 36-inch table: for each carriage position given, go there (and to an odd arm angle),
make the firmware forget the position (/enable off and on), run /homearm and /homeradius, then move to carriage 20,000
and compare the counters with the camera. Usage: big_home_test.py 1550,30000,56000 [hz=1600]"""
import sys, subprocess
from big_lib import *


def where(tag='home_t'):
    ball(tag)
    return [float(x) for x in subprocess.run(['python3', os.path.join(ROOT, 'tools', 'big_where.py'), OUT + '/' + tag + '.jpg'], capture_output=True, text=True).stdout.split()]


hz = sys.argv[2] if len(sys.argv) > 2 else '1600'
for k, c in enumerate(int(x) for x in sys.argv[1].split(',')):
    precheck()
    while abs(c - mv()['carriage']) > 1:
        move(max(-8000, min(8000, c - mv()['carriage'])), 0, 3000, 8000)
    turn(5000 + 7000 * k, 3000, 8000)
    before = where()
    get('/enable?on=0'); time.sleep(1.0); get('/enable?on=1'); time.sleep(0.3)
    t0 = time.time(); h1 = get('/homearm', 90)
    rep = get('/homeradius?hz=' + hz)
    while status()['move']['home'] == 1: time.sleep(0.3)
    m = mv(); dt = time.time() - t0
    out = {'what': 'home', 'start_carriage': c, 'cam_before': before[:2], 'homearm': h1, 'reply': rep, 'state': m['home'], 'went': m['home_went'], 'secs': round(dt, 1), 'fault': m['fault']}
    if m['home'] == 2:
        move(20000 - m['carriage'], 0, 3000, 8000); w = where(); m = mv()
        out.update(carriage=m['carriage'], cam_rho=w[0], diff_mm=round((w[0] - m['carriage']) / 160, 1))
    log(out)
    if m['home'] != 2: break
