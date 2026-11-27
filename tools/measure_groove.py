#!/usr/bin/env python3
"""Measure visible ridge-to-ridge spacing in millimeters on photographed sand.

Supply registered, perspective-corrected photographs on the same metric grid,
with the table's zero-angle axis to the right and positive angles turning
counterclockwise. Use the measured working radius
of the ball, its matching pixel radius and center (x y), and the signed .thr
outline. Supply --all-motion when other engraving and travel strokes also
appear in the image. --repeat accepts another photograph of the finished sand.

Use --native-px-per-mm for the coarsest original camera sampling across the
measured region. The rectified pixel scale alone cannot show whether the
camera resolved the ridges. Lighting must reveal two bright shoulders around
the dark trough. Their visible spacing does not measure physical depth, total
displaced sand, usable erase pitch, or tracking error.
"""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from scipy.spatial import cKDTree

from check_ring_scene import sample_walk


@dataclass
class Station:
    distance: float
    point: np.ndarray
    tangent: np.ndarray
    normal: np.ndarray
    passes: int


def read_gray(path):
    data = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if data is None:
        raise ValueError(f'Cannot read photograph {path}')
    return data.astype(np.float32)


def motion_mm(filename, radius, sample_step=0.15):
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('The physical working radius must be positive and finite.')
    route = np.loadtxt(filename, ndmin=2)
    if len(route) < 2 or route.shape[1] != 2 or not np.isfinite(route).all():
        raise ValueError(f'Expected a signed two-column theta/rho path in {filename}')
    if np.any((route[:, 1] < 0) | (route[:, 1] > 1.00001)):
        raise ValueError(f'Radius outside the working area in {filename}')
    # Bound the dense polar walk before sample_walk expands it with np.repeat.
    spacing = sample_step / radius
    with np.errstate(over='ignore', invalid='ignore'):
        delta = np.diff(route, axis=0)
        arc = delta[:, 0] * np.maximum(route[:-1, 1], route[1:, 1])
        needed = np.maximum(1, np.ceil(np.hypot(arc, delta[:, 1]) / spacing)).sum()
    if not np.isfinite(needed) or needed > 2_000_000:
        raise ValueError('This route would exceed two million samples. Select the relevant drawing.')
    # Convert the true polar interpolation to the rectified image's y-down frame.
    return sample_walk(route, spacing) * [radius, -radius]


def stations_on_path(points, all_points, half_span, spacing):
    distance = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if distance[-1] / spacing > 8_000:
        raise ValueError('More than 8000 candidate sections. Increase --spacing or select a shorter outline.')
    tree = cKDTree(all_points)

    def at(s):
        return np.array([np.interp(s, distance, v) for v in points.T])

    selected = []
    reasons = {'sharp_turn': 0, 'neighboring_stroke': 0, 'repeated_location': 0}
    reach = 2.8  # mm along each side of the center, used to establish a local normal.
    for s in np.arange(reach, distance[-1] - reach, spacing):
        point = at(s)
        left = point - at(s - reach)
        right = at(s + reach) - point
        a, b = np.linalg.norm(left), np.linalg.norm(right)
        if min(a, b) < reach * 0.95 or left @ right < a * b * math.cos(math.radians(22)):
            reasons['sharp_turn'] += 1
            continue
        tangent = (left + right) / np.linalg.norm(left + right)
        normal = np.array([-tangent[1], tangent[0]])
        # The 2 mm wide sampling strip must be clear of other programmed
        # centerlines. Allow small curvature and exact retraces along this line.
        cloud = all_points[tree.query_ball_point(point, half_span + 2.5)] - point
        side = abs(cloud @ normal)
        if np.any((abs(cloud @ tangent) < 1.7) & (side > 1.2) & (side < half_span + 1.6)):
            reasons['neighboring_stroke'] += 1
            continue
        if any(np.linalg.norm(point - prev.point) < spacing * 0.84 for prev in selected):
            reasons['repeated_location'] += 1
            continue
        near = np.sort(tree.query_ball_point(point, 1.5))
        if not len(near):
            raise ValueError('The supplied full motion does not contain the selected outline.')
        passes = 1 + np.count_nonzero(np.diff(near) > 1)
        selected.append(Station(float(s), point, tangent, normal, int(passes)))
    return selected, reasons


def light_profile(image, station, xs, center, pixels_per_mm):
    # Median of nine parallel cuts across a two-millimeter length limits grain
    # and JPEG noise. Use a fixed optical smoothing scale, independent of width.
    along = np.linspace(-1, 1, 9)[:, None, None]
    positions = station.point + station.tangent * along + xs[None, :, None] * station.normal
    uv = center + pixels_per_mm * positions
    x, y = np.moveaxis(uv.astype('float32'), -1, 0)
    if np.any(x < 1) or np.any(y < 1) or np.any(x >= image.shape[1] - 1) or np.any(y >= image.shape[0] - 1):
        return None
    values = np.median(cv2.remap(image, x, y, cv2.INTER_LINEAR), axis=0)
    return gaussian_filter1d(values, 0.34 / (xs[1] - xs[0]), mode='nearest')


