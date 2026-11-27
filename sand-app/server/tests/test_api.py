import json
import time
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server.app import create_app

TOKEN = 'secret'
W = {'X-Worker-Token': TOKEN}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(tmp_path, clock):
    app = create_app(data_dir=tmp_path, token=TOKEN, clock=clock)
    return TestClient(app)


def jpg(size=(300, 200), color=(120, 80, 60), fmt='JPEG'):
    buf = io.BytesIO()
    im = Image.new('RGB', size, color)
    for x in range(0, size[0], 7):
        for y in range(0, size[1], 5):
            im.putpixel((x, y), (x % 256, y % 256, 200))
    im.save(buf, fmt)
    return buf.getvalue()


def add(client, name, join=False):
    r = client.post('/api/people', json={'name': name})
    assert r.status_code == 201, r.text
    p = r.json()
    if join:
        p = client.patch('/api/people/%d' % p['id'], json={'joined': True}).json()
    return p


def person(client, pid):
    return next(p for p in client.get('/api/state').json()['people'] if p['id'] == pid)


def test_names_unique_case_insensitive(client):
    p = add(client, '  Alex ')
    assert p['name'] == 'Alex' and p['joined'] is False and p['faces'] == 0 and p['interests'] == []
    r = client.post('/api/people', json={'name': 'aLEX'})
    assert r.status_code == 409 and r.json() == {'error': 'taken', 'name': 'Alex'}
    assert client.post('/api/people', json={'name': '   '}).status_code == 400
    assert client.post('/api/people', json={'name': 'x' * 31}).status_code == 400
    assert client.post('/api/people', json={}).status_code == 400
    assert client.post('/api/people', json={'name': 'x' * 30}).status_code == 201


def test_bulk_add(client):
    add(client, 'Maria')
    r = client.post('/api/people/bulk', json={'names': ['Sam', 'maria', 'Lek', 'lek', '', 'Thomas']})
    assert r.json() == {'added': 3}
    names = [p['name'] for p in client.get('/api/state').json()['people']]
    assert names == ['Lek', 'Maria', 'Sam', 'Thomas']
    assert client.post('/api/people/bulk', json={'names': 'x'}).status_code == 400


def test_no_store_on_api(client):
    assert client.get('/api/state').headers['cache-control'] == 'no-store'


def auto(client):
    """Switch the old time-driven turns on (for tests written against them)."""
    assert client.post('/api/host/settings', json={'auto_advance': True}).status_code == 200


def test_state_shape_empty(client):
    s = client.get('/api/state').json()
    assert s['clock'] == 'idle' and s['paused'] is False and s['ring'] == 'interests'
    assert s['table']['current'] is None and s['table']['upcoming'] == []
    assert len(s['table']['zones']) == 11


def test_join_color_and_rotation(client, clock):
    auto(client)
    a = add(client, 'Alex', join=True)
    assert a['joined'] and a['zone'] == 'centre'
    s = client.get('/api/state').json()
    cur = s['table']['current']
    assert cur['person_id'] == a['id'] and cur['zone'] == 'centre' and cur['percent'] == 0
    assert cur['steps'] == ['Clearing the spot', "Writing Alex's name"]
    assert cur['ends_at'] - cur['started_at'] == 270
    r = client.patch('/api/people/%d' % a['id'], json={'color': 3})
    assert r.json()['color'] == 3
    assert client.patch('/api/people/%d' % a['id'], json={'color': 8}).status_code == 400
    assert client.patch('/api/people/%d' % a['id'], json={'color': None}).json()['color'] is None
    assert client.patch('/api/people/999', json={'color': 1}).status_code == 404
    b = add(client, 'Bill', join=True)
    c = add(client, 'Cara', join=True)
    clock.t += 270 + 1
    s = client.get('/api/state').json()
    # fill: the second person goes into the first empty slice, the centre stays up
    assert s['table']['current']['person_id'] == b['id'] and s['table']['current']['zone'] == 'inner-1'
    assert s['table']['current']['started_at'] == 1_800_000_000 + 270
    pa = person(client, a['id'])
    assert pa['zone'] == 'centre' and pa['zones'] == ['centre'] and pa['next_at'] is not None
    assert person(client, c['id'])['next_at'] is not None
    pb = person(client, b['id'])
    assert pb['zone'] == 'inner-1' and pb['zones'] == ['inner-1'] and pb['next_at'] is not None  # on the table, still projected
    assert s['table']['hold_until'] is None and s['table']['current']['done'] is False


