#!/usr/bin/env python3
"""Use a family photo across a live garden, change its border and recover the original guest drawings."""
import argparse
import base64
import io
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_attached_garden import Table, served, wait_table
from test_garden_room import API, choose, drawing_files, open_room, suggest
from test_guest_place import contour, contour_samples
from test_ring_guest_border import MOBILE, from_files, preview, replay, save
from test_ring_lettering import seat_view
from test_ring_object_photo import PhoneTraffic, capture_stages, expand
from test_ring_photo import check_portrait, frame, ordinary_erase_pitch
from test_ring_seated_group import seated_view
from test_ring_shadows import ready
from test_ring_sketch_crossings import finger_sketch, KITE
from test_seated_beard import center_and_border
from thrcommon import MAX_POINTS


def prepare(page, url):
    open_room(page, url)
    jobs = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
    suggest(page, 'an acoustic guitar for Thomas and an open book for Alex')
    setup, _ = save(page, url+API)
    jobs.extend(setup['motion']['files'])
    finger_sketch(page, 'Ribbon kite', KITE)
    setup, _ = save(page, url+API)
    jobs.extend(setup['motion']['files'])
    choose(page, 'zone', 'outer')
    preview(page, 4, 'Lek', order='progressive')
    saved, _ = save(page, url+API)
    jobs.extend(saved['motion']['files'])
    state = saved['state']
    assert state['outer'] == 4 and state['ids'][:2] == ['guitar_silhouette', 'books_open']
    assert state['labels'][state['ids'][2]] == 'Ribbon kite' and state['ids'][2] in state['custom']
    return state, jobs


def group_photo(page, photo):
    choose(page, 'zone', 'center')
    expand(page, '#centerPhoto')
    page.locator('#portraitArea').select_option('wide')
    page.locator('#portraitFile').set_input_files(photo)
    page.locator('#portraitMode').select_option('group')
    page.locator('#portraitStyle').select_option('seats')
    page.locator('#portraitSubmit').click()
    ready(page)
    assert page.locator('#faceBoxes button[aria-pressed=true]').count() == 2
    return page.evaluate("""async () => {
      const s=JSON.parse(document.querySelector('#scene').textContent), wide=s.live.wideCenter;
      const radius=wide.transit.at(-1)[1], g=s.live.groove, R=s.live.radiusMM;
      const art=await GuestPhoto.fromFile(document.querySelector('#portraitFile').files[0],{
        group:true,groupStyle:'seats',portraitDiameterMm:2*R*radius,portraitDiameterGrooves:2*radius/g,
        portraitTrackingGrooves:s.live.trackingMarginMM/(R*g)});
      return {radius,groove:g,workingMm:R,narrow:s.zones.center.transit.at(-1)[1],
        points:art.points,seats:art.seatFaces,segments:OasisRingPlanner.photo(wide,art.points).segments,
        ordinary:wide.erase,geo:s.live.planner.geometry,dock:wide.transit[0]};
    }""")


def same_guests(state, original):
    for key in ('ids', 'custom', 'labels', 'guestBook', 'drawingInterests'):
        assert state.get(key) == original.get(key), f'The garden lost {key} while its guest drawings were covered.'


def bed(state, size):
    return np.frombuffer(base64.b64decode(state['bed']), dtype=np.uint8).reshape((size, size))


def saved_jobs(page, url, files, jobs):
    saved, revision = save(page, url+API)
    actual = saved['motion']['files']
    assert [(p['name'], p['text'].encode()) for p in actual] == files
    jobs.extend(actual)
    return saved, revision


def inspect_preview(page, previous, data, protected, directory, stage_lengths):
    files = drawing_files(page, '#downloads')
    parts = [np.loadtxt(io.BytesIO(raw)) for _,raw in files]
    assert all(2 <= len(p) <= MAX_POINTS for p in parts)
    route = from_files(files, data['dock'])
    frames = capture_stages(page)
    # File cuts and the preview's beat boundaries are independent. Retain the
    # real five-decimal samples and split at the renderer's four successive strokes.
    offsets = np.r_[0,np.cumsum(np.asarray(stage_lengths)-1)]
    assert offsets[-1] == len(route)-1
    beats = [route[a:b+1] for a,b in zip(offsets, offsets[1:])]
    rebuilt = replay(page, previous['bed'], *beats)
    during = replay(page, previous['bed'], *beats[:2])
    for actual, shown in ((during,frames[1]),(rebuilt,frames[-1])):
        diff = np.abs(actual.astype(float)-shown)
        assert diff.mean() < 1.1 and np.percentile(diff,99) < 6, (directory.name,diff.mean(),np.percentile(diff,99))
    for image in [*frames[1:],rebuilt]:
        np.testing.assert_array_equal(image[protected], frames[0][protected])
    assert np.any(frames[1] != frames[0]) and np.any(frames[-1] != frames[1])
    directory.mkdir(parents=True, exist_ok=True)
    for name,img in zip(('before','during','after'),frames):
        Image.fromarray(img).save(directory/(name+'.png'))
    for name,payload in files:
        (directory/name).write_bytes(payload)
    return files, route, frames


