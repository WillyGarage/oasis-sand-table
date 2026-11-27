#!/usr/bin/env python3
"""Replay Alex's photographed beard in the seated family group before and after moving his chair.

Pass GALLERY --previous PRE_BEARD_GALLERY --group PRIVATE_FAMILY_COMPOSITE --alex ORIGINAL_ALEX_JPEG.
This regression uses the 420 mm working radius, 7 mm groove and the original Thomas, Alex and Lek photo panels.
"""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageEnhance, ImageOps
from playwright.sync_api import sync_playwright
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_attached_garden import Table, served, wait_table
from test_garden_room import caption, choose, drawing_files
from test_ring_guest_border import MOBILE, from_files, open_garden, preview, replay, save
from test_ring_photo import frame
from test_ring_seated_group import analyze_seats, assign_seats, compare_signed_faces, seated_view
from test_ring_shadows import ready


def photographed_edges(group_file, alex_file):
    # The middle panel of this known family fixture is a crop of Alex's original.
    # 288 independent feature matches registered these two pictures. Nine cuts
    # through the lower beard measure the actual dark-hair to skin transition.
    original = ImageOps.exif_transpose(Image.open(alex_file)).convert('L')
    group = Image.open(group_file).convert('L').resize((1000,378), Image.Resampling.LANCZOS)
    registered = original.transform(group.size, Image.Transform.AFFINE,
        (3.5485,0,-392.0,0,3.5485,-267.7), Image.Resampling.BICUBIC)
    source, composite = [gaussian_filter(np.asarray(photo,float),1.1) for photo in (registered,group)]
    assert np.abs(source-composite)[155:279,456:566].mean() < 3, 'Expected Alex in the middle of the family photo.'
    columns = np.arange(510,535,3)
    def edge(image):
        changes = np.gradient(image[263:281,columns],axis=0)
        assert changes.max(axis=0).min() > 5
        return 263 + changes.argmax(axis=0)
    source_edge, group_edge = edge(source), edge(composite)
    assert abs(source_edge-group_edge).max() <= 1
    # Follow a second hair boundary, well inside the physical chin. A shirt
    # or neckline passing near the lower edge cannot supply this cheek line.
    cheek_x = np.arange(535,552,3)
    cheek_lines = [210+np.gradient(image[210:226,cheek_x],axis=0).argmin(axis=0) for image in (source,composite)]
    agree = abs(cheek_lines[0]-cheek_lines[1])<=1
    assert agree.sum()>=4
    return np.column_stack((columns,source_edge)), np.column_stack((cheek_x[agree],cheek_lines[0][agree]))


def submit_photo(page, photo):
    choose(page,'zone','center')
    panel = page.locator('#centerPhoto')
    if not panel.evaluate('p=>p.open'):
        panel.locator('summary').first.click()
    page.locator('#portraitFile').set_input_files(photo)
    page.locator('#portraitMode').select_option('group')
    page.locator('#portraitStyle').select_option('seats')
    page.locator('#portraitSubmit').click()
    ready(page)
    caption(page,'Group portrait · 3 faces around the table')


def center_and_border(size, data):
    y,x = np.mgrid[-1:1:complex(size),-1:1:complex(size)]
    r = np.hypot(x,y)
    groove, radius = data['groove'], data['radius']
    border = (r>radius+3*groove) & (r<.99) & ((y<0)|(abs(x)>3*groove))
    return r<radius-2*groove, border


