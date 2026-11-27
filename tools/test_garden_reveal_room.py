#!/usr/bin/env python3
"""Check exact early-guest file acceptance, stale revisions and playback on a local simulated table."""
import copy
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile

from playwright.sync_api import sync_playwright

from garden_room import unpack_path
import ring_preview
import ring_scene
from test_attached_garden import Table, served, wait_table
from test_garden_room import API
from thrcommon import motion_files_hash


def motion_part(path, number):
    return {'name': f'guest-ring-{number}.thr',
            'text': ''.join(f'{theta:.5f} {radius:.5f}\n' for theta, radius in path)}


def expose_routes(folder):
    ring_scene.build(folder, 420, 7, 3.5, 4, face_edge=True, guest_pitch_mm=2)
    scene = ring_preview.scene_data(folder/'scene.json', 440)
    live = scene['live']
    cat = live['planner']
    routes = {}
    for slot, old, new in [(0,'phage','guitar'), (0,'books','guitar'), (1,cat['defaults'][1],'temple')]:
        tile = cat['places'][slot]
        approach,clear,recut,home = (unpack_path(tile[key]) for key in ('approach','clear','recut','exit'))
        art = unpack_path(cat['excursions'][slot][new])
        # Two dock-to-dock parts make swapped or duplicated files independently
        # valid physical trips. Only the expected sequence may reach the queue.
        first = ring_scene.join(approach,art,unpack_path(tile.get('fillExit',tile['exit'])))
        last = ring_scene.join(approach,clear,recut,art,home)
        files = [motion_part(first,1),motion_part(last,2)]
        if old == 'phage':
            tile.setdefault('reveals',{}).setdefault(old,{})[new] = {'files':files}
        elif slot == 1:
            # An earlier phone previewed the two-part trip. The regenerated gallery
            # ships only its new trip and the digest of the earlier download.
            tile.setdefault('revealTargets',{})[new] = {
                'from':[old,'phage'], 'files':[motion_part(last,1)],
                'previousFilesHash':motion_files_hash(files), 'progressIndex':len(approach)-1,
            }
        else:
            tile.setdefault('revealTargets',{})[new] = {'from':[old], 'files':files}
        routes[slot,old,new] = files
    # This target accepts those exact files only when replacing a telescope.
    # The room must reject them when the actual source is a phage.
    tile = cat['places'][0]
    tile['revealTargets']['temple'] = {'from':['telescope'], 'files':routes[0,'phage','guitar']}
    page = folder/'gallery.html'
    renderer = (Path(__file__).resolve().parents[1]/'web/ring-sand.js').read_text()
    page.write_text('<html><head></head><body><script type="application/json" id="scene">'+
                    json.dumps(scene,separators=(',',':'))+'</script><script>'+renderer+'</script></body></html>')
    return page, live, routes


def change(page, starting, revision, slot, subject, files, early_from=None):
    state = copy.deepcopy(starting)
    state['ids'][slot] = subject
    # Use the same saved-height quantization as the editor. Rebased requests
    # receive the current bed and replay their original signed movements on it.
    state['bed'] = page.evaluate("""([encoded,files])=>{
      const live=JSON.parse(document.getElementById('scene').textContent).live;
      const sim=new RingSand(live.size,live.groove,live.profile);
      const bed=Float32Array.from(atob(encoded),c=>c.charCodeAt(0)/170-1);
      for (const file of files) {
        const path=file.text.trim().split(/\\n/).map(row=>row.split(' ').map(Number));
        sim.carve(bed,path);
      }
      let packed='';
      for (const h of bed) packed+=String.fromCharCode(Math.round((Math.min(.5,Math.max(-1,h))+1)*170));
      return btoa(packed);
    }""",[starting['bed'],files])
    motion={'zone':'middle','place':slot,'files':files}
    if early_from is not None:
        motion['earlyFrom']=early_from
    return {'revision':revision,'state':state,'motion':motion}


