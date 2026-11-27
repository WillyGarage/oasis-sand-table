"""Locate the dark band of each photographed eyebrow in the aligned face crop."""

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates

from wide_portrait_hair import pick_face


def brow_stroke(gray, brow, eye, groove, broad=False, *, anatomy=False):
    """Search between forehead and eyelid in brow-local coordinates, including head tilt."""
    origin = brow[0]
    length = np.linalg.norm(brow[-1] - origin)
    if length < 5 * groove or len(brow) < 3:
        return None
    across = (brow[-1] - origin) / length
    down = np.array([-across[1], across[0]])
    if (eye.mean(axis=0) - brow.mean(axis=0)) @ down < 0:
        down = -down
    along = (brow - origin) @ across
    if np.any(np.diff(along) <= 0):
        return None
    x = np.linspace(.025, .975, 41) * length
    offset = np.interp(x, along, (brow - origin) @ down)
    centerline = origin + x[:, None] * across + offset[:, None] * down
    # A brow is a band of hair with lighter skin on both sides. A hairline,
    # glasses rim or socket shadow can have just one strong edge.
    steps = (np.linspace(-.14, .36, 43) if broad else np.linspace(-.14, .22, 31)) * length
    centers = centerline[:, None, :] + steps[None, :, None] * down
    reach = (.20 if broad else .14) * length
    if np.min(centers) < reach or np.max(centers) >= len(gray) - reach:
        return None
    smooth = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.8, .019 * length))

    def light(displacement):
        where = centers + displacement * down
        return map_coordinates(smooth, [where[..., 1], where[..., 0]], order=1, mode='nearest')

    middle = light(0)
    above = (light(-.095 * length) + light(-reach)) / 2 - middle
    below = (light(.095 * length) + light(reach)) / 2 - middle
    support = np.minimum(above, below)
    if broad:
        # A thick brow can fill the shorter pair of probes. At this scale
        # require a strong dark band and keep the search in the brow's half
        # of the socket so that a dark eyelid cannot win.
        outer = np.minimum(light(-.18 * length), light(.18 * length)) - middle
        support = .8 * np.maximum(support, outer)
    # Enforce physical separation from the visible lid even on a very narrow
    # eye. Also limit adjacent columns' rate of departure from the initial arch.
    gap = np.linalg.norm(centers[:, :, None, :] - eye, axis=-1).min(axis=2)
    score = support - 3 * (steps / (.16 * length)) ** 2
    score[gap < max(1.6 * groove, (.18 if broad else .14) * length)] = -1000
    if broad:
        eye_level = (eye.mean(axis=0) - origin) @ down
        score[steps[None, :] > .54 * (eye_level - offset[:, None])] = -1000
    transition = 3.5 * ((steps[:, None] - steps) / (.038 * length)) ** 2
    previous = score[0].copy()
    parents = np.zeros(score.shape, dtype=int)
    for i in range(1, len(x)):
        costs = previous[:, None] - transition
        parents[i] = np.argmax(costs, axis=0)
        previous = score[i] + costs.max(axis=0)
    selected = [previous.argmax()]
    for row in parents[:0:-1]:
        selected.append(row[selected[-1]])
    selected.reverse()
    confidence = support[np.arange(len(x)), selected]
    clear = (confidence >= 7) & (score[np.arange(len(x)), selected] > -100)
    # Do not bridge through bangs, carry a guess out onto the temple, or
    # move a brow when the initial stroke already follows the photograph.
    if anatomy:
        # Here the guide is an independent face measurement. Trace a single
        # continuous, well-lit band; a dim temple can hide either end.
        visible = (gaussian_filter1d(confidence, 1.5) >= 10) & (score[np.arange(len(x)), selected] > -100)
        runs = np.flatnonzero(np.diff(np.r_[False, visible, False])).reshape(-1, 2)
        if not len(runs):
            return None
        a, stop = max(runs, key=lambda run: run[1] - run[0])
        if stop - a < .60 * len(x) or np.median(confidence[a:stop]) < 15:
            return None
        b = stop - 1
    else:
        minimum_contrast = 21 if broad else 13
        if np.mean(clear) < .74 or np.median(confidence) < minimum_contrast:
            return None
        a, b = np.flatnonzero(clear)[[0, -1]]
        if b - a < .73 * len(x) or np.any(np.convolve((~clear[a:b+1]).astype(int), np.ones(5), 'valid') >= 5):
            return None
    shift = gaussian_filter1d(steps[selected], 1.25, mode='nearest')
    if not anatomy and np.median(np.abs(shift[a:b + 1])) < .42 * groove:
        return None
    line = centerline + shift[:, None] * down
    line = line[a:b + 1]
    return cv2.approxPolyDP(line.astype('float32'), .09 * groove, False)[:, 0].astype(float)


