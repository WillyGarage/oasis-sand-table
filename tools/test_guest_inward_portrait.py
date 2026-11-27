"""Select a face from a real group photo on two phones and exercise the Mini's inward drawing.

python3 tools/test_guest_inward_portrait.py GROUP.jpg --face 2
python3 tools/test_guest_inward_portrait.py captures/family-source/nov21/redwood-pair.jpg --redwoods-features
"""
import argparse
from io import StringIO
from itertools import product
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from check_ring_scene import sample_walk
from test_guest_center import FramedMini, ORIGIN, ROOT, DOCK
from mini_portrait_timing import elapsed_seconds
from wide_portrait import chromium


def phone(browser, device):
    page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
    def serve(route):
        assert route.request.url.startswith(ORIGIN + '/')
        return device.handle(route)
    page.context.route('**/*', serve)
    page.goto(ORIGIN + '/lib/guest.html')
    expect(page.locator('#previewButton')).to_be_enabled()
    return page


def preview(page):
    page.locator('#previewButton').click()
    expect(page.locator('#draw')).to_be_enabled(timeout=20000)
    expect(page.locator('#draw')).to_have_text('Draw this inward portrait')


def choose(page, photo, face):
    page.get_by_role('button', name='Photo', exact=True).click()
    page.locator('#photoTarget').select_option('full')
    style = page.locator('#inwardPortrait')
    expect(style).to_have_value('standard')
    page.locator('#photoName').fill('Test')
    expect(style).to_be_visible()
    page.locator('#photoName').fill('')
    page.locator('#photoMode').select_option('group')
    expect(style).to_be_hidden()
    page.locator('#photoMode').select_option('one')
    page.locator('#file').set_input_files(photo)
    style.select_option('inward')
    preview(page)
    assert page.locator('#faceBoxes button').count() >= 2
    page.locator('#faceBoxes button').nth(face).click()
    expect(page.locator('#draw')).to_be_enabled(timeout=20000)


def checked_route(text, opening):
    path = np.loadtxt(StringIO(text))
    assert 2 <= len(path) <= 12000 and np.isfinite(path).all()
    assert abs(np.diff(path[:, 0])).max() <= .0551 and 0 <= path[:, 1].min() <= path[:, 1].max() == 1
    assert abs(path[0, 0] - opening) < .00001 and abs(math.remainder(path[-1, 0]-DOCK[0], math.tau)) < .00001
    assert path[0, 1] == path[-1, 1] == 1
    return path


def distance_to_stroke(point, stroke):
    start, direction = stroke[:-1], np.diff(stroke, axis=0)
    along = np.clip(((point - start) * direction).sum(axis=1) /
                    np.maximum((direction * direction).sum(axis=1), 1e-12), 0, 1)
    return np.linalg.norm(start + along[:, None] * direction - point, axis=1).min()


def check_rim_letters(page, path, name):
    letters = page.evaluate('n => GuestLettering.rimName(n, 5.32/114.03).strokes', name)
    xy = 114.03 * path[:, 1, None] * np.column_stack((np.cos(path[:, 0]), np.sin(path[:, 0])))
    for letter in letters:
        stroke = np.array(letter['path']) * 114.03
        # Find one uninterrupted visit to this letter. The background spiral
        # also passes through its bounding box, but never traces the glyph.
        close = np.zeros(len(xy), dtype=bool)
        for a, b in zip(stroke[:-1], stroke[1:]):
            edge = b - a
            along = np.clip(((xy - a) * edge).sum(axis=1) / max(edge @ edge, 1e-12), 0, 1)
            close |= np.linalg.norm(xy - a - along[:, None] * edge, axis=1) < .18
        hits = np.flatnonzero(close)
        visit = max(np.split(hits, np.flatnonzero(np.diff(hits) != 1) + 1), key=len)
        assert len(visit) > 1 and max(distance_to_stroke(p, xy[visit]) for p in stroke) < .18


