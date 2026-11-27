"""Compare the phone's automatic portrait download with each intended drawing style."""
import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from test_garden_room import drawing_files
from test_ring_shadows import ready


def check(page, url, photo, area, expected_style, *, group=False, name=''):
    page.goto('about:blank')
    page.goto(url + '?layout=garden#photos')
    page.locator('#portraitArea').select_option(area)
    page.locator('#portraitFile').set_input_files(photo)
    if group:
        page.locator('#portraitMode').select_option('group')
    style = page.locator('#portraitStyle' if group else '#soloStyle')
    expect(style).to_have_value('heads' if group else 'auto')
    if name:
        page.locator('#photoCaption').fill(name)
    page.locator('#portraitSubmit').click()
    ready(page)
    automatic = drawing_files(page, '#downloads')
    status = page.locator('#portraitStatus').inner_text()
    if name:
        assert name in status
    if group:
        assert '2 faces arranged together' in status
        style.select_option('pose')
        ready(page)
        assert drawing_files(page, '#downloads') != automatic
    style.select_option(expected_style)
    ready(page)
    assert drawing_files(page, '#downloads') == automatic, (photo, area, name, expected_style)
    print(photo.name, area, expected_style, status, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('solo', type=Path, help='Photograph suitable for shadow engraving')
    parser.add_argument('crowded', type=Path, help='Photograph whose shadow engraving fails the spacing check')
    parser.add_argument('pair', type=Path)
    args = parser.parse_args()
    url = args.gallery.resolve().as_uri()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            page = browser.new_page(offline=True, viewport={'width':390, 'height':844})
            check(page, url, args.solo, 'wide', 'shadow')
            check(page, url, args.solo, 'center', 'head')
            check(page, url, args.crowded, 'wide', 'head')
            check(page, url, args.solo, 'wide', 'head', name='L')
            check(page, url, args.pair, 'wide', 'heads', group=True)
