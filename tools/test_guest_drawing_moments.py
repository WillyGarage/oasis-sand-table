#!/usr/bin/env python3
"""Compare each phone progress view with its exact row in the downloaded guest drawing."""

import argparse
import io
import math
from pathlib import Path
import re
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from check_ring_scene import joined, travel
from test_garden_room import choose, drawing_files, suggest
from test_ring_guest_border import MOBILE, replay
from test_ring_photo import frame


def replay_to(page, bed, parts, end):
    prefix = []
    for part in parts:
        if end <= 0:
            break
        prefix.append(part[:end+1])
        end -= len(part)-1
    return replay(page, bed, *prefix)


def check_subject(page, slot, art, request, legacy, evidence):
    signed = page.evaluate("""([slot,art]) => {
        const live=JSON.parse(document.querySelector('#scene').textContent).live;
        const state=JSON.parse(localStorage.getItem(live.storageKey));
        return {bed:state.bed, ...live.planner.places[slot].revealTargets[art]};
    }""", [slot, art])
    suggest(page, request)
    finished = frame(page)
    files = drawing_files(page, '#downloads')
    assert files == [(f['name'], f['text'].encode()) for f in signed['files']]
    parts = [np.loadtxt(io.BytesIO(data)) for _, data in files]
    dock = [-math.pi/2, 1]
    distance = travel(joined(parts, dock, dock, art))
    choose(page, 'stage', 'cleared')
    picker = page.locator('#guestMoment')
    default = frame(page)
    np.testing.assert_array_equal(default, replay_to(page, signed['bed'], parts, signed['progressIndex']))
    if legacy:
        expect(picker).to_be_hidden()
        return

    moments = signed['progressMoments']
    assert len(moments) == 2 and moments[-1]['endIndex'] == signed['progressIndex']
    expect(picker.locator('option')).to_have_text([m['label'] for m in moments])
    expect(picker).to_have_value('1')
    picker.select_option([])
    expect(picker).to_have_value('1')
    for index, moment in enumerate(moments):
        picker.select_option(str(index))
        end, label = moment['endIndex'], moment['label']
        percentage = math.floor(100*distance[end]/distance[-1] + .5)
        expect(page.locator('.caption')).to_contain_text(label)
        expect(page.locator('.caption')).to_contain_text(f'{percentage}% of the ball’s travel')
        actual = frame(page)
        np.testing.assert_array_equal(actual, replay_to(page, signed['bed'], parts, end))
        if index == 0:
            assert np.any(actual != default), 'The first and second visits show the same sand.'
        if evidence:
            if index == 0:
                page.locator('#shownComposition').screenshot(path=str(evidence/f'{art}-controls.png'))
            page.locator('#guestZoom').click()
            page.locator('.sand-display').screenshot(path=str(evidence/f'{art}-visit-{index+1}.png'))
            page.locator('#guestZoom').click()
        print(f'{art}: {label}, signed row {end}, {percentage}% of travel')
    choose(page, 'stage', 'redrawn')
    np.testing.assert_array_equal(finished, frame(page))
    assert drawing_files(page, '#downloads') == files


def run(browser, gallery, *, legacy=False, evidence=None):
    with browser.new_page(**MOBILE) as page:
        page.goto(gallery.resolve().as_uri()+'#guests')
        suggest(page, 'A phage for Thomas, a guitar for Alex and a Thai rooftop for Lek')
        page.locator('#keep').click()
        expect(page.locator('#keep')).to_be_hidden()
        page.reload()  # Start from the same stored heights used by the independent replay.
        check_subject(page, 0, 'guitar_silhouette', 'An acoustic guitar for Thomas', legacy, evidence)
        check_subject(page, 1, 'books_open', 'An open book for Alex', legacy, evidence)
        if not legacy:
            page.locator('#guestRedraw').select_option('ring')
            choose(page, 'stage', 'cleared')
            expect(page.locator('#guestMoment')).to_be_hidden()
            page.locator('#guestRedraw').select_option('place')
            expect(page.locator('#guestMoment')).to_have_value('1')
            suggest(page, 'An acoustic guitar for Thomas and an open book for Alex')
            choose(page, 'stage', 'cleared')
            labels = page.locator('#guestMoment option').all_text_contents()
            assert any('Thomas' in label and 'finished' in label for label in labels)
            assert any('Alex' in label and 'finished' in label for label in labels)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('--previous', type=Path, help='Earlier signed drawings with one progress frame')
    parser.add_argument('--evidence', type=Path, help='Save the four enlarged phone views')
    args = parser.parse_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        chrome = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))[-1]
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            run(browser, args.gallery, evidence=args.evidence)
            if args.previous:
                # Run today's editor with the earlier embedded scene and its original signed files.
                data = re.compile(r'<script type="application/json" id="scene">.*?</script>', re.S)
                earlier = data.search(args.previous.read_text()).group()
                with tempfile.TemporaryDirectory() as tmp:
                    older = Path(tmp)/'older.html'
                    older.write_text(data.sub(lambda _: earlier, args.gallery.read_text(), count=1))
                    run(browser, older, legacy=True)
