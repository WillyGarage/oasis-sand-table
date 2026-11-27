#!/usr/bin/env python3
"""Measure Thomas's photographed smile and facial hair in seated, full-center and guest-place phone downloads.

Run with NEW_GALLERY PREVIOUS_GALLERY PRIVATE_PHOTO_DIRECTORY [--evidence DIRECTORY].
The source directory contains the original Thomas, Alex and Lek JPEGs. No network is used.
"""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree

from check_ring_scene import sample_walk
from test_garden_room import choose
from test_ring_guest_border import MOBILE, from_files, replay
from test_ring_object_photo import expand
from test_ring_photo import frame
from test_ring_seated_group import seated_view
from test_seated_beard import center_and_border
from test_separate_seat_photos import chair_photo, photo_form, render
from thrcommon import unpack_path


def photographed_edges(path):
    """Measure the boundaries of the teeth, moustache and goatee in the original photograph."""
    with Image.open(path) as image:
        original = np.asarray(ImageOps.exif_transpose(image).convert('L'), dtype=float)
    assert original.shape == (1500, 2000), 'Use the original Thomas photo with its original framing.'
    # Thomas's public face picker works in a 1000 x 750 photo. All brightness
    # measurements here use the original pixels before converting their locations.
    x = np.arange(676, 707, 6)
    columns = np.stack([original[:,2*i-1:2*i+2].mean(axis=1) for i in x], axis=1)
    smooth = gaussian_filter1d(columns, 1.7, axis=0)
    gradient = np.gradient(smooth, axis=0)
    upper = 554 + gradient[554:582].argmax(axis=0)
    lower = 578 + gradient[578:606].argmin(axis=0)
    k = np.arange(len(x))
    assert np.min(gradient[upper,k]) > 7 and np.max(gradient[lower,k]) < -6
    assert np.min(smooth[(upper+lower)//2,k]-smooth[upper-5,k]) > 58
    assert np.min(smooth[(upper+lower)//2,k]-smooth[lower+5,k]) > 48
    edges = {'teeth':np.stack((np.column_stack((x,upper/2)), np.column_stack((x,lower/2))))}
    # On these columns the dark chin hair gives way to the brighter neck. The
    # second set measures the separate hair-to-skin boundary above the upper lip.
    for key, xs, lo, hi, half, combine in [
            ('chin', np.arange(664,728,9), 346,370,1,np.mean),
            ('moustache', [678,682,686,690,698,702,706], 270,278,2,np.median)]:
        profiles = np.stack([combine(original[:,2*i-half:2*i+half+1],axis=1) for i in xs],axis=1)
        gradient = np.gradient(gaussian_filter1d(profiles,2,axis=0),axis=0)
        y = 2*lo + gradient[2*lo:2*hi+1].argmax(axis=0)
        assert gradient[y,np.arange(len(xs))].min() > 3, (key,'missing hair boundary')
        edges[key] = np.column_stack((xs,y/2))
    return edges


def observe_seats(page):
    # Observe only the photo placement. All strokes, travel joins and turns
    # measured below come directly from the files downloaded from the editor.
    page.evaluate("""() => {
      const convert=GuestPhoto.fromSeatPhotos;
      GuestPhoto.fromSeatPhotos=async (...args)=>{
        const result=await convert(...args);
        window.drawnSeats=result.seatFaces;
        return result;
      };
    }""")


def observe_solo_frame(page):
    # Solo drawings expose their photo dimensions, but not the fitted crop.
    # Record its origin and radius at the point where the converter applies
    # them, including any change to the photographed chin in a later gallery.
    page.evaluate("""() => {
      const script=document.querySelector('#portraitTools'), source=script.textContent;
      const fit='const norm=p=>[(p[0]-cx)/radius,(cy-p[1])/radius];';
      if (source.split(fit).length!==2) throw Error('Expected one solo portrait frame.');
      script.textContent=source.replace(fit,fit+
        ' window.drawnSoloFrame={sourceCenter:[cx,cy],center:[0,0],rotation:0,scale:1/radius};');
    }""")


def in_table(points, place, radius):
    angle = place['rotation']
    rotation = np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]])
    local = (points-place['sourceCenter'])*[1,-1]
    return (place['center'] + (local @ rotation)*place['scale'])*radius


def download(page, gallery, photos, edges, count, directory):
    guest = count == 0
    page.goto(gallery.resolve().as_uri()+('?layout=garden#guests' if guest else '?layout=portrait#photos'))
    if guest:
        choose(page,'zone','middle')
        expand(page,'#centerPhoto')
        page.locator('#portraitPlace').select_option('0')
    else:
        photo_form(page)
    if count > 1:
        page.locator('#portraitMode').select_option('separate')
        for name in ('thomas','alex','lek')[:count]:
            chair_photo(page,photos/(name+'.jpg'),1)
        observe_seats(page)
    else:
        observe_solo_frame(page)
        page.locator('#portraitFile').set_input_files(photos/'thomas.jpg')
    files = render(page)
    data = page.evaluate("""() => {
      const {live,zones}=JSON.parse(document.querySelector('#scene').textContent), z=zones.center;
      return {bed:live.bed, workingMM:live.radiusMM, groove:live.groove, trackingMM:live.trackingMarginMM,
        radius:z.transit.at(-1)[1],
        dock:z.transit[0], transit:z.transit.length, erase:z.erase.length, photoErase:z.photoErase,
        geometry:live.planner?.geometry, openFirst:live.planner?.defaults[0]===live.planner?.openSubject};
    }""")
    placement = page.evaluate('window.drawnSeats[0]' if count>1 else 'window.drawnSoloFrame')
    route = from_files(files,data['dock'])
    if guest:
        assert data['openFirst']
        geometry = data['geometry']
        angle = geometry['angles'][0]
        placement['center'] = geometry['center']*np.array([np.cos(angle),np.sin(angle)])
        placement['rotation'] = angle+np.pi/2
        placement['scale'] *= geometry['scale']
        radius, art = 1, route
    else:
        clear_len = len(unpack_path(data['photoErase'])) if data['photoErase'] else data['erase']
        radius = data['radius']
        art = route[data['transit']+clear_len-2:len(route)-data['transit']+1]
    signed = cKDTree(sample_walk(art,data['groove']/72))
    if count <= 1:
        # Two outer eye corners and the left and right edges of Thomas's nose,
        # registered in the original 1000-pixel preview before the mouth fix.
        # This checks the scale, orientation and offset independently of the smile.
        anchors = np.array([[637,212], [736,204], [672,260], [704,258]])
        anchor_errors = signed.query(in_table(anchors,placement,radius))[0] / (placement['scale']*radius)
        assert anchor_errors.max() < 1, ('incorrect photo registration (source pixels)',anchor_errors)
    face_ink = signed
    if count > 1:
        # The path to another chair may graze the photographed chin outside
        # the old short outline. Measure Thomas's own engraving between its two returns.
        xy = art[:,1,None]*np.column_stack((np.cos(art[:,0]),np.sin(art[:,0])))
        visits = np.flatnonzero(np.linalg.norm(xy-radius*np.asarray(placement['anchor']),axis=1) < .00003)
        assert len(visits) >= 2
        face_ink = cKDTree(sample_walk(art[visits[0]:visits[-1]+1],data['groove']/72))
    hair_errors = {key:np.round(face_ink.query(in_table(edges[key],placement,radius))[0]/data['groove'],3).tolist()
                   for key in ('chin','moustache')}
    teeth = edges['teeth']
    upper, lower = in_table(teeth,placement,radius)
    boundary_errors = signed.query([upper,lower])[0] / data['groove']
    # Probe the interior at finer spacing than one source pixel. Checking just
    # the opening's overall height would miss a travel line through the teeth.
    x = np.linspace(teeth[0,1,0],teeth[0,-2,0],97)
    centers = np.column_stack((x, np.interp(x,teeth[0,:,0],teeth.mean(axis=0)[:,1])))
    clear = signed.query(in_table(centers,placement,radius))[0]
    depth = np.interp(x,teeth[0,:,0],np.linalg.norm(lower-upper,axis=1))
    choose(page,'stage','original')
    before = frame(page)
    choose(page,'stage','redrawn')
    shown = frame(page)
    rebuilt = replay(page,data['bed'],route)
    diff = abs(rebuilt.astype(float)-shown)
    assert diff.mean()<1.1 and np.percentile(diff,99)<5
    if guest:
        y,xp = np.mgrid[-1:1:complex(len(shown)),-1:1:complex(len(shown))]
        r = np.hypot(xp,y)
        lo,hi = geometry['bounds']
        protected = (r < lo-2*data['groove']) | ((r > hi+2*data['groove']) & (r<.99) &
                    ((y<0) | (abs(xp)>3*data['groove'])))
    else:
        _,protected = center_and_border(len(shown),data)
    assert np.array_equal(shown[protected],before[protected]) and np.array_equal(rebuilt[protected],before[protected])
    directory.mkdir(parents=True,exist_ok=True)
    for name,raw in files:
        (directory/name).write_bytes(raw)
    Image.fromarray(rebuilt).save(directory/'signed-table.png')
    if count > 1:
        seated_view(rebuilt,placement,data['radius']).save(directory/'thomas-from-chair.png')
    groove_mm = data['groove']*data['workingMM']
    clearance_mm = clear*data['workingMM'] - groove_mm/2
    return {'files':[name for name,_ in files], 'hair_errors_grooves':hair_errors,
            'median_edge_error_grooves':np.median(boundary_errors,axis=1).round(3).tolist(),
            'edge_errors_grooves':boundary_errors.round(3).tolist(),
            'minimum_tooth_clearance_mm':round(float(clearance_mm.min()),2),
            'median_tooth_clearance_mm':round(float(np.median(clearance_mm)),2),
            'minimum_centerline_distance_fraction':round(float(np.min(clear/depth)),3),
            'upper_edge_distance_fraction':round(float(np.median(
                boundary_errors[0,1:-1]*data['groove']/np.linalg.norm(lower-upper,axis=1)[1:-1])),3),
            'photographed_band_mm':round(float(np.median(depth)*data['workingMM']),2),
            'two_edge_spacing_mm':round(1.25*groove_mm + 2*data['trackingMM'],2),
            'tracking_mm':data['trackingMM'],
            'open_fraction':round(float(np.mean(clearance_mm>0)),3),
            'protected_sand_pixels':int(protected.sum()),'mean_replay_error':round(float(diff.mean()),3)}


def exercise(browser, args, evidence):
    edges = photographed_edges(args.photos/'thomas.jpg')
    report = {'photo_edges':{key:points.tolist() for key,points in edges.items()}}
    for version, gallery in [('previous',args.previous),('current',args.gallery)]:
        cases = report[version] = {}
        for count,mode in [(3,'three-chairs'),(2,'two-chairs'),(1,'solo'),(0,'guest')]:
            with browser.new_page(**MOBILE) as page:
                page.route('http**://**/*',lambda request:request.abort())
                cases[mode]=download(page,gallery,args.photos,edges,count,evidence/version/mode)
                print(version,mode,cases[mode],flush=True)
    (evidence/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    old, new = report['previous'], report['current']
    assert old['three-chairs']['minimum_tooth_clearance_mm'] < 0 and old['three-chairs']['open_fraction'] < .8, \
        'The earlier three-chair drawing must show the travel stroke through Thomas’s teeth.'
    assert min(old['solo']['median_edge_error_grooves']) > 1.5, 'Expected the earlier oversized full-center mouth.'
    for mode, result in new.items():
        assert max(result['hair_errors_grooves']['chin']) <= .5, (mode,'the ball misses the photographed chin',result)
        if mode!='guest':
            assert np.median(old[mode]['hair_errors_grooves']['chin']) > 2, (mode,'expected the earlier short chin')
        if mode in ('two-chairs','three-chairs'):
            assert max(result['hair_errors_grooves']['moustache']) <= .5, (mode,'the ball misses the moustache edge',result)
        fits_both = result['photographed_band_mm'] >= result['two_edge_spacing_mm']
        assert fits_both == (mode=='solo'), (mode,'unexpected face scale for this fitted gallery',result)
        if not fits_both:
            # At smaller scales the lower edge carries the smile. The ball's
            # centerline must still stay outside the middle of the teeth.
            assert result['median_edge_error_grooves'][1] < .28, (mode,'missed the single lower tooth edge',result)
            assert result['minimum_centerline_distance_fraction'] > .25, (mode,'travel cuts the central teeth',result)
            assert result['upper_edge_distance_fraction'] > .6, (mode,'an extra stroke crowds the upper teeth',result)
            continue
        assert max(result['median_edge_error_grooves']) <= .5, (mode,'the groove misses a photographed tooth edge',result)
        assert result['minimum_tooth_clearance_mm'] > result['tracking_mm'], (mode,'tracking can close the opening',result)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('gallery','previous','photos'):
        parser.add_argument(name,type=Path)
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args,args.evidence or Path(tmp))
