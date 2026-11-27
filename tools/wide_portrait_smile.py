"""Measure one continuous lip opening for a wide-center sand portrait."""

import cv2
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import gaussian_filter1d, map_coordinates

from wide_portrait_hair import pick_face


# Inner lip landmarks, from one corner to the other on each edge.
UPPER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308]
LOWER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308]


def loop_sections(loop, x):
    """Return the upper and lower intersections of an existing loop at each x."""
    edges = np.roll(loop, -1, axis=0) - loop
    spans_x = np.abs(edges[:, 0]) > 1e-5
    start, edges = loop[spans_x], edges[spans_x]
    if not len(edges):
        return None
    fractions = (x[:, None] - start[:, 0]) / edges[:, 0]
    inside = (fractions >= 0) & (fractions < 1)
    if not np.all(inside.sum(axis=1) == 2):
        return None
    y = start[:, 1] + fractions * edges[:, 1]
    return np.array([np.min(np.where(inside, y, np.inf), axis=1),
                     np.max(np.where(inside, y, -np.inf), axis=1)])


def coherent_edge(score, offsets, penalty, unit=1.):
    """Choose one smoothly varying offset across consecutive photo columns."""
    previous = score[0]
    parents = np.zeros(score.shape, dtype=np.intp)
    for i in range(1, len(score)):
        jumps = (offsets[i - 1, :, None] - offsets[i, None, :]) / unit
        choices = previous[:, None] - penalty * jumps**2
        parents[i] = np.argmax(choices, axis=0)
        previous = score[i] + np.max(choices, axis=0)
    selected = np.empty(len(score), dtype=np.intp)
    selected[-1] = previous.argmax()
    for i in range(len(score) - 1, 0, -1):
        selected[i - 1] = parents[i, selected[i]]
    return selected


def measure_margin(blurred, anchors, other, x, width, groove, origin, across, down, central, old):
    """Search narrowly around the anatomical margin for a persistent edge or dark seam."""
    guide = PchipInterpolator(anchors[:, 0], anchors[:, 1])(x)
    opposite = PchipInterpolator(other[:, 0], other[:, 1])(x)
    # The limits taper to zero at both corners and never reach the opposite lip.
    radius = np.minimum.reduce([np.full_like(x, min(.64 * groove, .028 * width)),
                                .20 * np.minimum(x, width - x), .25 * np.abs(opposite - guide)])
    shifts = radius[:, None] * np.linspace(-1, 1, 17)
    origins = origin + x[:, None] * across

    def evidence(y, stations):
        positions = stations[:, None, :] + y[..., None] * down

        def at(distance):
            q = positions + distance * down
            return map_coordinates(blurred, q.transpose(2, 0, 1)[::-1], order=1, mode='nearest')

        center = at(0)

        def contrast(gap):
            before, after = at(-gap), at(gap)
            # The inner mouth can be lighter (teeth) or darker than the lip.
            # A thin dark seam can also separate the upper lip from the gum.
            return np.maximum(np.abs(before - after), 1.5 * (np.minimum(before, after) - center))

        return np.minimum(contrast(.35 * groove), contrast(.70 * groove))

    score = evidence(guide[:, None] + shifts, origins) - 10 * (shifts / groove)**2
    selected = coherent_edge(score, shifts, 4., .22 * groove)
    offset = gaussian_filter1d(shifts[np.arange(len(x)), selected], 2.2)
    measured = guide + np.clip(offset, -radius, radius)
    centers = origins[central]
    return measured, evidence(measured[central, None], centers)[:, 0], evidence(old[:, None], centers)[:, 0]


