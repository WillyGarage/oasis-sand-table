#!/usr/bin/env python3
"""Compare the actual phone exports as an acoustic guitar emerges from a guest’s phage."""
import argparse
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from guest_guitar import guitar
from test_garden_room import API, choose, drawing_files, open_room, room, suggest
from test_guest_custom_reveal import previous_relief, protected_sand
from test_guest_place import unpack
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_lettering import seat_view
from test_ring_object_photo import expand
from test_ring_photo import frame


def signed_route(files, dock):
    return from_files([(f['name'],f['text'].encode()) for f in files],dock)


def features(geometry, slot):
    """Sample unique physical strokes in the authored guitar, before following any toolpath."""
    shape = guitar()
    angle = math.radians(30)
    c,s = np.cos(angle),np.sin(angle)
    upright = shape @ np.array([[c,s],[-s,c]])
    a = geometry['angles'][slot]
    normal = np.array([np.cos(a),np.sin(a)])
    tangent = np.array([-normal[1],normal[0]])
    physical = geometry['center']*normal + geometry['scale']*(shape[:,0,None]*tangent - shape[:,1,None]*normal)
    result = {k:[] for k in ('body','sound_hole','neck','headstock','bridge','whole')}
    seen = set()
    for i,(p,q) in enumerate(zip(upright,upright[1:])):
        u,v = physical[i:i+2]
        length = np.linalg.norm(v-u)
        if length < 1e-9:
            continue
        key = tuple(sorted((tuple(p.round(7)),tuple(q.round(7)))))
        if key in seen:
            continue
        seen.add(key)
        on_bridge = abs(p[1]+.57)<1e-6 and abs(q[1]+.57)<1e-6
        if on_bridge and p[0]*q[0]>=0:
            continue  # The single full bridge spans both outward/return half strokes.
        groups = ['whole']
        if i<48 or i>=len(shape)-49:
            groups.append('body')
        if all(abs(np.linalg.norm(x-[0,-.147])-.206)<1e-6 for x in (p,q)):
            groups.append('sound_hole')
        if all(abs(abs(x[0])-.132)<1e-6 and .188-1e-6<=x[1]<=.645+1e-6 for x in (p,q)):
            groups.append('neck')
        if min(p[1],q[1]) >= .645-1e-6 and max(p[1],q[1]) > .645+1e-6:
            groups.append('headstock')
        if on_bridge:
            groups.append('bridge')
        count = max(1,math.ceil(length/.00075))
        xy = u+(np.arange(count)[:,None]+.5)/count*(v-u)
        for group in groups:
            result[group].append((xy,np.full(count,length/count)))
    return {k:(np.vstack([x for x,w in v]),np.concatenate([w for x,w in v])) for k,v in result.items()}


def visit_bounds(route, excursion, rail):
    first = np.flatnonzero(abs(excursion[:,1]-rail)>1e-7)[0]-1
    angle = excursion[first,0]
    at = (abs(check.wrapped(route[:,0]-angle))<=1e-5) & (abs(route[:,1]-rail)<=1e-5)
    found = np.flatnonzero(at)
    entering = found[abs(route[found-1,1]-rail)<=1e-5]
    leaving = found[abs(route[found+1,1]-rail)<=1e-5]
    assert len(entering)==len(leaving) and np.all(entering<leaving)
    return np.column_stack((entering,leaving))


def sample_trip(route, distance, start, end):
    """Sample the signed polar interpolation and remember travel to each sampled location."""
    path = route[start:end+1]
    cum = distance[start:end+1]
    dr = np.diff(path,axis=0)
    counts = np.maximum(1,np.ceil(np.hypot(dr[:,1],dr[:,0]*np.maximum(path[:-1,1],path[1:,1]))/.0003)).astype(int)
    indices = np.repeat(np.arange(len(counts)),counts)
    u = (np.arange(len(indices))-np.repeat(np.cumsum(counts)-counts,counts))/counts[indices]
    pose = np.vstack([path[indices]+u[:,None]*dr[indices],path[-1]])
    xy = pose[:,1,None]*np.column_stack((np.cos(pose[:,0]),np.sin(pose[:,0])))
    return xy, np.r_[cum[indices]+u*np.diff(cum)[indices],cum[-1]]


