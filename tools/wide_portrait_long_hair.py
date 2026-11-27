"""Fit locks below the chin into a wider engraving from the selected guest's photograph."""

import base64

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import minimize
from scipy.spatial import cKDTree

from wide_portrait import (
    PLAN, downloaded_route, excursion_cloud, fit_photo_features, load_models, samples, same_excursion,
)
from wide_portrait_woodcut import at_pixels, hair_field
from wide_portrait_hair import (
    FACE_OVAL,
    component_near,
    inner_distance,
    mask_for,
    measured_hair,
    outlines,
    pick_face,
)


# The wide search starts at the selected face in the original oriented image.
# Black margins in the valid mask are real photo boundaries, where a lock may be clipped.
WIDE_TILE = """async ({area,scale,dx,dy}) => {
  const file=document.getElementById('hostPortraitInput').files[0], url=URL.createObjectURL(file);
  try {
    const im=new Image(); im.src=url; await im.decode();
    const canvas=document.createElement('canvas');canvas.width=canvas.height=600;
    const ctx=canvas.getContext('2d'), step=2*area.radius/(scale*600);
    const left=area.x-(300+dx)*step, top=area.y-(300+dy)*step;
    ctx.fillStyle='white';ctx.fillRect(0,0,600,600);
    ctx.drawImage(im,-left/step,-top/step,area.width/step,area.height/step);
    return {png:canvas.toDataURL('image/png').split(',')[1],
      bounds:[-left/step,-top/step,(area.width-left)/step,(area.height-top)/step]};
  } finally {URL.revokeObjectURL(url);}
}"""


def tile(page, source, scale, shift, python):
    area = source["crop"]["area"]
    data = page.evaluate(
        WIDE_TILE, {"area": area, "scale": scale, "dx": float(shift[0]), "dy": float(shift[1])}
    )
    raw = base64.b64decode(data["png"], validate=True)
    gray = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    meshes, masks = load_models(raw, python)
    return gray, meshes, masks, data["bounds"]


def relocate(mark, scale, translation):
    return {
        **mark,
        **{
            key: (np.asarray(mark[key]) * scale + translation).tolist()
            for key in ("points", "lids", "rim", "opening")
            if key in mark
        },
    }


