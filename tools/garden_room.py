#!/usr/bin/env python3
"""Share one generated Oasis gallery and its kept drawings on a local HTTP server."""
import argparse
import base64
from collections import OrderedDict
from concurrent.futures import Future
from contextlib import closing
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata
from urllib.parse import urlsplit

import garden_playback
import garden_portrait
from oasis_player import OasisPlayer, PlaybackError, validate_parts


MAX_BODY = 20 * 1024 * 1024
MARKER = '<meta name="oasis-room" content="./api/garden">'
PHRASE_MARKER = '<meta name="oasis-phrase" content="./api/phrase">'
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?'
MOTION_LINE = re.compile(rf'[ \t]*({NUMBER})[ \t]+({NUMBER})[ \t]*', re.ASCII)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= value.keys() <= set(required) | set(optional),
            'Unexpected or missing fields.')


def short_text(value, limit):
    return isinstance(value, str) and len(value) <= limit and not any(
        ord(ch) < 32 or 0xd800 <= ord(ch) <= 0xdfff for ch in value)


def name_key(name):
    # Match GuestArt.normalize, including its removal of English possessives.
    text = re.sub(r"['’]s\b", '', name.lower(), flags=re.ASCII)
    return ' '.join(''.join(ch if ch.isalnum() else ' ' for ch in text).split())


def active_guests(state):
    """Compare what a guest sees at each seat, including older, pre-guest-book saves."""
    book = state.get('guestBook')
    if book:
        people = {name_key(person['name']): person for person in book['people']}
        guests = [(people[key]['name'], people[key]['interest']) for key in book['active']]
    else:
        guests = [('Thomas', 'Bacteriophages'), ('Alex', 'Teaching and playing guitar'), ('Lek', 'Thailand')]
    guests = [(name, 'Teaching and playing guitar' if name_key(name) == 'alex' and interest == 'Teaching'
               else interest) for name, interest in guests]
    labels = state.get('labels', {})
    return [(guest, labels.get(subject)) for guest, subject in zip(guests, state['ids'])]


def eligible_drawing_name(key, label):
    name = ' '.join(unicodedata.normalize('NFC', label).lower().split())
    if (not re.fullmatch(r'sketch-[0-9]+', key) or name in
            ('guest sketch', 'guest drawing', 'photo drawing', 'portrait from photo') or
            (name.startswith('“') and name.endswith('”'))):
        return ''
    return name


def clean_drawing_interest(value):
    require(short_text(value, 120) and all(not 127 <= ord(ch) <= 159 for ch in value),
            'Invalid drawing interests.')
    phrases = [piece.strip() for piece in value.split(',') if piece.strip()]
    clean = ', '.join(phrases)
    require(len(phrases) <= 8 and len(clean) <= 120, 'Invalid drawing interests.')
    return clean


def interests_by_picture(state):
    # Historical and current clients may give the exact same named ink different IDs.
    index = {}
    for key, text in state.get('drawingInterests', {}).items():
        name = eligible_drawing_name(key, state['labels'][key])
        index.setdefault(name, []).append((state['custom'][key], text))
    return index


def carry_kept_drawings(previous, state):
    """Keep the room's named ink when an older phone submits only its guest-book paths."""
    if state is None:
        return
    custom, labels = state['custom'], state['labels']
    people = (state.get('guestBook') or {}).get('people', [])
    required = dict.fromkeys(key for key in [*(p['subject'] for p in people), *state['ids']] if key in custom)
    old = (previous or {}).get('custom', {})
    old_labels = (previous or {}).get('labels', {})
    seen = {}
    interests = {}
    prior_tags = interests_by_picture(previous or {})
    # Missing means a client predates interest phrases. An explicit empty map
    # from a new phone can remove the last phrase for a picture it just kept.
    required_tags = interests_by_picture(state) if 'drawingInterests' in state else prior_tags

    def retain_interest(key, label, shape, tags):
        name = eligible_drawing_name(key, label)
        for other, text in tags.get(name, ()):
            if shape == other:
                if text:
                    interests[key] = text
                break

    def distinct(key, label, shape):
        name = eligible_drawing_name(key, label)
        if not name:
            return False
        matches = seen.setdefault(name, [])
        if shape in matches:
            return False
        matches.append(shape)
        return True

    for key in required:
        distinct(key, labels[key], custom[key])
        retain_interest(key, labels[key], custom[key], required_tags)
    extras = []
    points = 0
    # These optional paths come exclusively from the last committed room.
    # Fresh previews can enter storage only through a guest actually keeping one.
    reserved = set(old) | set(required)
    next_number = 1
    for key in reversed(old):
        if len(extras) >= 12 or len(extras) + len(required) >= 256:
            break
        shape, label = old[key], old_labels[key]
        if points + len(shape) > 16000 or not distinct(key, label, shape):
            continue
        if key in required:
            # A phone that never saw the old library can reuse one of its IDs.
            # Keep the chosen new path under the ID it submitted and move the archive.
            while 'sketch-' + str(next_number) in reserved:
                next_number += 1
            key = 'sketch-' + str(next_number)
            reserved.add(key)
        retain_interest(key, label, shape, prior_tags)
        extras.append((key, shape, label))
        points += len(shape)
    kept = [*reversed(extras), *((key,custom[key],labels[key]) for key in required)]
    state['custom'] = {key: shape for key, shape, _ in kept}
    state['labels'] = {key: label for key, _, label in kept}
    if interests:
        state['drawingInterests'] = interests
    else:
        state.pop('drawingInterests', None)


def place_revisions(db, layout, revision):
    rows = db.execute('SELECT revision FROM place_revision WHERE layout=? ORDER BY place', (layout,))
    revisions = tuple(value for value, in rows)
    # An earlier version can reopen this same database and accept new saves
    # without recording their seats. Any such gap invalidates all older previews.
    return revisions if len(revisions) == 3 and max(revisions) == revision else (revision,) * 3


def unpack_path(encoded):
    from thrcommon import unpack_path as decode
    return decode(encoded)


def check_outline(shape):
    require(isinstance(shape, list) and 4 <= len(shape) <= 8000, 'Invalid sketch length.')
    for point in shape:
        require(isinstance(point, list) and len(point) == 2 and
                all(type(v) in (float, int) and -1.000001 <= v <= 1.000001 for v in point) and
                math.hypot(*point) <= 1 + 1e-8, 'Sketch is outside its place.')
    require(math.dist(shape[0], shape[-1]) <= 1e-6 and any(math.dist(shape[0], p) > 1e-6 for p in shape),
            'Sketch must draw a stroke and return to its start.')


