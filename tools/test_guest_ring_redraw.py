#!/usr/bin/env python3
"""Check both redraw choices in a private phone gallery and on an attached simulated table."""
import argparse
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

from test_attached_garden import Table, served, wait_table
from test_garden_room import API, caption, choose, drawing_files, open_room, suggest
from test_guest_scene_request import BATCH, regions
from test_ring_guest_border import MOBILE, save
from test_ring_object_photo import expand, select_object
from test_ring_photo import frame


def downloads(page):
    return [{'name': name, 'text': data.decode()} for name, data in drawing_files(page, '#downloads')]


def whole_files(page, ids, custom=None):
    return page.evaluate('''([ids,custom])=>{
      const catalog=JSON.parse(document.querySelector('#scene').textContent).live.planner;
      return OasisRingPlanner.files(OasisRingPlanner.plan(catalog,ids,custom).path);
    }''', [ids, custom or {}])


def private_phone(page, gallery, folder, screenshot):
    page.goto(gallery.resolve().as_uri()+'#guests')
    redraw = page.locator('#guestRedraw')
    suggest(page,BATCH)
    expect(redraw).to_be_hidden()
    page.locator('#keep').click()
    expect(page.locator('#keep')).to_be_hidden()
    before = frame(page)
    live = page.evaluate('''()=>{
      const l=JSON.parse(document.querySelector('#scene').textContent).live;
      return {groove:l.groove, geometry:l.planner.geometry};
    }''')
    protected, seats = regions(len(before),live)
    suggest(page,'a guitar for Thomas')
    expect(redraw).to_have_value('place')
    local = downloads(page)
    select_end = frame(page)
    redraw.select_option('ring')
    caption(page,'redraws all three guest drawings. The center and border stay visible.')
    whole = downloads(page)
    assert whole == whole_files(page,['guitar_silhouette','books_open','temple_gable']) and whole != local
    assert np.array_equal(frame(page)[protected],before[protected])
    choose(page,'stage','cleared')
    caption(page,'The whole middle ring is clear.')
    erased = frame(page)
    assert np.array_equal(erased[protected],before[protected])
    assert all(np.any(erased[mask]!=before[mask]) for mask in seats)
    if screenshot:
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=screenshot)
    choose(page,'stage','original')
    expect(redraw).to_have_value('ring')
    redraw.select_option('place')
    choose(page,'stage','redrawn')
    assert downloads(page) == local and np.array_equal(frame(page),select_end)
    assert all(np.array_equal(select_end[mask],before[mask]) for mask in seats[1:])
    redraw.select_option('ring')
    expect(page.locator('#downloads a')).to_have_count(0)
    suggest(page,'a pumpkin for Alex')
    expect(redraw).to_have_value('place')
    suggest(page,'a guitar for Thomas and a pumpkin for Alex')
    expect(redraw.locator('option:checked')).to_have_text('One guest’s place at a time')
    local_pair = downloads(page)
    assert np.array_equal(frame(page)[seats[2]],before[seats[2]])
    choose(page,'stage','cleared')
    expect(page.locator('#guestMoments')).to_be_visible()
    assert np.array_equal(frame(page)[seats[2]],before[seats[2]])
    redraw.select_option('ring')
    expect(page.locator('#guestMoments')).to_be_hidden()
    assert np.array_equal(frame(page),erased)
    choose(page,'stage','redrawn')
    caption(page,'redraws all three guest drawings. The center and border stay visible.')
    assert np.array_equal(frame(page)[protected],before[protected])
    assert downloads(page) == whole_files(page,['guitar_silhouette','pumpkin_ribbed','temple_gable'])
    if screenshot:
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=screenshot.with_name(screenshot.stem+'-two-guests'+screenshot.suffix))
    redraw.select_option('place')
    assert downloads(page)==local_pair
    choose(page,'stage','cleared')
    expect(page.locator('#guestMoments')).to_be_visible()
    suggest(page,'a guitar for Thomas, a pumpkin for Alex and books for Lek')
    caption(page,'clears and redraws the whole guest ring')
    expect(redraw).to_be_hidden()
    suggest(page,'add a crescent to Lek’s roof')
    expect(redraw).to_be_hidden()
    expand(page,'#peopleBox')
    page.locator('#personName').fill('Mira')
    page.locator('#personInterest').fill('Microbiology')
    page.locator('#personDrawing').select_option('phage_faceted')
    page.locator('#personSubmit').click()
    expect(page.locator('#keep')).to_have_text('Keep guest')
    expect(redraw).to_be_hidden()
    page.locator('#peopleBox > summary').click()

    # The photograph is synthetic and never leaves the private gallery.
    artwork = Image.new('RGB',(420,420),'white')
    pen = ImageDraw.Draw(artwork)
    pen.ellipse((105,55,310,280),outline='black',width=12)
    pen.line([(210,280),(198,340),(222,380)],fill='black',width=10)
    photo = folder/'balloon.png'
    artwork.save(photo)
    select_object(page,photo,'Birthday balloon')
    expect(redraw).to_have_value('place')
    page.locator('#drawingInterests').fill('Birthdays')
    redraw.select_option('ring')
    expect(page.locator('#keep')).to_have_text('Keep Thomas’s drawing')
    expect(page.locator('#drawingInterests')).to_have_value('Birthdays')
    page.locator('#keep').click()
    expect(page.locator('#keep')).to_be_hidden()
    caption(page,'Birthday balloon')
    page.locator('#layout').select_option('portrait')
    expect(redraw).to_be_hidden()


