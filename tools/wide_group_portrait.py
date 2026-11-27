"""Fit the photographed features of two to four selected guests in the center of the garden."""

import json
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linprog
from scipy.spatial import cKDTree

import wide_portrait as portrait


# Only the compact mark list crosses the browser boundary during fitting.
# The final plan and downloads are obtained from the ordinary garden planner.
SUMMARY = """marks => {
  const s=JSON.parse(document.querySelector('#scene').textContent), g=s.live;
  try {
    return OasisRingPlanner.shadowPhoto(g.wideCenter || s.zones.center,marks,g).marks.map(m=>m.source);
  } catch(error) {return [];}
}"""
ESSENTIAL = {'head', 'eye', 'glasses', 'smile', 'nose', 'bridge'}


@dataclass
class Face:
    marks: list
    required: set
    hull: np.ndarray
    box: dict


def match_boxes(selected, detected):
    """Require a distinct detected face behind every requested crop on the same photograph."""
    matches = set()
    for box in selected:
        scores = []
        for peer in detected:
            side = np.array([box['w'], peer['w']])
            offset = np.abs([box[k] - peer[k] for k in ('x', 'y')])
            overlap = np.clip(side.mean() - offset, 0, side.min()).prod()
            scores.append(overlap / (side @ side - overlap))
        order = np.argsort(scores)
        if (not len(order) or scores[order[-1]] < .55 or order[-1] in matches
                or len(order) > 1 and scores[order[-2]] > scores[order[-1]] - .15):
            raise ValueError('Select a separate visible face for each person in the photo.')
        matches.add(order[-1])


def face_art(marks, plan, box):
    """Use only engraved solo features. Retain the distinction between a lens and an eye within it."""
    offered = [marks[i] for i in sorted(event['source'] for event in plan['events'])]
    eyes = [m for m in offered if m['kind'] in ('eye', 'glasses')]
    if len(eyes) != 2 or not all(any(m['kind'] == k for m in offered) for k in ('head', 'smile', 'nose')):
        raise ValueError('One of these faces has too little photographed detail for a group engraving.')
    required = {i for i, m in enumerate(offered) if m['kind'] in ESSENTIAL or m.get('measuredLensEye')}
    # With loose hair, the open head traces the hair's outer edge. The
    # separate closed hairline contains the jaw and must fit before shadows.
    if any(m['kind'] == 'head' and not m['closed'] for m in offered):
        required.update(i for i, m in enumerate(offered) if m['kind'] == 'hairline' and m['closed'])
    outline = np.concatenate([offered[i]['points'] for i in sorted(required)])
    hull = cv2.convexHull(np.float32(outline))[:, 0].astype(float)
    return Face(offered, required, hull, box)


def face_directions(faces):
    centers = np.array([[f.box['x'], -f.box['y']] for f in faces])
    offsets = centers - centers.mean(axis=0)
    order = np.argsort(np.arctan2(offsets[:, 1], offsets[:, 0]))
    angles = np.arange(len(faces)) * 2 * np.pi / len(faces)
    ideal = np.exp(1j * angles)
    alignment = np.sum((offsets[order, 0] + 1j * offsets[order, 1]) * ideal.conj())
    if abs(alignment) < 1.e-6:
        raise ValueError('The chosen face positions overlap.')
    directions = np.empty(len(faces))
    directions[order] = angles + np.angle(alignment)
    return directions


def fitted_head(face, direction, count, radius, groove):
    """Maximize a true-to-scale silhouette within its part of the circle."""
    # An inscribed regular polygon bounds the entire head inside the rounded
    # table. The two radial edges reserve clear space between different people.
    angles = np.arange(64) * 2 * np.pi / 64
    normal = np.column_stack((np.cos(angles), np.sin(angles)))
    distance = np.full(len(angles), (radius - 2.4 * groove) * np.cos(np.pi / 64))
    half_angle = np.pi / count
    edges = np.array([direction + half_angle + np.pi / 2, direction - half_angle - np.pi / 2])
    normal = np.vstack([normal, np.column_stack((np.cos(edges), np.sin(edges)))])
    distance = np.r_[distance, -1.7 * groove, -1.7 * groove]
    supports = np.max(face.hull @ normal.T, axis=0)
    result = linprog([0, 0, -1], A_ub=np.column_stack((normal, supports)), b_ub=distance,
                     bounds=[(None, None), (None, None), (0., None)], method='highs')
    if not result.success:
        raise ValueError('The selected heads do not fit together.')
    return result.x[:2], result.x[2]


