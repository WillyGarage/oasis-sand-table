#!/usr/bin/env python3
"""Verify the two group portrait styles using a real seven-person photo in the phone UI.

    python3 tools/test_ring_faces.py garden.html single-face.jpg seven-person-group.jpg \
        --shoulder captures/photo2sand_test/ohara.jpg
"""
import argparse
import hashlib
import io
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

import check_ring_scene as check
from test_ring_photo import check_portrait, frame, ordinary_erase_pitch


def no_faces():
    """A high-contrast geometric drawing produces a valid engraving with zero faces."""
    im = Image.new('RGB', (480, 320), '#f9f6ef')
    pen = ImageDraw.Draw(im)
    pen.polygon([(50, 260), (150, 54), (255, 260)], fill='#35474b')
    pen.rectangle((272, 105, 428, 258), fill='#6b372a')
    data = io.BytesIO()
    im.save(data, format='PNG')
    return {'name': 'shapes.png', 'mimeType': 'image/png', 'buffer': data.getvalue()}


def ready(page):
    page.wait_for_function("""!document.querySelector('#portraitSubmit').disabled &&
        document.querySelector('input[name=stage]:checked').value === 'redrawn' &&
        !document.querySelector('#portraitSource').hidden""")


def tilted_pair(page, url, source):
    """Two people in one photo, with one head tilted away from the upright scan."""
    page.goto(url+'?layout=portrait#photos')
    page.locator('#portraitFile').set_input_files(source)
    page.locator('#portraitMode').select_option('group')
    page.locator('#portraitStyle').select_option('faces')
    page.locator('#portraitSubmit').click()
    ready(page)
    assert page.locator('#faceBoxes button[aria-pressed=true]').count() == 2
    close = result(page, 'faces')
    assert close['count'] == 2 and close['style'] == 'faces'
    plan = check.joined(close['segments'], close['segments'][0][0], close['segments'][0][0], 'tilted pair')
    assert len(plan) > 2
    page.locator('#portraitStyle').select_option('pose')
    ready(page)
    assert result(page, 'pose')['count'] == 2


def result(page, style):
    # Use the displayed source blob. This works for embedded examples and
    # uploaded camera photos without assuming they have the same resolution.
    return page.evaluate("""async style => {
      const scene = JSON.parse(document.querySelector('#scene').textContent);
      const source = await (await fetch(document.querySelector('#sourceImage').src)).blob();
      const file = new File([source], 'source', {type:source.type});
      const zone = scene.zones.center;
      const grooves = 2 * zone.transit.at(-1)[1] / scene.live.groove;
      const photo = await GuestPhoto.fromFile(file, {group:true, groupStyle:style, portraitDiameterGrooves:grooves});
      const plan = OasisRingPlanner.photo(zone, photo.points);
      const digest = await crypto.subtle.digest('SHA-256', await source.arrayBuffer());
      return {style:photo.groupStyle, count:photo.facesDetected, points:photo.points, segments:plan.segments,
              sha:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join(''),
              groove:scene.live.groove, normal:zone.erase, fine:!!zone.photoErase};
    }""", style)


def verify_download(page, analysis, folder):
    details = page.locator('#downloads')
    if not details.evaluate('el=>el.open'):
        details.locator('summary').click()
    links = details.locator('a')
    links.first.wait_for()
    parts = []
    for link in links.all():
        with page.expect_download() as pending:
            link.click()
        file = pending.value
        assert file.suggested_filename.startswith('center-portrait-')
        file.save_as(folder / file.suggested_filename)
        parts.append(check.read_path(folder, file.suggested_filename))
    segments = analysis['segments']
    dock = segments[0][0]
    route = check.joined(parts, dock, dock, 'close group portrait')
    error = check_portrait(analysis['points'], segments, route, analysis['groove'],
                           ordinary_erase_pitch(analysis['normal']), analysis['fine'])
    return len(route), len(parts), error / analysis['groove']


