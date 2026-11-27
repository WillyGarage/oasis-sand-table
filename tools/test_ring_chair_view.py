#!/usr/bin/env python3
"""Test camera-only controls on two local phones. Supply a two-layout gallery and a two-person photo."""
import argparse
import hashlib
import math
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright

from test_garden_room import caption, choose, drawing_files, room
from test_ring_guest_border import MOBILE, save
from test_ring_object_photo import expand
from test_ring_shadows import ready


def open_layout(page, url, layout):
    endpoint = url + '/api/garden/' + layout
    with page.expect_response(lambda response: response.url == endpoint and response.request.method == 'GET'):
        page.goto(url + '/garden?layout=' + layout)
    expect(page.locator('.controls')).not_to_have_attribute('inert', '')
    expect(page.locator('#chairView')).to_have_attribute('aria-pressed', 'false')


def screen_state(page):
    # The PNG is the actual selected drawing stage; the download URLs identify
    # the original Blob objects. Comparing names alone would miss regeneration.
    pixels = page.locator('#sand').evaluate('im=>im.src')
    links = page.locator('#downloads a, #roomFiles a').evaluate_all('links=>links.map(a=>[a.download,a.href])')
    return hashlib.sha256(pixels.encode()).digest(), links


def headings(page, seats):
    for label, angle in seats:
        expect(page.locator('#seatNumber')).to_have_text(label)
        rotation = page.locator('#sand').evaluate('im=>parseFloat(getComputedStyle(im).rotate)||0')
        # The physical radius pointing to this viewer must point down on the screen.
        assert abs(math.remainder(math.radians(rotation) - angle - math.pi/2, math.tau)) < 1e-5, (label, rotation)
        page.locator('#nextSeat').tap()
    expect(page.locator('#seatNumber')).to_have_text(seats[0][0])


def camera_cycle(page, seats):
    cached = screen_state(page)
    camera = page.locator('#chairView')
    camera.tap()
    expect(camera).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.sand-display.from-chair')).to_have_count(1)
    assert screen_state(page) == cached
    headings(page, seats)
    assert screen_state(page) == cached
    camera.tap()
    expect(camera).to_have_attribute('aria-pressed', 'false')
    expect(page.locator('.sand-display.from-chair')).to_have_count(0)
    assert screen_state(page) == cached, 'Changing seats replaced the selected render or its motion links.'
    return cached[0]


def seated_pair(phone, pair):
    expand(phone, '#centerPhoto')
    phone.locator('#portraitFile').set_input_files(pair)
    phone.locator('#portraitMode').select_option('group')
    phone.locator('#portraitStyle').select_option('seats')
    phone.locator('#portraitSubmit').click()
    ready(phone)
    expect(phone.locator('#seatNumber')).to_have_text('Seat 1 of 2')


def check_garden(host, guest, url, pair):
    angles = host.locator('#scene').evaluate('s=>JSON.parse(s.textContent).live.planner.geometry.angles')
    named = [(name+'’s chair', angle) for name, angle in zip(('Thomas','Alex','Lek'), angles, strict=True)]
    stages = set()
    for stage in ('original','cleared','redrawn'):
        choose(host, 'stage', stage)
        if stage == 'redrawn':
            files = drawing_files(host, '#downloads')
        stages.add(camera_cycle(host, named))
    assert len(stages) == 3 and drawing_files(host, '#downloads') == files
    expect(guest.locator('#chairView')).to_have_attribute('aria-pressed', 'false')
    seated_pair(host, pair)
    kept, _ = save(host, url+'/api/garden/garden')
    assert kept['state']['portraitSeats'] == 2
    caption(guest, kept['state']['portrait'])
    choose(guest, 'zone', 'middle')
    camera_cycle(guest, named)


