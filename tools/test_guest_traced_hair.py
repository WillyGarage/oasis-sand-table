"""Exercise optional laptop tracing from the normal phone photo preview, without a table."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, choose, drawing_files, open_room, room
from test_ring_guest_border import MOBILE, save
from test_ring_shadows import ready
from wide_portrait import chromium


def select_face(phone, face):
    source = phone.locator('#portraitSource')
    if not source.evaluate('el=>el.open'):
        source.locator('summary').click()
    phone.locator('#faceBoxes button').nth(face - 1).click()
    ready(phone)


def preview(phone, photo, face):
    phone.locator('#portraitArea').select_option('wide')
    phone.locator('#portraitFile').set_input_files(photo)
    phone.locator('#portraitSubmit').click()
    ready(phone)
    if face is not None:
        select_face(phone, face)


def exercise(browser, ordinary_url, url, photo, expected, evidence=None, face=None):
    report = json.loads((expected[0].parent/'result.json').read_text())
    nose, brows = 'nose' in report, 'brows' in report
    smile, eyes = 'smile' in report, 'eyes' in report
    woodcut = 'woodcut' in report
    flowing_hair = 'flowingHair' in report
    long_hair = 'longHair' in report
    labels = [label for label, present in (
        ('hair', report['method'] == 'measured-hair'), ('nose', report.get('nose', {}).get('applied')),
        ('one eyebrow' if report.get('brows', {}).get('count') == 1 else 'eyebrows', report.get('brows', {}).get('applied')),
        ('smile', report.get('smile', {}).get('applied')),
        ('moustache', report.get('smile', {}).get('moustache')),
        ('eyes', report.get('eyes', {}).get('applied')),
    ) if present]
    features = ', '.join(labels[:-1]) + ' and ' + labels[-1] if len(labels) > 1 else ''.join(labels)
    with browser.new_page(**MOBILE) as phone:
        open_room(phone, ordinary_url, 'photos')
        preview(phone, photo, face)
        expect(phone.locator('#portraitHair')).to_be_hidden()
        expect(phone.locator('#photoTraceSubmit')).to_be_hidden()
        original = drawing_files(phone, '#downloads')

    with browser.new_page(**MOBILE) as phone, browser.new_page(**MOBILE) as guest:
        sent = []
        endpoint = url + '/api/portrait'
        phone.on('request', lambda r: sent.append(r) if r.url == endpoint else None)
        if not (nose and brows and smile and eyes and woodcut and long_hair and flowing_hair):
            # Earlier rooms advertise only the features they can accept.
            def earlier_service(route):
                response = route.fetch()
                body = response.body()
                for marker, supported in ((b' data-nose="1"', nose), (b' data-brows="1"', brows),
                                          (b' data-smile="1"', smile), (b' data-eyes="1"', eyes),
                                          (b' data-woodcut="1"', woodcut), (b' data-long-hair="1"', long_hair),
                                          (b' data-flowing-hair="1"', flowing_hair)):
                    if not supported:
                        body = body.replace(marker, b'')
                route.fulfill(response=response, body=body)
            phone.route(url+'/garden', earlier_service)
        open_room(phone, url, 'photos')
        preview(phone, photo, face)
        assert not sent
        hair, note = phone.locator('#portraitHair'), phone.locator('#portraitHairNote')
        expect(note).to_contain_text('garden laptop')
        phone.route(endpoint, lambda r: r.fulfill(status=429), times=1)
        hair.click()
        expect(note).to_contain_text('try again')
        assert drawing_files(phone, '#downloads') == original

        # A guest can reframe a different drawing while the laptop is busy.
        # Its late reply must never replace the new preview.
        held = []
        phone.route(endpoint, lambda route: held.append(route), times=1)
        with phone.expect_request(endpoint):
            hair.click()
        phone.locator('#soloStyle').select_option('head')
        ready(phone)
        close_up = drawing_files(phone, '#downloads')
        assert close_up != original
        held[0].fulfill(status=503)
        expect(hair).to_be_hidden()
        assert drawing_files(phone, '#downloads') == close_up
        phone.locator('#soloStyle').select_option('auto')
        ready(phone)

        action = hair
        if nose or brows or smile or eyes:
            # A single explicit tap performs the local crop and traces the same face.
            phone.locator('#portraitFile').set_input_files([])
            phone.locator('#portraitFile').set_input_files(photo)
            action = phone.locator('#photoTraceSubmit')
            phone.locator('#photoCaption').fill('Test')
            expect(action).to_be_hidden()
            phone.locator('#photoCaption').fill('')
            expect(action).to_be_enabled()
            if face is not None:
                action.click()
                ready(phone)
                assert len(sent) == 2  # Choose a person before sending a group photo.
                select_face(phone, face)
                action = hair
        with phone.expect_response(lambda r: r.url == endpoint, timeout=125000) as pending:
            action.click()
        response = pending.value
        assert response.ok, response.status
        if features:
            expect(hair).to_have_text('Show first drawing')
            expect(note).to_contain_text('the ' + features + ' traced')
        else:
            expect(hair).to_be_disabled()
            expect(note).to_contain_text('Showing the first drawing')
        assert len(sent) == 3 and sent[-1].method == 'POST'
        request = json.loads(sent[-1].headers['x-oasis-portrait'])
        assert request['face'] == (None if face is None else face - 1) and request['layout'] == 'garden'
        assert ('traceNose' in request) is nose and request.get('traceNose', False) is nose
        assert ('traceBrows' in request) is brows and request.get('traceBrows', False) is brows
        assert ('traceSmile' in request) is smile and request.get('traceSmile', False) is smile
        assert ('traceEyes' in request) is eyes and request.get('traceEyes', False) is eyes
        assert ('hairWoodcut' in request) is woodcut and request.get('hairWoodcut', False) is woodcut
        assert ('flowingHair' in request) is flowing_hair
        assert ('longHair' in request) is long_hair
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            phone.locator('.sand-display').evaluate("el=>el.scrollIntoView({behavior:'instant',block:'start'})")
            phone.screenshot(path=evidence/'guest-preview.png')
        traced = drawing_files(phone, '#downloads')
        actual = [data for _, data in traced]
        reference = [f.read_bytes() for f in expected]
        if evidence:
            for name, data in traced:
                (evidence/name).write_bytes(data)
        assert actual == reference, (
            'Phone and laptop drawing differ', hashlib.sha256(b''.join(actual)).hexdigest(),
            hashlib.sha256(b''.join(reference)).hexdigest()
        )
        if features:
            assert traced != original
            hair.click()
            assert drawing_files(phone, '#downloads') == original
            hair.click()
            assert drawing_files(phone, '#downloads') == traced
        else:
            assert traced == original
        alternate = phone.locator('#portraitWoodcut')
        if report.get('woodcut', {}).get('applied'):
            expect(alternate).to_have_text('Show woodcut hair')
            alternate.click()
            cut = drawing_files(phone, '#downloads')
            folder = expected[0].parent / 'hair-woodcut'
            files = json.loads((folder/'result.json').read_text())['files']
            assert [data for _, data in cut] == [(folder/f).read_bytes() for f in files]
            assert cut != traced
            expect(note).to_contain_text(str(report['woodcut']['strokes'])+' strokes')
            expect(alternate).to_have_text('Show open engraving')
            if evidence:
                phone.locator('.sand-display').scroll_into_view_if_needed()
                phone.screenshot(path=evidence/'guest-woodcut.png')
            alternate.click()
            assert drawing_files(phone, '#downloads') == traced
            alternate.click()
            traced = cut
        else:
            expect(alternate).to_be_hidden()
        full = phone.locator('#portraitLongHair')
        if report.get('longHair', {}).get('applied'):
            full.click()
            wide = drawing_files(phone, '#downloads')
            folder = expected[0].parent / 'full-hair'
            parts = json.loads((folder / 'result.json').read_text())['files']
            assert [data for _, data in wide] == [(folder/f).read_bytes() for f in parts]
            expect(full).to_have_text('Show close-up')
            full.click()
            assert [data for _, data in drawing_files(phone, '#downloads')] == reference
            full.click()
            if evidence:
                phone.locator('.sand-display').scroll_into_view_if_needed()
                phone.screenshot(path=evidence/'guest-full-hair.png')
            traced = wide
        elif full.count():
            expect(full).to_be_hidden()
        flowing = phone.locator('#portraitFlowing')
        if report.get('flowingHair', {}).get('applied'):
            flowing.click()
            curves = drawing_files(phone, '#downloads')
            folder = expected[0].parent / 'flowing-hair'
            files = json.loads((folder/'result.json').read_text())['files']
            assert [data for _, data in curves] == [(folder/f).read_bytes() for f in files]
            assert curves != original and curves != traced
            expect(note).to_contain_text('follow the direction')
            expect(flowing).to_have_text('Show open engraving')
            flowing.click()
            assert [data for _, data in drawing_files(phone, '#downloads')] == reference
            flowing.click()
            if evidence:
                phone.locator('.sand-display').scroll_into_view_if_needed()
                phone.screenshot(path=evidence/'guest-flowing.png')
            traced = curves
        elif flowing.count():
            expect(flowing).to_be_hidden()
        assert len(sent) == 3
        saved, _ = save(phone, url + API)
        assert [f['text'].encode() for f in saved['motion']['files']] == [data for _, data in traced]
        open_room(guest, url, 'photos')
        choose(guest, 'zone', 'center')
        assert drawing_files(guest, '#roomFiles') == traced


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('photo', type=Path, help='Source photograph for the expected wide-center drawing')
    parser.add_argument('expected', type=Path, nargs='+', help='Corresponding laptop .thr files in order')
    parser.add_argument('--evidence', type=Path, help='Save the phone preview and actual downloads')
    parser.add_argument('--face', type=int, help='Choose this numbered person from a group photo on both phones')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        with (room(args.gallery, folder/'ordinary.db') as ordinary,
              room(args.gallery, folder/'tracing.db', photo_portraits=True) as tracing,
              sync_playwright() as pw):
            with pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
                exercise(browser, ordinary, tracing, args.photo, args.expected, args.evidence, args.face)
    print('Guest photo tracing matched the host. The first drawing, retry and cross-phone save passed.')
