"""Guest-sized pie engravings."""
import numpy as np

from autumn_leaves import chain, cubic


def pumpkin_pie():
    """A closed, upright engraving in one guest place. The cream overlaps the far cut edge."""
    tip = np.array([-.89, -.20])
    back = np.array([-.10, .57])
    near = np.array([.77, .06])
    tip_filling, tip_bottom = (-.865, -.40), (-.845, -.57)
    near_filling, near_bottom = (.73, -.25), (.71, -.43)

    # The long cut face exposes smooth pumpkin filling and a thinner pastry base.
    filling = cubic(tip_filling, (-.42, -.386), (.31, -.27), near_filling)
    base = cubic(near_bottom, (.25, -.50), (-.46, -.587), tip_bottom)
    cut_face = chain([near, near_filling, near_bottom], base,
                     [tip_bottom, tip_filling, tip, tip_filling], filling, [near_filling, near])

    # The two banks of the curved crust share their ends. Three wide crimps read
    # on the far bank even when one groove occupies an eighth of the picture radius.
    t = np.linspace(0, 1, 73)
    chord = near - back
    outward = np.array([-chord[1], chord[0]]) / np.linalg.norm(chord)
    bow = np.sin(np.pi*t)
    smooth = back + t[:, None]*chord + (.15*bow)[:, None]*outward
    flute = (.18 + .12*np.sin(3*np.pi*t)**2) * bow**.58
    scalloped = smooth + flute[:, None]*outward
    smooth[[0, -1]] = scalloped[[0, -1]] = [back, near]

    # Let the far edge disappear behind the cream. Both ways through its outline
    # are part of the dollop, so the ball never needs to cut across the pie's top.
    left = tip + .47*(back-tip)
    right = tip + .85*(back-tip)
    peak = (-.275, .78)
    upper = chain(cubic(right, (-.14, .59), (-.26, .65), peak),
                  cubic(peak, (-.45, .739), (-.507, .582), (-.47, .506)),
                  cubic((-.47, .506), (-.648, .443), (-.661, .244), left))
    lower = chain(cubic(left, (-.50, .084), (-.21, .047), (-.07, .153)),
                  cubic((-.07, .153), (.019, .219), (.002, .30), (-.06, .338)),
                  cubic((-.06, .338), (.009, .400), (-.02, .496), right))
    far_edge = chain([tip, left], upper[::-1], lower[::-1], lower, [right, back])
    path = chain(far_edge, scalloped, cut_face, smooth[::-1], smooth, [near, tip])
    return path * (.977 / np.linalg.norm(path, axis=1).max())


def lattice_pie():
    """Six pastry strips cross a whole pie in a fluted shell."""
    tau = 2*np.pi

    def rim(angle):
        radius = 1 + .062*np.cos(12*angle)
        return np.array([np.cos(angle)*radius, .74*np.sin(angle)*radius + .058])

    def crust(start, end):
        angles = np.linspace(start, end, 2 + int((end-start)*48))
        return np.array([rim(angle) for angle in angles])

    # Walk each strip from the rim and back along itself. This keeps the
    # spaces between the lattice free of entrance and return grooves.
    visits = {}
    for slope in (-1, 1):
        direction = np.array([1., slope]) / np.sqrt(2)
        normal = np.array([-slope, 1.]) / np.sqrt(2)
        for offset in (-.51, 0., .51):
            reach = np.sqrt(1-offset**2) * direction
            ends = (offset*normal-reach, offset*normal+reach)
            angles = [np.arctan2(y,x) % tau for x,y in ends]
            left, right = map(rim, angles)
            span = right-left
            strip = cubic(left, left+.3*span+[0,.03], left+.7*span+[0,.03], right)
            visits[angles[0]] = chain(strip, strip[::-1])

    # The broad, shallow front edge is visible below the pastry.
    lower = chain(cubic(rim(np.pi), (-.96,-.26), (-.79,-.60), (-.68,-.75)),
                  cubic((-.68,-.75), (-.49,-.89), (.49,-.89), (.68,-.75)),
                  cubic((.68,-.75), (.79,-.60), (.96,-.26), rim(0)))
    visits[np.pi] = chain(lower, lower[::-1])
    parts = []
    start = 0.
    for angle, visit in sorted(visits.items()):
        parts.extend((crust(start,angle), visit))
        start = angle
    path = chain(*parts, crust(start,tau))
    path -= (path.max(axis=0) + path.min(axis=0)) / 2
    return path * (.96 / np.linalg.norm(path, axis=1).max())