def check_portrait(host, guest, url, pair):
    for phone in (host,guest):
        open_layout(phone, url, 'portrait')
    camera_cycle(host, [('Near side', -math.pi/2), ('Opposite side', math.pi/2)])
    seated_pair(host, pair)
    expand(host, '#portraitSource')
    source = host.locator('#sourceImage')
    source_url = source.get_attribute('src')
    boxes = host.locator('#faceBoxes button')
    expect(boxes).to_have_count(2)
    framing = boxes.evaluate_all('items=>items.map(b=>[b.style.cssText,b.getAttribute("aria-pressed")])')

    seats = [('Seat 1 of 2', -math.pi/2), ('Seat 2 of 2', -3*math.pi/2)]
    zoom = host.locator('#zoom')
    tracks = drawing_files(host,'#downloads')
    unzoomed = screen_state(host)
    zoom.tap()
    expect(zoom).to_have_attribute('aria-pressed','true')
    assert screen_state(host) == unzoomed, 'Enlarging the portrait replaced its render or motion links.'
    transform = host.locator('#sand').evaluate('im=>im.style.transform')
    assert transform and 'scale' in transform
    camera_cycle(host,seats)
    expect(zoom).to_have_attribute('aria-pressed','true')
    assert host.locator('#sand').evaluate('im=>im.style.transform') == transform
    expect(source).to_have_attribute('src',source_url)
    assert boxes.evaluate_all('items=>items.map(b=>[b.style.cssText,b.getAttribute("aria-pressed")])') == framing
    assert source.evaluate("""im=>!im.closest('.sand-display') && getComputedStyle(im).transform==='none'
                              && getComputedStyle(im).rotate==='none'""")
    assert drawing_files(host,'#downloads') == tracks
    host.locator('#chairView').tap()
    host.locator('#nextSeat').tap()
    expect(host.locator('#seatNumber')).to_have_text('Seat 2 of 2')
    zoom.tap()
    expect(zoom).to_have_attribute('aria-pressed','false')
    expect(host.locator('#chairView')).to_have_attribute('aria-pressed','true')
    expect(host.locator('#seatNumber')).to_have_text('Seat 2 of 2')
    assert screen_state(host) == unzoomed and drawing_files(host,'#downloads') == tracks

    patch, revision = save(host, url+'/api/garden/portrait')
    assert [(f['name'],f['text'].encode()) for f in patch['motion']['files']] == tracks
    assert patch['state']['portraitSeats'] == 2
    caption(guest, patch['state']['portrait'])
    expect(guest.locator('#chairView')).to_have_attribute('aria-pressed','false')
    expect(guest.locator('#seatNumber')).to_have_text('Seat 1 of 2')
    assert drawing_files(guest,'#roomFiles') == tracks
    camera_cycle(guest,seats)
    open_layout(guest, url, 'portrait')
    expect(guest.locator('#seatNumber')).to_have_text('Seat 1 of 2')
    assert drawing_files(guest,'#roomFiles') == tracks

    # A border-change replay still has the saved pair in its center.
    choose(guest,'zone','outer')
    choose(guest,'stage','cleared')
    camera_cycle(guest,seats)
    current = guest.request.get(url+'/api/garden/portrait').json()
    assert current['revision'] == revision and current['state'] == patch['state']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('pair', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp, room(args.gallery, Path(temp)/'garden.db') as url, sync_playwright() as pw:
        chrome = next(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux64/chrome'))
        with pw.chromium.launch(executable_path=str(chrome)) as browser, browser.new_page(**MOBILE) as host, browser.new_page(**MOBILE) as guest:
            errors, writes = [], []
            for phone in (host,guest):
                phone.on('pageerror',lambda error: errors.append(str(error)))
                phone.route('http**://**/*',lambda r: r.continue_() if r.request.url.startswith(url+'/') else r.abort())
                phone.on('request',lambda req: writes.append(req.url) if req.method != 'GET' else None)
                open_layout(phone,url,'garden')
            check_garden(host,guest,url,args.pair)
            check_portrait(host,guest,url,args.pair)
            assert writes == [url+'/api/garden/garden',url+'/api/garden/portrait'] and not errors, (writes,errors)
    print('Both phones passed. Chair changes preserved all three stages, the source photo and the exact motion downloads.')


if __name__ == '__main__':
    main()
