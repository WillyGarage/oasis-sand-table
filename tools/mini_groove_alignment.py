"""Find a small similarity transform from signed, illuminated relief to photographed grooves."""
import cv2
import numpy as np

from mini_bed_preview import blur


def groove_alignment(modeled, photographed, valid):
    """Match only opening-image features. Return None when the position is ambiguous."""
    size = len(photographed)
    # Patch widths, grid spacing and allowed movement were measured on the 780px tray.
    scale = size / 780
    step, half, span = [max(1, round(v * scale)) for v in (34, 21, 10)]
    model = (blur(modeled, 2) - blur(modeled, 12)).astype(np.float32)
    photo = (blur(photographed, 2) - blur(photographed, 12)).astype(np.float32)
    origins, shifts, distinctive = [], [], []
    rows, cols = np.ogrid[:2*span+1, :2*span+1]
    for y in range(half + span, size - half - span, step):
        for x in range(half + span, size - half - span, step):
            patch_slice = np.s_[y-half:y+half+1, x-half:x+half+1]
            if not valid[patch_slice].all():
                continue
            patch = model[patch_slice]
            if patch.std() < 1:
                continue
            # A straight rake line pins an offset across the line, but leaves
            # every position along its tangent equally plausible.
            gy, gx = np.gradient(patch)
            xx, xy, yy = (gx*gx).mean(), (gx*gy).mean(), (gy*gy).mean()
            if xx*yy - xy*xy < .025 * (xx+yy)**2:
                continue
            window = photo[y-half-span:y+half+span+1, x-half-span:x+half+span+1]
            scores = cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED)
            row, col = np.unravel_index(scores.argmax(), scores.shape)
            peak = scores[row, col]
            if peak < .55 or row in (0, 2*span) or col in (0, 2*span):
                continue
            # Subpixel peak of the local parabola, independently on each axis.
            offsets = []
            for lo, hi in ((scores[row, col-1], scores[row, col+1]),
                           (scores[row-1, col], scores[row+1, col])):
                offsets.append(np.clip(.5*(hi-lo)/max(1e-5, 2*peak-hi-lo), -.5, .5))
            origins.append((x, y))
            shifts.append((col-span+offsets[0], row-span+offsets[1]))
            # Repeated intersections can match at several distinct peaks.
            # Retain their weight in the fit, but require independent support
            # from unambiguous patches before trusting the fitted transform.
            distant = (rows-row)**2 + (cols-col)**2 > max(2, 4*scale)**2
            distinctive.append(not distant.any() or scores[distant].max() < peak - .01)

    if len(origins) < 12:
        return None
    origins = np.asarray(origins, np.float32)
    destinations = origins + np.asarray(shifts, np.float32)
    matrix, mask = cv2.estimateAffinePartial2D(origins, destinations, method=cv2.RANSAC,
                                               ransacReprojThreshold=2.4*scale, maxIters=600,
                                               confidence=.99, refineIters=10)
    if matrix is None:
        return None
    # A cluster on one face cannot determine how the whole tray should move.
    support = origins[mask.ravel().astype(bool) & np.asarray(distinctive)]
    corners = np.array([[0, 0], [size, 0], [0, size], [size, size]])
    displacement = corners @ matrix[:, :2].T + matrix[:, 2] - corners
    if (len(support) < max(12, .2*len(origins)) or np.linalg.norm(displacement, axis=1).max() > 16*scale
            or np.ptp(support, axis=0).min() < size*.2
            or cv2.contourArea(cv2.convexHull(support)) < .035*size**2):
        return None
    return matrix.astype(np.float32)
