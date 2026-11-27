"""Exercise anonymous full-size portrait comparisons on a phone and desktop."""
import argparse
import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from wide_portrait import chromium

URL = 'https://preview.example.com/oasis-portrait-gallery.html'


def check_collection(page, url, catalog):
    for group in ('real', 'mini', 'wide'):
        page.goto(f'{url}#collection/{group}')
        links = page.locator('.archive a')
        expected = {}
        for entry in catalog['entries']:
            matches = []
            for index, version in enumerate(entry['versions'], 1):
                medium = version['medium']
                kind = 'real' if medium == 'Real Mini sand' else 'wide' if medium.startswith('36-inch') else 'mini'
                if kind == group:
                    matches.append((datetime.fromisoformat(version.get('date', entry['date'])), index))
            if matches:
                _, index = max(matches)
                expected[f"#{entry['id']}/{index}"] = entry['versions'][index - 1]
        expect(links).to_have_count(len(expected))
        visible = links.evaluate_all("items=>items.map(a=>[a.hash,a.querySelector('.medium').textContent])")
        assert dict(visible) == {k:v['label'] for k,v in expected.items()}
        hash_value = visible[0][0]
        links.first.click()
        expect(page.locator('#mainCaption')).to_contain_text(expected[hash_value]['label'])
        assert page.url == url + hash_value
        page.locator('#browsePortraits').click()
        assert page.url == f'{url}#collection/{group}'
        page.reload()
        expect(page.locator('.collectionViews [aria-current=page]')).to_have_attribute('href', f'#collection/{group}')
    page.get_by_role('link', name='All studies', exact=True).click()
    expect(page.locator('.archive a')).to_have_count(len(catalog['entries']))


def check_routes(page, url, catalog, entry, screenshots, width):
    study = entry['routes']
    address = f"{url}#{entry['id']}"
    page.goto(address+'/1/detail')
    page.get_by_role('link', name='Compare drawing routes').click()
    assert page.url == address+'/routes'
    expect(page.locator('#routeTitle')).to_be_focused()
    assert entry['name'] not in page.locator('body').inner_text()
    slider = page.get_by_role('slider')
    index = next(i for i, frame in enumerate(study['frames']) if frame['meters'] == study['initialMeters'])
    expect(slider).to_have_value(str(index))
    page.screenshot(path=screenshots/f"{width}-{entry['id']}-routes.png")
    slider.press('Home')
    expect(page.locator('#prevRouteStep')).to_be_disabled()
    for i, frame in enumerate([*study['frames'], study['finished']]):
        if i:
            page.locator('#nextRouteStep').click()
        expect(slider).to_have_value(str(i))
        for key in ('earlier', 'revised'):
            image = page.locator('#'+key+'Route')
            expect(image).to_be_visible()
            expect(image).to_have_attribute('src', catalog['images'][frame[key]])
            assert image.evaluate('async im => {await im.decode();return im.naturalWidth===im.naturalHeight}')
            if frame.get('seconds', {}).get(key, 0):
                seconds = frame['seconds'][key]
                expected = (f'{seconds//60}:{seconds%60:02d} on the Mini' if study['paths'][key]['timing'] == 'measured'
                            else f'about {(seconds+30)//60} min')
                expect(page.locator('#'+key+'Label')).to_contain_text(expected)
    expect(page.locator('#nextRouteStep')).to_be_disabled()
    expect(page.locator('#routeDistance')).to_have_text('Finished')
    for key in ('earlier', 'revised'):
        expect(page.locator('#'+key+'Label')).to_contain_text(str(study['paths'][key]['meters']))
    page.get_by_role('button', name=study['paths']['revised']['label'], exact=True).click()
    expect(page.locator('#earlierFigure')).to_be_hidden()
    expect(page.locator('#revisedFigure')).to_be_visible()
    page.locator('#prevRouteStep').click()
    expect(page.locator('#routeDistance')).to_contain_text('m')
    page.get_by_role('button', name='Side by side', exact=True).click()
    expect(page.locator('#earlierFigure')).to_be_visible()
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
    page.locator('#leaveRoutes').click()
    assert page.url == address+'/1'
    page.goto(address+'/routes')
    page.reload()
    expect(slider).to_have_value(str(index))
    expect(page.locator('#galleryPage')).to_be_hidden()


