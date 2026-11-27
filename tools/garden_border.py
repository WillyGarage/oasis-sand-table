"""Check a downloaded three-guest border against the saved drawings in chair coordinates."""
import math

import numpy as np

from check_ring_scene import TOL, check_sampled_strokes, require, same_track, seam_segments


def make_sectors(zone, angles, pitch, groove):
    """Prepare independent full-width rakes for each chair and the laurel between chairs."""
    from guest_spiral_sector import spiral_sector
    from ring_scene import fluted_sector, pack_path

    gate, high = zone['transit'][-1]
    low = min(point[1] for point in zone['erase'])
    inner = low + .6*groove
    reserve = math.atan2(.725*(high-low), inner) + 1.8*groove/inner
    chairs = sorted((gate+(angle-gate)%math.tau, slot) for slot, angle in enumerate(angles))
    spans = []
    start = gate
    for angle, slot in chairs:
        left, right = angle-reserve, angle+reserve
        if left <= start or right >= gate+math.tau:
            return []
        spans.extend([(start, left, None), (left, right, slot)])
        start = right
    spans.append((start, gate+math.tau, None))
    sectors = []
    for left, right, slot in spans:
        sweep = fluted_sector(low, high, pitch, groove, left, right, smooth_edges=True)
        sector = dict(left=left, right=right, slot=slot, clear=pack_path(sweep))
        if slot is not None:
            sector['spiral'] = pack_path(spiral_sector(zone,left,right,groove))
        sectors.append(sector)
    return sectors


def grain_probes(zone, sectors, size, groove):
    """Sample relief in two directions between the chairs, away from the circular frames."""
    low = min(point[1] for point in zone['erase'])
    high = zone['transit'][-1][1]
    radius_px = (size-1)/2

    probes = []
    for sector in sectors:
        if sector['slot'] is None:
            continue
        # Just outside either end of a seat the laurel rises to the high
        # rail. The exposed columns between the frames contain background
        # only, including after editing drawings on every chair.
        for edge, sign in ((sector['left'],-1),(sector['right'],1)):
            for depth in np.linspace(.32,.67,12):
                r = low+depth*(high-low)
                for offset in np.linspace(1.2,2.4,7):
                    angle = edge+sign*offset*groove/r
                    cosine, sine = math.cos(angle), math.sin(angle)
                    x = round(radius_px*(1+r*cosine))
                    y = round(radius_px*(1-r*sine))
                    # Leave room for the adjacent pixels used to measure the slope.
                    if 0 < x < size-1 and 0 < y < size-1:
                        probes.append([y*size+x, round(cosine,5), round(sine,5)])
    return probes


def stored_grain(encoded, probes):
    """Circular tracks vary most with radius. Radial flutes vary most around the rim."""
    import base64

    values = np.frombuffer(base64.b64decode(encoded), dtype=np.uint8)
    size = math.isqrt(len(values))
    indices, cosine, sine = np.asarray(probes).T
    indices = indices.astype(np.intp)
    dx = values[indices+1].astype(float)-values[indices-1]
    dy = values[indices+size].astype(float)-values[indices-size]
    across_rings = np.sum((dx*cosine-dy*sine)**2)
    across_flutes = np.sum((dx*sine+dy*cosine)**2)
    return 'spiral' if across_rings > across_flutes else 'fluted'


def fitted_vertices(shape, inner, outer, max_width):
    # Keep every vertex inside the outside circle and every straight chord on
    # the chair side of the inner tangent. Center the drawing across the seat.
    points = np.asarray(shape)[:-1]
    x, y = points.T
    width = np.ptp(x)
    x = x - (x.min()+x.max())/2
    depth = y.max()-y
    area = outer**2-inner**2
    denominator = np.hypot(inner*depth, np.hypot(x,depth)*math.sqrt(area)) + inner*depth
    scale = area / max(denominator)
    if width > 0:
        scale = min(scale, max_width/width)
    tangent = scale*x
    center = min(np.sqrt(outer**2-tangent**2) + scale*y)
    placed = np.column_stack((tangent,center-scale*y))
    entry = np.flatnonzero(np.hypot(*placed.T) >= outer-1e-9)
    require(len(entry), 'The guest artwork must attach at its outside edge.')
    start = entry[0]
    return np.vstack((placed[start:], placed[:start+1]))


