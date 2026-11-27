"""Follow the photographed direction of short hair while leaving room between sand grooves."""

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter


def strands(gray, available, groove):
    image = cv2.bilateralFilter(gray, 7, 13, 8).astype('float32') / 255
    dx = cv2.Sobel(image, -1, 1, 0)
    dy = cv2.Sobel(image, -1, 0, 1)
    # A doubled angle gives the same orientation for light-to-dark and
    # dark-to-light edges along the same strand.
    xx, xy, power = [gaussian_filter(value, .78 * groove)
                     for value in (dy*dy - dx*dx, -2*dx*dy, dx*dx + dy*dy)]
    coherence = np.hypot(xx, xy) / np.maximum(power, 1.e-8)
    angle = .5 * np.arctan2(xy, xx)
    tangent = np.stack((np.cos(angle), np.sin(angle)), axis=-1)
    allowed = available & (coherence > .27) & (power > 1.e-5)
    strength = np.where(allowed, coherence * np.sqrt(power), 0.)

    # Start at the most distinct photographed strand in each groove-sized
    # neighborhood. Later strokes can fill the remaining room between them.
    stride = max(2, int(.68 * groove))
    seeds = []
    height, width = gray.shape
    for y in range(0, height, stride):
        for x in range(0, width, stride):
            tile = strength[y:y+stride, x:x+stride]
            j, i = np.unravel_index(tile.argmax(), tile.shape)
            if tile[j, i] > 0:
                seeds.append((-float(tile[j, i]), x+i, y+j))

    occupied = np.zeros(gray.shape, 'uint8')
    step = .32 * groove

    def follow(x, y, direction):
        point = np.array([x, y], dtype=float)
        heading = direction * tangent[y, x]
        path = []
        for _ in range(int(max(gray.shape) * 1.3 / step)):
            i, j = np.rint(point).astype(int)
            if not (0 <= i < width and 0 <= j < height and allowed[j, i]) or occupied[j, i]:
                break
            local = tangent[j, i]
            if local @ heading < 0:
                local = -local
            if local @ heading < .72:
                break
            heading = .45 * heading + .55 * local
            heading /= np.linalg.norm(heading)
            path.append(point.copy())
            point += step * heading
            if len(path) > 9 and np.linalg.norm(path[:-7] - point, axis=1).min() < 1.25 * step:
                break
        return path

    for _, x, y in sorted(seeds):
        if occupied[y, x]:
            continue
        left, right = follow(x, y, -1), follow(x, y, 1)
        points = np.array(left[::-1] + right[1:])
        if len(points) < 2 or np.linalg.norm(np.diff(points, axis=0), axis=1).sum() < 3.5 * groove:
            continue
        cv2.polylines(occupied, [np.rint(points).astype('int32')], False, 1, max(1, round(4.4 * groove)))
        yield points
