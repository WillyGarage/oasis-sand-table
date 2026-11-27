import io
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server import icons, render, svgstrokes
from server.app import ApiError, create_app, split_labels

TOKEN = 'secret'
SVG_OK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">'
          '<path d="M3 20h18"/><rect x="4" y="6" width="16" height="10" rx="2"/><circle cx="12" cy="11" r="3"/></svg>')
SQUARE = [[[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.2, 0.2]]]


# ---------- SVG flattening and validation ----------

def test_flatten_shapes_and_transform():
    st = svgstrokes.svg_to_strokes(SVG_OK)
    assert len(st) == 3
    circle = st[2]
    assert len(circle) > 12 and circle[0] == pytest.approx(circle[-1])
    t = '<svg viewBox="0 0 24 24"><g transform="translate(10 0)"><path d="M0 0L5 0"/></g></svg>'
    assert svgstrokes.svg_to_strokes(t)[0] == [(10.0, 0.0), (15.0, 0.0)]


def test_flatten_curves_and_arcs_are_smooth():
    st = svgstrokes.svg_to_strokes('<svg><path d="M2 12a10 10 0 0 1 20 0 M2 20 C 6 2, 18 2, 22 20 Q12 4 2 20"/></svg>')
    assert len(st) == 2
    arc = st[0]
    assert len(arc) > 20
    # every point of the half circle is 10 from its centre (12, 12)
    assert all(abs(((x - 12) ** 2 + (y - 12) ** 2) ** 0.5 - 10) < 0.05 for x, y in arc)


@pytest.mark.parametrize('bad', [
    '<svg><script>alert(1)</script></svg>',
    '<svg onload="x()"><path d="M0 0L5 5"/></svg>',
    '<svg><path d="M0 0L5 5" onclick="x()"/></svg>',
    '<svg><a href="http://evil"><path d="M0 0L5 5"/></a></svg>',
    '<svg><image href="http://evil/x.png"/></svg>',
    '<svg><use xlink:href="#a"/></svg>',
    '<svg><foreignObject><div/></foreignObject></svg>',
    '<svg><text>hi</text></svg>',
    '<svg><style>path{fill:url(http://x)}</style></svg>',
    '<svg><path d="M0 0L5 5" style="fill:red"/></svg>',
    '<svg><path d="M0 0L5 5" stroke="url(#x)"/></svg>',
    '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg><path d="M0 0L5 5"/></svg>',
    '<svg><!-- c --><path d="M0 0L5 5"/></svg>',
    '<svg><path d="M0 0L5 5"/>&#60;</svg>',
    '<svg xmlns="http://evil.example/ns"><path d="M0 0L5 5"/></svg>',
    '<div><path d="M0 0L5 5"/></div>',
    '<svg><path d="M0 0L5 5"><path d="M1 1L2 2"/></path></svg>',
    '<svg><circle cx="1" cy="1" r="1e999"/></svg>',
    '<svg><path d="' + 'M0 0L1 1' * 2000 + '"/></svg>',
    '<svg>' + '<path d="M0 0L5 5"/>' * 100 + '</svg>',
    '<svg><g>' * 10 + '<path d="M0 0L5 5"/>' + '</g>' * 10 + '</svg>',
    '<svg><path d="M0 0L5 5"/>',
    '', '   ', None, 5,
    '<svg>' + 'x' * 30000 + '</svg>',
    '<svg><path d="M"/></svg>',
])
def test_hostile_or_broken_svg_is_rejected(bad):
    with pytest.raises(svgstrokes.SvgError):
        svgstrokes.svg_to_strokes(bad)


def test_too_many_strokes_and_points_rejected():
    many = '<svg>' + ''.join('<line x1="0" y1="%d" x2="9" y2="%d"/>' % (i % 20, i % 20) for i in range(45)) + '</svg>'
    with pytest.raises(svgstrokes.SvgError):
        svgstrokes.svg_to_strokes(many)