def coverage(scene, slot, record):
    catalog = scene['guest_plan']
    g = catalog['geometry']
    route = signed_route(record['files'],scene['dock'])
    excursion = unpack(catalog['excursions'][slot]['guitar_silhouette'])
    visits = visit_bounds(route,excursion,g['rail'])
    mm = scene['assumed_working_radius_mm']
    travel = check.travel(route)*mm/1000
    # Exclude every clearing row from the feature test. The last full retrace
    # certifies which early marks are part of the actual finished instrument.
    samples = [sample_trip(route,travel,*visit) for visit in visits]
    trees = [(cKDTree(p),v) for p,v in samples]
    groove=scene['groove_width']
    sweep_spacing=groove/55
    sweep_parts=[check.sample_walk(route[stop:start+1],sweep_spacing)
                 for (_,stop),(start,_) in zip(visits,visits[1:])]
    next_clears=[cKDTree(np.vstack(sweep_parts[i:])) for i in range(len(sweep_parts))]
    clearance=1.65*groove+2*scene['tracking_margin']+sweep_spacing
    arrivals,engraved = {},{}
    for name,(points,weight) in features(g,slot).items():
        first = np.full(len(points),np.inf)
        raw = first.copy()
        for i,(tree,meters) in enumerate(trees):
            hits = tree.query_ball_point(points,.0007)
            when=np.array([meters[idx].min() if len(idx) else np.inf for idx in hits])
            raw=np.minimum(raw,when)
            if i<len(next_clears):
                when[next_clears[i].query(points)[0]<clearance]=np.inf
            first=np.minimum(first,when)
        assert np.isfinite(first).all(),(slot,name,'unmatched authored strokes')
        arrivals[name] = (first,weight)
        engraved[name] = (raw,weight)
    def fraction(name,at,mapping):
        first,weight = mapping[name]
        return round(float(100*weight[first<=at].sum()/weight.sum()),1)
    def crossing(name,threshold,mapping):
        first,weight = mapping[name]
        order = np.argsort(first)
        return round(float(first[order][np.searchsorted(np.cumsum(weight[order]),threshold*sum(weight)-1e-12)]),3)
    progress=[m['endIndex'] for m in record.get('progressMoments',[])] or [record['progressIndex']]
    report = {'travel_m':round(float(travel[-1]),3),'first_complete_guitar_m':crossing('whole',1,engraved),
              'clearance_certified_complete_m':crossing('whole',1,arrivals),
              'displayed_progress_m':[round(float(travel[i]),3) for i in progress],
              'milestones_m':{s:{str(int(t*100)):crossing(s,t,engraved) for t in (.5,.95,1)} for s in arrivals},
              'visits':[{'end':int(end),'meters':round(float(travel[end]),3),
                         'clearance_certified_percent':{s:fraction(s,travel[end],arrivals) for s in arrivals},
                         'engraved_percent':{s:fraction(s,travel[end],engraved) for s in arrivals}} for _,end in visits[:-1]]}
    return route, visits, report


