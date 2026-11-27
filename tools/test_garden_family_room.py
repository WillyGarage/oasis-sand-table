#!/usr/bin/env python3
"""Check a family portrait and a saved sketch across a restart of an attached, simulated garden."""
import argparse
import copy
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright

from test_attached_garden import Table, served, wait_table
from test_garden_reveal_room import put
from test_garden_room import API, open_room
from test_garden_short_fill_room import current, single


def center_request(page, saved, mode):
    state = copy.deepcopy(saved['state'])
    motion, state['bed'] = page.evaluate("""([state, mode]) => {
        const scene=JSON.parse(document.querySelector('#scene').textContent);
        const live=scene.live, plan=OasisRingPlanner;
        const route=mode==='widePortrait' ? plan.photo(live.wideCenter, [[0,-1],[-.68,.2],[.54,.6],[0,-1]])
            : plan.restoreGuests(scene,state.ids,state.custom);
        const files=plan.files(route.path,'family-center');
        const bed=Float32Array.from(atob(state.bed),c=>c.charCodeAt(0)/170-1);
        const sim=new RingSand(live.size,live.groove,live.profile);
        sim.carve(bed,route.path);
        let packed='';
        for (const height of bed) packed+=String.fromCharCode(Math.round((Math.max(-1,Math.min(.5,height))+1)*170));
        return [{zone:'center',centerMode:mode,files},btoa(packed)];
    }""", [state,mode])
    if mode == 'widePortrait':
        state.update(widePortrait=True, portrait='Geometric study')
    else:
        state.pop('widePortrait')
        state.update(portrait='', center=0)
    return dict(revision=saved['revision'], motion=motion, state=state)


def exercise(page, gallery, directory):
    database = directory / 'table.db'
    table = Table(database)
    with served(gallery, database, table, prepared=True) as url:
        open_room(page, url)
        live = page.locator('#scene').evaluate("""el=>{
            const s=JSON.parse(el.textContent).live;
            return {setup:s.setup,edition:s.edition,bed:s.bed,planner:{defaults:s.planner.defaults}};
        }""")
        sketch = single(page, current(page,url,live), 1, 'sketch-1')
        put(page, url, sketch, 200)
        prior = page.request.get(url+API).json()
        portrait = center_request(page, prior, 'widePortrait')
        stale_fill = single(page, prior, 2, 'temple_gable')
        put(page, url, dict(portrait, motion=sketch['motion']), 400)
        without_mode = {k:v for k,v in portrait['motion'].items() if k!='centerMode'}
        put(page, url, dict(portrait, motion=without_mode), 400)
        put(page, url, portrait, 200)
        put(page, url, stale_fill, 409)
        wide = page.request.get(url+API).json()
        put(page, url, dict(stale_fill, revision=wide['revision']), 400)
        assert page.request.get(url+API+'/drawings/middle').json()['files'] == []
        assert page.request.get(url+API+'/drawings/center').json()['files'] == portrait['motion']['files']
        assert table.dispatched(1) == live['setup'][0]

    with served(gallery, database, table) as url:
        open_room(page, url)
        assert page.request.get(url+API).json() == wide
        restore = center_request(page, wide, 'restoreGuests')
        missing_sketch = copy.deepcopy(restore)
        missing_sketch['state']['ids'][1] = 'open_place'
        put(page, url, missing_sketch, 400)
        wrong_erase = dict(restore, motion=dict(restore['motion'], files=portrait['motion']['files']))
        put(page, url, wrong_erase, 400)
        put(page, url, dict(restore, motion=None), 400)
        assert page.request.get(url+API).json() == wide
        last = put(page, url, restore, 200).json()['revision']
        for zone in ('center','middle'):
            assert page.request.get(url+API+'/drawings/'+zone).json() == {'revision':last,'files':restore['motion']['files']}
        assert page.request.get(url+API).json()['state']['custom']['sketch-1'] == sketch['state']['custom']['sketch-1']
        repeated = dict(restore, revision=last)
        put(page, url, repeated, 400)
        files = live['setup'] + sketch['motion']['files'] + portrait['motion']['files'] + restore['motion']['files']
        for i, signed in enumerate(files, 1):
            assert table.dispatched(i) == signed
            table.outcome = 'complete'
        wait_table(page, url, ready=True, queued=0, revision=last)
        assert len(table.calls) == len(files)
        print(f'{len(files)} files played exactly once across restart; the original sketch returned in its place.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser, browser.new_page() as page:
            exercise(page,args.gallery,Path(tmp))
