#!/usr/bin/env python3
"""Verify the wide-center 'Around the table' portraits using actual phone downloads and earlier photo measurements.

Pass GALLERY PAIR CROPPED_THREE SEVEN --previous PRE_SEATS_GALLERY --evidence DIRECTORY.
Add --upgrade-from PRIOR_SEATED_GALLERY to exercise the attached-room upgrade. On the original
three- and seven-person fixtures this also checks each person's width against its earlier engraving.
The room runs on loopback. Only sand images and movement files are written to the evidence directory.
"""

import argparse
import base64
import hashlib
import json
import math
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_attached_garden import Table, served, wait_table
from test_garden_room import caption, choose, drawing_files, room
from test_ring_group_shadows import source_measurements
from test_ring_guest_border import MOBILE, from_files, open_garden, preview, replay, save
from test_ring_photo import check_portrait, frame, ordinary_erase_pitch
from test_ring_shadows import ready


def analyze_seats(page, order=None):
    return page.evaluate("""async seatOrder => {
      const s=JSON.parse(document.querySelector('#scene').textContent), z=s.zones.center, live=s.live;
      const radius=z.transit.at(-1)[1], tracking=live.trackingMarginMM ?? live.radiusMM*live.groove/2;
      const result=await GuestPhoto.fromFile(document.querySelector('#portraitFile').files[0],{
        group:true,groupStyle:'seats',portraitDiameterMm:2*radius*live.radiusMM,portraitDiameterGrooves:2*radius/live.groove,
        portraitTrackingGrooves:tracking/(live.radiusMM*live.groove),seatOrder});
      const plan=OasisRingPlanner.photo(z,result.points);
      return {points:result.points, seats:result.seatFaces, count:result.facesDetected, boxes:result.includedFaces,
        sourceSize:[result.sourceWidth,result.sourceHeight],
        style:result.groupStyle, segments:plan.segments, ordinary:z.erase,
        fine:!!z.photoErase, radius, groove:live.groove, tracking:tracking/live.radiusMM, workingMm:live.radiusMM};
    }""", order)


def browse_seats(page, data, files, selector, directory, *, halfway=False):
    count = len(data['seats'])
    image = frame(page)
    links = page.locator(selector+' a')
    urls = links.evaluate_all('a=>a.map(x=>x.href)')
    for index, seat in enumerate(data['seats']):
        expect(page.locator('#seatNumber')).to_have_text(f'Seat {index+1} of {count}')
        angle = seat['seatAngle']
        # The selected seat's radius must now point down on the actual displayed table.
        rotation = page.locator('#sand').evaluate('im=>parseFloat(getComputedStyle(im).rotate)||0')
        screen_angle = -angle + math.radians(rotation)
        np.testing.assert_allclose([math.cos(screen_angle),math.sin(screen_angle)],[0,1], atol=.0001)
        if selector == '#downloads' and index in (0,count-1):
            page.locator('.bowl').screenshot(path=str(directory/f'view-{index+1}.png'))
        page.get_by_role('button',name='View from next seat').click()
    expect(page.locator('#seatNumber')).to_have_text(f'Seat 1 of {count}')
    assert np.array_equal(frame(page), image) and urls == links.evaluate_all('a=>a.map(x=>x.href)')
    if not halfway:
        assert drawing_files(page, selector) == files


def face_button(page, box, size):
    """Locate the tapped person by where their face falls on the original photo."""
    buttons = page.locator('#faceBoxes button')
    centers = buttons.evaluate_all("""buttons => buttons.map(b => [
      (parseFloat(b.style.left)+parseFloat(b.style.width)/2)/100,
      (parseFloat(b.style.top)+parseFloat(b.style.height)/2)/100
    ])""")
    delta = np.linalg.norm(np.asarray(centers)-np.array([box['x'],box['y']])/size, axis=1)
    assert np.sum(delta < .002) == 1, 'Expected one selection on the photographed face'
    return buttons.nth(int(np.argmin(delta)))


def assign_seats(page, boxes, size):
    page.locator('#arrangeSeats').tap()
    expect(page.locator('#portraitSource')).to_have_attribute('open','')
    for i, box in enumerate(boxes):
        face = face_button(page, box, size)
        face.tap()
        if i+1 < len(boxes):
            expect(face).to_be_disabled()
            expect(face).to_have_text(str(i+1))
    ready(page)


def seating_request(page, data, original, directory):
    boxes = [s['sourceBox'] for s in data['seats']]
    assert boxes == sorted(boxes, key=lambda box:(box['x'],box['y'])), 'New photo inherited the preceding order'
    size = np.array(data['sourceSize'])
    # Swapping the first two in a group of three cannot be achieved by rotating the table.
    wanted = [boxes[1],boxes[0],*boxes[2:]]
    baseline = frame(page)
    page.locator('#arrangeSeats').tap()
    face_button(page, boxes[-1], size).tap()
    page.locator('#frameFace').tap()
    expect(face_button(page, boxes[-1], size)).to_be_enabled()
    face_button(page, boxes[1], size).tap()
    page.locator('#arrangeSeats').tap()
    ready(page)
    assert drawing_files(page,'#downloads') == original and np.array_equal(frame(page),baseline)

    assign_seats(page, wanted, size)
    changed = drawing_files(page,'#downloads')
    assert changed != original
    reordered = analyze_seats(page, wanted)
    assert [seat['sourceBox'] for seat in reordered['seats']] == wanted
    changed_sand = frame(page)
    assert not np.array_equal(changed_sand, baseline)
    assign_seats(page, boxes, size)
    assert drawing_files(page,'#downloads') == original and np.array_equal(frame(page),baseline)
    assign_seats(page, wanted, size)
    assert drawing_files(page,'#downloads') == changed and np.array_equal(frame(page),changed_sand)
    Image.fromarray(baseline).save(directory/'photo-order.jpg', quality=94)
    return reordered, changed


