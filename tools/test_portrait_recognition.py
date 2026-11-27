"""Exercise a gallery recognition round on a phone without revealing the sitters early."""

import argparse
import base64
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from gallery_test_server import gallery_http
from wide_portrait import chromium


def direct_link(entry, index):
    version = f"{entry['id']}/{index + 1}"
    return "#recognize/" + base64.b64encode(version.encode()).decode().rstrip('=')


def check_drawing(page, url, catalog, entry, index, out, width, group):
    version = entry['versions'][index]
    address = url + direct_link(entry, index)
    page.goto(address)
    question = page.get_by_role('heading', name='Who do you recognize?')
    guess = page.get_by_role('textbox', name='Who do you recognize?')
    face = page.get_by_role('img', name='Unnamed sand portrait')
    expect(question).to_be_focused()
    expect(guess).to_have_value('')
    expect(page.get_by_role('button', name='Reveal', exact=True)).to_be_disabled()
    expect(face).to_have_attribute('src', catalog['images'][version['views'][0]])
    face.evaluate('im=>im.decode()')
    expect(page.locator('main:visible img:visible')).to_have_count(1)
    expect(page.locator('main:visible canvas:visible, main:visible a:visible')).to_have_count(0)
    # The whole visible page is the drawing, one neutral question and the two choices.
    assert ' '.join(page.locator('body').inner_text().split()) == 'Who do you recognize? Reveal Not sure'
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
    if group:
        page.screenshot(path=out/f'{width}-direct-pair.png')
        guess.fill('Aunt May and Ben')
        guess.press('Enter')
    else:
        page.get_by_role('button', name='Not sure', exact=True).click()
    expect(page.locator('#answers li')).to_have_count(1)
    expect(page.locator('#answers strong')).to_have_text(entry['name'])
    expected = 'You guessed “Aunt May and Ben”.' if group else 'You were unsure.'
    expect(page.locator('#answers li p').first).to_have_text(expected)
    expect(page.locator('#answers .medium')).to_have_text(' · '.join([entry['title'], version['label'], version['medium']]))
    assert page.url == address
    page.get_by_role('button', name='Copy results').click()
    expect(page.locator('#copyNotice')).to_have_text('Results copied.')
    assert page.evaluate('navigator.clipboard.readText()').endswith('First guess: ' + ('Aunt May and Ben' if group else 'Not sure'))
    page.get_by_role('button', name='Hand to the next person').click()
    expect(guess).to_have_value('')
    expect(page.locator('#answers li')).to_have_count(0)
    expect(face).to_have_attribute('src', catalog['images'][version['views'][0]])
    page.get_by_role('button', name='Not sure', exact=True).click()
    page.get_by_role('link', name='Back to portraits').click()
    assert page.url == url + '#' + entry['id'] + '/' + str(index + 1)
    begin = page.get_by_role('link', name='Guess who’s in this portrait')
    expect(begin).to_have_attribute('href', direct_link(entry, index))
    begin.click()
    expect(guess).to_have_value('')
    expect(question).to_be_focused()


def check_each_face(page, url, catalog, entry, index, out, width):
    version = entry['versions'][index]
    page.goto(url + f"#{entry['id']}/{index + 1}")
    page.get_by_role('link', name='Guess each face').click()
    address = direct_link(entry, index) + '/faces'
    assert page.url == url + address
    page.reload()
    expected = {catalog['images'][face['image']]: face['name'] for face in version['faceGuesses']}
    seen = []
    for i in range(len(expected)):
        progress = f'Face {i + 1} of {len(expected)}'
        expect(page.locator('#roundProgress')).to_have_text(progress)
        face = page.get_by_role('img', name=progress, exact=True)
        face.evaluate('im => im.decode()')
        seen.append(expected[face.get_attribute('src')])
        visible = page.locator('main:visible').inner_text()
        assert all(name not in visible for name in expected.values())
        expect(page.locator('#roundSummary')).to_be_hidden()
        if i == 0:
            page.screenshot(path=out/f'{width}-group-face.png')
            page.get_by_role('textbox', name='Who is it?').fill('First guess')
            page.get_by_role('button', name='Next face').click()
        else:
            page.get_by_role('button', name='Not sure').click()
    assert sorted(seen) == sorted(expected.values())
    assert page.locator('#answers strong').all_text_contents() == seen
    assert page.locator('#answers li p').first.inner_text() == 'You guessed “First guess”.'
    assert 'You were unsure.' in page.locator('#answers li').nth(1).inner_text()
    page.locator('#savedRounds summary').click()
    page.get_by_role('button', name='Save this round').click()
    expect(page.get_by_role('button', name='This round is saved')).to_be_disabled()
    page.get_by_role('button', name='Hand to the next person').click()
    expect(page.locator('#roundProgress')).to_have_text(f'Face 1 of {len(expected)}')
    expect(page.locator('#roundSummary')).to_be_hidden()


