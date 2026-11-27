"""Botanical and Thanksgiving engravings for the upright guest disc."""
import math

import numpy as np

from autumn_leaves import chain, cubic, maple


def _fit(*parts):
    for a, b in zip(parts, (*parts[1:], parts[0])):
        if not np.allclose(a[-1], b[0], atol=1e-9, rtol=0):
            raise ValueError("Harvest engraving has a disconnected stroke")
    path = chain(*parts)
    center = (path.max(axis=0) + path.min(axis=0)) / 2
    path -= center
    return path * (.966 / np.linalg.norm(path, axis=1).max())


def acorn():
    """One tilted oak nut with a woody stem and a broad, overhanging cup."""
    left, right = (-.824, .194), (.799, .16)
    stem_left, stem_right = (-.183, .67), (-.017, .675)
    tip = (-.008, -.899)
    cup_left = cubic(left, (-.819, .495), (-.523, .663), stem_left)
    stem = chain(cubic(stem_left, (-.191, .762), (-.26, .846), (-.355, .924)),
                 cubic((-.355, .924), (-.343, .995), (-.219, 1.014), (-.17, .963)),
                 cubic((-.17, .963), (-.047, .868), (-.002, .748), stem_right))
    cup_right = cubic(stem_right, (.319, .688), (.745, .501), right)
    lip = cubic(right, (.469, -.038), (-.505, -.051), left)
    nut = chain(cubic(left, (-.698, .139), (-.705, -.37), (-.448, -.569)),
                cubic((-.448, -.569), (-.285, -.728), (-.082, -.755), tip),
                cubic(tip, (.045, -.757), (.285, -.728), (.449, -.561)),
                cubic((.449, -.561), (.657, -.377), (.643, .114), right))
    path = _fit(cup_left, stem, cup_right, lip, nut, lip)
    angle = math.radians(-24)
    return path @ np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]])


def pineapple_with_ring():
    """A diamond-skinned pineapple behind a freshly cored ring."""
    left, right = (-.28, .34), (.26, .34)
    center = np.array([.63, -.57])

    def arc(rx, ry, start, end):
        angles = np.deg2rad(np.linspace(start, end, 1 + math.ceil(abs(end - start) / 5)))
        return center + np.column_stack((rx * np.cos(angles), ry * np.sin(angles)))

    def rim(start, end):
        return arc(.455, .43, start, end)

    # Follow the visible fruit around the near edge of the slice; the hidden
    # outline and all the skin markings stop at this edge.
    near_rim = rim(225, 85)
    low, high = near_rim[0], near_rim[-1]
    skin = chain(cubic(left, (-.59, .34), (-.73, .072), (-.69, -.225)),
                 cubic((-.69, -.225), (-.69, -.347), (-.66, -.49), (-.63, -.56)),
                 cubic((-.63, -.56), (-.535, -.81), (-.32, -.938), (-.01, -.94)),
                 cubic((-.01, -.94), (.12, -.94), (.236, -.92), low),
                 near_rim, cubic(high, (.686, .14), (.55, .332), right))
    top = cubic(right, (.131, .394), (-.09, .388), left)
    body = chain(skin, top)
    # The low blades spread out over the shoulders, the tallest spear rises off-center.
    crown = chain(
        cubic(left, (-.35, .44), (-.49, .51), (-.64, .586)),
        cubic((-.64, .586), (-.46, .60), (-.32, .56), (-.19, .51)),
        cubic((-.19, .51), (-.24, .68), (-.39, .84), (-.515, .92)),
        cubic((-.515, .92), (-.31, .894), (-.15, .774), (-.057, .642)),
        cubic((-.057, .642), (-.09, .818), (-.036, 1.065), (.065, 1.205)),
        cubic((.065, 1.205), (.037, 1.008), (.086, .843), (.139, .671)),
        cubic((.139, .671), (.234, .84), (.407, .963), (.529, .991)),
        cubic((.529, .991), (.414, .831), (.319, .648), (.308, .534)),
        cubic((.308, .534), (.427, .622), (.56, .668), (.69, .67)),
        cubic((.69, .67), (.485, .531), (.37, .405), right))
    branches = {}
    for slope in (.82, -.82):
        heights = body[:, 1] - slope * body[:, 0]
        for level in (-.72, -.30, .12):
            delta = heights - level
            start, end = np.flatnonzero(delta[:-1] * delta[1:] < 0)
            p, q = (body[i] + (body[i+1] - body[i]) * delta[i] / (delta[i] - delta[i+1])
                    for i in (start, end))
            span = q - p
            row = cubic(p, p + .33 * span + (0, .039), p + .70 * span + (0, .049), q)
            branches[start] = chain(row, row[::-1])

    # The radial cut reaches the core without crossing the smooth hole.
    far_rim = rim(225, 386)
    hole = arc(.239, .224, 26, 386)
    cut = np.linspace(far_rim[-1], hole[0], 9)
    anchor = int(np.argmin(np.linalg.norm(body - low, axis=1)))
    branches[anchor] = chain(far_rim, cut, hole, cut[::-1], rim(26, 225))
    engraved = []
    for i, point in enumerate(body):
        engraved.append(point)
        if i in branches:
            engraved.extend(branches[i])
    return _fit(np.asarray(engraved), crown, top)


def rolling_pin(tilt=32):
    """Turned wooden handles, a broad barrel and one curved end in a single walk."""
    # Half of the turned grip, sampled at equal intervals from axle to tip.
    # Mirroring the profile gives both handles the same narrow neck and thumb rest.
    grip_radius = [
        0.067, 0.063019237311385, 0.060934639231824, 0.060132740740741, 0.060000076817558,
        0.063140124570734, 0.071685958924121, 0.082114611644213, 0.090866887596714, 0.096768770301624,
        0.1027049990611, 0.10852072807361, 0.11396153304116, 0.11877298966579, 0.1227006736495,
        0.12549016069434, 0.12688702650231, 0.12697186891581, 0.12681334879722, 0.12651384804194,
        0.12607192902461, 0.12548615411989, 0.12475508570243, 0.12387728614687, 0.12282824489905,
        0.1200432333992, 0.11447236187646, 0.10597376456746, 0.094355120987654, 0.058248612345679,
        6.9388939039072e-18,
    ]
    grip = np.column_stack((np.linspace(.56, 1., len(grip_radius)), grip_radius))

    h = .276
    barrel = cubic((-.55, h), (-.19, h*1.035), (.23, h*1.032), (.55, h))
    shoulder = cubic((.55, h), (.603, h), (.60, h*.80), (.595, h*.70))
    axle = cubic(shoulder[-1], (.59, h*.65), (.582, .067), grip[0])
    half_handle = chain(shoulder, axle, grip)
    handle = chain(half_handle, half_handle[::-1]*[1, -1])
    end = cubic((.55, -h), (.475, -h*.72), (.475, h*.72), (.55, h))

    # The cap starts on the silhouette. Retrace it before following the barrel home.
    path = chain(barrel, handle, end, end[::-1], barrel[::-1]*[1, -1], -handle)
    angle = math.radians(tilt)
    c, s = math.cos(angle), math.sin(angle)
    return path @ np.array([[c, s], [-s, c]]) * .939


