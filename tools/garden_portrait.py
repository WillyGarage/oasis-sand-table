"""Private, offline photo preparation for an explicitly enabled Oasis room."""

import argparse
import io
from importlib.util import find_spec
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import warnings

PHOTO_BYTES = 16 * 1024 * 1024
PIXEL_LIMIT = 50_500_000
MAX_EDGE = 16_384
PREPARE_SECONDS = 75
DRAWING_BYTES = 4 * 1024 * 1024
TYPES = {'image/jpeg': ('JPEG', 'jpg'), 'image/png': ('PNG', 'png'), 'image/webp': ('WEBP', 'webp')}
TRACE_FEATURES = {'traceNose': 'nose', 'traceBrows': 'brows', 'traceSmile': 'smile', 'traceEyes': 'eyes',
                  'hairWoodcut': 'woodcut', 'longHair': 'longHair', 'flowingHair': 'flowingHair',
                  'rakePrint': 'rakePrint', 'cheekPrint': 'cheekPrint'}
ALTERNATE_FOLDERS = {
    'woodcut': 'hair-woodcut', 'longHair': 'full-hair', 'flowingHair': 'flowing-hair',
    'rakePrint': 'rake-print', 'cheekPrint': 'cheek-print',
}
MARKER = '<meta name="oasis-portrait" content="./api/portrait" data-nose="1" data-brows="1" data-smile="1" data-eyes="1" data-woodcut="1" data-flowing-hair="1" data-rake-print="1" data-cheek-print="1" data-long-hair="1" data-group="1" data-group-locks="1" data-group-rake="1">'
HEIC_MARKER = '<meta name="oasis-heic" content="./api/portrait/heic">'


class PortraitError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def installed_heic_reader():
    """Return a local, memory-only reader when ImageMagick has its HEIC decoder."""
    binary = shutil.which('magick') or shutil.which('convert')
    if not binary:
        return None
    try:
        formats = subprocess.run([binary, '-list', 'format'], capture_output=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows = (line.split() for line in formats.splitlines())
    if not any(len(row) >= 3 and row[0].rstrip(b'*') == b'HEIC' and row[2].startswith(b'r') for row in rows):
        return None

    def read(data):
        # Explicit coder and primary image. Read pixels and return a still over pipes.
        command = [binary, '-quiet', '-limit', 'thread', '1', '-limit', 'memory', '512MiB',
                   '-limit', 'map', '0', '-limit', 'disk', '0', '-limit', 'width', str(MAX_EDGE),
                   '-limit', 'height', str(MAX_EDGE)]
        if data[4:8] != b'ftyp':
            raise PortraitError(415, 'Choose a readable HEIC photo.')
        def run(args):
            try:
                return subprocess.run(command + args, input=data, capture_output=True,
                                      check=True, timeout=25).stdout
            except (OSError, subprocess.SubprocessError):
                raise PortraitError(415, 'The garden laptop could not open this HEIC photo.') from None
        dimensions = run(['-ping', 'heic:-[0]', '-format', '%w %h', 'info:']).split()
        if len(dimensions) != 2 or not all(part.isdigit() for part in dimensions):
            raise PortraitError(415, 'The HEIC photo has no readable dimensions.')
        width, height = map(int, dimensions)
        if not (0 < width <= MAX_EDGE and 0 < height <= MAX_EDGE and width * height <= PIXEL_LIMIT):
            raise PortraitError(413, 'This photo is too large to prepare. Choose a smaller copy.')
        for quality in ('96', '86'):
            jpeg = run(['heic:-[0]', '-auto-orient', '-strip', '-quality', quality, 'jpeg:-'])
            if 0 < len(jpeg) <= PHOTO_BYTES:
                check_photo(jpeg, 'image/jpeg')
                return jpeg
        raise PortraitError(413, 'Choose a smaller copy for the garden laptop.')
    return read


def request_options(raw, sizes):
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        data = None
    common = {'layout', 'diameterMm', 'grooveMm'}
    if not isinstance(data, dict):
        raise PortraitError(400, 'Choose a face and a portrait area in the garden.')
    group = 'faces' in data
    if group:
        styles = {'groupLocks', 'rakePrint'}
        valid = (set(data) - styles == common | {'faces'} and all(type(data.get(k, False)) is bool for k in styles)
                 and not (data.get('groupLocks') and data.get('rakePrint')))
    else:
        valid = set(data) - TRACE_FEATURES.keys() == common | {'face'} and all(
            type(data[key]) is bool for key in TRACE_FEATURES if key in data
        )
    if not valid:
        raise PortraitError(400, 'Choose a face and a portrait area in the garden.')
    layout = data['layout']
    if not isinstance(layout, str) or layout not in sizes:
        raise PortraitError(409, 'Select the wide portrait area in this room.')

    def number(v):
        return type(v) in (float, int) and abs(v) <= 1_000_000 and math.isfinite(v)

    for got, expected in zip((data['diameterMm'], data['grooveMm']), sizes[layout]):
        if not number(got) or abs(got - expected) > 0.01:
            raise PortraitError(409, 'The selected portrait area does not match this room.')

    def valid_box(face):
        return (
            isinstance(face, dict)
            and set(face) == {'x', 'y', 'w'}
            and all(number(v) for v in face.values())
            and 18 <= face['w'] <= 1000
            and all(face['w'] / 2 - 0.001 <= face[k] <= 1000 - face['w'] / 2 + 0.001 for k in ('x', 'y'))
        )

    if group:
        faces = data['faces']
        if not isinstance(faces, list) or len(faces) not in (2, 3, 4) or not all(valid_box(b) for b in faces):
            raise PortraitError(400, 'Choose two to four faces in the photo picker.')
        if data.get('rakePrint') and len(faces) != 2:
            raise PortraitError(400, 'Select two faces for this paired print.')
        if any(face in faces[:i] for i, face in enumerate(faces)):
            raise PortraitError(400, 'Choose distinct faces in the photo picker.')
    else:
        face = data['face']
        if face is not None and not (type(face) is int and 0 <= face < 64 or valid_box(face)):
            raise PortraitError(400, 'Choose a valid face in the photo picker.')
    return data


def check_photo(data, mime):
    from PIL import Image, UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[TYPES[mime][0]]) as image:
                width, height = image.size
                if max(width, height) > MAX_EDGE or width * height > PIXEL_LIMIT:
                    raise PortraitError(413, 'This photo is too large to prepare. Choose a smaller copy.')
                if getattr(image, 'n_frames', 1) != 1:
                    raise PortraitError(415, 'Choose a single still JPEG, PNG or WebP photo.')
                image.verify()
            with Image.open(io.BytesIO(data), formats=[TYPES[mime][0]]) as image:
                image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PortraitError(413, 'This photo is too large to prepare. Choose a smaller copy.') from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as err:
        if isinstance(err, PortraitError):
            raise
        raise PortraitError(415, 'Choose a complete, readable JPEG, PNG or WebP photo.') from None


