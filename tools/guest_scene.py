#!/usr/bin/env python3
"""Build upright pictures that share one Oasis drawing and can be replaced independently.

Each subject stays in a fixed disc, with a short entrance to the outer rim. A closed
drawing returns to the same entrance, so travelling between pictures never cuts
across the sand. New scenes and replacements are drawn after the table's full fine
erase. Adding a picture in an empty place can draw directly from the rim. Inputs/outputs are in
drawing coordinates, the same theta/rho used by /status and .thr files.

    python3 tools/guest_scene.py --demo captures/thanksgiving --manifest web/guest-paths.json
"""
import argparse
import json
import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

import bg_erase
import compose
import thrcommon
from guest_line_art import anvil, birdhouse, camping_trailer, chef_hat, coffee_grinder, cooking_pot, folded_crane, paper_bird, rocking_chair, washing_machine
from guest_harvest_art import (acorn, acorn_oak, caramel_apple, cornucopia, crescent_roll, desk_lamp, dinner_candle, ear_of_corn, gravy_boat, harvest_basket, harvest_pear, harvest_wheat, lotus_blossom, oven_mitt, pineapple_with_ring,
                              maple_leaf, mayflower_ship, pilgrim_hat, roast_turkey, rolling_pin, turkey_leg, wishbone)
from guest_guitar import electric_guitar
from guest_book_art import two_books
from guest_pie_art import lattice_pie, pumpkin_pie

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patterns" / "icons"))
import coarse
import make_alex
import make_creatures
import make_lek
import make_thomas

NAMES = ("Lower left", "Lower right", "Top")
ANGLES = np.radians([-150., -30., 90.])
RADIUS = .405
CENTERS = .555 * np.column_stack((np.cos(ANGLES), np.sin(ANGLES)))
GROOVE_HALF = .021
RIM_TOLERANCE = .003
DEFAULT = ("phage", "books", "temple")

# Mini versions leave room for distinct grooves at roughly 75 mm across.
# Each is one closed walk. Shared edges double as connections between details.
def phage():
    return [
        (0,.94), (.34,.74), (.34,.40), (0,.19), (-.34,.40), (-.34,.74), (0,.94),
        (0,.61), (.34,.40), (0,.61), (-.34,.40), (0,.19),
        (-.12,.13), (-.12,-.22), (.12,-.22), (.12,.13), (0,.19),
        (.12,.13), (-.12,.13), (-.12,-.04), (.12,-.04), (.12,-.22),
        (.23,-.28), (0,-.38), (-.23,-.28), (-.12,-.22), (-.23,-.28),
        (-.59,-.13), (-.79,-.49), (-.59,-.13), (-.23,-.28),
        (-.33,-.41), (-.40,-.75), (-.33,-.41), (-.23,-.28), (0,-.38),
        (.23,-.28), (.59,-.13), (.79,-.49), (.59,-.13), (.23,-.28),
        (.33,-.41), (.40,-.75), (.33,-.41), (.23,-.28), (.12,-.22),
        (.12,.13), (0,.19), (.34,.40), (.34,.74), (0,.94)
    ]


def books():
    # Three offset hardcovers, pages inset in the open ends, a ribbon in the top book.
    return [
        (-.86,-.40), (-.67,-.60), (.69,-.60), (.80,-.51), (.79,-.32), (-.62,-.32),
        (-.86,-.40), (-.84,-.18), (-.61,-.10), (.67,-.10), (.79,-.18), (.79,-.32),
        (-.62,-.32), (-.64,-.10), (-.61,-.10), (-.74,-.01), (-.76,.18),
        (-.57,.30), (.78,.30), (.87,.23), (.88,.04), (.67,-.10), (-.61,-.10),
        (-.74,-.01), (.64,-.01), (.86,.10), (.88,.04), (.64,-.08), (.67,-.10),
        (-.61,-.10), (-.74,-.01), (-.76,.18), (-.57,.30), (-.46,.32),
        (-.61,.39), (-.60,.57), (-.44,.70), (.53,.70), (.74,.55), (.74,.36), (.56,.30),
        (-.46,.32), (-.61,.39), (-.42,.44), (.53,.44), (.74,.55), (.53,.44),
        (.48,.44), (.48,.20), (.38,.25), (.28,.18), (.28,.44), (-.42,.44),
        (-.61,.39), (-.46,.32), (-.57,.30), (-.76,.18), (-.74,-.01),
        (-.61,-.10), (-.84,-.18), (-.86,-.40)
    ]


