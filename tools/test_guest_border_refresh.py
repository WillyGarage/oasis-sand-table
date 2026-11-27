#!/usr/bin/env python3
"""Refresh a single changed guest in the real border form, with two phones and signed movements."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

import check_ring_scene as check
from test_garden_family_portrait import bed
from test_garden_room import API, caption, choose, drawing_files, keep, open_room, room, suggest
from test_guest_border_seat import masks
from test_guest_keepsake_border import chair_detail, signed_subject, source_drawings
from test_ring_guest_border import MOBILE, from_files, replay, save
from test_ring_object_photo import expand
from test_ring_photo import frame
from test_ring_shadows import ready
from wide_portrait import chromium


ROOT = Path(__file__).resolve().parents[1]


def opening(browser, editor, database, order):
    with room(editor, database) as url, browser.new_page(**MOBILE) as page:
        open_room(page, url)
        suggest(page, 'a phage for Thomas, an open book for Alex and a Thai rooftop for Lek')
        keep(page)
        choose(page, 'zone', 'outer')
        page.locator('#borderDesign').select_option('-1')
        page.locator('#borderOrder').select_option(order)
        page.locator('#borderPreview').click()
        keep(page)
        choose(page, 'zone', 'middle')
        suggest(page, 'a heart with B and L inside for Lek')
        keep(page)
        choose(page, 'zone', 'center')
        expand(page, '#centerPhoto')
        page.locator('#portraitArea').select_option('wide')
        page.locator('#portraitMode').select_option('prepared')
        page.locator('#portraitFile').set_input_files(ROOT/'patterns/portrait-gallery/drawings/crown-at-dinner-normal.oasisportrait')
        page.locator('#portraitSubmit').click()
        ready(page)
        kept, _ = save(page, url+API)
        assert kept['state']['widePortrait'] and kept['state']['outer'] == -1


def requests(page, api):
    choose(page, 'zone', 'center')
    page.locator('#restoreGuests').click()
    keep(page)
    choose(page, 'zone', 'middle')
    suggest(page, 'a guitar for Thomas')
    keep(page)
    suggest(page, 'put the guest drawings around the table')
    expect(page.locator('#keep')).to_have_text('Keep Thomas’s border drawing')
    page.locator('#borderGuest').fill('Alex')
    page.locator('#borderPreview').click()
    expect(page.locator('#borderOrder option:checked')).to_have_text('Draw each section as it clears')
    page.locator('#borderGuest').fill('')
    page.locator('#borderPreview').click()
    saved, _ = save(page, api)
    assert saved['motion']['guestBorderSeat']['place'] == 0
    choose(page, 'zone', 'middle')
    suggest(page, 'a phage for Thomas and a guitar for Alex')
    keep(page)
    suggest(page, 'put the guest drawings around the table')
    saved, _ = save(page, api)
    assert saved['motion']['guestBorderOrder'] == 'progressive' and 'guestBorderSeat' not in saved['motion']


def refresh(browser, editor, database, out, order, previous=None):
    out.mkdir(parents=True, exist_ok=True)
    with room(editor, database) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as friend:
        for page in (host, friend):
            open_room(page, url)
            choose(page, 'zone', 'outer')
        api = url+API
        opening_receipt = host.request.get(api).json()
        before = opening_receipt['state']
        catalog, sources = source_drawings(host, before)
        assert sources[2]['label'] == 'Lek · Heart with BL'
        original = frame(host)
        host.locator('#borderDesign').select_option('-1')
        host.locator('#borderOrder').select_option('whole')
        host.locator('#borderPreview').click()
        whole = drawing_files(host, '#downloads')
        host.locator('#borderOrder').select_option('progressive')
        host.locator('#borderPreview').click()
        files = drawing_files(host, '#downloads')
        assert host.request.get(api).json() == opening_receipt and not host.locator('#editBorderPlace').is_checked()
        assert ('only Lek' in host.locator('#borderOrder option:checked').inner_text()) == bool(previous)
        grain = 'fluted' if order == 'progressive' else 'spiral'
        geometry = host.evaluate("""([sources,local,grain])=>{
          const s=JSON.parse(document.querySelector('#scene').textContent), shapes=sources.map(x=>x?.points??null);
          const p=local ? GuestKeepsakeBorder.planSeat(s,2,shapes[2],grain) : GuestKeepsakeBorder.plan(s,shapes,'progressive');
          const piece=p.placements[2], ink=OasisRingPlanner.travelDistances(p.path.slice(piece.first,piece.last+1));
          return {piece, halfway:piece.first+OasisRingPlanner.halfIndex(ink),
            sector:s.live.guestBorderSectors.find(x=>x.slot===2)};
        }""", [sources, bool(previous), grain])
        target = geometry['piece']
        route = from_files(files, catalog['dock'])
        distance = check.travel(route)*catalog['radiusMm']/1000
        proof = signed_subject(route, target, sources[2]['points'], catalog['angles'][2], catalog['radiusMm'])

        def picture(name, image):
            Image.fromarray(image).save(out/(name+'.png'))
            chair_detail(image, target['angle'], target['center'], np.asarray(sources[2]['points']),
                         target['scale'], catalog['groove']).save(out/(name+'-detail.png'))

        picture('before', original)
        final = frame(host)
        picture('after', final)
        choose(host, 'stage', 'cleared')
        middle = frame(host)
        picture('in-progress', middle)
        if previous:
            caption(host, 'Heart with BL is partly drawn.')
            assert host.locator('#middleStageLabel').inner_text() == 'In progress'
            visible = replay(host, before['bed'], route[:geometry['halfway']+1])
            assert np.mean(np.abs(visible.astype(float)-middle)) < .1
        choose(host, 'stage', 'redrawn')
        payload, revision = save(host, api)
        state, motion = payload['state'], payload['motion']
        assert state['guestBorder'] == sources
        assert [(f['name'], f['text'].encode()) for f in motion['files']] == files
        for key in ('ids', 'guestBook', 'custom', 'labels', 'widePortrait', 'portrait', 'center', 'borderGuest'):
            assert state.get(key) == before.get(key), key
        caption(friend, 'Lek · Heart with BL')
        assert drawing_files(friend, '#roomFiles') == files and np.array_equal(frame(host), frame(friend))
        friend.goto('about:blank')
        open_room(friend, url)
        choose(friend, 'zone', 'outer')
        assert drawing_files(friend, '#roomFiles') == files and friend.request.get(api).json()['revision'] == revision
        interior, unaffected, neighbors = masks(len(original), catalog, geometry['sector'])
        np.testing.assert_array_equal(bed(state,len(original))[interior], bed(before,len(original))[interior])

        if previous:
            assert motion['guestBorderSeat'] == dict(place=2, subject=before['ids'][2],
                                                    **({'grain':'spiral'} if order=='whole' else {}))
            for mask in (interior, unaffected, *neighbors):
                assert np.array_equal(final[mask], original[mask]) and np.array_equal(middle[mask], original[mask])
                assert np.array_equal(bed(state,len(original))[mask], bed(before,len(original))[mask])
            old_route, old_report, old_whole = previous
            old_distance = check.travel(old_route)*catalog['radiusMm']/1000
            assert whole == old_whole and distance[-1] < .14*old_distance[-1]
            assert distance[target['last']] < .28*old_report['finished_m']
            at = np.argmin(abs(old_distance-distance[target['last']]))
            picture('earlier-at-completion', replay(host,before['bed'],old_route[:at+1]))
            picture('current-at-completion', replay(host,before['bed'],route[:target['last']+1]))
            if order == 'progressive':
                requests(host, api)
        else:
            assert motion['guestBorderOrder'] == 'progressive' and 'guestBorderSeat' not in motion
        for name, raw in files:
            (out/name).write_bytes(raw)
        report = dict(**proof, first_m=round(distance[target['first']],3), finished_m=round(distance[target['last']],3),
                      total_m=round(distance[-1],3), protected_center_pixels=int(interior.sum()),
                      protected_neighbor_pixels=[int(m.sum()) for m in neighbors])
        (out/'verified.json').write_text(json.dumps(report,indent=2)+'\n')
        print(out.name, report, flush=True)
        return route, report, whole


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('previous', 'editor', 'output'):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw,None)) as browser:
        for order in ('progressive','whole'):
            seed = Path(tmp)/(order+'.db')
            opening(browser, args.previous, seed, order)
            previous = None
            for name, editor in [('earlier',args.previous),('current',args.editor)]:
                db = Path(tmp)/(order+'-'+name+'.db')
                shutil.copyfile(seed, db)
                previous = refresh(browser, editor, db, args.output/(order+'-'+name), order, previous)
