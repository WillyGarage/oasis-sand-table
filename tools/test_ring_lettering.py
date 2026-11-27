#!/usr/bin/env python3
"""Exercise typed guest lettering, including two concurrent phones, and replay the signed downloads.

    python3 tools/test_ring_lettering.py captures/guest-lettering/gallery.html --evidence captures/guest-lettering/proof

Use a three-zone gallery built with open guest places. The local room has no table or external connection.
"""

import argparse
import json
import math
from pathlib import Path
import re
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_concurrent_guests import as_file_payload, barrier, check_bed, watch_saves
from test_garden_room import API, caption, choose, drawing_files, keep, open_room, room, suggest
from test_guest_place import contour_samples, evidence, physical_parts, unpack
from guest_fill_checks import checked_fill, original_excursion
from test_open_guests import verify_download
from test_ring_guest_border import MOBILE, from_files, save
from test_ring_object_photo import capture_stages
from test_ring_photo import frame

GUESTS = ('Thomas', 'Alex', 'Lek')


def seat_view(image, geom, slot):
    angle, reach = geom['angles'][slot], geom['scale']
    radial = np.array([math.cos(angle), math.sin(angle)])
    center = geom['center'] * radial
    # The guest's right follows the ribbon counterclockwise. Looking inward is up.
    right = np.array([-radial[1], radial[0]]) * [1,-1]
    down = radial * [1,-1]
    size = 360
    half = (len(image)-1)/2
    origin = half*(1+center*[1,-1])
    reach *= 1.22
    origin -= half*reach*(right+down)
    a,b = half*2*reach/size * np.column_stack((right,down))
    return Image.fromarray(image).transform((size,size), Image.Transform.AFFINE,
        (a[0],a[1],origin[0],b[0],b[1],origin[1]), resample=Image.Resampling.BICUBIC)


def inspect_letters(page, live, text, slot, files, frames, old, proposed, folder):
    catalog = live['planner']
    geom = catalog['geometry']
    new_id = proposed['ids'][slot]
    thai = any('\u0e00' <= c <= '\u0e7f' for c in text)
    layout = page.evaluate(
        "([text,groove,thai])=>(thai ? GuestThaiLettering : GuestLettering).design(text,{groove})",
        [text,catalog['pairGroove'],thai])
    np.testing.assert_allclose(proposed['custom'][new_id], layout['path'], rtol=0, atol=1e-8)
    assert proposed['labels'][new_id] == f'“{text}”'
    assert layout['legible'] and layout['xHeightGrooves'] >= layout['minimumGrooves']
    assert ''.join(layout['lines']).replace(' ','') == text.replace(' ','')
    tile = catalog['places'][slot]
    route = from_files(files, unpack(catalog['transit'])[0])
    if old['ids'][slot] == catalog['openSubject']:
        replay_report = verify_download(page, folder, old, proposed, slot, files, frames, live, True)
        _, art, _ = checked_fill(route, catalog, slot, original_excursion(page, catalog, proposed, slot))
    else:
        replay_report = evidence(page, folder, old, proposed, frames, files, catalog, slot, live)
        art = physical_parts(route, tile, catalog)[2][len(unpack(tile['recut']))-1:]
    assert geom['faceEdge']
    g = live['groove']
    angle = geom['angles'][slot]
    radial = np.array([math.cos(angle),math.sin(angle)])
    centered = check.sample_walk(art, g/32) - geom['center']*radial
    viewer = np.column_stack((centered @ [-radial[1],radial[0]], -centered @ radial))/geom['scale']
    engraved = cKDTree(viewer)
    rows = {}
    # Thai strokes are shaped as a whole word, including the marks above and below the letters.
    word = contour_samples(np.asarray(layout['path']), catalog['pairGroove']/24)
    max_error = float(engraved.query(word)[0].max()/catalog['pairGroove'])
    assert max_error < .15, ('Missing signed lettering at the nearest seat', text, max_error)
    for glyph in layout.get('glyphs', []):
        if glyph['char'] == ' ':
            continue
        for stroke in glyph.get('strokes', [glyph['points']]):
            samples = contour_samples(np.asarray(stroke), catalog['pairGroove']/24)
            error = float(engraved.query(samples)[0].max()/catalog['pairGroove'])
            assert error < .15, ('Missing signed stroke at the nearest seat', text, glyph['char'], error)
            max_error = max(max_error, error)
        rows.setdefault(glyph['line'], []).append(glyph)
    row_heights = []
    if not thai:
        assert list(rows) == list(range(len(layout['lines'])))
    for row, glyphs in rows.items():
        line = layout['lines'][row]
        assert ''.join(g['char'] for g in glyphs) == line.replace(' ','')
        bounds = np.asarray([g['bounds'] for g in glyphs])
        assert np.all(np.diff(bounds[:,[0,2]].mean(axis=1)) > 0), 'Letters reversed at the guest’s seat'
        row_heights.append(bounds[:,[1,3]].mean())
    assert np.all(np.diff(row_heights) < 0), 'Lines inverted at the guest’s seat'
    seat_view(frames[-1],geom,slot).save(folder/'from-guest-seat.png')
    return {'guest':GUESTS[slot], 'text':text, 'lines':layout['lines'],
            'x_height_grooves':round(layout['xHeightGrooves'],2), 'missing_stroke_distance_grooves':round(max_error,4),
            'replay':replay_report}