def test_fit_centres_and_scales():
    f = svgstrokes.fit_strokes([[(0, 0), (24, 0), (24, 12)], [(0, 12), (6, 12)]])
    xs = [x for s in f for x, _ in s]
    ys = [y for s in f for _, y in s]
    assert all(0 <= v <= 1 for v in xs + ys)
    assert (min(xs) + max(xs)) / 2 == pytest.approx(0.5, abs=0.001)
    assert (min(ys) + max(ys)) / 2 == pytest.approx(0.5, abs=0.001)
    assert max(max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx(0.8, abs=0.01)
    assert max(((x - .5) ** 2 + (y - .5) ** 2) ** .5 for s in f for x, y in s) <= 0.451
    with pytest.raises(svgstrokes.SvgError):
        svgstrokes.fit_strokes([[(1, 1), (1.1, 1.1)]])


def test_whole_lucide_library_fits_the_api():
    lib = icons.lucide()
    assert len(lib) > 2000 and 'guitar' in lib and 'sailboat' in lib
    for name in ('guitar', 'music', 'sailboat', 'book-open', 'cpu'):
        st = svgstrokes.fit_strokes(icons.lucide_strokes(name))
        assert 0 < len(st) <= 40 and sum(len(s) for s in st) <= 4000


# ---------- the splitter ----------

@pytest.mark.parametrize('text,have,want', [
    ('computers, AI, music', (), ['computers', 'AI', 'music']),
    ('tennis;cooking', (), ['tennis', 'cooking']),
    ('a\nb\r\nc', (), ['a', 'b', 'c']),
    ('rock and roll', (), ['rock and roll']),
    ('star wars', (), ['star wars']),
    (' ,, AI ,  ai , Ai,', (), ['AI']),
    ('Music, jazz', ['music'], ['jazz']),
    ('  hot   pot ', (), ['hot pot']),
])
def test_split_labels(text, have, want):
    assert split_labels(text, have) == want


def test_split_labels_limits():
    with pytest.raises(ApiError):
        split_labels('x' * 41 + ', y')
    with pytest.raises(ApiError):
        split_labels(','.join(str(i) for i in range(25)))
    with pytest.raises(ApiError):
        split_labels('a,' * 300)
    assert split_labels(' , ;\n') == []


# ---------- the API: several interests in one entry ----------

class Clock:
    def __init__(self):
        self.t = 1_800_000_000

    def __call__(self):
        return self.t


@pytest.fixture
def clk():
    return Clock()


@pytest.fixture
def client(tmp_path, clk):
    return TestClient(create_app(data_dir=tmp_path, token=TOKEN, clock=clk))


def person(client, name='Ann'):
    return client.post('/api/people', json={'name': name}).json()['id']


def test_post_several_interests(client):
    pid = person(client)
    r = client.post('/api/people/%d/interests' % pid, json={'label': 'computers, AI, music'})
    assert r.status_code == 201
    got = r.json()['interests']
    assert [i['label'] for i in got] == ['computers', 'AI', 'music']
    assert all(i['status'] == 'pending' for i in got)
    # same again: all three are duplicates now
    r = client.post('/api/people/%d/interests' % pid, json={'label': 'AI, MUSIC'})
    assert r.status_code == 201 and r.json() == {'interests': []}
    assert len(client.get('/api/state').json()['people'][0]['interests']) == 3


def test_single_interest_keeps_old_shape(client):
    pid = person(client)
    r = client.post('/api/people/%d/interests' % pid, json={'label': 'rock and roll'})
    assert r.status_code == 201 and r.json()['label'] == 'rock and roll' and 'interests' not in r.json()


def test_several_interests_errors(client):
    pid = person(client)
    for body in ({'label': ' , ; '}, {'label': 'a, ' + 'b' * 41}, {'label': ','.join(map(str, range(30)))}):
        assert client.post('/api/people/%d/interests' % pid, json=body).status_code == 400
    # strokes with a comma in the label: still one interest, no split
    r = client.post('/api/people/%d/interests' % pid, json={'label': 'a, b', 'strokes': SQUARE})
    assert r.status_code == 201 and r.json()['label'] == 'a, b' and r.json()['status'] == 'ready'


# ---------- relief_png ----------

def test_relief_png_size_and_speed():
    t = time.time()
    png = render.relief_png(SQUARE, 240)
    assert time.time() - t < 0.3
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    im = Image.open(io.BytesIO(png))
    assert im.size == (240, 240) and im.mode == 'RGBA'
    assert im.getpixel((0, 0))[3] == 0 and im.getpixel((120, 120))[3] == 255   # transparent outside the disc
    many = [[[0.1 + 0.8 * (i % 7) / 7, 0.1 + 0.8 * j / 60] for j in range(61)] for i in range(25)]
    t = time.time()
    big = Image.open(io.BytesIO(render.relief_png(many, 600)))
    assert time.time() - t < 1.0 and big.size == (600, 600)


def test_relief_png_options_and_look():
    sq = Image.open(io.BytesIO(render.relief_png(SQUARE, 100, disc=False))).convert('RGB')
    assert sq.size == (100, 100) and sq.getpixel((2, 2)) == (240, 235, 222)      # plain sand
    assert min(sq.getpixel((20, y))[0] for y in range(90)) < 150                    # a dark groove
    assert max(sq.getpixel((x, 50))[0] for x in range(100)) >= 250                  # a lit lip
    page = Image.open(io.BytesIO(render.relief_png(SQUARE, 100, bg='#f5f2e9')))
    assert page.mode == 'RGB' and page.getpixel((0, 0)) == (0xf5, 0xf2, 0xe9)
    render.relief_png([[[0.5, 0.5]], [[0.1, 0.1], [0.1, 0.1]]], 64)                 # dots and empty strokes survive
    render.relief_png([], 64)


def test_later_stroke_replaces_earlier():
    over = [[[0.1, 0.5], [0.9, 0.5]], [[0.5, 0.1], [0.5, 0.9]]]
    im = Image.open(io.BytesIO(render.relief_png(over, 200, disc=False))).convert('L')
    # the vertical groove (later) is carved straight through the horizontal one: its floor runs unbroken, no lip of
    # the horizontal groove shows up in it
    col = [im.getpixel((100, y)) for y in range(40, 161)]
    assert max(col) - min(col) <= 3 and col[0] < 200
    # and the horizontal groove is broken where it meets the later vertical lips
    assert im.getpixel((100, 100)) == im.getpixel((100, 50))


def test_icon_png_endpoint(client, tmp_path):
    pid = person(client)
    pend = client.post('/api/people/%d/interests' % pid, json={'label': 'clarinet'}).json()
    r = client.get('/img/icon/%d.png' % pend['id'])
    assert r.status_code == 200 and r.headers['content-type'].startswith('image/svg+xml') and b'clarinet' in r.content
    done = client.post('/api/people/%d/interests' % pid, json={'label': 'box', 'strokes': SQUARE}).json()
    r = client.get('/img/icon/%d.png?v=%d' % (done['id'], done['v']))
    assert r.headers['content-type'] == 'image/png'
    assert Image.open(io.BytesIO(r.content)).size == (240, 240)
    assert Image.open(io.BytesIO(client.get('/img/icon/%d.png?s=500' % done['id']).content)).size == (480, 480)
    assert (tmp_path / 'icons' / ('%d_%d_240.png' % (done['id'], done['v']))).exists()
    assert client.get('/img/icon/%d.svg' % done['id']).headers['content-type'].startswith('image/svg+xml')
    assert client.get('/img/icon/9999.png').status_code == 404
    client.delete('/api/interests/%d' % done['id'])
    assert not list((tmp_path / 'icons').glob('%d_*' % done['id']))


# ---------- generate() with a fake SDK client ----------

class FakeClient:
    def __init__(self, reply=None, stop='end_turn', exc=None):
        self.reply, self.stop, self.exc, self.calls = reply, stop, exc, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type='thinking', thinking='..'),
                                                               SimpleNamespace(type='text', text=text)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=200,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


