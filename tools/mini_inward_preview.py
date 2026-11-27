"""Preview a portrait that is drawn while a fine inward erase crosses the Mini.

All three camera frames must be square and registered to the same drawing disc.
The reference pair shows a clean 0.020 spiral and the preceding portrait, under
one light. The opening image shows that same completed portrait under the light
for the new drawing. When the earlier portrait started at center, the clear
photo shows the ball there. When it included its own whole-tray inward erase,
supply the registered clean-bed estimate for its opening bearing, with the
ball removed. Both routes must meet at the same rim dock. Inputs stay local.

  mini_inward_preview.py --previous old.thr --drawing new.thr \
      --reference-clear clear.png --reference-finished old.png --opening now.png \
      --rows 2100 --out preview.png

Omit --rows to preview the entire drawing. Give split movement files in playback
order. Images omit the steel ball and retain the opening camera's brightness.
For a moving camera exposure, --observation accepts its registered ball fix:
credible, unit (X,Y in tray radii), and range (two inclusive zero-based indices
bracketing the exposure). The preview ends where the observed ball meets the
signed movement, including positions between two rows.
Use --preserve-retraced-spiral when the ball reaches a feature by following a
groove it has already cleared. This keeps the photographed spiral texture there.

Use --signed-only for a movement simulation on any background, including an
off-center erase. It starts the previous drawing on level sand, then replays
the current drawing up to the requested row or observed ball position. This
mode needs no reference photographs. Add --opening with a registered photo of
the preceding drawing to estimate how the new grooves catch the same light.
For a small edit on the same inward spiral, add --repeat-control with the
unedited portrait replanned from the new start. This predicts the finished
drawing by following the change in the simulated grooves and carrying nearby
texture from the opening photograph. The original, unmodified file that
made the opening photograph still goes in --previous.

With a complete signed drawing and an opening photograph, add --ripple-regions
areas.npz --ripple-report contrast.json to estimate how strongly the clearing
spiral will show in bare skin. Supply registered boolean masks, one per named
region, with all portrait strokes excluded. The report measures RMS brightness
variation along the signed rake direction on the camera's 0-255 gray scale. It uses local groove spacing and orientation
from the signed movements, and the same light in the opening photograph. Check
weaklyMatchedFraction before interpreting estimates for unfamiliar geometry.
Background-ripple estimates are separate from the PNG and from face contrast.
For a partial signed replay use --moving-ripples with --opening and either
--rows or --observation. It transfers the light on the opening photograph's
periodic grooves only onto fully raked sand behind the moving ball.

After a physical run, --ripple-observed final-a.png final-b.png measures both
finished photographs with the same signed frequency and regions. These photos
only score the frozen forecast.

With --photographic-ripples, the PNG also shows the predicted fine spiral in
the opening light. The renderer transfers brightness and which side of a ridge
was illuminated from similarly spaced, similarly oriented turns in that
photograph. Use a complete signed drawing and an opening at the same exposure.
Add --align-photo-grooves to compare distinctive grooves in the opening photo
with the previous signed path. When they establish a small offset, rotation or
change of scale across the tray, blend the corrected lighting prediction equally
with the original photographic-ripples prediction. The option includes
--photographic-ripples. It changes only the preview, never the movements.
"""
import argparse
import base64
import json
import math
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from mini_bed_preview import GROOVE_MM, RADIUS_MM, ROOT, blur, disk, gray, without_ball
from mini_inward_portrait import PITCH
from oasis_player import PlaybackError, near, validate_parts
from sandsim import MOCK
from wide_portrait import chromium


def read_parts(paths):
    files = [dict(name=p.name, text=p.read_text(encoding='ascii')) for p in paths]
    validate_parts(files)
    pieces = [np.loadtxt(part['text'].splitlines(), ndmin=2) for part in files]
    for before, after in zip(pieces, pieces[1:]):
        after[:, 0] += math.tau * round((before[-1, 0] - after[0, 0]) / math.tau)
    return np.vstack([pieces[0], *[piece[1:] for piece in pieces[1:]]])


