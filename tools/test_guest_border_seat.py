#!/usr/bin/env python3
"""Change a live border suggestion from a phone, recall a real saved sketch, and reopen the guests’ places."""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from ring_scene import motif
from test_attached_garden import Table, served, wait_table
from test_garden_family_portrait import bed, mobile_chairs, saved_jobs
from test_garden_room import API, choose, drawing_files
from test_guest_keepsake_border import chair_detail, existing_room, old_border_survives, reopen, signed_subject, source_drawings
from test_guest_place import contour, contour_samples
from test_ring_guest_border import MOBILE, from_files, preview, replay
from test_ring_lettering import seat_view
from test_ring_object_photo import PhoneTraffic
from test_ring_photo import frame


PLACE = 2


def suggest_outer(page, suggestion, saved_id=None):
    page.locator('#borderDesign').select_option('-1')
    page.locator('#editBorderPlace + span').click()
    expect(page.locator('#editBorderPlace')).to_be_checked()
    page.locator('#borderPlace').select_option(str(PLACE))
    page.locator('#borderSubject').fill(suggestion)
    if saved_id is not None:
        expect(page.locator(f'#borderSaved option[value="{saved_id}"]')).to_have_count(1)
        if page.locator('#borderSaved').is_visible():
            page.locator('#borderSaved').select_option(saved_id)
    expect(page.locator('#borderPreview')).to_be_enabled()
    page.locator('#borderPreview').click()
    expect(page.locator('#keep')).to_be_visible()


def route_details(page, sources, grain):
    return page.evaluate("""([all,place,grain])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent), shapes=all.map(x=>x?.points??null);
      const p=GuestKeepsakeBorder.planSeat(s,place,shapes[place],grain), full={};
      for(const order of ['whole','progressive']) {
        const path=GuestKeepsakeBorder.plan(s,shapes,order).path;
        full[order]=OasisRingPlanner.files(path,'border');
      }
      const sector=s.live.guestBorderSectors.find(v=>v.slot===place);
      return {placement:p.placements[place],lengths:p.segments.map(x=>x.length),
              sector:{left:sector.left,right:sector.right},cut:p.sectorSteps[0].clearEnd,full};
    }""",[sources,PLACE,grain])


def sample_pixels(xy, size):
    col, row = np.rint((1+xy*[1,-1])*(size-1)/2).astype(int).T
    return np.unique(row*size+col).tolist()


def vanished(page, original, different, old_route, old_placement, raw_clear, radius):
    # The previous drawing is known from a verified, signed path. At those
    # exact grooves, compare two real saved beds with different prior pictures.
    start, stop = old_placement['first'], old_placement['last']
    points = check.sample_walk(old_route[start:stop+1], radius['groove']*.09)
    size = len(frame(page))
    actual = page.evaluate("""([old,other,parts,sites])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent).live;
      const decode=raw=>Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1);
      const a=decode(old),b=decode(other),sim=new RingSand(s.size,s.groove,s.profile);
      const ink=sites.filter(i=>Math.abs(a[i]-b[i])>.15);
      const relief=()=>ink.reduce((sum,i)=>sum+Math.abs(a[i]-b[i]),0);
      const before=relief();
      for(const part of parts){sim.carve(a,part);sim.carve(b,part);}
      return {points:ink.length,remaining:relief()/before};
    }""",[original['bed'],different['bed'],[p.tolist() for p in raw_clear],sample_pixels(points,size)])
    assert actual['points']>100 and actual['remaining']<.015,actual
    return actual


def masks(size, catalog, sector):
    y,x = np.mgrid[-1:1:complex(size),-1:1:complex(size)]
    r, theta = np.hypot(x,y), np.arctan2(-y,x)
    lo, hi = sector['left'], sector['right']
    center = (lo+hi)/2
    gap = 2*catalog['groove']
    away = abs(np.angle(np.exp(1j*(theta-center)))) > (hi-lo)/2+gap/catalog['inner']
    # The approach can retrace the shared outside rail. Exclude its two-groove-wide
    # neighborhood, then verify the entire remaining view outside the changed place.
    interior = r<=catalog['inner']
    unaffected = away & (r<catalog['outer']-gap)
    neighbors = []
    for a in catalog['angles'][:PLACE]:
        turn = abs(np.angle(np.exp(1j*(theta-a))))
        neighbors.append((turn<(hi-lo)/2) & (r>catalog['inner']+gap) & (r<catalog['outer']-gap))
    return interior, unaffected, neighbors