def test_faces_upload_and_fetch(client):
    p = add(client, 'Alex')
    big = jpg((3000, 1500))
    r = client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', big, 'image/jpeg'),
                                                           'face2': ('b.png', jpg((50, 50), fmt='PNG'), 'image/png')})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['faces'] == 2 and j['face_v'] == 1
    img = client.get('/img/face/%d.jpg' % p['id'])
    assert img.status_code == 200 and img.headers['content-type'] == 'image/jpeg'
    assert 'max-age=86400' in img.headers['cache-control']
    im = Image.open(io.BytesIO(img.content))
    assert im.size == (400, 400)
    assert client.get('/img/face/%d.jpg?n=2' % p['id']).status_code == 200
    assert client.get('/img/face/%d.jpg?n=3' % p['id']).status_code == 404
    # stored crops are re-encoded and downscaled
    crop = client.get('/api/worker/face/%d/1' % p['id'], headers=W)
    assert max(Image.open(io.BytesIO(crop.content)).size) == 1024
    # replace with one face
    r = client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')})
    assert r.json()['faces'] == 1 and r.json()['face_v'] == 2
    assert client.get('/img/face/%d.jpg?n=2' % p['id']).status_code == 404
    r = client.delete('/api/people/%d/faces' % p['id'])
    assert r.json()['faces'] == 0 and r.json()['face_v'] == 3
    assert client.get('/img/face/%d.jpg' % p['id']).status_code == 404


def test_faces_reject_non_image_and_exif(client, tmp_path):
    p = add(client, 'Alex')
    r = client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', b'not an image', 'image/jpeg')})
    assert r.status_code == 400
    r = client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.txt', b'<svg/>', 'image/svg+xml')})
    assert r.status_code == 400
    assert person(client, p['id'])['faces'] == 0
    # EXIF orientation 6 (rotate 90) turns a 300x200 into 200x300
    im = Image.new('RGB', (300, 200), (200, 100, 50))
    ex = Image.Exif()
    ex[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, 'JPEG', exif=ex)
    assert client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', buf.getvalue(), 'image/jpeg')}).status_code == 200
    crop = client.get('/api/worker/face/%d/1' % p['id'], headers=W)
    assert Image.open(io.BytesIO(crop.content)).size == (200, 300)
    assert client.post('/api/people/999/faces', files={'face1': ('a.jpg', jpg(), 'image/jpeg')}).status_code == 404


def test_interest_lifecycle_with_worker(client):
    a = add(client, 'Alex', join=True)
    b = add(client, 'Bill', join=True)
    r = client.post('/api/people/%d/interests' % a['id'], json={'label': 'Star Wars'})
    assert r.status_code == 201
    i = r.json()
    assert i['status'] == 'pending' and i['source'] == 'ai' and i['v'] == 1 and i['shared_with'] == []
    r = client.post('/api/people/%d/interests' % b['id'], json={'label': 'star wars movies'})
    assert r.json()['shared_with'] == ['Alex']
    assert person(client, a['id'])['interests'][0]['shared_with'] == ['Bill']
    jobs = client.get('/api/worker/jobs', headers=W).json()
    assert {j['id'] for j in jobs['interests']} == {i['id'], r.json()['id']}
    pend = client.get('/img/icon/%d.svg' % i['id'])
    assert pend.status_code == 200 and pend.headers['content-type'].startswith('image/svg+xml')
    assert 'Star Wars' in pend.text and 'Georgia' in pend.text
    strokes = [[[0.1, 0.1], [0.5, 0.9], [0.9, 0.1]], [[0.5, 0.5]]]
    # stale v
    r = client.post('/api/worker/interests/%d' % i['id'], headers=W, json={'v': 99, 'strokes': strokes})
    assert r.status_code == 409
    # label edit while the worker was busy makes the old job stale
    r = client.patch('/api/interests/%d' % i['id'], json={'label': 'Yoda'})
    assert r.json()['v'] == 2 and r.json()['status'] == 'pending'
    r = client.post('/api/worker/interests/%d' % i['id'], headers=W, json={'v': 1, 'strokes': strokes})
    assert r.status_code == 409
    r = client.post('/api/worker/interests/%d' % i['id'], headers=W, json={'v': 2, 'strokes': {'strokes': strokes}})
    assert r.status_code == 200
    got = person(client, a['id'])['interests'][0]
    assert got['status'] == 'ready' and got['source'] == 'ai' and got['v'] == 3
    svg = client.get('/img/icon/%d.svg' % i['id']).text
    assert '#8f7a45' in svg and '#f7efd6' in svg and 'Yoda' not in svg
    assert {j['id'] for j in client.get('/api/worker/jobs', headers=W).json()['interests']} == {r_id for r_id in [
        person(client, b['id'])['interests'][0]['id']]}
    # a second post for the same v is stale now
    assert client.post('/api/worker/interests/%d' % i['id'], headers=W, json={'v': 2, 'strokes': strokes}).status_code == 409
    # user sketch replaces it
    r = client.patch('/api/interests/%d' % i['id'], json={'strokes': strokes})
    assert r.json()['status'] == 'ready' and r.json()['source'] == 'sketch' and r.json()['label'] == 'Yoda'
    # create with strokes straight away
    r = client.post('/api/people/%d/interests' % a['id'], json={'label': 'Me', 'strokes': strokes})
    assert r.status_code == 201 and r.json()['status'] == 'ready' and r.json()['source'] == 'sketch'
    assert client.delete('/api/interests/%d' % i['id']).status_code == 204
    assert client.delete('/api/interests/%d' % i['id']).status_code == 404
    assert client.get('/img/icon/%d.svg' % i['id']).status_code == 404
    assert client.post('/api/people/999/interests', json={'label': 'x'}).status_code == 404
    assert client.post('/api/people/%d/interests' % a['id'], json={'label': ''}).status_code == 400
    assert client.post('/api/people/%d/interests' % a['id'], json={'label': 'y' * 41}).status_code == 400


