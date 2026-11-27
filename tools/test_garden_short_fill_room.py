#!/usr/bin/env python3
"""Exercise left/right native and hand-drawn fills against the real room using two gallery releases."""
import argparse
import copy
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import sync_playwright

from garden_room import unpack_path
from test_attached_garden import Table, served, wait_table
from test_garden_multi_room import edited_motion, split_file
from test_garden_reveal_room import change, put
from test_garden_room import API, drawing_files, open_room, room, suggest


SKETCH = [[-.43, .19], [-.19, -.54], [.58, -.14], [.22, .43], [-.43, .19]]


def current(page, url, live):
    stored = page.request.get(url+API).json()
    if stored['state'] is None:
        stored['state'] = dict(edition=live['edition'], bed=live['bed'], ids=live['planner']['defaults'],
                               center=0, outer=0, portrait='', custom={}, labels={})
    return stored


def single(page, stored, place, subject):
    prior = stored['state']
    shapes = dict(prior['custom'])
    if subject == 'sketch-1':
        shapes[subject] = SKETCH
    motion = page.evaluate("""([ids,place,subject,shapes])=>{
      const catalog=JSON.parse(document.querySelector('#scene').textContent).live.planner;
      const targets=ids.slice(); targets[place]=subject;
      const route=OasisRingPlanner.planChange(catalog,ids,targets,shapes);
      return {zone:'middle',place,fill:route.fill,shortFill:route.shortFill,
              files:OasisRingPlanner.files(route.path)};
    }""", [prior['ids'],place,subject,shapes])
    if motion.get('shortFill') is None:
        motion.pop('shortFill',None)
    body = change(page,prior,stored['revision'],place,subject,motion['files'])
    body['motion'] = motion
    body['state']['custom'] = shapes
    if subject == 'sketch-1':
        body['state']['labels'][subject] = 'Guest sketch'
    return body


def reject_short(page, url, body, catalog):
    motion = body['motion']
    side, place = motion['shortFill'], motion['place']
    opposite = 'left' if side == 'right' else 'right'
    for invalid in ({'shortFill':opposite},{'shortFill':None},{'shortFill':'inner'},{'shortFill':True},
                    {'fill':False},{'place':(place+1)%3},{'addFrom':'books'},{'earlyFrom':'phage'},
                    {'customReveal':{'clearSegment':1,'artSegment':2,'end':3}}):
        put(page,url,edited_motion(body,**invalid),400)
    for key in ('fill','place','shortFill'):
        put(page,url,dict(body,motion={k:v for k,v in motion.items() if k!=key}),400)
    assert len(motion['files']) == 1
    file = motion['files'][0]
    rows = np.array([line.split() for line in file['text'].splitlines()],float)
    approach = len(unpack_path(catalog['places'][place]['shortFill'][side]))
    inside = rows[approach-1:len(rows)-approach+1]
    rail = catalog['geometry']['rail']
    off = np.flatnonzero(abs(inside[:,1]-rail) > .000025)
    start, end = approach-1 + off[[0,-1]] + [-1,1]
    lead = (approach-1+start)//2
    assert approach-1 < lead < start
    def reject_track(track):
        text = ''.join(f'{theta:.5f} {rho:.5f}\n' for theta,rho in track)
        put(page,url,edited_motion(body,files=[dict(file,text=text)]),400)
    # All remain connected, inside the broad middle band, and return to the dock.
    # Neither a forged approach nor reversing a closed picture is the selected trip.
    forged = rows.copy()
    forged[approach-3,0] += .002
    reject_track(forged)
    reversed_ink = rows.copy()
    reversed_ink[start:end+1] = reversed_ink[start:end+1][::-1]
    reject_track(reversed_ink)
    forged = rows.copy()
    forged[lead,0] += .003
    reject_track(forged)
    forged[-lead-1,0] += .003
    reject_track(forged)
    # Touch the same in-zone drawing with its saved outline reversed.
    if body['state']['ids'][place] == 'sketch-1':
        altered = copy.deepcopy(body)
        altered['state']['custom']['sketch-1'].reverse()
        put(page,url,altered,400)


