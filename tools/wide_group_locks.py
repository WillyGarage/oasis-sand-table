"""Keep photographed hair on both sides of a guest's face at the size of a group engraving."""

from dataclasses import dataclass
from itertools import product
import math

import cv2
import numpy as np
from scipy.spatial import cKDTree

import wide_portrait as portrait
from wide_group_portrait import (
    Face, SUMMARY, arrange_marks, excursions, face_directions, fitted_head, same_neighbors, verify_group,
)
from wide_portrait_grain import strands as photographed_strands
from wide_portrait_locks import verified_cropped_locks
from wide_portrait_woodcut import at_pixels


@dataclass
class PhotoLocks:
    strands: list
    clearance: np.ndarray
    offset: np.ndarray
    gray: np.ndarray


def photographed_locks(page, source, marks, baseline, photo, offset):
    revised, _, signed, clearance = verified_cropped_locks(page, source, marks, baseline, photo, offset)
    strands = [(side, np.asarray(mark['points'])) for (side, _), mark in zip(signed, revised[len(marks):], strict=True)]
    return PhotoLocks(strands, clearance, np.asarray(offset if offset is not None else (0., 0.)), photo[0])


def bilateral_pairs(study, groove):
    # Keep the photographed curvature. Shorter ends can leave space for the ball
    # to turn around inside fine hair when the same person shares the center.
    sides = [[portrait.samples(points, .55 * groove) for side, points in study.strands if side == sign]
             for sign in (-1, 1)]
    for top, tip in ((0., 0.), (.12, .12), (0., .12), (.05, .20)):
        for left, right in product(*sides):
            yield [q[int(top*len(q)):len(q)-int(tip*len(q))] for q in (left, right)]


def framed_face(face, pair):
    locks = [dict(kind='shade', closed=False, points=q.tolist()) for q in pair]
    marks = face.marks + locks
    required = face.required | {len(marks)-2, len(marks)-1}
    hull = cv2.convexHull(np.float32(np.vstack([face.hull, *pair])))[:, 0].astype(float)
    return Face(marks, required, hull, face.box)


def inside_hair(study, curves, paths, owner, first, source, position, scale, *, occupied=None):
    # Invert this individual's exact group transform, then check the entire
    # downloaded lock, including its approach, against the original photo.
    groove = source['width']
    size = len(study.clearance)
    px = size / source['diameter']
    unit = np.array([px, -px])
    for i, curve in enumerate(curves, first):
        path = paths[owner, i]
        cloud = portrait.excursion_cloud(path, {'first': 0, 'last': len(path)-1}, source['radius'], .05 * groove)
        pixels = ((cloud-position)/scale - study.offset)*unit + size/2
        margin = (.5 + .05/2) * groove * px/scale + math.sqrt(2)
        if at_pixels(study.clearance, pixels).min() < margin:
            return False
        samples = portrait.samples(curve*scale + position, .08*groove)
        covered = cKDTree(cloud).query(samples)[0] < .13 * groove
        runs = np.flatnonzero(np.diff(np.r_[False, covered, False])).reshape(-1, 2)
        if not any(b-a >= .86*len(samples) for a, b in runs):
            return False
        if occupied is not None:
            if any(tree.query(cloud)[0].min() < 1.45 * groove for tree in occupied):
                return False
            occupied.append(cKDTree(cloud))
    return True


def fit_group_locks(page, source, faces, studies, rotation, baseline):
    radius, width = source['diameter']/2, source['width']
    faces = list(faces)
    directions = face_directions(faces)
    existing, _ = arrange_marks(faces, directions, radius, width, rotation)
    old = excursions(existing, baseline, portrait.downloaded_route(page, baseline, source['dock']))
    placements, result = {}, None
    for owner, study in studies.items():
        face = faces[owner]
        heading = directions[owner] + rotation
        _, previous_scale = fitted_head(face, heading, len(faces), radius, width)
        for pair in bilateral_pairs(study, width):
            candidate = framed_face(face, pair)
            position, scale = fitted_head(candidate, heading, len(faces), radius, width)
            if scale < .85 * previous_scale:
                continue
            trial = faces.copy()
            trial[owner] = candidate
            gathered, required = arrange_marks(trial, directions, radius, width, rotation)
            if not gathered:
                continue
            marks = [m for _, m in gathered]
            kept = {gathered[i][0] for i in page.evaluate(SUMMARY, marks)}
            if not required <= kept:
                continue
            plan = portrait.plan_marks(page, marks)
            if plan is None:
                continue
            route = portrait.downloaded_route(page, plan, source['dock'])
            paths = excursions(gathered, plan, route)
            if not same_neighbors(old, paths, owner):
                continue
            try:
                if not inside_hair(study, pair, paths, owner, len(face.marks), source, position, scale):
                    continue
                gap = verify_group(page, source, gathered, required, plan, len(faces), route=route)
            except ValueError:
                continue
            faces, old = trial, paths
            result = gathered, required, plan, gap
            placements[owner] = study, position, scale
            break
    if result is None:
        raise ValueError('The photographed locks need more room on both sides of a face.')
    return (*result, placements)