def signed_replay(previous, drawing, rows, browser_path=None, *, opening=None, ripple_regions=None, ripple_observed=(),
                  photographic_ripples=False, align_photo_grooves=False, moving_ripples=False):
    """Render both signed paths, in order, with the Mini's measured groove width."""
    if ripple_observed and ripple_regions is None:
        raise ValueError('Supply bare-sand regions when scoring a finished photograph.')
    if (ripple_regions is not None or photographic_ripples or align_photo_grooves) and (opening is None or rows != len(drawing)):
        raise ValueError('Photographic ripples need a complete signed drawing and its opening photograph.')
    if moving_ripples and (opening is None or rows >= len(drawing) or photographic_ripples or align_photo_grooves or ripple_regions is not None):
        raise ValueError('Moving ripples need a partial signed drawing and its opening photograph.')
    if not 1 <= rows <= len(drawing):
        raise ValueError('The requested number of drawn rows is outside the file.')
    if not near(previous[-1], drawing[0]):
        raise ValueError('The previous physical finish must meet the new opening.')
    with sync_playwright() as session:
        with session.chromium.launch(executable_path=chromium(session, browser_path)) as browser:
            page = browser.new_page(offline=True)
            for source in ('web/ring-sand.js', 'tools/mini_local_grooves.js'):
                page.add_script_tag(content=(ROOT/source).read_text())
            result = page.evaluate("""({previous,drawing,groove,shape,size,fitLight}) => {
                const sand = new MiniLocalGrooves(size, groove, shape);
                const bed = sand.empty();
                sand.carve(bed, previous);
                if (fitLight) {
                    const encode = field => {
                        const bytes = new Uint8Array(field.buffer);
                        const chunks = [];
                        for (let i=0; i<bytes.length; i+=16384)
                            chunks.push(String.fromCharCode(...bytes.subarray(i, i+16384)));
                        return btoa(chunks.join(''));
                    };
                    const earlier = bed.slice();
                    const low = sand.empty(), high = sand.empty();
                    high.fill(1);
                    for (const surface of [bed, low, high]) sand.carve(surface, drawing);
                    const touched = low.map((v,i) => Math.max(0, Math.min(1, 1-high[i]+v)));
                    return [earlier, bed, touched].map(encode);
                }
                sand.carve(bed, drawing);
                return sand.image(bed).split(',')[1];
            }""", dict(previous=previous.tolist(), drawing=drawing[:rows].tolist(), groove=GROOVE_MM/RADIUS_MM,
                       shape={**MOCK, 'lighting': 'mini'}, size=780 if opening is None else len(opening),
                       fitLight=opening is not None))
    if opening is None:
        return base64.b64decode(result)
    fields = [np.frombuffer(base64.b64decode(item), dtype='<f4').reshape(opening.shape) for item in result]
    image = signed_light(opening, previous[-1], *fields)
    if photographic_ripples or align_photo_grooves or moving_ripples:
        from mini_ripple_render import photograph_ripples
        image = photograph_ripples(fields[0], fields[1], opening, image, fields[2], previous[-1], moving=moving_ripples)
    if align_photo_grooves:
        image = aligned_groove_light(opening, previous[-1], *fields, image)
    ok, png = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('Could not encode the photographed-light preview.')
    if ripple_regions is not None:
        from mini_ripple_contrast import forecast
        report = forecast(fields[0], fields[1], opening, image, ripple_regions,
                          dock=previous[-1], observed=ripple_observed)
        return png.tobytes(), report
    return png.tobytes()


