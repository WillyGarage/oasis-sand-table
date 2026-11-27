#!/usr/bin/env python3
"""Score a completed prediction against one or more held-out, registered Mini photographs."""
import argparse
import json
from pathlib import Path

import numpy as np

from mini_bed_preview import BALL_SHADOW_MM, RADIUS_MM, blur, disk, fields, gray


def detail(image):
    return blur(image, .95) - blur(image, 14)


def compare(model, prediction, original, finished, masks):
    model_before, model_after = model
    observed_texture = detail(finished)
    observed_change = detail(finished - original)
    methods = [('original_replay', model_before, model_after),
               ('calibrated_replay', original, prediction),
               ('no_drawing', original, original)]
    results = {region: {'pixels': int(mask.sum())} for region, mask in masks.items()}
    for method, before, after in methods:
        rendered_texture = detail(after)
        rendered_change = detail(after - before)
        for region, mask in masks.items():
            scores = {}
            for key, a, b in [('texture', rendered_texture, observed_texture),
                              ('change', rendered_change, observed_change)]:
                x, y = a[mask], b[mask]
                scores[key + '_mae'] = round(float(np.abs(x - y).mean()), 3)
                scores[key + '_correlation'] = (round(float(np.corrcoef(x, y)[0, 1]), 3)
                                                if min(x.std(), y.std()) > .005 else None)
            results[region][method] = scores
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--prediction', required=True, type=Path)
    parser.add_argument('--finished', required=True, type=Path, nargs='+')
    parser.add_argument('--route', required=True, type=Path)
    parser.add_argument('--pitch', required=True, type=float)
    parser.add_argument('--face-box', required=True, type=int, nargs=4,
                        metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    args = parser.parse_args()
    bed, prediction = gray(args.before), gray(args.prediction)
    if prediction.shape != bed.shape:
        parser.error('The bed and prediction must share the registered frame.')
    route = np.loadtxt(args.route, comments='#', ndmin=2)
    model0, model1, coverage = fields(route, args.pitch, len(bed))
    xn, yn = disk(bed.shape)
    usable = np.hypot(xn, yn) < .94
    for theta, radius in (route[0], route[-1]):
        distance = np.hypot(xn - radius * np.cos(theta), yn - radius * np.sin(theta))
        usable &= distance > max(.16, BALL_SHADOW_MM / RADIUS_MM)
    y, x = np.indices(bed.shape)
    left, top, right, bottom = args.face_box
    engraved = usable & (coverage > .94)
    masks = {'face': engraved & (x > left) & (x < right) & (y > top) & (y < bottom),
             'all_carved': engraved, 'untouched': usable & (coverage < .001)}
    if any(not np.any(mask) for mask in masks.values()):
        parser.error('Each named region must include usable sand.')
    report = {}
    for file in args.finished:
        photo = gray(file)
        if photo.shape != bed.shape:
            parser.error(f'The finished photograph {file} does not match the registered frame.')
        report[str(file)] = compare((model0, model1), prediction, bed, photo, masks)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
