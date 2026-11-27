"""Prepare a single face or select one in a guest photo, then reopen its print on a second phone."""
import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, choose, drawing_files, open_room, room
from test_ring_guest_border import MOBILE, save
from test_ring_shadows import ready
from thrcommon import motion_files_hash
from wide_portrait import chromium


def trace(phone, url, photo, index, flagged):
    open_room(phone, url, 'photos')
    phone.locator('#portraitArea').select_option('wide')
    phone.locator('#portraitFile').set_input_files(photo)
    phone.locator('#portraitSubmit').click()
    ready(phone)
    if index is not None:
        detail=phone.locator('#portraitSource')
        if not detail.evaluate('el=>el.open'):
            detail.locator('summary').click()
        phone.locator('#faceBoxes button').nth(index).click()
        ready(phone)
    before=drawing_files(phone,'#downloads')
    # The DevTools response cache can evict this JSON when all prepared
    # styles are included. Observe the real local reply before fulfilling it.
    answers = []
    endpoint = url + '/api/portrait'
    def read_host(request):
        response = request.fetch(timeout=100000)
        assert response.ok, response.status
        options = json.loads(request.request.headers['x-oasis-portrait'])
        assert bool(options.get('rakePrint')) == flagged
        if index is not None:
            assert options['face'] == index
        answers.append(response.json())
        request.fulfill(response=response)
    phone.route(endpoint, read_host, times=1)
    with phone.expect_response(lambda r:r.url==endpoint and r.request.method=='POST', timeout=100000):
        phone.locator('#portraitHair').click()
    reply = answers[0]
    expect(phone.locator('#portraitHair')).to_be_enabled(timeout=20000)
    opened=drawing_files(phone,'#downloads')
    return before,opened,reply


def exercise(browser, current_url, old_url, photo, index):
    with browser.new_page(**MOBILE) as phone, browser.new_page(**MOBILE) as second:
        old=trace(phone,old_url,photo,index,False) if old_url else None
        before,after,reply=trace(phone,current_url,photo,index,True)
        if old:
            assert before==old[0] and after==old[1] and reply['drawing']==old[2]['drawing']
        assert reply['rakePrint']['applied'] and reply['rakePrintDrawing']['includesCenterRake']
        button=phone.locator('#portraitRake')
        expect(button).to_be_visible()
        button.click()
        expect(phone.locator('#portraitHairNote')).to_contain_text('clears the center in one pass')
        printed=drawing_files(phone,'#downloads')
        assert printed!=after
        host_names=reply['rakePrint']['files']
        assert len(host_names)==len(printed)
        parts=[{'name':name,'text':data.decode()} for name,(_,data) in zip(host_names,printed,strict=True)]
        assert motion_files_hash(parts)==reply['rakePrint']['motionSHA256']
        button.click()
        assert drawing_files(phone,'#downloads')==after
        button.click()
        saved,_=save(phone,current_url+API)
        assert saved['motion']['includesCenterRake'] is True and saved['motion']['centerMode']=='widePortrait'
        open_room(second,current_url,'photos')
        choose(second,'zone','center')
        assert drawing_files(second,'#roomFiles')==printed
        return len(printed),sum(data.count(b'\n') for _,data in printed)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('garden',type=Path)
    parser.add_argument('photo',type=Path)
    parser.add_argument('--face',type=int,help='Select this numbered person from a group (first is 1).')
    parser.add_argument('--previous',type=Path,help='Earlier garden on the same geometry to compare both defaults.')
    args=parser.parse_args()
    from contextlib import ExitStack
    with ExitStack() as stack:
        tmp=Path(stack.enter_context(tempfile.TemporaryDirectory()))
        current=stack.enter_context(room(args.garden,tmp/'current.db',photo_portraits=True))
        earlier=stack.enter_context(room(args.previous,tmp/'earlier.db',photo_portraits=True)) if args.previous else None
        pw=stack.enter_context(sync_playwright())
        browser=stack.enter_context(pw.chromium.launch(executable_path=chromium(pw,None)))
        parts,rows=exercise(browser,current,earlier,args.photo,args.face-1 if args.face is not None else None)
    print(f'Guest photo print and second-phone recovery passed with {parts} files ({rows} rows across files).')
