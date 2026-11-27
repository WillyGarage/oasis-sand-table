#!/usr/bin/env python3
"""Replay real guest requests after replacing a phone gallery with different table measurements.

    python3 tools/test_ring_dimensions.py --evidence captures/measured-table/identity

Builds four local gardens. The only attached table in this test is the in-memory test controller.
"""
import argparse
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from unittest.mock import patch

import numpy as np
from playwright.sync_api import expect, sync_playwright

import check_ring_scene
import ring_preview
import ring_scene
from garden_room import load_gallery
from test_attached_garden import Table, refused, served
from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_lettering import rejected
from test_ring_photo import frame

SETTINGS = {
    'original': (450, 5, 2.5, 4, 2),
    'reference': (405, 4.5, 2.25, 3.6, 1.8),
    'proportional': (360, 4, 2, 3.2, 1.6),
    'wider': (420, 6, 3.5, 4, 2),
}
REQUEST = 'write “Thomas” for Alex'


def galleries(folder):
    paths = {}
    for name,(radius,groove,margin,pitch,guest_pitch) in SETTINGS.items():
        directory = folder/name
        ring_scene.build(directory,radius,groove,margin,pitch,open_guests=True,face_edge=True,guest_pitch_mm=guest_pitch)
        page = directory/'garden.html'
        ring_preview.build(directory/'scene.json',page,630)
        paths[name] = page
    return paths


def private_gallery(page, gallery, same_url):
    # On an actual phone, replacing the file at the same address preserves browser storage.
    page.goto('about:blank')
    shutil.copyfile(gallery,same_url)
    page.goto(same_url.resolve().as_uri()+'#guests')
    return page.evaluate("JSON.parse(document.getElementById('scene').textContent).live")


def check_private(browser, pages, folder, tmp):
    reports, moves = {}, {}
    with browser.new_context(**MOBILE) as phone:
        page = phone.new_page()
        target = tmp/'dinner.html'
        for name,path in pages.items():
            live = private_gallery(page,path,target)
            radius,groove,margin,*_ = SETTINGS[name]
            np.testing.assert_allclose((live['radiusMM'],live['groove']*radius), (radius,groove), atol=1e-12,rtol=0)
            original_bed = base64.b64decode(live['bed'])
            if name=='original':
                historical = hashlib.sha256(b'facing-guests\0'+original_bed).hexdigest()[:16]
                assert live['edition']==historical and 'legacyBedEdition' not in live
                assert live['storageKey']=='oasis-ring-garden-open-v1-facing-guests-'+historical
            setup = page.locator('#setupFiles')
            setup.locator('summary').click()
            dimensions = page.locator('#tableDimensions')
            expect(dimensions).to_be_visible()
            expect(dimensions).to_contain_text(f'{radius} mm radius')
            expect(dimensions).to_contain_text(f'Groove width {groove} mm')
            expect(dimensions).to_contain_text(f'Allows {margin:g} mm on either side')
            setup.locator('summary').click()
            caption(page,'Alex · Open place')
            assert not page.locator('#reset').is_visible(), 'This phone restored a drawing for a different physical size.'
            choose(page,'zone','center')
            center = page.evaluate("JSON.parse(document.getElementById('scene').textContent).zones.center.transit.at(-1)[1]")
            expect(page.locator('header p').first).to_contain_text(f'{2*center*radius/25.4:.1f}-inch center')
            choose(page,'zone','middle')
            if name=='wider':
                rejected(page,REQUEST,r'shorter|initials')
                suggest(page,'write “Hi” for Alex')
                caption(page,'Alex · “Hi”')
            else:
                suggest(page,REQUEST)
                caption(page,'Alex · “Thomas”')
            files = drawing_files(page,'#downloads')
            moves[name] = files
            zoom = page.locator('#guestZoom')
            zoom.click()
            expect(zoom).to_have_attribute('aria-pressed','true')
            page.locator('.bowl').screenshot(path=str(folder/name/'alex-seat.png'))
            track = from_files(files, ring_scene.DOCK)
            reports[name] = {
                'radius_mm':radius, 'groove_mm':groove, 'storage_key':live['storageKey'], 'edition':live['edition'],
                'starting_sand_sha256':hashlib.sha256(original_bed).hexdigest(),
                'route_mm':round(float(check_ring_scene.travel(track)[-1]*radius),2),
                'files':[hashlib.sha256(data).hexdigest() for _,data in files],
            }
            page.locator('#keep').click()
            expect(page.locator('#keep')).to_be_hidden()
            if name=='reference':
                page.reload()
                caption(page,'Alex · “Thomas”')
                saved_reference = frame(page)
            if name=='proportional':
                suggest(page,'a guitar for Thomas')
                page.locator('#keep').click()
                expect(page.locator('#keep')).to_be_hidden()
        for name in pages:
            private_gallery(page,pages[name],target)
            caption(page,'Alex · “Hi”' if name=='wider' else 'Alex · “Thomas”')
            if name=='reference':
                assert np.array_equal(frame(page),saved_reference)
                caption(page,'Thomas · Open place')
            if name=='proportional':
                caption(page,'Thomas · Acoustic guitar')
        old_private_key(page,pages['proportional'],target)
        assert len({r['edition'] for r in reports.values()}) == len(SETTINGS)
        assert len({r['storage_key'] for r in reports.values()}) == len(SETTINGS)
        assert reports['reference']['starting_sand_sha256']==reports['proportional']['starting_sand_sha256']
        assert moves['reference']==moves['proportional'], 'Proportional physical settings should have identical normalized movement.'
        scale = SETTINGS['proportional'][0]/SETTINGS['reference'][0]
        assert np.isclose(reports['proportional']['route_mm']/reports['reference']['route_mm'],scale,atol=1e-5)
    return reports