def preview_text(page, slot, text, request):
    suggest(page,request)
    caption(page, GUESTS[slot]+f' · “{text}”')
    expect(page.locator('input[name=zone][value=middle]')).to_be_checked()
    assert not page.locator('#sketch').evaluate('e=>e.open')
    return drawing_files(page,'#downloads'), capture_stages(page)


def rejected(page, request, guidance):
    page.locator('#idea').fill(request)
    page.get_by_role('button',name='Preview suggestion').click()
    expect(page.locator('#error')).to_contain_text(re.compile(guidance,re.I))
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#downloads')).to_be_hidden()
    assert not page.locator('#sketch').evaluate('e=>e.open')


def cancel_slow_thai(page, api):
    # Hold the real conversion result in the browser until after a second user action.
    # Running the actual converter keeps both its successful and rejected promises in play.
    pause_next = """() => {
      const convert = GuestThaiLettering.design;
      window.releaseWord = null;
      GuestThaiLettering.design = async (...args) => {
        GuestThaiLettering.design = convert;
        try { return await convert(...args); }
        finally { await new Promise(done => { window.releaseWord = done; }); }
      };
    }"""
    visible_editor = """() => {
      const at = id => document.getElementById(id);
      return [document.querySelector('.caption').textContent, at('idea').value, at('target').value,
        document.querySelector('input[name=zone]:checked').value,
        document.querySelector('input[name=stage]:checked').value, at('error').textContent,
        at('keep').hidden, at('downloads').hidden, at('sketch').open];
    }"""
    original = page.request.get(api).json()
    idea = page.locator('#idea')
    submit = page.get_by_role('button',name='Preview suggestion')
    for action in ('typing', 'target', 'zone', 'submit', 'invalid'):
        page.locator('#target').select_option('')
        page.evaluate(pause_next)
        word = '่' if action == 'invalid' else 'ปู'
        idea.fill(f'write “{word}” for Lek')
        submit.click()
        page.wait_for_function("typeof window.releaseWord === 'function'")
        if action in ('typing','invalid'):
            idea.fill('write “Hi” for Thomas')
        elif action == 'target':
            page.locator('#target').select_option('1')
        elif action == 'zone':
            choose(page,'zone','outer')
            choose(page,'zone','middle')
        else:
            # Autofill can replace a value without sending input. Submitting alone must invalidate the first word.
            idea.evaluate('(el,text)=>{el.value=text}', 'write “Hi” for Alex')
            submit.click()
            caption(page,'Alex · “Hi”')
        expected = page.evaluate(visible_editor)
        before = frame(page)
        downloads = drawing_files(page,'#downloads') if action == 'submit' else None
        page.evaluate('async()=>{window.releaseWord(); await new Promise(requestAnimationFrame)}')
        assert page.evaluate(visible_editor) == expected, ('Slow Thai request replaced a later edit', action)
        assert np.array_equal(frame(page),before), ('Slow Thai request changed the sand', action)
        if downloads:
            assert drawing_files(page,'#downloads') == downloads
    assert page.request.get(api).json() == original


