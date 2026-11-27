#!/usr/bin/env python3
"""Check a personalized border against earlier guest drawings and a simulated table's queue."""
import argparse
import copy
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright

from test_attached_garden import Table, served, wait_table
from test_garden_reveal_room import change, put
from test_garden_room import API, open_room, suggest
from test_ring_guest_border import save


def border_request(page, saved, order):
    state = saved['state']
    frame, files, starts, wipes = page.evaluate("""([state,order])=>{
        const scene=JSON.parse(document.querySelector('#scene').textContent), catalog=scene.live.planner;
        const frame=state.ids.map((id,slot)=>{
            if (id===catalog.openSubject) return null;
            const name=['Thomas','Alex','Lek'][slot], label=state.labels[id] || catalog.subjects[id];
            return {label:name+' · '+label,points:state.custom[id] || OasisRingPlanner.unpack(catalog.pairMotifs[id])};
        });
        const route=GuestKeepsakeBorder.plan(scene,frame.map(item=>item?.points || null),order);
        return [frame,OasisRingPlanner.files(route.path,'guest-border'),route.placements.map(p=>p?.first ?? null),
                route.sectorSteps?.map(s=>s.start) || []];
    }""", [state,order])
    body = change(page, state, saved['revision'], 0, state['ids'][0], files)
    body['state'].update(outer=-1, guestBorder=frame)
    body['motion'] = dict(zone='outer', files=files, guestBorder=True)
    if order == 'progressive':
        body['motion']['guestBorderOrder'] = order
    return body, starts, wipes


def wrong_row(body, row):
    """Move an interior vertex, leaving the border clear, entry and exit intact."""
    altered = copy.deepcopy(body)
    for part in altered['motion']['files']:
        points = part['text'].splitlines()
        if row < len(points):
            theta, rho = map(float, points[row].split())
            points[row] = f'{theta:.5f} {rho-.007:.5f}'
            part['text'] = '\n'.join(points)+'\n'
            return altered
        row -= len(points)-1
    raise AssertionError('Missing border point')


def fill_empty_border_seat(page, url, saved, order):
    """Fill Lek's empty rim seat while the middle ring still remembers an empty place."""
    state, revision = saved['state'], saved['revision']
    assert state['guestBorder'][2] is None
    subject = 'pumpkin_ribbed'
    art, files, stroke, sweep, grain, wrong_texture = page.evaluate("""([subject,encoded])=>{
        const scene=JSON.parse(document.querySelector('#scene').textContent), catalog=scene.live.planner;
        const points=OasisRingPlanner.unpack(catalog.pairMotifs[subject]);
        const grain=GuestBorderGrain.read(scene,Float32Array.from(atob(encoded),v=>v.charCodeAt(0)/170-1));
        const route=GuestKeepsakeBorder.planSeat(scene,2,points,grain);
        const other=GuestKeepsakeBorder.planSeat(scene,2,points,grain==='spiral' ? 'fluted' : 'spiral');
        return [{points,label:'Lek · '+catalog.subjects[subject]},OasisRingPlanner.files(route.path,'guest-border'),
                route.placements[2].first,route.sectorSteps[0].start,grain,OasisRingPlanner.files(other.path,'guest-border')];
    }""", [subject,state['bed']])
    assert grain == ('spiral' if order == 'whole' else 'fluted')
    request = change(page,state,revision,2,state['ids'][2],files)
    request['state']['guestBorder'][2] = art
    assert state['guestBorderGrain'] == grain
    motion = dict(zone='outer',guestBorder=True,guestBorderSeat=dict(place=2,subject=subject),files=files)
    if grain == 'spiral':
        motion['guestBorderSeat']['grain'] = grain
    request['motion'] = motion
    for update in ({'place':1}, {'place':True}, {'subject':'guitar'}):
        put(page,url,dict(request,motion=dict(motion,guestBorderSeat=dict(motion['guestBorderSeat'],**update))),400)
    other_seat = dict(place=2,subject=subject)
    if grain == 'fluted':
        other_seat['grain'] = 'spiral'
    put(page,url,dict(request,motion=dict(motion,guestBorderSeat=other_seat,files=wrong_texture)),400)
    put(page,url,dict(request,motion=dict(motion,guestBorderOrder='progressive')),400)
    put(page,url,dict(request,motion=dict(zone='outer',files=files,guestBorder=True)),400)
    for row in (sweep+4, stroke+3, 8):
        put(page,url,wrong_row(request,row),400)
    for key, value in (('guestBorder',[art,*request['state']['guestBorder'][1:]]), ('borderGuest','Different name'),
                       ('guestBorderGrain','spiral' if grain == 'fluted' else 'fluted')):
        put(page,url,dict(request,state=dict(request['state'],**{key:value})),400)
    assert page.request.get(url+API).json() == saved
    last = put(page,url,request,200).json()['revision']
    put(page,url,request,409)
    put(page,url,dict(request,revision=last),400)
    assert page.request.get(url+API+'/drawings/outer').json() == {'revision':last,'files':files}
    return last, files


