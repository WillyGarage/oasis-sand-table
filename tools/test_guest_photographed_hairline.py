"""Check the Mini's optional photographed hairline through the guest page.

python3 tools/test_guest_photographed_hairline.py restaurant-three.jpg redwood-solo.jpg
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from test_guest_inward_pair import open_photo, simulated_mini, submit
from test_guest_inward_portrait import phone, preview
from wide_portrait import chromium


def download(browser, assets, source, index, *, trace=False, name=''):
    device = simulated_mini(assets, 375.42036)
    with phone(browser, device) as page:
        open_photo(page, source, group=False, style='quiet-engraved', name=name)
        preview(page)
        faces = page.locator('#faceBoxes button')
        if faces.count() > 1:
            faces.nth(index).click()
        expect(page.locator('#draw')).to_be_enabled()
        option = page.get_by_label('Trace the photographed hairline')
        expect(option).to_be_visible()
        expect(option).not_to_be_checked()
        if trace:
            option.check()
            expect(page.locator('#effect')).to_contain_text('photographed hairline')
            if name:
                expect(page.locator('#effect')).to_contain_text(name.upper())
        # Check the same-scale claim before inspecting the actual download.
        expected = page.evaluate("""async ([index,trace,name])=>{
            const result=await GuestPhoto.fromFile(document.querySelector('#file').files[0], {
              face:index, portraitFraming:'head', inwardContours:true,
              portraitDiameterGrooves:await GuestCenterRoutes.photoDiameterGrooves('full')
            });
            const paths=result.inwardContours.concat(result.inwardHair);
            const extent=lines=>Math.max(...lines.flat().map(p=>Math.hypot(...p)));
            if(!result.fringe || extent([result.fringe])>extent(paths))
              throw Error('The hairline must stay inside the old drawing.');
            if(trace)paths.push(result.fringe);
            const style={quietFace:true}, opening=375.42036;
            return (name ? await GuestInwardPortrait.namedPlan(paths,opening,name,style) :
              GuestInwardPortrait.plan(paths,opening,style)).text;
        }""", [index, trace, name])
        submit(page, device)
        assert device.staged == expected
        return device.staged


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('restaurant', type=Path)
    parser.add_argument('redwoods', type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as temp, sync_playwright() as pw:
        assets = Path(temp)
        build_guest_web_assets(Path(__file__).resolve().parents[1] / 'web', assets, mini_only=True)
        with pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
            for photo, index in [(args.restaurant, 1), (args.redwoods, 0)]:
                ordinary = download(browser, assets, photo, index)
                active = download(browser, assets, photo, index, trace=True)
                assert ordinary != active
            download(browser, assets, args.restaurant, 2, trace=True, name='Mom')
    print('Both photo selections retained face scale and exported their measured hairline. The named portrait also matched.')
