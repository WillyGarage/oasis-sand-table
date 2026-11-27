"""Attached details drawn in the same upright coordinates as their original guest picture."""
import math

import numpy as np

from autumn_leaves import chain, cubic


def _anchor(base, target):
    """Use a vertex of the actual stored outline, including when that groove is revisited."""
    return int(np.argmin(np.linalg.norm(base[:-1] - target, axis=1)))


def _crescent(base, center, radius, tilt):
    """Return over the left eave after drawing the two pointed horns in the open sky."""
    index = _anchor(base, (-.67, .17))
    tip = base[index]
    joint, high, low = (-.26, -.968), (.45, .893), (.45, -.893)
    body = chain(cubic(joint, (-1.04, -.75), (-1.28, .12), (-.73, .684)),
                 cubic((-.73, .684), (-.44, .99), (.02, 1.085), high),
                 cubic(high, (-.49, .623), (-.49, -.623), low),
                 cubic(low, (.24, -1.01), (-.065, -1.016), joint))
    angle = math.radians(tilt)
    cosine, sine = math.cos(angle), math.sin(angle)
    body = center + radius * body @ np.array([[cosine, sine], [-sine, cosine]])
    lead = cubic(tip, tip + [.021, .12], body[0] + [-.044, -.105], body[0])
    return index, chain(lead, body, lead[::-1])


def roof_crescent(base):
    """The compact crescent fits inside the original guest disc in any orientation."""
    return _crescent(base, (-.442, .60), .245, -20)


def seated_roof_crescent(base):
    """A larger crescent where the fitted seat has enough clearable sky beside the gable."""
    return _crescent(base, (-.468, .70), .315, -17)


def guitar_note(base):
    """An eighth note hangs beside the lower guitar waist, clear of the tuning head."""
    index = _anchor(base, (.19, -.36))
    joint, head, stem_tip = (.50, -.514), (.813, -.363), (.792, .312)
    lead = cubic(base[index], (.296, -.355), (.359, -.561), joint)
    bottom = cubic(joint, (.490, -.763), (.841, -.690), head)
    top = cubic(head, (.79, -.243), (.552, -.289), joint)
    stem = np.linspace(head, stem_tip, 12)
    flag = cubic(stem_tip, (.920, .193), (1.039, .188), (.904, -.062))
    return index, chain(lead, bottom, stem, flag, flag[::-1], stem[::-1], top, lead[::-1])


def book_pencil(base):
    """Rest the pencil's barrel on the tip of the turned page, leaving both pages open."""
    index = _anchor(base, (.29, .56))
    # Coordinates along the shaft run from the point to the rounded eraser.
    # The underside touches the fold between the sharpened wood and the collar.
    tip, wood_top, wood_bottom = (0, 0), (.266, .108), (.280, -.101)
    rest, collar_top, collar_bottom = (.726, -.107), (.958, .110), (.989, -.106)
    front = cubic(rest, (.58, -.107), (.40, -.105), wood_bottom)
    wood = cubic(wood_top, (.319, .070), (.322, -.048), wood_bottom)
    shaft = cubic(wood_top, (.46, .114), (.79, .110), collar_top)
    collar = cubic(collar_top, (.975, .051), (.996, -.051), collar_bottom)
    eraser = chain(cubic(collar_top, (1.04, .113), (1.12, .110), (1.15, .092)),
                   cubic((1.15, .092), (1.185, .070), (1.190, -.051), (1.155, -.084)),
                   cubic((1.155, -.084), (1.14, -.108), (1.06, -.110), collar_bottom))
    back = cubic(collar_bottom, (.902, -.109), (.812, -.108), rest)
    # Revisit each seam from its outside junction. At guest-place size this
    # keeps the wood and eraser distinguishable inside the narrow barrel.
    outline = chain(front, [wood_bottom, tip, wood_top], wood, wood[::-1],
                    shaft, eraser, collar[::-1], collar, back)
    angle = math.radians(-18)
    cosine, sine = math.cos(angle), math.sin(angle)
    return index, base[index] + (outline - rest) @ np.array([[cosine, sine], [-sine, cosine]])


# Each callback returns the attachment index and a closed trip from that exact vertex.
ADDITIONS = {
    'temple_crescent': ('Crescent over Thai rooftop', 'temple_gable', roof_crescent),
    'guitar_note': ('Acoustic guitar with a music note', 'guitar_silhouette', guitar_note),
    'book_pencil': ('Open book with a pencil', 'books_open', book_pencil),
}
SEATED_ADDITIONS = {'temple_crescent': seated_roof_crescent}


def engraving(name, base, *, callback=None):
    """The same new strokes are used in the complete design and its local addition."""
    make_detail = callback if callback is not None else ADDITIONS[name][2]
    index, stroke = make_detail(base)
    return np.vstack((base[:index + 1], stroke[1:], base[index + 1:])), stroke