def measured_smile(gray, meshes, marks, diameter_mm, groove_mm, translation_mm=(0., 0.),
                   *, color=None, corners_only=False):
    """Propose a closed smile mark in drawing millimeters only for a visibly open mouth."""
    if gray.ndim != 2 or gray.shape[0] != gray.shape[1] or not len(meshes):
        return None
    if not np.isfinite([diameter_mm, groove_mm]).all() or min(diameter_mm, groove_mm) <= 0:
        return None
    size = len(gray)
    groove = groove_mm * size / diameter_mm
    if groove < 1:
        return None
    old = [m for m in marks if m['kind'] == 'smile']
    if len(old) != 1 or not old[0].get('closed'):
        return None
    translation = np.asarray(translation_mm)
    scale = np.array([1., -1.]) * size / diameter_mm

    def pixels(mark):
        return (np.asarray(mark['points']) - translation) * scale + size / 2

    previous = pixels(old[0])
    eyes = sorted((pixels(m).mean(axis=0) for m in marks if m['kind'] in ('eye', 'glasses')),
                  key=lambda p: p[0])
    if len(eyes) != 2 or len(previous) < 3 or not np.isfinite(previous).all() or not np.isfinite(eyes).all():
        return None
    meshes = [m for m in meshes if m.ndim == 2 and m.shape[0] > 473 and m.shape[1] == 2
              and np.isfinite(m[[468, 473, 61, 291]]).all()]
    if not meshes:
        return None
    try:
        mesh = pick_face(meshes, np.array([*eyes, previous.mean(axis=0)]))
    except ValueError:
        return None
    lip = mesh[[*UPPER, *LOWER]]
    if not np.isfinite(lip).all() or np.any((lip < 2 * groove) | (lip >= size - 2 * groove)):
        return None
    start = mesh[78]
    width = np.linalg.norm(mesh[308] - start)
    if width < 7 * groove:
        return None
    across = (mesh[308] - start) / width
    down = np.array([-across[1], across[0]])
    if (mesh[14] - mesh[13]) @ down < 0:
        down = -down
    basis = np.column_stack((across, down))
    upper, lower = (mesh[UPPER] - start) @ basis, (mesh[LOWER] - start) @ basis
    if min(np.diff(upper[:, 0]).min(), np.diff(lower[:, 0]).min()) <= .1:
        return None
    if (mesh[14] - mesh[13]) @ down < 1.50 * groove:
        return None

    if corners_only:
        # The phone's first engraving has an eight-point inner-lip loop.
        # More detailed outlines were measured by another tracing style.
        if len(previous) != 8:
            return None
        outline = extend_dark_corners(gray, (previous - start) @ basis, upper, lower, start, basis, groove)
        if outline is None:
            return None
        return {'kind': 'smile', 'closed': True,
                'points': ((outline - size / 2) / scale + translation).tolist()}

    if color is not None:
        if color.shape != (size, size, 3) or color.dtype != np.uint8:
            return None
        outline = gum_and_teeth(color, mesh, groove)
        if outline is None:
            return None
        return {'kind': 'smile', 'closed': True,
                'points': ((outline - size / 2) / scale + translation).tolist()}

    x = np.linspace(0, width, 65)
    central = (x >= .15 * width) & (x <= .85 * width)
    previous_y = loop_sections((previous - start) @ basis, x[central])
    if previous_y is None:
        return None
    blurred = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.7, .20 * groove))
    fitted, scores, old_scores = [], [], []
    for i, (guide, opposite) in enumerate(((upper, lower), (lower, upper))):
        y, strength, old_strength = measure_margin(
            blurred, guide, opposite, x, width, groove, start, across, down, central, previous_y[i])
        if np.median(strength) < 11 or any(np.median(section) < 6 for section in np.array_split(strength, 3)):
            return None
        weak = np.flatnonzero(np.diff(np.r_[False, strength < 4, False])).reshape(-1, 2)
        if any((end - begin) * (x[1] - x[0]) > 1.5 * groove for begin, end in weak):
            return None
        fitted.append(y)
        scores.append(np.mean(strength))
        old_scores.append(np.mean(old_strength))
    # Moustache and lip highlights can offer two credible contours. Keep the
    # previous drawing when it already follows edges of comparable strength.
    if np.mean(scores) < max(np.mean(old_scores) + 6, 1.20 * np.mean(old_scores)):
        return None
    top, bottom = fitted
    gap = bottom - top
    if min(gap) < -1e-7 or np.percentile(gap[central], 25) < 1.50 * groove:
        return None
    # Small adjustments inside the width of one sand groove already look the same.
    deviation = np.abs(np.array(fitted)[:, central] - previous_y)
    if np.mean(deviation) < .45 * groove or np.percentile(deviation, 75) < .65 * groove:
        return None
    loop = np.column_stack((np.r_[x, x[-2:0:-1]], np.r_[top, bottom[-2:0:-1]])) @ basis.T + start
    outline = cv2.approxPolyDP(loop.astype('float32'), .075 * groove, True)[:, 0]
    if len(outline) < 6:
        return None
    return {'kind': 'smile', 'closed': True, 'points': ((outline - size / 2) / scale + translation).tolist()}


