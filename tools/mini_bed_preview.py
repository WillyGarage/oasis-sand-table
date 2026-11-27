#!/usr/bin/env python3
"""Predict a Mini drawing on a photographed, inward-raked bed. Operates entirely offline.

Use square photographs registered to the drawing coordinates, with the working radius
from center to mid-edge and positive theta counterclockwise. For calibration, photograph
a solitary center-to-rim groove before and after cutting it, under the same light.
Use that camera and light for the new bed photograph. The profile contains no images.

  mini_bed_preview.py calibrate --before raked.png --after cut.png --route radial.thr \
      --pitch .035 --out mini-light.json
  mini_bed_preview.py predict --before new-bed.png --route portrait.thr \
      --pitch .030 --profile mini-light.json --out expected.png

With a separate completed drawing under the same light, use "refine" to fit
how sharp the newly cut grooves appear. Keep the photographs used for judging
the new prediction separate from the photographs used to fit the profile.
Add --bed-contrast to measure how groove visibility changes between places
where the spiral in the starting photograph appears faint or strong.

The steel ball and its shadow are omitted from the predicted sand. By default the
ball is at the first drawing point. When comparing two files with different starts
on one photographed bed, supply the photographed ball position with --bed-ball.
To compare a localized edit, predict both routes with --local-grooves. This
carves each pass in order, so a shorter or longer cut cannot affect a distant,
unchanged stroke. Leave the flag off to reproduce earlier previews.
The prediction includes only the movements in the file.
"""
import argparse
import base64
import json
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares, minimize_scalar

from sandsim import MOCK
from wide_portrait import chromium


ROOT = Path(__file__).resolve().parents[1]
RADIUS_MM = 114.03
GROOVE_MM = 5.32
BALL_SHADOW_MM = 17.5

# Render the actual signed movements twice on different starting heights. The
# carver mixes the previous height with the groove of each pass, so the difference
# tells us how much of the previous surface survived at each pixel.
FIELDS_JS = """({size, groove, pitch, route, shape, localGrooves}) => {
    const Renderer = localGrooves ? MiniLocalGrooves : RingSand;
    const sand = new Renderer(size, groove, {...shape, lighting: 'mini'});
    const turns = Math.fround(1 / Math.fround(pitch));
    const steps = Math.trunc(Math.fround(turns * 360));
    const rake = Array.from({length:steps + 1}, (_, i) =>
        [2 * Math.PI * turns * i / steps, 1 - i / steps]);
    const bed = sand.empty();
    sand.carve(bed, rake);
    const before = sand.image(bed).split(',')[1];
    sand.carve(bed, route);
    const after = sand.image(bed).split(',')[1];

    const low = sand.empty(), high = sand.empty();
    high.fill(1);
    sand.carve(low, route);
    sand.carve(high, route);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const context = canvas.getContext('2d');
    const image = context.createImageData(size, size);
    for (let i = 0; i < low.length; i++) {
        const v = Math.round(255 * (1 - high[i] + low[i]));
        image.data.set([v, v, v, 255], 4 * i);
    }
    context.putImageData(image, 0, 0);
    return [before, after, canvas.toDataURL().split(',')[1]];
}"""


def gray(path):
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape[0] != image.shape[1] or image.shape[0] < 2:
        raise ValueError(f'Expected a square, registered photograph at {path}.')
    return image.astype(np.float32)


def fields(route, pitch, size, browser_path=None, *, local_grooves=False):
    if route.ndim != 2 or route.shape[1] != 2 or len(route) < 2 or not np.isfinite(route).all():
        raise ValueError('Expected a finite two-column drawing with at least two positions.')
    if (route[:, 1] < 0).any() or (route[:, 1] > 1).any():
        raise ValueError('The motion radius must be between zero and one.')
    if not .01 <= pitch <= .2:
        raise ValueError('The Mini accepts an inward rake pitch between .01 and .2.')
    with sync_playwright() as session:
        executable = chromium(session, browser_path)
        with session.chromium.launch(executable_path=executable) as browser:
            page = browser.new_page(offline=True)
            page.add_script_tag(content=(ROOT / 'web/ring-sand.js').read_text())
            if local_grooves:
                page.add_script_tag(content=(ROOT / 'tools/mini_local_grooves.js').read_text())
            result = page.evaluate(FIELDS_JS, dict(size=size, groove=GROOVE_MM / RADIUS_MM,
                                   pitch=pitch, route=route.tolist(), shape=MOCK, localGrooves=local_grooves))
    arrays = []
    for item in result:
        pixels = np.frombuffer(base64.b64decode(item), dtype=np.uint8)
        arrays.append(cv2.imdecode(pixels, cv2.IMREAD_GRAYSCALE).astype(np.float32))
    before, after, coverage = arrays
    return before, after, coverage / 255.