def check_group_test(page, url, catalog, entry, pair, out, width):
    page.goto(url + f"#{entry['id']}/{pair[0]+1}")
    versions = '/'.join(str(i + 1) for i in sorted(pair))
    target = f"{entry['id']}/{versions}".encode()
    fragment = '#group-test/' + base64.b64encode(target).decode().rstrip('=')
    link = page.locator('#groupTest')
    default_partner = entry['compare'][pair[0]] if 'compare' in entry else int(pair[0] == 0)
    if default_partner != pair[1]:
        # Multiple curated pairs may start with the same photographed drawing.
        page.locator('#pair').click()
        page.locator('#pairVersion').select_option(str(pair[1]))
    expect(link).to_be_visible()
    expect(link).to_have_attribute('href', fragment)
    # Open the shared round without carrying the gallery's chosen-partner query.
    address = url + fragment
    page.goto(address)
    faces = {catalog['images'][f['image']]: (i,f['name'])
             for i in pair for f in entry['versions'][i]['faceGuesses']}
    count = len(faces)//2
    seen, answers = [], {}
    for guest in (1, 2):
        order = []
        for number in range(count):
            progress = f'Guest {guest} · Face {number+1} of {count}'
            expect(page.locator('#roundProgress')).to_have_text(progress)
            img = page.get_by_role('img', name=progress, exact=True)
            drawing, person = faces[img.get_attribute('src')]
            order.append((drawing, person))
            visible = page.locator('body').inner_text()
            assert not any(name in visible for _,name in faces.values())
            assert '<first guess>' not in visible and entry['versions'][drawing]['label'] not in visible
            if not number:
                page.screenshot(path=out/f'{width}-two-guests-{guest}.png')
            if guest == 1 and not number:
                answer = '<first guess>'
            elif guest == 2 and not number:
                answer = None
            else:
                answer = f'Guess {guest}.{number+1}'
            answers[guest,person] = answer
            if answer is None:
                page.get_by_role('button', name='Not sure', exact=True).click()
            else:
                page.locator('#guess').fill(answer)
                page.locator('#guess').press('Enter')
            if not number:
                page.reload()  # Preserve committed answers and which drawing this guest saw.
        assert len({i for i,_ in order}) == 1 and len({name for _,name in order}) == count
        seen.append(order)
        if guest == 1:
            expect(page.locator('#passTitle')).to_be_focused()
            expect(page.locator('#roundSummary')).to_be_hidden()
            assert not any(name in page.locator('body').inner_text() for _,name in order)
            page.reload()
            expect(page.get_by_role('button', name='Start the other drawing')).to_be_visible()
            # The shared address reveals no first guest's answers to a fresh tab.
            with page.context.new_page() as next_phone:
                next_phone.goto(address)
                expect(next_phone.locator('#roundProgress')).to_have_text(f'Guest 1 · Face 1 of {count}')
            page.screenshot(path=out/f'{width}-pass-phone.png')
            page.get_by_role('button', name='Start the other drawing').click()
    assert seen[0][0][0] != seen[1][0][0]
    expected = [(guest, person) for _,person in seen[0] for guest in (1,2)]
    for _ in range(2):
        rows = page.locator('#answers li')
        expect(rows).to_have_count(2*count)
        for row,(guest,person) in zip(rows.all(),expected,strict=True):
            answer = answers[guest,person]
            expect(row.locator('strong')).to_have_text(person)
            expect(row.locator('p').first).to_have_text(
                f'Guest {guest} was unsure.' if answer is None else f'Guest {guest} guessed “{answer}”.')
            assert faces[row.locator('img').get_attribute('src')] == (seen[guest-1][0][0],person)
        page.reload()
    page.screenshot(path=out/f'{width}-both-guesses.png')
    page.locator('#savedRounds summary').click()
    page.locator('#saveRound').click()
    page.reload()
    page.locator('#savedRounds summary').click()
    expect(page.locator('#saveRound')).to_be_disabled()
    with page.expect_download() as download:
        page.locator('#downloadRounds').click()
    text = download.value.path().read_text()
    for (guest,person),answer in answers.items():
        version = entry['versions'][seen[guest-1][0][0]]
        assert f'Guest {guest} · {person} · {entry["title"]} · {version["label"]} ({version["medium"]}). First guess: {answer or "Not sure"}' in text
    page.get_by_role('button', name='Try with two more guests').click()
    expect(page.locator('#roundProgress')).to_have_text(f'Guest 1 · Face 1 of {count}')
    expect(page.locator('#answers li')).to_have_count(0)


