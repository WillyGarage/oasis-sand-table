"""Import a host-prepared portrait on a phone and compare its saved moves with the host's files."""
import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, choose, drawing_files, open_room, room
from test_ring_guest_border import MOBILE, save
from test_ring_shadows import ready


def exercise(browser, url, drawing, paths):
    with browser.new_page(**MOBILE) as phone, browser.new_page(**MOBILE) as guest:
        open_room(phone, url, 'prepared-portrait')
        mode = phone.locator('#portraitMode')
        expect(mode).to_have_value('prepared')
        field = phone.locator('#portraitFile')
        field.set_input_files(drawing)
        submit = phone.locator('#portraitSubmit')
        submit.click()
        expect(phone.locator('#portraitStatus')).to_contain_text('matching portrait area')
        expect(phone.locator('#keep')).to_be_hidden()
        phone.locator('#portraitArea').select_option('wide')
        submit.click()
        ready(phone)
        expect(phone.locator('#portraitSource')).to_be_hidden()
        expect(phone.locator('#soloStyles')).to_be_hidden()
        expect(phone.locator('#photoCaptionField')).to_be_hidden()
        choose(phone, 'stage', 'cleared')
        choose(phone, 'stage', 'redrawn')
        files = drawing_files(phone, '#downloads')
        assert [data for _,data in files] == [p.read_bytes() for p in paths]
        kept, _ = save(phone, url+API)
        assert [f['text'].encode() for f in kept['motion']['files']] == [data for _,data in files]
        open_room(guest, url, 'photos')
        choose(guest, 'zone', 'center')
        assert drawing_files(guest, '#roomFiles') == files

        # A bad import must never leave the previous portrait ready to play.
        open_room(phone, url, 'prepared-portrait')
        invalid = json.loads(drawing.read_text())
        line = invalid['marks'][0]['points'] if 'marks' in invalid else invalid['points']
        line[0] = [invalid['diameterMm'],0]
        field.set_input_files({'name':'bad.oasisportrait','mimeType':'application/json','buffer':json.dumps(invalid).encode()})
        submit.click()
        expect(phone.locator('#portraitStatus')).to_contain_text('Choose a prepared portrait file')
        expect(phone.locator('#keep')).to_be_hidden()
        mode.select_option('one')
        assert field.evaluate('el=>el.files.length') == 0
        expect(phone.locator('#soloStyles')).to_be_visible()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('drawing', type=Path)
    parser.add_argument('paths', type=Path, nargs='+', help='Host motion files, in playback order')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp, room(args.gallery, Path(temp)/'room.db') as url, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, url, args.drawing, args.paths)
    print('Prepared portrait matched the host downloads and the saved drawing on a second phone.')
