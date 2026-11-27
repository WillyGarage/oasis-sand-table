#!/usr/bin/env python3
"""Check the timed guest preview using the mobile controls and a controllable browser clock."""
import argparse
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

from test_ring_photo import frame


def run(page, url):
    page.goto(url + '?layout=portrait#changing-garden')
    panel = page.locator('#changingGarden')
    button = panel.get_by_role('button')
    status = panel.get_by_role('status')
    key = 'oasis-ring-garden-v1'

    def state():
        return page.evaluate('key => JSON.parse(localStorage.getItem(key))', key)

    def start():
        if not panel.evaluate('el=>el.open'):
            panel.locator('summary').click()
        button.click()
        assert button.inner_text() == 'Stop changing', status.inner_text()

    def tick():
        page.clock.fast_forward(30_000)

    def stopped():
        assert button.inner_text() == 'Start changing'
        held = state()
        tick()
        assert state() == held

    def introduce(name, interest, slot, subject):
        book = page.locator('#peopleBox')
        if not book.evaluate('el=>el.open'):
            book.locator('summary').click()
        page.locator('#personPick').select_option('')
        page.locator('#personName').fill(name)
        page.locator('#personInterest').fill(interest)
        page.locator('#personPlace').select_option(str(slot))
        page.locator('#personDrawing').select_option(subject)
        if subject == 'sketch':
            canvas = page.locator('#sketchPad')
            canvas.scroll_into_view_if_needed()
            box = canvas.bounding_box()
            x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
            page.mouse.move(x-30, y+16)
            page.mouse.down()
            page.mouse.move(x+4, y-25, steps=5)
            page.mouse.move(x+34, y+16, steps=5)
            page.mouse.up()
        page.locator('#personSubmit').click()
        page.locator('#keep').click()

    page.clock.install(time='2026-11-20T18:00:00Z')
    page.clock.pause_at('2026-11-20T18:01:00Z')
    assert panel.evaluate('el=>el.open') and button.is_visible()
    assert page.locator('#layout').input_value() == 'garden'
    stopped()
    assert state() is None, 'Opening the example should not keep any drawing'
    initial = frame(page)
    n = len(initial)
    y, x = np.mgrid[-1:1:complex(n), -1:1:complex(n)]
    r = np.hypot(x, y)
    protected = ((r < .32) | ((r > .81) & (r < .97))) & (abs(x) > .06)

    start()
    page.clock.fast_forward(29_999)
    assert state() is None
    before = ['phage', 'books', 'temple']
    for i in range(6):
        page.clock.fast_forward(1 if i == 0 else 30_000)
        after = state()['ids']
        slot = i % 3
        assert [j for j in range(3) if before[j] != after[j]] == [slot]
        assert len(set(after)) == len(after)
        eligible = page.evaluate('''slot => {
          const g = JSON.parse(document.querySelector('#scene').textContent).live.planner;
          return GuestArt.interestIdeas(['Bacteriophages',GuestArt.alexInterest || 'Teaching','Thailand'][slot], g).map(a=>a.id);
        }''', slot)
        assert after[slot] in eligible
        assert np.array_equal(frame(page)[protected], initial[protected]), 'A neighboring zone changed'
        before = after
    button.click()
    stopped()

    start()
    page.locator('#idea').fill('a guitar for Thomas')
    stopped()
    page.get_by_role('button', name='Preview suggestion').click()
    button.click()
    assert 'current edit' in status.inner_text() and page.locator('#keep').is_visible()
    page.locator('#keep').click()
    assert state()['ids'][0] == 'guitar'

    start()
    page.locator('#layout').select_option('portrait')
    held = state()
    assert not panel.is_visible()
    tick()
    assert state() == held
    page.locator('#layout').select_option('garden')
    page.goto(url + '#changing-garden')
    page.reload()
    start()
    page.evaluate("""Object.defineProperty(document,'hidden',{configurable:true,value:true});
                     document.dispatchEvent(new Event('visibilitychange'));
                     delete document.hidden;""")
    stopped()
    start()
    page.reload()
    stopped()

    # Replace two of the original guests. A known symbol can change a guest
    # whose interest has only one native choice; unknown interests get no guesses.
    introduce('Ada', 'stargazing', 0, 'telescope')
    introduce('Blair', 'qzxwgy', 1, 'books')
    start()
    tick()
    saved = state()
    assert saved['labels'][saved['ids'][0]] == 'Ringed planet'
    planet_path = saved['custom'][saved['ids'][0]]
    assert saved['ids'][1] == 'books'
    tick()
    assert state()['ids'][2] != saved['ids'][2]
    tick()
    saved = state()
    assert saved['labels'][saved['ids'][0]] == 'Comet'
    assert saved['custom'][saved['ids'][0]] != planet_path
    button.click()
    introduce('Sky', 'stargazing', 0, 'sketch')
    saved = state()
    sketch = saved['ids'][0]
    assert sketch.startswith('sketch-')
    start()
    for _ in range(3):
        tick()
        changed = state()
        assert changed['ids'][:2] == [sketch, 'books'] and changed['ids'][2] != saved['ids'][2]
        assert changed['custom'][sketch] == saved['custom'][sketch]
        saved = changed
    button.click()
    # This unassigned pictograph is a suggestion, but has no drawable glyph
    # in the browser's fonts. Even a font which shows the missing-glyph box
    # should never turn that box into a guest drawing.
    missing = chr(0x1FAFF)
    check_missing = page.evaluate('''ch => {
      const data = JSON.parse(document.querySelector('#scene').textContent).live.planner;
      const ideas = GuestArt.interestIdeas(ch, data);
      function signature(value) {
        try { return JSON.stringify(GuestArt.glyphStrokes(value)[0]); } catch { return ''; }
      }
      return [ideas.length, ['','\\u0378',String.fromCodePoint(0x10ffff)].map(signature).includes(signature(ch))];
    }''', missing)
    assert check_missing == [1, True]
    introduce('Casey', missing, 2, 'temple')
    button.click()
    assert 'No other drawings' in status.inner_text()
    stopped()
    print('Six fair turns, the full 30-second hold, both protected zones, personal interests, '
          'sketch retention, unknown interests, the stop button, manual edits, layout switching, '
          'tab hiding and page reload passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path)
    args = parser.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            run(page, args.page.resolve().as_uri())
            assert not errors, errors