def oven_mitt():
    """An oven mitt with wide diagonal quilting, a bound cuff and a hanging loop."""
    left, right = (-.41, -.57), (.44, -.57)
    thumb, tip, notch = (-.70, .12), (-.56, .42), (-.15, .18)
    shoulder, crown, side = (-.075, .59), (.27, .96), (.56, .52)
    palm = chain(cubic(left, (-.42, -.33), (-.62, -.11), thumb),
                 cubic(thumb, (-.80, .32), (-.72, .48), tip),
                 cubic(tip, (-.43, .39), (-.22, .125), notch),
                 cubic(notch, (-.11, .24), (-.13, .44), shoulder),
                 cubic(shoulder, (-.046, .79), (.045, .96), crown),
                 cubic(crown, (.48, .98), (.56, .80), side),
                 cubic(side, (.575, .14), (.47, -.32), right))
    cuff = cubic(right, (.18, -.62), (-.14, -.60), left)
    panel = chain(palm, cuff)

    # Clip each row of quilting at the cloth edge. The top row crosses the
    # thumb and fingers separately, leaving their open notch untouched.
    heights = panel[:, 1] - .88 * panel[:, 0]
    seams = {}
    for level in (-.40, .14, .68):
        offset = heights - level
        edges = np.flatnonzero(offset[:-1] * offset[1:] < 0)
        crossings = [panel[i] + (panel[i+1] - panel[i]) * offset[i] / (offset[i] - offset[i+1])
                     for i in edges]
        for i, p, q in zip(edges[::2], crossings[::2], crossings[1::2]):
            seams[i] = chain(np.linspace(p, q, 13), np.linspace(q, p, 13))
    sewn = []
    for i, p in enumerate(panel):
        sewn.append(p)
        if i in seams:
            sewn.extend(seams[i])

    foot_l, foot_r = (-.418, -.85), (.455, -.835)
    loop = chain(cubic(foot_l, (-.58, -.82), (-.76, -.925), (-.683, -1.013)),
                 cubic((-.683, -1.013), (-.602, -1.10), (-.45, -.965), foot_l))
    hem = chain(cubic(left, (-.403, -.67), (-.435, -.78), foot_l), loop,
                cubic(foot_l, (-.18, -.907), (.19, -.885), foot_r),
                cubic(foot_r, (.474, -.78), (.445, -.67), right))
    return _fit(np.asarray(sewn), hem, cuff)


def harvest_basket():
    """Two orchard apples in a woven basket under one broad, open handle."""
    def rim(x):
        return (x, -.13 + .14*(x/.9)**2)

    def lip(a, b):
        return np.array([rim(x) for x in np.linspace(a, b, 12)])

    def base(x):
        return (x, -.74 + .117*(x/.61)**2)

    def foot(a, b):
        return np.array([base(x) for x in np.linspace(a, b, 16)])

    def retrace(line):
        return chain(line, line[::-1])

    left, right = rim(-.9), rim(.9)
    stem = (-.438, .315)
    left_apple = chain(
        cubic(rim(-.74), (-.85, .12), (-.77, .35), (-.61, .355)),
        cubic((-.61, .355), (-.52, .37), (-.49, .30), stem),
        retrace(cubic(stem, (-.436, .412), (-.409, .46), (-.35, .493))),
        cubic(stem, (-.387, .347), (-.319, .414), (-.21, .388)),
        cubic((-.21, .388), (-.05, .36), (.016, .192), rim(-.045)))
    # The leaf points into the opening, where its tip stays clear of the handle.
    leaf, tip = (.299, .267), (.072, .595)
    right_apple = chain(
        cubic(rim(-.045), (-.075, .011), (-.007, .262), (.117, .287)),
        cubic((.117, .287), (.196, .329), (.250, .27), leaf),
        cubic(leaf, (.138, .289), (.057, .496), tip),
        cubic(tip, (.267, .591), (.346, .435), leaf),
        cubic(leaf, (.335, .294), (.412, .394), (.512, .369)),
        cubic((.512, .369), (.729, .365), (.791, .154), rim(.696)))
    apples = chain(lip(-.9, -.74), left_apple, right_apple, lip(.696, .9))
    handle = chain(cubic(left, (-.84, .43), (-.547, .946), (-.045, .975)),
                   cubic((-.045, .975), (.466, 1.002), (.792, .546), right))

    # Retrace two curved ribs and one willow strand to reach the next part
    # of the bowl without marking any of the open cells between the strands.
    flank_l, flank_r = (-.788, -.315), (.79, -.307)
    bowl = chain(
        cubic(right, (.891, -.10), (.825, -.226), flank_r),
        cubic(flank_r, (.737, -.471), (.715, -.571), base(.61)),
        foot(.61, .27), retrace(cubic(base(.27), (.36, -.59), (.438, -.31), rim(.467))),
        foot(.27, -.27), retrace(cubic(base(-.27), (-.367, -.59), (-.461, -.32), rim(-.48))),
        foot(-.27, -.61), cubic(base(-.61), (-.712, -.581), (-.757, -.441), flank_l),
        retrace(cubic(flank_l, (-.406, -.465), (.409, -.467), flank_r)),
        cubic(flank_l, (-.82, -.221), (-.883, -.093), left))
    return _fit(handle, bowl, apples, lip(.9, -.9))


