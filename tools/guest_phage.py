"""A compact phage for narrow guest places on the large sand table."""
import math

import numpy as np


def compact_phage():
    """A faceted head, open tail tube and six splayed fibers on a broad baseplate."""
    crown = (.005, .96)
    facet = (-.06, .593)
    head_left, head_right = (-.36, .398), (.35, .408)
    right_corner, left_corner = (.35, .758), (-.36, .739)
    neck = (0, .175)
    shoulder, plate_y = .116, -.36
    plate_edge = .195
    points = [crown, facet, head_left, facet, head_right, right_corner, head_right, neck,
              (shoulder, .088), (shoulder, plate_y)]
    # Each fiber returns along the same groove to avoid a line between feet.
    for side in (1, -1):
        root = (side * plate_edge, plate_y)
        points.append(root)
        for knee_x, knee_y, foot_x, foot_y in ((.18, -.55, .238, -.81),
                                                (.43, -.32, .59, -.68),
                                                (.615, -.145, .88, -.36)):
            knee = (side * knee_x, knee_y)
            points.extend([knee, (side * foot_x, foot_y), knee, root])
        points.append((side * shoulder, plate_y))
        if side == 1:
            points.extend([(0, plate_y), (-shoulder, plate_y)])
    points.extend([(-shoulder, .088), neck, head_left, left_corner, crown, right_corner, crown])
    angle = math.radians(7)
    c, s = np.cos(angle), np.sin(angle)
    return np.asarray(points) @ np.array([[c, s], [-s, c]])