def inner_route(route, data):
    beyond = route[:,1] > data['radius'] + check.TOL
    assert check.seam_segments(route,data['dock'][0])[beyond[:-1] | beyond[1:]].all()


def clear_old_ink(page, previous, clear, radius):
    # Compare the same physical clear on two beds. Strong differences before the pass
    # are the remembered art that would survive if the clear missed part of the disk.
    remaining=page.evaluate("""([raw,clear,radius])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent).live;
      const decode=bytes=>Float32Array.from(atob(bytes),b=>b.charCodeAt(0)/170-1);
      const a=decode(raw), b=decode(s.bed), sim=new RingSand(s.size,s.groove,s.profile);
      const sites=[];let original=0, residue=0;
      for(let i=0;i<a.length;i++){
        const x=2*(i%s.size)/(s.size-1)-1, y=1-2*Math.floor(i/s.size)/(s.size-1);
        const d=Math.abs(a[i]-b[i]);
        if(Math.hypot(x,y)<radius-1.5*s.groove && d>.18){sites.push(i);original+=d;}
      }
      sim.carve(a,clear); sim.carve(b,clear);
      for(const i of sites)residue+=Math.abs(a[i]-b[i]);
      return {pixels:sites.length,remainingFraction:residue/original};
    }""",[previous['bed'],clear.tolist(),radius])
    assert remaining['pixels']>1000 and remaining['remainingFraction']<.005, remaining
    return remaining


def chair_frames(frames, data, directory):
    for i,seat in enumerate(data['seats']):
        for name,img in zip(('before','during','after'),frames):
            seated_view(img,seat,data['radius']).save(directory/f'chair-{i+1}-{name}.jpg',quality=94)


def mobile_chairs(page, labels, directory):
    button = page.locator('#chairView')
    if button.get_attribute('aria-pressed') != 'true':
        button.tap()
    for i, label in enumerate(labels, 1):
        expect(page.locator('#seatNumber')).to_have_text(label)
        page.locator('.sand-display').screenshot(path=str(directory / f'mobile-chair-{i}.png'))
        page.locator('#nextSeat').tap()
    button.tap()