def compare_signed_faces(original, files_before, arranged, files_after):
    """Follow each person's actual downloaded furrows to their newly requested seat."""
    def read_faces(data, files):
        route = from_files(files, data['segments'][0][0])
        start = len(data['segments'][0]) + len(data['segments'][1]) - 2
        art = route[start:start+len(data['segments'][2])]
        xy = art[:,1,None]*np.column_stack((np.cos(art[:,0]),np.sin(art[:,0])))
        result = {}
        for seat in data['seats']:
            anchor = np.asarray(seat['anchor'])*data['radius']
            visits = np.flatnonzero(np.linalg.norm(xy-anchor,axis=1)<2e-5)
            assert len(visits) >= 2, 'Signed drawing is missing a portrait entry'
            ink = check.sample_walk(art[visits[0]:visits[-1]+1],.09/data['workingMm'])
            drawn_bounds = np.r_[ink.min(axis=0),ink.max(axis=0)]*data['workingMm']
            expected_bounds = np.array(seat['bounds'])*data['radius']*data['workingMm']
            np.testing.assert_allclose(drawn_bounds, expected_bounds, atol=.10, rtol=0,
                                       err_msg='The drawn portrait does not fit its photographed outline')
            angle = seat['seatAngle']
            turn = np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
            result[seat['sourceIndex']] = ink @ turn * data['workingMm']
        return result

    before, after = read_faces(original,files_before), read_faces(arranged,files_after)
    errors = {}
    for source, old in before.items():
        new = after[source]
        miss = max(cKDTree(old).query(new)[0].max(),cKDTree(new).query(old)[0].max())
        assert miss < .12, f'Person {source+1} changed shape or moved to the wrong seat ({miss:.2f} mm)'
        errors[source] = round(float(miss),3)
    return errors


def legacy_border(page, api, url, count):
    # Hold the normal border save while trying a forged change to the center.
    held = []
    def intercept(route):
        if route.request.method == 'PUT':
            held.append(route)
        else:
            route.fallback()
    page.route(api, intercept)
    try:
        with page.expect_request(lambda r:r.url==api and r.method=='PUT'):
            page.locator('#keep').click()
        assert len(held) == 1
        body = held[0].request.post_data_json
        assert body['motion']['zone']=='outer' and body['state']['portraitSeats']==count
        forged = {**body,'state':{**body['state'],'portraitSeats':count+1}}
        rejected = page.request.put(api,headers={'Origin':url},data=forged)
        assert rejected.status==400 and 'Seat views' in rejected.text(), rejected.text()
        assert page.request.get(api).json()['revision']==body['revision']
        # The earlier client sends the exact valid border change without the new center field.
        del body['state']['portraitSeats']
        with page.expect_response(lambda r:r.url==api and r.request.method=='PUT') as saved:
            held[0].fallback(post_data=json.dumps(body))
        assert saved.value.status==200, saved.value.text()
        expect(page.locator('#keep')).to_be_hidden()
        assert page.request.get(api).json()['state']['portraitSeats']==count
        return body
    finally:
        page.unroute(api, intercept)


def seat_clearance(signed_art, seats, radius, groove, tracking):
    """Measure only the individual engraving between its two visits to the shoulder entry."""
    theta, rho = signed_art.T
    xy = rho[:,None]*np.column_stack((np.cos(theta), np.sin(theta)))
    strokes = []
    for seat in seats:
        anchor = radius*np.asarray(seat['anchor'])
        visits = np.flatnonzero(np.linalg.norm(xy-anchor,axis=1) < 2e-5)
        assert len(visits) >= 2, 'Signed portrait did not return to its own entry'
        strokes.append(check.sample_walk(signed_art[visits[0]:visits[-1]+1], groove/40))
    minimum = min(cKDTree(a).query(b)[0].min() for i,a in enumerate(strokes) for b in strokes[:i])
    # Sampling can overestimate the gap by one sample spacing. Allow also for
    # the five-decimal theta/radius values in the downloaded movement file.
    clear = minimum - groove - 2*tracking - groove/40 - 2e-5
    assert clear > .20*groove, 'Adjacent heads can touch within the stated tracking allowance'
    return float(clear)


