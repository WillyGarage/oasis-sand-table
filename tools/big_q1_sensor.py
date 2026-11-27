#!/usr/bin/env python3
"""Qualification 1: the arm home sensor (GPIO21). Full arm turns each way with the radius held, logging where the
sensor switches (both edges, arm counter modulo one turn) and the ball's camera position before and after each turn.
Usage: big_q1_sensor.py [turns_each_way=4] [hz=2000]"""
import sys
from big_lib import *

n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
hz = float(sys.argv[2]) if len(sys.argv) > 2 else 2000
s = precheck()
edges()                                   # clear the log
p0 = ball('q1_start')
log({'what': 'start', 'move': mv(s), 'ball': p0, 'hz': hz})
for sign in (+1, -1, +1, -1):
    for k in range(n if sign > 0 or True else n):
        s = turn(sign * ARM_TURN, hz, 3000)
        e = edges()
        p = ball('q1_last')
        m = mv(s)
        log({'what': 'turn', 'dir': sign, 'k': k, 'a': m['a'], 'r': m['r'], 'fault': m['fault'], 'slip_err': m['slip_err'],
             'edges': [[x[1], x[1] % ARM_TURN, x[2]] for x in e], 'ball': p, 'ball_err_px': [round(p[0] - p0[0], 1), round(p[1] - p0[1], 1)]})
        if m['fault'] or abs(p[0] - p0[0]) + abs(p[1] - p0[1]) > 6:
            log({'what': 'ABORT: fault or ball off by more than 6 px'})
            sys.exit(1)
log({'what': 'done', 'move': mv()})
