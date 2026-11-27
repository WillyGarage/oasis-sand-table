"""Photograph-supported eyelids and iris edges for a wide sand portrait."""

import cv2
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import map_coordinates

from wide_portrait_hair import pick_face


# Each list runs in the same direction across the face. The last five points
# are the model's iris center and its four rim measurements.
EYES = [
    ([33, 246, 161, 160, 159, 158, 157, 173, 133],
     [33, 7, 163, 144, 145, 153, 154, 155, 133], [468, 469, 470, 471, 472]),
    ([362, 398, 384, 385, 386, 387, 388, 466, 263],
     [362, 382, 381, 380, 374, 373, 390, 249, 263], [473, 474, 475, 476, 477]),
]


def eye_observations(gray, mesh, indices, groove):
    upper, lower, iris = (mesh[ids] for ids in indices)
    points = np.vstack((upper, lower, iris))
    if not np.isfinite(points).all() or points.min() < groove or points.max() >= len(gray) - groove:
        return {}
    origin = upper[0]
    width = np.linalg.norm(upper[-1] - origin)
    if width < 5.5 * groove:
        return {}
    across = (upper[-1] - origin) / width
    down = np.array([-across[1], across[0]])
    if (lower[4] - upper[4]) @ down < 0:
        down *= -1
    basis = np.column_stack((across, down))
    top, bottom, ring = ((line - origin) @ basis for line in (upper, lower, iris))
    if min(np.min(np.diff(top[:, 0])), np.min(np.diff(bottom[:, 0]))) <= .01:
        return {}
    lid = [PchipInterpolator(*edge.T) for edge in (top, bottom)]
    xs = np.linspace(0, width, 33)
    if (lid[1](xs) - lid[0](xs)).min() < -.01:
        return {}
    center = ring[0]
    if not .20 * width < center[0] < .80 * width:
        return {}
    # Project the two measured semiaxes into eye coordinates. A tilted iris
    # remains an ellipse, including when only a short piece is between the lids.
    axes = np.column_stack(((ring[1] - ring[3]) / 2, (ring[2] - ring[4]) / 2))
    cov = axes @ axes.T
    if cov[1, 1] < groove**2 or np.linalg.det(cov) <= 0:
        return {}
    tilt = cov[0, 1] / cov[1, 1]
    radius = np.sqrt(cov[0, 0] - cov[0, 1] * tilt)
    if radius < groove or radius > .34 * width or np.sqrt(cov[1, 1]) > .35 * width:
        return {}

    def height(x, v):
        return (1 - v) * lid[0](x) + v * lid[1](x)

    def pixels(x, y):
        return np.stack((x, y), axis=-1) @ basis.T + origin

    def brightness(x, y):
        return map_coordinates(gray, pixels(x, y).T[::-1], order=1, mode='nearest')

    # Check the actual photo along both model lids. A vertical stripe alone
    # could otherwise look like an iris in a closed or obscured eye.
    stations = np.linspace(.13, .87, 21) * width
    for curve in lid:
        margin = curve(stations)
        middle = brightness(stations, margin)
        evidence = []
        for reach in (.4 * groove, .75 * groove):
            before = brightness(stations, margin - reach)
            after = brightness(stations, margin + reach)
            evidence.append(np.maximum(abs(before - after), 1.45 * (np.minimum(before, after) - middle)))
        strength = np.min(evidence, axis=0)
        if np.median(strength) < 8 or any(np.median(section) < 4.5 for section in np.array_split(strength, 3)):
            return {}

    def edge(v, sign, shift):
        x = np.full_like(v, center[0] + shift + sign * radius)
        for _ in range(8):
            dy = height(x, v) - center[1]
            radial = 1 - dy**2 / cov[1, 1]
            if np.min(radial) < .03:
                return None
            new_x = center[0] + shift + tilt * dy + sign * radius * np.sqrt(radial)
            movement = np.max(np.abs(new_x - x))
            x = new_x
        if movement > .12 * groove:
            return None
        return x

    def light(x, v):
        return brightness(x, height(x, v))

    observations = {}
    for sign in (-1, 1):
        rows = np.array([.23, .34, .45, .56, .67, .78])
        best = None
        # Shift the measured arc as a whole. The iris cannot zigzag around an
        # eyelash or chase the small white reflection on an otherwise dark eye.
        for shift in np.linspace(-1., 1., 19) * min(.12 * width, .90 * groove):
            x = edge(rows, sign, shift)
            if x is None or np.min(np.minimum(x, width - x)) < 1.25 * groove:
                continue
            strengths, relatives = [], []
            for gap in (.43 * groove, .74 * groove):
                white = light(x + sign * gap, rows)
                dark = light(x - sign * gap, rows)
                strengths.append(white - dark)
                relatives.append((white - dark) / np.maximum(24, .5 * (white + dark)))
            strength = np.min(strengths, axis=0)
            relative = np.min(relatives, axis=0)
            if np.percentile(strength, 25) < 5 or np.median(strength) < 8 or np.median(relative) < .12:
                continue
            quality = np.median(strength) + .5 * np.percentile(strength, 25) - 5 * abs(shift) / groove
            if best is None or quality > best[0]:
                best = quality, shift
        if best is None:
            continue
        quality, shift = best
        v = np.linspace(0., 1., 13)
        x = edge(v, sign, shift)
        if x is None:
            continue
        y = height(x, v)
        if min(lid[1](x) - lid[0](x)) < 1.50 * groove:
            continue
        iris_edge = pixels(x, y)
        # Keep the two margins and the two joins as separate arrays so the
        # route can enter the iris and retrace it without crossing white sand.
        ts = np.unique(np.r_[xs[1:-1], top[1:-1, 0], x[0]])
        bs = np.unique(np.r_[xs[1:-1], bottom[1:-1, 0], x[-1]])
        ts, bs = np.r_[0, ts, width], np.r_[0, bs, width]
        up, lo = pixels(ts, lid[0](ts)), pixels(bs, lid[1](bs))
        aperture = np.vstack((up, lo[-2:0:-1]))
        # Require room for light sand on the observed side after engraving at
        # the ball width. Measure the largest circle inside this specific cell.
        white_top = ts[(ts - x[0]) * sign > 0]
        white_bottom = bs[(bs - x[-1]) * sign > 0]
        if sign < 0:
            white_top, white_bottom = white_top[::-1], white_bottom[::-1]
        cell = np.vstack((iris_edge, pixels(white_bottom, lid[1](white_bottom)),
                          pixels(white_top, lid[0](white_top))[::-1]))
        scale = 10 / groove
        poly = np.round((cell - cell.min(axis=0)) * scale).astype('int32') + 2
        mask = np.zeros((poly[:, 1].max() + 3, poly[:, 0].max() + 3), 'uint8')
        cv2.fillPoly(mask, [poly], 1)
        white_radius = (cv2.distanceTransform(mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE).max() - .5) / scale
        if white_radius < .60 * groove:
            continue
        ti, bi = np.searchsorted(ts, x[0]), np.searchsorted(bs, x[-1])
        observations[sign] = dict(
            quality=quality, center=origin + (center + [shift, 0]) @ basis.T,
            center_fraction=(center[0] + shift) / width, iris=iris_edge, aperture=aperture,
            upper=up, lower=lo, top_join=ti, bottom_join=bi, white_radius=white_radius)
    return observations


