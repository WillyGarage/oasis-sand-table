"""Shade a pair of photographed guests without refitting their engraved faces."""

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree

import wide_portrait as portrait
from wide_group_crown import eye_frame
from wide_group_portrait import excursions, verify_group
from wide_portrait_hair import component_near, hair_locks, mask_for
from wide_portrait_rake import save_raked_field, shadow_field


def strokes_along_part(lines):
    """Stop at a hair tip rather than doubling around it into a printed hook."""
    for line in lines:
        walk = portrait.samples(line, 1.2)
        if len(walk) < 3:
            continue
        _, _, axes = np.linalg.svd(walk - walk.mean(axis=0), full_matrices=False)
        along = gaussian_filter1d(walk @ axes[0], 4, mode="nearest")
        turns = np.flatnonzero(np.diff(np.gradient(along) > 0)) + 1
        for segment in np.split(walk, turns):
            if len(segment) < 20:
                continue
            smooth = gaussian_filter1d(segment, 2.8, axis=0, mode="nearest")
            shape = cv2.approxPolyDP(smooth.astype("float32"), 0.75, False)[:, 0]
            if len(shape) >= 2:
                yield dict(kind="shade", closed=False, points=shape.tolist())


def shade_head(study, owner, gathered, world):
    """Register the original face crop to its final paired position using the eyes."""
    source, solo, photo, translation = study
    width = source["width"]
    group = [m for (who, _), m in gathered if who == owner]
    center, span, _ = eye_frame(solo)
    placed, placed_span, _ = eye_frame(group)
    zoom = placed_span / span
    position = placed - zoom * center

    def mouth(marks):
        return np.mean(next(m["points"] for m in marks if m["kind"] == "smile"), axis=0)

    if np.linalg.norm(mouth(solo) * zoom + position - mouth(group)) > 0.3 * width:
        raise ValueError("The photo crop no longer matches this engraved face.")
    _, tone, origin, scale = shadow_field({**source, "width": width / zoom}, solo, translation)
    uv = ((world - position) / zoom * scale + origin).astype("float32")

    def project(field):
        return cv2.remap(field, uv[:, :, 0], uv[:, :, 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    if photo is None:
        return project(tone), []
    gray, _, masks = photo
    groove = width * scale[0] / zoom
    try:
        hair = component_near(masks[0] > 0.48, mask_for(gray.shape, source["crop"]["hair"]))
        head = next(m for m in solo if m["kind"] == "head")
        skin = component_near(
            masks[1] > 0.55, mask_for(gray.shape, np.asarray(head["points"]) * scale + origin)
        )
    except ValueError:
        return project(tone), []  # A bald or obscured head can still carry the face's own photo shadows.
    if hair.sum() < 5 * groove**2:
        return project(tone), []
    light = cv2.GaussianBlur(gray.astype("float32"), (0, 0), 0.38 * groove)
    lo, hi = np.percentile(light[hair > 0], [8, 94])
    hair_tone = 0.40 + 0.56 * (1 - np.clip((light - lo) / max(hi - lo, 1), 0, 1))
    hair_tone = cv2.GaussianBlur(hair * hair_tone.astype("float32"), (0, 0), 0.55 * groove)
    size = len(gray)
    yy, xx = np.indices(gray.shape)
    side = np.minimum.reduce([xx, yy, size - 1 - xx, size - 1 - yy])
    hair_tone *= np.clip(side / (3 * groove), 0, 1)
    tone = np.maximum(0.65 * tone, hair_tone)

    local = np.stack([xx, yy], axis=-1)
    physical = (local - origin) / scale * zoom + position
    away = (side > 8) & (np.linalg.norm(physical, axis=2) < source["diameter"] / 2 - 2.65 * width)
    obstruction = np.zeros(gray.shape, "uint8")
    for (who, _), mark in gathered:
        line = np.rint((np.asarray(mark["points"]) - position) / zoom * scale + origin).astype("int32")
        if who != owner and mark["kind"] == "head":
            cv2.fillPoly(obstruction, [line], 1)
        cv2.polylines(obstruction, [line], mark["closed"], 1, max(1, round(2.7 * groove)))
    lines = hair_locks(gray, hair, skin, np.maximum(hair, skin), away & (obstruction == 0), 0.73 * groove)
    tracks = list(strokes_along_part([(line - origin) / scale * zoom + position for line in lines]))

    return project(tone), tracks


def preserve_faces(page, source, base, required, plan, additions):
    gathered = base.copy()
    width = source["width"]
    previous = excursions(gathered, plan, portrait.downloaded_route(page, plan, source["dock"]))
    for owner, stroke in additions:
        key = (owner, 1 + max(i for (who, i), _ in gathered if who == owner))
        trial = [*gathered, (key, stroke)]
        proposed = portrait.plan_marks(page, [m for _, m in trial])
        if not proposed or not any(e["source"] == len(gathered) for e in proposed["events"]):
            continue
        route = portrait.downloaded_route(page, proposed, source["dock"])
        current = excursions(trial, proposed, route)
        if previous.keys() | {key} != current.keys() or any(
            not portrait.same_excursion(path, current[k]) for k, path in previous.items()
        ):
            continue
        line = portrait.samples(np.asarray(stroke["points"]), 0.1 * width)
        signed = current[key]
        cloud = portrait.excursion_cloud(
            signed, {"first": 0, "last": len(signed) - 1}, source["radius"], 0.04 * width
        )
        if (cKDTree(cloud).query(line)[0] < 0.25 * width).mean() < 0.6:
            continue
        try:
            verify_group(page, source, trial, required, proposed, 2, route=route)
        except ValueError:
            continue
        gathered, plan, previous = trial, proposed, current
    return gathered, plan


def save_pair_print(page, source, studies, gathered, required, plan, directory):
    radius, size, width = source["radius"], source["diameter"], source["width"]
    if abs(radius - 420) > 0.001 or abs(size - 632.8) > 0.01 or abs(width - 7) > 0.001:
        raise ValueError("This paired print needs the 632.8 mm center and 7 mm groove.")
    if len(studies) != 2:
        raise ValueError("Both selected people need a registered photograph.")
    # A single shared raster covers the physical wide center, including the sand
    # between the two separately scaled photo crops and either side of the seam.
    pixels = 732
    scale = np.array([pixels / size, -pixels / size])
    origin = np.full(2, pixels / 2)
    yy, xx = np.indices((pixels, pixels))
    world = (np.stack([xx, yy], axis=-1) - origin) / scale
    radius_map = np.linalg.norm(world, axis=2)
    field = np.zeros(xx.shape, "float32")
    additions = []
    for who, study in enumerate(studies):
        tint, lines = shade_head(study, who, gathered, world)
        mask = np.zeros(xx.shape, "uint8")
        neighbor = np.zeros_like(mask)
        for (owner, _), mark in gathered:
            q = np.rint(np.asarray(mark["points"]) * scale + origin).astype("int32")
            if owner != who and mark["kind"] == "head":
                cv2.fillPoly(neighbor, [q], 1)
            if who == owner and mark["kind"] not in ("head", "hairline"):
                cv2.polylines(mask, [q], mark["closed"], 1, round(0.9 * width * scale[0]))

        def clearance(obstacle, edge, ramp):
            room = cv2.distanceTransform(1 - obstacle, cv2.DIST_L2, 5) / (width * scale[0])
            return np.clip((room - edge) / ramp, 0, 1)

        tint *= clearance(neighbor, 1.5, 2) * clearance(mask, 1, 1.5)
        if (tint > 0.22).sum() < 2 * (width * scale[0]) ** 2:
            raise ValueError("One of the selected faces has too little clear space for its shadows.")
        field = np.maximum(field, tint)
        additions.extend((who, line) for line in lines)
    radial = radius_map / width
    # Fade before the dock and the center, where bunching forms a target.
    field *= (
        0.66
        * np.clip((size / 2 - radius_map - width) / (1.6 * width), 0, 1)
        * np.clip((radial - 3) / 5, 0, 1)
        * np.clip((radius_map - 24) / 70, 0, 1) ** 2
    )
    all_marks, shaped = preserve_faces(page, source, gathered, required, plan, additions)
    directory.mkdir()
    result = save_raked_field(page, source, shaped, field, origin, scale, directory)
    return {
        **result,
        "applied": True,
        "locks": len(all_marks) - len(gathered),
        "note": "Both faces keep their scale while the rake draws the photographed shadows.",
    }
