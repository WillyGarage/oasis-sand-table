"""Check host preparation against the actual Automatic photo form, including its framed-head fallback.

python3 tools/test_wide_portrait.py GARDEN.html PHOTO_WITH_HAIR.jpg PHOTO_WITH_CROWDED_FEATURES.jpg
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

from test_ring_shadows import export, ready
from wide_portrait import chromium


def prepared(garden, photo, dest, *options):
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name('wide_portrait.py')),
            str(garden),
            str(photo),
            '--out',
            str(dest),
            *options,
        ],
        check=True,
    )
    report = json.loads((dest / 'result.json').read_text())
    drawing = json.loads((dest / 'portrait.oasisportrait').read_text())
    assert set(drawing) == {'format', 'diameterMm', 'grooveMm', 'points' if 'points' in drawing else 'marks'}
    assert drawing['format'] == 'oasis-prepared-portrait-v1'
    files = [(dest / name).read_bytes() for name in report['files']]
    return report, drawing, files


def ordinary(browser, garden, photo, dest):
    dest.mkdir()
    with browser.new_page(offline=True, viewport={'width': 390, 'height': 844}) as phone:
        phone.goto(garden.resolve().as_uri() + '?layout=garden#photos')
        phone.locator('#portraitArea').select_option('wide')
        phone.locator('#soloStyle').select_option('auto')
        phone.locator('#portraitFile').set_input_files(photo)
        phone.locator('#portraitSubmit').click()
        ready(phone)
        export(phone, dest)
    return [p.read_bytes() for p in sorted(dest.glob('*.thr'), key=lambda v: int(v.stem.rsplit('-', 1)[1]))]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('garden', type=Path)
    parser.add_argument('hair', type=Path, help='Guest whose photographed hair fits the wide center.')
    parser.add_argument(
        'crowded', type=Path, help='Guest whose shadow portrait falls back to a head close-up.'
    )
    parser.add_argument(
        '--trace-nose',
        action='store_true',
        help='Require a measured nose on the first photo and the exact outline fallback on the second.',
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as engine:
        root = Path(temp)
        report, drawing, enhanced = prepared(args.garden, args.hair, root / 'hair')
        assert report['method'] == 'measured-hair' and report['protectedMarks'] >= 3
        assert 'marks' in drawing and 'nose' not in report
        if args.trace_nose:
            nose_report, nose_drawing, nose_files = prepared(
                args.garden, args.hair, root / 'nose', '--trace-nose'
            )
            assert nose_report['nose']['applied'] and nose_files != enhanced
            assert len(nose_drawing['marks']) == len(drawing['marks'])
            changed = [
                i for i, (old, new) in enumerate(zip(drawing['marks'], nose_drawing['marks'])) if old != new
            ]
            assert len(changed) == 1 and drawing['marks'][changed[0]]['kind'] == 'nose'
        report, drawing, missing = prepared(
            args.garden, args.hair, root / 'missing', '--model-python', str(root / 'none')
        )
        assert report['method'] == 'ordinary-shadows' and 'marks' in drawing
        report, drawing, outline = prepared(args.garden, args.crowded, root / 'outline')
        assert report['method'] == 'ordinary-outline' and 'points' in drawing
        if args.trace_nose:
            fallback, kept, files = prepared(args.garden, args.crowded, root / 'outline-nose', '--trace-nose')
            assert fallback['nose']['applied'] is False and kept == drawing and files == outline
        with engine.chromium.launch(executable_path=chromium(engine, None)) as browser:
            normal = ordinary(browser, args.garden, args.hair, root / 'normal-hair')
            assert normal == missing and normal != enhanced
            assert ordinary(browser, args.garden, args.crowded, root / 'normal-outline') == outline
    print('Host hair, ordinary shadow and Automatic close-up exports verified.')
