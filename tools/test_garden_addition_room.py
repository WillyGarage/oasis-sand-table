#!/usr/bin/env python3
"""Check that an attached garden only adds ink to the previously kept base artwork.

Run with the current fitted open gallery and an earlier gallery built for the same table.
The two local phone sessions share a simulated controller and one persistent room.
"""
import argparse
import copy
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright

from garden_room import name_key
from test_attached_garden import Table, served, wait_table
from test_garden_reveal_room import change, put
from test_garden_room import API, open_room, suggest
from test_ring_guest_border import MOBILE, save


def addition_request(page, room, choices):
    """Assemble only published, calibrated addition files. Ordinary state comes from the saved room."""
    catalog = page.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner")
    files, parts = [], []
    for place, source, target in choices:
        signed = catalog['places'][place]['additions'][source][target]['files']
        parts.append({'place':place, 'addFrom':source, 'count':len(signed)})
        for file in signed:
            files.append(dict(file, name=f'guest-ring-{len(files)+1}.thr'))
    place, _, target = choices[0]
    body = change(page, room['state'], room['revision'], place, target, files)
    motion = {'zone':'middle', 'files':files}
    if len(parts) == 1:
        motion.update(place=place, addFrom=choices[0][1])
    else:
        motion['parts'] = parts
    body['motion'] = motion
    state = body['state']
    book = state.get('guestBook')
    for place, _, target in choices:
        state['ids'][place] = target
        for person in book['people'] if book else ():
            if name_key(person['name']) == book['active'][place]:
                person['subject'] = target
    return body


def exercise(browser, gallery, earlier, db):
    table = Table(db)
    with served(earlier, db, table, prepared=True) as url, browser.new_page(**MOBILE) as host:
        open_room(host, url)
        jobs = host.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.setup")
        suggest(host, 'a guitar for Thomas, books for Alex and a Thai rooftop for Lek')
        prepared, _ = save(host, url+API)
        assert prepared['state']['ids'] == ['guitar_silhouette','books_open','temple_gable']
        jobs.extend(prepared['motion']['files'])
        old = host.request.get(url+API).json()
    guitar = (0,'guitar_silhouette','guitar_note')
    book = (1,'books_open','book_pencil')
    roof = (2,'temple_gable','temple_crescent')
    with served(gallery, db, table) as url, browser.new_page(**MOBILE) as phone:
        open_room(phone, url)
        edition = phone.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.edition")
        if old['state']['edition'] != edition:
            previous = phone.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.previousOpening.edition")
            assert old['state']['edition'] == previous
            old['state']['edition'] = edition
        assert phone.request.get(url+API).json() == old
        # These files are authentic for seat 1 or 2, but the base in those
        # places is respectively the guitar and the book, not the roof.
        for other in (0,1):
            wrong_seat = addition_request(phone,old,[(other,roof[1],roof[2])])
            put(phone,url,wrong_seat,400)
        single = addition_request(phone, old, [roof])
        for extra in [{'fill':True},{'earlyFrom':roof[1]}, {'customReveal':{}}, {'addFrom':guitar[1]}]:
            invalid = dict(single, motion=dict(single['motion'], **extra))
            put(phone,url,invalid,400)
        bare = dict(single, motion={'zone':'middle','files':single['motion']['files'],'place':roof[0]})
        put(phone,url,bare,400)
        additions = addition_request(phone,old,[guitar,book,roof])
        mixed_source = copy.deepcopy(additions)
        mixed_source['motion']['parts'][1]['addFrom'] = 'temple_gable'
        put(phone,url,mixed_source,400)
        # Alter a single in-zone coordinate while preserving the dock and
        # filenames. The trusted excursion must match every exported point.
        altered = copy.deepcopy(additions)
        part = altered['motion']['files'][altered['motion']['parts'][0]['count']]
        lines = part['text'].splitlines()
        index = len(lines)//2
        angle, radius = map(float,lines[index].split())
        lines[index] = f'{angle+.001:.5f} {radius:.5f}'
        part['text'] = '\n'.join(lines)+'\n'
        put(phone,url,altered,400)
        assert phone.request.get(url+API).json() == old
        revision = put(phone,url,additions,200).json()['revision']
        jobs.extend(additions['motion']['files'])
        put(phone,url,single,409)
        stored = phone.request.get(url+API).json()
        assert stored['state']['ids'] == ['guitar_note','book_pencil','temple_crescent']

    with served(gallery, db, table) as url, browser.new_page(**MOBILE) as returning:
        open_room(returning,url)
        assert returning.request.get(url+API).json() == stored
        # Make an ordinary change over the decorated roof. The room must
        # subsequently accept a fresh short addition, while retaining Thomas's note.
        suggest(returning, 'a swept Thai rooftop for Lek')
        base, _ = save(returning,url+API)
        assert base['state']['ids'] == ['guitar_note','book_pencil','temple_gable']
        assert 'addFrom' not in base['motion'] and not base['motion'].get('fill')
        jobs.extend(base['motion']['files'])
        fresh = returning.request.get(url+API).json()
        last = addition_request(returning,fresh,[roof])
        assert last['motion']['files'] == single['motion']['files']
        revision = put(returning,url,last,200).json()['revision']
        jobs.extend(last['motion']['files'])
        for n, job in enumerate(jobs,1):
            assert table.dispatched(n)==job
            table.outcome='complete'
        wait_table(returning,url,state='idle',ready=True,queued=0,revision=revision)
        assert len(table.calls)==len(jobs)
        print(f'The room accepted all three additions, rejected mismatched bases and altered files, '
              f'and played all {len(jobs)} files once in order across the upgrade and restart.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery',type=Path)
    parser.add_argument('earlier',type=Path)
    args=parser.parse_args()
    chrome=sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
    with tempfile.TemporaryDirectory() as temp,sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser,args.gallery,args.earlier,Path(temp)/'room.db')
