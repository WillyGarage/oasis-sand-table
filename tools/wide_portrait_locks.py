"""Draw long locks from a guest's photographed hair where the circular close-up cuts it off."""

import math

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree

from wide_portrait import downloaded_route, excursion_cloud, plan_marks, same_excursion, samples
from wide_portrait_hair import FACE_OVAL, mask_for, pick_face
from wide_portrait_woodcut import at_pixels


def distance(mask):
    return cv2.distanceTransform(mask.astype('uint8'), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def cropped_strands(gray, confidence, skin, mesh, head, groove, crop_center, old_ink):
    """Fit a small family of curves to the measured widths and directions of scalp hair."""
    eyes = sorted(mesh[[468, 473]], key=lambda point: point[0])
    mid = np.mean(eyes, axis=0)
    span = np.linalg.norm(eyes[1] - eyes[0])
    if span < 5 * groove or np.median(at_pixels(confidence, mesh[[1, 13, 14, 468, 473]])) > .4:
        raise ValueError('The photo does not separate the hair from the face.')
    across = (eyes[1] - eyes[0]) / span
    down = np.array([-across[1], across[0]])
    if (mesh[152] - mesh[10]) @ down < 0:
        down = -down
    basis = np.column_stack((across, down))
    y, x = np.indices(gray.shape)
    pixels = np.stack((x, y), axis=-1)
    u, v = ((pixels - mid) @ basis).transpose(2, 0, 1)
    radius = np.linalg.norm(pixels - crop_center, axis=2)
    oval = mask_for(gray.shape, mesh[FACE_OVAL]).astype(bool)
    face = (distance(oval) > .80 * groove) & (v > -.35 * span)
    hair = (confidence > .72) & (skin < .35) & ~face
    _, labels = cv2.connectedComponents(hair.astype('uint8'))
    # Include only components that meet *this person's* photographed upper scalp.
    scalp = (distance(~oval) < .24 * span) & (v < -.06 * span) & (v > -1.4 * span)
    hits = np.bincount(labels[scalp], minlength=labels.max() + 1)
    hits[0] = 0
    attached = np.isin(labels, np.flatnonzero(hits > max(9 * groove**2, .09 * hits.max())))
    size = len(gray)
    room = attached & (radius < size / 2)
    if np.mean(room & ~head) < .075:
        raise ValueError('The close-up already covers the visible hair.')
    clearance = distance(room)
    available = ((clearance > .78 * groove + 1.5) & (distance(~old_ink) > 1.6 * groove)
                 & (radius < size / 2 - 3.5 * groove))

    # Average the direction of the real strands over approximately one sand
    # groove. Shadows without a consistent direction cannot supply a lock.
    filtered = cv2.bilateralFilter(gray, 7, 14, 6).astype('float32') / 255
    gx = cv2.Sobel(filtered, -1, 1, 0)
    gy = cv2.Sobel(filtered, -1, 0, 1)

    def blur(arr):
        return cv2.GaussianBlur(arr, (0, 0), max(2., 1.05 * groove))
    cross, diff, power = blur(2 * gx * gy), blur(gx * gx - gy * gy), blur(gx * gx + gy * gy)
    coherence = np.hypot(diff, cross) / np.maximum(power, 1e-7)
    angle = .5 * np.arctan2(cross, diff) + np.pi / 2
    flow = np.stack((np.cos(angle), np.sin(angle)), axis=-1) @ basis
    local_slope = flow[:, :, 0] * np.sign(flow[:, :, 1]) / np.maximum(np.abs(flow[:, :, 1]), .25)
    fractions = np.linspace(.04, .96, 39)
    candidates = []
    for sign in (-1, 1):
        side = u * sign > 0
        clipped = room & side & (radius > size / 2 - 2.5 * groove) & (v > -.55 * span)
        texture = room & side & (coherence > .4) & (np.abs(flow[:, :, 1]) > .38) & (power > .00014)
        # A sharp boundary around featureless hair also has a strong gradient.
        # Require real strand texture well inside the region on *this* side.
        interior = (clearance > 2.4 * groove) & side
        fine_texture = texture & (gx * gx + gy * gy > .00014)
        if (np.count_nonzero(clipped) < 5 * groove**2 or np.count_nonzero(interior) < 12 * groove**2
                or np.mean(fine_texture[interior]) < .12):
            continue
        lo, hi = np.min(v[texture]), np.max(v[texture])
        cell = .09 * span
        levels, slopes, shape_y, shapes = [], [], [], []
        for start in np.arange(lo, hi, cell):
            band = (v >= start) & (v < start + cell)
            measured = local_slope[texture & band]
            if len(measured) > .7 * groove**2:
                levels.append(start + .5 * cell)
                slopes.append(np.median(measured))
            lateral = u[attached & side & band]
            if len(lateral) >= groove**2:
                shape_y.append(start + .5 * cell)
                shapes.append(np.quantile(lateral, fractions))
        if min(len(levels), len(shape_y)) < 5:
            continue
        depth = np.arange(np.floor(levels[0]), np.ceil(levels[-1]) + 1)
        shift = np.cumsum(gaussian_filter1d(np.interp(depth, levels, slopes), .11 * span))
        shift -= shift[len(shift) // 2]
        bend = .38 * (shift - gaussian_filter1d(shift, .24 * span))
        segments = []
        side_available = available & side
        for profile in np.asarray(shapes).T:
            # Estimate the envelope in the original square photograph. The
            # circle clips finished strands rather than supplying a false edge.
            lateral = gaussian_filter1d(np.interp(depth, shape_y, profile), .09 * span) + bend
            path = np.column_stack((lateral, depth)) @ basis.T + mid
            xi, yi = np.rint(path).astype(int).T
            inside = (xi >= 0) & (yi >= 0) & (xi < size) & (yi < size)
            keep = np.zeros(len(path), bool)
            keep[inside] = side_available[yi[inside], xi[inside]]
            for a, b in np.flatnonzero(np.diff(np.r_[False, keep, False])).reshape(-1, 2):
                if b - a < 8:
                    continue
                q = path[a:b]
                steps = np.diff(q, axis=0)
                length = np.linalg.norm(steps, axis=1).sum()
                if length < max(8 * groove, .55 * span) or np.mean(~at_pixels(head, q)) < .60:
                    continue
                tangent = np.vstack((steps, steps[-1]))
                tangent /= np.linalg.norm(tangent, axis=1)[:, None]
                px, py = xi[a:b], yi[a:b]
                alignment = np.abs(np.sum((tangent @ basis) * flow[py, px], axis=1))
                if np.mean((coherence[py, px] > .38) & (power[py, px] > .00014) & (alignment > .78)) >= .36:
                    segments.append((length * (.55 + .45 * alignment.mean()), q))
        taken = np.zeros(gray.shape, dtype='uint8')
        kept = 0
        for _, curve in sorted(segments, key=lambda pair: -pair[0]):
            if np.any(at_pixels(taken, samples(curve, 1.4 * groove))):
                continue
            simplified = cv2.approxPolyDP(curve.astype('float32'), .075 * groove, False)[:, 0]
            candidates.append((sign, samples(simplified, .38 * groove)))
            cv2.polylines(taken, [np.rint(curve).astype('int32')], False, 1, round(6.2 * groove))
            kept += 1
            if kept == 5:
                break
    return candidates, clearance, attached


def nearby_faces(source, meshes, mesh, photographed):
    """Reject a connected mass touching another person's head in the photo."""
    for other in meshes:
        if other is mesh:
            continue
        oval = mask_for(photographed.shape, other[FACE_OVAL]).astype(bool)
        if np.count_nonzero(photographed & oval) > .07 * np.count_nonzero(oval):
            return True
    # A neighboring face may cross the crop without enough landmarks for the
    # local model. The phone's original face detections still cover that case.
    boxes = source.get('boxes', [])
    if len(boxes) <= 1:
        return False
    area, selected = source['crop'].get('area'), source.get('selected')
    if not area or not selected or not np.isfinite(area['radius']) or area['radius'] <= 0:
        return True
    rows, cols = np.where(photographed)
    size = len(photographed)
    scale = .5 * size / area['radius']
    for box in boxes:
        if np.hypot(box['x'] - selected['x'], box['y'] - selected['y']) < .25 * min(box['w'], selected['w']):
            continue
        x = (box['x'] - area['x']) * scale + size / 2
        y = (box['y'] - area['y']) * scale + size / 2
        r = .5 * box['w'] * scale
        if np.count_nonzero(np.hypot(cols-x, rows-y) < 1.12 * r) > max(4., .07 * r**2):
            return True
    return False


def cropped_woodcut(page, source, marks, baseline, photo, offset):
    revised, plan, strands, _ = verified_cropped_locks(page, source, marks, baseline, photo, offset)
    return revised, plan, len(strands)


def verified_cropped_locks(page, source, marks, baseline, photo, offset):
    gray, meshes, masks = photo
    size, width, radius = len(gray), source['width'], source['radius']
    masks = np.asarray(masks)
    if not np.isfinite((width, radius, source['diameter'])).all() or min(width, radius, source['diameter']) <= 0:
        raise ValueError('The photo has no measured drawing area.')
    if gray.shape != (size, size) or masks.shape != (2, size, size) or not np.isfinite(masks).all():
        raise ValueError('The photo has no separate hair measurements.')
    scale = np.array([1., -1.]) * size / source['diameter']
    shift = np.asarray(offset if offset is not None else (0., 0.))
    groove = width * scale[0]
    if groove < 1:
        raise ValueError('The photo does not resolve the groove width.')

    def pixels(q):
        return (np.asarray(q) - shift) * scale + size / 2

    events = {e['source']: e for e in baseline['events']}

    def features(kinds):
        return [pixels(marks[i]['points']) for i in events if marks[i]['kind'] in kinds]
    eyes = sorted([q.mean(axis=0) for q in features(('eye', 'glasses'))], key=lambda q: q[0])
    mouths, heads = features(('smile',)), features(('head',))
    if len(eyes) != 2 or len(mouths) != 1 or len(heads) != 1:
        raise ValueError('The hair needs one separately traced face.')
    available_meshes = [m for m in meshes if m.ndim == 2 and m.shape[0] >= 478
                        and m.shape[1] == 2 and np.isfinite(m).all()]
    mesh = pick_face(available_meshes, np.array([*eyes, mouths[0].mean(axis=0)]))
    original = downloaded_route(page, baseline, source['dock'])
    old_ink = np.zeros(gray.shape, 'uint8')
    protected = []
    for e in events.values():
        cloud = excursion_cloud(original, e, radius, width * .035)
        protected.append(cloud)
        cv2.polylines(old_ink, [np.rint(pixels(cloud)).astype('int32')], False, 1, 1)
    earlier_ink = cKDTree(np.vstack(protected))
    head = mask_for(gray.shape, heads[0]).astype(bool)
    candidates, clearance, attached = cropped_strands(
        gray, *masks.astype('float32'), mesh, head, groove, pixels([0., 0.]), old_ink.astype(bool))
    if nearby_faces(source, available_meshes, mesh, attached):
        raise ValueError('The cropped hair touches another person.')
    for _ in range(3):
        if any(sum(side == direction for side, _ in candidates) < 2 for direction in (-1, 1)):
            break
        revised = marks + [
            dict(kind='shade', closed=False, points=((q - size / 2) / scale + shift).tolist())
            for _, q in candidates]
        plan = plan_marks(page, revised)
        if plan is None:
            break
        current = {e['source']: e for e in plan['events']}
        if {i for i in current if i < len(marks)} != events.keys():
            break
        route = downloaded_route(page, plan, source['dock'])
        if any(not same_excursion(original[e['first']:e['last']+1],
                                  route[current[i]['first']:current[i]['last']+1]) for i, e in events.items()):
            break
        safe = []
        occupied = [earlier_ink]
        for i, (side, strand) in enumerate(candidates, len(marks)):
            if i not in current:
                continue
            cloud = excursion_cloud(route, current[i], radius, width * .035)
            # Check the full ball width along the signed approach, the lock and
            # its return. Require a long continuous stroke from the candidate.
            if (at_pixels(clearance, pixels(cloud)).min() < (.5 + .035/2) * groove + math.sqrt(2)
                    or any(tree.query(cloud)[0].min() < (1.23 + .035) * width for tree in occupied)):
                continue
            coverage = cKDTree(pixels(cloud)).query(strand)[0] <= .12 * groove
            runs = np.flatnonzero(np.diff(np.r_[False, coverage, False])).reshape(-1, 2)
            if not any(b - a >= .78 * len(strand) for a, b in runs):
                continue
            safe.append((side, strand))
            occupied.append(cKDTree(cloud))
        if len(safe) == len(candidates):
            return revised, plan, safe, clearance
        candidates = safe
    raise ValueError('There is too little room for separate cropped locks on both sides.')