def run_worker(folder, options, mime, browser, model_python):
    from playwright.sync_api import sync_playwright
    from wide_portrait import prepare

    data = sys.stdin.buffer.read(PHOTO_BYTES + 1)
    if not data or len(data) > PHOTO_BYTES:
        raise PortraitError(413, 'This photo is too large to prepare.')
    check_photo(data, mime)
    file = {'name': 'guest.' + TYPES[mime][1], 'mimeType': mime, 'buffer': data}
    face = options.get('face')
    group = 'faces' in options
    args = argparse.Namespace(
        garden=folder / 'garden.html',
        layout=options['layout'],
        face=(face + 1 if type(face) is int else None),
        face_box=(face if isinstance(face, dict) else None),
        trace_nose=group or options.get('traceNose', False),
        trace_brows=group or options.get('traceBrows', False),
        trace_smile=group or options.get('traceSmile', False),
        trace_eyes=group or options.get('traceEyes', False),
        hair_woodcut=options.get('hairWoodcut', False),
        flowing_hair=options.get('flowingHair', False),
        full_hair=options.get('longHair', False),
        rake_print=options.get('rakePrint', False),
        cheek_print=options.get('cheekPrint', False),
        group_locks=options.get('groupLocks', False),
        model_python=Path(model_python),
    )
    output = folder / 'drawing'
    output.mkdir(mode=0o700)
    with (
        sync_playwright() as engine,
        engine.chromium.launch(
            executable_path=browser, args=['--disable-background-networking', '--disable-breakpad']
        ) as chrome,
    ):
        context = chrome.new_context(offline=True, service_workers='block')
        context.route('http://**/*', lambda request: request.abort())
        context.route('https://**/*', lambda request: request.abort())
        if group:
            from wide_group_portrait import prepare_group

            try:
                result = prepare_group(context.new_page(), args, output, upload=file, selected_faces=options['faces'])
            except ValueError:
                if args.group_locks:
                    raise PortraitError(422, 'The long hair could not fit on both sides at this size.') from None
                raise PortraitError(422, 'The selected faces could not all be engraved clearly in this center.') from None
            if result['method'] != 'group-engraving' or result['people'] != len(options['faces']):
                raise PortraitError(422, 'The prepared drawing could not include every selected face.')
            if args.group_locks and (type(result.get('locks')) is not int or result['locks'] < 1):
                raise PortraitError(422, 'The long hair could not fit on both sides at this size.')
        else:
            try:
                result = prepare(context.new_page(), args, output, upload=file)
            except Exception as error:
                message = str(error)
                if 'face number is outside' in message or 'Select a face in this photo' in message:
                    raise PortraitError(
                        422, 'The chosen face no longer matches this photo. Select the face again.'
                    ) from None
                raise
    drawing = output / 'portrait.oasisportrait'
    if drawing.stat().st_size > DRAWING_BYTES:
        raise PortraitError(422, 'This portrait has too much detail for a guest drawing.')
    response = {
        'drawing': json.loads(drawing.read_text()),
        'method': result['method'],
    }
    if group:
        response['people'] = result['people']
        if args.group_locks:
            response['locks'] = result['locks']
    else:
        response['note'] = result['note']
    for flag, key in TRACE_FEATURES.items():
        if options.get(flag):
            response[key] = result[key]
    for key, folder_name in ALTERNATE_FOLDERS.items():
        if result.get(key, {}).get('applied'):
            alternate = output / folder_name / 'portrait.oasisportrait'
            if alternate.stat().st_size > DRAWING_BYTES:
                response[key] = {'applied': False, 'note': 'This version has too much detail for a guest drawing.'}
            else:
                response[key + 'Drawing'] = json.loads(alternate.read_text())
    return response


