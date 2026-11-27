#!/usr/bin/env python3
"""Generate a concentric garden and independent .thr replacements, entirely offline.

    python3 tools/ring_scene.py --out captures/ring-scene
    python3 tools/ring_scene.py --layout portrait --out captures/ring-wide
    python3 tools/ring_scene.py --mini-portrait --out captures/mini-portrait

The initial drawing starts at the six-o'clock rim of a prepared bed. The large
layouts cut a stem from rim to center, then texture and draw each zone. The Mini
portrait layout starts on fine-cleared sand and draws just its flower and border.
A change enters on that stem, clears just its band, draws the new subject,
and restores the segment of stem it shares with future trips. Every route
returns to the same dock. All dimensions are provisional until measured in sand.
"""
import argparse
import base64
import heapq
import json
import math
from itertools import combinations, permutations
from pathlib import Path

import numpy as np

from autumn_leaves import autumn_leaf
from guest_embellishments import ADDITIONS, SEATED_ADDITIONS, engraving
from guest_book_art import books as open_book
from guest_guitar import guitar as guitar_silhouette
from guest_harvest_art import rolling_pin
from guest_phage import compact_phage
from guest_popup_book import popup_book
from guest_pumpkin import pumpkin as ribbed_pumpkin
from guest_roof_art import temple as swept_roof
import guest_scene
import thrcommon

TAU = math.tau
GATE = -math.pi / 2
DOCK = (GATE, 1.0)
BANDS = {"center": (0, .36), "middle": (.36, .77), "outer": (.77, 1)}
LAYOUTS = {"garden": BANDS, "portrait": {"center": (0, BANDS["outer"][0]), "outer": BANDS["outer"]}}
MINI_BANDS = {"center": (0, .70), "outer": (.70, 1)}
MINI_PREPARED_PITCH = .020


def line(angle0, r0, angle1, r1):
    """Sample a polar segment tightly enough for the existing trajectory player."""
    steps = max(1, math.ceil(abs(angle1-angle0)/.05), math.ceil(abs(r1-r0)/.015))
    return np.column_stack((np.linspace(angle0, angle1, steps+1), np.linspace(r0, r1, steps+1)))


def stem(r0, r1):
    return line(GATE, r0, GATE, r1)


def join(*parts):
    """Keep cumulative angles across connected segments, including file splits."""
    result = [np.asarray(parts[0])]
    for raw in parts[1:]:
        part = np.array(raw, dtype=float, copy=True)
        end = result[-1][-1]
        part[:, 0] += TAU * round((end[0] - part[0, 0]) / TAU)
        if not np.allclose(end, part[0], atol=1e-7, rtol=0):
            raise ValueError(f'Disconnected garden path: {end} → {part[0]}')
        if len(part) > 1:
            result.append(part[1:])
    return np.vstack(result)


def erase(low, high, pitch):
    """Finish both edges of the winding spiral with a closed contour."""
    turns = math.ceil((high - low) / pitch)
    border = line(GATE, high, GATE+TAU, high)
    sweep = line(GATE, high, GATE+turns*TAU, low)
    inner = line(GATE, low, GATE+TAU, low) if low else np.array([[GATE, low]])
    return join(border, sweep, inner, stem(low, high))


def outward_center_erase(high, pitch):
    """Enter on the dock spoke and cover that mark as the spiral returns to the perimeter."""
    path = erase(0, high, pitch)[::-1].copy()
    path[:, 0] += TAU * round((GATE - path[0, 0]) / TAU)
    return path


def leaf(angle, root, tip, bow, half_width):
    """A tapered, bent leaf, in the coordinate frame of its radial stem."""
    up = np.linspace(0, 1, 25)
    u = np.r_[up, up[-2::-1]]
    side = np.r_[np.ones(len(up)), -np.ones(len(up)-1)]
    lean = bow * u + .28 * bow * np.sin(np.pi*u)
    width = half_width * np.sin(np.pi*u) * (1.2-.45*u)
    return np.column_stack((angle + lean + side*width, root + (tip-root)*u))


def flower(low, high, sunflower, groove=5 / 450):
    """Enter at the tip of the southern petal and leave along its opposite flank."""
    count = 13 if sunflower else 8
    turn = math.pi / count
    bow = .05 if sunflower else 0.
    root = high * (.39 if sunflower else .245)
    # A shallow margin lets the pointed tips read separately from the frame.
    # Only the entrance petal crosses this margin, over at most 1½ groove widths.
    gap = min(.073 * high, 1.5 * groove)
    tip = high - gap
    phase = GATE - bow
    short_tip = tip * (.81 if sunflower else .72)
    first = leaf(phase, root, tip, bow, .69 * turn)
    peak = int(np.argmax(first[:, 1]))
    door = line(GATE, high, GATE, tip)
    seed = line(phase, root, phase - 3 * math.tau, 0.)
    # Follow one side of the first petal into the seed. The return spiral
    # puts the ball back on the collar without cutting across the seed's coils.
    parts = [door, first[:peak+1][::-1], seed, seed[::-1]]
    for j in range(count):
        angle = phase + 2 * j * turn
        if j:
            parts.append(leaf(angle, root, tip, bow, .69 * turn))
        parts.append(leaf(angle, root, root + .75 * (tip-root), .75 * bow, .36 * .69 * turn))
        between = angle + turn
        parts.extend((line(angle, root, between, root),
                      leaf(between, root, short_tip, .55 * bow, .28 * turn),
                      line(between, root, angle + 2 * turn, root)))
    # The first petal's other side is still uncut and naturally leads back out.
    return join(*parts, first[peak:][::-1], door[::-1])


SMALL_GUEST_STYLES = {"books": "books_open", "guitar": "guitar_silhouette",
                      "temple": "temple_gable", "pumpkin": "pumpkin_ribbed"}
OPEN_PLACE = "open_place"


def telescope():
    """A tilted refractor, with a stepped eyepiece and a three-legged mount."""
    # Draw the tube in its own frame, then the mount with its legs pointing down.
    axis = np.array([.84, math.sqrt(1 - .84**2)])
    normal = np.array([-axis[1], axis[0]])
    def tube(points):
        u, v = np.asarray(points).T
        return np.array([-.055, .236]) + u[:, None]*axis + v[:, None]*normal

    lens_angle = np.linspace(-math.pi / 2, 3 * math.pi / 2, 37)
    lens = tube(np.column_stack((.77 + .092*np.cos(lens_angle), .21*np.sin(lens_angle))))
    # Start at the bottom of the objective. Follow its near edge to the
    # top, continue down the outline, and return around the entire glass.
    rim = lens[:19]
    upper_and_rear = tube([
        (.77, .21), (.54, .21), (.49, .15), (.05, .141),
        # A small finder on a single bracket, parallel to the main barrel.
        (.037, .29), (.165, .29), (.165, .414), (-.36, .39),
        (-.36, .303), (-.072, .29), (-.063, .139), (.05, .141),
        (-.063, .139), (-.48, .13), (-.51, .078),
        (-.71, .078), (-.73, .105), (-.84, .105), (-.84, -.10),
        (-.73, -.10), (-.71, -.068), (-.51, -.068), (-.48, -.13), (-.18, -.14),
    ])
    saddle = tube([(-.18, -.14), (.15, -.146)])
    # Each foot tapers back to the head. The shorter rear leg is visible
    # through the gap between the front two. The saddle closes the cradle.
    mount = np.array([
        saddle[0], (-.13, .025), (-.084, -.046), (-.084, -.115),
        (-.14, -.14), (-.15, -.207), (-.54, -.78), (-.48, -.775),
        (-.048, -.235), (-.018, -.67), (.034, -.64), (.058, -.235),
        (.466, -.776), (.52, -.78), (.15, -.207), (.142, -.14),
        (.073, -.115), (.073, -.038), (.145, .055), saddle[1],
    ])
    lower_and_hood = tube([(-.18, -.14), (.15, -.146), (.49, -.15), (.54, -.21), (.77, -.21)])
    return np.vstack((rim, upper_and_rear[1:], mount[1:], saddle[:1],
                      lower_and_hood[1:], lens[1:-1], rim[:1]))


