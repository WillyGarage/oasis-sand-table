#!/usr/bin/env python3
"""Exercise the real guest page in Chromium against a simulated table. No device or internet required.

Run python3 tools/test_guest_web.py. Pass --group-photo PATH to exercise automatic face
selection with a real multi-person photo. Requires Python Playwright with Chromium and Pillow.
"""
import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import struct
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'http://oasis.test'
CATALOG = json.loads((ROOT / 'web/guest-paths.json').read_text())
SLOTS = CATALOG['slots']


class Table:
    def __init__(self):
        self.revision = 1
        self.part_protocol = 2
        self.catalog = CATALOG
        self.slots = ['', '', '']
        self.known = False
        self.people = {}
        self.people_rev = 1
        self.photo = False
        self.evolving = False
        self.themes = ['', '', '']
        self.pending = False
        self.reject_next = False
        self.calls = []
        self.parts = [b'', b'', b'']
        self.part_reads = []
        self.clears = []
        self.test_pending_fresh = True

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        def scene():
            return dict(partProtocol=self.part_protocol,rev=str(self.revision), known=self.known, pending=self.pending,
                        slots=self.slots, photo=self.photo, peopleRev=str(self.people_rev),
                        evolving=self.evolving, themes=self.themes, hold=300)
        if path == '/lib/guest-paths.json':
            return route.fulfill(json=self.catalog)
        if path == '/guest-state':
            return route.fulfill(json=scene())
        if path == '/guest-part':
            args = parse_qs(urlsplit(request.url).query)
            if self.pending or not self.known or args['rev'][0] != str(self.revision):
                return route.fulfill(status=409, body='Scene changed.')
            i = int(args['slot'][0])
            self.part_reads.append((i,self.slots[i]))
            return route.fulfill(body=self.parts[i], content_type='application/octet-stream')
        if path == '/guest-evolve':
            fields = parse_qs(request.post_data or '', keep_blank_values=True)
            if fields['rev'][0] != str(self.revision):
                return route.fulfill(status=409,body='Scene changed.')
            self.evolving = fields['on'][0] == '1'
            self.themes = [fields[k][0] for k in ('a','b','c')] if self.evolving else ['', '', '']
            if self.evolving:
                assert any(',' in csv for csv in self.themes)
                assert all(not csv or self.slots[i] in csv.split(',') for i,csv in enumerate(self.themes))
            self.revision += 1
            if self.pending and self.test_pending_fresh:
                assert self.evolving, 'The initiating phone should arm during the pending fresh scene.'
                self.pending, self.known, self.test_pending_fresh = False, True, False
            return route.fulfill(json=scene())
        if path == '/guest-people':
            if request.method == 'POST':
                fields = parse_qs(request.post_data or '', keep_blank_values=True)
                person = {k: fields[k][0] for k in ('name', 'interest', 'subject')}
                self.people[person['name']] = person
                self.people_rev += 1
            return route.fulfill(json=dict(rev=str(self.people_rev), people=list(self.people.values())))
        if path == '/status':
            return route.fulfill(json=dict(state='drawing' if self.pending else 'idle', homed=True,
                                           auto=False, queue=[], fault=0, theta=math.pi/2, rho=1.0))
        if path != '/guest-draw':
            name = Path(path).name or 'index.html'
            file = ROOT / 'web' / ('ring-planner.js' if name == 'guest-ring-planner.js' else name)
            return route.fulfill(path=file) if file.is_file() else route.fulfill(status=404)

        h = request.headers
        if self.reject_next or h['x-guest-rev'] != str(self.revision) or self.pending:
            self.reject_next = False
            return route.fulfill(status=409, body='Scene changed, preview again.')
        assert h['content-type'] == 'application/octet-stream'
        assert request.post_data_buffer is not None
        points = list(struct.iter_unpack('<ff', request.post_data_buffer))
        mode, ids = h['x-guest-mode'], h['x-guest-slots'].split(',')
        assert len(ids) == 3 and all(len(s) <= 40 for s in ids)
        assert all(math.isfinite(t) and 0 <= r <= 1.00001 for t,r in points)
        if mode == 'photo':
            assert 2 <= len(points) <= 12000 and not any(ids)
            assert 'x-guest-counts' not in h
            self.parts = [b'', b'', b'']
            self.clears.append(True)
        else:
            # Firmware v8.16 must reject old browser tabs carrying a legacy erase and draw.
            if 'x-guest-counts' not in h:
                return route.fulfill(status=400, body='Refresh the guest drawing page.')
            counts = [int(n) for n in h['x-guest-counts'].split(',')]
            assert len(counts) == 3 and sum(counts) == len(points)
            assert all(n == 0 or 2 <= n <= 12000 for n in counts)
            if mode == 'fresh':
                assert [bool(v) for v in counts] == [bool(v) for v in ids]
                self.parts = [b'', b'', b'']
                self.clears.append(True)
            else:
                changed = [i for i,old in enumerate(self.slots) if ids[i] != old]
                assert self.known and len(changed) == 1 and [i for i,n in enumerate(counts) if n] == changed
                self.clears.append(bool(self.slots[changed[0]]))
            start = 0
            for i,n in enumerate(counts):
                if not n:
                    continue
                component = points[start:start+n]
                segment = request.post_data_buffer[start*8:(start+n)*8]
                start += n
                assert abs(component[0][1]-1) < .001 and abs(component[-1][1]-1) < .001
                assert all(abs(t-u) <= 3.15 for (t,_),(u,_) in zip(component,component[1:]))
                if ids[i] in self.catalog['subjects']:
                    original = self.catalog['subjects'][ids[i]]['paths'][i]
                    # Exact input demonstrates the browser didn't insert an erased circle or a rim lead-in.
                    assert segment == b''.join(struct.pack('<ff',*point) for point in original)
                for j,slot in enumerate(SLOTS):
                    if i == j:
                        continue
                    cx,cy = slot['center']
                    assert min(math.hypot(r*math.cos(t)-cx,r*math.sin(t)-cy) for t,r in component) > slot['radius']+.035
                self.parts[i] = segment
        self.calls.append((mode, ids, len(points)))
        self.revision += 1
        self.slots = ids
        self.photo = mode == 'photo'
        self.known = mode != 'photo'
        if self.test_pending_fresh and mode == 'fresh':
            self.pending, self.known = True, False
        self.evolving = False
        self.themes = ['', '', '']
        return route.fulfill(json=scene())