def exercise(browser, gallery, previous, source, output, db):
    table=Table(db)
    with served(previous or gallery,db,table,prepared=True) as url, browser.new_page(**MOBILE) as prior_phone:
        original, jobs = prepare(prior_phone,url)
    with served(gallery,db,table) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        api=url+API
        traffic=PhoneTraffic(url)
        for phone in (host,guest):
            phone.route('http**://**/*',traffic.check)
            open_room(phone,url)
        assert host.request.get(api).json()['state']==original
        data=group_photo(host,traffic.photo(source.name,source.read_bytes(),'image/jpeg'))
        assert len(data['seats'])==2 and data['radius']>1.9*data['narrow']
        n=len(frame(host))
        inner,border=center_and_border(n,data)
        files, portrait, images=inspect_preview(host,original,data,border,output/'portrait',list(map(len,data['segments'])))
        assert len(files)>1, 'The fitted family portrait should exercise a split download'
        inner_route(portrait,data)
        error=check_portrait(data['points'],data['segments'],portrait,data['groove'],
                             ordinary_erase_pitch(data['ordinary']), True)
        at_clear=len(data['segments'][0])+len(data['segments'][1])-2
        assert data['segments'][1][-1][1]>.70
        erase_proof=clear_old_ink(host,original,portrait[:at_clear+1],data['radius'])
        painted=data['segments'][2]
        dist=check.travel(np.asarray(painted))
        halfway=at_clear+int(np.searchsorted(dist,dist[-1]/2))
        drawing=replay(host,original['bed'],portrait[:halfway+1])
        np.testing.assert_array_equal(drawing[border],images[0][border])
        for i,seat in enumerate(data['seats']):
            seated_view(drawing,seat,data['radius']).save(output/'portrait'/f'chair-{i+1}-drawing.jpg',quality=94)
        chair_frames(images,data,output/'portrait')
        saved,_=saved_jobs(host,url,files,jobs)
        state=saved['state']
        assert state['widePortrait'] and state['portraitSeats']==2 and saved['motion']['centerMode']=='widePortrait'
        assert state['outer']==original['outer'] and state['borderGuest']==original['borderGuest']
        np.testing.assert_array_equal(bed(state,n)[border],bed(original,n)[border])
        same_guests(state,original)
        # An independently loaded phone holds neither the original source nor the first phone's draft.
        guest.goto('about:blank')
        open_room(guest,url,'photos')
        choose(guest,'zone','center')
        expect(guest.locator('input[name=zone][value=middle]')).to_be_disabled()
        assert drawing_files(guest,'#roomFiles')==files
        assert guest.locator('#portraitFile').evaluate('el=>el.files.length')==0
        mobile_chairs(guest, ['Seat 1 of 2', 'Seat 2 of 2'], output/'portrait')
        choose(guest,'zone','outer')
        preview(guest,2,'Lek',order='progressive')
        cut_lengths=guest.evaluate("""() => OasisRingPlanner.borderReveal(
          JSON.parse(document.querySelector('#scene').textContent).zones.outer,2).segments.map(p=>p.length)""")
        border_files,border_route,border_images=inspect_preview(guest,state,data,inner,output/'border',cut_lengths)
        assert border_route[:,1].min()>data['radius']
        assert np.any(border_images[0][border]!=border_images[-1][border])
        chair_frames(border_images,data,output/'border')
        changed,_=saved_jobs(guest,url,border_files,jobs)
        border_state=changed['state']
        assert border_state['widePortrait'] and border_state['portraitSeats']==2
        assert border_state['outer']==2 and border_state['borderGuest']=='Lek'
        np.testing.assert_array_equal(bed(border_state,n)[inner],bed(state,n)[inner])
        same_guests(border_state,original)
        host.goto('about:blank')
        open_room(host,url,'photos')
        choose(host,'zone','center')
        host.locator('#restoreGuests').click()
        expect(host.locator('#keep')).to_be_visible()
        segments=host.evaluate("""state=>{
          const scene=JSON.parse(document.querySelector('#scene').textContent);
          return OasisRingPlanner.restoreGuests(scene,state.ids,state.custom).segments;
        }""",border_state)
        restore_files,restore,restored_images=inspect_preview(host,border_state,data,border,output/'restore',list(map(len,segments)))
        inner_route(restore,data)
        expected=check.joined(segments,data['dock'],data['dock'],'restore')
        assert check.same_track(expected,restore)
        clear_end=len(segments[0])+len(segments[1])-2
        lotus=host.evaluate("JSON.parse(document.querySelector('#scene').textContent).zones.center.drawings[0]")
        assert check.same_track(restore[clear_end:clear_end+len(lotus)],np.asarray(lotus))
        restore_clear=clear_old_ink(host,border_state,restore[:clear_end+1],data['radius'])
        ink=cKDTree(check.sample_walk(restore[clear_end:],data['groove']/32))
        misses=[]
        for slot in range(3):
            shape=contour(original,slot,data['geo'])
            samples=contour_samples(shape,data['groove']/32)
            miss=float(ink.query(samples)[0].max())*data['workingMm']
            assert miss<data['groove']*data['workingMm']/5,(slot,miss)
            misses.append(round(miss,3))
            for label,img in zip(('before','during','after'),restored_images):
                seat_view(img,data['geo'],slot).save(output/'restore'/f'guest-{slot+1}-{label}.jpg',quality=94)
        kept,last=saved_jobs(host,url,restore_files,jobs)
        restored=kept['state']
        assert kept['motion']['centerMode']=='restoreGuests' and not restored.get('widePortrait')
        assert restored['center']==0 and restored['portrait']=='' and not restored.get('portraitSeats')
        assert restored['outer']==2 and restored['borderGuest']=='Lek'
        np.testing.assert_array_equal(bed(restored,n)[border],bed(border_state,n)[border])
        same_guests(restored,original)
        guest.goto('about:blank')
        open_room(guest,url)
        expect(guest.locator('input[name=zone][value=middle]')).to_be_enabled()
        assert guest.request.get(api).json()['state']==restored
        mobile_chairs(guest, ['Thomas’s chair', 'Alex’s chair', 'Lek’s chair'], output/'restore')
        for i,job in enumerate(jobs,1):
            assert table.dispatched(i)==job
            table.outcome='complete'
        wait_table(guest,url,state='idle',ready=True,queued=0,revision=last)
        assert len(table.calls)==len(jobs) and not traffic.violations,traffic.violations
        result={'center_diameter_mm':round(2*data['radius']*data['workingMm'],1),
                'artwork_max_error_mm':round(error*data['workingMm'],3),'protected_border_pixels':int(border.sum()),
                'protected_inner_pixels':int(inner.sum()),'enter_clear':erase_proof,'restore_clear':restore_clear,
                'restored_drawings_error_mm':misses,'portrait_parts':len(files),'border_parts':len(border_files),
                'restore_parts':len(restore_files),'all_dispatched_files':len(jobs),'guest_ids':original['ids']}
        (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('photo',type=Path,help='A two-person group photograph')
    parser.add_argument('--previous',type=Path,help='An earlier three-zone gallery of the same measured layout')
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args.gallery,args.previous,args.photo,args.evidence or Path(tmp)/'evidence',Path(tmp)/'garden.db')