def open_helix():
    """Two open strands with six spaced rungs, drawn on the same grooves on return."""
    t = np.linspace(-1, 1, 161)
    angle = math.radians(53)
    axis = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-axis[1], axis[0]])
    stem = (.92 * t)[:, None] * axis
    bend = (.36 * np.sin(np.pi * .84 * t))[:, None] * normal
    front, back = stem + bend, stem - bend
    rungs = [14, 33, 54, 106, 127, 146]
    skew = 4  # Offset the far end of each rung along the second strand.

    path = []
    for index, point in enumerate(front):
        path.append(point)
        if index in rungs[1:-1]:
            path.extend((back[index + skew], point))
    # Use the last and first rungs to change strands. The four open tips
    # are dead ends, so each gets a short retrace to its nearest rung.
    first, last = rungs[0], rungs[-1]
    return np.vstack((path, front[-2:last-1:-1], back[last+skew:],
                      back[-2::-1], back[1:first+skew+1], front[first::-1]))


RING_MOTIFS = {
    "telescope": ("Telescope on a tripod", telescope),
    "rolling_pin": ("Rolling pin", rolling_pin),
    "dna_open": ("Open double helix", open_helix),
    "books_open": ("Open book", open_book),
    "guitar_silhouette": ("Acoustic guitar silhouette", guitar_silhouette),
    "temple_gable": ("Swept Thai rooftop", swept_roof),
    "temple_popup_book": ("Thai roof pop-up book", popup_book),
    "pumpkin_ribbed": ("Pumpkin with five lobes", ribbed_pumpkin),
    "phage_faceted": ("Faceted bacteriophage", compact_phage),
}
# Lucide source curves sampled on their 24-unit grid. The resulting closed
# walks use the same unit disc as custom guest art, stored at 1/10,000 radius.
# Reused paths enter and return over existing grooves. See guest_line_art-LICENSE.txt.
LIBRARY_MOTIFS = json.loads((Path(__file__).resolve().parents[1] /
                             'patterns/guest-rings/lucide-outlines.json').read_text())
# Keep a ring drawing in its original catalog position when a Mini version is added.
SUBJECTS = {**{key: label for key, label in guest_scene.SUBJECTS.items() if key not in RING_MOTIFS},
            **{key: label for key, (label, _) in RING_MOTIFS.items()},
            **{key: art['label'] for key, art in LIBRARY_MOTIFS.items()},
            **{key: label for key, (label, _, _) in ADDITIONS.items()}}


def motif(name):
    if name in LIBRARY_MOTIFS:
        return np.asarray(LIBRARY_MOTIFS[name]['points'], dtype=float) / 10000
    if name in ADDITIONS:
        return engraving(name, motif(ADDITIONS[name][1]))[0]
    if name in RING_MOTIFS:
        return RING_MOTIFS[name][1]()
    return guest_scene.motif(name)


def detail_style(name, original, center, scale, fitted_seats):
    """Let a detail occupy the sky only within the sector reserved for its guest."""
    ordinary = ADDITIONS[name][2]
    spacious = SEATED_ADDITIONS.get(name) if fitted_seats else None
    if spacious is None:
        return ordinary
    _, sky = spacious(original)
    # All seated motifs turn with their chairs. In this frame the first chair
    # is at six o'clock. Check every signed-player segment of the larger shape
    # against the radial and angular limits assumed when protecting a neighbor.
    walk = guest_scene.polar(scale*sky + [0, -center])
    tolerance = .00002  # Both five-decimal file roundings.
    bearing = np.abs(walk[:,0]-GATE)
    if (walk[:,1].min() >= center-scale+tolerance and walk[:,1].max() <= center+scale-tolerance
            and bearing.max() <= math.asin(scale/center)-tolerance):
        return spacious
    return ordinary


def hanging_subject(name, base_angle, center, rail, scale, face_edge=False, fitted=False):
    """Hang an emblem from its nearest point on the outer rail."""
    radial = np.array([math.cos(base_angle), math.sin(base_angle)])
    def placed(outline):
        if face_edge:
            outline = thrcommon.rotate_xy(outline, base_angle - GATE)
        return center*radial + scale*outline

    # Attach at the original silhouette even when the added detail extends
    # farther out. This keeps the same hanger in a full drawing or a later edit.
    if name in ADDITIONS:
        original = motif(ADDITIONS[name][1])
        callback = detail_style(name, original, center, scale, face_edge and fitted)
        complete, _ = engraving(name, original, callback=callback)
        xy = placed(complete[:-1])
        original_xy = placed(original[:-1])
        root = original_xy[np.argmax(np.linalg.norm(original_xy,axis=1))]
        index = np.argmin(np.linalg.norm(xy-root,axis=1))
    else:
        xy = placed(motif(name)[:-1])
        index = np.argmax(np.linalg.norm(xy,axis=1))
    xy = np.concatenate([xy[index:], xy[:index+1]])
    path = guest_scene.polar(xy)
    angle = base_angle + math.remainder(path[0, 0]-base_angle, TAU)
    attach = line(angle, rail, angle, path[0, 1])
    return angle, join(attach, path, attach[::-1])


# The UI lists Thomas, Alex and Lek. Going counterclockwise from six
# o'clock, the ball passes Alex, then Lek, then Thomas.
SLOT_TWELFTHS = (10, 2, 6)
TRAVEL_ORDER = (1, 2, 0)
# The modeled displaced ridge extends 1.15 groove widths from a new stroke.
# Protect half an existing groove as well. The extra .05 is rounding headroom.
GUEST_SAND_CLEARANCE = 1.70


def guest_geometry(low, high, face_edge=False, *, clearance=None, groove=0):
    width = high - low
    inset = .026 * width
    scale = .455 * width
    fit = {}
    if clearance is not None and clearance > inset:
        # The top seat approaches along the band's outer limit. A neighbor's
        # furthest mark is its short hanging line at the rail. Move the rail
        # and the drawing's outer limit together to keep that line intact.
        fitted_scale = scale - (clearance - inset)
        if fitted_scale > 0 and 2 * fitted_scale >= groove:
            scale, inset = fitted_scale, clearance
            fit["refitted"] = True
        else:
            # A disc smaller than one cut cannot show a letter or outline.
            # A whole-ring redraw can still use the original composition.
            fit["independentPlaces"] = False
    return dict(rail=high - inset, center=(low + high) / 2, scale=scale, bounds=[low, high],
                angles=[GATE + TAU * i / 12 for i in SLOT_TWELFTHS],
                **({"faceEdge": True} if face_edge else {}), **fit)


def guest_excursion(subject, slot, geometry):
    """Leave the circular rail for one upright emblem, then rejoin it.

    Every subject in a given place starts and finishes at the same leaves.
    That makes each trip interchangeable without disturbing neighboring art.
    """
    angle = geometry["angles"][slot]
    rail = geometry["rail"]
    before = GATE + TAU * (SLOT_TWELFTHS[slot] - 1) / 12
    after = GATE + TAU * (SLOT_TWELFTHS[slot] + 1) / 12
    if subject == OPEN_PLACE:
        return line(before, rail, after, rail)
    entrance, art = hanging_subject(subject, angle, geometry["center"], rail, geometry["scale"],
                                    geometry.get("faceEdge", False), geometry.get("refitted", False))
    if not before < entrance < after:
        raise ValueError(f"{subject} fell outside its assigned sector")
    return join(line(before, rail, entrance, rail), art, line(entrance, rail, after, rail))


