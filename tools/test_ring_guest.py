#!/usr/bin/env python3
"""Exercise the browser's guest-ring planner offline, from selection to its exported .thr files.

Run from any directory with `python3 tools/test_ring_guest.py`. Requires Node.
"""
import json
import math
from io import StringIO
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.spatial import cKDTree

import check_ring_scene as check
from guest_embellishments import engraving, seated_roof_crescent
from guest_reveal import eligible_sources
import guest_scene
import ring_scene
import thrcommon


PLANNER = Path(__file__).resolve().parents[1] / 'web' / 'ring-planner.js'
NODE = r"""
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [modulePath, folder] = process.argv.slice(1);
const planner = require(modulePath);
const scene = JSON.parse(fs.readFileSync(path.join(folder, 'scene.json')));
const {cases, custom} = JSON.parse(fs.readFileSync(0));
const defaults = cases[0];
const bad = [null, [], defaults.slice(0,2), [...defaults,'guitar'], defaults.join(','),
             ['',...defaults.slice(1)], [42,...defaults.slice(1)],
             ['unknown',...defaults.slice(1)], ['constructor',...defaults.slice(1)]];
for (const ids of bad) assert.throws(() => planner.plan(scene.guest_plan, ids), undefined,
                                     'Unsupported selection accepted: ' + JSON.stringify(ids));
const sketchIds = ['sketch', ...defaults.slice(1)];
for (const invalid of [[], [[0,0],[.1,.2],[.3,0]], [[0,0],[0,0],[0,0],[0,0]],
                       [[0,0],[.3,0],[0,1],[.01,0]], [[0,0],[.9,.8],[.3,.4],[0,0]],
                       [[0,0],[NaN,0],[.3,.4],[0,0]], Array(8001).fill([0,0])]) {
    assert.throws(() => planner.plan(scene.guest_plan, sketchIds, {sketch:invalid}));
}
assert.throws(() => planner.plan(scene.guest_plan, defaults, {phage:custom.sketch}));
// In bounds and closed, but the many trips across the shape expand past the
// planner's real travel-point budget when it inserts intermediate waypoints.
const zigzag = Array.from({length: 2201}, (_, i) => [i % 2 ? .99 : -.99, 0]);
assert.throws(() => planner.plan(scene.guest_plan, sketchIds, {sketch: zigzag}), /32,000/);

if (scene.guest_plan.defaults.includes('books_open')) {
    // Two valid photo traces can exceed the single-place point limit when
    // concatenated. Repeated sub-groove samples may be combined in the pair.
    const pairCatalog = {pairMotifs:{}, pairGroove:scene.groove_width / scene.guest_plan.geometry.scale};
    const first = {id:'sketch-1',points:custom.detailed};
    const second = {id:'sketch-2',points:custom.detailed.map(([x,y])=>[-y,x])};
    const original = JSON.stringify([first,second]);
    for (const relation of ['beside','behind']) {
        const path = planner.pair(pairCatalog,first,second,relation);
        assert.ok(path.length <= 8000);
        assert.deepEqual(path[0],path.at(-1));
        assert.ok(path.every(p=>Math.hypot(...p)<=1));
        const route = planner.plan(scene.guest_plan,['new-pair',...defaults.slice(1)],{'new-pair':path});
        assert.ok(planner.files(route.path).length);
    }
    assert.equal(JSON.stringify([first,second]),original);
    assert.throws(()=>planner.pair(pairCatalog,{points:[[0,0],[1,1],[0,0],[0,0]]},second,'beside'),/unit circle/);

    const proposed = cases[1];
    const early = planner.planChange(scene.guest_plan, defaults, proposed);
    assert.equal(early.earlyFrom, 'phage');
    const catalog = scene.guest_plan, tile = catalog.places[0];
    const source = tile.revealTargets[proposed[0]];
    assert.deepEqual(early.files, source.files);
    assert.deepEqual(early.segments[1].at(-1), early.path[source.progressIndex]);
    for (const [slot, old, target] of [[0,'guitar_silhouette','books_open'], [1,'telescope','books_open'],
                                       [1,'telescope','temple_gable'], [2,'phage','books_open'],
                                       [0,'phage','phage_faceted'],[1,'phage_faceted','phage'],
                                       [2,'phage','phage_faceted']]) {
        const before = defaults.slice(), next = defaults.slice();
        before[slot] = old;
        next[slot] = target;
        const route = planner.planChange(catalog,before,next);
        assert.equal(route.earlyFrom,old);
        assert.deepEqual(route.files, catalog.places[slot].revealTargets[target].files);
        if (target === 'books_open') {
            const record = catalog.places[slot].revealTargets[target];
            assert.deepEqual(route.segments[1].at(-1), route.path[record.progressIndex]);
            for (const prior of record.from) {
                before[slot] = prior;
                assert.deepEqual(planner.planChange(catalog,before,next).files, route.files);
            }
        }
        before[slot] = 'sketch';
        assert.equal(planner.planChange(catalog,before,next,custom).earlyFrom,undefined);
        before[slot] = catalog.openSubject;
        assert.equal(planner.planChange(catalog,before,next).fill,true);
    }
    function verifyBatch(before, after) {
        const route = planner.planChange(catalog,before,after,custom);
        const changed = after.map((id,i) => before[i]!==id ? i : -1).filter(i => i>=0);
        assert.deepEqual(route.parts.map(p=>p.place).sort(), changed);
        let file = 0;
        for (const part of route.parts) {
            const one = before.slice();
            one[part.place] = after[part.place];
            const local = planner.planChange(catalog,before,one,custom);
            const signed = local.files || planner.files(local.path);
            assert.equal(part.fill, local.fill);
            assert.equal(part.earlyFrom, local.earlyFrom);
            if (route.tour) {
                assert.equal(part.fill,true);
                const chunks = route.filePaths.slice(file,file+part.count);
                const leg = planner.join(chunks,.000011);
                const target = local.art, tau = 2*Math.PI;
                const actualArt = leg.some(([a,r],i) => {
                    if (Math.abs(r-target[0][1]) > .000006 || i+target.length>leg.length) return false;
                    const offset = tau*Math.round((a-target[0][0])/tau);
                    if (Math.abs(a-target[0][0]-offset) > .000006) return false;
                    return target.every(([b,s],j) => Math.abs(leg[i+j][0]-b-offset) <= .000006 &&
                        Math.abs(leg[i+j][1]-s) <= .000006);
                });
                assert.ok(actualArt, 'Connected trip changed the guest engraving');
                file += part.count;
                continue;
            }
            assert.equal(part.count, signed.length);
            for (const {text} of signed) {
                assert.deepEqual(route.files[file], {name:'guest-ring-'+(file+1)+'.thr',text});
                file++;
            }
        }
        assert.equal(file,route.files.length);
        const firstEnd = route.filePaths.slice(0,route.parts[0].count).reduce((sum,p) => sum+p.length-1,0);
        assert.deepEqual(route.segments[1],route.path.slice(0,firstEnd+1));
        return route.parts;
    }
    const open = catalog.openSubject;
    for (const after of [[...defaults.slice(0,2),open], defaults]) {
        assert.ok(verifyBatch([open,open,open],after).every(part=>part.fill));
    }
    const entered = [open,open,defaults[2]];
    // On the fitted garden two short trips beat the connected route for
    // these neighbors. A gallery with only the original entries uses the tour.
    const oldEntries = {...catalog,places:catalog.places.map(p=>({...p,shortFill:undefined}))};
    const oldPair = planner.planChange(oldEntries,entered,defaults);
    const pair = planner.planChange(catalog,entered,defaults);
    assert.equal(oldPair.tour,true);
    assert.deepEqual(pair.files,planner.planChange({...catalog,fillTours:undefined},entered,defaults).files);
    assert.ok(planner.travelDistances(pair.path).at(-1) < planner.travelDistances(oldPair.path).at(-1));
    // The shorter tour through Lek first delays the first picture. With Alex
    // already on display, the earlier finished phage still shortens the trip.
    const aroundBook = planner.planChange(catalog,[open,defaults[1],open],defaults);
    assert.equal(aroundBook.tour,true);
    assert.deepEqual(aroundBook.parts.map(p=>p.place),[0,2]);
    const byPlace = planner.planChange(catalog,[open,defaults[1],open],defaults,{},true);
    assert.deepEqual(byPlace.files,planner.planChange({...catalog,fillTours:undefined},[open,defaults[1],open],defaults).files);
    // A continuous sketch can span a player file boundary mid-seat.
    custom.longSketch = Array.from({length:901}, (_,i)=>[i%2 ? .7 : -.7,0]);
    assert.ok(verifyBatch(entered,['longSketch',defaults[1],defaults[2]]).some(p=>p.count>1));
    // A direct addition precedes an occupied seat even if its place number is higher.
    const mixed = verifyBatch(['phage',open,defaults[2]], [proposed[0],'detailed',defaults[2]]);
    assert.equal(mixed[0].place,1);
    assert.equal(mixed[0].fill,true);
    assert.equal(mixed[1].earlyFrom,'phage');
    // These two local trips run farther than a whole-ring pass but keep the
    // seated guest's books intact. With all three changing the full ring wins.
    verifyBatch(defaults, ['telescope',defaults[1],open]);
    const longTrip = verifyBatch(defaults, ['detailed', 'temple_gable', defaults[2]]);
    assert.ok(longTrip.find(part=>part.place===0).count > 1);
    const allChanged = [proposed[0],'telescope','books_open'];
    assert.deepEqual(planner.planChange(catalog,defaults,allChanged),planner.plan(catalog,allChanged));
    const separate = planner.planChange(catalog,defaults,allChanged,{},true);
    assert.deepEqual(separate.parts.map(part=>part.place).sort(),[0,1,2]);
    assert.throws(()=>planner.planChange(catalog,defaults,defaults,{},true),/already/);
    const legacy = {...catalog,places:undefined};
    assert.deepEqual(planner.planChange(legacy,[open,open,open],defaults),planner.plan(legacy,defaults));
    assert.throws(()=>planner.planChange(legacy,[open,open,open],defaults,{},true),/guest place/);
    // Reopen a previous catalog which pinned its guitar to the old phage.
    tile.reveals = {phage:{[proposed[0]]:source}};
    delete tile.revealTargets;
    assert.deepEqual(planner.planChange(catalog,defaults,proposed).files,early.files);
    assert.equal(planner.planChange(catalog,proposed,defaults).earlyFrom,undefined);
}

function save(prefix, route) {
    const files = planner.files(route);
    assert(files.length > 0);
    assert.equal(new Set(files.map(file => file.name)).size, files.length);
    return files.map(file => {
        assert.equal(path.basename(file.name), file.name);
        assert.match(file.name, /\.thr$/);
        const local = prefix + '-' + file.name;
        fs.writeFileSync(path.join(folder, local), file.text);
        return local;
    });
}
const variants = cases.map((ids, index) => {
    const result = planner.plan(scene.guest_plan, ids, custom);
    return {name: ids.join('/'), path: result.art, replace: save('guest' + index, result.path)};
});
scene.zones.middle.variants.push(...variants);
fs.writeFileSync(path.join(folder, 'with-guests.json'), JSON.stringify(scene));
"""


