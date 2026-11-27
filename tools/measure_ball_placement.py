#!/usr/bin/env python3
"""Compare settled ball centers marked in photos with the ordered polar commands.

The CSV columns are theta_rad,rho,x_px,y_px,photo. Use empty pixel coordinates
for an unobserved stop. Give repeat photos of one stop the same optional
receipt. List all photos of each arrival together. Measure pixels without using the commanded position to
choose the ball. All photos must share a camera pose (or be registered to it).
The physical frame is centered on the table, positive x is theta zero, y up.

Supply surveyed marks (role,x_px,y_px,x_mm,y_mm) in the ball-center plane.
Use role=fit for the camera transform and role=check for independent marks.
For old Mini sessions, a dated v6h camera file and its original mm/unit scale
can instead be replayed. A report describes these stops on this table only.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.distance import pdist


def csv_rows(path, columns):
    with path.open(newline='') as stream:
        rows = csv.DictReader(stream)
        if not set(columns).issubset(rows.fieldnames or []):
            raise ValueError(f'{path} needs columns {", ".join(columns)}.')
        result = list(rows)
        if any(any(row[k] is None for k in columns) for row in result):
            raise ValueError(f'{path} contains an incomplete CSV row. Retain empty cells for missed stops.')
        return result


def numbers(row, *keys):
    values = np.array([float(row[k]) for k in keys])
    if not np.isfinite(values).all():
        raise ValueError(f'Expected finite values for {", ".join(keys)}.')
    return values


def project(matrix, pixels):
    pixels = np.asarray(pixels, dtype=float).reshape(-1, 2)
    homogeneous = np.column_stack((pixels, np.ones(len(pixels)))) @ matrix.T
    if np.any(np.abs(homogeneous[:, 2]) < 1e-12):
        raise ValueError('A measured point projects to infinity. Check the camera references.')
    points = homogeneous[:, :2] / homogeneous[:, 2, None]
    if not np.isfinite(points).all():
        raise ValueError('Invalid camera projection.')
    return points


def summary(errors):
    if len(errors) == 0:
        return None
    return dict(zip(('median', 'p95', 'max'), np.percentile(errors, [50, 95, 100]).tolist()))


def surveyed_camera(path):
    groups = {'fit': [], 'check': []}
    used = set()
    for row in csv_rows(path, ('role', 'x_px', 'y_px', 'x_mm', 'y_mm')):
        role = row['role'].strip()
        if role not in groups:
            raise ValueError('Each reference mark needs role fit or check.')
        point = numbers(row, 'x_px', 'y_px', 'x_mm', 'y_mm')
        px, mm = tuple(point[:2]), tuple(point[2:])
        if ('px', px) in used or ('mm', mm) in used:
            raise ValueError('Each reference mark must be distinct, including check marks.')
        used.update([('px', px), ('mm', mm)])
        groups[role].append(point)
    if len(groups['fit']) < 4:
        raise ValueError('At least four surveyed fit marks spread over the table are needed.')
    fit = np.array(groups['fit'])
    matrix, _ = cv2.findHomography(fit[:, :2], fit[:, 2:], 0)
    if matrix is None or not np.isfinite(matrix).all() or np.linalg.matrix_rank(matrix) < 3:
        raise ValueError('The surveyed marks do not define a camera transform.')
    report = {'source': str(path)}
    for role, rows in groups.items():
        errors = []
        if rows:
            points = np.array(rows)
            errors = np.linalg.norm(project(matrix, points[:, :2]) - points[:, 2:], axis=1)
        report[role] = {'marks': len(rows), 'residual_mm': summary(errors)}
    return matrix, report


def archived_camera(path, mm_per_unit):
    if mm_per_unit is None or not math.isfinite(mm_per_unit) or mm_per_unit <= 0:
        raise ValueError('An archived Mini camera needs its positive --mm-per-unit scale.')
    camera = json.loads(path.read_text())
    if camera.get('model') != 'v6h':
        raise ValueError('Expected a dated Mini v6h calibration or a surveyed reference CSV.')
    matrix = np.asarray(camera['params']['H'], dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or np.linalg.matrix_rank(matrix) < 3:
        raise ValueError('The archived camera matrix is invalid.')
    transform = np.diag([mm_per_unit, mm_per_unit, 1]) @ np.linalg.inv(matrix)
    return transform, {'source': str(path), 'date': camera['date'], 'mm_per_unit': mm_per_unit,
                       'check': None, 'kind': 'Historical camera fitted with the Mini arm model'}


def measure(rows, matrix, radius):
    if not math.isfinite(radius) or radius <= 0 or not rows:
        raise ValueError('Supply ordered targets and the measured positive working radius.')
    photos = set()
    arrivals = {}
    stops = []
    for index, row in enumerate(rows):
        theta, rho = numbers(row, 'theta_rad', 'rho')
        if not 0 <= rho <= 1:
            raise ValueError('Target rho is outside the working radius.')
        radial = np.array([math.cos(theta), math.sin(theta)])
        target = rho * radius * radial
        # Rows without a receipt describe one exposure for each commanded stop.
        receipt = (row.get('receipt') or '').strip()
        key = receipt or index
        if key in arrivals:
            stop = arrivals[key]
            if stop is not stops[-1] or not np.allclose(stop['target_mm'], target, rtol=0, atol=1e-6):
                raise ValueError(f'Repeated receipt at a different arrival or target: {receipt}')
        else:
            approach = None
            if stops and stops[-1]['rho'] != rho:
                approach = 'from smaller radius' if stops[-1]['rho'] < rho else 'from larger radius'
            stop = {'theta_rad': theta, 'rho': rho, 'target_mm': target.tolist(), 'receipt': receipt,
                    'previous_target_direction': approach, 'photos': [], 'observed_mm': None}
            stops.append(stop)
            arrivals[key] = stop
        photo = row['photo'].strip()
        if photo:
            if photo in photos:
                raise ValueError(f'Photograph listed twice: {photo}')
            photos.add(photo)
        measurement = {'file': photo, 'observed_mm': None}
        stop['photos'].append(measurement)
        if not row['x_px'].strip() and not row['y_px'].strip():
            continue
        if not photo or not row['x_px'].strip() or not row['y_px'].strip():
            raise ValueError('A measured stop needs both pixel coordinates and its photograph.')
        position = project(matrix, [numbers(row, 'x_px', 'y_px')])[0]
        measurement['observed_mm'] = position.tolist()
        if stop['observed_mm'] is None:
            displacement = position - target
            stop.update(observed_mm=position.tolist(), error_mm=float(np.linalg.norm(displacement)),
                        outward_mm=float(displacement @ radial) if rho else None,
                        counterclockwise_mm=float(displacement @ [-radial[1], radial[0]]) if rho else None)

    repeats = defaultdict(list)
    observed = [s for s in stops if s['observed_mm'] is not None]
    for stop in observed:
        # Group equivalent commands, including angles that differ by full turns.
        repeats[tuple(np.round(stop['target_mm'], 3))].append(stop)
        positions = [p['observed_mm'] for p in stop['photos'] if p['observed_mm'] is not None]
        stop['stationary_spread_mm'] = float(pdist(positions).max()) if len(positions) > 1 else None
    repeated = []
    for target, visits in repeats.items():
        if len(visits) < 2:
            continue
        points = [s['observed_mm'] for s in visits]
        directions = {s['previous_target_direction'] for s in visits}
        repeated.append({'target_mm': list(target), 'observed_visits': len(points),
                         'max_separation_mm': float(pdist(points).max()),
                         'previous_targets_on_both_radial_sides':
                             {'from smaller radius', 'from larger radius'} <= directions})
    return {'working_radius_mm': radius, 'commanded_stops': len(stops), 'measured_stops': len(observed),
            'distinct_measured_targets': len(repeats), 'error_mm': summary([s['error_mm'] for s in observed]),
            'repeated_targets': repeated, 'stops': stops}


def zone_coverage(report, layout):
    if not math.isclose(layout['assumed_working_radius_mm'], report['working_radius_mm'], abs_tol=1e-6):
        raise ValueError('Use the garden layout fitted to the working radius of the measured table.')
    coverage = {}
    for name, zone in layout['zones'].items():
        low, high = zone['bounds']
        stops = [s for s in report['stops'] if low <= s['rho'] < high or (high == 1 and s['rho'] == 1)]
        measured = [s for s in stops if s['observed_mm'] is not None]
        unique = {tuple(np.round(s['target_mm'], 3)) for s in measured}
        coverage[name] = {'bounds_rho': [low, high], 'commanded_stops': len(stops),
                          'distinct_measured_targets': len(unique),
                          'error_mm': summary([s['error_mm'] for s in measured])}
    return coverage


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument('observations', type=Path)
    cli.add_argument('--radius-mm', type=float, required=True)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument('--references', type=Path)
    source.add_argument('--mini-calibration', type=Path)
    cli.add_argument('--mm-per-unit', type=float, help='Original plane scale for --mini-calibration')
    cli.add_argument('--layout', type=Path, help='Report coverage within the zones of a fitted scene.json')
    args = cli.parse_args()
    try:
        if args.references:
            if args.mm_per_unit is not None:
                raise ValueError('Surveyed references already use millimeters.')
            matrix, camera = surveyed_camera(args.references)
        else:
            matrix, camera = archived_camera(args.mini_calibration, args.mm_per_unit)
        rows = csv_rows(args.observations, ('theta_rad', 'rho', 'x_px', 'y_px', 'photo'))
        report = measure(rows, matrix, args.radius_mm)
        report['camera'] = camera
        if args.layout:
            report['zones'] = zone_coverage(report, json.loads(args.layout.read_text()))
    except (ValueError, KeyError, OSError, cv2.error) as exc:
        cli.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