def seam_crop(image, angle, radius, width, height):
    # Preserve the actual radial and tangential scale viewed from this side of the table.
    normal = np.asarray([np.cos(angle),np.sin(angle)])*[1,-1]
    along = np.asarray([-np.sin(angle),np.cos(angle)])*[1,-1]
    scale = (len(image)-1)/2
    center = scale*(1+radius*normal)
    dx,dy = along*width*scale,normal*height*scale
    start = center-(dx+dy)/2
    out = (round(210*width/height),210)
    return Image.fromarray(image).transform(out,Image.Transform.AFFINE,
        (dx[0]/out[0],dy[0]/out[1],start[0],dx[1]/out[0],dy[1]/out[1],start[1]),
        resample=Image.Resampling.BICUBIC)


def check_spiral_seam(page, state, sources, catalog, sector, approach_and_clear, frames, folder):
    clear = approach_and_clear[1]
    low,high = clear[:,1].min(),catalog['outer']
    g = catalog['groove']
    old_clear,fluted = page.evaluate("""([place,shape])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent);
      const alt=GuestKeepsakeBorder.planSeat(s,place,shape,'fluted');
      return [s.zones.outer.erase,alt.segments.slice(0,2)];
    }""",[PLACE,sources[PLACE]['points']])
    old_points = cKDTree(check.sample_walk(old_clear,g/18))
    new_points = check.sample_walk(clear,g/18)
    theta = np.arctan2(new_points[:,1],new_points[:,0])
    radius = np.linalg.norm(new_points,axis=1)
    mid = (sector['right']+sector['left'])/2
    signed_angle = np.angle(np.exp(1j*(theta-mid)))
    half = (sector['right']-sector['left'])/2
    # Check the outer two flanks independently of the transitions between
    # successive spiral grooves in the middle of the requested place.
    flank = (abs(signed_angle)>.68*half) & (abs(signed_angle)<.95*half)
    inner = flank & (radius>low+g) & (radius<high-g)
    phase_mm = {}
    for label,side in [('left',signed_angle<0),('right',signed_angle>0)]:
        distance = old_points.query(new_points[inner & side])[0]*catalog['radiusMm']
        phase_mm[label] = round(float(np.percentile(distance,99)),3)
        assert len(distance)>500,(label,len(distance))
    fluted = replay(page,state['bed'],*(np.round(np.asarray(p),5) for p in fluted))
    before,matched,_ = frames
    n = len(before)
    y,x = np.mgrid[-1:1:complex(n),-1:1:complex(n)]
    r,theta = np.hypot(x,y),np.arctan2(-y,x)
    left,right = sector['left'],sector['right']
    interior = (r>low+1.9*g) & (r<high-2.5*g)
    # Compare visible texture immediately *inside* both joins. A stripe of
    # previously blank sand here must stay in phase with its neighboring spiral.
    diffs = {}
    for label,bound,direction in [('left',left,1),('right',right,-1)]:
        offset = direction*np.angle(np.exp(1j*(theta-bound)))*r
        area = interior & (offset>1.2*g) & (offset<2.5*g)
        def change(im):
            return float(np.mean(np.abs(im[area].astype(float)-before[area])))
        def ring_direction(image):
            dy,dx=np.gradient(image.mean(axis=2))
            radial=np.abs(dx*x+dy*y)[area].sum()
            tangent=np.abs(dy*x-dx*y)[area].sum()
            return float(radial/(radial+tangent))
        levels = page.evaluate("""([raw,trip,pixels])=>{
          const l=JSON.parse(document.querySelector('#scene').textContent).live;
          const a=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1),b=a.slice();
          const sim=new RingSand(l.size,l.groove,l.profile);
          for(const part of trip) sim.carve(b,part);
          return [pixels.map(i=>a[i]),pixels.map(i=>b[i])];
        }""",[state['bed'],[p.tolist() for p in approach_and_clear],np.flatnonzero(area).tolist()])
        signed_corr = float(np.corrcoef(*levels)[0,1])
        visible_corr = float(np.corrcoef(before[area].mean(axis=1),matched[area].mean(axis=1))[0,1])
        old_change,matched_change = change(fluted),change(matched)
        original_axis,fluted_axis,matched_axis = map(ring_direction,(before,fluted,matched))
        diffs[label] = {'pixels':int(area.sum()),'fluted_difference':round(old_change,2),'spiral_difference':round(matched_change,2),
                        'ring_direction_original':round(original_axis,3),'ring_direction_fluted':round(fluted_axis,3),
                        'ring_direction_matched':round(matched_axis,3),'signed_height_correlation':round(signed_corr,3),
                        'visible_brightness_correlation':round(visible_corr,3)}
        assert area.sum()>100 and abs(matched_axis-original_axis)<.5*abs(fluted_axis-original_axis),diffs
    dfont=ImageFont.truetype('DejaVuSans.ttf',18)
    heading=ImageFont.truetype('DejaVuSans-Bold.ttf',24)
    sheet=Image.new('RGB',(672,863),'#f6f1e9')
    draw=ImageDraw.Draw(sheet)
    draw.text((20,14),'Both edges of Lek’s border place',font=heading,fill='#282720')
    draw.text((20,52),'Left edge',font=dfont,fill='#514d43')
    draw.text((356,52),'Right edge',font=dfont,fill='#514d43')
    for i,(label,img) in enumerate([('Original spiral',before),('Fluted clear',fluted),('Matching spiral clear',matched)]):
        top=87+i*254
        draw.text((20,top),label,font=heading,fill='#282720')
        for col,a in enumerate((left,right)):
            crop=seam_crop(img,a,(low+high)/2,.23,high-low+.012)
            sheet.paste(crop,(20+336*col,top+35))
    sheet.save(folder/'spiral-seams.jpg',quality=94)
    print('Signed spiral joins',json.dumps(diffs),flush=True)
    assert all(d['signed_height_correlation']>0 and d['visible_brightness_correlation']>0 for d in diffs.values()),diffs
    return {'p99_original_spiral_distance_mm':phase_mm,'visible_edge_texture':diffs}