def test_icon_escapes_label(client):
    a = add(client, 'Alex')
    i = client.post('/api/people/%d/interests' % a['id'], json={'label': '<b>&"x'}).json()
    svg = client.get('/img/icon/%d.svg' % i['id']).text
    assert '<b>' not in svg and '&lt;b&gt;&amp;' in svg


def test_strokes_validation(client):
    a = add(client, 'Alex')
    url = '/api/people/%d/interests' % a['id']

    def post(strokes):
        return client.post(url, json={'label': 'x', 'strokes': strokes}).status_code

    assert post([[[0, 0], [1, 1]]]) == 201
    assert post({'strokes': [[[0, 0], [1, 1]]]}) == 201
    assert post([]) == 400
    assert post('nope') == 400
    assert post([[]]) == 400
    assert post([[[0.1]]]) == 400
    assert post([[[0.1, 'a']]]) == 400
    assert post([[[0.1, True]]]) == 400
    assert post([[[0.1, 0.2, 0.3]]]) == 400
    assert post([[[0, 0]]] * 41) == 400
    assert post([[[0, 0]]] * 40) == 201
    assert post([[[0.5, 0.5]] * 2001, [[0.5, 0.5]] * 2000]) == 400
    assert post([[[0.5, 0.5]] * 2000, [[0.5, 0.5]] * 2000]) == 201
    # clamped
    r = client.post(url, json={'label': 'c', 'strokes': [[[-5, 9], [0.5, 0.5]]]})
    assert r.status_code == 201
    from server.app import clean_strokes
    assert clean_strokes([[[-5, 9]]]) == [[[0.0, 1.0]]]


def test_worker_token_enforced(tmp_path, clock):
    c = TestClient(create_app(data_dir=tmp_path, token=TOKEN, clock=clock))
    calls = [('get', '/api/worker/jobs', None), ('get', '/api/worker/plan', None),
             ('get', '/api/worker/face/1/1', None),
             ('post', '/api/worker/interests/1', {'v': 1, 'strokes': [[[0, 0]]]}),
             ('post', '/api/worker/progress', {'turn': 1, 'percent': 1, 'done': False})]
    for method, url, body in calls:
        assert getattr(c, method)(url, **({'json': body} if body else {})).status_code == 401, url
        assert getattr(c, method)(url, headers={'X-Worker-Token': 'wrong'}, **({'json': body} if body else {})).status_code == 401
    assert c.get('/api/worker/jobs', headers=W).status_code == 200
    # no token configured: everything 401, even with a header
    c2 = TestClient(create_app(data_dir=tmp_path, token='', clock=clock))
    assert c2.get('/api/worker/jobs', headers=W).status_code == 401
    assert c2.get('/api/worker/jobs', headers={'X-Worker-Token': ''}).status_code == 401
    assert c2.get('/api/state').status_code == 200