def photographed_features(data, normal, reference, family):
    """Sample the finished signed ink in each photographed upper head and eye region."""
    radius, groove = data['radius'], data['groove']
    end = len(data['segments'][0]) + len(data['segments'][1]) - 2
    art = normal[end:end+len(data['segments'][2])]
    xy = art[:,1,None]*np.column_stack((np.cos(art[:,0]),np.sin(art[:,0])))
    features = []
    for seat in data['seats']:
        anchor = radius*np.array(seat['anchor'])
        hits = np.flatnonzero(np.linalg.norm(xy-anchor,axis=1) < .00002)
        ink = check.sample_walk(art[hits[0]:hits[-1]+1],groove/30)
        # Count a retraced eyelid once regardless of how often the pen returns.
        _, indices = np.unique(np.rint(ink/(groove/16)),axis=0,return_index=True)
        ink = ink[indices]
        face = reference['faces'][reference['boxes'].index(seat['sourceBox'])]
        a = seat['rotation']
        axes = np.array([[math.cos(a),math.sin(a)],[-math.sin(a),math.cos(a)]])
        def project(points):
            local = (np.asarray(points) - seat['sourceCenter']) * [1,-1]
            return radius*(seat['center'] + local @ axes * seat['scale'])

        # Five independent readings of the side of the nose in the family
        # photograph's 1000-pixel decode. The old groove crossed its front.
        if family:
            nose_edge = ([[248.7,355.0],[250.7,361.4],[251.5,367.5],[252.7,373.7],[253.9,380.0]]
                         if seat['sourceBox']['x'] < data['sourceSize'][0]/2 else
                         [[597.8,236.4],[596.8,245.5],[593.9,255.5],[588.8,266.7],[591.4,273.9]])
            nose_error = cKDTree(ink).query(project(nose_edge))[0]
            assert np.median(nose_error) < .30*groove, 'The seated outline misses the side of the photographed nose'
        landmarks = project(face['L'])
        eyes = landmarks[36:48].mean(axis=0)
        down = landmarks[8]-eyes
        brow = landmarks[17:27].mean(axis=0)
        regions = {'upper_head':ink[(ink-brow) @ down < -.20*groove*np.linalg.norm(down)]}
        frames = face['glasses']
        for side in range(2):
            curve = project(frames[side]) if frames else landmarks[36+6*side:42+6*side]
            curve = np.vstack((curve,curve[0]))
            distance = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(curve,axis=0),axis=1))]
            grid = np.linspace(0,distance[-1],max(2,math.ceil(distance[-1]/(groove/20))))
            samples = np.column_stack([np.interp(grid,distance,axis) for axis in curve.T])
            regions['eye_'+str(side+1)] = ink[cKDTree(samples).query(ink)[0] < groove*.75]
        assert all(len(points) >= 5 for points in regions.values()), 'Missing measured face feature'
        features.append(regions)
    return features


def early_ink(route, clear, fraction, groove):
    """Discard the ordinary spiral and its retracings so a crossing cannot impersonate an eye."""
    dist = check.travel(route)
    stop = np.searchsorted(dist,dist[-1]*fraction)
    partial = np.vstack((route[:stop],route[stop-1]+(route[stop]-route[stop-1])*
                         ((dist[-1]*fraction-dist[stop-1])/(dist[stop]-dist[stop-1]))))
    center = np.flatnonzero(clear[:,1] == 0)[-1]
    rim = center+1+np.argmax(clear[center+1:,1])
    spiral = clear[center:rim+1]
    direction = np.sign(spiral[-1,0]-spiral[0,0])
    start = np.flatnonzero(partial[:,1] == 0)[-1]
    work = partial[start:]
    radii = np.interp(direction*work[:,0],direction*spiral[:,0],spiral[:,1])
    off = np.abs(work[:,1]-radii) > check.TOL
    engraving = off[:-1] | off[1:]
    if not np.any(engraving):
        return None
    cuts = np.r_[0,np.flatnonzero(engraving[1:] != engraving[:-1])+1,len(work)-1]
    later_sweeps, ink = [], []
    for first,last in reversed(list(zip(cuts,cuts[1:]))):
        samples = check.sample_walk(work[first:last+1],groove/28)
        if engraving[first]:
            # The renderer displaces sand within 1.15 grooves of the ball.
            # Exclude any earlier ink a later ordinary pass could disturb.
            for tree in later_sweeps:
                samples = samples[tree.query(samples)[0] > 1.15*groove+groove/28]
            ink.append(samples)
        else:
            later_sweeps.append(cKDTree(samples))
    return cKDTree(np.vstack(ink)) if any(len(samples) for samples in ink) else None