def photo_fixture():
    pic = Image.new('RGB', (240, 180), '#e1dbca')
    d = ImageDraw.Draw(pic)
    for cx, y, size, color in [(60, 64, 32, '#6b6c88'), (156, 56, 43, '#9f6644')]:
        d.ellipse((cx-size, y-size, cx+size, y+size), fill='#504c40')
        d.ellipse((cx-size+6, y-size+12, cx+size-5, y+size), fill='#c5a786')
        d.ellipse((cx-size-18, y+size-1, cx+size+18, 226), fill=color)
        d.line((cx-10, y+12, cx+9, y+13), fill='#483c30', width=3)
    out = BytesIO()
    pic.save(out, format='JPEG')
    return dict(name='group.jpg', mimeType='image/jpeg', buffer=out.getvalue())


def suggest(page, text, target='auto'):
    page.get_by_role('button', name='Suggestion', exact=True).click()
    page.locator('#idea').fill(text)
    page.locator('#target').select_option(target)
    page.locator('#previewButton').click()
    page.wait_for_function("document.querySelector('#previewButton').getAttribute('aria-busy') !== 'true'")


def send(page):
    page.locator('#draw:enabled').click(timeout=6000)
    page.wait_for_function("/accepted|keep changing it/.test(document.querySelector('#message').textContent)")


