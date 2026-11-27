"""Transfer photographed illumination onto the periodic ridges of a signed Mini replay."""
import cv2
import numpy as np

from mini_bed_preview import GROOVE_MM, RADIUS_MM
from mini_ripple_contrast import ENERGY, SIZE, STEP, WEIGHTS, WINDOW, RippleSpectrum, reference_patches


def coefficients(spectrum, image):
    waves, total_energy = [], []
    for centered, band in spectrum.transforms(image):
        waves.append(band)
        # Parseval energy in the same half-plane used for the rake direction.
        total_energy.append(WINDOW**2 / 2 * (centered**2).sum(axis=(1, 2)))
    return np.vstack(waves).astype('complex64'), np.concatenate(total_energy)


def add_patches(delta, band):
    """Reconstruct overlapping Hann-windowed corrections on the 780px reference disc."""
    side = (SIZE-WINDOW)//STEP + 1
    correction = np.zeros((SIZE, SIZE))
    weight = np.zeros_like(correction)
    for row in range(side):
        frequencies = np.zeros((side, WINDOW, WINDOW//2+1), np.complex64)
        frequencies[:, band] = delta[row*side:(row+1)*side]
        # Real FFTs store both signs of ky on the kx=0 axis. The analysis
        # counted just one, so restore its conjugate before inversion.
        frequencies[:, -1:-WINDOW//2:-1, 0] = frequencies[:, 1:WINDOW//2, 0].conj()
        blocks = np.fft.irfft2(frequencies, axes=(-2, -1)) * WEIGHTS
        for column, block in enumerate(blocks):
            area = np.s_[row*STEP:row*STEP+WINDOW, column*STEP:column*STEP+WINDOW]
            correction[area] += block
            weight[area] += WEIGHTS**2
    return correction / np.maximum(weight, .02)


def photograph_ripples(previous, current, opening, rendered, touched, dock, *, moving=False):
    if any(a.shape != opening.shape for a in (previous, current, rendered, touched)):
        raise ValueError('Register the two height fields and photographs to the same drawing disc.')
    if moving:
        # A fully replaced pixel no longer depends on its starting height.
        # Fade in behind that boundary over one measured groove width, so
        # neighboring turns cannot imprint a ripple on the surviving portrait.
        fully_cut = (touched >= 1-1e-6).astype('uint8')
        distance = cv2.distanceTransform(fully_cut, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        groove = (len(opening)-1) * GROOVE_MM / (2*RADIUS_MM)
        touched = np.clip((distance-1)/groove, 0, 1)
        if not touched.any():
            return rendered.copy()
    old, new = RippleSpectrum(previous), RippleSpectrum(current)
    distances, neighbors, weights = reference_patches(old, new, dock)
    weights = weights / weights.sum(axis=1)[:, None]
    amplitude = (weights*old.contrast(opening)[neighbors]).sum(axis=1)

    # A ridge lights from the side. Measure which side of its signed crest
    # actually caught the light in this opening, locally and by orientation.
    old_height, _ = coefficients(old, previous)
    light, _ = coefficients(old, opening)
    cross = light * old_height.conj()
    cross = (np.where(old.reflected, cross.conj(), cross) * old.main).sum(axis=1)
    old_phase = cross / np.maximum(abs(cross), 1e-10)
    reflected = np.cos(old.angle[neighbors] - new.angle[:, None]) < 0
    phases = np.where(reflected, old_phase[neighbors].conj(), old_phase[neighbors])
    phase = (phases*weights).sum(axis=1)
    agreement = abs(phase)
    phase /= np.maximum(agreement, 1e-10)

    height, total_energy = coefficients(new, current)
    base, _ = coefficients(new, rendered)
    ripple = height * new.main
    energy = (abs(ripple)**2).sum(axis=1)
    rms = np.sqrt(2*energy / (ENERGY*WINDOW**2))
    gain = amplitude / np.maximum(rms, 1e-8)
    rotation = np.where(new.reflected, phase[:, None].conj(), phase[:, None])
    target = ripple * gain[:, None] * rotation

    # A single dark eyelid can have a clear direction too. Keep its broad
    # engraved shape wherever periodic turns do not dominate the relief.
    periodic = energy / np.maximum(total_energy, 1e-10)
    use = np.clip((periodic-.30)/.45, 0, 1) * np.clip((new.coherence-.5)/.35, 0, 1)
    if moving:
        # Neighbor weights rank the best available references even when all
        # are remote. Reduce the transfer where the opening lacks a nearby
        # match in position, wavelength and direction, or the lit sides differ.
        use *= agreement * (weights * np.exp(-.5*distances**2)).sum(axis=1)
    else:
        use *= np.clip(agreement/.25, 0, 1)
    delta = (target-base*new.main) * use[:, None]
    correction = add_patches(delta, new.band)
    y, x = np.indices(correction.shape)
    radius = np.hypot(x-389.5, y-389.5)/389.5
    correction *= np.clip((.97-radius)/.06, 0, 1)
    correction = cv2.resize(correction, rendered.shape[::-1], interpolation=cv2.INTER_LINEAR)
    return np.uint8(np.clip(np.rint(rendered + correction*np.clip(touched, 0, 1)), 0, 255))
