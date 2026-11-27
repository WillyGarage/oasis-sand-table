#!/usr/bin/env python3
"""Compare two 8-bit top-down Oasis photos with the same camera, exposure and crop.

    python3 tools/compare_sand_zones.py before.jpg after.jpg --scene layout/scene.json \
        --zone outer --working-radius-px 404 --blank-reference cleared.jpg --out border-check

For a single added subject, use --disc X Y R (all in working radii, +y up).
For one guest change, use --guest-place 1, 2 or 3 with the matching scene.
The separate -chairs.jpg shows registered photographs facing each chair. For an
archived Mini guest drawing, pass web/guest-paths.json as its scene. Mask the
ball in both positions with --exclude-disc if it moved between photographs.
Use the photographed rim-dock ball radius in the top-down view. In the Mini's
900 px November 20 positive-angle dock photos that radius was about 404 px.
The 0.30 threshold came from the physical crescent. A six-level noise floor
limited false detections to under 1% on a uniform fine erase when the ball
moved only on the rim. Both known additions remained detectable. The inputs
are the matched, brightened images from the capture tool. Use --rim-images with
the same frames before brightening if the lightened rim loses its detail. The
score still measures grooves in the brightened photographs. Changes below the
threshold, or inside an excluded area, are unresolved.
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


THRESHOLD = .30
NOISE_FLOOR = 6.


def read(path):
    photo = cv2.imread(str(path))
    if photo is None or photo.shape[0] != photo.shape[1]:
        raise ValueError(f'Expected a square top-down photo at {path}')
    return photo


def gray(photo):
    return cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY).astype(np.float32)


def blur(image, sigma):
    return cv2.GaussianBlur(image, (0, 0), sigma)


def geometry(size, working_radius):
    y, x = np.mgrid[:size, :size]
    return (x-size/2)/working_radius, (size/2-y)/working_radius


def guest_places(scene):
    """Read the places actually used by this drawing. The Mini and ring layouts differ."""
    if 'guest_plan' in scene:
        plan = scene['guest_plan']
        g = plan['geometry']
        return [dict(label=label, angle=a, center=[g['center']*math.cos(a), g['center']*math.sin(a)],
                     radius=g['scale'], rail=g['rail']) for label,a in zip(plan['slots'],g['angles'],strict=True)]
    return scene.get('slots', [])


def guest_mask(x, y, place):
    cx,cy = place['center']
    size = place['radius']
    if 'rail' not in place:
        return np.hypot(x-cx,y-cy) <= size
    # The fitted crescent can reach outside the nominal guest disc. Include the
    # entire reserved sector, from its nearest edge through its hanging groove.
    center = math.hypot(cx,cy)
    angle = np.arctan2(y,x) - place['angle']
    delta = (angle + np.pi) % (2*np.pi) - np.pi
    r = np.hypot(x,y)
    return (abs(delta) <= math.asin(size/center)) & (r >= center-size) & (r <= max(center+size,place['rail']))


def align(before, after, fixed, radius, rim_images=None):
    left, right = (before, after) if rim_images is None else rim_images
    if left.shape != before.shape or right.shape != after.shape:
        raise ValueError('Rim photographs must use the same top-down crop as the sand photographs.')
    a, b = gray(left), gray(right)
    # Only the stationary bowl rim influences this rigid registration. Aligning the decorated
    # sand itself could hide an actual shift of its features.
    try:
        cc, warp = cv2.findTransformECC(a, b, np.eye(2,3,dtype=np.float32), cv2.MOTION_EUCLIDEAN,
            (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 75, 1e-6), fixed.astype(np.uint8)*255, 5)
    except cv2.error as error:
        raise ValueError('Rim registration inconclusive. Use matched frames with a visible stationary rim.') from error
    center = np.array([a.shape[1]/2,a.shape[0]/2])
    xy = warp[:,:2] @ center + warp[:,2] - center
    roll = math.degrees(math.atan2(warp[0,1],warp[0,0]))
    if not (math.isfinite(cc) and np.isfinite(warp).all()) or cc < .85 or np.linalg.norm(xy) > .025*radius or abs(roll) > 1.5:
        raise ValueError(f'Rim registration inconclusive: correlation {cc:.3f}, shift {xy} pixels, roll {roll:.2f} degrees.')
    registered = cv2.warpAffine(after, warp, (a.shape[1],a.shape[0]),
                                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    if rim_images is not None:
        a = gray(before)
    b = gray(registered)
    contrast = np.std(b[fixed]) / max(np.std(a[fixed]), 1)
    return registered, {'translation_px':xy.astype(float).round(3).tolist(), 'roll_degrees':round(roll,3),
                        'rim_correlation':round(cc,4), 'rim_contrast_ratio':round(float(contrast),3),
                        'rim_brightness_change_on_255_scale':round(float(np.median((b-a)[fixed])),2)}


def change_score(before, after, groove_px):
    # Retain groove-scale relief. Remove the gradual brightness gradient across
    # the sand and suppress pixel noise; a genuine flattened groove still changes
    # the signal. The noise floor suppresses the blocky camera compression
    # revealed by brightening photos of the Mini's smooth, dark center.
    def relief(im):
        g = gray(im)
        return blur(g, .08*groove_px) - blur(g, .46*groove_px)
    a,b = relief(before), relief(after)
    return blur((a-b)**2, .32*groove_px)/(blur(a*a+b*b, .32*groove_px) + 2*NOISE_FLOOR**2)


def stats(score, mask, groove_px):
    values = score[mask]
    if len(values) < 100:
        raise ValueError('Zone has too little usable sand.')
    flagged = ((score > THRESHOLD) & mask).astype(np.uint8)
    contours = cv2.findContours(flagged,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
    # A single long stray groove could occupy very little of a large protected zone.
    # Its farthest two flagged pixels lie on its convex hull.
    longest = 0.
    for contour in contours:
        _,_,w,h = cv2.boundingRect(contour)
        if math.hypot(w-1,h-1) <= longest:
            continue
        hull = cv2.convexHull(contour).reshape(-1,2).astype(np.float32)
        differences = hull[:,None,:] - hull[None,:,:]
        longest = max(longest,float(np.sqrt(np.sum(differences**2,axis=2).max())))
    return {'pixels':len(values), 'flagged_pixels':int(flagged.sum()), 'flagged_percent':round(100*float(np.mean(values > THRESHOLD)),2),
            'largest_contiguous_change_in_groove_widths':round(longest/groove_px,2),
            'median_score':round(float(np.median(values)),3), 'p99_score':round(float(np.percentile(values,99)),3)}


def evidence(before, after, score, changed, protected, radius, dock_deg, bounds, output):
    """Context, the largest measured change per zone and a textured reference crop."""
    region = changed | protected
    overlay = after.copy()
    overlay[~region] = np.uint8(.43*overlay[~region])
    for mask,color in [(changed,(40,102,200)),(protected,(150,95,105))]:
        flag = mask & (score > THRESHOLD)
        overlay[flag] = np.uint8(.38*overlay[flag] + .62*np.array(color))
    patch = max(36,round(radius*.26))
    def detail_location(mask, strength):
        m = mask.astype(np.float32)
        count = cv2.boxFilter(m,-1,(patch,patch),normalize=False)
        total = cv2.boxFilter(strength*m,-1,(patch,patch),normalize=False)
        valid = mask & (count > patch*patch*.8)
        if not valid.any():
            valid = mask & (count >= count.max()*.9)
        best = np.where(valid,total/np.maximum(count,1),-1)
        y,x = np.unravel_index(best.argmax(),best.shape)
        return x-patch//2,y-patch//2
    def label(img, text, x, y):
        cv2.putText(img,text,(x,y),cv2.FONT_HERSHEY_SIMPLEX,.55,(48,48,40),1,cv2.LINE_AA)
    texture = (blur(gray(before),1.5) - blur(gray(before),8))**2
    rows = [(detail_location(changed,score),'Most changed crop in the requested zone'),
            (detail_location(protected,score),'Most changed crop in the protected zone'),
            (detail_location(protected,texture),'Strongest original detail in the protected zone')]
    if bounds:
        # Keep the shared boundaries and travel groove visible for inspection,
        # even though we expressly exclude them from the protected-area score.
        def location(r, angle):
            theta = math.radians(angle)
            return (round(len(before)/2+r*radius*math.cos(theta)-patch/2),
                    round(len(before)/2-r*radius*math.sin(theta)-patch/2))
        boundaries = [r for r in bounds if 0 < r < 1]
        if boundaries:
            rows.append((location((max(boundaries)+1)/2,dock_deg),'Access groove toward the dock'))
            for boundary in boundaries:
                rows.append((location(boundary,dock_deg+180),'Shared boundary opposite the dock'))
    sheet = np.full((34+220*len(rows),748,3),(242,245,246),np.uint8)
    for col,((x,y),title) in enumerate(rows):
        color = (40,102,200) if col == 0 else (150,95,105)
        cv2.rectangle(overlay,(x,y),(x+patch,y+patch),color,3)
        label(sheet,title,344,37+220*col)
        for i,(im,name) in enumerate([(before,'Before'),(after,'After')]):
            loc = 344 + 210*i
            crop = im[y:y+patch,x:x+patch]
            sheet[77+220*col:235+220*col,loc:loc+158] = cv2.resize(crop,(158,158),interpolation=cv2.INTER_CUBIC)
            label(sheet,name,loc,67+220*col)
    sheet[63:383,14:334] = cv2.resize(overlay,(320,320),interpolation=cv2.INTER_AREA)
    label(sheet,'Measured groove changes',14,43)
    label(sheet,'Rust shows changes inside the zone',14,416)
    label(sheet,'Purple shows changes outside it',14,443)
    label(sheet,'Dark areas were excluded',14,470)
    if not cv2.imwrite(str(output),sheet):
        raise OSError(f'Could not write {output}')


def chair_sheet(before, after, places, radius, scores, output):
    """Rotate each registered pair as seen by a guest looking in from that seat."""
    side, pad, heading = 256, 12, 38
    sheet = np.full((len(places)*(side+heading+pad),2*side+3*pad,3),244,np.uint8)
    v,u = np.mgrid[:side,:side].astype(np.float32)-(side-1)/2
    for row,(place,report) in enumerate(zip(places,scores,strict=True)):
        a = place['angle']
        cx,cy = place['center']
        # Right follows the rim counterclockwise. The bottom of the image faces the chair.
        scale = 2.55*place['radius']*radius/side
        mx = before.shape[1]/2+cx*radius + scale*(-np.sin(a)*u + np.cos(a)*v)
        my = before.shape[0]/2-cy*radius - scale*( np.cos(a)*u + np.sin(a)*v)
        top = row*(side+heading+pad)
        for col,(frame,title) in enumerate([(before,'Before'),(after,'After')]):
            left = pad+col*(side+pad)
            view = cv2.remap(frame,mx.astype(np.float32),my.astype(np.float32),cv2.INTER_LINEAR)
            sheet[top+heading:top+heading+side,left:left+side] = view
            text = f"Place {row+1} - {title}"
            if col and 'flagged_percent' in report:
                text += f" ({report['flagged_percent']:g}% flagged)"
            cv2.putText(sheet,text,(left,top+25),cv2.FONT_HERSHEY_SIMPLEX,.5,(54,50,44),1,cv2.LINE_AA)
    if not cv2.imwrite(str(output),sheet):
        raise OSError(f'Could not write {output}')


def compare(before, after, radius, groove, dock_deg, disc=None, bounds=None, exclude=(), blank=None, rim_images=None,
            *, places=(), guest=None, zones=None, has_stem=True, rim_annulus=(1.015,1.072)):
    if before.shape != after.shape:
        raise ValueError('Camera crops have different dimensions.')
    if not (math.isfinite(radius) and radius > 0 and math.isfinite(groove) and groove > 0):
        raise ValueError('The working radius and groove width must be positive finite numbers.')
    x,y = geometry(len(before),radius)
    r = np.hypot(x,y)
    a = math.radians(dock_deg)
    along, across = x*math.cos(a)+y*math.sin(a), y*math.cos(a)-x*math.sin(a)
    dock = np.hypot(along-1,across) < max(.12,2.5*groove)
    clear = ~dock
    for cx,cy,rad in exclude:
        clear &= np.hypot(x-cx,y-cy) > rad
    # topdown_true blacks out a circle at 47.75% of the full width with a soft
    # edge. That synthetic circle cannot tell whether the actual bowl moved.
    inner_rim, outer_rim = rim_annulus
    if not (1 <= inner_rim < outer_rim and math.isfinite(outer_rim)):
        raise ValueError('Choose a stationary rim strip outside the working sand.')
    fixed = (r > inner_rim) & (r < outer_rim) & (r*radius < len(before)*.47) & clear
    if fixed.sum() < 100:
        raise ValueError('Too little stationary rim is visible in this crop.')
    aligned, registration = align(before, after, fixed, radius, rim_images)
    score = change_score(before,aligned,radius*groove)
    # The ordinary bowl crop omits the lip. Only the concentric garden has
    # a permanent stem between its center and dock.
    travel = has_stem & (along >= 0) & (np.abs(across) < 1.5*groove)
    valid = (r < .94) & clear & ~travel
    masks = [guest_mask(x,y,p) & valid for p in places]
    adjacent = {}
    for name in ('center','outer'):
        if zones and name in zones:
            lo,hi = zones[name]['bounds']
            adjacent[name] = valid & ((lo == 0) | (r > lo+groove)) & (r < hi-groove)
    if guest is not None:
        changed = masks[guest].copy()
        protected = np.zeros_like(valid)
        for i,mask in enumerate(masks):
            if i != guest:
                protected |= mask
        for mask in adjacent.values():
            protected |= mask
    elif disc is not None:
        cx,cy,rad = disc
        distance = np.hypot(x-cx,y-cy)
        changed = distance <= rad
        protected = distance > rad + 1.5*groove
    else:
        low,high = bounds
        gap = groove
        changed = (r < high-gap) & ((low == 0) | (r > low+gap))
        protected = (r < low-gap) | (r > high+gap)
    changed &= valid
    protected &= valid
    result = {'registration':registration, 'rim_annulus':list(rim_annulus), 'score_threshold':THRESHOLD,
        'noise_floor_on_255_scale':NOISE_FLOOR, 'excluded_discs':exclude,
        'working_radius_px':radius,'groove_px':round(groove*radius,2), 'dock_degrees':dock_deg,
        'requested':stats(score,changed,groove*radius),'protected':stats(score,protected,groove*radius)}
    if places:
        def measured(mask):
            return stats(score,mask,groove*radius) if mask.sum() >= 100 else {
                'pixels':int(mask.sum()),'status':'Too little visible sand.'}
        result['guest_places'] = [dict(place=i+1,label=p['label'],**measured(mask))
                                  for i,(p,mask) in enumerate(zip(places,masks,strict=True))]
        result['adjacent_zones'] = {name:measured(mask) for name,mask in adjacent.items()}
    if bounds:
        # Reworking the strip between two zones can leave a visible circular
        # frame even when every protected figure survives. Measure it separately.
        boundaries = [boundary for boundary in bounds if 0 < boundary < 1]
        result['shared_boundaries'] = []
        for boundary in boundaries:
            strip = valid & (np.abs(r-boundary) < groove/2)
            if strip.sum() >= 100:
                result['shared_boundaries'].append({'radius':boundary, **stats(score,strip,groove*radius)})
        if boundaries:
            access = clear & travel & (r > max(boundaries)+groove) & (r < .94)
            if access.sum() >= 100:
                result['access_strip_outside_divider'] = stats(score,access,groove*radius)
    if blank is not None:
        if blank.shape != before.shape:
            raise ValueError('Blank reference has a different camera crop.')
        empty,registration = align(before,blank,fixed,radius)
        # Score the known artwork as well as the entire protected region. A
        # damaged line can cover very little of the total surrounding sand.
        original_detail = change_score(before,empty,radius*groove) > THRESHOLD
        original = protected & original_detail
        result['blank_registration'] = registration
        result['visible_original_detail_in_protected_area'] = (stats(score,original,groove*radius)
            if original.sum() >= 100 else {'pixels':int(original.sum())})
        if places:
            for report,mask in zip(result['guest_places'],masks,strict=True):
                report['visible_original_detail'] = measured(mask & original_detail)
    return aligned,score,changed,protected,result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('before',type=Path)
    parser.add_argument('after',type=Path)
    parser.add_argument('--scene',type=Path,help='ring_scene.py manifest for bounds, groove width and dock')
    parser.add_argument('--blank-reference',type=Path,help='matched photograph of the cleared sand before setup')
    parser.add_argument('--rim-images', type=Path, nargs=2, metavar=('BEFORE','AFTER'),
                        help='unbrightened copies in the same top-down crop, for aligning an overexposed rim')
    parser.add_argument('--rim-annulus',type=float,nargs=2,default=(1.015,1.072),metavar=('INNER','OUTER'),
                        help='stationary bowl rim used for alignment, in working radii')
    subjects = parser.add_mutually_exclusive_group(required=True)
    subjects.add_argument('--zone',choices=['center','middle','outer'])
    subjects.add_argument('--guest-place',type=int,choices=(1,2,3),
                          help='receiving place, numbered from 1 in the matching --scene or Mini guest catalog')
    subjects.add_argument('--disc',type=float,nargs=3,metavar=('X','Y','R'))
    parser.add_argument('--working-radius-px','--radius-px',type=float,required=True,
                        help='observed rim-dock ball distance from the center, in top-down image pixels')
    parser.add_argument('--groove',type=float,help='groove width in working radii, default .044')
    parser.add_argument('--dock-deg',type=float,help='paper angle, positive up from right; default 90 for moon/star')
    parser.add_argument('--exclude-disc',type=float,nargs=3,action='append',default=[],metavar=('X','Y','R'),
                        help='extra moving ball, shadow, or other known occlusion')
    parser.add_argument('--out',type=Path,required=True,help='output stem for .json and .jpg')
    args = parser.parse_args()
    before,after = read(args.before),read(args.after)
    scene = json.loads(args.scene.read_text()) if args.scene else {}
    places = guest_places(scene)
    if args.zone and args.zone not in scene.get('zones',{}):
        parser.error('--zone requires its matching --scene manifest')
    if args.guest_place and args.guest_place > len(places):
        parser.error('--guest-place requires a matching scene with guest places')
    groove = args.groove if args.groove is not None else scene.get('groove_width',.044)
    radius = args.working_radius_px
    dock = args.dock_deg if args.dock_deg is not None else math.degrees(scene.get('dock',[math.pi/2])[0])
    band = args.zone or ('middle' if args.guest_place and 'guest_plan' in scene else None)
    bounds = scene['zones'][band]['bounds'] if band else None
    blank = read(args.blank_reference) if args.blank_reference else None
    rim_images = [read(path) for path in args.rim_images] if args.rim_images else None
    after,score,changed,protected,result = compare(before,after,radius,groove,dock,args.disc,bounds,args.exclude_disc,blank,rim_images,
        places=places,guest=args.guest_place-1 if args.guest_place else None,zones=scene.get('zones'),
        has_stem='slots' not in scene,rim_annulus=args.rim_annulus)
    if rim_images is not None:
        result['rim_images'] = [path.name for path in args.rim_images]
    if args.blank_reference:
        result['blank_reference'] = args.blank_reference.name
    result.update(before=args.before.name,after=args.after.name,zone=args.zone,disc=args.disc,bounds=bounds)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    evidence(before,after,score,changed,protected,radius,dock,bounds,args.out.with_suffix('.jpg'))
    if places:
        result['guest_place'] = args.guest_place
        chairs = args.out.with_name(args.out.stem+'-chairs.jpg')
        chair_sheet(before,after,places,radius,result['guest_places'],chairs)
        result['chair_photos'] = chairs.name
    output = json.dumps(result,indent=2)
    args.out.with_suffix('.json').write_text(output+'\n')
    print(output)