def reference_handoff(phone, picture):
    table = Table()
    table.known, table.slots = True, ['phage', '', 'temple']
    page = phone(table)
    for description in ('a lighthouse beside an open book', 'a phage, books and a rooftop'):
        suggest(page, description+' for Alex')
        assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
        page.locator('#useReference').click()
        assert page.locator('#photoTarget').input_value() == '1'
        assert page.locator('#referenceSubject').inner_text() == description[2:].capitalize()+' for Alex'
        assert not table.calls
    request = 'a garden wheelbarrow for Alex'
    suggest(page, request)
    page.get_by_role('button', name='Use a reference picture').click()
    assert page.locator('#photoMode').input_value() == 'whole'
    assert page.locator('#photoTarget').input_value() == '1'
    assert page.locator('#referenceSubject').inner_text() == 'Garden wheelbarrow for Alex'
    page.locator('#file').set_input_files(picture)
    page.locator('#previewButton').click()
    page.locator('#draw:enabled').wait_for()
    assert not table.calls and 'empty' in page.locator('#effect').inner_text()
    send(page)
    assert table.slots[0]=='phage' and table.slots[1].startswith('photo-garden-wheelbarrow-') and table.slots[2]=='temple'
    assert page.evaluate("JSON.parse(localStorage.getItem('oasis-guest-places-v1')).names[1]") == 'Alex'
    page.get_by_role('button', name='Suggestion', exact=True).click()
    assert page.locator('#idea').input_value() == request

    # A filled or subsequently changed place needs a fresh choice before any submission.
    suggest(page, 'a redwood treehouse')
    page.locator('#useReference').click()
    target = page.locator('#photoTarget')
    assert target.input_value() == '' and target.locator('option').evaluate_all('(opts)=>opts.map(o=>o.value)') == ['', '0', '1', '2']
    assert not page.locator('#file').input_value()
    page.locator('#file').set_input_files(picture)
    page.locator('#previewButton').click()
    page.wait_for_function("document.querySelector('#error').textContent.includes('Choose a guest place')")
    target.select_option('0')
    page.locator('#previewButton').click()
    page.locator('#draw:enabled').wait_for()
    table.revision += 1
    page.locator('#draw').click()
    page.wait_for_function("document.querySelector('#draw').disabled && document.querySelector('#photoTarget').value === ''")
    assert len(table.calls) == 1
    page.close()


