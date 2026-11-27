#!/usr/bin/env python3
"""Exercise a phrase request, its fallbacks, and its actual sand files from two phones.

    python3 tools/test_garden_phrase.py combined-garden.html [--fixture wheelbarrow.png]

Use a fitted three-zone garden. The renderer and garden database live inside this test.
"""

import argparse
import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

from garden_room import make_server
from test_garden_room import API, caption, drawing_files, keep, open_room, suggest
from test_ring_guest_border import MOBILE
from test_ring_object_photo import checked_save
from test_ring_photo import frame
from test_ring_sketch_crossings import KITE, finger_sketch


def wheelbarrow():
    image = Image.new('RGB', (512, 512), 'white')
    pen = ImageDraw.Draw(image)
    pen.polygon([(89, 177), (391, 177), (299, 292), (164, 278)], fill='black')
    pen.line([(118, 351), (210, 252), (409, 161), (457, 155)], fill='black', width=16)
    pen.line([(245, 272), (287, 361), (319, 250)], fill='black', width=14)
    pen.ellipse((73, 303, 159, 389), outline='black', width=17)
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


class Renderer:
    def __init__(self, png):
        self.png = png
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, phrase):
        self.calls.append(phrase)
        if len(self.calls) == 1:
            self.entered.set()
            if not self.release.wait(timeout=60):
                raise TimeoutError('Phone never released the delayed illustration')
        elif len(self.calls) == 2:
            raise RuntimeError('Simulated unavailable renderer')
        return self.png


@contextmanager
def garden(gallery, database, renderer):
    with make_server(gallery, database, phrase_renderer=renderer) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            renderer.release.set()
            server.shutdown()
            thread.join()


def unknown(page, phrase, guest, generation=True):
    page.locator('#idea').fill(phrase)
    page.get_by_role('button', name='Preview suggestion').click()
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#sketch > summary')).to_be_visible()
    expect(page.locator('#suggestionPhoto')).to_contain_text(guest)
    expect(page.locator('#suggestionPhoto')).to_be_visible()
    generate = page.locator('#generateSuggestion')
    if generation:
        expect(generate).to_be_visible()
        expect(generate).to_contain_text(guest)
    else:
        expect(generate).to_be_hidden()


def phrase_response(page):
    return page.expect_response(lambda r: r.request.method == 'POST' and urlsplit(r.url).path == '/api/phrase')


def error_retry(page, words, status):
    with phrase_response(page) as response:
        page.locator('#generateSuggestion').click()
    result = response.value
    assert result.status == status
    if status == 429:
        assert int(result.headers['retry-after']) > 0
    expect(page.locator('#phraseStatus')).to_have_text(result.json()['error'])
    expect(page.locator('#idea')).to_have_value(words)
    expect(page.locator('#generateSuggestion')).to_be_enabled()
    expect(page.locator('#keep')).to_be_hidden()
    expect(page.locator('#suggestionPhoto')).to_be_visible()
    expect(page.locator('#sketch > summary')).to_be_visible()