def put(page, url, body, status):
    response=page.request.put(url+API,headers={'Origin':url},data=body)
    assert response.status==status,(response.status,response.text()[:300])
    return response


def far_guest_requests(page, url, catalog, stored):
    """Keep an older phone's conventional far-seat edit, then its new signed rooftop."""
    tile = catalog['places'][2]
    guitar, roof = (catalog['preferredSubjects'][name] for name in ('guitar','temple'))
    approach, clear, recut, home = (unpack_path(tile[key]) for key in ('approach','clear','recut','exit'))
    path = ring_scene.join(approach,clear,recut,unpack_path(catalog['excursions'][2][guitar]),home)
    ordinary = [motion_part(path,1)]
    prior = change(page,stored['state'],stored['revision'],2,guitar,ordinary)
    guitar_rev = put(page,url,prior,200).json()['revision']

    target = tile['revealTargets'][roof]
    assert guitar in target['from']
    new = change(page,prior['state'],guitar_rev,2,roof,target['files'],guitar)
    put(page,url,dict(new,motion=dict(new['motion'],earlyFrom=roof)),400)
    # The far route must keep the two lower engravings through the whole edit.
    previous = page.request.get(url+API).headers['x-oasis-place-revisions'].split(',')
    wrong = copy.deepcopy(new)
    wrong['state']['ids'][0] = 'pumpkin'
    put(page,url,wrong,400)
    revision = put(page,url,new,200).json()['revision']
    accepted = page.request.get(url+API)
    assert accepted.headers['x-oasis-place-revisions'].split(',') == [*previous[:2],str(revision)]
    assert accepted.json()['state'] == new['state']
    assert page.request.get(url+API+'/drawings/middle').json() == {'revision':revision,'files':target['files']}
    return [*ordinary,*target['files']], revision