def harvest_choices(phone):
    table = Table()
    table.known, table.slots = True, ['phage', '', 'temple']
    page = phone(table)
    page.get_by_role('button', name='Suggestion', exact=True).click()
    shelf = page.locator('#thanksgivingDrawings')
    shelf.locator('summary').click()
    assert shelf.get_by_role('button').count() == 24
    for subject, words in [('cornucopia', 'a horn of plenty'), ('maple_leaf', 'a fall maple leaf'),
                           ('acorn', 'an acorn'), ('acorn', 'a single acorn'),
                           ('desk_lamp', 'an adjustable desk lamp with two hinged arms and a tilted shade'),
                           ('desk_lamp', 'a swing-arm desk lamp'), ('harvest_pear', 'a Bartlett pear'),
                           ('harvest_pear', 'a pear cut in half'), ('harvest_wheat', 'an ear of wheat'),
                           ('harvest_wheat', 'a stalk of wheat'), ('crescent_roll', 'a butter croissant'),
                           ('harvest_basket', 'a basket of apples'), ('oven_mitt', 'an oven glove'), ('rolling_pin', 'a wooden rolling pin'), ('pineapple_with_ring', 'a pineapple with a cut ring'),
                           ('gravy_boat', 'a sauce boat'), ('turkey_leg', 'a turkey drumstick'),
                           ('pumpkin_pie', 'a slice of pumpkin pie with whipped cream'),
                           ('lattice_pie', 'a whole lattice apple pie'),
                           ('pilgrim_hat', 'a pilgrim hat with a buckle'),
                           ('roast_turkey', 'a whole roasted turkey on a serving platter'),
                           ('dinner_candle', 'a lit candle in a holder with a handle'),
                           ('caramel_apple', 'a caramel apple on a wooden stick'),
                           ('mayflower_ship', 'the Mayflower'), ('mayflower_ship', 'the Mayflower sailing ship'),
                           ('turkey_leg', 'a roasted turkey leg'), ('wishbone', 'a turkey wish bone')]:
        page.locator('#idea').fill('an unfinished drawing for Alex')
        shelf.get_by_role('button', name='Preview '+CATALOG['subjects'][subject]['label'], exact=True).click()
        page.locator('#draw:enabled').wait_for()
        assert page.locator('#idea').input_value() == 'an unfinished drawing for Alex'
        expected = page.locator('#drawing').evaluate('canvas => canvas.toDataURL()')
        suggest(page, words+' for Alex')
        assert page.locator('#drawing').evaluate('canvas => canvas.toDataURL()') == expected
        assert not table.calls
    send(page)
    assert table.slots == ['phage', 'wishbone', 'temple']
    suggest(page, 'an oak leaf and an acorn for Alex')
    assert page.locator('#key li').nth(1).evaluate('li => li.firstChild.textContent.trim()') == 'Acorn with an oak leaf'
    suggest(page, 'a turkey for Alex')
    assert page.locator('#key li').nth(1).evaluate('li => li.firstChild.textContent.trim()') == 'Turkey'
    suggest(page, 'a turkey leg decorated with my initials for Alex')
    assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
    suggest(page, 'a wishbone carved from a maple branch for Alex')
    assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
    suggest(page, 'a roast turkey carved with initials for Alex')
    assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
    suggest(page, 'a feathered pilgrim hat for Alex')
    assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
    suggest(page, 'a desk lamp with a stained glass shade for Alex')
    assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
    suggest(page, 'a whole pumpkin pie for Alex')
    assert page.locator('#useReference').is_visible() and not page.locator('#draw').is_enabled()
    page.close()