def crescent_roll():
    """A crescent-shaped dinner roll with a broad center and curled, tapered tips."""
    left_tip, right_tip = (-.79, -.49), (.84, -.455)
    left_end, left_fold, left_crown = (-.87, .004), (-.61, .35), (-.24, .538)
    right_crown, right_fold, right_end = (.27, .525), (.64, .352), (.884, .007)
    crown = chain(cubic(left_tip, (-1.045, -.327), (-1.01, -.092), left_end),
                  cubic(left_end, (-.901, .176), (-.78, .364), left_fold),
                  cubic(left_fold, (-.544, .478), (-.368, .556), left_crown),
                  cubic(left_crown, (-.161, .644), (.162, .674), right_crown),
                  cubic(right_crown, (.453, .553), (.61, .495), right_fold),
                  cubic(right_fold, (.797, .332), (.896, .145), right_end),
                  cubic(right_end, (.987, -.138), (.988, -.337), right_tip))

    def seam(start, a, b, end):
        # Retrace each fold to reach the next one along the underside.
        line = cubic(start, a, b, end)
        return chain(line, line[::-1])

    right_horn, right_layer, right_flap = (.731, -.19), (.489, -.078), (.144, -.108)
    left_flap, left_layer, left_horn = (-.128, -.114), (-.46, -.072), (-.731, -.19)
    underside = chain(
        cubic(right_tip, (.795, -.466), (.77, -.329), right_horn),
        seam(right_horn, (.852, -.115), (.89, -.059), right_end),
        cubic(right_horn, (.636, -.222), (.538, -.14), right_layer),
        seam(right_layer, (.49, .107), (.539, .267), right_fold),
        cubic(right_layer, (.352, -.157), (.239, -.179), right_flap),
        seam(right_flap, (.101, .173), (.165, .411), right_crown),
        cubic(right_flap, (.052, -.244), (-.088, -.218), left_flap),
        seam(left_flap, (-.152, .073), (-.194, .413), left_crown),
        cubic(left_flap, (-.26, -.172), (-.377, -.152), left_layer),
        seam(left_layer, (-.516, .082), (-.534, .215), left_fold),
        cubic(left_layer, (-.555, -.165), (-.65, -.23), left_horn),
        seam(left_horn, (-.83, -.093), (-.882, -.019), left_end),
        cubic(left_horn, (-.775, -.335), (-.746, -.448), left_tip))
    return _fit(crown, underside)


def harvest_wheat():
    """One tilted ear of wheat with six plump kernels, their bristles, and the terminal grain."""
    root = (0., -.45)
    stem = cubic((-.11, -.95), (-.045, -.77), (-.027, -.62), root)
    right, left = [], []
    for i, width in enumerate((.34, .345, .27)):
        y = root[1] + i * .30
        bottom, top = (0., y), (0., y + .30)
        for side, kernels in ((1, right), (-1, left)):
            tip = (side * width, y + .36)
            base = cubic(bottom, (side * width * .32, y + .002), (side * width * .93, y + .125), tip)
            lip = cubic(tip, (side * width * .54, y + .358), (side * width * .19, y + .337), top)
            bristle = cubic(tip, (side * (width + .03), y + .452), (side * (width + .075), y + .585),
                            (side * (width + .091), y + .68 - .032 * i))
            kernels.append(chain(base, bristle, bristle[::-1], lip))
    y = top[1]
    tip = (.01, y + .45)
    crown = chain(cubic(top, (-.133, y + .13), (-.091, y + .26), tip),
                  cubic(tip, (.104, y + .25), (.111, y + .09), top))

    # The return follows the opposite row of kernels, leaving their open faces intact.
    path = chain(stem, *right, crown, *(kernel[::-1] for kernel in reversed(left)), stem[::-1])
    tilt = math.radians(-19)
    return _fit(path @ np.array([[math.cos(tilt), math.sin(tilt)], [-math.sin(tilt), math.cos(tilt)]]))


def harvest_pear():
    """A Bartlett pear cut lengthwise, with a core joining the two seed outlines."""
    crown, seed_tip = (.10, .60), (-.002, -.243)
    fruit = chain(
        cubic(crown, (.015, .59), (-.09, .69), (-.16, .52)),
        cubic((-.16, .52), (-.24, .36), (-.23, .16), (-.38, -.012)),
        cubic((-.38, -.012), (-.51, -.18), (-.68, -.32), (-.663, -.565)),
        cubic((-.663, -.565), (-.64, -.829), (-.413, -.939), (-.164, -.929)),
        cubic((-.164, -.929), (.02, -.92), (.111, -.953), (.27, -.912)),
        cubic((.27, -.912), (.507, -.846), (.637, -.651), (.594, -.416)),
        cubic((.594, -.416), (.562, -.224), (.416, -.091), (.343, .073)),
        cubic((.343, .073), (.254, .261), (.299, .427), (.244, .555)),
        cubic((.244, .555), (.207, .646), (.164, .632), crown))
    stem = cubic(crown, (.131, .773), (.189, .885), (.325, .977))
    core = cubic(crown, (.008, .33), (.15, -.01), seed_tip)
    left_seed = chain(
        cubic(seed_tip, (-.088, -.296), (-.254, -.348), (-.23, -.47)),
        cubic((-.23, -.47), (-.206, -.603), (-.053, -.552), (-.021, -.442)),
        cubic((-.021, -.442), (.002, -.376), (.01, -.307), seed_tip))
    right_seed = chain(
        cubic(seed_tip, (.103, -.245), (.238, -.283), (.235, -.389)),
        cubic((.235, -.389), (.224, -.504), (.112, -.491), (.057, -.41)),
        cubic((.057, -.41), (.02, -.345), (.014, -.292), seed_tip))
    return _fit(fruit, stem, stem[::-1], core, left_seed, right_seed, core[::-1])


def desk_lamp():
    """A hinged task lamp with a weighted foot and a bulb below the tilted shade."""
    foot_left, foot_right, pivot = (-.82, -.9), (.27, -.9), (-.27, -.68)
    base_left = cubic(foot_left, (-.785, -.767), (-.513, -.683), pivot)
    base_right = cubic(pivot, (-.056, -.673), (.243, -.789), foot_right)
    sole = cubic(foot_right, (.319, -.963), (-.834, -.963), foot_left)
    elbow, cap, head = (-.71, .055), (-.008, .731), (.11, .575)
    arm = chain(cubic(pivot, (-.429, -.414), (-.581, -.109), elbow),
                cubic(elbow, (-.507, .253), (-.191, .574), cap),
                cubic(cap, (.036, .79), (.080, .689), head))

    # The brim and bulb share the same tilted axis. Their contact points split
    # the lip so the ball can draw the exposed bulb without cutting the shade.
    def shade(across, depth):
        return (head[0] + .898*across + .439*depth,
                head[1] + .439*across - .898*depth)

    left, right = shade(-.437, .608), shade(.437, .608)
    bulb_left, bulb_right = shade(-.16, .644), shade(.16, .644)
    dome_left = cubic(head, shade(-.24, 0), shade(-.395, .244), left)
    dome_right = cubic(head, shade(.27, 0), shade(.387, .239), right)
    left_lip = cubic(left, shade(-.38, .635), shade(-.24, .645), bulb_left)
    center_lip = cubic(bulb_left, shade(-.05, .65), shade(.05, .65), bulb_right)
    right_lip = cubic(bulb_right, shade(.24, .645), shade(.374, .632), right)
    bulb = cubic(bulb_left, shade(-.18, .933), shade(.169, .951), bulb_right)
    return _fit(base_left, arm, dome_left, left_lip, bulb, center_lip[::-1],
                center_lip, right_lip, dome_right[::-1], arm[::-1], base_right, sole)


