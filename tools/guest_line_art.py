"""Chair-sized engravings. The folded-wing crane is an original drawing.

Origami, ChefHat and Caravan use 0.453.0. Birdhouse, Anvil, RockingChair,
WashingMachine and CookingPot use 0.562.0. Source centerlines are joined on
the 24-unit grid for a continuous walk. See guest_line_art-LICENSE.txt.
"""
import numpy as np

from autumn_leaves import chain, cubic


def _arc(center, radius, start, end):
    """A circular arc, in the original drawing's x-right, y-down coordinates."""
    angles = np.deg2rad(np.linspace(start, end, 1 + int(np.ceil(abs(end - start) / 7.5))))
    return np.round(center + radius * np.column_stack((np.cos(angles), np.sin(angles))), 12)


def _engraving(*strokes):
    """Join at shared vertices, turn upright and fit the guest's unit disc."""
    for previous, following in zip(strokes, (*strokes[1:], strokes[0])):
        if not np.allclose(previous[-1], following[0], rtol=0, atol=1e-9):
            raise ValueError("Guest engraving has a break between strokes")
    walk = chain(*strokes)
    centered = walk - (walk.min(axis=0) + walk.max(axis=0)) / 2
    return centered * [1, -1] * (.89 / np.linalg.norm(centered, axis=1).max())


def coffee_grinder():
    """A hand mill with an open hopper, bent crank and drawer in a wooden case."""
    rim = (20, 34)
    lip = (44, 40)
    right = (68, 34)
    neck = (50, 54)
    left_foot = (37, 54)
    case = (15, 56)
    corner = (64, 56)
    back = (79, 48)
    # Reach the crank through the center of the open hopper. Return in its groove.
    crank = chain([lip, (44, 19)], cubic((44, 19), (55, 16), (62, 24), (72, 21)),
                  [(72, 21), (83, 17), (83, 12)])
    knob = chain(cubic((83, 12), (77, 11), (76, -2), (82, -3)),
                 cubic((82, -3), (90, -5), (91, 12), (83, 12)))
    bowl = chain(cubic(rim, (22, 25), (65, 25), right),
                 cubic(right, (68, 38), (54, 41), lip),
                 crank, knob, crank[::-1], cubic(lip, (31, 40), (20, 39), rim),
                 cubic(rim, (21, 42), (29, 51), left_foot),
                 [left_foot, neck], cubic(neck, (60, 50), (66, 41), right))
    # The drawer pull hangs from its upper edge. Each transit uses a case seam.
    drawer = chain([(15, 68), (32, 68)],
                   cubic((32, 68), (32, 81), (47, 81), (47, 68)),
                   [(47, 68), (64, 68), (15, 68)])
    box = chain(cubic(right, (66, 41), (60, 50), neck),
                [neck, (60, 48), back, (79, 84), (64, 92), corner, back, corner,
                 case, (15, 68)], drawer, [(15, 68), (15, 92), (64, 92), corner, case, left_foot])
    return _engraving(bowl, box, cubic(left_foot, (29, 51), (21, 42), rim))


def paper_bird():
    """A folded paper bird, with a triangular beak and a crease along its wing."""
    crown, under_beak = (12.214, 3.381), (15.252, 8.784)
    shoulder, breast = (12, 12), (20, 20.009)
    tail_fold, base = (8.046, 17.046), (12, 21)

    # Split the source strokes at the six folds where two sheets of paper meet.
    neck = chain([shoulder, (12, 4)], cubic((12, 4), (12, 3.76), (12.084, 3.55), crown))
    beak = chain(cubic(crown, (12.4, 3.15), (12.68, 3), (13, 3)),
                 [(13, 3), (19.297, 3)],
                 cubic((19.297, 3), (20.225, 3), (20.653, 4.154), (19.948, 4.759)),
                 [(19.948, 4.759), under_beak])
    throat = [crown, under_beak]
    chest = chain([under_beak, (20.628, 18.347)],
                  cubic((20.628, 18.347), (20.848, 18.739), (20.78, 19.229), (20.461, 19.546)),
                  [(20.461, 19.546), breast])
    belly = chain([breast, (19.293, 20.709)],
                  cubic((19.293, 20.709), (19.105, 20.896), (18.852, 21), (18.587, 21)),
                  [(18.587, 21), base])
    tail = chain([base, (6.351, 21)],
                 cubic((6.351, 21), (6.124, 21), (5.903, 20.923), (5.726, 20.781)),
                 [(5.726, 20.781), (3.25, 18.8)],
                 cubic((3.25, 18.8), (2.509, 18.206), (2.934, 17.012), (3.881, 17.019)),
                 [(3.881, 17.019), tail_fold])
    wing = chain([tail_fold, (4.586, 13.586)],
                 cubic((4.586, 13.586), (4.211, 13.211), (4, 12.702), (4, 12.172)),
                 [(4, 12.172), (4, 6.415)],
                 cubic((4, 6.415), (4, 5.516), (5.067, 5.069), (5.707, 5.708)),
                 [(5.707, 5.708), shoulder])
    wing_crease, tail_crease = [shoulder, breast], [base, tail_fold]
    return _engraving(tail, wing, neck, beak, throat[::-1], throat, chest,
                      wing_crease[::-1], wing_crease, belly, tail_crease, tail_crease[::-1])