class Layout:
    def __init__(self, scene):
        live = scene['live']
        self.edition = live['edition']
        self.editions = {self.edition, live['previousEdition']}
        self.previous_opening = live.get('previousOpening')
        # A bed-only edition can be shared by different physical sizes. It is
        # meaningful only inside an already bound database with a matching fingerprint.
        self.legacy_bed_edition = live.get('legacyBedEdition')
        self.radius_mm = live['radiusMM']
        self.groove = live['groove']
        self.size = live['size'] ** 2
        self.wide_center = live.get('wideCenter')
        portrait_zone = self.wide_center or (scene['zones']['center'] if scene['layout']=='portrait' else None)
        self.portrait_size = (2*portrait_zone['transit'][-1][1]*self.radius_mm,self.groove*self.radius_mm) if portrait_zone else None
        self.zones = set(scene['zones'])
        self.design_counts = {zone: len(scene['zones'][zone]['drawings']) for zone in ('center','outer')}
        catalog = live.get('planner') or {}
        self.subjects = set(catalog.get('subjects', {}))
        self.open_subject = catalog.get('openSubject')
        self.places = len(catalog.get('defaults', []))
        self.geometry = catalog.get('geometry', {})
        self.guest_border = live.get('guestBorder') is True
        self.guest_border_progressive = live.get('guestBorderProgressive') is True
        self.guest_border_seat = self.guest_border_progressive and live.get('guestBorderSeat') is True
        if self.guest_border:
            from check_ring_scene import joined
            self.motif_labels = catalog['subjects']
            self.motif_outlines = {key:unpack_path(value).tolist() for key,value in catalog['pairMotifs'].items()}
            outer = scene['zones']['outer']
            self.border_clear = joined([outer['transit'],outer['erase']],outer['transit'][0],
                                       outer['erase'][-1], 'Clearing the outer ring')
            if self.guest_border_progressive:
                self.border_sectors = [dict(sector, clear=unpack_path(sector['clear']))
                                       for sector in live['guestBorderSectors']]
                if self.guest_border_seat:
                    for sector in self.border_sectors:
                        if sector['slot'] is not None:
                            sector['spiral'] = unpack_path(sector['spiral'])
                    self.grain_probes = live['guestBorderGrain']
        if self.wide_center:
            from check_ring_scene import joined
            wide = self.wide_center
            transit = wide['transit']
            self.wide_radius = transit[-1][1]
            require(self.places == 3 and abs(self.wide_radius-self.geometry['bounds'][1]) < 1e-6,
                    'The family portrait must fit the guest ring.')
            restore = [transit, unpack_path(wide['restoreClear']), scene['zones']['center']['drawings'][0],
                       unpack_path(wide['restoreStem']), unpack_path(catalog['fixed'][0])]
            self.restore_start = joined(restore, transit[0], restore[-1][-1], 'Returning to guest places')
            self.restore_order = catalog['order']
            self.restore_fixed = [unpack_path(part) for part in catalog['fixed'][1:]]
            clear = unpack_path(wide['photoErase'])
            self.wide_sweep = joined([transit, clear], transit[0], clear[-1], 'Family portrait clear')
        self.scale = self.geometry.get('scale', 1)
        self.excursions = catalog.get('excursions', [])
        self.fill_tours = catalog.get('fillTours', {})
        self.custom_reveal = catalog.get('customReveal')
        self.place_paths = []
        self.middle_clear = None
        if catalog.get('transit') and catalog.get('erase'):
            from check_ring_scene import joined

            transit, erase = (unpack_path(catalog[k]) for k in ('transit','erase'))
            self.middle_clear = joined([transit, erase], transit[0], erase[-1], 'Whole guest ring')
        for place in catalog.get('places', []):
            if place is None:
                self.place_paths.append(None)
                continue
            approach, clear, recut, exit_path = (unpack_path(place[k]) for k in ('approach','clear','recut','exit'))
            prefix = joined([approach, clear, recut], approach[0], recut[-1], 'Guest clearing')
            self.place_paths.append(dict(clear=prefix, erase_segments=len(clear)-1, exit=exit_path, approach=approach,
                                         fill_exit=unpack_path(place['fillExit']) if 'fillExit' in place else exit_path,
                                         short_fill=place.get('shortFill', {}),
                                         limits=place['limits'], radii=place['radialBounds'],
                                         reveals=place.get('reveals', {}), reveal_targets=place.get('revealTargets', {}),
                                         additions=place.get('additions', {})))
        self.setup = live['setup']
        self.dock = scene['zones']['center']['transit'][0]
        self.bounds = {}
        for name, zone in scene['zones'].items():
            if name == 'middle':
                self.bounds[name] = catalog['geometry']['bounds']
            else:
                radii = [p[1] for p in zone['erase']]
                self.bounds[name] = [min(radii), max(radii)]
        self.initial = dict(bed=live['bed'], ids=catalog.get('defaults', []), center=0, outer=0,
                            portrait='', custom={})
        self.signature = self.attachment_signature(self.radius_mm, self.edition)
        require(len(base64.b64decode(live['bed'], validate=True)) == self.size, 'Invalid gallery bed.')

    def attachment_signature(self, radius_mm, edition, setup=None):
        configuration = (self.setup if setup is None else setup, self.dock, self.bounds, radius_mm, self.groove, edition)
        return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()

    def bound_edition(self, signature):
        if signature == self.signature:
            return self.edition
        # The original signature used JSON numbers directly. A command-line
        # radius of 450.0 and the default 450 could be serialized differently.
        radii = [self.radius_mm]
        if float(self.radius_mm).is_integer():
            alternate = float if type(self.radius_mm) is int else int
            radii.append(alternate(self.radius_mm))
        def matches(edition, files):
            return edition and any(signature == self.attachment_signature(r, edition, files) for r in radii)
        for edition in (self.edition, self.legacy_bed_edition):
            if matches(edition, self.setup):
                return edition
        old = self.previous_opening
        if old:
            from thrcommon import motion_files_hash
            setup = old['setup']
            if motion_files_hash(setup) == old['setupHash']:
                for edition in (old['edition'], old.get('legacyBedEdition')):
                    if matches(edition, setup):
                        return edition
        return None

    def check_route(self, zone, files, *, place=None, state=None, fill=False, short_fill=None, early_from=None, add_from=None,
                    custom_reveal=None, tour=None, center_mode=None, guest_border=False, border_order=None, border_seat=None, includes_center_rake=False):
        import numpy as np
        from check_ring_scene import TOL, covers_seam, joined, same_track, seam_segments

        validate_parts(files)
        parts = [np.fromstring(file['text'], dtype=float, sep=' ').reshape(-1, 2) for file in files]
        require(all(np.max(np.abs(part[:, 0])) < 10000 and
                    np.all(abs(np.diff(part[:, 0])) <= math.pi + TOL) for part in parts),
                'Ambiguous turn.')
        route = joined(parts, self.dock, self.dock, zone)
        if zone == 'setup':  # Pinned gallery asset on prepared sand.
            return
        lo, hi = self.bounds[zone]
        if center_mode:
            require(zone == 'center' and self.wide_center and state, 'No family portrait space in this layout.')
            hi = self.wide_radius
        radii = route[:, 1]
        require(np.all(radii >= lo - TOL), 'The route enters the inner drawing.')
        inside = radii <= hi + TOL
        stem = seam_segments(route, self.dock[0])
        require(np.all((inside[:-1] & inside[1:]) | stem), 'The route crosses another zone.')
        if guest_border:
            from garden_border import check_art, check_sections
            require(state and state['outer'] == -1 and zone == 'outer', 'Select the guest drawings for the border.')
            if border_order == 'progressive' or border_seat is not None:
                check_sections(route, self.border_sectors, state['guestBorder'], self.geometry['angles'],
                               (lo,hi), self.groove, self.dock[0], place=border_seat['place'] if border_seat else None,
                               grain=border_seat.get('grain','fluted') if border_seat else 'fluted')
                if border_seat is not None:
                    # Only its own wedge and the outer rail were used. The
                    # original inner access is still available to the next guest.
                    return
            else:
                require(same_track(route[:len(self.border_clear)], self.border_clear),
                        'Clear the border before drawing the guest artwork.')
                check_art(route[len(self.border_clear)-1:], state['guestBorder'], self.geometry['angles'],
                          (lo,hi), self.groove, self.dock[0])
        if center_mode == 'widePortrait':
            self.check_wide_portrait(route, includes_center_rake)
        elif center_mode == 'restoreGuests':
            self.check_guest_return(route, state)
            return
        if tour is not None:
            require(zone == 'middle' and state, 'A guest tour needs a middle-ring drawing.')
            order = [trip['place'] for trip in tour]
            key = '-'.join(map(str, sorted(order)))
            candidate = next((steps for steps in self.fill_tours.get(key, ())
                              if [step['place'] for step in steps] == order), None)
            require(candidate is not None, 'Unknown guest tour.')
            # Joined files share one endpoint. A seat can span several files
            # and the next seat starts on the previous seat's last gate.
            ends = np.cumsum([0, *(len(part)-1 for part in parts)])
            first = 0
            for i, (step, trip) in enumerate(zip(candidate, tour)):
                last = first + trip['count']
                require(('exit' in step) == (i == len(tour)-1), 'Incomplete guest tour.')
                approach = unpack_path(step['approach'])
                exit_path = unpack_path(step['exit']) if 'exit' in step else None
                self.check_engraving(trip['place'], state, route[ends[first]:ends[last]+1], approach, exit_path)
                first = last
            return
        if place is not None:
            require(state and zone == 'middle' and 0 <= place < len(self.place_paths)
                    and self.place_paths[place] is not None, 'Unknown clearing path.')
            paths = self.place_paths[place]
            if add_from is not None:
                target = state['ids'][place]
                addition = paths['additions'].get(add_from, {}).get(target)
                require(addition and files == addition['files'], 'Incorrect artwork addition for this guest place.')
                self.check_subject(place, state)
                return
            if custom_reveal is not None:
                self.check_custom_reveal(place, state, route, custom_reveal)
                return
            if early_from is not None:
                target = state['ids'][place]
                require(not fill and early_from in self.subjects and target in self.subjects
                        and target != self.open_subject and target != early_from,
                        'An early replacement needs two occupied native drawings.')
                self.check_subject(place, state)
                return
            if short_fill:
                require(fill and short_fill in paths['short_fill'], 'Unknown short approach to this guest place.')
                prefix = unpack_path(paths['short_fill'][short_fill])
                exit_path = prefix[::-1]
            else:
                prefix, exit_path = (paths['approach'], paths['fill_exit']) if fill else (paths['clear'], paths['exit'])
            self.check_engraving(place, state, route, prefix, exit_path, short_fill)
            return
        if zone == 'middle' and self.middle_clear is not None:
            require(same_track(route[:len(self.middle_clear)], self.middle_clear),
                    'A whole-ring change must clear the whole guest ring.')
            if state and self.open_subject in state['ids']:
                self.check_open_places(state['ids'], route[len(self.middle_clear)-1:])
        art = np.flatnonzero(~stem)
        require(len(art) > 0, 'Empty zone drawing.')
        # A portrait can end on the edge of its own disc. All inner zones must
        # still have an established way through the ring we just changed.
        covers_seam(route[art[-1]+1:], self.dock[0], hi if zone == 'center' else lo, 1, zone)

    def check_wide_portrait(self, route, includes_center_rake=False):
        """A seated or shaded portrait can visit a face during its fine spiral."""
        import numpy as np
        from check_ring_scene import TOL, same_track

        sweep = self.wide_sweep
        home = np.asarray(self.wide_center['transit'][::-1])
        require(len(route) > len(sweep)+len(home)+1 and same_track(route[-len(home):], home),
                'The family portrait must engrave a picture and return on the stem.')
        if includes_center_rake:
            from check_ring_scene import sweep_coverage

            require(abs(self.radius_mm-420) < .001 and abs(self.groove*self.radius_mm-7) < .001 and
                    abs(self.wide_radius*self.radius_mm-316.4) < .01 and
                    same_track(route[:len(home)], home[::-1]),
                    'The single-pass print needs its measured wide center and dock.')
            # Proof is over the actual downloaded moves, even if a guest edits
            # an import. Bound the number of interpolated samples first. The
            # ordinary route/exit checks still guard the neighboring border.
            change = np.diff(route, axis=0)
            length = np.hypot(change[:,1], change[:,0] * np.maximum(route[:-1,1],route[1:,1]))
            proof_groove = self.groove - 2*TOL
            require(np.maximum(1,np.ceil(length/(proof_groove*.08))).sum() <= 550000,
                    'The single-pass print exceeds the clearing proof limit.')
            sweep_coverage([route], 0, self.wide_radius, proof_groove, -math.pi, math.pi,
                           'The portrait must clear the entire wide center')
            return
        if same_track(route[:len(sweep)], sweep):
            return
        # Even the interleaved portraits include each calibrated spiral vertex
        # in order. They may add whole turns inside an excursion to a face.
        next_row = 0
        for angle, radius in route:
            expected_angle, expected_radius = sweep[next_row]
            if abs(radius - expected_radius) <= TOL and abs(math.remainder(angle-expected_angle, math.tau)) <= TOL:
                next_row += 1
                if next_row == len(sweep):
                    return
        raise ValueError('The family portrait must clear both the center and the guest ring.')

    def check_guest_return(self, route, state):
        """Match the whole restore, including the actual named or sketched subjects."""
        import numpy as np
        from check_ring_scene import same_track, wrapped, TOL

        pos = 0

        def consume(expected):
            nonlocal pos
            expected = np.asarray(expected)
            require(same_track(route[pos:pos+len(expected)], expected), 'The guest return does not match the saved garden.')
            pos += len(expected)-1

        consume(self.restore_start)
        for place, fixed in zip(self.restore_order, self.restore_fixed, strict=True):
            key = state['ids'][place]
            if key in self.excursions[place]:
                consume(unpack_path(self.excursions[place][key]))
            else:
                # A sketch has no fixed point count. Its terminal gate is on
                # the rail beyond the entire guest place.
                left, right = self.geometry['gates'][place]
                remaining = route[pos:]
                gates = np.flatnonzero((abs(wrapped(remaining[:,0]-right)) <= TOL) &
                                       (abs(remaining[:,1]-self.geometry['rail']) <= TOL))
                require(len(gates) and gates[0] > 1, 'Missing saved guest sketch.')
                sketch = remaining[:gates[0]+1].copy()
                sketch[:,0] -= math.tau * round((sketch[0,0]-left)/math.tau)
                self.check_sketch(sketch, self.guest_coordinates(state['custom'][key], place), place)
                pos += gates[0]
            consume(fixed)
        consume(self.wide_center['transit'][::-1])
        require(pos == len(route)-1, 'Unexpected travel after the guest drawings.')

    def guest_coordinates(self, shape, place):
        import numpy as np
        from thrcommon import rotate_xy

        angle = self.geometry['angles'][place]
        center = self.geometry['center'] * np.array([math.cos(angle), math.sin(angle)])
        outline = np.asarray(shape)
        if self.geometry.get('faceEdge'):
            outline = rotate_xy(outline, angle + math.pi/2)
        return center + self.scale * outline

    def check_engraving(self, place, state, route, approach, exit_path, short_fill=None):
        from check_ring_scene import same_pose, same_track

        end = len(route) if exit_path is None else len(route)-len(exit_path)+1
        require(end > len(approach) and same_track(route[:len(approach)], approach)
                and (exit_path is None or same_track(route[end-1:], exit_path)), 'Incorrect approach or return path.')
        engraving = route[len(approach)-1:end].copy()
        left, right = self.geometry['gates'][place]
        rail = self.geometry['rail']
        start = right if short_fill == 'right' else left
        finish = start if short_fill else right
        require(same_pose(engraving[0], (start, rail)) and same_pose(engraving[-1], (finish, rail)),
                'Incorrect guest drawing gate.')
        engraving[:, 0] -= math.tau * round((engraving[0, 0] - start) / math.tau)
        return self.check_subject(place, state, engraving, short_fill)

    def check_custom_reveal(self, place, state, route, detour):
        """Strip one or two visits, then prove each against the verified ordinary drawing."""
        import numpy as np
        from check_ring_scene import same_track, TOL

        paths = self.place_paths[place]
        require(self.custom_reveal and state['ids'][place] in state['custom'],
                'An early guest sketch needs a fitted place and a saved outline.')
        visits = [detour, detour['second']] if 'second' in detour else [detour]
        ordinary_parts, branches = [], []
        removed = cursor = 0
        previous_lane = -1
        for visit in visits:
            lane, segment, end = (visit[key] for key in ('clearSegment', 'artSegment', 'end'))
            require(previous_lane < lane < paths['erase_segments'], 'Invalid guest clearing row.')
            previous_lane = lane
            count = end-segment if end > segment else segment-end+1
            base_start = len(paths['approach']) + lane
            start = base_start + removed
            stop = start + 2*count + 1
            require(stop < len(route), 'The guest detour did not return to its clearing row.')
            ordinary_parts.append(route[cursor:start])
            branches.append((base_start, segment, end, count, route[start:stop]))
            removed += stop-start
            cursor = stop

        ordinary = np.concatenate([*ordinary_parts, route[cursor:]])
        prefix, exit_path = paths['clear'], paths['exit']
        first, last = self.check_engraving(place, state, ordinary, prefix, exit_path)
        engraving = ordinary[len(prefix)-1:len(ordinary)-len(exit_path)+1]
        for start, segment, end, count, branch in branches:
            require(first <= segment < last and first <= end <= last, 'The early stroke extends past its drawing.')
            stroke = engraving[segment+1:end+1] if end > segment else engraving[end:segment+1][::-1]
            require(same_track(branch[1:count+1], stroke) and same_track(branch[:count+1], branch[count:][::-1]),
                    'The early pass must trace the selected artwork and return along it.')
            # At signed-file precision the crossing may move a few microns.
            # Project it onto each bounded driver segment, on its actual unwrapped turn.
            for a, b in ((ordinary[start-1], ordinary[start]), (engraving[segment], engraving[segment+1])):
                point = branch[0].copy()
                point[0] += math.tau * round((a[0]-point[0])/math.tau)
                delta = b-a
                length2 = delta @ delta
                require(length2 > 0, 'A stationary point cannot supply the guest crossing.')
                fraction = np.clip((point-a) @ delta / length2, 0, 1)
                require(np.linalg.norm(point-(a+fraction*delta)) <= TOL,
                        'The early stroke must start on both the clearing row and the artwork.')

    def check_open_places(self, ids, art):
        """A later direct addition relies on these seats being empty after a whole-ring redraw."""
        import numpy as np
        from check_ring_scene import TOL, wrapped

        rail = np.abs(art[:,1] - self.geometry['rail']) <= TOL
        turns = np.diff(art[:,0])
        midpoints = art[:-1,0] + turns/2
        span = math.asin(self.scale / self.geometry['center'])
        # Include the hanger as well as the guest disc. The two decorative
        # leaves live beyond this interval. Only the established rail traverses it.
        for place, subject in enumerate(ids):
            if subject == self.open_subject:
                distance = np.abs(wrapped(midpoints - self.geometry['angles'][place]))
                outside = distance > span + np.abs(turns)/2 + TOL
                require(np.all(outside | (rail[:-1] & rail[1:])), 'An open place contains a drawing.')

    def check_subject(self, place, state, engraving=None, short_fill=None):
        """Every stroke off the hanging rail must be inside this place's swept sand."""
        import numpy as np
        from check_ring_scene import TOL, same_track

        paths = self.place_paths[place]
        angles, radii = paths['limits'], paths['radii']
        key = state['ids'][place]
        shape = state['custom'].get(key)
        ink_bounds = None
        rail = self.geometry['rail']
        if shape is None:
            expected = unpack_path(self.excursions[place][key])
            if short_fill:
                off_rail = np.flatnonzero(abs(expected[:,1] - rail) > 1e-7)
                require(len(off_rail) > 0, 'A short fill needs a guest drawing.')
                first, last = off_rail[0], off_rail[-1]
                lead = expected[:first] if short_fill == 'left' else expected[last+1:][::-1]
                # Both gates enter the same hanger, draw the native picture in
                # its original order, and return on exactly the incoming lead.
                expected = np.vstack((lead[:-1], expected[first-1:last+2], lead[-2::-1]))
            if engraving is not None:
                require(same_track(engraving, expected), 'The engraving does not match the chosen subject.')
            path = expected
        else:
            angle = self.geometry['angles'][place]
            xy = self.guest_coordinates(shape, place)
            # The bearing along each straight stroke stays between its ends. Radius
            # can dip in the middle, so include its closest point to the table center.
            delta = np.diff(xy, axis=0)
            squared = (delta * delta).sum(axis=1)
            fraction = np.divide(-(xy[:-1] * delta).sum(axis=1), squared,
                                 out=np.zeros_like(squared), where=squared > 0).clip(0, 1)
            nearest = xy[:-1] + fraction[:,None] * delta
            require(np.min(np.hypot(*nearest.T)) >= radii[0] - TOL, 'The sketch extends beyond the erase.')
            theta = angle + (np.arctan2(xy[:,1], xy[:,0]) - angle + math.pi) % math.tau - math.pi
            path = np.column_stack((theta, np.hypot(*xy.T)))
            require(radii[0]-TOL <= self.geometry['rail'] <= radii[1]+TOL, 'The hanger extends beyond the erase.')
            if engraving is not None:
                ink_bounds = self.check_sketch(engraving, xy, place, short_fill)
        for track in (path,) if engraving is None else (path, engraving):
            on_rail = abs(track[:,1] - rail) <= TOL
            within = ((track[:,0] >= angles[0] - TOL) & (track[:,0] <= angles[1] + TOL)
                      & (track[:,1] >= radii[0] - TOL) & (track[:,1] <= radii[1] + TOL))
            require(np.all((on_rail[:-1] & on_rail[1:]) | (within[:-1] & within[1:])),
                    'The guest engraving extends outside the cleared sand.')
        return ink_bounds

    def check_sketch(self, engraving, xy, place, short_fill=None):
        """Match the phone's densely sampled walk to the original guest-supplied vertices."""
        import numpy as np
        from check_ring_scene import TOL, check_sampled_strokes, same_track

        rail = self.geometry['rail']
        below = np.flatnonzero(np.abs(engraving[:,1] - rail) > TOL)
        require(len(below) and below[0] and below[-1] < len(engraving)-1, 'Missing guest engraving.')
        contour = engraving[below[0]-1:below[-1]+2]
        entrance = contour[0,0]
        gates = self.geometry['gates'][place]
        lead, leave = engraving[:below[0]], engraving[below[-1]+1:]
        if short_fill:
            require(same_track(lead, leave[::-1]), 'The sketch must retrace its incoming rail.')
            # customExcursion evenly samples this circular lead at most .05
            # radians apart. Allow for the exported five-decimal endpoint.
            span = abs(entrance-lead[0,0])
            count = len(lead)-1
            require(max(1,math.ceil((span-TOL)/.05)) <= count <= max(1,math.ceil((span+TOL)/.05))
                    and np.allclose(lead[:,0], np.linspace(lead[0,0], entrance, len(lead)), atol=TOL, rtol=0),
                    'Incorrect rail lead for the guest sketch.')
        incoming = -1 if short_fill == 'right' else 1
        outgoing = -incoming if short_fill else 1
        require(np.all((engraving[:,0] >= gates[0]-TOL) & (engraving[:,0] <= gates[1]+TOL))
                and np.all(incoming*np.diff(lead[:,0]) >= -TOL)
                and np.all(outgoing*np.diff(leave[:,0]) >= -TOL)
                and abs(contour[-1,0]-entrance) <= TOL, 'The sketch left its hanging rail.')
        # The shared rail leads to the outermost vertex, down the hanger and
        # around the closed sketch in its original order before retracing the hanger.
        tip = np.array([math.cos(entrance), math.sin(entrance)])
        lengths = np.hypot(*xy[:-1].T)
        radius = lengths.max()
        peaks = np.flatnonzero(lengths >= radius - 1e-14)
        entry = peaks[np.argmin(np.linalg.norm(xy[peaks] - radius * tip, axis=1))]
        require(np.linalg.norm(xy[entry] - radius * tip) <= TOL, 'Incorrect sketch entrance.')
        anchor = rail * xy[entry] / lengths[entry]
        reference = np.vstack((anchor, xy[entry:-1], xy[:entry+1], anchor))
        actual = contour[:,1,None] * np.column_stack((np.cos(contour[:,0]), np.sin(contour[:,0])))
        counts = check_sampled_strokes(actual, reference, hanger_steps=abs(rail-radius)/.015)
        return below[0]-1+counts[0], below[-1]+1-counts[-1]

    def check_change(self, previous, state, zone, local=(), center_mode=None, border_motion=None):
        require(state and not state.get('starting'), 'A new physical layout needs prepared sand.')
        old = previous or self.initial
        was_wide = old.get('widePortrait', False)
        is_wide = state.get('widePortrait', False)
        if center_mode == 'widePortrait':
            require(is_wide and state['center'] == old['center'], 'The family portrait must cover the guest places.')
        elif center_mode == 'restoreGuests':
            require(was_wide and not is_wide and not state['portrait'] and state['center'] == 0,
                    'Restore the flower and guest drawings from a wide portrait.')
        else:
            require(is_wide == was_wide, 'Changing the portrait size needs its drawing files.')
            require(not was_wide or zone not in ('middle','center'), 'Restore the guest places before drawing there.')
        if was_wide or is_wide:
            require(state.get('guestBook') == old.get('guestBook') and active_guests(state) == active_guests(old),
                    'Keep the guest book and drawings while the portrait covers their places.')
        if zone != 'center':
            require(all(old[k] == state[k] for k in ('center','portrait')), 'Center changed without its route.')
        if zone != 'outer':
            require(old['outer'] == state['outer'], 'Border changed without its route.')
            require(old.get('guestBorder') == state.get('guestBorder'), 'Guest artwork in the border changed without its route.')
        elif state['outer'] == -1:
            require(border_motion, 'The saved guest artwork needs its own border drawing.')
            border_seat = border_motion.get('guestBorderSeat')
            if border_seat is None:
                self.check_border_sources(old, state['guestBorder'])
            else:
                self.check_border_seat_change(old,state,border_seat)
        if self.guest_border_seat and state['outer'] == -1:
            expected = old.get('guestBorderGrain')
            if border_motion and 'guestBorderSeat' not in border_motion:
                expected = 'fluted' if border_motion.get('guestBorderOrder') == 'progressive' else 'spiral'
            if expected is not None:
                state.setdefault('guestBorderGrain',expected)
            require(state.get('guestBorderGrain') == expected, 'Changing the recorded rim texture requires a full border drawing.')
        if zone != 'middle' or local:
            changed = {i for i, (before, after) in enumerate(zip(old['ids'], state['ids']))
                       if before != after or old['custom'].get(before) != state['custom'].get(after)}
            require(changed == {trip['place'] for trip in local}, 'The drawing does not match the changed guest places.')
            for trip in local:
                place = trip['place']
                if 'addFrom' in trip:
                    require(old['ids'][place] == trip['addFrom'], 'The addition starts from another drawing.')
                if 'customReveal' in trip:
                    require(old['ids'][place] != self.open_subject, 'An open place needs a direct drawing.')
                if 'earlyFrom' in trip:
                    from thrcommon import motion_files_hash

                    # Match every signed download to the source in the locked room.
                    origin = old['ids'][place]
                    require(origin == trip['earlyFrom'], 'The early replacement starts from another drawing.')
                    paths, target, files = self.place_paths[place], state['ids'][place], trip['files']
                    specific = paths['reveals'].get(origin, {}).get(target)
                    if not specific or specific['files'] != files:
                        shared = paths['reveal_targets'].get(target, {})
                        allowed = shared.get('from')
                        previous_hash = shared.get('previousFilesHash')
                        require(isinstance(allowed, list) and origin in allowed and
                                (shared.get('files') == files or
                                 (previous_hash and motion_files_hash(files) == previous_hash)),
                                'Incorrect early replacement files.')
                if trip.get('fill'):
                    require(self.open_subject and old['ids'][place] == self.open_subject
                            and state['ids'][place] != self.open_subject, 'This guest place is already occupied.')
                self.check_subject(place, old)
        if zone is None:
            require(old['bed'] == state['bed'], 'Sand changed without a drawing.')

    def check_border_seat_change(self, old, state, seat):
        from garden_border import stored_grain
        place = seat['place']
        require(old['outer'] == -1 and old.get('guestBorder'), 'First draw a border for the guests.')
        grain = old.get('guestBorderGrain') or stored_grain(old['bed'], self.grain_probes)
        require(grain == seat.get('grain','fluted'), 'Use the same erase texture as the existing guest border.')
        require(all(old.get(key) == state.get(key) for key in ('guestBook','labels','custom'))
                and old.get('drawingInterests',{}) == state.get('drawingInterests',{})
                and old.get('borderGuest','') == state.get('borderGuest',''),
                'A border request must preserve the guest book, saved drawings and border name.')
        changed = [i for i,(a,b) in enumerate(zip(old['guestBorder'],state['guestBorder'],strict=True)) if a != b]
        require(changed == [place], 'A request for one guest must change only that border drawing.')
        self.check_border_sources(old,state['guestBorder'],[(place,seat['subject'])])

    def check_border_sources(self, previous, frame, places=None):
        roster = active_guests(previous)
        if places is None:
            places = enumerate(previous['ids'])
        for slot, subject in places:
            if subject == self.open_subject:
                require(frame[slot] is None, 'An open place has no drawing to put in the border.')
                continue
            guest, _ = roster[slot][0]
            if subject in previous['custom']:
                shape, name = previous['custom'][subject], previous['labels'][subject]
            else:
                require(subject in self.motif_outlines, 'Choose an existing drawing for the guest border.')
                shape, name = self.motif_outlines[subject], self.motif_labels[subject]
            require(frame[slot] == {'label':guest+' · '+name, 'points':shape},
                    'Guest drawings have changed since this border was previewed.')

    def valid_custom_id(self, key):
        if len(key) > 160:
            return False
        symbol = r'symbol-[a-f0-9]+(?:-[a-f0-9]+)*'
        if re.fullmatch(r'sketch-[0-9]+|' + symbol, key):
            return True
        pair = re.fullmatch(r'pair-(?:above|below|beside|behind|lean)-([a-z0-9_-]+)__([a-z0-9_-]+)', key)
        return bool(pair and all(part in self.subjects or re.fullmatch(symbol, part) for part in pair.groups()))

    def validate(self, state):
        if state is None:
            return
        fields(state, ('edition','bed','center','outer','portrait','ids','custom','labels'),
               ('guestBook','borderGuest','guestBorder','guestBorderGrain','portraitSeats','widePortrait','starting','drawingInterests'))
        require(isinstance(state['edition'], str) and state['edition'] in self.editions, 'Different gallery edition.')
        require(isinstance(state['bed'], str) and len(state['bed']) == 4 * ((self.size + 2) // 3) and
                len(base64.b64decode(state['bed'], validate=True)) == self.size, 'Invalid sand bed.')
        for key, count in self.design_counts.items():
            minimum = -1 if key == 'outer' and self.guest_border else 0
            require(type(state[key]) is int and minimum <= state[key] < count, 'Invalid selection.')
        require(type(state.get('starting', False)) is bool and short_text(state['portrait'], 180), 'Invalid selection.')
        require(('guestBorder' in state) == (state['outer'] == -1), 'Guest border and selection disagree.')
        if 'guestBorderGrain' in state:
            require(self.guest_border_seat and 'guestBorder' in state and state['guestBorderGrain'] in ('spiral','fluted'),
                    'Unknown guest border texture.')
        if 'guestBorder' in state:
            frame = state['guestBorder']
            require(self.guest_border and not state.get('starting') and isinstance(frame, list)
                    and len(frame) == self.places and any(item is not None for item in frame), 'Invalid guest border.')
            for item in frame:
                if item is not None:
                    fields(item, ('label','points'))
                    require(short_text(item['label'], 240) and item['label'].strip(), 'Invalid guest border title.')
                    check_outline(item['points'])
        if 'borderGuest' in state:
            require(self.design_counts['outer'] > 2 and short_text(state['borderGuest'], 48), 'Invalid border guest.')
        if 'portraitSeats' in state:
            require(state['portrait'] and type(state['portraitSeats']) is int and 2 <= state['portraitSeats'] <= 32000,
                    'Invalid portrait seat count.')
        if 'widePortrait' in state:
            require(self.wide_center and state['widePortrait'] is True and state['portrait'] and not state.get('starting'),
                    'A wide portrait needs a compatible guest garden and a photograph.')

        ids, custom, labels = (state[k] for k in ('ids','custom','labels'))
        require(isinstance(ids, list) and len(ids) == self.places and isinstance(custom, dict) and
                isinstance(labels, dict) and labels.keys() == custom.keys() and
                len(custom) <= (256 if self.places else 0), 'Invalid guest drawings.')
        for key, shape in custom.items():
            require(self.valid_custom_id(key) and short_text(labels[key], 180), 'Invalid drawing name.')
            check_outline(shape)
            steps = sum(max(1, math.ceil(math.dist(a, b) * self.scale / .01)) for a, b in zip(shape, shape[1:]))
            require(steps < 32000, 'Sketch exceeds the travel limit.')
        if 'drawingInterests' in state:
            tags = state['drawingInterests']
            require(isinstance(tags, dict) and tags.keys() <= custom.keys() and
                    all(eligible_drawing_name(key, labels[key]) for key in tags), 'Unknown or unnamed drawing in interests.')
            state['drawingInterests'] = {key: clean_drawing_interest(value) for key, value in tags.items()}
        available = self.subjects | custom.keys()
        if self.open_subject:
            available.add(self.open_subject)
        require(all(isinstance(i,str) and i in available for i in ids), 'Unknown guest drawing.')
        book = state.get('guestBook')
        if book is None:
            return
        fields(book, ('people','active'))
        require(self.places and isinstance(book['people'], list) and self.places <= len(book['people']) <= 256 and
                isinstance(book['active'], list) and len(book['active']) == self.places, 'Invalid guest book.')
        roster = {}
        for person in book['people']:
            fields(person, ('name','interest','subject'))
            require(short_text(person['name'], 48) and short_text(person['interest'], 180) and
                    isinstance(person['subject'],str) and person['subject'] in available, 'Invalid guest.')
            key = name_key(person['name'])
            require(key and key not in roster, 'Duplicate or missing guest name.')
            roster[key] = person['subject']
        active = book['active']
        require(all(isinstance(key,str) and key in roster for key in active) and
                len(set(active)) == self.places and [roster[k] for k in active] == ids, 'Invalid guest places.')


def validate_motion(motion, layout):
    """Validate the envelope and return its individually checkable seat trips."""
    if motion is None:
        return []
    fields(motion, ('zone','files'), ('place','fill','shortFill','earlyFrom','addFrom','customReveal','parts','tour','centerMode','guestBorder','guestBorderOrder','guestBorderSeat','includesCenterRake'))
    require(isinstance(motion['zone'],str) and motion['zone'] in layout.zones and
            isinstance(motion['files'], list) and 1 <= len(motion['files']) <= 24, 'Invalid drawing files.')
    local = []
    if {'guestBorder','guestBorderOrder','guestBorderSeat'}.intersection(motion):
        fields(motion, ('zone','files','guestBorder'), ('guestBorderOrder','guestBorderSeat'))
        require(layout.guest_border and motion['zone'] == 'outer' and motion['guestBorder'] is True,
                'A guest border belongs in the outer ring.')
        if 'guestBorderOrder' in motion:
            require('guestBorderSeat' not in motion and layout.guest_border_progressive and motion['guestBorderOrder'] == 'progressive',
                    'This layout cannot draw the guest border in that order.')
        if 'guestBorderSeat' in motion:
            seat = motion['guestBorderSeat']
            fields(seat, ('place','subject'), ('grain',))
            require(layout.guest_border_seat and type(seat['place']) is int and 0 <= seat['place'] < layout.places
                    and short_text(seat['subject'],160) and seat['subject'] and seat['subject'] != layout.open_subject
                    and ('grain' not in seat or seat['grain'] == 'spiral'),
                    'Choose a guest and an existing drawing for this border.')
    if 'includesCenterRake' in motion:
        require(motion['includesCenterRake'] is True and motion.get('centerMode') == 'widePortrait',
                'Only the wide center portrait can include its clearing pass.')
    if 'centerMode' in motion:
        fields(motion, ('zone','files','centerMode'), ('includesCenterRake',))
        require(layout.wide_center and motion['zone'] == 'center' and motion['centerMode'] in ('widePortrait','restoreGuests'),
                'Unsupported center and guest-ring change.')
    if 'tour' in motion:
        require(motion['tour'] is True and 'parts' in motion, 'A guest tour needs its visits.')
    if 'parts' in motion:
        fields(motion, ('zone','files','parts'), ('tour',))
        parts, files = motion['parts'], motion['files']
        require(motion['zone'] == 'middle' and isinstance(parts, list) and 2 <= len(parts) <= 3,
                'A combined drawing changes two or three guest places.')
        used, offset = set(), 0
        for part in parts:
            if 'tour' in motion:
                fields(part, ('place','count','fill'))
            else:
                fields(part, ('place','count'), ('fill','shortFill','earlyFrom','addFrom','customReveal'))
            place, count = part['place'], part['count']
            require(type(place) is int and place not in used and type(count) is int
                    and 0 < count <= len(files)-offset, 'Invalid guest trip boundary.')
            used.add(place)
            group = files[offset:offset+count]
            for j, file in enumerate(group, offset+1):
                require(isinstance(file, dict) and file.get('name') == f'guest-ring-{j}.thr',
                        'Unexpected combined drawing filename.')
            if 'tour' in motion:
                local.append(part)
            else:
                # Historical dock trips compare their original numbering and bytes.
                local.append(dict(part, files=[dict(file, name=f'guest-ring-{j}.thr')
                                               for j, file in enumerate(group, 1)]))
            offset += count
        require(offset == len(files), 'Unclaimed drawing files.')
    elif 'place' in motion:
        local = [motion]
    else:
        require(not {'fill','shortFill','earlyFrom','addFrom','customReveal'}.intersection(motion), 'A local drawing needs a guest place.')
    for trip in local:
        require(motion['zone'] == 'middle' and type(trip['place']) is int
                and 0 <= trip['place'] < layout.places, 'Unknown guest place.')
        if 'addFrom' in trip:
            source = trip['addFrom']
            require(not {'fill','earlyFrom','customReveal'}.intersection(trip) and
                    isinstance(source, str) and source in layout.subjects and source != layout.open_subject,
                    'An addition needs its existing guest drawing.')
        if 'fill' in trip:
            require(trip['fill'] is True and layout.open_subject, 'A direct drawing needs an open place.')
        if 'shortFill' in trip:
            require(trip.get('fill') is True and trip['shortFill'] in ('left','right'), 'Invalid open-place approach.')
        if 'earlyFrom' in trip:
            source = trip['earlyFrom']
            require('fill' not in trip and isinstance(source,str) and source in layout.subjects
                    and source != layout.open_subject, 'An early replacement needs an occupied guest place.')
        if 'customReveal' in trip:
            detour = trip['customReveal']
            indices = ('clearSegment','artSegment','end')
            fields(detour, indices, ('second',))
            require('fill' not in trip and 'earlyFrom' not in trip, 'Conflicting guest motion.')
            visits = [detour]
            if 'second' in detour:
                fields(detour['second'], indices)
                visits.append(detour['second'])
            for visit in visits:
                require(all(type(visit[k]) is int and visit[k] >= 0 for k in indices), 'Invalid guest crossing.')
    names = set()
    for part in motion['files']:
        fields(part, ('name','text'))
        name, text = part['name'], part['text']
        require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.thr', name)
                and name not in names, 'Invalid drawing filename.')
        names.add(name)
        require(isinstance(text,str) and len(text) <= 1_000_000 and text.isascii(), 'Invalid motion text.')
        lines = text.splitlines()
        require(2 <= len(lines) <= 12000, 'Invalid drawing length.')
        for line in lines:
            coords = len(line) <= 96 and MOTION_LINE.fullmatch(line)
            require(coords, 'Invalid motion line.')
            theta, radius = map(float, coords.groups())
            require(math.isfinite(theta) and 0 <= radius <= 1, 'Invalid drawing coordinate.')

    if 'parts' in motion and 'tour' not in motion:
        # Tours are checked in one pass from dock to dock. Separate local trips
        # also need the global file-boundary check before their individual checks.
        validate_parts(motion['files'])
    return local