def check_lasting_strokes(record, excursion, rail, groove, margin, partial_visits):
    parts = [np.loadtxt(StringIO(file['text'])) for file in record['files']]
    route = check.joined(parts, ring_scene.DOCK, ring_scene.DOCK, 'guest drawing')
    angle = excursion[np.flatnonzero(abs(excursion[:, 1]-rail) > 1e-7)[0]-1, 0]
    at_binding = ((abs(check.wrapped(route[:, 0]-angle)) <= 1e-5) &
                  (abs(route[:, 1]-rail) <= 1e-5))
    visits = np.flatnonzero(at_binding).reshape(-1, 2)
    assert len(visits) == partial_visits+2  # partial visits, full drawing, finishing retrace
    assert visits[partial_visits-1, 1] <= record['progressIndex'] < visits[partial_visits, 0]
    spacing = groove/200
    clearance = 1.65*groove + 2*margin
    finished = cKDTree(check.sample_walk(route[visits[-1, 0]:visits[-1, 1]+1], spacing))
    for (start, end), (next_start, _) in zip(visits[:partial_visits], visits[1:]):
        strokes = check.sample_walk(route[start:end+1], spacing)
        assert finished.query(strokes)[0].max() < spacing
        # Exclude the deliberately shared rail and its hanging line, which
        # the ball retraces on every visit. Later erase rows must leave the drawing intact.
        signed_rail = min(rail, round(rail, 5))
        strokes = strokes[np.linalg.norm(strokes, axis=1) < signed_rail-clearance-spacing]
        intervening = check.sample_walk(route[end:next_start+1], spacing)
        assert cKDTree(intervening).query(strokes)[0].min() - spacing >= clearance


