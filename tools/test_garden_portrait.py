"""Exercise private room photo preparation with real local images and optional isolated host comparisons.

python3 tools/test_garden_portrait.py GARDEN.html PHOTO.jpg PHOTO.oasisportrait --pair GROUP.jpg SECOND.oasisportrait
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image
import garden_portrait as portrait
import psutil
from garden_room import make_server


def post(origin, body, options, *, mime='image/jpeg', foreign=False, extra=None):
    headers = {
        'Origin': 'http://other.invalid' if foreign else origin,
        'Content-Type': mime,
        'X-Oasis-Portrait': json.dumps(options),
    }
    headers.update(extra or {})
    request = Request(origin + '/api/portrait', data=body, headers=headers)
    try:
        reply = urlopen(request, timeout=100)
    except HTTPError as error:
        reply = error
    with reply:
        return reply.status, json.load(reply), reply.headers


def check(garden, photo, prepared, pair, nose=None, brows=None, combined=None, smile=None, all_features=None,
          eyes=None):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with make_server(garden, root / 'disabled.db') as disabled:
            t = threading.Thread(target=disabled.serve_forever, daemon=True)
            t.start()
            try:
                origin = f'http://127.0.0.1:{disabled.server_port}'
                with urlopen(origin) as response:
                    assert portrait.MARKER.encode() not in response.read()
                assert post(origin, b'no image', {})[0] == 404
            finally:
                disabled.shutdown()
                t.join()
        private = root / 'host-tmp'
        private.mkdir()
        with (
            patch.object(tempfile, 'tempdir', str(private)),
            make_server(garden, root / 'enabled.db', photo_portraits=True) as server,
        ):
            origin = f'http://127.0.0.1:{server.server_port}'
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                with urlopen(origin) as response:
                    assert response.read().count(portrait.MARKER.encode()) == 1
                diameter, groove = server.portrait_sizes['garden']
                options = {'layout': 'garden', 'diameterMm': diameter, 'grooveMm': groove, 'face': 0}
                data = photo.read_bytes()
                assert post(origin, b'none', options, foreign=True)[0] == 403
                assert post(origin, b'none', options, extra={'Sec-Fetch-Site': 'cross-site'})[0] == 403
                assert post(origin, b'none', options, mime='text/plain')[0] == 415
                assert post(origin, b'none', dict(options, traceNose='yes'))[0] == 400
                assert post(origin, b'none', dict(options, traceBrows=1))[0] == 400
                assert post(origin, b'none', dict(options, traceSmile='true'))[0] == 400
                assert post(origin, b'none', dict(options, traceEyes=1))[0] == 400
                assert post(origin, b'none', dict(options, hairWoodcut='true'))[0] == 400
                assert post(origin, b'none', dict(options, longHair='true'))[0] == 400
                assert post(origin, b'none', dict(options, groupLocks=True))[0] == 400
                assert post(origin, b'none', dict(options, traceLips=True))[0] == 400
                assert post(origin, b'none', dict(options, face=-1))[0] == 400
                assert post(origin, b'none', dict(options, face={'x': 9, 'y': 10, 'w': 40}))[0] == 400
                assert post(origin, b'none', dict(options, diameterMm=diameter + 1))[0] == 409
                assert post(origin, b'none', dict(options, layout='wrong'))[0] == 409
                boxes = [{'x': 80, 'y': 90, 'w': 55}, {'x': 160, 'y': 90, 'w': 40}]
                group = {k: v for k, v in options.items() if k != 'face'}
                too_many = [{'x': 80 + 100 * i, 'y': 90, 'w': 55} for i in range(5)]
                for faces in ([], boxes[:1], too_many, boxes * 2, boxes[:1] * 2, [0, 1], [boxes[0], {'x': 4, 'y': 8, 'w': 60}]):
                    assert post(origin, b'none', dict(group, faces=faces))[0] == 400
                assert post(origin, b'none', dict(options, faces=boxes))[0] == 400
                assert post(origin, b'none', dict(group, faces=boxes, traceEyes=True))[0] == 400
                for value in ('true', 1, None):
                    assert post(origin, b'none', dict(group, faces=boxes, groupLocks=value))[0] == 400
                    assert post(origin, b'none', dict(group, faces=boxes, rakePrint=value))[0] == 400
                assert post(origin, b'none', dict(group, faces=boxes, rakePrint=True, groupLocks=True))[0] == 400
                assert post(origin, b'none', dict(group, faces=too_many[:3], rakePrint=True))[0] == 400
                assert post(origin, b'none', dict(group, faces=boxes, diameterMm=diameter + 1))[0] == 409
                assert (
                    post(origin, b'none', options, extra={'Content-Length': str(portrait.PHOTO_BYTES + 1)})[0]
                    == 413
                )
                # Use a tiny image and a tiny test pixel ceiling to exercise the
                # decoded-size limit without allocating an oversized bitmap.
                png = io.BytesIO()
                Image.new('RGB', (22, 22)).save(png, 'PNG')
                with patch.object(portrait, 'PIXEL_LIMIT', 100):
                    try:
                        portrait.check_photo(png.getvalue(), 'image/png')
                    except portrait.PortraitError as e:
                        assert e.status == 413
                    else:
                        raise AssertionError('The decoded pixel ceiling was ignored.')
                assert post(origin, png.getvalue(), options, mime='image/jpeg')[0] == 415
                with ThreadPoolExecutor(max_workers=1) as pool:
                    first = pool.submit(post, origin, data, options)
                    until = time.monotonic() + 4
                    while not server.portrait_lock.locked() and time.monotonic() < until:
                        time.sleep(0.02)
                    assert server.portrait_lock.locked()
                    busy = post(origin, b'none', options)
                    assert busy[0] == 429 and busy[2]['Retry-After']
                    code, result, headers = first.result()
                assert code == 200 and headers['Cache-Control'] == 'no-store'
                first_manifest = json.loads((prepared.parent/'result.json').read_text())
                assert set(result) == {'drawing', 'method', 'note'} and result['method'] == first_manifest['method']
                assert result['drawing'] == json.loads(prepared.read_text())
                for flags, expected in (({'traceNose': True}, nose), ({'traceBrows': True}, brows),
                                        ({'traceNose': True, 'traceBrows': True}, combined),
                                        ({'traceSmile': True}, smile), ({'traceEyes': True}, eyes),
                                        (None, all_features)):
                    if expected:
                        manifest = json.loads((expected.parent/'result.json').read_text())
                        if flags is None:
                            flags = {flag: True for flag, key in portrait.TRACE_FEATURES.items() if key in manifest}
                        code, traced, _ = post(origin, data, dict(options, **flags))
                        assert code == 200
                        for flag, key in portrait.TRACE_FEATURES.items():
                            assert (key in traced) == (flag in flags)
                            if flag in flags:
                                assert traced[key] == manifest[key]
                        assert traced['drawing'] == json.loads(expected.read_text())
                        for key, folder in (('woodcut', 'hair-woodcut'), ('longHair', 'full-hair'),
                                            ('flowingHair', 'flowing-hair'), ('rakePrint','rake-print')):
                            applied = manifest.get(key, {}).get('applied', False)
                            assert (key + 'Drawing' in traced) == applied
                            if applied:
                                assert traced[key + 'Drawing'] == json.loads(
                                    (expected.parent/folder/'portrait.oasisportrait').read_text())
                assert not list(private.glob('oasis-private-portrait-*'))
                assert post(origin, data, dict(options, face=63))[0] == 422
                if pair:
                    other, expected = map(Path, pair)
                    code, answer, _ = post(origin, other.read_bytes(), dict(options, face=1))
                    assert code == 200 and answer['drawing'] == json.loads(expected.read_text())
                with patch.object(portrait, 'PREPARE_SECONDS', 1.8):
                    assert post(origin, data, options)[0] == 504
                assert (
                    not list(private.glob('oasis-private-portrait-*')) and not server.portrait_lock.locked()
                )
                assert not any(
                    any(str(private) in arg for arg in (proc.info['cmdline'] or []))
                    for proc in psutil.process_iter(['cmdline'])
                )
                with sqlite3.connect(root / 'enabled.db') as db:
                    assert not db.execute('SELECT 1 FROM drawing WHERE revision>0').fetchone()
                    assert not db.execute('SELECT 1 FROM garden WHERE revision>0').fetchone()
            finally:
                server.shutdown()
                t.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('garden', 'photo', 'prepared'):
        parser.add_argument(arg, type=Path)
    parser.add_argument('--pair', nargs=2, metavar=('GROUP_PHOTO', 'SECOND_FACE_DRAWING'))
    parser.add_argument('--nose', type=Path, help='Verified CLI preparation of this guest with --trace-nose.')
    parser.add_argument('--brows', type=Path, help='Verified CLI preparation with --trace-brows alone.')
    parser.add_argument('--combined', type=Path, help='Verified CLI preparation with nose and brow tracing.')
    parser.add_argument('--smile', type=Path, help='Verified CLI preparation with smile tracing alone.')
    parser.add_argument('--eyes', type=Path, help='Verified CLI preparation with eye tracing alone.')
    parser.add_argument('--all-features', type=Path, help='Verified CLI preparation with all trace options.')
    args = parser.parse_args()
    check(args.garden, args.photo, args.prepared, args.pair, args.nose, args.brows,
          args.combined, args.smile, args.all_features, args.eyes)
    print(
        'Verified opt-in, existing face choice, byte/pixel limits, one offline job, exact response, timeout, cleanup and untouched room.'
    )
