"""Build the Mini guest page's movement data from checked-in tracks and measured geometry."""
import gzip
import json
import math
from pathlib import Path
import tempfile

import numpy as np

from check_ring_scene import TOL, read_path, safe_route, same_track
import ring_scene
import thrcommon


TRACKS = Path(__file__).resolve().parents[1] / 'patterns' / 'guest-rings'

# The Mini loads these scripts directly or from its photo form. Other files
# starting with "guest" in web/ serve the larger garden's editor.
MINI_WEB_FILES = (
    'guest.html', 'guest.js', 'guest-art.js', 'guest-themes.js', 'guest-paths.json',
    'guest-photo.js', 'guest-reviewed-portrait.js', 'guest-face-picker.js', 'guest-face-model.js', 'guest-face-verify.js',
    'guest-landmarks.js', 'guest-face-LICENSE.txt', 'guest-face-verify-LICENSE.txt',
    'guest-center-routes.js', 'guest-center-play.js', 'guest-lettering.js', 'guest-thai-lettering.js',
    'guest-portrait-caption.js',
)
MINI_GENERATED_FILES = ('guest-ring-planner.js', 'guest-center-data.json', 'guest-inward-portrait.js')


def roof_ranges(frame, low, high):
    """Each signed sector starts and finishes its engraving at the outer eave."""
    count = 7
    eave = high - .11 * (high - low)
    at_eave = np.abs(frame[:, 1] - eave) <= TOL
    # At an internal joint we finish one roof, clear the next sector, and
    # return to that joint to engrave its roof. Keep only the visible strokes.
    joints = []
    for i in range(count + 1):
        angle = ring_scene.GATE + i * math.tau / count
        rows = np.flatnonzero(at_eave & (np.abs(frame[:, 0] - angle) <= TOL))
        if len(rows) != (1 if i in (0, count) else 2):
            raise ValueError(f'Cannot locate the two sides of roof joint {i}.')
        joints.append(rows)
    spans = [[int(left[-1]), int(right[0])] for left, right in zip(joints, joints[1:])]
    if any(end <= start for start, end in spans):
        raise ValueError('The seven roof strokes are out of order.')
    return spans


def build():
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        ring_scene.build_mini_portrait(folder)
        zones = json.loads((folder / 'scene.json').read_text())['zones']
    center, outer = zones['center'], zones['outer']
    high = center['safe_bounds'][1]
    folder = TRACKS / 'mini-center'
    stocks = {}
    for name in ('center-clear', 'phage', 'guitar', 'book', 'add-pencil'):
        route = read_path(folder, name + '.thr')
        safe_route(route, ring_scene.GATE, 0, high, ring_scene.DOCK, high, name)
        stocks[name] = ring_scene.pack_path(route)
        if name == 'center-clear':
            # The phone's photo planner uses the full-precision fine spiral.
            # Check its complete path against the independently archived sand run.
            transit = np.asarray(center['transit'])
            photo_clear = thrcommon.unpack_path(center['photoErase'])
            generated = ring_scene.join(transit, photo_clear, transit[::-1])
            if not same_track(route, generated):
                raise ValueError('The Mini photo erase differs from the archived center clear.')

    frame_name = 'lek-mini-gables-1.thr'
    frame = read_path(TRACKS, frame_name)
    low, outer_high = outer['safe_bounds']
    safe_route(frame, ring_scene.GATE, low, outer_high, ring_scene.DOCK, low, frame_name)
    # The docked setup must round-trip byte for byte, including its final newline.
    if ''.join(thrcommon.thr_lines(frame)).encode('ascii') != (TRACKS / frame_name).read_bytes():
        raise ValueError('The checked-in seven-roof track is not in five-decimal player format.')
    return dict(stock=stocks, frame=ring_scene.pack_path(frame), roofs=roof_ranges(frame, low, outer_high),
                transit=center['transit'], photoErase=center['photoErase'],
                centerBounds=center['safe_bounds'], outerBounds=outer['safe_bounds'])


def build_guest_web_assets(web, destination, *, mini_only=False):
    # The firmware serves /lib/guest* uncached and expands the .gz filename transparently.
    def write(name, contents):
        (destination / (name + ".gz")).write_bytes(gzip.compress(contents, compresslevel=6, mtime=0))

    assets = (web / name for name in MINI_WEB_FILES) if mini_only else sorted(web.glob("guest*"))
    for asset in assets:
        write(asset.name, asset.read_bytes())
    write("guest-inward-portrait.js", (web / "ring-shadow.js").read_bytes() + b"\n" +
          (web / "ring-sand.js").read_bytes() + b"\n" +
          (Path(__file__).with_name("mini_local_grooves.js")).read_bytes() + b"\n" +
          (web / "guest-inward-portrait.js").read_bytes())
    write("guest-ring-planner.js", (web / "ring-planner.js").read_bytes())
    write("guest-center-data.json", json.dumps(build(), separators=(",", ":"), allow_nan=False).encode("ascii"))

if __name__ == '__main__':
    print(json.dumps(build(), separators=(',', ':'), allow_nan=False))