def inspect_download(page, api, data, edges, out):
    files = drawing_files(page,'#downloads')
    before = page.request.get(api).json()['state']
    segments = data['segments']
    route = from_files(files,segments[0][0])
    ends = np.cumsum([len(p)-1 for p in segments])
    parts = [route[a:b+1] for a,b in zip([0,*ends[:-1]],ends)]
    assert ends[-1]+1 == len(route)
    art = parts[2]
    xy = art[:,1,None]*np.column_stack((np.cos(art[:,0]),np.sin(art[:,0])))
    alex, = [seat for seat in data['seats'] if .45 < seat['sourceBox']['x']/data['sourceSize'][0] < .55]
    anchor = data['radius']*np.asarray(alex['anchor'])
    hits = np.flatnonzero(np.linalg.norm(xy-anchor,axis=1)<2e-5)
    assert len(hits) >= 2
    signed = check.sample_walk(art[hits[0]:hits[-1]+1], data['groove']/40)
    angle = alex['rotation']
    turn = np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]])
    edge, cheek = edges
    local = (np.vstack((edge,cheek))-np.asarray(alex['sourceCenter']))*[1,-1]
    wanted = (alex['center']+local@turn*alex['scale'])*data['radius']
    distances, nearest = cKDTree(signed).query(wanted)
    miss, cheek_miss = np.split(distances/data['groove'],[len(edge)])
    # A positive value places the nearest actual groove above the beard's bottom.
    above = ((signed[nearest]-wanted) @ turn.T)[:len(edge),1] * data['workingMm']
    choose(page,'stage','original')
    old_view = frame(page)
    _, border = center_and_border(len(old_view),data)
    for stage,cut in [('cleared',2),('redrawn',len(parts))]:
        choose(page,'stage',stage)
        shown = frame(page)
        rebuilt = replay(page,before['bed'],*parts[:cut])
        diff = abs(rebuilt.astype(np.int16)-shown.astype(np.int16))
        assert diff.mean()<1.1 and np.percentile(diff,99)<5
        assert np.array_equal(shown[border],old_view[border]) and np.array_equal(rebuilt[border],old_view[border])
    out.mkdir(parents=True,exist_ok=True)
    seated_view(rebuilt,alex,data['radius']).save(out/'alex-from-chair.jpg',quality=94)
    Image.fromarray(rebuilt).save(out/'signed-replay.png')
    for name,raw in files:
        (out/name).write_bytes(raw)
    metrics = {'alex_slot':data['seats'].index(alex), 'beard_edge_error_grooves':np.round(miss,3).tolist(),
               'median_edge_error_grooves':round(float(np.median(miss)),3),
               'median_cheek_error_grooves':round(float(np.median(cheek_miss)),3),
               'median_above_beard_mm':round(float(np.median(above)),2),'protected_border_pixels':int(border.sum()),
               'travel_m':round(float(check.travel(route)[-1]*data['workingMm']/1000),3)}
    (out/'measurements.json').write_text(json.dumps(metrics,indent=2)+'\n')
    print(out.name, metrics, flush=True)
    return files, metrics


