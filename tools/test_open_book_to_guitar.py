#!/usr/bin/env python3
"""Rehearse Alex's dinner request using two real browser clients and a temporary local garden."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, choose, drawing_files, open_room, room, suggest
from test_guest_custom_reveal import previous_relief, protected_sand
from test_guest_guitar_opening import coverage
from test_ring_guest_border import MOBILE, replay, save
from test_ring_lettering import seat_view
from test_ring_photo import frame
from ring_scene import keeps_other_places
from test_ring_shadows import ready
from wide_portrait import chromium


def prepare(browser, gallery, database, photo):
    with room(gallery,database) as url, browser.new_page(**MOBILE) as page:
        open_room(page,url,'photos')
        page.locator('#portraitFile').set_input_files(photo)
        page.locator('#portraitSubmit').click()
        ready(page)
        portrait,_ = save(page,url+API)
        assert portrait['state']['portrait'] and portrait['motion']['zone']=='center'
        choose(page,'zone','middle')
        suggest(page,'A phage for Thomas, an open book for Alex and a Thai rooftop for Lek')
        opening,_ = save(page,url+API)
        assert opening['state']['ids']==['phage_faceted','books_open','temple_gable']
        return opening['state']


def contact_sheet(frames,geometry,travel,output):
    sheet=Image.new('RGB',(925,370),'#f8f4ea')
    draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('DejaVuSans.ttf',17)
    for index,(picture,title,distance) in enumerate(zip(frames,('Alex’s open book','Body of the guitar','Sound hole and first fret','Finished guitar'),travel)):
        tile=seat_view(picture,geometry,1).resize((220,220),Image.Resampling.LANCZOS)
        x=13+228*index
        sheet.paste(tile,(x,62))
        draw.text((x,296),title,font=font,fill='#332719')
        draw.text((x,323),f'{distance:.1f} m',font=font,fill='#5d5241')
    draw.text((13,17),'Alex’s open book becomes his guitar',font=ImageFont.truetype('DejaVuSans.ttf',25),fill='#31261d')
    sheet.save(output/'alex-book-to-guitar.jpg',quality=94)


def rehearse(browser,gallery,database,scene,opening,folder,specific):
    folder.mkdir(parents=True,exist_ok=True)
    g=scene['guest_plan']['geometry']
    with room(gallery,database) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        for page in (host,guest):
            open_room(page,url)
            caption(page,'Alex · Open book')
        assert host.request.get(url+API).json()['state']==opening
        initial=frame(host)
        choose(guest,'zone','center')
        portrait=drawing_files(guest,'#roomFiles')
        choose(guest,'zone','middle')
        # A person can type this live; the destination comes from the room's guest interests.
        suggest(host,'an acoustic guitar')
        caption(host,'Alex · Acoustic guitar')
        signed=drawing_files(host,'#downloads')
        rec=host.evaluate('''specific=>{
          const p=JSON.parse(document.getElementById('scene').textContent).live.planner.places[1];
          return specific ? p.reveals.books_open.guitar_silhouette : p.revealTargets.guitar_silhouette;
        }''', specific)
        assert [(f['name'],f['text'].encode()) for f in rec['files']]==signed
        path,_,metrics=coverage(scene,1,rec)
        margin=scene['guest_clearance_mm']/scene['assumed_working_radius_mm']
        assert keeps_other_places(path,g,1,scene['groove_width'],margin)
        metrics['neighbor_clearance_mm']=scene['guest_clearance_mm']
        np.testing.assert_allclose(path[[0,-1]], [scene['dock']]*2,atol=.000006,rtol=0)
        chunks=[np.loadtxt(f['text'].splitlines()) for f in rec['files']]
        assert len(chunks)==1
        final=frame(host)
        images=[initial]
        choose(host,'stage','cleared')
        for i,step in enumerate(rec['progressMoments']):
            host.locator('#guestMoment').select_option(str(i))
            caption(host,step['label'])
            images.append(frame(host))
            simulated=replay(host,opening['bed'],chunks[0][:step['endIndex']+1])
            assert np.abs(images[-1].astype(float)-simulated).mean()<1.1
        choose(host,'stage','redrawn')
        images.append(final)
        simulated=replay(host,opening['bed'],*chunks)
        assert np.abs(final.astype(float)-simulated).mean()<1.1
        kept,_=save(host,url+API)
        assert kept['motion']['place']==1 and kept['motion']['earlyFrom']=='books_open'
        assert kept['state']['ids']==['phage_faceted','guitar_silhouette','temple_gable']
        assert kept['state']['center']==opening['center'] and kept['state']['portrait']==opening['portrait']
        caption(guest,'Alex · Acoustic guitar')
        assert drawing_files(guest,'#roomFiles')==signed
        guest.goto('about:blank')
        open_room(guest,url)
        caption(guest,'Alex · Acoustic guitar')
        assert drawing_files(guest,'#roomFiles')==signed
        choose(guest,'zone','center')
        assert drawing_files(guest,'#roomFiles')==portrait
        live=host.evaluate("""()=>{const {size,groove,planner}=JSON.parse(document.querySelector('#scene').textContent).live;
          return {size,groove,planner:{geometry:planner.geometry,erase:planner.erase}}}""")
        metrics['unchanged_pixels']=protected_sand(opening,kept['state'],1,live,images)
        metrics['old_book_relief']=previous_relief(host,opening,kept['state'],path,rec['progressIndex'],1,live)
        metrics['coordinates']=len(path)
        metrics['coordinate_sha256']=hashlib.sha256(signed[0][1]).hexdigest()
        for name,data in signed:
            (folder/name).write_bytes(data)
        Image.fromarray(initial).save(folder/'dinner-opening.jpg',quality=94)
        Image.fromarray(final).save(folder/'dinner-guitar.jpg',quality=94)
        for i,im in enumerate(images):
            Image.fromarray(im).save(folder/f'table-{i}.jpg',quality=92)
            seat_view(im,g,1).save(folder/f'chair-{i}.png')
        contact_sheet(images,g,[0,*metrics['displayed_progress_m'],metrics['travel_m']],folder)
        return metrics,kept


def write_demo(folder, metrics):
    """Package only replayed sand images so the dinner example opens without a room or a controller."""
    from base64 import b64encode
    from io import BytesIO
    stages=[]
    for i,(name,meters) in enumerate(zip(('Open book','Body curves','Sound hole and fret','Finished guitar'),
            (0,*metrics['displayed_progress_m'],metrics['travel_m']))):
        images=[]
        for img in (folder/f'table-{i}.jpg',folder/f'chair-{i}.png'):
            image=Image.open(img).convert('RGB')
            encoded=BytesIO()
            image.save(encoded,'WEBP',quality=92,method=6)
            images.append('data:image/webp;base64,'+b64encode(encoded.getvalue()).decode('ascii'))
        stages.append(dict(name=name,meters=meters,images=images))
    page="""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light">
