"""Prepare parallel woodcut strokes confined to the photographed hair in a wide portrait."""

import math

import cv2
import numpy as np
from scipy.spatial import cKDTree

from wide_portrait import PLAN, downloaded_route, excursion_cloud, same_excursion, samples
from wide_portrait_hair import FACE_OVAL, inner_distance, mask_for, pick_face


def at_pixels(image, points):
    x, y = np.rint(points).astype(int).T
    if x.min() < 0 or y.min() < 0 or x.max() >= image.shape[1] or y.max() >= image.shape[0]:
        raise ValueError('The hair extends beyond the measured photograph.')
    return image[y, x]


def hair_field(confidence, head, mesh, groove):
    """Limit the semantic hair mask to the selected head and exclude the facial interior."""
    eyes = mesh[[468, 473]]
    across = eyes[1] - eyes[0]
    span = np.linalg.norm(across)
    if span < 5 * groove:
        raise ValueError('The face is too small for separate hair hatching.')
    across /= span
    down = np.array([-across[1], across[0]])
    if (mesh[152] - mesh[10]) @ down < 0:
        down *= -1
    y, x = np.indices(confidence.shape)
    depth = (x - eyes[:, 0].mean()) * down[0] + (y - eyes[:, 1].mean()) * down[1]
    oval = mask_for(confidence.shape, mesh[FACE_OVAL])
    # Side hair and a ponytail may extend below the chin. Only exclude the
    # lower face *inside* its outline, where dark hair could be eyebrows or beard.
    # The landmark oval includes part of the hair at the temples. Keep a
    # groove of tolerance along this approximate edge; the photographic mask
    # and the exact earlier eye and frame paths still apply there.
    facial_interior = (inner_distance(oval) > groove) & (depth > -.12 * span)
    allowed = (head > 0) & ~facial_interior
    if np.median(at_pixels(confidence, mesh[[1, 13, 14, 468, 473]])) > .4:
        raise ValueError('The photo does not separate the hair from the face.')
    confident = (confidence > .65) & ~facial_interior
    _, regions = cv2.connectedComponents(confident.astype('uint8'))
    hits = np.bincount(regions[(head > 0) & (depth < .25 * span)], minlength=int(regions.max()) + 1)
    hits[0] = 0
    scalp_regions = np.flatnonzero(hits >= max(4 * groove**2, .02 * hits.max()))
    photographed = np.isin(regions, scalp_regions)
    core = photographed & allowed
    if core.sum() < 12 * groove**2 or core.sum() < .32 * photographed.sum():
        raise ValueError('This photo has too little separate hair to hatch.')
    # A small change in head angle should not rotate every hatch in a nearly
    # upright portrait. Turn the graphic's diagonal with larger head tilts.
    angle = round(math.atan2(across[1], across[0]) / (math.pi / 6)) * math.pi / 6
    axis = np.array([math.cos(angle), math.sin(angle)])
    vertical = np.array([-axis[1], axis[0]])
    if vertical @ down < 0:
        vertical *= -1
    direction = axis + .45 * vertical
    return core, core & (depth < 0), allowed & (confidence > .5), photographed, direction / np.linalg.norm(direction)


def hatches(available, direction, groove):
    """Clip evenly spaced oblique lines to the observed hair, keeping separate patches separate."""
    normal = np.array([-direction[1], direction[0]])
    # Cover the entire cropped square even for a diagonal or mirrored head.
    extent = 10 * math.ceil((math.hypot(*available.shape) + groove) / 10)
    along = np.arange(-extent, extent, .65)[:, None] * direction
    height, width = available.shape
    for level in np.arange(-extent, extent, 1.85 * groove):
        points = along + level * normal
        x, y = np.rint(points).astype(int).T
        inside = (x > 0) & (x < width - 1) & (y > 0) & (y < height - 1)
        keep = np.zeros(len(points), dtype=bool)
        keep[inside] = available[y[inside], x[inside]]
        for start, stop in np.flatnonzero(np.diff(np.r_[False, keep, False])).reshape(-1, 2):
            if (stop - start) * .65 >= 3.8 * groove:
                # Intermediate vertices let the planner shorten either end and
                # place its entry while keeping the remaining stroke straight.
                yield samples(points[[start, stop - 1]], .34 * groove)


def verify_hatches(page, source, baseline, original, retained, revised, plan, clearance, photographed, pixels, groove):
    previous = {e['source']: e for e in baseline['events']}
    updated = {e['source']: e for e in plan['events']}
    route = downloaded_route(page, plan, source['dock'])
    for index, old_index in enumerate(retained):
        if index not in updated:
            raise ValueError('The woodcut would crowd a stroke in the original portrait.')
        a, b = previous[old_index], updated[index]
        if not same_excursion(original[a['first']:a['last'] + 1], route[b['first']:b['last'] + 1]):
            raise ValueError('The woodcut would move an existing stroke or its approach.')
    safe, unsafe = [], []
    reached = np.zeros(photographed.shape, dtype='uint8')
    for index, event in updated.items():
        if index < len(retained):
            continue
        cloud = excursion_cloud(route, event, source['radius'], source['width'] * .035)
        # The distance transform measures pixel center to pixel center. Reserve
        # both pixel half-diagonals, half a sampling step and the ball radius.
        required = (.5 + .035 / 2) * groove + math.sqrt(2)
        if np.min(at_pixels(clearance, pixels(cloud))) < required:
            unsafe.append(index)
            continue
        safe.append(index)
        # Count only the engraved part of a hatch, not a connector or a trim
        # that appeared on the preview but never made it into the download.
        curve = samples(np.asarray(revised[index]['points']), .025 * source['width'])
        on_hatch = cKDTree(curve).query(cloud)[0] < .1 * source['width']
        xy = np.rint(pixels(cloud[on_hatch])).astype(int)
        reached[xy[:, 1], xy[:, 0]] = 1
    if len(safe) < 4:
        raise ValueError('Too few hatch lines fit fully inside the photographed hair.')
    interior = inner_distance(photographed) > .5 * groove
    if not interior.any() or np.mean(inner_distance(1 - reached)[interior] <= 2 * groove) < .30:
        raise ValueError('The hatching would cover too little of the hair in the photograph.')
    return safe, unsafe


