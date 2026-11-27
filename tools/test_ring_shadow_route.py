#!/usr/bin/env python3
"""Prove the photo-shadow planner's downloaded movement without driving a table.

Default: a synthetic, inward-facing smile and two eyes at 450 mm and 360 mm working radius.
Optionally test converted photographs with: test_ring_shadow_route.py --scene scene.json marks.json [...]
The marks are ordered Cartesian paths in millimetres, in the editor's shadowMarks format.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np
from scipy.spatial import cKDTree

import check_ring_scene as check
from garden_room import Layout
from oasis_player import validate_parts
from ring_preview import scene_data
from ring_scene import build


def example(radius, eye_near_cheek=False):
    def feature(kind, xy, closed=False):
        return dict(kind=kind, closed=closed, points=(np.array(xy) * radius).tolist())

    marks = [
        feature('head', [[0,.76], [-.69,.43], [-.66,-.36], [0,-.80], [.67,-.38], [.68,.41]], True),
        feature('eye', [[-.38,.18], [-.29,.24], [-.20,.21], [-.29,.17]], True),
        feature('eye', [[.15,.12], [.27,.23], [.40,.16]], False),
        feature('smile', [[-.27,-.25], [-.13,-.34], [0,-.36], [.18,-.33], [.31,-.21]]),
        feature('nose', [[-.07,.02], [.14,-.04]]),  # crosses the origin on the way to the far endpoint
        feature('shade', [[-.52,-.02], [-.45,-.08], [-.43,-.13]]),
        feature('shade', [[-.37,.18], [-.28,.24], [-.19,.21]]),  # in an eye's footprint
        feature('shade', [[-.1,.99], [-.02,1.04]]),  # outside drawable reach
    ]
    if eye_near_cheek:
        # The measured eye fits beside a sloping cheek. Entering the eye at
        # its outermost heading would bring the access groove into the head.
        marks[0] = feature('head', [[0,.78],[-.68,.48],[-.66,-.38],[0,-.8],[.47,-.35],[.68,.35],[.36,.65]], True)
        x = .5671
        marks[2] = feature('eye', [[x,.11],[x-.035,.14],[x-.15,.13],[x-.035,.085]], True)
    return marks


NODE = """
const fs=require('node:fs'), assert=require('node:assert/strict'), planner=require('./web/ring-planner.js');
const {scene, marks, example, faces}=JSON.parse(fs.readFileSync(0,'utf8'));
const center=scene.zones.center, geometry={radiusMM:scene.assumed_working_radius_mm,groove:scene.groove_width};
const options=faces ? {faces} : undefined;
for (const calibration of [{},{radiusMM:450,groove:NaN}])
  assert.throws(()=>planner.shadowPhoto(center,marks,calibration,options));
assert.throws(()=>planner.shadowPhoto(center,marks.filter(m=>m.kind==='head'),geometry,options));
if (faces) {
  assert.throws(()=>planner.shadowPhoto(center,marks,geometry));
  assert.throws(()=>planner.shadowPhoto(center,marks,geometry,{faces:[...faces,997]}));
  assert.throws(()=>planner.shadowPhoto(center,marks.filter(m=>m.owner!==faces[0] || m.kind!=='smile'),geometry,options));
  assert.throws(()=>planner.shadowPhoto(center,marks.filter(m=>m.owner!==faces[0] ||
    ['head','eye','glasses','smile'].includes(m.kind)),geometry,options));
}
const route=planner.shadowPhoto(center,marks,geometry,options);
assert.deepEqual(planner.join(route.segments),route.path);
if(example===true) {
  assert(!route.marks.some(m=>m.source===6 || m.source===7));
  assert(route.marks.some(m=>m.kind==='nose'));
  // The closed inner contour in a long-haired portrait draws the jaw.
  // Its route cannot silently disappear into an already occupied eye.
  const locks=marks.map(m=>m.kind==='head' ? {...m,closed:false} : m);
  const jaw={...marks[1],kind:'hairline',closed:true};
  assert.throws(()=>planner.shadowPhoto(center,[...locks,jaw],geometry));

  // An iris whose extra stroke conflicts with the cheek cannot cost the
  // guest a previously drawable shadow portrait. Recover the original lids.
  const crowded=marks.map((m,i)=>i===1 ? {...m,points:[...m.points,marks[0].points[0]]} : m);
  assert.throws(()=>planner.shadowPhoto(center,crowded,geometry));
  crowded[1].lids=marks[1].points;
  assert.deepEqual(planner.shadowPhoto(center,crowded,geometry).path,route.path);
  // Keep both complete lenses if a photographed hinge runs into the cheek.
  const frames=marks.map(m=>m.kind==='eye' ? {...m,kind:'glasses'} : m);
  const broad=frames.map((m,i)=>i===1 ? {...m,points:[...m.points,marks[0].points[0]]} : m);
  assert.throws(()=>planner.shadowPhoto(center,broad,geometry));
  broad[1].rim=frames[1].points;
  assert.deepEqual(planner.shadowPhoto(center,broad,geometry).path,
    planner.shadowPhoto(center,frames,geometry).path);
  // If either nostril lands on an eye or both reach the same patch of sand,
  // the old nose returns. Later events still point to their real source marks.
  const nose=marks.findIndex(m=>m.kind==='nose');
  for(const pair of [[marks[nose].points,marks[1].points], [marks[1].points,marks[nose].points],
                     [marks[nose].points,marks[nose].points]]){
    const proposed=marks.slice();
    proposed.splice(nose,1,{...marks[nose],noseBase:marks[nose].points,points:pair[0]},
      {...marks[nose],points:pair[1]});
    const fallback=planner.shadowPhoto(center,proposed,geometry);
    assert.deepEqual(fallback.path,route.path);
    assert.deepEqual(fallback.marks.map(m=>m.source),route.marks.map(m=>m.source>nose ? m.source+1 : m.source));
  }
  // Reject a proposed open smile that would cost the mouth its access from the spiral.
  const smile=marks.findIndex(m=>m.kind==='smile');
  const crowdedMouth=marks.map((m,i)=>i===smile ? {...m,points:[...m.points,marks[0].points[0]]} : m);
  assert.throws(()=>planner.shadowPhoto(center,crowdedMouth,geometry));
  crowdedMouth[smile].opening=marks[smile].points;
  assert.deepEqual(planner.shadowPhoto(center,crowdedMouth,geometry).path,route.path);
}
if(example==='group') {
  const hair = marks.length-1;
  assert(!route.marks.some(m=>m.source===hair), 'A hairline joined the other person’s head');
  const corrected = marks.map((m,i)=>i===hair ? {...m,owner:1} : m);
  assert(planner.shadowPhoto(center,corrected,geometry,options).marks.some(m=>m.source===hair));
}
process.stdout.write(JSON.stringify({parts:planner.files(route.path,'photo-shadow'),
    progress:route.marks, halfway:route.halfwayFraction, totalMM:route.distanceMM}));
