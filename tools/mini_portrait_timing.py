"""Estimate Mini playback time from a recorded controller status and signed portrait.

The ball starts at the drawing's first point. All elapsed times exclude loading,
homing, pauses and separate erases. A center turn consumes motor time even when
the ball travels no distance across the sand. The speed estimate follows the
firmware's corner limits with continuous acceleration and full-route lookahead.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np


def motor_positions(route, calibration):
    """Inverse kinematics in full steps, up to constant motor offsets."""
    theta, rho = route.T
    radius = np.clip(rho, 0, 1) * calibration['rmax']
    elbow = math.tau - 2 * np.arcsin(np.minimum(.999, radius / (2 * calibration['l'])))
    a, a1, b1, b2 = (calibration[key] for key in ('a', 'a1', 'b1', 'b2'))
    determinant = -a*b1 - a1*b2
    return np.column_stack(((a*elbow - b2*theta) / determinant,
                            (-b1*theta - a1*elbow) / determinant))


def elapsed_seconds(route, status):
    """Return cumulative seconds at each source row, including stationary rows."""
    route = np.asarray(route, dtype='float32').astype(float)  # firmware stores each point as two floats
    if route.ndim != 2 or route.shape[1] != 2 or not len(route) or not np.isfinite(route).all():
        raise ValueError('Expected at least one finite theta/rho position.')
    if np.any((route[:, 1] < 0) | (route[:, 1] > 1)):
        raise ValueError('The drawing extends beyond the Mini radius.')
    vmax, join, accel, corner = (float(status[k]) for k in ('vmax', 'vj', 'acc', 'accc'))
    calibration = status['cal']
    if not all(math.isfinite(v) and v > 0 for v in (vmax, join, accel, corner, calibration['l'], calibration['rmax'])):
        raise ValueError('Expected a calibrated Mini with positive speed and acceleration settings.')
    terms = [calibration[k] for k in ('a', 'a1', 'b1', 'b2')]
    if not np.isfinite(terms).all() or terms[0]*terms[2] + terms[1]*terms[3] == 0:
        raise ValueError('The angular calibration cannot resolve both motors.')
    path = motor_positions(route, calibration)
    # Only differences matter when starting at the dock. One full step has 16 ticks.
    ticks = np.rint((path - path[0]) * 16)
    distinct = np.r_[True, np.any(np.diff(ticks, axis=0) != 0, axis=1)]
    if np.count_nonzero(distinct) == 1:
        return np.zeros(len(route))
    lengths = np.max(abs(np.diff(ticks[distinct], axis=0)), axis=1) / 16
    delta = np.diff(path[distinct], axis=0)
    directions = delta / np.max(abs(delta), axis=1)[:, None]
    change = np.maximum(1e-8, np.max(abs(np.diff(directions, axis=0)), axis=1))
    # The firmware limits the instantaneous change in either motor's velocity
    # and also imposes corner acceleration relative to adjacent segment lengths.
    junction = np.minimum((min(join, vmax) / change)**2, corner * .5 * (lengths[1:] + lengths[:-1]) / change)
    junction = np.clip(junction, min(40., vmax)**2, vmax**2)
    end_speed_sq = min(join, vmax)**2
    limits = np.r_[end_speed_sq, junction, end_speed_sq]
    for i in range(len(lengths)-1, -1, -1):
        limits[i] = min(limits[i], limits[i+1] + 2*accel*lengths[i])
    for i, length in enumerate(lengths):
        limits[i+1] = min(limits[i+1], limits[i] + 2*accel*length)
    # A short segment has a triangular speed profile. A longer one reaches
    # cruise speed between the acceleration and braking portions.
    peak_sq = np.minimum(vmax**2, accel*lengths + .5*(limits[:-1] + limits[1:]))
    cruise = np.maximum(0., lengths - (2*peak_sq - limits[:-1] - limits[1:]) / (2*accel))
    seconds = (2*np.sqrt(peak_sq) - np.sqrt(limits[:-1]) - np.sqrt(limits[1:])) / accel + cruise / np.sqrt(peak_sq)
    return np.r_[0., np.cumsum(seconds)][np.cumsum(distinct)-1]


if __name__ == '__main__':
    from mini_inward_preview import read_parts
    from oasis_player import PlaybackError

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('status', type=Path, help='JSON from the Mini /status endpoint at the drawing speed')
    cli.add_argument('route', type=Path, nargs='+', help='Movement file(s) in playback order with matching endpoints')
    cli.add_argument('--row', type=int, help='Estimate at this one-based row of the joined drawing')
    args = cli.parse_args()
    try:
        times = elapsed_seconds(read_parts(args.route), json.loads(args.status.read_text()))
        row = len(times) if args.row is None else args.row
        if not 1 <= row <= len(times):
            raise ValueError('Choose a row inside the drawing.')
        print(json.dumps(dict(row=row, estimatedSeconds=round(float(times[row-1]), 1))))
    except (KeyError, ValueError, OSError, PlaybackError) as error:
        cli.exit(2, f'{error}\n')
