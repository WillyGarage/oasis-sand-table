#!/usr/bin/env python3
"""Keep guests’ actual drawings around a family portrait and refresh the border from a second phone."""
import argparse
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from ring_scene import motif
from test_attached_garden import Table, served, wait_table
from test_garden_family_portrait import bed, group_photo, inspect_preview, mobile_chairs, prepare, saved_jobs
from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_place import unpack
from test_ring_guest_border import MOBILE, preview, save
from test_ring_object_photo import PhoneTraffic, expand
from test_ring_photo import frame


def reopen(page, url, zone):
    page.goto('about:blank')
    open_room(page, url)
    choose(page, 'zone', zone)


def existing_room(page, url, photo):
    state, jobs = prepare(page, url)
    choose(page, 'zone', 'middle')
    expand(page, '#peopleBox')
    page.locator('#personPick').select_option(label='Thomas')
    page.locator('#personInterest').fill('Bacteriophages and acoustic guitar')
    page.locator('#personDrawing').select_option(state['ids'][0])
    page.locator('#personSubmit').click()
    roster, _ = save(page, url+API)
    assert not roster.get('motion') and roster['state']['ids'] == state['ids']
    group_photo(page, photo)
    saved, _ = saved_jobs(page, url, drawing_files(page, '#downloads'), jobs)
    assert saved['state']['widePortrait'] and saved['state']['portraitSeats'] == 2
    return saved['state'], jobs


def source_drawings(page, current):
    catalog = page.evaluate("""() => {
      const s=JSON.parse(document.querySelector('#scene').textContent), l=s.live, c=l.planner;
      return {labels:c.subjects, pairMotifs:c.pairMotifs, empty:c.openSubject,
        angles:c.geometry.angles, groove:l.groove, radiusMm:l.radiusMM, dock:s.zones.outer.transit[0],
        inner:l.wideCenter.transit.at(-1)[1], outer:s.zones.outer.transit.at(-1)[1]};
    }""")
    book = current.get('guestBook')
    guests = [next(p['name'] for p in book['people'] if p['name'].casefold()==key)
              for key in book['active']] if book else ['Thomas','Alex','Lek']
    sources = []
    for name, subject in zip(guests, current['ids']):
        if subject == catalog['empty']:
            sources.append(None)
            continue
        if subject in current['custom']:
            label, points = current['labels'][subject], current['custom'][subject]
        else:
            points = unpack(catalog['pairMotifs'][subject])
            np.testing.assert_allclose(points, motif(subject), atol=5.1e-9, rtol=0)
            label, points = catalog['labels'][subject], points.tolist()
        sources.append({'label':name+' · '+label, 'points':points})
    return catalog, sources


def chair_detail(image, angle, center, shape, scale, groove):
    """Look inward from the guest's chair; crop to their actual outline in physical sand."""
    radial = np.array([math.cos(angle), math.sin(angle)])
    right, down = np.array([-radial[1],radial[0]]), radial
    lo, hi = shape.min(axis=0), shape.max(axis=0)
    mid = (lo+hi)*scale/2
    center = np.asarray(center) + mid[0]*right - mid[1]*down
    width = np.max(hi-lo)*scale + 4*groove
    half = (len(image)-1)/2
    xy = half*(1+center*[1,-1])
    dx, dy = right*[1,-1]*half*width, down*[1,-1]*half*width
    start = xy-(dx+dy)/2
    return Image.fromarray(image).transform((300,300),Image.Transform.AFFINE,
        (dx[0]/300,dy[0]/300,start[0],dx[1]/300,dy[1]/300,start[1]),resample=Image.Resampling.BICUBIC)


def signed_subject(route, meta, points, seat_angle, radius_mm):
    outline = np.asarray(points)[:-1]
    start = meta['entryVertex']
    vertices = np.vstack((outline[start:],outline[:start+1]))
    assert abs(math.remainder(meta['angle']-seat_angle,math.tau))<1e-6
    right = np.array([-math.sin(seat_angle),math.cos(seat_angle)])
    up = -np.array([math.cos(seat_angle),math.sin(seat_angle)])
    expected = meta['center'] + meta['scale']*(vertices[:,0,None]*right+vertices[:,1,None]*up)
    piece = route[meta['first']:meta['last']+1]
    # Signed engraving must reach each authored vertex in order. Compare on the plane
    # of the table, not just on the raster where a groove could conceal a skipped line.
    steps = np.maximum(1,np.ceil(np.linalg.norm(np.diff(vertices,axis=0),axis=1)*meta['scale']/.01)).astype(int)
    indices = np.r_[0,np.cumsum(steps)]
    assert indices[-1] == len(piece)-1
    actual = piece[indices,1,None]*np.column_stack((np.cos(piece[indices,0]),np.sin(piece[indices,0])))
    error = float(np.linalg.norm(actual-expected,axis=1).max()*radius_mm)
    assert error < .008, error
    return {'max_vertex_error_mm':round(error,4),'size_mm':np.round(np.ptp(vertices,axis=0)*meta['scale']*radius_mm,1).tolist()}


