"""Make a lasting part of a new guest picture visible while its old picture is cleared."""

import math
from dataclasses import dataclass

import numpy as np

from check_ring_scene import travel
from thrcommon import unpack_path


_FAR_EXTENT = math.radians(83)
# Distance inward from the guest's center, in picture radii. Choose a
# crossing at the pages, feet, lower lobes, sound hole or curled eaves.
# None takes the last lane crossing the artwork to finish its upper detail.
_FAR_STAGES = {
    'books_open': (-.09, None),
    'books': (.12, None),
    'phage': (.05, None),
    'phage_faceted': (.05, None),
    'pumpkin_ribbed': (-.02, None),
    'guitar_silhouette': (.33, None),
    'guitar': (.22, None),
    'temple_gable': (.19, .74),
    'temple': (.19, None),
}


def _path(data):
    if isinstance(data, str):
        return unpack_path(data)
    return np.asarray(data, dtype=float)


def _picture(excursion, rail, workspace):
    """Find the actual excursion from the rail, including its short hanging line."""
    try:
        excursion = _path(excursion)
    except (TypeError, ValueError):
        return None
    if excursion.ndim != 2 or excursion.shape[1] != 2 or not np.isfinite(excursion).all():
        return None
    off_rail = np.flatnonzero(abs(excursion[:, 1] - rail) > 1e-7)
    if not len(off_rail) or off_rail[0] == 0 or off_rail[-1] == len(excursion)-1:
        return None
    entry, leave = off_rail[0]-1, off_rail[-1]+1
    body = excursion[entry:leave+1]
    lo, hi = workspace['radialBounds']
    left, right = workspace['limits']
    if not np.isfinite([lo, hi, left, right]).all() or not (0 <= lo < hi <= 1 and left < right):
        return None
    theta = (left+right)/2 + np.arctan2(np.sin(body[:, 0]-(left+right)/2), np.cos(body[:, 0]-(left+right)/2))
    if (body[:, 1].min() < lo-1e-7 or body[:, 1].max() > hi+1e-7 or
            theta.min() < left-1e-7 or theta.max() > right+1e-7 or
            abs(theta[0]-theta[-1]) > 1e-6):
        return None
    return excursion, entry, leave


@dataclass(frozen=True)
class _EraseRows:
    low: float
    high: float
    angle: float
    gate: float | None
    sign: int
    turns: int
    step: float
    start_extent: float

    def radius(self, row, theta):
        from ring_scene import GATE, TAU
        return self.high-self.step*(row+(theta-GATE)/TAU)

    def tip(self, row):
        # Keep the far turnaround of each ordinary spiral row. Joining tips
        # directly would leave visible teeth between the picture and its neighbor.
        fraction = row/(self.turns-1)
        mix = np.log(self.high/(self.high-fraction*(self.high-self.low)))/math.log(self.high/self.low)
        return self.angle+self.sign*(self.start_extent+(_FAR_EXTENT-self.start_extent)*mix)


def _erase_rows(geometry, slot, pitch, groove, margin):
    from ring_scene import GATE, TAU
    if slot not in (0, 1, 2) or not np.isfinite([pitch, groove, margin]).all() or margin < 0 or not 0 < pitch <= .65*groove:
        return None
    low, high = geometry['bounds']
    angle, center, scale = geometry['angles'][slot], geometry['center'], geometry['scale']
    if not np.isfinite([low, high, angle, center, scale, geometry['rail']]).all() or not 0 < low < high <= 1:
        return None
    if not low <= geometry['rail'] <= high or not 0 < scale < center or not center <= 1:
        return None
    ratio = (scale+1.2*groove)/center
    sign = -1 if slot == 0 else 1
    gate = None if slot == 2 else GATE + (TAU if slot == 0 else 0)
    far = angle+sign*_FAR_EXTENT
    # The rows fan outward within one revolution, from the six-o'clock stem.
    near = 2*angle-far if gate is None else gate
    if (ratio > math.sin(_FAR_EXTENT) or sign*(angle-near) < 0 or
            not GATE <= far <= GATE+TAU or not GATE <= near <= GATE+TAU):
        return None
    count = (high-low)/pitch
    if not math.isfinite(count):
        return None
    turns = math.ceil(count)
    if turns < 4:
        return None
    return _EraseRows(low, high, angle, gate, sign, turns, (high-low)/turns, math.asin(ratio))


