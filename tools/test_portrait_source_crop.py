#!/usr/bin/env python3
"""Check full-resolution face selection in a local gallery using Bill's private family sources.

    python3 tools/test_portrait_source_crop.py GALLERY.html --family captures/family-source
"""
import argparse
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from PIL import Image, ImageOps
from playwright.sync_api import expect, sync_playwright

from test_ring_object_photo import expand
from test_ring_shadows import ready


# Independent manual squares on the original 2000 x 1500 family photos.
# Each record also gives the top-left position of that entire photo in the panorama.
PEOPLE = {'Thomas': ((1382, 463, 400), (100, 45)),
          'Lek': ((633, 658, 372), (2200, 65)),
          'Alex': ((1382, 416, 474), (4300, 30))}


def make_pictures(family, tmp):
    panorama = Image.new('RGB', (6400, 1600), (88, 88, 88))
    crops, boxes = {}, {}
    for name, ((x, y, w), (px, py)) in PEOPLE.items():
        with Image.open(family/(name.lower()+'.jpg')) as source:
            assert source.size == (2000, 1500), f'Expected the original camera photo of {name}'
            image = source.convert('RGB')
        panorama.paste(image, (px, py))
        left, top = max(0, x-420), max(0, y-420)
        crop = image.crop((left, top, left+840, top+840))
        assert crop.tobytes() == panorama.crop((px+left, py+top, px+left+840, py+top+840)).tobytes()
        filename = tmp/(name+'.png')
        crop.save(filename, compress_level=2)
        crops[name] = (filename, (x-left, y-top, w))
        boxes[name] = (x+px, y+py, w)
    filename = tmp/'panorama.png'
    panorama.save(filename, compress_level=2)
    return filename, boxes, crops


def inspect(page, file, expected_size):
    field = page.locator('#portraitFile')
    field.set_input_files(file)
    scan = field.evaluate('el=>GuestPhoto.inspectSeatPhoto(el.files[0])')
    assert (scan['sourceWidth'], scan['sourceHeight']) == expected_size
    return scan


def draw(page, scan, choice, expected_box):
    result = page.locator('#portraitFile').evaluate("""async (el,face)=>{
      const r=await GuestPhoto.fromFile(el.files[0],{face,portraitFraming:'head',
        portraitDiameterGrooves:16.34,portraitTrackingGrooves:.5});
      return {points:r.points.slice(1,-1),hasFace:r.hasPortrait,boxes:r.faceBoxes,
        selected:r.includedFaces,width:r.sourceWidth,height:r.sourceHeight};
    }""", choice)
    assert result['hasFace'] and len(result['points']) > 20
    assert [result['width'], result['height']] == [scan['sourceWidth'], scan['sourceHeight']]
    assert result['boxes'] == scan['detectedFaces'] and result['selected'] == [expected_box]
    return result['points']


def select_face(page, scan, native, scale):
    # Match a detector result against a hand-marked head in the overview, then
    # select that box by its ordinary picker index and by an independent manual box.
    x, y, w = (n*scale for n in native)
    boxes = scan['detectedFaces']
    matches = [(i,b) for i,b in enumerate(boxes)
               if math.hypot(b['x']-x, b['y']-y)<.38*w and .55 < b['w']/w < 1.8]
    assert len(matches) == 1, (native, matches)
    index, automatic = matches[0]
    draw(page, scan, index, automatic)
    manual = dict(x=x, y=y, w=w)
    return index, draw(page, scan, manual, manual)


def painted(points):
    # The checked guest place is 114.38 mm across. Sample the 7 mm groove
    # footprint at 8 pixels/mm, at its drawn position without image registration.
    ink = np.zeros((1024, 1024), np.uint8)
    xy = np.asarray(points)*[8*57.19, -8*57.19] + 512
    cv2.polylines(ink, [np.rint(xy).astype(np.int32)], False, 255, 1)
    return cv2.distanceTransform(255-ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)/8


