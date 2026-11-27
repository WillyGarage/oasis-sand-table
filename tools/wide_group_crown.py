"""Recover a cropped crown in the free sand beside a group portrait."""

import numpy as np
from scipy.optimize import linprog
from scipy.spatial import cKDTree

import wide_portrait as portrait
from wide_group_portrait import excursions, order_marks, same_neighbors, verify_group
from wide_portrait_long_hair import relocate


def eye_frame(marks):
    left, right = sorted((np.mean(m['points'], axis=0) for m in marks if m['kind'] in ('eye', 'glasses')),
                         key=lambda center: center[0])
    across = right - left
    span = np.linalg.norm(across)
    if span <= 0:
        raise ValueError('The selected eyes overlap.')
    return (left + right) / 2, span, np.array([-across[1], across[0]]) / span


def place_crown(face, previous, neighbors, radius, width):
    """Maximize the existing eye size, then minimize how far the person moves."""
    center, span, _ = eye_frame(face.marks)
    anchor, old_span, _ = eye_frame(previous)
    relative = (np.vstack([m['points'] for m in face.marks]) - center) * (old_span / span)
    angles = np.linspace(0, 2 * np.pi, 96, endpoint=False)
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    supports = (relative @ directions.T).max(axis=0)
    normals = list(directions)
    bounds = list((radius - 2.5 * width) * np.cos(np.pi / len(angles)) - directions @ anchor)
    # A tilted lock can hang beyond a neighbor's face with empty sand
    # alongside it. Bound each separate mark instead of closing that gap.
    for mark in neighbors:
        other = np.asarray(mark['points']) - anchor
        nearest = (other @ directions.T).min(axis=0)
        axis = np.argmax(nearest - supports)
        normals.append(directions[axis])
        bounds.append(nearest[axis])
    normals = np.asarray(normals)
    limits = np.column_stack((normals, (relative @ normals.T).max(axis=0)))
    # Keep the facial scale and position close to the existing composition.
    shift = .52 * old_span
    movement = [(-shift, shift), (-shift, shift)]
    for gap in (2.4, 2.1):
        distances = np.asarray(bounds).copy()
        distances[len(angles):] -= gap * width
        fit = linprog([0, 0, -1], A_ub=limits, b_ub=distances, bounds=[*movement, (.90, 1.)])
        if fit.success:
            break
    else:
        raise ValueError('There is too little room beside this face for its full hair.')
    zoom = fit.x[2]
    # With scale fixed, find the nearest placement by total absolute x/y shift.
    displacement = np.vstack([np.column_stack((normals, np.zeros_like(normals))),
                              [[1, 0, -1, 0], [-1, 0, -1, 0], [0, 1, 0, -1], [0, -1, 0, -1]]])
    fit = linprog([0, 0, 1, 1], A_ub=displacement, b_ub=np.r_[distances - zoom * limits[:, 2], 0, 0, 0, 0],
                  bounds=[*movement, (0, None), (0, None)])
    if not fit.success:
        raise ValueError('The wider head could not be placed in the remaining space.')
    scale = zoom * old_span / span
    return [relocate(mark, scale, anchor + fit.x[:2] - center * scale) for mark in face.marks]


def signed_crown(previous, marks, paths, owner, source):
    """A full groove of photographed hair must actually appear above the old silhouette."""
    old_center, old_span, old_up = eye_frame(previous)
    outer = next(m for m in previous if m['kind'] == 'head')
    old_top = ((np.asarray(outer['points']) - old_center) @ old_up).max() / old_span
    center, span, up = eye_frame(marks)
    width = source['width']
    head_index, head = next((i, m) for i, m in enumerate(marks) if m['kind'] == 'head')
    head_path = paths.get((owner, head_index))
    if head_path is None:
        return False
    outline = np.asarray(head['points'])
    height = (outline - center) @ up
    tip = outline[height >= height.max() - width]
    cloud = portrait.excursion_cloud(head_path, {'first': 0, 'last': len(head_path)-1}, source['radius'], .1 * width)
    if height.max() < old_top * span + width or cKDTree(cloud).query(tip)[0].max() > .35 * width:
        return False
    for i, mark in enumerate(marks):
        if mark['kind'] != 'shade' or (owner, i) not in paths:
            continue
        line = portrait.samples(np.asarray(mark['points']), .10 * width)
        above = (line - center) @ up > old_top * span
        if not np.any(above):
            continue
        track = paths[owner, i]
        cloud = portrait.excursion_cloud(track, {'first': 0, 'last': len(track)-1}, source['radius'], .1 * width)
        traced = above & (cKDTree(cloud).query(line)[0] < .35 * width)
        if np.sum(np.linalg.norm(np.diff(line, axis=0), axis=1)[traced[:-1] & traced[1:]]) >= width:
            return True
    return False


def fit_group_crowns(page, source, gathered, required, plan, gap, candidates, count):
    if not candidates:
        return gathered, required, plan, gap
    route = portrait.downloaded_route(page, plan, source['dock'])
    paths = excursions(gathered, plan, route)
    for owner, face in candidates.items():
        previous = [m for key, m in gathered if key[0] == owner]
        neighbors = [m for key, m in gathered if key[0] != owner]
        try:
            marks = place_crown(face, previous, neighbors,
                                source['diameter'] / 2, source['width'])
            trial = [(k, m) for k, m in gathered if k[0] != owner]
            trial.extend(((owner, i), mark) for i, mark in enumerate(marks))
            if len(trial) > 600:  # Maximum portable mark count in the guest editor.
                continue
            needed = {k for k in required if k[0] != owner} | {(owner, i) for i in face.required}
            order_marks(trial, needed)
            proposed = portrait.plan_marks(page, [m for _, m in trial])
            if not proposed:
                continue
            route = portrait.downloaded_route(page, proposed, source['dock'])
            updated = excursions(trial, proposed, route)
            if not same_neighbors(paths, updated, owner) or not signed_crown(previous, marks, updated, owner, source):
                continue
            separation = verify_group(page, source, trial, needed, proposed, count, route=route)
            if separation < 2 * source['width']:
                continue
        except ValueError:
            continue
        gathered, required, plan, gap, paths = trial, needed, proposed, separation, updated
    return gathered, required, plan, gap
