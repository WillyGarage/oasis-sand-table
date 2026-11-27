#!/usr/bin/env python3
r"""Preview a local Mini stroke edit by moving the groove in a photograph of the earlier drawing.

Supply a square, registered photograph captured under the light you want to preview.
Each --edit gives zero-based first and last position indices, inclusive, in the
earlier and revised .thr files. Include the whole affected stroke or out-and-back
excursion. The two routes must agree between the edited stretches.

  python3 tools/mini_photo_transfer.py --photo earlier.png --original before.thr \
      --revised after.thr --edit 452 512 452 558 --out predicted.png

This uses the old groove's actual side lighting. It estimates where an existing
stroke will appear after a small move. It cannot estimate fresh sand piled up
by the ball or the carving of an entirely new feature. On the first side-lit
physical comparison it correctly predicted a stronger lower lid, and predicted
the wrong direction for the change in iris contrast.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from mini_bed_preview import GROOVE_MM, RADIUS_MM, gray
from thrcommon import to_xy


def signed_pixels(route, radius):
    """Sample both axes moving together, including bends between signed positions."""
    starts, ends = route[:-1], route[1:]
    delta = ends - starts
    extent = abs(delta[:, 1]) + abs(delta[:, 0]) * np.maximum(starts[:, 1], ends[:, 1])
    counts = np.maximum(1, np.ceil(2 * radius * extent)).astype(int)
    pieces = [a + np.arange(count)[:, None] / count * d
              for a, d, count in zip(starts, delta, counts)]
    full = np.vstack([*pieces, route[-1:]])
    x, y = to_xy(full)
    return radius * (np.column_stack((x, -y)) + 1)


def sampled_line(points, n):
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    keep = np.r_[True, np.diff(lengths) > 0]
    if lengths[-1] <= .01:
        raise ValueError('Each edited span must contain a visible stroke.')
    positions = np.linspace(0., lengths[-1], n)
    return np.column_stack([np.interp(positions, lengths[keep], v[keep]) for v in points.T])


def stroke(points):
    """Use one outward pass for a stroke the ball retraces exactly on its way back."""
    samples = sampled_line(points, 385)
    if np.max(np.linalg.norm(samples - samples[::-1], axis=1)) < .05:
        return samples[:193]
    return samples[::2]


def split_edits(original, revised, edits, radius):
    edited, fixed = [], []
    previous_old = previous_new = 0
    for old_start, old_end, new_start, new_end in edits:
        if not (previous_old <= old_start < old_end < len(original) and
                previous_new <= new_start < new_end < len(revised)):
            raise ValueError('List non-overlapping edit spans in drawing order, within both route files.')
        unchanged = original[previous_old:old_start + 1]
        if not np.array_equal(unchanged, revised[previous_new:new_start + 1]):
            raise ValueError('The routes differ outside the supplied edit spans.')
        if len(unchanged) > 1:
            fixed.append(signed_pixels(unchanged, radius))
        old_part, new_part = original[old_start:old_end + 1], revised[new_start:new_end + 1]
        if np.array_equal(old_part, new_part):
            fixed.append(signed_pixels(old_part, radius))
        else:
            edited.append((stroke(signed_pixels(old_part, radius)), stroke(signed_pixels(new_part, radius))))
        previous_old, previous_new = old_end, new_end
    tail = original[previous_old:]
    if not np.array_equal(tail, revised[previous_new:]):
        raise ValueError('The routes differ outside the supplied edit spans.')
    if len(tail) > 1:
        fixed.append(signed_pixels(tail, radius))
    return edited, fixed


def transfer(photo, original, revised, edits):
    """Return a registered uint8 prediction, preserving measured sand outside the edited strokes."""
    photo = np.asarray(photo)
    if photo.ndim != 2 or photo.shape[0] != photo.shape[1] or len(photo) < 2:
        raise ValueError('Expected a square, registered gray photograph.')
    if not (np.isfinite(photo).all() and photo.min() >= 0 and photo.max() <= 255):
        raise ValueError('Expected gray values from 0 to 255.')
    original, revised = np.asarray(original), np.asarray(revised)
    for route in (original, revised):
        if (route.ndim != 2 or route.shape[1] != 2 or len(route) < 2 or not np.isfinite(route).all()
                or np.min(route[:, 1]) < 0 or np.max(route[:, 1]) > 1):
            raise ValueError('Expected two finite route columns with radius between zero and one.')
    radius = (len(photo) - 1) / 2
    edited, fixed = split_edits(original, revised, edits, radius)
    out = np.uint8(np.rint(photo))
    if not edited:
        return out
    groove = GROOVE_MM * radius / RADIUS_MM
    extents = np.vstack([points for pair in edited for points in pair])
    lo = np.maximum(0, np.floor(extents.min(axis=0) - 2.5 * groove).astype(int))
    hi = np.minimum(len(photo), np.ceil(extents.max(axis=0) + 2.5 * groove).astype(int))
    yy, xx = np.mgrid[lo[1]:hi[1], lo[0]:hi[0]]
    grid = np.stack((xx, yy), axis=-1).astype('float32')

    def weight(distance):
        return np.where(distance < 2.25 * groove, np.exp(-(distance / groove) ** 2) / (distance ** 2 + 1), 0.)

    # A fixed background and nearby unchanged cuts resist displacing the old
    # image. Several nearby edited strokes contribute to a single inverse map.
    total = np.full(grid.shape[:2], 1. / (.95 * groove) ** 2)
    if fixed:
        total += weight(cKDTree(np.vstack(fixed)).query(grid)[0])
    displacement = np.zeros_like(grid, dtype='float64')
    for old, new in edited:
        distance, index = cKDTree(new).query(grid)
        weights = weight(distance)
        total += weights
        displacement += weights[:, :, None] * (old[index] - new[index])
    source = (grid + displacement / total[:, :, None]).astype('float32')
    moved = cv2.remap(photo.astype('float32'), source, None, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    out[lo[1]:hi[1], lo[0]:hi[0]] = np.uint8(np.rint(np.clip(moved, 0, 255)))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('photo', 'original', 'revised', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--edit', action='append', nargs=4, type=int, required=True,
                        metavar=('OLD_FIRST', 'OLD_LAST', 'NEW_FIRST', 'NEW_LAST'))
    args = parser.parse_args()
    try:
        if args.out.resolve() in {p.resolve() for p in (args.photo, args.original, args.revised)}:
            raise ValueError('Choose an output path different from the inputs.')
        image = transfer(gray(args.photo), np.loadtxt(args.original, ndmin=2), np.loadtxt(args.revised, ndmin=2),
                         args.edit)
        if not cv2.imwrite(str(args.out), image):
            raise ValueError('Could not write the preview.')
    except (OSError, ValueError, cv2.error) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()
