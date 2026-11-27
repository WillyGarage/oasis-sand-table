"""Draw a portrait during a whole-tray inward rake, ending on its outline at the rim.

An NPZ stores ordered XY strokes in units of usable tray radius (Y up). The
named exit stroke begins at the center and follows the artwork out to the rim.
Use --spiral-entry NAME to reach a delicate feature along a previously cut
turn of the rake, preserving the blank sand beside it.
Only signed movement files are written. Nothing here contacts the table.
"""
import argparse
import io
import math
from pathlib import Path

import cv2
import numpy as np

from mini_bed_preview import GROOVE_MM, RADIUS_MM
from oasis_player import validate_parts
from thrcommon import MAX_POINTS

PITCH = .020
# One float32 rounding unit in tray radii (about 0.00001 mm on the Mini).
CENTER_EPS = np.finfo(np.float32).eps


def polar_curve(points):
    xy = np.asarray(points, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or len(xy) < 2 or not np.isfinite(xy).all():
        raise ValueError('A stroke needs at least two finite XY positions.')
    if np.max(np.linalg.norm(xy, axis=1)) > 1.0000001:
        raise ValueError('A stroke exceeds the usable Mini tray.')
    # Keep both halves of a closed path in order, including its opening vertex.
    # Bound the simplification in millimeters before sampling Cartesian chords.
    breaks = {0, len(xy)-1, *np.flatnonzero(np.linalg.norm(xy, axis=1) < CENTER_EPS)}
    if np.linalg.norm(xy[-1]-xy[0]) < 1e-7:
        breaks.add(len(xy)//2)
    ordered = sorted(breaks)
    # A stroke can return to center several times, for example after each
    # spectacle lens. OpenCV omits the repeated closing vertex even in open
    # mode. Give each such loop two distinct endpoints before simplifying it.
    for a, b in zip(ordered, ordered[1:]):
        if b > a + 1 and np.linalg.norm(xy[b]-xy[a]) < CENTER_EPS:
            breaks.add(a + int(np.argmax(np.linalg.norm(xy[a:b+1]-xy[a], axis=1))))
    ordered = sorted(breaks)
    pieces = [cv2.approxPolyDP(xy[a:b+1].astype('float32'), .025/RADIUS_MM, False).reshape(-1, 2)
              for a, b in zip(ordered, ordered[1:])]
    vertices = np.vstack([pieces[0], *[piece[1:] for piece in pieces[1:]]]).astype(float)
    path = [xy[0]]
    for a, b in zip(vertices, vertices[1:]):
        n = math.ceil(np.linalg.norm(b-a)*RADIUS_MM/.65)
        if n:
            path.extend(a+(b-a)*np.arange(1, n+1)[:, None]/n)
    if len(path) < 2:
        raise ValueError('A stroke has zero length at this scale.')
    path[-1] = xy[-1]
    q = np.array(path)
    r = np.linalg.norm(q, axis=1).clip(0, 1)
    # A Cartesian chord may pass exactly through the origin between samples.
    # In polar coordinates the ball must reach zero on its incoming bearing,
    # turn at zero radius, and only then move out on the new bearing.
    a, b = q[:-1], q[1:]
    det = a[:, 0]*b[:, 1] - a[:, 1]*b[:, 0]
    crosses = (np.sum(a*b, axis=1) < 0) & (abs(det) <= CENTER_EPS*np.linalg.norm(b-a, axis=1))
    split = np.flatnonzero(crosses & (r[:-1] >= CENTER_EPS) & (r[1:] >= CENTER_EPS)) + 1
    if len(split):
        q = np.insert(q, split, [0., 0.], axis=0)
        r = np.insert(r, split, 0.)
    r[r < CENTER_EPS] = 0.
    keep = np.r_[True, (r[:-1] != 0) | (r[1:] != 0)]
    q, r = q[keep], r[keep]
    if len(q) < 2:
        raise ValueError('A stroke has zero length at this scale.')
    angle = np.arctan2(q[:, 1], q[:, 0])
    if r[0] == 0:
        angle[0] = angle[1]
    if r[-1] == 0:
        angle[-1] = angle[-2]
    interior = np.flatnonzero(r[1:-1] == 0) + 1
    outgoing = angle[interior+1]
    angle[interior] = angle[interior-1]
    angle = np.insert(angle, interior+1, outgoing)
    r = np.insert(r, interior+1, 0.)
    return np.column_stack([np.unwrap(angle), r])


def entry(curve, start_angle, clearance_mm):
    """Find a short radial approach after the inward sweep has cleared the mark."""
    angle, rho = curve.T
    low = rho.min()
    span = math.tau/PITCH
    earliest = start_angle + span * max(0., 1-low+clearance_mm/RADIUS_MM)
    bearing = angle + math.tau*np.ceil((earliest-angle)/math.tau)
    progress = (bearing-start_angle)/span
    stem = rho-(1-progress)
    # Prefer an endpoint if it costs less than a small fraction of a groove.
    cost = stem.copy()
    cost[1:-1] += .13*GROOVE_MM/RADIUS_MM
    cost[(progress > 1) | (stem < 0)] = np.inf
    i = int(cost.argmin())
    if not np.isfinite(cost[i]):
        i = int(rho.argmin())
        return 1., i
    return float(progress[i]), i


def spiral_crossing(curve, start_angle, name, *, pitch=PITCH):
    """Split the signed stroke at its innermost intersection with the inward erase."""
    center = np.flatnonzero(curve[:, 1] == 0)
    if len(center):
        return curve, int(center[0])
    # A signed segment is linear in both axes. Whenever this expression
    # reaches an integer, the stroke and the rake share an exact location.
    phase = (curve[:, 0] - start_angle)/math.tau + (curve[:, 1] - 1)/pitch
    closest = None
    for i, (a, b) in enumerate(zip(phase, phase[1:])):
        for tick in range(math.ceil(min(a, b)-1e-10), math.floor(max(a, b)+1e-10)+1):
            if abs(b-a) < 1e-12:
                fraction = float(curve[i+1, 1] < curve[i, 1])
            else:
                fraction = min(1., max(0., (tick-a)/(b-a)))
            r = curve[i, 1] + fraction*(curve[i+1, 1]-curve[i, 1])
            if closest is None or r < closest[0]:
                closest = (r, i, fraction)
    if closest is None:
        raise ValueError(f'No inward spiral crossing on stroke {name!r}.')
    _, i, fraction = closest
    if fraction <= 1e-10:
        return curve, i
    if fraction >= 1 - 1e-10:
        return curve, i+1
    cross = curve[i] + fraction*(curve[i+1]-curve[i])
    return np.insert(curve, i+1, cross, axis=0), i+1


def visit(curve, i):
    # From the entry visit both ends of an open stroke. A closed mark needs one lap.
    if curve[0, 1] == curve[-1, 1] == 0:
        # Different tangents still meet at the center. Keep both bearings for
        # the stationary turn where the two ends join.
        walk = np.vstack([curve[i:], curve[:i+1]])
    elif abs(curve[0, 1]-curve[-1, 1]) < 1e-7 and abs(math.remainder(curve[-1, 0]-curve[0, 0], math.tau)) < 1e-6:
        walk = np.vstack([curve[i:], curve[1:i+1]])
    else:
        walk = np.vstack([curve[i::-1], curve[1:], curve[-2::-1][:len(curve)-1-i]])
    walk[:, 0] = np.unwrap(walk[:, 0])
    return walk


def compile_portrait(strokes, exit_stroke, start_angle, clearance_mm, *, spiral_entries=()):
    if not np.isfinite([start_angle, clearance_mm]).all() or clearance_mm < 0:
        raise ValueError('Use a finite starting angle and a nonnegative clearance.')
    spiral_entries = set(spiral_entries)
    unknown = spiral_entries.difference(strokes)
    if unknown:
        raise ValueError(f'Unknown spiral-entry strokes: {", ".join(sorted(unknown))}')
    tail = polar_curve(exit_stroke)
    if tail[0, 1] > 1e-7 or abs(tail[-1, 1]-1) > 1e-7:
        raise ValueError('The exit stroke must lead from the center to the rim.')
    path = [np.array([start_angle, 1.])]
    events = []

    def line_to(target, along_art=True):
        origin = path[-1]
        delta = np.asarray(target)-origin
        if np.max(abs(delta)) < 1e-10:
            return
        steps = max(1, math.ceil(abs(delta[0])/.055))
        if along_art:
            extent = abs(delta[0])*max(origin[1], target[1])+abs(delta[1])
            steps = max(steps, math.ceil(extent*RADIUS_MM/.85))
        path.extend(origin+delta*np.arange(1, steps+1)[:, None]/steps)

    def trace(curve):
        shift = math.tau*round((path[-1][0]-curve[0, 0])/math.tau)
        for theta, r in curve:
            line_to([theta+shift, r])

    jobs = []
    for name, points in strokes.items():
        curve = polar_curve(points)
        crossing = None
        if name in spiral_entries:
            curve, i = spiral_crossing(curve, start_angle, name)
            crossing = 1. - curve[i, 1]
            u = min(1., 1. - curve[:, 1].min() + clearance_mm/RADIUS_MM)
        else:
            u, i = entry(curve, start_angle, clearance_mm)
        jobs.append((u, name, visit(curve, i), crossing))
    turns = 0.
    for u, name, walk, crossing in sorted(jobs, key=lambda job: job[0]):
        theta = start_angle+u*math.tau/PITCH+turns
        line_to([theta, 1-u], along_art=False)
        if crossing is None:
            if u == 1.:
                # At the center set the bearing before moving radially out.
                line_to([theta+math.remainder(walk[0, 0]-theta, math.tau), 0])
            anchor = len(path)-1
            line_to([path[-1][0], walk[0, 1]])
        else:
            anchor = len(path)-1
            bearing = start_angle + crossing*math.tau/PITCH + turns
            line_to([bearing, 1-crossing], along_art=False)
            if crossing == 1.:
                line_to([bearing+math.remainder(walk[0, 0]-bearing, math.tau), 0])
        angle = path[-1][0]
        first = len(path)-1
        trace(walk)
        last = len(path)-1
        turns += math.tau*round((path[-1][0]-angle)/math.tau)
        if crossing is None:
            line_to([path[-1][0], 1-u])
        elif crossing < 1.:
            line_to([start_angle+u*math.tau/PITCH+turns, 1-u], along_art=False)
        if u == 1.:
            line_to([start_angle+u*math.tau/PITCH+turns, 0])
        event = dict(label=name, anchor=anchor, first=first, last=last, back=len(path)-1)
        if crossing is not None:
            event.update(entryKind='spiral', crossingProgress=float(crossing))
        events.append(event)
    line_to([start_angle+math.tau/PITCH+turns, 0], along_art=False)
    center = len(path)-1
    line_to([path[-1][0]+math.remainder(tail[0, 0]-path[-1][0], math.tau), 0])
    first = len(path)-1
    trace(tail)
    events.append(dict(label='exit', atCenter=center, first=first, last=len(path)-1))
    return np.array(path), events


def movement_files(path):
    parts = []
    for i in range(0, len(path)-1, MAX_POINTS-1):
        content = io.StringIO()
        np.savetxt(content, path[i:i+MAX_POINTS], fmt='%.8f')
        parts.append(dict(name=f'portrait-{len(parts)+1}.thr', text=content.getvalue()))
    validate_parts(parts)
    return parts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('strokes', type=Path)
    parser.add_argument('out', type=Path, help='New directory for ordered movement files')
    parser.add_argument('--start-angle', type=float, required=True, help='Signed starting angle at the rim, radians')
    parser.add_argument('--clearance-mm', type=float, default=.6*GROOVE_MM)
    parser.add_argument('--omit', action='append', default=[], help='Omit this archived stroke')
    parser.add_argument('--spiral-entry', action='append', default=[], metavar='NAME',
                        help='Follow the existing inward groove to this stroke and back. Repeat for multiple strokes.')
    args = parser.parse_args()
    with np.load(args.strokes, allow_pickle=False) as archive:
        strokes = {key: archive[key] for key in archive.files if key != 'exit' and key not in args.omit}
        path, _ = compile_portrait(strokes, archive['exit'], args.start_angle, args.clearance_mm,
                                   spiral_entries=args.spiral_entry)
    parts = movement_files(path)
    args.out.mkdir(parents=True, exist_ok=False)
    for part in parts:
        (args.out/part['name']).write_text(part['text'], encoding='ascii')