def detrend(profile, xs):
    left = xs < xs[0] * 0.78
    right = xs > xs[-1] * 0.78
    baseline = np.interp(
        xs, [np.median(xs[left]), np.median(xs[right])], [np.median(profile[left]), np.median(profile[right])]
    )
    return profile - baseline


def shoulders(profile, xs, noise):
    # The known path localizes the floor. No preferred separation is given to
    # the two maxima. A shoulder at the end of the search would be censored.
    center = np.flatnonzero(abs(xs) < min(3.5, xs[-1] * 0.42))
    bottom = center[np.argmin(profile[center])]
    if profile[bottom] > -noise:
        return None
    peaks, _ = find_peaks(profile, prominence=noise * 0.75)
    peaks = peaks[(profile[peaks] > noise) & (abs(xs[peaks]) < xs[-1] - 0.6)]
    left = peaks[peaks < bottom]
    right = peaks[peaks > bottom]
    if not len(left) or not len(right):
        return None
    i, j = left[-1], right[0]
    if min(profile[i], profile[j]) - profile[bottom] < 2.5 * noise:
        return None
    if abs((xs[i] + xs[j]) / 2) > xs[-1] * 0.42:
        return None

    def peak_position(k):
        a, b, c = profile[k - 1 : k + 2]
        curvature = a - 2 * b + c
        fraction = 0.5 * (a - c) / curvature if curvature else 0.0
        return float(xs[k] + np.clip(fraction, -0.5, 0.5) * (xs[1] - xs[0]))

    return [peak_position(i), peak_position(j)]


def quantiles(values):
    if not values:
        return None
    names = ['min', 'q10', 'q25', 'median', 'q75', 'q90', 'max']
    return dict(zip(names, np.round(np.percentile(values, [0, 10, 25, 50, 75, 90, 100]), 3).tolist()))


def new_shoulders(blank, difference, finished, xs, gate, tolerance):
    if shoulders(blank, xs, gate):
        return None, 'already_visible_in_blank'
    pair = shoulders(difference, xs, gate)
    if pair is None:
        return None, 'no_new_paired_shoulders'
    direct = shoulders(finished, xs, gate)
    if direct is None or max(abs(np.subtract(pair, direct))) > tolerance:
        return None, 'shoulders_disagree_with_finished_photo'
    return pair, None


