#!/usr/bin/env python3
"""Draw a .thr pattern on the 36-inch table and check it with the camera.
  big_draw.py pattern.thr [--shots SECONDS] [--vball MM_S] [--rmax STEPS]
Uploads the pattern (POST /thr), starts /play and polls /status. With --shots it pauses the drawing every SECONDS,
photographs the ball, logs the firmware's counters next to the camera's reading, and continues. The log
(captures/big-qual/big_draw.jsonl) holds one line per stop: carriage and arm from the counters, radius and angle from
the camera, and the difference in mm. Refuses to start unless the table is idle, homed and fault-free."""
import sys, math, urllib.request
from big_lib import *
import numpy as np, cv2
cal = json.load(open(ROOT + '/firmware-notes/big-camera-calibration.json'))
Hi = np.linalg.inv(np.array(cal['H_table_steps_to_image']))
args = sys.argv[1:]; opt = {}
while len(args) > 1 and args[-2].startswith('--'):
    opt[args[-2][2:]] = float(args[-1]); args = args[:-2]
thr = args[0]


def cam(tag='draw_last'):
    p = ball(tag)
    t = cv2.perspectiveTransform(np.array([[p[:2]]], np.float64), Hi)[0, 0]
    return float(t[0]), float(t[1])


def compare(what):
    s = status(); m = s['move']
    x, y = cam()
    th = 2 * math.pi * m['a'] / ARM_TURN
    ex, ey = m['carriage'] * math.cos(th), m['carriage'] * math.sin(th)
    d = {'what': what, 'pt': s['job']['pt'], 'n': s['job']['n'], 'carriage': m['carriage'], 'a': m['a'], 'cam_xy': [round(x), round(y)],
         'exp_xy': [round(ex), round(ey)], 'err_mm': round(math.hypot(x - ex, y - ey) / 160, 1),
         'err_radial_mm': round((math.hypot(x, y) - m['carriage']) / 160, 1), 'fault': m['fault'], 'slip_err': m['slip_err'], 'checks': m['slip_checks']}
    log(d); return s


s = precheck()
if 'vball' in opt or 'rmax' in opt:
    print(get('/cfg?' + '&'.join('%s=%g' % (k, opt[k]) for k in ('vball', 'rmax') if k in opt)))
body = open(thr, 'rb').read()
req = urllib.request.Request(T + '/thr', data=body, headers={'Content-Type': 'text/plain'}, method='POST')
up = urllib.request.urlopen(req, timeout=60).read().decode().strip(); log({'what': 'upload', 'file': thr, 'reply': up})
compare('before')
rep = get('/play'); log({'what': 'play', 'reply': rep, 'epoch': time.time()})
if 'playing' not in rep:
    raise SystemExit(rep)
shots = opt.get('shots', 0); last = time.time()
while True:
    s = status()
    if not s['job']['run']:
        break
    if shots and time.time() - last >= shots:
        get('/pause?on=1'); t = time.time()
        while not status()['job']['paused'] and status()['job']['run'] and time.time() - t < 20:
            time.sleep(0.1)
        if status()['job']['run']:
            compare('paused')
        get('/pause?on=0'); last = time.time()
    time.sleep(0.5)
s = compare('end'); j = s['job']
log({'what': 'done', 'end': j['end'], 'steps': j['steps'], 'ms': j['ms'], 'move': s['move']})