def photo_picker(page, group_file):
    def preview():
        page.locator('#previewButton').click()
        page.locator('#draw:enabled').wait_for()

    def sand():
        return page.locator('#drawing').evaluate('canvas => canvas.toDataURL()')

    def frame(rect):
        x, y, w, h = (rect[k] for k in ('x','y','width','height'))
        page.mouse.move(x+w*.04, y+h*.04)
        page.mouse.down()
        page.mouse.move(x+w*.96, y+h*.96, steps=8)
        page.mouse.up()
        page.locator('#draw:enabled').wait_for()

    source = page.locator('#sourceFrame')
    boxes = page.locator('#faceBoxes button')
    selected = page.locator('#faceBoxes button[aria-pressed=true]')
    file_input = page.locator('#file')
    page.get_by_role('button', name='Photo', exact=True).click()
    file_input.set_input_files(photo_fixture())
    preview()
    original = sand()
    page.locator('#frameFace').click()
    source.scroll_into_view_if_needed()
    rect = source.bounding_box()
    assert rect == page.locator('#photoImage').bounding_box()
    # The synthetic photo contains a head at (156,56) roughly 80 pixels wide.
    frame(dict(x=rect['x']+rect['width']*115/240, y=rect['y']+rect['height']*16/180,
               width=rect['width']/3, height=rect['height']*80/180))
    assert page.locator('#faceBoxes .frame').count() == 1 and original != sand()
    page.locator('#photoMode').select_option('whole')
    preview()
    assert page.locator('#faceActions').is_hidden() and not boxes.count()
    if not group_file:
        return

    file_input.set_input_files(group_file)
    page.locator('#photoMode').select_option('one')
    preview()
    assert boxes.count() >= 2 and selected.first.get_attribute('aria-label') == 'Draw face 1'
    original = sand()
    boxes.nth(1).click()
    page.locator('#draw:enabled').wait_for()
    assert selected.first.get_attribute('aria-label') == 'Draw face 2' and sand() != original
    page.locator('#photoTarget').select_option('1')
    preview()
    assert selected.first.get_attribute('aria-label') == 'Draw face 2'
    # Compare the actual outgoing binary drawing with that person's route in this exact place.
    expected = page.evaluate("""async slot => {
      const result = await GuestPhoto.fromFile(document.querySelector('#file').files[0], {face:1});
      return Array.from(new Uint8Array(GuestArt.buffer(GuestArt.pathForPhoto(result.points,slot))));
    }""", SLOTS[1])
    with page.expect_request('**/guest-draw') as command:
        send(page)
    assert command.value.post_data_buffer == bytes(expected)
    page.locator('#photoTarget').select_option('full')
    page.locator('#photoMode').select_option('group')
    preview()
    while selected.count() > 1:
        selected.first.click()
        page.locator('#draw:enabled').wait_for()
    selected.first.click()
    assert selected.count() == 1 and 'before removing' in page.locator('#faceHelp').inner_text()
    page.locator('#frameFace').click()
    source.scroll_into_view_if_needed()
    frame(boxes.first.bounding_box())
    assert selected.count() == 2 and '2 faces selected' in page.locator('#effect').inner_text()
    # Another file containing the same pixels must clear both earlier face choices.
    file_input.set_input_files(dict(name='another-group.jpg',mimeType='image/jpeg',buffer=group_file.read_bytes()))
    page.locator('#photoMode').select_option('one')
    preview()
    assert selected.first.get_attribute('aria-label') == 'Draw face 1'
    assert sand() == original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group-photo', type=Path)
    parser.add_argument('--reference-picture', type=Path, help='Reference illustration to import for the unfamiliar guest request')
    args = parser.parse_args()
    table = Table()
    errors = []
    with sync_playwright() as pw:
        cached = sorted((Path.home()/'.cache/ms-playwright').glob('chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(**({'executable_path': str(cached[-1])} if cached else {})) as browser:
            def phone(device=table):
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                page.context.route('**/*', lambda r: device.handle(r) if r.request.url.startswith(ORIGIN+'/')
                                   else r.abort())
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(ORIGIN+'/lib/guest.html')
                page.locator('#previewButton:enabled').wait_for()
                return page

            host, guest = phone(), phone()
            assert host.locator('#key li').count() == 3
            # Guest interests can contain multiple hobbies, negations and unfamiliar topics.
            subjects = {key: value['label'] for key, value in CATALOG['subjects'].items()}
            ideas = host.evaluate("""subjects => [
                'Thomas studies bacteriophages', 'Alex is a teacher', 'Lek is from Thailand',
                'Enjoys gardening and plays the violin', 'Not into golf but loves knitting',
                'Studies knot theory', 'Collects compasses',
            ].map(s => GuestArt.interestIdeas(s, {subjects}).map(item => {
                if (item.glyph && !GuestArt.glyphStrokes(item.glyph).length) throw Error('Empty drawing');
                return item.id;
            }))""", subjects)
            assert ideas[0] == ['phage', 'dna', 'symbol-1f52c']
            assert ideas[1][:2] == ['books', 'classroom'] and ideas[2] == ['temple', 'thailand', 'elephant']
            assert ideas[3][:2] == ['symbol-1f331', 'symbol-1f3bb']
            assert ideas[4] == ['symbol-1f9f6'] and ideas[5] == []
            assert ideas[6] == ['symbol-1f9ed']
            host.locator('#addBox summary').click()
            host.locator('#personName').fill('Gwen')
            host.locator('#personIdea').fill('plays violin')
            host.locator('#addGuest button').click()
            host.wait_for_function("document.querySelector('#roster').textContent.includes('Gwen')")
            guest.wait_for_function("document.querySelector('#roster').textContent.includes('Gwen')")
            assert guest.locator('#roster input:checked').count() == 3
            assert table.people['Gwen']['subject'].startswith('glyph-')
            host.locator('#previewButton').click()
            guest.locator('#previewButton').click()
            host.locator('#keepChanging').check()
            assert 'Rocket' in host.locator('#alternate0').input_value()
            host.locator('#alternate0').fill('Bacteriophage, Double helix')
            send(host)
            assert table.slots == ['phage', 'books', 'temple']
            # A tab left open on the previous release must never submit its old circle-erase path.
            unchanged = (table.revision, table.slots.copy(), table.parts.copy(), len(table.calls))
            old_status = host.evaluate('''async rev => (await fetch('/guest-draw',{
              method:'POST',headers:{'Content-Type':'application/octet-stream',
              'X-Guest-Mode':'edit','X-Guest-Rev':String(rev),'X-Guest-Slots':'guitar,books,temple'},
              body:new Float32Array([0,1,0,.5,0,1])})).status''',table.revision)
            assert old_status == 400 and unchanged == (table.revision, table.slots, table.parts, len(table.calls))
            assert table.evolving and table.themes == ['phage,dna', 'books,guitar,clapper_alt,classroom','temple,elephant,hotpot,thailand']
            # The other phone prepared a whole-scene drawing against yesterday's revision.
            guest.locator('#draw').click()
            guest.wait_for_function("document.querySelector('#error').textContent.includes('changed')")
            assert len(table.calls) == 1
            suggest(host, 'a phage, books and a Thai rooftop')
            assert host.locator('#draw').text_content() == 'Draw this scene'
            # An addressee identifies a place, even when the subject is an uncatalogued symbol.
            suggest(host, 'a violin for Thomas')
            assert host.locator('#draw').text_content() == 'Replace Bacteriophage'
            assert 'whole table with the fine spiral' in host.locator('#effect').inner_text()
            assert 'violin' in host.locator('#key li').first.inner_text().lower()
            for words, title in [('an electric guitar', 'Electric guitar'), ('an acoustic guitar', 'Acoustic guitar')]:
                suggest(host, words+' for Thomas')
                assert host.locator('#key li').first.evaluate('li => li.firstChild.textContent.trim()') == title
            for words, title in [('a stack of two books', 'Two stacked books'), ('three stacked books', 'Stack of books')]:
                suggest(host, words+' for Thomas')
                assert host.locator('#key li').first.evaluate('li => li.firstChild.textContent.trim()') == title
            for words in ('a lotus', 'a lotus flower', 'a lotus flower on a lily pad'):
                suggest(host, words+' for Lek')
                assert host.locator('#key li').nth(2).evaluate('li => li.firstChild.textContent.trim()') == 'Lotus blossom on a leaf'
            suggest(host, 'a flurgle for Lek')
            assert not host.locator('#draw').is_enabled() and 'flurgle' in host.locator('#error').inner_text()
            # Carol's phone may submit meanwhile: receiving a conflict must not lose the new drawing.
            suggest(host, 'Replace the phage with a guitar')
            table.reject_next = True
            host.locator('#draw').click()
            host.wait_for_function("document.querySelector('#error').textContent.includes('Scene changed')")
            assert len(table.calls) == 1
            suggest(host, 'Replace the phage with a guitar')
            send(host)
            assert table.slots == ['guitar', 'books', 'temple']
            assert table.evolving and set(table.themes[0].split(',')) == {'guitar','phage','dna'}
            guest.wait_for_function("document.querySelector('#keepChanging').checked")
            with guest.expect_response('**/guest-evolve'):
                guest.locator('#keepChanging').uncheck()
            guest.wait_for_function("!document.querySelector('#keepChanging').checked")
            assert not table.evolving
            suggest(host, 'A guitar leaning against my books')
            send(host)
            assert table.slots[1] == 'guitar_books'
            suggest(host, 'replace the rooftop with a rocket')
            send(host)
            assert table.slots[2] == 'rocket'
            suggest(host, 'a whale beside the rocket')
            send(host)
            assert table.slots[2].startswith('pair_') and table.slots[2].endswith('__rocket')
            newcomer = phone()  # Independent storage; the pair label and artwork reconstruct from the slot ID.
            assert 'whale beside rocket' in newcomer.locator('#key').inner_text().lower()
            suggest(host, 'draw a flurgle beside a guitar')
            assert not host.locator('#draw').is_enabled() and 'flurgle' in host.locator('#error').inner_text()
            host.locator('#idea').fill('flurgle')
            host.locator('#target').select_option('1')
            rect = host.locator('#pad').bounding_box()
            host.mouse.move(rect['x']+30, rect['y']+40)
            host.mouse.down()
            host.mouse.move(rect['x']+120, rect['y']+160, steps=6)
            host.mouse.up()
            host.locator('#previewButton').click()
            send(host)
            assert table.slots[1].startswith('sketch-flurgle-')
            suggest(host, '', '1')
            assert not host.locator('#draw').is_enabled()
            sketch_id, sketch_bytes = table.slots[1], table.parts[1]
            suggest(newcomer, 'books', '0')
            assert 'whole table with the fine spiral' in newcomer.locator('#effect').inner_text()
            send(newcomer)
            assert table.clears[-1] and table.parts[1] == sketch_bytes and (1,sketch_id) in table.part_reads
            suggest(host, 'a sunflower next to my books')
            send(host)
            assert table.slots[0].startswith('pair_') and table.slots[0].endswith('__books')
            host.get_by_role('button', name='Photo', exact=True).click()
            host.locator('#file').set_input_files(photo_fixture())
            host.locator('#photoMode').select_option('group')
            host.locator('#photoTarget').select_option('1')
            host.locator('#previewButton').click()
            send(host)
            portrait_id, portrait_data = table.slots[1], table.parts[1]
            assert portrait_id.startswith('photo-group-photo-')
            suggest(newcomer, 'Thai rooftop', '2')
            send(newcomer)
            assert (1,portrait_id) in table.part_reads and table.parts[1] == portrait_data
            host.locator('#photoTarget').select_option('full')
            host.locator('#previewButton').click()
            host.locator('#draw:enabled').wait_for()
            assert 'found' in host.locator('#effect').inner_text()
            send(host)
            assert table.calls[-1][0] == 'photo'
            newcomer.reload()
            newcomer.wait_for_function("document.querySelector('#previewHeading').textContent === 'Photo on the sand'")
            assert 'Starting a new scene clears it' in newcomer.locator('#effect').inner_text()
            # Filling an empty place adds only that drawing. Existing coordinates stay byte-identical.
            host.get_by_role('button',name="Who's here",exact=True).click()
            host.locator('#roster label').filter(has_text='Lek').locator('input').uncheck()
            host.locator('#previewButton').click()
            send(host)
            assert table.slots == ['phage','books',''] and table.clears[-1]
            previous = table.parts[:2]
            suggest(newcomer,'Thai rooftop','2')
            assert 'empty top place' in newcomer.locator('#effect').inner_text()
            send(newcomer)
            assert not table.clears[-1] and table.parts[:2] == previous
            assert table.slots == ['phage','books','temple']
            # Each of three places has a separate 12,000-point playback buffer.
            subjects = dict(CATALOG['subjects'])
            for i, name in enumerate(('phage','books','temple')):
                original = subjects[name]
                paths = list(original['paths'])
                paths[i] = [point for point in paths[i] for _ in range(6)]
                subjects[name] = {**original,'paths':paths}
            table.catalog = {**CATALOG, 'subjects':subjects}
            detailed = phone()
            detailed.get_by_role('button',name="Who's here",exact=True).click()
            detailed.locator('#freshSand').check()
            detailed.locator('#previewButton').click()
            send(detailed)
            assert 12000 < table.calls[-1][2] <= 36000
            # Updated phones never hand a v8.16 component-only edit to old firmware.
            table.part_protocol = 1
            old_firmware_phone = phone()
            suggest(old_firmware_phone,'replace the phage with a guitar')
            assert not old_firmware_phone.locator('#draw').is_enabled()
            assert 'needs the new guest drawing software' in old_firmware_phone.locator('#status').inner_text()
            dinner = Table()
            diner = phone(dinner)
            for request, place, subject in [
                ('a slice of pumpkin pie for Thomas', 0, 'pumpkin_pie'),
                ('a folded paper bird for Alex', 1, 'origami_crane'),
                ('a camping trailer for Lek', 2, 'caravan'),
                ('a baker’s hat for Thomas', 0, 'chef_hat'),
                ('a pumpkin for Thomas', 0, 'pumpkin'),
            ]:
                suggest(diner, request)
                send(diner)
                assert dinner.slots[place] == subject, (request, dinner.slots)
                if dinner.pending:
                    # Like the Mini, publish the new places one revision after acceptance.
                    dinner.pending, dinner.known = False, True
                    dinner.revision += 1
                    diner.reload()
                    diner.locator('#previewButton:enabled').wait_for()
            assert dinner.slots == ['pumpkin', 'origami_crane', 'caravan']
            # An explicit source or the place picker wins without moving a person's seat.
            suggest(diner, 'replace the folded paper bird with a guitar for Thomas')
            send(diner)
            suggest(diner, 'replace the pumpkin with books for Thomas', '2')
            send(diner)
            assert dinner.slots == ['pumpkin', 'guitar', 'books']
            for name, old in [('Thomas', 'Pumpkin'), ('Alex', 'Acoustic guitar')]:
                suggest(diner, 'a pumpkin pie for '+name)
                assert diner.locator('#draw').text_content() == 'Replace '+old
            suggest(diner, 'replace Alex with a pumpkin pie for Thomas')
            assert diner.locator('#draw').text_content() == 'Replace Acoustic guitar'
            # A second phone changes the scene. Even if the exact artwork returns, a
            # new revision cannot inherit old names or give Alex someone else's books.
            stranger = phone(dinner)
            for name in ['Thomas', 'Alex']:
                suggest(stranger, 'a pumpkin pie for '+name)
                assert not stranger.locator('#draw').is_enabled()
            for item in ['a baker’s hat', 'a guitar']:
                suggest(stranger, item, '1')
                send(stranger)
            for name in ['Thomas', 'Alex']:
                suggest(diner, 'a pumpkin pie for '+name)
                assert not diner.locator('#draw').is_enabled() and 'filled' in diner.locator('#error').inner_text()
            # A rejected drawing cannot claim another seat.
            suggest(diner, 'a pumpkin pie for Thomas', '1')
            dinner.reject_next = True
            diner.locator('#draw').click()
            diner.wait_for_function("document.querySelector('#error').textContent.includes('Scene changed')")
            suggest(diner, 'a pumpkin pie for Thomas')
            assert not diner.locator('#draw').is_enabled()
            shared_motif = Table()
            shared_motif.test_pending_fresh = False
            familiar = phone(shared_motif)
            for request in ['books for Thomas', 'a baker’s hat for Alex']:
                suggest(familiar, request)
                send(familiar)
            assert shared_motif.slots == ['books', 'chef_hat', '']
            trial = Table()
            trial.test_pending_fresh = False
            photo_picker(phone(trial), args.group_photo)
            reference_handoff(phone, args.reference_picture or photo_fixture())
            harvest_choices(phone)
            assert not errors, errors
            print(f'{len(table.calls)} drawings passed, including empty-place additions, whole-scene redraws, cross-phone artwork and stale versions.')


if __name__ == '__main__':
    main()