<title>Alex’s book becomes a guitar</title>
<style>
*{box-sizing:border-box} body{margin:0;background:#f8f5ee;color:#2b2920;font:1.02rem/1.45 system-ui,sans-serif}
main{max-width:770px;margin:auto;padding:clamp(16px,4vw,38px)}
h1{font:500 clamp(2rem,5vw,3.1rem)/1.04 Georgia,serif;margin:0 0 .5rem;color:#333426} p{margin:0 0 1rem}
figure{margin:0} img{display:block;width:100%;aspect-ratio:1;object-fit:contain;background:#f0eadd;border-radius:9px}
.controls{display:flex;justify-content:space-between;align-items:center;gap:.6rem;margin:0 0 .55rem}
input,button{accent-color:#555c42} button{font:inherit;padding:.48em .6em;border:1px solid #a9a793;border-radius:6px;color:inherit;background:transparent;cursor:pointer}
button[aria-pressed=true]{background:#424b35;color:white;border-color:#424b35}
nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.33em;margin:0 0 .7rem;line-height:1.1}
label{white-space:nowrap} output{font-variant-numeric:tabular-nums} figcaption{font-size:.9rem;color:#585448;margin:.6rem 0}
@media(max-width:420px){nav button{font-size:.85rem}.controls{font-size:.9rem}}
</style><main><h1>Alex’s book becomes a guitar</h1>
<p>Thomas’s phage and Lek’s rooftop surround a family portrait while Alex’s drawing changes.</p>
<nav aria-label="Drawing stages"></nav>
<div class="controls"><output aria-live="polite"></output><label><input id="detail" type="checkbox"> Alex’s chair</label></div>
<figure><img alt=""><figcaption>Simulated sand on the planned 36-inch table. Distances follow the ball from its starting position.</figcaption></figure>
</main><script>
const stages=STAGE_DATA;
const nav=document.querySelector('nav'),sand=document.querySelector('img'),detail=document.querySelector('#detail');
let stage=0;
function show(){
  const step=stages[stage];
  sand.src=step.images[detail.checked?1:0];
  sand.alt=(detail.checked?'Alex’s chair':'The whole garden')+' with '+step.name.toLowerCase()+' in Alex’s place';
  document.querySelector('output').textContent=step.meters.toFixed(1)+' m of travel';
  Array.from(nav.children).forEach((b,i)=>b.setAttribute('aria-pressed',String(i===stage)));
}
stages.forEach((s,i)=>{const b=document.createElement('button'); b.textContent=s.name; b.onclick=()=>{stage=i;show()};nav.append(b)});
detail.onchange=show;show();
</script></html>"""
    (folder.parent/'alex-book-to-guitar.html').write_text(page.replace('STAGE_DATA',json.dumps(stages,separators=(',',':'))))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('gallery','previous','scene','photo','output'):
        parser.add_argument(name,type=Path)
    args=parser.parse_args()
    scene=json.loads(args.scene.read_text())
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw,None)) as browser:
        database=Path(tmp)/'opening.db'
        opening=prepare(browser,args.previous,database,args.photo)
        report={}
        for mode,gallery in [('previous',args.previous),('new',args.gallery)]:
            db=Path(tmp)/(mode+'.db')
            shutil.copy2(database,db)
            metrics,body=rehearse(browser,gallery,db,scene,opening,args.output/mode,mode=='new')
            report[mode]=metrics
            if mode=='previous':
                old_request=body
        old,new=report['previous'],report['new']
        assert new['travel_m']<old['travel_m']*.75
        assert new['milestones_m']['sound_hole']['100']<old['milestones_m']['sound_hole']['100']*.8
        assert new['first_complete_guitar_m']<old['first_complete_guitar_m']*.7
        # A phone which previewed the earlier release can still keep exactly what it saw.
        with room(args.gallery,database) as url, browser.new_page() as page:
            response=page.request.put(url+API,data=old_request,headers={'Origin':url})
            assert response.ok, response.text()
        write_demo(args.output/'new',new)
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for mode,r in report.items():
            print(mode,r['travel_m'],r['milestones_m']['sound_hole']['100'],r['first_complete_guitar_m'],
                  r['old_book_relief'],r['unchanged_pixels'])


if __name__=='__main__':
    main()