CUSTOM = {'subject': 'monitor', 'shapes': ['screen', 'stand'], 'lucide_icon': '', 'lucide_fit': 'none', 'svg': SVG_OK}


def test_generate_custom_and_request_shape():
    c = FakeClient(CUSTOM)
    res = icons.generate('  star\x00 wars <script> ' + 'x' * 80, client=c)
    assert res['source'] == 'custom' and res['strokes'] and res['usage']['usd'] > 0
    kw = c.calls[0]
    assert kw['model'] == 'claude-opus-5-5' and kw['max_tokens'] == 8000
    assert kw['output_config']['effort'] == 'medium' and kw['output_config']['format']['type'] == 'json_schema'
    assert 'temperature' not in kw and 'top_p' not in kw and 'thinking' not in kw and 'stream' not in kw
    assert kw['system'][0]['cache_control'] == {'type': 'ephemeral'}
    user = kw['messages'][0]['content']
    assert user.count('<topic>') == 1 and user.count('</topic>') == 1 and '\x00' not in user
    assert '<script>' not in user and len(user.split('<topic>')[1].split('</topic>')[0]) <= 40
    assert 'star wars' in user and 'x' * 80 not in user
    assert 'x' * 80 not in kw['system'][0]['text']


def test_generate_library_only_when_exact():
    lib = dict(CUSTOM, lucide_icon='guitar', lucide_fit='exact', svg='')
    res = icons.generate('guitar', client=FakeClient(lib))
    assert res['source'] == 'lucide' and res['lucide'] == 'guitar'
    loose = dict(CUSTOM, lucide_icon='church', lucide_fit='close')
    assert icons.generate('thai temples', client=FakeClient(loose))['source'] == 'custom'
    with pytest.raises(icons.GenerationError):      # invented name and no drawing
        icons.generate('x', client=FakeClient(dict(lib, lucide_icon='not-a-real-icon')))
    assert icons.generate('x', client=FakeClient(dict(lib, lucide_icon='not-a-real-icon', svg=SVG_OK)))['source'] == 'custom'