def old_private_key(page, gallery, target):
    live = private_gallery(page,gallery,target)
    key,old_key = live['storageKey'],live['legacyStorageKey']
    get = lambda k: page.evaluate('(k)=>JSON.parse(localStorage.getItem(k))', k)
    saved = get(key)
    saved_frame = frame(page)
    bed_only = hashlib.sha256(b'facing-guests\0'+base64.b64decode(live['bed'])).hexdigest()[:16]
    for edition in (bed_only,live['previousEdition']):
        prior = dict(saved,edition=edition)
        page.evaluate("""([key,oldKey,prior])=>{
            localStorage.removeItem(key); localStorage.setItem(oldKey,JSON.stringify(prior));
        }""",[key,old_key,prior])
        page.reload()
        assert get(old_key)==prior
        if edition==bed_only:
            caption(page,'Thomas · Open place')
            assert get(key) is None
        else:
            caption(page,'Thomas · Acoustic guitar')
            assert get(key)==saved and np.array_equal(frame(page),saved_frame)
    page.locator('#reset').click()
    page.reload()
    caption(page,'Thomas · Open place')
    assert get(old_key)==prior and page.evaluate('(k)=>localStorage.getItem(k)',key)=='null'


def legacy_gallery(current, destination):
    # Reproduce the previously shipped bed-only edition, without changing any physical
    # parameter, drawing file, initial bed or browser entry point.
    before,marker,rest = current.read_text().partition('<script type="application/json" id="scene">')
    assert marker
    raw,close,after = rest.partition('</script>')
    scene = json.loads(raw)
    live = scene['live']
    live['edition'] = hashlib.sha256(b'facing-guests\0'+base64.b64decode(live['bed'])).hexdigest()[:16]
    live.pop('legacyBedEdition',None)
    live['radiusMM'] = float(live['radiusMM'])  # Earlier CLI gallery serialized the same radius as 360.0.
    destination.write_text(before+marker+json.dumps(scene,separators=(',',':'))+close+after)


def reimport_old_guest_placement(pages, folder):
    # Prior software cut exactly the historical 450/5 normalized layout at the
    # proportional 360/4 settings. Load those actual movements through today's
    # importer, just as an owner would reopen their saved scene.json.
    base = pages['original'].parent
    radius,groove,margin,pitch,guest_pitch = SETTINGS['proportional']
    old = json.loads((base/'scene.json').read_text())
    assert 'guest_clearance_mm' not in old
    np.testing.assert_allclose([old['groove_width'],old['tracking_margin'],old['erase_pitch'],
                                old['zones']['middle']['erase_pitch']],
                               np.array([groove,margin,pitch,guest_pitch])/radius,rtol=1e-12)
    old['assumed_working_radius_mm'] = radius
    source = folder/'saved-scene.json'
    source.write_text(json.dumps(old,separators=(',',':'))+'\n')
    for part in old['setup']:
        shutil.copyfile(base/part,folder/part)
    page = folder/'original-360-opening.html'
    ring_preview.build(source,page,630)
    return page


def shared(browser, pages, folder):
    db = folder/'room.db'
    with browser.new_context(**MOBILE) as phone:
        page = phone.new_page()
        with room(pages['reference'],db) as url:
            open_room(page,url)
            suggest(page,REQUEST)
            prior,_ = save(page,url+API)
            original = page.request.get(url+API).json()
        for name in ('original','proportional','wider'):
            refused(pages[name],db,'Different gallery edition')
            with room(pages[name],folder/(name+'.db')) as url:
                open_room(page,url)
                caption(page,'Alex · Open place')
                response=page.request.put(url+API,headers={'Origin':url},data=prior)
                assert response.status==400 and page.request.get(url+API).json()=={'state':None,'revision':0}
                if name=='wider':
                    rejected(page,REQUEST,r'shorter|initials')
                suggest(page,'a guitar for Thomas')
                save(page,url+API)
                page.reload()
                caption(page,'Thomas · Acoustic guitar')
        with room(pages['reference'],db) as url:
            open_room(page,url)
            caption(page,'Alex · “Thomas”')
            assert page.request.get(url+API).json()==original