def folded_crane():
    """A sideways folded bill and a swept wing, with open sand between the tips."""
    bill = (-1.07, .26)
    shoulder, wing = (-.14, -.008), (.52, .40)
    belly, cheek = (.22, -.54), (-.77, .28)
    # The triangular wing returns along its crease. The last short fold
    # leads in from the bill to define the eye without an extra approach.
    points = np.array([
        bill, (-.78,.50), (-.67,.78), (-.33,.76), (-.21,.56), shoulder,
        belly, wing, belly, shoulder, wing, (.53,.10), (1.10,.58),
        (.76,-.24), belly, (-.31,-.58), (-.67,-.35), (-.76,-.04),
        (-.64,.31), cheek, (-.55,.52), cheek, bill
    ])
    points -= (points.max(0) + points.min(0))/2
    return .89*points/np.linalg.norm(points,axis=1).max()


def chef_hat():
    """Three lobes above a wide cuff; the return crosses the cuff on its seam."""
    right, left = (18, 17), (6, 17)
    crown = chain([right, (18, 14.65)],
                  cubic((18, 14.65), (18, 14.193), (18.316, 13.806), (18.727, 13.609)),
                  cubic((18.727, 13.609), (20.484, 12.771), (21.382, 10.79), (20.855, 8.916)),
                  cubic((20.855, 8.916), (20.329, 7.042), (18.529, 5.82), (16.593, 6.02)),
                  cubic((16.593, 6.02), (15.804, 4.185), (13.998, 2.996), (12, 2.996)))
    other_half = crown[::-1] * [-1, 1] + [24, 0]
    cuff = chain([left, (6, 20)], _arc((7, 20), 1, 180, 90),
                 [(7, 21), (17, 21)], _arc((17, 20), 1, 90, 0), [(18, 20), right])
    seam = [right, left]
    return _engraving(crown, other_half, cuff, seam, seam[::-1])


def camping_trailer():
    """A single-axle trailer with a window, rounded door and an upturned hitch."""
    high, low = (2, 9), (2, 13)  # Window hinges on the back wall.
    wheel_back, wheel_front, sill, nose = (6, 19), (10, 19), (14, 19), (18, 19)
    roof = chain([nose, (18, 9)], _arc((14, 9), 4, 0, -90),
                 [(14, 5), (6, 5)], _arc((6, 9), 4, -90, -180))
    window = chain([high, (5, 9)], _arc((5, 10), 1, -90, 0),
                   [(6, 10), (6, 12)], _arc((5, 12), 1, 0, 90), [(5, 13), low])
    wall = [high, low]
    underside = chain([low, (2, 17)], _arc((4, 17), 2, 180, 90), [(4, 19), wheel_back])
    wheel_top = _arc((8, 19), 2, 180, 360)
    wheel_bottom = _arc((8, 19), 2, 0, 180)
    door = chain([wheel_front, (10, 10)], _arc((11, 10), 1, 180, 270),
                 [(11, 9), (13, 9)], _arc((13, 10), 1, 270, 360), [(14, 10), sill])
    step = [wheel_front, sill]
    hitch = chain([nose, (21, 19)], _arc((21, 18), 1, 90, 0), [(22, 18), (22, 17)])
    return _engraving(roof, window, wall[::-1], wall, underside, wheel_top,
                      wheel_bottom, wheel_bottom[::-1], door, step[::-1], step,
                      [sill, nose], hitch, hitch[::-1])