@pytest.mark.parametrize('client', [
    FakeClient(CUSTOM, stop='refusal'),
    FakeClient(CUSTOM, stop='max_tokens'),
    FakeClient('not json'),
    FakeClient('[1, 2]'),
    FakeClient(dict(CUSTOM, svg='<svg><script>x</script></svg>')),
    FakeClient(dict(CUSTOM, svg='')),
    FakeClient({}),
])
def test_generate_failures_are_errors_not_crashes(client):
    with pytest.raises(icons.GenerationError):
        icons.generate('x', client=client)


def test_generate_sdk_exception_chain():
    import anthropic
    import httpx2
    req = httpx2.Request('POST', 'http://x')

    def status(cls, code):
        return cls('boom', response=httpx2.Response(code, request=req), body=None)
    cases = [(status(anthropic.RateLimitError, 429), False), (status(anthropic.InternalServerError, 500), False),
             (status(anthropic.AuthenticationError, 401), True), (status(anthropic.NotFoundError, 404), True),
             (status(anthropic.BadRequestError, 400), False), (anthropic.APITimeoutError(request=req), False),
             (anthropic.APIConnectionError(request=req), False)]
    for exc, fatal in cases:
        with pytest.raises(icons.GenerationError) as e:
            icons.generate('x', client=FakeClient(exc=exc))
        assert e.value.fatal is fatal, exc


# ---------- the background service ----------

@pytest.fixture
def gen():
    calls = []

    def fake(label):
        calls.append(label)
        return {'strokes': SQUARE, 'source': 'custom', 'subject': label, 'usage': {'usd': 0.01}, 'seconds': 0.1}
    fake.calls = calls
    return fake


def service(tmp_path, clk, gen, **kw):
    """An app plus a service on its database; the service is driven by hand (tick), not by its thread."""
    app = create_app(data_dir=tmp_path, token=TOKEN, clock=clk, icon_gen=gen, start_icons=False)
    return TestClient(app), app.state.icons, kw


def direct(svc):
    return svc.tick(run=lambda job: (svc.process(job), svc.inflight.discard(job[0])))


def ready(client):
    return {i['label']: i['status'] for p in client.get('/api/state').json()['people'] for i in p['interests']}


def test_service_fills_pending_and_reuses_cache(tmp_path, clk, gen):
    client, svc, _ = service(tmp_path, clk, gen)
    pa, pb = person(client, 'Ann'), person(client, 'Bob')
    client.post('/api/people/%d/interests' % pa, json={'label': 'computers, AI, music'})
    client.post('/api/people/%d/interests' % pb, json={'label': 'ai, Tennis'})
    assert direct(svc) == 5
    assert set(ready(client).values()) == {'ready'}
    assert sorted(gen.calls) == ['AI', 'Tennis', 'computers', 'music']   # "ai" reused the cached "AI"
    assert svc.usage_counts() == (4, 4)
    iv = client.get('/api/state').json()['people'][0]['interests'][0]
    assert iv['v'] == 2 and iv['source'] == 'ai'


