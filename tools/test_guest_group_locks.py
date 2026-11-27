"""Check the opt-in group hair request, cached comparisons and second-phone recall.

Both galleries should be the same wide-table fit. The earlier editor offers the
ordinary group engraving. Each source is a local photo with two or three selected
foreground faces. The local portrait worker handles every unmocked request.
"""
import argparse
import base64
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import choose, drawing_files, room
from test_guest_group_engraving import open_photo_room, preview
from test_ring_group_shadows import MOBILE
from test_ring_guest_border import save
from wide_portrait import chromium


def prepared(phone, url, photo):
    calls = []
    endpoint = url + '/api/portrait'
    phone.on('request', lambda r: calls.append(json.loads(r.headers['x-oasis-portrait'])) if r.url == endpoint else None)
    open_photo_room(phone, url, 'garden')
    preview(phone, photo)
    phone.evaluate("""url=>{
      const fetch=window.fetch;
      window.fetch=async(...args)=>{
        const reply=await fetch(...args);
        if(reply.ok && reply.url===url)window.latestGroup=reply.clone().json();
        return reply;
      };
    }""", endpoint)
    first = drawing_files(phone, '#downloads')
    action = phone.locator('#portraitHair')
    expect(action).to_have_text('Preview group engraving on garden laptop')
    assert not calls and not phone.locator('#portraitLongHair').is_visible()
    selected = phone.evaluate("""async () => {
      const scan=await GuestPhoto.inspectSeatPhoto(document.querySelector('#portraitFile').files[0]);
      const boxes=[...document.querySelectorAll('#faceBoxes button')];
      return scan.detectedFaces.filter((_,i)=>boxes[i].getAttribute('aria-pressed')==='true');
    }""")
    with phone.expect_response(lambda r: r.url == endpoint, timeout=150000) as received:
        action.click()
    assert received.value.status == 200, received.value.status
    expect(action).to_have_text('Show first drawing')
    assert len(calls) == 1 and set(calls[0]) == {'layout', 'faces', 'diameterMm', 'grooveMm'}
    assert calls[0]['faces'] == selected
    return first, drawing_files(phone, '#downloads'), calls


def recall(browser, url, files):
    with browser.new_page(**MOBILE) as guest:
        posts = []
        guest.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        open_photo_room(guest, url, 'garden')
        choose(guest, 'zone', 'center')
        assert drawing_files(guest, '#roomFiles') == files and not posts


def changed_photo(browser, url, first_photo, next_photo, ordinary_reply, hair_reply):
    with browser.new_page(**MOBILE) as phone:
        endpoint = url + '/api/portrait'
        phone.route(endpoint, lambda r: r.fulfill(json=ordinary_reply), times=1)
        _, _, calls = prepared(phone, url, first_photo)
        held = []
        phone.route(endpoint, lambda route: held.append(route), times=1)
        with phone.expect_request(endpoint):
            phone.locator('#portraitLongHair').click()
        phone.locator('#portraitFile').set_input_files(next_photo)
        phone.locator('#portraitSubmit').click()
        expect(phone.locator('#portraitHair')).to_have_text('Preview group engraving on garden laptop')
        other = drawing_files(phone, '#downloads')
        held[0].fulfill(json=hair_reply)
        assert drawing_files(phone, '#downloads') == other and len(calls) == 2
        expect(phone.locator('#portraitLongHair')).to_be_hidden()


