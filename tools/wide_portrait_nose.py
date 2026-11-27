"""Measure the visible boundary under a photographed nose for wide-center sand art."""

import cv2
import numpy as np
from scipy.interpolate import splprep, splev
from scipy.ndimage import gaussian_filter1d, map_coordinates

from wide_portrait_hair import pick_face


def ambiguous_underside(intensity, previous, proposed, lateral, down, groove):
    """Check for a competing lower shadow between the proposed underside and the original stroke."""
    def underside(line):
        x = line @ lateral
        ends = sorted((int(np.argmin(x)), int(np.argmax(x))))
        # Exclude both upturned wings. Compare the underside at matching
        # positions across the nose, including when the head is tilted.
        bottom = line[ends[0]:ends[1] + 1]
        bottom = bottom[np.argsort(bottom @ lateral)]
        return bottom @ lateral, bottom @ down

    old_x, old_y = underside(previous)
    new_x, new_y = underside(proposed)
    left = max(old_x[0], new_x[0])
    right = min(old_x[-1], new_x[-1])
    if right - left < groove:
        return False
    xs = np.linspace(left, right, int(np.ceil((right - left) / (.10 * groove))) + 1)
    upper = np.interp(xs, new_x, new_y)
    separation = (np.interp(xs, old_x, old_y) - upper) / groove
    if separation.max() <= 1.4:
        return False
    filtered = cv2.GaussianBlur(intensity, (0, 0), max(.65, .22 * groove))
    origins = xs[:, None] * lateral + upper[:, None] * down

    def boundary(depth):
        near = origins + (depth - .4) * groove * down
        far = origins + (depth + .4) * groove * down
        return (map_coordinates(filtered, near.T[::-1], order=1, mode='nearest')
                - map_coordinates(filtered, far.T[::-1], order=1, mode='nearest'))

    strength = np.maximum(5., .85 * boundary(0))
    competing = np.zeros(len(xs), dtype=bool)
    for depth in np.arange(.8, 2.21, .2):
        competing |= (separation > depth - .15) & (boundary(depth) >= strength)
    ambiguous = (separation > 1.4) & competing
    edges = np.flatnonzero(np.diff(np.r_[False, ambiguous, False])).reshape(-1, 2)
    # An equally credible edge over one ball groove makes this replacement
    # visibly uncertain. A brief crossing by a beard hair does not.
    return any((end - start) * (xs[1] - xs[0]) >= groove for start, end in edges)