def _sweeps_picture(rows, picture, pad):
    """Prove the expanded old engraving fits between complete clearing rows."""
    from ring_scene import TAU
    path, start, end = picture
    body = path[start:end+1]
    r = body[:, 1]
    if r.min()-pad < rows.low+rows.step or r.max()+pad > rows.high-rows.step or r.min() <= pad:
        return False
    # Align the whole polar walk at once. A segment that makes an extra turn
    # passes through other sectors, even when its two endpoints coincide.
    theta = body[:, 0] + TAU*round((rows.angle-body[0, 0])/TAU)
    spread = np.arcsin(pad/np.minimum(r[:-1], r[1:]))
    lower = np.minimum(theta[:-1], theta[1:])-spread
    upper = np.maximum(theta[:-1], theta[1:])+spread
    outer = np.maximum(r[:-1], r[1:])+pad
    # This is the earliest (narrowest) row bracketing any point of the
    # padded segment. Every later row reaches at least as far around the ring.
    earliest = np.clip(np.floor((rows.radius(0,upper)-outer)/rows.step-1e-9), 0, rows.turns-1)
    far = rows.tip(earliest)
    near = 2*rows.angle-far if rows.gate is None else rows.gate
    return bool(np.all(lower >= np.minimum(near,far)) and np.all(upper <= np.maximum(near,far)))


def eligible_sources(excursions, geometry, slot, pitch, groove, place, margin=0):
    """Stock artwork whose furrow and displaced sand the signed rows cover."""
    rows = _erase_rows(geometry, slot, pitch, groove, margin) if place else None
    # Rounding a source and a sweep to five decimal places in theta and rho
    # can change their relative distance by less than 2e-5 working radii.
    rounding = 2e-5
    if rows is None or rows.step/2+rounding > groove/2:
        return []
    pad = 1.15*groove + 2*margin + rounding
    allowed = []
    for key, path in excursions.items():
        picture = _picture(path, geometry['rail'], place)
        if picture is not None and _sweeps_picture(rows, picture, pad):
            allowed.append(key)
    return allowed


def plan(geometry, slot, pitch, groove, old_excursion, new_excursion, place, *, margin=0):
    """Plan a single pair of engravings, including the original phage-to-guitar study."""
    if not place or _picture(old_excursion, geometry['rail'], place) is None:
        return None
    return plan_target(geometry, slot, pitch, groove, new_excursion, place, margin=margin)


def plan_target(geometry, slot, pitch, groove, new_excursion, place, *, margin=0, grow_from_base=False):
    """Return the dock-to-dock route and progress index, or None if the new picture cannot fit.

    The two lower seats reach each spiral row along the six-o'clock stem.
    Pitch, groove and single-pass tracking margin are fractions of the working radius.
    With grow_from_base, draw only connected exposed strokes during the first visit.
    """
    from ring_scene import join

    rows = _erase_rows(geometry, slot, pitch, groove, margin) if place else None
    if rows is None or rows.gate is None:
        return None
    new = _picture(new_excursion, geometry['rail'], place)
    if new is None:
        return None
    path, entry, leave = new
    body = path[entry:leave+1]
    length = travel(body)
    if not length[-1]:
        return None

    # A later row can push sand out 1.15 grooves. Protect half a groove of
    # the earlier drawing, plus tracking error on both passes.
    clearance = 1.65*groove + 2*margin
    if grow_from_base:
        clearance += 2e-5  # round both the erase and the engraving to the export precision
    visits = {}
    for row in _checkpoints(rows):
        minimum = rows.radius(row+1, geometry['gates'][slot][0])+clearance
        safe = body[:, 1] >= minimum
        if safe.all():
            if not visits:
                return None
            visits[row] = body if grow_from_base else path
            return _finish_route(geometry, slot, rows, place, new, visits, along_rail=grow_from_base)
        if visits or not (safe[0] and safe[-1]):
            continue
        if grow_from_base:
            # At the pumpkin's widest part all five lower lobes are accessible
            # from its base. The still-buried shoulders and stalk come later.
            if minimum <= geometry['center']+.08*geometry['scale']:
                lower = _reachable_strokes(body, minimum)
                if len(lower) > 1:
                    visits[row] = lower
            continue
        starts = np.flatnonzero(safe & ~np.r_[False, safe[:-1]])
        ends = np.flatnonzero(safe & ~np.r_[safe[1:], False])
        if (length[ends]-length[starts]).sum() < .36*length[-1]:
            continue
        # Leave the longest uncleared stretch until later. Isolated features
        # like a guitar bridge are reached along the intended engraving.
        split = np.argmax(length[starts[1:]]-length[ends[:-1]])
        prefix = body[:ends[split]+1]
        suffix = body[starts[split+1]:][::-1]
        visits[row] = join(path[:entry+1], prefix, prefix[::-1], suffix, suffix[::-1], path[leave:])
    return None


