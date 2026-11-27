#!/usr/bin/env python3
"""Teach a picture on one phone and verify interest-based playback on a simulated table."""
import argparse
import base64
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from check_ring_scene import travel
from test_attached_garden import Table, served, wait_table
from test_garden_room import API, caption, drawing_files, open_room
from test_guest_place import unpack
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_lettering import seat_view
from test_ring_object_photo import PhoneTraffic, crop, expand
from test_ring_photo import frame
from test_saved_guest_drawings import ask, draw_another_version


def exercise(browser, gallery, photo, evidence):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / 'room.db'
        table = Table(db)
        with served(gallery, db, table, prepared=True) as url, \
                browser.new_context(**MOBILE, service_workers='block') as left, \
                browser.new_context(**MOBILE, service_workers='block') as right:
            traffic = PhoneTraffic(url)
            errors = []
            for phone in (left, right):
                phone.route('http**://**/*', traffic.check)
                phone.on('weberror', lambda err: errors.append(str(err.error)))
            first, host = left.new_page(), right.new_page()
            api = url + API
            open_room(first, url)
            live = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
            catalog = live['planner']
            vacant = catalog['openSubject']
            expected_files = list(live['setup'])

            def keep(page):
                body, _ = save(page, api)
                expected_files.extend(body.get('motion', {}).get('files', []))
                return body

            ask(first, 'a meadow oak for Thomas')
            first.locator('#suggestionPhoto').click()
            first.locator('#portraitFile').set_input_files(traffic.photo('tree.jpg', photo.read_bytes(), 'image/jpeg'))
            first.locator('#portraitSubmit').click()
            expect(first.locator('#keep')).to_be_visible(timeout=25000)
            crop(first, .45, .485, .714)
            interests = 'botany, autumn hiking'
            first.locator('#drawingInterests').fill(interests)
            taught = keep(first)['state']
            oak = taught['ids'][0]
            shape = taught['custom'][oak]
            assert taught['drawingInterests'][oak] == interests
            first.close()

            open_room(host, url)
            expand(host, '#peopleBox')
            host.locator('#personName').fill('Rowan')
            host.locator('#personPlace').select_option('2')
            topic = host.locator('#personInterest')
            drawing = host.locator('#personDrawing')
            topic.fill('teaching, not a botanist')
            expect(drawing.locator('optgroup[label="From their interests"] option[value="'+oak+'"]')).to_have_count(0)
            topic.fill('a botanist who teaches')
            expect(drawing).to_have_value(oak)
            drawing.select_option(vacant)
            host.locator('#personSubmit').click()
            assert 'motion' not in keep(host)

            # Alex and Rowan both have a clear place. Only Rowan has this interest.
            ask(host, 'a meadow oak')
            caption(host, 'Rowan · Meadow oak')
            expect(host.locator('#drawingInterests')).to_have_value(interests)
            host.locator('#drawingInterests').fill('unrelated abandoned change')
            host.goto('about:blank')
            open_room(host, url)
            ask(host, 'draw something for Alex')
            alex = keep(host)['state']
            assert alex['ids'][1] in catalog['subjects'] and alex['drawingInterests'][oak] == interests
            draw_another_version(host, 'Wind harp', 'Thomas')
            before = keep(host)['state']
            harp = before['ids'][0]
            assert harp != oak and oak not in before['ids']
            ask(host, 'draw something for Rowan')
            caption(host, 'Rowan · Meadow oak')
            expect(host.locator('#portraitFile')).to_have_value('')
            preview = frame(host)
            download = drawing_files(host, '#downloads')

            # Discard that preview. Let the host independently choose from the guest book.
            host.goto('about:blank')
            open_room(host, url, 'changing-garden')
            toggle = host.locator('#changingGarden button')
            toggle.click()
            expect(toggle).to_have_text('Stop changing')
            delivered = 0

            def finish_queue():
                nonlocal delivered
                while delivered < len(expected_files):
                    assert table.dispatched(delivered + 1) == expected_files[delivered]
                    table.outcome = 'complete'
                    delivered += 1

            def next_automatic():
                with host.expect_response(lambda r: r.request.method == 'PUT' and
                                          r.request.post_data_json.get('automatic'), timeout=25000) as arrival:
                    finish_queue()
                response = arrival.value
                assert response.ok, response.text()
                body = response.request.post_data_json
                expected_files.extend(body['motion']['files'])
                assert body['state']['ids'][0] == harp, 'A manually placed sketch was overwritten.'
                return body

            placed = next_automatic()
            after = placed['state']
            assert placed['motion']['place'] == 2 and placed['motion']['fill']
            assert after['ids'] == [harp, before['ids'][1], oak] and after['custom'][oak] == shape
            assert [(p['name'], p['text'].encode()) for p in placed['motion']['files']] == download
            route = from_files(download, unpack(catalog['transit'])[0])
            sand = replay(host, before['bed'], route)
            assert np.mean(np.abs(sand.astype(float) - preview)) < .6
            geom = catalog['geometry']
            n = live['size']
            y, x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
            radius = np.hypot(x, y)
            low, high = geom['bounds']
            margin = 2 * live['groove']
            protected = (radius < low-margin) | ((radius > high+margin) & ((y < 0) | (abs(x) > margin)))
            for slot in (0, 1):
                angle = geom['angles'][slot]
                protected |= np.hypot(x-geom['center']*np.cos(angle), -y-geom['center']*np.sin(angle)) < geom['scale']*.93

            def bed(state):
                return np.frombuffer(base64.b64decode(state['bed']), dtype=np.uint8).reshape(n,n)

            np.testing.assert_array_equal(bed(before)[protected], bed(after)[protected])
            # A guest on the other phone changes Alex's place during Rowan's hold.
            # Rowan's automatic drawing can still take its next turn afterwards.
            other = left.new_page()
            open_room(other, url)
            ask(other, 'a pumpkin for Alex')
            keep(other)
            caption(host, 'Alex · Pumpkin')
            neighbor = next_automatic()
            assert neighbor['motion']['place'] == 1 and neighbor['state']['ids'][2] == oak
            following = next_automatic()
            assert following['motion']['place'] == 2 and following['state']['ids'][2] != oak
            toggle.click()
            finish_queue()
            wait_table(host, url, state='idle', queued=0, ready=True)
            assert len(table.calls) == delivered and not traffic.violations and not errors
            result = dict(vertices=len(shape), protected_pixels=int(protected.sum()), files_delivered=delivered,
                          distance_m=round(float(travel(route)[-1])*live['radiusMM']/1000, 3),
                          automatic_places=[placed['motion']['place'], neighbor['motion']['place'], following['motion']['place']],
                          rowan_next=following['state']['ids'][2], radius_mm=live['radiusMM'],
                          groove_mm=live['groove']*live['radiusMM'], tracking_mm=live['trackingMarginMM'])
            if evidence:
                evidence.mkdir(parents=True, exist_ok=True)
                seat_view(sand, geom, 2).save(evidence / 'oak-at-rowans-seat.png')
                Image.fromarray(sand).save(evidence / 'whole-table.png')
                (evidence / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
                for name, data in download:
                    (evidence / name).write_bytes(data)
            return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path, help='Gallery with three initially open guest places')
    parser.add_argument('photo', type=Path, help='Local oak reference painting')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            print(exercise(browser, args.gallery, args.photo, args.evidence))
