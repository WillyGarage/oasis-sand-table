"""Verify signed guest fills against their gallery's frozen gates and full engraving."""

import numpy as np

import check_ring_scene as check
from test_guest_place import unpack


def original_excursion(page, catalog, state, slot):
    subject = state['ids'][slot]
    if subject in catalog['excursions'][slot]:
        return unpack(catalog['excursions'][slot][subject])
    # A freehand or typed drawing has no stock route. Generate its original
    # gate-to-gate path using the gallery's conventional fill, with both short
    # entries removed. Callers also compare its ink to the user's saved strokes.
    assert subject in state['custom']
    return np.asarray(page.evaluate("""([ids,custom,slot])=>{
        const c=JSON.parse(document.querySelector('#scene').textContent).live.planner;
        delete c.places[slot].shortFill;
        const previous=ids.slice(); previous[slot]=c.openSubject;
        return OasisRingPlanner.planChange(c,previous,ids,custom).art;
    }""", [state['ids'], state['custom'], slot]))


def joined(parts):
    return check.joined(parts, parts[0][0], parts[-1][-1], 'expected guest fill')


def fill_sections(catalog, slot, engraving, side):
    place = catalog['places'][slot]
    if side is None:
        return unpack(place['approach']), engraving, unpack(place.get('fillExit', place['exit']))
    assert side in ('left','right') and side in place['shortFill']
    off_rail = np.flatnonzero(abs(engraving[:,1] - catalog['geometry']['rail']) > 1e-7)
    assert len(off_rail) and off_rail[0] > 0 and off_rail[-1] < len(engraving)-1
    start, end = off_rail[0]-1, off_rail[-1]+1
    rail_lead = engraving[:start+1] if side == 'left' else engraving[end:][::-1]
    entry = joined([unpack(place['shortFill'][side]), rail_lead])
    return entry, engraving[start:end+1], entry[::-1]


def checked_fill(route, catalog, slot, engraving, side=...):
    # A standalone HTML download has no room receipt to name the entrance.
    # Match the entire signed route to a permitted entrance in that case.
    sides = [None, *catalog['places'][slot].get('shortFill', {})] if side is ... else [side]
    for candidate in sides:
        entry, body, exit_path = fill_sections(catalog, slot, engraving, candidate)
        if check.same_track(route, joined([entry, body, exit_path])):
            start = len(entry)-1
            end = start+len(body)-1
            return route[:start+1], route[start:end+1], route[end:]
    raise AssertionError(f'Guest place {slot} changed its approach, engraving or return ({sides})')


def tour_legs(catalog, parts):
    order = [part['place'] for part in parts]
    key = '-'.join(str(slot) for slot in sorted(order))
    matching = [legs for legs in catalog['fillTours'][key] if [leg['place'] for leg in legs] == order]
    assert len(matching) == 1 and all('shortFill' not in part for part in parts)
    return matching[0]


def check_tour_leg(route, leg, engraving):
    sections = [unpack(leg['approach']), engraving]
    if leg.get('exit'):
        sections.append(unpack(leg['exit']))
    assert check.same_track(route, joined(sections)), 'The signed tour changed its approach, engraving or exit.'