def _reachable_strokes(body, minimum):
    """Trace exposed segments connected to the hanging point and return along the engraving."""
    neighbors = {}
    for start, end in zip(body, body[1:]):
        if start[1] < end[1]:
            start, end = end, start
        if start[1] < minimum:
            continue
        if end[1] < minimum:
            end = start + (end-start)*((minimum-start[1])/(end[1]-start[1]))
        a, b = tuple(start), tuple(end)
        if a != b:
            neighbors.setdefault(a, {})[b] = None
            neighbors.setdefault(b, {})[a] = None

    # Identical vertices include shared ends of lobes and deliberately retraced
    # outlines. Visiting a branch never requires crossing unmarked sand.
    return _walk_strokes(neighbors, tuple(body[0]))


def _walk_strokes(neighbors, entry):
    """Consume the connected edges and retrace each one to the entry."""
    route = [entry]
    stack = route.copy()
    while stack:
        current = stack[-1]
        if neighbors.get(current):
            other = next(iter(neighbors[current]))
            del neighbors[current][other], neighbors[other][current]
            stack.append(other)
            route.append(other)
        else:
            stack.pop()
            if stack:
                route.append(stack[-1])
    return np.asarray(route)


def _crossing_visit(rows, row, art, wipe, groove, margin, *, book_cover=None):
    """Enter a connected piece of real artwork where a clearing lane crosses it."""
    delta = art[:, 1] - rows.radius(row, art[:, 0])
    neighbors, crossings = {}, set()
    for a, b, da, db in zip(art, art[1:], delta, delta[1:]):
        if max(da, db) <= 0:
            continue
        if min(da, db) <= 0:
            # Both paths interpolate linearly in theta and radius. Two
            # traversals of the same edge must share the same clipped vertex.
            cross = np.round(a + (b-a)*(da/(da-db)), 8)
            crossings.add(tuple(cross))
            if da <= 0:
                a = cross
            else:
                b = cross
        start, end = tuple(a), tuple(b)
        if start != end:
            neighbors.setdefault(start, {})[end] = None
            neighbors.setdefault(end, {})[start] = None

    if book_cover is not None:
        # At the upper book's two right-hand junctions, visit the page edge
        # before its crossing ribbon so the V lies on top in the sand.
        for point, edges in neighbors.items():
            theta, r = point
            if len(edges) > 2 and theta > rows.angle and r*math.cos(theta-rows.angle) < book_cover:
                neighbors[point] = dict.fromkeys(reversed(edges))

    # The far seat already follows each full spiral lane and bends into the
    # next one. Search the actual stored wipe for its last visit to each
    # crossing; the short blend between lanes cannot serve as an entrance.
    on_lane = abs(wipe[:, 1] - rows.radius(row, wipe[:, 0])) <= 2e-8
    lanes = np.flatnonzero(on_lane[:-1] & on_lane[1:])
    left = np.minimum(wipe[lanes, 0], wipe[lanes+1, 0])
    right = np.maximum(wipe[lanes, 0], wipe[lanes+1, 0])
    ports = []
    for point in crossings:
        matches = lanes[(left <= point[0]+1e-8) & (point[0] <= right+1e-8)]
        if len(matches):
            ports.append((matches[-1], point))

    best, longest = None, 0
    guard = 1.65*groove + 2*margin + 2e-5
    for index, entry in sorted(ports, reverse=True):
        if not neighbors.get(entry):
            continue
        walk = _walk_strokes(neighbors, entry)
        # Favor a component with several grooves' worth of actual artwork
        # already clear of the following passes, excluding the access itself.
        safe = walk[:, 1] - rows.radius(row, walk[:, 0]) > guard
        lasting = np.diff(travel(walk))[safe[:-1] & safe[1:]].sum()/2
        if lasting > longest and lasting >= 3*groove:
            best, longest = (index, walk), lasting
    return best


