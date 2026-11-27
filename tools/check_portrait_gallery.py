"""Replay every archived prepared portrait in a local garden and check its actual downloads."""

import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from test_garden_room import drawing_files
from test_ring_shadows import ready
from wide_portrait import chromium

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'patterns/portrait-gallery/catalog.json'


def check(garden):
    entries = json.loads(CATALOG.read_text())
    exported = {}
    versions = 0
    with sync_playwright() as engine, engine.chromium.launch(executable_path=chromium(engine, None)) as browser:
        page = browser.new_page(offline=True, viewport={'width': 390, 'height': 844})
        page.goto(garden.resolve().as_uri() + '?layout=portrait#prepared-portrait')
        for entry in entries:
            for version in entry['versions']:
                if 'drawing' not in version:
                    continue  # A camera-only entry has no downloadable guest drawing.
                drawing = ROOT / version['drawing']
                digest = hashlib.sha256(drawing.read_bytes()).hexdigest()
                label = f"{entry['id']} / {version['label']}"
                if digest != version['sha256']:
                    raise ValueError(f'{label}: the archived portrait file has changed.')
                if digest not in exported:
                    page.locator('#portraitFile').set_input_files(drawing)
                    page.locator('#portraitSubmit').click()
                    ready(page)
                    files = drawing_files(page, '#downloads')
                    exported[digest] = [hashlib.sha256(data).hexdigest() for _, data in files]
                if exported[digest] != version['parts']:
                    raise ValueError(f'{label}: the garden exported different movement files.')
                versions += 1
    print(f'Checked {versions} archive versions against the garden downloads ({len(exported)} distinct drawings).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('garden', type=Path, help='Local combined editor built for the archived wide center')
    check(parser.parse_args().garden)