def extend_dark_corners(gray, prior, upper, lower, origin, basis, groove):
    """Extend a coarse mouth only where its opening continues into a dark corner."""
    width = upper[-1, 0]
    ends = prior[[prior[:, 0].argmin(), prior[:, 0].argmax()]]
    old_width = ends[1, 0] - ends[0, 0]
    if not .65 * width < old_width < 1.35 * width:
        return None
    blurred = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.75, .22 * groove))

    def sample(x, y):
        pos = origin + x[..., None] * basis[:, 0] + y[..., None] * basis[:, 1]
        return map_coordinates(blurred, pos.transpose(2, 0, 1)[::-1], order=1, mode='nearest')

    extended = {}
    for side, direction in enumerate((1, -1)):
        # Search at the independently located inside lip junction. Shadows
        # outside the mouth commonly continue above, below, or into the cheek.
        x, y = np.meshgrid(side * width + direction * width * np.linspace(-.095, .15, 51),
                           width * np.linspace(-.075, .075, 37))
        center = np.mean([sample(x + direction * g * groove, y) for g in (0, .18, .40)], axis=0)
        outside = np.mean([sample(x - direction * g * groove, y) for g in (.55, 1., 1.5)], axis=0) - center
        near = x + direction * .1 * groove
        vertical = [.68 * groove, .95 * groove, 1.25 * groove]
        above = np.mean([sample(near, y - distance) for distance in vertical], axis=0) - center
        below = np.mean([sample(near, y + distance) for distance in vertical], axis=0) - center
        weakest = np.minimum.reduce([outside, above, below])
        distance = (np.abs(x - side * width) + .7 * np.abs(y)) / groove
        score = .5 * weakest + .3 * outside + .1 * (above + below) - 1.7 * distance
        best = np.unravel_index(score.argmax(), score.shape)
        extension = direction * (ends[side, 0] - x[best])
        if groove < extension < .22 * width and min(weakest[best], score[best]) > 18:
            extended[side] = np.array([x[best], y[best]])
    if not extended:
        return None

    revised = ends.copy()
    for side, point in extended.items():
        revised[side] = point
    x = np.linspace(revised[0, 0], revised[1, 0], 81)
    old_x = np.clip(x, ends[0, 0] + 1e-4, ends[1, 0] - 1e-4)
    measured_x = (x - x[0]) * width / (x[-1] - x[0])
    old = loop_sections(prior, old_x)
    if old is None:
        return None
    for side, point in extended.items():
        progress = np.abs(x - point[0])
        # Follow the measured upper and lower lip near the corner. Fade
        # into the old contour before the middle of the smile.
        weight = .5 + .5 * np.cos(np.pi * np.clip(progress / (.43 * old_width), 0, 1))
        for edge, guide in zip(old, (upper, lower)):
            margin = np.interp(measured_x, guide[:, 0], guide[:, 1])
            lift = point[1] - guide[0 if side == 0 else -1, 1]
            margin += lift * np.clip(1 - progress / (.19 * old_width), 0, 1)
            margin = point[1] + (margin - point[1]) * np.clip(progress / (1.2 * groove), 0, 1)
            edge += weight * (margin - edge)
    top, bottom = old
    if np.min(bottom - top) < -1e-6:
        return None
    loop = np.c_[np.r_[x, x[-2:0:-1]], np.r_[top, bottom[-2:0:-1]]] @ basis.T + origin
    return cv2.approxPolyDP(loop.astype('float32'), .105 * groove, True)[:, 0]


