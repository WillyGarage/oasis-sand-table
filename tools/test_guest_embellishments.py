#!/usr/bin/env python3
"""Exercise additive guest drawings on two mobile browsers, including an existing shared garden."""
import argparse
import base64
import io
import tempfile
from pathlib import Path

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_scene_request import regions
from test_ring_guest_border import MOBILE, replay, save
from test_ring_object_photo import expand
from test_ring_photo import frame
from check_ring_scene import joined, sample_walk
from thrcommon import unpack_path

GUITAR = 'guitar_silhouette'
BOOK = 'books_open'
ROOF = 'temple_gable'
NOTE = 'guitar_note'
PENCIL = 'book_pencil'
MOON = 'temple_crescent'


def reject(page, api, text, message):
    original = page.request.get(api).json()
    page.locator('#idea').fill(text)
    page.get_by_role('button',name='Preview suggestion').click()
    expect(page.locator('#error')).to_contain_text(message)
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#downloads')).to_be_hidden()
    expect(page.locator('input[name=stage][value=original]')).to_be_checked()
    assert page.request.get(api).json() == original


def base_garden(page, url):
    api = url+API
    open_room(page,url)
    suggest(page,'a guitar for Thomas, books for Alex and a Thai rooftop for Lek')
    payload,_ = save(page,api)
    assert payload['state']['ids'][::2] == [GUITAR,ROOF]
    expand(page,'#peopleBox')
    page.locator('#personName').fill('Mae Lin')
    page.locator('#personInterest').fill('Guitar')
    page.locator('#personPlace').select_option('0')
    page.locator('#personDrawing').select_option(GUITAR)
    page.locator('#personSubmit').click()
    payload,_=save(page,api)
    assert payload['state']['guestBook']['active'][0]=='mae lin'
    return payload['state']


def replay_addition(page, state, live, places, final):
    before=frame(page)
    choose(page,'stage','redrawn')
    files=drawing_files(page,'#downloads')
    parts=[np.loadtxt(io.BytesIO(raw)) for _,raw in files]
    after=frame(page)
    rebuilt=replay(page,state['bed'],*parts)
    delta=np.abs(rebuilt.astype(float)-after)
    assert delta.mean()<1.1 and np.percentile(delta,99)<5
    protected, seats=regions(len(after),live)
    y,x=np.mgrid[-1:1:complex(len(after)),-1:1:complex(len(after))]
    groove=live['groove']
    route=joined(parts,parts[0][0],parts[0][0],'phone addition')
    travel=cKDTree(sample_walk(route,groove/10))
    for i,mask in enumerate(seats):
        if i in places:
            assert np.any(before[mask]!=after[mask]), ('no new drawing',i)
            # Include actual grooves of the existing picture inside this edited
            # seat. The ride back over a stem and into the new ornament is allowed.
            source=cKDTree(sample_walk(unpack_path(live['excursions'][i][state['ids'][i]]),groove/10))
            pixels=np.column_stack((x[mask],-y[mask]))
            old_ink=source.query(pixels)[0]<groove*.45
            undisturbed=old_ink & (travel.query(pixels)[0]>2*groove)
            assert undisturbed.sum() > .2*old_ink.sum() > 20, ('too little original artwork survived',i)
            protected[mask] |= undisturbed
        else:
            protected |= mask
    assert np.array_equal(before[protected],after[protected])
    assert np.array_equal(before[protected],rebuilt[protected])
    choose(page,'stage','cleared')
    caption(page,'taking shape' if len(places)==1 else 'has been added')
    assert np.array_equal(before[protected],frame(page)[protected])
    choose(page,'stage','redrawn')
    caption(page,final)
    return files, protected