def signed_light(opening, dock, previous, current, touched):
    """Estimate the lighting on the new relief from strong grooves in the opening exposure."""
    start, ball = without_ball(opening, dock)
    x, y = disk(start.shape)
    radius = np.hypot(x, y)
    old_features = relief_features(previous, x, y)
    interior = (radius < .94) & ~ball
    slopes = np.hypot(old_features[:, :, 1], old_features[:, :, 2])
    strong = slopes > max(1.e-4, np.percentile(slopes[interior], 65))
    coefficients = fit_relief(old_features, start, interior & strong)
    old_light = old_features @ coefficients
    new_light = relief_features(current, x, y) @ coefficients
    # Infer broad illumination under the old drawing before adding the new grooves.
    valid = ((radius < .986) & ~ball).astype('float32')
    ambient = blur((start-old_light)*valid, 25)/np.maximum(blur(valid, 25), .0001)
    prediction = (1-touched)*(start-old_light) + touched*ambient + new_light
    image = np.where((touched > 0) & (radius <= 1), prediction, start)
    return np.uint8(np.rint(np.clip(image, 0, 255)))


def aligned_groove_light(opening, dock, previous, current, touched, baseline):
    """Use the opening relief to align a second forecast in camera coordinates."""
    from mini_groove_alignment import groove_alignment
    from mini_ripple_render import photograph_ripples

    start, ball = without_ball(opening, dock)
    x, y = disk(opening.shape)
    radius = np.hypot(x, y)
    valid = (radius < .93) & ~ball
    features = relief_features(previous, x, y)
    slopes = np.hypot(features[:, :, 1], features[:, :, 2])
    strong = valid & (slopes > max(1e-4, np.percentile(slopes[valid], 65)))
    if np.count_nonzero(strong) < max(75, .001*opening.size):
        return baseline
    matrix = groove_alignment(features @ fit_relief(features, start, strong), start, valid)
    if matrix is None:
        return baseline

    old, new, contact = [cv2.warpAffine(field, matrix, opening.shape[::-1],
                                       flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                         for field in (previous, current, touched)]
    lighting = signed_light(opening, dock, old, new, contact)
    corrected = photograph_ripples(old, new, opening, lighting, contact, dock)
    blended = cv2.addWeighted(baseline, .5, corrected, .5, 0)
    return np.where(radius <= 1, blended, baseline)


def repeat_texture(opening, dock, control, revised):
    """Move photographed texture only where the two simulated surfaces correspond."""
    if (opening.shape != control.shape or control.shape != revised.shape or opening.ndim != 2
            or len(opening) < 2 or opening.shape[0] != opening.shape[1]):
        raise ValueError('Use three square, registered images of equal size.')
    size = len(opening)
    groove = GROOVE_MM * (size - 1) / (2 * RADIUS_MM)
    measured, ball = without_ball(opening, dock)

    def structure(image):
        # Estimate displacement at the same resolution as the physical calibration.
        field = cv2.resize(image.astype('float32'), (780, 780), interpolation=cv2.INTER_LINEAR)
        width = GROOVE_MM * 779 / (2 * RADIUS_MM)
        feature = cv2.GaussianBlur(field, (0, 0), .7) - cv2.GaussianBlur(field, (0, 0), width)
        return np.uint8(np.clip(128 + 5 * feature, 0, 255))

    def displacement(first, second):
        flow = cv2.calcOpticalFlowFarneback(first, second, None, .5, 4, 19, 5, 7, 1.5, 0)
        return cv2.resize(flow, (size, size), interpolation=cv2.INTER_LINEAR) * (size / 780)

    def sample(image, positions):
        return cv2.remap(image, positions, None, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    old, new = structure(control), structure(revised)
    flow = displacement(new, old)
    grid = np.indices(opening.shape, dtype='float32')[::-1].transpose(1, 2, 0)
    origin = grid + flow
    roundtrip = np.linalg.norm(flow + sample(displacement(old, new), origin), axis=2)
    old = cv2.resize(old, (size, size))
    new = cv2.resize(new, (size, size))
    mismatch = cv2.GaussianBlur(abs(sample(old, origin).astype('float32') - new), (0, 0), groove / 5)
    weight = np.exp(-.5 * (roundtrip / (.14 * groove))**2 - .5 * (mismatch / 30)**2)
    weight[(np.linalg.norm(flow, axis=2) > 2.5 * groove) | ball] = 0
    estimate = revised + weight * sample(measured - control, origin)
    return np.uint8(np.clip(np.rint(estimate), 0, 255))


class AmbiguousStage(ValueError):
    """A confirmed ball position fits multiple stages of the same drawing."""


def observed_stage(route, observation):
    """Fit the ball within its exposure interval, retaining both signed polar axes."""
    if not isinstance(observation, dict) or observation.get('credible') is not True:
        raise ValueError('The exposure needs a confirmed camera position.')
    bounds = observation.get('range')
    if (not isinstance(bounds, list) or len(bounds) != 2 or
            any(type(i) is not int for i in bounds) or not 0 <= bounds[0] <= bounds[1] < len(route)):
        raise ValueError('The camera interval must fall within the signed drawing.')
    try:
        point = np.asarray(observation.get('unit'), dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError('Supply a finite registered X,Y ball position in tray radii.') from exc
    if point.shape != (2,) or not np.isfinite(point).all():
        raise ValueError('Supply a finite registered X,Y ball position in tray radii.')

    first, last = bounds
    window = route[first:last+1]
    delta = np.diff(window, axis=0)
    # Bound the distance between samples even on a long turn at the outer rim.
    travel = RADIUS_MM*(abs(delta[:, 0])*np.maximum(window[:-1, 1], window[1:, 1]) + abs(delta[:, 1]))
    counts = np.maximum(1, np.ceil(travel/.10).astype(int))
    segments = np.repeat(np.arange(len(delta)), counts)
    offsets = np.arange(len(segments)) - np.repeat(np.cumsum(counts)-counts, counts)
    fraction = offsets / counts[segments]
    polar = np.vstack((window[segments] + fraction[:, None]*delta[segments], window[-1]))
    xy = polar[:, 1, None]*np.column_stack((np.cos(polar[:, 0]), np.sin(polar[:, 0])))
    error = np.linalg.norm(xy-point, axis=1)*RADIUS_MM
    best = int(np.argmin(error))
    if error[best] > 3.:
        raise ValueError('The measured ball is over 3 mm from every position in the exposure.')
    # A return to the same groove after drawing elsewhere has two plausible
    # stages. One photograph cannot tell which excursion has already happened.
    possible = np.flatnonzero(error <= error[best]+1.5)
    cumulative = np.r_[0., np.linalg.norm(np.diff(xy, axis=0), axis=1).cumsum()*RADIUS_MM]
    gaps = np.flatnonzero(np.diff(possible) > 1)
    if np.any(cumulative[possible[gaps+1]] - cumulative[possible[gaps]] > GROOVE_MM):
        raise AmbiguousStage('The ball visits the observed position more than once in this exposure.')
    index = last if best == len(segments) else first + int(segments[best])
    part = 0. if best == len(segments) else float(fraction[best])
    report = dict(index=index, fraction=part, distanceMm=float(error[best]))
    if part == 0:
        return route, index+1, report
    return np.insert(route, index+1, polar[best], axis=0), index+2, report


def engraving_spans(route, rows, *, preserve_retraced_spiral=False):
    """Identify successive feature and rake segments in the exact exported file."""
    if not 1 <= rows <= len(route):
        raise ValueError('The requested number of drawn rows is outside the file.')
    a, b = route[:-1], route[1:]
    angle, radius = (b - a).T
    span = math.tau / PITCH
    phase = a[:, 0] - route[0, 0] - span * (1 - a[:, 1])
    # Older movement files round radius to five decimals. Two independently
    # rounded endpoints can differ by 0.00001 radius along the same spiral.
    aligned = ((abs(np.remainder(phase + math.pi, math.tau) - math.pi) < span*.0000051)
               & (abs(angle + span*radius) < span*.0000101))
    on_spiral = aligned & (radius <= 0) & (angle > 0)
    rake = np.zeros(len(a), dtype=bool)
    # Keep alternative continuations until a complete chain reaches center.
    # An engraving can borrow half a spiral segment and then turn back.
    reached = {10_000_000: -1}
    parent = {}
    last = None
    for i in np.flatnonzero(on_spiral):
        start, end = (round(float(r)*10_000_000) for r in (a[i, 1], b[i, 1]))
        if start in reached:
            parent[i] = reached[start]
            # Stick with the first visit. A later feature may walk backwards
            # to the rim and return on the exact same stretch of spiral.
            reached.setdefault(end, i)
            if end == 0:
                last = i
                break
    if last is None:
        raise ValueError('The drawing must include one continuous fine rake from rim to center.')
    while last >= 0:
        rake[last] = True
        last = parent[last]
    if rows == 1:
        return []
    edges = rake[:rows-1]
    if preserve_retraced_spiral:
        # Only the part from the rim down to the last completed rake segment
        # already has this texture. A visit ahead of it is a fresh cut.
        cleared_radius = np.minimum.accumulate(np.r_[route[0, 1], np.where(edges, b[:rows-1, 1], 1.)])[:-1]
        inner_endpoint = np.minimum(a[:rows-1, 1], b[:rows-1, 1])
        edges = edges | (aligned[:rows-1] & (abs(angle[:rows-1]) > .00001)
                         & (inner_endpoint >= cleared_radius - 1e-7))
    bounds = [0, *(np.flatnonzero(edges[1:] != edges[:-1]) + 1), len(edges)]
    return [[int(lo), int(hi), int(not edges[lo])] for lo, hi in zip(bounds, bounds[1:])]


def model_fields(size, previous, drawing, rows, previous_phase, browser_path=None, *, preserve_retraced_spiral=False):
    spans = engraving_spans(drawing, rows, preserve_retraced_spiral=preserve_retraced_spiral)
    previous_spans = (engraving_spans(previous, len(previous), preserve_retraced_spiral=preserve_retraced_spiral)
                      if previous[0, 1] == 1. else None)
    with sync_playwright() as session:
        with session.chromium.launch(executable_path=chromium(session, browser_path)) as browser:
            page = browser.new_page(offline=True)
            for source in ('web/ring-sand.js', 'tools/mini_local_grooves.js', 'tools/mini_inward_fields.js'):
                page.add_script_tag(content=(ROOT / source).read_text())
            result = page.evaluate('options => inwardPortraitFields(options)', dict(
                size=size, groove=GROOVE_MM/RADIUS_MM, shape=MOCK, pitch=PITCH,
                previousPhase=previous_phase, previous=previous.tolist(), drawing=drawing[:rows].tolist(),
                previousSpans=previous_spans, spans=spans))
    return [np.frombuffer(base64.b64decode(item), dtype='<f4').reshape(size, size) for item in result]


def relief_features(height, x, y):
    pixels_mm = (len(height)-1)/(2*RADIUS_MM)
    # blur() uses 780-pixel reference widths for every input resolution.
    reference_px_mm = 779/(2*RADIUS_MM)
    smoothed = blur(height, .9*reference_px_mm)
    gy, gx = [g * (GROOVE_MM*pixels_mm/2) for g in np.gradient(smoothed)]
    return np.stack([smoothed-blur(height, 5*reference_px_mm), gx, gy,
                     gx*x, gx*y, gy*x, gy*y, np.hypot(gx, gy)], axis=-1)


def without_parked_ball(x, y, point):
    theta, radius = point
    return np.hypot(x-radius*np.cos(theta), y-radius*np.sin(theta)) * RADIUS_MM > 19


def transfer_light(clear, earlier, opening, available):
    """Learn the light change from the bare sand surrounding the earlier face."""
    weight = available.astype('float32')
    # Where an old face covers the sand, borrow a little information from
    # the rest of the tray. An empty local sample has no brightness of its own.
    prior_weight = .002
    divisor = blur(weight, 37) + prior_weight

    def average(values):
        return (blur(values*weight, 37) + prior_weight*values[available].mean())/divisor

    a, b = average(earlier), average(opening)
    slope = np.clip((average(earlier*opening) - a*b)/np.maximum(1, average(earlier**2) - a*a), .08, 2)
    return np.clip(b + slope*(clear-a), 0, 255)


def fit_relief(features, target, available):
    if np.count_nonzero(available) < max(75, .001*target.size):
        raise ValueError('Too little of the earlier engraved portrait is visible for fitting.')
    def sampled_detail(image):
        return (blur(image, .9) - blur(image, 14))[available][::4]
    x = np.column_stack([sampled_detail(image) for image in features.transpose(2, 0, 1)])
    y = sampled_detail(target)
    coef = np.linalg.lstsq(x, y, rcond=1e-4)[0]
    for _ in range(6):
        weight = (1+((x@coef-y)/4)**2)**-.25
        coef = np.linalg.lstsq(x*weight[:, None], y*weight, rcond=1e-4)[0]
    return coef


def shifted_spiral(bed, phase, x, y):
    """Move each ring radially by the fraction of a pitch between start bearings."""
    wrapped = (float(phase) + math.pi) % math.tau - math.pi
    shift = wrapped * PITCH / math.tau
    radius = np.hypot(x, y)
    factor = (radius-shift)/np.maximum(1e-6, radius)
    half = (len(bed)-1)/2
    return cv2.remap(bed, (1+x*factor)*half, (1-y*factor)*half, cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)


def predict(clear, earlier, opening, previous, drawing, rows, previous_phase=None, browser_path=None,
            *, comparison=False, preserve_retraced_spiral=False):
    if clear.shape != earlier.shape or clear.shape != opening.shape:
        raise ValueError('Register the three camera images to the same size.')
    previous_inward = previous[0, 1] == 1.
    if not near(previous[-1], drawing[0]) or drawing[0, 1] != 1.:
        raise ValueError('The previous drawing must end at the new drawing’s rim dock.')
    if not previous_inward and previous[0, 1] > 1e-7:
        raise ValueError('The previous drawing must start at the cleared center or include a whole inward erase.')
    if previous_phase is None:
        previous_phase = previous[0, 0] if previous_inward else 0.
    if not np.isfinite(previous_phase):
        raise ValueError('The reference spiral needs a finite starting angle.')
    if previous_inward and abs(math.remainder(previous_phase-previous[0, 0], math.tau)) > .002:
        raise ValueError('The clean-bed estimate must match the previous inward erase’s starting angle.')
    prev_bed, prev_art, prev_cov, fresh_bed, partial, touched, art = model_fields(
        len(clear), previous, drawing, rows, previous_phase, browser_path,
        preserve_retraced_spiral=preserve_retraced_spiral)
    x, y = [axis.astype('float32') for axis in disk(clear.shape)]
    radius = np.hypot(x, y)
    if not previous_inward:
        clear, _ = without_ball(clear, previous[0])
    start, _ = without_ball(opening, drawing[0])
    unshadowed = without_parked_ball(x, y, previous[0]) & without_parked_ball(x, y, previous[-1])
    available = unshadowed & (radius < .97) & (prev_cov < .02)
    if np.count_nonzero(available) < .01*clear.size:
        raise ValueError('Too little bare sand surrounds the preceding portrait.')
    old = transfer_light(clear, earlier, opening, available)
    if previous_inward:
        # The earlier face gives us a real photograph of the previous spiral
        # wherever the last engraving left a broad patch of bare sand. Blend
        # that measured bed into the estimate across one groove at the edges.
        distance = cv2.distanceTransform(available.astype('uint8'), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        weight = np.minimum(1., distance*(2*RADIUS_MM)/((len(clear)-1)*GROOVE_MM))
        old += weight*(opening-old)
    old_background = old*(1-prev_cov) + blur(old, 23)*prev_cov
    earlier_features = relief_features(prev_art, x, y)
    features = earlier_features - (1-prev_cov[:, :, None])*relief_features(prev_bed, x, y)
    coef = fit_relief(features, opening-old_background, unshadowed & (radius < .94) & (prev_cov > .93))
    bed = shifted_spiral(old, drawing[0, 0]-previous_phase, x, y)
    remaining = 1-touched
    cleared = touched-art
    background = start*remaining + bed*cleared + blur(bed, 23)*art
    relief = (relief_features(partial, x, y)@coef - remaining*(earlier_features@coef)
              - cleared*(relief_features(fresh_bed, x, y)@coef))
    image = np.where(touched > 0, background+relief, start)
    image = np.uint8(np.rint(np.clip(image, 0, 255)))
    if comparison:
        # Hold the measured light, previous face and area swept constant.
        # This control shows what the new erase alone would look like there.
        clear_only = np.uint8(np.rint(np.clip(start*remaining + bed*touched, 0, 255)))
        return image, dict(clear_only=clear_only, touched=touched, engraved=art)
    return image


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--previous', type=Path, nargs='+', required=True)
    parser.add_argument('--drawing', type=Path, nargs='+', required=True)
    parser.add_argument('--reference-clear', type=Path)
    parser.add_argument('--reference-finished', type=Path)
    parser.add_argument('--opening', type=Path)
    parser.add_argument('--signed-only', action='store_true', help='Simulate the signed movements on the previous surface.')
    parser.add_argument('--repeat-control', type=Path, nargs='+',
                        help='Unedited portrait replanned from the current rim dock, for a small edit on the same inward spiral.')
    parser.add_argument('--preserve-retraced-spiral', action='store_true',
                        help='Keep the cleared-bed texture when the ball follows an already cleared spiral groove.')
    parser.add_argument('--previous-rake-angle', type=float, help='Reference clear bearing, in radians. Defaults to '
                        'zero for a separate erase, or to the previous movement file’s opening bearing.')
    position = parser.add_mutually_exclusive_group()
    position.add_argument('--rows', type=int, help='Number of signed positions already drawn')
    position.add_argument('--observation', type=Path, help='Registered camera ball and signed exposure interval (JSON)')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--comparison', type=Path, help='Also freeze an NPZ containing the erase-only prediction '
                        'and the touched and engraved fractions at this row.')
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--ripple-regions', type=Path, help='NPZ of named boolean masks on bare sand, registered to the camera.')
    parser.add_argument('--ripple-report', type=Path, help='JSON ripple-contrast forecast from the opening photograph.')
    parser.add_argument('--ripple-observed', type=Path, nargs='+', default=[],
                        help='Completed exposures to score in --ripple-report, in the given order.')
    parser.add_argument('--photographic-ripples', action='store_true',
                        help='Light the signed clearing grooves from matching ridges in the opening photograph.')
    parser.add_argument('--moving-ripples', action='store_true',
                        help='Light fully raked sand during a partial signed replay with --rows or --observation.')
    parser.add_argument('--align-photo-grooves', action='store_true',
                        help='Blend a small opening-photo groove alignment into the photographic-ripples preview.')
    args = parser.parse_args()
    try:
        photos = [args.reference_clear, args.reference_finished, args.opening]
        if args.signed_only and (any(photos[:2]) or args.comparison or args.previous_rake_angle is not None
                                 or args.preserve_retraced_spiral):
            raise ValueError('Use the photo and erase-comparison options with a photograph-based preview.')
        if not args.signed_only and not all(photos):
            raise ValueError('Supply --reference-clear, --reference-finished and --opening, or use --signed-only.')
        if args.repeat_control and (not args.signed_only or not args.opening or args.rows is not None or args.observation):
            raise ValueError('Use --repeat-control with a complete --signed-only drawing and its --opening photograph.')
        if ((args.ripple_regions is None) != (args.ripple_report is None) or
                (args.ripple_regions and (not args.signed_only or not args.opening or args.rows is not None
                                          or args.observation or args.repeat_control))):
            raise ValueError('Use --ripple-regions and --ripple-report together with --signed-only, --opening and a complete drawing.')
        if (args.photographic_ripples or args.align_photo_grooves) and (
                not args.signed_only or not args.opening or args.repeat_control or args.observation or args.rows is not None):
            option = '--align-photo-grooves' if args.align_photo_grooves else '--photographic-ripples'
            raise ValueError(f'Use {option} with --signed-only, --opening and a complete drawing.')
        if args.moving_ripples and (not args.signed_only or not args.opening or (not args.observation and args.rows is None)):
            raise ValueError('Use --moving-ripples with --signed-only, --opening and --rows or --observation.')
        if args.ripple_regions and args.ripple_regions.suffix.lower() != '.npz':
            raise ValueError('Use a named NPZ of boolean bare-sand masks.')
        if args.ripple_observed and not args.ripple_regions:
            raise ValueError('Use --ripple-regions and --ripple-report with a finished ripple observation.')
        sources = [*args.previous, *args.drawing, *(args.repeat_control or []), *photos,
                   args.observation, args.ripple_regions, *args.ripple_observed]
        sources = [path for path in sources if path is not None]
        if args.out.suffix.lower() != '.png' or any(args.out.resolve() == p.resolve() for p in sources):
            raise ValueError('Choose a separate PNG path for the preview.')
        if args.comparison and (args.comparison.suffix != '.npz'
                                or any(args.comparison.resolve() == p.resolve() for p in [*sources, args.out])):
            raise ValueError('Choose a separate NPZ path for the comparison.')
        if args.ripple_report and (args.ripple_report.suffix.lower() != '.json' or
                                   any(args.ripple_report.resolve() == p.resolve() for p in [*sources, args.out])):
            raise ValueError('Choose a separate JSON path for the ripple report.')
        previous, drawing = read_parts(args.previous), read_parts(args.drawing)
        rows = len(drawing) if args.rows is None else args.rows
        if args.observation:
            drawing, rows, fit = observed_stage(drawing, json.loads(args.observation.read_text()))
        if args.signed_only:
            opening = gray(args.opening) if args.opening else None
            if args.ripple_regions:
                with np.load(args.ripple_regions, allow_pickle=False) as masks:
                    regions = dict(masks)
                observed = [gray(p) for p in args.ripple_observed]
                revised, report = signed_replay(previous, drawing, rows, args.browser, opening=opening,
                                                ripple_regions=regions, ripple_observed=observed,
                                                photographic_ripples=args.photographic_ripples,
                                                align_photo_grooves=args.align_photo_grooves)
                args.ripple_report.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
            else:
                revised = signed_replay(previous, drawing, rows, args.browser, opening=opening,
                                        photographic_ripples=args.photographic_ripples, align_photo_grooves=args.align_photo_grooves,
                                        moving_ripples=args.moving_ripples)
            if args.repeat_control:
                control = read_parts(args.repeat_control)
                if (not near(control[0], drawing[0]) or not near(control[-1], drawing[-1])
                        or not near(drawing[0], drawing[-1]) or abs(drawing[0, 1] - 1) > .001):
                    raise ValueError('Both complete redraws must start and finish at the same rim dock.')
                earlier = signed_replay(previous, control, len(control), args.browser, opening=opening)
                def decode(png):
                    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
                predicted = repeat_texture(opening, drawing[0], decode(earlier), decode(revised))
                ok, png = cv2.imencode('.png', predicted)
                if not ok:
                    raise ValueError('Could not encode the repeated portrait preview.')
                revised = png.tobytes()
            args.out.write_bytes(revised)
        else:
            image = predict(*(gray(photo) for photo in photos), previous, drawing, rows,
                            args.previous_rake_angle, args.browser, comparison=bool(args.comparison),
                            preserve_retraced_spiral=args.preserve_retraced_spiral)
            if args.comparison:
                image, fields = image
                np.savez_compressed(args.comparison, **fields)
            if not cv2.imwrite(str(args.out), image):
                raise OSError(f'Could not save {args.out}')
        if args.observation:
            print(json.dumps(fit))
    except (ValueError, OSError, PlaybackError) as err:
        parser.exit(2, f'{err}\n')