def flowing_locks(source, study, position, scale, owner, clouds):
    """Trace a few long, separated strands in the photographed hair at its final group size."""
    width = source['width']
    size = len(study.gray)
    unit = np.array([1., -1.]) * size / source['diameter']
    groove = width * unit[0] / scale

    def pixels(points):
        return ((points - position) / scale - study.offset) * unit + size/2

    def millimeters(points):
        return ((points - size/2) / unit + study.offset) * scale + position

    ink = np.zeros_like(study.gray, dtype='uint8')
    neighbors = ink.copy()
    for key, cloud in clouds.items():
        line = [np.rint(pixels(cloud)).astype('int32')]
        cv2.polylines(ink, line, False, 1, 2)
        if key[0] != owner:
            cv2.polylines(neighbors, line, False, 1, 2)
    to_ink = cv2.distanceTransform(1 - ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    to_neighbor = cv2.distanceTransform(1 - neighbors, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    y, x = np.indices(ink.shape)
    radius = np.linalg.norm(millimeters(np.stack((x, y), axis=-1)), axis=-1)
    available = ((study.clearance > .65*groove + 1) & (to_ink > 1.52*groove)
                 & (to_neighbor > 2.8*groove) & (radius < source['diameter']/2 - 1.85*width))
    curves = []
    for curve in photographed_strands(study.gray, available, groove):
        length = np.linalg.norm(np.diff(curve, axis=0), axis=1).sum()
        if length >= 6.5*groove:
            line = cv2.approxPolyDP(np.float32(curve), .075*groove, False)[:, 0]
            curves.append((length, millimeters(line)))
    return [line for _, line in sorted(curves, key=lambda item: -item[0])[:3]]


def finish_group_hair(page, source, gathered, plan, gap, placements, count):
    """Try additional flowing strands after every face, including its crown, has been placed."""
    width = source['width']
    route = portrait.downloaded_route(page, plan, source['dock'])
    previous = excursions(gathered, plan, route)
    added = 0
    for owner, (study, position, scale) in placements.items():
        clouds = {key: portrait.excursion_cloud(path, {'first': 0, 'last': len(path)-1},
                                                source['radius'], .05*width)
                  for key, path in previous.items()}
        lines = flowing_locks(source, study, position, scale, owner, clouds)
        if len(lines) < 2 or len(gathered) + len(lines) > 600:
            continue
        first = max(i for (who, i), _ in gathered if who == owner) + 1
        extra = [((owner, i), dict(kind='shade', closed=False, points=line.tolist()))
                 for i, line in enumerate(lines, first)]
        trial = gathered + extra
        candidate = portrait.plan_marks(page, [mark for _, mark in trial])
        if not candidate:
            continue
        route = portrait.downloaded_route(page, candidate, source['dock'])
        updated = excursions(trial, candidate, route)
        if (updated.keys() != previous.keys() | {key for key, _ in extra}
                or any(not portrait.same_excursion(path, updated[key]) for key, path in previous.items())):
            continue
        try:
            # Include the connectors when checking the sand left between
            # the new hair and the strokes already on the tray.
            occupied = [cKDTree(np.vstack(list(clouds.values())))]
            solo = [(line - position) / scale for line in lines]
            if not inside_hair(study, solo, updated, owner, first, source, position, scale, occupied=occupied):
                continue
            # Every defining feature already passed verify_group and retains
            # its exact excursion. Check the new separation between people.
            separation = verify_group(page, source, trial, set(), candidate, count, route=route)
        except ValueError:
            continue
        if separation >= gap:
            gathered, plan, previous, gap = trial, candidate, updated, separation
            added += len(lines)
    return gathered, plan, gap, added
