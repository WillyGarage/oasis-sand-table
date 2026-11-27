#!/usr/bin/env python3
"""Prepare a single guest's wide-center portrait privately on the garden laptop.

python3 tools/wide_portrait.py GARDEN.html PHOTO.jpg --out DEST [--face 2] [--trace-nose] [--trace-brows] [--trace-smile] [--trace-eyes]

The garden supplies the table dimensions, ordinary portrait, planner and renderer.
A local hair model proposes only the head outline and hair. If any earlier facial
stroke cannot be preserved at its original scale, the ordinary portrait wins.
With --trace-nose, a distinct photographed nose can replace the existing one
when every other downloaded stroke and its approach still fit exactly.
With --trace-brows, the laptop can recenter a brow on the pictured hair.
With --trace-smile, it can follow the opening between the lips.
With --trace-eyes, it can draw the direction of gaze and resolve visible eyes through glasses.
With --hair-woodcut, a second drawing adds slanted grooves inside the photographed
hair when the style fits. Its files are in DEST/hair-woodcut/.
With --full-hair, a wider view of long locks can be saved in DEST/full-hair/.
With --rake-print, the 632.8 mm center can shade the face during its clearing pass.
A verified example opens in Prepared portrait from DEST/rake-print/portrait.oasisportrait.
Open DEST/preview.png to see the simulated sand. In the garden's center photo
form choose Prepared portrait and open DEST/portrait.oasisportrait. The .thr
files are the exact movements. DEST/result.json records any fallback.

Hair tracing uses the photo2sand MediaPipe environment and local models in
~/.cache/photo2sand. The ordinary guest portrait also works without those models.
The source photograph stays private on the laptop.
"""

import argparse
import base64
import io
from itertools import chain
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from playwright.sync_api import sync_playwright
from scipy.optimize import minimize
from scipy.spatial import cKDTree

from check_ring_scene import read_path, joined, same_track
from thrcommon import motion_files_hash
from wide_portrait_hair import ClippedHair, measured_hair, mask_for

TOOLS = Path(__file__).resolve().parent
WEB = TOOLS.parent / 'web'
FIELDS = {'kind', 'closed', 'points', 'lids', 'rim', 'opening', 'noseBase', 'facialHair', 'chinStrand'}

# These are the normal garden APIs. Only this local invocation requests the
# selected pixels, inside the same offline browser that decoded the photograph.
SOURCE = """async selected => {
  const face=selected?.groupMember || selected;
  const scene=JSON.parse(document.getElementById('scene').textContent);
  const g=scene.live, z=g?.wideCenter || (scene.layout==='portrait' && scene.zones.center);
  if (!z || !g?.bed) throw Error('Use a locally built garden with a wide portrait center.');
  const edge=z.transit.at(-1)[1], diameter=2*edge*g.radiusMM, width=g.groove*g.radiusMM;
  const file=document.getElementById('hostPortraitInput').files[0];
  if(Number.isInteger(face)){
    const info=await GuestPhoto.inspectSeatPhoto(file);
    if(face<0 || face>=info.facesDetected)throw Error('That face number is outside the detected faces.');
  }
  let crop=null;
  function selectedPixels(image,frame,area){
    const source=document.createElement('canvas'), tile=document.createElement('canvas');
    source.width=image.width; source.height=image.height;
    source.getContext('2d').putImageData(image,0,0);
    tile.width=tile.height=600;
    const ctx=tile.getContext('2d');
    ctx.fillStyle='white';ctx.fillRect(0,0,600,600);
    ctx.drawImage(source,frame.cx-frame.radius,frame.cy-frame.radius,frame.radius*2,frame.radius*2,0,0,600,600);
    const scale=diameter/(2*frame.radius);
    const tilePoint=([x,y])=>[300+(x-frame.cx)*300/frame.radius,300+(y-frame.cy)*300/frame.radius];
    const tuft=frame.beardSmile && frame.beardStrokes?.some(line=>line.chinStrand);
    crop={area,png:tile.toDataURL('image/png').split(',')[1],
      ...(tuft ? {moustache:{corners:frame.beardSmile.corners.map(tilePoint),
        nose:[31,33,35].map(i=>tilePoint(frame.landmarks[i]))}} : {}),
      ...(frame.earTrace ? {earTrace:frame.earTrace} : {}),
      hair:frame.person.hair.map(([x,y])=>[(x-frame.cx)*scale,(frame.cy-y)*scale])};
  }
  const shadow=diameter/width>=60;
  let route=null;
  const options={face,group:false,groupStyle:'pose',portraitFraming:'framedHead',shoulderLocks:!selected?.groupMember,earJewelry:!selected?.groupMember,
    fitShadowMarks:marks=>{route=OasisRingPlanner.shadowPhoto(z,marks,g);},
    portraitStyle:shadow?'shadow':'line',portraitDiameterMm:diameter,portraitDiameterGrooves:diameter/width,
    portraitTrackingGrooves:Number.isFinite(g.trackingMarginMM) ? g.trackingMarginMM/width : undefined,
    onShadowFrame:selectedPixels};
  let res=await GuestPhoto.fromFile(file,options);
  let reason=res.shadowReason;
  if(!route && shadow && res.shadowMarks?.length){
    try {route=OasisRingPlanner.shadowPhoto(z,res.shadowMarks,g);}
    catch(error){reason=error.message;}
  }
  const marks=route ? res.shadowMarks : null;
  if(!route){
    // The ordinary Automatic form requests a close-up again when its shadow
    // plan fails; points from the first conversion contain the legacy bust.
    if(shadow && res.hasPortrait)res=await GuestPhoto.fromFile(file,{...options,portraitStyle:'line'});
    route=OasisRingPlanner.photo(z,res.points);
  }
  return {diameter,width,dock:z.transit[0],transit:z.transit,radius:g.radiusMM,faces:res.facesDetected,boxes:res.faceBoxes,selected:res.includedFaces[0],
    marks,points:marks ? null : res.points,events:route.marks || [],path:route.path,crop,
    reason:reason || (shadow?'No separate shadow portrait fits.':'This center is too small for shadow portraits.')};
}"""

PLAN = """marks => {
  const scene=JSON.parse(document.getElementById('scene').textContent),g=scene.live;
  const z=g.wideCenter || scene.zones.center;
  try {const p=OasisRingPlanner.shadowPhoto(z,marks,g);return {path:p.path,events:p.marks};}
  catch(e){return null;}
}"""

REPLAY = """route => {
  const g=JSON.parse(document.getElementById('scene').textContent).live;
  const bed=Float32Array.from(atob(g.bed),b=>b.charCodeAt(0)/170-1);
  const sim=new RingSand(g.size,g.groove,g.profile); sim.carve(bed,route);
  return sim.image(bed).split(',')[1];
}"""