def check_art(route, sources, angles, bounds, groove, dock, *, start_angle=None):
    low, high = bounds
    width = high-low
    inner, outer = low+.6*groove, high-1.8*groove
    require(outer > inner > 0, 'The border is too narrow for guest drawings.')
    reserve = math.atan2(.725*width,inner) + 1.8*groove/inner
    start = dock if start_angle is None else start_angle
    theta = route[:,0] - math.tau*round((route[0,0]-start)/math.tau)
    rho = route[:,1]
    require(np.all((theta >= dock-TOL) & (theta <= dock+math.tau+TOL)),
            'The guest garland must stay within one turn around the chairs.')
    on_rail = abs(rho-high) <= TOL
    for position, source in zip(angles,sources,strict=True):
        heading = theta - (dock+(position-dock)%math.tau)
        # Include a long segment crossing the seat, even if both vertices are
        # outside it. The laurel in the neighboring gaps ends at the rail.
        inside = (np.maximum(heading[:-1],heading[1:]) > -reserve+TOL) & (
                  np.minimum(heading[:-1],heading[1:]) < reserve-TOL)
        allowed = on_rail[:-1] & on_rail[1:]
        if source is not None:
            vertices = fitted_vertices(source['points'],inner,outer,1.45*width)
            ink = np.flatnonzero((abs(heading) < reserve) & (rho <= outer+TOL))
            require(len(ink) >= 4, 'Missing artwork at a guest’s chair.')
            first, end = ink[0], ink[-1]
            angles_ink = heading[first:end+1]
            radii_ink = rho[first:end+1]
            actual = radii_ink[:,None]*np.column_stack((np.sin(angles_ink), np.cos(angles_ink)))
            check_sampled_strokes(actual, vertices)
            allowed[first:end] = True
            attachment = math.atan2(*vertices[0])
            on_hanger = (abs(heading-attachment) <= TOL) & (rho >= outer-TOL)
            allowed |= on_hanger[:-1] & on_hanger[1:]
        require(np.all(~inside | allowed), 'Unexpected stroke across a guest’s border artwork.')


def check_sections(route, sectors, sources, angles, bounds, groove, dock, *, place=None, grain='fluted'):
    """Check one requested seat or a complete progressive pass around the guest border."""
    low, high = bounds
    if place is None:
        occupied = [i for i,s in enumerate(sectors) if s['slot'] is not None and sources[s['slot']] is not None]
        require(occupied, 'The border needs at least one guest drawing.')
        first = min(occupied, key=lambda i: abs(math.remainder(sectors[i]['left']-dock, math.tau)))
        order = [(first+i)%len(sectors) for i in range(len(sectors))]
    else:
        order = [i for i,sector in enumerate(sectors) if sector['slot'] == place]
        require(len(order) == 1 and sources[place] is not None, 'Select one guest drawing on the rim.')
    start = dock + math.remainder(sectors[order[0]]['left']-dock, math.tau)
    angle = start
    offset = 0
    cuts = []
    for idx in order:
        sector = sectors[idx]
        sweep = sector['spiral'] if grain == 'spiral' else sector['clear']
        remaining = route[offset:]
        at_left = (abs(remaining[:,0]-angle) <= TOL) & (abs(remaining[:,1]-high) <= TOL)
        match = next((offset+k for k in np.flatnonzero(at_left)
                      if same_track(remaining[k:k+len(sweep)], sweep)), None)
        require(match is not None, 'The border needs a complete clearing pass at every section.')
        offset = match+len(sweep)-1
        cuts.append((idx, angle, match, offset))
        angle += sector['right']-sector['left']
    at_end = (abs(route[offset:,0]-angle) <= TOL) & (abs(route[offset:,1]-high) <= TOL)
    ends = np.flatnonzero(at_end)
    require(len(ends), 'Finish the last garland section at the rim.')
    last_end = offset+ends[0]

    # In either direction the only connection to the first chair is the
    # short arc of the outer frame plus the already-cut radial access.
    for approach, corner in ((route[:cuts[0][2]+1],start), (route[last_end:],angle)):
        rail = abs(approach[:,1]-high) <= TOL
        allowed = (rail[:-1] & rail[1:]) | seam_segments(approach,dock)
        if place is not None:
            require(np.all(approach[:,1] >= high-TOL), 'A seat change must leave the access groove below the rim alone.')
        expected_angle = abs(math.remainder(corner-dock,math.tau))
        travel_angle = np.sum(abs(np.diff(approach[:,0])))
        require(np.all(allowed) and abs(travel_angle-expected_angle) < 3*TOL,
                'Use the short outer frame between the guest garland and its access groove.')

    # Remove only the verified clearing paths. Reassemble the remaining
    # engravings in chair order so whole and progressive use one art check.
    engravings = [None]*len(sectors)
    for i,(idx,left,_,clear_end) in enumerate(cuts):
        sector = sectors[idx]
        end = cuts[i+1][2] if i+1 < len(cuts) else last_end
        art = route[clear_end:end+1].copy()
        art[:,0] += sector['left']-left
        require(np.all((art[:,0] >= sector['left']-TOL) & (art[:,0] <= sector['right']+TOL)),
                'Engrave each section before entering the next one.')
        engravings[idx] = art
    if place is None:
        check_art(np.vstack(engravings), sources, angles, bounds, groove, dock)
    else:
        idx = order[0]
        check_art(engravings[idx], [sources[place]], [angles[place]], bounds, groove, dock,
                  start_angle=sectors[idx]['left'])