def acorn_oak():
    """An acorn in its cup and a rounded white-oak leaf on the same twig."""
    stem, fork = (-.39, .38), (-.15, .56)
    left, right, point = (-.86, .017), (.044, .032), (-.40, -.82)
    left_cup = cubic(left, (-.90, .21), (-.61, .39), stem)
    right_cup = cubic(stem, (-.16, .398), (.07, .23), right)
    # The cap overhangs the body. Its single scalloped lip divides the smooth
    # nut from the domed cup without hatching over either surface.
    seam = chain(cubic(right, (-.02, -.045), (-.13, -.10), (-.23, -.074)),
                 cubic((-.23, -.074), (-.31, -.154), (-.43, -.16), (-.51, -.097)),
                 cubic((-.51, -.097), (-.66, -.143), (-.79, -.055), left))
    nut = chain(cubic(left, (-.77, -.024), (-.835, -.385), (-.65, -.585)),
                cubic((-.65, -.585), (-.559, -.685), (-.437, -.697), point),
                cubic(point, (-.363, -.692), (-.245, -.697), (-.128, -.57)),
                cubic((-.128, -.57), (.038, -.385), (-.057, -.055), right))

    twig = cubic(stem, (-.344, .456), (-.224, .52), fork)
    twig_tip = cubic(fork, (-.072, .64), (-.025, .735), (.028, .768))
    leaf_base = (.173, .61)
    stalk = cubic(fork, (-.056, .626), (.089, .634), leaf_base)
    # Two sinuses on each side separate broad rounded lobes. The vein
    # stops below the tip, where the blade gets narrower than two grooves.
    bank = chain(cubic((0, 0), (-.034, .085), (-.19, .061), (-.225, .168)),
                 cubic((-.225, .168), (-.31, .322), (-.158, .303), (-.155, .38)),
                 cubic((-.155, .38), (-.161, .455), (-.32, .419), (-.323, .555)),
                 cubic((-.323, .555), (-.326, .719), (-.169, .682), (-.155, .747)),
                 cubic((-.155, .747), (-.146, .823), (-.231, .872), (-.135, 1.029)),
                 cubic((-.135, 1.029), (-.090, 1.133), (-.036, 1.153), (0, 1.184)))
    far_bank = bank[::-1] * [-1, 1]
    far_bank[:, 1] -= .047 * np.sin(math.pi * far_bank[:, 1] / 1.184)
    midrib = cubic((0, 0), (-.025, .27), (.018, .58), (.006, .802))
    leaf = chain(bank, far_bank, midrib, midrib[::-1])
    axis = np.array([.625, -.781]); axis /= np.linalg.norm(axis)
    leaf = leaf_base + leaf[:, :1] * [-axis[1], axis[0]] + leaf[:, 1:] * axis
    return _fit(left_cup, twig, twig_tip, twig_tip[::-1], stalk, leaf, stalk[::-1],
                twig[::-1], right_cup, seam, nut, seam)


def ear_of_corn():
    """An exposed ear with staggered kernels between two partly peeled husks."""
    lefts = [(-.356, .018), (-.392, .295), (-.325, .57)]
    rights = [(.355, .045), (.388, .32), (.316, .595)]
    apex, base, overlap = (0, .905), (.013, -.895), (.055, -.354)
    left_tip, right_tip = (-.793, .404), (.747, .491)
    left_edge = cubic(base, (-.466, -.72), (-.662, -.238), left_tip)
    left_fold = cubic(left_tip, (-.586, .256), (-.477, .077), lefts[0])
    left_inner = cubic(lefts[0], (-.194, -.064), (-.056, -.22), overlap)
    right_inner = cubic(overlap, (.153, -.192), (.237, -.054), rights[0])
    right_fold = cubic(rights[0], (.454, .19), (.56, .39), right_tip)
    right_edge = cubic(right_tip, (.687, -.14), (.454, -.67), base)
    lower_fold = cubic(base, (.179, -.70), (.158, -.51), overlap)
    husk_vein = cubic(base, (-.064, -.735), (-.261, -.40), (-.384, -.135))
    left_shoulder = cubic(lefts[2], (-.278, .761), (-.128, .909), apex)
    right_shoulder = cubic(apex, (.139, .89), (.263, .763), rights[2])

    t = np.linspace(0, 1, 31)[:, None]
    rows = [(1-t) * a + t * b + np.sin(np.pi*t) * [0, -.058]
            for a, b in zip(np.array(lefts), np.array(rights))]

    # Stagger the kernels so the ball never scores a continuous straight
    # line down the middle of the ear. Each division branches from a row
    # and rejoins at that exact point by retracing the groove.
    courses = []
    for band, columns in enumerate(((15,), (10, 21), (15,))):
        row = rows[band]
        pieces = []
        start = 0
        for col in columns:
            root = row[col]
            end = rows[band+1][col] if band + 1 < len(rows) else np.asarray(apex)
            bow = np.array([-.023 if col < 15 else .023, 0])
            division = cubic(root, root + .32 * (end - root) + bow,
                             root + .72 * (end - root) + bow, end)
            pieces.extend((row[start:col+1], division, division[::-1]))
            start = col
        courses.append(chain(*pieces, row[start:]))
    # Pick up the top of the right flank while passing it, then alternate
    # across the rows. Return to the open husks down the left flank.
    kernels = chain(courses[0], [rights[0], rights[1], rights[2], rights[1]], courses[1][::-1],
                    [lefts[1], lefts[2]], courses[2], right_shoulder[::-1], left_shoulder[::-1],
                    [lefts[2], lefts[1], lefts[0]])
    path = _fit(left_edge, left_fold, kernels, left_inner, right_inner,
                right_fold, right_edge, lower_fold, lower_fold[::-1], husk_vein, husk_vein[::-1])
    # A slight tilt leaves one husk lower than the other in the chair view.
    a = math.radians(13)
    return path @ np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def maple_leaf():
    """Give the five-pointed border leaf its own petiole and room for the veins."""
    stem = cubic((-.17, -.31), (-.07, -.23), (.01, -.12), (0, 0))
    return _fit(stem, maple(), stem[::-1])