def plan_far_seat(geometry, pitch, groove, target, new_excursion, place, *, margin=0):
    """Show the far guest's picture directly from crossings of its original inward spiral."""
    from ring_scene import GATE, TAU, join

    rows = _erase_rows(geometry, 2, pitch, groove, margin) if place else None
    picture = _picture(new_excursion, geometry['rail'], place) if rows else None
    if picture is None or target not in _FAR_STAGES:
        return None
    path, entry, leave = picture
    body = path[entry:leave+1]
    # The loops in the sand, without the radial hanging stroke to the rail.
    angular_edges = np.flatnonzero(abs(np.diff(body[:, 0])) > 1e-7)
    if not len(angular_edges):
        return None
    art = body[angular_edges[0]:angular_edges[-1]+2].copy()
    art[:, 0] += TAU*round((rows.angle-art[0, 0])/TAU)
    approach, wipe, recut, exit_path = (_path(place[k]) for k in ('approach','clear','recut','exit'))
    sections = [approach]
    resume, preview = 0, None
    first, second = _FAR_STAGES[target]
    # The reference artwork has just under a third of a picture radius between
    # a lasting line and the next sweep. Wait a few rows longer on coarser sand.
    first += max(0., (1.65*groove + 2*margin)/geometry['scale'] - .325)
    for depth in (first, second):
        if depth is None:
            last = math.ceil(np.max((rows.high-art[:, 1])/rows.step - (art[:, 0]-GATE)/TAU))-1
            candidates = range(last, last-4, -1)
        else:
            radius = geometry['center'] - depth*geometry['scale']
            desired = (rows.high-radius)/rows.step - (rows.angle-GATE)/TAU
            candidates = sorted(range(round(desired)-3, round(desired)+4), key=lambda k: abs(k-desired))
        book_cover = geometry['center']-.4*geometry['scale'] if target == 'books' and depth is None else None
        for row in candidates:
            if 0 <= row < rows.turns:
                visit = _crossing_visit(rows, row, art, wipe, groove, margin, book_cover=book_cover)
                if visit is not None and visit[0] >= resume:
                    break
        else:
            return None
        i, walk = visit
        # Resume on the same signed lane. Every off-lane edge belongs to the
        # final picture, including the retrace back to this point.
        sections.append(np.vstack((wipe[resume:i+1], walk, wipe[i+1])))
        if preview is None:
            preview = sum(len(part)-1 for part in sections)-1  # back at the crossing
        resume = i+1
    sections.extend((wipe[resume:], recut, path, exit_path))
    return join(*sections), preview


def _checkpoints(rows):
    return (min(k+1, rows.turns-1) for k in range(0, rows.turns, 2))


def _safe_prefix(path, minimum):
    """Clip a stroke at its first inward crossing, using the player's polar interpolation."""
    bad = np.flatnonzero(path[:, 1] < minimum)
    if not len(bad):
        return path
    i = bad[0]
    if i == 0:
        return path[:0]
    start, end = path[i-1:i+1]
    fraction = (minimum-start[1])/(end[1]-start[1])
    return np.vstack((path[:i], start+fraction*(end-start)))


