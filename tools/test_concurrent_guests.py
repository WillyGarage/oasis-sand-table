#!/usr/bin/env python3
"""Two phones keep manual drawings from one revision using a real loopback room and a fake table.

    python3 tools/test_concurrent_guests.py GALLERY_WITH_OPEN_GUEST_PLACES

An explicit photo destination, a colliding custom drawing ID, a background poll, and a
stale PUT each come from the unmodified mobile editor. The barrier holds its original requests.
"""

import argparse
from contextlib import closing
import io
from pathlib import Path
import sqlite3
import tempfile
import time
import zlib

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

from test_attached_garden import Table, served, wait_table
from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_ring_guest_border import MOBILE
from test_ring_photo import frame

DOG = Path(__file__).resolve().parents[1] / 'patterns/dog/face_crop.jpg'


def photo_drafts(pages):
    # Two different files, one conversion per fresh phone. Each browser allocates sketch-1.
    sketch = Image.new('RGB', (320, 320), 'white')
    ink = ImageDraw.Draw(sketch)
    ink.line([(40, 158), (158, 41), (279, 158), (252, 158), (252, 277),
              (73, 277), (73, 158), (40, 158)], fill='black', width=8)
    ink.rectangle([134, 195, 179, 277], outline='black', width=7)
    png = io.BytesIO()
    sketch.save(png, format='PNG')
    sources = [DOG, {'name': 'cabin.png', 'mimeType': 'image/png', 'buffer': png.getvalue()}]
    files, shapes = [], []
    for slot, (page, source, title, guest) in enumerate(zip(pages, sources, ('Maverick', 'Cabin'), ('Thomas', 'Alex'))):
        page.locator('#centerPhoto > summary').click()
        page.locator('#guestPhotoKind').select_option('object')
        page.locator('#portraitPlace').select_option(str(slot))
        page.locator('#objectName').fill(title)
        page.locator('#portraitFile').set_input_files(source)
        page.locator('#portraitSubmit').click()
        caption(page, guest + ' · ' + title)
        files.append(drawing_files(page, '#downloads'))
        shapes.append(page.evaluate("""async () => {
          const scene=JSON.parse(document.querySelector('#scene').textContent).live;
          const source=document.querySelector('#portraitFile').files[0];
          const result=await GuestPhoto.fromFile(source, {object:true,
            portraitDiameterGrooves:2*scene.planner.geometry.scale/scene.groove});
          return result.points.slice(1,-1);
        }"""))
    assert files[0] != files[1] and shapes[0] != shapes[1]
    return files, shapes


def watch_saves(page, api):
    events = []

    def record(response):
        if response.url == api and response.request.method == 'PUT':
            events.append((response.status, response.request.post_data_json))

    page.on('response', record)
    return events


def barrier(pages, api, revision, slots, same_target=False):
    """Hold both real UI saves, let one win, then deliver the other's stale PUT unmodified."""
    def hold_first_put(pending):
        def intercept(route):
            if route.request.method == 'PUT' and not pending:
                pending.append(route)
            else:
                route.continue_()
        return intercept

    held = [[], []]
    handlers = []
    for page, pending in zip(pages, held):
        intercept = hold_first_put(pending)
        handlers.append(intercept)
        page.route(api, intercept)

    try:
        for page, pending in zip(pages, held):
            page.locator('#keep').click()
            deadline = time.monotonic() + 5
            while not pending and time.monotonic() < deadline:
                page.wait_for_timeout(20)
            assert pending, 'Keep did not submit the original preview'
        outgoing = [pending[0].request.post_data_json for pending in held]
        for body, slot in zip(outgoing, slots):
            assert body['revision'] == revision
            assert body['motion']['zone'] == 'middle' and body['motion']['place'] == slot
            assert body['motion']['fill'] is True

        def release(index, status):
            page = pages[index]
            with page.expect_response(lambda r: r.url == api and r.request.method == 'PUT' and r.status == status):
                held[index][0].continue_()

        release(0, 200)
        release(1, 409)
        if same_target:
            expect(pages[1].locator('#roomReload')).to_be_visible(timeout=10000)
        else:
            expect(pages[1].locator('#keep')).to_be_hidden(timeout=10000)
        return outgoing
    finally:
        for page, handler in zip(pages, handlers):
            page.unroute(api, handler)


def as_file_payload(files):
    return [{'name': name, 'text': data.decode('ascii')} for name, data in files]


def check_bed(page, saved, slots):
    # Rebuild from empty seats, rounding the heights between saves exactly as two serial guests do.
    assert page.evaluate("""([state,slots])=>{
      const live=JSON.parse(document.querySelector('#scene').textContent).live;
      const renderer=new RingSand(live.size,live.groove,live.profile), planner=live.planner;
      let ids=planner.defaults.slice(), encoded=live.bed;
      for(const slot of slots){
        const next=ids.slice();next[slot]=state.ids[slot];
        const move=OasisRingPlanner.planChange(planner,ids,next,state.custom);
        if(!move.fill || move.place!==slot)return false;
        const bed=Float32Array.from(atob(encoded), b=>b.charCodeAt(0)/170-1);
        for(const part of move.segments)renderer.carve(bed,part);
        const bytes=Uint8Array.from(bed,b=>Math.round((1+Math.max(-1, Math.min(.5,b)))*170));
        let packed='';
        for(let i=0;i<bytes.length;i+=8192)packed+=String.fromCharCode(...bytes.subarray(i,i+8192));
        encoded=btoa(packed);ids=next;
      }
      return encoded===state.bed;
    }""", [saved, slots]), 'Saved sand differs from drawing the two accepted requests in order'