def temple():
    # Broad gable and two flared roof tiers, hooked eaves, pointed doorway.
    return [
        (0,.78), (-.015,.91), (.06,.98), (.02,.88), (0,.78),
        (-.12,.54), (-.35,.25), (-.54,.16), (-.62,.30), (-.59,.10), (-.43,.04),
        (0,.68), (.43,.04), (.59,.10), (.62,.30), (.54,.16), (.35,.25), (.12,.54), (0,.78),
        (0,.68), (-.43,.04), (.43,.04), (0,.68), (0,.40), (-.14,.18), (.14,.18), (0,.40),
        (0,.68), (-.43,.04), (-.59,.10), (-.70,-.06), (-.84,-.13), (-.90,.02),
        (-.86,-.21), (-.65,-.29), (-.42,-.08), (.42,-.08), (.65,-.29), (.86,-.21),
        (.90,.02), (.84,-.13), (.70,-.06), (.59,.10), (.43,.04), (.42,-.08),
        (.65,-.29), (.56,-.27), (.56,-.52), (.68,-.58), (.68,-.66),
        (-.68,-.66), (-.68,-.58), (-.56,-.52), (.56,-.52), (.15,-.52),
        (.15,-.37), (0,-.20), (-.15,-.37), (-.15,-.52), (-.56,-.52),
        (-.56,-.27), (-.65,-.29), (-.42,-.08), (-.43,.04), (0,.68), (0,.78)
    ]


def guitar_books():
    # The guitar leans to the right. Its side covers the left ends of the
    # books; the shared contour lets us draw both without a crossing.
    neck = (-.22, .22)
    silhouette = [
        neck, (.06,.71), (.04,.79), (.12,.91), (.21,.88), (.25,.80),
        (.19,.69), (.13,.67), (-.12,.18), (-.04,.10), (-.03,.00),
        (-.09,-.10), (-.17,-.15), (-.21,-.24), (-.17,-.33),
        (-.17,-.44), (-.23,-.54), (-.34,-.61), (-.50,-.62),
        (-.65,-.57), (-.77,-.46), (-.81,-.34), (-.79,-.22), (-.72,-.14),
        (-.60,-.10), (-.51,-.07), (-.47,.02), (-.49,.11), (-.46,.19),
        (-.37,.25), (-.30,.25), neck,
    ]
    sound = [(-.31 + .101 * math.cos(t), .012 + .101 * math.sin(t))
             for t in np.linspace(math.pi/2, math.pi/2 + math.tau, 28)]
    string = [neck, (-.31,.113)]
    bridge = [(-.32,-.09), (-.45,-.31), (-.54,-.26), (-.36,-.36),
              (-.45,-.31), (-.32,-.09)]
    details = string + sound + [(-.21,.01),(-.23,-.05)] + bridge + [
        (-.23,-.05), (-.21,.01), (-.25,.10),(-.31,.113), neck]
    books = [
        (-.04,.10), (.60,.10), (.75,.01), (.76,-.13), (.59,-.22),
        (-.18,-.22), (-.09,-.10), (-.03,.00), (.61,.00), (.75,.01),
        (.61,.00), (.59,-.22), (.76,-.13), (.85,-.22), (.86,-.34),
        (.72,-.42), (-.17,-.42), (-.17,-.33), (.72,-.33), (.85,-.22),
        (.72,-.33), (.72,-.42), (.66,-.45), (.68,-.55), (.56,-.62),
        (-.50,-.62), (-.34,-.61), (-.23,-.54), (.53,-.54), (.66,-.45),
        (.53,-.54), (.56,-.62), (.68,-.55), (.66,-.45), (.72,-.42),
        (-.17,-.42), (-.17,-.33), (-.21,-.24), (-.17,-.15), (-.09,-.10),
        (-.03,.00), (-.04,.10)
    ]
    join_at = silhouette.index(books[0])
    return details + silhouette[1:join_at] + books + silhouette[join_at+1:]