def check_pair_choice(page, url, entry):
    slug = entry['id']
    versions = entry['versions']
    page.goto(url + '?compare=1#' + slug + '/7/detail')
    select = page.get_by_label('Compare with', exact=True)
    expect(select).to_have_value(str(entry['compare'][6]))
    select.select_option('7')
    address = page.url
    expect(page.locator('#otherCaption')).to_contain_text(versions[7]['label'])
    page.reload()
    expect(select).to_have_value('7')
    expect(page.locator('#mainCaption')).to_contain_text(versions[6]['label'])
    expect(page.locator('#otherImage')).to_have_attribute('src', page.evaluate(
        '() => catalog.images[selected.versions[7].views[1]]'))
    page.get_by_label('Portrait', exact=True).select_option('7')
    expect(select).to_have_value('6')
    expect(page.locator('#otherCaption')).to_contain_text(versions[6]['label'])
    page.locator('#pair').click()
    expect(select).to_be_hidden()
    assert 'against=' not in page.url
    page.goto(address.split('#')[0] + '#mini-boardwalk-pair/7/detail')
    expected = page.evaluate('() => comparisonPartner(selected,version)')
    expect(select).to_have_value(str(expected))


def check_sequence_playback(page, url, entry):
    page.goto(url + '#' + entry['id'] + '/progress')
    slider = page.locator('#frameIndex')
    play = page.locator('#playSequence')
    frames = entry['sequence']
    both = page.get_by_role('button', name='Side by side', exact=True)
    both.click()
    expect(both).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#sequenceImage')).to_have_attribute('alt', 'Photographed sand at 0:00')
    expect(page.locator('#sequencePreviewImage')).to_have_attribute('alt', 'Simulated sand at 0:00')
    assert page.locator('#sequenceImages img:visible').count() == 2
    play.click()
    expect(play).to_have_text('Pause')
    page.clock.run_for(100 + int(20000 * frames[1]['seconds'] / frames[-1]['seconds']))
    assert int(slider.input_value()) >= 1
    instant = frames[int(slider.input_value())]['seconds']
    when = f'{instant//60}:{instant%60:02d}'
    expect(page.locator('#sequenceImage')).to_have_attribute('alt', 'Photographed sand at ' + when)
    expect(page.locator('#sequencePreviewImage')).to_have_attribute('alt', 'Simulated sand at ' + when)
    play.click()
    paused = slider.input_value()
    page.clock.run_for(4000)
    expect(slider).to_have_value(paused)
    play.click()
    page.get_by_role('button', name='Simulation', exact=True).click()
    expect(page.locator('#sequenceOther')).to_be_hidden()
    page.clock.run_for(20500)
    expect(slider).to_have_value(str(len(frames)-1))
    expect(page.locator('#sequenceImage')).to_have_attribute('alt', 'Simulated sand at ' +
            f'{frames[-1]["seconds"]//60}:{frames[-1]["seconds"]%60:02d}')
    play.click()
    expect(slider).to_have_value('0')
    slider.press('ArrowRight')
    expect(play).to_have_text('Play time-lapse')
    page.clock.run_for(4000)
    expect(slider).to_have_value('1')
    play.click()
    page.get_by_role('link', name='Back to portrait', exact=True).click()
    expect(play).to_have_text('Play time-lapse')


