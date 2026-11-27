#!/usr/bin/env python3
"""Run two phone browsers and a simulated table across two real combined gallery releases."""
import argparse
from pathlib import Path
import sqlite3
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from test_attached_garden import Table, served, wait_table
from test_garden_room import caption, choose, drawing_files, room
from test_ring_photo import frame
from thrcommon import motion_files_hash


def open_phone(page, url, layout, shared=True):
    page.goto(f'{url}?layout={layout}#photos')
    expect(page.locator('#layout')).to_have_value(layout)
    if shared:
        expect(page.locator('.controls')).not_to_have_attribute('inert', '')
        expect(page.locator('#roomNotice')).to_be_hidden()
    return page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")


def photo(page, source):
    page.locator('#portraitFile').set_input_files(source)
    page.locator('#portraitSubmit').click()
    expect(page.locator('#keep')).to_be_visible(timeout=40000)


def keep(page, api):
    with page.expect_response(lambda response: response.url == api and response.request.method == 'PUT') as sent:
        page.locator('#keep').click()
    assert sent.value.status == 200, sent.value.text()[:250]
    expect(page.locator('#keep')).to_be_hidden()
    return sent.value.request.post_data_json


def finish(table, offset, files):
    for index, part in enumerate(files, offset+1):
        assert table.dispatched(index) == part
        table.outcome = 'complete'
    return offset + len(files)


def startup_download(page):
    return [{'name':name.split('-', 1)[1], 'text':data.decode('ascii')}
            for name, data in drawing_files(page, '#setupFiles')]


def carried_private(page, old, new, layout, saved, expected_frame):
    url = 'http://127.0.0.1/private'
    page.route('http://127.0.0.1/*', lambda route: route.fulfill(path=old, content_type='text/html'))
    prior = open_phone(page, url, layout, shared=False)
    old_key = prior.get('storageKey', f'oasis-ring-{layout}-v1')
    page.evaluate("([k,s])=>localStorage.setItem(k,JSON.stringify(s))", [old_key,saved])
    page.reload()
    assert np.array_equal(frame(page), expected_frame)
    page.unroute('http://127.0.0.1/*')
    page.route('http://127.0.0.1/*', lambda route: route.fulfill(path=new, content_type='text/html'))
    fresh = open_phone(page, url, layout, shared=False)
    assert np.array_equal(frame(page), expected_frame)
    key = fresh.get('storageKey', f'oasis-ring-{layout}-v1')
    read = lambda: page.evaluate('k=>JSON.parse(localStorage.getItem(k))', key)
    assert read() == dict(saved,edition=fresh['edition'])
    if old_key != key:
        # The complete original is still usable when the phone cannot
        # accommodate two copies. A later visit can finish the migration.
        page.add_init_script("""if(sessionStorage.getItem('fullKey')) {
          const original = Storage.prototype.setItem;
          Storage.prototype.setItem = function(key,data) {
            if (this===localStorage && key===sessionStorage.getItem('fullKey'))
              throw new DOMException('Storage full','QuotaExceededError');
            return original.call(this,key,data);
          };
        }""")
        page.evaluate("k=>{localStorage.removeItem(k);sessionStorage.setItem('fullKey',k)}",key)
        page.reload()
        assert np.array_equal(frame(page),expected_frame) and read() is None
        assert page.evaluate('k=>JSON.parse(localStorage.getItem(k))',old_key) == saved
        page.evaluate("sessionStorage.removeItem('fullKey')")
        page.reload()
        assert read() == dict(saved,edition=fresh['edition'])
    page.locator('#reset').click()
    page.reload()
    assert page.evaluate('k=>localStorage.getItem(k)', key) == 'null'
    assert not np.array_equal(frame(page), expected_frame)
    page.unroute('http://127.0.0.1/*')


