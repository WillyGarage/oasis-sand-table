"""Trace two photographed moustache wings without closing the tooth opening."""

import base64

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates
from scipy.spatial import cKDTree

import wide_portrait as portrait


def photographed_wings(source):
    """Find both dark bands between the upper lip and the base of the nose."""
    crop = source.get('crop') or {}
    guide = crop.get('moustache')
    if not guide:
        return None
    left, right = np.asarray(guide['corners'])
    across = right - left
    span = np.linalg.norm(across)
    mm_per_pixel = source['diameter'] / 600
    if span < 42 or span * mm_per_pixel < 10 * source['width']:
        return None
    down = across[::-1] * [-1, 1]
    origin = np.asarray(guide['nose']) - left
    nose = np.column_stack([origin @ axis / span**2 for axis in (across, down)])
    if not (.15 < nose[0, 0] < nose[1, 0] < nose[2, 0] < .85 and -.38 < nose[1, 1] < -.11):
        return None
    image = cv2.imdecode(np.frombuffer(base64.b64decode(crop['png']), np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (600, 600, 3):
        return None
    blue, green, red = cv2.split(cv2.GaussianBlur(image.astype(np.float32), (0, 0), .7))
    # Lip skin is redder than the hair directly above it, even at similar luminance.
    tone = .299 * red + .587 * green + .114 * blue + .5 * (red - .66 * green - .34 * blue)
    sides = (nose[[0, 2]] + nose[1]) / 2
    anchors = [[-.02, -.05], [sides[0, 0], sides[0, 1] + .09],
               [nose[1, 0], nose[1, 1] + .064], [sides[1, 0], sides[1, 1] + .09], [1.02, -.05]]

    def wing(start, end):
        u = np.linspace(start, end, 22)[:, None]
        middle = np.interp(u, *np.asarray(anchors).T)
        v = middle + np.linspace(-.055, .055, 13)

        def sample(du, dv):
            xy = left + (u + du)[..., None] * across + (v + dv)[..., None] * down
            return map_coordinates(tone, [xy[..., 1], xy[..., 0]], order=1, mode='nearest')

        core = np.median([sample(x, y) for x, y in [(0, 0), (-.011, 0), (.011, 0), (0, .01), (0, -.01)]], axis=0)
        upper = .5 * (sample(0, -.09) + sample(0, -.075)) - core
        lower = .5 * (sample(0, .052) + sample(0, .075)) - core
        contrast = .40 * np.minimum(60, upper) + .28 * np.minimum(55, lower)
        contrast += .32 * np.minimum(70, np.maximum(upper, lower))
        merit = contrast - 135 * np.abs(v - middle)
        score, parents = merit[0], []
        for i in range(1, len(u)):
            delta = np.abs(v[i][:, None] - v[i - 1])
            paths = score - 130 * delta - 550 * delta**2
            best = np.argmax(paths, axis=1)
            parents.append(best)
            score = merit[i] + paths[np.arange(len(best)), best]
        j = int(np.argmax(score))
        columns = [j]
        for prior in reversed(parents):
            j = prior[j]
            columns.append(j)
        row = np.arange(len(u))
        columns.reverse()
        observed = contrast[row, columns]
        # Both the outer hairs and their roots need support. A single sharp
        # mouth corner or a dark nostril alone does not describe a moustache.
        if (np.median(observed[:9]) < 22 or np.median(observed[12:]) < 19 or
                np.quantile(observed, .3) < 14 or np.median(upper[row, columns]) < 8):
            return None
        edge = gaussian_filter1d(v[row, columns], 1.03)
        return (left + u * across + edge[:, None] * down - 300) * [mm_per_pixel, -mm_per_pixel]

    wings = [wing(-.016, nose[1, 0] - .047), wing(1.016, nose[1, 0] + .047)]
    return None if any(w is None for w in wings) else wings


def join_wings(smile, wings):
    """Visit the dark band from its photographed corner, returning on its own groove."""
    loop = np.asarray(smile['points'])
    delta = np.roll(loop, -1, axis=0) - loop
    length2 = np.maximum(np.sum(delta**2, axis=1), 1e-10)
    visits = {}
    for wing in wings:
        t = np.clip(np.sum((wing[0] - loop) * delta, axis=1) / length2, 0, 1)
        on_loop = loop + t[:, None] * delta
        i = int(np.argmin(np.linalg.norm(on_loop - wing[0], axis=1)))
        visits.setdefault(i, []).append((t[i], on_loop[i], wing))
    result = []
    for i, point in enumerate(loop):
        result.append(point.tolist())
        for _, contact, wing in sorted(visits.get(i, []), key=lambda v: v[0]):
            result.extend([contact.tolist(), *wing.tolist(), *wing[-2::-1].tolist(), contact.tolist()])
    return {**smile, 'points': result}


def fit_wings(page, source, marks, plan, wings, offset):
    """Accept only if the downloaded route contains both wings and every prior feature."""
    if not wings or not marks:
        return marks, plan
    index = next((i for i, m in enumerate(marks) if m['kind'] == 'smile' and m['closed']), None)
    events = {e['source']: e for e in plan['events']}
    if index not in events:
        return marks, plan
    width, radius = source['width'], source['radius']
    original = portrait.downloaded_route(page, plan, source['dock'])
    step = width * .045
    def cloud(route, event):
        return portrait.excursion_cloud(route, event, radius, step)

    neighbors = [cloud(original, event) for i, event in events.items() if i != index]
    others = cKDTree(np.concatenate(neighbors))
    opening = np.asarray(marks[index]['points'])
    polygon = np.float32(opening)
    branches = []
    for wing in wings:
        points = wing + (offset if offset is not None else [0, 0])
        # The outer hair can meet the lip at its corner. Keep its first
        # supported point outside the visible teeth, even after polar rounding.
        inside = np.array([cv2.pointPolygonTest(polygon, tuple(p), True) for p in points]) > -.08 * width
        if np.any(inside):
            last = np.flatnonzero(inside)[-1]
            if last >= len(points) / 3:
                return marks, plan
            points = points[last + 1:]
        blocked = np.flatnonzero(others.query(points)[0] < 1.46 * width)
        branch = points[:blocked[0]] if len(blocked) else points
        if len(branch) < 3 or np.linalg.norm(np.diff(branch, axis=0), axis=1).sum() < 2.1 * width:
            return marks, plan
        branches.append(branch)
    revised = marks.copy()
    revised[index] = join_wings(marks[index], branches)
    candidate = portrait.plan_marks(page, revised)
    if not candidate:
        return marks, plan
    updated = {e['source']: e for e in candidate['events']}
    if events.keys() != updated.keys():
        return marks, plan
    route = portrait.downloaded_route(page, candidate, source['dock'])
    for i, e in events.items():
        if i == index:
            continue
        f = updated[i]
        if not portrait.same_excursion(original[e['first']:e['last'] + 1], route[f['first']:f['last'] + 1]):
            return marks, plan
    before, after = cloud(original, events[index]), cloud(route, updated[index])
    ink = cKDTree(after)
    if any(ink.query(portrait.samples(line, step))[0].max() > .12 * width
           for line in [np.vstack([opening, opening[0]]), *branches]):
        return marks, plan
    extra = after[cKDTree(before).query(after)[0] > .08 * width]
    if portrait.crosses_opening(extra, opening, .03 * width):
        return marks, plan
    return revised, candidate