def check_seated_reveal(page, data, files, reference, bed, directory, family):
    """Compare the optional route and its halfway phone frame against the actual downloads."""
    directory.mkdir(exist_ok=True)
    toggle = page.locator('#seatedReveal')
    if not toggle.count():  # Also exercise saved galleries produced before this option.
        return {}
    toggle.check()
    ready(page)
    signed = drawing_files(page,'#downloads')
    if signed == files:
        expect(page.locator('#seatedRevealNotice')).to_be_visible()
        expect(page.locator('#middleStageLabel')).to_have_text('Cleared')
        expect(page.locator('#keep')).to_be_visible()
        assert not family, 'The fitted family pair fell back to the ordinary drawing'
        toggle.uncheck()
        ready(page)
        return {'ordinary_fallback':True}
    expect(page.locator('#middleStageLabel')).to_have_text('Halfway')
    expect(page.locator('#seatedRevealNotice')).to_be_hidden()
    for name, content in signed:
        (directory/name).write_bytes(content)
    segments = data['segments']
    route, normal = [from_files(parts,segments[0][0]) for parts in (signed, files)]
    dist = check.travel(route)
    groove = data['groove']
    start = len(segments[0])-1
    clear = normal[start:start+len(segments[1])]
    regions = photographed_features(data,normal,reference,family)
    normal_first_ink = check.travel(normal)[start+len(clear)-1]
    assert normal_first_ink > .7*check.travel(normal)[-1]
    # The actual protected border cannot change during an early excursion.
    choose(page,'stage','original')
    original = frame(page)
    choose(page,'stage','cleared')
    half = frame(page)
    y,x = np.mgrid[-1:1:complex(len(half)),-1:1:complex(len(half))]
    outer = (np.hypot(x,y)>data['radius']+3*groove) & (np.hypot(x,y)<.99) & ((y<0)|(abs(x)>3*groove))
    assert np.array_equal(half[outer],original[outer])
    half_index = int(np.argmin(abs(dist-.5*dist[-1])))
    diff = abs(half.astype(int)-replay(page,bed,route[:start+1],route[start:half_index+1]).astype(int))
    assert diff.mean()<1.1 and np.percentile(diff,99)<5, ('Different halfway drawing',diff.mean())
    browse_seats(page,data,signed,'#downloads',directory,halfway=True)
    result = {'travel_m':round(float(dist[-1]*data['workingMm']/1000),3),
              'ordinary_travel_m':round(float(check.travel(normal)[-1]*data['workingMm']/1000),3),
              'ordinary_erase_end_percent':round(float(normal_first_ink/check.travel(normal)[-1]*100),2),
              'people':{}}
    for fraction in (.5,.7):
        cloud = early_ink(route,clear,fraction,groove)
        assert early_ink(normal,clear,fraction,groove) is None
        for seat, marks in zip(data['seats'],regions):
            covered = {label:round(100*float(np.mean(cloud.query(points)[0] < .12*groove)),1) if cloud is not None else 0
                       for label,points in marks.items()}
            if family:
                assert covered['upper_head'] >= 85 and min(covered['eye_1'],covered['eye_2']) >= 65, (
                    'Too little of a seated portrait survives the sweep',seat['sourceIndex'],fraction,covered)
            result['people'].setdefault(seat['sourceIndex'],{})[fraction] = covered
        cut = int(np.argmin(abs(dist-fraction*dist[-1])))
        raster = half if fraction == .5 else replay(page,bed,route[:start+1],route[start:cut+1])
        for i,seat in enumerate(data['seats'],1):
            seated_view(raster,seat,data['radius']).save(directory/f'seat-{i}-at-{int(100*fraction)}.jpg',quality=94)
    choose(page,'stage','redrawn')
    assert np.array_equal(frame(page)[outer],original[outer])
    toggle.uncheck()
    ready(page)
    assert drawing_files(page,'#downloads') == files
    return result


def seated_view(image, seat, radius):
    """Show the actual sand with the selected viewer at the bottom of the frame."""
    side = 300
    center, bounds, rotation = np.array(seat['center']), np.array(seat['bounds']), seat['rotation']
    extent = max(bounds[2]-bounds[0],bounds[3]-bounds[1])*1.3
    r = (len(image)-1)/2
    x,y = r*(1+center*[radius,-radius])
    m = r*radius*extent/side
    a,b = m*math.cos(rotation),m*math.sin(rotation)
    return Image.fromarray(image).transform((side,side),Image.Transform.AFFINE,
                (a,b,x-side*(a+b)/2, -b,a,y-side*(a-b)/2),resample=Image.Resampling.BICUBIC)


def check_family_smile(ink, project, left_face, groove, tracking):
    # Five upper and lower margin readings taken on the original private photo
    # at its 1000-pixel decode, before fitting the smiles. All distances below
    # come from the phone download, including the connecting stroke.
    edges = ([[[195,405],[205,407],[214,410],[224,412],[234,412]],
              [[193,421],[202,426],[211,429],[221,431],[231,428]]] if left_face else
             [[[646,310],[659,304],[672,295],[685,287],[698,281]],
              [[655,335],[669,329],[682,320],[696,315],[708,306]]])
    upper, lower = project(edges)
    edge_error = np.median(ink.query([upper, lower])[0], axis=1) / groove
    assert edge_error[0] < .39 and edge_error[1] < .22, ('Missed the photographed opening', edge_error)
    # Both passes can wander inward. Check the remaining room across the
    # center of the actual pictured opening, including any furrow through it.
    cuts = np.linspace(upper, lower, 101)
    radii = np.max(ink.query(cuts)[0], axis=0)
    assert np.median(radii) > groove/2+tracking, 'The smile can disappear at the measured tracking allowance'
    if left_face:
        assert ink.query(project([218,398]))[0] > groove/2, 'A travel line crosses the skin above the lip'
    return np.round(edge_error, 3).tolist()


