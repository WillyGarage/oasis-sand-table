#!/usr/bin/env python3
"""Replay a progressively engraved guest border from two phones and a previously kept family portrait."""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from guest_book_art import engraving
from test_attached_garden import Table, served, wait_table
from test_garden_family_portrait import bed, mobile_chairs, saved_jobs
from test_garden_room import API, choose, drawing_files
from test_guest_keepsake_border import chair_detail, existing_room, reopen, signed_subject, source_drawings
from test_ring_guest_border import MOBILE, from_files, preview, replay
from test_ring_object_photo import PhoneTraffic
from test_ring_photo import frame


def plan(page, sources, order):
    return page.evaluate("""([sources,order])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent);
      const {placements,moments,halfwayIndex}=GuestKeepsakeBorder.plan(s,sources.map(x=>x?.points??null),order);
      return {placements,moments,halfwayIndex};
    }""", [sources,order])


def book_landmark(route, placement):
    """First arrival at every major bound of the two pages including the folded corner."""
    _, strokes = engraving()
    required = np.vstack([strokes[k] for k in ('spine','left_edge','left_pages','right_pages','right_side','folded_edge','crease')])
    a = placement['angle']
    right, up = np.array([-np.sin(a), np.cos(a)]), -np.array([np.cos(a), np.sin(a)])
    sites = placement['center'] + placement['scale']*(right*required[:,0,None]+up*required[:,1,None])
    start, end = placement['first'], placement['last']
    ink = route[start:end+1]
    xy = ink[:,1,None]*np.column_stack((np.cos(ink[:,0]),np.sin(ink[:,0])))
    visits = cKDTree(xy).query_ball_point(sites,r=.000025)
    assert all(visits), 'An authored book stroke is missing from the signed border file.'
    return int(start+max(min(x) for x in visits))


def measured(route, data, sources, catalog):
    walking = check.travel(route)*catalog['radiusMm']/1000
    for i,(p,source) in enumerate(zip(data['placements'], sources)):
        signed_subject(route,p,source['points'],catalog['angles'][i],catalog['radiusMm'])
    first = min(range(len(sources)),key=lambda p:data['placements'][p]['last'])
    assert first==1 and 'book' in sources[first]['label'].lower()
    finished = data['placements'][first]['last']
    landmark = book_landmark(route,data['placements'][first])
    assert landmark < finished
    return {'first':first,'landmark':landmark,'firstEnd':finished,
            'landmark_m':round(walking[landmark],3),'first_m':round(walking[finished],3),'total_m':round(walking[-1],3),
            'first_percent':round(100*walking[finished]/walking[-1],2)}, walking


def check_old_and_finished(page, old, route, first, half, catalog):
    """Track the old leaf relief and the new book independently by subtracting two sand beds."""
    old_outline = page.evaluate("""idx=>JSON.parse(document.querySelector('#scene').textContent).zones.outer.drawings[idx]""",
                                old['outer'])
    leaves = check.sample_walk(old_outline,catalog['groove']*.095)
    radial = np.linalg.norm(leaves,axis=1)
    keep = (radial > route[:,1].min()+catalog['groove']) & (radial < catalog['outer']-2*catalog['groove'])
    leaves = leaves[keep]
    n = len(frame(page))
    def pixels(xy):
        p = np.rint((1+xy*[1,-1])*(n-1)/2).astype(int)
        return np.unique(p[:,0]+n*p[:,1]).tolist()
    # Choose leaves at least 120 degrees away, wholly beyond the first cleared sector.
    azimuth = np.arctan2(leaves[:,1],leaves[:,0])
    far = abs(np.angle(np.exp(1j*(azimuth-first['angle'])))) > np.pi*2/3
    book = check.sample_walk(route[first['first']:first['last']+1],catalog['groove']*.09)
    book = book[np.linalg.norm(book,axis=1)<catalog['outer']-4*catalog['groove']]
    result = page.evaluate("""([raw,path,first,half,allLeaves,farLeaves,newSites])=>{
      const s=JSON.parse(document.querySelector('#scene').textContent),live=s.live;
      const original=Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1);
      const sim=new RingSand(live.size,live.groove,live.profile),neutral=original.slice();
      sim.carve(neutral,s.zones.outer.erase);
      const strong=(a,b,sites)=>sites.filter(i=>Math.abs(a[i]-b[i])>.15);
      const delta=(a,b,sites)=>sites.reduce((sum,i)=>sum+Math.abs(a[i]-b[i]),0);
      const all=strong(original,neutral,allLeaves),far=strong(original,neutral,farLeaves);
      const after=end=>{
        const a=original.slice(),b=neutral.slice(),trip=path.slice(0,end+1);
        sim.carve(a,trip); sim.carve(b,trip);
        return [delta(a,b,all)/delta(original,neutral,all),delta(a,b,far)/delta(original,neutral,far)];
      };
      const a=original.slice();
      sim.carve(a,path.slice(0,first.first+1));
      const b=a.slice();
      sim.carve(a,path.slice(first.first,first.last+1));
      const book=strong(a,b,newSites),ink=delta(a,b,book);
      const remaining=path.slice(first.last);
      sim.carve(a,remaining); sim.carve(b,remaining);
      return {leaf_samples:all.length,far_leaf_samples:far.length,
              first:after(first.last),half:after(half),end:after(path.length-1),
              book_samples:book.length,first_book_still_present:delta(a,b,book)/ink};
    }""",[old['bed'],route.tolist(),first,half,pixels(leaves),pixels(leaves[far]),pixels(book)])
    assert result['leaf_samples']>250 and result['far_leaf_samples']>80, result
    assert result['first'][1]>.985 and 0.1<result['half'][0]<result['first'][0] and max(result['end'])<.01,result
    assert result['book_samples']>40 and result['first_book_still_present']>.98,result
    return result