def check_close_group(page, native_boxes):
    """Compare the ordinary file route with the same manual boxes on the original camera pixels."""
    pairs = page.locator('#portraitFile').evaluate("""async (el, selected)=>{
      const file=el.files[0], source=await createImageBitmap(file);
      const canvas=document.createElement('canvas');
      canvas.width=source.width; canvas.height=source.height;
      const ctx=canvas.getContext('2d');
      ctx.drawImage(source,0,0); source.close();
      const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
      const info=await GuestPhoto.inspectSeatPhoto(file);
      const sx=info.sourceWidth/canvas.width, sy=info.sourceHeight/canvas.height;
      const native=selected.map(([x,y,w])=>({x,y,w}));
      const overview=native.map(({x,y,w})=>({x:x*sx,y:y*sy,w:w*sx}));
      const pairs=[];
      for (const diameter of [90.4,41.2]) {
        const options={group:true,groupStyle:'faces',portraitDiameterGrooves:diameter,portraitTrackingGrooves:.5};
        const actual=await GuestPhoto.fromFile(file,{...options,groupFaces:overview});
        const expected=await GuestPhoto.fromPixels(pixels,{...options,groupFaces:native},{boxes:native});
        if (JSON.stringify(actual.includedFaces)!==JSON.stringify(overview)) throw Error('Group picker moved');
        pairs.push([diameter,actual.points.slice(1,-1),expected.points.slice(1,-1)]);
      }
      return pairs;
    }""", list(native_boxes))
    for diameter, actual, expected in pairs:
        pixels_per_mm = 3
        radius = diameter*7/2
        size = math.ceil(2*radius*pixels_per_mm+50)
        def footprint(points):
            route = np.zeros((size,size), np.uint8)
            xy = np.asarray(points)*[radius*pixels_per_mm,-radius*pixels_per_mm]+size/2
            cv2.polylines(route,[np.rint(xy).astype(np.int32)],False,255,1)
            return cv2.distanceTransform(255-route,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)/pixels_per_mm
        a, b = footprint(actual), footprint(expected)
        union = (a<=3.5)|(b<=3.5)
        overlap = ((a<=3.5)&(b<=3.5)).sum()/union.sum()
        distance = np.percentile(np.r_[a[b==0],b[a==0]],95)
        assert overlap >= .96 and distance <= .8, (diameter, overlap, distance)


def check_mirrored_photos(page, family, tmp):
    for name in ('Thomas','Lek'):
        source_box = PEOPLE[name][0]
        with Image.open(family/(name.lower()+'.jpg')) as source:
            mirror = ImageOps.mirror(source)
        path = tmp/(name+'-selfie.jpg')
        mirror.save(path, quality=94)
        scan = inspect(page,path,(1000,750))
        assert scan['facesDetected'] == 1, (name,scan)
        x,y,w = source_box
        manual = (mirror.width-x,y,w)
        idx, reference = select_face(page,scan,manual,.5)
        auto = painted(draw(page,scan,idx,scan['detectedFaces'][idx])) <= 3.5
        ink = painted(reference) <= 3.5
        overlap = (auto&ink).sum()/(auto|ink).sum()
        print(f'{name} selfie: one face, {overlap:.1%} overlap with its hand-framed drawing.')
        assert overlap > .65, (name,overlap)

    # Keep the left face at the mirrored selfie scale and place a second
    # guest in the other half. A successful first match must not hide either.
    with Image.open(tmp/'Thomas-selfie.jpg') as group, Image.open(family/'alex.jpg') as alex:
        group.paste(alex.crop((850,0,1850,1470)),(1000,0))
        path = tmp/'two-guests.png'
        group.save(path)
    scan = inspect(page,path,(1000,750))
    assert scan['facesDetected'] == 2, scan
    select_face(page,scan,(618,463,400),.5)
    select_face(page,scan,(1532,416,474),.5)