def measure(
    before,
    after,
    repeat,
    outline,
    all_motion,
    center,
    scale,
    half_span=10.0,
    spacing=3.5,
    native_px_per_mm=None,
):
    if (
        not np.isfinite([*center, scale, half_span, spacing]).all()
        or scale <= 0
        or half_span < 3
        or spacing <= 0
    ):
        raise ValueError('Use a positive metric scale and spacing, and a search half-span of at least 3 mm.')
    if before.shape != after.shape or (repeat is not None and before.shape != repeat.shape):
        raise ValueError('Rectified photographs must share one calibrated pixel grid.')
    if native_px_per_mm is not None and (not math.isfinite(native_px_per_mm) or native_px_per_mm <= 0):
        raise ValueError('The native camera sampling must be positive and finite.')
    if not (0 <= center[0] < before.shape[1] and 0 <= center[1] < before.shape[0]):
        raise ValueError('The working center must lie inside the rectified photograph.')
    if 2 * half_span * scale > math.hypot(*before.shape) or 2 * half_span / 0.1 > 30_000:
        raise ValueError('Select a search half-span that fits the photograph and the profile sampler.')
    candidates, excluded = stations_on_path(outline, all_motion, half_span, spacing)
    xs = np.linspace(-half_span, half_span, round(2 * half_span / 0.1) + 1)
    if len(xs) * len(candidates) > 3_000_000:
        raise ValueError('Too many profile samples. Increase --spacing or shorten the search half-span.')
    excluded['outside_photo'] = 0
    chosen = []
    profiles = []
    for st in candidates:
        b = light_profile(before, st, xs, center, scale)
        if b is None:
            excluded['outside_photo'] += 1
            continue
        a = light_profile(after, st, xs, center, scale)
        chosen.append(st)
        row = [detrend(b, xs), detrend(a - b, xs), detrend(a, xs)]
        if repeat is not None:
            r = light_profile(repeat, st, xs, center, scale)
            row.extend((detrend(r - b, xs), detrend(r, xs)))
        profiles.append(row)

    blank_profiles = np.array([data[0] for data in profiles])
    mad = np.median(abs(blank_profiles - np.median(blank_profiles))) if profiles else 0
    gate = max(3.0, 3 * 1.4826 * mad)  # The lower floor rejects faint JPEG ripples on a very smooth bed.
    tolerance = max(0.5, 1.5 / scale)
    records = []
    blank_hits = 0
    repeat_peak_disagreements = 0
    widths, repeat_widths, repeat_deltas, single_pass = [], [], [], []
    for st, data in zip(chosen, profiles):
        blank, diff, finished = data[:3]
        blank_hits += shoulders(blank, xs, gate) is not None
        pair, reason = new_shoulders(blank, diff, finished, xs, gate, tolerance)
        row = dict(
            distance_along_outline_mm=round(st.distance, 2),
            center_mm=st.point.round(3).tolist(),
            tangent_deg=round(math.degrees(math.atan2(st.tangent[1], st.tangent[0])) % 180, 1),
            programmed_passes=st.passes,
            visible_peaks_mm=pair,
        )
        if pair:
            width = pair[1] - pair[0]
            row['width_mm'] = round(width, 3)
            widths.append(width)
            if st.passes == 1:
                single_pass.append(width)
            if repeat is not None:
                rep, _ = new_shoulders(blank, *data[3:], xs, gate, tolerance)
                if rep:
                    repeat_widths.append(rep[1] - rep[0])
                    repeat_deltas.append(repeat_widths[-1] - width)
                    row['repeat_width_mm'] = round(repeat_widths[-1], 3)
                    if max(abs(np.subtract(pair, rep))) > tolerance:
                        row['repeat_peaks_disagree'] = True
                        repeat_peak_disagreements += 1
        else:
            row['excluded'] = reason
        records.append(row)
    sensitivity = {}
    for multiplier in (0.75, 1.25):
        samples = []
        for blank, diff, finished, *_ in profiles:
            pair, _ = new_shoulders(blank, diff, finished, xs, gate * multiplier, tolerance)
            if pair:
                samples.append(pair[1] - pair[0])
        sensitivity[str(multiplier)] = {
            'count': len(samples),
            'median_mm': quantiles(samples)['median'] if samples else None,
        }

    observed = quantiles(widths)
    sampling = min(scale, native_px_per_mm) if native_px_per_mm is not None else scale
    supported = len(widths) >= 8 and blank_hits <= 0.1 * len(chosen) and observed['median'] * sampling >= 6
    report = dict(
        status='measured' if supported else 'insufficient_evidence',
        observable='Light-peak separation across the new dark groove on registered rectified photos.',
        units='millimeters',
        pass_count_method='Separate visits of the signed sampled movement within 1.5 mm of the section center.',
        pixels_per_mm=round(scale, 5),
        rectified_mm_per_pixel=round(1 / scale, 5),
        native_pixels_per_mm=native_px_per_mm,
        native_mm_per_pixel=round(1 / native_px_per_mm, 5) if native_px_per_mm else None,
        native_pixels_across_median=round(native_px_per_mm * observed['median'], 2)
        if native_px_per_mm and observed
        else None,
        sampling_note='Resolution gate uses the coarser of the declared native and rectified pixel grids.'
        if native_px_per_mm
        else 'Only the rectified grid was checked. Native camera sampling is unknown.',
        half_span_mm=half_span,
        spacing_mm=spacing,
        noise_gate_gray_levels=round(float(gate), 2),
        geometrically_excluded=excluded,
        sections_tested=len(chosen),
        sections_accepted=len(widths),
        blank_control_detections=blank_hits,
        visible_ridge_spacing_mm=observed,
        single_pass_count=len(single_pass),
        single_pass_mm=quantiles(single_pass),
        repeat_pairs_detected=len(repeat_widths),
        repeat_peak_disagreements=repeat_peak_disagreements,
        repeat_width_mm=quantiles(repeat_widths),
        repeat_minus_first_width_mm=quantiles(repeat_deltas),
        noise_gate_sensitivity=sensitivity,
        sections=records,
    )
    return report, (chosen, profiles, xs)