def stop_worker(process):
    # Playwright starts Chromium in a separate process group. Reap the whole
    # process tree, including the local model and Chromium's utility processes.
    import psutil

    try:
        root = psutil.Process(process.pid)
        root.suspend()
        # Stop descendants before taking the final inventory. A browser
        # launching its renderer at the deadline cannot leave that child behind.
        children = set()
        while True:
            unseen = set(root.children(recursive=True)) - children
            if not unseen:
                break
            for child in unseen:
                try:
                    child.suspend()
                except psutil.NoSuchProcess:
                    pass
            children.update(unseen)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            root.kill()
        except psutil.NoSuchProcess:
            pass
        psutil.wait_procs(children, timeout=2)
    except psutil.NoSuchProcess:
        pass
    process.kill()
    process.wait(timeout=5)


def installed_renderer(gallery):
    """Pin the exact room gallery, then run each image decoder and model inside a timed worker."""
    if any(find_spec(module) is None for module in ('psutil', 'PIL', 'playwright', 'cv2', 'scipy')):
        raise ValueError('Install the local portrait tool and its offline browser dependencies first.')
    from playwright.sync_api import sync_playwright
    from wide_portrait import chromium

    root = Path(__file__).resolve().parents[1]
    model_python = root / 'build/p2s-venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    model_dir = Path.home() / '.cache/photo2sand'
    if not model_python.is_file() or not all(
        (model_dir / name).is_file() for name in ('face_landmarker.task', 'selfie_multiclass_256x256.tflite')
    ):
        raise ValueError(
            'Install the offline photo2sand environment and both local models before enabling photo portraits.'
        )
    with sync_playwright() as engine:
        browser = chromium(engine, None)

    def render(data, mime, options):
        with tempfile.TemporaryDirectory(prefix='oasis-private-portrait-') as temp:
            folder = Path(temp)
            # Only drawing files and the offline garden are written. The photo
            # passes through the local pipe into an in-memory browser File.
            (folder / 'garden.html').write_bytes(gallery)
            cmd = [
                sys.executable,
                __file__,
                str(folder),
                json.dumps(options, separators=(',', ':')),
                mime,
                browser,
                str(model_python),
            ]
            env = dict(
                os.environ, TMPDIR=temp, TEMP=temp, TMP=temp, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1'
            )
            with subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
            ) as process:
                try:
                    body, _ = process.communicate(input=data, timeout=PREPARE_SECONDS)
                except subprocess.TimeoutExpired:
                    stop_worker(process)
                    raise PortraitError(
                        504, 'Photo preparation timed out. Try a closer crop or use the ordinary preview.'
                    ) from None
            alternates = sum(bool(options.get(flag)) for flag, key in TRACE_FEATURES.items()
                             if key in ALTERNATE_FOLDERS)
            limit = DRAWING_BYTES * (1 + alternates) + 4096
            if process.returncode or len(body) > limit:
                raise PortraitError(503, 'The laptop could not prepare this photo. Use the ordinary preview.')
            result = json.loads(body)
            if 'error' in result:
                raise PortraitError(result['status'], result['error'])
            drawing = result['drawing']
            if (
                abs(drawing['diameterMm'] - options['diameterMm']) > 0.01
                or abs(drawing['grooveMm'] - options['grooveMm']) > 0.01
            ):
                raise PortraitError(409, 'The prepared portrait does not match this room.')
            return result

    return render


if __name__ == '__main__':
    try:
        response = run_worker(Path(sys.argv[1]), json.loads(sys.argv[2]), *sys.argv[3:])
    except PortraitError as failure:
        response = {'error': str(failure), 'status': failure.status}
    except Exception:
        response = {
            'error': 'The laptop could not prepare this photo. Use the ordinary preview.',
            'status': 503,
        }
    sys.stdout.write(json.dumps(response, allow_nan=False, separators=(',', ':')))
