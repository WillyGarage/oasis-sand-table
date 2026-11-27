"""Pair Mini camera exposures with the actual ball movements for the portrait gallery.

Use a recorded phone trial (physical/ and at-dock/), the preceding drawing's
physical/ folder, and a new output directory. The two JSON files contain the
gallery sequence and its supporting measurements. --in-progress builds a
partial sequence through the latest independently located moving ball. The
proof lists any verified exposures that fit more than one stage of the drawing.
--moving-ripples uses the light from the opening photograph on fully raked
parts of each moving preview. The ending still uses the frozen forecast.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image

from mini_bed_preview import disk, gray, without_ball
from mini_inward_preview import AmbiguousStage, observed_stage, read_parts, signed_replay
from oasis_player import near


def read(path):
    return json.loads(path.read_bytes())


def matches(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f'{path.name} differs from the recorded copy.')


def registered_camera(folder, tag, record):
    source = folder / (tag + '-raw.jpg')
    matches(source, record['sha256'])
    reg = read(folder / (tag + '-registration.json'))
    if reg['good'] < 20 or reg['sectors'] < 4 or reg['goodMedian'] > 2:
        raise ValueError(f'{tag} could not be registered to the tray.')
    u, v = np.meshgrid(np.arange(780, dtype=np.float32), np.arange(780, dtype=np.float32))
    x, y = (u-389.5)/389.5, (389.5-v)/389.5
    transform = np.asarray(reg['drawingToRaw'])
    coords = transform @ np.stack([x.ravel(), y.ravel(), np.ones(x.size, dtype=np.float32)])
    if not np.isfinite(coords).all() or np.any(np.abs(coords[2]) < 1e-9):
        raise ValueError(f'{tag} has an invalid camera registration.')
    px, py = (coords[:2] / coords[2]).reshape(2, 780, 780).astype('float32')
    raw = cv2.imread(str(source))
    if raw is None:
        raise ValueError(f'{tag} could not be decoded.')
    return cv2.cvtColor(cv2.remap(raw, px, py, cv2.INTER_CUBIC), cv2.COLOR_BGR2GRAY)


def gallery_image(gray_image, size=470):
    # Apply one photographic treatment to the signed simulation and the camera.
    # Keep the ridges' light and dark sides, and remove the desk outside the tray.
    image = gray_image.astype('float32')
    x, y = disk(image.shape)
    radius = np.hypot(x, y)
    background = cv2.GaussianBlur(image, (0, 0), 24)
    fine = cv2.GaussianBlur(image, (0, 0), .65)
    level = np.median(background[radius < .96])
    shown = np.clip(193 + 68*(background/max(level, 1)-1)
                    + 365.5*(fine/np.maximum(background, 12)-1), 0, 255)
    rgb = np.repeat(np.rint(shown).astype('uint8')[:, :, None], 3, axis=2)
    rgb[radius > 1] = (249, 246, 238)
    return Image.fromarray(rgb).resize((size, size), Image.Resampling.LANCZOS)


def render(trial, preceding, output, in_progress=False, *, moving_ripples=False):
    folder, forecast = trial/'physical', trial/'at-dock'
    intent, earlier = read(folder/'intent.json'), read(preceding/'intent.json')
    evidence = read(forecast/'evidence.json')
    if intent['priorReceipt'] != earlier['receipt'] or evidence['priorReceipt'] != earlier['receipt']:
        raise ValueError('The forecast and camera trial need the same preceding drawing.')
    current, previous = folder/'submitted.thr', preceding/'submitted.thr'
    opening, predicted = preceding/'after-full-b-rect.png', forecast/'predicted.png'
    matches(current, intent['sha256'])
    matches(previous, earlier['sha256'])
    for path, key in [(current, 'submittedFileSha256'), (previous, 'priorPathSha256'),
                      (opening, 'openingImageSha256'), (predicted, 'signedForecastSha256')]:
        matches(path, evidence[key])
    route, prior = read_parts([current]), read_parts([previous])
    if len(route) != intent['rows'] or not near(route[0], prior[-1]):
        raise ValueError('The submitted file does not begin at the preceding drawing’s dock.')
    old_sand = gray(opening)
    if old_sand.shape != (780, 780):
        raise ValueError('The opening photograph needs the 780-pixel camera registration.')
    moving = [(p.name.removesuffix('-quiet-proof.json'), read(p))
              for p in sorted(folder.glob('travel-*-quiet-proof.json'))]
    tags = [('before-full-b', None), *((tag, fix) for tag, fix in moving if fix['credible'])]
    if not in_progress:
        final, restored = read(folder/'final.json'), read(folder/'restored.json')
        completed = {'id': intent['receipt'], 'state': 'complete'}
        if (not final['travelOpticallyVerified'] or final['receipt'] != intent['receipt']
                or restored['state'] != 'idle' or restored['receipt'] != completed
                or final['status']['receipt'] != completed or final['status']['index'] != len(route)):
            raise ValueError('The camera record and completed drawing receipt do not agree.')
        tags.append(('after-full-b', None))

    sequence, proof, omitted = [], [], []
    for tag, fix in tags:
        record = read(folder/(tag+'-position.json'))
        before, after = record['status_before'], record['status_after']
        elapsed = (record['started'] + record['ended'])/2 - intent['time']
        if fix is not None:
            receipt = {'id': intent['receipt'], 'state': 'running'}
            interval = [max(0, before['index']-1), min(len(route)-1, after['index'])]
            if fix['label'] != tag or fix['range'] != interval:
                raise ValueError(f'{tag} does not bracket the recorded ball position.')
        else:
            start = tag == 'before-full-b'
            receipt = {'id': intent['priorReceipt'] if start else intent['receipt'], 'state': 'complete'}
            measurement = read(folder/(tag+'-proof.json'))
            if measurement['mismatchMm'] > 3:
                raise ValueError(f'{tag} does not show the ball at its recorded dock.')
            elapsed = 0 if start else read(folder/'done.json')['time']-intent['time']
        if before['receipt'] != receipt or after['receipt'] != receipt:
            raise ValueError(f'The wrong drawing was present during {tag}.')
        seconds = round(elapsed)
        if sequence and sequence[-1]['seconds'] >= seconds:
            raise ValueError(f'Exposure {tag} is out of order.')
        camera = registered_camera(folder, tag, record)
        moving_light = False
        if tag == 'before-full-b':
            simulated = without_ball(old_sand, prior[-1])[0]
        elif tag == 'after-full-b':
            simulated = gray(predicted)
        else:
            try:
                path, count, measurement = observed_stage(route, fix)
            except AmbiguousStage as exc:
                omitted.append(dict(tag=tag, seconds=seconds, cameraOriginal=record['sha256'],
                                    interval=interval, reason=str(exc)))
                continue
            moving_light = moving_ripples and count < len(path)
            if moving_ripples and count == len(path):
                simulated = gray(predicted)
            else:
                png = signed_replay(prior, path, count, opening=old_sand, moving_ripples=moving_light)
                simulated = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        frame = {'seconds': seconds}
        frame_hashes = {}
        for kind, pixels in [('photo', camera), ('preview', simulated)]:
            treatment = '-moving-ripples' if moving_light and kind == 'preview' else ''
            filename = f'{trial.parent.name}-{tag}{treatment}-{kind}.webp'
            gallery_image(pixels).save(output/filename, quality=88, method=6)
            frame[kind] = filename
            frame_hashes[kind] = hashlib.sha256((output/filename).read_bytes()).hexdigest()
        sequence.append(frame)
        proof.append(dict(frame=frame, tag=tag, cameraOriginal=record['sha256'],
                          hashes=frame_hashes, position=measurement))
    (output/'sequence.json').write_text(json.dumps(sequence, indent=2)+'\n')
    record = dict(motion=intent['sha256'], receipt=intent['receipt'], previousMotion=earlier['sha256'],
                  openingPhoto=evidence['openingImageSha256'], forecast=evidence['signedForecastSha256'],
                  completed=not in_progress, frames=proof, omittedAmbiguousExposures=omitted)
    if moving_ripples:
        record['movingPreviewLight'] = 'Matched periodic grooves from the opening photograph, on fully raked sand.'
    (output/'proof.json').write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial', type=Path)
    parser.add_argument('preceding', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--in-progress', action='store_true')
    parser.add_argument('--moving-ripples', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        stage = Path(temporary)
        render(args.trial, args.preceding, stage, args.in_progress, moving_ripples=args.moving_ripples)
        # Swap the index after every file it references is present.
        for path in [*stage.glob('*.webp'), stage/'proof.json', stage/'sequence.json']:
            path.replace(args.output/path.name)