"""


def exercise(manifest, marks, synthetic, label, faces=None):
    scene = json.loads(manifest.read_text())
    payload = json.dumps(dict(scene=scene, marks=marks, example=synthetic, faces=faces))
    js = subprocess.run(['node', '-e', NODE], input=payload, text=True, capture_output=True,
                        cwd=Path(__file__).resolve().parents[1])
    if js.returncode:
        raise AssertionError(js.stderr)
    result = json.loads(js.stdout)
    files, progress = result['parts'], result['progress']
    validate_parts(files)
    Layout(scene_data(manifest, 240)).check_route('center', files)
    assert 1 <= len(files) <= 24
    parts = [np.fromstring(f['text'], sep=' ').reshape(-1, 2) for f in files]
    motion = check.joined(parts, scene['dock'], scene['dock'], label)
    assert np.abs(np.diff(motion[:, 0])).max() < np.pi + check.TOL
    z = scene['zones']['center']
    raw = base64.b64decode(z['photoErase'])
    erase = np.cumsum(np.frombuffer(raw, '<i4').reshape(-1, 2), axis=0) / 1e8
    transit = np.asarray(z['transit'])
    clear_only = check.joined([transit, erase, transit[::-1]], scene['dock'], scene['dock'], 'clear')
    plain = np.ones(len(motion), bool)
    for mark in progress:
        plain[mark['first']:mark['last']+1] = False
    stripped = motion[plain].copy()
    stripped[:, 0] = np.unwrap(stripped[:, 0])
    assert check.same_track(stripped, clear_only), 'The export omitted or modified a prepared erase segment'

    full_radius = scene['assumed_working_radius_mm']
    groove = scene['groove_width'] * full_radius
    distance = np.r_[0, np.cumsum(np.hypot(np.diff(motion[:, 1]),
        np.diff(motion[:, 0]) * (motion[1:, 1] + motion[:-1, 1]) / 2))] * full_radius
    assert abs(distance[-1] - result['totalMM']) / result['totalMM'] < .0001
    assert abs(result['halfway'] - .5) < .001
    pose = lambda p: np.array([np.cos(p[0]), np.sin(p[0])]) * p[1] * full_radius
    finish = {}
    excursions = []
    people = {owner: [] for owner in (faces or [])}
    for mark in progress:
        start, end = mark['first'], mark['last']
        assert np.linalg.norm(pose(motion[start])-pose(motion[end])) < .01
        assert abs(motion[start, 1]*full_radius-mark['anchorRadiusMM']) < .01
        # Other marks are separate excursions. The intervening erase and
        # its later laps have nondecreasing radii; so do the rim and exit.
        # A pair of radial endpoints bounds every controller-interpolated segment.
        future_min = min(motion[end:, 1][plain[end:]].min(), motion[end, 1]) * full_radius
        assert future_min - mark['outerRadiusMM'] > 1.20 * groove
        # Check actual polar interpolation from the downloaded file, including
        # the thin radial entrances. Sampling contributes at most 0.10 groove
        # to the lower bound on the distance between any two excursions.
        delta = np.diff(motion[start:end+1], axis=0)
        travel = np.hypot(delta[:,1], delta[:,0] * motion[start:end+1,1].max()) * full_radius
        samples = np.maximum(1, np.ceil(travel / (.10*groove)).astype(int))
        segment = np.repeat(np.arange(len(delta)), samples)
        step = (np.arange(len(segment)) - (np.cumsum(samples)-samples)[segment]) / samples[segment]
        polar = np.vstack([motion[start+segment] + delta[segment]*step[:,None], motion[end]])
        xy = np.column_stack((np.cos(polar[:,0]), np.sin(polar[:,0]))) * polar[:,1,None] * full_radius
        ends = np.asarray(marks[mark['source']]['points'])[[0,-1]]
        joins = {'hairline':'head', 'bridge':'glasses'}
        owner = mark.get('owner')
        for previous, prev_owner, old_xy, old_tree, old_ends in excursions:
            if owner == prev_owner and joins.get(previous) == mark['kind']:
                far = np.linalg.norm(old_xy[:,None,:]-old_ends, axis=2).min(axis=1) > 2.4*groove
                gap = cKDTree(xy).query(old_xy[far])[0]
            else:
                candidates = xy
                if owner == prev_owner and joins.get(mark['kind']) == previous:
                    candidates = xy[np.linalg.norm(xy[:,None,:]-ends, axis=2).min(axis=1) > 2.4*groove]
                gap = old_tree.query(candidates)[0]
            assert gap.min(initial=np.inf) - .10*groove > groove, f"{mark['kind']} overlaps {previous}"
        tree = cKDTree(xy)
        excursions.append((mark['kind'], owner, xy, tree, ends))
        if faces:
            assert marks[mark['source']]['owner'] == owner, 'Progress assigned a feature to the wrong person'
            people[owner].append(mark['kind'])
            # Optional shading may be trimmed at either end. Prove at least two
            # source vertices were visited in the actual physical excursion.
            source_distances = tree.query(marks[mark['source']]['points'])[0]
            assert (source_distances < .11*groove).sum() >= 2, 'A group feature lost its source geometry'
        if mark['kind'] in ('eye','glasses','smile','head','nose'):
            # Confirm the depicted feature on the actual exported path. It
            # may be a non-closed lid or seam; each input vertex must be visited.
            xy = np.array([pose(p) for p in motion[start:end+1]])
            for point in marks[mark['source']]['points']:
                assert np.linalg.norm(xy-point, axis=1).min() < .025
        finish[mark['kind']] = max(finish.get(mark['kind'], 0), distance[end] / distance[-1])
    if faces:
        for kinds in people.values():
            assert 'head' in kinds and 'smile' in kinds
            assert kinds.count('eye') + kinds.count('glasses') >= 2
            assert set(kinds) & {'nose','brow','bridge','hairline','shade'}
    if synthetic is True:
        assert finish['eye'] < .40 and finish['smile'] < .40
        nose = next(m for m in progress if m['kind'] == 'nose')
        assert motion[nose['first']:nose['last']+1, 1].min() == 0
    eyes = max(finish.get('eye', 0), finish.get('glasses', 0))
    print(f"{label}: {len(progress)} marks, {len(motion):,} poses, {len(files)} files, "
          f"{distance[-1]/1000:.2f} m, both eyes at {eyes:.1%}, smile at {finish['smile']:.1%}.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--faces', type=int, help='Number of selected people in group shadow marks')
    parser.add_argument('marks', type=Path, nargs='*')
    args = parser.parse_args()
    if args.scene and args.marks:
        for source in args.marks:
            owners = list(range(args.faces)) if args.faces else None
            exercise(args.scene, json.loads(source.read_text()), False, source.stem, owners)
    elif args.scene or args.marks:
        parser.error('Supply the scene and at least one set of measured marks together.')
    else:
        with TemporaryDirectory() as temporary:
            for radius, groove in [(450, 5), (360, 6)]:
                folder = Path(temporary) / str(radius)
                build(folder, radius, groove, 2, 3.8, 'portrait')
                scene = json.loads((folder/'scene.json').read_text())
                reach = scene['zones']['center']['safe_bounds'][1] * radius
                exercise(folder/'scene.json', example(reach), True, f'{radius} mm working radius')
                if radius == 450:
                    exercise(folder/'scene.json', example(reach, True), True, 'Eye beside sloping cheek')
                    group = []
                    for owner, center in enumerate([[-.39,0],[.39,0]]):
                        for mark in example(.44*reach)[:6]:
                            points = (np.asarray(mark['points']) + reach*np.asarray(center)).tolist()
                            group.append(dict(mark, points=points, owner=owner))
                    # A deliberately misassigned hairline touches the other person's head.
                    q = np.array([.39,.76*.44]) * reach
                    group.append(dict(kind='hairline', owner=0, closed=False,
                                      points=[q.tolist(), (q + reach*np.array([.016,.06])).tolist()]))
                    exercise(folder/'scene.json', group, 'group', 'Two people in one center', [0,1])
