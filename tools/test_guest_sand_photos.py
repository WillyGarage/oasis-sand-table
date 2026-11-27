#!/usr/bin/env python3
"""Exercise guest-place photo measurements with known marks in synthetic camera frames."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import cv2
import numpy as np

import ring_scene


SIZE, RADIUS = 900, 404
COMPARATOR = Path(__file__).with_name("compare_sand_zones.py")
# These are positions in the camera picture, with the image origin at the upper left.
# They are deliberately independent of the comparator's angle and place calculations.
LEFT, RIGHT, TOP = (252, 564), (648, 564), (450, 222)
BALL_BEFORE, BALL_AFTER = (466, 238), (666, 582)


def stroke(photo, points):
    line = np.asarray(points, np.int32)
    cv2.polylines(photo, [line + (0, 3)], False, 220, 3, cv2.LINE_AA)
    cv2.polylines(photo, [line], False, 57, 3, cv2.LINE_AA)


def background(marked=True):
    y, x = np.mgrid[:SIZE, :SIZE] - SIZE // 2
    radius = np.hypot(x, y)
    rng = np.random.default_rng(712)
    grain = rng.normal(0, 4, radius.shape).astype(np.float32)
    sand = 149 + .025*x - .010*y + cv2.GaussianBlur(grain, (0, 0), .7)
    # A fixed textured bowl rim gives the CLI something independent of the sand
    # to register against, including when the camera has rotated a fraction of a degree.
    rim = 82 + 14*np.sin(.055*x + .037*y) + 18*cv2.GaussianBlur(grain, (0, 0), 1.3)
    photo = np.clip(np.where(radius < RADIUS, sand, rim), 0, 255).astype(np.uint8)
    if not marked:
        return photo
    for cx, cy in (LEFT, RIGHT, TOP, (450, 450), (733, 270)):
        stroke(photo, [(cx-15, cy-10), (cx-7, cy-18), (cx+8, cy-12)])
    # A deep dimple by each drawing gives the chair photographs a visible
    # landmark. These three positions occupy different corners as seen from the chairs.
    for x, y in ((280, 576), (654, 596), (423, 204)):
        cv2.circle(photo, (x+1, y+2), 5, 208, -1, cv2.LINE_AA)
        cv2.circle(photo, (x, y), 4, 18, -1, cv2.LINE_AA)
    return photo


def add_ball(photo, point):
    x, y = point
    cv2.circle(photo, (x+3, y+3), 10, 45, -1, cv2.LINE_AA)
    cv2.circle(photo, point, 9, 195, -1, cv2.LINE_AA)
    cv2.circle(photo, (x-3, y-3), 3, 246, -1, cv2.LINE_AA)


def after_frame(sand):
    shifted = sand.copy()
    add_ball(shifted, BALL_AFTER)
    warp = cv2.getRotationMatrix2D((SIZE/2, SIZE/2), .20, 1.)
    warp[:, 2] += (1.5, -1.)
    return cv2.warpAffine(shifted, warp, (SIZE, SIZE), borderMode=cv2.BORDER_REFLECT)


def verify_chair_views(path):
    """Check the actual landmarks in both columns of the JPEG from each seat."""
    sheet = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert sheet is not None, path
    row_height, col_width = sheet.shape[0]//3, sheet.shape[1]//2
    # The first guest faces northeast: the dimple is ahead to the right.
    # The second has it behind to the left, the guest across has it behind to the right.
    for row, expected_xy in enumerate(((.66, .43), (.34, .67), (.68, .65))):
        for col in range(2):
            view = sheet[row*row_height:(row+1)*row_height, col*col_width:(col+1)*col_width]
            header = row_height//6
            y, x = np.nonzero(view[header:] < 32)
            assert len(x) >= 30, (path, row, col, "missing dimple")
            xy = (np.median(x)/col_width, (np.median(y)+header)/row_height)
            assert np.allclose(xy, expected_xy, atol=.045), (path, row, col, xy, expected_xy)


def measure(folder, scene, name, place, frame, *, exclude_ball=True):
    after = folder / (name + ".png")
    stem = folder / name
    assert cv2.imwrite(str(after), frame)
    cmd = [sys.executable, str(COMPARATOR), str(folder/"before.png"), str(after),
           "--scene", str(scene), "--guest-place", str(place),
           "--working-radius-px", str(RADIUS), "--blank-reference", str(folder/"blank.png"), "--out", str(stem)]
    if exclude_ball:
        for x, y in (BALL_BEFORE, BALL_AFTER):
            cmd += ["--exclude-disc", str((x-SIZE/2)/RADIUS), str((SIZE/2-y)/RADIUS), str(26/RADIUS)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    assert run.returncode == 0, run.stderr
    report = json.loads(stem.with_suffix(".json").read_text())
    assert [s["place"] for s in report["guest_places"]] == [1, 2, 3], report["guest_places"]
    assert report["registration"]["rim_correlation"] > .94, report["registration"]
    assert np.allclose(report["registration"]["translation_px"], (1.5, -1.), atol=.25), report["registration"]
    assert abs(report["registration"]["roll_degrees"]-.20) < .05, report["registration"]
    assert len(report["excluded_discs"]) == (2 if exclude_ball else 0)
    montage = cv2.imread(str(stem.with_suffix(".jpg")))
    assert montage is not None and min(montage.shape[:2]) >= 450
    verify_chair_views(folder/report["chair_photos"])
    seats = report["guest_places"]
    assert all(100 <= seat["visible_original_detail"]["pixels"] < seat["pixels"]//4 for seat in seats)
    garden = report["adjacent_zones"]
    assert all(s["pixels"] > 4000 for s in (*seats, garden["center"], garden["outer"]))
    assert report["requested"]["flagged_percent"] == seats[place-1]["flagged_percent"]
    return {**{str(s["place"]): s for s in seats}, "center": garden["center"], "garland": garden["outer"]}


def verify(name, regions, changed):
    for region, stats in regions.items():
        percent = stats["flagged_percent"]
        span = stats["largest_contiguous_change_in_groove_widths"]
        pixels = stats["pixels"] * percent / 100
        if region in changed:
            assert pixels >= 65 and span >= 2.3, (name, region, stats)
        else:
            assert pixels < 20 and span < 1., (name, region, stats)
    print(name, ", ".join(f"{key} {value['flagged_percent']:.2f}%" for key, value in regions.items()))


def exercise(folder, scene):
    assert cv2.imwrite(str(folder/"blank.png"), background(marked=False))
    sand = background()
    before = sand.copy()
    add_ball(before, BALL_BEFORE)
    assert cv2.imwrite(str(folder/"before.png"), before)

    # Both balls are inside guest places. The unmasked control proves their
    # removal matters; a test that put the ball outside the rim would pass by accident.
    only_ball = after_frame(sand)
    verify("unmasked ball", measure(folder, scene, "ball-visible", 3, only_ball, exclude_ball=False), {"2", "3"})
    verify("excluded ball", measure(folder, scene, "ball-excluded", 3, only_ball), set())

    left, right = LEFT, RIGHT
    first = sand.copy()
    stroke(first, [(left[0]-28, left[1]+14), (left[0]-13, left[1]-3),
                   (left[0]+7, left[1]+10), (left[0]+23, left[1]-3)])
    stroke(first, [(right[0]-20, right[1]+5), (right[0]-4, right[1]-1)])
    stroke(first, [(477, 413), (493, 423)])
    changed = measure(folder, scene, "replace-left", 1, after_frame(first))
    verify("lower-left replacement", changed, {"1", "2", "center"})
    assert changed["1"]["flagged_percent"] > 2 * changed["2"]["flagged_percent"], changed

    far = sand.copy()
    stroke(far, [(TOP[0]-25, TOP[1]+4), (TOP[0]-8, TOP[1]-3), (TOP[0]+6, TOP[1]+3)])
    stroke(far, [(728, 275), (745, 271)])
    verify("upper replacement", measure(folder, scene, "replace-top", 3, after_frame(far)), {"3", "garland"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path, nargs="?", help="existing 420 mm trial three-zone scene.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="guest-sand-photos-") as directory:
        folder = Path(directory)
        scene = args.scene
        if scene is None:
            ring_scene.build(folder/"scene", 420, 7, 3.5, 4, face_edge=True, guest_pitch_mm=2)
            scene = folder/"scene"/"scene.json"
        exercise(folder, scene)