def plan_open_book(geometry, slot, pitch, groove, new_excursion, place, *, margin=0):
    """Draw the page block, then the rising spine and curl, then the whole book.

    Return the signed route and inclusive end indices for the first two visits.
    A different engraving, seat orientation or insufficient space uses the caller's fallback.
    """
    from guest_book_art import engraving
    from guest_scene import polar
    from ring_scene import GATE, TAU, guest_excursion, join, line
    from thrcommon import rotate_xy

    rows = _erase_rows(geometry, slot, pitch, groove, margin) if place and geometry.get('faceEdge') else None
    if rows is None or rows.gate is None:
        return None
    rail = geometry['rail']
    new = _picture(new_excursion, rail, place)
    if new is None:
        return None
    path, entry, leave = new
    # The intermediate strokes must belong to this exact engraving, including
    # its hanging point. A saved drawing can retain an older version of the art.
    expected = guest_excursion('books_open', slot, geometry)
    if path.shape != expected.shape:
        return None
    turns = round((expected[0, 0]-path[0, 0])/TAU)
    if not np.allclose(path+[TAU*turns, 0], expected, atol=1e-7, rtol=0):
        return None
    body = path[entry:leave+1]
    left, right = geometry['gates'][slot]
    clearance = 1.65*groove + 2*margin + 2e-5  # signed export rounds both paths
    if body[:, 1].min() <= clearance:
        return None
    # A clearing segment close enough to touch the art must be in this angular
    # interval. Radius decreases to the right, so its maximum is at the left gate.
    theta = body[:, 0]+TAU*round((rows.angle-body[0, 0])/TAU)
    spread = math.asin(clearance/body[:, 1].min())
    if theta.min()-spread < left or theta.max()+spread > right:
        return None

    center = geometry['center']*np.array([math.cos(rows.angle), math.sin(rows.angle)])
    _, upright = engraving()
    strokes = {name: polar(center+geometry['scale']*rotate_xy(points, rows.angle-GATE))
               for name, points in upright.items()}
    binding = strokes['left_cover'][0]
    if abs(math.remainder(body[0, 0]-binding[0], TAU)) > 1e-7:
        return None
    attach = line(body[0, 0], rail, body[0, 0], binding[1])
    if len(body) < len(attach) or not np.allclose(body[:len(attach)], attach, atol=1e-7, rtol=0):
        return None
    lower = join(attach, strokes['left_cover'], strokes['left_pages'][::-1],
                 strokes['right_pages'], strokes['right_cover'][::-1], attach[::-1])
    diagonal = strokes['crease'][::-1]
    diagonal_length = travel(diagonal)[-1]
    lowest_cover = lower[:, 1].min()
    lowest_side = strokes['right_side'][:, 1].min()
    lowest_page = body[:, 1].min()
    visits = {}
    for row in _checkpoints(rows):
        minimum = rows.radius(row+1, left)+clearance
        if lowest_page >= minimum:
            if len(visits) != 2:
                return None
            visits[row] = body
            return _finish_route(geometry, slot, rows, place, new, visits, along_rail=True)
        if not visits and lowest_cover >= minimum:
            visits[row] = lower
        elif len(visits) == 1 and lowest_side >= minimum:
            crease = _safe_prefix(diagonal, minimum)
            # A short shelf looks like a stray line. At about one third of the
            # diagonal, the two emerging sides read as the turned corner.
            if not len(crease) or travel(crease)[-1] < .35*diagonal_length:
                continue
            side = _safe_prefix(strokes['left_edge'], minimum)
            spine = _safe_prefix(strokes['spine'], minimum)
            curl = _safe_prefix(strokes['folded_edge'][::-1], minimum)
            if any(len(piece) == 0 for piece in (side, spine, curl)):
                continue
            visits[row] = join(attach, strokes['left_cover'], side, side[::-1], strokes['left_pages'][::-1],
                               spine, spine[::-1], strokes['right_pages'], strokes['right_side'], curl, curl[::-1],
                               crease, crease[::-1], strokes['right_side'][::-1], strokes['right_cover'][::-1], attach[::-1])
    return None


