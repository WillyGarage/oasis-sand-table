#!/usr/bin/env python3
"""Exercise names under center portraits on two local phones using private source files."""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, choose, drawing_files, open_room, room
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_object_photo import PhoneTraffic, expand
from test_ring_photo import check_portrait, frame, ordinary_erase_pitch
from test_ring_shadows import ready


def preview(page):
    page.locator('#portraitSubmit').click()
    ready(page)


def exercise(browser, gallery, source, group, output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, room(gallery, Path(tmp)/'room.db') as url, \
            browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as peer:
        traffic = PhoneTraffic(url)
        for page in [host, peer]:
            page.route('**/*', traffic.check)
        open_room(host, url)
        choose(host, 'zone', 'center')
        expand(host, '#centerPhoto')
        area, name = ('wide', 'Bill and Lek') if group else ('center', 'Lek')
        host.locator('#portraitArea').select_option(area)
        host.locator('#portraitFile').set_input_files(traffic.photo(source.name, source.read_bytes(), 'image/jpeg'))
        if group:
            host.locator('#portraitMode').select_option('group')
            host.locator('#portraitStyle').select_option('faces')
        preview(host)
        before = frame(host)
        plain = drawing_files(host, '#downloads')
        caption = host.locator('#photoCaption')
        # Editing the caption invalidates the previously shown movement. Removing
        # it must reproduce the unlettered files exactly, including file splits.
        caption.fill(name)
        expect(host.locator('#keep')).to_be_hidden()
        caption.fill('')
        preview(host)
        assert drawing_files(host, '#downloads') == plain

        if group:
            host.locator('#portraitArea').select_option('center')
            caption.fill('Bill and Lek')
            host.locator('#portraitSubmit').click()
            expect(host.locator('#portraitStatus')).to_contain_text('wider center')
            expect(host.locator('#keep')).to_be_hidden()
            host.locator('#portraitArea').select_option('wide')
        caption.fill(name)
        preview(host)
        expect(host.locator('#portraitStatus')).to_contain_text('“'+name+'”')
        after = frame(host)
        files = drawing_files(host, '#downloads')
        assert files != plain
        details = host.evaluate("""async ([group,name])=>{
          const s=JSON.parse(document.querySelector('#scene').textContent), live=s.live;
          const z=group ? live.wideCenter : s.zones.center, r=z.transit.at(-1)[1], g=live.groove;
          const res=await GuestPhoto.fromFile(document.querySelector('#portraitFile').files[0],{
            group,groupStyle:group?'faces':'pose',portraitFraming:group?undefined:'framedHead',portraitStyle:'line',portraitDiameterMm:2*r*live.radiusMM,
            portraitDiameterGrooves:2*r/g,portraitTrackingGrooves:live.trackingMarginMM/(g*live.radiusMM)});
          const art=await GuestPortraitCaption.fit(res.points,name,g/r);
          return {art,raw:res.points,segments:OasisRingPlanner.photo(z,art.points).segments,
            radius:r,R:live.radiusMM,groove:g,clear:z.erase};
        }""", [group, name])
        art = details['art']
        path = from_files(files, details['segments'][0][0])
        # Examine the points on the real download in order, including every
        # connector, then independently compare all face vertices and the gap.
        error = check_portrait(art['points'], details['segments'], path, details['groove'],
                               ordinary_erase_pitch(details['clear']), True)
        mm = details['radius'] * details['R']
        face = np.array(art['portrait'])
        delta = face - art['scale'] * np.array(details['raw'][1:-1])
        np.testing.assert_allclose(delta, np.broadcast_to(delta[0], delta.shape), atol=1e-11)
        assert abs(delta[0, 0]) < 1e-11 and .75 <= art['scale'] <= 1
        text = np.array(art['caption'])
        gap = (face[:, 1].min() - text[:, 1].max()) * mm
        groove = details['groove'] * details['R']
        assert gap >= 1.74 * groove and art['letterGrooves'] >= 4.2

        h, w = before.shape[:2]
        y, x = np.mgrid[-1:1:complex(h), -1:1:complex(w)]
        safe = (np.hypot(x,y) > details['radius']+2*details['groove']) & (np.hypot(x,y)<.97)
        assert safe.sum()>50000
        np.testing.assert_array_equal(before[safe], after[safe])
        host.locator('#sand').screenshot(path=str(output/'sand.png'))
        Image.fromarray(before).save(output/'without.jpg', quality=95)
        Image.fromarray(after).save(output/'with.jpg', quality=95)
        for i, (_, data) in enumerate(files, 1):
            (output/f'{i}.thr').write_bytes(data)
        kept, _ = save(host, url+API)
        assert name in kept['state']['portrait']
        open_room(peer, url, 'photos')
        choose(peer, 'zone', 'center')
        assert drawing_files(peer, '#roomFiles') == files
        assert not traffic.violations
        return dict(name=name, portrait_scale=art['scale'], letter_height_mm=round(art['letterGrooves']*groove,1),
                    clearance_mm=round(gap,1), protected_pixels=int(safe.sum()),
                    max_path_deviation_mm=round(error*details['R'],3), downloaded_parts=len(files))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('solo', type=Path)
    parser.add_argument('pair', type=Path)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        output = args.evidence or Path(tmp)
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report = [exercise(browser, args.gallery, photo, group, output/key)
                      for photo, group, key in [(args.solo,False,'solo'),(args.pair,True,'family')]]
        (output/'results.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