def wishbone():
    """One continuous silhouette around two bowed shanks and the raised keel."""
    keel, crotch = (.025, .96), (-.005, .35)
    right_knuckle, left_knuckle = (.80, -.62), (-.73, -.70)
    outer_right = chain(cubic(keel, (.16, .98), (.17, .87), (.10, .77)),
                        cubic((.10, .77), (.08, .68), (.14, .64), (.20, .59)),
                        cubic((.20, .59), (.48, .40), (.60, .01), (.65, -.36)),
                        cubic((.65, -.36), (.68, -.52), (.75, -.50), right_knuckle))
    inner_right = chain(cubic(right_knuckle, (.89, -.77), (.67, -.86), (.57, -.65)),
                        cubic((.57, -.65), (.47, -.42), (.44, -.11), (.31, .09)),
                        cubic((.31, .09), (.21, .25), (.07, .39), crotch))
    inner_left = chain(cubic(crotch, (-.17, .28), (-.28, .06), (-.36, -.18)),
                       cubic((-.36, -.18), (-.43, -.42), (-.48, -.64), (-.61, -.76)),
                       cubic((-.61, -.76), (-.73, -.84), (-.81, -.77), left_knuckle))
    outer_left = chain(cubic(left_knuckle, (-.67, -.57), (-.62, -.55), (-.60, -.42)),
                       cubic((-.60, -.42), (-.58, -.12), (-.46, .34), (-.24, .53)),
                       cubic((-.24, .53), (-.14, .60), (-.065, .66), (-.075, .75)),
                       cubic((-.075, .75), (-.13, .87), (-.095, .96), keel))
    return _fit(outer_right, inner_right, inner_left, outer_left)


def cornucopia():
    """A curved horn with a woven rib, a pear at the mouth, and a spilling apple."""
    tip, rib_top, lip = (-.86, .46), (-.28, .07), (.22, .48)
    rib_base, rim_base = (-.48, -.36), (.40, -.49)
    curl = chain(cubic(tip, (-1.01, .37), (-.98, .22), (-.86, .10)),
                 cubic((-.86, .10), (-.77, -.012), (-.66, -.08), (-.56, -.07)),
                 cubic((-.56, -.07), (-.46, -.07), (-.38, -.02), rib_top))
    crown = cubic(rib_top, (-.10, .22), (.06, .45), lip)
    under_curl = cubic(tip, (-1.20, .46), (-1.10, -.14), rib_base)
    belly = cubic(rib_base, (-.25, -.54), (.07, -.62), rim_base)
    rib = cubic(rib_top, (-.43, .025), (-.54, -.14), rib_base)
    rim = chain(cubic(lip, (.04, .56), (-.10, .23), (-.055, -.027)),
                cubic((-.055, -.027), (-.02, -.28), (.13, -.51), rim_base))

    pear_neck, shoulder, apple_bottom = (.36, .61), (.49, .10), (.44, -.36)
    pear_top = cubic(lip, (.27, .52), (.27, .67), pear_neck)
    pear_stem = cubic(pear_neck, (.38, .69), (.39, .75), (.45, .78))
    pear_right = chain(cubic(pear_neck, (.46, .63), (.43, .49), (.49, .42)),
                       cubic((.49, .42), (.58, .34), (.68, .20), (.61, .12)),
                       cubic((.61, .12), (.57, .13), (.53, .14), shoulder))
    pear_left = cubic(shoulder, (.19, .017), (.085, .29), lip)
    apple_cleft = (.73, .043)
    apple_left = cubic(shoulder, (.34, .06), (.32, -.21), apple_bottom)
    apple_right = chain(cubic(apple_bottom, (.52, -.47), (.62, -.37), (.69, -.40)),
                        cubic((.69, -.40), (.84, -.46), (.97, -.27), (1.00, -.11)),
                        cubic((1.00, -.11), (1.04, .071), (.89, .20), apple_cleft))
    apple_stem = cubic(apple_cleft, (.74, .12), (.79, .17), (.84, .20))
    apple_top = cubic(apple_cleft, (.67, .07), (.58, .14), shoulder)
    # Hidden parts of the rim stop at the fruit. Every return follows an
    # existing groove, including the trip between the apple and lower lip.
    fruit_edge = cubic(apple_bottom, (.44, -.40), (.43, -.46), rim_base)
    return _fit(curl, rib, rib[::-1], crown, pear_top,
                pear_stem, pear_stem[::-1], pear_right, apple_left, apple_right,
                apple_stem, apple_stem[::-1], apple_top, pear_left, rim, fruit_edge[::-1],
                fruit_edge, belly[::-1], under_curl[::-1])


def gravy_boat():
    """A low porcelain sauce boat with a pulled lip, open handle and flared foot."""
    lip, rim, handle_base = (-1.23, .55), (.34, .24), (.32, -.18)
    toe, heel = (-.36, -.40), (.09, -.40)
    back = chain(cubic(lip, (-.91, .52), (-.77, .35), (-.52, .34)),
                 cubic((-.52, .34), (-.17, .36), (.21, .42), rim))
    front = chain(cubic(lip, (-1.00, .53), (-.85, .15), (-.60, .068)),
                  cubic((-.60, .068), (-.30, -.03), (.19, .02), rim))
    handle = chain(cubic(rim, (.53, .48), (.81, .59), (.93, .40)),
                   cubic((.93, .40), (1.12, .13), (.73, -.11), handle_base))
    right_rim = cubic(rim, (.43, .13), (.41, -.05), handle_base)
    right_side = cubic(handle_base, (.28, -.27), (.22, -.35), heel)
    left_side = chain(cubic(lip, (-1.13, .34), (-.91, .32), (-.825, .067)),
                      cubic((-.825, .067), (-.765, -.18), (-.62, -.36), toe))
    base = cubic(toe, (-.22, -.44), (-.04, -.44), heel)
    foot = chain(cubic(toe, (-.38, -.49), (-.63, -.50), (-.58, -.54)),
                 cubic((-.58, -.54), (-.50, -.64), (.21, -.64), (.32, -.54)),
                 cubic((.32, -.54), (.36, -.50), (.13, -.49), heel))
    return _fit(foot, right_side[::-1], handle[::-1], back[::-1], left_side, base,
                right_side[::-1], right_rim[::-1], front[::-1], left_side)