def hair_ribbons(page, source, marks, plan, photo):
    gray, mesh, masks = photo
    diameter, width = source["diameter"], source["width"]
    unit = np.array([1.0, -1.0]) * len(gray) / diameter
    groove = len(gray) * width / diameter

    def pixels(q):
        return np.asarray(q) * unit + len(gray) / 2

    head = mask_for(gray.shape, pixels(marks[0]["points"]))
    core, _, support, _, _ = hair_field(masks[0].astype("float32"), head, mesh, groove)
    taken = np.zeros(gray.shape, np.uint8)
    previous = {e["source"]: e for e in plan["events"]}
    original = downloaded_route(page, plan, source["dock"])
    for index in previous:
        m = marks[index]
        cv2.polylines(taken, [np.rint(pixels(m["points"])).astype("int32")], m["closed"], 1, 1)
    room = (inner_distance(core) > 0.78 * groove) & (inner_distance(1 - taken) > 1.6 * groove)
    clearance = cv2.distanceTransform(support.astype("uint8"), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    mid = np.median(mesh[[1, 13, 14, 10], 0])
    added = []
    # Follow a fraction of the way across each side of the actual hair band,
    # clipping at gaps, shoulders and places the ball already engraved.
    for side in (-1, 1):
        region = core & ((np.arange(len(gray)) - mid) * side >= 0)[None, :]
        rows = np.flatnonzero(np.sum(region, axis=1) > 4)
        if len(rows) < 3:
            continue
        left, right = [
            gaussian_filter1d(np.array([fn(np.flatnonzero(region[y])) for y in rows], float), 0.8 * groove)
            for fn in (np.min, np.max)
        ]
        for fraction in (0.5, 0.22, 0.78, 0.08, 0.92):
            xx = np.rint(left + (right - left) * fraction).astype(int)
            valid = room[rows, xx] & np.r_[True, np.diff(rows) == 1]
            for a, b in np.flatnonzero(np.diff(np.r_[False, valid, False])).reshape(-1, 2):
                if b - a < 4.4 * groove:
                    continue
                curve = np.column_stack((xx[a:b:3], rows[a:b:3])).astype("float32")
                curve = cv2.approxPolyDP(curve[:, None, :], 1.0, False)[:, 0, :]
                ink = samples(curve, 0.34 * groove)
                if not np.all(at_pixels(room, ink)):
                    continue
                added.append(
                    {"kind": "shade", "closed": False, "points": ((ink - len(gray) / 2) / unit).tolist()}
                )
                cv2.polylines(
                    room.view("uint8"), [np.rint(ink).astype("int32")], False, 0, round(3.5 * groove)
                )
    for _ in range(3):
        if len(added) < 2:
            break
        new = marks + added
        trial = page.evaluate(PLAN, new)
        if not trial:
            break
        current = {e["source"]: e for e in trial["events"]}
        if {i for i in current if i < len(marks)} != previous.keys():
            break
        route = downloaded_route(page, trial, source["dock"])
        if any(
            i not in current
            or not same_excursion(
                original[e["first"] : e["last"] + 1], route[current[i]["first"] : current[i]["last"] + 1]
            )
            for i, e in previous.items()
        ):
            break
        safe = []
        for i, e in current.items():
            if i < len(marks):
                continue
            q = excursion_cloud(route, e, source["radius"], width * 0.045)
            if np.min(at_pixels(clearance, pixels(q))) >= (0.5 + 0.045 / 2) * groove + 2**0.5:
                safe.append(new[i])
        if len(safe) < 2:
            break
        if len(safe) == len(added):
            return new, trial, len(safe)
        added = safe
    return marks, plan, 0


def wider_hair(page, source, marks, baseline, offset, model_python, *, previous_smile=None, raised_only=False):
    diameter, width = source["diameter"], source["width"]
    area = source["crop"].get("area")
    if area is None:
        raise ValueError("This portrait does not have a measured source crop.")
    active = [marks[i] for i in sorted(e["source"] for e in baseline["events"])]
    eyes = [np.mean(m["points"], axis=0) for m in active if m["kind"] in ("eye", "glasses")]
    mouths = [np.mean(m["points"], axis=0) for m in active if m["kind"] == "smile"]
    if len(eyes) != 2 or len(mouths) != 1:
        raise ValueError("A wider view needs two clear eyes and a mouth.")
    offset = np.zeros(2) if offset is None else np.asarray(offset)
    features = np.asarray([*sorted(eyes, key=lambda q: q[0]), mouths[0]]) - offset
    units = np.array([1.0, -1.0]) * 600 / diameter
    scout_scale, scout_shift = 0.34, np.array([0.0, -58.0])
    gray, meshes, masks, bounds = tile(page, source, scout_scale, scout_shift, model_python)
    expected = features * units * scout_scale + 300 + scout_shift
    mesh = pick_face(meshes, expected)
    oval = mask_for(gray.shape, mesh[FACE_OVAL])
    top = oval.copy()
    top[int(np.mean(expected[:2], axis=0)[1]) :] = 0
    # Select only a connected hair region supported at the photographed scalp
    # and extending significantly below this person's chin.
    hair = component_near(
        masks[0] > 0.72, cv2.dilate(top, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    )
    edge = outlines(hair)[0]
    span = np.linalg.norm(expected[0] - expected[1])
    across = (expected[1] - expected[0]) / span
    down = np.array([-across[1], across[0]])
    depth = (edge - mesh[152]) @ down
    rows, cols = np.where(hair)
    pixels = np.column_stack((cols, rows))
    low = (pixels - mesh[152]) @ down > span * 0.42
    raised = np.quantile(depth, 0.95) < 0.7 * span or np.count_nonzero(low) < 0.65 * span**2
    if raised_only and not raised:
        raise ValueError("The hair extends below the chin.")
    if np.any(edge.min(axis=0) < np.maximum(1, bounds[:2]) + 2) or np.any(
        edge.max(axis=0) > np.minimum(598, bounds[2:]) - 2
    ):
        raise ValueError("The ends of the hair continue beyond this photograph.")
    # Use both detected face boxes and face meshes. A connected mass touching
    # another person's upper head cannot be attributed to the selected guest.
    for other in meshes:
        if np.linalg.norm(other[1] - mesh[1]) < 0.2 * span:
            continue
        if np.count_nonzero(hair & mask_for(gray.shape, other[FACE_OVAL])) > 0.07 * span**2:
            raise ValueError("The photograph joins hair from two people.")
    for box in source.get("boxes", []):
        selected = source["selected"]
        if np.hypot(box["x"] - selected["x"], box["y"] - selected["y"]) < 0.25 * min(box["w"], selected["w"]):
            continue
        factor = 300 * scout_scale / area["radius"]
        center = np.array([box["x"] - area["x"], box["y"] - area["y"]]) * factor + 300 + scout_shift
        radius = box["w"] * factor / 2
        if np.count_nonzero(np.linalg.norm((pixels - center) / radius, axis=1) < 1.12) > max(
            4.0, 0.07 * span**2
        ):
            raise ValueError("The selected hair overlaps another face.")
    # Offer this alternate only when the new crop recovers a substantial
    # length missing from the active engraving. A dark shirt or a full beard
    # contained in the existing head cannot satisfy that condition alone.
    heads = [m for m in active if m["kind"] == "head"]
    if len(heads) != 1:
        raise ValueError("The wider view needs one complete head outline.")
    original = heads[0]
    head = (np.asarray(original["points"]) - offset) * units * scout_scale + 300 + scout_shift
    if raised:
        # On a tilted head, measure toward the crown along the person's own
        # axis. Require an area of connected scalp hair beyond the old top.
        old_top = np.min(head @ down)
        if (old_top - np.quantile(edge @ down, .05) < .22 * span
                or np.count_nonzero(pixels @ down < old_top - .15 * span) < .08 * span**2):
            raise ValueError("The wider view adds too little photographed hair above the face.")
    elif np.quantile(depth, 0.95) - np.max((head - mesh[152]) @ down) < 0.48 * span:
        raise ValueError("The current portrait already includes these locks.")
    envelope = np.vstack((edge, mesh[FACE_OVAL]))
    center = minimize(
        lambda c: np.linalg.norm(envelope - c, axis=1).max(),
        envelope.mean(axis=0),
        method="Nelder-Mead",
        options={"maxiter": 160},
    ).x
    # Leave room for the ball to enter each side of the engraved silhouette.
    zoom = (300 - 3.5 * width * 600 / diameter) / np.linalg.norm(envelope - center, axis=1).max()
    scale = scout_scale * zoom
    shift = (300 + scout_shift - center) * zoom
    # Coarse segmentation can understate the furthest lock. If the measured
    # outline won't fit, retry with more room around the same photographed
    # center, provided the eyes can still be resolved in the wider view.
    last_error = "The portrait could not include the full locks."
    for resize in (1.0, 0.86):
        fitted = scale * resize
        if (not raised and fitted >= 0.85) or span * zoom * resize * diameter / (600 * width) < 5:
            break
        if raised and not .72 <= fitted <= 1.:
            continue
        try:
            return fitted_hair(
                page, source, active, features, offset, fitted, shift * resize, model_python, previous_smile,
                raised=raised,
            )
        except ValueError as error:
            last_error = str(error)
    raise ValueError(last_error)


def fitted_hair(page, source, active, features, offset, scale, shift, model_python, previous_smile=None, *, raised=False):
    diameter, width = source["diameter"], source["width"]
    units = np.array([1.0, -1.0]) * 600 / diameter
    gray, meshes, masks, bounds = tile(page, source, scale, shift, model_python)
    meshes = list(meshes)
    translation = shift / units - offset * scale
    moved = [relocate(m, scale, translation) for m in active]
    mesh = pick_face(meshes, features * units * scale + 300 + shift)
    skin = mask_for(gray.shape, mesh[FACE_OVAL])

    def facial(m):
        if m["kind"] not in ("head", "hairline", "shade"):
            return True
        if m["kind"] != "shade":
            return False
        q = np.rint(samples(np.asarray(m["points"]) * units + 300, 2)).astype(int)
        x, y = np.clip(q, 0, 599).T
        return np.mean(skin[y, x]) > 0.88

    face = [m for m in moved if facial(m)]
    old_hair = source["crop"]["hair"]
    if old_hair:
        old_hair = (np.asarray(old_hair) * scale + shift / units).tolist()
    hair = measured_hair(gray, masks, meshes, moved, old_hair, diameter, width)
    outer = np.asarray(hair[0]["points"]) * units + 300
    if np.any(outer.min(axis=0) < np.asarray(bounds[:2]) + 2) or np.any(
        outer.max(axis=0) > np.asarray(bounds[2:]) - 2
    ):
        raise ValueError("A lock runs off the edge of the original photograph.")
    if raised:
        from wide_portrait_locks import nearby_faces

        # The closer measurement can resolve a neighbor the scouting tile
        # missed. Map all the original detections into this exact pixel crop.
        area = source["crop"]["area"]
        radius = area["radius"] / scale
        tile_area = dict(area, radius=radius, x=area["x"] - shift[0]*radius/300,
                         y=area["y"] - shift[1]*radius/300)
        framed = dict(source, crop=dict(source["crop"], area=tile_area))
        if nearby_faces(framed, meshes, mesh, mask_for(gray.shape, outer).astype(bool)):
            raise ValueError("The wider head outline overlaps another person.")
    proposed = [hair[0], *face, *hair[1:]]
    # A photo-derived lip opening may fit the close-up and crowd a cheek in
    # the wider portrait. Establish the complete wider engraving, including
    # its hair strokes, before offering the new mouth at this scale.
    if previous_smile is not None and not raised:
        mouth = next(i for i, mark in enumerate(proposed) if mark["kind"] == "smile")
        replacement = proposed[mouth]
        proposed[mouth] = relocate(previous_smile, scale, translation)
    plan = page.evaluate(PLAN, proposed)
    if not plan:
        raise ValueError("The wider portrait does not fit this garden.")
    events = {e["source"]: e for e in plan["events"]}
    required = [i for i, m in enumerate(proposed) if m["kind"] in ("head", "eye", "glasses", "smile", "nose")
                or raised and (m.get("measuredLensEye") or m["kind"] == "bridge")]
    if not set(required) <= events.keys():
        raise ValueError("The wider portrait would lose a facial feature.")
    # Independently sample the rounded polar download. Require most of each
    # eye or lip to survive at this smaller scale.
    route = downloaded_route(page, plan, source["dock"])
    for i in required:
        mark = proposed[i]
        q = np.asarray(mark["points"])
        curve = np.vstack((q, q[0])) if mark["closed"] else q
        trace = cKDTree(excursion_cloud(route, events[i], source["radius"], width * 0.055))
        if np.mean(trace.query(samples(curve, width * 0.18))[0] < width * 0.48) < 0.80:
            raise ValueError("The wider engraving would lose a drawn eye, lip or silhouette.")
    if raised:
        from wide_portrait_woodcut import woodcut_version

        return woodcut_version(page, source, proposed, plan, (gray, meshes, masks), (0., 0.), follow_grain=True)
    full, plan, count = hair_ribbons(page, source, proposed, plan, (gray, mesh, masks))
    if previous_smile is not None:
        original = downloaded_route(page, plan, source["dock"])
        try:
            full, plan = fit_photo_features(page, source, full, plan, original, {mouth: replacement})
        except ValueError:
            pass  # Keep the established wider drawing when the new smile crowds it.
    return full, plan, count
