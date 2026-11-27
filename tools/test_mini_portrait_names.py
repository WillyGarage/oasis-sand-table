#!/usr/bin/env python3
"""Play the ordinary Mini photo form on two private, phone-sized Chromium sessions."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import numpy as np
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from test_guest_center import FramedMini, ORIGIN, ROOT, Table, verify_center


def preview(page):
    page.locator('#previewButton').click()
    expect(page.locator('#draw')).to_be_enabled(timeout=20000)


def phone(browser, assets):
    device = FramedMini(assets)
    page = browser.new_page(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
    def handle(route):
        assert route.request.url.startswith(ORIGIN+'/'), 'Guest photo requested a non-table destination.'
        if urlsplit(route.request.url).path == '/guest-draw':
            return Table.handle(device, route)
        return device.handle(route)
    page.context.route('**/*', handle)
    page.goto(ORIGIN+'/lib/guest.html')
    expect(page.locator('#previewButton')).to_be_enabled()
    return page


def choose(page, source, target, group):
    page.get_by_role('button', name='Photo', exact=True).click()
    page.locator('#photoTarget').select_option(target)
    page.locator('#file').set_input_files(source)
    page.locator('#photoMode').select_option('group' if group else 'one')
    # Compare the existing shoulder framing, including on an earlier bundle.
    head = page.locator('#centerHead')
    if head.is_visible():
        head.uncheck()
    preview(page)
    expect(page.locator('#faceBoxes button')).to_have_count(2)
    if not group:
        page.locator('#faceBoxes button').nth(1).click()  # Lek, right of Bill in the original.
        expect(page.locator('#draw')).to_be_enabled()


def submit(page, target):
    path = '/thr' if target == 'center' else '/guest-draw'
    with page.expect_request(lambda req: urlsplit(req.url).path == path) as sent:
        page.locator('#draw').click()
    expect(page.locator('#message')).to_contain_text('started' if target == 'center' else 'accepted')
    raw = sent.value.post_data_buffer
    if target == 'center':
        verify_center(raw.decode())
    else:
        values = np.frombuffer(raw,dtype='<f4').reshape(-1,2)
        assert 2 <= len(values) <= 12000 and values[0,1] == values[-1,1] == 1
        assert np.isfinite(values).all() and (np.abs(np.diff(values[:,0])) <= 3.15).all()
        assert values[:,1].min() >= 0 and values[:,1].max() <= 1
    return raw


def geometry(page, target, group, name):
    result = page.evaluate('''async ([target,group,name])=>{
        const diameter=await GuestCenterRoutes.photoDiameterGrooves(target), groove=2/diameter;
        const photo=await GuestPhoto.fromFile(document.querySelector('#file').files[0],{group,face:group?null:1});
        const fit=await GuestPortraitCaption.fit(photo.points,name,groove);
        const data=target==='center' ? new TextEncoder().encode((await GuestCenterRoutes.photo(fit.points)).text) :
          new Uint8Array(GuestArt.buffer(GuestArt.pathForPhoto(fit.points,{center:[0,0],radius:1,angle:-Math.PI/2})));
        const bytes=Array.from(data,c=>String.fromCharCode(c)).join('');
        return {fit,raw:photo.points,diameter,data:btoa(bytes)};
    }''', [target,group,name])
    fit = result['fit']
    face, text = np.array(fit['portrait']), np.array(fit['caption'])
    delta = face - fit['scale'] * np.array(result['raw'][1:-1])
    np.testing.assert_allclose(delta, np.repeat(delta[:1],len(delta),axis=0), atol=1e-10)
    radius = result['diameter']*5.32/2
    gap = (face[:,1].min() - text[:,1].max()) * radius
    assert .75 <= fit['scale'] <= 1 and fit['letterGrooves'] >= 4.2 and gap >= 1.749*5.32
    return (dict(face_scale=fit['scale'], lowercase_height_mm=round(fit['letterGrooves']*5.32,2),
                 clearance_mm=round(gap,2), diameter_mm=round(2*radius,2)), base64.b64decode(result['data']))


def explore(browser, assets, source, target, group, name, output, previous):
    routes, metrics = {}, {}
    for label in ('plain','named','repeat'):
        with phone(browser,assets) as page:
            choose(page,source,target,group)
            field = page.get_by_label('Name under the portrait')
            expect(field).to_be_visible()
            if label == 'plain':
                before = page.locator('#drawing').evaluate('c=>c.toDataURL()')
                field.fill(name)
                expect(page.locator('#draw')).to_be_disabled()
                field.fill('   ')
                preview(page)
                assert page.locator('#drawing').evaluate('c=>c.toDataURL()') == before
            else:
                field.fill('Bill and Lek')
                page.locator('#previewButton').click()
                expect(page.locator('#error')).to_contain_text('need more room')
                expect(page.locator('#draw')).to_be_disabled()
                field.fill(name)
                preview(page)
                expect(page.locator('#effect')).to_contain_text('“'+name+'”')
                if label == 'named':
                    metrics, expected = geometry(page,target,group,name)
            routes[label] = submit(page,target)
            if label == 'named':
                assert routes[label] == expected
    if previous:
        with phone(browser,previous) as page:
            choose(page,source,target,group)
            assert submit(page,target) == routes['plain']
    assert routes['named']==routes['repeat'] and routes['plain']!=routes['named']
    if output:
        folder=output/(target+('-pair' if group else '-solo'))
        folder.mkdir(parents=True,exist_ok=True)
        for label in ('plain','named'):
            ext='thr' if target=='center' else 'bin'
            (folder/(label+'.'+ext)).write_bytes(routes[label])
    named = routes['named']
    return dict(target=target, group=group, name=name, **metrics,
                rows=len(named.splitlines()) if target=='center' else len(named)//8,
                sha256=hashlib.sha256(named).hexdigest())


def exclusions(browser, assets, source):
    with phone(browser,assets) as page:
        choose(page,source,'center',False)
        field=page.get_by_label('Name under the portrait')
        field.fill('เล็ก')
        page.locator('#previewButton').click()
        expect(page.locator('#error')).to_contain_text('need more room')
        expect(page.locator('#draw')).to_be_disabled()
        page.get_by_label('Head only').check()
        # A bare L would bring the hair too close to the seven-roof frame.
        field.fill('L')
        page.locator('#previewButton').click()
        expect(page.locator('#error')).to_contain_text('Whole table')
        expect(page.locator('#draw')).to_be_disabled()
        # Selecting the same single face in Group photo must keep its crown clear too.
        field.fill('')
        page.locator('#photoMode').select_option('group')
        preview(page)
        page.locator('#faceBoxes button').first.click()
        field.fill('L')
        page.locator('#previewButton').click()
        expect(page.locator('#error')).to_contain_text('Whole table')
        expect(page.locator('#draw')).to_be_disabled()
        field.fill('')
        preview(page)
        page.locator('#photoMode').select_option('whole')
        expect(field).to_be_hidden()
        page.locator('#photoMode').select_option('one')
        page.locator('#photoTarget').select_option('0')
        expect(field).to_be_hidden()
        page.locator('#photoTarget').select_option('full')
        field.fill('Previous name')
        empty = io.BytesIO()
        Image.new('RGB',(320,240),'white').save(empty,format='PNG')
        page.locator('#file').set_input_files(dict(name='blank.png',mimeType='image/png',buffer=empty.getvalue()))
        expect(field).to_have_value('')
        field.fill('Name')
        page.locator('#previewButton').click()
        expect(page.locator('#error')).not_to_be_empty()
        expect(page.locator('#draw')).to_be_disabled()


def full_closeup(browser, assets, source, group=False):
    with phone(browser, assets) as page:
        page.get_by_role('button', name='Photo', exact=True).click()
        page.locator('#photoTarget').select_option('full')
        page.locator('#photoMode').select_option('group' if group else 'one')
        expect(page.get_by_label('Close up on faces' if group else 'Head only')).to_be_checked()
        page.locator('#file').set_input_files(source)
        preview(page)
        if not group:
            page.locator('#faceBoxes button').nth(1).click()
            expect(page.locator('#draw')).to_be_enabled()
        # Switching through a smaller circle must not reuse its eye or mouth
        # geometry on a full-table portrait of the same selected person.
        page.locator('#photoTarget').select_option('center')
        preview(page)
        page.locator('#photoTarget').select_option('full')
        preview(page)
        expected = page.evaluate('''async group => {
            const d=await GuestCenterRoutes.photoDiameterGrooves('full');
            const file=document.querySelector('#file').files[0];
            const art=await GuestPhoto.fromFile(file,{group,face:group?null:1,groupStyle:group?'heads':undefined,
              portraitFraming:'head',portraitDiameterGrooves:d});
            const path=GuestArt.pathForPhoto(art.points,{center:[0,0],radius:1,angle:-Math.PI/2});
            return Array.from(new Uint8Array(GuestArt.buffer(path)));
        }''', group)
        assert submit(page,'full') == bytes(expected)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('couple',type=Path,help='Bill on the left and Lek on the right')
    cli.add_argument('--bundle',type=Path)
    cli.add_argument('--previous',type=Path,help='Optional Mini bundle from before portrait names')
    cli.add_argument('--evidence',type=Path)
    args=cli.parse_args()
    with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
        bundle=args.bundle or Path(tmp)
        if not args.bundle:
            build_guest_web_assets(ROOT/'web',bundle,mini_only=True)
        chrome=next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            report=[explore(browser,bundle,args.couple,target,group,name,args.evidence,args.previous)
                    for target,group,name in [('full',False,'Lek'),('full',True,'B L'),('center',True,'B L')]]
            exclusions(browser,bundle,args.couple)
            full_closeup(browser,bundle,args.couple)
            full_closeup(browser,bundle,args.couple,group=True)
        output=json.dumps(report,indent=2)
        if args.evidence:
            (args.evidence/'tested-routes.json').write_text(output+'\n')
        print(output)


if __name__ == '__main__':
    main()
