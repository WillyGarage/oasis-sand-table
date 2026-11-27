#!/usr/bin/env python3
"""Exercise the whole-Mini glasses option on two independent close-up pair photos."""
import argparse
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import tempfile

import numpy as np
from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from test_mini_portrait_names import ROOT, phone, preview, submit
from wide_portrait import chromium


def upload(page, photo, *, target='full', mode='group', heads=True, caption=''):
    page.get_by_role('button', name='Photo', exact=True).click()
    page.locator('#photoTarget').select_option(target)
    page.locator('#photoMode').select_option(mode)
    page.locator('#file').set_input_files(photo)
    page.locator('#centerHead').set_checked(heads)
    if caption:
        page.locator('#photoName').fill(caption)
    preview(page)


def export(browser, assets, photo, *, eyes=None, smile=None, **settings):
    with phone(browser, assets) as page:
        upload(page, photo, **settings)
        toggle = page.get_by_label('Show eyes inside glasses')
        if eyes == 'hidden':
            expect(toggle).to_be_hidden()
        elif eyes:
            expect(toggle).to_be_checked()
            if eyes in ('off', 'again'):
                toggle.uncheck()
                expect(page.locator('#draw')).to_be_enabled()
            if eyes == 'again':
                toggle.check()
                expect(page.locator('#draw')).to_be_enabled()
        mouth = page.get_by_label('Trace the photographed smile')
        if smile == 'hidden':
            expect(mouth).to_be_hidden()
        elif smile:
            expect(mouth).not_to_be_checked()
            mouth.check()
            expect(page.locator('#draw')).to_be_enabled()
            if smile == 'restore':
                mouth.uncheck()
                expect(page.locator('#draw')).to_be_enabled()
        return submit(page, settings.get('target', 'full'))


def check_insertions(original, revised):
    old, new = [np.frombuffer(raw, dtype='<f4').reshape(-1, 2) for raw in (original, revised)]
    edits = SequenceMatcher(None, list(map(tuple, old)), list(map(tuple, new)), autojunk=False).get_opcodes()
    assert [e[0] for e in edits] == ['equal', 'insert', 'equal', 'insert', 'equal']
    for tag, _, _, start, end in edits:
        if tag != 'insert':
            continue
        # The matching run can consume either copy of the departure point.
        branch = new[start-1:end] if np.array_equal(new[start-1], new[end-1]) else new[start:end+1]
        np.testing.assert_array_equal(branch, branch[::-1])
        xy = np.column_stack((np.cos(branch[:, 0]), np.sin(branch[:, 0]))) * branch[:, 1, None]
        assert np.linalg.norm(xy - xy[0], axis=1).max() * 114.03 < 30, 'Eye left its lens vicinity.'


def check_mouth_change(before, after):
    # These pair fixtures change one smile. Every other position in the
    # downloaded movement file, including both eye visits, must be identical.
    old, new = [np.frombuffer(raw, dtype='<f4').reshape(-1, 2) for raw in (before, after)]
    prefix = 0
    while np.array_equal(old[prefix], new[prefix]):
        prefix += 1
    end = 1
    while np.array_equal(old[-end], new[-end]):
        end += 1
    assert prefix > 0 and end > 1
    for route in (old, new):
        local = route[prefix-1:len(route)-end+2]
        xy = np.column_stack((np.cos(local[:, 0]), np.sin(local[:, 0]))) * local[:, 1, None]
        assert np.linalg.norm(np.ptp(xy, axis=0)) * 114.03 < 50, 'Smile changed a movement outside this face.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pair', type=Path, nargs=2, help='Two pair photos with visible eyes inside one set of glasses.')
    parser.add_argument('--control', type=Path, action='append', default=[], help='A photo without room for both lids.')
    parser.add_argument('--smiles', action='store_true', help='Both fixtures also have measurable open smiles. Check all four styles.')
    parser.add_argument('--previous', type=Path, help='Earlier compressed Mini guest bundle for byte-for-byte comparison.')
    parser.add_argument('--bundle', type=Path, help='Use an already packaged Mini guest bundle.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary, sync_playwright() as session:
        assets = args.bundle or Path(temporary)
        if not args.bundle:
            build_guest_web_assets(ROOT / 'web', assets, mini_only=True)
        with session.chromium.launch(executable_path=chromium(session, None)) as browser:
            for pair in args.pair:
                enhanced = export(browser, assets, pair, eyes='on')
                original = export(browser, assets, pair, eyes='off')
                assert enhanced == export(browser, assets, pair, eyes='again')
                if args.previous:
                    assert original == export(browser, args.previous, pair)
                check_insertions(original, enhanced)
                if args.smiles:
                    both = export(browser, assets, pair, eyes='on', smile='on')
                    mouth = export(browser, assets, pair, eyes='off', smile='on')
                    assert len({both, mouth, enhanced, original}) == 4
                    check_insertions(mouth, both)
                    check_mouth_change(original, mouth)
                    check_mouth_change(enhanced, both)
                    assert export(browser, assets, pair, eyes='on', smile='restore') == enhanced
                print(pair.name, len(original)//8, 'to', len(enhanced)//8, hashlib.sha256(enhanced).hexdigest(), flush=True)

            cases = [(control, {}) for control in args.control]
            cases.extend((args.pair[0], settings) for settings in (
                dict(target='center'), dict(heads=False), dict(mode='one'), dict(caption='B')))
            for photo, settings in cases:
                route = export(browser, assets, photo, eyes='hidden', smile='hidden' if args.smiles else None, **settings)
                if args.previous:
                    assert route == export(browser, args.previous, photo, **settings)
                print(photo.name, settings, 'original framing', flush=True)


if __name__ == '__main__':
    main()