def mixed(page, stored, separate):
    """Combine the real phone's two independent dock-to-dock downloads."""
    files, parts = [], []
    for body in separate:
        motion = body['motion']
        parts.append(dict(place=motion['place'], fill=True, shortFill=motion['shortFill'], count=len(motion['files'])))
        for part in motion['files']:
            files.append(dict(part, name=f'guest-ring-{len(files)+1}.thr'))
    initial = separate[0]['state']
    body = change(page,stored['state'],stored['revision'],0,initial['ids'][0],files)
    for change_ in separate:
        seat = change_['motion']['place']
        body['state']['ids'][seat] = change_['state']['ids'][seat]
        for key in ('custom','labels'):
            body['state'][key].update(change_['state'][key])
    body['motion'] = dict(zone='middle', files=files, parts=parts)
    return body


def exercise(browser, new, old, folder):
    db = folder/'attached.db'
    table = Table(db)
    with browser.new_page() as earlier, served(old, db, table, prepared=True) as url:
        open_room(earlier,url)
        live = earlier.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        assert not any('shortFill' in p for p in live['planner']['places'])
        legacy = single(earlier,current(earlier,url,live),2,'temple')
        group = 'a guitar for Thomas, books for Alex and a Thai rooftop for Lek'
        suggest(earlier,group)
        old_group_files = drawing_files(earlier,'#downloads')
        assert legacy['motion'].get('fill') is True and 'shortFill' not in legacy['motion']
        assert table.dispatched(1) == live['setup'][0]
    with served(new, db, table) as url, browser.new_page() as page:
        open_room(page,url)
        live = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        catalog = live['planner']
        # Shorter individual entries must not turn this established 4.12 m
        # loop into three separate dock trips totaling 5.90 m.
        suggest(page,group)
        assert drawing_files(page,'#downloads') == old_group_files
        # A guest who previewed the old route before the room upgraded can still keep it.
        assert put(page,url,legacy,200).json()['revision'] == 1
        prior = current(page,url,live)
        native, custom = single(page,prior,0,'guitar'), single(page,prior,1,'sketch-1')
        assert [r['motion']['shortFill'] for r in (native,custom)] == ['right','left']
        paired = mixed(page,prior,[native,custom])
        parts = paired['motion']['parts']
        # Split the actual custom engraving across two hardware files.
        i = 1
        cut = len(paired['motion']['files'][i]['text'].splitlines())//2
        split_file(paired['motion'],parts[i],i,cut)
        for changes in ({'tour':True}, {'shortFill':'right'}, {'parts':list(reversed(parts))},
                        {'parts':[parts[0],dict(parts[1],shortFill='right')]},
                        {'parts':[dict(parts[0],count=2),dict(parts[1],count=1)]}):
            put(page,url,edited_motion(paired,**changes),400)
        for body in (native,custom):
            reject_short(page,url,body,catalog)
        assert page.request.get(url+API).json() == prior
        assert put(page,url,paired,200).json()['revision'] == 2
        put(page,url,paired,409)
        put(page,url,dict(paired,revision=2),400)
        expected = live['setup'] + legacy['motion']['files'] + paired['motion']['files']
        assert page.request.get(url+API+'/drawings/middle').json()['files'] == paired['motion']['files']
    with served(new, db, table) as url, browser.new_page() as page:
        for n,file in enumerate(expected,1):
            assert table.dispatched(n) == file
            table.outcome = 'complete'
        wait_table(page,url,ready=True,queued=0,revision=2)
        assert len(table.calls)==len(expected)
    with room(new,folder/'unattached.db') as url, browser.new_page() as page:
        open_room(page,url)
        for place,subject,side in ((0,'sketch-1','right'),(1,'books','left')):
            before = current(page,url,live)
            body = single(page,before,place,subject)
            assert body['motion']['shortFill']==side
            reject_short(page,url,body,catalog)
            assert put(page,url,body,200).json()['revision']==before['revision']+1
    print('Both gate directions preserved native and custom stroke order. The attached table played the earlier '
          'phone’s fill and the two new guest trips exactly once across restart, including a split sketch.')


if __name__=='__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('gallery',type=Path,help='updated open 420 mm gallery')
    cli.add_argument('earlier',type=Path,help='previous gallery for the same open garden')
    args = cli.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=chrome) as browser:
            exercise(browser,args.gallery,args.earlier,Path(tmp))
