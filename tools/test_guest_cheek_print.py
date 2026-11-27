"""Reopen a guest's selected cheek engraving from a second phone.

python3 tools/test_guest_cheek_print.py GARDEN.html PHOTO.jpg --face 2
"""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, choose, drawing_files, open_room, room
from test_ring_guest_border import MOBILE, save
from test_ring_shadows import ready
from thrcommon import motion_files_hash
from wide_portrait import chromium


def select_photo(phone, url, photo, index):
    open_room(phone, url, 'photos')
    phone.locator('#portraitArea').select_option('wide')
    phone.locator('#portraitFile').set_input_files(photo)
    phone.locator('#portraitSubmit').click()
    ready(phone)
    if index is not None:
        picker = phone.locator('#portraitSource')
        if not picker.evaluate('el => el.open'):
            picker.locator('summary').click()
        phone.locator('#faceBoxes button').nth(index).click()
        ready(phone)


def exercise(browser, url, photo, index, evidence=None):
    with browser.new_page(**MOBILE) as phone, browser.new_page(**MOBILE) as other:
        select_photo(phone, url, photo, index)
        open_files = drawing_files(phone, '#downloads')
        answers = []

        def record(route):
            options = json.loads(route.request.headers['x-oasis-portrait'])
            assert options['cheekPrint'] and options['face'] == index
            assert not any(options.get(key) for key in ('rakePrint', 'hairWoodcut', 'longHair', 'flowingHair'))
            response = route.fetch(timeout=100000)
            assert response.ok, response.status
            answers.append(response.json())
            route.fulfill(response=response)

        phone.route(url+'/api/portrait', record)
        button = phone.get_by_role('button', name='Engrave cheek shadows')
        button.click()
        expect(phone.locator('#portraitHairNote')).to_contain_text('photographed cheek and jaw', timeout=100000)
        reply = answers[0]
        assert reply['cheekPrint']['applied'] and reply['cheekPrintDrawing']['includesCenterRake']
        files = drawing_files(phone, '#downloads')
        assert files != open_files
        parts = [dict(name=name, text=raw.decode()) for name, (_, raw) in
                 zip(reply['cheekPrint']['files'], files, strict=True)]
        assert motion_files_hash(parts) == reply['cheekPrint']['motionSHA256']
        phone.get_by_role('button', name='Show open engraving').click()
        assert drawing_files(phone, '#downloads') == open_files
        button.click()
        assert len(answers) == 1 and drawing_files(phone, '#downloads') == files
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence/'open.oasisportrait').write_text(json.dumps(reply['drawing'], separators=(',', ':')))
            (evidence/'shaded.oasisportrait').write_text(json.dumps(reply['cheekPrintDrawing'], separators=(',', ':')))
            for name, raw in files:
                (evidence/name).write_bytes(raw)
            phone.locator('.sand-display').screenshot(path=evidence/'phone.png')
        saved, _ = save(phone, url+API)
        assert saved['motion']['includesCenterRake'] is True
        assert [f['text'].encode() for f in saved['motion']['files']] == [raw for _, raw in files]
        open_room(other, url, 'photos')
        choose(other, 'zone', 'center')
        assert drawing_files(other, '#roomFiles') == files
        # A crop without readable cheek shading must keep its exact open route.
        with browser.new_page(**MOBILE) as third:
            select_photo(third, url, photo, index)
            previous = drawing_files(third, '#downloads')
            decline = {'drawing': reply['drawing'], 'cheekPrint': {'applied': False}}
            third.route(url + '/api/portrait', lambda route: route.fulfill(json=decline), times=1)
            third.get_by_role('button', name='Engrave cheek shadows').click()
            expect(third.locator('#portraitHairNote')).to_contain_text('too little separate cheek shadow')
            expect(third.locator('#portraitCheeks')).to_be_hidden()
            assert drawing_files(third, '#downloads') == previous
        return reply['cheekPrint']['motionSHA256']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('garden', type=Path)
    parser.add_argument('photo', type=Path)
    parser.add_argument('--face', type=int, help='One-based position in the guest photo picker.')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as tmp, room(args.garden, Path(tmp)/'room.db', photo_portraits=True) as url:
        with sync_playwright() as session, session.chromium.launch(executable_path=chromium(session, None)) as browser:
            print(exercise(browser, url, args.photo, args.face-1 if args.face else None, args.evidence))