def plot(path, photo, center, scale, report, detail):
    from matplotlib import use

    use('Agg')
    import matplotlib.pyplot as plt

    stations, profiles, xs = detail
    fig, (image, chart) = plt.subplots(1, 2, figsize=(11.4, 5.0), gridspec_kw={'width_ratios': [1, 1.3]})
    image.imshow(photo, cmap='gray', vmin=np.percentile(photo, 1), vmax=np.percentile(photo, 98))
    if stations:
        positions = np.array([s.point for s in stations])
        low = center + (positions.min(axis=0) - xs[-1]) * scale
        high = center + (positions.max(axis=0) + xs[-1]) * scale
        image.set(xlim=(low[0], high[0]), ylim=(high[1], low[1]))
    image.set(aspect='equal', title=f"{report['sections_accepted']} accepted cross-sections")
    image.axis('off')
    shifted = []
    for st, data, row in zip(stations, profiles, report['sections']):
        peaks = row['visible_peaks_mm']
        if peaks:
            xy = center + scale * (st.point + np.asarray(peaks)[:, None] * st.normal)
            image.plot(xy[:, 0], xy[:, 1], color='#21a08e', linewidth=1)
            trace = np.interp(xs + np.mean(peaks), xs, data[1])
            shifted.append(trace)
            chart.plot(xs, trace, color='#447e8a', alpha=0.1, linewidth=0.8)
    if shifted:
        chart.plot(xs, np.median(shifted, axis=0), color='#226473', linewidth=2, label='New relief, median')
    if profiles:
        chart.plot(
            xs, np.median([p[0] for p in profiles], axis=0), color='#a05a32', label='Blank control, median'
        )
        chart.legend(frameon=False)
    else:
        chart.text(0.5, 0.5, 'No isolated cross-sections', transform=chart.transAxes, ha='center')
    chart.axhline(0, color='.75', linewidth=0.7)
    chart.set(
        xlabel='Across the groove (mm)',
        ylabel='Relative brightness (0–255)',
        title='Profiles centered between their two bright shoulders',
    )
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--before', type=Path, required=True, help='registered blank bed')
    parser.add_argument('--after', type=Path, required=True, help='registered finished drawing')
    parser.add_argument('--repeat', type=Path, help='independent photograph of the unchanged finished bed')
    parser.add_argument(
        '--outline', type=Path, required=True, help='signed .thr containing the selected drawing'
    )
    parser.add_argument(
        '--all-motion', type=Path, help='signed .thr including all other potentially intersecting movements'
    )
    parser.add_argument(
        '--center',
        type=float,
        nargs=2,
        required=True,
        metavar=('X', 'Y'),
        help='working center in rectified pixels',
    )
    parser.add_argument(
        '--radius-px', type=float, required=True, help='measured working radius in the rectified photograph'
    )
    parser.add_argument(
        '--radius-mm', type=float, required=True, help='same physical working radius in millimeters'
    )
    parser.add_argument(
        '--native-px-per-mm',
        type=float,
        help='coarsest original sensor pixels per millimeter over the measured sand',
    )
    parser.add_argument(
        '--half-span', type=float, default=10.0, help='cross-section search length on each side, mm'
    )
    parser.add_argument('--spacing', type=float, default=3.5, help='distance between candidate sections, mm')
    parser.add_argument('--out', type=Path, required=True, help='directory for JSON and diagnostic image')
    args = parser.parse_args()
    try:
        if not np.isfinite([args.radius_px, args.radius_mm]).all() or min(args.radius_px, args.radius_mm) <= 0:
            raise ValueError('Both working radii must be positive and finite.')
        scale = args.radius_px / args.radius_mm
        center = np.asarray(args.center)
        before, after = [read_gray(p) for p in (args.before, args.after)]
        repeat = read_gray(args.repeat) if args.repeat else None
        points = motion_mm(args.outline, args.radius_mm)
        full = motion_mm(args.all_motion, args.radius_mm) if args.all_motion else points
        result, detail = measure(
            before,
            after,
            repeat,
            points,
            full,
            center,
            scale,
            args.half_span,
            args.spacing,
            args.native_px_per_mm,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')
    result.update(
        inputs={
            name: str(getattr(args, name))
            for name in ('before', 'after', 'repeat', 'outline', 'all_motion')
            if getattr(args, name)
        },
        radius_mm=args.radius_mm,
        radius_px=args.radius_px,
        center_px=center.tolist(),
        pass_count_source='full supplied drawing and travel path'
        if args.all_motion
        else 'supplied outline only',
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'measurement.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    plot(args.out / 'width-evidence.png', after, center, scale, result, detail)
    if result['status'] != 'measured':
        parser.exit(
            2,
            'Insufficient supported cross-sections, blank specificity or image resolution. See measurement.json.\n',
        )
    v = result['visible_ridge_spacing_mm']
    print(
        f"Median visible ridge spacing {v['median']:.2f} mm "
        f"(middle half {v['q25']:.2f}–{v['q75']:.2f} mm). "
        f"{result['sections_accepted']} of {result['sections_tested']} sections accepted. "
        f"{result['blank_control_detections']} blank detections."
    )
    count = result['single_pass_count']
    source = result['pass_count_source']
    if count:
        print(
            f"Single programmed pass ({source}): {result['single_pass_mm']['median']:.2f} mm "
            f"median across {count} sections."
        )
    else:
        print(f"No single-pass sections detected ({source}).")
    if args.native_px_per_mm is None:
        print(result['sampling_note'])


if __name__ == '__main__':
    main()