def guest_leaf_pair(angle, rail, tip):
    return join(leaf(angle, rail, tip, -.063, .023), leaf(angle, rail, tip, .063, .023))


def guest_stem_leaves(low, high, rail):
    width = high-low
    root_right, root_left = low + .71 * width, low + .52 * width
    return (stem(rail, root_right), leaf(GATE, root_right, root_right - .24 * width, .154, .055),
            stem(root_right, root_left), leaf(GATE, root_left, root_left - .24 * width, -.163, .057),
            stem(root_left, high))


def guest_ornaments(low, high, rail=None):
    """Four fixed sections, interleaved with the three guest excursions."""
    if rail is None:
        rail = guest_geometry(low, high)["rail"]
    width = high - low
    angles = [GATE + TAU * i / 12 for i in (1, 3, 5, 7, 9, 11)]
    tip = rail - width * .22
    pairs = [guest_leaf_pair(a, rail, tip) for a in angles]
    return [
        join(stem(high, rail), line(GATE, rail, angles[0], rail), pairs[0]),
        join(pairs[1], line(angles[1], rail, angles[2], rail), pairs[2]),
        join(pairs[3], line(angles[3], rail, angles[4], rail), pairs[4]),
        join(pairs[5], line(angles[5], rail, GATE + TAU, rail), *guest_stem_leaves(low, high, rail))
    ]


def guest_styles(geometry, groove):
    # At 24 grooves across the old fret pattern still closes up. The original
    # composition has almost 32. Use the open shapes below the crossover.
    if not groove or 2 * geometry["scale"] >= 28 * groove:
        return {}
    if geometry.get("refitted"):
        return {**SMALL_GUEST_STYLES, "phage": "phage_faceted"}
    return SMALL_GUEST_STYLES


def guest_subjects(preferred, open_places=False, use_guitar=False):
    if open_places:
        return (OPEN_PLACE,) * len(guest_scene.DEFAULT)
    subjects = ("guitar", *guest_scene.DEFAULT[1:]) if use_guitar else guest_scene.DEFAULT
    # The starting bed and its saved edition include the original phage.
    # A new request in that same garden can prefer the more open engraving.
    return tuple(subject if subject == "phage" else preferred.get(subject, subject) for subject in subjects)


def guest_band(low, high, use_guitar, *, open_places=False, face_edge=False, clearance=None, groove=0):
    geometry = guest_geometry(low, high, face_edge, clearance=clearance, groove=groove)
    names = guest_subjects(guest_styles(geometry, groove), open_places, use_guitar)
    return guest_band_drawing(geometry, names)


def guest_band_drawing(geometry, names):
    low, high = geometry["bounds"]
    sections = guest_ornaments(low, high, geometry["rail"])
    parts = [sections[0]]
    for index, slot in enumerate(TRAVEL_ORDER):
        parts.extend([guest_excursion(names[slot], slot, geometry), sections[index + 1]])
    return join(*parts)


def pack_path(path):
    """Encode signed coordinate deltas at 1e-8 resolution as little-endian integers."""
    points = np.rint(np.asarray(path) * 100_000_000).astype(np.int64)
    points[1:] = np.diff(points, axis=0)
    if np.abs(points).max() >= 2**31:
        raise ValueError("A ring path step exceeds the packed coordinate range.")
    return base64.b64encode(points.astype("<i4").tobytes()).decode("ascii")


def guest_place_paths(geometry, slot, pitch, groove):
    """Replace one upright guest on the original inward spiral, keeping both neighbors visible."""
    low, high = geometry["bounds"]
    center, scale, rail = geometry["center"], geometry["scale"], geometry["rail"]
    angle = geometry["angles"][slot]
    left, right = angle-TAU/12, angle+TAU/12
    width = high-low
    turns = math.ceil(width/pitch)
    spacing = width/turns
    # The disc holds every supported outline, including a custom pair or an
    # off-center sketch whose long hanging stroke starts at the highest point.
    # Leave the customary guest ring available on trays that put the transit
    # rails too close to the other guests' furrows for an independent edit.
    if (not geometry.get("independentPlaces", True) or turns < 2
            or center+scale+1.25*groove > high or center-scale-1.25*groove < low
            or rail+.80*groove > high):
        return None
    initial = math.asin((scale+1.2*groove)/center)
    widest = math.radians(83)
    if widest+initial >= TAU/3:
        return None

    def contour(a, radius, b):
        return line(a, radius, a+math.remainder(b-a, TAU), radius)

    def spiral_radius(turn, theta):
        return high-spacing*(turn+(theta-GATE)/TAU)

    def lane(turn, start, end):
        return line(start, spiral_radius(turn, start), end, spiral_radius(turn, end))

    def spread(turn):
        # Extend each later, inward pass beyond the preceding turnaround.
        # This softens its end in the original grain instead of stacking stops.
        progress = turn/(turns-1)
        through = math.log(high/(high-progress*width))/math.log(high/low)
        return initial + (widest-initial)*through

    access = line(left, high, left, rail)
    approach = join(stem(1, high), contour(GATE, high, left), access)
    to_gate = join(line(right, rail, right, high), contour(right, high, GATE))
    depart = join(to_gate, stem(high, low), stem(low, 1))
    wipe = [access[::-1]]
    tip = rail - width*.22
    recut = [contour(left, rail, right), guest_leaf_pair(right, rail, tip),
             contour(right, rail, left), guest_leaf_pair(left, rail, tip)]
    if slot != 2:
        # Both lower seats can reach every spiral row on the existing
        # six-o'clock stem without crossing another guest's drawing.
        clockwise = slot == 0
        gate = GATE+TAU if clockwise else GATE
        sign = -1 if clockwise else 1
        near = angle+sign*initial
        wipe.extend((contour(left, high, gate), contour(gate, high, near), contour(near, high, gate)))
        previous = high
        for turn in range(turns):
            far = angle+sign*spread(turn)
            radius = spiral_radius(turn, gate)
            wipe.extend((line(gate, previous, gate, radius), lane(turn, gate, far), lane(turn, far, gate)))
            previous = radius
        wipe.extend((line(gate, previous, gate, low), contour(gate, low, far), contour(far, low, gate),
                     stem(low, high), contour(gate, high, left), access))
        recut.extend((contour(left, rail, gate), *guest_stem_leaves(low, high, rail),
                      contour(gate, high, left), access))
        work_limits = [far, gate+.22] if clockwise else [gate-.22, far]
    else:
        # At the top seat no radial stem is available. Ease into each next
        # groove across the face of the guest's area, then retrace the entire
        # original spiral row across that transition. Both far ends stay on
        # the background spiral, without leaving straight dividing strokes.
        blend = min(.32, initial)
        start = angle+blend/2
        theta = np.linspace(start, start-blend, max(3, math.ceil(blend/.009)+1))
        fraction = np.linspace(0, 1, len(theta))
        ease = fraction**2*(3-2*fraction)
        # At a full-groove erase pitch, the first spiral turn can fall just
        # over half a groove inside the wall at the right edge of this seat.
        outer_end = angle+initial if high-spiral_radius(0, angle+initial) > groove/2 else angle-initial
        wipe.extend((contour(left, high, outer_end), contour(outer_end, high, start)))
        previous = np.full(len(theta), high)
        for turn in range(turns):
            current = spiral_radius(turn, theta)
            half = spread(turn)
            wipe.extend((np.column_stack((theta, (1-ease)*previous+ease*current)),
                         lane(turn, theta[-1], angle-half), lane(turn, angle-half, angle+half),
                         lane(turn, angle+half, start)))
            previous = current
        wipe.extend((line(start, previous[0], start, low), contour(start, low, angle-widest),
                     line(angle-widest, low, GATE+TAU, low), stem(low, high),
                     contour(GATE, high, left), access))
        work_limits = [angle-widest, angle+widest]
    # A direct addition only touches this guest's rail and the engraving.
    # The full stem is already cut and needs no restoration.
    return dict(approach=pack_path(approach), fillExit=pack_path(join(to_gate, stem(high, 1))),
                clear=pack_path(join(*wipe)), recut=pack_path(join(*recut)),
                exit=pack_path(depart), limits=[angle-initial, angle+initial],
                workLimits=work_limits, radialBounds=[low, high])