def keep_border(page, url, before, jobs, folder):
    catalog, sources = source_drawings(page,before)
    choose(page,'zone','outer')
    page.locator('#borderDesign').select_option('-1')
    if page.locator('#borderOrder').is_visible():
        page.locator('#borderOrder').select_option('whole')
    expect(page.locator('#borderPreview')).to_be_enabled()
    page.locator('#borderPreview').click()
    for source in filter(None,sources):
        caption(page,source['label'])
    plan=page.evaluate("""sources=>{
        const s=JSON.parse(document.querySelector('#scene').textContent);
        const p=GuestKeepsakeBorder.plan(s,sources.map(v=>v?.points??null));
        return {lengths:p.segments.map(x=>x.length),placements:p.placements};
    }""",sources)
    size=len(frame(page))
    y,x=np.mgrid[-1:1:complex(size),-1:1:complex(size)]
    protected=np.hypot(x,y)<=catalog['inner']
    files,route,frames=inspect_preview(page,before,catalog,protected,folder,plan['lengths'])
    assert route[:,1].min() > catalog['inner']
    assert page.request.get(url+API).json()['state'] == before
    # Compare the rim artwork as seen before and after a refresh. Include the
    # original marks anywhere inside the seat, even when the new subject is narrower.
    lower, higher = route[:,1].min(), catalog['outer']
    radial = np.hypot(x,y)
    angular = np.arctan2(-y,x)
    half_width = math.atan2(.725*(higher-lower),lower)
    tone_change = np.max(np.abs(frames[-1].astype(np.int16)-frames[0]),axis=2)
    changed = []
    shown=[]
    for slot,(source,meta) in enumerate(zip(sources,plan['placements'])):
        turn = (angular-catalog['angles'][slot]+np.pi)%(2*np.pi)-np.pi
        area = (radial >= lower) & (radial <= higher) & (abs(turn)<half_width)
        changed.append(round(100*np.mean(tone_change[area]>18),2))
        if source is None:
            assert meta is None
            shown.append(None)
            continue
        record=signed_subject(route,meta,source['points'],catalog['angles'][slot],catalog['radiusMm'])
        shown.append({'label':source['label'],**record})
        for name,image in zip(('before','cleared','kept'),frames):
            detail=chair_detail(image,meta['angle'],meta['center'],np.asarray(source['points']),meta['scale'],catalog['groove'])
            detail.save(folder/f'guest-{slot+1}-{name}.jpg',quality=95)
    saved,_=saved_jobs(page,url,files,jobs)
    state=saved['state']
    assert state['outer']==-1 and saved['motion']['guestBorder'] is True
    assert state['guestBorder']==sources
    for key in ('ids','guestBook','custom','labels','widePortrait','portrait','portraitSeats','center'):
        assert state.get(key)==before.get(key),key
    np.testing.assert_array_equal(bed(state,size)[protected],bed(before,size)[protected])
    return state,files,{'drawings':shown,'protected_pixels':int(protected.sum()),'file_parts':len(files),'changed_percent_by_seat':changed}


def old_border_survives(before, after, size, data, mask=None):
    assert after['guestBorder']==before['guestBorder'] and after['outer']==before['outer']==-1
    if mask is None:
        y,x=np.mgrid[-1:1:complex(size),-1:1:complex(size)]
        # The known six-o'clock spoke is used for access to the inner sand.
        mask=(np.hypot(x,y)>data['inner']+3*data['groove']) & (np.hypot(x,y)<.99) & ((y<0)|(abs(x)>3*data['groove']))
    np.testing.assert_array_equal(bed(after,size)[mask],bed(before,size)[mask])
    return mask