def exercise(page, gallery, previous, directory, order):
    db = directory/'party.db'
    table = Table(db)
    with served(previous, db, table, prepared=True) as url:
        open_room(page,url)
        files = page.locator('#scene').evaluate('el=>JSON.parse(el.textContent).live.setup')
        suggest(page,'a guitar for Thomas and an open book for Alex')
        prior, _ = save(page,url+API)
        files.extend(prior['motion']['files'])
        before = page.request.get(url+API).json()

    with served(gallery, db, table) as url:
        open_room(page,url)
        assert page.request.get(url+API).json() == before
        frame, starts, wipes = border_request(page,before,order)
        assert frame['state']['guestBorder'][-1] is None
        assert frame['state']['guestBorder'][1]['label'] == 'Alex · Open book'
        put(page,url,dict(frame,motion=None),400)
        put(page,url,dict(frame,motion={'zone':'outer','files':frame['motion']['files']}),400)
        put(page,url,wrong_row(frame,starts[1]+2),400)
        if order == 'progressive':
            assert len(wipes) == 7
            for start in (wipes[0], wipes[-1]):
                put(page,url,wrong_row(frame,start+5),400)
            put(page,url,dict(frame,motion=dict(zone='outer',files=frame['motion']['files'],guestBorder=True)),400)
        elif page.locator('#scene').evaluate('el=>JSON.parse(el.textContent).live.guestBorderProgressive===true'):
            put(page,url,dict(frame,motion=dict(frame['motion'],guestBorderOrder='progressive')),400)
        swapped = copy.deepcopy(frame)
        swapped['state']['guestBorder'][:2] = swapped['state']['guestBorder'][:2][::-1]
        put(page,url,swapped,400)
        covered = copy.deepcopy(frame)
        covered['state']['guestBorder'][2] = covered['state']['guestBorder'][0]
        put(page,url,covered,400)
        assert page.request.get(url+API).json() == before
        revision = put(page,url,frame,200).json()['revision']
        files.extend(frame['motion']['files'])
        put(page,url,frame,409)
        assert page.request.get(url+API+'/drawings/outer').json() == {'revision':revision, 'files':frame['motion']['files']}

    with served(gallery, db, table) as url:
        open_room(page,url)
        snapshot = page.request.get(url+API).json()
        assert snapshot['state']['guestBorder'] == frame['state']['guestBorder']
        renamed = copy.deepcopy(snapshot)
        renamed['state']['guestBorder'][0]['label']='Someone else’s drawing'
        put(page,url,renamed,400)
        # Naming this border alone preserves the exact queued motion.
        snapshot['state']['borderGuest'] = 'Family'
        last = put(page,url,snapshot,200).json()['revision']
        assert page.request.get(url+API+'/drawings/outer').json()['revision'] == revision
        if page.locator('#scene').evaluate('el=>JSON.parse(el.textContent).live.guestBorderSeat===true'):
            last, requested = fill_empty_border_seat(page,url,page.request.get(url+API).json(),order)
            files.extend(requested)
    with served(gallery, db, table) as url:
        open_room(page,url)
        for i, part in enumerate(files,1):
            assert table.dispatched(i) == part
            table.outcome='complete'
        wait_table(page,url,ready=True,queued=0,revision=last)
        assert len(table.calls) == len(files)
        print(f'One open place; both artworks verified in the border. {len(files)} files played once across restart.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--order',choices=['whole','progressive'],default='whole')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome=sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser, browser.new_page() as page:
            exercise(page,args.gallery,args.previous,Path(tmp),args.order)
