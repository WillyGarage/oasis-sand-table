#!/usr/bin/env python3
"""Check a ring-scene bundle on disk. Pass the generated directory or scene.json.

The check starts at the declared dock on prepared sand. On the Mini, commanded
angle changes linearly between motor targets, and radius stays between its
endpoints on the drawing branch of the arm. This lets us bound whole segments
without mistaking a coarse sample of points for a protected sand surface.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from thrcommon import MAX_POINTS


# Coordinates in .thr files can be rounded to five decimal places.
TOL = 0.000025
TAU = math.tau


def require(condition, message):
    if not condition:
        raise ValueError(message)


def wrapped(angle):
    return (angle + math.pi) % TAU - math.pi


def same_pose(a, b):
    # A turn at the centre can be an explicit move in the file. Keep its
    # direction across a file split, even though the ball is stationary there.
    return abs(a[1] - b[1]) <= TOL and abs(wrapped(a[0] - b[0])) <= TOL


def read_path(folder, name):
    path = np.loadtxt(folder / name, dtype=float, ndmin=2)
    require(path.shape[1] == 2 and len(path) >= 2, f'{name}: expected at least two theta/rho pairs')
    require(len(path) <= MAX_POINTS, f'{name}: file exceeds the Mini player limit of {MAX_POINTS} points')
    require(np.isfinite(path).all(), f'{name}: non-finite coordinate')
    require(np.all((path[:, 1] >= -TOL) & (path[:, 1] <= 1 + TOL)), f'{name}: outside working disc')
    jump = np.where(abs(np.diff(path[:, 0])) > math.pi + TOL)[0]
    require(not jump.size, f'{name}: ambiguous signed turn at segment {jump[:1].tolist()}')
    return path


def joined(parts, start, end, label):
    previous = start
    aligned = []
    for route in parts:
        route = np.asarray(route, dtype=float)
        require(route.ndim == 2 and route.shape[1] == 2 and len(route), f'{label}: missing theta/rho path')
        require(same_pose(previous, route[0]), f'{label}: unplanned connecting move')
        # The firmware chooses the equivalent starting turn closest to its
        # current angle, then preserves every signed turn inside the file.
        turns = round((previous[0] - route[0, 0]) / TAU)
        route = route + [turns * TAU, 0]
        aligned.append(route[1:] if aligned else route)
        previous = route[-1]
    require(bool(aligned), f'{label}: empty route')
    require(same_pose(previous, end), f'{label}: incorrect end position')
    return np.vstack(aligned)


def same_track(a, b):
    if a.shape != b.shape:
        return False
    offset = TAU * round((a[0, 0] - b[0, 0]) / TAU)
    return np.allclose(a, b + [offset, 0], atol=TOL, rtol=0)


def check_sampled_strokes(actual, vertices, *, hanger_steps=None):
    """Match rounded, signed movement to a line drawing in its Cartesian frame."""
    delta = np.diff(vertices, axis=0)
    subdivisions = np.hypot(*delta.T) / .01
    if hanger_steps is not None:
        subdivisions[[0,-1]] = hanger_steps
    counts = np.maximum(1, np.ceil(subdivisions).astype(int))
    starts = np.cumsum(counts) - counts
    adjustment = 0
    # An exact multiple of the sampling step can round to opposite sides of
    # ceil() in the browser and Python. Locate the shared vertex in the file.
    for i in np.flatnonzero((subdivisions > .99) & (abs(subdivisions-np.rint(subdivisions)) < 1e-10)):
        nominal = round(subdivisions[i])
        end = starts[i] + adjustment + nominal
        require(end < len(actual), 'Missing sketch points.')
        count = nominal + int(np.linalg.norm(actual[end]-vertices[i+1]) > TOL)
        adjustment += count - counts[i]
        counts[i] = count
    require(counts.sum()+1 == len(actual), 'Incorrect sketch length.')
    segments = np.repeat(np.arange(len(counts)), counts)
    offsets = np.arange(len(segments)) - np.repeat(np.cumsum(counts)-counts, counts)
    expected = vertices[segments] + (offsets/counts[segments])[:,None]*delta[segments]
    require(np.allclose(actual[:-1], expected, rtol=0, atol=TOL) and
            np.linalg.norm(actual[-1]-vertices[-1]) <= TOL, 'The engraving does not match the sketch.')
    return counts


def seam_segments(points, angle):
    on = abs(wrapped(points[:, 0] - angle)) <= TOL
    return on[:-1] & on[1:] & (abs(np.diff(points[:, 0])) <= 2 * TOL)


def covers_seam(points, angle, lo, hi, label):
    # Check overlap of actual radial strokes. A picture crossing the spoke
    # several times cannot accidentally claim those crossings as a cut route.
    radial = points[:, 1]
    mask = seam_segments(points, angle)
    spans = np.sort(np.column_stack((radial[:-1][mask], radial[1:][mask])), axis=1)
    covered = lo
    for start, stop in sorted(map(tuple, spans)):
        if stop < covered:
            continue
        if start > covered + TOL:
            break
        covered = max(stop, covered)
    require(covered >= hi - TOL, f'{label}: shared groove missing between radii {covered:.4f} and {hi:.4f}')


def safe_route(route, angle, safe_lo, safe_hi, dock, stem_end, label):
    # By monotonicity of radius, the swept furrow plus tracking
    # tolerance is inside the target if both radii are safely inside.
    radial = route[:, 1]
    require(radial.min() >= safe_lo - TOL, f'{label}: passed into a protected inner zone')
    inside = (radial >= safe_lo - TOL) & (radial <= safe_hi + TOL)
    outside = ~(inside[:-1] & inside[1:])
    bad = np.where(outside & ~seam_segments(route, angle))[0]
    require(not bad.size, f'{label}: protected band crossed away from the seam at {bad[:1].tolist()}')
    # The exit must leave an unbroken groove for the next inward edit.
    # The innermost zone only needs access as far as its perimeter.
    segments = seam_segments(route, angle)
    last_art = np.where(~segments)[0]
    require(last_art.size > 0, f'{label}: missing art')
    covers_seam(route[last_art[-1] + 1 :], angle, stem_end, dock[1], label)


def check_flower_access(art, angle, groove, label):
    # The only straight travel on the spoke bridges the frame and a petal tip.
    points = np.asarray(art)
    radial = points[:, 1]
    on_spoke = seam_segments(points, angle)
    petals = np.flatnonzero(~on_spoke)
    require(bool(petals.size), f'{label}: flower contains only a radial stroke')
    tip = max(radial[petals].max(), radial[petals + 1].max())
    straight = on_spoke & (np.abs(np.diff(radial)) > TOL)
    inner = np.minimum(radial[1:], radial[:-1])
    require(np.all(inner[straight] >= tip - TOL), f'{label}: straight travel cuts through the flower')
    require(radial[0] - tip <= 1.5 * groove + TOL, f'{label}: long connector from frame to flower')
    exit_radii = radial[petals[-1] + 1:]
    require(exit_radii[0] >= tip - TOL and np.all(np.diff(exit_radii) >= -TOL),
            f'{label}: flower returns through its petals instead of leaving at the edge')


def covers_guest_rail(art, rail):
    """An open-place tour may follow any part of the rail cut by the opening art."""
    on = abs(art[:, 1] - rail) <= TOL
    at = np.flatnonzero(on[:-1] & on[1:])
    spans = []
    for left, right in np.sort(np.column_stack((art[at, 0], art[at+1, 0])), axis=1):
        start = left % TAU
        end = start + right-left
        spans.append((start, min(end, TAU)))
        if end > TAU:
            spans.append((0, end-TAU))
    covered = 0.
    for start, end in sorted(spans):
        require(start <= covered + TOL, 'opening leaves a gap in the rail used between guest places')
        covered = max(covered, end)
    require(covered >= TAU-TOL, 'opening does not finish the rail used between guest places')


def travel(route):
    r = route[:, 1]
    return np.r_[0.0, np.cumsum(np.hypot(np.diff(r), np.diff(route[:, 0]) * (r[:-1] + r[1:]) / 2))]


def sample_walk(route, spacing):
    """Locate points on the player's polar interpolation at most spacing apart."""
    route = np.asarray(route)
    delta = np.diff(route, axis=0)
    arc = np.maximum(route[:-1, 1], route[1:, 1]) * delta[:, 0]
    counts = np.maximum(1, np.ceil(np.hypot(arc, delta[:, 1]) / spacing).astype(int))
    segment = np.repeat(np.arange(len(counts)), counts)
    offset = np.arange(len(segment)) - np.repeat(np.cumsum(counts) - counts, counts)
    positions = np.vstack([route[segment] + delta[segment] * (offset / counts[segment])[:, None], route[-1]])
    return positions[:, 1, None] * np.column_stack((np.cos(positions[:, 0]), np.sin(positions[:, 0])))