def test_service_shares_one_call_between_simultaneous_guests(tmp_path, clk):
    n, gate = [], threading.Event()

    def slow(label):
        n.append(label)
        gate.wait(2)
        return {'strokes': SQUARE, 'source': 'custom', 'usage': {}, 'seconds': 0}
    client, svc, _ = service(tmp_path, clk, slow)
    for name in ('Ann', 'Bob'):
        client.post('/api/people/%d/interests' % person(client, name), json={'label': 'Hiking'})
    jobs = [(1, 'Hiking', 1), (2, 'hiking', 1)]
    ts = [threading.Thread(target=svc.process, args=(j,)) for j in jobs]
    [t.start() for t in ts]
    time.sleep(0.2)
    gate.set()
    [t.join() for t in ts]
    assert len(n) == 1 and set(ready(client).values()) == {'ready'}


def test_pending_pickup_after_restart(tmp_path, clk, gen):
    client, svc, _ = service(tmp_path, clk, gen)
    client.post('/api/people/%d/interests' % person(client), json={'label': 'sailing'})
    assert ready(client) == {'sailing': 'pending'}
    # "restart": a new app and service on the same data directory
    client2, svc2, _ = service(tmp_path, clk, gen)
    assert direct(svc2) == 1
    assert ready(client2) == {'sailing': 'ready'}


def test_spending_cap_per_hour_and_day_survives_restart(tmp_path, clk, gen):
    app = create_app(data_dir=tmp_path, token=TOKEN, clock=clk, icon_gen=gen, start_icons=False)
    client = TestClient(app)
    svc = icons.IconService(tmp_path / 'sand.db', threading.RLock(), gen=gen, clock=clk, max_hour=2, max_day=3)
    client.post('/api/people/%d/interests' % person(client), json={'label': 'a, b, c, d'})
    direct(svc)
    assert list(ready(client).values()).count('ready') == 2
    assert len(gen.calls) == 2
    # restart: the count comes from the database, so it does not reset
    svc2 = icons.IconService(tmp_path / 'sand.db', threading.RLock(), gen=gen, clock=clk, max_hour=2, max_day=3)
    direct(svc2)
    assert len(gen.calls) == 2
    clk.t += 3601                                            # next hour: one more allowed (3 per day)
    direct(svc2)
    assert len(gen.calls) == 3
    clk.t += 3601
    direct(svc2)
    assert len(gen.calls) == 3                               # day cap hit
    assert list(ready(client).values()).count('pending') == 1
    clk.t += 86400
    direct(svc2)
    assert set(ready(client).values()) == {'ready'}


def test_cache_hits_do_not_count_against_the_cap(tmp_path, clk, gen):
    client, svc, _ = service(tmp_path, clk, gen)
    svc.max_hour = 1
    client.post('/api/people/%d/interests' % person(client), json={'label': 'a'})
    client.post('/api/people/%d/interests' % person(client, 'Bob'), json={'label': 'A, b'})
    direct(svc)
    assert ready(client)['a'] == 'ready'
    assert gen.calls == ['a']
    assert svc.usage_counts()[0] == 1


def test_three_failures_then_ten_minute_pause(tmp_path, clk):
    n = []

    def bad(label):
        n.append(1)
        raise icons.GenerationError('boom')
    client, svc, _ = service(tmp_path, clk, bad)
    client.post('/api/people/%d/interests' % person(client), json={'label': 'x'})
    for _ in range(5):
        direct(svc)
        clk.t += 6                                           # past the short gap between tries
    assert len(n) == 3 and ready(client) == {'x': 'pending'}
    clk.t += 600
    direct(svc)
    assert len(n) == 4


def test_fatal_error_pauses_everything(tmp_path, clk):
    def nokey(label):
        raise icons.GenerationError('API key rejected', fatal=True)
    client, svc, _ = service(tmp_path, clk, nokey)
    client.post('/api/people/%d/interests' % person(client), json={'label': 'a, b'})
    direct(svc)
    assert direct(svc) == 0                                  # paused for 5 minutes


