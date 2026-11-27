"""Exercise an optional prepared group through the real private guest room, on two phones.

Pass an editor, a photo with 2–4 selected faces, and optionally a reviewed group
.oasisportrait file. Default foreground selection and explicit inclusion use the
same picker as a guest. No table or external service is contacted.
"""
import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import choose, drawing_files, room
from test_ring_group_shadows import MOBILE, toggle
from test_ring_guest_border import save
from test_ring_shadows import ready
from thrcommon import motion_files_hash
from wide_portrait import chromium


def open_photo_room(phone, url, layout):
    with phone.expect_response(lambda r: r.url == url + '/api/garden/' + layout and r.request.method == 'GET'):
        phone.goto(url + '/garden?layout=' + layout + '#photos')
    expect(phone.locator('meta[name=oasis-room]')).to_have_count(1)


def preview(phone, photo):
    if phone.locator('#portraitArea').is_visible():
        phone.locator('#portraitArea').select_option('wide')
    phone.locator('#portraitMode').select_option('group')
    phone.locator('#portraitFile').set_input_files(photo)
    phone.locator('#portraitSubmit').click()
    ready(phone)


def exercise(browser, url, photo, toggles, expected, refuse, evidence, layout='garden', expected_print=None):
    with browser.new_page(**MOBILE) as phone, browser.new_page(**MOBILE) as guest:
        endpoint = url + '/api/portrait'
        requests = []
        phone.on('request', lambda r: requests.append(r) if r.url == endpoint else None)
        open_photo_room(phone, url, layout)
        preview(phone, photo)
        for index in toggles:
            toggle(phone, index - 1)
        action, note = phone.locator('#portraitHair'), phone.locator('#portraitHairNote')
        expect(action).to_have_text('Preview group engraving on garden laptop')
        expect(note).to_contain_text('Sends this photo to the garden laptop')
        selected = phone.evaluate("""async()=>{
          const scan=await GuestPhoto.inspectSeatPhoto(document.getElementById('portraitFile').files[0]);
          const buttons=[...document.querySelectorAll('#faceBoxes button')];
          return scan.detectedFaces.filter((_,i)=>buttons[i].getAttribute('aria-pressed')==='true');
        }""")
        assert len(selected) in (2, 3, 4)
        original = drawing_files(phone, '#downloads')
        assert not requests
        for style in ('pose', 'faces', 'seats', 'shadows', 'heads'):
            phone.locator('#portraitStyle').select_option(style)
            ready(phone)
            assert action.is_visible() == (style == 'heads')
        assert drawing_files(phone, '#downloads') == original and not requests

        # A busy local server doesn't replace the first drawing. A response to an
        # abandoned selection doesn't replace a later pose, even if it arrives late.
        phone.route(endpoint, lambda route: route.fulfill(status=429), times=1)
        action.click()
        expect(note).to_contain_text('try again')
        assert drawing_files(phone, '#downloads') == original
        held = []
        phone.route(endpoint, lambda route: held.append(route), times=1)
        with phone.expect_request(endpoint):
            action.click()
        phone.locator('#portraitStyle').select_option('pose')
        ready(phone)
        pose = drawing_files(phone, '#downloads')
        held[0].fulfill(status=422)
        assert drawing_files(phone, '#downloads') == pose and not action.is_visible()
        phone.locator('#portraitStyle').select_option('heads')
        ready(phone)
        # Chromium may release an intercepted POST body after the page consumes
        # it. Retain the portable drawing as seen by this test phone instead.
        phone.evaluate("""url=>{
          const fetch=window.fetch;
          window.fetch=async(...args)=>{
            const reply=await fetch(...args);
            if(reply.url===url)window.testGroupReply=reply.clone().json();
            return reply;
          };
        }""", endpoint)
        with phone.expect_response(lambda r: r.url == endpoint, timeout=360000) as receipt:
            action.click()
        response = receipt.value
        request = json.loads(response.request.headers['x-oasis-portrait'])
        assert set(request) == {'layout', 'diameterMm', 'grooveMm', 'faces'} and request['faces'] == selected
        assert response.request.method == 'POST' and len(requests) == 3
        if refuse:
            assert response.status == 422, response.status
            expect(note).to_contain_text('Your first drawing is ready.')
            reviewed = original
        else:
            assert response.ok, response.status
            expect(action).to_have_text('Show first drawing')
            result = phone.evaluate('window.testGroupReply')
            assert result['method'] == 'group-engraving' and result['people'] == len(selected)
            drawing = result['drawing']
            if expected:
                assert drawing == json.loads(expected.read_text()), 'Guest drawing differs from the reviewed group'
            expect(note).to_contain_text(f'{len(selected)} selected faces')
            reviewed = drawing_files(phone, '#downloads')
            assert reviewed != original
            if evidence:
                evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
                phone.locator('.sand-display').screenshot(path=evidence/'phone-preview.png')
                for name, data in reviewed:
                    (evidence/name).write_bytes(data)
            action.click()
            assert drawing_files(phone, '#downloads') == original
            action.click()
        assert drawing_files(phone, '#downloads') == reviewed and len(requests) == 3
        if expected_print is not None:
            assert len(selected) == 2 and not refuse
            action = phone.get_by_role('button', name='Shade with the rake')
            with phone.expect_response(lambda r: r.url == endpoint, timeout=360000) as receipt:
                action.click()
            assert receipt.value.ok
            reply = phone.evaluate('window.testGroupReply')
            assert reply['drawing'] == drawing and reply['rakePrintDrawing'] == json.loads(expected_print.read_text())
            expect(phone.locator('#portraitRake')).to_have_text('Show open engraving')
            printed = drawing_files(phone, '#downloads')
            assert printed != reviewed
            phone.locator('#portraitRake').click()
            assert drawing_files(phone, '#downloads') == reviewed
            phone.locator('#portraitRake').click()
            assert drawing_files(phone, '#downloads') == printed and len(requests) == 4
            reviewed = printed
        payload, _ = save(phone, url + '/api/garden/' + layout)
        actual = payload['motion']['files']
        assert [f['text'].encode() for f in actual] == [data for _, data in reviewed]
        assert all(k not in json.dumps(payload['state']) for k in ('selectedFaces', 'sourceWidth', 'data:image'))
        open_photo_room(guest, url, layout)
        choose(guest, 'zone', 'center')
        assert drawing_files(guest, '#roomFiles') == reviewed
        if len(selected) == 4 and not refuse:
            # A second guest can pick the same four in a different order.
            guest.goto('about:blank')
            open_photo_room(guest, url, layout)
            preview(guest, photo)
            for index in reversed(toggles):
                toggle(guest, index - 1)
            picks = guest.locator('#faceBoxes button')
            first = next(i for i in range(picks.count()) if picks.nth(i).get_attribute('aria-pressed') == 'true')
            toggle(guest, first)
            toggle(guest, first)
            with guest.expect_response(lambda r: r.url == endpoint, timeout=360000) as repeat:
                guest.locator('#portraitHair').click()
            assert repeat.value.ok and json.loads(repeat.value.request.headers['x-oasis-portrait'])['faces'] == selected
            expect(guest.locator('#portraitHair')).to_have_text('Show first drawing')
            assert drawing_files(guest, '#downloads') == reviewed
        return motion_files_hash(actual)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('garden', type=Path)
    parser.add_argument('photo', type=Path)
    parser.add_argument('--toggle', type=int, action='append', default=[], help='Toggle this one-based picker face')
    parser.add_argument('--layout', choices=('garden', 'portrait'), default='garden')
    parser.add_argument('--expected', type=Path, help='Compare the host answer to a reviewed portable group')
    parser.add_argument('--expected-print', type=Path, help='Verify the optional pair print and recall its signed files on a second phone.')
    parser.add_argument('--expect-refusal', action='store_true', help='The selected group cannot fit this center')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp, room(args.garden, Path(temp)/'room.db', photo_portraits=True) as url:
        with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
            signature = exercise(browser, url, args.photo, args.toggle, args.expected, args.expect_refusal, args.evidence, args.layout, args.expected_print)
    print('Saved and recalled the original preview.' if args.expect_refusal else 'Saved and recalled the group engraving.', signature)
