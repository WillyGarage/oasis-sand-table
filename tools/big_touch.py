#!/usr/bin/env python3
"""Centre-touch experiment on the 36-inch table (Bill allowed it 2026-11-22, camera watching).
The factory method: arm parked a few steps inside the home sensor's rising edge, radius driven inward slowly until the
sensor drops. Here: arm to a = EDGE+inside (approached forward), carriage to START steps, then raw radius pulses inward
at HZ with stop-on-sensor-low, at most START+OVER pulses. Logs where it stopped, the camera before and after, then backs
out 1,600 steps, restores the counters and re-homes the arm (the correction shows whether the arm itself slipped).
Usage: big_touch.py [inside=5] [start=2400] [over=400] [hz=800]"""
import sys, subprocess
from big_lib import *
inside = int(sys.argv[1]) if len(sys.argv) > 1 else 5
start = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
over = int(sys.argv[3]) if len(sys.argv) > 3 else 400
hz = int(sys.argv[4]) if len(sys.argv) > 4 else 800


def where(tag):
    ball(tag)
    w = subprocess.run(['python3', os.path.join(ROOT, 'tools', 'big_where.py'), OUT + '/' + tag + '.jpg'], capture_output=True, text=True).stdout.split()
    return [float(x) for x in w]


def arm_to(mod, hz=700):
    a = mv()['a']; d = (mod - a) % ARM_TURN; d = d - ARM_TURN if d > ARM_TURN / 2 else d
    if d: turn(d, hz, 3000)


def wait_pulse():
    while status()['pulse']['run']: time.sleep(0.1)
    return status()


s = precheck(); m = mv(s)
if not (m['arm_homed'] and m['rad_homed']): raise SystemExit('home first')
arm_to(-1500 % ARM_TURN); arm_to(6 + inside)
d = start - mv()['carriage']
if d: move(d, 0, 2000, 3000)
s = status(); m = mv(s); r0, a0 = m['r'], m['a']
w0 = where('touch_before')
log({'what': 'ready', 'inside': inside, 'carriage': m['carriage'], 'a_mod': a0 % ARM_TURN, 's21': m['s21'], 'cam_rho_deg': w0[:2]})
if not m['s21']: raise SystemExit('sensor is not high at the start')
n = start + over
rep = get('/pulse?step=1&dir=2&dv=1&n=%d&hz=%d&until=21&lv=0' % (n, hz)); s = wait_pulse(); p = s['pulse']
w1 = where('touch_after')
log({'what': 'touch', 'reply': rep, 'pulses': p['done'], 'hit_at': p['hit_at'], 's21': s['move']['s21'], 'cam_rho_deg': w1[:2],
     'carriage_if_no_slip': start - p['done']})
done = p['done']
get('/pulse?step=1&dir=2&dv=0&n=1600&hz=%d' % hz); s = wait_pulse()
w2 = where('touch_backed')
get('/zero?r=%d&a=%d' % (r0 - done + 1600, a0))
h = get('/homearm', 60)
w3 = where('touch_final')
get('/setcarriage?c=%d' % (start - done + 1600))    # keep the counter frame, so repeated touches can be compared
log({'what': 'after', 's21_after_backout': s['move']['s21'], 'cam_after_backout': w2[:2], 'counter_carriage_if_no_slip': start - done + 1600,
     'homearm': h, 'cam_final': w3[:2], 'move': mv()})