def disk(shape):
    half = (shape[0] - 1) / 2
    y, x = np.indices(shape)
    return (x - half) / half, (half - y) / half


def without_ball(image, point):
    x, y = disk(image.shape)
    theta, radius = point
    separation = np.hypot(x - radius * np.cos(theta), y - radius * np.sin(theta))
    mask = separation < BALL_SHADOW_MM / RADIUS_MM
    filled = cv2.inpaint(image.astype(np.uint8), mask.astype(np.uint8), 11 * image.shape[0] / 780,
                         cv2.INPAINT_TELEA).astype(np.float32)
    return filled, mask


def blur(image, width):
    return cv2.GaussianBlur(image, (0, 0), width * image.shape[0] / 780)


def calibrate(before, after, route, pitch, browser_path=None):
    if before.shape != after.shape:
        raise ValueError('The two registered calibration photographs must have the same dimensions.')
    model0, model1, coverage = fields(route, pitch, len(before), browser_path)
    before, opening_ball = without_ball(before, route[0])
    after, parked_ball = without_ball(after, route[-1])

    def relief(base, result):
        # Remove the surviving old texture and the low-frequency illumination.
        cut = result - (1 - coverage) * base - coverage * blur(base, 23)
        return blur(cut, .9) - blur(cut, 14)

    predicted = relief(model0, model1)
    observed = relief(before, after)
    radius = np.hypot(*disk(before.shape))
    usable = (coverage > .52) & ~opening_ball & ~parked_ball
    radii = np.arange(.18, .92, .075)
    amplitudes = []
    for center in radii:
        band = usable & (abs(radius - center) < .055)
        if np.count_nonzero(band) < max(12, .00012 * before.size):
            raise ValueError('The calibration stroke must cross the usable radius from center to rim.')
        expected_range = np.ptp(np.percentile(predicted[band], [10, 90]))
        measured_range = np.ptp(np.percentile(observed[band], [10, 90]))
        if min(expected_range, measured_range) < 1:
            raise ValueError('The calibration groove is not visible across the whole radius.')
        amplitudes.append(measured_range / expected_range)
    return dict(version=1, radius_mm=RADIUS_MM, groove_mm=GROOVE_MM, radii=radii.tolist(),
                gain=gaussian_filter1d(amplitudes, 1.1, mode='nearest').tolist())


def light_profile(profile):
    if (profile.get('version') not in (1, 2, 3) or profile.get('radius_mm') != RADIUS_MM
            or profile.get('groove_mm') != GROOVE_MM):
        raise ValueError('Expected a light profile calibrated for this Mini.')
    radii = np.asarray(profile['radii'], dtype=float)
    weights = np.asarray(profile['gain'], dtype=float)
    if (radii.ndim != 1 or weights.shape != radii.shape or len(radii) < 2 or not
            (np.isfinite(radii).all() and np.isfinite(weights).all() and np.all(np.diff(radii) > 0)
             and np.all(weights > 0))):
        raise ValueError('The light profile contains invalid radii or groove contrasts.')
    softness = 0. if profile['version'] == 1 else profile.get('groove_softness_mm')
    if not isinstance(softness, (float, int)) or not np.isfinite(softness) or not 0 <= softness <= GROOVE_MM:
        raise ValueError('Expected groove softness in mm, between zero and one groove width.')
    if profile['version'] == 3:
        levels = np.asarray(profile['bed_contrast_levels'], dtype=float)
        gains = np.asarray(profile['bed_contrast_gains'], dtype=float)
        if (levels.shape != (2,) or gains.shape != (2,) or not np.isfinite([levels, gains]).all()
                or not 0 <= levels[0] < levels[1] or np.min(gains) <= 0):
            raise ValueError('Expected two distinct bed contrasts and their positive groove gains.')
    return radii, weights, softness


def soften_groove(relief, softness_mm):
    if softness_mm == 0:
        return relief
    sigma = softness_mm * (relief.shape[0] - 1) / (2 * RADIUS_MM)
    return cv2.GaussianBlur(relief, (0, 0), sigma)


def bed_contrast(photo, point):
    clean, _ = without_ball(photo, point)
    texture = blur(clean, .95) - blur(clean, 14)
    return np.sqrt(blur(texture ** 2, 14))


