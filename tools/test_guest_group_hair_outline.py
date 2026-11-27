"""Verify a Mini guest's optional three-face hair outline and exact return to the previous drawing."""
import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from build_guest_center import build_guest_web_assets
from test_guest_inward_pair import open_photo, simulated_mini, submit
from test_guest_inward_portrait import phone, preview
from wide_portrait import chromium


def export(browser, assets, photo, args, with_hair):
    mini = simulated_mini(assets, args.dock)
    with phone(browser, mini) as page:
        open_photo(page, photo, style='quiet-engraved')
        preview(page)
        if args.enlarged:
            page.locator('#largerFaces').check()
            expect(page.locator('#draw')).to_be_enabled()
        if args.separate_eyes:
            page.locator('#spaceEyes').check()
            expect(page.locator('#draw')).to_be_enabled()
        option = page.get_by_role('checkbox', name='Trace the hair outline')
        if args.declined:
            expect(option).to_be_hidden()
        else:
            expect(option).to_be_visible()
            option.check()
            expect(page.locator('#effect')).to_contain_text('outer hair follows the photograph')
            if not with_hair:
                option.uncheck()
                expect(page.locator('#draw')).to_be_enabled()
        route = submit(page, mini)
        data = mini.staged.encode()
        assert len(data.splitlines()) == len(route)
        return data


def main(args):
    with TemporaryDirectory() as temporary:
        assets = Path(temporary)
        build_guest_web_assets(Path(__file__).resolve().parents[1]/'web', assets, mini_only=True)
        with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
            original = export(browser, assets, args.photo, args, False)
            outlined = export(browser, assets, args.photo, args, True)
            if args.declined:
                assert outlined == original
            else:
                assert outlined != original
            if args.original:
                assert original == args.original.read_bytes()
            if args.expected:
                assert outlined == args.expected.read_bytes()
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                (args.save/'open.thr').write_bytes(original)
                (args.save/'hair.thr').write_bytes(outlined)
            print('Original', hashlib.sha256(original).hexdigest())
            print('Selected', hashlib.sha256(outlined).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('photo', type=Path)
    parser.add_argument('--dock', type=float, default=431.96899)
    parser.add_argument('--enlarged', action='store_true')
    parser.add_argument('--separate-eyes', action='store_true')
    parser.add_argument('--declined', action='store_true')
    parser.add_argument('--original', type=Path)
    parser.add_argument('--expected', type=Path)
    parser.add_argument('--save', type=Path)
    main(parser.parse_args())
