"""Exercise the offline Mini guest page with the two pairs and a larger family photo.

python3 tools/test_guest_inward_pair.py boardwalk-pair.jpg redwood-pair.jpg restaurant-three.jpg
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

from build_guest_center import build_guest_web_assets
from check_ring_scene import sample_walk
from test_guest_center import FramedMini, ROOT
from test_guest_inward_portrait import check_rim_letters, checked_route, phone, preview
from test_guest_web import Table
from wide_portrait import chromium


OPENING = 262.32299
RADIUS_MM = 114.03


def simulated_mini(assets, opening=OPENING):
    device = FramedMini(assets)
    device.status['theta'] = opening
    return device


def open_photo(page, source, *, group=True, style='inward', name=''):
    page.get_by_role('button', name='Photo', exact=True).click()
    page.locator('#photoTarget').select_option('full')
    page.locator('#photoMode').select_option('group' if group else 'one')
    page.locator('#file').set_input_files(source)
    page.locator('#inwardPortrait').select_option(style)
    page.locator('#photoName').fill(name)


def submit(page, device):
    before = device.started
    opening = device.status['theta']
    page.locator('#draw').click()
    expect(page.locator('#message')).to_contain_text('started')
    assert device.started == len(device.uploads) == before + 1 and not device.calls
    return checked_route(device.staged, opening)


def ordinary_group(browser, assets, source, count=2):
    device = simulated_mini(assets)
    with phone(browser, device) as page:
        # The ordinary whole-photo player accepts a binary path. Inward
        # drawings must still use the separately checked receipt endpoints.
        page.route('**/guest-draw', lambda route: Table.handle(device, route))
        open_photo(page, source, style='standard')
        page.locator('#previewButton').click()
        expect(page.locator('#draw')).to_be_enabled(timeout=20000)
        expect(page.locator('#faceBoxes button[aria-pressed=true]')).to_have_count(count)
        if page.locator('#pairSmile').is_visible():
            page.locator('#pairSmile').check()
            expect(page.locator('#draw')).to_be_enabled(timeout=20000)
        with page.expect_response(lambda response: response.url.endswith('/guest-draw')) as drawing:
            page.locator('#draw').click()
        response = drawing.value
        assert response.ok and response.request.headers['x-guest-mode'] == 'photo'
        route = np.frombuffer(response.request.post_data_buffer, dtype='<f4').reshape(-1, 2)
        assert len(device.calls) == 1 and not device.uploads and 2 <= len(route) <= 12000
        return route


def pair_geometry(browser, assets, source):
    ordinary = ordinary_group(browser, assets, source)
    device = simulated_mini(assets)
    with phone(browser, device) as page:
        open_photo(page, source)
        preview(page)
        expect(page.locator('#effect')).to_contain_text('both faces')
        contours = page.evaluate("""async () => {
            const file = document.querySelector('#file').files[0];
            const photo = await GuestPhoto.fromFile(file, {group:true, foregroundFirst:true,
                groupStyle:'heads', portraitFraming:'head', inwardContours:true, tracePairEyes:true,
                tracePairSmiles:true, portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
            return photo.inwardContours;
        }""")
        inward = submit(page, device)

    # Use submillimeter samples of the two real uploads, including the
    # ordinary player's interpolation. A spiral crossing a head by chance
    # cannot account for the full outline and several features inside it.
    tracks = [cKDTree(sample_walk(path, .0005) * RADIUS_MM) for path in (ordinary, inward)]
    sides = {False: [], True: []}
    for line in contours:
        xy = np.asarray(line) * RADIUS_MM
        sides[float(xy[:, 0].mean()) > 0].append(xy)
    for right, strokes in sides.items():
        head = next(line for line in strokes if np.ptp(line[:, 1]) > .65 * RADIUS_MM)
        # The ordinary player keeps every vertex at least 2% of the tray
        # radius from its singular center. A few head vertices land there.
        radius = np.linalg.norm(head, axis=1, keepdims=True)
        ordinary_head = head * np.maximum(1, .02 * RADIUS_MM / np.maximum(radius, 1e-12))
        for label, track, expected in zip(('ordinary', 'inward'), tracks, (ordinary_head, head)):
            miss = track.query(expected)[0].max()
            assert miss < .14, (source.name, right, label, 'head outline', miss)

        shared_details = [line for line in strokes if np.ptp(line[:, 1]) < .5 * RADIUS_MM and
                          np.ptp(line[:, 0]) > 8 and all(track.query(line)[0].max() < .14 for track in tracks)]
        assert len(shared_details) >= 2, (source.name, right, 'shared facial features')


def deselect_to_solo(browser, assets, source):
    routes = []
    for group in (True, False):
        device = simulated_mini(assets)
        with phone(browser, device) as page:
            open_photo(page, source, group=group, style='engraved')
            preview(page)
            buttons = page.locator('#faceBoxes button')
            expect(buttons).to_have_count(2)
            buttons.nth(0 if group else 1).click()
            expect(buttons.nth(1)).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#draw')).to_be_enabled(timeout=20000)
            if group:
                expect(page.locator('#effect')).to_contain_text('1 face selected')
            submit(page, device)
            routes.append(device.staged)
    assert routes[0] == routes[1], (source.name, 'one group face must match the same solo selection')


def busy_named_pair(browser, assets, source):
    name = 'Bill'
    device = simulated_mini(assets)
    with phone(browser, device) as host, phone(browser, device) as guest:
        open_photo(host, source)
        preview(host)
        submit(host, device)
        open_photo(guest, source, style='engraved', name=name)
        guest.locator('#previewButton').click()
        expect(guest.locator('#previewHeading')).to_have_text('Portrait preview on this phone', timeout=20000)
        expect(guest.locator('#faceBoxes button[aria-pressed=true]')).to_have_count(2)
        expect(guest.locator('#effect')).to_contain_text(name, ignore_case=True)
        expect(guest.locator('#draw')).to_be_disabled()
        assert device.started == len(device.uploads) == 1
        device.finish()
        dock = device.status['theta']
        assert abs(dock - OPENING) > 1
        expect(guest.locator('#draw')).to_be_enabled(timeout=20000)
        expect(guest.locator('#effect')).to_contain_text('both faces')
        expect(guest.locator('#effect')).to_contain_text('lower rim')
        expect(guest.locator('#photoName')).to_have_value(name)
        assert device.started == len(device.uploads) == 1
        path = submit(guest, device)
        check_rim_letters(guest, path, name)
        resumed = device.staged
    ready = simulated_mini(assets, dock)
    with phone(browser, ready) as independent:
        open_photo(independent, source, style='engraved', name=name)
        preview(independent)
        submit(independent, ready)
    assert resumed == ready.staged, 'The busy draft must be rebuilt from the same final dock as an idle submission.'


def pick_two_from_group(browser, assets, source, previous_photo):
    device = simulated_mini(assets)
    with phone(browser, device) as host, phone(browser, device) as page:
        open_photo(host, previous_photo)
        preview(host)
        submit(host, device)
        open_photo(page, source)
        page.locator('#previewButton').click()
        buttons = page.locator('#faceBoxes button')
        selected = page.locator('#faceBoxes button[aria-pressed=true]')
        expect(selected.nth(2)).to_be_visible(timeout=20000)
        count = selected.count()
        assert count == 3
        expect(page.locator('#previewHeading')).to_have_text('Portrait preview on this phone', timeout=20000)
        expect(page.locator('#draw')).to_be_disabled()
        # Including a fourth face cannot leave a stale draw button behind.
        extra = buttons.nth(buttons.evaluate_all(
            "nodes=>nodes.findIndex(node=>node.getAttribute('aria-pressed')==='false')"))
        extra.click()
        expect(selected).to_have_count(4)
        expect(page.locator('#error')).to_contain_text('Clear, then draw')
        expect(page.locator('#draw')).to_be_disabled()
        extra.click()
        expect(selected).to_have_count(3)
        # Preview the first two, then change the second person while the
        # other phone's drawing is still running.
        for remaining in range(count - 1, 1, -1):
            selected.last.click()
            expect(selected).to_have_count(remaining)
        waiting = page.locator('#previewHeading')
        expect(waiting).to_have_text('Portrait preview on this phone', timeout=20000)
        buttons.nth(1).click()
        expect(page.locator('#effect')).to_contain_text('1 face selected', timeout=20000)
        buttons.nth(count - 1).click()
        expect(page.locator('#effect')).to_contain_text('2 faces selected', timeout=20000)
        expect(waiting).to_have_text('Portrait preview on this phone')
        expect(page.locator('#draw')).to_be_disabled()
        assert device.started == len(device.uploads) == 1 and not device.calls
        device.finish()
        expect(page.locator('#draw')).to_be_enabled(timeout=20000)
        included = buttons.evaluate_all(
            "buttons=>buttons.map(button=>button.getAttribute('aria-pressed')==='true')")
        assert [i for i, chosen in enumerate(included) if chosen] == [0, count - 1]
        expected = page.evaluate("""async ([flags, opening]) => {
            const file = document.querySelector('#file').files[0];
            const options = {group:true, foregroundFirst:true, groupStyle:'heads', portraitFraming:'head',
                tracePairEyes:true, tracePairSmiles:true, inwardContours:true,
                portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')};
            const {faceBoxes} = await GuestPhoto.fromFile(file, options);
            const groupFaces = faceBoxes.map((box,i)=>({...box,included:flags[i]}));
            const pair = await GuestPhoto.fromFile(file, {...options,groupFaces});
            return GuestInwardPortrait.plan(pair.inwardContours, opening, {keepScale:true}).text;
        }""", [included, device.status['theta']])
        assert device.started == len(device.uploads) == 1 and not device.calls
        submit(page, device)
        assert device.staged == expected, 'The submitted pair must contain the two faces still selected.'


def three_faces(browser, assets, source):
    ordinary_group(browser, assets, source, count=3)
    device = simulated_mini(assets)
    with phone(browser, device) as page:
        open_photo(page, source, style='quiet-engraved')
        preview(page)
        expect(page.locator('#effect')).to_contain_text('all three faces')
        groups = page.evaluate("""async () => {
            const file = document.querySelector('#file').files[0];
            const get = diameter => GuestPhoto.fromFile(file,{group:true,foregroundFirst:true,
                groupStyle:'heads',portraitFraming:'head',inwardContours:true,portraitDiameterGrooves:diameter});
            const smaller = await get(await GuestCenterRoutes.photoDiameterGrooves('full'));
            const wider = await get(95);
            return [smaller,wider].map(q=>({style:q.groupStyle, visits:q.inwardContours, larger:q.largerFaceContours}));
        }""")
        assert groups[0]['style'] == 'faces' and groups[1]['style'] == 'heads'
        assert len(groups[0]['visits']) == 6 and len(groups[1]['visits']) == 3
        large = groups[0]['larger']
        assert len(large) == 6 and not groups[1].get('larger')
        expect(page.get_by_label('Give smaller faces more room')).not_to_be_checked()
        path = submit(page, device)
        actual = cKDTree(sample_walk(path, .0005) * RADIUS_MM)
        centers = []
        for i,tour in enumerate(groups[0]['visits']):
            points = RADIUS_MM * np.asarray(tour)
            assert actual.query(points)[0].max() < .14
            if i < 3:
                assert min(np.ptp(points, axis=0)) > 6 * 5.32
                centers.append(np.mean(points, axis=0))
        assert min(np.linalg.norm(a-b) for i,a in enumerate(centers) for b in centers[:i]) > 7 * 5.32
        # Exercise the real serializer just below and above the Mini's file
        # limit. The portable planner normally splits two rows earlier.
        sizes = page.evaluate("""() => {
            const stroke=OasisRingPlanner.portraitStroke, sizes=[];
            try {
                for(const n of [11998,11999,12000,12001]){
                    OasisRingPlanner.portraitStroke=()=>Array.from({length:n},(_,i)=>
                        [-Math.PI/2, (n-i)%2 ? 1 : .9]);
                    try{
                        const r=GuestInwardPortrait.plan([[[0,.2],[.1,.3],[.1,.2]]],-Math.PI/2);
                        sizes.push([r.path.length,r.path.at(-1)[1]]);
                    }catch(error){sizes.push(error.message);}
                }
            } finally {OasisRingPlanner.portraitStroke=stroke;}
            return sizes;
        }""")
        assert sizes[:3] == [[11998,1],[11999,1],[12000,1]] and 'too many lines' in sizes[3]

    device = simulated_mini(assets)
    with phone(browser, device) as page:
        open_photo(page, source, style='quiet-engraved')
        preview(page)
        option = page.get_by_label('Give smaller faces more room')
        # An oversized alternate cannot replace the current drawing. The
        # original sizes remain usable at the same opening and with the same crop.
        page.evaluate("""() => {
            window.originalStroke=OasisRingPlanner.portraitStroke;
            OasisRingPlanner.portraitStroke=()=>Array.from({length:12001},(_,i)=>
                [-Math.PI/2, i%2 ? .9 : 1]);
        }""")
        option.check()
        expect(page.locator('#error')).to_contain_text('Uncheck Give smaller faces more room')
        expect(page.locator('#draw')).to_be_disabled()
        assert not device.uploads
        page.evaluate('() => {OasisRingPlanner.portraitStroke=window.originalStroke;}')
        option.uncheck()
        expect(page.locator('#draw')).to_be_enabled()
        option.check()
        expect(page.locator('#draw')).to_be_enabled()
        page.locator('#photoName').fill('Family')
        expect(option).to_be_hidden()
        preview(page)
        page.locator('#photoName').fill('')
        preview(page)
        expect(option).to_be_checked()
        enlarged = submit(page, device)
        actual = cKDTree(sample_walk(enlarged, .0005) * RADIUS_MM)
        for line in large:
            assert actual.query(RADIUS_MM * np.asarray(line))[0].max() < .14
        # A uniform scale and translation keep every facial feature and tilt.
        scales = []
        for original, wider in zip(groups[0]['visits'], large):
            before, after = np.asarray(original), np.asarray(wider)
            scale = np.ptp(after[:, 0]) / np.ptp(before[:, 0])
            assert np.max(np.abs((after-after[0]) - scale*(before-before[0]))) < 1e-8
            scales.append(scale)
        assert np.allclose(sorted(scales[:3]), sorted(scales[3:]))
        assert np.allclose(sorted(scales[:3]), [1, 1.186, 1.230], atol=.002)


    # The lower bridge must remain a separate, opt-in visit for this crowded
    # eye. Previously kept and unchecked groups retain their complete noses.
    device = simulated_mini(assets)
    with phone(browser, device) as page:
        open_photo(page, source, style='quiet-engraved')
        preview(page)
        enlarge = page.get_by_label('Give smaller faces more room')
        separate = page.get_by_label('Leave space between the eye and nose')
        expect(separate).to_be_hidden()
        enlarge.check()
        expect(separate).to_be_visible()
        separate.check()
        expect(page.locator('#draw')).to_be_enabled()
        expected = page.evaluate("""async () => {
            const f=document.querySelector('#file').files[0];
            const r=await GuestPhoto.fromFile(f,{group:true,foregroundFirst:true,
                groupStyle:'heads',portraitFraming:'head',inwardContours:true,separateCrowdedEyes:true,
                portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
            return r.largerFaceContours;
        }""")
        assert len(expected) == len(large)+1
        retained = [line for line in large if line in expected]
        assert len(retained) == len(large)-1
        enlarge.uncheck()
        expect(separate).to_be_hidden()
        expect(page.locator('#draw')).to_be_enabled()
        enlarge.check()
        expect(separate).to_be_checked()
        expect(page.locator('#draw')).to_be_enabled()
        spaced = submit(page, device)
        actual = cKDTree(sample_walk(spaced, .0005) * RADIUS_MM)
        assert max(actual.query(np.asarray(line)*RADIUS_MM)[0].max() for line in expected) < .14
        assert not np.array_equal(spaced, enlarged)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for source in ('boardwalk', 'redwoods', 'restaurant'):
        cli.add_argument(source, type=Path)
    args = cli.parse_args()
    with TemporaryDirectory() as temp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        assets = Path(temp)
        build_guest_web_assets(ROOT / 'web', assets, mini_only=True)
        for source in (args.boardwalk, args.redwoods):
            pair_geometry(browser, assets, source)
            deselect_to_solo(browser, assets, source)
            print(f'{source.name}: both head outlines and facial features fit the ordinary pair; one selection matches Solo.', flush=True)
        busy_named_pair(browser, assets, args.boardwalk)
        three_faces(browser, assets, args.restaurant)
        pick_two_from_group(browser, assets, args.restaurant, args.boardwalk)
        print('Named pair and changed face selection held while busy and submitted once at the final dock.')


if __name__ == '__main__':
    main()