def sweep_coverage(clear, low, high, groove, left, right, label):
    """Certify the whole angular sector against clearing strokes made before its ornament."""
    from scipy.spatial import cKDTree

    tree = cKDTree(np.vstack([sample_walk(part, groove * 0.08) for part in clear]))
    radial_steps = math.ceil((high - low) / (groove * 0.1))
    angular_steps = math.ceil((right - left) * high / (groove * 0.1))
    dr = (high - low) / radial_steps
    dt = (right - left) / angular_steps
    radii = low + dr * (np.arange(radial_steps) + 0.5)
    angles = left + dt * (np.arange(angular_steps) + 0.5)
    limit = groove / 2 + TOL
    observed = bound = 0.0
    for i in range(0, len(radii), 12):
        r, theta = np.meshgrid(radii[i : i + 12], angles, indexing='ij')
        r, theta = r.ravel(), theta.ravel()
        height, width = dr, dt
        # Refine only cells too close to the measured edge of a furrow. An entire
        # cell is covered when its center distance plus its radius fits the groove.
        while len(r):
            xy = np.column_stack((r * np.cos(theta), r * np.sin(theta)))
            nearest = tree.query(xy)[0]
            observed = max(observed, nearest.max())
            require(
                observed <= limit, f'{label}: erase leaves uncovered sand ({observed / groove:.3f} grooves)'
            )
            upper = nearest + 0.5 * np.hypot(height, high * width)
            unresolved = upper > limit
            if not unresolved.all():
                bound = max(bound, upper[~unresolved].max())
            if not unresolved.any():
                break
            require(height > TOL * 0.02, f'{label}: cannot certify complete continuous erase coverage')
            r, theta = r[unresolved], theta[unresolved]
            height, width = height / 2, width / 2
            r = (r[:, None] + height * np.array([-0.5, -0.5, 0.5, 0.5])).ravel()
            theta = (theta[:, None] + width * np.array([-0.5, 0.5, -0.5, 0.5])).ravel()
    return observed, bound


