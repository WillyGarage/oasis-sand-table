#!/usr/bin/env python3
"""Clearing-speed test on the 36-inch table: a band cleared as concentric strips, each strip at its own ball speed.
  big_speed_test.py OUTDIR R_OUT_MM R_IN_MM SPEED1 [SPEED2 ...]
Strips are equal width, from R_OUT inward, 2.5 mm spacing, a whole number of turns each starting and ending at theta 0,
so the ball should finish every strip at a known spot. After each strip: fault check, the firmware's counters, and a
camera frame plus a close crop around where the ball should be (the camera's own ball finder stops at about 335 mm, so
the crops are for looking at). Stops at the first fault. Ball speed is put back to 40 mm/s at the end, fault or not."""
import sys, os, json, time, math, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from big_lib import status, get, ROOT, ARM_TURN
import numpy as np, cv2

out, r_out, r_in = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
speeds = [float(v) for v in sys.argv[4:]]
os.makedirs(out, exist_ok=True)
H = np.array(json.load(open(os.path.join(ROOT, 'firmware-notes/big-camera-calibration.json')))['H_table_steps_to_image'])
LOG = open(os.path.join(out, 'speed_test.jsonl'), 'a')


def log(d):
    d['t'] = time.strftime('%H:%M:%S'); s = json.dumps(d); print(s, flush=True); LOG.write(s + '\n'); LOG.flush()


def wait(tag, limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        s = status(); m, j = s['move'], s['job']
        if m['fault']:
            get('/stop'); log({'what': 'FAULT', 'tag': tag, 'move': m}); return None
        if not j['run'] and not m['run']:
            return s
        time.sleep(0.5)
    get('/stop'); log({'what': 'TIMEOUT', 'tag': tag}); return None


def shot(tag, s):
    f = os.path.join(out, tag + '.jpg')
    subprocess.run([os.path.join(ROOT, 'tools/cam.sh'), f, '1'], env=dict(os.environ, OASIS_EXP='-6'), capture_output=True, timeout=90)
    m = s['move']; th = 2 * math.pi * m['a'] / ARM_TURN
    p = cv2.perspectiveTransform(np.array([[[m['carriage'] * math.cos(th), m['carriage'] * math.sin(th)]]], np.float64), H)[0, 0]
    img = cv2.imread(f)
    if img is not None:
        x, y = int(p[0]), int(p[1]); h, w = img.shape[:2]
        crop = img[max(0, y - 70):min(h, y + 70), max(0, x - 70):min(w, x + 70)].copy()
        cv2.circle(crop, (min(70, x), min(70, y)), 14, (0, 0, 255), 1)
        cv2.imwrite(os.path.join(out, tag + '-ball.png'), cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    return [round(float(p[0])), round(float(p[1]))]


s = status()
rmax = s['cfg']['rmax']; mm = rmax / 160.0
assert not s['job']['run'] and not s['move']['run'] and not s['move']['fault'], s['move']
assert r_out <= mm + 0.01, ('r_out beyond rho 1', r_out, mm)
w = (r_out - r_in) / len(speeds); turns = max(1, round(w / 2.5))
log({'what': 'start', 'rmax': rmax, 'strips': len(speeds), 'width_mm': w, 'turns': turns, 'speeds': speeds})
try:
    get('/cfg?vball=40')
    get('/goto?th=0&rho=%.5f' % (r_out / mm))
    if not wait('to start', 120):
        sys.exit(1)
    for k, v in enumerate(speeds):
        a, b = r_out - k * w, r_out - (k + 1) * w
        get('/cfg?vball=%g' % v)
        rep = get('/spiral?from=%.5f&to=%.5f&pitch=%.6f' % (a / mm, b / mm, (a - b) / mm / turns))
        t0 = time.time()
        s = wait('strip %d' % k, 1200)
        if not s:
            sys.exit(1)
        m = s['move']; secs = time.time() - t0
        px = shot('strip%d-%gmm_s' % (k, v), s)
        log({'what': 'strip', 'k': k, 'speed': v, 'from_mm': round(a, 1), 'to_mm': round(b, 1), 'reply': rep, 'secs': round(secs, 1),
             'length_m': round(2 * math.pi * (a + b) / 2 * turns / 1000, 2), 'carriage': m['carriage'], 'a_mod': m['a'] % ARM_TURN,
             'slip_checks': m['slip_checks'], 'slip_err': m['slip_err'], 'sg_avg': m['sg_avg'], 'expected_px': px})
finally:
    get('/cfg?vball=40')
    log({'what': 'end', 'vball': status()['cfg']['vball']})