def plan_acoustic_guitar(geometry, slot, pitch, groove, new_excursion, place, *, margin=0, old_book=None):
    """Show the waist, then the sound hole and fret, before the complete guitar."""
    from guest_guitar import engraving
    from ring_scene import GATE, TAU, guest_excursion, join
    from thrcommon import rotate_xy

    rows = _erase_rows(geometry, slot, pitch, groove, margin) if place and geometry.get('faceEdge') else None
    if rows is None or rows.gate is None:
        return None
    new = _picture(new_excursion, geometry['rail'], place)
    if new is None:
        return None
    path, entry, leave = new
    expected = guest_excursion('guitar_silhouette', slot, geometry)
    if (path.shape != expected.shape or
            not np.allclose(path+[TAU*round((expected[0,0]-path[0,0])/TAU), 0], expected, atol=1e-7, rtol=0)):
        return None
    body = path[entry:leave+1]
    # One genuine hanger reaches the soundboard. Keep it out of the branching
    # walk and merge equivalent vertices of retraced strokes before walking.
    # Adding a turn while joining polar segments can add a few floating bits.
    edges = np.flatnonzero(np.abs(np.diff(body[:,0])) > 1e-7)
    if not len(edges):
        return None
    attach = body[:edges[0]+1]
    outline = np.round(body[edges[0]:edges[-1]+2], 8)
    clearance = 1.65*groove + 2*margin + 2e-5
    left, right = geometry['gates'][slot]
    if body[:,1].min() <= clearance:
        return None
    spread = math.asin(clearance/body[:,1].min())
    angle = rows.angle+np.angle(np.exp(1j*(body[:,0]-rows.angle)))
    if angle.min()-spread < left or angle.max()+spread > right:
        return None

    center = geometry['center']*np.array([math.cos(rows.angle), math.sin(rows.angle)])
    _, features = engraving()
    def depths(key):
        xy = center+geometry['scale']*rotate_xy(features[key], rows.angle-GATE)
        return np.linalg.norm(xy, axis=1)

    book_edge = None
    if old_book is not None:
        old = _picture(old_book, geometry['rail'], place)
        pad = 1.15*groove + 2*margin + 2e-5
        if old is None or not _sweeps_picture(rows, old, pad):
            return None
        book = old[0][old[1]:old[2]+1]
        # Only these original spiral grooves can run through displaced book sand.
        # Allow for both signed passes at their tracking limits and a rounding error.
        book_angle = np.angle(np.exp(1j*(book[:,0]-rows.angle)))
        extent = np.max(rows.sign*book_angle) + math.asin(pad/book[:,1].min())
        # The smooth changes between adjacent grooves run under the incoming guitar.
        extent = max(extent, np.max(rows.sign*(angle-rows.angle)) + .06, .10)
        book_edge = rows.angle+rows.sign*extent

    thresholds = [depths('waists').min(), min(depths(k).min() for k in ('fret','bridge','soundhole'))]
    visits = {}
    for row in _checkpoints(rows):
        minimum = rows.radius(row+1, left)+clearance
        if len(visits) < len(thresholds):
            if minimum <= thresholds[len(visits)]:
                trace = _reachable_strokes(outline, minimum)
                visits[row] = join(attach, trace, attach[::-1])
        elif minimum <= body[:,1].min():
            visits[row] = body
            return _finish_route(geometry, slot, rows, place, new, visits, along_rail=True,
                                 follow_guitar=True, book_edge=book_edge)
    return None