def measured_eyes(gray, meshes, marks, diameter_mm, groove_mm, translation_mm=(0., 0.)):
    """Return variants of two indexed eye marks, with iris, center and aperture in drawing mm."""
    if gray.ndim != 2 or gray.shape[0] != gray.shape[1] or not np.isfinite([diameter_mm, groove_mm]).all():
        return []
    if min(diameter_mm, groove_mm) <= 0:
        return []
    size = len(gray)
    groove = groove_mm * size / diameter_mm
    scale = np.array([1., -1.]) * size / diameter_mm
    trans = np.asarray(translation_mm)
    eyes = [(i, m) for i, m in enumerate(marks) if m['kind'] == 'eye']
    mouths = [m for m in marks if m['kind'] == 'smile']
    if groove < 1 or len(eyes) != 2 or len(mouths) != 1:
        return []

    def to_mm(p):
        return ((p - size / 2) / scale + trans).tolist()

    def to_pixels(m):
        return (np.asarray(m['points']) - trans) * scale + size / 2

    for _, m in eyes:
        pts = to_pixels(m)
        if not m['closed'] or len(pts) < 3 or 'lids' in m or not np.isfinite(pts).all():
            return []
        # A retraced branch already engraves iris detail. Keep the original.
        if np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(np.unique(pts.round(4), axis=0)) != len(pts):
            return []
    meshes = [m for m in meshes if m.ndim == 2 and m.shape[0] >= 478 and m.shape[1] == 2
              and np.isfinite(m[[468, 473, 61, 291]]).all()]
    expected = np.array([to_pixels(m).mean(axis=0) for _, m in eyes])
    mouth = to_pixels(mouths[0]).mean(axis=0)
    if not np.isfinite(mouth).all():
        return []
    try:
        mesh = pick_face(meshes, np.array([*sorted(expected, key=lambda p: p[0]), mouth]))
    except ValueError:
        return []
    # Associate each model eye with its own prepared mark, including a mirror.
    centers = mesh[[468, 473]]
    if np.linalg.norm(expected - centers[::-1], axis=1).sum() < np.linalg.norm(expected - centers, axis=1).sum():
        eyes.reverse()

    blurred = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.60, .13 * groove))
    pair = [eye_observations(blurred, mesh, ids, groove) for ids in EYES]
    choices = []
    for side in set(pair[0]).intersection(pair[1]):
        first, second = pair[0][side], pair[1][side]
        if max(first['quality'], second['quality']) < 24:
            continue
        if abs(first['center_fraction'] - second['center_fraction']) > .21:
            continue
        choices.append((min(first['quality'], second['quality']), side))
    if not choices:
        return []
    side = max(choices)[1]
    variants = []
    for from_upper in (True, False):
        result = []
        for (i, _), observation in zip(eyes, pair):
            e = observation[side]
            iris, up, lo = e['iris'], e['upper'], e['lower']
            if from_upper:
                split = e['top_join']
                outline = np.vstack((up[:split], iris, iris[-2::-1], up[split+1:], lo[-2:0:-1]))
            else:
                split = e['bottom_join']
                outline = np.vstack((lo[:split], iris[::-1], iris[1:], lo[split+1:], up[-2:0:-1]))
            result.append(dict(index=i, mark=dict(kind='eye', closed=True, points=to_mm(outline)),
                               aperture=to_mm(e['aperture']), iris=to_mm(iris), center=to_mm(e['center'])))
        variants.append(result)
    return variants