def busy_preview(browser, assets, photo, face, name, style):
    device = FramedMini(assets)
    device.status.update(theta=1136.21890639, vmax=400, vj=200, acc=200, accc=2000)
    with phone(browser, device) as host, phone(browser, device) as guest:
        choose(host, photo, face)
        host.locator('#draw').click()
        expect(host.locator('#message')).to_contain_text('started')
        opening = device.status['theta']
        guest.get_by_role('button', name='Photo', exact=True).click()
        guest.locator('#photoTarget').select_option('full')
        guest.locator('#file').set_input_files(photo)
        guest.locator('#inwardPortrait').select_option('inward')
        guest.locator('#previewButton').click()
        heading = guest.locator('#previewHeading')
        waiting = 'Portrait preview on this phone'
        expect(heading).to_have_text(waiting, timeout=20000)
        guest.locator('#faceBoxes button').nth(face).click()
        expect(heading).to_have_text(waiting, timeout=20000)
        guest.locator('#inwardPortrait').select_option(style)
        guest.locator('#photoName').fill(name)
        guest.locator('#previewButton').click()
        expect(heading).to_have_text(waiting, timeout=20000)
        expect(guest.locator('#effect')).to_contain_text(name, ignore_case=True)
        expect(guest.locator('#effect')).to_contain_text('min from start to finish')
        draft = guest.locator('#drawing').evaluate('canvas => canvas.toDataURL()')
        device.revision += 1
        device.pending = True
        expect(guest.locator('#status')).to_contain_text('Drawing in the sand', timeout=7500)
        assert guest.locator('#drawing').evaluate('canvas => canvas.toDataURL()') == draft
        expect(guest.locator('#draw')).to_be_disabled()
        expect(guest.locator('#resumeCenter')).to_be_hidden()
        assert len(device.uploads) == device.started == 1 and not device.calls

        # Finish at the first phone's actual signed endpoint. The second
        # phone keeps the face, style and letters but must rebuild its route.
        device.finish()
        device.pending = False
        dock = device.status['theta']
        assert abs(dock-opening) > 1
        expect(guest.locator('#draw')).to_be_enabled(timeout=20000)
        expect(guest.locator('#faceBoxes button').nth(face)).to_have_attribute('aria-pressed', 'true')
        expected = guest.evaluate("""async ([face, name, theta, quietFace]) => {
            const file = document.querySelector('#file').files[0];
            const photo = await GuestPhoto.fromFile(file, {face, portraitFraming:'head', inwardContours:true,
                portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
            return (await GuestInwardPortrait.namedPlan(photo.inwardContours.concat(photo.inwardHair), theta, name, {quietFace})).text;
        }""", [face, name, dock, style == "quiet-engraved"])
        assert len(device.uploads) == device.started == 1
        guest.locator('#draw').click()
        expect(guest.locator('#message')).to_contain_text('started')
        assert device.staged == expected
        checked_route(device.staged, dock)

        # Previewing again while this drawing runs is reversible. Editing a
        # field and then leaving the tab must cancel the automatic rebuild.
        guest.locator('#previewButton').click()
        expect(heading).to_have_text(waiting, timeout=20000)
        guest.locator('#photoName').fill('')
        expect(heading).not_to_have_text(waiting)
        guest.locator('#previewButton').click()
        expect(heading).to_have_text(waiting, timeout=20000)
        guest.locator('[data-tab="request"]').click()
        device.finish()
        expect(guest.locator('#status')).to_have_text('Table ready', timeout=7500)
        expect(guest.locator('#draw')).to_be_disabled()
        assert len(device.uploads) == device.started == 2 and not device.calls

        preview(host)
        device.lose_upload_reply = True
        host.locator('#draw').click()
        expect(host.locator('#resumeCenter')).to_be_visible(timeout=7500)
        guest.locator('[data-tab="photo"]').click()
        guest.locator('#previewButton').click()
        expect(heading).to_have_text(waiting, timeout=20000)
        expect(guest.locator('#draw')).to_be_disabled()
        expect(guest.locator('#resumeCenter')).to_be_hidden()
        assert len(device.uploads) == 3 and device.started == 2
        host.locator('#resumeCenter').click()
        expect(host.locator('#message')).to_contain_text('started')
        device.finish()
        expect(guest.locator('#draw')).to_be_enabled(timeout=20000)
        assert len(device.uploads) == device.started == 3 and not device.calls


