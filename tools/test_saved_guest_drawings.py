#!/usr/bin/env python3
"""Teach an open three-place garden a subject from a photo and recall it on a second phone."""
import argparse
import mimetypes
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_ring_guest_border import MOBILE, save
from test_ring_object_photo import PhoneTraffic, expand


def ask(page, text):
    page.locator('#idea').fill(text)
    page.get_by_role('button', name='Preview suggestion').click()


def draw_another_version(page, label, guest='Alex'):
    page.locator('#idea').fill(label + ' for ' + guest)
    expand(page, '#sketch')
    pad = page.locator('#sketchPad')
    pad.scroll_into_view_if_needed()
    rect = pad.bounding_box()
    x, y = rect['x'] + rect['width']/2, rect['y'] + rect['height']/2
    page.mouse.move(x-28, y+16)
    page.mouse.down()
    page.mouse.move(x, y-24, steps=5)
    page.mouse.move(x+30, y+12, steps=5)
    page.mouse.up()
    page.get_by_role('button', name='Preview suggestion').click()
    caption(page, guest + ' · ' + label)


def exercise(browser, gallery, photo, label):
    with tempfile.TemporaryDirectory() as tmp, room(gallery, Path(tmp)/'garden.db') as url, \
            browser.new_context(**MOBILE, service_workers='block') as a, \
            browser.new_context(**MOBILE, service_workers='block') as b:
        traffic = PhoneTraffic(url)
        for phone in (a,b):
            phone.route('http**://**/*', traffic.check)
        host, guest = a.new_page(), b.new_page()
        api = url + API
        open_room(host, url)
        ask(host, label + ' for Lek')
        host.locator('#suggestionPhoto').click()
        expect(host.locator('#portraitPlace')).to_have_value('2')
        expect(host.locator('#objectName')).to_have_value(label)
        mime = mimetypes.guess_type(photo.name)[0]
        host.locator('#portraitFile').set_input_files(traffic.photo(photo.name,photo.read_bytes(),mime))
        host.locator('#portraitSubmit').click()
        caption(host, 'Lek · ' + label)
        files = drawing_files(host,'#downloads')
        first, _ = save(host,api)
        assert first['motion']['place'] == 2 and first['motion']['fill']
        art = first['state']['ids'][2]
        path = first['state']['custom'][art]
        assert files == [(part['name'],part['text'].encode()) for part in first['motion']['files']]
        suggest(host, 'a guitar for Lek')
        save(host,api)

        # Earlier phones sent only the paths still required by the guest book.
        prior = host.request.get(api).json()
        older = {**prior['state'], 'custom':{}, 'labels':{}}
        assert art not in older['ids'] and not older.get('guestBook')
        response = host.request.put(api,headers={'Origin':url},data={'revision':prior['revision'],'state':older})
        assert response.ok, response.text()
        assert host.request.get(api).json()['state']['custom'][art] == path

        # This phone has never seen the photo. The named drawing has already left the sand.
        open_room(guest,url)
        ask(guest,'saved '+label+' miniature for Thomas')
        expect(guest.locator('#error')).to_contain_text('not in the saved')
        expect(guest.locator('#keep')).to_be_hidden()
        ask(guest, 'please draw the ' + label.lower() + ' for Thomas')
        caption(guest, 'Thomas · ' + label)
        recalled, _ = save(guest,api)
        assert recalled['motion']['place'] == 0 and recalled['motion']['fill']
        assert recalled['state']['ids'][0] == art and recalled['state']['custom'][art] == path

        draw_another_version(guest,label)
        second, _ = save(guest,api)
        other = second['state']['ids'][1]
        assert other != art and second['state']['custom'][other] != path
        open_room(host,url)
        request = 'replace the guitar with the saved ' + label + ' for Lek'
        ask(host,request)
        expect(host.locator('#error')).to_contain_text('2 drawings')
        expect(host.locator('#keep')).to_be_hidden()
        picker = host.get_by_role('combobox', name='Saved guest drawings')
        for candidate in (other,art):
            host.locator('#target').select_option('')
            ask(host,request)
            picker.select_option(candidate)
            caption(host,'Lek · ' + label)
            expect(host.locator('#target')).to_have_value('2')
            expect(host.locator('#keep')).to_be_visible()
        chosen, _ = save(host,api)
        assert chosen['state']['ids'] == [art,other,art]
        assert chosen['state']['custom'][art] == path
        open_room(guest,url)
        guest.locator('#target').select_option('0')
        guest.locator('#savedDrawing').select_option(art)
        expect(guest.locator('#error')).to_contain_text('already in this guest')
        expect(guest.locator('#keep')).to_be_hidden()
        assert not traffic.violations and traffic.writes == 5, (traffic.violations,traffic.writes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('photo',type=Path)
    parser.add_argument('--name',default='Kaypro II')
    args = parser.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args.gallery,args.photo,args.name)
    print('Saved, replaced and recalled the named drawing across two phones.')
