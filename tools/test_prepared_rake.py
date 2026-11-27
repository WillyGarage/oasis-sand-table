"""Check a wide portrait's single-pass clear, the phone fallback and independent room proof.

python3 tools/test_prepared_rake.py GARDEN.html PRINT.oasisportrait
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from garden_room import Layout, validate_motion
from test_ring_guest_border import MOBILE
from wide_portrait import chromium, evaluate_geometry


def must_reject(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError('The room accepted an incomplete clearing pass.')


def exercise(page, gallery, drawing):
    page.goto(gallery.resolve().as_uri()+'?layout=garden#prepared-portrait')
    data=json.loads(drawing.read_text())
    assert data['includesCenterRake'] is True
    layout=Layout(json.loads(page.locator('#scene').text_content()))
    paths=evaluate_geometry(page, """d=>{
      const geometry=JSON.parse(document.getElementById('scene').textContent).live,z=geometry.wideCenter;
      const planner=OasisRingPlanner;
      // This still looks like a print, but the innermost 40% is untouched.
      const gap=d.points.map(([x,y])=>{
        const r=Math.hypot(x,y);
        return r<.4 ? r<1e-8 ? [0,-.4] : [x*.4/r,y*.4/r] : [x,y];
      });
      const valid=planner.preparedPhoto(z,d.points,geometry,true), ordinary=planner.photo(z,gap);
      const fallback=planner.preparedPhoto(z,gap,geometry,true);
      const unrequested=planner.preparedPhoto(z,d.points,geometry,false);
      const standard=planner.photo(z,d.points);
      const different=planner.preparedPhoto(z,d.points,{...geometry,groove:geometry.groove*.92},true);
      if (!valid.includesCenterRake || fallback.includesCenterRake || different.includesCenterRake ||
          JSON.stringify(ordinary.path)!==JSON.stringify(fallback.path) ||
          JSON.stringify(standard.path)!==JSON.stringify(unrequested.path)) throw Error('Incorrect clearing decision.');
      const unchecked=planner.join([z.transit,ordinary.art,z.transit.slice().reverse()]);
      return {gap,valid:planner.files(valid.path,'portrait'),incomplete:planner.files(unchecked,'portrait')};
    }""",data)
    motion={'zone':'center','centerMode':'widePortrait','includesCenterRake':True,'files':paths['valid']}
    validate_motion(motion,layout)
    layout.check_route('center',paths['valid'],center_mode='widePortrait',state=layout.initial,includes_center_rake=True)
    must_reject(lambda: layout.check_route('center',paths['incomplete'],center_mode='widePortrait',
                                            state=layout.initial,includes_center_rake=True))
    must_reject(lambda: validate_motion({**motion,'centerMode':'restoreGuests'},layout))
    must_reject(lambda: validate_motion({**motion,'includesCenterRake':1},layout))

    page.locator('#portraitArea').select_option('wide')
    file_field=page.locator('#portraitFile')
    for points,message in [(data['points'],'clears and draws the center in one pass'),
                           (paths['gap'],'center will be cleared before this portrait')]:
        file_field.set_input_files({'name':'print.oasisportrait','mimeType':'application/json',
                                    'buffer':json.dumps({**data,'points':points}).encode()})
        page.locator('#portraitSubmit').click()
        expect(page.locator('#portraitStatus')).to_contain_text(message,timeout=15000)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('drawing',type=Path)
    args=parser.parse_args()
    with sync_playwright() as pw,pw.chromium.launch(executable_path=chromium(pw,None)) as browser:
        exercise(browser.new_page(offline=True,**MOBILE),args.gallery,args.drawing)
    print('Single-pass clear and independent room validation passed. The phone restored the regular erase for a gap.')