def clears_guest_sectors(path, geometry, protected, groove, clearance):
    """Check the whole trip against protected seats, including their hanging strokes."""
    if not protected:
        return True
    from check_ring_scene import sample_walk
    step = groove / 8
    xy = sample_walk(path, step)
    radius = np.linalg.norm(xy, axis=1)
    angle = np.arctan2(xy[:, 1], xy[:, 0])
    center, scale = geometry["center"], geometry["scale"]
    half_width = math.asin(scale / center)
    for neighbor in protected:
        bearing = geometry["angles"][neighbor]
        # Any guest's outline and its path out to the rail fit inside this
        # annular sector. Project onto its nearest bounding ray, then clamp radius.
        turn = np.maximum(0., np.abs((angle-bearing+math.pi) % TAU-math.pi) - half_width)
        along = radius * np.cos(turn)
        nearest = np.clip(along, center-scale, max(geometry["rail"], center+scale))
        distance = np.hypot(along-nearest, radius*np.sin(turn))
        if distance.min() <= clearance + step/2 + .00001:  # sample spacing and five-decimal export
            return False
    return True


def keeps_other_places(path, geometry, slot, groove, clearance):
    protected = set(range(len(geometry["angles"]))) - {slot}
    path = np.asarray(path)
    if not len(path) or not np.isfinite(path).all():
        return False
    if slot == 2 and len(path) > 1 and (GUEST_SAND_CLEARANCE-1.65)*groove > 2e-5+2e-8:
        # The far seat approaches past a neighbor on the outer circle. That
        # circle is exactly the designed clearance above the neighbor's rail.
        # A polar segment never falls below its smaller endpoint radius, so
        # these edges have an exact bound without a sampling error. The .05
        # groove built into the inset covers both five-decimal roundings.
        outside = max(geometry["rail"], geometry["center"]+geometry["scale"]) + clearance
        # The outer contour itself can round inward in the five-decimal file.
        # The 0.05-groove reserve above covers both that and the neighbor's cut.
        near = np.minimum(path[:-1, 1], path[1:, 1]) < outside-1e-5
        boundaries = np.flatnonzero(np.diff(np.r_[False, near, False]))
        return all(clears_guest_sectors(path[start:end+1], geometry, protected, groove, clearance)
                   for start, end in boundaries.reshape(-1, 2))
    return clears_guest_sectors(path, geometry, protected, groove, clearance)


def guest_fill_tours(geometry, places, groove, clearance):
    """Connect open guest places along the rail inscribed by the opening scene."""
    rail = geometry["rail"]
    gates = geometry["gates"]
    available = [i for i, place in enumerate(places) if place]
    all_seats = set(range(len(gates)))
    result = {}
    for size in (2, 3):
        for seats in combinations(available, size):
            protected = all_seats.difference(seats)
            # Cutting the circle at the skipped seat forces every connector
            # to go around its whole preserved wedge. With all three open,
            # take the shorter arc between the existing leaves.
            cut = geometry["angles"][next(iter(protected))] if protected else None

            def along_rail(start, end):
                if cut is None:
                    turn = math.remainder(end-start, TAU)
                else:
                    turn = (end-cut) % TAU - (start-cut) % TAU
                return line(start, rail, start+turn, rail)

            candidates = []
            for order in permutations(seats):
                starts = [GATE, *(gates[seat][1] for seat in order)]
                ends = [*(gates[seat][0] for seat in order), GATE]
                paths = [along_rail(start, end) for start, end in zip(starts, ends)]
                paths[0] = join(stem(1, rail), paths[0])
                paths[-1] = join(paths[-1], stem(rail, 1))
                if all(clears_guest_sectors(path, geometry, protected, groove, clearance) for path in paths):
                    sections = [{"place": seat, "approach": pack_path(path)} for seat, path in zip(order, paths)]
                    sections[-1]["exit"] = pack_path(paths[-1])
                    candidates.append(sections)
            if candidates:
                result["-".join(map(str, seats))] = candidates
    return result


def signed_guest_files(route):
    return [dict(name=name, text="".join(thrcommon.thr_lines(part)))
            for name, part in file_parts("guest-ring", route)]


def detail_approach(base_path, anchor, approaches):
    from check_ring_scene import travel
    # Every edge in this graph is an actual cut in the published base drawing.
    # Coalesce revisited vertices, so a guitar's sound hole or far fret need
    # not be driven merely to reach its side. Work backward from the joint.
    vertices = [tuple(p) for p in base_path]
    edges = {}
    lengths = np.diff(travel(base_path))
    for a, b, length in zip(vertices, vertices[1:], lengths):
        edges.setdefault(a, {})[b] = length
        edges.setdefault(b, {})[a] = length
    root = vertices[anchor]
    distance, toward, queue = {root: 0}, {}, [(0,root)]
    while queue:
        total, node = heapq.heappop(queue)
        if total != distance[node]:
            continue
        for neighbor, length in edges[node].items():
            candidate = total+length
            if candidate < distance.get(neighbor, math.inf):
                distance[neighbor], toward[neighbor] = candidate, node
                heapq.heappush(queue, (candidate,neighbor))
    options = []
    for approach in approaches:
        # The two ends of the stock excursion are the leaf gates.
        gate = min((vertices[0],vertices[-1]),key=lambda p:abs(math.remainder(p[0]-approach[-1,0],TAU)))
        trail = [gate]
        while trail[-1] != root:
            trail.append(toward[trail[-1]])
        options.append(join(approach, trail))
    return min(options, key=lambda p:travel(p)[-1])


def guest_gate_paths(geometry, slot, place):
    """Dock-to-gate routes on the outer contour and the prepared hanging rail."""
    rail = geometry["rail"]
    outer = (thrcommon.unpack_path(place["approach"]), thrcommon.unpack_path(place["fillExit"])[::-1])
    inner = []
    for gate in geometry["gates"][slot]:
        arc = line(GATE, rail, GATE+math.remainder(gate-GATE, TAU), rail)
        inner.append(join(stem(1, rail), arc))
    return outer, inner


def short_fill_approaches(geometry, slot, gate_paths, groove, clearance):
    """Pick a safe entry at each leaf. Crossing a neighbor on the hanging rail can damage its picture."""
    from check_ring_scene import travel
    approaches = {}
    for side, paths in zip(("left", "right"), zip(*gate_paths)):
        safe = [p for p in paths if keeps_other_places(p.round(5), geometry, slot, groove, clearance)]
        if safe:
            approaches[side] = pack_path(min(safe, key=lambda p: travel(p)[-1]))
    return approaches