def make_sheet(folder, frames, closeups, result):
    regular=ImageFont.truetype('DejaVuSans.ttf',18)
    title=ImageFont.truetype('DejaVuSans-Bold.ttf',25)
    sheet=Image.new('RGB',(620,1084),'#f6f1e9')
    draw=ImageDraw.Draw(sheet)
    draw.text((20,14),'A guest border, one drawing at a time',font=title,fill='#282720')
    draw.text((20,53),'Sand simulation · 420 mm working radius · 7 mm groove',font=regular,fill='#4e4b42')
    for i,(index,headline,sub) in enumerate(((0,'Autumn leaves','Before the border changes'),
        (1,'Alex’s book appears',f"{result['first_m']:.1f} m of ball travel"),
        (3,'All three drawings are finished',f"{result['total_m']:.1f} m of ball travel"))):
        top=95+i*324
        draw.text((20,top),headline,font=title,fill='#282720')
        draw.text((20,top+36),sub,font=regular,fill='#4e4b42')
        image=Image.fromarray(frames[index]).resize((242,242),Image.Resampling.LANCZOS)
        sheet.paste(image,(25,top+66))
        sheet.paste(closeups[index].resize((225,225),Image.Resampling.LANCZOS),(365,top+77))
    sheet.save(folder/'before-first-final.jpg',quality=93)