def occupied_clearance(browser, gallery, folder):
    with room(gallery,folder/'clearance.db') as url, browser.new_context(**MOBILE) as phone:
        page = phone.new_page()
        open_room(page,url)
        live = page.evaluate("JSON.parse(document.getElementById('scene').textContent).live")
        geom = live['planner']['geometry']
        radius,groove,margin,*_ = SETTINGS['wider']
        people = ('Thomas','Alex','Lek')
        for slot,subject in enumerate(('bacteriophage','calendar','Thai rooftop')):
            suggest(page,f'a {subject} for {people[slot]}')
            body,_ = save(page,url+API)
            assert body['motion'].get('fill') and body['motion']['place']==slot
        runs = []
        for slot,subject in enumerate(('guitar','stack of books','guitar')):
            suggest(page,f'a {subject} for {people[slot]}')
            files = drawing_files(page,'#downloads')
            body,_ = save(page,url+API)
            assert body['motion'].get('place')==slot and not body['motion'].get('fill')
            assert files==[(f['name'],f['text'].encode()) for f in body['motion']['files']]
            for name,data in files:
                (gallery.parent/(people[slot]+'-'+Path(name).name)).write_bytes(data)
            path = from_files(files,ring_scene.DOCK)
            step = groove/48
            points = check_ring_scene.sample_walk(path,step/radius)*radius
            by_neighbor = {}
            for neighbor,angle in enumerate(geom['angles']):
                if neighbor==slot:
                    continue
                center = radius*geom['center']*np.array([np.cos(angle),np.sin(angle)])
                # Subtract half the maximum spacing for a lower bound over the
                # continuous signed movement, and allow both drawings to drift.
                lower = np.linalg.norm(points-center,axis=1).min()-radius*geom['scale']-step/2
                surviving = lower-2*margin
                assert surviving>1.65*groove,(people[slot],people[neighbor],surviving,groove)
                by_neighbor[people[neighbor]] = round(surviving,3)
            runs.append({'guest':people[slot],'clear_after_drift_mm':by_neighbor})
        return runs


def guest_style_requests(browser, gallery, folder):
    with room(gallery,folder/'styles.db') as url, browser.new_context(**MOBILE) as phone:
        page = phone.new_page()
        open_room(page,url)
        page.locator('#peopleBox > summary').click()
        for interest,choice in [('teacher','books_open'),('guitarist','guitar_silhouette'),('Thai architecture','temple_gable')]:
            page.locator('#personInterest').fill(interest)
            expect(page.locator('#personDrawing')).to_have_value(choice)
        page.locator('#peopleBox > summary').click()

        def draw(request, slot, expected):
            suggest(page,request)
            accepted,_ = save(page,url+API)
            assert accepted['state']['ids'][slot] == expected, request

        draw('a stack of books for Alex',1,'books')
        draw('books for Thomas',0,'books_open')
        rejected(page,'replace the books with a rocket','two guests')
        draw('replace the stack of books with a Thai rooftop',1,'temple_gable')
        draw('replace the open book with a guitar',0,'guitar_silhouette')
        draw('a guitar leaning against my books for Lek',2,'guitar_books')
        draw('replace the Thai rooftop with a telescope',1,'telescope')


def same_setup_different_guest_size(browser, gallery, folder):
    # Produce a valid second planner whose disc is smaller but whose empty setup
    # and background rails are identical. A bed-only binding cannot identify its art.
    current_geometry = ring_scene.guest_geometry
    def smaller(*args,**kwargs):
        geometry = current_geometry(*args,**kwargs)
        return dict(geometry,scale=.91*geometry['scale'])
    radius,groove,margin,pitch,guest_pitch = SETTINGS['proportional']
    alternate = folder/'smaller'
    with patch.object(ring_scene,'guest_geometry',side_effect=smaller):
        ring_scene.build(alternate,radius,groove,margin,pitch,open_guests=True,
                         face_edge=True,guest_pitch_mm=guest_pitch)
    measured,legacy = alternate/'measured.html',alternate/'legacy.html'
    ring_preview.build(alternate/'scene.json',measured,630)
    legacy_gallery(measured,legacy)
    current = load_gallery(gallery)[1]['garden']
    small = load_gallery(measured)[1]['garden']
    assert current.setup==small.setup and current.initial['bed']==small.initial['bed']
    assert small.scale<current.scale and small.edition!=current.edition
    db = folder/'identical-setup.db'
    table = Table(db)
    with served(legacy,db,table,prepared=True) as url, browser.new_context(**MOBILE) as phone:
        page = phone.new_page()
        open_room(page,url)
        table.dispatched(1)
        suggest(page,'a guitar for Thomas')
        save(page,url+API)
    before = binding(db),queue(db)
    refused(gallery,db,'physical layout',controller=table,table_layout='garden')
    assert (binding(db),queue(db))==before and len(table.calls)==1


