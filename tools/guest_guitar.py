"""An acoustic guitar for a guest place only about sixteen sand grooves across."""

import math

import numpy as np

from autumn_leaves import chain, cubic


def engraving():
    """Return the finished guitar and named features in its tilted guest-seat frame."""
    neck = .132
    hole_y, hole_radius = -.147, .206
    points = [(0, -.940)]

    def curve(handle1, handle2, end):
        a, b, c, d = (np.asarray(p) for p in (points[-1], handle1, handle2, end))
        for t in np.arange(1, 13) / 12:
            s = 1 - t
            points.append(s**3*a + 3*s*s*t*b + 3*s*t*t*c + t**3*d)

    # One smooth waist between the lower bout and the smaller shoulder.
    curve((-.248, -.949), (-.539, -.846), (-.557, -.638))
    curve((-.576, -.423), (-.357, -.397), (-.337, -.275))
    waist = points[-1]
    curve((-.316, -.177), (-.454, -.137), (-.444, -.003))
    curve((-.435, .125), (-.285, .187), (-neck, .188))
    left_body = points.copy()

    # The fingerboard meets the soundhole at its edge. The bridge hangs from
    # the opposite edge by one string. The ball never crosses the opening.
    hole_entry = (-neck, hole_y + math.sqrt(hole_radius**2 - neck**2))
    angle = math.acos(-neck / hole_radius)
    bottom = 1.5 * math.pi

    def hole_arc(start, end, count):
        for a in np.linspace(start, end, count)[1:]:
            points.append((hole_radius*math.cos(a), hole_y + hole_radius*math.sin(a)))

    points.append(hole_entry)
    hole_start = len(points)-1
    hole_arc(angle, bottom, 29)
    hole_bottom = len(points)-1
    bridge = (0, -.57)
    points.extend([bridge, (-.168, -.57), (.168, -.57), bridge, (0, hole_y - hole_radius)])
    bridge_end = len(points)-1
    hole_arc(bottom, angle + math.tau, 31)
    hole_end = len(points)-1
    points.extend([hole_entry, left_body[-1]])

    # A single fret and the nut leave broad open frets on a 7 mm groove.
    for y in (.406, .645):
        points.extend([(-neck, y), (neck, y), (-neck, y)])
    head_start = len(points)-1
    curve((-.14, .683), (-.175, .693), (-.175, .720))
    points.append((-.19, .868))
    curve((-.195, .919), (-.139, .956), (-.08, .954))
    curve((-.04, .955), (-.03, .929), (0, .929))
    curve((.032, .929), (.047, .955), (.08, .954))
    curve((.141, .956), (.189, .924), (.19, .868))
    points.append((.175, .720))
    curve((.175, .693), (.14, .683), (neck, .645))
    head_end = len(points)-1
    points.append((neck, .188))
    points.extend((-x, y) for x, y in left_body[-2::-1])

    # The outer rail meets the bass side of the lower bout from beneath.
    tilt = math.radians(30)
    c, s = math.cos(tilt), math.sin(tilt)
    tilt_matrix = np.array([[c, -s], [s, c]])
    features = dict(waists=[waist, (-waist[0], waist[1])],
                    soundhole=[*points[hole_start:hole_bottom+1], *points[bridge_end:hole_end+1]],
                    bridge=points[hole_bottom:bridge_end+1],
                    fret=[(-neck, .406), (neck, .406)], head=points[head_start:head_end+1])
    return np.asarray(points) @ tilt_matrix, {k: np.asarray(p) @ tilt_matrix for k,p in features.items()}


def guitar():
    """A closed, tilted guitar contour in the guest's x-right, y-up unit disc."""
    return engraving()[0]


def electric_guitar():
    """A solid-body guitar with offset horns and one-sided headstock."""
    left, right = (-.106, .015), (.106, .015)
    nut, tip = (-.088, .706), (.125, .962)
    head = chain(cubic(nut, (-.129, .753), (-.102, .795), (-.063, .811)),
                 cubic((-.063, .811), (.003, .862), (.062, .949), tip),
                 cubic(tip, (.189, .974), (.230, .886), (.184, .841)),
                 cubic((.184, .841), (.132, .804), (.090, .784), (.088, .706)))
    # One open fret, the nut and the heel give the fretting hand room at
    # guest scale. The short crosswise strokes below are a pickup and bridge.
    neck = [left, (-.096, .404), (.096, .404), (-.096, .404), nut, (.088, .706), nut]
    heel = [right, left, (0, .015), (0, -.249),
            (-.185, -.218), (.185, -.28), (0, -.249), (0, -.56),
            (-.142, -.56), (.142, -.56), (0, -.56), (0, -.249), (0, .015), right]
    treble_horn, bass_horn = (.463, .122), (-.431, .335)
    body = chain(cubic(right, (.14, -.142), (.26, -.175), (.35, -.021)),
                 cubic((.35, -.021), (.400, .052), (.419, .148), treble_horn),
                 cubic(treble_horn, (.539, .048), (.493, -.149), (.417, -.251)),
                 cubic((.417, -.251), (.316, -.42), (.526, -.531), (.526, -.676)),
                 cubic((.526, -.676), (.541, -.882), (.268, -.978), (.027, -.943)),
                 cubic((.027, -.943), (-.258, -.927), (-.566, -.842), (-.542, -.643)),
                 cubic((-.542, -.643), (-.535, -.486), (-.31, -.415), (-.341, -.238)),
                 cubic((-.341, -.238), (-.355, -.101), (-.554, .095), bass_horn),
                 cubic(bass_horn, (-.385, .387), (-.374, .218), (-.341, .136)),
                 cubic((-.341, .136), (-.301, .006), (-.192, -.131), left))
    walk = chain(neck, head, [head[-1], right], heel, body)
    angle = math.radians(27)
    return walk @ np.array([[math.cos(angle), -math.sin(angle)],
                            [math.sin(angle), math.cos(angle)]])