def guest_additions(geometry, slot, pitch, groove, excursions, place, margin, clearance):
    """Walk the existing base from its rail to the joint, add the detail, and retrace the approach."""
    from check_ring_scene import travel
    from guest_reveal import eligible_sources
    if not place:
        return {}
    gate_paths = guest_gate_paths(geometry, slot, place)
    approaches = [p for pair in gate_paths for p in pair if keeps_other_places(p, geometry, slot, groove, clearance)]
    if not approaches:
        return {}
    targets = {key: excursions[key] for key in ADDITIONS}
    # A subsequent change must be able to clear the whole decorated outline and hanger.
    erasable = eligible_sources(targets, geometry, slot, pitch, groove, place, margin)
    angle = geometry["angles"][slot]
    result = {}
    for target in erasable:
        _, base, compact = ADDITIONS[target]
        original = motif(base)
        callback = detail_style(target, original, geometry["center"], geometry["scale"],
                                geometry.get("faceEdge") and geometry.get("refitted"))
        idx, detail = callback(original)
        if (not np.array_equal(detail[0], original[idx]) or not np.array_equal(detail[0], detail[-1]) or
                not np.isfinite(detail).all() or (callback is compact and np.linalg.norm(detail,axis=1).max() > 1.000001)):
            raise ValueError(f"{target} does not return to its base inside the guest place")
        xy = thrcommon.rotate_xy(detail, angle-GATE) if geometry.get("faceEdge") else detail
        xy = geometry["center"]*np.array([math.cos(angle),math.sin(angle)]) + geometry["scale"]*xy
        art = guest_scene.polar(xy)
        base_path = thrcommon.unpack_path(excursions[base])
        point = np.array([angle+math.remainder(art[0,0]-angle, TAU), art[0,1]])
        anchor = np.argmin(np.linalg.norm(base_path-point,axis=1))
        if np.linalg.norm(base_path[anchor]-point) > 2e-8:
            raise ValueError(f"{target} joint is absent from its signed base")
        approach = detail_approach(base_path, anchor, approaches)
        path = join(approach, art, approach[::-1])
        if not keeps_other_places(path.round(5), geometry, slot, groove, clearance):
            continue
        run = travel(art)
        cut = len(approach)-1+int(np.searchsorted(run, run[-1]/2))
        result.setdefault(base,{})[target] = dict(files=signed_guest_files(path), progressIndex=cut)
    return result


def guest_reveal_targets(geometry, slot, pitch, groove, excursions, place, targets, margin, clearance):
    from guest_reveal import eligible_sources, plan_acoustic_guitar, plan_far_seat, plan_open_book, plan_target

    if not place:
        return {}

    sources = eligible_sources(excursions, geometry, slot, pitch, groove, place, margin)
    result = {}
    if slot == 2:
        # A fine garden offers the detailed icons by default. Guests may
        # still ask for the open book, compact gable or acoustic guitar.
        targets = dict.fromkeys([*targets, *SMALL_GUEST_STYLES.values()])
    staged = {
        "books_open": (plan_open_book, ("Lower pages", "Spine and folded corner")),
        "guitar_silhouette": (plan_acoustic_guitar, ("Curves of the guitar body", "Sound hole and first fret")),
    }
    for target in targets:
        allowed = [source for source in sources if source != target]
        if not allowed:
            continue
        # Every source uses the same underlying spiral. Only the new engraving
        # determines where the ball can leave the spiral and show a partial picture.
        args = (geometry, slot, pitch, groove, excursions[target], place)
        if slot == 2:
            trip = plan_far_seat(geometry, pitch, groove, target, excursions[target], place, margin=margin)
        else:
            trip = plan_target(*args, margin=margin, grow_from_base=target == "pumpkin_ribbed")
        if trip is None:
            continue
        path, progress = trip
        if not keeps_other_places(path, geometry, slot, groove, clearance):
            continue
        record = {"from": allowed, "files": signed_guest_files(path), "progressIndex": progress}
        if slot != 2 and target in staged:
            plan, labels = staged[target]
            visits = plan(*args, margin=margin)
            if visits is not None and keeps_other_places(visits[0], geometry, slot, groove, clearance):
                route, first, second = visits
                # A guest who already previewed the old drawing can send the exact
                # files they saw. The new preview offers both visits to the picture.
                record["previousFilesHash"] = thrcommon.motion_files_hash(record["files"])
                record.update(files=signed_guest_files(route), progressIndex=second,
                              progressMoments=[dict(label=label, endIndex=end)
                                               for label, end in zip(labels, (first, second))])
        result[target] = record
    return result


def open_book_to_guitar(geometry, slot, pitch, groove, excursions, place, margin, clearance):
    from guest_reveal import plan_acoustic_guitar
    if slot != 1 or not place or "books_open" not in excursions or "guitar_silhouette" not in excursions:
        return {}
    trip = plan_acoustic_guitar(geometry, slot, pitch, groove, excursions["guitar_silhouette"],
                               place, margin=margin, old_book=excursions["books_open"])
    if trip is None or not keeps_other_places(trip[0].round(5), geometry, slot, groove, clearance):
        return {}
    route, body, soundhole = trip
    moments = [{"label":"Curves of the guitar body", "endIndex":body},
               {"label":"Sound hole and first fret", "endIndex":soundhole}]
    record = {"files":signed_guest_files(route), "progressIndex":soundhole, "progressMoments":moments}
    return {"books_open":{"guitar_silhouette":record}}


def guest_catalog(low, high, transit, clear, pitch=None, groove=None, *, open_guests=False, face_edge=False,
                  clearance=None, margin=0):
    geometry = guest_geometry(low, high, face_edge, clearance=clearance, groove=groove or 0)
    preferred = guest_styles(geometry, groove)
    fixed = guest_ornaments(low, high, geometry["rail"])
    # A replacement always restores this ring's stretch of the shared stem.
    fixed[-1] = join(fixed[-1], stem(high, low), stem(low, high))
    excursions = []
    for slot in range(len(SLOT_TWELFTHS)):
        paths = {}
        for subject in (*SUBJECTS, OPEN_PLACE):
            route = guest_excursion(subject, slot, geometry)
            if not np.isfinite(route).all() or route[:, 1].min() < low or route[:, 1].max() > high:
                raise ValueError(f"Guest subject {subject} escaped the middle ring")
            paths[subject] = pack_path(route)
        excursions.append(paths)
    geometry["gates"] = [[GATE + TAU * (i - 1) / 12, GATE + TAU * (i + 1) / 12]
                         for i in SLOT_TWELFTHS]
    places = ([guest_place_paths(geometry, slot, pitch, groove) for slot in range(len(SLOT_TWELFTHS))]
              if pitch is not None and groove is not None else [])
    tours = {}
    if places and face_edge and clearance is not None:
        tours = guest_fill_tours(geometry, places, groove, clearance)
        targets = [preferred.get(family, family) for family in ("guitar", "books", "temple")]
        # An earlier phone can still have a signed request for the original phage.
        targets.extend(("phage", "phage_faceted", "pumpkin_ribbed"))
        for slot, place in enumerate(places):
            if not place:
                continue
            reveals = guest_reveal_targets(geometry, slot, pitch, groove, excursions[slot], place,
                                           targets, margin, clearance)
            if reveals:
                place["revealTargets"] = reveals
            book_guitar = open_book_to_guitar(geometry, slot, pitch, groove, excursions[slot], place, margin, clearance)
            if book_guitar:
                place["reveals"] = book_guitar
            gate_paths = guest_gate_paths(geometry, slot, place)
            approaches = short_fill_approaches(geometry, slot, gate_paths, groove, clearance)
            if approaches:
                place["shortFill"] = approaches
            additions = guest_additions(geometry, slot, pitch, groove, excursions[slot], place, margin, clearance)
            if additions:
                place["additions"] = additions
    return dict(version=1, slots=guest_scene.NAMES, openSubject=OPEN_PLACE,
                defaults=guest_subjects(preferred, open_guests),
                **({"preferredSubjects": preferred} if preferred else {}),
                styles=SMALL_GUEST_STYLES, librarySubjects=[*LIBRARY_MOTIFS, "pineapple_with_ring", "rolling_pin"],
                subjects=SUBJECTS, order=TRAVEL_ORDER, geometry=geometry,
                fixed=[pack_path(path) for path in fixed], excursions=excursions,
                transit=pack_path(transit), erase=pack_path(clear),
                file_limit=thrcommon.MAX_POINTS - 2, **({"places": places} if any(places) else {}),
                **({"fillTours": tours} if tours else {}))