def exercise(browser, args, folder):
    db=folder/'garden.db'
    with room(args.previous or args.gallery,db) as url,browser.new_page(**MOBILE) as page:
        state=base_garden(page,url)
    with room(args.gallery,db) as url,browser.new_page(**MOBILE) as host,browser.new_page(**MOBILE) as guest:
        api=url+API
        open_room(host,url)
        live=host.evaluate("""() => {
          const s=JSON.parse(document.querySelector('#scene').textContent).live,c=s.planner;
          return {geometry:c.geometry,groove:s.groove,labels:c.subjects,edition:s.edition,previous:s.previousOpening?.edition,
            excursions:c.excursions.map(seat=>({guitar_silhouette:seat.guitar_silhouette,books_open:seat.books_open,temple_gable:seat.temple_gable}))};
        }""")
        if state['edition'] != live['edition']:
            assert state['edition'] == live['previous']
            state['edition'] = live['edition']
        assert host.request.get(api).json()['state']==state
        picker=host.locator('#guestAddition')
        expect(picker).to_be_visible()
        assert picker.locator('option').all_text_contents()[1:] == ['Mae Lin · Add a music note','Alex · Add a pencil','Lek · Add a crescent moon']
        reject(host,api,'Add a music note to Thomas’s guitar','no guest called')
        reject(host,api,'Add a music note to Lek’s guitar','Swept Thai rooftop')
        reject(host,api,'Add a shooting star to Lek’s rooftop','decoration is unavailable')
        reject(host,api,'Add a leaf to Alex’s books','decoration is unavailable')
        reject(host,api,'Add a music note to Mae Lin’s guitar and add a crescent to Alex’s roof','Alex')
        host.locator('#target').select_option('1')
        expect(picker).to_be_visible()
        assert picker.locator('option').all_text_contents()[1:] == ['Alex · Add a pencil']
        reject(host,api,'Add a crescent to Lek’s roof','different places')
        host.locator('#target').select_option('')
        expected={}
        for place,target,name in [(0,NOTE,'Mae Lin'),(1,PENCIL,'Alex'),(2,MOON,'Lek')]:
            picker.select_option(f'{place}-{target}')
            expect(host.locator('#keep')).to_be_visible()
            expect(host.locator('#middleStageLabel')).to_have_text('In progress')
            expect(host.locator('#lastStageLabel')).to_have_text('Added')
            choose(host,'stage','original')
            caption(host,name+' · '+live['labels'][state['ids'][place]])
            expected[place],_=replay_addition(host,state,live,[place],'was added to the existing')
        suggest(host,'add a music note to Mae Lin’s guitar, a pencil to Alex’s open book and a crescent moon to Lek’s rooftop')
        choose(host,'stage','original')
        files,protected=replay_addition(host,state,live,[0,1,2],'added to the existing drawings')
        # Each drawing-in-progress frame names the addition and leaves its base visible.
        choose(host,'stage','cleared')
        moments=host.locator('#guestMoment')
        for label in ('Mae Lin’s music note takes shape','Alex’s pencil takes shape','Lek’s crescent moon takes shape'):
            moments.select_option(label=label)
            caption(host,'taking shape on the existing')
        choose(host,'stage','redrawn')
        payload,_=save(host,api)
        after,motion=payload['state'],payload['motion']
        assert after['ids']==[NOTE,PENCIL,MOON]
        assert after['guestBook']['active']==state['guestBook']['active']
        assert {p['place']:p['addFrom'] for p in motion['parts']}=={0:GUITAR,1:BOOK,2:ROOF}
        assert [raw for _,raw in files]==[raw for p in motion['parts'] for _,raw in expected[p['place']]]
        assert [(f['name'],f['text'].encode()) for f in motion['files']]==files
        a,b=[np.frombuffer(base64.b64decode(s['bed']),np.uint8) for s in (state,after)]
        assert np.array_equal(a[protected.ravel()],b[protected.ravel()])
        expect(picker).to_be_hidden()
        reject(host,api,'add a note for Mae Lin','already')
        reject(host,api,'add a pencil to Alex’s open book','already')
        open_room(guest,url)
        assert drawing_files(guest,'#roomFiles')==files
        assert np.array_equal(frame(host),frame(guest))
        # A future clear must remove the pencil, including the point above the
        # page. Compare the same downloaded clear on the old and decorated beds.
        suggest(guest,'clear Alex’s place')
        clear=[np.loadtxt(io.BytesIO(raw)) for _,raw in drawing_files(guest,'#downloads')]
        blank=replay(guest,after['bed'],*clear)
        control=replay(guest,state['bed'],*clear)
        geometry=live['geometry']
        angle=geometry['angles'][1]
        y,x=np.mgrid[-1:1:complex(len(blank)),-1:1:complex(len(blank))]
        seat=np.hypot(x-geometry['center']*np.cos(angle),-y-geometry['center']*np.sin(angle))<geometry['scale']+3*live['groove']
        np.testing.assert_array_equal(blank[seat],control[seat])
        # Asking for the complete picture can replace another subject. A source-
        # specific request against that same subject has to fail before preview.
        reject(guest,api,'Add a music note to Alex’s guitar','Alex')
        suggest(guest,'Acoustic guitar with a music note for Alex')
        payload,_=save(guest,api)
        assert payload['state']['ids'][1]==NOTE and 'addFrom' not in payload['motion']
        suggest(guest,'a Thai rooftop for Lek')
        save(guest,api)
        suggest(guest,'a crescent over Lek’s rooftop and a pumpkin for Alex')
        payload,_=save(guest,api)
        assert {p['place']:p.get('addFrom') for p in payload['motion']['parts']}=={1:None,2:ROOF}
        assert payload['state']['ids'][2]==MOON
        # Classic guitar differs from the silhouette even though both have the word guitar.
        expand(guest,'#peopleBox')
        guest.locator('#personPick').select_option('mae lin')
        guest.locator('#personDrawing').select_option('guitar')
        guest.locator('#personSubmit').click()
        payload,_=save(guest,api)
        assert payload['state']['ids'][0]=='guitar'
        reject(guest,api,'Add a music note to Mae Lin’s guitar','Acoustic guitar silhouette')
        suggest(guest,'Acoustic guitar silhouette for Mae Lin')
        payload,_=save(guest,api)
        assert payload['state']['ids'][0]==GUITAR
        # Choosing the decorated subject directly from the guest book uses
        # the same additive file as either spelling in the suggestion form.
        expand(guest,'#peopleBox')
        guest.locator('#personPick').select_option('mae lin')
        guest.locator('#personDrawing').select_option(NOTE)
        guest.locator('#personSubmit').click()
        assert drawing_files(guest,'#downloads')==expected[0]
        payload,_=save(guest,api)
        assert payload['motion']['place']==0 and payload['motion']['addFrom']==GUITAR
        assert payload['state']['ids'][0]==NOTE and payload['state']['guestBook']['active'][0]=='mae lin'
        print('Two phones kept the original garden, drew all three additions in one request, mixed an addition with a replacement, '
              'and rejected unknown guests, unsupported details and the wrong kind of guitar.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('--previous',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args,Path(tmp))