def exercise(browser, args, database, out):
    edges = photographed_edges(args.group,args.alex)
    table = Table(database)

    def local_room(page,url):
        page.route('http**://**/*',lambda r: r.continue_() if r.request.url.startswith(url+'/') else r.abort())
        open_garden(page,url,'portrait')

    with served(args.previous,database,table,prepared=True,layout='portrait') as url, browser.new_page(**MOBILE) as first:
        api = url+'/api/garden/portrait'
        local_room(first,url)
        jobs = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
        preview(first,4,'Lek',order='progressive')
        border,_ = save(first,api)
        jobs.extend(border['motion']['files'])
        submit_photo(first,args.group)
        old_files, old = inspect_download(first,api,analyze_seats(first),edges,out/'previous')
        assert old['alex_slot']==1 and old['median_edge_error_grooves']>3, 'Expected the earlier missing beard.'
        saved,_ = save(first,api)
        jobs.extend(saved['motion']['files'])
        room = first.request.get(api).json()
        old_sand = frame(first)

    with served(args.gallery,database,table,layout='portrait') as url, browser.new_page(**MOBILE) as host, \
            browser.new_page(**MOBILE) as guest:
        api = url+'/api/garden/portrait'
        for page in (host,guest):
            local_room(page,url)
            choose(page,'zone','center')
            caption(page,'Group portrait · 3 faces around the table')
            assert drawing_files(page,'#roomFiles')==old_files and np.array_equal(frame(page),old_sand)
        assert host.request.get(api).json()==room
        submit_photo(host,args.group)
        default = analyze_seats(host)
        first_files, new = inspect_download(host,api,default,edges,out/'new')
        assert new['alex_slot']==1 and first_files!=old_files
        kept,_ = save(host,api)
        jobs.extend(kept['motion']['files'])
        open_garden(guest,url,'portrait')
        choose(guest,'zone','center')
        assert drawing_files(guest,'#roomFiles')==first_files and np.array_equal(frame(host),frame(guest))
        # Source photos stay on their respective phones. The second guest selects
        # the same local photo and puts Alex first before saving the new seating.
        submit_photo(guest,args.group)
        boxes = [s['sourceBox'] for s in default['seats']]
        order = [boxes[1],boxes[0],boxes[2]]
        assign_seats(guest,order,np.array(default['sourceSize']))
        changed = analyze_seats(guest,order)
        moved_files, moved = inspect_download(guest,api,changed,edges,out/'moved')
        assert moved['alex_slot']==0 and moved_files!=first_files
        rotation_error = compare_signed_faces(default,first_files,changed,moved_files)
        moved_body,_ = save(guest,api)
        jobs.extend(moved_body['motion']['files'])
        open_garden(host,url,'portrait')
        choose(host,'zone','center')
        assert drawing_files(host,'#roomFiles')==moved_files
        settled = frame(host)
        assert np.array_equal(settled,frame(guest))
        choose(host,'zone','outer')
        preview(host,3,'Lek')
        final,revision = save(host,api)
        jobs.extend(final['motion']['files'])
        center, border_pixels = center_and_border(len(settled),changed)
        after = frame(host)
        assert np.array_equal(settled[center],after[center]) and np.any(settled[border_pixels]!=after[border_pixels])
        open_garden(guest,url,'portrait')
        assert np.array_equal(frame(guest),after)
        assert guest.request.get(api+'/drawings/center').json()['files']==moved_body['motion']['files']
        # The same photo at lower exposure exposed a missing-beard regression.
        # The scratch JPEG stays in the owner-only temporary room directory.
        dim_photo = database.parent/'dim-family.jpg'
        dim_photo.touch(mode=0o600,exist_ok=False)
        with Image.open(args.group) as family:
            ImageEnhance.Brightness(family.convert('RGB')).enhance(.68).save(dim_photo,quality=90)
        submit_photo(guest,dim_photo)
        _, dimmed = inspect_download(guest,api,analyze_seats(guest),edges,out/'dimmed')
        assert dimmed['alex_slot']==1 and guest.request.get(api).json()['revision']==revision
        for i,job in enumerate(jobs,1):
            assert table.dispatched(i)==job
            table.outcome='complete'
        wait_table(host,url,state='idle',ready=True,queued=0,revision=revision)
        assert len(table.calls)==len(jobs)
        report = dict(previous=old, corrected=new, moved=moved, dimmed=dimmed, changed_seat_error_mm=rotation_error,
                      protected_center_pixels=int(center.sum()), ordered_playback_files=len(jobs),
                      source_beard_edge=edges[0].tolist(), source_cheek_edge=edges[1].tolist())
        (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        for sample in (new,moved,dimmed):
            # A groove extends half its width to each side of the centerline.
            # Every measured bottom-edge point should fall inside it.
            assert max(sample['beard_edge_error_grooves']) < .5, 'The drawing misses the photographed lower beard.'
            assert sample['median_cheek_error_grooves'] < .5, 'The drawing misses the photographed inner cheek.'
        print(f'Both phones received Alex at his new seat, the new border preserved the portrait, and all '
              f'{len(jobs)} downloaded files played exactly once across the gallery upgrade.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    for name in ('previous','group','alex'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args,Path(tmp)/'wide.db',args.evidence or Path(tmp))