def check_visit(page, url, files, state, alt_bed, prior, new_sources, catalog, folder, grain):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    route = from_files(files,catalog['dock'])
    data = route_details(page,new_sources,grain)
    lo, hi = data['sector']['left'], data['sector']['right']
    in_ink = route[:,1]<catalog['outer']-check.TOL
    angle = abs(np.angle(np.exp(1j*(route[:,0]-(lo+hi)/2))))
    assert np.all(angle[in_ink] <= (hi-lo)/2+check.TOL)
    assert route[:,1].min() > catalog['inner']
    cuts = np.r_[0,np.cumsum(np.asarray(data['lengths'])-1)]
    if len(cuts)!=5 or cuts[-1]!=len(route)-1 or cuts[2]!=data['cut']:
        othergrain = 'spiral' if grain=='fluted' else 'fluted'
        alt = route_details(page,new_sources,othergrain)
        reading = page.evaluate("""raw=>{
          const s=JSON.parse(document.querySelector('#scene').textContent);
          const h=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1);
          return GuestBorderGrain.read(s,h);
        }""",state['bed'])
        raise AssertionError((grain, reading, 'actual/expected/other rows',len(route),cuts[-1]+1,sum(alt['lengths'])-3))
    beats = [route[a:b+1] for a,b in zip(cuts,cuts[1:])]
    drawing = new_sources[PLACE]
    art = signed_subject(route,data['placement'],drawing['points'],catalog['angles'][PLACE],catalog['radiusMm'])
    frames = []
    for stage in ('original','cleared','redrawn'):
        choose(page,'stage',stage)
        if stage == 'cleared':
            expect(page.locator('.caption')).to_contain_text('Lek’s part of the border is clear.')
        if stage == 'redrawn':
            expect(page.locator('.caption')).to_contain_text(drawing['label'])
        if stage != 'original':
            expect(page.locator('.caption')).to_contain_text('the wide portrait')
        frames.append(frame(page))
    n = len(frames[0])
    center, elsewhere, neighbors = masks(n,catalog,data['sector'])
    for actual,parts in zip(frames[1:],(beats[:2],beats)):
        check_image = replay(page,state['bed'],*parts)
        diff = np.abs(check_image.astype(np.int16)-actual.astype(np.int16))
        assert diff.mean()<1.1 and np.percentile(diff,99)<6,(diff.mean(),np.percentile(diff,99))
        for mask in [center,elsewhere,*neighbors]:
            np.testing.assert_array_equal(actual[mask],frames[0][mask])
    assert page.request.get(url+API).json()['state']==state
    matching = {}
    if grain == 'spiral':
        matching = check_spiral_seam(page,state,new_sources,catalog,data['sector'],beats[:2],frames,folder)
    old_ink = vanished(page,state,alt_bed,*prior,beats[:2],catalog)
    before, cleared, finished = frames
    target = data['placement']
    closeups = []
    # Keep all three views on exactly the same center and scale. The old kite and
    # new pumpkin both use the full band height and share the same chair angle.
    for label,img in zip(('before','cleared','finished'),(before,cleared,finished)):
        Image.fromarray(img).save(folder/(label+'.png'))
        crop = chair_detail(img,target['angle'],target['center'],np.array(drawing['points']),target['scale'],catalog['groove'])
        crop.save(folder/('lek-'+label+'.jpg'),quality=95)
        closeups.append(crop)
    for name,raw in files:
        (folder/name).write_bytes(raw)
    walk = check.travel(route)*catalog['radiusMm']/1000
    full = {}
    for name,lst in data['full'].items():
        companion = from_files([(f['name'],f['text'].encode()) for f in lst],catalog['dock'])
        full[name] = round(float(check.travel(companion)[-1]*catalog['radiusMm']/1000),3)
    assert walk[-1] < min(full.values())/3
    return {'meters':round(float(walk[-1]),3),'cleared_m':round(float(walk[cuts[2]]),3),
            'full_border_m':full,'protected_portrait_pixels':int(center.sum()),'protected_away_from_rail':int(elsewhere.sum()),
            'protected_neighbor_pixels':[int(m.sum()) for m in neighbors],'old_ink':old_ink,'engraving':art,
            'files':len(files),**matching}, (route,target), frames, closeups


