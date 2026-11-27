"""Follow a selected face from a phone photo through the guest editor and a second phone."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import sync_playwright, expect

import garden_portrait
from test_garden_room import choose, drawing_files, room
from test_guest_group_engraving import open_photo_room
from test_ring_guest_border import MOBILE, save
from test_ring_shadows import ready
from wide_portrait import chromium


def select_person(phone, source, index, heic_endpoint=None):
    phone.locator('#portraitFile').set_input_files(source)
    phone.locator('#portraitSubmit').click()
    if heic_endpoint:
        expect(phone.locator('#openHeic')).to_be_visible()
        assert not phone.evaluate('(url) => performance.getEntriesByName(url).length', heic_endpoint)
        with phone.expect_response(heic_endpoint) as converted:
            phone.locator('#openHeic').click()
        assert converted.value.ok and converted.value.headers['cache-control'] == 'no-store'
        expect(phone.locator('#openHeic')).to_be_hidden()
    boxes = phone.locator('#faceBoxes button')
    expect(boxes.nth(index)).to_be_attached(timeout=30000)
    phone.locator('#portraitSource').evaluate('panel => panel.open = true')
    boxes.nth(index).click()
    ready(phone)


def check(editor, photo, index):
    uploads = []
    original_renderer = garden_portrait.installed_renderer
    def record_host_input(gallery):
        render = original_renderer(gallery)
        def recording(data, mime, options):
            uploads.append((data, mime, options))
            return render(data, mime, options)
        return recording
    with patch.object(garden_portrait, 'installed_renderer', record_host_input), tempfile.TemporaryDirectory() as temp, \
            room(editor, Path(temp)/'garden.db', photo_portraits=True) as url, \
            sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser, \
            browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
        endpoint = url + '/api/portrait'
        requests = []
        host.on('request', lambda req: requests.append(req) if req.url == endpoint else None)
        open_photo_room(host, url, 'portrait')
        heic = photo.suffix.lower() in ('.heic', '.heif')
        source = dict(name=photo.name, mimeType='image/heic' if heic else 'image/avif', buffer=photo.read_bytes())
        select_person(host, source, index, endpoint+'/heic' if heic else None)
        assert not requests
        dimensions = host.locator('#portraitFile').evaluate('''async node => {
          const bitmap = await createImageBitmap(node.files[0]);
          try {return [bitmap.width, bitmap.height]} finally {bitmap.close()}
        }''')
        with host.expect_response(endpoint, timeout=110000) as response:
            host.locator('#portraitHair').click()
        assert response.value.ok, response.value.status
        expect(host.locator('#portraitHair')).to_have_text('Show first drawing', timeout=20000)
        accepted = drawing_files(host, '#downloads')
        assert len(requests) == 1
        request = requests[0]
        assert request.headers['content-type'] == 'image/jpeg'
        assert len(uploads) == 1 and uploads[0][1] == 'image/jpeg'
        jpg = uploads[0][0]
        with Image.open(BytesIO(jpg)) as converted:
            assert converted.format == 'JPEG' and list(converted.size) == dimensions
            assert not converted.getexif()
        first_selection = json.loads(request.headers['x-oasis-portrait'])['face']
        # Repeat the choice with exactly the converted pixels. Ordinary JPEGs keep their bytes.
        select_person(host, dict(name='same-pixels.jpg', mimeType='image/jpeg', buffer=jpg), index)
        with host.expect_response(endpoint, timeout=110000) as control:
            host.locator('#portraitHair').click()
        assert control.value.ok, control.value.status
        expect(host.locator('#portraitHair')).to_have_text('Show first drawing', timeout=20000)
        assert len(uploads) == 2 and uploads[-1][0] == jpg
        second_selection = json.loads(requests[-1].headers['x-oasis-portrait'])['face']
        assert second_selection == first_selection
        assert drawing_files(host, '#downloads') == accepted
        upload, _ = save(host, url+'/api/garden/portrait')
        assert [f['text'].encode() for f in upload['motion']['files']] == [data for _, data in accepted]
        open_photo_room(guest, url, 'portrait')
        choose(guest, 'zone', 'center')
        assert drawing_files(guest, '#roomFiles') == accepted
        print('Two phones, selected face', index+1, 'of group,', dimensions, 'pixels, signed files',
              [hashlib.sha256(data).hexdigest() for _, data in accepted])


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('editor', type=Path)
    cli.add_argument('photo', type=Path, help='AVIF or HEIC group photo')
    cli.add_argument('--face', type=int, default=2, help='One-based face in the picker')
    args = cli.parse_args()
    check(args.editor, args.photo, args.face-1)
