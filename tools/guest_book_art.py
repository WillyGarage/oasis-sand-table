"""An open book with a turned page for the smaller guest places."""
import numpy as np

from autumn_leaves import chain, cubic


def engraving():
    """Return the finished book and the same strokes for drawing it as it opens."""
    binding, foot, crown = (0, -.77), (-.015, -.40), (.012, .34)
    left, right = (-.81, -.25), (.82, -.28)
    left_top, turned_top, turned_tip = (-.82, .47), (.30, .585), (.82, .12)

    # The lower cover shows below the two page blocks. Its central notch is
    # the most outward point in a seat-facing layout, where the rail meets it.
    left_cover = chain(cubic(binding, (-.26, -.46), (-.68, -.36), (-.91, -.47)),
                       [(-.91, -.47), left])
    right_cover = chain(cubic(binding, (.24, -.48), (.64, -.38), (.90, -.48)),
                        [(.90, -.48), right])
    left_pages = cubic(foot, (-.26, -.18), (-.58, -.095), left)
    right_pages = cubic(foot, (.24, -.21), (.59, -.10), right)
    spine = cubic(foot, (.01, -.12), (.012, .18), crown)
    left_edge = chain([left, left_top], cubic(left_top, (-.56, .65), (-.19, .63), crown))

    # The turned corner bounds an actual pocket of clear sand. Retrace its
    # diagonal to keep the rest of the right page free of connecting lines.
    crease = [turned_top, turned_tip]
    folded_edge = chain([turned_top, (.28, .035)],
                        cubic((.28, .035), (.44, .08), (.68, .14), turned_tip))
    right_edge = chain(cubic(crown, (.12, .50), (.23, .565), turned_top),
                       crease, folded_edge[::-1], crease, [turned_tip, right])

    path = chain(left_cover, left_pages[::-1], spine, left_edge[::-1],
                 left_pages[::-1], right_pages, right_edge[::-1], spine[::-1],
                 right_pages, right_cover[::-1])
    scale = .982 / np.linalg.norm(path, axis=1).max()
    strokes = dict(left_cover=left_cover, right_cover=right_cover, left_pages=left_pages,
                   right_pages=right_pages, spine=spine, left_edge=left_edge,
                   right_side=[right, turned_tip], folded_edge=folded_edge, crease=crease)
    return path * scale, {key: np.asarray(points)*scale for key, points in strokes.items()}


def books():
    """A closed engraving in the upright guest disc, entered at the binding."""
    return engraving()[0]


def two_books():
    """An open book resting on a closed hardcover with a hanging bookmark."""
    joint = np.array([-.03, -.20])
    left, top, outer, foot = (-.82,-.219), (.53,-.185), (.86,-.070), (.53,-.61)
    far_foot = (.86, -.483)
    spine = cubic(left, (-1.01,-.21), (-1.02,-.612), (-.78,-.613))
    fore = cubic(far_foot, (.80,-.406), (.80,-.142), outer)
    pages = cubic(top, (.47,-.244), (.47,-.54), foot)

    # Use the open volume's own binding as its contact with the closed cover.
    novel = books()*.92
    novel = novel - novel[0] + joint
    # The lower cover disappears behind the ribbon. Its two visible ends meet
    # the sides of the bookmark, so no travel line crosses the open pages.
    ribbon_top = (-.47, -.2106)
    ribbon_left, ribbon_right = (-.47,-.6123), (-.18,-.6116)
    ribbon = [ribbon_left, (-.47,-.884), (-.328,-.760), (-.18,-.884), ribbon_right]
    left_cover = chain([joint, ribbon_top, left], spine, [spine[-1], ribbon_left])
    lower = chain(left_cover, ribbon, [ribbon_right, foot], pages[::-1], pages,
                  [foot, far_foot], fore, [outer, top, joint])
    tail = [ribbon_top, ribbon_left, *ribbon[1:], (-.18,-.204), joint]
    path = chain(novel, lower, [joint, ribbon_top], tail)
    path -= (path.max(axis=0) + path.min(axis=0)) / 2
    return path * (.966 / np.linalg.norm(path, axis=1).max())