def engravings(data, files, reference, count, final, directory, family_photo=False):
    parts = [np.asarray(part) for part in data['segments']]
    route = from_files(files, parts[0][0])
    groove, radius = data['groove'], data['radius']
    error = check_portrait(data['points'], parts, route, groove, ordinary_erase_pitch(data['ordinary']), data['fine'])
    start = len(parts[0]) + len(parts[1]) - 2
    signed_art = route[start:start + len(parts[2])]
    ink = cKDTree(check.sample_walk(signed_art, groove/24))
    seats = data['seats']
    assert data['style'] == 'seats' and len(seats) == data['count'] == count
    assert sorted(s['sourceIndex'] for s in seats) == list(range(count))
    angles, checks = [], []
    for seat in seats:
        box = seat['sourceBox']
        assert data['boxes'][seat['sourceIndex']] == box
        face = reference['faces'][reference['boxes'].index(box)]
        angle, rotation = seat['seatAngle'], seat['rotation']
        radial = np.array([math.cos(angle), math.sin(angle)])
        turn = np.array([[math.cos(rotation), -math.sin(rotation)], [math.sin(rotation), math.cos(rotation)]])
        center = np.asarray(seat['center'])
        assert np.dot(center / np.linalg.norm(center), radial) > .998
        # Eyes should sit inward of the mouth. Use the source jaw and eyes to judge the actual motion.
        landmarks = (np.asarray(face['L']) - seat['sourceCenter']) * [1, -1]
        drawn = center + landmarks @ turn.T * seat['scale']
        eyes = drawn[36:48].mean(0)
        toward_chin = drawn[8] - eyes
        cosine = toward_chin @ radial / np.linalg.norm(toward_chin)
        assert cosine > math.cos(math.radians(50)), 'A face is upside down for its nearest guest'
        np.testing.assert_allclose(drawn[8], seat['chin'], rtol=0, atol=.005)
        jaw = ink.query(drawn[:17] * radius)[0] / groove
        lips = ink.query(drawn[[48,54]] * radius)[0] / groove
        assert np.percentile(jaw, 90) < .65 and max(lips) < .9, ('Missing photographed jaw or lips', jaw, lips)
        if count == 2:
            # In the family pair the rail meets a short neckline. The previous
            # shoulders used a third of a jaw width below the chin. Cropping
            # all the way to the head instead put the rail on the jaw itself.
            # seat_clearance verifies the download visits this anchor twice.
            down = drawn[8] - drawn[[19,24]].mean(0)
            jaw_width = np.linalg.norm(drawn[0] - drawn[16])
            to_entry = np.asarray(seat['anchor']) - drawn[8]
            extension = to_entry @ down / (np.linalg.norm(down) * jaw_width)
            assert .02 < extension < .18, ('Expected a short neckline below the chin', extension)
        eye_error = []
        for indices in (slice(36,42), slice(42,48)):
            eye_error.append(float(min(ink.query(drawn[indices]*radius)[0])/groove))
        assert max(eye_error) < 1.3, ('Missing eye or glasses', eye_error)
        angles.append(angle % math.tau)
        source_eye_axis = np.asarray(face['L'])[42:48].mean(0) - np.asarray(face['L'])[36:42].mean(0)
        _,temples = ink.query(drawn[[0,16]]*radius)
        signed_width = np.linalg.norm(ink.data[temples[1]]-ink.data[temples[0]]) * data['workingMm']
        checks.append({'source_index':seat['sourceIndex'],
                       'photo_position':np.round(np.array([box['x'],box['y']])/data['sourceSize'],3).tolist(),
                       'head_width_mm':round(seat['headWidth']*radius*data['workingMm'], 2),
                       'signed_temple_width_mm':round(float(signed_width),2),
                       'photographic_eye_tilt_deg':round(math.degrees(math.atan2(source_eye_axis[1],source_eye_axis[0])), 1),
                       'head_tilt_from_inward_deg':round(math.degrees(math.acos(np.clip(cosine,-1,1))),1),
                       'jaw_p90_grooves':round(float(np.percentile(jaw,90)),3), 'lip_error_grooves':round(float(max(lips)),3)})
        if family_photo and np.allclose(np.array([radius, groove, data['tracking']])*data['workingMm'],
                                        [316.4,7,3.5], atol=.1, rtol=0):
            def project(source):
                local = (np.asarray(source) - seat['sourceCenter']) * [1,-1]
                return radius*(center + local @ turn.T * seat['scale'])
            checks[-1]['smile_margin_error_grooves'] = check_family_smile(
                ink, project, box['x'] < data['sourceSize'][0]/2, groove, data['tracking'])
        seated_view(final,seat,radius).save(directory/f"seat-{len(checks)}.jpg", quality=94)
    gaps = np.diff(np.r_[np.sort(angles), min(angles)+math.tau])
    np.testing.assert_allclose(gaps, math.tau/count, rtol=0, atol=.002)
    clear = seat_clearance(signed_art, seats, radius, groove, data['tracking'])
    return {'people':checks,'files':len(files),'signed_rows':len(route),'ordered_error_grooves':round(error/groove,4),
            'clear_between_people_after_tracking_mm':round(clear*data['workingMm'],2)}, route