def test_worker_face_preview(client):
    p = add(client, 'Alex')
    client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')})
    assert client.get('/api/worker/jobs', headers=W).json()['faces'] == [{'person_id': p['id'], 'face_v': 1, 'n': 1}]
    standin = client.get('/img/face/%d.jpg' % p['id']).content
    prev = jpg((100, 100), (10, 200, 10), 'PNG')
    r = client.post('/api/worker/faces/%d' % p['id'], headers=W, files={'preview': ('p.png', prev, 'image/png')},
                    data={'face_v': '9', 'path': '[[0,0]]'})
    assert r.status_code == 409
    r = client.post('/api/worker/faces/%d' % p['id'], headers=W, files={'preview': ('p.png', prev, 'image/png')},
                    data={'face_v': '1', 'path': '{"strokes": [[[0.1,0.1],[0.2,0.2]]]}'})
    assert r.status_code == 200
    assert client.get('/api/worker/jobs', headers=W).json()['faces'] == []
    real = client.get('/img/face/%d.jpg' % p['id']).content
    assert real != standin and Image.open(io.BytesIO(real)).size == (100, 100)
    # a new upload bumps face_v and the stand-in comes back
    client.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')})
    assert Image.open(io.BytesIO(client.get('/img/face/%d.jpg' % p['id']).content)).size == (400, 400)
    assert len(client.get('/api/worker/jobs', headers=W).json()['faces']) == 1


def test_host_controls(client, clock):
    ids = [add(client, n, join=True)['id'] for n in ('A', 'B', 'C', 'D')]
    s = client.post('/api/host/pause', json={'paused': True}).json()
    assert s['paused'] is True
    clock.t += 5000
    s = client.get('/api/state').json()
    assert s['table']['current']['turn'] == 1
    s = client.post('/api/host/pause', json={'paused': False}).json()
    assert s['paused'] is False and s['table']['current']['ends_at'] == clock.t + 270
    s = client.post('/api/host/skip').json()
    assert s['table']['current']['turn'] == 2 and s['table']['current']['zone'] == 'centre'
    s = client.post('/api/host/move', json={'person_id': ids[3], 'dir': -1}).json()
    assert client.post('/api/host/move', json={'person_id': ids[3], 'dir': 2}).status_code == 400
    assert client.post('/api/host/ring', json={'ring': 'lotus'}).json()['ring'] == 'lotus'
    assert client.post('/api/host/ring', json={'ring': 'nope'}).status_code == 400
    s = client.post('/api/host/settings', json={'centre_minutes': 10, 'slice_minutes': 2}).json()
    s = client.post('/api/host/skip').json()
    assert s['table']['current']['ends_at'] - s['table']['current']['started_at'] == 600
    assert client.post('/api/host/settings', json={'centre_minutes': 0}).status_code == 400
    assert client.post('/api/host/pause', json={'paused': 'x'}).status_code == 400


def test_delete_person_clears_zone(client):
    a = add(client, 'Alex', join=True)
    b = add(client, 'Bill', join=True)
    client.post('/api/people/%d/faces' % a['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')})
    assert client.delete('/api/people/%d' % a['id']).status_code == 204
    s = client.get('/api/state').json()
    assert [p['name'] for p in s['people']] == ['Bill']
    centre = next(z for z in s['table']['zones'] if z['zone'] == 'centre')
    assert centre['person_id'] == b['id']  # Bill took over immediately
    assert client.get('/img/face/%d.jpg' % a['id']).status_code == 404
    assert client.delete('/api/people/%d' % a['id']).status_code == 404