def check_far_visits(record, place, excursion, groove, margin):
    """Check signed detours against the old spiral and the requested subject."""
    parts = [np.loadtxt(StringIO(f['text'])) for f in record['files']]
    route = check.joined(parts, ring_scene.DOCK, ring_scene.DOCK, 'far guest')
    approach, clear, recut, end = (thrcommon.unpack_path(place[k]) for k in ('approach','clear','recut','exit'))
    ordinary = ring_scene.join(approach,clear,recut,excursion,end)
    expected = np.loadtxt(thrcommon.thr_lines(ordinary))
    # Every point of the original erase and final engraving must be visited
    # in order. Each extra excursion begins and ends on the interrupted lane.
    matches, cursor = [], 0
    for i, point in enumerate(route):
        if cursor < len(expected) and np.max(abs(point-expected[cursor])) < 1e-7:
            matches.append(i)
            cursor += 1
    assert cursor == len(expected), 'An original clearing lane or final stroke was skipped'
    gaps = np.flatnonzero(np.diff(matches) > 1)
    assert len(gaps) == 2
    assert record['progressIndex'] == matches[gaps[0]+1]-1
    spacing = groove/30
    drawn = cKDTree(check.sample_walk(excursion,spacing))
    visits = []
    for old_index in gaps:
        begin, finish = matches[old_index]+1, matches[old_index+1]-1
        visits.append(route[begin:finish+1])
        np.testing.assert_allclose(route[begin],route[finish],atol=1e-8,rtol=0)
        a, b = expected[old_index:old_index+2]
        t = (route[begin,0]-a[0])/(b[0]-a[0])
        assert -.001 <= t <= 1.001 and abs(route[begin,1]-(a[1]+t*(b[1]-a[1]))) < 2e-5
        # The later full engraving may be one complete turn ahead at the rail.
        strokes = check.sample_walk(visits[-1],spacing)
        assert drawn.query(strokes)[0].max() < spacing
        remaining = expected[old_index+1:len(approach)+len(clear)-1]
        sweeping = cKDTree(check.sample_walk(remaining,spacing))
        surviving = strokes[sweeping.query(strokes)[0] > 1.65*groove + 2*margin + spacing]
        assert len(np.unique(np.round(surviving/(groove/4)),axis=0)) >= 12
    return visits