def exercise(browser, gallery, out, database):
    with room(gallery,database) as url, browser.new_context(**MOBILE) as a, browser.new_context(**MOBILE) as b:
        pages = [a.new_page(),b.new_page()]
        problems = []
        for context in (a,b):
            context.route('http**://**/*',lambda r:r.continue_() if r.request.url.startswith(url+'/') else r.abort())
        for page in pages:
            page.on('pageerror',lambda exc:problems.append(str(exc)))
            open_room(page,url)
        first,second = pages
        api = url+API
        live = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live")
        catalog = live['planner']
        assert catalog['defaults'] == [catalog['openSubject']]*3
        suggest(first,'a bacteriophage for Thomas')
        keep(first)
        phage = catalog.get('preferredSubjects', {}).get('phage', 'phage')
        caption(second, 'Thomas · '+catalog['subjects'][phage])
        original = first.request.get(api).json()
        events = [watch_saves(p,api) for p in pages]

        # Both phones prepare and submit from exactly the same revision, then one retries automatically.
        jobs = [(2,'Lek','write "Lek" for Lek'),(1,'Thank you','write "Thank you" for Alex')]
        previews = [preview_text(page,*job) for page,job in zip(pages,jobs)]
        original_puts = barrier(pages,api,original['revision'],(2,1))
        reports = {}
        merged = first.request.get(api).json()
        assert merged['revision'] == original['revision']+2
        for page,job,(files,frames),outgoing,history in zip(pages,jobs,previews,original_puts,events):
            slot,text,_ = job
            accepted = [body for status,body in history if status==200]
            assert len(accepted)==1 and accepted[0]['motion']['files']==as_file_payload(files)
            saved = merged['state']
            assert saved['labels'][saved['ids'][slot]] == f'“{text}”'
            assert saved['custom'][saved['ids'][slot]] == outgoing['state']['custom'][outgoing['state']['ids'][slot]]
            reports[text] = inspect_letters(page,live,text,slot,files,frames,original['state'],outgoing['state'],out/text)
        check_bed(first,merged['state'],(0,2,1))
        for p in pages:
            caption(p,'Lek · “Lek”')
            caption(p,'Alex · “Thank you”')
        assert np.array_equal(frame(first),frame(second))
        second.reload()
        caption(second,'Alex · “Thank you”')
        assert drawing_files(second,'#roomFiles') == previews[1][0]
        assert np.array_equal(frame(first),frame(second))

        # Now put a name over the occupied phage, leaving both neighboring inscriptions in the sand.
        files,frames = preview_text(first,0,'Thomas','write my name for Thomas')
        body,revision = save(first,api)
        assert body['motion']['place']==0 and not body['motion'].get('fill') and body['motion']['files']==as_file_payload(files)
        reports['Thomas'] = inspect_letters(first,live,'Thomas',0,files,frames,merged['state'],body['state'],out/'Thomas')
        caption(second,'Thomas · “Thomas”')
        assert drawing_files(second,'#roomFiles') == files
        assert np.array_equal(frame(first),frame(second))

        expected = first.request.get(api).json()
        rejected(first,'write "Thomas" for Thomas',r'already in')
        first.locator('#target').select_option('1')
        rejected(first,'write "Hi" for Lek',r'differ|same|intended|match|different')
        first.locator('#target').select_option('2')
        rejected(first,'write my name',r'already in')
        first.locator('#target').select_option('')
        rejected(first,'write my name',r'choose a guest|guest.*name')
        rejected(first,'write "Happy Thanksgiving" for Lek',r'shorter|initials|shorten')
        assert first.request.get(api).json() == expected and expected['revision']==revision
        cancel_slow_thai(first,api)

        thai = 'เล็ก'
        files,frames = preview_text(first,2,thai,f'write “{thai}” for Lek')
        body,revision = save(first,api)
        assert body['motion']['place']==2 and body['motion']['files']==as_file_payload(files)
        reports[thai] = inspect_letters(first,live,thai,2,files,frames,expected['state'],body['state'],out/thai)
        second.reload()
        caption(second,'Lek · “'+thai+'”')
        assert drawing_files(second,'#roomFiles') == files
        assert np.array_equal(frame(first),frame(second))
        expected = first.request.get(api).json()
        rejected(first,f'write “{thai}” for Lek',r'already in')
        rejected(first,'write “สุขสันต์วันขอบคุณพระเจ้า” for Lek',r'shorter|space')
        assert first.request.get(api).json() == expected and expected['revision']==revision
        files,frames = preview_text(first,1,'Thanks!','write “Thanks!” for Alex')
        body,_ = save(first,api)
        reports['Thanks!'] = inspect_letters(first,live,'Thanks!',1,files,frames,expected['state'],body['state'],out/'Thanks!')
        assert not problems, problems
        (out/'results.json').write_text(json.dumps(reports,indent=2)+'\n')
        return reports


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('gallery',type=Path)
    cli.add_argument('--evidence',type=Path,required=True)
    args = cli.parse_args()
    args.evidence.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            results=exercise(browser,args.gallery,args.evidence,Path(temp)/'room.db')
            for result in results.values():
                print(result['guest'],result['lines'],result['x_height_grooves'],'grooves')