def evaluate_geometry(page, operation, value):
    """Pass a complete route across the browser boundary as a single JSON value."""
    # Playwright otherwise serializes each coordinate as a separate tagged
    # object. These planner operations accept and return only JSON data.
    argument = json.dumps(value, separators=(',', ':'), allow_nan=False)
    answer = page.evaluate('encoded => JSON.stringify((' + operation + ')(JSON.parse(encoded)))', argument)
    return json.loads(answer)


def plan_marks(page, marks):
    return evaluate_geometry(page, PLAN, marks)


def portrait_files(page, path):
    return evaluate_geometry(page, "route => OasisRingPlanner.files(route,'portrait')", path)


def chromium(playwright, override):
    if override:
        return str(override)
    default = Path(playwright.chromium.executable_path)
    if default.is_file():
        return str(default)
    installed = shutil.which('chromium') or shutil.which('google-chrome')
    if installed:
        return installed
    cached = sorted((Path.home() / '.cache/ms-playwright').glob('chromium-*/chrome-linux*/chrome'))
    if cached:
        return str(cached[-1])
    raise ValueError('Choose an installed Chromium executable with --browser.')


def load_models(tile, model_python):
    if not model_python.is_file():
        raise ValueError('The local hair-model Python environment is unavailable.')
    try:
        result = subprocess.run(
            [str(model_python), str(TOOLS / 'wide_portrait_hair.py')],
            input=tile,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise ValueError('The local hair model could not run.') from err
    if result.returncode:
        raise ValueError('The local hair model or its installed model files are unavailable.')
    with np.load(io.BytesIO(result.stdout), allow_pickle=False) as data:
        return data['faces'], data['masks']


def samples(points, spacing):
    if len(points) < 2:
        return np.asarray(points)
    lengths = np.r_[0, np.linalg.norm(np.diff(points, axis=0), axis=1).cumsum()]
    if not lengths[-1]:
        return np.asarray(points[:1])
    positions = np.linspace(0, lengths[-1], math.ceil(lengths[-1] / spacing) + 1)
    return np.column_stack([np.interp(positions, lengths, axis) for axis in np.asarray(points).T])


def excursion_cloud(path, event, radius, spacing):
    """Sample the actual polar interpolation, including each signed turn."""
    segment = path[event['first'] : event['last'] + 1]
    dif = np.diff(segment, axis=0)
    steps = np.hypot(dif[:, 0] * (segment[:-1, 1] + segment[1:, 1]) / 2, dif[:, 1]) * radius
    distances = np.r_[0, steps.cumsum()]
    positions = np.linspace(0, distances[-1], math.ceil(distances[-1] / spacing) + 1)
    angle, rho = [np.interp(positions, distances, col) for col in segment.T]
    return np.column_stack([np.cos(angle) * rho, np.sin(angle) * rho]) * radius


def protected_features(source):
    """Retain every actual non-hair mark. A planner may have trimmed an end or simplified an iris."""
    width, diameter = source['width'], source['diameter']

    def pixels(v):
        return np.asarray(v) * [1, -1] * 600 / diameter + 300

    hair = (
        mask_for((600, 600), pixels(source['crop']['hair']))
        if source['crop']['hair']
        else np.zeros((600, 600), 'uint8')
    )
    result = []
    route = np.array(source['path'])
    for event in sorted(source['events'], key=lambda e: e['source']):
        mark = source['marks'][event['source']]
        kind = mark['kind']
        if kind in ('head', 'hairline'):
            continue
        points = np.array(mark['points'])
        if kind == 'shade' and not mark.get('facialHair'):
            line = samples(pixels(points), 2).round().astype(int)
            x, y = np.clip(line, 0, 599).T
            if (hair[y, x] > 0).all():
                continue
        tree = cKDTree(excursion_cloud(route, event, source['radius'], width * 0.055))
        mark = {k: v for k, v in mark.items() if k in FIELDS and k not in ('lids', 'rim', 'opening', 'noseBase')}
        # Lock the engraved facial outline. A new hairstyle must
        # preserve the fallback chosen in the original movement file.
        original = source['marks'][event['source']]
        fallback = original.get('lids') or original.get('rim') or original.get('opening') or original.get('noseBase')
        if fallback and tree.query(points)[0].max() > width * 0.11:
            points = np.asarray(fallback)
        curve = np.vstack([points, points[0]]) if mark['closed'] else points
        targets = samples(curve, width * 0.075)
        targets = targets[tree.query(targets)[0] < width * 0.105]
        if len(targets) < 2:
            raise ValueError('Could not establish the earlier facial stroke locations.')
        if kind == 'shade' and not mark['closed']:
            found = np.flatnonzero(tree.query(points)[0] < width * 0.105)
            if len(found) >= 2:
                points = points[found[0] : found[-1] + 1]
        mark['points'] = points.tolist()
        result.append((mark, targets))
    return result


def offsets(head, groove):
    vertices = np.asarray(head['points'])
    center = minimize(
        lambda p: np.linalg.norm(vertices - p, axis=1).max(),
        vertices.mean(axis=0),
        method='Nelder-Mead',
        options={'maxiter': 220},
    ).x
    all_offsets = [np.zeros(2), *(-center * t for t in (0.33, 0.67, 1)), [-center[0], 0], [0, -center[1]]]
    all_offsets += [
        [dx * groove, dy * groove]
        for dx, dy in [(0.7, 0), (-0.7, 0), (0, 0.7), (0, -0.7), (1.4, 0), (-1.4, 0)]
    ]
    unique = {tuple(np.round(point, 5)) for point in all_offsets}
    return sorted(unique, key=lambda point: (math.hypot(*point), point))


def aligned_photo(source, model_python):
    crop = source['crop']
    if not crop:
        raise ValueError('The selected photo crop could not be matched to the drawing.')
    tile = base64.b64decode(crop['png'], validate=True)
    img = cv2.imdecode(np.frombuffer(tile, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or img.shape != (600, 600):
        raise ValueError('The face crop could not be decoded.')
    meshes, masks = load_models(tile, model_python)
    if not len(meshes):
        raise ValueError('The local hair model found no face in this crop.')
    return img, meshes, masks


def hair_version(page, source, photo):
    img, meshes, masks = photo
    protected = protected_features(source)
    facial = [mark for mark, _ in protected]
    head = next(m for m in source['marks'] if m['kind'] == 'head')
    hair = measured_hair(
        img, masks, meshes, [head, *facial], source['crop']['hair'], source['diameter'], source['width']
    )
    if source['crop'].get('earTrace'):
        head_points = page.evaluate(
            '({head,ear,width})=>GuestShadow.joinPiercedEar(head,ear,width)',
            {'head': hair[0]['points'], 'ear': source['crop']['earTrace'], 'width': source['width']},
        )
        if head_points is None:
            raise ValueError('This hairstyle could not preserve the photographed ear.')
        hair[0] = {**hair[0], 'points': head_points}
    original = [hair[0], *facial, *hair[1:]]
    width = source['width']
    best = None
    for offset in offsets(hair[0], width):
        marks = [{**m, 'points': (np.asarray(m['points']) + offset).tolist()} for m in original]
        answer = plan_marks(page, marks)
        if answer is None:
            continue
        events = {e['source']: e for e in answer['events']}
        if not all(i in events for i in range(1, len(protected) + 1)):
            continue
        texture = sum(i > len(protected) for i in events)
        if texture < 2 or 0 not in events:
            continue
        route = np.asarray(answer['path'])
        preserved = True
        for i, (_, target) in enumerate(protected, 1):
            trace = excursion_cloud(route, events[i], source['radius'], width * 0.055)
            if cKDTree(trace).query(target + offset)[0].max() > width * 0.12:
                preserved = False
                break
        if not preserved:
            continue
        # The nearest fully successful placement wins ties on hair detail.
        if best is None or texture > best[0]:
            best = (texture, marks, answer, offset)
        if texture == len(hair) - 1:
            break
    if best is None:
        raise ValueError('The measured hair would crowd an existing facial line.')
    _, marks, answer, offset = best
    return marks, answer, len(protected), list(offset)


def downloaded_route(page, plan, dock):
    parts = portrait_files(page, plan['path'])
    arrays = [np.loadtxt(io.StringIO(part['text']), dtype=float, ndmin=2) for part in parts]
    route = joined(arrays, dock, dock, 'photographed feature')
    if not same_track(route, np.asarray(plan['path'])):
        raise ValueError('The photo preview did not match its exported motion.')
    return route


def same_excursion(first, second):
    if first.shape != second.shape or not np.array_equal(first[:, 1], second[:, 1]):
        return False
    # Signed headings can shift by a complete revolution. After rounding to
    # five decimals the same physical angle can then differ by one last digit.
    difference = second[:, 0] - first[:, 0]
    turns = round(difference[0] / math.tau)
    if not turns:
        return np.array_equal(first[:, 0], second[:, 0])
    return np.max(np.abs(difference - turns * math.tau)) <= .0000101


def crosses_opening(points, loop, tolerance):
    """Check how far the sampled ball center enters a photographed opening."""
    near = points[np.all((points >= loop.min(axis=0)) & (points <= loop.max(axis=0)), axis=1)]
    polygon = loop.astype(np.float32)
    return any(cv2.pointPolygonTest(polygon, (float(x), float(y)), True) > tolerance for x, y in near)


def verify_feature(page, source, before, original, proposed, index, mark, merged=(), adjusted=(), revised=None,
                   *, eye=None):
    kind = mark['kind']
    # Check each complete, rounded polar excursion, including its link to
    # the clearing turn. Comparing source points would miss actual trimming,
    # a changed entry angle, or a simplified iris in the finished download.
    previous = {e['source']: e for e in before['events']}
    updated = {e['source']: e for e in proposed['events']}
    if previous.keys() - set(merged) != updated.keys() or index not in updated:
        raise ValueError(f'The photographed {kind} would crowd another facial line.')
    if revised is None:
        revised = downloaded_route(page, proposed, source['dock'])
    width, radius = source['width'], source['radius']
    spacing = width * 0.045
    feature = excursion_cloud(revised, updated[index], radius, spacing)
    vertices = np.asarray(mark['points'])
    if mark['closed']:
        vertices = np.vstack((vertices, vertices[0]))
    goal = samples(vertices, spacing)
    if cKDTree(feature).query(goal)[0].max() > width * 0.09:
        raise ValueError(f'The full photographed {kind} did not fit the drawing.')
    protected = []
    for key, old in previous.items():
        if key == index or key in merged:
            continue
        new = updated[key]
        a = original[old['first'] : old['last'] + 1]
        b = revised[new['first'] : new['last'] + 1]
        if key not in adjusted and not same_excursion(a, b):
            raise ValueError(f'The photographed {kind} would change an existing stroke or its approach.')
        protected.append(excursion_cloud(revised, new, radius, spacing))
    # The independent ball travel must clear the *actual connectors* to eyes,
    # cheeks, lips, hair and every other surviving physical excursion.
    others = np.vstack(protected)
    clearance = float(cKDTree(others).query(feature)[0].min())
    if clearance < 1.23 * width + spacing:
        raise ValueError(f'The approach to the photographed {kind} comes too close to another line.')
    if eye is not None:
        verify_eye_opening(eye, updated[index], feature, others, revised, radius, width)
    if kind == 'smile' and mark['closed']:
        # Reject an access stroke running through the opening, even a line
        # wholly enclosed by the lips. Include subsequent clearing passes.
        # A rounded polar segment may bow just inside its own lip centerline.
        end = {'first': updated[index]['last'], 'last': len(revised) - 1}
        remaining = excursion_cloud(revised, end, radius, spacing)
        if (crosses_opening(feature, vertices, .06 * width) or crosses_opening(others, vertices, 0)
                or crosses_opening(remaining, vertices, 0)):
            raise ValueError('A movement would cut through the photographed smile.')


def separable_feature(mark, source, baseline, original, index, merged=()):
    """Omit only an end of the photographed contour if an existing groove occupies that sand."""
    width, radius = source['width'], source['radius']
    other = np.vstack(
        [
            excursion_cloud(original, e, radius, width * 0.045)
            for e in baseline['events']
            if e['source'] != index and e['source'] not in merged
        ]
    )
    vertices = np.asarray(mark['points'])
    cumulative = np.r_[0, np.linalg.norm(np.diff(vertices, axis=0), axis=1).cumsum()]
    line = samples(vertices, width * 0.045)
    distances = np.linspace(0, cumulative[-1], len(line))
    apart = cKDTree(other).query(line)[0]
    previous = None
    for clearance in (1.42, 1.65, 1.95):
        free = apart > clearance * width
        stops = np.flatnonzero(np.diff(np.r_[False, free, False])).reshape(-1, 2)
        for start, end in stops:
            # Keep the middle and most of the observed span. A tiny fragment
            # can fit comfortably while losing the shape of the feature.
            if start == 0 and end == len(line):
                continue
            if start > len(line) * 0.40 or end < len(line) * 0.60 or end - start < 0.60 * len(line):
                continue
            portion = line[start:end]
            # Span along the actual left/right direction, including head tilt.
            axis = vertices[-1] - vertices[0]
            axis /= max(np.linalg.norm(axis), 1e-9)
            span = np.ptp(vertices @ axis)
            if np.ptp(portion @ axis) < max(0.67 * span, 4.5 * width):
                continue
            if (start, end) == previous:
                continue
            previous = (start, end)
            lo, hi = distances[[start, end - 1]]
            inside = vertices[(cumulative > lo) & (cumulative < hi)]
            clipped = np.vstack((portion[0], inside, portion[-1]))
            yield {**mark, 'points': clipped.tolist()}


def nose_version(page, source, marks, baseline, photo, offset):
    from wide_portrait_nose import measured_nose

    indices = [i for i, m in enumerate(marks) if m['kind'] == 'nose']
    if len(indices) != 1 or not any(e['source'] == indices[0] for e in baseline['events']):
        raise ValueError('This drawing has no separate nose to trace.')
    img, meshes, _ = photo
    nose = measured_nose(img, meshes, marks, source['diameter'], source['width'], offset or (0.0, 0.0))
    if nose is None:
        raise ValueError('The photo does not show a clear enough edge around the nose.')
    index = indices[0]
    original = downloaded_route(page, baseline, source['dock'])
    problem = 'The photographed nose does not fit the existing portrait.'
    for candidate in chain((nose,), separable_feature(nose, source, baseline, original, index)):
        revised = list(marks)
        revised[index] = candidate
        plan = plan_marks(page, revised)
        if plan:
            try:
                verify_feature(page, source, baseline, original, plan, index, candidate)
            except ValueError as error:
                problem = str(error)
            else:
                return revised, plan
    raise ValueError(problem)


def overlapping_brow_shadows(candidate, marks, indices, width):
    """Only a plain photo shadow lying along the same brow can merge into its groove."""
    brow = cKDTree(samples(np.asarray(candidate['points']), .045 * width))
    overlap = set()
    for index in indices:
        mark = marks[index]
        if mark['kind'] != 'shade' or mark['closed'] or mark.get('facialHair'):
            continue
        gap = brow.query(samples(np.asarray(mark['points']), .045 * width))[0]
        if np.quantile(gap, .9) <= .60 * width and gap.max() <= width:
            overlap.add(index)
    return overlap


def brow_version(page, source, marks, baseline, photo, offset):
    from wide_portrait_brows import photographed_brows

    count = 0
    for index, mark in photographed_brows(photo[0], marks, source['diameter'], source['width'], offset or (0, 0)):
        previous = {e['source'] for e in baseline['events']}
        if index not in previous:
            continue
        original = downloaded_route(page, baseline, source['dock'])
        coincident = overlapping_brow_shadows(mark, marks, previous, source['width'])
        clipped = separable_feature(mark, source, baseline, original, index, coincident)
        for candidate in chain((mark,), clipped):
            revised = list(marks)
            revised[index] = candidate
            plan = plan_marks(page, revised)
            if plan is None:
                continue
            missing = previous - {e['source'] for e in plan['events']}
            # A generic shadow sometimes traces the eyebrow itself. Allow a
            # single duplicate to merge only inside the new groove's footprint.
            if len(missing) > 1 or (missing and missing != overlapping_brow_shadows(
                candidate, marks, missing, source['width']
            )):
                continue
            try:
                verify_feature(page, source, baseline, original, plan, index, candidate, missing)
            except ValueError:
                continue
            marks, baseline = revised, plan
            count += 1
            break
    return marks, baseline, count


def plain_shade(mark):
    return mark['kind'] == 'shade' and not mark['closed'] and not mark.get('facialHair')


def shadows_following_brow(brow, marks, events, route, radius, width):
    """Find actual shade strokes running along the photographed hair for several grooves."""
    step = .06 * width
    strand = samples(np.asarray(brow['points']), step)
    tree = cKDTree(strand)

    def tangents(points):
        directions = np.gradient(points, axis=0)
        return directions / np.maximum(np.linalg.norm(directions, axis=1, keepdims=True), 1e-8)

    along = tangents(strand)
    matching = set()
    for index, event in events.items():
        if not plain_shade(marks[index]):
            continue
        path = samples(np.asarray(marks[index]['points']), step)
        if len(path) < 2:
            continue
        gap, nearest = tree.query(path)
        parallel = np.abs(np.sum(tangents(path) * along[nearest], axis=1)) >= .82
        overlap = (gap <= .70 * width) & parallel
        if not np.any(overlap):
            continue
        actual = cKDTree(excursion_cloud(route, event, radius, step))
        overlap &= actual.query(path)[0] < .11 * width
        runs = np.flatnonzero(np.diff(np.r_[False, overlap, False])).reshape(-1, 2)
        if any((b - a - 1) * step >= 2.6 * width for a, b in runs):
            matching.add(index)
    return matching


def separate_brow_shadows(page, source, marks, baseline, photo, offset):
    from wide_portrait_brows import brow_bands

    count = 0
    for index, candidate in brow_bands(photo[0], photo[1], marks, source['diameter'], source['width'], offset or (0, 0)):
        events = {event['source']: event for event in baseline['events']}
        if index not in events:
            continue
        route = downloaded_route(page, baseline, source['dock'])
        duplicates = shadows_following_brow(candidate, marks, events, route, source['radius'], source['width'])
        if not duplicates:
            continue
        try:
            marks, baseline = fit_photo_features(page, source, marks, baseline, route, {index: candidate},
                                                 adjustable_shades=duplicates)
        except ValueError:
            continue
        count += 1
    return marks, baseline, count


def cut_nearby_shadow(mark, keep, width):
    """Keep a single continuous crease when its end runs into a photographed feature."""
    vertices = np.asarray(mark['points'])
    distance = np.r_[0, np.linalg.norm(np.diff(vertices, axis=0), axis=1).cumsum()]
    arc = np.linspace(0, distance[-1], len(keep))
    runs = np.flatnonzero(np.diff(np.r_[False, keep, False])).reshape(-1, 2)
    pieces = [(arc[a], arc[b-1]) for a, b in runs if arc[b-1] - arc[a] >= 2.4 * width]
    if len(pieces) != 1:
        return mark
    start, end = pieces[0]
    endpoints = np.column_stack([np.interp([start, end], distance, axis) for axis in vertices.T])
    line = np.vstack((endpoints[0], vertices[(distance > start) & (distance < end)], endpoints[1]))
    return {**mark, 'points': line.tolist()}


def verify_eye_opening(eye, event, actual, others, route, radius, width):
    """Protect the photographed whites on the finished, rounded polar path."""
    spacing = width * .045
    aperture = np.asarray(eye['aperture'])
    intended = np.asarray(eye['mark']['points'])
    if eye['mark']['closed']:
        intended = np.vstack((intended, intended[0]))
    iris = samples(np.asarray(eye['iris']), spacing)
    if cKDTree(actual).query(iris)[0].max() > .09 * width:
        raise ValueError('The ball could not follow the photographed iris edge.')
    # The path may retrace the lids or the iris. A shortcut through the white
    # of the eye would survive in the sand even if the intended lines also fit.
    away = cKDTree(samples(intended, spacing)).query(actual)[0] > .1 * width
    if crosses_opening(actual[away], aperture, .06 * width) or crosses_opening(others, aperture, 0):
        raise ValueError('The approach would cut across the photographed eye.')
    later = {'first': event['last'], 'last': len(route) - 1}
    if crosses_opening(excursion_cloud(route, later, radius, spacing), aperture, .06 * width):
        raise ValueError('A later movement would cut across the photographed eye.')


def fit_photo_features(page, source, marks, baseline, original, replacements, *, eyes=(), adjustable_shades=None):
    """Fit the new features while preserving earlier shading away from their contours."""
    width, radius = source['width'], source['radius']
    spacing = width * .045
    lines = []
    for mark in replacements.values():
        points = np.asarray(mark['points'])
        lines.append(samples(np.vstack((points, points[0])) if mark['closed'] else points, spacing))
    contours = cKDTree(np.vstack(lines))
    eye_by_index = {eye['index']: eye for eye in eyes}
    previous = {e['source']: e for e in baseline['events']}
    # Cache exactly which portion of each affected photograph line the ball
    # previously engraved. Planners may shorten either end for their entrance.
    shading = {}
    problem = ('The photographed eyes need more space.' if eyes else
               'The photographed smile is too close to another part of the portrait.')
    for clearance in (0, 1.55, 1.88, 2.22):
        revised_marks = list(marks)
        for index, mark in replacements.items():
            revised_marks[index] = mark
        if clearance:
            if not shading:
                break
            for key, (points, was_drawn, gap) in shading.items():
                keep = was_drawn & (gap > clearance * width)
                if not keep.all():
                    revised_marks[key] = cut_nearby_shadow(marks[key], keep, width)
        plan = plan_marks(page, revised_marks)
        if plan is None:
            continue
        updated = {e['source']: e for e in plan['events']}
        if updated.keys() - previous.keys() or replacements.keys() - updated.keys():
            continue
        route = downloaded_route(page, plan, source['dock'])
        adjusted, removed = set(), previous.keys() - updated.keys()
        distant_change = False
        for key, old in previous.items():
            if key in replacements:
                continue
            new = updated.get(key)
            if new and same_excursion(original[old['first']:old['last']+1], route[new['first']:new['last']+1]):
                continue
            if not plain_shade(marks[key]):
                raise ValueError('The photographed eyes would move another facial feature.' if eyes else
                                 'The photographed smile would move a different facial feature.')
            if adjustable_shades is not None and key not in adjustable_shades:
                distant_change = True
                continue
            if key not in shading:
                pts = samples(np.asarray(marks[key]['points']), spacing)
                old_ink = cKDTree(excursion_cloud(original, old, radius, spacing))
                shading[key] = pts, old_ink.query(pts)[0] < .11 * width, contours.query(pts)[0]
            pts, was_drawn, gap = shading[key]
            if new:
                new_ink = cKDTree(excursion_cloud(route, new, radius, spacing))
                drawn = new_ink.query(pts)[0] < .11 * width
                adjusted.add(key)
            else:
                drawn = np.zeros(len(pts), dtype=bool)
            # Two competing grooves plus their shoulders need this space.
            # Distant portions of the earlier crease must survive exactly
            # enough to still fall on its intended centerline, including
            # earlier trimmed ends. A nearby access can take its new approach.
            if not np.any(was_drawn & (gap < 2.25 * width)) or np.any((was_drawn != drawn) & (gap > 2.25 * width)):
                distant_change = True
        if distant_change:
            problem = ('The photographed eyes would shorten a distant shading line.' if eyes else
                       'The photographed smile would shorten a distant cheek or chin line.')
            continue
        try:
            for index, mark in replacements.items():
                verify_feature(page, source, baseline, original, plan, index, mark, removed,
                               adjusted | replacements.keys(), route, eye=eye_by_index.get(index))
        except ValueError as error:
            problem = str(error)
            continue
        return revised_marks, plan
    raise ValueError(problem)


def smile_version(page, source, marks, baseline, photo, offset):
    from wide_portrait_smile import measured_smile

    indices = [i for i, mark in enumerate(marks) if mark['kind'] == 'smile']
    if len(indices) != 1:
        raise ValueError('This portrait has no separate mouth opening to trace.')
    gray, meshes, _ = photo
    dimensions = source['diameter'], source['width'], offset or (0, 0)
    smile = measured_smile(gray, meshes, marks, *dimensions)
    corners_only = smile is None
    if corners_only:
        smile = measured_smile(gray, meshes, marks, *dimensions, corners_only=True)
        if smile is None:
            raise ValueError('This photo has no clearer open smile at this size.')
    index = indices[0]
    original = downloaded_route(page, baseline, source['dock'])
    try:
        fitted, plan = fit_photo_features(page, source, marks, baseline, original, {index: smile})
        return fitted, plan, None
    except ValueError:
        if corners_only:
            raise
        # The monochrome trace can hug a row of teeth or a bright lower lip.
        # Only try a different opening if the original color crop shows both
        # an exposed gum band and pale teeth. Apply the same sand checks.
        tile = base64.b64decode(source['crop']['png'], validate=True)
        color = cv2.imdecode(np.frombuffer(tile, np.uint8), cv2.IMREAD_COLOR)
        alternate = None if color is None else measured_smile(gray, meshes, marks, *dimensions, color=color)
        if alternate is None:
            raise
    fitted, plan = fit_photo_features(page, source, marks, baseline, original, {index: alternate})
    return fitted, plan, marks[index]


def fit_lens_eyes(page, source, marks, baseline, original, pair):
    """Replace generic lines inside the photographed eyes. Keep both rims and the face exact."""
    width, radius = source['width'], source['radius']
    contours = [(np.asarray(eye['rim'], 'float32'), np.asarray(eye['aperture'], 'float32')) for eye in pair]

    def inside_lens(mark):
        if not plain_shade(mark):
            return False
        line = [tuple(point) for point in samples(np.asarray(mark['points']), .15 * width)]
        return any(all(cv2.pointPolygonTest(rim, point, True) > .6 * width
                       and cv2.pointPolygonTest(aperture, point, True) > -3 * width for point in line)
                   for rim, aperture in contours)

    retained = [i for i, mark in enumerate(marks) if not inside_lens(mark)]
    revised_marks = [marks[i] for i in retained] + [dict(eye['mark'], measuredLensEye=True) for eye in pair]
    plan = plan_marks(page, revised_marks)
    if plan is None:
        raise ValueError('The photographed eyes do not fit inside both lenses.')
    route = downloaded_route(page, plan, source['dock'])
    old = {event['source']: event for event in baseline['events']}
    new = {event['source']: event for event in plan['events']}
    for j, i in enumerate(retained):
        if (i in old) != (j in new):
            raise ValueError('Tracing the eyes would change a line outside the lenses.')
        if i in old:
            a, b = old[i], new[j]
            if not same_excursion(original[a['first']:a['last']+1], route[b['first']:b['last']+1]):
                raise ValueError('Tracing the eyes would change a line outside the lenses.')
    if not all(index in new for index in range(len(retained), len(revised_marks))):
        raise ValueError('Both photographed eyes need a separate entrance.')
    spacing = .045 * width
    clouds = {i: excursion_cloud(route, event, radius, spacing) for i, event in new.items()}
    for i, eye in enumerate(pair, len(retained)):
        others = np.vstack([cloud for k, cloud in clouds.items() if k != i])
        intended = samples(np.asarray(eye['mark']['points']), spacing)
        if (cKDTree(clouds[i]).query(intended)[0].max() > .09 * width or
                cKDTree(others).query(clouds[i])[0].min() < 1.23 * width + spacing):
            raise ValueError('The full photographed eyelid and iris cannot clear the frame.')
        rim = np.asarray(eye['rim'], 'float32')
        if any(cv2.pointPolygonTest(rim, tuple(p), True) <= .6 * width for p in clouds[i]):
            raise ValueError('The entrance to the photographed eye would cross the frame.')
        verify_eye_opening(eye, new[i], clouds[i], others, route, radius, width)
    return revised_marks, plan


def eye_version(page, source, marks, baseline, photo, offset):
    from wide_portrait_eyes import measured_eyes, measured_lens_eyes

    gray, meshes, _ = photo
    if any(m['kind'] == 'glasses' for m in marks):
        pair = measured_lens_eyes(gray, meshes, marks, source['diameter'], source['width'], offset or (0, 0))
        if pair is None:
            raise ValueError('The photo does not resolve two clear eyes through the glasses at this size.')
        original = downloaded_route(page, baseline, source['dock'])
        return fit_lens_eyes(page, source, marks, baseline, original, pair)
    candidates = measured_eyes(gray, meshes, marks, source['diameter'], source['width'], offset or (0, 0))
    if not candidates:
        raise ValueError('The photo does not resolve clearer eyes at this drawing size.')
    original = downloaded_route(page, baseline, source['dock'])
    problem = 'There is too little room for both eyes.'
    for pair in candidates:
        replacements = {eye['index']: eye['mark'] for eye in pair}
        try:
            return fit_photo_features(page, source, marks, baseline, original, replacements, eyes=pair)
        except ValueError as error:
            problem = str(error)
    raise ValueError(problem)


def save_portrait(page, source, marks, plan, dst):
    """Write the portable drawing, replay its signed downloads and verify the center and transit."""
    route = plan['path']
    files = portrait_files(page, route)
    if not files or any(part['name'] != f'portrait-{i}.thr' for i, part in enumerate(files, 1)):
        raise ValueError('The garden returned an invalid set of portrait file names.')
    prepared = {
        'format': 'oasis-prepared-portrait-v1',
        'diameterMm': source['diameter'],
        'grooveMm': source['width'],
    }
    if marks is None:
        prepared['points'] = source['points']
        if source.get('includesCenterRake'):
            prepared['includesCenterRake'] = True
    else:
        prepared['marks'] = [{k: v for k, v in m.items() if k in FIELDS} for m in marks]
    portrait_file = dst / 'portrait.oasisportrait'
    portrait_file.write_text(json.dumps(prepared, separators=(',', ':'), allow_nan=False) + '\n')
    # Read back the portable document with the public planner for that shape.
    # A guest opening it must obtain exactly the same motion bytes.
    restored = page.evaluate(
        """drawing => {
      const scene=JSON.parse(document.getElementById('scene').textContent),g=scene.live;
      const z=g.wideCenter || scene.zones.center;
      const plan=drawing.marks ? OasisRingPlanner.shadowPhoto(z,drawing.marks,g) :
        drawing.includesCenterRake ? OasisRingPlanner.preparedPhoto(z,drawing.points,g,true) :
        OasisRingPlanner.photo(z,drawing.points);
      return OasisRingPlanner.files(plan.path,'portrait');
    }""",
        json.loads(portrait_file.read_text()),
    )
    if restored != files:
        raise ValueError('The prepared drawing did not reproduce its planned route.')
    for part in files:
        (dst / part['name']).write_text(part['text'])
    verified = joined([read_path(dst, f['name']) for f in files], source['dock'], source['dock'], 'portrait')
    if not same_track(verified, np.array(route)):
        raise ValueError('The motion files do not reproduce the planned route.')
    transit = np.asarray(source['transit'])
    outer = len(transit)
    center = verified[outer - 1 : len(verified) - outer + 1, 1]
    if (
        not same_track(verified[:outer], transit)
        or not same_track(verified[-outer:], transit[::-1])
        or not len(center)
        or center.max() > transit[-1, 1] + 0.000025
    ):
        raise ValueError('The exported motion would leave the center or its existing approach.')
    # Carve the independently read files, including their rounded coordinates.
    raster = base64.b64decode(evaluate_geometry(page, REPLAY, verified.tolist()), validate=True)
    if not raster.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('The garden did not produce a PNG sand preview.')
    (dst / 'preview.png').write_bytes(raster)
    return {
        'rows': len(verified),
        'files': [f['name'] for f in files],
        'motionSHA256': motion_files_hash(files),
    }


def open_portrait_photo(page, args, upload=None):
    # No network requests, including requests from a third-party source in an
    # old local editor. Embedded face models and garden dimensions stay local.
    address = args.garden.resolve().as_uri()
    if args.layout:
        address += '?layout=' + args.layout
    page.goto(address, wait_until='load')
    if (
        args.layout
        and page.evaluate("JSON.parse(document.getElementById('scene').textContent).layout") != args.layout
    ):
        raise ValueError('The requested garden layout is unavailable.')
    page.evaluate("""()=>{for(const id of ['portraitModels','portraitTools']){
      const source=document.getElementById(id);
      if(!source?.textContent.trim())throw Error('Choose a locally built garden with guest photo support.');
      const script=document.createElement('script');script.textContent=source.textContent;
      document.head.append(script);script.remove();
    }}""")
    # Pick a private input reserved for this job, independent of which guest
    # control is displayed in this version of the editor.
    page.evaluate("""()=>{const input=document.createElement('input');input.type='file';
      input.id='hostPortraitInput';input.hidden=true;document.body.prepend(input);}""")
    page.locator('#hostPortraitInput').set_input_files(upload if upload is not None else args.photo.resolve())


def fix_nose_for_host(page, source, group):
    """Keep the engraved solo nose when later operations move or remove other marks."""
    marks = list(source['marks'] or [])
    paired = next((i for i, mark in enumerate(marks) if 'noseBase' in mark), None)
    if paired is None:
        return
    first = dict(marks[paired])
    base = first.pop('noseBase')
    both = all(any(e['source'] == i for e in source['events']) for i in (paired, paired + 1))
    if group or not both:
        # A group fits several reduced faces on these same grooves. Use the
        # former single nose there, including its previously verified routes.
        marks[paired:paired + 2] = [dict(first, points=base)]
        plan = plan_marks(page, marks)
        if plan is None:
            raise ValueError('The smaller nose could not be engraved in this portrait.')
        source.update(plan)
    else:
        marks[paired] = first
    source['marks'] = marks


def trace_selected_face(page, args, selected, *, group=False):
    # The group fitter needs compact heads at its smaller physical scale.
    choice = {'groupMember': selected} if group else selected
    source = page.evaluate(SOURCE, choice)
    missing_frame = source['crop'] is None or (
        getattr(args, 'full_hair', False) and not source['crop'].get('area'))
    if source['marks'] and missing_frame:
        # Older built gardens don't report their aligned crop. Preserve their
        # original guest geometry, including the fallback route. Borrow only
        # the pixel tile when the installed converter confirms the exact frame.
        for name in ('ring-shadow.js', 'guest-photo.js'):
            page.add_script_tag(path=str(WEB / name))
        current = page.evaluate(SOURCE, choice)

        def silhouette(analysis):
            return next((m['points'] for m in analysis['marks'] or [] if m['kind'] == 'head'), None)

        if silhouette(current) == silhouette(source):
            source['crop'] = current['crop']
    fix_nose_for_host(page, source, group)
    marks = source['marks']
    plan = {'path': source['path'], 'events': source['events']}
    method = 'ordinary-outline' if marks is None else 'ordinary-shadows'
    reason = source['reason'] if marks is None else ''
    protected, offset, photo = None, None, None
    if marks:
        try:
            photo = aligned_photo(source, args.model_python)
            marks, plan, protected, offset = hair_version(page, source, photo)
            method = 'measured-hair'
        except (ValueError, cv2.error) as err:
            reason = str(err)
            source['hairCropClipped'] = isinstance(err, ClippedHair)
    nose_result = None
    if getattr(args, 'trace_nose', False):
        nose_result = {'applied': False, 'note': 'This drawing has no confirmed, separate photo nose.'}
        if marks and photo is not None:
            try:
                marks, plan = nose_version(page, source, marks, plan, photo, offset)
                nose_result = {'applied': True, 'note': 'The drawing follows the photographed nose.'}
            except (ValueError, cv2.error) as err:
                nose_result['note'] = str(err)
    brows_result = None
    if getattr(args, 'trace_brows', False):
        count = 0
        if marks and photo is not None:
            marks, plan, count = brow_version(page, source, marks, plan, photo, offset)
        brows_result = {'applied': count > 0, 'count': count}
    smile_result, previous_smile = None, None
    if getattr(args, 'trace_smile', False):
        smile_result = {'applied': False, 'note': 'This drawing has no confirmed, separate photo smile.'}
        if marks and photo is not None:
            try:
                marks, plan, previous_smile = smile_version(page, source, marks, plan, photo, offset)
                smile_result = {'applied': True, 'note': 'The drawing follows the photographed opening between the lips.'}
            except (ValueError, cv2.error) as err:
                smile_result['note'] = str(err)
    eyes_result = None
    if getattr(args, 'trace_eyes', False):
        eyes_result = {'applied': False, 'note': 'This drawing has no confirmed pair of photographed eyes.'}
        if marks and photo is not None:
            try:
                marks, plan = eye_version(page, source, marks, plan, photo, offset)
                through_glasses = any(m['kind'] == 'glasses' for m in marks)
                note = ('Both upper eyelids and the dark of the eyes follow the photograph inside the glasses.'
                        if through_glasses else 'Both eyes follow the gaze in the photograph.')
                eyes_result = {'applied': True, 'note': note}
            except (ValueError, cv2.error) as err:
                eyes_result['note'] = str(err)
    manifest = {
        'method': method,
        'note': reason,
        'diameterMm': source['diameter'],
        'grooveMm': source['width'],
        'facesDetected': source['faces'],
        'protectedMarks': protected,
        'translationMm': offset,
    }
    if eyes_result is not None:
        manifest['eyes'] = eyes_result
    if smile_result is not None:
        manifest['smile'] = smile_result
    if brows_result is not None:
        manifest['brows'] = brows_result
    if nose_result is not None:
        manifest['nose'] = nose_result
    return source, marks, plan, photo, previous_smile, manifest


def finish_brows(page, source, marks, plan, photo, manifest):
    brows = manifest.get('brows')
    if brows is not None and not brows['applied'] and marks and photo is not None:
        marks, plan, count = separate_brow_shadows(page, source, marks, plan, photo, manifest['translationMm'])
        manifest['brows'] = {'applied': count > 0, 'count': count}
    return marks, plan


def prepare(page, args, dst, *, upload=None):
    open_portrait_photo(page, args, upload)
    selected = args.face_box or (None if args.face is None else args.face - 1)
    source, marks, plan, photo, previous_smile, manifest = trace_selected_face(page, args, selected)
    offset = manifest['translationMm']
    earlier_marks, earlier_plan = marks, plan
    if getattr(args, 'full_hair', False):
        long_hair = {'applied': False, 'note': 'This photo has no separate long locks outside the close-up.'}
        if marks and photo is not None:
            from wide_portrait_long_hair import wider_hair

            alternate = dst / 'full-hair'
            try:
                expanded, long_plan, count = wider_hair(
                    page, source, marks, plan, offset, args.model_python, previous_smile=previous_smile)
                alternate.mkdir()
                saved = save_portrait(page, source, expanded, long_plan, alternate)
            except (ValueError, cv2.error) as err:
                if alternate.exists():
                    shutil.rmtree(alternate)
                long_hair['note'] = str(err)
            else:
                (alternate / 'result.json').write_text(json.dumps(saved, indent=2) + '\n')
                long_hair = {'applied': True, 'strokes': count, 'note': 'The wider portrait includes the photographed hair.'}
        manifest['longHair'] = long_hair
    # At the close-up scale a generic shadow may trace the same brow twice.
    # Compare against the completed face, including its eyes and smile. The
    # separately fitted wider and woodcut drawings keep their own geometry.
    marks, plan = finish_brows(page, source, marks, plan, photo, manifest)
    from wide_portrait_moustache import fit_wings, photographed_wings

    wings = photographed_wings(source) if getattr(args, 'trace_smile', False) else None
    for requested, key, dirname in (
        (getattr(args, 'hair_woodcut', False), 'woodcut', 'hair-woodcut'),
        (getattr(args, 'flowing_hair', False), 'flowingHair', 'flowing-hair'),
    ):
        if not requested:
            continue
        result = {'applied': False, 'note': 'The hair is too small or indistinct for separate grooves.'}
        if marks and photo is not None:
            from wide_portrait_woodcut import guest_woodcut, woodcut_version

            alternate = dst / dirname
            try:
                if key == 'flowingHair':
                    hatched, hair_plan, count = woodcut_version(
                        page, source, marks, plan, photo, offset, follow_grain=True)
                    note = 'The strokes follow the direction of the photographed hair.'
                else:
                    hatched, hair_plan, count, note = guest_woodcut(
                        page, source, photo, offset, (earlier_marks, earlier_plan), (marks, plan))
                alternate.mkdir()
                hatched, hair_plan = fit_wings(page, source, hatched, hair_plan, wings, offset)
                saved = save_portrait(page, source, hatched, hair_plan, alternate)
            except (ValueError, cv2.error) as err:
                if alternate.exists():
                    shutil.rmtree(alternate)
                result['note'] = str(err)
            else:
                (alternate / 'result.json').write_text(json.dumps(saved, indent=2) + '\n')
                result = {'applied': True, 'strokes': count, 'note': note}
        manifest[key] = result
    before_wings = marks
    marks, plan = fit_wings(page, source, marks, plan, wings, offset)
    if marks is not before_wings:
        manifest['smile']['moustache'] = True
        if not manifest['smile']['applied']:
            manifest['smile']['note'] = 'The photographed moustache fits around the existing smile.'
    if getattr(args, 'rake_print', False):
        from wide_portrait_rake import save_rake_print

        alternate = dst / 'rake-print'
        alternate.mkdir()
        try:
            manifest['rakePrint'] = save_rake_print(page, source, marks, offset, alternate)
        except (ValueError, cv2.error) as err:
            shutil.rmtree(alternate)
            manifest['rakePrint'] = {'applied': False, 'note': str(err)}
    if getattr(args, 'cheek_print', False):
        from wide_portrait_cheeks import save_cheek_print

        alternate = dst / 'cheek-print'
        alternate.mkdir()
        try:
            manifest['cheekPrint'] = save_cheek_print(page, source, marks, plan, photo, offset, alternate)
        except (ValueError, cv2.error) as err:
            shutil.rmtree(alternate)
            manifest['cheekPrint'] = {'applied': False, 'note': str(err)}
    manifest.update(save_portrait(page, source, marks, plan, dst))
    (dst / 'result.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('garden', type=Path, help='Local editor HTML built for the table dimensions.')
    parser.add_argument('photo', type=Path, help='A private local guest photo.')
    parser.add_argument(
        '--out', type=Path, required=True, help='New directory for the verified drawing and preview.'
    )
    parser.add_argument(
        '--layout', choices=['garden', 'portrait'], help='Choose a layout in a combined garden.'
    )
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument(
        '--face', type=int, help='Face number from the ordinary guest photo picker, beginning at 1.'
    )
    choice.add_argument(
        '--face-box',
        nargs=3,
        type=float,
        metavar=('X', 'Y', 'WIDTH'),
        help='Use a manually framed square in guest photo-picker pixels.',
    )
    parser.add_argument(
        '--trace-nose',
        action='store_true',
        help='Also trace a well-resolved photographic nose when every other stroke survives.',
    )
    parser.add_argument(
        '--trace-brows', action='store_true',
        help='Center the eyebrow strokes on visible brow hair where all other features fit.',
    )
    parser.add_argument(
        '--trace-smile', action='store_true',
        help='Trace the opening between the lips when the photo and the available sand resolve it.',
    )
    parser.add_argument(
        '--trace-eyes', action='store_true',
        help='Follow the photographed eyelids and iris where both eyes resolve at the given groove width.',
    )
    parser.add_argument('--cheek-print', action='store_true', help='Engrave the photographed cheek and jaw shadows.')
    parser.add_argument('--rake-print', action='store_true',
                        help='Also make a fully clearing 7 mm shadow print from the selected face.')
    parser.add_argument('--full-hair', action='store_true',
                        help='Also save a wider engraving in full-hair/ when long locks extend beyond the close-up.')
    parser.add_argument('--flowing-hair', action='store_true',
                        help='Also trace the photographed direction of the hair in flowing-hair/ when it fits.')
    parser.add_argument('--hair-woodcut', action='store_true',
                        help='Also save a hair-only woodcut in hair-woodcut/ when it fits the photograph.')
    parser.add_argument('--browser', type=Path, help='Installed Chromium executable.')
    parser.add_argument(
        '--model-python',
        type=Path,
        default=TOOLS.parent / 'build/p2s-venv/bin/python',
        help='Python with MediaPipe and the installed photo2sand models.',
    )
    args = parser.parse_args()
    if not args.garden.is_file() or not args.photo.is_file():
        parser.error('Choose an existing local garden HTML and a photograph.')
    if args.face is not None and args.face < 1:
        parser.error('Face numbers begin at 1.')
    if args.face_box is not None:
        args.face_box = dict(zip(('x', 'y', 'w'), args.face_box))
    dest = args.out.resolve()
    if dest.exists():
        parser.error('Choose a new output directory so an earlier drawing stays intact.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=dest.parent, prefix='.portrait-') as temporary:
            stage = Path(temporary) / 'drawing'
            stage.mkdir(mode=0o700)
            with sync_playwright() as engine:
                with engine.chromium.launch(executable_path=chromium(engine, args.browser)) as browser:
                    context = browser.new_context(offline=True, service_workers='block')
                    context.route('http://**/*', lambda request: request.abort())
                    context.route('https://**/*', lambda request: request.abort())
                    manifest = prepare(context.new_page(), args, stage)
            stage.rename(dest)
    except Exception as err:
        parser.exit(1, f'Could not prepare the portrait. {err}\n')
    print(f'{manifest["method"]}, {manifest["rows"]:,} positions. {dest / "preview.png"}')
    if 'nose' in manifest:
        print(manifest['nose']['note'])
    if manifest['note']:
        print(manifest['note'])


if __name__ == '__main__':
    main()
