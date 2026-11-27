#!/usr/bin/env python3
"""Verify who receives music in the Mini and in a shared, locally hosted dinner garden."""
import argparse
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import API, caption, drawing_files, open_room, room, suggest
from test_guest_web import ORIGIN, Table, send, suggest as mini_suggest
from test_ring_guest_border import MOBILE, save
from wide_portrait import chromium

ALEX = 'Teaching and playing guitar'


def mini(browser):
    table = Table()
    table.test_pending_fresh = False
    table.people['Alex'] = dict(name='Alex', interest='Teaching', subject='books')
    with browser.new_page(**MOBILE) as host:
        host.context.route('**/*', lambda r: table.handle(r) if r.request.url.startswith(ORIGIN+'/') else r.abort())
        host.goto(ORIGIN+'/lib/guest.html')
        host.locator('#previewButton:enabled').wait_for()
        expect(host.locator('#roster')).to_contain_text(ALEX)
        mini_suggest(host, 'an electric guitar')
        host.locator('#keepChanging').check()
        options = host.locator('#alternate1')
        expect(options.locator('..')).to_contain_text('Alex')
        assert options.input_value().split(', ')[:3] == [
            table.catalog['subjects'][key]['label'] for key in ('electric_guitar','books','guitar')]
        send(host)
        assert table.slots == ['', 'electric_guitar', '']
        assert table.themes[1].split(',')[:3] == ['electric_guitar', 'books', 'guitar']
        host.reload()
        host.locator('#previewButton:enabled').wait_for()
        mini_suggest(host, 'music')
        send(host)
        assert table.slots == ['', 'glyph-266b', '']
        mini_suggest(host, 'a guitar for Thomas')
        send(host)
        assert table.slots == ['guitar', 'glyph-266b', '']
        mini_suggest(host, 'an electric guitar', '2')
        send(host)
        assert table.slots == ['guitar', 'glyph-266b', 'electric_guitar']
    # Two people can request the same picture and keep their own interests.
    table = Table()
    table.known, table.slots = True, ['phage', 'books', 'temple']
    with browser.new_page(**MOBILE) as host:
        host.context.route('**/*', lambda r: table.handle(r) if r.request.url.startswith(ORIGIN+'/') else r.abort())
        host.goto(ORIGIN+'/lib/guest.html')
        host.locator('#previewButton:enabled').wait_for()
        mini_suggest(host, 'a bacteriophage for Alex')
        host.locator('#keepChanging').check()
        for i, name in enumerate(('Thomas', 'Alex')):
            expect(host.locator(f'#alternate{i}').locator('..')).to_contain_text(name)
        send(host)
        assert table.slots == ['phage','phage','temple']
        assert 'guitar' not in table.themes[0].split(',') and 'guitar' in table.themes[1].split(',')
    # An older phone may have a fact in its own storage and a real custom interest on the table.
    table = Table()
    table.people['Alex'] = dict(name='Alex', interest='Painting with watercolors', subject='books')
    with browser.new_page(**MOBILE) as host:
        host.context.route('**/*', lambda r: table.handle(r) if r.request.url.startswith(ORIGIN+'/') else r.abort())
        host.goto(ORIGIN+'/lib/guest.html')
        host.locator('#previewButton:enabled').wait_for()
        expect(host.locator('#roster')).to_contain_text('Painting with watercolors')
        host.locator('#previewButton').click()
        host.locator('#keepChanging').check()
        options = host.locator('#alternate1')
        expect(options.locator('..')).to_contain_text('Alex')
        assert table.catalog['subjects']['guitar']['label'] not in options.input_value().split(', ')
        host.locator('#keepChanging').uncheck()
        mini_suggest(host, 'an acoustic guitar')
        send(host)
        assert table.slots == ['guitar', '', '']


def read_person(page, name):
    page.locator('#peopleBox').evaluate('e=>e.open=true')
    page.locator('#personPick').select_option(label=name)
    return page.locator('#personInterest').input_value()


def reopen(page, url):
    page.goto('about:blank')
    open_room(page, url)


