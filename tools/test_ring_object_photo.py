#!/usr/bin/env python3
"""Exercise real mobile object-photo editing and replay its actual downloads using two local phones.

Pass the occupied and open three-zone galleries, a contact sheet (cup and motorcycle
across its top half, blank at bottom right), a face photograph and an evidence directory.
"""
import argparse
import base64
import io
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_garden_room import API, caption, choose, drawing_files, keep, open_room, room, suggest
from test_guest_place import evidence, physical_parts, unpack
from test_open_guests import verify_download
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_photo import frame


class PhoneTraffic:
    """Allow only the room and look for source-file bytes, including inside a saved drawing."""
    def __init__(self, url, api=API):
        self.url = url
        self.api = api
        self.fragments = []
        self.violations = []
        self.writes = 0

    def photo(self, name, raw, mime):
        marker = ('PRIVATE-OASIS-FILE-' + name).encode()
        raw += marker
        name = 'private-guest-' + name
        self.fragments.extend([name.encode(), marker, raw[len(raw)//2:len(raw)//2+64],
                               base64.b64encode(raw)[len(raw)//2:len(raw)//2+64]])
        return {'name': name, 'mimeType': mime, 'buffer': raw}

    def check(self, route):
        req = route.request
        path = urlsplit(req.url).path
        if (not req.url.startswith(self.url + '/') or
                (req.method != 'GET' and (req.method, path) != ('PUT', self.api))):
            self.violations.append(f'{req.method} {path}')
            route.abort()
            return
        if req.method == 'PUT':
            self.writes += 1
        sent = req.url.encode() + (req.post_data_buffer or b'')
        if any(fragment in sent for fragment in self.fragments):
            self.violations.append('source photo sent in ' + path)
        route.continue_()


def expand(page, selector):
    panel = page.locator(selector)
    if not panel.evaluate('el => el.open'):
        panel.locator(':scope > summary').click()


def select_object(page, source, label=''):
    expand(page, '#centerPhoto')
    page.locator('#guestPhotoKind').select_option('object')
    page.locator('#portraitPlace').select_option('0')
    page.locator('#objectName').fill(label)
    page.locator('#portraitFile').set_input_files(source)
    expect(page.locator('#keep')).to_be_hidden()
    page.locator('#portraitSubmit').click()
    expect(page.locator('#portraitSource')).to_be_visible(timeout=25000)
    expect(page.locator('#portraitSubmit')).to_be_enabled()


def crop(page, cx, cy, width=.46):
    expand(page, '#portraitSource')
    page.get_by_role('button', name='Frame the subject', exact=True).click()
    # Match the pointer handler, which maps the whole displayed image to decoded source pixels.
    source = page.locator('#sourceImage')
    w, h = source.evaluate('async el => {await el.decode();return [el.naturalWidth,el.naturalHeight]}')
    area = page.locator('#sourceFrame')
    area.evaluate('el=>el.scrollIntoView({block:"center",behavior:"instant"})')
    bounds = area.bounding_box()
    assert bounds and w and h
    edge = width * min(w, h)
    x = bounds['x'] + bounds['width']*cx
    y = bounds['y'] + bounds['height']*cy
    dx, dy = [edge / size * bounds[key] / 2 for size, key in ((w, 'width'), (h, 'height'))]
    page.mouse.move(x-dx, y-dy)
    page.mouse.down()
    page.mouse.move(x+dx, y+dy, steps=6)
    page.mouse.up()
    expect(page.locator('#portraitSubmit')).to_be_enabled(timeout=25000)
    expect(page.locator('#faceBoxes span.frame')).to_have_count(1)
    # Verify the square actually covers the selected quadrant, including after failed conversions.
    selected = page.locator('#faceBoxes span.frame').evaluate(
        'e=>[parseFloat(e.style.left)+parseFloat(e.style.width)/2,'
        'parseFloat(e.style.top)+parseFloat(e.style.height)/2]')
    np.testing.assert_allclose(selected, [100*cx, 100*cy], atol=1)


def capture_stages(page):
    frames = []
    for stage in ('original', 'cleared', 'redrawn'):
        choose(page, 'stage', stage)
        frames.append(frame(page))
    return frames


def engraving(files, live):
    catalog = live['planner']
    seat = catalog['places'][0]
    path = from_files(files, unpack(catalog['transit'])[0])
    part = physical_parts(path, seat, catalog)[2][len(unpack(seat['recut']))-1:]
    samples = check.sample_walk(part, live['groove']/20)
    geom = catalog['geometry']
    angle = geom['angles'][0]
    center = geom['center']*np.array([np.cos(angle), np.sin(angle)])
    return samples[np.linalg.norm(samples-center, axis=1) < geom['scale']*.99]


def distinct_crops(cup_files, bike_files, live):
    cup, bike = [engraving(files, live) for files in (cup_files, bike_files)]
    d = [np.percentile(cKDTree(a).query(b)[0], 90)/live['groove'] for a,b in ((cup,bike),(bike,cup))]
    assert min(d) > .5, ('Crop did not change the physical drawing', d)
    return [round(float(x), 2) for x in d]


def checked_save(page, second, api, before, label, opened, files):
    body, revision = save(page, api)
    motion = body['motion']
    assert motion['zone'] == 'middle' and motion['place'] == 0 and motion.get('fill', False) == opened
    assert files == [(f['name'], f['text'].encode()) for f in motion['files']]
    after = body['state']
    assert before['ids'][1:] == after['ids'][1:]
    assert all(before.get(k) == after.get(k) for k in ('center','portrait','outer','borderGuest'))
    subject = after['ids'][0]
    assert after['labels'][subject] == label and before['ids'][0] != subject
    shape = np.asarray(after['custom'][subject])
    assert shape.ndim == 2 and shape.shape[1] == 2 and len(shape) > 4 and np.isfinite(shape).all()
    caption(second, 'Thomas · ' + label)
    assert drawing_files(second, '#roomFiles') == files
    second.reload()
    caption(second, 'Thomas · ' + label)
    assert drawing_files(second, '#roomFiles') == files
    assert np.array_equal(frame(page), frame(second))
    assert page.request.get(api).json() == {'revision': revision, 'state': after}
    return after


def cancel_photo_drafts(page, second, api, source, saved_files, catalog):
    saved = page.request.get(api).json()
    saved_frame = frame(page)
    saved_subject = saved['state']['ids'][0]
    caption_saved = 'Thomas · ' + saved['state']['labels'][saved_subject]
    choose(page, 'stage', 'redrawn')
    next_caption = page.locator('.caption').inner_text()
    next_files = drawing_files(page, '#downloads')
    next_frame = frame(page)
    choose(page, 'stage', 'original')

    for action in ('close', 'switch zones'):
        select_object(page, source, 'Canceled motorcycle')
        crop(page, .75, .25)
        caption(page, 'Thomas · Canceled motorcycle')
        expect(page.locator('#keep')).to_be_visible()
        if action == 'close':
            page.locator('#centerPhoto > summary').click()
        else:
            choose(page, 'zone', 'center')
            choose(page, 'zone', 'middle')
        expect(page.locator('#guestEditor')).to_be_visible()
        expect(page.locator('#keep')).to_be_hidden()
        expect(page.locator('#downloads')).to_be_hidden()
        expect(page.locator('#portraitFile')).to_have_value('')
        caption(page, caption_saved)
        assert np.array_equal(frame(page), saved_frame)
        assert drawing_files(page, '#roomFiles') == saved_files
        assert page.request.get(api).json() == saved

        # The ordinary Redrawn button must still show the same next picture as before the draft.
        expect(page.locator('input[name=stage][value=redrawn]')).to_be_enabled()
        choose(page, 'stage', 'redrawn')
        expect(page.locator('.caption')).to_have_text(next_caption)
        assert np.array_equal(frame(page), next_frame)
        assert drawing_files(page, '#downloads') == next_files
        choose(page, 'stage', 'original')

    suggest(page, 'a pumpkin for Alex')
    caption(page, 'Alex · Pumpkin')
    expect(page.locator('.caption')).to_contain_text(caption_saved)
    body, revision = save(page, api)
    state = body['state']
    assert body['motion']['place'] == 1 and revision == saved['revision'] + 1
    pumpkin = catalog.get('preferredSubjects', {}).get('pumpkin', 'pumpkin')
    assert state['ids'] == [saved_subject, pumpkin, saved['state']['ids'][2]]
    assert state['custom'] == saved['state']['custom'] and state['labels'] == saved['state']['labels']
    caption(second, 'Alex · Pumpkin')
    caption(second, caption_saved)
    assert np.array_equal(frame(page), frame(second))


def exercise(browser, gallery, source, face, folder, opened):
    errors = []
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp, room(gallery, Path(temp)/'garden.db') as url, \
            browser.new_context(**MOBILE, service_workers='block') as a, browser.new_context(**MOBILE, service_workers='block') as b:
        traffic = PhoneTraffic(url)
        sheet = traffic.photo('subjects.jpg', source.read_bytes(), 'image/jpeg')
        portrait = traffic.photo('person.jpg', face.read_bytes(), 'image/jpeg')
        white = io.BytesIO()
        Image.new('RGB', (190,190), 'white').save(white, format='PNG')
        blank = traffic.photo('blank.png', white.getvalue(), 'image/png')
        for context in (a, b):
            context.route('http**://**/*', traffic.check)
        first, second = a.new_page(), b.new_page()
        for page in (first, second):
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            open_room(page, url)
        api = url + API
        def current():
            return first.request.get(api).json()
        def saved_zones():
            return {zone:first.request.get(api+'/drawings/'+zone).json() for zone in ('center','outer')}

        # Give center and border real, non-default saved movement files.
        for zone in ('center','outer'):
            choose(first, 'zone', zone)
            choose(first, 'stage', 'redrawn')
            keep(first)
        protected = saved_zones()
        assert all(value['revision'] and value['files'] for value in protected.values())
        choose(first, 'zone', 'middle')
        baseline = current()
        before = baseline['state']
        live = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        catalog = live['planner']
        assert before['ids'][0] == (catalog['openSubject'] if opened else 'phage')
        start_writes = traffic.writes
        label = 'Red motorcycle' if opened else 'Photo drawing'
        if opened:
            select_object(first, blank, label)
            expect(first.locator('#portraitStatus')).to_contain_text('clearer outline')
            expect(first.locator('#keep')).to_be_hidden()
            expect(first.locator('#frameFace')).to_have_text('Frame the subject')
        select_object(first, sheet, 'First title' if opened else '')
        report = {}
        if opened:
            crop(first, .75, .75)
            expect(first.locator('#portraitStatus')).to_contain_text('clearer outline')
            expect(first.locator('#keep')).to_be_hidden()
            assert first.locator('#downloads a:visible').count() == 0
            crop(first, .75, .25)
            expect(first.locator('#middleStageLabel')).to_have_text('Halfway')
            expect(first.locator('#lastStageLabel')).to_have_text('Drawn')
            caption(first, 'Thomas · First title')
            original_files = drawing_files(first, '#downloads')
            original_frame = frame(first)
            first.locator('#objectName').fill(label)
            expect(first.locator('#keep')).to_be_hidden()
            expect(first.locator('#faceBoxes span.frame')).to_have_count(1)
            first.locator('#portraitSubmit').click()
            caption(first, 'Thomas · ' + label)
            assert np.array_equal(frame(first), original_frame)
            assert drawing_files(first, '#downloads') == original_files
        else:
            crop(first, .25, .25)
            caption(first, 'Thomas · ' + label)
            cup = drawing_files(first, '#downloads')
            cup_frame = frame(first)
            crop(first, .75, .25)
            caption(first, 'Thomas · ' + label)
            bike = drawing_files(first, '#downloads')
            bike_frame = frame(first)
            report['crop_90th_distance_grooves'] = distinct_crops(cup, bike, live)
            report['changed_sand_pixels'] = int(np.any(cup_frame!=bike_frame,axis=-1).sum())
            assert report['changed_sand_pixels'] > 200
            crop(first, .25, .25)
            assert np.array_equal(cup_frame, frame(first))
            assert [data for _,data in drawing_files(first, '#downloads')] == [data for _,data in cup]
        caption(first, 'Thomas · ' + label)
        expect(first.locator('#keep')).to_have_text('Keep Thomas’s drawing')
        assert first.evaluate('Boolean(window.GuestPhoto && !window.GuestFaceStages && !window.faceapi)')
        assert current() == baseline and traffic.writes == start_writes
        frames = capture_stages(first)
        files = drawing_files(first, '#downloads')
        after = checked_save(first, second, api, before, label, opened, files)
        if opened:
            assert 'First title' not in after['labels'].values()
            report['engraving'] = verify_download(first, folder, before, after, 0, files, frames, live, True)
            select_object(first, sheet, 'Unsaved object name')
            expect(first.locator('#keep')).to_be_visible()
            first.locator('#guestPhotoKind').select_option('face')
            expect(first.locator('#objectName')).to_be_hidden()
            expect(first.locator('#keep')).to_be_hidden()
            first.locator('#portraitFile').set_input_files(portrait)
            first.locator('#portraitSubmit').click()
            caption(first, 'Thomas · Portrait from photo')
            assert first.evaluate('Boolean(window.GuestFaceStages && window.faceapi)')
            expect(first.locator('#keep')).to_have_text('Keep Thomas’s portrait')
            checked_save(first, second, api, after, 'Portrait from photo', False, drawing_files(first, '#downloads'))
        else:
            report['engraving'] = evidence(first, folder, before, after, frames, files, catalog, 0, live)
            cancel_photo_drafts(first, second, api, sheet, files, catalog)
        assert protected == saved_zones()
        assert not traffic.violations and not errors, (traffic.violations, errors)
        report['accepted_writes'] = traffic.writes
        return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('occupied','open','source','face','evidence'):
        p.add_argument(key, type=Path)
    args = p.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            results = {}
            for opened in (False, True):
                name = 'open' if opened else 'occupied'
                results[name] = exercise(browser, getattr(args,name), args.source, args.face, args.evidence/name, opened)
                print(name, json.dumps(results[name]), flush=True)
    (args.evidence/'results.json').write_text(json.dumps(results, indent=2) + '\n')