def attached_phones(host, guest, gallery, folder):
    db = folder/'garden.db'
    table = Table(db)
    with served(gallery,db,table,prepared=True) as url:
        open_room(host,url)
        api = url+API
        jobs = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
        def queue(page):
            body, revision = save(page,api)
            jobs.extend(body['motion']['files'])
            return body, revision

        suggest(host,'a guitar for Thomas and books for Alex')
        queue(host)
        suggest(host,'a phage for Thomas')
        host.locator('#guestRedraw').select_option('ring')
        caption(host,'redraws both guest drawings')
        partial, _ = queue(host)
        assert partial['motion'] == {'zone':'middle','files':whole_files(host,partial['state']['ids'])}
        suggest(host,'a Thai rooftop for Lek')
        expect(host.locator('#guestRedraw')).to_be_hidden()
        queue(host)
        open_room(guest,url)
        suggest(host,'a guitar for Thomas')
        redraw = host.locator('#guestRedraw')
        redraw.select_option('ring')
        stale = downloads(host)
        suggest(guest,'a pumpkin for Alex')
        newer, revision = queue(guest)
        expect(host.locator('#roomReload')).to_be_visible(timeout=10000)
        host.locator('#keep').click()
        expect(host.locator('#roomReload')).to_be_visible()
        assert host.request.get(api).json() == {'revision':revision,'state':newer['state']}
        host.locator('#roomReload').click()
        expect(host.locator('#roomReload')).to_be_hidden()
        suggest(host,'a guitar for Thomas')
        expect(redraw).to_have_value('place')
        redraw.select_option('ring')
        fresh = downloads(host)
        assert fresh != stale
        final, revision = queue(host)
        ids = final['state']['ids']
        assert ids == ['guitar_silhouette',*newer['state']['ids'][1:]]
        assert final['motion'] == {'zone':'middle','files':fresh} and fresh == whole_files(host,ids)
        assert host.request.get(api+'/drawings/middle').json()['files'] == fresh
        suggest(host,'add a music note to Thomas’s guitar and a crescent to Lek’s roof')
        expect(redraw).to_be_hidden()
        suggest(host,'a phage for Thomas and books for Alex')
        expect(redraw).to_have_value('place')
        pair_local = downloads(host)
        redraw.select_option('ring')
        pair_whole = downloads(host)
        pair, revision = queue(host)
        ids = pair['state']['ids']
        assert ids == ['phage_faceted','books_open','temple_gable']
        assert pair['motion'] == {'zone':'middle','files':pair_whole}
        assert pair_whole == whole_files(host,ids) and pair_whole!=pair_local
        suggest(host,'a guitar for Thomas and a pumpkin for Alex')
        expect(redraw).to_have_value('place')
        pair_local = downloads(host)
        separate, revision = queue(host)
        assert sorted(part['place'] for part in separate['motion']['parts'])==[0,1]
        assert separate['motion']['files']==pair_local
        assert separate['state']['ids']==['guitar_silhouette','pumpkin_ribbed','temple_gable']
        for number, motion in enumerate(jobs,1):
            assert table.dispatched(number) == motion
            table.outcome = 'complete'
        wait_table(host,url,ready=True,queued=0,revision=revision)
        assert len(table.calls)==len(jobs)


if __name__=='__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('gallery',type=Path,help='fitted three-place open garden with the wide companion layout')
    cli.add_argument('--screenshot',type=Path)
    args = cli.parse_args()
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        folder = Path(temp)
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=chrome) as browser:
            with browser.new_page(**MOBILE) as private:
                private_phone(private,args.gallery,folder,args.screenshot)
            with browser.new_page(**MOBILE) as host,browser.new_page(**MOBILE) as guest:
                attached_phones(host,guest,args.gallery,folder)
    print('Verified local and whole-ring files, protected zones, guest photos and stale two-phone requests.')