def load_gallery(page):
    html = Path(page).read_text(encoding='utf-8')
    layouts = {}
    for data in re.findall(r'<script type="application/json" id="(?:scene|otherScene)">(.*?)</script>', html, re.S):
        scene = json.loads(data)
        if scene is not None:
            require(scene['layout'] in ('garden','portrait'), 'Unknown gallery layout.')
            layouts[scene['layout']] = Layout(scene)
    require(layouts and '<head>' in html and MARKER not in html, 'Expected a generated local gallery.')
    return html.replace('<head>', '<head>\n' + MARKER, 1).encode('utf-8'), layouts


class RoomHandler(BaseHTTPRequestHandler):
    timeout = 20

    def log_request(self, code='-', size='-'):
        if code != 304:
            super().log_request(code, size)

    def reply(self, code, value=None, etag=None, compressed=False, places=None, content_type=None, retry_after=None):
        body = b'' if value is None else value if isinstance(value,bytes) else json.dumps(
            value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(code)
        if body:
            default_type = 'text/html' if isinstance(value, bytes) else 'application/json'
            self.send_header('Content-Type', content_type or default_type + '; charset=utf-8')
        if code != 304:
            self.send_header('Content-Length', str(len(body)))
        if etag is not None:
            self.send_header('ETag', f'"{etag}"')
        if places is not None:
            self.send_header('X-Oasis-Place-Revisions', ','.join(map(str, places)))
        if retry_after is not None:
            self.send_header('Retry-After', str(retry_after))
        if isinstance(value, bytes) and content_type is None:
            self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if body:
            self.wfile.write(body)

    def route(self):
        path = urlsplit(self.path).path
        match = re.fullmatch(r'/api/garden/(garden|portrait)(?:/drawings/(center|middle|outer))?', path)
        if match:
            layout, zone = match.groups()
            if layout in self.server.layouts and (not zone or zone in self.server.layouts[layout].zones):
                return layout, zone
        return None, None

    def from_garden(self):
        origin = self.headers.get('Origin', '').lower()
        host = self.headers.get('Host', '').lower()
        proxied_https = self.client_address[0] in ('127.0.0.1','::1') and self.headers.get('X-Forwarded-Proto') == 'https'
        scheme = 'https' if proxied_https else 'http'
        return host and origin == scheme + '://' + host and self.headers.get('Sec-Fetch-Site') != 'cross-site'

    def do_GET(self):
        if (self.server.attached and
                urlsplit(self.path).path == f'/api/garden/{self.server.attached}/drawings/setup'):
            return self.reply(200, {'revision':0, 'files':self.server.starting_files})
        if urlsplit(self.path).path == '/api/playback' and self.server.worker:
            layout = self.server.attached
            try:
                with closing(sqlite3.connect(self.server.db)) as db:
                    db.execute('BEGIN')
                    revision, = db.execute('SELECT revision FROM garden WHERE layout=?', (layout,)).fetchone()
                    status = garden_playback.status(db, layout, self.server.worker)
                return self.reply(200, dict(status, revision=revision, layout=layout))
            except sqlite3.Error:
                return self.reply(503, {'error':'Table status is unavailable.'})
        if urlsplit(self.path).path in ('/', '/garden'):
            encodings = {}
            for coding in self.headers.get('Accept-Encoding', '').lower().split(','):
                name, *params = coding.split(';')
                quality = next((p.split('=',1)[1] for p in params if p.strip().startswith('q=')), '1')
                try:
                    encodings[name.strip()] = 0 < float(quality) <= 1
                except ValueError:
                    encodings[name.strip()] = False
            use_gzip = encodings.get('gzip', encodings.get('*', False))
            return self.reply(200, self.server.compressed if use_gzip else self.server.gallery, compressed=use_gzip)
        layout, zone = self.route()
        if not layout:
            return self.reply(404, {'error':'Unknown path.'})
        key, table, args = ('files', 'drawing WHERE layout=? AND zone=?', (layout, zone)) if zone else (
            'state', 'garden WHERE layout=?', (layout,))
        tags = [x.strip().removeprefix('W/') for x in self.headers.get('If-None-Match','').split(',')]
        places = None
        try:
            with closing(sqlite3.connect(self.server.db)) as db:
                # Read the revision and its payload from the same SQLite snapshot. Unchanged
                # polling phones never fetch the large drawing column from disk.
                db.execute('BEGIN')
                row = db.execute('SELECT revision FROM ' + table, args).fetchone()
                rev = row[0] if row else 0
                unchanged = '*' in tags or f'"{rev}"' in tags
                if not unchanged:
                    saved = db.execute('SELECT ' + key + ' FROM ' + table, args).fetchone()[0] if row else '[]'
                    if not zone and self.server.layouts[layout].places == 3:
                        places = place_revisions(db, layout, rev)
        except sqlite3.Error:
            return self.reply(503, {'error':'Garden storage unavailable.'})
        if unchanged:
            return self.reply(304, etag=rev)
        self.reply(200, {'revision':rev, key:json.loads(saved)}, rev, places=places)

    def portrait(self, open_heic=False):
        if self.server.portrait_renderer is None or (open_heic and self.server.heic_reader is None):
            return self.reply(404, {'error':'Unknown path.'})
        if not self.from_garden():
            return self.reply(403, {'error':'Prepare a photo from this garden page.'})
        mime = self.headers.get_content_type()
        if open_heic and mime not in ('image/heic', 'image/heif'):
            return self.reply(415, {'error':'Choose a HEIC photo.'})
        if not open_heic and mime not in garden_portrait.TYPES:
            return self.reply(415, {'error':'Choose a JPEG, PNG or WebP photo.'})
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if not open_heic:
                metadata = self.headers.get_all('X-Oasis-Portrait', [])
                require(len(metadata)==1 and len(metadata[0])<=1024, 'Choose a face and portrait area.')
                options = garden_portrait.request_options(metadata[0], self.server.portrait_sizes)
            require(len(lengths)==1 and re.fullmatch(r'[0-9]{1,12}',lengths[0]) and
                    'Transfer-Encoding' not in self.headers,'An exact photo size is required.')
            size = int(lengths[0])
            require(size>0,'Choose a photo first.')
            if size>garden_portrait.PHOTO_BYTES:
                return self.reply(413, {'error':'The photo exceeds the 16 MB upload limit.'})
        except garden_portrait.PortraitError as error:
            return self.reply(error.status, {'error':str(error)})
        except ValueError as error:
            return self.reply(400, {'error':str(error)})
        if not self.server.portrait_lock.acquire(blocking=False):
            return self.reply(429, {'error':'Another portrait is being prepared. Try again shortly.'},retry_after=5)
        try:
            # Limit wall time as well as idle socket time while holding the one
            # private-photo slot. Never persist these bytes in the room database.
            body = bytearray()
            deadline = time.monotonic()+30
            while len(body)<size:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError
                self.connection.settimeout(min(self.timeout,remaining))
                chunk=self.rfile.read1(min(65536,size-len(body)))
                if not chunk:raise ValueError('Incomplete photo upload.')
                body.extend(chunk)
            self.connection.settimeout(self.timeout)
            result=(self.server.heic_reader(body) if open_heic else self.server.portrait_renderer(body,mime,options))
        except garden_portrait.PortraitError as error:
            return self.reply(error.status,{'error':str(error)})
        except TimeoutError:
            return self.reply(408,{'error':'The photo upload timed out. Try a smaller copy.'})
        except ValueError:
            return self.reply(400,{'error':'The photo could not be read.'})
        except Exception:
            return self.reply(503,{'error':'The laptop could not prepare this photo. Use the ordinary preview.'})
        finally:
            self.server.portrait_lock.release()
        return self.reply(200,result,content_type='image/jpeg' if open_heic else None)

    def do_POST(self):
        if urlsplit(self.path).path == '/api/portrait/heic':
            return self.portrait(open_heic=True)
        if urlsplit(self.path).path == '/api/portrait':
            return self.portrait()
        if urlsplit(self.path).path != '/api/phrase' or self.server.phrase_renderer is None:
            return self.reply(404, {'error':'Unknown path.'})
        if not self.from_garden():
            return self.reply(403, {'error':'Request a drawing from this garden page.'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error':'Expected application/json.'})
        try:
            lengths = self.headers.get_all('Content-Length', [])
            require(len(lengths) == 1 and re.fullmatch(r'[0-9]+', lengths[0]) and
                    'Transfer-Encoding' not in self.headers, 'Body length is required.')
            length = int(lengths[0])
            require(length > 0, 'Empty drawing request.')
            if length > 8192:
                return self.reply(413, {'error':'Drawing request exceeds the size limit.'})
            body = self.rfile.read(length)
            require(len(body) == length, 'Incomplete drawing request.')
            data = json.loads(body.decode('utf-8'))
            fields(data, ('phrase',))
            phrase = data['phrase']
            require(short_text(phrase, 600) and phrase.strip() and '<|' not in phrase
                    and not any(127 <= ord(c) <= 159 or c in '\u2028\u2029' for c in phrase), 'Invalid phrase.')
        except (ValueError, RecursionError, TimeoutError):
            return self.reply(400, {'error':'Use 1–600 characters of ordinary text on one line.'})
        try:
            png = self.server.phrase_renderer(phrase.strip())
        except PhraseBusy:
            return self.reply(429, {'error':'Another drawing is being made. Try again shortly.'}, retry_after=15)
        except Exception:
            return self.reply(503, {'error':'Could not make this drawing. Try again or choose a reference picture.'})
        self.reply(200, png, content_type='image/png')

    def do_PUT(self):
        layout, zone = self.route()
        if not layout or zone:
            return self.reply(404, {'error':'Unknown write path.'})
        attached = self.server.attached
        if attached and layout != attached:
            return self.reply(409, {'error':'This table uses another layout.'})
        if not self.from_garden():
            return self.reply(403, {'error':'Save from this garden page.'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error':'Expected application/json.'})
        try:
            length = int(self.headers.get('Content-Length', ''))
            require(length > 0 and not self.headers.get('Transfer-Encoding'), 'Body length is required.')
            if length > MAX_BODY:
                return self.reply(413, {'error':'Drawing exceeds the size limit.'})
            body = self.rfile.read(length)
            require(len(body) == length, 'Incomplete save.')
            data = json.loads(body.decode('utf-8'))
            fields(data, ('revision','state'), ('motion','automatic'))
            revision, state, motion = data['revision'], data['state'], data.get('motion')
            automatic = data.get('automatic', False)
            require(type(automatic) is bool and (not automatic or (attached and motion and motion['zone'] == 'middle')),
                    'Automatic changes require the attached guest ring.')
            require(type(revision) is int and 0 <= revision < 2**53, 'Invalid revision.')
            spec = self.server.layouts[layout]
            spec.validate(state)
            local = validate_motion(motion, spec)
            guest_zone = motion is not None and motion['zone'] == 'middle'
            has_open = bool(state and spec.open_subject and spec.open_subject in state['ids'] and not state.get('starting'))
            # An unmarked local shortcut must not qualify as a historical full-ring
            # save, including in a shared gallery that has no attached table.
            if motion and motion.get('tour'):
                spec.check_route('middle', motion['files'], state=state, tour=local)
            elif local:
                for trip in local:
                    spec.check_route('middle', trip['files'], place=trip['place'], state=state,
                                     fill=trip.get('fill', False), short_fill=trip.get('shortFill'),
                                     early_from=trip.get('earlyFrom'), add_from=trip.get('addFrom'),
                                     custom_reveal=trip.get('customReveal'))
            elif motion and (attached or guest_zone or has_open or motion.get('centerMode') or motion.get('guestBorder')):
                spec.check_route(motion['zone'], motion['files'], state=state, center_mode=motion.get('centerMode'),
                                 includes_center_rake=motion.get('includesCenterRake',False),
                                 guest_border=motion.get('guestBorder', False), border_order=motion.get('guestBorderOrder'),
                                 border_seat=motion.get('guestBorderSeat'))
        except (ValueError, TypeError, KeyError, PlaybackError, RecursionError, OverflowError):
            return self.reply(400, {'error':'Invalid garden or drawing data.'})
        try:
            with closing(sqlite3.connect(self.server.db, timeout=5)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                current, before = db.execute('SELECT revision,state FROM garden WHERE layout=?', (layout,)).fetchone()
                if current == revision and (not automatic or garden_playback.status(db, layout, self.server.worker)['ready']):
                    previous = json.loads(before)
                    zone = motion['zone'] if motion else None
                    center_mode = motion.get('centerMode') if motion else None
                    was_wide = (previous or {}).get('widePortrait')
                    if state and not state.get('starting'):
                        # An earlier phone editing the border or a guest place
                        # still leaves the center portrait and its viewers in place.
                        if zone != 'center':
                            seats = (previous or {}).get('portraitSeats')
                            if seats is not None and state['portrait'] == previous['portrait']:
                                state.setdefault('portraitSeats', seats)
                            require(state.get('portraitSeats') == seats, 'Seat views belong to the center portrait.')
                        # An older phone can preserve the guest without knowing the field.
                        prior_guest = (previous or {}).get('borderGuest', '')
                        if prior_guest and 'borderGuest' not in state:
                            state['borderGuest'] = prior_guest
                        if zone in ('middle','center'):
                            require(state.get('borderGuest','') == prior_guest, 'Changing this zone cannot rename the border.')
                        if was_wide and zone == 'outer':
                            state.setdefault('widePortrait', True)
                    wide_change = center_mode or (state and (state.get('widePortrait') or (was_wide and not state.get('starting'))))
                    custom_border_change = state and not state.get('starting') and (
                        'guestBorder' in state or 'guestBorder' in (previous or {}))
                    if attached or guest_zone or has_open or wide_change or custom_border_change:
                        border_motion = motion if motion and motion.get('guestBorder') else None
                        spec.check_change(previous, state, zone, local, center_mode, border_motion)
                    carry_kept_drawings(previous, state)
                    packed = json.dumps(state, separators=(',',':'), allow_nan=False)
                    current += 1
                    db.execute('UPDATE garden SET revision=?,state=? WHERE layout=?', (current,packed,layout))
                    if spec.places == 3:
                        stamps = [current] * 3
                        if local:
                            touched = {trip['place'] for trip in local}
                            prior = active_guests(previous or spec.initial)
                            latest = active_guests(state)
                            for i, stamp in enumerate(place_revisions(db, layout, current-1)):
                                if i not in touched and prior[i] == latest[i]:
                                    stamps[i] = stamp
                        db.executemany('UPDATE place_revision SET revision=? WHERE layout=? AND place=?',
                                       [(stamp, layout, i) for i, stamp in enumerate(stamps)])
                    if state is None or state.get('starting'):
                        db.execute('DELETE FROM drawing WHERE layout=?', (layout,))
                    elif motion:
                        files = json.dumps(motion['files'], separators=(',',':'))
                        db.execute('INSERT OR REPLACE INTO drawing VALUES(?,?,?,?)', (layout,motion['zone'],current,files))
                        if center_mode == 'widePortrait':
                            db.execute('DELETE FROM drawing WHERE layout=? AND zone=?', (layout,'middle'))
                        elif center_mode == 'restoreGuests':
                            db.execute('INSERT OR REPLACE INTO drawing VALUES(?,?,?,?)', (layout,'middle',current,files))
                        if attached:
                            garden_playback.enqueue(db, layout, current, motion['zone'], motion['files'])
                    code = 200
                else:
                    code = 409
        except (ValueError, PlaybackError) as error:
            return self.reply(400, {'error':str(error)})
        except sqlite3.Error:
            return self.reply(503, {'error':'Could not save this drawing.'})
        self.reply(code, {'revision':current}, current)


class PhraseBusy(Exception):
    """The laptop is illustrating a different subject."""


class PhrasePreviews:
    """Keep recent illustrations in this room and share an unfinished one between phones."""

    def __init__(self, render):
        self.render = render
        self.lock = threading.Lock()
        self.requests = OrderedDict()

    def __call__(self, phrase):
        with self.lock:
            request = self.requests.get(phrase)
            if request is not None:
                self.requests.move_to_end(phrase)
                start = False
            else:
                if any(not other.done() for other in self.requests.values()):
                    raise PhraseBusy()
                request = self.requests[phrase] = Future()
                start = True
        if start:
            try:
                png = self.render(phrase)
                require(isinstance(png, bytes) and png.startswith(b'\x89PNG\r\n\x1a\n'), 'Invalid drawing.')
            except Exception as error:
                with self.lock:
                    del self.requests[phrase]
                    request.set_exception(error)
            else:
                with self.lock:
                    request.set_result(png)
                    # The local illustrator's 640px line drawings are usually a few KB.
                    if len(png) > 1024 * 1024:
                        del self.requests[phrase]
                    elif len(self.requests) > 16:
                        self.requests.popitem(last=False)
        return request.result()


class RoomServer(ThreadingHTTPServer):
    worker = None

    def server_close(self):
        super().server_close()
        if self.worker:
            self.worker.stop()


def make_server(page, db, bind='127.0.0.1', port=0, *, controller=None, table_layout=None,
                prepared=False, hold_seconds=30, poll_seconds=1, phrase_renderer=None, photo_portraits=False):
    """Return a ready ThreadingHTTPServer; pass a filesystem path for the SQLite db."""
    html, layouts = load_gallery(page)
    portrait_renderer = None
    heic_reader = None
    portrait_sizes = {key:spec.portrait_size for key,spec in layouts.items()
                      if (not table_layout or key==table_layout) and spec.portrait_size and
                      spec.portrait_size[0]/spec.portrait_size[1]>=60}
    require(not re.search(rb'<meta\s+name=["\']oasis-portrait["\']',html,re.I),
            'Expected a local gallery without a portrait room endpoint.')
    if photo_portraits:
        require(portrait_sizes, 'This room needs a wide portrait center to offer laptop photo preparation.')
        original = html.replace(MARKER.encode(),b'',1)
        portrait_renderer = garden_portrait.installed_renderer(original)
        html = html.replace(MARKER.encode(),MARKER.encode()+b'\n'+garden_portrait.MARKER.encode(),1)
        heic_reader = garden_portrait.installed_heic_reader()
        if heic_reader:
            html = html.replace(MARKER.encode(), MARKER.encode()+b'\n'+garden_portrait.HEIC_MARKER.encode(), 1)
    if phrase_renderer is not None:
        require(callable(phrase_renderer), 'Expected a phrase renderer.')
        html = html.replace(MARKER.encode(), MARKER.encode() + b'\n' + PHRASE_MARKER.encode(), 1)
    path = str(Path(db).resolve())
    require((controller is None and table_layout is None and not prepared) or
            (controller is not None and table_layout in layouts), 'Select exactly one attached table and layout.')
    worker = None
    bound_edition = None
    starting_files = None
    if controller:
        spec = layouts[table_layout]
        spec.check_route('setup', spec.setup)
        worker = garden_playback.Worker(path, table_layout, controller, hold_seconds, poll_seconds)
        marker = f'<meta name="oasis-table-layout" content="{table_layout}">'.encode()
        html = html.replace(MARKER.encode(), MARKER.encode() + b'\n' + marker, 1)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute("SELECT 1 FROM sqlite_master WHERE name='garden'").fetchone()
        conn.execute('CREATE TABLE IF NOT EXISTS attachment(id INTEGER PRIMARY KEY CHECK(id=1), layout TEXT, board TEXT, geometry TEXT)')
        binding = conn.execute('SELECT layout,board,geometry FROM attachment WHERE id=1').fetchone()
        if controller:
            if binding:
                if binding[0] == table_layout:
                    bound_edition = spec.bound_edition(binding[2])
                require(bound_edition is not None, 'Use the database and gallery for this physical layout.')
                controller.bind_identity(binding[1])
                if binding[2] != spec.signature:
                    conn.execute('UPDATE attachment SET geometry=? WHERE id=1', (spec.signature,))
            else:
                require(prepared and not existing, 'A new physical session needs a fresh database and prepared sand.')
                board = controller.bind_identity()
                controller.check(spec.setup[0])
                conn.execute('INSERT INTO attachment VALUES(1,?,?,?)', (table_layout,board,spec.signature))
            garden_playback.init_schema(conn)
            # Playback retires completed part data. Pin the exact original
            # preparation separately, including when reopening a pre-pin database.
            conn.execute('CREATE TABLE IF NOT EXISTS attachment_setup(id INTEGER PRIMARY KEY CHECK(id=1), files TEXT NOT NULL)')
            pinned = conn.execute('SELECT files FROM attachment_setup WHERE id=1').fetchone()
            if pinned:
                starting_files = json.loads(pinned[0])
            else:
                old = spec.previous_opening
                old_bound = bound_edition and old and bound_edition in (old['edition'],old.get('legacyBedEdition'))
                starting_files = old['setup'] if old_bound else spec.setup
                conn.execute('INSERT INTO attachment_setup VALUES(1,?)', (json.dumps(starting_files,separators=(',',':')),))
            if binding is None:
                garden_playback.enqueue(conn, table_layout, 0, 'setup', starting_files)
        else:
            require(binding is None or binding[0] is None, 'Reopen this physical session with its attached table.')
            conn.execute('INSERT OR IGNORE INTO attachment VALUES(1,NULL,NULL,NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS garden(layout TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS drawing(layout TEXT NOT NULL, zone TEXT NOT NULL, revision INTEGER NOT NULL, files TEXT NOT NULL, PRIMARY KEY(layout,zone))')
        conn.execute('''CREATE TABLE IF NOT EXISTS place_revision(
            layout TEXT NOT NULL, place INTEGER NOT NULL CHECK(place BETWEEN 0 AND 2),
            revision INTEGER NOT NULL, PRIMARY KEY(layout,place))''')
        for key, spec in layouts.items():
            conn.execute("INSERT OR IGNORE INTO garden VALUES(?,0,'null')", (key,))
            revision, saved = conn.execute('SELECT revision,state FROM garden WHERE layout=?', (key,)).fetchone()
            state = json.loads(saved)
            old = spec.previous_opening
            old_editions = {old['edition'], old['previousEdition']} if old else set()
            if key == table_layout and bound_edition and bound_edition != spec.edition:
                # Only the matched physical binding identifies an old bed-only edition.
                old_editions.add(bound_edition)
            if (state is None and key == table_layout and old and bound_edition
                    and bound_edition in (old['edition'], old.get('legacyBedEdition'))):
                # No phone ever kept an edit. The table nevertheless has its own
                # opening queued or on display. Its stored files must keep playing.
                state = dict(spec.initial, bed=old['bed'], labels={}, edition=old['edition'], starting=True)
            if isinstance(state, dict) and state.get('edition') in old_editions:
                state['edition'] = spec.edition  # Saved pixels, photos and jobs keep their original meaning.
                conn.execute('UPDATE garden SET state=? WHERE layout=?',
                             (json.dumps(state, separators=(',', ':'), ensure_ascii=False), key))
            spec.validate(state)
            if spec.places == 3:
                conn.executemany('INSERT OR IGNORE INTO place_revision VALUES(?,?,?)',
                                 [(key, place, revision) for place in range(3)])
    server = RoomServer((bind,port), RoomHandler)
    server.gallery, server.layouts, server.db, server.attached = html, layouts, path, table_layout
    server.phrase_renderer = PhrasePreviews(phrase_renderer) if phrase_renderer is not None else None
    server.portrait_renderer = portrait_renderer
    server.heic_reader = heic_reader
    server.portrait_lock = threading.Lock()
    server.portrait_sizes = portrait_sizes
    server.starting_files = starting_files
    try:
        server.compressed = gzip.compress(html, compresslevel=5, mtime=0)
        if worker:
            server.worker = worker.start()
    except BaseException:
        server.server_close()
        raise
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--table-url', help='Origin of a calibrated table running our tagged player firmware')
    parser.add_argument('--table-layout', choices=('garden','portrait'))
    parser.add_argument('--view-seconds', type=float, default=30)
    parser.add_argument('--photo-portraits', action='store_true', help='Let guests explicitly send a photo to this room laptop for offline wide-center portraits')
    parser.add_argument('--phrase-drawings', action='store_true', help='Let guests preview unfamiliar subjects using the offline model installed on this host')
    parser.add_argument('--prepared', action='store_true', help='Start the initial layout on prepared sand at its rim dock, using a fresh database')
    args = parser.parse_args()
    renderer = None
    if args.phrase_drawings:
        from phrase_drawing import installed_renderer
        try:
            renderer = installed_renderer()
        except ValueError as error:
            parser.error(str(error))
    try:
        server = make_server(args.page,args.db,args.bind,args.port,
                             controller=OasisPlayer(args.table_url) if args.table_url else None,
                             table_layout=args.table_layout,prepared=args.prepared,hold_seconds=args.view_seconds,
                             phrase_renderer=renderer,photo_portraits=args.photo_portraits)
    except (ImportError,ValueError) as error:
        parser.error(str(error))
    with server:
        print(f'http://{args.bind}:{server.server_port}/garden', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