def check_redwoods_features(page):
    # Three independent locations where the teeth meet the lower lip in the
    # second face of the original redwoods photograph, at Mini size in mm.
    lower_lip = np.array([[16.2, -73.1], [30.6, -71.1], [43.1, -63.6]])
    contours = page.evaluate("""async () => {
        const file = document.querySelector('#file').files[0];
        const options = {face: 1, portraitFraming: 'head',
                         portraitDiameterGrooves: await GuestCenterRoutes.photoDiameterGrooves('full')};
        const ordinary = await GuestPhoto.fromFile(file, options);
        const inward = await GuestPhoto.fromFile(file, {...options, inwardContours: true});
        if (JSON.stringify(ordinary.points) !== JSON.stringify(inward.points))
            throw Error('The inward preview changed the ordinary portrait.');
        return inward.inwardContours;
    }""")
    scale = (114.03 - 5.32 / 2) / max(np.linalg.norm(line, axis=1).max() for line in contours)
    # The long-hair crop moves the face rigidly on the tray. Express the
    # current strokes at the original crop's origin for the photo samples below.
    crop_translation_mm = np.array([-15.87113296, 19.72469024])
    lines = [np.asarray(line) * scale - crop_translation_mm for line in contours]
    # A separate mouth stroke spans both corners and stays below the nose.
    mouths = [line for line in lines if line[:, 1].max() < -45 and np.ptp(line[:, 0]) > 45]
    assert len(mouths) == 1, 'Expected the smile to be reachable independently from the inward spiral.'
    mouth = np.vstack([mouths[0], mouths[0][0]])
    for point in lower_lip:
        assert distance_to_stroke(point, mouth) < 1.5

    # The upper strokes and corners already followed the source. The lower
    # samples are from the full-resolution original, independent of the phone
    # fit. Her eye on the viewer's left is the narrower one.
    eyes = [
        ([[-21.99,-21.02], [-19.31,-17.42], [-12.04,-14.29], [-3.87,-15.65]],
         [[-17.25,-20.39], [-15.42,-19.92], [-13.64,-19.26], [-11.76,-18.97], [-9.96,-18.37], [-8.21,-17.65]]),
        ([[25.51,-3.33], [31.34,2.57], [37.98,6.16], [45.86,5.68]],
         [[32.16,-4.62], [34.20,-3.71], [36.26,-2.88], [38.24,-1.84], [40.40,-1.22], [42.46,-.39]]),
    ]
    for upper, photo_lower in eyes:
        matching = [line for line in lines if len(line) >= 4 and np.allclose(line[:4], upper, atol=.15)]
        assert len(matching) == 1, 'Lost the original upper lid or opposite corner.'
        lower = np.vstack([matching[0][3:], matching[0][0]])
        errors = [distance_to_stroke(point, lower) for point in photo_lower]
        assert np.median(errors) < .5 and max(errors) < 1, 'The lower lid misses the photographed eye.'


def check_photographed_part(browser, assets, photo, opening, usual):
    device = FramedMini(assets)
    device.status['theta'] = opening
    with phone(browser, device) as page:
        choose(page, photo, 1)
        expect(page.locator('#photoPart')).to_be_hidden()
        page.locator('#inwardPortrait').select_option('quiet-engraved')
        preview(page)
        part = page.get_by_role('checkbox', name='Follow the part in the hair')
        expect(part).not_to_be_checked()
        # Anchor samples on the visible part in the original redwoods crop, in
        # Mini millimeters. Only the hair strokes can satisfy this comparison.
        expected = page.evaluate("""async opening => {
            const file=document.querySelector('#file').files[0];
            const r=await GuestPhoto.fromFile(file,{face:1,portraitFraming:'head',inwardContours:true,
                portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
            return {face:r.inwardContours,before:r.inwardHair,after:r.partedHair,
                route:GuestInwardPortrait.plan(r.inwardContours.concat(r.partedHair),opening,{quietFace:true}).text};
        }""", opening)
        scale = (114.03 - 5.32 / 2) / max(np.linalg.norm(l, axis=1).max() for l in expected['face'])
        for point in ([-16.24, 75.99], [-15.66, 79.47], [-14.5, 83.53]):
            def gap(key):
                return min(distance_to_stroke(point, np.asarray(line)*scale) for line in expected[key])
            assert gap('before') > 7 and gap('after') < 1.5
        for selected, output in ((True, expected['route']), (False, usual)):
            part.set_checked(selected)
            expect(page.locator('#draw')).to_be_enabled()
            page.locator('#draw').click()
            expect(page.locator('#message')).to_contain_text('started')
            checked_route(device.staged, opening)
            assert device.staged == output
            device.finish()
            device.status['theta'] = opening
            if selected:
                # The next guest recreates the same selection at the same dock.
                page.reload()
                choose(page, photo, 1)
                page.locator('#inwardPortrait').select_option('quiet-engraved')
                preview(page)
        assert device.started == 2


