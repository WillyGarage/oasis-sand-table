#!/usr/bin/env python3
"""Qualification 3: speed and acceleration limits per motor on the 36-inch table, with StallGuard readings.
  big_q3.py radius HZ[,HZ..] [acc=8000] [lo=12000] [hi=42000]   out-and-back radius moves at each top speed
  big_q3.py arm HZ[,HZ..] [acc=8000] [carriage=12000]           one arm turn forward and one back at each top speed
  big_q3.py racc ACC[,ACC..] HZ      8,000-step radius moves out and back at each acceleration
  big_q3.py aacc ACC[,ACC..] HZ [carriage]   quarter turns across the home sensor, there and back
Stops at the first lost position (arm: the firmware's sensor check; radius: the camera), repairs the counters and
exits. Each move logs speed, StallGuard at full speed (median, min) and the camera result."""
import sys, statistics, math
from big_lib import *
import numpy as np, cv2
cal = json.load(open(ROOT + '/firmware-notes/big-camera-calibration.json'))
Hi = np.linalg.inv(np.array(cal['H_table_steps_to_image']))


def rho(tag='q3_last'):
    p = ball(tag)
    t = cv2.perspectiveTransform(np.array([[p[:2]]], np.float64), Hi)[0, 0]
    return float(np.hypot(*t)), p


def sgsum(col, hz):
    d = json.loads(get('/sg'))['s']
    vcol = 1 if col == 3 else 2
    full = [x[col] for x in d if x[vcol] >= 0.95 * hz and x[col] >= 0]
    allv = [x[col] for x in d if x[col] >= 0]
    top = max([x[vcol] for x in d] or [0])
    return {'n': len(d), 'top': top, 'full_n': len(full), 'med': statistics.median(full) if full else None, 'min': min(full) if full else None,
            'min_any': min(allv) if allv else None, 'raw': [[x[0], x[vcol], x[col]] for x in d[::max(1, len(d) // 40)]]}


def go_carriage(c):
    d = c - mv()['carriage']
    if d:
        move(d, 0, 2000, 3000)


def try_move(r, a, hz, acc):
    t0 = time.time()
    try:
        s = move(r, a, hz, acc)
    except RuntimeError as e:
        return None, str(e), time.time() - t0
    return s, None, time.time() - t0


mode = sys.argv[1]; vals = [float(x) for x in sys.argv[2].split(',')]
s = precheck(); m = mv(s)
if not (m['arm_homed'] and m['rad_homed']):
    raise SystemExit('home first: %s' % m)
if mode in ('radius', 'racc'):
    if mode == 'radius':
        acc = float(sys.argv[3]) if len(sys.argv) > 3 else 8000; lo = int(sys.argv[4]) if len(sys.argv) > 4 else 12000
        hi = int(sys.argv[5]) if len(sys.argv) > 5 else 42000; tests = [(hz, acc) for hz in vals]
    else:
        hz = float(sys.argv[3]); lo, hi = 26000, 34000; tests = [(hz, a) for a in vals]
    go_carriage(hi); go_carriage(lo)                 # always arrive at lo moving inward: same backlash state every time
    base, p = rho(); log({'what': 'base', 'mode': mode, 'carriage': lo, 'rho_cam': round(base), 'ball': p})
    for hz, acc in tests:
        out = {'what': mode, 'hz': hz, 'acc': acc, 'epoch': time.time()}
        s1, err, dt = try_move(hi - lo, 0, hz, acc); out['sg_out'] = sgsum(3, hz); out['t_out'] = round(dt, 1)
        s2, err2, dt = try_move(lo - hi, 0, hz, acc); out['sg_in'] = sgsum(3, hz)
        r1, p = rho(); out.update(rho_cam=round(r1), off_steps=round(r1 - base), err=err or err2, fault=mv()['fault'])
        out['lost'] = bool(abs(r1 - base) > 600 or err or err2 or out['fault'])
        log(out)
        if out['lost']:
            get('/fault?clear=1'); get('/setcarriage?c=%d' % round(r1 + (lo - base)))
            log({'what': 'LOST radius position; carriage reset from the camera', 'move': mv()}); break
elif mode in ('arm', 'aacc'):
    if mode == 'arm':
        acc = float(sys.argv[3]) if len(sys.argv) > 3 else 8000; car = int(sys.argv[4]) if len(sys.argv) > 4 else 12000
        tests = [(hz, acc) for hz in vals]; span = ARM_TURN
    else:
        hz = float(sys.argv[3]); car = int(sys.argv[4]) if len(sys.argv) > 4 else 12000; tests = [(hz, a) for a in vals]; span = 9600
    go_carriage(car)
    a0 = -4800 - mv()['a'] % ARM_TURN if mode == 'aacc' else -(mv()['a'] % ARM_TURN) + 4800
    turn(a0 if abs(a0) < ARM_TURN / 2 or mode == 'aacc' else a0 + ARM_TURN, 2000, 3000)
    base, p0 = rho(); log({'what': 'base', 'mode': mode, 'carriage': car, 'a': mv()['a'], 'rho_cam': round(base), 'ball': p0})
    for hz, acc in tests:
        out = {'what': mode, 'hz': hz, 'acc': acc, 'carriage': car, 'epoch': time.time(), 'ball_mm_s': round(hz / ARM_TURN * 2 * math.pi * car / 160)}
        errs = []
        for sign in (1, -1):
            A = mv()['a']; r = (A + sign * span) // 6 - A // 6
            c0 = mv()['edges']
            s1, err, dt = try_move(r, sign * span, hz, acc); k = 'fwd' if sign > 0 else 'back'
            if not err and mv()['edges'] == c0:
                err = 'the arm never reached the home sensor'
            out['sg_' + k] = sgsum(4, hz); out['slip_' + k] = mv()['slip_err']; out['t_' + k] = round(dt, 1); errs.append(err)
            if err or mv()['fault']:
                errs[-1] = err; break
        r1, p = rho(); m = mv()
        out.update(rho_cam=round(r1), ball_off_px=[round(p[0] - p0[0], 1), round(p[1] - p0[1], 1)], err=[e for e in errs if e], fault=m['fault'], checks=m['slip_checks'])
        out['lost'] = bool(m['fault'] or out['err'] or abs(p[0] - p0[0]) + abs(p[1] - p0[1]) > 6)
        log(out)
        if out['lost']:
            h = get('/homearm', 60); r2, p = rho()
            if not mv()['rad_homed']:
                get('/setcarriage?c=%d' % round(r2 + cal['rho0_steps'] * 0 ))
            log({'what': 'LOST arm position; re-homed on the sensor', 'homearm': h, 'rho_cam': round(r2), 'move': mv()}); break
log({'what': 'end', 'move': mv()})