def check_real_sand(page, catalog, out, width):
    picks = {}
    for entry in catalog['entries']:
        if 'realSandPick' in entry:
            version = entry['versions'][entry['realSandPick']]
            assert version['medium'] == 'Real Mini sand'
            picks[catalog['images'][version['views'][0]]] = entry['name']
    assert len(picks) == len(set(picks.values())) >= 2
    page.get_by_role('link', name='Try the photographed portraits').click()
    assert page.url.endswith('#real-sand')
    page.reload()
    for attempt in range(2):
        seen = []
        for index in range(len(picks)):
            expect(page.locator('#roundProgress')).to_have_text(f'Portrait {index+1} of {len(picks)}')
            face = page.locator('#unnamedFace')
            face.evaluate('im => im.decode()')
            seen.append(picks[face.get_attribute('src')])
            assert all(name not in page.locator('body').inner_text() for name in picks.values())
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            if not attempt and not index:
                page.screenshot(path=out / f'{width}-real-sand.png')
            page.get_by_role('button', name='Not sure', exact=True).click()
        assert set(seen) == set(picks.values())
        expect(page.locator('#answers strong')).to_have_text(seen)
        page.locator('#savedRounds summary').click()
        expect(page.locator('#saveRound')).to_be_enabled()
        page.locator('#saveRound').click()
        expect(page.locator('#saveRound')).to_be_disabled()
        expect(page.locator('#savedCount')).to_have_text('1 round saved here.' if not attempt else '2 rounds saved here.')
        if not attempt:
            page.get_by_role('button', name='Hand to the next person').click()
            expect(page.locator('#answers li')).to_have_count(0)
            page.reload()
            expect(page.locator('#savedRounds')).to_be_hidden()
    page.screenshot(path=out / f'{width}-saved-guesses.png')
    with page.expect_download() as downloading:
        page.locator('#downloadRounds').click()
    downloaded = downloading.value.path().read_text()
    assert downloaded.count('First guess: Not sure') == 2 * len(picks)
    for person in seen:
        assert downloaded.count(person + ' · ') == 2
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('#clearRounds').click()
    expect(page.locator('#savedCount')).to_have_text('2 rounds saved here.')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#clearRounds').click()
    expect(page.locator('#downloadRounds')).to_be_hidden()
    expect(page.locator('#savedCount')).to_have_text('0 rounds saved here.')
    page.get_by_role('link', name='Try all portrait styles').click()
    assert page.url.endswith('#recognize')