def test_worker_plan_and_progress(client, clock):
    a = add(client, 'Alex', join=True)
    b = add(client, 'Bill', join=True)
    strokes = [[[0.1, 0.1], [0.9, 0.9]]]
    client.post('/api/people/%d/interests' % a['id'], json={'label': 'kites', 'strokes': strokes})
    client.patch('/api/people/%d' % a['id'], json={'color': 4})
    plan = client.get('/api/worker/plan', headers=W).json()
    cur = plan['current']
    assert cur['name'] == 'Alex' and cur['color'] == 4 and cur['ring'] == 'interests' and cur['turn'] == 1
    assert plan['next']['name'] == 'Bill' and len(plan['zones']) == 11
    turn = plan['state']['table']['current']['turn']
    r = client.post('/api/worker/progress', headers=W, json={'turn': turn, 'percent': 55, 'done': False})
    s = r.json()
    assert s['clock'] == 'table' and s['table']['current']['percent'] == 55
    clock.t += 3000  # sim stands down while the table is reporting... until reports go stale
    clock.t = clock.t - 3000 + 60
    assert client.get('/api/state').json()['table']['current']['turn'] == 1
    r = client.post('/api/worker/progress', headers=W, json={'turn': turn, 'percent': 100, 'done': True})
    assert r.json()['table']['current']['turn'] == 2
    assert client.post('/api/worker/progress', headers=W, json={'turn': 'x', 'percent': 1}).status_code == 400


def test_centre_hold_in_state_and_plan(client, clock):
    auto(client)
    ids = [add(client, 'P%d' % i, join=True)['id'] for i in range(6)]
    # fill: centre, 5 slices, then the centre person's own slice; the next turn is the first steady centre turn
    for _ in range(7):
        clock.t += 270
    s = client.get('/api/state').json()
    assert s['table']['current']['zone'] == 'centre' and s['table']['hold_until'] is None
    started = s['table']['current']['started_at']
    # the driver reports the centre turn done: the hold starts, the plan shows no current turn
    turn = s['table']['current']['turn']
    clock.t += 100
    s = client.post('/api/worker/progress', headers=W, json={'turn': turn, 'percent': 100, 'done': True}).json()
    done_at = clock.t
    cur = s['table']['current']
    assert cur['turn'] == turn and cur['done'] is True and cur['percent'] == 100 and s['table']['hold_until'] == done_at + 60
    assert s['table']['upcoming'][0]['at'] == done_at + 60 and s['table']['upcoming'][0]['zone'] == 'centre'
    plan = client.get('/api/worker/plan', headers=W).json()
    assert plan['current'] is None and plan['next']['at'] == done_at + 60 and plan['next']['zone'] == 'centre'
    pc = next(p for p in s['people'] if p['id'] == cur['person_id'])
    assert pc['zone'] == 'centre' and pc['zones'][0] == 'centre' and pc['next_at'] is not None
    # any read after the hold starts the next turn (the table keeps the clock)
    clock.t += 59
    assert client.get('/api/state').json()['table']['current']['turn'] == turn
    clock.t += 2
    s = client.get('/api/state').json()
    assert s['table']['current']['turn'] == turn + 1 and s['table']['current']['done'] is False
    assert s['table']['hold_until'] is None
    assert client.get('/api/worker/plan', headers=W).json()['current']['turn'] == turn + 1


def test_frontend_placeholder_and_static(client):
    r = client.get('/')
    assert r.status_code in (200,)  # real index.html if the frontend exists, else the placeholder
    assert r.headers['cache-control'] == 'no-cache'
    assert client.get('/nope/missing.js').status_code == 404
    assert 'import hmac' not in client.get('/%2e%2e/server/app.py').text
    assert 'import hmac' not in client.get('/../server/app.py').text


# ---------- draw_face order: landmark portrait, then photo drawing, then the sketch ----------

PHOTO_STROKES = [[[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.2, 0.2]]]


def _photo_app(tmp_path, calls, result=PHOTO_STROKES, wait=60, delay=0):
    import time as _t

    def photo_gen(b):
        calls.append(len(b))
        _t.sleep(delay)
        if result is None:
            from server.icons import GenerationError
            raise GenerationError('fail')
        return {'strokes': result, 'usage': {'usd': 0.03}, 'subject': 'dog'}
    return TestClient(create_app(data_dir=tmp_path, token=TOKEN, photo_gen=photo_gen, photo_wait=wait,
                                 start_icons=False))


def _fake_face_art(monkeypatch, ok):
    from server import app as appmod
    if appmod.face_art is None:
        class _FA: pass
        monkeypatch.setattr(appmod, 'face_art', _FA(), raising=False)
    monkeypatch.setattr(appmod.face_art, 'face_strokes',
                        lambda crop: {'ok': ok, 'strokes': [[[0.1, 0.1], [0.9, 0.9]], [[0.1, 0.9], [0.9, 0.1]]] if ok else None},
                        raising=False)


