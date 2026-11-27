"""Rehearse a saved Mini tracing and an unrelated photo on two simulated phones."""
import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from test_guest_inward_pair import open_photo, simulated_mini, submit
from test_guest_inward_portrait import check_rim_letters, phone, preview
from wide_portrait import chromium


def open_face(page, source, index):
    open_photo(page, source, group=False, style='quiet-engraved')
    preview(page)
    faces = page.locator('#faceBoxes button')
    if faces.count() > 1:
        faces.nth(index).click()
    expect(page.locator('#draw')).to_be_enabled(timeout=20000)


def reviewed(browser, bundle, source, use_tracing, name=''):
    device = simulated_mini(bundle, 375.42036)
    with phone(browser, device) as page:
        open_face(page, source, 2)
        page.locator('#soloSmile').select_option('open')
        field = page.locator('#savedDetailsField')
        expect(field).to_be_visible()
        page.locator('#savedDetails').check()
        expect(page.locator('#effect')).to_contain_text('saved tracing')
        if not use_tracing:
            page.locator('#savedDetails').uncheck()
            expect(page.locator('#effect')).not_to_contain_text('saved tracing')
        if name:
            page.get_by_label('Name under the portrait').fill(name)
            preview(page)
            expect(field).to_be_visible()
            expect(page.locator('#savedDetails')).to_be_checked()
            expect(page.locator('#effect')).to_contain_text('saved tracing')
            expected = page.evaluate("""async name=>{
              const file=document.querySelector('#file').files[0];
              const photo=await GuestPhoto.fromFile(file,{face:2,portraitFraming:'head',inwardContours:true,
                portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
              return (await GuestInwardPortrait.namedPlan(photo.reviewedPortrait,375.42036,name,{quietFace:true})).text;
            }""", name)
        route = submit(page, device)
        if name:
            assert device.staged == expected
            check_rim_letters(page, route, name)
        return hashlib.sha256(device.staged.encode()).hexdigest()


def ordinary(browser, bundle, source, index, hide_library):
    device = simulated_mini(bundle, 375.42036)
    with phone(browser, device) as page:
        if hide_library:
            page.route('**/guest-reviewed-portrait.js*', lambda req: req.fulfill(
                content_type='application/javascript', body=''))
            page.reload()
            expect(page.locator('#previewButton')).to_be_enabled()
            assert not page.evaluate('!!window.GuestReviewedPortrait')
        open_face(page, source, index)
        expect(page.locator('#savedDetailsField')).to_be_hidden()
        original = page.evaluate("""async face=>{
          const source=document.querySelector('#file').files[0];
          const r=await GuestPhoto.fromFile(source,{face,portraitFraming:'head',inwardContours:true,
            portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')});
          return !!r.reviewedPortrait;
        }""", index)
        assert not original
        submit(page, device)
        return device.staged


def exercise(browser, bundle, source, other, other_face):
    first = reviewed(browser, bundle, source, True)
    second = reviewed(browser, bundle, source, True)
    earlier = reviewed(browser, bundle, source, False)
    assert first == second and earlier != first
    assert reviewed(browser, bundle, source, True, name='Mom') not in (first, earlier)
    assert earlier == '3bb0c9a18271b593d80de4869c767ee3167cb912405454e7e2aa0340dbfb0a81'
    assert ordinary(browser, bundle, other, other_face, True) == ordinary(browser, bundle, other, other_face, False)
    assert ordinary(browser, bundle, source, 1, True) == ordinary(browser, bundle, source, 1, False)
    # A different file with the same length cannot inherit the reviewed face.
    length = source.stat().st_size
    with browser.new_page() as page:
        page.goto('about:blank')
        path = Path(__file__).resolve().parents[1] / 'web/guest-reviewed-portrait.js'
        page.add_script_tag(path=str(path))
        assert not page.evaluate("""async length=>{
          const file=new File([new Uint8Array(length)],'different.jpg');
          return !!await GuestReviewedPortrait.forPhoto(file,2,{open:[[]]},{});
        }""", length)
    print('Two fresh phones exported the same saved engraving.', first)
    print('The usual smile, the other diner, and the separate photo kept their exact downloads.')


if __name__ == '__main__':
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('source', type=Path)
    args.add_argument('other', type=Path)
    args.add_argument('--other-face', type=int, default=0)
    values = args.parse_args()
    with TemporaryDirectory() as temp, sync_playwright() as pw:
        assets = Path(temp)
        build_guest_web_assets(Path(__file__).resolve().parents[1] / 'web', assets, mini_only=True)
        with pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
            exercise(browser, assets, values.source, values.other, values.other_face)