def photographed_bed(photo, route, pitch, profile, browser_path, bed_ball, *, local_grooves=False):
    radii, weights, softness = light_profile(profile)
    if bed_ball is not None and (np.shape(bed_ball) != (2,) or not np.isfinite(bed_ball).all()
                                 or not 0 <= bed_ball[1] <= 1):
        raise ValueError('Expected the photographed ball bearing and a radius between zero and one.')
    model0, model1, coverage = fields(route, pitch, len(photo), browser_path, local_grooves=local_grooves)
    clean, _ = without_ball(photo, route[0] if bed_ball is None else bed_ball)
    illumination = blur(clean, 23)
    model_light = blur(model0, 23)
    gain = np.interp(np.hypot(*disk(photo.shape)), radii, weights)
    old_texture = clean - illumination
    surviving = illumination + (1 - coverage) * old_texture
    # Keep the rounding of the archived, unsoftened previews.
    replaced = gain * (model1 - model_light)
    remaining = (1 - coverage) * (old_texture - gain * (model0 - model_light))
    return surviving, illumination + replaced + remaining, coverage, softness


def predict(photo, route, pitch, profile, browser_path=None, *, bed_ball=None, local_grooves=False):
    bed, image, _, softness = photographed_bed(photo, route, pitch, profile, browser_path, bed_ball,
                                               local_grooves=local_grooves)
    if softness or profile['version'] == 3:
        groove = soften_groove(image - bed, softness)
        if profile['version'] == 3:
            contrast = bed_contrast(photo, route[0] if bed_ball is None else bed_ball)
            groove *= np.interp(contrast, profile['bed_contrast_levels'], profile['bed_contrast_gains'])
        image = bed + groove
    return np.clip(image, 0, 255).astype(np.uint8)


def refine(before, after, route, pitch, profile, browser_path=None, *, bed_ball=None, fit_bed_contrast=False):
    """Fit just the appearance of new grooves, leaving the photographed grain in place."""
    if before.shape != after.shape:
        raise ValueError('The two registered photographs must have the same dimensions.')
    bed, image, coverage, _ = photographed_bed(before, route, pitch, profile, browser_path, bed_ball)
    x, y = disk(before.shape)
    mask = (np.hypot(x, y) < .94) & (coverage > .94)
    for angle, radius in [route[0] if bed_ball is None else bed_ball, route[-1]]:
        mask &= np.hypot(x - radius * np.cos(angle), y - radius * np.sin(angle)) * RADIUS_MM > BALL_SHADOW_MM + 1
    if np.count_nonzero(mask) < max(30, .001 * before.size):
        raise ValueError('Too little engraved sand is visible outside the ball and the rim.')

    def contrast(image):
        return (blur(image, .95) - blur(image, 14))[mask]

    observed = contrast(after - bed)
    baseline = min(np.abs(observed).mean(), np.abs(contrast(after - before)).mean())
    fits = []
    for width in (0., .45, .90, 1.35):
        signal = contrast(soften_groove(image - bed, width))
        fit = minimize_scalar(lambda g: np.abs(observed - g * signal).mean(),
                              bounds=(.15, 2.5), method='bounded')
        if .151 < fit.x < 2.499 and fit.fun < baseline:
            fits.append((fit.fun, width, fit.x))
    if not fits:
        raise ValueError('No groove contrast could be fitted from these photographs.')
    _, softness, scale = min(fits)
    result = {**profile, 'version': 2, 'gain': (np.asarray(profile['gain']) * scale).tolist(),
              'groove_softness_mm': softness}
    if fit_bed_contrast or profile['version'] == 3:
        measured = bed_contrast(before, route[0] if bed_ball is None else bed_ball)
        low, high = np.percentile(measured[mask], [2, 98])
        if high - low < 1:
            raise ValueError('The cleared bed needs visibly different spiral contrasts for this fit.')
        weight = np.clip((measured - low) / (high - low), 0, 1)
        groove = soften_groove(image - bed, softness) * scale
        signals = np.column_stack([contrast(groove * w)[::3] for w in (1 - weight, weight)])
        target = observed[::3]
        if np.linalg.matrix_rank(signals) != 2:
            raise ValueError('Too few distinct groove contrasts for this fit.')
        fit = least_squares(lambda gains: signals @ gains - target, [1., 1.],
                            bounds=(.05, 3.), loss='soft_l1', f_scale=3.)
        if not fit.success or np.mean(abs(fit.fun)) >= np.mean(abs(signals.sum(axis=1) - target)):
            raise ValueError('The bed contrast did not improve this calibration.')
        result.update(version=3, bed_contrast_levels=[float(low), float(high)],
                      bed_contrast_gains=fit.x.tolist())
    return result


