#!/usr/bin/env python3
"""Find the steel ball on the 36-inch table's tray in one frame from the USB camera (index 1, 1920x1080).
Prints "x y score" in full-frame pixels. Read-only.
Method (2026-11-22, bare tray lit by the ring): fit the lit rim as an ellipse, then inside 85% of it take the spot
with the largest local brightness range (the ball's highlight sits beside its near-black reflection).
Usage: big_ball.py frame.jpg"""
import sys, cv2, numpy as np
g = cv2.cvtColor(cv2.imread(sys.argv[1]), cv2.COLOR_BGR2GRAY)
# the lit rim is the largest bright ring: fit an ellipse to it, search inside 85% of it
bright = (cv2.blur(g, (9, 9)) > 150).astype(np.uint8)
cs, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
(ex, ey), (ew, eh), ea = cv2.fitEllipse(max(cs, key=cv2.contourArea))
tray = np.zeros_like(g, np.uint8)
cv2.ellipse(tray, ((ex, ey), (ew * 0.85, eh * 0.85), ea), 255, -1)
tray = tray > 0
# the ball is a tiny spot with a bright highlight right next to a near-black reflection: the largest local
# brightness range (max minus min over 7x7) inside the tray. The tray itself is smooth.
k7 = np.ones((7, 7), np.uint8)
rng = (cv2.dilate(g, k7).astype(np.int16) - cv2.erode(g, k7).astype(np.int16)).astype(np.float32)
rng[~tray] = 0
rng = cv2.GaussianBlur(rng, (5, 5), 0)
_, mx, _, (bx, by) = cv2.minMaxLoc(rng)
win = rng[by - 6:by + 7, bx - 6:bx + 7]
w = np.clip(win - 0.6 * mx, 0, None)
ys, xs = np.nonzero(w)
xs = (w[w > 0] * xs).sum() / w.sum(); ys = (w[w > 0] * ys).sum() / w.sum()
xs, ys = np.array([xs]), np.array([ys])
bx, by = bx + 2, by + 2   # so the "- 8" below lands on the window origin (by - 6)
print(f"{xs.mean() + bx - 8:.1f} {ys.mean() + by - 8:.1f} {mx:.0f}" if len(xs) else "none",
      f"ellipse {ex:.0f} {ey:.0f} {ew:.0f} {eh:.0f} {ea:.1f}" if "-v" in sys.argv else "")
