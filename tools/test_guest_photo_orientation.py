"""Open the same group photo in all eight lossless storage orientations on the Mini guest page."""
import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps
from playwright.sync_api import expect, sync_playwright

from test_guest_inward_portrait import FramedMini, ROOT, build_guest_web_assets, checked_route, choose, phone, preview
from wide_portrait import chromium


def render(browser, assets, photo, face):
    device = FramedMini(assets)
    with phone(browser, device) as page:
        choose(page, photo, face)
        count = page.locator('#faceBoxes button').count()
        page.locator('#inwardPortrait').select_option('engraved')
        preview(page)
        thumbnail = page.locator('#photoImage').evaluate("""async img => {
            await img.decode();
            const canvas=document.createElement('canvas');
            canvas.width=96;canvas.height=72;
            const ctx=canvas.getContext('2d');
            ctx.drawImage(img,0,0,96,72);
            const bytes=ctx.getImageData(0,0,96,72).data;
            return [img.naturalWidth,img.naturalHeight,Array.from(bytes)];
        }""")
        page.locator('#draw').click()
        expect(page.locator('#message')).to_contain_text('started')
    checked_route(device.staged, device.status['theta'])
    assert device.uploads == [device.staged] and device.started == 1
    return (count, hashlib.sha256(device.staged.encode('ascii')).hexdigest(),
            thumbnail[:2], hashlib.sha256(bytes(thumbnail[2])).hexdigest())


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('group_photo', type=Path)
    cli.add_argument('--face', type=int, default=2, help='Numbered from one')
    args = cli.parse_args()
    with Image.open(args.group_photo) as src:
        upright = ImageOps.exif_transpose(src).convert('RGB')
    ops = Image.Transpose
    # Inverse storage transforms. Tags 6 and 8 are quarter turns in opposite directions.
    inverse = [None, ops.FLIP_LEFT_RIGHT, ops.ROTATE_180, ops.FLIP_TOP_BOTTOM,
               ops.TRANSPOSE, ops.ROTATE_90, ops.TRANSVERSE, ops.ROTATE_270]
    with TemporaryDirectory() as temp, sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw,None)) as browser:
        path = Path(temp)
        assets = path / 'assets'
        assets.mkdir()
        build_guest_web_assets(ROOT / 'web', assets, mini_only=True)
        for number, transform in enumerate(inverse, 1):
            raw = upright if transform is None else upright.transpose(transform)
            exif = Image.Exif()
            exif[274] = number
            photo = path / 'group.png'
            raw.save(photo, exif=exif)
            result = render(browser, assets, photo, args.face - 1)
            if number == 1:
                expected = result
            assert result == expected, (number, result, expected)
        # Some browsers ignore EXIF in WebP even though they honor it in PNG.
        photo = path / 'rotated.webp'
        exif = Image.Exif()
        exif[274] = 6
        upright.transpose(ops.ROTATE_90).save(photo, lossless=True, exif=exif)
        assert render(browser, assets, photo, args.face - 1) == expected
        print(f'All eight PNG orientations and a rotated WebP found {expected[0]} faces and sent the same drawing ({expected[1][:12]}).')


if __name__ == '__main__':
    main()
