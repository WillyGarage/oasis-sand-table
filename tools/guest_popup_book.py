"""An open book that unfolds into a Thai gable in a small guest place."""
import numpy as np

from autumn_leaves import chain, cubic


def popup_book():
    """Engrave the book, then its raised paper roof, returning to the binding."""
    binding, foot, gutter = (0, -.96), (0, -.65), (0, -.32)
    cover, front, back, tab = (.85, -.58), (.84, -.36), (.84, -.06), (.32, -.14)
    post, eave, peak = (.32, .17), (.53, .17), (0, .68)
    mirror = np.array([-1., 1.])

    # The cover projects below the page block. The shallow curved page tops
    # meet in the gutter, leaving a blank page on either side of the binding.
    cover_edge = chain(cubic(binding, (.26, -.73), (.62, -.45), cover), [cover, front])
    page_front = cubic(front, (.56, -.235), (.22, -.43), foot)
    page_side = cubic(front, (.84, -.25), (.87, -.11), back)
    page_back = cubic(back, (.66, .035), (.46, -.055), tab)
    leaf = chain(page_side, page_back)
    fold = cubic(tab, (.20, -.16), (.08, -.26), gutter)
    pages = chain(cover_edge*mirror, page_front*mirror, page_front[::-1], cover_edge[::-1],
                  [binding, foot, gutter], fold[::-1]*mirror, leaf[::-1]*mirror,
                  page_front*mirror, page_front[::-1], leaf, fold, fold[::-1])

    # Two paper tabs lift the gable off the spread. The three points terminate
    # in upturned eaves and a forward-curling chofah at the ridge.
    pillar = np.array([tab, post])
    overhang = cubic(post, (.39, .168), (.46, .16), eave)
    wing = cubic(eave, (.69, .15), (.78, .36), (.82, .49))
    slope = cubic(eave, (.31, .185), (.13, .52), peak)
    finial = cubic(peak, (.00, .82), (.10, .966), (.235, .985))
    sill = cubic(post, (.15, .152), (-.15, .152), (-post[0], post[1]))
    roof = chain(pillar, overhang, wing, wing[::-1], slope, finial, finial[::-1],
                 slope[::-1]*mirror, wing*mirror, wing[::-1]*mirror, overhang[::-1]*mirror,
                 sill[::-1], sill, pillar[::-1]*mirror)
    # Leave by the left page fold and binding without scoring a page face.
    path = chain(pages, roof, fold*mirror, [gutter, foot, binding])
    return path * (.982 / np.linalg.norm(path, axis=1).max())