def compare_routes(before, finished, original, candidate, pitch, profile, browser_path=None, *, bed_ball=None):
    """Project the difference between two signed routes onto a registered color photograph."""
    if finished is None or finished.shape not in (before.shape, (*before.shape, 3)):
        raise ValueError('The cleared and finished photographs must have the same registered frame.')
    predictions = []
    for route in (original, candidate):
        predictions.append(predict(before, route, pitch, profile, browser_path,
                                   bed_ball=bed_ball, local_grooves=True).astype(np.int16))
    # The finished photograph includes the ball and its shadow at the original dock.
    # Equivalent bearings can differ by a whole number of turns, or coincide at center.
    def endpoints(route):
        theta, radius = route[[0, -1]].T
        return np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))
    docks = endpoints(original)
    if not np.allclose(docks, endpoints(candidate), atol=1e-5, rtol=0):
        raise ValueError('The two routes must start and finish at the same physical positions.')
    delta = predictions[1] - predictions[0]
    x, y = disk(before.shape)
    delta[np.hypot(x - docks[1, 0], y - docks[1, 1]) < BALL_SHADOW_MM / RADIUS_MM] = 0
    if finished.ndim == 3:
        delta = delta[:, :, None]
    return np.clip(finished.astype(np.int16) + delta, 0, 255).astype(np.uint8)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest='action', required=True)
    fit = subs.add_parser('calibrate', help='Measure the contrast of a separate, isolated cut.')
    tune = subs.add_parser('refine', help='Measure the appearance of grooves in a separate completed drawing.')
    tune.add_argument('--bed-contrast', action='store_true',
                      help='Use the local visibility of the photographed erase spiral to predict new grooves.')
    draw = subs.add_parser('predict', help='Replay a new drawing on the photographed bed.')
    compare = subs.add_parser('compare', help='Preview a small route edit on a photograph of the finished drawing.')
    compare.add_argument('--candidate', required=True, type=Path, help='Edited route with the same starting and ending docks.')
    draw.add_argument('--local-grooves', action='store_true',
                      help='Carve local passes independently for before/after comparisons of edited routes.')
    for command in (fit, tune, compare):
        command.add_argument('--after', required=True, type=Path)
    for command in (tune, draw, compare):
        command.add_argument('--profile', required=True, type=Path)
        command.add_argument('--bed-ball', type=float, nargs=2, metavar=('THETA', 'RHO'),
                             help='Photographed ball position in radians and fraction of the working radius.')
    for command in (fit, tune, draw, compare):
        command.add_argument('--before', required=True, type=Path)
        command.add_argument('--route', required=True, type=Path)
        command.add_argument('--pitch', type=float, required=True, help='Spacing of the preceding inward rake.')
        command.add_argument('--out', required=True, type=Path)
        command.add_argument('--browser', type=Path)
    args = parser.parse_args()
    try:
        inputs = [args.before, args.route]
        inputs.extend(path for name in ('after', 'profile', 'candidate') if (path := getattr(args, name, None)) is not None)
        if args.out.resolve() in {item.resolve() for item in inputs}:
            raise ValueError('Choose an output path different from the source files.')
        before = gray(args.before)
        route = np.loadtxt(args.route, comments='#', ndmin=2)
        if args.action == 'refine':
            profile = refine(before, gray(args.after), route, args.pitch, json.loads(args.profile.read_text()),
                             args.browser, bed_ball=args.bed_ball, fit_bed_contrast=args.bed_contrast)
            args.out.write_text(json.dumps(profile, indent=2) + '\n')
        elif args.action == 'calibrate':
            profile = calibrate(before, gray(args.after), route, args.pitch, args.browser)
            args.out.write_text(json.dumps(profile, indent=2) + '\n')
        else:
            profile = json.loads(args.profile.read_text())
            if args.action == 'compare':
                finished = cv2.imread(str(args.after), cv2.IMREAD_COLOR)
                candidate = np.loadtxt(args.candidate, comments='#', ndmin=2)
                result = compare_routes(before, finished, route, candidate, args.pitch, profile,
                                        args.browser, bed_ball=args.bed_ball)
            else:
                result = predict(before, route, args.pitch, profile, args.browser,
                                 bed_ball=args.bed_ball, local_grooves=args.local_grooves)
            if not cv2.imwrite(str(args.out), result):
                raise OSError(f'Could not write the predicted image to {args.out}.')
    except (ValueError, KeyError, OSError, cv2.error) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