def gum_and_teeth(image, mesh, groove):
    """Trace the top of visible gum and the lower tooth edge as one open smile."""
    # The two outside lip corners bound the gum as well as the teeth. Using
    # just the inside corners can cut off a dark, but clearly open, corner.
    start, end = mesh[[61, 291]]
    width = np.linalg.norm(end - start)
    if width < 7 * groove:
        return None
    across = (end - start) / width
    down = np.array([-across[1], across[0]])
    if (mesh[14] - mesh[13]) @ down < 0:
        down = -down
    basis = np.column_stack((across, down))
    x = np.linspace(0, width, 81)
    guides = []
    for indices in (UPPER, LOWER, [61, 40, 37, 0, 267, 270, 291]):
        vertices = mesh[[61, *indices[1:-1], 291]]
        if not np.isfinite(vertices).all() or np.any((vertices < 2 * groove) | (vertices >= len(image) - 2 * groove)):
            return None
        v = (vertices - start) @ basis
        if np.min(np.diff(v[:, 0])) <= .1:
            return None
        guides.append(PchipInterpolator(v[:, 0], v[:, 1])(x))
    top, bottom, outer_lip = guides
    if np.min(bottom - top) < -1e-6:
        return None
    stations = start + x[:, None] * across
    blur = cv2.GaussianBlur(image, (0, 0), max(.65, .17 * groove))
    lab = cv2.cvtColor(blur, cv2.COLOR_BGR2LAB).astype('float32')

    def color_at(y):
        pixels = stations[:, None] + y[..., None] * down
        coords = pixels.transpose(2, 0, 1)[::-1]
        return np.stack([map_coordinates(lab[:, :, i], coords, order=1, mode='nearest')
                         for i in (0, 1)], axis=-1)

    middle = (x > .25 * width) & (x < .75 * width)
    teeth, gum, lip, above_gum = color_at(np.column_stack(
        (.39 * top + .61 * bottom, top, bottom + .75 * groove, outer_lip))).transpose(1, 0, 2)
    # Require light, less-red teeth, a separately visible gum band above
    # them, and a lip beneath. A closed, bearded or shadowed mouth keeps
    # its original drawing when any color comparison is inconclusive.
    for other, min_light in ((gum, 18.), (lip, 14.)):
        contrast = teeth[middle] - other[middle]
        if np.percentile(contrast[:, 0], 25) < min_light or np.percentile(-contrast[:, 1], 25) < 5:
            return None
    if np.median((above_gum - gum)[middle, 0]) < 14 or np.median((bottom - top)[middle]) < 2.2 * groove:
        return None

    taper = np.clip(np.minimum(x, width - x) / (.07 * width), 0., 1.)
    # At the dark corners the lower lip is lighter than the opening. Learn
    # the change in polarity from each column so no corner is invented.
    polarity = gaussian_filter1d(np.clip((teeth[:, 0] - lip[:, 0] - 2.) / 27., -1, 1), 3.)
    upper_bounds = (np.maximum(np.minimum(top, outer_lip) - .35 * groove * taper, top - 2.6 * groove * taper),
                    top + np.minimum(.45 * groove, .15 * (bottom - top)) * taper)
    lower_bounds = (bottom - np.minimum(1.65 * groove, .36 * (bottom - top)) * taper,
                    bottom + 1.1 * groove * taper)
    margins = []
    for bounds, guide, sign, red_weight in (
        (upper_bounds, (outer_lip + top) / 2, np.ones_like(x), .45),
        (lower_bounds, bottom, polarity, .65),
    ):
        lo, hi = bounds
        y = lo[:, None] + (hi - lo)[:, None] * np.linspace(0, 1, 37)
        above, below = color_at(y - .35 * groove), color_at(y + .35 * groove)
        light = above[:, :, 0] - below[:, :, 0]
        red = below[:, :, 1] - above[:, :, 1]
        residual = (y - guide[:, None]) / groove
        score = sign[:, None] * light + red_weight * red - 1.2 * residual**2
        selected = coherent_edge(score, residual, 35.)
        chosen = score[np.arange(len(x)), selected]
        if min(np.median(section) for section in np.array_split(chosen[middle], 3)) < 9:
            return None
        observed = y[np.arange(len(x)), selected]
        margins.append(guide + gaussian_filter1d(observed - guide, 1.6) * taper)
    top, bottom = margins
    if np.min(bottom - top) < -1e-6 or np.percentile((bottom - top)[middle], 25) < 1.5 * groove:
        return None
    loop = np.c_[np.r_[x, x[-2:0:-1]], np.r_[top, bottom[-2:0:-1]]] @ basis.T + start
    outline = cv2.approxPolyDP(loop.astype('float32'), .075 * groove, True)[:, 0]
    return outline if len(outline) >= 6 else None