def test_fine_far_seat(folder):
    ring_scene.build(folder, 410, 4, 2, 4, face_edge=True, guest_pitch_mm=2)
    manifest = json.loads((folder / 'scene.json').read_text())
    catalog = manifest['guest_plan']
    place = catalog['places'][2]
    targets = place['revealTargets']
    assert catalog.get('preferredSubjects', {}).get('phage', 'phage') == 'phage'
    assert set(targets) == {'guitar','books','temple','phage','phage_faceted', *ring_scene.SMALL_GUEST_STYLES.values()}
    for target, record in targets.items():
        assert set(record['from']) == set(catalog['subjects']) - {target}
        _, later = check_far_visits(record, place, thrcommon.unpack_path(catalog['excursions'][2][target]),
                                    manifest['groove_width'], manifest['tracking_margin'])
        if target == 'books':
            # The bookmark must lie on top of the horizontal page line at
            # both crossings. Inspect the last stroke there in chair coordinates.
            geo = catalog['geometry']
            angle = geo['angles'][2]
            center = geo['center'] * np.array([math.cos(angle), math.sin(angle)])
            marks = check.sample_walk(later, geo['scale']*.001)
            seated = thrcommon.rotate_xy(marks-center, ring_scene.GATE-angle)/geo['scale']
            for x in (.28, .48):
                hits = np.flatnonzero(np.linalg.norm(seated[:-1]-[x,.30],axis=1) < .025)
                dx, dy = seated[hits[-1]+1]-seated[hits[-1]]
                assert abs(dy) > 5*abs(dx)


def check_guest_additions(plan, place, slot, groove, dock):
    """Replay the short file on its base and compare with the complete engraving."""
    spacing = groove / 24
    def samples(subject):
        return check.sample_walk(thrcommon.unpack_path(plan['excursions'][slot][subject]), spacing)

    for base, target in [('temple_gable','temple_crescent'), ('guitar_silhouette','guitar_note')]:
        files = place['additions'][base][target]['files']
        route = check.joined([np.loadtxt(StringIO(part['text'])) for part in files], dock, dock, target)
        old, complete = samples(base), samples(target)
        short = check.sample_walk(route, spacing)
        assert check.travel(route)[-1] < check.travel(thrcommon.unpack_path(place['clear']))[-1]
        assert cKDTree(old).query(complete)[0].max() > groove
        assert cKDTree(np.vstack((old,short))).query(complete)[0].max() < spacing