def dark_iris_center(gray, feature, groove):
    """Locate a vertical dark stroke with photographed light on both sides of the iris."""
    upper, lower = feature['upper'], feature['lower']
    origin = upper[0]
    across = upper[-1] - origin
    width = np.linalg.norm(across)
    across /= width
    down = np.array([-across[1], across[0]])
    if (lower[len(lower) // 2] - upper[len(upper) // 2]) @ down < 0:
        down *= -1
    axes = np.column_stack((across, down))
    top, bottom = (edge @ axes for edge in (upper - origin, lower - origin))
    target = (feature['center'] - origin) @ across

    def sample_column(x, levels):
        upper_y = np.interp(x, top[:, 0], top[:, 1])
        lower_y = np.interp(x, bottom[:, 0], bottom[:, 1])
        y = upper_y + levels * (lower_y - upper_y)
        xy = origin + np.column_stack((np.full(len(y), x), y)) @ axes.T
        return xy, map_coordinates(gray, xy.T[::-1], order=1, mode='nearest')

    # The most visible iris flank can differ through two reflective lenses.
    # In that case the drawing uses the dark centers of both eyes, and each
    # must independently have lighter pixels on *both* sides at several depths.
    levels = np.array([.24, .36, .48, .60, .72])
    best = None
    for shift in np.linspace(-.55, .55, 13) * groove:
        x = target + shift
        if min(x, width - x) < 1.7 * groove:
            continue
        _, center = sample_column(x, levels)
        scores = []
        for sign in (-1, 1):
            distances = np.linspace(1.5 * groove, min(2.5 * groove, x if sign < 0 else width - x), 7)
            light = np.array([sample_column(x + sign * reach, levels)[1] for reach in distances])
            # A single narrow glint must not qualify as visible sclera.
            contrast = np.percentile(light, 70, axis=0) - center
            scores.append(np.percentile(contrast, 25))
        strength = min(scores)
        relative = strength / max(24., np.mean(center))
        if strength < 9 or relative < .21:
            continue
        quality = strength - 3 * abs(shift) / groove
        if best is None or quality > best[0]:
            best = quality, x
    if best is None:
        return None
    x = best[1]
    core, _ = sample_column(x, np.linspace(0., .83, 11))
    if np.linalg.norm(core[0] - core[-1]) < groove:
        return None
    split = np.searchsorted(top[:, 0], x)
    stroke = np.vstack((upper[:split], core, core[-2::-1], upper[split:]))
    return stroke, core


def lens_observations(gray, mesh, groove):
    """Measure a shared iris edge, or the independently supported dark center of each eye."""
    levels = (1., .82, .73)
    blurred = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.65, .12 * groove))
    found = []
    for indices in EYES:
        sides = {}
        for level in levels:
            for side, observed in eye_observations(blurred, mesh, indices, groove * level).items():
                if side not in sides or sides[side]['quality'] < observed['quality']:
                    sides[side] = observed
        if not sides:
            return None
        found.append(sides)
    shared = found[0].keys() & found[1].keys()
    if shared:
        side = max(shared, key=lambda k: min(pair[k]['quality'] for pair in found))
        pair = [s[side] for s in found]
        if min(e['quality'] for e in pair) >= 18:
            return pair, False
    return [max(s.values(), key=lambda e: e['quality']) for s in found], True


