#!/usr/bin/env python3
"""Check the opt-in wide stand mixer in a fitted three-zone dinner garden."""
import argparse
from hashlib import sha256
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_photo import frame
from wide_portrait import chromium


def request(page, words):
    page.locator('#idea').fill(words)
    page.get_by_role('button', name='Preview suggestion').click()


def exercise(browser, gallery, directory):
    with room(gallery, directory/'room.db') as url, browser.new_page(**MOBILE) as phone, browser.new_page(**MOBILE) as other:
        open_room(phone, url, 'example-stand-mixer')
        offer = phone.get_by_role('button', name='Preview stand mixer in the wide center')
        expect(offer).to_be_visible()
        expect(phone.locator('#keep')).to_be_hidden()
        suggest(phone, 'a phage for Thomas, an open book for Alex and a Thai rooftop for Lek')
        occupied,_ = save(phone,url+API)
        opening = phone.request.get(url+API).json()
        assert opening['state']['ids'] == occupied['state']['ids']
        assert len(set(opening['state']['ids'])) == 3

        # Keep ordinary requests on their existing paths. Changing a request withdraws an old offer.
        request(phone, 'a mixer truck for Alex')
        expect(offer).to_be_hidden()
        expect(phone.locator('#suggestionPhoto')).to_be_visible()
        suggest(phone, 'a paint roller for Alex')
        caption(phone, 'Paint roller')
        expect(offer).to_be_hidden()
        request(phone, 'please draw a stand mixer')
        expect(offer).to_be_visible()
        expect(phone.locator('#keep')).to_be_hidden()
        request(phone, 'a stand-mixer for Alex')
        expect(offer).to_be_visible()
        expect(phone.locator('#suggestionPhoto')).to_be_visible()
        expect(phone.locator('#wideSuggestion')).to_contain_text('all three guest places')
        assert phone.request.get(url+API).json() == opening
        offer.click()
        caption(phone, 'Stand mixer across the center and guest places')
        expect(phone.locator('#keep')).to_be_visible()
        files = drawing_files(phone, '#downloads')
        assert phone.request.get(url+API).json() == opening

        # These are the four previously reviewed firmware files at the 215 mm size.
        assert [sha256(data).hexdigest() for _,data in files] == [
            'fd33ef0b241f87fae7b5974a3912257f954bc6888287d9a2a1aa9dff5fc3b672',
            '85bd100b5ee2b48bf430b6f6e2c4d83610eb0f63179a15cf3cac86dbe243259c',
            '765031b6d7cdb2f313cc18d419f3251d8b8c586c69d59a6536fc75bdf8064525',
            '6facd595ec78935143319f3b1e330d8d990bcd9cad533349980860273274a416',
        ]
        live = phone.locator('#scene').evaluate('s => JSON.parse(s.textContent).live')
        entry = live['wideCenter']['transit'][0]
        route = from_files(files, entry)
        bed = (opening.get('state') or {}).get('bed', live['bed'])
        exact = replay(phone, bed, route)
        assert np.abs(frame(phone).astype(float)-exact).mean() < 1.2
        before = replay(phone, bed, np.array([entry,entry]))
        n=len(before)
        y,x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
        border = (np.hypot(x,y)>.80) & (np.hypot(x,y)<.99) & ((y<0) | (np.abs(x)>.025))
        assert np.array_equal(before[border], exact[border])

        kept,revision = save(phone,url+API)
        assert kept['motion']['includesCenterRake'] and kept['motion']['centerMode']=='widePortrait'
        assert kept['state']['portrait']=='Stand mixer'
        open_room(other, url, 'photos')
        choose(other,'zone','center')
        assert drawing_files(other,'#roomFiles') == files
        assert other.request.get(url+API).json()['state']['ids'] == opening['state']['ids']
        other.locator('#restoreGuests').click()
        caption(other,'guest places are back')
        assert other.request.get(url+API).json()['revision'] == revision
        restored,_ = save(other,url+API)
        assert restored['state']['ids'] == opening['state']['ids'] and not restored['state'].get('widePortrait')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw,None)) as browser:
        exercise(browser, args.gallery, Path(tmp))