def _finish_route(geometry, slot, rows, place, new, visits, *, along_rail=False, follow_guitar=False, book_edge=None):
    from ring_scene import GATE, join, line

    path, entry, leave = new
    rail, angle = geometry['rail'], rows.angle
    low, high = rows.low, rows.high
    left, right = geometry['gates'][slot]
    gate, sign = rows.gate, rows.sign
    turns, step = rows.turns, rows.step
    radius, tip = rows.radius, rows.tip
    if book_edge is not None:
        def tip(row):
            # A gradual spread avoids stacking turnaround marks in a straight
            # line beside the guitar. Keep every endpoint on its original lane.
            spread = .09*row/(turns-1)
            return gate + sign*min(sign*(rows.tip(row)-gate),sign*(book_edge-gate)+spread)

    def lane(row, a, b):
        return line(a, radius(row, a), b, radius(row, b))

    def stem(a, b):
        return line(gate, a, gate, b)

    def rim(a, r, b):
        return line(a, r, b, r)

    def visit(dock_radius, picture):
        if along_rail:
            # Return by the same hanging point. Both ends of the short approach
            # lie on lines already present in the opening garden.
            side, edge = (path[leave:][::-1], right) if slot == 0 else (path[:entry+1], left)
            incoming = join(stem(dock_radius, rail), rim(gate, rail, edge), side)
            return join(incoming, picture, incoming[::-1])
        # Enter on the shared high boundary. Returning over an arbitrary spiral
        # after adjacent turns have been cut leaves a dark arc across the bed.
        return join(stem(dock_radius, high), rim(gate, high, left), line(left, high, left, rail),
                    picture, line(right, rail, right, high), rim(right, high, gate), stem(high, dock_radius))

    # Switch rows near the picture and cross that blend again on an original
    # spiral. Both distant turnarounds are approached AND left on their own row.
    t = np.linspace(0, 1, 23)
    ease = t*t*(3-2*t)
    near = tip(0)
    if follow_guitar:
        body = path[entry:leave+1]
        bearing = body[:,0]+math.tau*round((angle-body[0,0])/math.tau)
        blend = min(.10, rows.start_extent/2)
        parts = [line(GATE, 1, GATE, high)]
    else:
        parts = [_path(place['approach']), line(left, rail, left, high), rim(left, high, gate)]
    # The final route passes from the stem to the left leaf and from the
    # right leaf back to the stem on this same outer rim. Together these
    # already retrace the old outer edge of the entire guitar clearing.
    if not follow_guitar or sign*(near-gate) > max(sign*(left-gate),sign*(right-gate)):
        parts.extend([rim(gate, high, near), rim(near, high, gate)])
    last = high
    marks = []

    for k in range(0, turns, 2):
        far = tip(k)
        parts.extend([stem(last, radius(k, gate)), lane(k, gate, far)])
        row = min(k+1, turns-1)
        if row != k:
            far_next = tip(row)
            switch = angle-sign*.10
            across = switch+sign*.14
            if follow_guitar:
                # Hide changes of groove under the future guitar wherever
                # this exact spiral row crosses its body, neck or hanging line.
                # Staying on the original spiral at the far ends keeps their
                # fine curved ridge free of an extra row of visible turn marks.
                separation = body[:,1]-radius(k,bearing)
                hits = np.flatnonzero((separation[:-1] <= 0) != (separation[1:] <= 0))
                if len(hits):
                    fraction = separation[hits]/(separation[hits]-separation[hits+1])
                    crossings = bearing[hits]+fraction*(bearing[hits+1]-bearing[hits])
                    cross = crossings[np.argmax(sign*(crossings-angle))]
                    switch, across = cross-sign*blend/2, cross+sign*blend/2
            theta = np.linspace(switch, across, len(t))
            parts.extend([lane(k, far, switch), np.column_stack([theta, radius(k, theta)-step*ease]),
                          lane(row, across, far_next), lane(row, far_next, gate)])
        else:
            parts.append(lane(k, far, gate))
        last = radius(row, gate)
        if row in visits:
            parts.append(visit(last, visits[row]))
            marks.append(sum(len(section)-1 for section in parts))
    # Restore the normal layering when the lowest rows are done. This short
    # final tracing repairs the lower outline where it meets the hanging line.
    far = tip(turns-1)
    parts.extend([stem(last, low), rim(gate, low, far), rim(far, low, gate), stem(low, high),
                  rim(gate, high, left), line(left, high, left, rail), _path(place['recut']), path,
                  _path(place['exit'])])
    route = join(*parts)
    ordinary_distance = sum(travel(p)[-1] for p in
                            [_path(place['approach']), _path(place['clear']), _path(place['recut']),
                             path, _path(place['exit'])])
    if travel(route)[-1] >= ordinary_distance:
        return None
    return (route, *marks[:-1])
