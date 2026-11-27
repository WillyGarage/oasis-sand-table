"""Shared constants and helpers for .thr (theta-rho) files.

A .thr file is text, one "theta rho" pair per line. theta is radians and
cumulative (keeps growing over many turns), rho is 0 (centre) .. 1 (rim).
The ball moves in straight lines in (theta, rho) space between points.

Everything that depends on the table's (provisional) speed lives HERE so it can
be recalibrated in one place:

    time_seconds = sum(max(|dtheta| * STEPS_PER_RAD, |drho| * STEPS_PER_RHO)
                       * SECONDS_PER_STEP)
"""
import base64
import hashlib
import json

import numpy as np

# --- provisional table constants (re-measure on the real table) --------------
STEPS_PER_RAD = 1660.0      # theta axis steps per radian
STEPS_PER_RHO = 3000.0      # radial axis steps for rho 0 -> 1
SECONDS_PER_STEP = 0.0035   # seconds per step
# --- hard limits / design rules ----------------------------------------------
MAX_POINTS = 12000          # firmware limit per file
MAX_DTHETA = np.radians(1.5)  # guideline: max theta step between points
MAX_DRHO = 0.01             # guideline: max rho step between points
GROOVE = 0.04               # groove width as a fraction of tray radius
MIN_LINE_GAP = 0.035        # lines closer than this merge


def read_thr(path):
    """Return an (N, 2) float array of (theta, rho)."""
    a = np.loadtxt(path, dtype=float, ndmin=2)
    return a[:, :2]


def motion_files_hash(files):
    """Hash the ordered part names and exact text, including final newlines."""
    parts = [(part['name'], part['text']) for part in files]
    encoded = json.dumps(parts, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def unpack_path(encoded):
    deltas = np.frombuffer(base64.b64decode(encoded, validate=True), dtype='<i4').reshape(-1, 2)
    return np.cumsum(deltas, axis=0, dtype=np.int64) / 1e8


def thr_lines(pts):
    for th, r in np.asarray(pts, dtype=float):
        yield f"{th:.5f} {min(1.0, max(0.0, r)):.5f}\n"


def write_thr(path, pts):
    with open(path, "w") as f:
        f.writelines(thr_lines(pts))


def est_seconds(pts):
    """Estimated draw time in seconds for an (N,2) theta/rho array."""
    pts = np.asarray(pts, dtype=float)
    if len(pts) < 2:
        return 0.0
    d = np.abs(np.diff(pts, axis=0))
    steps = np.maximum(d[:, 0] * STEPS_PER_RAD, d[:, 1] * STEPS_PER_RHO)
    return float(steps.sum() * SECONDS_PER_STEP)


def est_minutes(pts):
    return est_seconds(pts) / 60.0


def to_xy(pts):
    """(theta, rho) -> unit-disc x, y (y up)."""
    pts = np.asarray(pts, dtype=float)
    return pts[:, 1] * np.cos(pts[:, 0]), pts[:, 1] * np.sin(pts[:, 0])


def rotate_xy(points, angle):
    """Rotate Cartesian drawing points counterclockwise, with y up."""
    c, s = np.cos(angle), np.sin(angle)
    return np.asarray(points) @ np.array([[c, s], [-s, c]])
