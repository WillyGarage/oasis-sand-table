"""Trace a single selected head in a private, physically scaled garden face crop."""

import io
import math
import sys

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d


class ClippedHair(ValueError):
    """The measured silhouette continued outside the selected portrait crop."""


FACE_OVAL = [
    10,
    338,
    297,
    332,
    284,
    251,
    389,
    356,
    454,
    323,
    361,
    288,
    397,
    365,
    379,
    378,
    400,
    377,
    152,
    148,
    176,
    149,
    150,
    136,
    172,
    58,
    132,
    93,
    234,
    127,
    162,
    21,
    54,
    103,
    67,
    109,
]


def mask_for(shape, points):
    mask = np.zeros(shape, np.uint8)
    if len(points) > 2:
        cv2.fillPoly(mask, [np.rint(points).astype('int32')], 1)
    return mask


def outlines(mask):
    curves, _ = cv2.findContours(mask.astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return sorted(
        (c[:, 0].astype(float) for c in curves if cv2.contourArea(c) >= 9),
        key=lambda c: -cv2.contourArea(c.astype('float32')),
    )


def component_near(mask, target):
    count, labels = cv2.connectedComponents(mask.astype('uint8'))
    hits = np.bincount(labels[target > 0], minlength=count)
    hits[0] = 0
    if not hits.max():
        raise ValueError('The hair mask missed the selected face.')
    curves = outlines(labels == hits.argmax())
    if not curves:
        raise ValueError('No separate hair and skin boundary was found.')
    return mask_for(mask.shape, curves[0])


def simplify(points, closed, sigma=2.0, tolerance=0.8):
    line = gaussian_filter1d(
        np.asarray(points, dtype=float), sigma, axis=0, mode='wrap' if closed else 'nearest'
    )
    return cv2.approxPolyDP(line.astype('float32').reshape(-1, 1, 2), tolerance, closed)[:, 0, :]


def length(line):
    return np.linalg.norm(np.diff(line, axis=0), axis=1).sum()


def runs(points, usable, closed=False):
    if closed and not usable.all():
        first = np.flatnonzero(~usable)[0]
        points, usable = np.roll(points, -first, axis=0), np.roll(usable, -first)
    bounds = np.flatnonzero(np.diff(np.r_[False, usable, False]))
    return [points[a:b] for a, b in bounds.reshape(-1, 2) if b - a >= 3]


def inner_distance(mask):
    return cv2.distanceTransform(mask.astype('uint8'), cv2.DIST_L2, 5)


def pick_face(meshes, expected):
    if len(meshes) == 0:
        raise ValueError('The local hair model could not confirm the selected face.')
    span = np.linalg.norm(expected[0] - expected[1])

    def error(mesh):
        eyes = sorted(mesh[[468, 473]], key=lambda point: point[0])
        facial_points = np.array([*eyes, mesh[[61, 291]].mean(axis=0)])
        return np.max(np.linalg.norm(facial_points - expected, axis=1))

    best = min(meshes, key=error)
    if error(best) > max(6, 0.55 * span):
        raise ValueError('The local hair model found a different face in this crop.')
    return best


def hair_locks(gray, crown, skin, head, available, groove):
    """Trace coherent image texture. Between faint strands, interpolate along the hair band."""
    blurred = cv2.GaussianBlur(gray.astype('float32'), (0, 0), 1.4)
    gx = cv2.Sobel(blurred, cv2.CV_32F, 1, 0) / 8
    gy = cv2.Sobel(blurred, cv2.CV_32F, 0, 1) / 8

    def smooth(a):
        return cv2.GaussianBlur(a, (0, 0), 2.2 * groove)

    xx, yy, xy = smooth(gx * gx), smooth(gy * gy), smooth(gx * gy)
    coherence = np.hypot(xx - yy, 2 * xy) / (xx + yy + 0.00001)
    angle = 0.5 * np.arctan2(2 * xy, xx - yy) + math.pi / 2
    strength = coherence**1.2 * np.sqrt(xx + yy)
    skin_distance = inner_distance(1 - skin)
    band = cv2.GaussianBlur(
        skin_distance / (skin_distance + inner_distance(head) + 0.1), (0, 0), 0.8 * groove
    )
    tangent = np.arctan2(cv2.Sobel(band, cv2.CV_32F, 0, 1), cv2.Sobel(band, cv2.CV_32F, 1, 0)) + math.pi / 2
    weight = np.clip((coherence - 0.25) * 1.4, 0, 0.8) * np.clip((np.sqrt(xx + yy) - 0.65) / 2.5, 0, 1)
    blended = 0.5 * np.arctan2(
        weight * np.sin(2 * angle) + (1 - weight) * np.sin(2 * tangent),
        weight * np.cos(2 * angle) + (1 - weight) * np.cos(2 * tangent),
    )
    field = np.dstack([np.cos(blended), np.sin(blended)])
    domain = available & (inner_distance(crown) > 1.2 * groove)
    n = len(gray)

    def follow(seed, direction):
        position = seed.copy()
        x, y = np.rint(position).astype(int)
        previous = field[y, x] * direction
        points = []
        for _ in range(95):
            x, y = np.rint(position).astype(int)
            if not (4 < x < n - 4 and 4 < y < n - 4 and domain[y, x]):
                break
            vector = field[y, x].copy()
            if vector @ previous < 0:
                vector *= -1
            if vector @ previous < 0.7:
                break
            points.append(position.copy())
            position += 2.5 * vector
            previous = vector
            if len(points) > 10 and np.linalg.norm(points[-1] - points[0]) < 4:
                break
        return points

    candidates = []
    for y in range(12, n - 12, 14):
        for x in range(12, n - 12, 14):
            if not domain[y, x]:
                continue
            seed = np.array([x, y], float)
            line = np.array(follow(seed, -1)[::-1] + follow(seed, 1)[1:])
            if len(line) < 15:
                continue
            ix, iy = np.rint(line).astype(int).T
            score = length(line) * (1 + 0.3 * np.mean(np.clip(strength[iy, ix], 0, 3)))
            candidates.append((score, line))
    result, used = [], np.zeros_like(crown)
    for _, line in sorted(candidates, key=lambda item: -item[0]):
        x, y = np.rint(line).astype(int).T
        pieces = runs(line, used[y, x] == 0)
        if not pieces:
            continue
        best = max(pieces, key=length)
        if length(best) < 5 * groove:
            continue
        cv2.polylines(used, [np.rint(best).astype('int32')], False, 1, max(1, round(4.8 * groove)))
        result.append(simplify(best, False, 1))
        if len(result) == 5:
            break
    return result


def measured_hair(gray, masks, meshes, marks, old_hair, diameter, groove_mm):
    """Return proposed head and hair strokes. The caller protects all accepted facial strokes."""
    n = len(gray)
    groove = groove_mm * n / diameter

    def pixels(points):
        return np.array(points) * [1, -1] * n / diameter + n / 2

    def physical(points):
        return ((np.asarray(points) - n / 2) * [1, -1] * diameter / n).tolist()

    eyes = sorted(
        (pixels(m['points']).mean(axis=0) for m in marks if m['kind'] in ('eye', 'glasses')),
        key=lambda point: point[0],
    )
    mouth = next(pixels(m['points']).mean(axis=0) for m in marks if m['kind'] == 'smile')
    mesh = pick_face(meshes, np.array([*eyes, mouth]))
    oval = mask_for(gray.shape, mesh[FACE_OVAL])
    original = mask_for(gray.shape, pixels(next(m['points'] for m in marks if m['kind'] == 'head')))
    upper = mask_for(gray.shape, pixels(old_hair)) if old_hair else original.copy()
    if not old_hair:
        upper[int(np.mean(eyes, axis=0)[1]) :] = 0

    def soft(mask, s):
        return (cv2.GaussianBlur(mask.astype('float32'), (0, 0), s) > 0.48).astype('uint8')

    skin = component_near(soft(masks[1] > 0.54, 3.0), oval)
    hair = cv2.morphologyEx(
        soft(masks[0] > 0.52, 3.9), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    )
    crown = component_near(hair, upper)
    if np.count_nonzero(crown & upper) < 10 * groove**2:
        raise ValueError('Too little measured hair at this drawing size.')
    yy = np.indices(gray.shape)[0]
    skin &= (
        (yy < mesh[152, 1] - 0.17 * abs(mesh[454, 0] - mesh[234, 0])) | (inner_distance(1 - oval) < groove)
    ).astype('uint8')
    head = component_near(soft(skin | crown | oval, 3.6), oval)
    has_beard = any(m.get('facialHair') for m in marks)
    if has_beard:
        nose = next((pixels(m['points']) for m in marks if m['kind'] == 'nose'), None)
        if nose is None:
            raise ValueError('The beard and hair could not be kept separate.')
        top, lower = np.mean(eyes, axis=0)[1] - groove, nose[:, 1].mean() - 0.7 * groove
        phase = np.clip((lower - yy) / max(1, lower - top), 0, 1)
        phase = phase**2 * (3 - 2 * phase)
        occupied = np.zeros_like(skin)
        for m in marks:
            if m['kind'] not in ('head', 'hairline'):
                cv2.polylines(occupied, [pixels(m['points']).round().astype('int32')], m['closed'], 1, 1)
        clear = np.clip((inner_distance(1 - occupied) / groove - 2.6) / 2.4, 0, 1)
        phase *= clear**2 * (3 - 2 * clear)

        def signed(m):
            return inner_distance(m) - inner_distance(1 - m)

        head = ((1 - phase) * signed(original) + phase * signed(head) > 0).astype('uint8')
    head_curve = outlines(head)[0]
    new_head = simplify(head_curve, True, 1.5, 1.0)
    if np.any(new_head.min(0) < 1) or np.any(new_head.max(0) > n - 2):
        raise ClippedHair('The hair touches the edge of the selected photo crop.')
    output = [{'kind': 'head', 'closed': True, 'points': physical(new_head)}]

    def add(points):
        output.append({'kind': 'shade', 'closed': False, 'points': physical(points), 'facialHair': True})

    boundary = outlines(crown)[0]
    bx, by = boundary.round().astype(int).T
    edge = (inner_distance(1 - skin)[by, bx] < 1.15 * groove) & (inner_distance(head)[by, bx] > 2.15 * groove)
    for piece in sorted(runs(boundary, edge, True), key=lambda v: -length(v))[:3]:
        if length(piece) > 5.4 * groove:
            add(simplify(piece, False, 3, 0.72))
    reserved = np.zeros_like(crown)
    facial = [m for m in marks if m['kind'] not in ('head', 'hairline')]
    for m in [*output, *facial]:
        cv2.polylines(reserved, [pixels(m['points']).round().astype('int32')], m['closed'], 255, 1)
    for line in hair_locks(gray, crown, skin, head, inner_distance(255 - reserved) > 2.2 * groove, groove):
        add(line)
    if len(output) < 3:
        raise ValueError('Too little room for a distinct hairline and separate locks.')
    return output


def segment():
    # The model environment can be kept separate from the browser environment.
    # Send only binary arrays over the local pipe. The original crop is never saved.
    from photo2sand import detect

    data = np.frombuffer(sys.stdin.buffer.read(), np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    faces, confidence = detect(image)
    output = io.BytesIO()
    np.savez_compressed(
        output, faces=np.asarray([points for points, _ in faces]), masks=confidence[[1, 3]].astype('float16')
    )
    sys.stdout.buffer.write(output.getvalue())


if __name__ == '__main__':
    segment()