def photographed_brows(gray, marks, diameter, width, translation):
    """Yield individually supported replacement strokes, in the drawing's millimeters."""
    scale = len(gray) / diameter * np.array([1., -1.])
    origin = np.asarray(translation)

    def pixels(mark):
        return (np.asarray(mark['points']) - origin) * scale + len(gray) / 2

    brows = [(i, pixels(m)) for i, m in enumerate(marks) if m['kind'] == 'brow']
    eyes = [pixels(m) for m in marks if m['kind'] == 'eye']
    if len(brows) != 2 or len(eyes) != 2:
        return
    eyes.sort(key=lambda q: q[:, 0].mean())
    brows.sort(key=lambda entry: entry[1][:, 0].mean())
    for (index, brow), eye in zip(brows, eyes):
        line = brow_stroke(gray, brow, eye, width * len(gray) / diameter)
        if line is None:
            line = brow_stroke(gray, brow, eye, width * len(gray) / diameter, broad=True)
        if line is not None:
            yield index, {**marks[index], 'points': ((line - len(gray) / 2) / scale + origin).tolist()}



def darker_than_earlier_brow(gray, line, previous, groove):
    """Check the same columns on the earlier brow and the newly measured hair."""
    if len(line) < 2 or len(previous) < 2:
        return False
    direction = line[-1] - line[0]
    span = np.linalg.norm(direction)
    if span < 4 * groove:
        return False
    direction /= span
    if (previous[-1] - previous[0]) @ direction < 0:
        previous = previous[::-1]
    new_x, old_x = line @ direction, previous @ direction
    if min(np.min(np.diff(new_x)), np.min(np.diff(old_x))) <= .01:
        return False
    start, end = max(new_x[0], old_x[0]), min(new_x[-1], old_x[-1])
    if end - start < .62 * span:
        return False
    x = np.linspace(start, end, 31)
    new = np.column_stack([np.interp(x, new_x, axis) for axis in line.T])
    old = np.column_stack([np.interp(x, old_x, axis) for axis in previous.T])
    if np.median(np.linalg.norm(new - old, axis=1)) < .72 * groove:
        return False
    smooth = cv2.GaussianBlur(gray.astype('float32'), (0, 0), max(.7, .18 * groove))
    new_light, old_light = [map_coordinates(smooth, q[:, ::-1].T, order=1, mode='nearest') for q in (new, old)]
    return np.median(old_light - new_light) >= 12 and np.percentile(old_light - new_light, 25) >= 4


def brow_bands(gray, meshes, marks, diameter, width, translation):
    """Propose hair bands measured from the selected face, independent of its engraved brows."""
    scale = len(gray) / diameter * np.array([1., -1.])
    origin = np.asarray(translation)
    groove = width * len(gray) / diameter

    def pixels(mark):
        return (np.asarray(mark['points']) - origin) * scale + len(gray) / 2

    eyes = sorted([pixels(m) for m in marks if m['kind'] == 'eye'], key=lambda q: q[:, 0].mean())
    brows = sorted([(i, pixels(m)) for i, m in enumerate(marks) if m['kind'] == 'brow'],
                   key=lambda pair: pair[1][:, 0].mean())
    mouth = [pixels(m).mean(axis=0) for m in marks if m['kind'] == 'smile']
    meshes = [m for m in meshes if m.ndim == 2 and m.shape[0] > 473 and m.shape[1] == 2 and np.isfinite(m).all()]
    if len(eyes) != 2 or len(brows) != 2 or len(mouth) != 1 or not meshes:
        return
    try:
        mesh = pick_face(meshes, np.array([*(eye.mean(axis=0) for eye in eyes), mouth[0]]))
    except ValueError:
        return
    # Both rows of the anatomical mesh describe the photographed brow area,
    # lateral to medial. Sort by image position so a mirrored photo still fits.
    rows = [([70, 63, 105, 66, 107], [46, 53, 52, 65, 55]),
            ([300, 293, 334, 296, 336], [276, 283, 282, 295, 285])]
    guides = sorted([(mesh[top] + mesh[bottom]) / 2 for top, bottom in rows], key=lambda q: q[:, 0].mean())
    for (index, previous), eye, guide in zip(brows, eyes, guides):
        line = brow_stroke(gray, guide, eye, groove, anatomy=True)
        if line is not None and darker_than_earlier_brow(gray, line, previous, groove):
            yield index, {**marks[index], 'points': ((line - len(gray) / 2) / scale + origin).tolist()}