def relief_survival(page, before, route, visits, scene, slot):
    """Run the same later rake movements on two beds, one with the early guitar strokes and one without."""
    geometry=scene['guest_plan']['geometry']
    sides=len(frame(page))
    sites=[]
    early_ink=[]
    for start,end in visits[:-2]:
        early_ink.append(check.sample_walk(route[start:end+1],.0003))
        ink=cKDTree(np.vstack(early_ink))
        groups={}
        for name,(points,_) in features(geometry,slot).items():
            carved=points[ink.query(points)[0]<.0007]
            pix=np.rint((carved*[1,-1]+1)*(sides-1)/2).astype(int)
            groups[name]=np.unique(pix[:,1]*sides+pix[:,0]).tolist()
        sites.append(groups)
    return page.evaluate("""([raw,route,visits,sites])=>{
      const l=JSON.parse(document.querySelector('#scene').textContent).live;
      const sim=new RingSand(l.size,l.groove,l.profile);
      const rawBed=()=>Float32Array.from(atob(raw),c=>c.charCodeAt(0)/170-1);
      const out=[];
      for(let j=0;j<visits.length-2;j++){
        const a=rawBed(),b=a.slice();
        let at=0;
        for(const [enter,leave] of visits.slice(0,j+1)){
          const common=route.slice(at,enter+1);
          sim.carve(a,common);sim.carve(b,common);
          sim.carve(a,route.slice(enter,leave+1));at=leave;
        }
        const groups={};
        for(const [name,px] of Object.entries(sites[j])){
          const hit=px.filter(i=>Math.abs(a[i]-b[i])>.12);
          groups[name]={hit,initial:hit.reduce((sum,i)=>sum+Math.abs(a[i]-b[i]),0)};
        }
        for(let i=j+1;i<visits.length;i++){
          const common=route.slice(at,visits[i][0]+1);
          sim.carve(a,common);sim.carve(b,common);at=visits[i][1];
        }
        const result={};
        for(const [name,{hit,initial}] of Object.entries(groups)){
          const remaining=hit.reduce((sum,i)=>sum+Math.abs(a[i]-b[i]),0);
          result[name]={pixels:hit.length,retained_percent:initial ? Math.round(1000*remaining/initial)/10 : null};
        }
        out.push(result);
      }
      return out;
    }""",[before['bed'],route.tolist(),visits.tolist(),sites])


def check_phone(browser, gallery, scene, slot, folder, mode):
    name = ('Thomas','Alex')[slot]
    with tempfile.TemporaryDirectory() as db,room(gallery,Path(db)/'room.db') as url,browser.new_page(**MOBILE) as page:
        open_room(page,url)
        choose(page,'zone','middle')
        # Fill the two neighbors as well, so their unchanged sand includes actual drawings.
        for i,(person,id_) in enumerate(zip(('Thomas','Alex','Lek'),('phage','books_open','temple_gable'))):
            expand(page,'#peopleBox')
            page.locator('#personPick').select_option(label=person)
            page.locator('#personDrawing').select_option('phage' if i==slot else id_)
            page.locator('#personSubmit').click()
            save(page,url+API)
        before = page.request.get(url+API).json()['state']
        assert before['ids'][slot]=='phage'
        if page.locator('#peopleBox').evaluate('el=>el.open'):
            page.locator('#peopleBox summary').first.click()
        suggest(page,'an acoustic guitar for '+name)
        files = drawing_files(page,'#downloads')
        data = page.evaluate("""slot=>{
          const s=JSON.parse(document.querySelector('#scene').textContent), c=s.live.planner;
          return {live:{size:s.live.size,groove:s.live.groove,planner:{geometry:c.geometry,erase:c.erase}},
                  record:c.places[slot].revealTargets.guitar_silhouette};
        }""",slot)
        record = data['record']
        assert files==[(f['name'],f['text'].encode()) for f in record['files']]
        route,visits,metrics = coverage(scene,slot,record)
        final = frame(page)
        played = replay(page,before['bed'],*(np.loadtxt(f['text'].splitlines()) for f in record['files']))
        delta = np.abs(final.astype(np.int16)-played.astype(np.int16))
        assert delta.mean()<1.1 and np.percentile(delta,99)<6,(mode,slot,'finished',delta.mean())
        choose(page,'stage','original')
        initial = frame(page)
        choose(page,'stage','cleared')
        expect(page.locator('#middleStageLabel')).to_have_text('In progress')
        pages=[]
        moments = record.get('progressMoments') or [{'label':'First visit','endIndex':record['progressIndex']}]
        for i,m in enumerate(moments):
            if len(moments)>1:
                page.locator('#guestMoment').select_option(str(i))
                expect(page.locator('.caption')).to_contain_text(m['label'])
            shown = frame(page)
            # The browser carves each downloaded file separately at a file boundary.
            offset = m['endIndex']; slices=[]
            for file in record['files']:
                rows = np.loadtxt(file['text'].splitlines())
                slices.append(rows[:min(len(rows),offset+1)])
                offset -= len(rows)-1
                if offset<=0: break
            actual = replay(page,before['bed'],*slices)
            diff = np.abs(actual.astype(np.int16)-shown.astype(np.int16))
            assert diff.mean()<1.1 and np.percentile(diff,99)<6,(mode,slot,m,diff.mean())
            pages.append(shown)
        choose(page,'stage','redrawn')
        kept,_ = save(page,url+API)
        assert kept['motion']['earlyFrom']=='phage' and kept['state']['ids'][slot]=='guitar_silhouette'
        info = data['live']
        metrics['early_relief_survival'] = relief_survival(page,before,route,visits,scene,slot)
        metrics['protected'] = protected_sand(before,kept['state'],slot,info,[initial,*pages,final])
        metrics['old_phage_relief'] = previous_relief(page,before,kept['state'],route,record['progressIndex'],slot,info)
        g = scene['guest_plan']['geometry']
        out = folder/f'{name.lower()}-{mode}'
        out.mkdir(exist_ok=True)
        Image.fromarray(final).save(out/'whole-table.jpg',quality=94)
        for i,im in enumerate([initial,*pages,final]):
            seat_view(im,g,slot).save(out/f'chair-{i}.jpg',quality=95)
        for f in record['files']: (out/f['name']).write_text(f['text'])
        return metrics