def test_draw_face_face_found_makes_no_photo_call(tmp_path, monkeypatch):
    calls = []
    c = _photo_app(tmp_path, calls)
    _fake_face_art(monkeypatch, True)
    p = add(c, 'Alex')
    assert c.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')}).status_code == 200
    assert calls == []
    assert c.get('/img/face/%d.jpg' % p['id']).status_code == 200
    assert len((tmp_path / 'faces').glob('*_strokes.json').__next__().read_text()) > 10


def test_draw_face_no_face_uses_photo_drawing(tmp_path, monkeypatch):
    calls = []
    c = _photo_app(tmp_path, calls)
    _fake_face_art(monkeypatch, False)
    p = add(c, 'Alex', join=True)
    assert c.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')}).status_code == 200
    assert len(calls) == 1
    f = tmp_path / 'faces' / ('%d_1_strokes.json' % p['id'])
    assert json.loads(f.read_text()) == PHOTO_STROKES
    assert c.get('/img/face/%d.jpg' % p['id']).headers['content-type'] == 'image/jpeg'
    plan = c.get('/api/worker/plan', headers=W).text
    assert '"face_strokes"' in plan or 'face_strokes' in plan


def test_draw_face_photo_failure_falls_back_to_sketch(tmp_path, monkeypatch):
    calls = []
    c = _photo_app(tmp_path, calls, result=None)
    _fake_face_art(monkeypatch, False)
    p = add(c, 'Alex')
    assert c.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')}).status_code == 200
    assert len(calls) == 1
    assert not (tmp_path / 'faces' / ('%d_1_strokes.json' % p['id'])).exists()
    assert c.get('/img/face/%d.jpg' % p['id']).status_code == 200


def test_draw_face_photo_timeout_falls_back(tmp_path, monkeypatch):
    calls = []
    c = _photo_app(tmp_path, calls, wait=0.2, delay=1.0)
    _fake_face_art(monkeypatch, False)
    p = add(c, 'Alex')
    assert c.post('/api/people/%d/faces' % p['id'], files={'face1': ('a.jpg', jpg(), 'image/jpeg')}).status_code == 200
    assert not (tmp_path / 'faces' / ('%d_1_strokes.json' % p['id'])).exists()


# ---------- auto_advance off: the table is the only clock ----------

def finish_turn(client):
    cur = client.get('/api/state').json()['table']['current']
    return client.post('/api/worker/progress', headers=W, json={'turn': cur['turn'], 'percent': 100, 'done': True}).json()


def test_idle_state_nothing_advances_with_time(client, clock):
    for n in ('Alex', 'Bill', 'Cara'):
        add(client, n, join=True)
    s = client.get('/api/state').json()
    assert s['clock'] == 'idle' and s['table']['current']['turn'] == 1
    clock.t += 100000
    s = client.get('/api/state').json()
    assert s['clock'] == 'idle' and s['table']['current']['turn'] == 1 and s['table']['current']['percent'] == 0
    assert s['table']['upcoming'] and all(u['at'] is None for u in s['table']['upcoming'])
    assert all(p['next_at'] is None for p in s['people'])
    cur_pid = s['table']['current']['person_id']
    ins = {p['id']: p['next_in'] for p in s['people']}
    order = [u['person_id'] for u in s['table']['upcoming']]
    first = {}
    for k, pid in enumerate(order):
        first.setdefault(pid, k)
    assert ins == first and min(ins.values()) == 0
    assert client.get('/api/state').json()['table']['current']['turn'] == 1


def test_idle_percent_is_the_drivers_last_value_and_clock_flips(client, clock):
    add(client, 'Alex', join=True)
    add(client, 'Bill', join=True)
    turn = client.get('/api/state').json()['table']['current']['turn']
    s = client.post('/api/worker/progress', headers=W, json={'turn': turn, 'percent': 35, 'done': False}).json()
    assert s['clock'] == 'table' and s['table']['current']['percent'] == 35
    assert s['table']['upcoming'][0]['at'] is not None
    assert next(p for p in s['people'] if p['name'] == 'Bill')['next_at'] is not None
    clock.t += 121
    s = client.get('/api/state').json()
    assert s['clock'] == 'idle' and s['table']['current']['percent'] == 35 and s['table']['current']['turn'] == turn
    assert s['table']['upcoming'][0]['at'] is None