def pick_one_person(page, url, source):
    page.goto(url + '?layout=portrait#photos')
    page.locator('#portraitFile').set_input_files({'name':'new-group.jpg', 'mimeType':'image/jpeg',
                                                   'buffer':source.read_bytes()})
    page.locator('#portraitSubmit').click()
    ready(page)
    boxes = page.locator('#faceBoxes button')
    assert boxes.count() > 1
    original = frame(page)
    boxes.nth(1).click()
    ready(page)
    assert boxes.nth(1).get_attribute('aria-pressed') == 'true'
    other = frame(page)
    assert not np.array_equal(original, other)
    page.locator('#layout').select_option('garden')
    ready(page)
    assert boxes.nth(1).get_attribute('aria-pressed') == 'true'
    page.locator('#layout').select_option('portrait')
    ready(page)
    assert np.array_equal(frame(page), other)

    # Draw a face-sized square over the first person using the actual source image.
    # The resulting square is held in photo coordinates when the layout resizes.
    page.locator('#frameFace').click()
    page.locator('#sourceFrame').scroll_into_view_if_needed()
    first = boxes.first.bounding_box()
    page.mouse.move(first['x']+1, first['y']+1)
    page.mouse.down()
    page.mouse.move(first['x']+first['width']-1, first['y']+first['height']-1, steps=8)
    page.mouse.up()
    ready(page)
    assert page.locator('#faceBoxes .frame').count() == 1
    assert page.locator('#faceBoxes button[aria-pressed=true]').count() == 0
    assert not np.array_equal(frame(page), other)
    assert page.locator('#keep').is_visible()
    # Switching the selected file must discard the previous face.
    page.locator('#portraitFile').set_input_files(source)
    page.locator('#portraitSubmit').click()
    ready(page)
    assert np.array_equal(frame(page), original)


def correct_group(page, url, source):
    page.goto(url + '?layout=portrait#photos')
    page.locator('#portraitFile').set_input_files(source)
    page.locator('#portraitMode').select_option('group')
    style = page.locator('#portraitStyle')
    style.select_option('faces')
    page.locator('#portraitSubmit').click()
    ready(page)
    source_panel = page.locator('#portraitSource')
    if not source_panel.evaluate('el => el.open'):
        source_panel.locator('summary').click()
    boxes = page.locator('#faceBoxes button')
    selected = page.locator('#faceBoxes button[aria-pressed=true]')
    assert selected.count() == 7

    # Leave out one real person, then frame them again slightly more tightly.
    # The new square stands in for a face that the automatic pass missed.
    original_count = boxes.count()
    face = page.get_by_role('button', name=selected.first.get_attribute('aria-label'), exact=True)
    face.click()
    ready(page)
    assert selected.count() == 6
    page.locator('#frameFace').click()
    page.locator('#sourceFrame').scroll_into_view_if_needed()
    # Clicking an input can scroll the mobile image; measure the unselected
    # box again relative to the new viewport before starting the gesture.
    area = face.bounding_box()
    x, y, w, h = (area[k] for k in ('x','y','width','height'))
    page.mouse.move(x+w*.04, y+h*.04)
    page.mouse.down()
    page.mouse.move(x+w*.96, y+h*.96, steps=8)
    page.mouse.up()
    ready(page)
    assert selected.count() == 7 and boxes.count() == original_count + 1
    assert face.get_attribute('aria-pressed') == 'false'
    manual = boxes.last
    assert manual.get_attribute('aria-pressed') == 'true'
    corrected = frame(page)

    manual.click()
    ready(page)
    assert selected.count() == 6 and manual.get_attribute('aria-pressed') == 'false'
    manual.click()
    ready(page)
    assert np.array_equal(corrected, frame(page))
    style.select_option('pose')
    ready(page)
    assert selected.count() == 7 and not np.array_equal(corrected, frame(page))
    style.select_option('faces')
    ready(page)
    assert np.array_equal(corrected, frame(page))
    for layout in ('garden','portrait'):
        page.locator('#layout').select_option(layout)
        ready(page)
        assert selected.count() == 7 and manual.get_attribute('aria-pressed') == 'true'
    assert np.array_equal(corrected, frame(page))
    page.locator('#keep').click()
    page.reload()
    assert '7 faces together' in page.locator('.caption').inner_text()
    assert np.abs(frame(page).astype(float) - corrected).mean() < 1
    page.locator('#reset').click()