SHAPES = {
    "phage": ("Bacteriophage", phage), "books": ("Stack of books", books),
    "two_books": ("Two stacked books", two_books),
    "temple": ("Thai rooftop", temple), "guitar_books": ("Guitar leaning on books", guitar_books), "guitar": ("Acoustic guitar", coarse.guitar),
    "electric_guitar": ("Electric guitar", electric_guitar),
    "pumpkin": ("Pumpkin", coarse.pumpkin), "classroom": ("Apple on books", make_alex.classroom),
    "clapper": ("Clapperboard", make_alex.clapper), "clapper_alt": ("Film reel", make_alex.clapper_alt),
    "turkey": ("Turkey", make_alex.turkey), "elephant": ("Thai elephant", make_lek.elephant),
    "thailand": ("Thailand", make_lek.thailand), "hotpot": ("Hot pot", make_lek.hotpot),
    "rocket": ("Rocket", make_thomas.rocket), "aztec": ("Aztec sun stone", make_thomas.aztec),
    "dna": ("Double helix", make_thomas.dna), "hunt": ("Hunt", make_thomas.hunt_alt),
    "trex": ("T. rex", make_creatures.trex), "raptor": ("Velociraptor", make_creatures.raptor),
    "paper_crane": ("Folded paper bird", paper_bird), "origami_crane": ("Paper crane with folded wings", folded_crane),
    "chef_hat": ("Chef’s hat", chef_hat),
    "caravan": ("Camping trailer", camping_trailer), "pumpkin_pie": ("Slice of pumpkin pie", pumpkin_pie),
    "lattice_pie": ("Whole lattice pie", lattice_pie), "pilgrim_hat": ("Buckled pilgrim hat", pilgrim_hat),
    "lotus_blossom": ("Lotus blossom on a leaf", lotus_blossom),
    "acorn": ("Acorn", acorn), "acorn_oak": ("Acorn with an oak leaf", acorn_oak),
    "indian_corn": ("Ear of corn", ear_of_corn),
    "birdhouse": ("Birdhouse", birdhouse), "anvil": ("Anvil", anvil),
    "rocking_chair": ("Rocking chair", rocking_chair), "washing_machine": ("Washing machine", washing_machine),
    "cooking_pot": ("Cooking pot", cooking_pot),
    "coffee_grinder": ("Hand-cranked coffee grinder", coffee_grinder),
    "cornucopia": ("Cornucopia", cornucopia), "maple_leaf": ("Maple leaf", maple_leaf),
    "wishbone": ("Turkey wishbone", wishbone), "gravy_boat": ("Gravy boat", gravy_boat),
    "turkey_leg": ("Roast turkey drumstick", turkey_leg),
    "roast_turkey": ("Roast turkey on a platter", roast_turkey),
    "dinner_candle": ("Dinner candle in a holder", dinner_candle),
    "pineapple_with_ring": ("Pineapple with a cut ring", pineapple_with_ring),
    "oven_mitt": ("Quilted oven mitt", oven_mitt),
    # Both long sides of the barrel show in this direction on the measured Mini bed.
    "rolling_pin": ("Rolling pin", lambda: rolling_pin(tilt=-33)),
    "harvest_basket": ("Harvest apple basket", harvest_basket),
    "crescent_roll": ("Crescent roll", crescent_roll),
    "harvest_wheat": ("Harvest wheat", harvest_wheat),
    "harvest_pear": ("Halved harvest pear", harvest_pear),
    "desk_lamp": ("Adjustable desk lamp", desk_lamp),
    "caramel_apple": ("Caramel apple on a stick", caramel_apple),
    "mayflower_ship": ("Mayflower sailing ship", mayflower_ship),
}
SUBJECTS = {name: data[0] for name, data in SHAPES.items()}


@lru_cache(maxsize=None)
def motif(name):
    if name not in SHAPES:
        raise ValueError(f"Unknown subject: {name}")
    spec = SHAPES[name][1]()
    if isinstance(spec, (list, np.ndarray)):
        xy = np.array(spec, float)
    else:
        if 'path' in spec:
            line = list(spec['path'])
            line += line[-2::-1]
        else:
            spec.pop('final', None)
            for region in spec['regions']:
                region['pitch'] = region.get('pitch', 1) / RADIUS
            closed, _ = make_creatures.build(spec)
            line = closed[1:-1]    # discard artificial run from the source picture's rim
        xy = (np.asarray(line) - [make_creatures.CX, make_creatures.CY]) / make_creatures.S
        xy[:, 1] *= -1
    if not np.allclose(xy[0], xy[-1]):
        raise ValueError(f"{name} does not return along its own lines")
    xy = compose.simplify(xy, .003)
    if not np.array_equal(xy[0], xy[-1]):
        xy = np.vstack([xy, xy[0]])
    scale = max(1., np.hypot(*xy.T).max())
    return xy / scale


def rim(slot):
    return np.array([math.cos(ANGLES[slot]), math.sin(ANGLES[slot])])


def polar(xy):
    return compose.xy_to_polar(xy)


def join(parts):
    aligned = []
    for part in parts:
        p = np.asarray(part, float).copy()
        if aligned:
            last = aligned[-1][-1]
            p[:, 0] += math.tau * round((last[0] - p[0, 0]) / math.tau)
            if not np.allclose(last, p[0], rtol=0, atol=2e-6):
                raise ValueError("Disconnected guest drawing")
            p = p[1:]
        if len(p):
            aligned.append(p)
    if not aligned:
        raise ValueError("The scene is empty")
    return checked(np.vstack(aligned))


def checked(points):
    if len(points) >= thrcommon.MAX_POINTS:
        raise ValueError(f"Scene exceeds the Mini's limit ({len(points)} points)")
    if not np.isfinite(points).all() or np.min(points[:, 1]) < 0 or np.max(points[:, 1]) > 1.000001:
        raise ValueError("Point outside the drawing area")
    return points