def check_fitted_widths(source_sha, data, people):
    # Each number is temple to temple on the preceding gallery's actual download,
    # sorted by the detected face's source index, independent of the seating order.
    baselines = {
        '61cc88e35869c2b7c6c020bc5be5cd403a902686632a4d6e7d1a0dc7de2860ed':
            ([168.45, 173.83, 176.76], 1.035),
        '6579b24f4c2048bcc910ff663ecd8a793be49d422766bf08ce5b73a73890cd0d':
            ([127.80, 122.44, 130.08, 132.42, 141.51, 124.47, 124.81], 1.02),
    }
    working = data['workingMm']
    dimensions = [working, working*data['radius'], working*data['groove'], working*data['tracking']]
    if source_sha not in baselines or not np.allclose(dimensions,[420,316.4,7,3.5],rtol=0,atol=.05):
        return
    previous, minimum_gain = baselines[source_sha]
    for person in people:
        index = person['source_index']
        assert person['signed_temple_width_mm'] >= previous[index]*minimum_gain, (
            'The fitted group portrait lost its measured gain', index, previous[index], person['signed_temple_width_mm'])


def saved_group_upgrade(browser, args):
    """Upgrade a table with a seated portrait on it and play the original and new exports in order."""
    def submit(page, source, count):
        choose(page,'zone','center')
        panel = page.locator('#centerPhoto')
        if not panel.evaluate('p=>p.open'):
            panel.locator('summary').first.click()
        page.locator('#portraitMode').select_option('group')
        page.locator('#portraitStyle').select_option('seats')
        page.locator('#portraitFile').set_input_files(source)
        page.locator('#portraitSubmit').click()
        ready(page)
        caption(page,f'Group portrait · {count} faces around the table')
        return drawing_files(page,'#downloads')

    def pair_routes(page):
        ordinary = submit(page,args.pair,2)
        page.locator('#seatedReveal').check()
        ready(page)
        return ordinary,drawing_files(page,'#downloads')

    with tempfile.TemporaryDirectory() as folder:
        database = Path(folder)/'wide.db'
        table = Table(database)
        with served(args.upgrade_from,database,table,prepared=True,layout='portrait') as url, \
                browser.new_page(**MOBILE) as first:
            api = url+'/api/garden/portrait'
            open_garden(first,url,'portrait')
            setup = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
            preview(first,4,'Lek',order='progressive')
            border,_ = save(first,api)
            old_pair = pair_routes(first)
            original = submit(first,args.cropped,3)
            saved,_ = save(first,api)
            old_room = first.request.get(api).json()
            old_sand = frame(first)
            assert saved['state']['portraitSeats'] == 3
            assert original == [(f['name'],f['text'].encode()) for f in saved['motion']['files']]

        with served(args.gallery,database,table,layout='portrait') as url, \
                browser.new_page(**MOBILE) as first, browser.new_page(**MOBILE) as second:
            api = url+'/api/garden/portrait'
            open_garden(second,url,'portrait')
            choose(second,'zone','center')
            caption(second,'Group portrait · 3 faces around the table')
            assert second.request.get(api).json() == old_room
            assert drawing_files(second,'#roomFiles') == original and np.array_equal(frame(second),old_sand)
            assert pair_routes(second) == old_pair, 'A previously proven drawing of the pair changed.'
            all_files = [*setup,*border['motion']['files'],*saved['motion']['files']]
            for photo,count in ((args.cropped,3),(args.seven,7)):
                files = submit(second,photo,count)
                kept,revision = save(second,api)
                assert files == [(f['name'],f['text'].encode()) for f in kept['motion']['files']]
                assert second.request.get(api+'/drawings/outer').json()['files'] == border['motion']['files']
                all_files.extend(kept['motion']['files'])
                open_garden(first,url,'portrait')
                choose(first,'zone','center')
                caption(first,f'Group portrait · {count} faces around the table')
                assert drawing_files(first,'#roomFiles') == files and np.array_equal(frame(first),frame(second))
                if count == 3:
                    assert files != original, 'The updated phone produced the old three-person drawing.'
            for i,part in enumerate(all_files,1):
                assert table.dispatched(i) == part
                table.outcome = 'complete'
            wait_table(first,url,state='idle',queued=0,ready=True,revision=revision)
            assert len(table.calls) == len(all_files)
            print(f'The saved three-person drawing kept its sand and files through the gallery update. '
                  f'Both phones received the new three- and seven-person portraits. '
                  f'All {len(all_files)} files played once in order with the simulated controller.',flush=True)


