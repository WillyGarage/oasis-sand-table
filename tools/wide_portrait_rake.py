"""Carve the shadow in the selected photograph by bunching a wide center's clearing turns."""
import base64
import math

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from wide_portrait import evaluate_geometry, plan_marks, save_portrait


def shadow_field(source, marks, translation):
    crop = source.get('crop')
    if not crop or not marks:
        raise ValueError('This photograph needs a separate engraved face and its original crop.')
    encoded = np.frombuffer(base64.b64decode(crop['png'], validate=True), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != (600, 600):
        raise ValueError('The selected face has no registered photo crop.')
    size = image.shape[0]
    scale = size / source['diameter']
    offset = np.asarray(translation if translation is not None else [0, 0])
    xy_scale = np.array([scale, -scale])
    zero = size / 2 - offset * xy_scale
    groove = scale * source['width']

    def pixels(mark):
        return np.asarray(mark['points']) * xy_scale + zero

    glasses = [pixels(mark) for mark in marks if mark['kind'] == 'glasses']
    eyes = glasses if len(glasses) == 2 else [pixels(mark) for mark in marks if mark['kind'] == 'eye']
    smiles = [pixels(mark) for mark in marks if mark['kind'] == 'smile']
    if len(eyes) != 2 or not smiles:
        raise ValueError('This print needs two engraved eyes and a smile in the crop.')
    eyes = np.concatenate(eyes)
    ex, ey = np.mean(eyes[:, 0]), np.median(eyes[:, 1])
    width = np.ptp(eyes[:, 0])
    mouth = np.median(smiles[0][:, 1])
    height = mouth - ey
    if min(height, width) < 3 * groove:
        raise ValueError('The selected face is too small to keep the shadows clear of its expression.')

    head = np.zeros((size, size), np.uint8)
    protected = np.zeros_like(head)
    facial = []
    for mark in marks:
        points = pixels(mark)
        kind = mark['kind']
        if kind == 'head' or (kind == 'hairline' and mark['closed']):
            cv2.fillPoly(head, [np.rint(points).astype('int32')], 255)
        x, y = np.median(points, axis=0)
        if kind == 'shade':
            expression = eyes[:, 0].min()-1.5*groove < x < eyes[:, 0].max()+1.5*groove and ey-2.5*groove < y < mouth+groove
            ear = abs(x-ex) > .69*width and ey-1.5*groove < y < mouth+.27*height
            if not (expression or ear or mark.get('chinStrand') or mark.get('facialHair')):
                continue
        facial.append(mark)
        if kind not in ('head', 'hairline'):
            cv2.polylines(protected, [np.rint(points).astype('int32')], mark['closed'], 255, round(1.2*groove))

    yy, xx = np.indices(head.shape)
    oval = ((xx-ex)/(.92*width))**2 + ((yy-ey-.34*height)/(1.28*height))**2
    skin = (oval < .68) & (head > 0)
    if skin.sum() < 5*groove**2:
        raise ValueError('The face falls outside its selected photo crop.')
    light = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[:, :, 0]
    light = cv2.GaussianBlur(cv2.bilateralFilter(light, 13, 18, 10), (0, 0), .54*groove)
    low, high = np.percentile(light[head > 0], [6, 91])
    light = np.clip((light.astype('float32')-low)/max(1, high-low), 0, 1)
    low, high = np.percentile(light[skin], [8, 86])
    skin_tone = np.clip((high-light)/max(.12, high-low), 0, 1)
    shade = np.maximum(cv2.GaussianBlur(1-light, (0,0), .39*groove),
                       skin_tone * .63 * np.exp(-np.maximum(0, oval-.67)*1.45))
    shade = .78 * np.clip((shade-.27)/.63, 0, 1)
    clear_space = cv2.distanceTransform(255-protected, cv2.DIST_L2, 5) / groove
    radial = np.hypot(xx-zero[0], yy-zero[1]) / groove
    shade *= np.minimum(np.clip((clear_space-1.2)/2.3, 0, 1), np.clip((radial-5)/6.5, 0, 1))
    shade *= cv2.GaussianBlur(np.float32(head > 0), (0,0), .7*groove)
    return facial, shade.astype('float32'), zero, xy_scale


def engraved_points(source, plan, field, zero, scale):
    """Transfer only the center artwork. The editor owns both dock trips."""
    radius = source['radius']
    edge = source['diameter']/2
    # The face excursions share vertices with the clear. Leave their signed
    # walks and their short entrances alone. Only the calibrated spiral moves.
    route = np.asarray(plan['path'])
    waiting = np.zeros(len(route), bool)
    for event in plan['events']:
        waiting[max(0,event['first']-1):event['last']+2] = True
    transit = len(source['transit'])
    route = route[transit-1:len(route)-transit+1]
    waiting = waiting[transit-1:len(waiting)-transit+1]
    delta = np.diff(route, axis=0)
    turn, move = delta.T
    pitch = 2.8
    slope = move / np.maximum(abs(turn), 1e-12) * radius * math.tau
    eligible = (abs(turn) > .0001) & (move > 0) & (abs(slope-pitch) < .015) & ~waiting[:-1] & ~waiting[1:]
    if not np.any(eligible):
        raise ValueError('The selected garden does not have the wide photo clearing spiral.')
    length = radius*np.hypot(move, turn*np.maximum(route[:-1,1], route[1:,1]))
    counts = np.maximum(1, np.ceil(length/1.5).astype(int))
    segments = np.repeat(np.arange(len(counts)), counts)
    starts = np.repeat(np.cumsum(counts)-counts, counts)
    fractions = (np.arange(len(segments))-starts)/counts[segments]
    walk = np.vstack([route[segments]+delta[segments]*fractions[:,None], route[-1]])
    eligible = np.r_[eligible[segments], False]
    distance = np.r_[0, np.cumsum((length/counts)[segments])]
    fade = np.zeros(len(walk))
    for start, end in np.flatnonzero(np.diff(np.r_[False, eligible, False])).reshape(-1, 2):
        fade[start:end] = np.clip(np.minimum(distance[start:end]-distance[start],
                                             distance[end]-distance[start:end])/(2*source['width']), 0, 1)

    theta, radial = walk.T
    direction = np.column_stack((np.cos(theta), np.sin(theta)))
    xy = direction * (radial*radius)[:,None] * scale + zero
    coords = [xy[:, 1], xy[:, 0]]
    if field.ndim == 3:
        # A photographically oriented print supplies its X and Y offsets in mm.
        offsets = np.column_stack([map_coordinates(component, coords, order=1, mode='constant', cval=0)
                                   for component in field.transpose(2, 0, 1)])
        points = direction * (radius*radial)[:, None] + offsets*fade[:, None]
    else:
        shadow = map_coordinates(field, coords, order=1, mode='constant', cval=0)
        # Smoothly bunch several adjacent passes into a deeper-looking shade.
        # The cap keeps each moved pass within 1.85 mm of the ordinary spiral.
        spacing = 3.25*pitch
        phase = (radial*radius/spacing) % 1
        compressed = (np.tanh(11*(phase-.5))+np.tanh(5.5))/(2*np.tanh(5.5))
        strength = np.clip((shadow-.08)/.82, 0, 1)**.96
        displacement = np.clip(spacing*(compressed-phase)*strength, -1.85, 1.85)*fade
        points = direction * (radius*radial+displacement)[:,None]
    points = cv2.approxPolyDP(points.astype('float32'), .14, False)[:,0].astype(float)/edge
    if len(points) > 32000:
        raise ValueError('The photograph needs too many turns for a portable portrait.')
    points /= np.maximum(1, np.linalg.norm(points, axis=1))[:,None]
    points[0] /= np.linalg.norm(points[0])
    points[-1] = points[0]
    return np.round(points, 9).tolist()


def save_rake_print(page, source, marks, translation, directory):
    if (abs(source['radius']-420) > .001 or abs(source['diameter']-632.8) > .01 or
            abs(source['width']-7) > .001):
        raise ValueError('This print has been rehearsed on a 632.8 mm center with a 7 mm groove.')
    if not page.evaluate("typeof OasisRingPlanner.preparedPhoto==='function'"):
        raise ValueError('This garden editor does not yet support a single-pass portrait print.')
    features, field, zero, scale = shadow_field(source, marks, translation)
    face = plan_marks(page, features)
    if face is None:
        raise ValueError('The clear cannot preserve the selected face strokes.')
    result = save_raked_field(page, source, face, field, zero, scale, directory)
    return {**result, 'applied': True, 'note':'The selected face clears and draws the full center in one pass.'}


def save_raked_field(page, source, face, field, zero, scale, directory):
    points = engraved_points(source, face, field, zero, scale)
    plan = evaluate_geometry(page, """points=>{
      const g=JSON.parse(document.getElementById('scene').textContent).live;
      const route=OasisRingPlanner.preparedPhoto(g.wideCenter,points,g,true);
      return {path:route.path,verified:!!route.includesCenterRake};
    }""", points)
    if not plan['verified']:
        raise ValueError('The signed portrait could not prove full coverage of this center.')
    return save_portrait(page, {**source, 'points':points, 'includesCenterRake':True}, None, plan, directory)