def garden(browser, page_file, database, previous):
    if previous:
        # The older editor writes its original starter bio even after Alex switches seats.
        with room(previous, database) as url, browser.new_page(**MOBILE) as page:
            open_room(page, url)
            assert read_person(page, 'Alex') == 'Teaching'
            page.locator('#personPlace').select_option('2')
            page.locator('#personDrawing').select_option('books_open')
            page.locator('#personSubmit').click()
            saved, _ = save(page, url+API)
            assert saved['state']['guestBook']['active'] == ['thomas', 'lek', 'alex']
    with room(page_file, database) as url, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        slot = 2 if previous else 1
        for page in host, guest:
            open_room(page, url)
            assert read_person(page, 'Alex') == ALEX
            options = page.locator('#personDrawing optgroup[label="From their interests"] option').evaluate_all(
                'opts=>opts.map(o=>o.value)')
            assert 'guitar_silhouette' in options
            assert read_person(page, 'Thomas') == 'Bacteriophages'
            expect(page.locator('#personDrawing optgroup[label="From their interests"] option[value="guitar_silhouette"]')).to_have_count(0)
            page.locator('#peopleBox').evaluate('e=>e.open=false')
        suggest(host, 'a guitar')
        caption(host, 'Alex · Acoustic guitar')
        files = drawing_files(host, '#downloads')
        payload, _ = save(host, url+API)
        assert payload['state']['ids'][slot] == 'guitar_silhouette' and payload['motion']['place'] == slot
        if previous:
            assert payload['state']['guestBook']['active'] == ['thomas', 'lek', 'alex']
        reopen(guest, url)
        caption(guest, 'Alex · Acoustic guitar')
        assert drawing_files(guest, '#roomFiles') == files
        suggest(guest, 'music')
        caption(guest, 'Alex ·')
        payload, _ = save(guest, url+API)
        assert payload['motion']['place'] == slot and payload['state']['ids'][slot] == 'symbol-266b'
        suggest(guest, 'an electric guitar for Thomas')
        caption(guest, 'Thomas · Electric guitar')
        payload, _ = save(guest, url+API)
        assert payload['motion']['place'] == 0
        third = 1 if previous else 2
        guest.locator('#target').select_option(str(third))
        suggest(guest, 'a guitar')
        caption(guest, 'Lek · Acoustic guitar')
        payload, _ = save(guest, url+API)
        assert payload['motion']['place'] == third
        # Keep an intentional edit, and find the musician from the new interests.
        reopen(guest, url)
        read_person(guest, 'Alex')
        guest.locator('#personInterest').fill('Gardening and stargazing')
        guest.locator('#personDrawing').select_option('telescope')
        guest.locator('#personSubmit').click()
        save(guest, url+API)
        read_person(guest, 'Lek')
        guest.locator('#personInterest').fill('Plays electric guitar')
        guest.locator('#personDrawing').select_option('temple_gable')
        guest.locator('#personSubmit').click()
        save(guest, url+API)
        reopen(host, url)
        assert read_person(host, 'Alex') == 'Gardening and stargazing'
        host.locator('#peopleBox').evaluate('e=>e.open=false')
        suggest(host, 'an electric guitar')
        caption(host, 'Lek · Electric guitar')
        payload, _ = save(host, url+API)
        assert payload['motion']['place'] == third


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw, pw.chromium.launch(
            executable_path=chromium(pw,None)) as browser:
        mini(browser)
        print('Mini books, music, explicit recipients, overrides and custom interests passed.', flush=True)
        garden(browser, args.page, Path(folder)/'fresh.db', None)
        if args.previous:
            garden(browser, args.page, Path(folder)/'legacy.db', args.previous)
        for fragment, name in [('example-alex-guitar','Alex'),('example-electric-guitar','Alex'),
                               ('example-thomas-guitar','Thomas')]:
            with browser.new_page(**MOBILE) as page:
                page.goto(args.page.resolve().as_uri()+'#'+fragment)
                expect(page.locator('#idea')).to_have_value(('an electric guitar' if fragment=='example-electric-guitar'
                                                           else 'guitar')+' for '+name)
                caption(page, name+' · '+('Electric' if fragment=='example-electric-guitar' else 'Acoustic')+' guitar')
        print('Shared room, two phones, personalized seats and named demonstration links passed.')


if __name__ == '__main__':
    main()