def test_idle_driver_done_skip_and_delete_still_work(client, clock):
    a = add(client, 'Alex', join=True)
    b = add(client, 'Bill', join=True)
    c = add(client, 'Cara', join=True)
    s = finish_turn(client)
    assert s['table']['current']['turn'] == 2
    clock.t += 5000
    s = client.post('/api/host/skip').json()
    assert s['table']['current']['turn'] == 3
    cur_pid = s['table']['current']['person_id']
    assert client.delete('/api/people/%d' % cur_pid).status_code == 204
    s = client.get('/api/state').json()
    assert s['table']['current']['turn'] == 4 and s['table']['current']['person_id'] != cur_pid


def test_plan_next_keeps_hold_time_when_idle(client, clock):
    for i in range(6):
        add(client, 'P%d' % i, join=True)
    for _ in range(40):
        s = finish_turn(client)
        if s['table']['current']['done']:
            break
    assert s['table']['current']['done'] is True
    hold = s['table']['hold_until']
    clock.t += 30
    plan = client.get('/api/worker/plan', headers=W).json()
    assert plan['current'] is None and plan['next']['at'] == hold
    clock.t += 5000                                   # no driver: the hold still ends by itself, the next turn starts
    s = client.get('/api/state').json()
    assert s['table']['current']['done'] is False and s['table']['hold_until'] is None and s['clock'] == 'idle'


def test_settings_auto_advance(client, clock):
    add(client, 'Alex', join=True)
    add(client, 'Bill', join=True)
    assert client.post('/api/host/settings', json={'auto_advance': 'yes'}).status_code == 400
    s = client.post('/api/host/settings', json={'auto_advance': True}).json()
    assert s['clock'] == 'simulated'
    clock.t += 300
    assert client.get('/api/state').json()['table']['upcoming'][0]['at'] is not None
    assert client.post('/api/host/settings', json={'auto_advance': False}).json()['clock'] == 'idle'


def test_rename_keeps_a_hand_drawn_interest(client):
    pid = client.post('/api/people', json={'name': 'Renamer'}).json()['id']
    it = client.post(f'/api/people/{pid}/interests', json={'label': 'my dog', 'strokes': [[[0.2, 0.2], [0.8, 0.8]]]}).json()
    r = client.patch(f"/api/interests/{it['id']}", json={'label': 'Maverick'}).json()
    assert (r['label'], r['status'], r['source']) == ('Maverick', 'ready', 'sketch') and r['v'] > it['v']


def test_face_upload_answers_at_once_and_the_drawing_follows(tmp_path):
    """Background mode: the upload returns with the face marked as being made; state shows it; when the drawing is
    done the version number goes up and the picture is served. A newer upload wins over an older job."""
    import threading
    from server import app as A
    gate, calls = threading.Event(), []

    class Clk:
        t = 1_000_000
        def __call__(self): return self.t

    app = create_app(data_dir=tmp_path, token=TOKEN, clock=Clk(), face_sync=False)
    c = TestClient(app)
    pid = c.post('/api/people', json={'name': 'Zoe'}).json()['id']
    real = A.render.face_standin
    def slow(crop):
        calls.append(1); gate.wait(20); return real(crop)
    A.render.face_standin = slow
    old_face_art = A.face_art
    A.face_art = None                      # no face model in this test: straight to the stand-in, which we hold back
    try:
        p = c.post('/api/people/%d/faces' % pid, files={'face1': ('f.jpg', jpg(), 'image/jpeg')}).json()
        assert p['faces'] == 1 and p['face_pending'] is True and p['face_v'] == 0
        assert c.get('/img/face/%d.jpg' % pid).status_code == 404        # nothing to show yet
        me = next(x for x in c.get('/api/state').json()['people'] if x['id'] == pid)
        assert me['face_pending'] is True
        assert c.patch('/api/people/%d' % pid, json={'joined': True}).status_code == 200   # joining does not wait
        gate.set()
        for _ in range(100):
            me = next(x for x in c.get('/api/state').json()['people'] if x['id'] == pid)
            if not me['face_pending']:
                break
            time.sleep(0.05)
        assert me['face_pending'] is False and me['face_v'] == 1 and me['faces'] == 1
        assert c.get('/img/face/%d.jpg?v=1' % pid).status_code == 200
    finally:
        gate.set(); A.render.face_standin = real; A.face_art = old_face_art