def birdhouse():
    left, right, peak = (5.04, 6.53), (18.96, 6.53), (12, 2)
    roof = [left, (3, 8), left, peak]
    # A vertical board seam connects the opening to the roof. Make the opening
    # wide enough that its center stays clear at a guest's groove width.
    seam = [peak, (12, 7.1)]
    opening = _arc((12, 10), 2.9, -90, 270)
    eaves = [peak, right, (21, 8), right, (17, 18), (20, 18), (17, 18), (12, 18)]
    post = [(12, 18), (12, 22)]
    wall = [(12, 18), (7, 18), (4, 18), (7, 18), left]
    return _engraving(roof, seam, opening, seam[::-1], eaves, post, post[::-1], wall)


def anvil():
    crown = chain(_arc((15, 5), 7, 90, 0), _arc((21, 5), 1, 0, -90),
                  [(21, 4), (8, 4)], _arc((8, 5), 1, -90, -180))
    horn = chain([(7, 5), (3, 5)], _arc((3, 6), 1, -90, -180),
                 _arc((6, 6), 4, 180, 90), [(6, 10), (7, 10), (7, 11)],
                 _arc((8, 11), 1, 180, 90), [(8, 12), (9, 12)])
    support = [(9, 12), (9, 17)]
    base = chain([(9, 17), (8, 17)], _arc((8, 20), 3, -90, -180),
                 _arc((6, 20), 1, 180, 90), [(6, 21), (18, 21)],
                 _arc((18, 20), 1, 90, 0), _arc((16, 20), 3, 0, -90),
                 [(16, 17), (15, 17)])
    return _engraving(crown, horn, support, base, [(15, 17), (9, 17)], support[::-1],
                      [(9, 12), (15, 12), (15, 17), (15, 12)])


def rocking_chair():
    # The two leg ends meet the actual rocker curve, avoiding a gap or a
    # second groove at the joint. Both are reached along the seat or runner.
    center_y = 18 - np.sqrt(13**2 - 9.25**2)
    def runner(left, right):
        x = np.linspace(left, right, 13)
        return np.column_stack((x, center_y + np.sqrt(13**2 - (x-12)**2)))
    heel, base, toe = runner(2.75, 5.5), runner(5.5, 18.5), runner(18.5, 21.25)
    back = [(9.5, 12.5), (6.5, 12.5), (3.5, 2)]
    seat = [(9.5, 12.5), (15, 12.5), (18, 12.5), (15, 12.5)]
    return _engraving(heel, [heel[-1], back[0]], back, back[::-1], seat,
                      [seat[-1], toe[0]], toe, toe[::-1], base[::-1], heel[::-1])


def washing_machine():
    # The left door hinge is shared with the case. A single sweeping water
    # line replaces the source's tiny control light and reads at guest size.
    case = chain([(3, 13), (3, 6), (6, 6), (3, 6), (3, 4)], _arc((5, 4), 2, 180, 270),
                 [(5, 2), (19, 2)], _arc((19, 4), 2, 270, 360), [(21, 4), (21, 20)],
                 _arc((19, 20), 2, 0, 90), [(19, 22), (5, 22)],
                 _arc((5, 20), 2, 90, 180), [(3, 20), (3, 13)])
    hinge = [(3, 13), (7, 13)]
    top = _arc((12, 13), 5, 180, 270)
    water = chain(_arc((12, 10.5), 2.5, -90, -270), _arc((12, 15.5), 2.5, -90, 90))
    right = _arc((12, 13), 5, 90, -90)
    left = _arc((12, 13), 5, 270, 90)
    return _engraving(case, hinge, top, water, right, left,
                      _arc((12, 13), 5, 90, 180), hinge[::-1])


def cooking_pot():
    rim = [(4, 12), (2, 12), (4, 12), (20, 12), (22, 12), (20, 12)]
    pan = chain([(20, 12), (20, 20)], _arc((18, 20), 2, 0, 90),
                [(18, 22), (6, 22)], _arc((6, 20), 2, 90, 180), [(4, 20), (4, 12)])
    # Rest the tilted lid on the pot so the ball can reach its handle.
    near, far = (8, 10.4), (14, 8)
    handle = chain(cubic(near, (7, 8), (7, 6.5), (8.5, 6)),
                   [(8.5, 6), (11, 5)], cubic((11, 5), (12.5, 4.5), (13.5, 6), far))
    lid = [far, (20, 5.6), far, near, (4, 12)]
    return _engraving(rim, pan, [(4, 12), near], handle, lid)