def sheet(folder, frames, details, report):
    text = ImageFont.truetype('DejaVuSans.ttf',18)
    title = ImageFont.truetype('DejaVuSans-Bold.ttf',25)
    output = Image.new('RGB',(624,1084),'#f6f1e9')
    d = ImageDraw.Draw(output)
    d.text((22,16),'A new suggestion for Lek',font=title,fill='#282720')
    d.text((22,54),'Seated family portrait · large-table simulation',font=text,fill='#524f47')
    labels = [('Ribbon kite','Before the suggestion'),('Lek’s place is clear',f"{report['cleared_m']:.1f} m of ball travel"),
              ('Field pumpkin',f"{report['meters']:.1f} m including the return to the dock")]
    for i,(im,crop,(headline,sub)) in enumerate(zip(frames,details,labels)):
        top = 95+324*i
        d.text((22,top),headline,font=title,fill='#282720')
        d.text((22,top+37),sub,font=text,fill='#524f47')
        output.paste(Image.fromarray(im).resize((242,242),Image.Resampling.LANCZOS),(22,top+66))
        output.paste(crop.resize((224,224),Image.Resampling.LANCZOS),(360,top+76))
    output.save(folder/'lek-kite-to-pumpkin.jpg',quality=93)


def exercise(browser, previous, gallery, photo, folder, db, order):
    grain = 'spiral' if order=='whole' else 'fluted'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    table = Table(db)
    with served(previous,db,table,prepared=True) as url,browser.new_page(**MOBILE) as first:
        traffic = PhoneTraffic(url)
        first.route('http**://**/*',traffic.check)
        wide,jobs = existing_room(first,url,traffic.photo(photo.name,photo.read_bytes(),'image/jpeg'))
        choose(first,'zone','outer')
        preview(first,-1,order=order)
        initial_files = drawing_files(first,'#downloads')
        saved,_ = saved_jobs(first,url,initial_files,jobs)
        original = saved['state']
        (folder/'starting-bed.b64').write_text(original['bed'])
        assert original['widePortrait'] and original['portraitSeats']==2
        assert not traffic.violations,traffic.violations
    with served(gallery,db,table) as url,browser.new_page(**MOBILE) as host,browser.new_page(**MOBILE) as guest:
        reopen(host,url,'outer')
        reopen(guest,url,'outer')
        assert guest.request.get(url+API).json()['state']==original
        assert drawing_files(guest,'#roomFiles')==initial_files
        catalog,sources = source_drawings(host,original)
        assert sources==original['guestBorder']
        first = host.evaluate("""([src,place,order])=>{
          const s=JSON.parse(document.querySelector('#scene').textContent);
          return GuestKeepsakeBorder.plan(s,src.map(v=>v.points),order).placements[place];
        }""",[sources,PLACE,order])
        previous_route = (from_files(initial_files,catalog['dock']),first)
        report = {'prepared_border':order,'working_radius_mm':catalog['radiusMm'],
                  'groove_mm':round(catalog['groove']*catalog['radiusMm'],3)}
        state = original
        contrast = wide
        for key,phone,other,subject,words in (
                ('pumpkin',guest,host,'pumpkin_ribbed','a field pumpkin'),
                ('kite',host,guest,original['ids'][PLACE],'saved Ribbon kite')):
            reopen(phone,url,'outer')
            suggest_outer(phone,words,subject if key=='kite' else None)
            selected = sources[PLACE] if key=='kite' else {
                'label':'Lek · '+catalog['labels'][subject],'points':motif(subject).tolist()}
            updated = [*sources[:PLACE],selected]
            signed = drawing_files(phone,'#downloads')
            record,cut,frames,details = check_visit(phone,url,signed,state,contrast,previous_route,updated,catalog,folder/key,grain)
            saved,_ = saved_jobs(phone,url,signed,jobs)
            assert saved['motion']['zone']=='outer' and saved['motion']['guestBorder'] is True
            command = {'place':PLACE,'subject':subject}
            if grain == 'spiral':
                command['grain']='spiral'
            assert saved['motion']['guestBorderSeat']==command,saved['motion'].get('guestBorderSeat')
            after = saved['state']
            for field in ('portrait','center','widePortrait','portraitSeats','ids','guestBook','custom','labels','drawingInterests'):
                assert after.get(field)==original.get(field),field
            assert after['guestBorder'][:PLACE]==sources[:PLACE] and after['outer']==-1
            kept = after['guestBorder'][PLACE]
            assert kept['label']==selected['label']
            np.testing.assert_allclose(kept['points'],selected['points'],rtol=0,atol=5.1e-9)
            n = len(frames[0])
            center,far,neighbors = masks(n,catalog,route_details(phone,updated,grain)['sector'])
            for mask in [center,far,*neighbors]:
                np.testing.assert_array_equal(bed(after,n)[mask],bed(state,n)[mask])
            reopen(other,url,'outer')
            assert other.request.get(url+API).json()['state']==after
            assert drawing_files(other,'#roomFiles')==signed
            report[key] = record
            if key=='pumpkin':
                pumpkin_files = signed
                sheet(folder,frames,details,record)
                reopen(other,url,'center')
                mobile_chairs(other,['Seat 1 of 2','Seat 2 of 2'],folder/key)
            previous_route,contrast,state = cut,state,after
        assert state['guestBorder']==original['guestBorder']
        # Deliberately leave the two rings different. If restoration ever
        # uses the border as its source, it will engrave a pumpkin in both.
        reopen(host,url,'outer')
        suggest_outer(host,'a field pumpkin')
        assert drawing_files(host,'#downloads')==pumpkin_files
        pumpkin,_ = saved_jobs(host,url,pumpkin_files,jobs)
        state = pumpkin['state']
        assert state['guestBorder'][:PLACE]==sources[:PLACE] and state['ids']==original['ids']
        assert 'pumpkin' in state['guestBorder'][PLACE]['label'].lower()
        reopen(guest,url,'center')
        guest.locator('#restoreGuests').click()
        restore_files = drawing_files(guest,'#downloads')
        route = from_files(restore_files,catalog['dock'])
        data = guest.evaluate("""state=>{
          const s=JSON.parse(document.querySelector('#scene').textContent);
          const p=OasisRingPlanner.restoreGuests(s,state.ids,state.custom);
          return {artStart:p.segments[0].length+p.segments[1].length-2,geo:s.live.planner.geometry};
        }""",original)
        g = catalog['groove']
        ink = cKDTree(check.sample_walk(route[data['artStart']:],g/32))
        misses = []
        for slot in range(3):
            points = contour_samples(contour(original,slot,data['geo']),g/32)
            miss = float(ink.query(points)[0].max())*catalog['radiusMm']
            assert miss < g*catalog['radiusMm']/5,(slot,miss)
            misses.append(round(miss,3))
        # Prove the substituted pumpkin would actually have failed this test.
        wrong = dict(original,ids=[*original['ids'][:PLACE],'pumpkin_ribbed'])
        pumpkin_outline = contour_samples(contour(wrong,PLACE,data['geo']),g/32)
        wrong_miss = float(ink.query(pumpkin_outline)[0].max())*catalog['radiusMm']
        assert wrong_miss > 2*g*catalog['radiusMm'],wrong_miss
        report['restored_middle']={'source_labels':[s['label'] for s in sources],'max_error_mm':misses,
                                   'wrong_pumpkin_error_mm':round(wrong_miss,2),'outer_label':state['guestBorder'][PLACE]['label']}
        restored,last = saved_jobs(guest,url,restore_files,jobs)
        restored = restored['state']
        reopened=frame(guest)
        Image.fromarray(reopened).save(folder/'restored-with-pumpkin.png')
        seat_view(reopened,data['geo'],PLACE).save(folder/'restored-middle-kite.jpg',quality=95)
        rim = route_details(guest,state['guestBorder'],grain)['placement']
        pumpkin_points = np.asarray(state['guestBorder'][PLACE]['points'])
        chair_detail(reopened,rim['angle'],rim['center'],pumpkin_points,rim['scale'],g).save(folder/'restored-outer-pumpkin.jpg',quality=95)
        reopen(host,url,'outer')
        assert drawing_files(host,'#roomFiles')==pumpkin_files
        assert host.request.get(url+API).json()['state']==restored
        assert restored['ids']==original['ids'] and not restored.get('widePortrait') and restored['guestBook']==original['guestBook']
        intact = old_border_survives(state,restored,n,catalog)
        for i,job in enumerate(jobs,1):
            assert table.dispatched(i)==job
            table.outcome='complete'
        wait_table(guest,url,state='idle',ready=True,queued=0,revision=last)
        assert len(table.calls)==len(jobs)
        report.update(saved_guest_files=len(jobs),restored_rim_pixels=int(intact.sum()))
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('photo',type=Path)
    parser.add_argument('--previous',required=True,type=Path)
    parser.add_argument('--evidence',type=Path)
    parser.add_argument('--prepared-order',choices=('whole','progressive','both'),default='both')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            folder = args.evidence or Path(tmp)/'evidence'
            orders = ('progressive','whole') if args.prepared_order=='both' else (args.prepared_order,)
            for order in orders:
                exercise(browser,args.previous,args.gallery,args.photo,folder/order,Path(tmp)/(order+'.db'),order)