def check_closer_redwoods_turns(ordinary_text, quiet_text):
    # These 20 mm sections cross blank skin in the registered group photograph.
    # No portrait stroke or access trip should be counted as a rake line here.
    sections = [([-18.590, 39.669], [.61624, .78756]), ([-6.880, 17.712], [.95298, .30303])]
    walks = [sample_walk(np.loadtxt(StringIO(text)), .001) * 114.03 for text in (ordinary_text, quiet_text)]
    for center, normal in sections:
        spacing = []
        for walk in walks:
            relative = walk - center
            along = relative @ normal
            across = relative @ [-normal[1], normal[0]]
            i = np.flatnonzero((across[:-1] > 0) != (across[1:] > 0))
            hits = along[i] - np.diff(along)[i] * across[i] / np.diff(across)[i]
            stations = np.sort(hits[np.abs(hits) < 10])
            assert len(stations) >= 4
            spacing.append(np.median(np.diff(stations)))
        assert 2.8 < spacing[0] < 4 and .55 < spacing[1] / spacing[0] < .65


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('photo', type=Path)
    cli.add_argument('--face', type=int, default=2, help='One-based face index')
    cli.add_argument('--name', default='L', help='A name or initial that fits below the selected face')
    cli.add_argument('--redwoods-features', '--redwoods-smile', action='store_true',
                     help='Check the photographed smile and eyelids on face 2 of redwood-pair.jpg')
    args = cli.parse_args()
    opening = 1136.21890639  # A real rim dock away from the six-o’clock exit.
    with TemporaryDirectory() as temp, sync_playwright() as w, w.chromium.launch(executable_path=chromium(w, None)) as browser:
        assets = Path(temp)
        build_guest_web_assets(ROOT / 'web', assets, mini_only=True)
        device = FramedMini(assets)
        device.status.update(theta=opening, vmax=400, vj=200, acc=200, accc=2000)
        routes = {}
        styles = ('inward', 'engraved', 'quiet-engraved')
        for name, style in product(('', args.name), styles):
            with phone(browser, device) as page:
                choose(page, args.photo, args.face-1)
                page.locator('#inwardPortrait').select_option(style)
                if name:
                    page.locator('#photoName').fill('A' * 40)
                    page.locator('#previewButton').click()
                    expect(page.locator('#error')).to_contain_text('initials')
                    expect(page.locator('#draw')).to_be_disabled()
                    expect(page.locator('#inwardPortrait')).to_have_value(style)
                    page.locator('#photoName').fill(name)
                preview(page)
                effect = page.locator('#effect').inner_text()
                on_rim = 'follows the lower rim' in effect
                if name:
                    assert ('“' + name + '”').casefold() in page.locator('#effect').inner_text().casefold()
                    if args.redwoods_features and name.upper() in ('LEK', 'L'):
                        assert on_rim
                if args.redwoods_features and style == 'engraved' and not name:
                    assert args.face == 2
                    check_redwoods_features(page)
                if style == 'engraved':
                    # An upload can reach the Mini even when the response does not reach the phone.
                    device.lose_upload_reply = True
                page.locator('#draw').click()
                if style == 'engraved':
                    expect(page.locator('#resumeCenter')).to_be_visible()
                    assert device.status['receipt']['state'] == 'staged'
                    with phone(browser, device) as guest:
                        expect(guest.locator('#resumeCenter')).to_be_visible()
                        guest.locator('#resumeCenter').click()
                        expect(guest.locator('#message')).to_contain_text('started')
                else:
                    expect(page.locator('#message')).to_contain_text('started')
                routes[(style, name)] = device.staged
                path = checked_route(device.staged, opening)
                minutes = max(1, round(elapsed_seconds(path, device.status)[-1] / 60))
                assert f'About {minutes} min from start to finish.' in effect
                if on_rim:
                    check_rim_letters(page, path, name)
                device.finish()
                page.reload()
                expect(page.locator('#previewHeading')).to_have_text('Photo on the sand')
                device.status['theta'] = opening
        assert (len(device.uploads),device.started) == (6,6)
        for style in styles:
            assert routes[(style, '')] != routes[(style, args.name)]

        if args.redwoods_features:
            check_closer_redwoods_turns(routes[('engraved', '')], routes[('quiet-engraved', '')])
            check_photographed_part(browser, assets, args.photo, opening, routes[('quiet-engraved', '')])
        print('Verified three inward styles with and without a name, the selected face, and recovery after a lost reply.')
        for style in ('engraved', 'quiet-engraved'):
            busy_preview(browser, assets, args.photo, args.face-1, args.name, style)
        print('A second phone kept its local draft and drew the selected face once from the actual finishing dock.')
        for name, route in routes.items():
            print(name, len(route.splitlines()), 'positions')


if __name__ == '__main__':
    main()