def exercise(browser, gallery, previous, photo, db, folder):
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    table=Table(db)
    with served(previous,db,table,prepared=True) as url,browser.new_page(**MOBILE) as older:
        traffic=PhoneTraffic(url)
        older.route('http**://**/*',traffic.check)
        old,jobs=existing_room(older,url,traffic.photo(photo.name,photo.read_bytes(),'image/jpeg'))
        choose(older,'zone','outer')
        older.locator('#borderDesign').select_option('-1')
        preview(older,-1,order='whole' if older.locator('#borderOrder').is_visible() else None)
        reference=drawing_files(older,'#downloads')
        assert not traffic.violations,traffic.violations
    with served(gallery,db,table) as url,browser.new_page(**MOBILE) as host,browser.new_page(**MOBILE) as second:
        reopen(host,url,'outer')
        reopen(second,url,'outer')
        assert second.request.get(url+API).json()['state']==old
        catalog,sources=source_drawings(host,old)
        host.locator('#borderDesign').select_option('-1')
        expect(host.locator('#borderOrder')).to_have_value('progressive')
        preview(host,-1,order='whole')
        files=drawing_files(host,'#downloads')
        assert files==reference,'Whole-border downloads differ from the previous release.'
        route=from_files(files,catalog['dock'])
        regular,_=measured(route,plan(host,sources,'whole'),sources,catalog)
        preview(host,-1,order='progressive')
        signed=drawing_files(host,'#downloads')
        route=from_files(signed,catalog['dock'])
        assert signed!=files and route[:,1].min()>catalog['inner']
        data=plan(host,sources,'progressive')
        faster,walking=measured(route,data,sources,catalog)
        assert faster['first_m'] < regular['first_m']*.5
        first=data['placements'][faster['first']]
        assert data['moments'][0]['place']==faster['first'] and data['moments'][0]['endIndex']==first['last']
        half=data['halfwayIndex']
        assert abs(walking[half] - walking[-1]/2) <= max(np.diff(walking))
        done=[sources[m['place']]['label'] for m in data['moments'] if m['endIndex']<=half]
        expect(host.locator('#middleStageLabel')).to_have_text('In progress')
        final=frame(host)
        choose(host,'stage','original')
        before=frame(host)
        choose(host,'stage','cleared')
        expect(host.locator('#guestMoment')).to_have_value('first')
        expect(host.locator('.caption')).to_contain_text(sources[faster['first']]['label']+' is the first finished')
        early=frame(host)
        host.locator('#guestMoment').select_option('halfway')
        expect(host.locator('.caption')).to_contain_text('Halfway through the ball’s travel')
        for label in done:
            expect(host.locator('.caption')).to_contain_text(label)
        middle=frame(host)
        choose(host,'stage','redrawn')
        n=len(before)
        y,x=np.mgrid[-1:1:complex(n),-1:1:complex(n)]
        protected=np.hypot(x,y)<=catalog['inner']
        assert int(protected.sum())>100000
        frames=[before,early,middle,final]
        for image,cut in zip(frames[1:],(first['last'],half,len(route)-1)):
            exact=replay(host,old['bed'],route[:cut+1])
            delta=np.abs(image.astype(np.int16)-exact.astype(np.int16))
            assert delta.mean()<1.1 and np.percentile(delta,99)<6,(cut,delta.mean(),np.percentile(delta,99))
            np.testing.assert_array_equal(before[protected],image[protected])
        closeups=[]
        for name,img in zip(('before','first','half','final'),frames):
            Image.fromarray(img).save(folder/(name+'.png'))
            for i,p in enumerate(data['placements']):
                detail=chair_detail(img,p['angle'],p['center'],np.array(sources[i]['points']),p['scale'],catalog['groove'])
                detail.save(folder/f"chair-{i+1}-{name}.jpg",quality=94)
                if i == faster['first']:
                    closeups.append(detail)
        make_sheet(folder,frames,closeups,faster)
        sand=check_old_and_finished(host,old,route,first,half,catalog)
        assert host.request.get(url+API).json()['state']==old
        saved,rev=saved_jobs(host,url,signed,jobs)
        motion=saved['motion']
        assert motion['zone']=='outer' and motion['guestBorder'] is True and motion['guestBorderOrder']=='progressive'
        state=saved['state']
        assert state['outer']==-1 and state['guestBorder']==sources
        for key in ('ids','guestBook','custom','labels','widePortrait','portrait','portraitSeats','center','drawingInterests'):
            assert old.get(key)==state.get(key),key
        np.testing.assert_array_equal(bed(old,n)[protected],bed(state,n)[protected])
        reopen(second,url,'outer')
        assert second.request.get(url+API).json()['state']==state
        assert drawing_files(second,'#roomFiles')==signed
        second.locator('#borderDesign').select_option('-1')
        expect(second.locator('#borderPreview')).to_be_disabled()
        np.testing.assert_array_equal(before[protected],frame(second)[protected])
        reopen(second,url,'center')
        mobile_chairs(second,['Seat 1 of 2','Seat 2 of 2'],folder)
        for i,job in enumerate(jobs,1):
            assert table.dispatched(i)==job
            table.outcome='complete'
        wait_table(second,url,state='idle',ready=True,queued=0,revision=rev)
        assert len(table.calls)==len(jobs)
        report={'first_guest':sources[faster['first']]['label'],'finished_at_halfway':done,
                'whole':regular,'progressive':faster,'modeled_relief':sand,'protected_pixels':int(protected.sum()),
                'border_files':len(signed),'queued_files':len(jobs)}
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('photo',type=Path)
    parser.add_argument('--previous',required=True,type=Path)
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args.gallery,args.previous,args.photo,Path(tmp)/'family.db',args.evidence or Path(tmp)/'evidence')