def binding(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT board,geometry FROM attachment WHERE id=1').fetchone()


def queue(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute('SELECT * FROM playback_part ORDER BY revision,part').fetchall()


def legacy_attachment(browser, pages, folder):
    same_movements = reimport_old_guest_placement(pages,folder)
    legacy = folder/'pre-dimensions.html'
    legacy_gallery(same_movements,legacy)
    old_spec = load_gallery(legacy)[1]['garden']
    new_spec = load_gallery(pages['proportional'])[1]['garden']
    assert new_spec.scale < old_spec.scale and new_spec.legacy_bed_edition is None
    db = folder/'bound.db'
    table = Table(db)
    with browser.new_context(**MOBILE) as phone:
        page = phone.new_page()
        target = folder/'saved-private.html'
        private_gallery(page,same_movements,target)
        suggest(page,'a guitar for Thomas')
        page.locator('#keep').click()
        expect(page.locator('#keep')).to_be_hidden()
        old_private_key(page,same_movements,target)
        private_gallery(page,pages['proportional'],target)
        caption(page,'Thomas · Open place')
        with served(legacy,db,table,prepared=True) as url:
            open_room(page,url)
            table.dispatched(1)
            suggest(page,REQUEST)
            prior,revision = save(page,url+API)
            old = page.request.get(url+API).json()
            old_files = drawing_files(page,'#roomFiles')
        old_binding = binding(db)
        old_queue = queue(db)
        for name in pages:
            refused(pages[name],db,'physical layout',controller=table,table_layout='garden')
        other = Table(db)
        other.identity = 'different-device'
        refused(same_movements,db,'different physical table',controller=other,table_layout='garden')
        assert not other.calls and binding(db)==old_binding and queue(db)==old_queue
        damaged = folder/'damaged.db'
        shutil.copyfile(db,damaged)
        with closing(sqlite3.connect(damaged)) as conn, conn:
            conn.execute('UPDATE garden SET state=? WHERE layout=?',
                         (json.dumps(dict(old['state'],outer=-2)),'garden'))
        refused(same_movements,damaged,'Invalid selection',controller=Table(damaged),table_layout='garden')
        assert binding(damaged)==old_binding and queue(damaged)==old_queue
        with served(same_movements,db,table) as url:
            open_room(page,url)
            caption(page,'Alex · “Thomas”')
            upgraded = page.request.get(url+API).json()
            edition = page.evaluate("JSON.parse(document.getElementById('scene').textContent).live.edition")
            assert upgraded==dict(old,state=dict(old['state'],edition=edition)) and old['state']['edition']!=edition
            assert drawing_files(page,'#roomFiles')==old_files and binding(db)!=old_binding
            assert queue(db)==old_queue and len(table.calls)==1
            response=page.request.put(url+API,headers={'Origin':url},data=dict(prior,revision=revision))
            assert response.status==400 and page.request.get(url+API).json()==upgraded
            suggest(page,'books for Thomas')
            save(page,url+API)
            assert len(queue(db))>len(old_queue)
        # Once a room has measured geometry, its original gallery still cannot draw on another profile.
        refused(pages['reference'],db,'physical layout',controller=table,table_layout='garden')
        with served(same_movements,db,table) as url:
            open_room(page,url)
            caption(page,'Thomas · Stack of books')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--evidence',type=Path,required=True)
    args = cli.parse_args()
    args.evidence.mkdir(parents=True,exist_ok=True)
    paths = galleries(args.evidence)
    with tempfile.TemporaryDirectory() as work, sync_playwright() as pw:
        tmp = Path(work)
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            reports=check_private(browser,paths,args.evidence,tmp)
            shared(browser,paths,tmp)
            legacy_attachment(browser,paths,tmp)
            same_setup_different_guest_size(browser,paths['proportional'],tmp)
            reports['wider']['occupied_changes'] = occupied_clearance(browser,paths['wider'],tmp)
            guest_style_requests(browser,paths['wider'],tmp)
    (args.evidence/'report.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps(reports,indent=2))


if __name__=='__main__':
    main()