def exercise(browser, old, new, layout, folder, source):
    db = folder / (layout+'.db')
    table = Table(db)
    path = '/api/garden/'+layout
    with browser.new_context() as left, browser.new_context() as right:
        a, b = left.new_page(), right.new_page()
        with served(old, db, table, prepared=True, layout=layout) as url:
            prior = open_phone(a, url+'/garden', layout)
            opening = frame(a)
            count = finish(table, 0, prior['setup'])
            wait_table(a, url, ready=True)
            # Keep an uploaded photograph, then a border from the second phone
            # while the controller is still executing the portrait.
            photo(a, source)
            portrait = keep(a, url+path)
            open_phone(b, url+'/garden', layout)
            caption(b, portrait['state']['portrait'])
            choose(b, 'zone', 'outer')
            choose(b, 'stage', 'redrawn')
            border = keep(b, url+path)
            choose(b, 'zone', 'center')
            saved = b.request.get(url+path).json()
            assert saved['revision'] == 2 and saved['state']['portrait']
            kept_frame = frame(b)
            wait_table(a, url, drawing={'revision':1,'zone':'center'}, queued=1)
            assert table.dispatched(count+1) == portrait['motion']['files'][0]
            token = table.token
        # The previous room software did not pin preparation downloads: after
        # finishing setup, only its last part survives in the playback receipt.
        with sqlite3.connect(db) as prior_db:
            prior_db.execute('DROP TABLE IF EXISTS attachment_setup')
            remaining, = prior_db.execute('SELECT COUNT(*) FROM playback_part WHERE revision=0').fetchone()
            assert remaining < len(prior['setup'])
        with served(new, db, table, layout=layout) as url:
            live = open_phone(a, url+'/garden', layout)
            assert live['previousOpening']['edition'] == prior['edition']
            assert live['previousOpening']['bed'] == prior['bed'] != live['bed']
            assert motion_files_hash(live['setup']) != motion_files_hash(prior['setup'])
            wanted = dict(saved,state=dict(saved['state'],edition=live['edition']))
            for page in (a,b):
                open_phone(page, url+'/garden', layout)
                caption(page, saved['state']['portrait'])
                assert page.request.get(url+path).json() == wanted
                assert np.array_equal(frame(page), kept_frame)
            assert startup_download(a) == prior['setup']
            for zone, change in [('center',portrait),('outer',border)]:
                assert a.request.get(url+path+'/drawings/'+zone).json()['files'] == change['motion']['files']
            assert table.token == token and len(table.calls) == count+1
            # The first untouched new phone can request today's lotus. Its neighbor
            # observes the new bed, and playback keeps the previous files ahead of it.
            a.locator('#centerPhoto > summary').click()
            choose(a, 'stage', 'redrawn')
            flower = keep(a, url+path)
            caption(b, 'Lotus')
            assert not np.array_equal(frame(b), kept_frame)
            for change in (portrait, border, flower):
                count = finish(table, count, change['motion']['files'])
            wait_table(b, url, ready=True, lastCompleted={'revision':3,'zone':'center'})
        with served(new, db, table, layout=layout) as url:
            open_phone(a, url+'/garden', layout)
            assert startup_download(a) == prior['setup'] and len(table.calls) == count

        # An attached room with no keeps has a real opening even at revision
        # zero. A newly prepared room must instead get the entire new opening.
        untouched = folder / ('untouched-'+layout+'.db')
        bare = Table(untouched)
        with served(old, untouched, bare, prepared=True, layout=layout):
            assert bare.dispatched(1) == prior['setup'][0]
        with served(new, untouched, bare, layout=layout) as url:
            open_phone(a, url+'/garden', layout)
            initial = a.request.get(url+path).json()
            assert initial['revision'] == 0 and initial['state']['bed'] == prior['bed']
            assert np.array_equal(frame(a), opening)
            assert startup_download(a) == prior['setup'] and len(bare.calls) == 1
        fresh = folder / ('fresh-'+layout+'.db')
        clean = Table(fresh)
        with served(new, fresh, clean, prepared=True, layout=layout) as url:
            open_phone(a, url+'/garden', layout)
            assert a.request.get(url+path).json() == {'revision':0,'state':None}
            assert clean.dispatched(1) == live['setup'][0] and startup_download(a) == live['setup']
            assert not np.array_equal(frame(a), opening)

        # A shared preview has no attachment signature. Its exact saved gallery
        # edition and bed still identify the kept photo on both phones.
        virtual = folder / ('preview-'+layout+'.db')
        with room(old, virtual) as url:
            for change in (portrait,border):
                response = a.request.put(url+path,headers={'Origin':url},data=change)
                assert response.status == 200, response.text()[:250]
        with room(new, virtual) as url:
            for page in (a,b):
                open_phone(page, url+'/garden', layout)
                assert page.request.get(url+path).json() == wanted
                assert np.array_equal(frame(page),kept_frame)
        carried_private(a, old, new, layout, saved['state'], kept_frame)
    print(f'{layout}: the kept photo and files crossed releases exactly; both phones saw the new flower. '
          'The old table resumed its queue, the fresh table received the new setup.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old', type=Path, help='previous combined three-zone and wide-center gallery')
    parser.add_argument('new', type=Path, help='updated combined gallery built from that previous edition')
    parser.add_argument('--photo', type=Path, default=Path(__file__).resolve().parents[1]/'captures/morning/dog_photo.jpg')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as work, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'), None)
        with pw.chromium.launch(executable_path=chrome) as browser:
            for key in ('garden','portrait'):
                exercise(browser, args.old.resolve(), args.new.resolve(), key, Path(work), args.photo)