def check_reveal(scene, zone, variant, route):
    """Recover every complete ornament in the exported movement, in drawing order."""
    from scipy.spatial import cKDTree

    reveal = variant['reveal']
    transit = np.asarray(zone['transit'])
    expected = joined([transit, reveal['path'], transit[::-1]], scene['dock'], scene['dock'], 'reveal preview')
    label = variant['name']
    require(same_track(route, expected), f'{label}: reveal download differs from the preview')
    start = len(transit) - 1
    body = route[start : len(route) - start]
    finished = reveal['finished']
    require(
        isinstance(finished, list)
        and len(finished) >= 2
        and all(type(i) is int for i in finished)
        and all(a < b for a, b in zip([-1] + finished, finished + [len(body)])),
        f'{label}: invalid completion indices',
    )
    canonical = np.asarray(variant['path'])
    sector = TAU / len(finished)
    gate = scene['dock'][0]
    previous = 0
    clearing, motifs = [], []
    for i, end in enumerate(finished):
        left, right = gate + i * sector, gate + (i + 1) * sector
        inside = np.flatnonzero((canonical[:, 0] > left + TOL) & (canonical[:, 0] < right - TOL))
        require(
            len(inside) > 2 and inside[0] > 0 and inside[-1] + 1 < len(canonical),
            f'{label}: missing source ornament {i + 1}',
        )
        motif = canonical[inside[0] - 1 : inside[-1] + 2]
        begin = end - len(motif) + 1
        require(
            begin > previous and same_track(body[begin : end + 1], motif),
            f'{label}: marker {i + 1} does not finish the original complete ornament',
        )
        clearing.append(body[previous : begin + 1])
        motifs.append(body[begin : end + 1])
        previous = end
    clearing.append(body[previous:])
    low, high = zone['safe_bounds']
    groove = scene['groove_width']
    certificates = [
        sweep_coverage(
            clearing[: i + 1],
            low,
            high,
            groove,
            gate + i * sector,
            gate + (i + 1) * sector,
            f'{label}, before ornament {i + 1}',
        )
        for i in range(len(finished))
    ]
    observed, bound = np.max(certificates, axis=0)
    # Later clearing can join an ornament at its two attachment points. Its
    # floor must never cut through the already finished interior of that motif.
    for i, motif in enumerate(motifs):
        later = cKDTree(np.vstack([sample_walk(part, groove * 0.16) for part in clearing[i + 1 :]]))
        points = sample_walk(motif, groove * 0.14)
        endpoints = points[[0, -1]]
        interior = points[np.linalg.norm(points[:, None] - endpoints, axis=2).min(axis=1) > 2.2 * groove]
        require(
            len(interior) > 0 and later.query(interior)[0].min() >= 0.5 * groove - TOL,
            f'{label}: later clearing touches finished ornament {i + 1}',
        )
    distance = travel(route)
    first = distance[start + finished[0]]
    conventional = travel(joined([transit, zone['erase']], scene['dock'], transit[-1], 'ordinary erase'))[-1]
    require(first < conventional, f'{label}: first reveal comes after the conventional full erase')
    return {
        'endpoints': [start + i for i in finished],
        'first_fraction': float(first / distance[-1]),
        'sweep_grid_max_grooves': float(observed / groove),
        'sweep_upper_bound_grooves': float(bound / groove),
    }