def lower_iris_return(gray, feature, groove):
    """Follow a visible iris flank to the dark lower edge under its photographed center."""
    iris, upper, lower = feature['iris'], feature['upper'], feature['lower']
    across = upper[-1] - upper[0]
    across /= np.linalg.norm(across)
    down = np.array([-across[1], across[0]])
    if (lower[len(lower) // 2] - upper[len(upper) // 2]) @ down < 0:
        down *= -1
    reach = (feature['center'] - iris[-1]) @ across
    if not .70 * groove < abs(reach) < 2.75 * groove:
        return None

    axes = np.column_stack((across, down))
    top, bottom = ((edge - upper[0]) @ axes for edge in (upper, lower))
    center_x = (feature['center'] - upper[0]) @ across
    if min(center_x, top[-1, 0] - center_x) < 2.5 * groove:
        return None

    def light(points):
        return map_coordinates(gray, np.moveaxis(points[..., ::-1], -1, 0), order=1, mode='nearest')

    def upper_samples(offsets):
        # A reflection can wash out the bottom of a dark iris. Confirm its
        # center and both lighter sides inside the upper part of the opening.
        xx = center_x + groove * offsets
        top_y = np.interp(xx, top[:, 0], top[:, 1])
        depth = np.interp(xx, bottom[:, 0], bottom[:, 1]) - top_y
        yy = top_y + np.array([.22, .32, .42])[:, None] * depth
        return light(upper[0] + xx[None, :, None] * across + yy[:, :, None] * down)

    middle = np.median(upper_samples(np.linspace(-.18, .18, 5)), axis=1)
    for side in (-1, 1):
        flank = np.percentile(upper_samples(side * np.linspace(1.5, 2.5, 9)), 70, axis=1)
        contrast = np.percentile(flank - middle, 25)
        if contrast < 9 or contrast < .21 * max(24., np.mean(middle)):
            return None

    t = np.linspace(0., 1., 13)
    x = (iris[-1] - upper[0]) @ across + t * reach
    y = np.interp(x, bottom[:, 0], bottom[:, 1])
    base = upper[0] + x[:, None] * across + y[:, None] * down

    # A reflection may hide one side of the iris. On the visible side the
    # measured flank already has lighter pixels outside it. The return to center
    # needs its own continuous dark-to-light boundary in the photograph.
    best = None
    for end_shift in np.linspace(-.45, .45, 9) * groove:
        for bow in (-.24, 0., .24):
            q = base + (t * end_shift + 4 * t * (1 - t) * bow * groove)[:, None] * down
            above = (light(q - .42 * groove * down) + light(q - .72 * groove * down)) / 2
            below = (light(q + .40 * groove * down) + light(q + .75 * groove * down)) / 2
            contrast = below - above
            strength = np.median(contrast)
            floor = np.percentile(contrast, 15)
            if floor < 4.5 or strength < 9:
                continue
            score = strength + .55 * np.percentile(contrast, 20) - 1.5 * abs(end_shift) / groove
            if best is None or score > best[0]:
                best = score, q
    if best is None or best[0] < 12:
        return None
    core = np.vstack((iris, best[1][1:]))
    cut = feature['top_join']
    return np.vstack((upper[:cut], core, core[-2::-1], upper[cut+1:])), core


def measured_lens_eyes(gray, meshes, marks, diameter_mm, groove_mm, translation_mm=(0., 0.)):
    """Fit a sparse upper eyelid and its visible iris edge inside each spectacle rim."""
    lenses = [m for m in marks if m['kind'] == 'glasses']
    mouths = [m for m in marks if m['kind'] == 'smile']
    if len(lenses) != 2 or len(mouths) != 1 or any(m['kind'] == 'eye' for m in marks):
        return None
    if (gray.ndim != 2 or gray.shape[0] != gray.shape[1] or
            not np.isfinite([diameter_mm, groove_mm]).all() or min(diameter_mm, groove_mm) <= 0):
        return None
    size = len(gray)
    scalar = size / diameter_mm
    groove = groove_mm * scalar
    if groove < 1:
        return None
    scale = np.array([scalar, -scalar])
    offset = np.asarray(translation_mm)

    def pixels(mark):
        return (np.asarray(mark['points']) - offset) * scale + size / 2

    def mm(points):
        return ((points - size / 2) / scale + offset).tolist()

    if any(not m['closed'] or len(m['points']) < 3 for m in lenses):
        return None
    rims = [pixels(m).astype('float32') for m in lenses]
    expected = [*sorted((r.mean(axis=0) for r in rims), key=lambda v: v[0]), pixels(mouths[0]).mean(axis=0)]
    plausible = [m for m in meshes if m.ndim == 2 and m.shape[0] >= 478 and m.shape[1] == 2
                 and np.isfinite(m).all()]
    try:
        mesh = pick_face(plausible, np.array(expected))
    except ValueError:
        return None
    # A sparse upper lid has no closed cell around the white of the eye. Read
    # the edges at finer image resolution, then check the iris hook, aperture,
    # spectacle rim and final signed excursion at the physical groove width.
    observed = lens_observations(gray, mesh, groove)
    if observed is None:
        return None
    pair, need_center = observed
    if abs(pair[0]['center_fraction'] - pair[1]['center_fraction']) > .21:
        return None
    blurred = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.6, .1 * groove))
    centers = []
    if need_center:
        centers = [dark_iris_center(blurred, feature, groove) for feature in pair]
        if any(center is None for center in centers):
            centers = [lower_iris_return(blurred, feature, groove) for feature in pair]
            if any(center is None for center in centers):
                return None
    result, used = [], set()
    for index, feature in enumerate(pair):
        upper, iris = feature['upper'], feature['iris']
        if np.linalg.norm(upper[-1] - upper[0]) < 5.5 * groove or feature['quality'] < 18:
            return None
        depth = np.linalg.norm(upper - iris[-1], axis=1).min()
        if depth < 1.03 * groove or feature['white_radius'] < .44 * groove:
            return None
        split = feature['top_join']
        if need_center:
            points, iris = centers[index]
        else:
            points = np.vstack((upper[:split], iris, iris[-2::-1], upper[split+1:]))
        resolved = np.vstack((feature['aperture'], iris))
        inside = [i for i, rim in enumerate(rims) if all(
            cv2.pointPolygonTest(rim, tuple(map(float, p)), True) >= 1.25 * groove for p in resolved)]
        if len(inside) != 1 or inside[0] in used:
            return None
        used.add(inside[0])
        result.append(dict(mark=dict(kind='shade', closed=False, points=mm(points)),
                           iris=mm(iris), aperture=mm(feature['aperture']),
                           rim=mm(rims[inside[0]])))
    return result