def arrange_marks(faces, directions, radius, groove, rotation):
    gathered = []
    required = set()
    for owner, (face, angle) in enumerate(zip(faces, directions)):
        position, scale = fitted_head(face, angle + rotation, len(faces), radius, groove)
        for index, original in enumerate(face.marks):
            mark = dict(original)
            for field in ('points', 'lids', 'rim', 'opening'):
                if field in mark:
                    mark[field] = (np.asarray(mark[field]) * scale + position).tolist()
            if max(np.linalg.norm(mark['points'], axis=1)) + 1.25 * groove >= radius:
                if index in face.required:
                    return [], set()
                continue
            key = (owner, index)
            if index in face.required:
                required.add(key)
            gathered.append((key, mark))
    order_marks(gathered, required)
    return gathered, required


def order_marks(gathered, required):
    # Eyes inside spectacles need their own approach before optional shading
    # competes for the same area. Preserve the camera-derived opening and nose.
    order = {'head': 0, 'glasses': 1, 'eye': 1, 'smile': 2, 'bridge': 3, 'nose': 4, 'brow': 6}
    gathered.sort(key=lambda item: (order.get(item[1]['kind'], 5 if item[0] in required else 7), item[0]))


def choose_group(page, source, faces):
    radius, groove = source['diameter'] / 2, source['width']
    directions = face_directions(faces)
    candidates = []
    for rotation in (0, -8, 8, -16, 16, -20, 20, -22, 22, -24, 24):
        gathered, required = arrange_marks(faces, directions, radius, groove, np.deg2rad(rotation))
        if not gathered:
            continue
        kept = page.evaluate(SUMMARY, [m for _, m in gathered])
        reached = {gathered[i][0] for i in kept}
        if not required <= reached:
            continue
        coverage = [sum(1 for who, _ in reached if who == owner) for owner in range(len(faces))]
        score = (min(coverage), sum(coverage), -abs(rotation))
        candidates.append((score, gathered, required, rotation))
    # A mark can be reached but shortened in the downloaded route. Check
    # each promising arrangement before giving up on the selected people.
    problem = 'The eyes, noses and smiles need more room to engrave these people together.'
    for _, gathered, required, rotation in sorted(candidates, key=lambda c: c[0], reverse=True):
        marks = [m for _, m in gathered]
        plan = portrait.plan_marks(page, marks)
        if not plan:
            continue
        try:
            gap = verify_group(page, source, gathered, required, plan, len(faces))
        except ValueError as err:
            problem = str(err)
            continue
        return gathered, required, plan, gap, np.deg2rad(rotation)
    raise ValueError(problem)


def verify_group(page, source, gathered, required, plan, count, *, route=None):
    if route is None:
        route = portrait.downloaded_route(page, plan, source['dock'])
    width = source['width']
    clouds = [[] for _ in range(count)]
    reached = set()
    for event in plan['events']:
        key, mark = gathered[event['source']]
        cloud = portrait.excursion_cloud(route, event, source['radius'], .10 * width)
        clouds[key[0]].append(cloud)
        if key not in required:
            continue
        path = np.asarray(mark['points'])
        outline = np.vstack([path, path[:1]]) if mark['closed'] else path
        samples = portrait.samples(outline, .10 * width)
        distances = cKDTree(cloud).query(samples)[0]
        if np.quantile(distances, .80) > .35 * width:
            raise ValueError('A photographed feature would be cut short in this group.')
        reached.add(key)
    if reached != required:
        raise ValueError('A selected face lost a defining feature.')
    clouds = [np.concatenate(group) for group in clouds]
    gaps = [cKDTree(first).query(other)[0].min() for i, first in enumerate(clouds) for other in clouds[i + 1:]]
    minimum_gap = 1.55 * width
    if count == 4:
        # In the four-person layout, drift on each of two adjacent grooves
        # can consume the open sand between the portraits.
        minimum_gap = max(minimum_gap, width + 2 * source.get('trackingMarginMm', 0))
    if min(gaps) < minimum_gap:
        raise ValueError('The engraved portraits would touch at this size.')
    return float(min(gaps))