def check_gallery(page, gallery, family, tmp):
    path, boxes, crops = make_pictures(family, tmp)
    page.goto(gallery.resolve().as_uri()+'#photos')
    page.locator('#portraitFile').set_input_files(family/'alex.jpg')
    page.locator('#portraitSubmit').click()
    ready(page)  # The normal photo form loaded the models and the public converter.
    scan = inspect(page, path, (1000, 250))
    assert scan['facesDetected'] == 3
    page.locator('#portraitMode').select_option('group')
    page.locator('#portraitStyle').select_option('faces')
    page.locator('#portraitSubmit').click()
    ready(page)
    expand(page, '#portraitSource')
    selected = page.locator('#faceBoxes button[aria-pressed=true]')
    expect(selected).to_have_count(3)
    for i, box in enumerate(scan['detectedFaces']):
        target = selected.nth(i)
        fractions = target.evaluate("b=>['left','top','width','height'].map(k=>parseFloat(b.style[k])/100)")
        x, y, w = (box[k] for k in ('x','y','w'))
        np.testing.assert_allclose(fractions, [(x-w/2)/1000,(y-w/2)/250,w/1000,w/250], atol=1e-5)
    selected.first.click()
    expect(selected).to_have_count(2)
    automatic, manual = {}, {}
    for name, box in boxes.items():
        automatic[name], manual[name] = select_face(page, scan, box, 1000/6400)
    assert len(set(automatic.values())) == 3
    alex_index = automatic['Alex']
    automatic_alex = painted(draw(page,scan,alex_index,scan['detectedFaces'][alex_index])) <= 3.5
    group_boxes = [scan['detectedFaces'][automatic[name]] for name in ('Thomas', 'Alex')]
    for selection in (None, group_boxes):
        group = page.locator('#portraitFile').evaluate("""async (el,groupFaces)=>{
          const r=await GuestPhoto.fromFile(el.files[0],{group:true,groupStyle:'faces',groupFaces,
            portraitDiameterGrooves:75,portraitTrackingGrooves:.5});
          return [r.sourceWidth,r.sourceHeight,r.facesDetected,r.includedFaces,r.faceBoxes];
        }""", selection)
        expected = scan['detectedFaces'] if selection is None else selection
        assert group == [1000, 250, len(expected), expected, scan['detectedFaces']]
    check_close_group(page, boxes.values())
    for name, (file, native) in crops.items():
        scan = inspect(page, file, (840, 840))
        box = dict(zip(('x','y','w'), native))
        candidate = painted(manual[name])
        reference = painted(draw(page, scan, box, box))
        a, b = candidate <= 3.5, reference <= 3.5
        overlap = (a&b).sum()/(a|b).sum()
        p95 = np.percentile(np.r_[candidate[reference==0], reference[candidate==0]], 95)
        # Measured overlaps were 92.4–95.4% and p95 errors were 0.40–0.79 mm.
        # The global-downsample version overlapped only 53.0–62.5%.
        assert overlap >= .91 and p95 <= 1., (name, overlap, p95)
        print(f'{name}: {overlap:.1%} groove overlap, {p95:.2f} mm at the 95th percentile.')
        if name == 'Alex':
            # The first overview scan placed an 87px window around a 74px face.
            # On its own that automatic selection gave only 39% groove overlap.
            automatic_overlap = (automatic_alex & b).sum()/(automatic_alex | b).sum()
            assert automatic_overlap > .70, automatic_overlap
    for name, (box, _) in PEOPLE.items():
        scan = inspect(page, family/(name.lower()+'.jpg'), (1000, 750))
        if name == 'Thomas':
            assert scan['facesDetected'] == 1, 'The bottom-right patch was offered as another face.'
        select_face(page, scan, box, .5)
    pair = inspect(page, family/'bill-with-lek.jpg', (1000, 750))
    for box in [(452,718,499), (1286,426,682)]:
        select_face(page, pair, box, .5)

    # Separate the two people in the same source frame and put Thomas between
    # them. Changing their position relative to the overview pixel grid used to
    # make the detector miss Thomas and the tilted face on the right.
    panorama = Image.new('RGB',(6400,1600),(88,88,88))
    with Image.open(family/'bill-with-lek.jpg') as couple, Image.open(family/'thomas.jpg') as thomas:
        panorama.paste(couple.crop((0,0,825,1500)),(180,50))
        panorama.paste(thomas,(1530,45))
        panorama.paste(couple.crop((825,0,2000,1500)),(4630,70))
    path = tmp/'separated.png'
    panorama.save(path,compress_level=2)
    scan = inspect(page,path,(1000,250))
    assert scan['facesDetected'] == 3, scan
    separated_boxes = [(632,768,499),(2912,508,400),(5091,496,682)]
    for box in separated_boxes:
        select_face(page,scan,box,1000/6400)
    check_close_group(page,separated_boxes)
    check_mirrored_photos(page,family,tmp)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('--family', required=True, type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            page = browser.new_page(offline=True)
            check_gallery(page, args.gallery, args.family, Path(tmp))
