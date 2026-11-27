#!/usr/bin/env python3
"""Compare dinner requests and their signed chair drawings across the folded-crane upgrade."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene
from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_guest_place import contour, contour_samples
from test_guest_web import ORIGIN, Table, send, suggest as mini_suggest
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_lettering import seat_view
from test_ring_photo import frame
from wide_portrait import chromium

OLD='paper_crane'
NEW='origami_crane'
GENERIC=('a folded paper bird','an origami crane','a paper crane','a folded crane','an origami bird')
CONTROLS=('a horn of plenty','an ear of corn','a sauce boat','a wish bone','a slice of pumpkin pie with whipped cream',
          'an oak leaf and acorn','a toffee apple')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def single(page,words):
    suggest(page,words)
    files=drawing_files(page,'#downloads')
    assert len(files)==1
    return files


def measure(page,subject,slot,files):
    live=page.evaluate('''()=>{const l=JSON.parse(document.querySelector('#scene').textContent).live;
      return {geometry:l.planner.geometry,size:l.radiusMM,groove:l.groove};}''')
    radius=live['size']
    walk=from_files(files,(-np.pi/2,1))
    intended=contour({'ids':[subject]*3},slot,live['geometry'])
    physical=check_ring_scene.sample_walk(walk,.00012)
    error=cKDTree(physical).query(contour_samples(intended,.00045))[0].max()*radius
    assert error<.14
    return dict(positions=len(walk),travel_m=round(float(check_ring_scene.travel(walk)[-1]*radius/1000),4),
                sha256=sha(files[0][1]),max_miss_mm=round(float(error),3),groove_mm=round(radius*live['groove'],2))


def empty_place(browser,gallery,output,old):
    output.mkdir(parents=True,exist_ok=True)
    with browser.new_page(**MOBILE,offline=True) as p:
        p.goto(gallery.resolve().as_uri()+'#guests')
        geometry=p.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.geometry")
        controls={s:sha(single(p,'please draw '+s+' for Alex')[0][1]) for s in CONTROLS}
        files=single(p,'please draw a folded paper bird for Alex')
        for s in GENERIC:
            assert single(p,'please draw '+s+' for Alex')==files
        (output/'guest-ring-1.thr').write_bytes(files[0][1])
        subject=OLD if old else NEW
        metrics=measure(p,subject,1,files)
        for i,guest in enumerate(('Thomas','Alex','Lek')):
            single(p,'a folded paper bird for '+guest)
            seat_view(frame(p),geometry,i).save(output/f'chair-{i}.png')
        single(p,'please draw a folded paper bird for Alex')
        p.locator('#guestZoom').click()
        p.locator('.bowl').screenshot(path=output/'phone.png')
        Image.open(output/'phone.png').crop((27,57,323,297)).save(output/'phone-crop.png')
        return metrics,controls,files


def old_room(browser,previous,gallery,db,original):
    with room(previous,db) as url,browser.new_page(**MOBILE) as page:
        open_room(page,url)
        suggest(page,'a phage for Thomas, a folded paper bird for Alex and a Thai rooftop for Lek')
        before,_=save(page,url+API)
        assert before['state']['ids']==['phage_faceted',OLD,'temple_gable']
    with room(gallery,db) as url,browser.new_page(**MOBILE) as host,browser.new_page(**MOBILE) as friend:
        for p in (host,friend):
            open_room(p,url)
            caption(p,'Alex · Folded paper bird')
            assert p.request.get(url+API).json()['state']==before['state']
        # Older generic phrases still address the old drawing in an occupied seat.
        single(host,'replace the folded paper bird with a guitar')
        caption(host,'Alex · Acoustic guitar')
        files=single(host,'please draw a folded paper bird for Alex')
        caption(host,'Alex · Paper crane with folded wings')
        saved,_=save(host,url+API)
        assert saved['state']['ids']==['phage_faceted',NEW,'temple_gable']
        assert saved['motion']['place']==1
        caption(friend,'Alex · Paper crane with folded wings')
        assert drawing_files(friend,'#roomFiles')==files
        friend.goto('about:blank')
        open_room(friend,url)
        assert drawing_files(friend,'#roomFiles')==files
        single(friend,'the original folded paper bird for Alex')
        restored,_=save(friend,url+API)
        assert restored['state']['ids']==before['state']['ids']
    with browser.new_page(**MOBILE,offline=True) as page:
        page.goto(gallery.resolve().as_uri()+'#guests')
        assert single(page,'an original paper crane for Alex')==original


def mini(browser):
    table=Table()
    table.test_pending_fresh=False
    table.known,table.slots=True,['phage',OLD,'temple']
    with browser.new_page(**MOBILE) as page:
        page.context.route('**/*',lambda route: table.handle(route) if route.request.url.startswith(ORIGIN+'/') else route.abort())
        page.goto(ORIGIN+'/lib/guest.html')
        page.locator('#previewButton:enabled').wait_for()
        mini_suggest(page,'replace the folded paper bird with a guitar')
        expect(page.locator('#draw')).to_have_text('Replace Folded paper bird')
        mini_suggest(page,'a folded paper bird','1')
        send(page)
        assert table.slots==['phage',NEW,'temple']
        result=dict(positions=table.calls[-1][2],sha256=sha(table.parts[1]))
        mini_suggest(page,'an original paper crane','1')
        send(page)
        assert table.slots==['phage',OLD,'temple']
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('gallery','previous','out'):
        parser.add_argument(k,type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as d,sync_playwright() as pw,pw.chromium.launch(executable_path=chromium(pw,None)) as b:
        old,unchanged,original=empty_place(b,args.previous,args.out/'previous',True)
        new,controls,_=empty_place(b,args.gallery,args.out/'current',False)
        assert unchanged==controls
        old_room(b,args.previous,args.gallery,Path(d)/'room.db',original)
        result=dict(previous=old,current=new,controls=controls,mini=mini(b))
        (args.out/'verified.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