def check_family_test(page, url, catalog):
    best = {e['name']: (e, e['realSandPick']) for e in catalog['entries'] if 'realSandPick' in e}
    entry = next(e for e in catalog['entries'] if e['id'] == 'closer-turns-across-the-face')
    index = 2
    page.goto(url + f"#{entry['id']}/{index+1}")
    page.locator('#familyTest').click()
    address = page.url
    assert '#family-test/' in address and entry['name'] not in address
    page.reload()
    def image_key(e, i):
        return catalog['images'][e['versions'][i]['views'][0]]
    partner = entry['compare'][index]
    reference = (image_key(entry, partner) if entry['versions'][partner]['medium'] == 'Real Mini sand'
                 else image_key(*best[entry['name']]))
    alternatives = {reference, image_key(entry, index)}
    other = {image_key(e, i) for name, (e, i) in best.items() if name != entry['name']}
    seen_versions = set()
    for guest in (1, 2):
        photos = set()
        for n in range(len(best)):
            expect(page.locator('#roundProgress')).to_have_text(f'Guest {guest} · Portrait {n+1} of {len(best)}')
            visible = page.locator('body').inner_text()
            assert all(name not in visible for name in best) and 'My first impression' not in visible
            photos.add(page.locator('#unnamedFace').get_attribute('src'))
            if guest == 1 and n == 0:
                page.locator('#guess').fill('My first impression')
                page.locator('#guess').press('Enter')
                page.reload()
            else:
                page.locator('#unsure').click()
        assert other <= photos and len(photos & alternatives) == 1
        seen_versions |= photos & alternatives
        if guest == 1:
            expect(page.locator('#roundSummary')).to_be_hidden()
            expect(page.locator('#passTitle')).to_be_focused()
            page.reload()
            pass_text = page.locator('body').inner_text()
            assert 'My first impression' not in pass_text and not any(name in pass_text for name in best)
            with page.context.new_page() as fresh:
                fresh.goto(address)
                expect(fresh.locator('#roundProgress')).to_have_text(f'Guest 1 · Portrait 1 of {len(best)}')
            page.locator('#startSecond').click()
            page.reload()
    expect(page.locator('#answers li')).to_have_count(2*len(best))
    names = page.locator('#answers strong').all_text_contents()
    assert set(names) == set(best) and all(names.count(name) == 2 for name in best)
    expect(page.locator('#answers')).to_contain_text('Guest 1 guessed “My first impression”.')
    page.reload()
    expect(page.locator('#answers')).to_contain_text('Guest 1 guessed “My first impression”.')
    page.locator('#newRound').click()
    assert page.url == address
    expect(page.locator('#roundProgress')).to_have_text(f'Guest 1 · Portrait 1 of {len(best)}')
    assert seen_versions == alternatives
    chosen = f"{entry['id']}/{index+1}"
    other_person, other_index = next(value for name, value in best.items() if name != entry['name'])
    for invalid in [chosen, entry['id'] + '/1', f"{other_person['id']}/{other_index+1}"]:
        encoded = base64.b64encode(f'{chosen}|{invalid}'.encode()).decode().rstrip('=')
        page.goto(url + '#family-test/' + encoded)
        expect(page.locator('#missingDrawing')).to_be_visible()
    # Asking for a real-sand test from either simulated version is unavailable.
    page.goto(url + f"#{entry['id']}/1")
    expect(page.locator('#familyTest')).to_be_hidden()