def excursions(gathered, plan, route):
    return {gathered[e['source']][0]: route[e['first']:e['last']+1] for e in plan['events']}


def same_neighbors(previous, updated, owner):
    others = {key for key in previous if key[0] != owner}
    return (others == {key for key in updated if key[0] != owner}
            and all(portrait.same_excursion(previous[key], updated[key]) for key in others))


def prepare_group(page, args, dst, *, upload=None, selected_faces):
    if len(selected_faces) not in (2, 3, 4):
        raise ValueError('Select two to four faces for a group engraving.')
    portrait.open_portrait_photo(page, args, upload)
    detected = page.evaluate("""async () => {
      const file = document.querySelector('#hostPortraitInput').files[0];
      return (await GuestPhoto.inspectSeatPhoto(file)).detectedFaces;
    }""")
    match_boxes(selected_faces, detected)
    faces = []
    studies = {}
    print_studies = []
    crowns = {}
    want_locks = getattr(args, 'group_locks', False)
    for box in selected_faces:
        source, marks, plan, photo, _, manifest = portrait.trace_selected_face(page, args, box, group=True)
        if not marks or any(abs(source['selected'][k] - box[k]) > .01 for k in ('x', 'y', 'w')):
            raise ValueError('The selected crop could not be engraved from this photo.')
        if source.get('hairCropClipped') and photo is not None:
            from wide_portrait_long_hair import wider_hair

            try:
                expanded, wider_plan, _ = wider_hair(
                    page, source, marks, plan, manifest['translationMm'], args.model_python, raised_only=True)
                crowns[len(faces)] = face_art(expanded, wider_plan, box)
            except (ValueError, cv2.error):
                pass  # An ordinary close crop still works for unconfirmed hair.
        marks, plan = portrait.finish_brows(page, source, marks, plan, photo, manifest)
        if want_locks and photo is not None:
            from wide_group_locks import photographed_locks

            try:
                studies[len(faces)] = photographed_locks(
                    page, source, marks, plan, photo, manifest['translationMm'])
            except (ValueError, cv2.error):
                pass  # Other selected people may have visible long hair.
        faces.append(face_art(marks, plan, box))
        if getattr(args, 'rake_print', False):
            print_studies.append((source, faces[-1].marks, photo, manifest['translationMm']))
    if want_locks and not studies:
        raise ValueError('The selected people have no separate photographed locks on both sides.')
    if len(faces) == 4:
        source['trackingMarginMm'] = page.evaluate(
            "JSON.parse(document.querySelector('#scene').textContent).live.trackingMarginMM || 0"
        )
    gathered, required, plan, gap, rotation = choose_group(page, source, faces)
    placements = {}
    if want_locks:
        from wide_group_locks import fit_group_locks

        gathered, required, plan, gap, placements = fit_group_locks(page, source, faces, studies, rotation, plan)
    if crowns:
        from wide_group_crown import fit_group_crowns

        # Extra required marks beyond the original face are the requested
        # bilateral locks. Leave that person's verified pair in place.
        locked = {owner for owner, i in required if i >= len(faces[owner].marks)}
        gathered, required, plan, gap = fit_group_crowns(
            page, source, gathered, required, plan, gap,
            {owner: face for owner, face in crowns.items() if owner not in locked}, len(faces))
    if placements:
        from wide_group_locks import finish_group_hair

        gathered, plan, gap, added = finish_group_hair(page, source, gathered, plan, gap, placements, len(faces))
    manifest = portrait.save_portrait(page, source, [m for _, m in gathered], plan, dst)
    if print_studies:
        from wide_pair_rake import save_pair_print

        try:
            manifest['rakePrint'] = save_pair_print(page, source, print_studies, gathered, required, plan, dst / 'rake-print')
        except (ValueError, cv2.error) as err:
            manifest['rakePrint'] = {'applied': False, 'note': str(err)}
    if placements:
        manifest['locks'] = 2*len(placements) + added
    manifest.update(method='group-engraving', people=len(faces), minimumGapMm=round(gap, 2),
                    note='The drawing follows the photographed features of the selected people.',
                    diameterMm=source['diameter'], grooveMm=source['width'])
    (dst / 'result.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest
