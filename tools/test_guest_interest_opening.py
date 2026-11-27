#!/usr/bin/env python3
"""Open three guest places from their interests on two phones and replay the actual queued drawings."""

import argparse
import base64
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import zlib

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from guest_fill_checks import checked_fill, check_tour_leg, original_excursion, tour_legs
from test_attached_garden import Table, served, wait_table
from test_garden_room import API, caption, choose, drawing_files, open_room, suggest
from test_guest_place import contour, contour_samples, unpack
from test_guest_scene_request import regions
from test_ring_faces import ready
from test_ring_guest_border import MOBILE, from_files, preview, replay, save
from test_ring_lettering import rejected, seat_view
from test_ring_object_photo import PhoneTraffic, capture_stages, expand
from test_ring_photo import frame
from test_saved_guest_drawings import ask


EVERYONE = 'draw something for everyone'
OPEN_PLACES = 'draw something for the open places'


def set_guest(page, api, slot, name, interests, vacant):
    expand(page, '#peopleBox')
    page.locator('#personPick').select_option('')
    page.locator('#personName').fill(name)
    page.locator('#personPlace').select_option(str(slot))
    page.locator('#personInterest').fill(interests)
    choices = page.locator('#personDrawing optgroup[label="From their interests"] option').evaluate_all(
        'os=>os.map(o=>o.value)')
    page.locator('#personDrawing').select_option(vacant)
    page.locator('#personSubmit').click()
    body, _ = save(page, api)
    assert body['state']['ids'][slot] == vacant
    return set(choices)


def sketch_mountains(page):
    page.locator('#idea').fill('Mountain range for Mira')
    expand(page, '#sketch')
    pad = page.locator('#sketchPad')
    pad.scroll_into_view_if_needed()
    box = pad.bounding_box()
    # Trace an original ridge around two peaks, returning to the foot of the first.
    peaks = [(-.74,-.43), (-.24,.48), (.02,.03), (.28,.58), (.73,-.43), (-.74,-.43)]
    for i, (x, y) in enumerate(peaks):
        px = box['x'] + (x+1)*box['width']/2
        py = box['y'] + (1-y)*box['height']/2
        page.mouse.move(px, py, steps=8 if i else 1)
        if i == 0:
            page.mouse.down()
    page.mouse.up()
    page.get_by_role('button', name='Preview suggestion').click()
    caption(page, 'Mira · Mountain range')


def verify_engraving(page, route, files, motion, state, slots, live):
    catalog = live['planner']
    parts = motion.get('parts') or [{**motion, 'count': len(files)}]
    assert sorted(part['place'] for part in parts) == slots
    assert all(part.get('fill') for part in parts)
    offset = 0
    legs = tour_legs(catalog, parts) if motion.get('tour') else [None]*len(parts)
    for part, tour_leg in zip(parts, legs):
        slot = part['place']
        subject = state['ids'][slot]
        group = files[offset:offset + part['count']]
        segments = [np.loadtxt(io.BytesIO(raw)) for _, raw in group]
        leg = check.joined(segments, segments[0][0], segments[-1][-1], 'one guest in the opening')
        offset += part['count']
        art = original_excursion(page, catalog, state, slot)
        if tour_leg:
            check_tour_leg(leg, tour_leg, art)
        else:
            checked_fill(leg, catalog, slot, art, part.get('shortFill'))
        if subject not in catalog['subjects']:
            assert subject in state['custom']
            wanted = contour_samples(contour(state, slot, catalog['geometry']), live['groove']/24)
            tree = cKDTree(check.sample_walk(leg, live['groove']/24))
            assert tree.query(wanted)[0].max() < live['groove'] * .15, subject
    assert offset == len(files)
    if motion.get('tour'):
        assert np.max(route[1:-1,1]) < 1-check.TOL, 'The connected trip returned to the dock early.'


def opening(page, url, live, slots, folder, shortcut=False):
    api = url + API
    current = page.request.get(api).json()
    before = current['state']
    vacant = live['planner']['openSubject']
    fixed = [page.request.get(api+'/drawings/'+zone).json() for zone in ('center','outer')]
    assert all(before['ids'][i] == vacant for i in slots)
    if shortcut:
        button = page.get_by_role('button', name='Fill open places from interests')
        button.click()
        expect(page.locator('#keep')).to_be_visible()
    else:
        suggest(page, EVERYONE if len(slots) == 3 else OPEN_PLACES)
    shown_caption = page.locator('.caption').inner_text()
    files = drawing_files(page, '#downloads')
    frames = capture_stages(page)
    assert page.request.get(api).json() == current, 'Previewing the opening changed the shared garden.'
    body, revision = save(page, api)
    state, motion = body['state'], body['motion']
    assert revision == current['revision'] + 1 and motion['zone'] == 'middle'
    assert files == [(item['name'], item['text'].encode()) for item in motion['files']]
    assert [page.request.get(api+'/drawings/'+zone).json() for zone in ('center','outer')] == fixed
    assert all(state[k] == before[k] for k in ('center', 'portrait', 'outer', 'borderGuest'))
    assert [i for i in range(3) if state['ids'][i] != before['ids'][i]] == slots
    route = from_files(files, unpack(live['planner']['transit'])[0])
    verify_engraving(page, route, files, motion, state, slots, live)
    reconstructed = replay(page, before['bed'], *[np.loadtxt(io.BytesIO(raw)) for _,raw in files])
    difference = np.abs(reconstructed.astype(np.int16) - frames[-1].astype(np.int16))
    assert difference.mean() < 1.1 and np.percentile(difference,99) < 6, difference.mean()
    geo = live['planner']['geometry']
    mask, places = regions(len(reconstructed), {'geometry':geo,'groove':live['groove']})
    for i in range(3):
        if i in slots:
            assert np.any(frames[0][places[i]] != frames[-1][places[i]])
        else:
            mask |= places[i]
            old = before['ids'][i]
            if old in before['custom']:
                assert state['custom'][old] == before['custom'][old] and state['labels'][old] == before['labels'][old]
    def bed(s):
        return np.frombuffer(base64.b64decode(s['bed']), np.uint8).reshape(mask.shape)
    assert np.array_equal(bed(before)[mask], bed(state)[mask])
    for img in [*frames[1:], reconstructed]:
        assert np.array_equal(frames[0][mask], img[mask]), 'A protected engraving moved.'
    folder.mkdir(parents=True, exist_ok=True)
    Image.fromarray(reconstructed).save(folder/'finish.png')
    for i in range(3):
        seat_view(reconstructed,geo,i).save(folder/f'chair-{i+1}.png')
    for name, raw in files:
        (folder/name).write_bytes(raw)
    report = dict(ids=state['ids'], changed=slots, caption=shown_caption, protected_pixels=int(mask.sum()),
                  signed_rows=len(route), travel_m=round(float(check.travel(route)[-1]*live['radiusMM']/1000),3),
                  tour=bool(motion.get('tour')), mean_replay_error=round(float(difference.mean()),4))
    (folder/'report.json').write_text(json.dumps(report,indent=2))
    print(report,flush=True)
    return state, files, revision


def original_phage(browser, previous, gallery, database):
    """Reopen an earlier attached room, keep its original art and request that engraving again."""
    table = Table(database)
    with served(previous,database,table,prepared=True) as url, browser.new_page(**MOBILE) as page:
        open_room(page,url)
        live = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        catalog = live['planner']
        assert catalog.get('preferredSubjects', {}).get('phage', 'phage') == 'phage'
        suggest(page, 'draw something for Thomas')
        caption(page, 'Thomas · Bacteriophage')
        files = drawing_files(page, '#downloads')
        body, revision = save(page, url+API)
        original = page.request.get(url+API).json()
        assert original['revision'] == revision and original['state']['ids'][0] == 'phage'
        old_view = frame(page)
        dock = unpack(catalog['transit'])[0]
        verify_engraving(page, from_files(files,dock), files, body['motion'], body['state'], [0], live)

    with served(gallery,database,table) as url, browser.new_page(**MOBILE) as page:
        open_room(page,url)
        caption(page, 'Thomas · Bacteriophage')
        assert page.request.get(url+API).json() == original
        assert drawing_files(page,'#roomFiles') == files and np.array_equal(frame(page),old_view)
        suggest(page,'replace the phage with a guitar')
        caption(page, 'Thomas · Acoustic guitar')
        rejected(page,'replace the faceted phage with a guitar','no longer in the guest ring')
        suggest(page,'an original phage for Alex')
        caption(page, 'Alex · Bacteriophage')
        new_files = drawing_files(page,'#downloads')
        new, new_revision = save(page,url+API)
        assert new_revision == revision + 1 and new['state']['ids'][:2] == ['phage','phage']
        upgraded = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        verify_engraving(page, from_files(new_files,dock), new_files, new['motion'], new['state'], [1], upgraded)

        suggest(page,'a faceted phage for Thomas')
        compact, _ = save(page,url+API)
        assert compact['state']['ids'][:2] == ['phage_faceted','phage']
        rejected(page,'replace the phage with a guitar','two guests')
        suggest(page,'replace the faceted phage with a guitar')
        caption(page, 'Thomas · Acoustic guitar')
        caption(page, 'Alex · Bacteriophage')
        suggest(page,'replace the original phage with a guitar')
        caption(page, 'Thomas · Faceted bacteriophage')
        caption(page, 'Alex · Acoustic guitar')
        replaced, _ = save(page,url+API)
        assert replaced['state']['ids'][:2] == ['phage_faceted','guitar_silhouette']
        rejected(page,'replace the original bacteriophage with a guitar','no longer in the guest ring')
        suggest(page,'replace the phage with a guitar')
        caption(page,'Thomas · Acoustic guitar')
        final, last_revision = save(page,url+API)
        assert final['state']['ids'][:2] == ['guitar_silhouette','guitar_silhouette']

        jobs = [*live['setup']]
        for saved in (body,new,compact,replaced,final):
            jobs.extend(saved['motion']['files'])
        for i,job in enumerate(jobs,1):
            assert table.dispatched(i) == job
            table.outcome = 'complete'
        wait_table(page,url,state='idle',ready=True,queued=0,revision=last_revision)
        assert len(table.calls) == len(jobs)
        print(f'Original phage kept its saved file and sand through the upgrade. Both original '
              f'engravings matched the older gallery. Generic and exact phage replacements found the '
              f'correct guests. All {len(jobs)} files played once.', flush=True)


def exercise(browser, gallery, db, photo, output):
    table = Table(db)
    with served(gallery,db,table,prepared=True) as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        api = url + API
        traffic = PhoneTraffic(url)
        for ctx in (a,b):
            ctx.route('http**://**/*', traffic.check)
        host, guest = a.new_page(), b.new_page()
        errors = []
        for page in (host,guest):
            page.on('pageerror',lambda err: errors.append(str(err)))
        open_room(host,url)
        source = traffic.photo(photo.name, photo.read_bytes(), 'image/jpeg')
        choose(host,'zone','center')
        expand(host,'#centerPhoto')
        host.locator('#portraitFile').set_input_files(source)
        host.locator('#portraitSubmit').click()
        ready(host)
        assert save(host,api)[0]['state']['portrait']
        choose(host,'zone','outer')
        preview(host,4,'Lek',order='progressive')
        save(host,api)
        choose(host,'zone','middle')
        live = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        vacant=live['planner']['openSubject']
        family, first, family_rev = opening(host,url,live,[0,1,2],output/'family')
        preferred = live['planner'].get('preferredSubjects', {})
        assert family['ids'] == [preferred.get('phage','phage'), 'books_open', 'temple_gable'], family['ids']
        open_room(guest,url)
        assert drawing_files(guest,'#roomFiles') == first and np.array_equal(frame(guest),frame(host))

        available = []
        for slot,(name,interest) in enumerate([('Mira','stargazing'),('Rowan','loves astronomy'),('Sam','plays guitar')]):
            available.append(set_guest(guest,api,slot,name,interest,vacant))
        assert available[0] == available[1] and len(available[0]) >= 2
        assert 'telescope' in available[0] and 'guitar_silhouette' in available[2]
        host.goto('about:blank')
        open_room(host,url)
        changed, new_group, group_rev = opening(host,url,live,[0,1,2],output/'new-guests')
        subjects = changed['ids']
        assert all(subject in candidates for subject,candidates in zip(subjects,available))
        assert len(set(subjects)) == 3, 'Guests with shared interests were given duplicate pictures.'
        assert changed['guestBook']['active'] == ['mira', 'rowan', 'sam']
        guest.goto('about:blank')
        open_room(guest,url)
        assert drawing_files(guest,'#roomFiles') == new_group
        suggest(guest,'clear all three guest places')
        save(guest,api)
        sketch_mountains(guest)
        sketch = save(guest,api)[0]['state']['ids'][0]
        expand(guest,'#centerPhoto')
        guest.locator('#portraitPlace').select_option('2')
        guest.locator('#portraitFile').set_input_files(source)
        guest.locator('#portraitName').fill('Alex')
        guest.locator('#portraitSubmit').click()
        ready(guest)
        caption(guest,'Sam · Portrait of Alex')
        portrait = save(guest,api)[0]['state']['ids'][2]
        host.goto('about:blank')
        open_room(host,url)
        # First preview by typing, then discard it and use the one-tap equivalent.
        suggest(host,OPEN_PLACES)
        typed = drawing_files(host,'#downloads')
        host.goto('about:blank')
        open_room(host,url)
        filled, one, last_rev = opening(host,url,live,[1],output/'open-only',shortcut=True)
        assert typed == one and filled['ids'] == [sketch,filled['ids'][1],portrait]
        assert filled['ids'][1] in available[1]
        assert not errors and not traffic.violations, (errors,traffic.violations)
        unchanged = host.request.get(api).json()
        ask(host,OPEN_PLACES)
        expect(host.locator('#keep')).to_be_hidden()
        expect(host.get_by_role('button',name='Fill open places from interests')).to_be_hidden()
        assert host.request.get(api).json() == unchanged

    with served(gallery,db,table) as url,browser.new_page(**MOBILE) as returning:
        open_room(returning,url)
        assert returning.request.get(url+API).json()['state'] == filled
        assert drawing_files(returning,'#roomFiles') == one
        with closing(sqlite3.connect(db)) as conn:
            parts = [(rev,name,zlib.decompress(raw)) for rev,name,raw in conn.execute(
                'SELECT revision,name,track FROM playback_part ORDER BY revision,part')]
        for rev,files in [(family_rev,first),(group_rev,new_group),(last_rev,one)]:
            assert [(name,raw) for actual,name,raw in parts if actual==rev] == files
        for i,(_,name,raw) in enumerate(parts,1):
            assert table.dispatched(i) == dict(name=name,text=raw.decode('ascii'))
            table.outcome = 'complete'
        wait_table(returning,url,state='idle',ready=True,queued=0,revision=last_rev)
        assert len(table.calls) == len(parts)
        print(f'{len(parts)} queued files played exactly once in order across restart.', flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('photo',type=Path,help='A local JPEG of Alex with one detected face.')
    parser.add_argument('--evidence',type=Path)
    parser.add_argument('--previous',type=Path,help='An earlier fitted gallery that recommended the original phage.')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            if args.previous:
                original_phage(browser, args.previous, args.gallery, Path(tmp)/'previous.db')
            exercise(browser,args.gallery,Path(tmp)/'room.db',args.photo,args.evidence or Path(tmp))