def check_slot(points, slot):
    # Check the actual polar interpolation, including the space a groove occupies.
    xy = np.column_stack(thrcommon.to_xy(points))
    for j, center in enumerate(CENTERS):
        if j != slot and np.linalg.norm(xy - center, axis=1).min() < RADIUS + 2 * GROOVE_HALF:
            raise ValueError("This move would mark a neighbouring picture")
    return checked(points)


@lru_cache(maxsize=None)
def picture(name, slot):
    xy = CENTERS[slot] + RADIUS * motif(name)
    gate = rim(slot)
    # Break the existing closed walk at the nearest point of a line, so we enter
    # at the silhouette regardless of which slot the guest put the design in.
    segments = np.diff(xy, axis=0)
    lengths = np.maximum((segments ** 2).sum(axis=1), 1e-14)
    t = np.clip(((gate - xy[:-1]) * segments).sum(axis=1) / lengths, 0, 1)
    q = xy[:-1] + t[:, None] * segments
    k = int(np.argmin(np.linalg.norm(q - gate, axis=1)))
    line = np.vstack([gate, q[k], xy[k + 1:-1], xy[:k + 1], q[k], gate])
    return check_slot(polar(line), slot)


def approach(start, slot, existing):
    """Reach the rim at the current angle, then follow the shorter arc."""
    if start is None:
        return np.array([[ANGLES[slot], 1.]])
    angle, radius = map(float, start)
    if not math.isfinite(angle) or not math.isfinite(radius) or not -.001 <= radius <= 1.002:
        raise ValueError("Invalid start position")
    if existing and radius < 1 - RIM_TOLERANCE:
        raise ValueError("The ball must be at the rim to change an existing scene")
    radius = float(np.clip(radius, 0, 1))
    dest = angle + math.remainder(ANGLES[slot] - angle, math.tau)
    return bg_erase.densify([(angle, radius), (angle, 1), (dest, 1)])


def check_subjects(subjects):
    if len(subjects) != len(ANGLES):
        raise ValueError("Expected three slots")
    for name in subjects:
        if name and name not in SUBJECTS:
            raise ValueError(f"Unknown subject: {name}")


def initial(subjects=DEFAULT, start=None):
    check_subjects(subjects)
    parts = []
    for slot, name in enumerate(subjects):
        if name:
            parts.extend([approach(start, slot, bool(parts)), picture(name, slot)])
            start = parts[-1][-1]
    return join(parts)


def swap(subjects, slot, subject, start=None):
    """Return artwork for a full-scene replacement, or just the addition to an empty place."""
    check_subjects(subjects)
    if slot not in range(len(ANGLES)) or subject not in SUBJECTS:
        raise ValueError("Unknown subject or place")
    if subjects[slot]:
        updated = list(subjects)
        updated[slot] = subject
        return initial(updated)   # Played after the ordinary whole-table erase.
    return join([approach(start, slot, True), picture(subject, slot)])


def export_manifest(path):
    slots = [dict(label=NAMES[i], angle=float(a), center=CENTERS[i].tolist(), radius=RADIUS)
             for i, a in enumerate(ANGLES)]
    subjects = {name: dict(label=title, paths=[picture(name, i).round(5).tolist() for i in range(len(slots))])
                for name, title in SUBJECTS.items()}
    notice = Path(__file__).with_name('guest_line_art-LICENSE.txt').read_text()
    path.write_text(json.dumps(dict(version=1, slots=slots, subjects=subjects, thanksgivingExtras=['rolling_pin'], artworkLicense=notice),
                               separators=(',', ':')) + '\n')


def demo(out, start):
    import sandsim
    out.mkdir(parents=True, exist_ok=True)
    scene = initial(start=start)
    update = swap(DEFAULT, 0, 'guitar', start=scene[-1])
    for stem, path in [('scene', scene), ('swap', update)]:
        bg_erase.write(out / (stem + '.thr'), path, stem + ' / artwork only; use the normal full-table erase first')
        print(f"{stem}: {len(path)} points, ball from {path[0]} to {path[-1]}, "
              f"{bg_erase.motor_minutes(path):.1f} min estimated", flush=True)
        preview = sandsim.render_steps([('erase', .02), path], size=650, real=True)
        compose.save_lit(np.asarray(preview), str(out / (stem + '.jpg')))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path)
    ap.add_argument('--demo', type=Path)
    ap.add_argument('--start', type=float, nargs=2, metavar=('THETA', 'RHO'))
    args = ap.parse_args()
    if not args.manifest and not args.demo:
        ap.error('provide --demo, --manifest, or both')
    if args.demo:
        demo(args.demo, args.start)
    if args.manifest:
        export_manifest(args.manifest)