def run(browser, args):
    cases = [('pair', args.pair, 2), ('cropped-three', args.cropped, 3), ('seven', args.seven, 7)]
    with browser.new_page() as local:
        local.route('http**://**/*', lambda route: route.abort())
        references = source_measurements(local, args.previous, [file for _,file,_ in cases])
    with tempfile.TemporaryDirectory() as tmp, room(args.gallery,Path(tmp)/'room.db') as url, \
            browser.new_context(**MOBILE, service_workers='block') as a, browser.new_context(**MOBILE, service_workers='block') as b:
        api = url + '/api/garden/portrait'
        violations, writes, forbidden = [], [], []
        def guard(route):
            req = route.request
            parsed = urlsplit(req.url)
            allowed = {'/garden','/favicon.ico','/api/garden/portrait','/api/garden/portrait/drawings/center',
                       '/api/garden/portrait/drawings/outer'}
            if not req.url.startswith(url + '/') or parsed.path not in allowed or parsed.query not in ('', 'layout=portrait') or (
                    req.method != 'GET' and (req.method != 'PUT' or req.url != api)):
                violations.append((req.method, req.url))
                route.abort()
            else:
                if req.method == 'PUT':
                    writes.append(req.post_data_buffer)
                route.continue_()
        for context in (a,b):
            context.route('http**://**/*', guard)
        first, second = a.new_page(), b.new_page()
        for page in (first, second):
            page.on('pageerror', lambda problem: violations.append(str(problem)))
            open_garden(page, url, 'portrait')
        preview(first, 4, 'Lek', order='progressive')
        border, _ = save(first, api)
        caption(second, 'Lek · Autumn leaves')
        report = {}
        family_files = None
        for i, (label, file, count) in enumerate(cases):
            directory = args.evidence / label
            directory.mkdir(parents=True, exist_ok=True)
            choose(first, 'zone', 'center')
            choose(second, 'zone', 'center')
            old = first.request.get(api).json()['state']
            before = frame(first)
            box = first.locator('#centerPhoto')
            if not box.evaluate('d=>d.open'):
                box.locator(':scope > summary').click()
            first.locator('#portraitMode').select_option('group')
            first.locator('#portraitStyle').select_option('seats')
            marker = ('private-original-' + label).encode()
            raw = file.read_bytes() + marker
            basename = 'private-upload-' + label + '.jpg'
            first.locator('#portraitFile').set_input_files({'name':basename,'mimeType':'image/jpeg','buffer':raw})
            encoded = base64.b64encode(raw)
            forbidden.extend([basename.encode(), marker, raw[len(raw)//2:len(raw)//2+80], encoded[len(encoded)//2:len(encoded)//2+80]])
            first.locator('#portraitSubmit').click()
            ready(first)
            data = analyze_seats(first)
            title = first.locator('.caption').inner_text()
            assert title == f'Group portrait · {count} faces around the table'
            files = drawing_files(first, '#downloads')
            original_files = files
            default_data = data
            original_positions = [s['sourceIndex'] for s in data['seats']]
            source_sha = hashlib.sha256(file.read_bytes()).hexdigest()
            family = count == 2 and source_sha == (
                'e16aa7f98e631fbbd72e2ba27160673b091b4d94fcea4d6ccf6cc67c78211296')
            reveal = {'photo_order':check_seated_reveal(first,data,files,references[file],old['bed'],
                                                        directory/'early-photo-order',family)}
            if count in (2,3):
                data, files = seating_request(first, data, files, directory)
                if count == 2:
                    family_files = files
                    reveal['other_seats'] = check_seated_reveal(first,data,files,references[file],old['bed'],
                                                                directory/'early-other-seats',family)
            browse_seats(first, data, files, '#downloads', directory)
            for name, content in files:
                (directory/name).write_bytes(content)
            final = frame(first)
            info, route = engravings(data, files, references[file], count, final, directory, family)
            if args.upgrade_from:
                check_fitted_widths(source_sha, data, info['people'])
            if any(reveal.values()):
                info['early_seated_drawing'] = reveal
            if count in (2,3):
                info['signed_face_rotation_error_mm'] = compare_signed_faces(default_data,original_files,data,files)
            assert any(abs(p['photo_position'][0]-.5) > .19 for p in info['people']), 'Expected an off-center face'
            if count == 2:
                assert max(abs(p['photographic_eye_tilt_deg']) for p in info['people']) > 15, 'Expected a genuinely tilted face'
            choose(first, 'stage', 'cleared')
            cleared = frame(first)
            choose(first, 'stage', 'redrawn')
            high, groove = data['radius'], data['groove']
            y,x = np.mgrid[-1:1:complex(len(before)), -1:1:complex(len(before))]
            r = np.hypot(x,y)
            outer = (r > high+3*groove) & (r < .99) & ((y < 0) | (abs(x)>3*groove))
            center = r < high-2*groove
            assert np.array_equal(cleared[outer],before[outer]) and np.array_equal(final[outer],before[outer])
            ends = np.cumsum([len(p)-1 for p in data['segments']])
            parts = [route[start:end+1] for start,end in zip([0,*ends[:-1]], ends)]
            for raster, moves in ((cleared, parts[:2]), (final, parts)):
                delta = np.abs(raster.astype(np.int16) - replay(first, old['bed'], *moves).astype(np.int16))
                assert delta.mean() < 1.1 and np.percentile(delta,99) < 5, 'Downloaded photo differs from displayed sand'
            for name, raster in [('before',before), ('cleared',cleared), ('drawn',final)]:
                Image.fromarray(raster).save(directory/(name+'.jpg'), quality=94)
            assert first.request.get(api).json()['state'] == old
            if family and reveal.get('other_seats',{}).get('people'):
                first.locator('#seatedReveal').check()
                ready(first)
                files = drawing_files(first,'#downloads')
                assert files == [(name,(directory/'early-other-seats'/name).read_bytes()) for name,_ in files]
            kept, _ = save(first, api)
            assert kept['state']['portrait'] == title and kept['state']['portraitSeats'] == count
            assert kept['state']['outer'] == old['outer']
            assert files == [(f['name'],f['text'].encode()) for f in kept['motion']['files']]
            assert first.request.get(api+'/drawings/outer').json()['files'] == border['motion']['files']
            open_garden(second, url, 'portrait')
            choose(second, 'zone', 'center')
            caption(second, title)
            assert second.locator('#portraitFile').evaluate('input => input.files.length') == 0
            assert drawing_files(second, '#roomFiles') == files
            browse_seats(second, data, files, '#roomFiles', directory)
            kept_sand = frame(second)
            assert np.array_equal(kept_sand, frame(first))
            choose(second,'zone','outer')
            new_border = 3 if i%2 == 0 else 4
            preview(second,new_border,'Lek')
            border = legacy_border(second,api,url,count) if i==0 else save(second,api)[0]
            after = frame(second)
            assert np.array_equal(after[center], kept_sand[center]) and np.any(after[outer]!=kept_sand[outer])
            assert first.request.get(api+'/drawings/center').json()['files'] == kept['motion']['files']
            choose(first,'zone','outer')
            caption(first, 'Lek · ' + ('Lotus buds' if new_border==3 else 'Autumn leaves'))
            assert np.array_equal(frame(first),after)
            Image.fromarray(after).save(directory/'after-border.jpg', quality=94)
            info.update(caption=title, protected_border_pixels=int(outer.sum()), kept_center_pixels=int(center.sum()))
            info['photo_order_from_left'] = [original_positions.index(s['sourceIndex'])+1 for s in data['seats']]
            info['photo_order_file_sha256'] = [hashlib.sha256(content).hexdigest() for _,content in original_files]
            info['saved_file_sha256'] = [hashlib.sha256(content).hexdigest() for _,content in files]
            report[label]=info
            print(label, json.dumps(info), flush=True)
        assert not violations and len(writes)==1+2*len(cases), (violations,len(writes))
        assert all(b'data:image/' not in body and not any(token in body for token in forbidden) for body in writes)
        # Try the other large layout. Removing a person from a pair leaves one actual face.
        with browser.new_context(**MOBILE) as private:
            private.route('http**://**/*', lambda r:r.abort())
            page = private.new_page()
            page.goto(args.gallery.resolve().as_uri()+'?layout=garden#photos')
            page.locator('#portraitFile').set_input_files(args.pair)
            page.locator('#portraitMode').select_option('group')
            page.locator('#portraitStyle').select_option('seats')
            page.locator('#portraitSubmit').click()
            caption(page,'Group portrait · 2 faces around the table')
            data = analyze_seats(page)
            narrow_order = [s['sourceBox'] for s in data['seats'][::-1]]
            assign_seats(page,narrow_order,np.array(data['sourceSize']))
            small_files = drawing_files(page,'#downloads')
            if page.locator('#seatedReveal').count():
                bed = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.bed")
                report['narrow_seated_drawing'] = check_seated_reveal(page,analyze_seats(page,narrow_order),small_files,
                    references[args.pair],bed,args.evidence/'early-narrow',False)
            page.locator('#layout').select_option('portrait')
            ready(page)
            assert drawing_files(page,'#downloads') == family_files, 'Wide layout lost the family seating order'
            page.locator('#layout').select_option('garden')
            ready(page)
            assert drawing_files(page,'#downloads') == small_files, 'Returning to three zones changed the family seats'
            reveal_toggle = page.locator('#seatedReveal')
            if reveal_toggle.count():
                reveal_toggle.check()
                ready(page)
            source = page.locator('#portraitSource')
            if not source.evaluate('e=>e.open'):
                source.locator(':scope > summary').click()
            page.locator('#faceBoxes button[aria-pressed=true]').last.click()
            expect(page.locator('.caption')).to_have_text('Group portrait · 1 face',timeout=25000)
            expect(page.locator('#portraitStatus')).to_contain_text('original pose')
            expect(page.locator('#seatViews')).to_be_hidden()
            if reveal_toggle.count():
                expect(reveal_toggle).to_be_checked()
                expect(page.locator('#seatedRevealNotice')).to_be_visible()
                expect(page.locator('#middleStageLabel')).to_have_text('Cleared')
            fallback = drawing_files(page,'#downloads')
            page.locator('#portraitStyle').select_option('pose')
            ready(page)
            assert drawing_files(page,'#downloads') == fallback
            if reveal_toggle.count():
                expect(reveal_toggle).not_to_be_checked()
                expect(page.locator('#seatedRevealNotice')).to_be_hidden()
        (args.evidence/'results.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('gallery','pair','cropped','seven'):
        p.add_argument(name,type=Path)
    p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--upgrade-from',type=Path,help='Earlier fitted gallery with seated group portraits.')
    p.add_argument('--evidence',type=Path,required=True)
    args = p.parse_args()
    with sync_playwright() as pw:
        executable = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(executable)) as browser:
            if args.upgrade_from:
                saved_group_upgrade(browser,args)
            run(browser,args)