def woodcut_version(page, source, marks, baseline, photo, offset, *, follow_grain=False):
    """Return (prepared marks, verified plan, new hair stroke count), or raise for the original drawing."""
    gray, meshes, masks = photo
    width, diameter = source['width'], source['diameter']
    size = len(gray)
    if (gray.shape != (size, size) or not len(masks) or masks[0].shape != gray.shape
            or not np.isfinite([width, diameter]).all() or min(width, diameter) <= 0):
        raise ValueError('The photo could not be measured at this drawing size.')
    confidence = np.asarray(masks[0], dtype='float32')
    if not np.isfinite(confidence).all():
        raise ValueError('The photo does not show a measurable hair region.')
    scalars = np.array([1., -1.]) * size / diameter
    translation = np.asarray((0., 0.) if offset is None else offset)
    groove = width * size / diameter
    if groove < 1:
        raise ValueError('The photo does not resolve the groove width.')

    def pixels(points):
        return (np.asarray(points) - translation) * scalars + size / 2

    existing = sorted(e['source'] for e in baseline['events'])
    faces = [marks[i] for i in existing]
    heads = [m for m in faces if m['kind'] == 'head']
    eyes = [pixels(m['points']).mean(axis=0) for m in faces if m['kind'] in ('eye', 'glasses')]
    mouths = [pixels(m['points']).mean(axis=0) for m in faces if m['kind'] == 'smile']
    if len(heads) != 1 or len(eyes) != 2 or len(mouths) != 1:
        raise ValueError('The woodcut needs one separate head with two eyes and a mouth.')
    valid = [m for m in meshes if m.ndim == 2 and m.shape[0] >= 478 and m.shape[1] == 2 and np.isfinite(m).all()]
    mesh = pick_face(valid, np.array([*sorted(eyes, key=lambda p: p[0]), mouths[0]]))
    head = mask_for(gray.shape, pixels(heads[0]['points']))
    core, scalp, hair, photographed, direction = hair_field(confidence, head, mesh, groove)
    original = downloaded_route(page, baseline, source['dock'])
    retained = []
    obstacle = np.zeros(gray.shape, dtype='uint8')
    for i in existing:
        mark = marks[i]
        line = pixels(mark['points'])
        # The planner uses facialHair for scalp locks as well as beard strokes.
        # A tagged mark below the eye line stays, even beside a dark sideburn.
        old_hair = scalp if mark.get('facialHair') else core
        if (mark['kind'] == 'shade' and not mark.get('chinStrand')
                and np.mean(at_pixels(old_hair, samples(line, 1))) > .95):
            continue
        retained.append(i)
        cv2.polylines(obstacle, [np.rint(line).astype('int32')], mark['closed'], 1, 1)
        if mark['kind'] in ('eye', 'glasses', 'smile') and mark['closed']:
            cv2.fillPoly(obstacle, [np.rint(line).astype('int32')], 1)

    available = (inner_distance(core) > .72 * groove) & (inner_distance(1 - obstacle) > 1.53 * groove)
    clearance = cv2.distanceTransform(hair.astype('uint8'), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    # Inactive original marks must not become newly visible when the old hair is
    # removed. Reuse each active mark exactly and verify its downloaded motion.
    base_marks = [marks[i] for i in retained]
    if follow_grain:
        from wide_portrait_grain import strands
        curves = strands(gray, available, groove)
    else:
        curves = hatches(available, direction, groove)
    additions = [dict(kind='shade', closed=False, points=((q - size / 2) / scalars + translation).tolist())
                 for q in curves]
    for _ in range(3):
        if len(additions) < 4 or len(base_marks) + len(additions) > 600:
            break
        revised = base_marks + additions
        plan = page.evaluate(PLAN, revised)
        if plan is None:
            break
        safe, unsafe = verify_hatches(
            page, source, baseline, original, retained, revised, plan, clearance, photographed, pixels, groove)
        if not unsafe:
            return revised, plan, len(safe)
        # Discard unsafe entries *and* rejected hatches. Re-read the new signed
        # plan: removing a neighbor can let the planner lengthen another entry.
        additions = [revised[i] for i in sorted(safe)]
    raise ValueError('The woodcut could not keep enough separate hatch lines within the photographed hair.')


def guest_woodcut(page, source, photo, offset, earlier, closeup):
    """Keep existing signed woodcuts; cropped locks are an alternate for newly eligible photos."""
    try:
        return (*woodcut_version(page, source, *earlier, photo, offset), 'The hair has separate slanted grooves.')
    except (ValueError, cv2.error) as original_error:
        from wide_portrait_locks import cropped_woodcut

        try:
            styled = cropped_woodcut(page, source, *closeup, photo, offset)
        except (ValueError, cv2.error):
            raise original_error from None
    return (*styled, 'The drawing follows separate locks of the photographed hair.')