def exercise(browser, gallery, db, png):
    words = 'a wheelbarrow for Thomas'
    renderer = Renderer(png)
    errors = []
    with garden(gallery, db, renderer) as url, browser.new_context(**MOBILE) as left, browser.new_context(**MOBILE) as right:
        first, other = left.new_page(), right.new_page()
        for page in (first, other):
            page.on('pageerror', lambda error: errors.append(str(error)))

        first.goto(gallery.resolve().as_uri() + '#guests')
        expect(first.locator('meta[name=oasis-phrase]')).to_have_count(0)
        unknown(first, words, 'Thomas', generation=False)
        first.locator('#suggestionPhoto').click()
        expect(first.locator('#portraitFile')).to_be_visible()
        expect(first.locator('#objectName')).to_have_value('Wheelbarrow')

        for page in (first, other):
            open_room(page, url)
            expect(page.locator('meta[name=oasis-phrase]')).to_have_attribute('content', './api/phrase')
        for phrase in ('a lighthouse beside an open book', 'a gramophone with a curved horn and a vinyl record'):
            unknown(first, phrase+' for Alex', 'Alex')
            expect(first.locator('#suggestionPhoto')).to_contain_text(phrase[2:].capitalize())
        for phrase in ('a guitar beside', 'a portrait of Lek beside a lighthouse'):
            first.locator('#idea').fill(phrase+' for Alex')
            first.get_by_role('button', name='Preview suggestion').click()
            expect(first.locator('#generateSuggestion')).to_be_hidden()
            expect(first.locator('#keep')).to_be_hidden()
        # An exact reviewed library subject is available without the model.
        # Keep the full wording when it specifies a different drawing.
        for subject in ('paint roller', 'binoculars', 'traffic cone'):
            suggest(first, subject+' for Alex')
            caption(first, 'Alex · '+subject.capitalize())
            expect(first.locator('#generateSuggestion')).to_be_hidden()
            unknown(first, 'a striped '+subject+' for Alex', 'Alex')
        for exact in ('a slot machine', 'a washing machine', 'sewing'):
            suggest(first, exact+' for Alex')
            expect(first.locator('#keep')).to_be_visible()
            expect(first.locator('#generateSuggestion')).to_be_hidden()
        assert not renderer.calls
        # Close the private trial draft before following the other phone's garden.
        first.reload()
        expect(first.locator('#idea')).to_have_value('')
        suggest(other, 'a rocket for Alex')
        keep(other)
        caption(first, 'Alex · Rocket')
        api = url + API
        initial = first.request.get(api).json()
        original = frame(other)

        unknown(first, 'a lighthouse for Thomas', 'Thomas')
        fallback = 'Windcatcher for Lek'
        unknown(other, fallback, 'Lek')
        # Hold one genuine HTTP request while a second phone asks the busy host for help.
        with phrase_response(first) as delayed:
            first.locator('#generateSuggestion').click()
            assert renderer.entered.wait(timeout=5)
            expect(first.locator('#phraseStatus')).to_be_visible()
            expect(first.locator('#generateSuggestion')).to_be_disabled()
            error_retry(other, fallback, 429)
            unknown(other, 'a lighthouse for Lek', 'Lek')
            with phrase_response(other) as shared:
                other.locator('#generateSuggestion').click()
                first.locator('#idea').fill('a harvest wagon for Alex')
                renderer.release.set()
        assert delayed.value.status == shared.value.status == 200
        expect(other.locator('#keep')).to_have_text('Keep Lek’s drawing')
        other.reload()
        unknown(other, fallback, 'Lek')
        finger_sketch(other, 'Windcatcher', KITE)
        expect(first.locator('#idea')).to_have_value('a harvest wagon for Alex')
        expect(first.locator('#keep')).to_be_hidden()
        assert np.array_equal(frame(first), original)
        assert first.request.get(api).json() == initial
        assert len(renderer.calls) == 1

        # Failure and retry must preserve the original request. The independent phone
        # imports the very same pixels by hand, to check the generated engraving exactly.
        unknown(first, words, 'Thomas')
        error_retry(first, words, 503)
        other.reload()
        caption(other, 'Alex · Rocket')
        unknown(other, words, 'Thomas')
        other.locator('#suggestionPhoto').click()
        expect(other.locator('#portraitPlace')).to_have_value('0')
        other.locator('#portraitFile').set_input_files({'name':'reference.png', 'mimeType':'image/png', 'buffer':png})
        other.locator('#portraitSubmit').click()
        caption(other, 'Thomas · Wheelbarrow')
        expect(other.locator('#keep')).to_be_visible()
        reference_files = [data for _, data in drawing_files(other, '#downloads')]
        reference_sand = frame(other)
        other.reload()
        caption(other, 'Alex · Rocket')

        with phrase_response(first) as success:
            first.locator('#generateSuggestion').click()
        result = success.value
        assert result.status == 200 and result.headers['content-type'] == 'image/png'
        assert [call.casefold() for call in renderer.calls] == ['lighthouse','wheelbarrow','wheelbarrow']
        assert result.request.post_data_json == {'phrase':renderer.calls[-1]}
        caption(first, 'Thomas · Wheelbarrow')
        expect(first.locator('#keep')).to_have_text('Keep Thomas’s drawing')
        # Chromium may refetch a no-cache image via GET when DevTools requests
        # response.body(). Inspect the actual POST result held by the form.
        url_data = first.locator('#portraitFile').evaluate('''input => new Promise(resolve => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.readAsDataURL(input.files[0]);
        })''')
        received = base64.b64decode(url_data.split(',', 1)[1], validate=True)
        assert received == png
        with Image.open(io.BytesIO(received)) as image:
            assert image.format == 'PNG'
            image.verify()
        assert first.request.get(api).json() == initial
        assert np.array_equal(frame(other), original)
        sand = frame(first)
        assert np.array_equal(sand, reference_sand)
        changed = np.any(sand != original, axis=-1).sum()
        assert changed > 200, changed
        files = drawing_files(first, '#downloads')
        assert [data for _, data in files] == reference_files
        opened = first.evaluate("JSON.parse(document.querySelector('#scene').textContent).live.planner.openSubject || ''")
        kept = checked_save(first, other, api, initial['state'], 'Wheelbarrow', initial['state']['ids'][0] == opened, files)
        suggest(other, 'Wheelbarrow for Lek')
        caption(other, 'Lek · Wheelbarrow')
        expect(other.locator('#generateSuggestion')).to_be_hidden()
        keep(other)
        caption(first, 'Lek · Wheelbarrow')
        copies = first.request.get(api).json()['state']
        assert copies['ids'] == [kept['ids'][0], kept['ids'][1], kept['ids'][0]]
        assert copies['custom'] == kept['custom'] and len(renderer.calls) == 3

        # The renderer returns the same wheelbarrow pixels for the unfamiliar
        # noun. Compare each generated pair to the independently kept drawing.
        before_pairs = len(renderer.calls)
        for wording in ('{} beside an open book', 'an open book above {}'):
            placement = wording.format('a lighthouse')
            unknown(first, placement+' for Alex', 'Alex')
            with phrase_response(first) as mixed:
                first.locator('#generateSuggestion').click()
            assert mixed.value.request.post_data_json == {'phrase':'lighthouse'}
            expect(first.locator('#keep')).to_have_text('Keep Alex’s drawing')
            suggest(other, wording.format('the saved Wheelbarrow')+' for Alex')
            expect(other.locator('#keep')).to_be_visible()
            assert drawing_files(first, '#downloads') == drawing_files(other, '#downloads')
            assert np.array_equal(frame(first), frame(other))
            first.reload()
            other.reload()
        assert renderer.calls[before_pairs:] == ['lighthouse']
        # A separate kept book should still be used as drawn. Request only
        # the missing machine to complete the explicitly positioned pair.
        unknown(first, 'a sewing machine beside an open book for Alex', 'Alex')
        with phrase_response(first) as machine_pair:
            first.locator('#generateSuggestion').click()
        assert machine_pair.value.request.post_data_json == {'phrase':'sewing machine'}
        expect(first.locator('#keep')).to_be_visible()
        first.reload()

        # A reference photo already contains the complete composition.
        unknown(first, 'a lighthouse beside an open book for Alex', 'Alex')
        first.locator('#suggestionPhoto').click()
        first.locator('#portraitFile').set_input_files({'name':'scene.png', 'mimeType':'image/png', 'buffer':png})
        first.locator('#portraitSubmit').click()
        expect(first.locator('#keep')).to_be_visible()
        suggest(other, 'the saved Wheelbarrow for Alex')
        assert drawing_files(first, '#downloads') == drawing_files(other, '#downloads')
        first.reload()
        # A described machine can include a familiar activity and a separate
        # support. The generator needs the whole request to draw the device.
        for words in ('an antique hand water pump with a long curved lever and a side spout',
                      'an old-fashioned sewing machine on a small table', 'a knitting machine'):
            requested = words.split(' ', 1)[1].capitalize()
            unknown(first, words+' for Alex', 'Alex')
            with phrase_response(first) as generated:
                first.locator('#generateSuggestion').click()
            assert generated.value.request.post_data_json == {'phrase': requested}
            expect(first.locator('#keep')).to_be_visible()
            exported = drawing_files(first, '#downloads')
            keep(first)
            other.goto('about:blank')
            open_room(other, url)
            caption(other, 'Alex · '+requested)
            assert other.evaluate('document.documentElement.scrollWidth') == MOBILE['viewport']['width']
            assert drawing_files(other, '#roomFiles') == exported
            first.reload()
        # A different drawing with the same name is already saved. Open the
        # reviewed lines exactly and wait for Keep.
        packet = (Path(__file__).resolve().parents[1] / 'patterns/guest-rings/sewing-machine.oasisguest').read_bytes()
        drawing = json.loads(packet)
        link = url+'/garden?layout=garden#guest-drawing/'+base64.urlsafe_b64encode(packet).decode().rstrip('=')
        before = first.request.get(api).json()
        first.goto(link)
        expect(first.locator('#keep')).to_be_visible()
        assert first.request.get(api).json()['revision'] == before['revision']
        exported = drawing_files(first, '#downloads')
        keep(first)
        after = first.request.get(api).json()['state']
        assert after['custom'][after['ids'][1]] == drawing['points']
        other.goto('about:blank')
        open_room(other, url)
        assert drawing_files(other, '#roomFiles') == exported
        assert not errors, errors
        return int(changed), sum(len(data.splitlines()) for _, data in files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('--fixture', type=Path, help='use an existing local wheelbarrow PNG')
    args = parser.parse_args()
    png = args.fixture.read_bytes() if args.fixture else wheelbarrow()
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as playwright:
        chrome = Path(playwright.chromium.executable_path)
        if not chrome.is_file():
            chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with playwright.chromium.launch(executable_path=chrome) as browser:
            changed, rows = exercise(browser, args.gallery, Path(temp) / 'garden.db', png)
    print(f'Wheelbarrow preview changed {changed:,} pixels and matched all {rows:,} reference motion rows. '
          'Two guests shared the kept files. Busy, failure, retry, stale input, photo, sketch and static gallery passed.')
