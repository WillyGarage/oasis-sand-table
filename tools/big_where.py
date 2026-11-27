#!/usr/bin/env python3
"""Where is the ball on the 36-inch table? Usage: big_where.py frame.jpg
Prints: radius_steps angle_deg x_px y_px. Uses firmware-notes/big-camera-calibration.json (fitted 2026-11-22 by
tools/big_q2_fit.py from 51 camera positions on three circles, 1.3 px rms, about 1.5 mm) and tools/big_ball.py.
Radius is from the arm's rotation centre in radius-motor steps (160 per mm). Angle 0 is the arm at a = 0 (home sensor)."""
import json, math, subprocess, sys, os
import numpy as np, cv2
here = os.path.dirname(os.path.abspath(__file__))
cal = json.load(open(os.path.join(here, '..', 'firmware-notes', 'big-camera-calibration.json')))
Hi = np.linalg.inv(np.array(cal['H_table_steps_to_image']))
out = subprocess.run(['python3', os.path.join(here, 'big_ball.py'), sys.argv[1]], capture_output=True, text=True).stdout.split()
x, y = float(out[0]), float(out[1])
t = cv2.perspectiveTransform(np.array([[[x, y]]], np.float64), Hi)[0, 0]
print(f"{math.hypot(*t):.0f} {math.degrees(math.atan2(t[1], t[0])):.1f} {x:.1f} {y:.1f}")
