"""Restore a guest's part of a spiral background while matching the existing ridges."""
import math

import numpy as np

from ring_scene import join, line
from sandsim import U_MAX, _profile_luts


def _outward_shift(pitch, groove):
    """Align the shoulders left by outward passes with those on the original inward bed."""
    # In overlapping furrows the last ball pass sets the slope. Even the exact
    # same centerlines can put an inward bed's dark groove on the opposite side
    # of an outward bed. Register one repeating cross-section of the two beds,
    # using the same groove profile as the large-table sand preview.
    depth, mix = _profile_luts()
    support = np.linspace(0, U_MAX, len(mix))
    samples = 128
    radial = np.arange(samples)*pitch/samples
    reach = math.ceil(U_MAX*groove/(2*pitch))+1
    lanes = pitch*np.arange(-reach, reach+2)

    def relief(centers):
        height = np.zeros(samples)
        for center in centers:
            distance = 2*np.abs(radial-center)/groove
            strength = np.interp(distance, support, mix, right=0)
            height += strength*(np.interp(distance, support, depth, right=0)-height)
        return height

    inward, outward = relief(lanes[::-1]), relief(lanes)
    errors = [np.mean((inward-np.roll(outward,k))**2) for k in range(samples)]
    return pitch*int(np.argmin(errors))/samples


def spiral_sector(zone, left, right, groove):
    """Return a left/high-to-left/high brush using only the selected angular sector."""
    gate, high = zone['transit'][-1]
    native = np.asarray(zone['erase'], dtype=float)
    inward = np.flatnonzero(np.diff(native[:, 1]) < -1e-9)
    if not inward.size or np.any(np.diff(inward) != 1):
        raise ValueError('The guest border needs a continuous inward background spiral.')
    sweep = native[inward[0]:inward[-1]+2]
    low = sweep[-1, 1]
    turns = round((sweep[-1, 0]-sweep[0, 0])/math.tau)
    if (turns < 1 or not np.isclose(sweep[0, 1], high, atol=1e-7, rtol=0)
            or not np.all(np.diff(sweep[:, 0]) > 0)
            or abs(sweep[-1, 0]-sweep[0, 0]-turns*math.tau) > 1e-6
            or abs(math.remainder(sweep[0, 0]-gate, math.tau)) > 1e-6
            or not (0 < low < high <= 1 and 0 < (high-low)/turns <= groove+1e-7)
            or not (gate-1e-7 <= left < right <= gate+math.tau+1e-7)):
        raise ValueError('The selected border section does not fit its calibrated spiral.')

    pitch = (high-low)/turns
    shift = _outward_shift(pitch, groove)

    def radius(turn, angle):
        # Preserve the original sweep's pitch and angular phase. The added
        # partial turn at the inner edge covers the strip revealed by shifting.
        original = np.interp(sweep[0, 0]+min(turn,turns-1)*math.tau+(angle-gate),
                             sweep[:, 0], sweep[:, 1])
        return np.clip(original+shift-(pitch if turn==turns else 0), low, high)

    mid = (left+right)/2
    blend = (right-left)*.40
    start, stop = mid+blend/2, mid-blend/2
    theta = np.linspace(start, stop, max(3, math.ceil(blend/.006)+1))
    t = np.linspace(0, 1, len(theta))
    ease = t*t*(3-2*t)
    # The initial radial admission is inside the old guest picture. The
    # outward sweep covers it before any new picture is engraved.
    parts = [line(left,high,start,high), line(start,high,start,low),
             line(start,low,left,low), line(left,low,right,low), line(right,low,start,low)]
    previous = np.full(len(theta),low)
    for turn in range(turns, -1, -1):
        current = radius(turn,theta)
        # Change grooves across the middle of the seat, then retrace that area
        # on the new arc. At both joins the ball reverses on the spiral;
        # its move to the next row stays well inside the guest's place.
        parts.extend((np.column_stack((theta,(1-ease)*previous+ease*current)),
                      line(stop,current[-1],left,radius(turn,left)),
                      line(left,radius(turn,left),right,radius(turn,right)),
                      line(right,radius(turn,right),start,current[0])))
        previous = current
    parts.extend((np.column_stack((theta,(1-ease)*previous+ease*high)),
                  line(stop,high,right,high),line(right,high,left,high)))
    return join(*parts)