def turkey_leg():
    """An upright roast drumstick with a double-knobbed bone and two carving marks."""
    shoulder, hip = (-.78, .61), (-.72, -.32)
    upper, lower = (.43, -.045), (.245, -.32)
    shoulder_edge = chain(cubic(upper, (.29, .10), (.24, .35), (-.04, .59)),
                          cubic((-.04, .59), (-.25, .75), (-.57, .78), shoulder))
    round_end = chain(cubic(shoulder, (-.99, .47), (-1.045, .24), (-1.01, .03)),
                      cubic((-1.01, .03), (-.99, -.15), (-.88, -.27), hip))
    underside = chain(cubic(hip, (-.55, -.38), (-.40, -.38), (-.22, -.32)),
                      cubic((-.22, -.32), (-.06, -.27), (.035, -.365), lower))
    skin_edge = chain(cubic(lower, (.30, -.335), (.30, -.23), (.33, -.21)),
                      cubic((.33, -.21), (.43, -.20), (.40, -.09), upper))
    bone = chain(cubic(upper, (.57, -.17), (.69, -.28), (.80, -.31)),
                 cubic((.80, -.31), (.94, -.18), (1.09, -.26), (1.085, -.405)),
                 cubic((1.085, -.405), (1.08, -.475), (1.02, -.505), (.99, -.51)),
                 cubic((.99, -.51), (1.055, -.65), (.91, -.755), (.805, -.68)),
                 cubic((.805, -.68), (.75, -.65), (.75, -.57), (.76, -.51)),
                 cubic((.76, -.51), (.61, -.46), (.43, -.32), lower))
    lower_mark = cubic(hip, (-.62, -.21), (-.69, -.018), (-.42, .117))
    upper_mark = cubic(shoulder, (-.49, .61), (-.41, .37), (-.27, .31))
    path = _fit(bone, skin_edge, shoulder_edge, upper_mark, upper_mark[::-1],
                round_end, lower_mark, lower_mark[::-1], underside, skin_edge)
    # The seat-facing garden approaches the bottom of the drawing. Turn the
    # bone up so the entrance meets the roast and leaves both knobs intact.
    angle = np.radians(14)
    return (path * [1, -1]) @ np.array([[np.cos(angle), np.sin(angle)],
                                        [-np.sin(angle), np.cos(angle)]])


def pilgrim_hat():
    """A felt crown, turned brim and broad buckle, upright in a guest place."""
    left, right = (-.657, -.287), (.605, -.240)
    left_band, right_band = (-.600, .024), (.542, .055)
    left_shoulder, right_shoulder = (-.431, .703), (.326, .732)
    left_side = cubic(left, (-.646, -.202), (-.618, -.065), left_band)
    right_side = cubic(right, (.594, -.171), (.551, -.001), right_band)
    crown = chain(cubic(left_band, (-.560, .203), (-.499, .525), left_shoulder),
                  cubic(left_shoulder, (-.42, .749), (-.354, .757), (-.285, .744)),
                  cubic((-.285, .744), (-.094, .713), (.119, .792), (.260, .775)),
                  cubic((.260, .775), (.301, .77), (.318, .758), right_shoulder),
                  cubic(right_shoulder, (.368, .565), (.498, .231), right_band))
    left_tip, right_tip = (-1.017, -.21), (1.007, -.112)
    left_brim = cubic(left_tip, (-.967, -.168), (-.77, -.20), left)
    right_brim = cubic(right, (.771, -.203), (.887, -.136), right_tip)
    brim = chain(cubic(right_tip, (1.057, -.228), (.935, -.368), (.713, -.451)),
                 cubic((.713, -.451), (.34, -.62), (-.249, -.678), (-.619, -.558)),
                 cubic((-.619, -.558), (-.800, -.507), (-1.045, -.375), left_tip))

    # The leather ends at the buckle on both sides. A single tongue leaves
    # a broad open window even when grooves are seven millimetres wide.
    lo_left, hi_left = (-.262, -.325), (-.262, -.018)
    lo_right, hi_right = (.274, -.304), (.274, .005)
    lower_left = cubic(left, (-.526, -.311), (-.379, -.331), lo_left)
    lower_right = cubic(lo_right, (.378, -.306), (.501, -.274), right)
    upper_left = cubic(left_band, (-.489, -.003), (-.344, -.019), hi_left)
    upper_right = cubic(hi_right, (.386, .004), (.459, .036), right_band)
    buckle_top = chain(cubic(hi_right, (.274, .061), (.297, .12), (.221, .122)),
                       cubic((.221, .122), (.074, .115), (-.099, .111), (-.204, .101)),
                       cubic((-.204, .101), (-.262, .10), (-.266, .047), hi_left))
    buckle_bottom = chain(cubic(lo_left, (-.263, -.412), (-.257, -.44), (-.186, -.441)),
                          cubic((-.186, -.441), (-.039, -.446), (.117, -.428), (.216, -.419)),
                          cubic((.216, -.419), (.274, -.419), (.271, -.362), lo_right))
    buckle_right = cubic(lo_right, (.277, -.205), (.277, -.083), hi_right)
    hinge = (-.262, -.164)
    above_hinge = cubic(hi_left, (-.266, -.069), (-.262, -.124), hinge)
    below_hinge = cubic(hinge, (-.263, -.227), (-.26, -.276), lo_left)
    tongue = cubic(hinge, (-.192, -.167), (-.113, -.157), (-.035, -.155))
    buckle_left = chain(above_hinge, tongue, tongue[::-1], below_hinge)

    # Set the outline first. Finishing with the edges of the buckle then the
    # front brim keeps the tongue distinct after the ball passes the band.
    return _fit(left_brim, left_side, crown, right_side[::-1], right_brim, brim,
                left_brim, lower_left, buckle_bottom, lower_right, right_side,
                upper_right[::-1], buckle_top, upper_left[::-1], upper_left,
                buckle_left, buckle_bottom, buckle_right, upper_right,
                right_side[::-1], right_brim, brim)


