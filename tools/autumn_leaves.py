"""Continuous maple and oak engravings for the ten-sector outer ring."""
import math

import numpy as np


# Species, lean from the inward radial direction, shift along the twig, twig bow.
COMPOSITION = (
    ('maple', 28, -.03, .043), ('oak', 57, .03, -.035),
    ('oak', -50, .06, .046), ('maple', -33, -.03, .018),
    ('oak', 61, -.03, -.047), ('maple', 19, .04, .030),
    ('maple', -27, -.04, -.034), ('oak', -60, .04, .041),
    ('maple', 35, .02, .047), ('oak', 49, -.04, -.020),
)


def cubic(start, handle1, handle2, end):
    p = np.array([start, handle1, handle2, end], dtype=float)
    t = np.linspace(0, 1, 11)[:, None]
    return (1-t)**3*p[0] + 3*(1-t)**2*t*p[1] + 3*(1-t)*t**2*p[2] + t**3*p[3]


def chain(*paths):
    return np.vstack([paths[0], *(part[1:] for part in paths[1:])])


def maple():
    # Five main points, with a smaller tooth on either shoulder of the crown.
    # Round the sinuses while retaining the abrupt changes of direction at the tips.
    corners = np.array([
        (0, 0), (-.25,-.005), (-.56,.085), (-.42,.22), (-.27,.255),
        (-.45,.40), (-.63,.62), (-.46,.57), (-.42,.735), (-.17,.49),
        (-.17,.76), (-.10,.72), (.015,1.05), (.105,.73), (.17,.78),
        (.175,.51), (.42,.73), (.45,.58), (.60,.61), (.45,.39),
        (.29,.245), (.43,.22), (.54,.09), (.27,.015),
    ])
    turns = {0:.12, 2:.018, 6:.015, 8:.025, 12:.015, 14:.025, 16:.025, 18:.018, 22:.018}
    pieces = []
    for i, point in enumerate(corners):
        radius = turns.get(i,.17)
        start = point + radius*(corners[i-1]-point)
        end = point + radius*(corners[(i+1)%len(corners)]-point)
        t = np.linspace(0,1,5)[:,None]
        pieces.append((1-t)**2*start + 2*(1-t)*t*point + t**2*end)
    # Sample the straight sides too: polar interpolation of a single long chord
    # would otherwise bend an edge near the corner of its sector.
    outline = [np.array([0.,0.])]
    for turn in pieces[1:]:
        outline.extend(np.linspace(outline[-1], turn[0], 8)[1:])
        outline.extend(turn[1:])
    outline.extend(np.linspace(outline[-1], (0,0), 8)[1:])
    veins = []
    for handles in [
        ((-.06,.17),(-.22,.34),(-.345,.45)),
        ((.005,.20),(-.015,.48),(.012,.70)),
        ((.06,.18),(.21,.34),(.35,.445)),
    ]:
        vein = cubic((0,0), *handles)
        veins.extend([vein, vein[::-1]])
    return chain(np.array(outline), *veins)


def oak():
    # A white oak blade broadens toward its rounded crown. Three obtuse lobes
    # on each side leave deep, smooth sinuses; the two banks are asymmetric.
    rows = [
        ((-.035,.050),(-.105,.064),(-.155,.072)),
        ((-.245,.078),(-.255,.207),(-.145,.221)),
        ((-.070,.230),(-.089,.269),(-.169,.290)),
        ((-.328,.308),(-.333,.468),(-.197,.476)),
        ((-.107,.479),(-.107,.530),(-.189,.552)),
        ((-.384,.595),(-.326,.784),(-.184,.753)),
        ((-.091,.732),(-.102,.797),(-.134,.848)),
        ((-.173,.924),(-.104,1.018),(-.021,1.018)),
        ((.078,1.018),(.160,.920),(.138,.842)),
        ((.076,.778),(.091,.749),(.173,.770)),
        ((.326,.831),(.356,.653),(.226,.590)),
        ((.110,.549),(.099,.505),(.201,.508)),
        ((.352,.518),(.330,.334),(.200,.315)),
        ((.092,.291),(.089,.245),(.167,.238)),
        ((.280,.226),(.259,.106),(.167,.095)),
        ((.085,.088),(.038,.048),(0,0)),
    ]
    outline = []
    start = (0,0)
    for handles in rows:
        outline.append(cubic(start, *handles))
        start = handles[-1]
    # Walk the central vein in order and return from every side branch on its
    # own groove. Each endpoint stays inside a broad lobe.
    low, high = (.012,.29), (-.010,.54)
    lower = cubic((0,0),(.006,.08),(.019,.19),low)
    middle = cubic(low,(.008,.38),(-.009,.45),high)
    upper = cubic(high,(-.014,.65),(.005,.76),(.012,.865))
    side1 = cubic(low,(-.045,.31),(-.122,.39),(-.198,.412))
    side2 = cubic(high,(.048,.56),(.15,.664),(.225,.693))
    return chain(*outline, lower, side1, side1[::-1], middle, side2, side2[::-1],
                 upper, upper[::-1], middle[::-1], lower[::-1])


def autumn_leaf(index):
    """Return one leaf and its twig from (-1,.16) to (1,.16); depth runs inward."""
    species, degrees, shift, bow = COMPOSITION[index % len(COMPOSITION)]
    blade = maple() if species == 'maple' else oak()
    # Work in physical proportions first. At the center of the proposed band a
    # sector's half-arc is 1.34 times its radial width.
    angle = math.radians(degrees)
    u, v = blade.T
    xx = u*math.cos(angle) + v*math.sin(angle)
    yy = -u*math.sin(angle) + v*math.cos(angle)
    # Let the tips sit at different depths; the outer ring already supplies
    # an inner frame and needs a little open sand between it and the leaves.
    rise = .685 + .028*math.cos(math.tau*(3*index+1)/10)
    scale = rise/(yy.max()-yy.min())
    # Spread the five maple lobes and lay the longer oak blade along the twig.
    # This gives both outlines room for clean sand between the side veins.
    stretch = 1.33 if species == 'maple' else 1.46
    x_scale = scale*stretch/1.34
    origin = np.array([shift - x_scale*(xx.max()+xx.min())/2, .222 - scale*yy.min()])
    drawing = origin + np.column_stack((x_scale*xx, scale*yy))
    direction = math.copysign(1., degrees)
    node = origin[0] - direction*.21

    def twig(x):
        depth = .16 + .044*np.sin(math.pi*(x+1)) + bow*np.sin(math.pi*(x+1)/2)**2
        return np.column_stack((x,depth))

    left = twig(np.linspace(-1.,node,39))
    right = twig(np.linspace(node,1.,39))
    left[0] = (-1., .16)
    right[-1] = (1., .16)
    petiole = cubic(left[-1], left[-1]+[direction*.09,.015],
                    origin-[.06*stretch*math.sin(angle)/1.34,.06*math.cos(angle)], origin)
    return chain(left, petiole, drawing, petiole[::-1], right)