def check_locks(browser, url, photo, *, refusal=False, evidence=None, expected=None, next_photo=None):
    with browser.new_page(**MOBILE) as phone:
        endpoint = url + '/api/portrait'
        stock, ordinary, calls = prepared(phone, url, photo)
        ordinary_reply = phone.evaluate('window.latestGroup')
        hair, action, note = (phone.locator(s) for s in ('#portraitLongHair', '#portraitHair', '#portraitHairNote'))
        expect(hair).to_have_text('Trace long hair on both sides')
        expect(note).to_contain_text('sends the photo to the garden laptop again')
        action.click()
        assert drawing_files(phone, '#downloads') == stock and len(calls) == 1
        action.click()
        # Neither a busy worker nor a worker that accidentally returned an ordinary
        # drawing with no lock count may replace the already prepared group.
        phone.route(endpoint, lambda r: r.fulfill(status=429), times=1)
        hair.click()
        expect(note).to_contain_text('try again')
        assert drawing_files(phone, '#downloads') == ordinary
        phone.route(endpoint, lambda r: r.fulfill(json=ordinary_reply), times=1)
        hair.click()
        expect(note).to_contain_text('could not confirm the hair strokes')
        assert drawing_files(phone, '#downloads') == ordinary
        with phone.expect_response(lambda r: r.url == endpoint, timeout=150000) as receipt:
            hair.click()
        expected_options = dict(calls[0], groupLocks=True)
        assert len(calls) == 4 and calls[1:] == [expected_options] * 3
        if refusal:
            assert receipt.value.status == 422, receipt.value.status
            expect(note).to_contain_text('could not fit on both sides')
            assert drawing_files(phone, '#downloads') == ordinary
            action.click()
            assert drawing_files(phone, '#downloads') == stock
            action.click()
            final = ordinary
        else:
            assert receipt.value.status == 200, receipt.value.status
            expect(hair).to_have_text('Show group engraving')
            reply = phone.evaluate('window.latestGroup')
            assert reply['method'] == 'group-engraving' and reply['people'] == len(calls[0]['faces'])
            assert type(reply['locks']) is int and reply['locks'] > 0
            if expected:
                assert reply['drawing'] == json.loads(expected.read_text())
            expect(note).to_contain_text(f"{reply['locks']} long hair strokes")
            final = drawing_files(phone, '#downloads')
            assert final != ordinary and final != stock
            if evidence:
                evidence.mkdir(parents=True, exist_ok=True)
                phone.locator('.sand-display').screenshot(path=evidence/'locks.png')
                phone.locator('#portraitHairField').screenshot(path=evidence/'controls.png')
                (evidence/'group.oasisportrait').write_text(json.dumps(reply['drawing']))
                for name, data in final:
                    (evidence/name).write_bytes(data)
            hair.click()
            assert drawing_files(phone, '#downloads') == ordinary
            action.click()
            assert drawing_files(phone, '#downloads') == stock
            hair.click()
        assert drawing_files(phone, '#downloads') == final and len(calls) == 4
        payload, _ = save(phone, url + '/api/garden/garden')
        assert [(f['name'], f['text'].encode()) for f in payload['motion']['files']] == final
        encoded = json.dumps(payload['state'])
        assert all(key not in encoded for key in ('selectedFaces', 'data:image', 'groupLocks', photo.name,
            base64.b64encode(photo.read_bytes()[:48]).decode()))
        recall(browser, url, final)
        if next_photo is not None:
            changed_photo(browser, url, photo, next_photo, ordinary_reply, reply)
        return ordinary, final


@contextmanager
def phones():
    with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        yield browser


def main(args):
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp)/'room.db'
        with room(args.previous, db, photo_portraits=True) as url, phones() as browser, browser.new_page(**MOBILE) as old:
            _, prior, calls = prepared(old, url, args.photo)
            expect(old.locator('#portraitLongHair')).to_be_hidden()
            save(old, url + '/api/garden/garden')
            assert len(calls) == 1
        with room(args.gallery, db, photo_portraits=True) as url, phones() as browser:
            recall(browser, url, prior)
            current_ordinary, _ = check_locks(browser, url, args.photo, evidence=args.evidence,
                                              expected=args.expected, next_photo=args.refusal_photo)
        with room(args.gallery, Path(temp)/'declined.db', photo_portraits=True) as url, phones() as browser:
            check_locks(browser, url, args.refusal_photo, refusal=True)
        # A current phone talking to the previous marker still exposes ordinary
        # group engraving and makes no requests for unsupported hair.
        with room(args.gallery, Path(temp)/'prior-host.db', photo_portraits=True) as url, phones() as browser, browser.new_page(**MOBILE) as phone:
            def older_marker(route):
                response=route.fetch()
                route.fulfill(response=response, body=response.body().replace(b' data-group-locks="1"', b''))
            phone.route('**/garden?*', older_marker)
            _, ordinary, calls = prepared(phone, url, args.photo)
            # Only the host's lock capability differs here. The editor used
            # for the older saved drawing can have a different face tracer.
            assert ordinary == current_ordinary and len(calls) == 1
            expect(phone.locator('#portraitLongHair')).to_be_hidden()
    print('Checked group locks, refusal, a changed photo, previous hosts and drawings, and exact second-phone downloads.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('gallery', 'previous', 'photo', 'refusal_photo'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--expected', type=Path)
    main(parser.parse_args())