def test_stale_version_is_not_overwritten(tmp_path, clk, gen):
    client, svc, _ = service(tmp_path, clk, gen)
    pid = person(client)
    iid = client.post('/api/people/%d/interests' % pid, json={'label': 'old'}).json()['id']
    job = (iid, 'old', 1)
    client.patch('/api/interests/%d' % iid, json={'label': 'new'})      # v is now 2
    svc.process(job)
    assert ready(client) == {'new': 'pending'}


def test_no_key_means_no_service(tmp_path, clk, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    app = create_app(data_dir=tmp_path, token=TOKEN, clock=clk)
    assert app.state.icons is None
    c = TestClient(app)
    c.post('/api/people/%d/interests' % person(c), json={'label': 'a'})
    jobs = c.get('/api/worker/jobs', headers={'X-Worker-Token': TOKEN}).json()['interests']
    assert [j['label'] for j in jobs] == ['a']              # the worker API still serves pending interests


def test_service_thread_runs_with_the_app(tmp_path, clk, gen):
    app = create_app(data_dir=tmp_path, token=TOKEN, clock=clk, icon_gen=gen)
    with TestClient(app) as c:
        c.post('/api/people/%d/interests' % person(c), json={'label': 'a, b'})
        for _ in range(50):
            if set(ready(c).values()) == {'ready'}:
                break
            time.sleep(0.1)
        assert set(ready(c).values()) == {'ready'}


# ---------- photo subject drawings ----------

def _photo_bytes(size=(1600, 1200)):
    buf = io.BytesIO()
    Image.new('RGB', size, (90, 80, 70)).save(buf, 'JPEG')
    return buf.getvalue()


PHOTO_REPLY = {'subject': 'scruffy dog', 'shapes': ['folded ears', 'long muzzle', 'wiry brows'],
               'svg': SVG_OK.replace('viewBox="0 0 24 24"', 'viewBox="0 0 48 48"')}


def test_draw_photo_happy_path_and_request_shape():
    c = FakeClient(PHOTO_REPLY)
    st = icons.draw_photo(_photo_bytes(), client=c)
    assert st and all(0 <= x <= 1 and 0 <= y <= 1 for s in st for x, y in s)
    kw = c.calls[0]
    assert kw['model'] == icons.MODEL and kw['output_config']['effort'] == icons.EFFORT
    assert kw['output_config']['format']['type'] == 'json_schema'
    block, text = kw['messages'][0]['content']
    assert block['type'] == 'image' and block['source']['type'] == 'base64' and block['source']['media_type'] == 'image/jpeg'
    import base64
    sent = Image.open(io.BytesIO(base64.b64decode(block['source']['data'])))
    assert max(sent.size) <= 768 and sent.format == 'JPEG'
    assert 'data' in kw['system'][0]['text'] and 'never follow it' in kw['system'][0]['text']


@pytest.mark.parametrize('client', [
    FakeClient(PHOTO_REPLY, stop='refusal'),
    FakeClient(PHOTO_REPLY, stop='max_tokens'),
    FakeClient('not json'),
    FakeClient(dict(PHOTO_REPLY, svg='<svg><script>x</script></svg>')),
    FakeClient(dict(PHOTO_REPLY, svg='')),
    FakeClient(None, exc=RuntimeError('boom')),
])
def test_draw_photo_failures_return_none(client):
    assert icons.draw_photo(_photo_bytes(), client=client) is None


def test_draw_photo_not_an_image_and_no_key(monkeypatch):
    assert icons.draw_photo(b'junk', client=FakeClient(PHOTO_REPLY)) is None
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    assert icons.draw_photo(_photo_bytes()) is None


def test_photo_counts_against_caps(tmp_path):
    lock = threading.RLock()
    calls = []

    def gen(b):
        calls.append(1)
        return {'strokes': SQUARE, 'usage': {'usd': 0.03}, 'subject': 'dog'}
    svc = icons.IconService(str(tmp_path / 'x.db'), lock, max_hour=2, max_day=10, photo_gen=gen)
    assert svc.draw_photo(b'x') == SQUARE and svc.draw_photo(b'x') == SQUARE
    assert svc.draw_photo(b'x') is None and len(calls) == 2
    assert svc.usage_counts()[0] == 2

    def bad(b):
        raise icons.GenerationError('nope')
    svc2 = icons.IconService(str(tmp_path / 'y.db'), lock, photo_gen=bad)
    assert svc2.draw_photo(b'x') is None