def open_places(browser, gallery, db, output):
    with room(gallery,db) as url,browser.new_page(**MOBILE) as phone:
        open_room(phone,url)
        choose(phone,'zone','outer')
        phone.locator('#borderDesign').select_option('-1')
        expect(phone.locator('#borderPreview')).to_be_disabled()
        expect(phone.locator('#guestBorderGuide')).to_contain_text('at least one')
        choose(phone,'zone','middle')
        suggest(phone,'an open book for Alex')
        saved,_=save(phone,url+API)
        one,_,_=keep_border(phone,url,saved['state'],[],output)
        assert one['guestBorder'][0] is None and one['guestBorder'][2] is None
        assert one['guestBorder'][1]['label']=='Alex · Open book'


def exercise(browser, gallery, previous, photo, db, output):
    table=Table(db)
    with served(previous,db,table,prepared=True) as url,browser.new_page(**MOBILE) as first:
        traffic=PhoneTraffic(url)
        first.route('http**://**/*',traffic.check)
        wide,jobs=existing_room(first,url,traffic.photo(photo.name,photo.read_bytes(),'image/jpeg'))
        assert not traffic.violations,traffic.violations
    with served(gallery,db,table) as url,browser.new_page(**MOBILE) as host,browser.new_page(**MOBILE) as guest:
        api=url+API
        reopen(host,url,'center')
        reopen(guest,url,'outer')
        assert guest.request.get(api).json()['state']==wide
        frozen,first_files,first=keep_border(guest,url,wide,jobs,output/'family')
        reopen(host,url,'center')
        mobile_chairs(host,['Seat 1 of 2','Seat 2 of 2'],output/'family')
        catalog,_=source_drawings(host,frozen)
        size=len(frame(host))
        # Record the actual frozen border bytes that the next guest may download.
        stored=host.request.get(api+'/drawings/outer').json()
        host.locator('#restoreGuests').click()
        restored,_=saved_jobs(host,url,drawing_files(host,'#downloads'),jobs)
        restored=restored['state']
        protected=old_border_survives(frozen,restored,size,catalog)
        assert restored['ids']==wide['ids'] and not restored.get('widePortrait')
        reopen(guest,url,'middle')
        suggest(guest,'a field pumpkin for Lek')
        replaced,_=saved_jobs(guest,url,drawing_files(guest,'#downloads'),jobs)
        changed=replaced['state']
        assert changed['ids'][2]=='pumpkin_ribbed' and changed['ids'][:2]==wide['ids'][:2]
        old_border_survives(restored,changed,size,catalog,protected)
        assert guest.request.get(api+'/drawings/outer').json()==stored
        reopen(host,url,'outer')
        assert drawing_files(host,'#roomFiles')==first_files
        refresh,new_files,second=keep_border(host,url,changed,jobs,output/'refreshed')
        change=second['changed_percent_by_seat']
        assert max(change[:2]) < 5 and change[2] > 15, change
        assert new_files!=first_files and refresh['guestBorder'][:2]==frozen['guestBorder'][:2]
        assert refresh['guestBorder'][2]['points']!=frozen['guestBorder'][2]['points']
        # A fresh phone can see that the new guest border already matches.
        reopen(guest,url,'outer')
        guest.locator('#borderDesign').select_option('-1')
        expect(guest.locator('#borderPreview')).to_be_disabled()
        mobile_chairs(guest,['Thomas’s chair','Alex’s chair','Lek’s chair'],output/'refreshed')
        preview(guest,3,'Lek',order='whole')
        stock,last=saved_jobs(guest,url,drawing_files(guest,'#downloads'),jobs)
        assert stock['state']['outer']==3 and 'guestBorder' not in stock['state']
        assert not stock['motion'].get('guestBorder')
        assert stock['state']['ids']==changed['ids']
        for i,job in enumerate(jobs,1):
            assert table.dispatched(i)==job
            table.outcome='complete'
        wait_table(guest,url,state='idle',ready=True,queued=0,revision=last)
        assert len(table.calls)==len(jobs)
        report={'original':first,'refreshed':second,'remembered_border_pixels':int(protected.sum()),'queued_files':len(jobs)}
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('photo',type=Path)
    parser.add_argument('--previous',required=True,type=Path)
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        output=args.evidence or Path(tmp)/'evidence'
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args.gallery,args.previous,args.photo,Path(tmp)/'family.db',output)
            open_places(browser,args.gallery,Path(tmp)/'open.db',output/'one-guest')
