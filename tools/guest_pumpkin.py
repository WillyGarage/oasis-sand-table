"""A low, ribbed field pumpkin for a guest facing the edge of the table."""

import numpy as np
from autumn_leaves import chain, cubic


def pumpkin():
    # The right shoulder sits lower. Each outer lobe narrows toward the flank.
    left_foot, right_foot = (-.28, -.66), (.105, -.69)
    stalk_left, stalk_right = (-.07, .398), (.165, .382)
    left_shoulder, right_shoulder = (-.50, .44), (.59, .392)
    left_heel, right_heel = (-.63, -.53), (.56, -.55)
    left_hem = cubic(left_foot, (-.44, -.705), (-.57, -.62), left_heel)
    left_edge = chain(cubic(left_heel, (-.93, -.55), (-1.035, -.17), (-.90, .125)),
                      cubic((-.90, .125), (-.83, .372), (-.67, .51), left_shoulder))
    right_edge = chain(cubic(right_shoulder, (.77, .421), (.963, .20), (.945, -.10)),
                       cubic((.945, -.10), (.93, -.37), (.79, -.58), right_heel))
    right_hem = cubic(right_heel, (.45, -.705), (.245, -.743), right_foot)
    left_cap = cubic(left_shoulder, (-.38, .525), (-.18, .56), stalk_left)
    right_cap = cubic(stalk_right, (.33, .52), (.475, .51), right_shoulder)
    crown = cubic(stalk_left, (.015, .367), (.102, .345), stalk_right)
    base = cubic(right_foot, (-.025, -.755), (-.187, -.72), left_foot)
    left_rib = chain(cubic(stalk_left, (-.25, .355), (-.393, .115), (-.40, -.125)),
                     cubic((-.40, -.125), (-.408, -.375), (-.369, -.55), left_foot))
    right_rib = chain(cubic(stalk_right, (.325, .278), (.395, .065), (.377, -.16)),
                      cubic((.377, -.16), (.356, -.39), (.255, -.62), right_foot))
    left_flank = chain(cubic(left_shoulder, (-.64, .40), (-.727, .15), (-.727, -.02)),
                       cubic((-.727, -.02), (-.727, -.25), (-.73, -.45), left_heel))
    right_flank = chain(cubic(right_shoulder, (.73, .40), (.704, .15), (.704, -.085)),
                        cubic((.704, -.085), (.704, -.25), (.66, -.45), right_heel))
    # A flared base follows the dip between lobes. The diagonal cap is the cut end.
    stalk = chain(cubic(stalk_left, (.008, .485), (-.024, .585), (-.065, .65)),
                  cubic((-.065, .65), (-.09, .69), (-.145, .74), (-.175, .775)),
                  cubic((-.175, .775), (-.141, .81), (-.04, .872), (-.008, .883)),
                  cubic((-.008, .883), (.135, .76), (.14, .545), stalk_right))

    # Each long rib is engraved once. Use the short seams to reach both sides.
    shape = chain(left_hem, left_edge, left_cap, stalk, right_cap, right_edge, right_hem,
                  right_rib[::-1], crown[::-1], left_cap[::-1], left_flank, left_hem[::-1],
                  left_rib[::-1], crown, right_cap, right_flank, right_hem, base)
    return shape * (.974 / np.linalg.norm(shape, axis=1).max())
