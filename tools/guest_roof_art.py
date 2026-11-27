"""A Thai gable with two swept eaves for the smaller guest places."""
import numpy as np

from autumn_leaves import chain, cubic


def temple():
    # The chofah curls forward from the ridge. Each eave turns back up at its tip.
    peak, upper, lower = (0, .61), (.46, -.075), (.71, -.47)
    chofah = cubic(peak, (-.04, .76), (.045, .94), (.20, .965))
    slope = cubic(peak, (.10, .43), (.23, .105), upper)
    upper_tip = cubic(upper, (.565, -.125), (.645, .025), (.67, .17))
    lower_slope = cubic(upper, (.52, -.18), (.60, -.40), lower)
    lower_tip = cubic(lower, (.83, -.49), (.914, -.37), (.92, -.19))
    upper_sill = cubic((-.46, -.075), (-.23, -.115), (.23, -.115), upper)
    right_sill = cubic(lower, (.62, -.49), (.55, -.50), (.49, -.503))
    inner_sill = cubic((.49, -.503), (.22, -.519), (-.22, -.519), (-.49, -.503))
    # Short posts under the overhang and a single base beam give the roof a
    # building to sit on. Its hanging stroke joins the foot of one of the posts.
    post = cubic((.49, -.503), (.49, -.59), (.49, -.68), (.49, -.76))
    base = cubic((.49, -.76), (.26, -.76), (-.26, -.76), (-.49, -.76))
    mirror = np.array([-1, 1])
    # Return from the wing tips in their own grooves. Doubling the upper sill
    # connects both tiers without drawing a diagonal across the open pediment.
    return chain(chofah[::-1], slope, upper_tip, upper_tip[::-1], lower_slope,
                 lower_tip, lower_tip[::-1], right_sill, post, base, post[::-1]*mirror,
                 inner_sill[::-1], inner_sill, right_sill[::-1]*mirror, lower_tip*mirror,
                 lower_tip[::-1]*mirror, lower_slope[::-1]*mirror, upper_tip*mirror,
                 upper_tip[::-1]*mirror, upper_sill, upper_sill[::-1],
                 slope[::-1]*mirror, chofah)