def comparison(folder, slot, old, new):
    name=('Thomas','Alex')[slot]
    before=folder/(name.lower()+'-previous'); after=folder/(name.lower()+'-new')
    title=ImageFont.truetype('DejaVuSans-Bold.ttf',24)
    text=ImageFont.truetype('DejaVuSans.ttf',18)
    out=Image.new('RGB',(666,692),'#f5f0e6')
    draw=ImageDraw.Draw(out)
    draw.text((20,16),name+'’s acoustic guitar',font=title,fill='#282720')
    draw.text((20,53),'Chair view · simulation at 420 mm working radius',font=text,fill='#514d43')
    panels = [('Previous first visit',old['displayed_progress_m'][0],before/'chair-1.jpg'),
              ('New first visit',new['displayed_progress_m'][0],after/'chair-1.jpg'),
              ('Second visit',new['displayed_progress_m'][1],after/'chair-2.jpg'),
              ('Back at the dock',new['travel_m'],after/'chair-3.jpg')]
    for i,(label,m,path) in enumerate(panels):
        x=20+(i%2)*330; y=93+(i//2)*294
        draw.text((x,y),label,font=title,fill='#282720')
        draw.text((x,y+32),f'{m:.1f} m of ball travel',font=text,fill='#514d43')
        out.paste(Image.open(path).resize((216,216),Image.Resampling.LANCZOS),(x,y+62))
    out.save(folder/f'{name.lower()}-guitar.jpg',quality=95)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('gallery',type=Path);p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--scene',type=Path,required=True);p.add_argument('--evidence',type=Path)
    a=p.parse_args()
    scene=json.loads(a.scene.read_text())
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        folder=a.evidence or Path(tmp)/'evidence';folder.mkdir(parents=True,exist_ok=True)
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report={}
            for slot,name in enumerate(('Thomas','Alex')):
                report[name]={}
                for mode,gallery in [('previous',a.previous),('new',a.gallery)]:
                    report[name][mode]=check_phone(browser,gallery,scene,slot,folder,mode)
                old,new=report[name].values()
                assert len(new['visits'])==3 and len(old['visits'])==2
                assert new['travel_m']<old['travel_m']*1.08
                assert new['milestones_m']['sound_hole']['100']<old['milestones_m']['sound_hole']['100']
                early,second_relief=new['early_relief_survival']
                assert early['body']['pixels']>80 and early['body']['retained_percent']>85,early
                assert all(second_relief[k]['pixels']>20 and second_relief[k]['retained_percent']>95 for k in ('sound_hole','neck'))
                second=new['visits'][1]['engraved_percent']
                assert second['body']==100 and second['sound_hole']==100 and second['neck']>25 and second['headstock']<1
                comparison(folder,slot,old,new)
            (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    main()