def exercise(browser, folder):
    gallery,live,routes=expose_routes(folder)
    db=folder/'room.db'
    table=Table(db)
    initial={'edition':live['edition'],'bed':live['bed'],'ids':live['planner']['defaults'],
             'center':0,'outer':0,'portrait':'','custom':{},'labels':{}}
    with served(gallery,db,table,prepared=True) as url, browser.new_context() as phone, browser.new_context() as other:
        a,b=phone.new_page(),other.new_page()
        # This focused test uses the actual HTTP room and the browser sand renderer.
        a.goto(url+'/garden')
        b.goto(url+'/garden')
        assert table.dispatched(1)==live['setup'][0]
        first=change(a,initial,0,0,'guitar',routes[0,'phage','guitar'],'phage')
        old_book=initial['ids'][1]
        next_seat=change(b,initial,0,1,'temple',routes[1,old_book,'temple'],old_book)
        motion=first['motion']
        # 'books' also has a valid entry with exactly these bytes. The actual
        # stored source, checked under the revision lock, must still match.
        for overrides in ({'earlyFrom':'books'}, {'earlyFrom':'open_place'}, {'earlyFrom':'sketch-1'},
                          {'earlyFrom':None}, {'fill':True}, {'place':1}, {'zone':'outer'},
                          {'files':motion['files'][:1]}, {'files':motion['files'][::-1]},
                          {'files':motion['files']+[motion['files'][0]]}):
            put(a,url,dict(first,motion=dict(motion,**overrides)),400)
        no_place=motion.copy()
        del no_place['place']
        put(a,url,dict(first,motion=no_place),400)
        forged=copy.deepcopy(first)
        forged['motion']['files'][0]['text']=forged['motion']['files'][0]['text'].replace(' ','  ',1)
        put(a,url,forged,400)
        wrong_step=copy.deepcopy(first)
        lines=wrong_step['motion']['files'][0]['text'].splitlines()
        theta,radius=map(float,lines[len(lines)//2].split())
        lines[len(lines)//2]=f'{theta:.5f} {radius+.00001:.5f}'
        wrong_step['motion']['files'][0]['text']='\n'.join(lines)+'\n'
        put(a,url,wrong_step,400)
        wrong_target=copy.deepcopy(first)
        wrong_target['state']['ids'][0]='pumpkin'
        put(a,url,wrong_target,400)
        unlisted=copy.deepcopy(first)
        unlisted['state']['ids'][0]='temple'
        put(a,url,unlisted,400)
        wrong_neighbor=copy.deepcopy(first)
        wrong_neighbor['state']['ids'][2]='pumpkin'
        put(a,url,wrong_neighbor,400)
        assert a.request.get(url+API).json()=={'revision':0,'state':None}
        with closing(sqlite3.connect(db)) as conn:
            assert conn.execute('SELECT COUNT(*) FROM playback_job').fetchone()==(1,)
        assert put(a,url,first,200).json()['revision']==1
        put(b,url,first,409)
        put(b,url,dict(first,revision=1),400)
        put(b,url,next_seat,409)
        put(b,url,dict(next_seat,revision=1),400)  # Retrying with a stale neighbor would revert the guitar.
        current=b.request.get(url+API).json()
        rebased=change(b,current['state'],1,1,'temple',next_seat['motion']['files'],old_book)
        assert rebased['motion']==next_seat['motion']
        assert rebased['motion']['files'] != live['planner']['places'][1]['revealTargets']['temple']['files']
        # The old digest applies only to the complete earlier download for this seat
        # and its actual source. Each individual part still starts and ends at the dock.
        altered=copy.deepcopy(rebased['motion']['files'])
        altered[0]['text']=altered[0]['text'].replace(' ','  ',1)
        for overrides in ({'earlyFrom':'phage'}, {'files':rebased['motion']['files'][::-1]}, {'files':altered}):
            put(b,url,dict(rebased,motion=dict(rebased['motion'],**overrides)),400)
        wrong_seat=copy.deepcopy(rebased)
        wrong_seat['state']['ids']=current['state']['ids'].copy()
        wrong_seat['state']['ids'][0]='temple'
        wrong_seat['motion'].update(place=0,earlyFrom=current['state']['ids'][0])
        put(b,url,wrong_seat,400)
        assert put(b,url,rebased,200).json()['revision']==2
        kept=b.request.get(url+API).json()
        assert kept['state']==rebased['state'] and len(table.calls)==1
        assert b.request.get(url+API+'/drawings/middle').json()['files']==rebased['motion']['files']
    with served(gallery,db,table) as url,browser.new_context() as phone:
        p=phone.new_page();p.goto(url+'/garden')
        assert p.request.get(url+API).json()==kept and len(table.calls)==1
        # A phone using an old gallery may still submit the conventional complete clearing.
        tile=live['planner']['places'][1]
        approach,clear,recut,home=(unpack_path(tile[key]) for key in ('approach','clear','recut','exit'))
        path=ring_scene.join(approach,clear,recut,unpack_path(live['planner']['excursions'][1][old_book]),home)
        conventional=[motion_part(path,1)]
        fallback=change(p,kept['state'],2,1,old_book,conventional)
        assert put(p,url,fallback,200).json()['revision']==3
        current_files=tile['revealTargets']['temple']['files']
        fresh=change(p,fallback['state'],3,1,'temple',current_files,old_book)
        assert put(p,url,fresh,200).json()['revision']==4
        far, revision = far_guest_requests(p,url,live['planner'],p.request.get(url+API).json())
        all_files=live['setup']+first['motion']['files']+rebased['motion']['files']+conventional+current_files+far
        for index,file in enumerate(all_files,1):
            assert table.dispatched(index)==file
            table.outcome='complete'
        wait_table(p,url,state='idle',ready=True,queued=0,revision=revision)
        assert len(table.calls)==len(all_files)
    print('Pinned and previous replacement files, source and target, stale seats, conventional fallback and queued restart passed.')


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as temp,sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,Path(temp))
