"""Estimate the visibility of periodic rake marks in bare sand under a photographed light."""
import cv2
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.spatial import cKDTree

from mini_bed_preview import RADIUS_MM


# At the Mini's registered 780px diameter these patches cover 14 mm. Even the
# widest analyzed groove has several turns in one patch. Hann weights suppress
# brightness discontinuities at the crop edges.
SIZE, WINDOW, STEP = 780, 48, 12
WEIGHTS = np.outer(np.hanning(WINDOW), np.hanning(WINDOW))
ENERGY = np.sum(WEIGHTS**2)


def patches(image):
    image = np.asarray(image, dtype=np.float32)
    if image.ndim != 2 or image.shape[0] != image.shape[1] or not np.isfinite(image).all():
        raise ValueError('Use a finite square image registered to the Mini rim.')
    interpolation = cv2.INTER_AREA if len(image) > SIZE else cv2.INTER_LINEAR
    scaled = cv2.resize(image, (SIZE, SIZE), interpolation=interpolation)
    return sliding_window_view(scaled, (WINDOW, WINDOW))[::STEP, ::STEP]


class RippleSpectrum:
    def __init__(self, relief):
        # Analyze the signed height field itself. It predicts spacing and
        # direction even when the preview is too smooth to show the grooves.
        fy, fx = np.meshgrid(np.fft.fftfreq(WINDOW), np.fft.rfftfreq(WINDOW), indexing='ij')
        frequency = np.hypot(fx, fy)
        upper = min(1 / 3.9, len(relief) / (2.5 * SIZE))
        self.band = (frequency >= 1 / 17) & (frequency <= upper) & ((fx > 0) | (fy > 0))
        if not self.band.any():
            raise ValueError('The registered image is too small to resolve the Mini rake spacing.')
        power = self.power(relief)
        peaks = power.argmax(axis=1)
        fx, fy = fx[self.band], fy[self.band]
        kx, ky = fx[peaks, None], fy[peaks, None]
        # Real-valued images have reflected peaks. Use one representative of
        # each pair and subtract an equal-frequency perpendicular noise band.
        def around(x, y):
            return np.minimum(np.hypot(fx-x, fy-y), np.hypot(fx+x, fy+y)) <= 1.9 / WINDOW
        self.main, self.noise = around(kx, ky), around(ky, -kx)
        self.frequency = np.hypot(kx, ky).ravel()
        self.angle = np.arctan2(ky, kx).ravel()
        self.reflected = fx*kx + fy*ky < 0
        self.coherence = (power*self.main).sum(axis=1) / np.maximum(1e-12, power.sum(axis=1))
        side = (SIZE - WINDOW) // STEP + 1
        y, x = np.indices((side, side))
        self.position = (np.column_stack((x.ravel(), y.ravel())) * STEP + WINDOW / 2 - 389.5) / 389.5

    def transforms(self, image):
        cells = patches(image)
        # FFT in strips so a high-resolution reference does not require a
        # complex double-precision buffer for every patch of the tray at once.
        for row in cells:
            centered = (row - (row*WEIGHTS).sum(axis=(1, 2))[:, None, None] / WEIGHTS.sum()) * WEIGHTS
            transform = np.fft.rfft2(centered, axes=(-2, -1))[:, self.band]
            yield centered, transform

    def power(self, image):
        power = [2 * np.abs(frequency)**2 / (ENERGY*WINDOW**2) for _, frequency in self.transforms(image)]
        return np.vstack(power).astype('float32')

    def contrast(self, image):
        power = self.power(image)
        signal = (power*self.main).sum(axis=1)
        noise = (power*self.noise).sum(axis=1) * self.main.sum(axis=1) / np.maximum(self.noise.sum(axis=1), 1)
        return np.sqrt(np.maximum(0, signal-noise))

    def coordinates(self):
        # Compare locations in tray radii, orientations modulo a half-turn
        # and relative pitch (a quarter natural-log unit is a 28% change).
        return np.column_stack((self.position / .58, np.cos(2*self.angle) / .55,
                                np.sin(2*self.angle) / .55, np.log(self.frequency) / .25))


def reference_patches(old, new, dock):
    # Keep the parked ball, camera border and nonperiodic parts of the
    # previous engraving out of the pool used to estimate illumination.
    pool = (old.coherence > .47) & (np.linalg.norm(old.position, axis=1) < .86)
    if dock is not None:
        theta, radius = dock
        ball = radius * np.array([np.cos(theta), -np.sin(theta)])
        clearance = 19/RADIUS_MM + WINDOW*np.sqrt(2)/(SIZE-1)
        pool &= np.linalg.norm(old.position-ball, axis=1) > clearance
    if pool.sum() < 2:
        raise ValueError('Too little periodic sand is visible in the opening photograph’s signed drawing.')
    nearest = cKDTree(old.coordinates()[pool])
    distance, indices = nearest.query(new.coordinates(), k=min(22, int(pool.sum())))
    weights = np.exp(-.5*((distance-distance[:, :1])/.7)**2)
    return distance, np.flatnonzero(pool)[indices], weights


def forecast(previous, current, opening, rendered, regions, *, dock=None, observed=()):
    """Mean directional RMS in each bare-sand region, independent of the groove phase."""
    if not regions or any(a.shape != opening.shape for a in (previous, current, rendered, *observed)):
        raise ValueError('Supply at least one bare-sand region and matching registered images.')
    old, new = RippleSpectrum(previous), RippleSpectrum(current)
    distance, indices, weights = reference_patches(old, new, dock)
    measured = old.contrast(opening)
    calibrated = (weights * measured[indices]).sum(axis=1) / weights.sum(axis=1)
    native = new.contrast(rendered)
    finals = [new.contrast(image) for image in observed]
    result = {}
    for name, mask in regions.items():
        if mask.dtype != np.bool_ or mask.shape != opening.shape:
            raise ValueError(f'Use a boolean mask matching the opening image for {name}.')
        region = (patches(mask) * WEIGHTS**2).sum(axis=(-2, -1)).ravel() / ENERGY > .52
        use = region & (new.coherence > .5) & (np.linalg.norm(new.position, axis=1) < .94)
        summary = dict(patches=int(use.sum()), regionPatches=int(region.sum()))
        if use.any():
            nearest_dist = distance[use, 0]
            summary.update(forecastRms=float(calibrated[use].mean()), renderedRms=float(native[use].mean()),
                           medianSpacingMm=float(np.median(1/new.frequency[use])*2*RADIUS_MM/(SIZE-1)),
                           weaklyMatchedFraction=float(np.mean(nearest_dist > 1.5)),
                           nearestMatchDistance95=float(np.percentile(nearest_dist, 95)))
            if finals:
                summary['observedRms'] = [float(value[use].mean()) for value in finals]
        result[name] = summary
    return result