def check(browser, gallery, out, served, width, url):
    with browser.new_context(viewport={'width': width, 'height': 844}, permissions=['clipboard-read', 'clipboard-write']) as ctx:
        page = ctx.new_page()
        requests, errors = [], []
        page.on('request', lambda req: requests.append(req) if req.url.startswith('http') else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = page.goto(url+'#recognize')
        assert response.status == 200
        if served:
            # Use this browser's tailnet resolver without retaining a 10+ MB inspector response.
            digest = page.evaluate("""async () => {
                const response = await fetch(location.pathname);
                const hash = await crypto.subtle.digest('SHA-256', await response.arrayBuffer());
                return Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2, '0')).join('');
            }""")
            assert digest == hashlib.sha256(gallery.read_bytes()).hexdigest()
        catalog = json.loads(page.locator('#catalog').text_content())
        eligible = {}
        for e in catalog['entries']:
            for idx in e.get('recognitionVersions', []):
                version = e['versions'][idx]
                eligible[catalog['images'][version['views'][0]]] = (e['name'], e['title'], version['label'], version['medium'])
        count = len({item[0] for item in eligible.values()})
        assert count >= 2
        page.get_by_label('Your guess').fill('  ')
        expect(page.get_by_role('button', name='Next portrait')).to_be_disabled()
        seen, guesses = [], []
        for i in range(count):
            expect(page.locator('#roundProgress')).to_have_text(f'Portrait {i+1} of {count}')
            expect(page.locator('#galleryPage')).to_be_hidden()
            expect(page.locator('#roundSummary')).to_be_hidden()
            assert not page.locator('main:visible a[href*="prepared-portrait"]').count()
            face = page.locator('#unnamedFace')
            face.evaluate('im=>im.decode()')
            expect(face).to_have_attribute('alt', f'Portrait {i+1} of {count}')
            item = eligible[face.get_attribute('src')]
            seen.append(item)
            visible = page.locator('main:visible').inner_text()
            assert all(name not in visible and title not in visible for name, title, _, _ in eligible.values())
            assert item[2] not in visible and item[3] not in visible
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            if not i:
                page.screenshot(path=out/f'{width}-unknown.png')
            if i % 2:
                page.get_by_role('button', name='Not sure', exact=True).click()
                guesses.append(None)
            else:
                guess = '<an unlisted name>' if i == 0 else item[0]
                page.get_by_label('Your guess').fill(guess)
                page.get_by_label('Your guess').press('Enter')
                guesses.append(guess)
        assert len({item[0] for item in seen}) == count
        expect(page.locator('#roundQuestions')).to_be_hidden()
        expect(page.locator('#answers li')).to_have_count(count)
        for row, (name, title, style, medium), guess in zip(page.locator('#answers li').all(), seen, guesses):
            expect(row.locator('strong')).to_have_text(name)
            expect(row.locator('p').first).to_have_text(f'You guessed “{guess}”.' if guess else 'You were unsure.')
            expect(row.locator('.medium')).to_have_text(f'{title} · {style} · {medium}')
        page.screenshot(path=out/f'{width}-results.png')
        page.get_by_role('button', name='Copy results').click()
        expect(page.locator('#copyNotice')).to_have_text('Results copied.')
        plain = page.evaluate('navigator.clipboard.readText()')
        assert len(plain.splitlines()) == count and 'First guess: <an unlisted name>' in plain
        assert {req.url for req in requests} == {url}
        assert sum('range' not in req.headers for req in requests) == (2 if served else 1)
        page.get_by_role('button', name='Try another round').click()
        expect(page.locator('#answers li')).to_have_count(0)
        expect(page.locator('#guess')).to_have_value('')
        page.get_by_role('link', name='Back to portraits').click()
        expect(page.locator('.archive a')).to_have_count(len(catalog['entries']))
        page.locator('.archive a').first.click()
        previous = page.url
        page.get_by_role('link', name='Name the faces').click()
        page.go_back()
        assert page.url == previous
        expect(page.locator('#galleryPage')).to_be_visible()
        expect(page.locator('#name')).to_be_hidden()
        study = next(entry for entry in catalog['entries'] if len(entry['versions']) >= 2)
        alternative = (study['default'] + 1) % len(study['versions'])
        page.goto(url + '#' + study['id'])
        option = page.locator('.versions button').nth(alternative)
        option.click()
        deep_link = url + '#' + study['id'] + '/' + str(alternative + 1)
        assert page.url == deep_link
        page.reload()
        expect(option).to_have_attribute('aria-pressed', 'true')
        page.locator('#zoom').click()
        page.locator('#pair').click()
        address = page.url
        assert address == deep_link.replace('#', '?compare=1#') + '/detail'
        page.reload()
        expect(page.locator('#zoom')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#pair')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#mainImage')).to_have_attribute('src', catalog['images'][study['versions'][alternative]['views'][1]])
        page.locator('#pair').click()
        for _ in study['zoomLabels'][1:]:
            page.locator('#zoom').click()
        assert page.url == deep_link
        page.get_by_role('link', name='Name the faces').click()
        page.get_by_role('link', name='Back to portraits').click()
        assert page.url == deep_link
        expect(option).to_have_attribute('aria-pressed', 'true')
        page.goto(url + '#' + study['id'] + '/999999')
        expect(page.locator('.versions button').nth(study['default'])).to_have_attribute('aria-pressed', 'true')
        # The finished, photographed pair is allowed for a single blind guess;
        # its blank bed and group sitters are excluded from the random round.
        group = next(e for e in catalog['entries'] if e['id'] == 'mini-boardwalk-pair')
        real = next(i for i in group['directRecognitionVersions'] if group['versions'][i]['medium'] == 'Real Mini sand')
        assert group['versions'][real]['label'] != 'After the inward pass'
        single = next(e for e in catalog['entries'] if e.get('recognitionVersions'))
        for entry in catalog['entries']:
            for index, version in enumerate(entry['versions']):
                if version.get('inscribedName'):
                    page.goto(url + f"#{entry['id']}/{index + 1}")
                    expect(page.locator('#reveal')).to_be_hidden()
                    expect(page.locator('#guessDrawing')).to_be_hidden()
                    page.goto(url + direct_link(entry, index))
                    expect(page.get_by_role('heading', name='This drawing is unavailable')).to_be_visible()
        # Reload as a cold handoff without visiting a named gallery view first.
        page.goto(url + direct_link(group, real))
        page.reload()
        expect(page.get_by_role('heading', name='Who do you recognize?')).to_be_visible()
        check_drawing(page, url, catalog, group, real, out, width, group=True)
        check_drawing(page, url, catalog, single, single['recognitionVersions'][0], out, width, group=False)
        page.goto(url + '#' + group['id'] + '/1')
        expect(page.locator('#guessDrawing')).to_be_hidden()
        page.goto(url + direct_link(group, 0))
        expect(page.get_by_role('heading', name='This drawing is unavailable')).to_be_visible()
        expect(page.locator('main:visible img:visible')).to_have_count(0)
        expect(page.locator('#galleryPage')).to_be_hidden()
        page.goto(url + '#recognize')
        expect(page.get_by_role('heading', name='Who is it?')).to_be_visible()
        check_real_sand(page, catalog, out, width)
        check_family_test(page, url, catalog)
        for index, version in enumerate(group['versions']):
            if version.get('faceGuesses'):
                check_each_face(page, url, catalog, group, index, out, width)
        for entry in catalog['entries']:
            for pair in entry.get('blindPairs', []):
                versions = [entry['versions'][i] for i in pair]
                if all(v['medium']=='Real Mini sand' and v.get('faceGuesses') for v in versions):
                    check_group_test(page, url, catalog, entry, pair, out, width)
        # A real drawing paired with its simulated forecast is ineligible.
        mixed = next(pair for pair in group['blindPairs'] if any(group['versions'][i]['medium']!='Real Mini sand' for i in pair))
        link = f"{group['id']}/" + '/'.join(str(i+1) for i in sorted(mixed))
        page.goto(url + '#group-test/' + base64.b64encode(link.encode()).decode().rstrip('='))
        expect(page.locator('#missingDrawing')).to_be_visible()
        page.goto(url + direct_link(group, 0) + '/faces')
        expect(page.locator('#missingDrawing')).to_be_visible()
        assert {req.url for req in requests} == {url, url + '?compare=1'}
        assert not errors, errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gallery', type=Path)
    parser.add_argument('screenshots', type=Path)
    parser.add_argument('--served', action='store_true')
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None),
            args=['--host-resolver-rules=MAP preview.example.com 127.0.0.1']) as browser:
        with nullcontext() if args.served else gallery_http(args.gallery) as server:
            url = "https://preview.example.com/oasis-portrait-gallery.html" if args.served else server.url
            for width in (390, 1120):
                check(browser, args.gallery, args.screenshots, args.served, width, url)
    print('Phone and desktop passed the random round, direct pair and single guesses, handoff, reveal, return and blank-bed exclusion.')