def lotus_blossom():
    """An open, five-petalled lotus above a round, gently folded leaf."""
    base, apex = (0, -.13), (.028, .755)
    inner, shoulder = np.array([.223, .319]), (.482, .235)
    middle_tip, outer_tip = (.496, .655), (.939, .469)
    mirror = np.array([-1, 1])
    lower_petal = cubic(base, (.145, -.043), (.238, .130), inner)
    right_petal = cubic(inner, (.235, .478), (.103, .643), apex)
    left_petal = cubic(inner * mirror, (-.234, .509), (-.072, .656), apex)

    # Only draw the visible part of each petal where another overlaps it.
    # Follow the existing edges on the return to keep each petal face open.
    rise = cubic(inner, (.29, .487), (.437, .570), middle_tip)
    shoulder_edge = cubic(middle_tip, (.516, .558), (.544, .390), shoulder)
    middle_edge = cubic(shoulder, (.390, -.01), (.162, -.101), base)
    outer_rise = cubic(shoulder, (.623, .343), (.789, .379), outer_tip)
    outer_edge = cubic(outer_tip, (.842, .125), (.498, -.173), base)
    side = chain(rise, shoulder_edge, outer_rise, outer_edge, middle_edge[::-1],
                 shoulder_edge[::-1], rise[::-1])
    flower = chain(lower_petal, side, right_petal, left_petal[::-1], side * mirror,
                   lower_petal[::-1] * mirror)
    flower[:, 1] += .093 * flower[:, 0]

    # A lotus leaf has a continuous margin. One fold through its depressed
    # centre survives the sand groove, leaving room for the broad surface.
    stem_end, left, right = (.022, -.331), (-.898, -.546), (.855, -.318)
    stem = cubic(base, (-.033, -.221), (-.009, -.289), stem_end)
    rear = chain(cubic(stem_end, (.259, -.295), (.477, -.20), (.672, -.23)),
                 cubic((.672, -.23), (.762, -.238), (.842, -.256), right))
    front = chain(cubic(right, (.938, -.485), (.746, -.545), (.484, -.604)),
                  cubic((.484, -.604), (.214, -.637), (.033, -.844), (-.235, -.821)),
                  cubic((-.235, -.821), (-.464, -.818), (-.476, -.737), (-.634, -.710)),
                  cubic((-.634, -.710), (-.777, -.687), (-.939, -.654), left))
    far_edge = chain(cubic(left, (-.859, -.446), (-.69, -.383), (-.51, -.364)),
                     cubic((-.51, -.364), (-.318, -.334), (-.182, -.352), stem_end))
    middle = (-.166, -.56)
    fold = chain(cubic(stem_end, (-.043, -.407), (-.094, -.503), middle),
                 cubic(middle, (-.270, -.589), (-.43, -.597), (-.52, -.588)))
    return _fit(stem, rear, front, far_edge, fold, fold[::-1], stem[::-1], flower)


def roast_turkey():
    """A whole roast in profile, with a tucked wing and drumstick on an oval platter."""
    heel, shoulder = (-.668, -.342), (-.841, .053)
    crown, back, thigh = (-.232, .635), (.024, .55), (.196, .151)
    lower_bone, upper_bone = (.677, .11), (.566, .244)
    leg_base, plate_joint = (.127, -.38), (.554, -.31)
    flank = cubic(heel, (-.751, -.271), (-.825, -.172), shoulder)
    breast = chain(cubic(shoulder, (-.875, .319), (-.639, .67), crown),
                   cubic(crown, (-.104, .64), (-.055, .614), back),
                   cubic(back, (.193, .498), (.291, .363), thigh))
    wing_tip = (-.321, .145)
    wing = chain(cubic(shoulder, (-.689, -.094), (-.510, .049), wing_tip),
                 cubic(wing_tip, (-.389, -.111), (-.548, -.243), (-.688, -.177)),
                 cubic((-.688, -.177), (-.769, -.141), (-.806, -.036), shoulder))

    leg_top = cubic(thigh, (.364, .282), (.450, .232), upper_bone)
    # Separate the two knobs at the exposed bone. Its narrow shaft joins
    # the closed thigh contour and the rear half of the serving plate hides behind it.
    bone = chain(cubic(lower_bone, (.7276, .1700), (.7824, .2414), (.8226, .2589)),
                 cubic((.8226, .2589), (.8575, .2663), (.8961, .1977), (.9573, .2394)),
                 cubic((.9573, .2394), (1.0404, .2958), (.9482, .3742), (.8307, .3481)),
                 cubic((.8307, .3481), (.8845, .4593), (.8209, .5580), (.7539, .5013)),
                 cubic((.7539, .5013), (.6932, .4646), (.7636, .3851), (.7388, .3600)),
                 cubic((.7388, .3600), (.6897, .3092), (.6290, .2725), upper_bone))
    leg_edge = cubic(lower_bone, (.635, .035), (.659, -.181), plate_joint)
    drumstick = cubic(plate_joint, (.436, -.430), (.244, -.443), leg_base)
    leg_inner = chain(cubic(leg_base, (-.025, -.338), (-.085, -.161), (-.011, -.011)),
                      cubic((-.011, -.011), (.033, .082), (.126, .128), thigh))
    belly = cubic(leg_base, (-.194, -.453), (-.51, -.458), heel)

    left, right = (-1.012, -.253), (.988, -.239)
    left_rim = cubic(heel, (-.795, -.345), (-.939, -.320), left)
    right_rim = cubic(plate_joint, (.729, -.177), (.931, -.181), right)
    front_rim = chain(cubic(right, (1.021, -.432), (.541, -.618), (.111, -.644)),
                      cubic((.111, -.644), (-.337, -.696), (-.949, -.527), left))
    return _fit(flank, wing, breast, leg_top, bone[::-1], leg_edge, drumstick, leg_inner,
                leg_inner[::-1], belly, left_rim, front_rim[::-1], right_rim[::-1], drumstick, belly)


def dinner_candle():
    """A lit wax taper in a shallow chamberstick with an open finger handle."""
    left_rim, right_rim = (-.795, -.445), (.381, -.392)
    left_base, right_base = (-.376, -.297), (.039, -.288)
    left_top, right_top = (-.369, .919), (.036, .943)
    wick_base, wick_tip = (-.187, .890), (-.197, 1.057)

    left_edge = cubic(left_base, (-.380, .173), (-.366, .604), left_top)
    right_edge = cubic(right_base, (.047, .129), (.032, .629), right_top)
    wax_left = cubic(left_top, (-.313, .972), (-.267, .853), wick_base)
    wax_right = cubic(wick_base, (-.119, .909), (-.035, .990), right_top)
    wick = cubic(wick_base, (-.182, .953), (-.192, 1.017), wick_tip)
    flame_tip = (-.060, 1.475)
    flame = chain(cubic(wick_tip, (-.404, 1.103), (-.356, 1.246), (-.252, 1.329)),
                  cubic((-.252, 1.329), (-.158, 1.398), (-.099, 1.427), flame_tip),
                  cubic(flame_tip, (-.092, 1.345), (.004, 1.291), (-.016, 1.208)),
                  cubic((-.016, 1.208), (-.038, 1.109), (-.128, 1.061), wick_tip))
    drip = chain(cubic(right_top, (-.011, .833), (-.084, .859), (-.100, .639)),
                 cubic((-.100, .639), (-.127, .355), (-.243, .396), (-.246, .639)),
                 cubic((-.246, .639), (-.260, .784), (-.314, .778), left_top))
    wax_base = cubic(left_base, (-.283, -.379), (-.064, -.371), right_base)

    back = cubic(left_rim, (-.682, -.351), (-.497, -.312), left_base)
    side = cubic(right_base, (.123, -.277), (.283, -.333), right_rim)
    front = cubic(right_rim, (.173, -.582), (-.609, -.618), left_rim)
    foot = chain(cubic(left_rim, (-.725, -.622), (-.498, -.707), (-.324, -.718)),
                 cubic((-.324, -.718), (-.016, -.755), (.278, -.633), right_rim))
    handle_base = (.310, -.506)
    handle = chain(cubic(right_rim, (.390, -.149), (.542, .114), (.705, .032)),
                   cubic((.705, .032), (.913, -.062), (.903, -.412), (.742, -.494)),
                   cubic((.742, -.494), (.581, -.569), (.410, -.566), handle_base))
    join = cubic(handle_base, (.334, -.475), (.362, -.433), right_rim)
    # Follow the wick and the wax edge back to the saucer without marking
    # the face of the candle or the opening in the handle.
    return _fit(back, left_edge, wax_left, wick, flame, wick[::-1], wax_right, drip,
                left_edge[::-1], wax_base, right_edge, right_edge[::-1], side,
                handle, join, front, foot, front)