def measured_nose(gray, meshes, marks, diameter_mm, groove_mm, translation_mm=(0., 0.)):
    """Return a nose stroke in the prepared drawing's coordinates, or None without clear evidence."""
    if gray.ndim != 2 or gray.shape[0] != gray.shape[1] or diameter_mm <= 0 or groove_mm <= 0:
        return None
    size = len(gray)
    groove = groove_mm * size / diameter_mm
    if not np.isfinite(groove) or groove < 1 or not len(meshes):
        return None
    translate = np.asarray(translation_mm)
    scale = np.array([1., -1.]) * size / diameter_mm

    def points(kind):
        return [(np.asarray(m['points']) - translate) * scale + size / 2 for m in marks if m['kind'] in kind]

    eyes = sorted((line.mean(axis=0) for line in points(('eye', 'glasses'))), key=lambda p: p[0])
    mouth, old_nose = points(('smile',)), points(('nose',))
    if len(eyes) != 2 or len(mouth) != 1 or len(old_nose) != 1:
        return None
    try:
        mesh = pick_face(meshes, np.array([*eyes, mouth[0].mean(axis=0)]))
    except ValueError:
        return None
    if not np.isfinite(mesh).all():
        return None

    # Face Mesh's matching alar rims, nostrils and tip define a *search area*.
    # The two side creases end on the wings before they reach the cheek folds.
    wings = mesh[[102, 331]]
    span = np.linalg.norm(wings[1] - wings[0])
    if span < 6 * groove or np.linalg.norm(old_nose[0].mean(axis=0) - mesh[1]) > .38 * span:
        return None
    lateral = (wings[1] - wings[0]) / span
    if min((mesh[1] - wings[0]) @ lateral, (wings[1] - mesh[1]) @ lateral) < 1.65 * groove:
        return None  # The far wing is too foreshortened to resolve on this table.
    anchors = np.array([
        (mesh[131] + mesh[49]) / 2, mesh[49], mesh[102], mesh[48],
        mesh[218], mesh[44], (mesh[1] + mesh[19]) / 2, mesh[274],
        mesh[438], mesh[278], mesh[331], mesh[279], (mesh[279] + mesh[360]) / 2,
    ])
    if np.min(np.linalg.norm(np.diff(anchors, axis=0), axis=1)) < .08:
        return None
    try:
        spline, _ = splprep(anchors.T, s=(.095 * groove)**2 * len(anchors), k=3)
    except (TypeError, ValueError):
        return None  # Degenerate landmarks cannot provide a stable search area.
    line = np.array(splev(np.linspace(0, 1, 101), spline)).T
    tangents = np.gradient(line, axis=0)
    normal = np.column_stack([-tangents[:, 1], tangents[:, 0]])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-8)
    # Orient the search toward the darker underside even on a mirrored photo.
    toward_tip = mesh[2] - mesh[168]
    if np.dot(normal[len(normal) // 2], toward_tip) < 0:
        normal *= -1
    search_radius = min(.095 * span, 1.15 * groove)
    offsets = np.linspace(-search_radius, search_radius, 29)
    probes = line[:, None, :] + normal[:, None, :] * offsets[None, :, None]
    if probes.min() < groove or probes.max() >= size - groove:
        return None

    intensity = gray.astype('float32')

    def contrast(sigma, distance):
        filtered = cv2.GaussianBlur(intensity, (0, 0), max(.65, sigma * groove))
        step = normal[:, None, :] * distance * groove

        def measure(locations):
            return map_coordinates(filtered, [locations[..., 1], locations[..., 0]], order=1, mode='nearest')

        return measure(probes - step) - measure(probes + step)

    fine = contrast(.19, .38)
    coarse = contrast(.32, .61)
    broad = contrast(.65, .9)
    # Reward a persistent light-to-dark edge at two scales. A smooth offset
    # avoids jumping sideways to beard hair or nostril shadows between samples.
    score = np.minimum(fine, coarse) - 5 * (offsets / groove)**2
    transition = 3 * ((offsets[:, None] - offsets[None, :]) / (.22 * groove))**2
    previous = score[0]
    back = np.empty(score.shape, dtype='int16')
    for i in range(1, len(score)):
        choices = previous[:, None] - transition
        back[i] = np.argmax(choices, axis=0)
        previous = score[i] + np.max(choices, axis=0)
    selected = np.empty(len(line), dtype='int16')
    selected[-1] = np.argmax(previous)
    for i in range(len(line) - 1, 0, -1):
        selected[i - 1] = back[i, selected[i]]
    ix = np.arange(len(line))
    evidence = np.minimum(fine[ix, selected], coarse[ix, selected])
    # Both wings and the underside need support in the actual pixels. A flat
    # crop, an isolated moustache edge, or a shadow on one cheek cannot qualify.
    if np.median(broad[ix, selected]) < 10 or np.percentile(broad[ix, selected], 20) < 4:
        return None
    if np.median(evidence) < 9 or any(np.median(section) < 5 for section in np.array_split(evidence, 5)):
        return None
    if np.mean(evidence < 3) > .17:
        return None
    result = line + gaussian_filter1d(offsets[selected], 2.0)[:, None] * normal
    # End on the upward turn of each wing. Following the returning edge to the
    # middle of the nose makes a closed hook at groove width, especially in
    # strong side lighting. Keep the measured outer width of both wings.
    along = result @ lateral
    half = len(result) // 2
    left = np.flatnonzero(along[:half] <= min(along[:half]) + .6 * groove)[0]
    right = half + np.flatnonzero(along[half:] >= max(along[half:]) - .6 * groove)[-1]
    result = result[left:right + 1]
    simplified = cv2.approxPolyDP(result.astype('float32'), .10 * groove, False)[:, 0]
    if len(simplified) < 4:
        return None
    down = np.array([-lateral[1], lateral[0]])
    if down @ toward_tip < 0:
        down *= -1
    if ambiguous_underside(intensity, old_nose[0], simplified, lateral, down, groove):
        return None
    return {'kind': 'nose', 'closed': False, 'points': ((simplified - size / 2) / scale + translate).tolist()}