def check_bundle(manifest):
    scene = json.loads(manifest.read_text())
    zones = scene['zones']
    dock = scene['dock']
    angle = dock[0]
    require(abs(dock[1] - 1) <= TOL, 'Expected a common dock on the rim')
    guard = scene['groove_width'] / 2 + scene['tracking_margin']
    require(scene['groove_width'] > 0 and scene['tracking_margin'] >= 0, 'Invalid physical margins')
    prepared_pitch = scene.get('prepared_erase_pitch')
    if prepared_pitch is not None:
        require(0 < prepared_pitch <= scene['groove_width'], 'Invalid prepared-sand erase pitch')
    setup = scene['setup']
    names = set(setup)
    for zone in zones.values():
        for variant in zone['variants']:
            names.update(variant['replace'])
            if 'reveal' in variant:
                names.update(variant['reveal']['replace'])
    paths = {name: read_path(manifest.parent, name) for name in sorted(names)}
    layout = joined((paths[name] for name in setup), dock, dock, 'setup')
    previous_hi = 0
    replacements = 0
    originals = []
    for key, zone in sorted(zones.items(), key=lambda item: item[1]['bounds'][0]):
        lo, hi = zone['bounds']
        safe_lo, safe_hi = zone['safe_bounds']
        require(abs(previous_hi - lo) <= TOL and 0 <= lo < hi <= 1, f'{key}: noncontiguous zones')
        previous_hi = hi
        require(safe_lo >= (lo + guard if lo > 0 else 0) - TOL and
                safe_hi <= hi - guard + TOL and safe_hi > safe_lo, f'{key}: inadequate footprint buffer')
        cut = np.asarray(zone['erase'])
        require(cut.ndim == 2 and cut.shape[1] == 2 and len(cut) >= 2, f'{key}: incomplete erase')
        require(abs(cut[:, 1].min() - safe_lo) <= TOL and abs(cut[:, 1].max() - safe_hi) <= TOL,
                f'{key}: erase does not span its declared working band')
        require(bool(np.any(~seam_segments(cut, angle))), f'{key}: erase has only a radial stroke')
        transit = np.asarray(zone['transit'])
        # The historical center clear starts on a circular contour. The new
        # outward clear enters on the spoke and finishes at the petal edge.
        edge_flower = key == 'center' and not prepared_pitch and seam_segments(cut, angle)[0]
        for index, variant in enumerate(zone['variants']):
            label = f'{key}/{variant["name"]}'
            files = variant['replace']
            route = joined((paths[name] for name in files), dock, dock, label)
            preview = joined([transit, cut, variant['path'], transit[::-1]], dock, dock, label)
            require(same_track(route, preview), f'{label}: exported motion differs from the erase and art shown')
            if edge_flower:
                check_flower_access(variant['path'], angle, scene['groove_width'], label)
            if index == 0:
                # Prepared-sand setup uses the exact same artwork and approach,
                # then returns to its dock without clearing the bed a second time.
                first = joined([transit, variant['path'], transit[::-1]], dock, dock, label) if prepared_pitch else route
                originals.append(first)
                if key == 'middle' and scene.get('guest_plan', {}).get('fillTours'):
                    # Inspect only the engraving after the spiral erase, using the
                    # signed file. safe_route also checks the finished dock stem.
                    art_start = len(transit) + len(cut) - 2
                    covers_guest_rail(route[art_start:art_start+len(variant['path'])],
                                      scene['guest_plan']['geometry']['rail'])
            stem_end = safe_hi if edge_flower or (key == 'center' and prepared_pitch) else safe_lo
            safe_route(route, angle, safe_lo, safe_hi, dock, stem_end, label)
            if 'reveal' in variant:
                reveal = variant['reveal']
                parts = [paths[name] for name in reveal['replace']]
                for left, right in zip(parts, parts[1:]):
                    require(np.array_equal(left[-1], right[0]), f'{label}: reveal file lost its signed join')
                progressive = joined(parts, dock, dock, label + ' reveal')
                safe_route(progressive, angle, safe_lo, safe_hi, dock, stem_end, label + ' reveal')
                check_reveal(scene, zone, variant, progressive)
                replacements += 1
            replacements += 1
    require(abs(previous_hi - 1) <= TOL, 'Zones do not cover the disc')
    # The first large-table stroke establishes the spoke on the fresh bed.
    # All the art must match the independently validated opening routes.
    gallery = joined(originals, dock, dock, 'initial zone drawings')
    if prepared_pitch:
        require(same_track(layout, gallery), 'prepared-sand setup differs from the original art and its access paths')
    else:
        cut_at = len(layout) - len(gallery)
        require(cut_at >= 0 and same_track(layout[cut_at:], gallery),
                'setup must draw the initial variants after establishing access')
        if cut_at:
            # Historical beds began with an extra trip down the spoke and back.
            seed = layout[:cut_at + 1]
            require(seam_segments(seed, angle).all(), 'setup approached the shared groove across fresh sand')
        else:
            # The first outward center clear reaches zero directly from the dock.
            first_turn = np.flatnonzero(~seam_segments(layout, angle))[0]
            seed = layout[:first_turn + 1]
        covers_seam(seed, angle, 0, dock[1], 'first setup stroke')
    return len(zones), replacements, len(layout), guard


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, help='generated ring-scene directory or scene.json')
    args = parser.parse_args()
    target = args.bundle / 'scene.json' if args.bundle.is_dir() else args.bundle
    try:
        zones, replacements, count, guard = check_bundle(target)
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f'Invalid ring scene: {error}\n')
    print(f'{zones} zones, {replacements} replacement routes, {count} setup waypoints. '
          f'Protected radial margin {guard:.5f} of the working radius. All files join at their specified positions.')
