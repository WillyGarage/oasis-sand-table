"""Draw a Mini portrait on fine, evenly spaced turns centered on its outline.

The NPZ contains strokes in tray coordinates (usable radius one, Y up). Its
'exit' starts at the off-center point where the erase ends and follows actual
artwork to the rim. The opening dock is a signed angle at the rim. Only local
movement files and a record of their exact row numbers are written.

  mini_offset_portrait.py strokes.npz output --start-angle 639.84726712
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

from mini_bed_preview import GROOVE_MM, RADIUS_MM
from mini_inward_portrait import CENTER_EPS, movement_files, polar_curve, spiral_crossing, visit


def compact_signed(route, required, tolerance_mm=.018):
    """Coalesce adjacent polar-linear steps while bounding the whole trajectory.

    With theta scaled by the largest radius, Euclidean distance in this local
    polar plane bounds the displacement in the tray. Both paths are linear in
    the polar plane, so checking the vertices also bounds the intervening edges.
    Preserve reversals, center turns and the controller's angular step limit.
    """
    bounds = sorted({*required, len(route)-1})
    chosen = [0]
    for stop in bounds:
        while chosen[-1] < stop:
            first = chosen[-1]
            kept = first+1
            for last in range(first+2, min(stop+1, first+22)):
                points = route[first:last+1]
                angle, radius = points[-1]-points[0]
                if abs(angle) > .055000005 or abs(radius) > .045:
                    break
                if min(points[0, 1], points[-1, 1]) > 0 and points[:, 1].min() == 0:
                    break
                relative = (points-points[0]) * [max(points[:, 1].max(), 1e-6)*RADIUS_MM, RADIUS_MM]
                end = relative[-1]
                length_squared = end @ end
                if length_squared < 1e-14:
                    break
                progress = (relative @ end)/length_squared
                error = np.linalg.norm(relative-progress[:, None]*end, axis=1)
                if (np.diff(progress) < -1e-7).any() or error.max() > tolerance_mm:
                    break
                kept = last
            chosen.append(kept)
    return np.array(chosen)


def rim_orders(sections, jobs, xy, dock):
    """Minimize rim travel between consecutively smaller arcs."""
    states = [(0., dock, [])]
    for i, (a, b) in enumerate(sections):
        fresh = []
        # Keep every feature and the final approach to the erase center in
        # order. Only a clipped section containing pure erase can be reversed.
        directions = (False, True) if not jobs[i] and i+1 < len(sections) else (False,)
        for reverse in directions:
            start, finish = xy([b, a] if reverse else [a, b])
            entry = math.atan2(start[1], start[0])
            leave = math.atan2(finish[1], finish[0])
            options = [(cost+abs(math.remainder(entry-old, math.tau)), leave, order+[reverse])
                       for cost, old, order in states]
            fresh.append(min(options, key=lambda state: state[0]))
        states = fresh
    return min(states, key=lambda state: state[0])[2]


def compile_offset_portrait(strokes, outline, dock, spacing_mm=1.85):
    """Return signed movements and their feature and erase row boundaries."""
    outline = np.asarray(outline, dtype=float)
    polar_curve(outline)
    center = outline[0]
    extent = 1 + np.linalg.norm(center)
    if not np.isfinite(dock) or not np.isfinite(spacing_mm) or not 0 < spacing_mm <= GROOVE_MM:
        raise ValueError(f'Use a finite starting angle and positive spacing up to the {GROOVE_MM} mm groove width.')
    if not 1+CENTER_EPS < extent < 2. or abs(np.linalg.norm(outline[-1])-1) > 1e-7:
        raise ValueError('The outline must start inside the tray, away from center, and end at the rim.')
    pitch = spacing_mm/(RADIUS_MM*extent)
    curves = {}
    for name, stroke in strokes.items():
        points = np.asarray(stroke, dtype=float)
        polar_curve(points)
        curves[name] = polar_curve((points-center)/extent)

    # Changing the opening phase by a fraction of a turn can put a genuine
    # groove beneath a short mark without moving the mark on the photograph.
    for offset in np.arange(32)*math.tau/32:
        opening = math.atan2(-center[1], -center[0]) + offset
        try:
            crossings = {name: spiral_crossing(curve, opening, name, pitch=pitch)
                         for name, curve in curves.items()}
        except ValueError:
            continue
        break
    else:
        raise ValueError('At this spacing some selected strokes never cross an erase groove.')
    finish = math.tau/pitch

    def xy(turn):
        turn = np.asarray(turn)
        angle = opening+turn
        return center + (extent*(1-turn/finish))[..., None]*np.stack([np.cos(angle), np.sin(angle)], axis=-1)

    def boundary(turn):
        return np.linalg.norm(xy(turn), axis=-1)-1

    probes = np.linspace(0, finish, math.ceil(finish/.012)+1)
    distance = boundary(probes)
    crossings_with_rim = [brentq(boundary, probes[i], probes[i+1])
                          for i in np.flatnonzero(distance[:-1]*distance[1:] < 0)]
    cuts = [0., *crossings_with_rim, finish]
    sections = [(a, b) for a, b in zip(cuts, cuts[1:])
                if b-a > 1e-7 and boundary((a+b)/2) < 0]
    jobs = [[] for _ in sections]
    for name, (curve, index) in crossings.items():
        turn = (1-curve[index, 1])*finish
        section = next((i for i, (a, b) in enumerate(sections) if a-1e-7 <= turn <= b+1e-7), None)
        if section is None:
            raise ValueError(f'The erase crossing for {name!r} is outside the physical tray.')
        walk = visit(curve, index)
        stroke = center + extent*walk[:, 1, None]*np.stack([np.cos(walk[:, 0]), np.sin(walk[:, 0])], axis=1)
        # Let the leading edge pass the mark before engraving. Backtrack
        # on the same cut, with a rim intersection limiting the excursion.
        safe = min(sections[section][1], turn+.17*math.tau)
        jobs[section].append((safe, turn, name, stroke))

    reversals = rim_orders(sections, jobs, xy, dock)
    pieces = [np.array([[dock, 1.]])]
    rows = 1
    events, erase = [], []

    def append(points):
        nonlocal rows
        theta, radius = pieces[-1][-1]
        path = polar_curve(points)
        path[:, 0] += math.tau*round((theta-path[0, 0])/math.tau)
        if abs(path[0, 1]-radius) > 1e-6 or (radius > 1e-7 and abs(path[0, 0]-theta) > 1e-5):
            raise ValueError('The erase and artwork do not meet.')
        extra = []
        for target in path:
            origin = np.array([theta, radius])
            delta = target-origin
            if np.max(abs(delta)) < 1e-10:
                continue
            n = max(1, math.ceil(abs(delta[0])/.055))
            extra.extend(origin+delta*np.arange(1, n+1)[:, None]/n)
            theta, radius = target
        if extra:
            pieces.append(np.array(extra))
            rows += len(extra)

    def sweep(a, b):
        if abs(b-a) > 1e-8:
            start = rows-1
            append(xy(np.linspace(a, b, max(2, math.ceil(abs(b-a)/.032)+1))))
            erase.append((start, rows-1))

    for i, (a, b) in enumerate(sections):
        if reversals[i]:
            a, b = b, a
        # Only the rim joins two clipped turns. A diagonal between their
        # endpoints would carve a visible line across freshly cleared sand.
        pt = xy(a)
        previous = pieces[-1][-1]
        angle = math.remainder(math.atan2(pt[1], pt[0])-previous[0], math.tau)
        if abs(angle) > 1e-9:
            n = math.ceil(abs(angle)/.055)
            pieces.append(np.column_stack((previous[0]+angle*np.arange(1, n+1)/n, np.ones(n))))
            rows += n
        cursor = a
        for safe, turn, name, stroke in sorted(jobs[i], key=lambda job: job[0]):
            sweep(cursor, safe)
            anchor = rows-1
            sweep(safe, turn)
            first = rows-1
            append(stroke)
            last = rows-1
            sweep(turn, safe)
            events.append(dict(label=name, anchor=anchor, first=first, last=last, back=rows-1))
            cursor = safe
        sweep(cursor, b)
    first = rows-1
    append(outline)
    events.append(dict(label='exit', first=first, last=rows-1))

    original = np.vstack(pieces)
    required = {i for event in events for key, i in event.items() if key != 'label'}
    required.update(i for pair in erase for i in pair)
    retained = compact_signed(original, required)
    for event in events:
        for key in event.keys()-{'label'}:
            event[key] = int(np.searchsorted(retained, event[key]))
    record = dict(center=center.tolist(), spacingMm=spacing_mm, opening=opening, turns=1/pitch,
                  reverseArcs=sum(reversals), arcs=len(sections), events=events,
                  eraseSpans=np.searchsorted(retained, erase).tolist())
    return original[retained], record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('strokes', type=Path)
    parser.add_argument('out', type=Path, help='New directory for ordered movement files and route.json')
    parser.add_argument('--start-angle', required=True, type=float, help='Signed angle at the opening rim dock')
    parser.add_argument('--spacing-mm', type=float, default=1.85)
    args = parser.parse_args()
    with np.load(args.strokes, allow_pickle=False) as archived:
        marks = {k: archived[k] for k in archived if k != 'exit'}
        route, report = compile_offset_portrait(marks, archived['exit'], args.start_angle, args.spacing_mm)
    parts = movement_files(route)
    report['signedFiles'] = {part['name']: hashlib.sha256(part['text'].encode('ascii')).hexdigest() for part in parts}
    report['sourceSha256'] = hashlib.sha256(args.strokes.read_bytes()).hexdigest()
    args.out.mkdir(parents=True, exist_ok=False)
    for part in parts:
        (args.out/part['name']).write_text(part['text'], encoding='ascii')
    (args.out/'route.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