def check_disjoint(pages, api, events, files, shapes, attached):
    first, second = pages
    if attached:
        intents = barrier(pages, api, 0, (0, 1))
        for slot, intent in enumerate(intents):
            assert intent['state']['ids'][slot] == 'sketch-1'
            assert intent['state']['custom']['sketch-1'] == shapes[slot]
    else:
        # Let the second guest's ordinary polling actually see the first save before tapping Keep.
        with second.expect_response(lambda r: r.url == api and r.request.method == 'GET' and
                                    r.status == 200 and 'if-none-match' in r.request.headers) as poll:
            first.locator('#keep').click()
        assert poll.value.json()['revision'] == 1
        expect(second.locator('#roomStatus')).to_contain_text('You can still keep this drawing.')
        expect(second.locator('#roomReload')).to_be_hidden()
        expect(second.locator('#objectName')).to_have_value('Cabin')
        expect(second.locator('#portraitPlace')).to_have_value('1')
        second.locator('#keep').click()
        expect(second.locator('#keep')).to_be_hidden(timeout=10000)
    accepted = [[body for status, body in history if status == 200] for history in events]
    assert [len(history) for history in accepted] == [1, 1]
    if attached:
        assert [status for status, _ in events[1]].count(409) >= 1
    for slot, (history, downloaded) in enumerate(zip(accepted, files)):
        assert history[0]['motion'] == {'zone':'middle', 'place':slot, 'fill':True, 'files':as_file_payload(downloaded)}

    record = first.request.get(api).json()
    assert record['revision'] == 2
    state = record['state']
    a, b, untouched = state['ids']
    assert a != b and untouched == 'open_place'
    assert state['custom'] == {a:shapes[0], b:shapes[1]} and state['labels'] == {a:'Maverick', b:'Cabin'}
    assert first.request.get(api + '/drawings/middle').json() == {'revision':2, 'files':as_file_payload(files[1])}
    check_bed(first, state, (0, 1))
    for page in pages:
        caption(page, 'Thomas · Maverick')
        caption(page, 'Alex · Cabin')
        expect(page.locator('#roomReload')).to_be_hidden()
    assert np.array_equal(frame(first), frame(second))
    return state


def same_place(pages, api, events, previous):
    first, second = pages
    downloaded = []
    for page, subject in zip(pages, ('a rocket', 'a pumpkin')):
        page.locator('#target').select_option('2')
        suggest(page, subject)
        caption(page, 'Lek · ' + ('Rocket' if subject == 'a rocket' else 'Pumpkin'))
        downloaded.append(drawing_files(page, '#downloads'))
    barrier(pages, api, 2, (2, 2), same_target=True)
    assert [status for status, _ in events[0]].count(200) == 2
    assert [status for status, _ in events[1]].count(200) == 1
    assert events[1][-1][0] == 409
    assert events[0][-1][1]['motion']['files'] == as_file_payload(downloaded[0])
    assert events[1][-1][1]['motion']['files'] == as_file_payload(downloaded[1])
    caption(second, 'Lek · Pumpkin')
    expect(second.locator('#idea')).to_have_value('a pumpkin')
    record = first.request.get(api).json()
    assert record['revision'] == 3
    state = record['state']
    assert state['ids'] == [*previous['ids'][:2], 'rocket']
    assert state['custom'] == previous['custom'] and state['labels'] == previous['labels']
    check_bed(first, state, (0, 1, 2))
    return downloaded[0]


def check_queue(page, url, database, table, accepted):
    setup = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
    expected = [setup, *(as_file_payload(x) for x in accepted)]
    wait_table(page, url, state='drawing', revision=3, queued=3)
    with closing(sqlite3.connect(database)) as db:
        rows = list(db.execute('SELECT revision,name,track FROM playback_part WHERE layout=? ORDER BY revision,part',
                               ('garden',)))
    assert [(rev, name, zlib.decompress(track).decode('ascii')) for rev, name, track in rows] == [
        (rev, part['name'], part['text']) for rev, files in enumerate(expected) for part in files
    ]
    parts = [part for files in expected for part in files]
    for i, part in enumerate(parts, 1):
        assert table.dispatched(i) == part
        table.outcome = 'complete'
    wait_table(page, url, state='idle', ready=True, revision=3, queued=0)
    assert len(table.calls) == len(parts)
    return len(parts)


def exercise(browser, gallery, database, attached):
    fake = Table(database) if attached else None
    server = served(gallery, database, fake, prepared=True) if attached else room(gallery, database)
    with server as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        pages = [a.new_page(), b.new_page()]
        errors = []
        origins, events = [], []
        for page in pages:
            page.on('pageerror', lambda e: errors.append(str(e)))
            open_room(page, url)
            origins.append(page.evaluate('performance.timeOrigin'))
            events.append(watch_saves(page, url + API))
        files, shapes = photo_drafts(pages)
        previous = check_disjoint(pages, url + API, events, files, shapes, attached)
        winner = same_place(pages, url + API, events, previous)
        assert origins == [p.evaluate('performance.timeOrigin') for p in pages]
        assert not errors, errors
        if fake:
            count = check_queue(pages[0], url, database, fake, [*files, winner])
            print(f'Attached fake completed {count} matching files in order, including setup.', flush=True)
        else:
            print('Shared room kept both photos without reload and preserved the same-place conflict.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            for attached in (False, True):
                exercise(browser, args.gallery, Path(tmp) / f'garden-{attached}.db', attached)