def cubic_path(start, *sections):
    """Sample joined cubic Bézier curves from their two handles and end point."""
    t = np.linspace(0, 1, 13)[1:, None]
    path = [np.array([start], dtype=float)]
    for handle1, handle2, end in sections:
        a = path[-1][-1]
        b, c, d = np.asarray([handle1, handle2, end])
        path.append((1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t**2*c + t**3*d)
    return np.vstack(path)


def thai_roof_peak(_sector=0):
    """A triangular pediment beneath two flared roof tiers and a swept finial."""
    gap = cubic_path((-1,.13),
                     ((-.89,.13), (-.81,.142), (-.738,.303)),
                     ((-.729,.190), (-.679,.112), (-.592,.12)))
    lower = cubic_path((-.592,.12), ((-.49,.15), (-.378,.299), (-.298,.411)))
    upper = cubic_path((-.298,.411),
                       ((-.388,.397), (-.459,.479), (-.476,.58)),
                       ((-.399,.496), (-.344,.456), (-.263,.504)),
                       ((-.15,.562), (-.069,.69), (0,.805)))
    finial = cubic_path((0,.805),
                        ((-.014,.875), (.022,.939), (.082,.975)),
                        ((.053,.897), (.08,.858), (0,.805)))
    fascia = cubic_path((-.592,.12), ((-.471,.12), (-.367,.158), (-.265,.252)))
    pediment = cubic_path((-.265,.252),
                          ((-.173,.353), (-.071,.522), (0,.65)),
                          ((.071,.522), (.173,.353), (.265,.252)))
    sill = cubic_path((-.265,.252), ((-.161,.245), (.161,.245), (.265,.252)))
    # Trace the open triangular panel, climb the left eaves, and descend
    # the matching right eaves. Short trips to the fascia retrace its groove.
    mirror = np.array([-1, 1])
    return np.vstack((gap, fascia[1:], pediment[1:], sill[-2::-1], fascia[-2::-1],
                      lower[1:], upper[1:], finial[1:], upper[-2::-1]*mirror,
                      lower[-2::-1]*mirror, fascia[1:]*mirror, fascia[-2::-1]*mirror,
                      gap[-2::-1]*mirror))


def lotus_bud(_sector=0):
    """Three petals share a base, with two open folds and a slightly leaning tip."""
    root, left, right = (0,.16), (-.19,.49), (.19,.50)
    stem_into_bud = cubic_path((-1,.096), ((-.66,.096), (-.24,.045), root))
    outline = cubic_path(root,
                         ((-.21,.205), (-.348,.32), (-.395,.61)),
                         ((-.329,.60), (-.247,.565), left),
                         ((-.18,.64), (-.084,.755), (.040,.915)),
                         ((.095,.775), (.20,.71), right),
                         ((.24,.57), (.33,.64), (.395,.66)),
                         ((.365,.40), (.234,.205), root))
    left_fold = cubic_path(root, ((-.085,.257), (-.18,.35), left))
    right_fold = cubic_path(root, ((.118,.235), (.18,.347), right))
    return np.vstack((stem_into_bud, outline[1:], left_fold[1:], left_fold[-2::-1],
                      right_fold[1:], right_fold[-2::-1], stem_into_bud[-2::-1]*[-1, 1]))


GUEST_BORDERS = {2: (thai_roof_peak, 10), 3: (lotus_bud, 11), 4: (autumn_leaf, 10)}


def sector_shapes(ornament, count):
    """Yield the tangent and depth coordinates for each section of a continuous border."""
    if not isinstance(count, (int, np.integer)) or count < 1:
        raise ValueError("A border needs at least one section.")
    edge_depth = None
    for index in range(count):
        path = np.asarray(ornament(index) if callable(ornament) else ornament)
        if path.ndim != 2 or path.shape[1] != 2 or len(path) < 2 or not np.isfinite(path).all():
            raise ValueError("A border section needs a finite two-dimensional path.")
        x, depth = path.T
        if not (np.all(abs(x) <= 1) and np.all((0 <= depth) & (depth <= 1))
                and x[0] == -1 and x[-1] == 1 and depth[0] == depth[-1]
                and (edge_depth is None or depth[0] == edge_depth)):
            raise ValueError("The ornament must stay inside its section and meet the adjoining stems.")
        edge_depth = depth[-1]
        yield x, depth


def ornament_border(low, high, ornament, count):
    # x runs from -1 to +1 across a sector. Depth points toward the center,
    # so each guest sees the roof or the flower upright from their side.
    parts = []
    for index, (x, depth) in enumerate(sector_shapes(ornament, count)):
        radius = high - (high-low)*depth
        if not parts:
            parts.append(stem(high, radius[0]))
        angle = GATE + (TAU/count)*(index + .5 + x/2)
        parts.append(np.column_stack((angle, radius)))
    parts.append(stem(radius[-1], high))
    return join(*parts)


def frame_arcs(left, right, start, end, count):
    """Brush a narrow strip beside a frame, beginning on its right edge."""
    radii = np.linspace(start, end, count)
    parts = []
    for index, radius in enumerate(radii):
        a, b = (right, left) if index % 2 == 0 else (left, right)
        if index:
            parts.append(line(a, radii[index-1], a, radius))
        parts.append(line(a, radius, b, radius))
    return parts


def fluted_sector(low, high, pitch, groove, left, right, *, smooth_edges=False):
    """Clear one wedge and finish its edges, returning to its outer left corner."""
    # At the rim the lanes have their widest spacing. A slightly closer rake
    # keeps the fluting quiet between ornaments, including on a narrower band.
    spacing = min(pitch, (.62 if smooth_edges else .72) * groove)
    lanes = 2 * math.ceil((right-left) * high / (2 * spacing))
    step = (right-left) / lanes
    if smooth_edges:
        strip = min(2.2 * groove, .19 * (high-low))
        inset = .47 * strip
        bend = min(.42 * step * high, .38 * inset)
    else:
        inset = min(spacing, (high-low) / 8)
        bend = min(.43 * step * high, .5 * inset)
    inner, outer = low+inset, high-inset
    if smooth_edges:
        edge_spacing = min(pitch, .38 * groove)
        # Even arcs finish at the right for the last outward lane. Odd arcs
        # finish at the left so the leaf can grow directly from its twig.
        inner_count = 2 * math.ceil((strip / edge_spacing + 1) / 2)
        outer_count = 2 * math.ceil(strip / (2 * edge_spacing)) + 1
        inner_frame = [line(right, inner, right, low+strip),
                       *frame_arcs(left, right, low+strip, low, inner_count), line(right, low, right, inner)]
        outer_frame = [line(right, outer, right, high-strip),
                       *frame_arcs(left, right, high-strip, high, outer_count)]
    else:
        inner_frame = [line(right, inner, left, inner), line(left, inner, left, low),
                       line(left, low, right, low), line(right, low, right, inner)]
        middle = (outer+high)/2
        outer_frame = [line(right, outer, left, outer), line(left, outer, left, middle),
                       line(left, middle, right, middle), line(right, middle, right, high),
                       line(right, high, left, high)]
    turn = np.linspace(0, math.pi, 7)
    # Center each lane in its strip so both sector edges are already wiped
    # before the ornament is cut, independently of either neighboring sector.
    parts = [line(left, high, left, outer), line(left, outer, left+step/2, outer)]
    for index in range(lanes):
        angle = left + (index+.5)*step
        inward = index % 2 == 0
        start, stop = (outer, inner) if inward else (inner, outer)
        parts.append(line(angle, start, angle, stop))
        if index == lanes-1:
            break
        if index == lanes-2:
            # Finish the inner frame on the last inward turn. The next outward
            # lane carries the ball back across the band on its normal track.
            parts.extend((line(angle, inner, right, inner), *inner_frame, line(right, inner, angle+step, inner)))
        else:
            radius = stop + (-bend if inward else bend) * np.sin(turn)
            parts.append(np.column_stack((angle + step*(1-np.cos(turn))/2, radius)))
    parts.extend((line(right-step/2, outer, right, outer), *outer_frame))
    return join(*parts)


def progressive_border(low, high, pitch, groove, ornament, count, *, smooth_edges=False, art_low=None):
    """Clear and draw each ornament in order. Return the body and its completion points."""
    if not (0 < low < high <= 1 and 0 < pitch <= groove):
        raise ValueError("A progressive border needs a bounded ring and an erase pitch within the groove width.")
    art_low = low if art_low is None else art_low
    parts, finished = [], []
    endpoint = 0
    for index, (x, depth) in enumerate(sector_shapes(ornament, count)):
        radius = high - (high-art_low)*depth
        left = GATE + TAU*index/count
        right = GATE + TAU*(index+1)/count
        erase_sector = fluted_sector(low, high, pitch, groove, left, right, smooth_edges=smooth_edges)
        art = np.column_stack((left + (right-left)*(1+x)/2, radius))
        sector = join(erase_sector, line(left, high, left, radius[0]), art)
        parts.append(sector)
        endpoint += len(sector)-1
        finished.append(endpoint)
        leave = line(right, radius[-1], right, high)
        parts.append(leave)
        endpoint += len(leave)-1
    return join(*parts, stem(high, low), stem(low, high)), finished


def border_band(low, high, variant):
    """Draw one complete large-table border and return to the six-o'clock rim."""
    if variant in GUEST_BORDERS:
        ornament, count = GUEST_BORDERS[variant]
        return ornament_border(low, high, ornament, count)
    span=high-low
    center=low+.50*span
    parts=[stem(high,center)]
    if variant:
        u=np.linspace(0,TAU,1201)
        for side in (-1,1):
            wave=.29*np.sin(12*u) + side*.12*np.sin(6*u)
            parts.append(np.column_stack((GATE+u, center+span*wave)))
    else:
        def stalk(a):
            return center+.066*span*np.sin(12*(a-GATE))
        cursor=GATE
        for index in range(14):
            a=GATE+(index+.28)*TAU/14
            u=np.linspace(cursor,a,28)
            parts.append(np.column_stack((u,stalk(u))))
            for side in (-1,1):
                # Each pair grows from one node on the stem. The midrib
                # runs two thirds of the way along the blade and retraces.
                r=stalk(a)
                tip=r+side*.35*span
                lean=.157
                blade=leaf(a,r,tip,lean,.064)
                t=np.linspace(0,.71,19)
                vein=np.column_stack((a+lean*t+.28*lean*np.sin(np.pi*t),r+(tip-r)*t))
                parts.extend([blade,vein,vein[::-1]])
            cursor=a
        u=np.linspace(cursor,GATE+TAU,15)
        parts.append(np.column_stack((u,stalk(u))))
    parts.append(stem(center,high))
    return join(*parts)


DESIGNS = {
    "center": (flower, ("Lotus", "Sunflower")),
    "middle": (guest_band, ("Phage, books and Thai rooftop", "Guitar, books and Thai rooftop")),
    "outer": (border_band, ("Wheat garland", "Crossing tides", "Thai roof peaks", "Lotus buds", "Autumn leaves")),
}


def mini_blossom(low, high, alternate):
    """A single six- or five-petal outline, entered at its southern petal."""
    count = 5 if alternate else 6
    u = np.linspace(0, TAU, count * 144 + 1)
    radius = high * (.36 + .55 * (.5 + .5 * np.cos(count * u)) ** .83)
    outline = np.column_stack((GATE + u, radius))
    valley = 72  # Halfway around the first petal, the closest point to the seed.
    angle = outline[valley, 0]
    seed = .20 * high
    collar = line(angle, radius[valley], angle, seed)
    return join(stem(high, radius[0]), outline[:valley+1], collar, line(angle, seed, angle+TAU, seed),
                collar[::-1], outline[valley:], stem(radius[0], high))


def mini_border(low, high, shells):
    """Single-groove shell arches or a pair of waves crossing ten times."""
    width = high - low
    u = np.linspace(0, TAU, 1261)
    if shells:
        rail = high - .08 * width
        lobes = rail - .78 * width * abs(np.sin(5*u)) ** 1.10
        return join(stem(high, rail), np.column_stack((GATE + u, lobes)),
                    line(GATE, rail, GATE + TAU, rail), stem(rail, high))
    middle = (low + high) / 2
    wave = .43 * width * np.sin(5*u)
    return join(stem(high, middle), np.column_stack((GATE + u, middle + wave)),
                np.column_stack((GATE + u, middle - wave)), stem(middle, high))


MINI_DESIGNS = {"center": (mini_blossom, ("Anemone", "Five-petal bloom")),
                "outer": (mini_border, ("Open ribbon", "Shell arches"))}


def file_parts(stemname, path):
    limit = thrcommon.MAX_POINTS-2
    for n, start in enumerate(range(0,len(path)-1,limit-1), start=1):
        yield f"{stemname}-{n}.thr", path[start:start+limit]


def write_parts(directory, stemname, path):
    names=[]
    for name, part in file_parts(stemname, path):
        thrcommon.write_thr(directory/name, part)
        names.append(name)
    return names


def coords(path):
    return np.asarray(path).round(7).tolist()


def build(out, radius_mm, groove_mm, margin_mm, pitch_mm, layout="garden", *, open_guests=False,
          face_edge=False, guest_pitch_mm=None, measured=False):
    """Use measured guest clearances for new dimensions or an explicit fit of the original 450/5/2.5 profile."""
    return _build(out, radius_mm, groove_mm, margin_mm, pitch_mm, layout, False,
                  open_guests=open_guests, face_edge=face_edge, guest_pitch_mm=guest_pitch_mm, measured=measured)


def build_mini_portrait(out):
    """114 mm working radius, 5 mm furrow and a 2 mm tracking allowance."""
    return _build(out, 114, 5, 2, 3.8, "portrait", mini_portrait=True)


def _build(out, radius_mm, groove_mm, margin_mm, pitch_mm, layout, mini_portrait, *, open_guests=False,
           face_edge=False, guest_pitch_mm=None, measured=False):
    if layout not in LAYOUTS:
        raise ValueError(f"Unknown ring layout: {layout}")
    if open_guests and layout != 'garden':
        raise ValueError('Open guest places require the three-zone garden.')
    if face_edge and layout != 'garden':
        raise ValueError('Facing the nearest guest requires a guest ring.')
    if guest_pitch_mm is not None and layout != 'garden':
        raise ValueError('Guest groove spacing requires a guest ring.')
    bands = MINI_BANDS if mini_portrait else LAYOUTS[layout]
    designs = MINI_DESIGNS if mini_portrait else DESIGNS
    dimensions=[radius_mm,groove_mm,margin_mm,pitch_mm]
    if not all(math.isfinite(x) for x in dimensions) or min(radius_mm,groove_mm,pitch_mm)<=0 or margin_mm<0:
        raise ValueError("Use positive finite radius, groove width, and pitch, and a nonnegative tracking margin.")
    groove,margin,pitch=np.array([groove_mm,margin_mm,pitch_mm])/radius_mm
    guest_pitch = pitch if guest_pitch_mm is None else guest_pitch_mm/radius_mm
    guard=groove/2+margin
    if 4*guard >= min(hi-lo for lo,hi in bands.values()):
        raise ValueError("Groove width and tracking margin leave too little room for this layout.")
    if not all(groove*.20 <= spacing <= groove for spacing in (pitch, guest_pitch)):
        raise ValueError("Choose an erase pitch between one fifth and one full groove width.")
    out.mkdir(parents=True,exist_ok=True)
    setup=[]
    manifest=dict(units="Theta in cumulative radians counterclockwise from +x, rho in working radii, y up.",
                  dock=list(DOCK), assumed_working_radius_mm=radius_mm,
                  groove_width=groove,tracking_margin=margin,erase_pitch=pitch,
                  starting_bed="Prepared flat sand with the ball docked at six o'clock.",
                  zones={})
    if layout != "garden":
        manifest["layout"] = layout
    if mini_portrait:
        manifest["prepared_erase_pitch"] = MINI_PREPARED_PITCH
        manifest["starting_bed"] = "Whole table uniformly cleared at pitch 0.020. Ball on the six-o’clock rim dock."
    clearance = None
    fitted = measured or (radius_mm, groove_mm, margin_mm) != (450, 5, 2.5)
    if layout == "garden" and fitted:
        # Each pass may be displaced toward the other by the stated tracking
        # margin. A return to the same nominal rail does not cancel either error.
        manifest["guest_clearance_mm"] = GUEST_SAND_CLEARANCE * groove_mm + 2 * margin_mm
        clearance = manifest["guest_clearance_mm"] / radius_mm
    for name,(r0,r1) in bands.items():
        low=r0+guard if r0 else 0
        high=r1-guard
        approach=stem(1,high)
        zone_pitch = guest_pitch if name == "middle" else pitch
        if mini_portrait and name == "outer":
            zone_pitch = MINI_PREPARED_PITCH
        large_center = name == "center" and not mini_portrait
        clear = outward_center_erase(high, zone_pitch) if large_center else erase(low, high, zone_pitch)
        if name == "middle":
            manifest["guest_plan"] = guest_catalog(low, high, approach, clear, zone_pitch, groove,
                                                  open_guests=open_guests, face_edge=face_edge,
                                                  clearance=clearance, margin=margin)
        make,labels=designs[name]
        empty_middle = name == 'middle' and open_guests
        if empty_middle:
            labels = ("Open guest places", *labels[1:])
        variants=[]
        for ix,label in enumerate(labels):
            ornament = GUEST_BORDERS.get(ix) if name == "outer" and not mini_portrait else None
            art_low = low
            if ornament and fitted:
                # The two safe bounds already separate adjacent path centers
                # by one groove plus both tracking margins. Reserve the rest
                # of the fitted clearance when an ornament reaches into it.
                inset = (GUEST_SAND_CLEARANCE - 1) * groove
                depth = max(d.max() for _, d in sector_shapes(*ornament))
                if (1 - depth) * (high - low) < inset:
                    art_low += inset
            if name == 'middle':
                path = guest_band(low, high, ix, open_places=empty_middle and ix == 0,
                                  face_edge=face_edge, clearance=clearance, groove=groove)
            elif large_center:
                path = make(low, high, ix, groove=groove)
            else:
                path = make(art_low, high, ix)
            # A center drawing can leave at its own perimeter: no other zone
            # needs a stem through the petals or the middle of a portrait.
            if name != "center":
                path=join(path,stem(high,low),stem(low,high))
            for active in (clear,path):
                if not np.isfinite(active).all() or active[:,1].min()<low-1e-7 or active[:,1].max()>high+1e-7:
                    raise ValueError(f"Path escaped {name} band")
            route=join(approach,clear,path,approach[::-1])
            variants.append(dict(name=label,path=coords(path),replace=write_parts(out,f"replace-{name}-{ix}",route)))
            if ornament:
                shape, count = ornament
                reveal, finished = progressive_border(low, high, zone_pitch, groove, shape, count,
                                                      smooth_edges=shape is autumn_leaf, art_low=art_low)
                replacement = join(approach, reveal, approach[::-1])
                variants[-1]["reveal"] = dict(path=coords(reveal), finished=finished,
                                              replace=write_parts(out, f"reveal-{name}-{ix}", replacement))
            if ix == 0:
                setup.append(join(approach, path, approach[::-1]) if mini_portrait else route)
        manifest["zones"][name]=dict(bounds=[r0,r1],safe_bounds=[low,high],
                                     transit=coords(approach),erase=coords(clear),variants=variants)
        if zone_pitch != pitch:
            manifest["zones"][name]["erase_pitch"] = zone_pitch
        if name == "center":
            # Closely overlapping turns give small portrait details a quieter bed.
            photo_clear = outward_center_erase(high, min(pitch, .4 * groove))
            manifest["zones"][name]["photoErase"] = pack_path(photo_clear)
    manifest["setup"]=write_parts(out,"setup",join(*setup))
    (out/"scene.json").write_text(json.dumps(manifest,separators=(",",":"),allow_nan=False)+"\n")


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out",type=Path,required=True)
    modes=cli.add_mutually_exclusive_group()
    modes.add_argument("--layout",choices=LAYOUTS,default="garden",
                       help="garden has a middle ring of guest drawings; portrait gives that space to the center")
    modes.add_argument("--mini-portrait", action="store_true", help="Mini flowers and border on uniformly fine-cleared sand")
    cli.add_argument("--open-guests", action="store_true", help="start the garden with three open places for live requests")
    cli.add_argument("--face-guests", action="store_true", help="face each guest drawing toward the nearest table edge")
    cli.add_argument("--radius-mm",type=float,help="assumed usable drawing radius (default 450)")
    cli.add_argument("--groove-mm",type=float,help="assumed full width of sand disturbed by one pass (default 5)")
    cli.add_argument("--margin-mm",type=float,help="maximum tracking error on each pass, in mm (default 2.5); specifying it fits guest places even at the original 450/5 dimensions")
    cli.add_argument("--pitch-mm",type=float,help="centerline spacing of the spiral erase (default 4)")
    cli.add_argument("--guest-pitch-mm",type=float,help="spiral spacing for the guest ring, including later changes (default: use --pitch-mm)")
    opt=cli.parse_args()
    if opt.open_guests and (opt.mini_portrait or opt.layout != "garden"):
        cli.error("--open-guests requires a three-zone garden")
    if opt.face_guests and (opt.mini_portrait or opt.layout != "garden"):
        cli.error("--face-guests requires a three-zone garden")
    if opt.guest_pitch_mm is not None and (opt.mini_portrait or opt.layout != "garden"):
        cli.error("--guest-pitch-mm requires a three-zone garden")
    dimensions=(opt.radius_mm, opt.groove_mm, opt.margin_mm, opt.pitch_mm)
    if opt.mini_portrait:
        if any(value is not None for value in dimensions):
            cli.error("--mini-portrait uses the Mini's fixed dimensions")
        build_mini_portrait(opt.out)
    else:
        values=[fallback if value is None else value for value,fallback in zip(dimensions,(450,5,2.5,4))]
        build(opt.out,*values,layout=opt.layout,open_guests=opt.open_guests,
              face_edge=opt.face_guests,guest_pitch_mm=opt.guest_pitch_mm, measured=opt.margin_mm is not None)