def run(page, url, single, seven, shoulder, folder):
    pick_one_person(page, url, seven)
    correct_group(page, url, seven)
    page.goto(url + '?layout=portrait#example-faces')
    ready(page)
    style, mode = page.locator('#portraitStyle'), page.locator('#portraitMode')
    assert (style.input_value(), mode.input_value()) == ('faces', 'group')
    assert page.locator('#sampleFaces').is_visible()
    example = result(page, 'faces')
    assert (example['style'], example['count']) == ('faces', 7)
    verify_download(page, example, folder)

    page.goto(url + '?layout=portrait#photos')
    page.reload()
    file = page.locator('#portraitFile')
    file.set_input_files(seven)
    mode.select_option('group')
    assert style.input_value() == 'heads'
    style.select_option('pose')
    page.locator('#portraitSubmit').click()
    ready(page)
    pose = result(page, 'pose')
    assert (pose['style'], pose['count']) == ('pose', 7)
    sha = hashlib.sha256(seven.read_bytes()).hexdigest()
    assert pose['sha'] == sha
    original_pose = frame(page)
    # A result from a slower conversion must not replace a newer selection.
    page.evaluate("""() => {
      const convert = GuestPhoto.fromFile;
      window.releaseOldPortrait = null;
      GuestPhoto.fromFile = async (file, options) => {
        const result = await convert(file, options);
        if (options.groupStyle === 'faces') {
          GuestPhoto.fromFile = convert;
          await new Promise(resolve => { window.releaseOldPortrait = resolve; });
        }
        return result;
      };
    }""")
    style.select_option('faces')
    page.wait_for_function("typeof window.releaseOldPortrait === 'function'")
    assert page.locator('#keep').is_hidden() and page.locator('#downloads').is_hidden()
    style.select_option('pose')
    ready(page)
    page.evaluate("""async () => {
      window.releaseOldPortrait();
      await new Promise(requestAnimationFrame);
    }""")
    assert np.array_equal(frame(page), original_pose)
    style.select_option('faces')
    ready(page)
    close = result(page, 'faces')
    assert (close['style'], close['count'], close['sha']) == ('faces', 7, sha)
    assert close['points'] != pose['points']
    assert file.evaluate('el=>el.files[0].name') == seven.name
    tight = frame(page)
    height = len(tight)
    y, x = np.mgrid[-1:1:complex(height), -1:1:complex(height)]
    radius = np.hypot(x, y)
    high = close['segments'][0][-1][1]
    centre = radius < high - close['groove']
    outside = ((radius > high + 3*close['groove']) & (radius < .98) & ((y < 0) | (abs(x) > 3*close['groove'])))
    assert np.array_equal(original_pose[outside], tight[outside])
    assert abs(original_pose[centre].astype(float) - tight[centre]).mean() > 1
    wide = verify_download(page, close, folder)

    page.locator('#layout').select_option('garden')
    ready(page)
    assert style.input_value() == 'faces' and mode.input_value() == 'group'
    small = result(page, 'faces')
    assert (small['style'], small['count'], small['sha']) == ('faces', 7, sha)
    normal = verify_download(page, small, folder)
    page.locator('#layout').select_option('portrait')
    ready(page)
    assert style.input_value() == 'faces'
    assert np.array_equal(frame(page), tight)
    style.select_option('pose')
    ready(page)
    assert np.array_equal(frame(page), original_pose)
    style.select_option('faces')
    ready(page)
    title = page.locator('.caption').inner_text()
    assert '7' in title
    page.locator('#keep').click()
    page.locator('input[name=zone][value=outer] + span').click()
    page.locator('input[name=stage][value=redrawn] + span').click()
    border = frame(page)
    assert np.array_equal(border[centre], tight[centre])
    assert np.any(border[outside] != tight[outside])
    page.locator('#keep').click()
    page.reload()
    assert page.locator('.caption').inner_text() == title
    assert page.locator('#reset').is_visible() and page.locator('#keep').is_hidden()

    fallbacks = [(single, 1), (no_faces(), 0)]
    if shoulder:
        fallbacks.append((shoulder, 1))
    for src, count in fallbacks:
        box = page.locator('#centerPhoto')
        if not box.evaluate('el=>el.open'):
            box.locator(':scope > summary').click()
        file.set_input_files(src)
        mode.select_option('group')
        style.select_option('faces')
        page.locator('#portraitSubmit').click()
        ready(page)
        fallback = result(page, 'faces')
        plain = result(page, 'pose')
        assert (fallback['count'], fallback['style']) == (count, 'pose')
        assert plain['count'] == count
        assert fallback['points'] == plain['points'], 'Fallback changed the original pose'
        status = page.locator('#portraitStatus').inner_text().lower()
        if count:
            assert 'one face' in status and 'pose' in status
        else:
            assert 'no face' in status
        verify_download(page, fallback, folder)

    print(f'Seven faces. Wide center {wide[0]} points in {wide[1]} files ({wide[2]:.3f} groove maximum trace error); '
          f'garden center {normal[0]} in {normal[1]} ({normal[2]:.3f} groove). '
          'Manual group corrections survived style changes, layout changes and saving. '
          'Source, example and 1- and 0-face fallbacks passed.')
    if shoulder:
        print('Both portrait styles excluded the sleeve from the face choices.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', type=Path)
    parser.add_argument('single', type=Path)
    parser.add_argument('seven', type=Path)
    parser.add_argument('--shoulder', type=Path, help='O’Hara portrait with a patterned sleeve beside the face')
    parser.add_argument('--tilted-pair', type=Path, action='append', default=[],
                        help='Two-person photo in which the upright scan misses a tilted head')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            run(page, args.page.resolve().as_uri(), args.single, args.seven, args.shoulder, Path(tmp))
            for source in args.tilted_pair:
                tilted_pair(page, args.page.resolve().as_uri(), source)
            assert not errors, errors