def caramel_apple():
    """Two lobes of an apple, with a tilted wooden stick and a dripping coating."""
    left, right = (-.754, .101), (.747, .108)
    left_root, right_root = (-.113, .333), (.084, .357)
    lower_left, lower_right, notch = (-.303, -.680), (.211, -.673), (-.044, -.604)
    left_crown = chain(cubic(left_root, (-.244, .394), (-.333, .554), (-.533, .493)),
                       cubic((-.533, .493), (-.667, .463), (-.752, .302), left))
    right_crown = chain(cubic(right_root, (.236, .432), (.373, .554), (.543, .472)),
                        cubic((.543, .472), (.689, .424), (.747, .289), right))
    bottom = chain(cubic(left, (-.751, -.162), (-.549, -.637), lower_left),
                   cubic(lower_left, (-.209, -.717), (-.093, -.638), notch),
                   cubic(notch, (.027, -.600), (.108, -.694), lower_right),
                   cubic(lower_right, (.475, -.695), (.733, -.154), right))
    tip_left, tip_right = (.335, 1.170), (.526, 1.080)
    stick = chain(cubic(left_root, (.034, .596), (.198, .930), tip_left),
                  cubic(tip_left, (.345, 1.198), (.526, 1.119), tip_right),
                  cubic(tip_right, (.363, .820), (.223, .548), right_root))
    cleft = cubic(left_root, (-.055, .286), (.035, .287), right_root)
    # The long drip hangs below a second, shorter one. Connect them along
    # the coating boundary so there is no travel line through the fruit.
    coating = chain(cubic(left, (-.584, .090), (-.591, .026), (-.523, -.031)),
                    cubic((-.523, -.031), (-.432, -.125), (-.365, .135), (-.300, .06)),
                    cubic((-.300, .06), (-.216, -.03), (-.348, -.286), (-.176, -.285)),
                    cubic((-.176, -.285), (-.016, -.281), (-.095, -.051), (.028, -.035)),
                    cubic((.028, -.035), (.111, -.022), (.159, -.170), (.256, -.162)),
                    cubic((.256, -.162), (.371, -.151), (.319, .077), (.439, .081)),
                    cubic((.439, .081), (.581, .079), (.661, .032), right))
    return _fit(left_crown[::-1], stick, cleft[::-1], cleft, right_crown,
                coating[::-1], bottom, bottom[::-1])


def mayflower_ship():
    """Side view of a merchant ship with two square sails and a triangular mizzen."""
    stern, mizzen, main, fore, bow = (-.98, -.005), (-.76, -.03), (-.13, -.28), (.59, -.21), (.91, -.12)
    main_yard, fore_yard = (-.22, .80), (.52, .57)
    flag_head, flag_tip, flag_foot = (-.245, 1.10), (-.655, 1.06), (-.235, .94)
    pennant = chain([main_yard, flag_head],
                    cubic(flag_head, (-.395, 1.19), (-.515, 1.01), flag_tip),
                    cubic(flag_tip, (-.435, .91), (-.395, 1.03), flag_foot),
                    [flag_foot, main_yard])

    def square_sail(mast, left, yard, right, clew, foot, tack, masthead):
        # The leaning yard and curved leeches put the wind in both sails.
        return chain([mast, foot],
                     cubic(foot, (foot[0]-.10, foot[1]+.07), (tack[0]+.05, tack[1]+.04), tack),
                     cubic(tack, (tack[0]+.18, tack[1]+.18), (left[0]+.23, left[1]-.13), left),
                     [left, yard], masthead, [yard, right],
                     cubic(right, (right[0]+.23, right[1]-.22), (clew[0]+.14, clew[1]+.18), clew),
                     cubic(clew, (clew[0]-.08, clew[1]+.06), (foot[0]+.08, foot[1]+.055), foot),
                     [foot, mast])

    mainsail = square_sail(main, (-.53, .87), main_yard, (.02, .75), (.12, .12),
                           (-.12, .07), (-.45, .13), pennant)
    foresail = square_sail(fore, (.29, .62), fore_yard, (.76, .50), (.80, .04),
                           (.58, .02), (.31, .09), [fore_yard, (.495, .645), fore_yard])
    mizzen_foot, peak, yard_end = (-.755, .10), (-1.07, .72), (-.58, .48)
    lateen = chain([mizzen, mizzen_foot], cubic(mizzen_foot, (-.81, .26), (-.96, .52), peak),
                   [peak, yard_end], cubic(yard_end, (-.58, .35), (-.68, .13), mizzen_foot),
                   [mizzen_foot, mizzen])
    hull = chain(cubic(bow, (.75, -.47), (.57, -.70), (.19, -.76)),
                 cubic((.19, -.76), (-.14, -.80), (-.53, -.73), (-.71, -.64)),
                 cubic((-.71, -.64), (-.87, -.50), (-.94, -.19), stern))
    return _fit([stern, mizzen], lateen, [mizzen, (-.57, -.04), (-.53, -.22), main],
                mainsail, cubic(main, (.02, -.31), (.37, -.28), fore), foresail,
                cubic(fore, (.71, -.19), (.77, -.16), bow), [bow, (1.09, .12), bow], hull)