def test_guest_paths(folder, face_edge, wide_groove=False):
    dimensions = (420, 7, 3.5, 4) if wide_groove else (450, 5, 2.5, 4)
    ring_scene.build(folder, *dimensions, face_edge=face_edge, guest_pitch_mm=2 if wide_groove else None)
    manifest = json.loads((folder / 'scene.json').read_text())
    catalog = ring_scene.SUBJECTS
    assert 'telescope' in catalog
    assert set(catalog) == set(manifest['guest_plan']['subjects'])
    if wide_groove:
        origins = manifest['guest_plan']
        assert origins['preferredSubjects']['phage'] == 'phage_faceted'
        assert origins['defaults'][0] == 'phage'  # keep established occupied beds and edition
        geometry = origins['geometry']
        rail, angle = geometry['rail'], geometry['angles'][0]
        # Both proposed old strokes fit in the nominal seat. The second
        # stroke's displaced sand can extend beyond the reach of the spiral.
        def hanging_line(radius):
            return [[angle-.02,rail], [angle,rail], [angle,radius], [angle,rail], [angle+.02,rail]]
        sources = {'central':hanging_line(geometry['center']), 'edge':hanging_line(geometry['bounds'][0]+.001)}
        args = (geometry, 0, manifest['zones']['middle']['erase_pitch'], manifest['groove_width'], origins['places'][0])
        assert eligible_sources(sources,*args,margin=manifest['tracking_margin']) == ['central']
        # The far seat can pass the neighbors on the outer groove. Moving
        # that same arc one groove toward their hanging strokes must fail.
        clearance = manifest['guest_clearance_mm']/dimensions[0]
        groove = manifest['groove_width']
        high = geometry['bounds'][1]
        for neighbor in geometry['angles'][:2]:
            for radius, safe in [(high, True), (high-groove, False)]:
                arc = ring_scene.line(neighbor-.12, radius, neighbor+.12, radius)
                assert ring_scene.keeps_other_places(arc, geometry, 2, groove, clearance) == safe
        # Exact downloads from earlier 420 mm galleries, so a phone
        # which already previewed that edition can still keep it after restart.
        old_books = ('c3ee275993e4e999fad7050fa6bd29653ddd6086623b808da0728dbd6e804f4f',
                     'e2a7a41d56d6c356105c821d7e83be42f572025c4307650dd331a35851421834')
        old_guitars = ('48f2a5c9334aefd3105df5535f1b33ec855d330cddeeb93d55b4fa9e5b8eabfc',
                       '1438ca377a8a19984416988f0fde1b3480029d0892a9f93963269b288769c8c4')
        old_phages = ('58181ea96733a74c118ef32118c3a720722302b04294051daf0323ad48ed6294',
                      'ecf8fed2cdd0167d3c3971cdabfd6e53bb4592a2d59307bdbb72add5f64e4ee2',
                      '90a76439db14462604ce0e43e02ba9705f84fee203fd01c4f4105a020b38c0b5')
        for slot, place in enumerate(origins['places']):
            check_guest_additions(origins, place, slot, groove, manifest['dock'])
            assert thrcommon.motion_files_hash(place['revealTargets']['phage']['files']) == old_phages[slot]
            assert origins['preferredSubjects']['pumpkin'] == 'pumpkin_ribbed'
            assert {'pumpkin_ribbed','phage','phage_faceted'} <= place['revealTargets'].keys()
            for target, reveal in place['revealTargets'].items():
                assert set(reveal['from']) == set(catalog) - {target}
                if slot == 2:
                    check_far_visits(reveal,place,thrcommon.unpack_path(origins['excursions'][slot][target]),
                                     manifest['groove_width'],manifest['tracking_margin'])
                elif target in ('books_open','guitar_silhouette'):
                    old = (old_guitars if target == 'guitar_silhouette' else old_books)[slot]
                    assert reveal['previousFilesHash'] == old
                    assert thrcommon.motion_files_hash(reveal['files']) != old
                    first, second = reveal['progressMoments']
                    assert first['label'] != second['label']
                    assert 0 < first['endIndex'] < second['endIndex'] == reveal['progressIndex']
                else:
                    assert 'previousFilesHash' not in reveal
                if slot != 2 and target in ('books_open', 'guitar_silhouette', 'pumpkin_ribbed'):
                    excursion = thrcommon.unpack_path(origins['excursions'][slot][target])
                    check_lasting_strokes(reveal, excursion, rail, manifest['groove_width'],
                                          manifest['tracking_margin'], 1 if target == 'pumpkin_ribbed' else 2)
    defaults = ['phage', 'books_open', 'temple_gable'] if wide_groove else list(guest_scene.DEFAULT)
    assert defaults == manifest['guest_plan']['defaults']
    guitar = ['guitar_silhouette' if wide_groove else 'guitar', *defaults[1:]]
    sketch = [[-.7,0], [-.15,.7], [.6,.25], [.37,-.6], [-.7,0]]
    # A smooth drawing at the maximum accepted input length exercises an
    # actual several-file export. Dense points are genuine positions on its path.
    u = np.linspace(0, math.tau, 8000)
    radius = .6 + .25*np.sin(3*u)
    detailed = np.column_stack((radius*np.cos(u), radius*np.sin(u))).tolist()
    detailed[-1] = detailed[0]
    custom = {'sketch': sketch, 'detailed': detailed}
    cases = [defaults, guitar, ['guitar'] * 3, ['sketch'] * 3, ['detailed'] * 3]
    for slot in range(3):
        for name in (*catalog, 'sketch'):
            ids = defaults.copy()
            ids[slot] = name
            if ids not in cases:
                cases.append(ids)
    subprocess.run(['node', '-e', NODE, str(PLANNER), str(folder)],
                   input=json.dumps({'cases': cases, 'custom': custom}), text=True, check=True)

    # The independent checker reads and reconnects the actual rounded files;
    # it also verifies the erase, swept groove, protected zones and return.
    extended = folder / 'with-guests.json'
    check.check_bundle(extended)
    middle = json.loads(extended.read_text())['zones']['middle']
    originals = manifest['zones']['middle']['variants']
    exports = middle['variants'][len(originals):]
    lo, hi = middle['safe_bounds']
    dock = manifest['dock']

    def load_route(files):
        return check.joined((check.read_path(folder, f) for f in files), dock, dock, str(files))

    for index in (0, 1):
        old = load_route(originals[index]['replace'])
        new = load_route(exports[index]['replace'])
        # Each independently generated text trajectory has five decimal places.
        np.testing.assert_allclose(new, old, rtol=0, atol=1.01e-5)

    for ids, variant in zip(cases, exports, strict=True):
        xy = np.column_stack(thrcommon.to_xy(variant['path']))
        tree = cKDTree(xy)
        # Use the original guest icons, independent of the planner's declared
        # selections, to check that each actual picture occupies its guest's seat.
        for angle, name in zip(np.deg2rad([-150, -30, 90]), ids, strict=True):
            center = (lo + hi) / 2 * np.array([math.cos(angle), math.sin(angle)])
            if wide_groove and name == 'temple_crescent':
                source, _ = engraving(name, ring_scene.motif('temple_gable'), callback=seated_roof_crescent)
            else:
                source = np.asarray(custom[name]) if name in custom else ring_scene.motif(name)
            if face_edge:
                # Looking in from the edge, up points toward the center.
                up = -center / np.linalg.norm(center)
                right = [up[1], -up[0]]
                source = source[:,0,None] * right + source[:,1,None] * up
            target = center + manifest['guest_plan']['geometry']['scale'] * source
            error, _ = tree.query(target)
            assert error.max() <= check.TOL, f'{name} is missing or misplaced in {ids}'

    files = exports[cases.index(['detailed'] * 3)]['replace']
    assert len(files) >= 3
    print(f'{len(catalog)} catalog subjects and two custom sketches verified in each of three places, '
          f'{len(cases)} distinct guest rings, two original routes matched, and '
          f'{len(load_route(files))} points round-tripped through {len(files)} files.')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as temporary:
        for edge in (False, True):
            test_guest_paths(Path(temporary) / ('edge' if edge else 'front'), edge)
        test_guest_paths(Path(temporary) / 'wide-groove', True, wide_groove=True)
        test_fine_far_seat(Path(temporary) / 'fine-groove')