def check(browser, gallery, screenshots, width, served):
    with browser.new_context(viewport={'width': width, 'height': 844}) as context:
        url = URL if served else gallery.as_uri()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = page.goto(url)
        assert response.ok
        if served:
            delivered = context.request.get(url)
            assert delivered.ok and hashlib.sha256(delivered.body()).digest() == hashlib.sha256(gallery.read_bytes()).digest()
        catalog = json.loads(page.locator('#catalog').text_content())
        check_collection(page, url, catalog)
        check_pair_choice(page, url, next(e for e in catalog['entries'] if e['id']=='room-for-the-smaller-faces'))
        checked = 0
        for entry in catalog['entries']:
            if 'routes' in entry:
                check_routes(page, url, catalog, entry, screenshots, width)
            view_ids = entry.get('viewIds', [])
            if len(view_ids) > 2:
                for index, version in enumerate(entry['versions'], 1):
                    address = f'{url}#{entry["id"]}/{index}'
                    page.goto(address + '/detail')
                    expect(page.locator('#mainImage')).to_have_attribute('src', catalog['images'][version['views'][1]])
                    for view in [*range(2, len(view_ids)), 0]:
                        button = page.locator('#zoom')
                        expect(button).to_have_text(entry['zoomLabels'][view])
                        button.click()
                        suffix = '/' + view_ids[view] if view else ''
                        assert page.url == address + suffix
                        page.reload()
                        expect(page.locator('#mainImage')).to_have_attribute('src', catalog['images'][version['views'][view]])
            replays = [(entry, entry.get('sequenceVersion', entry['default']), f"#{entry['id']}/progress")] if 'sequence' in entry else []
            replays.extend((v, i, f"#{entry['id']}/{i+1}/progress") for i, v in enumerate(entry['versions']) if 'sequence' in v)
            for i, source in enumerate(entry['versions']):
                if 'replayVersion' in source:
                    target = source['replayVersion']
                    address = next(frag for _, index, frag in replays if index == target)
                    page.goto(url + f"#{entry['id']}/{i+1}")
                    expect(page.get_by_role('link', name='Watch this drawing in real sand')).to_have_attribute('href', address)
            for replay, version_index, address in replays:
                page.goto(url + f"#{entry['id']}/{version_index+1}")
                page.get_by_role('link', name='See the portrait take shape').click()
                assert page.url.endswith(address)
                expect(page.locator('#sequenceTitle')).to_be_focused()
                assert entry['name'] not in page.locator('body').inner_text()
                slider = page.get_by_role('slider')
                slider.focus()
                for index, frame in enumerate(replay['sequence']):
                    if index:
                        slider.press('ArrowRight')
                    expect(slider).to_have_value(str(index))
                    for key, label in [('preview', 'Simulation'), ('photo', 'Real sand')]:
                        button = page.get_by_role('button', name=label, exact=True)
                        button.click()
                        expect(button).to_have_attribute('aria-pressed', 'true')
                        photo = page.locator('#sequenceImage')
                        expect(photo).to_have_attribute('src', catalog['images'][frame[key]])
                        assert photo.evaluate('async im => {await im.decode();return im.naturalWidth===im.naturalHeight}')
                    assert page.locator('#frameTime').inner_text().startswith(
                        f'{frame["seconds"]//60}:{frame["seconds"]%60:02d} of ')
                    if index == len(replay['sequence'])//2:
                        page.screenshot(path=screenshots/f'{width}-{entry["id"]}-{version_index+1}-progress.png')
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.reload()
                expect(slider).to_have_value('0')
                page.get_by_role('link', name='Back to portrait', exact=True).click()
                expect(page.locator('#galleryPage')).to_be_visible()
                assert page.url.endswith(f'#{entry["id"]}/{version_index+1}')
            for pair in entry.get('blindPairs', []):
                a, b = pair
                # Some studies compare several styles with the same central drawing.
                candidates = [(a, b), (b, a)]
                selected = next((i for i, j in candidates if entry['compare'][i] == j), a)
                page.goto(url + f'?compare=1#{entry["id"]}/{selected+1}/detail')
                if selected == a and entry['compare'][a] != b:
                    page.get_by_label('Compare with', exact=True).select_option(str(b))
                button = page.get_by_role('link', name='Compare without labels')
                expected = f'{entry["id"]}/{min(pair)+1}/{max(pair)+1}'
                address = '#compare/' + base64.b64encode(expected.encode()).decode().rstrip('=')
                expect(button).to_have_attribute('href', address + '/detail')
                button.click()
                expect(page.locator('#comparisonTitle')).to_be_focused()
                versions = sorted((entry['versions'][i] for i in pair), key=lambda v: v['views'][0])
                expect(page.locator('#comparisonImage')).to_have_attribute('src', catalog['images'][versions[0]['views'][1]])
                page.locator('#comparisonViews').get_by_role('button', name=entry['zoomLabels'][0], exact=True).click()
                sizes = []
                frames = []
                for index, version in enumerate(versions):
                    which = 'AB'[index]
                    page.get_by_role('button', name=f'Drawing {which}', exact=True).click()
                    expect(page.locator('#comparisonDetails')).to_be_hidden()
                    assert entry['name'] not in page.locator('body').inner_text()
                    assert version['label'] not in page.locator('body').inner_text()
                    image = page.get_by_role('img', name='Unnamed portrait '+which)
                    expect(image).to_have_attribute('src', catalog['images'][version['views'][0]])
                    sizes.append(image.evaluate('async im => {await im.decode();return [im.naturalWidth, im.naturalHeight]}'))
                    frames.append(image.bounding_box())
                assert sizes[0] == sizes[1] and frames[0] == frames[1]
                assert frames[0]['width'] >= 340 and not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                if entry['id'] == 'mini-redwoods-eye' and b == 5:
                    page.screenshot(path=screenshots/f'{width}-real-portrait.png')
                if entry['id'] == 'portrait-styles' and b == 1:
                    page.screenshot(path=screenshots/f'{width}-art-styles.png')
                for view, label in enumerate(entry['zoomLabels'][1:], 1):
                    controls = page.get_by_role('group', name='Choose a portrait detail')
                    controls.get_by_role('button', name=label, exact=True).click()
                    suffix = entry.get('viewIds', ['', 'detail'])[view]
                    assert page.url.endswith(address + '/' + suffix)
                    extents = []
                    for which, v in zip('BA', reversed(versions)):
                        page.get_by_role('button', name='Drawing '+which, exact=True).click()
                        img = page.get_by_role('img', name='Unnamed portrait '+which+', '+label, exact=True)
                        expect(img).to_have_attribute('src', catalog['images'][v['views'][view]])
                        extents.append(img.evaluate('async im=>{await im.decode();return [im.naturalWidth, im.naturalHeight]}'))
                    assert extents[0] == extents[1]
                    assert entry['name'] not in page.locator('body').inner_text()
                    expect(controls.get_by_role('button', name=label, exact=True)).to_have_attribute('aria-pressed', 'true')
                if entry['id'] == 'pierced-ear-on-the-mini':
                    page.screenshot(path=screenshots/f'{width}-ear-without-labels.png')
                page.get_by_role('button', name='Reveal name and styles').click()
                expect(page.locator('#comparisonName')).to_have_text(entry['name'])
                for which, version in zip('AB', versions):
                    expect(page.locator('#caption'+which)).to_have_text(f"{which} · {version['label']} · {version['medium']}")
                page.reload()
                expect(page.locator('#comparisonDetails')).to_be_hidden()
                expect(page.locator('#viewA')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('#comparisonImage')).to_have_attribute('src', catalog['images'][versions[0]['views'][-1]])
                page.get_by_role('link', name='Back to portraits').click()
                last_view = entry.get('viewIds', ['', 'detail'])[-1]
                expect(page.locator('#compareDrawings')).to_have_attribute('href', address + '/' + last_view)
                checked += 1
        page.goto(url+'?compare=1#mini-redwoods-woodcut/10')
        expect(page.locator('#compareDrawings')).to_be_hidden()
        page.goto(url+'#compare/unknown')
        expect(page.get_by_role('heading', name='This drawing is unavailable')).to_be_visible()
        expect(page.locator('#galleryPage')).to_be_hidden()
        with context.new_page() as playback:
            playback.clock.install()
            for entry in catalog['entries']:
                if 'sequence' in entry:
                    check_sequence_playback(playback, url, entry)
        assert not errors, errors
        print(f'{width}px: {checked} equal-size pairs checked')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('screenshots', type=Path)
    parser.add_argument('--served', action='store_true')
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p, p.chromium.launch(executable_path=chromium(p, None),
            args=['--host-resolver-rules=MAP preview.example.com 127.0.0.1']) as b:
        for width in (390, 1120):
            check(b, args.gallery.resolve(), args.screenshots, width, args.served)
