"""Centre pictures, drawn strokes, the table picture and keepsakes."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server.app import create_app

TOKEN = 'secret'
W = {'X-Worker-Token': TOKEN}
ST = [[[0.1, 0.1], [0.9, 0.9]], [[0.1, 0.9], [0.9, 0.1]]]


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
    return TestClient(create_app(data_dir=tmp_path, token=TOKEN, clock=clock))


def add(client, name, join=True, strokes=True):
    p = client.post('/api/people', json={'name': name}).json()
    if strokes:
        client.post('/api/people/%d/interests' % p['id'], json={'label': 'kites', 'strokes': ST})
    if join:
        client.patch('/api/people/%d' % p['id'], json={'joined': True})
    return p


def state(client):
    return client.get('/api/state').json()


def items(*keys):
    return {'items': [{'key': k, 'label': k.title(), 'strokes': ST} for k in keys]}


def set_art(client, *keys):
    r = client.post('/api/worker/centre-art', headers=W, json=items(*keys))
    assert r.status_code == 200, r.text
    return r.json()


def finish(client):
    cur = state(client)['table']['current']
    return client.post('/api/worker/progress', headers=W, json={'turn': cur['turn'], 'percent': 100, 'done': True}).json()


def run_to_centre(client, clock, after_turn=0, limit=30):
    """Finish turns (the table as the clock) until a centre draw turn newer than `after_turn` is current."""
    for _ in range(limit):
        cur = state(client)['table']['current']
        if cur and cur['kind'] == 'draw' and cur['zone'] == 'centre' and cur['turn'] > after_turn and not cur['done']:
            return cur
        if cur and cur['done']:
            clock.t += 61
            continue
        finish(client)
    raise AssertionError('no centre turn')


# ---------- centre art ----------

def test_centre_art_requires_worker_token_and_validates(client):
    assert client.post('/api/worker/centre-art', json=items('a')).status_code == 401
    for bad in ({'items': 'x'}, {'items': [{'key': 'A', 'label': 'x', 'strokes': ST}]},
                {'items': [{'key': 'a_b', 'label': 'x', 'strokes': ST}]},
                {'items': [{'key': 'k' * 41, 'label': 'x', 'strokes': ST}]},
                {'items': [{'key': 'a', 'label': '', 'strokes': ST}]},
                {'items': [{'key': 'a', 'label': 'x', 'strokes': []}]},
                {'items': [{'key': 'a', 'label': 'x'}]},
                items('a', 'a')):
        assert client.post('/api/worker/centre-art', headers=W, json=bad).status_code == 400, bad
    assert state(client)['centre_art'] == []


def test_centre_art_upsert_order_delete_and_enabled_memory(client):
    set_art(client, 'pie', 'turkey', 'leaf')
    s = state(client)
    assert [(a['key'], a['label'], a['enabled'], a['v']) for a in s['centre_art']] == [
        ('pie', 'Pie', True, 1), ('turkey', 'Turkey', True, 1), ('leaf', 'Leaf', True, 1)]
    s = client.post('/api/host/centre-art', json={'key': 'turkey', 'enabled': False}).json()
    assert [a['enabled'] for a in s['centre_art']] == [True, False, True]
    # re-post in a new order, one label changed: order follows the post, v bumps only for the changed one, off stays off
    body = {'items': [{'key': 'leaf', 'label': 'Leaf', 'strokes': ST}, {'key': 'turkey', 'label': 'Big turkey', 'strokes': ST},
                      {'key': 'pie', 'label': 'Pie', 'strokes': ST}]}
    client.post('/api/worker/centre-art', headers=W, json=body)
    got = [(a['key'], a['enabled'], a['v']) for a in state(client)['centre_art']]
    assert got == [('leaf', True, 1), ('turkey', False, 2), ('pie', True, 1)]
    # absent keys are deleted, and the host's choice is remembered if the key comes back
    set_art(client, 'pie')
    assert [a['key'] for a in state(client)['centre_art']] == ['pie']
    assert client.get('/img/centre-art/turkey.png').status_code == 404
    set_art(client, 'pie', 'turkey')
    assert {a['key']: a['enabled'] for a in state(client)['centre_art']} == {'pie': True, 'turkey': False}
    set_art(client)
    assert state(client)['centre_art'] == []


def test_host_centre_art_toggle(client):
    set_art(client, 'pie')
    assert client.post('/api/host/centre-art', json={'key': 'nope', 'enabled': True}).status_code == 404
    assert client.post('/api/host/centre-art', json={'key': 'pie', 'enabled': 'yes'}).status_code == 400
    assert client.post('/api/host/centre-art', json={'key': 'pie'}).status_code == 400
    s = client.post('/api/host/centre-art', json={'key': 'pie', 'enabled': False}).json()
    assert s['centre_art'][0]['enabled'] is False
    s = client.post('/api/host/centre-art', json={'key': 'pie', 'enabled': True}).json()
    assert s['centre_art'][0]['enabled'] is True


def test_centre_art_preview_png(client):
    set_art(client, 'pie')
    v = state(client)['centre_art'][0]['v']
    r = client.get('/img/centre-art/pie.png?v=%d' % v)
    assert r.status_code == 200 and r.headers['content-type'] == 'image/png'
    assert Image.open(io.BytesIO(r.content)).size == (240, 240)
    assert client.get('/img/centre-art/pie.png?s=120').status_code == 200
    assert client.get('/img/centre-art/Bad_Key.png').status_code == 404


def test_centre_art_pick_is_stable_enabled_only_and_centre_draw_only(client, clock):
    for n in ('A', 'B', 'C', 'D', 'E', 'F'):
        add(client, n)
    first = state(client)['table']['current']
    assert first['zone'] == 'centre' and first['centre_art'] == []          # started before the catalogue existed
    set_art(client, 'pie', 'turkey', 'leaf', 'corn')
    client.post('/api/host/centre-art', json={'key': 'corn', 'enabled': False})
    assert state(client)['table']['current']['centre_art'] == []            # still none for that turn
    plan = client.get('/api/worker/plan', headers=W).json()
    assert plan['current']['centre_art'] == [] and plan['next']['centre_art'] == []   # next is a slice turn
    assert plan['next']['turn'] == plan['current']['turn'] + 1
    finish(client)
    cur = state(client)['table']['current']
    assert cur['zone'] != 'centre' and cur['centre_art'] == []              # slice turns carry none
    assert client.get('/api/worker/plan', headers=W).json()['current']['centre_art'] == []
    cur = run_to_centre(client, clock, after_turn=first['turn'])
    keys = cur['centre_art']
    assert len(keys) == 2 and set(keys) <= {'pie', 'turkey', 'leaf'} and len(set(keys)) == 2
    for _ in range(5):                                                      # polling never changes it
        assert state(client)['table']['current']['centre_art'] == keys
    client.post('/api/host/centre-art', json={'key': keys[0], 'enabled': False})
    assert state(client)['table']['current']['centre_art'] == keys
    plan = client.get('/api/worker/plan', headers=W).json()
    assert [a['key'] for a in plan['current']['centre_art']] == keys
    assert all(a['strokes'] == ST and a['label'] for a in plan['current']['centre_art'])
    # the centre zone entry remembers the keys of its occupant, in state and in the plan
    centre = next(z for z in state(client)['table']['zones'] if z['zone'] == 'centre')
    assert centre['centre_art'] == keys
    assert next(z for z in plan['zones'] if z['zone'] == 'centre')['centre_art'] == keys
    # a slice turn after it leaves them on the zone, but the turn itself has none
    finish(client)
    clock.t += 61
    cur2 = state(client)['table']['current']
    centre = next(z for z in state(client)['table']['zones'] if z['zone'] == 'centre')
    assert centre['centre_art'] == keys or cur2['zone'] == 'centre'


def test_centre_art_pick_with_few_enabled(client, clock):
    for n in ('A', 'B'):
        add(client, n)
    finish(client)
    set_art(client, 'pie', 'turkey')
    client.post('/api/host/centre-art', json={'key': 'turkey', 'enabled': False})
    cur = run_to_centre(client, clock, after_turn=1)
    assert cur['centre_art'] == ['pie']
    client.post('/api/host/centre-art', json={'key': 'pie', 'enabled': False})
    cur = run_to_centre(client, clock, after_turn=cur['turn'])
    assert cur['centre_art'] == []


# ---------- drawn ----------

def pic(client, size=300):
    """The table picture once its render is done (the endpoint serves the previous one while a new one renders)."""
    client.get('/img/table.png?s=%d' % size)
    client.app.state.tables.flush()
    return client.get('/img/table.png?s=%d' % size).content


def post_drawn(client, turn, zone, strokes, **kw):
    return client.post('/api/worker/drawn', headers=W, json={'turn': turn, 'zone': zone, 'strokes': strokes}, **kw)


LINE = [[[-0.2, 0.0], [0.2, 0.0], [0.2, 0.1]]]


def test_drawn_validation(client):
    add(client, 'A')
    t = state(client)['table']['current']['turn']
    assert client.post('/api/worker/drawn', json={'turn': t, 'zone': 'centre', 'strokes': LINE}).status_code == 401
    assert post_drawn(client, t, 'centre', LINE).status_code == 200
    assert post_drawn(client, t, 'frame', LINE).status_code == 200
    for bad in ('x', None, [[]], [[[0, 0, 0]]], [[[1.06, 0]]], [[[0, -1.06]]], [['a', 'b']], [[[True, False]]],
                [[[0, 'x']]], [[[0, 0]]] * 2001):
        assert post_drawn(client, t, 'centre', bad).status_code == 400, str(bad)[:40]
    assert post_drawn(client, t, 'centre', [[[1.05, -1.05]]]).status_code == 200
    assert post_drawn(client, t, 'centre', []).status_code == 200
    assert post_drawn(client, t, 'nowhere', LINE).status_code == 400
    assert post_drawn(client, 'x', 'centre', LINE).status_code == 400
    assert post_drawn(client, True, 'centre', LINE).status_code == 400
    assert post_drawn(client, t, 'centre', [[[0.5, 0.5]] * 3] * 2000).status_code == 200        # 2000 strokes is the limit
    ok = [[[0.1, 0.1]] * 30] * 2000                                                              # 60000 points
    assert post_drawn(client, t, 'centre', ok).status_code == 200
    assert post_drawn(client, t, 'centre', ok + [[[0, 0]]]).status_code == 400                   # one over both limits


def test_drawn_stale_turns(client, clock):
    for n in ('A', 'B', 'C'):
        add(client, n)
    t1 = state(client)['table']['current']['turn']
    assert post_drawn(client, t1 + 1, 'centre', LINE).status_code == 409        # the future
    assert post_drawn(client, 0, 'centre', LINE).status_code == 409
    finish(client)                                                              # turn 2 (a slice) is current now
    cur = state(client)['table']['current']
    assert cur['turn'] == t1 + 1
    assert post_drawn(client, t1, 'centre', LINE).status_code == 200            # the turn that just finished
    assert post_drawn(client, cur['turn'], cur['zone'], LINE).status_code == 200   # the current turn
    assert post_drawn(client, t1, cur['zone'], LINE).status_code == 409         # that zone belongs to the new turn now
    finish(client)
    assert post_drawn(client, t1, 'centre', LINE).status_code == 409            # two turns back
    r = post_drawn(client, 1, 'frame', LINE)
    assert r.status_code == 409 and r.json()['error'] == 'stale'


def test_table_picture_follows_drawn_posts_and_reset(client, clock):
    add(client, 'A')
    add(client, 'B')
    tb = client.app.state.tables
    t = state(client)['table']['current']['turn']
    base = pic(client)                                            # centre is being drawn: plain sand
    assert base[:8] == b'\x89PNG\r\n\x1a\n'
    assert pic(client) == base                                     # same version: same picture
    finish(client)                                                 # A is on the table, B's turn started
    after = pic(client)
    assert after != base
    post_drawn(client, t, 'centre', [[[0.05 * i - 0.2, 0.05 * j] for i in range(9)] for j in range(5)])
    with_post = pic(client)
    assert with_post != after
    post_drawn(client, t, 'frame', [[[-0.9, 0.0], [0.9, 0.0]]])
    assert pic(client) != with_post
    client.post('/api/worker/reset', headers=W)
    tb.flush()
    s = state(client)
    assert s['table']['current']['turn'] > t
    # nothing from before the reset is accepted any more
    assert post_drawn(client, t, 'centre', LINE).status_code == 409
    assert tb is not None


def test_in_progress_zone_is_blank_and_post_only_for_its_occupant(client, clock):
    from server import render
    add(client, 'A')
    add(client, 'B')
    t = state(client)['table']['current']['turn']
    post_drawn(client, t, 'centre', LINE)
    # centre is in progress: blank; the post is stored but not used
    seen = {}
    real = render.table_png

    def spy(zones, frame=None, size=1000, rot_deg=None):
        seen['zones'], seen['frame'] = zones, frame
        return real(zones, frame, 120, rot_deg)
    render.table_png = spy
    try:
        pic(client, 200)
        assert seen['zones'] == {}
        finish(client)                                              # A finished: the post is for A, used now
        pic(client, 200)
        assert seen['zones']['centre'] == {'strokes': LINE}
        # A leaves; the centre is redrawn for B: blank while it runs, and A's old post is never used for B
        client.delete('/api/people/1')
        finish(client)
        cur = state(client)['table']['current']
        assert cur['zone'] == 'centre' and cur['person_id'] == 2
        pic(client, 200)
        assert 'centre' not in seen['zones']
        finish(client)
        pic(client, 200)
        c = seen['zones']['centre']
        assert c['name'] == 'B' and 'strokes' not in c
        post_drawn(client, cur['turn'], 'centre', LINE)              # a post made for B is used for B
        pic(client, 200)
        assert seen['zones']['centre'] == {'strokes': LINE}
    finally:
        render.table_png = real


def test_layout_fallback_zone_has_the_apps_own_items(client, clock):
    from server import render
    add(client, 'Alex')
    set_art(client, 'pie')
    seen = {}
    real = render.table_png

    def spy(zones, frame=None, size=1000, rot_deg=None):
        seen['zones'] = zones
        return real(zones, frame, 120, rot_deg)
    render.table_png = spy
    try:
        finish(client)                                              # centre finished, no post: layout
        pic(client, 200)
        c = seen['zones']['centre']
        assert c['name'] == 'Alex' and c['interests'] == [ST] and c['faces'] == [] and 'strokes' not in c
    finally:
        render.table_png = real


def test_table_png_size_and_default(client):
    add(client, 'A')
    r = client.get('/img/table.png?s=320')
    assert r.status_code == 200 and r.headers['content-type'] == 'image/png'
    assert r.headers['cache-control'] == 'no-cache'
    assert Image.open(io.BytesIO(r.content)).size == (320, 320)
    assert Image.open(io.BytesIO(client.get('/img/table.png?s=50').content)).size == (200, 200)
    assert Image.open(io.BytesIO(client.get('/img/table.png?s=9999').content)).size == (2000, 2000)


def test_table_image_full_table_renders(client):
    from server import render
    zones = {z: {'name': 'Person %s' % z, 'faces': [ST], 'interests': [ST, ST, ST],
                 'art': [ST, ST] if z == 'centre' else []} for z in render.TABLE_ZONES}
    png = render.table_png(zones, size=400)
    assert Image.open(io.BytesIO(png)).size == (400, 400)
    posted = {z: {'strokes': [[[0.5 * i / 10, 0.1 * j] for i in range(10)] for j in range(4)]} for z in render.TABLE_ZONES}
    assert Image.open(io.BytesIO(render.table_png(posted, [[[-1, 0], [1, 0]]], size=400))).size == (400, 400)


# ---------- keepsakes ----------

def test_keepsake_appears_after_a_turn_and_goes_with_the_person(client, clock, tmp_path):
    a = add(client, 'Alex')
    b = add(client, 'Bea')
    tb = client.app.state.tables
    assert all(p['keepsake_v'] == 0 for p in state(client)['people'])
    live = client.get('/img/keepsake/%d.png' % a['id'])               # none yet: the live table picture
    assert live.status_code == 200 and live.content[:4] == b'\x89PNG'
    assert live.headers['cache-control'] == 'no-cache'
    finish(client)
    tb.flush()
    s = state(client)
    pa = next(p for p in s['people'] if p['id'] == a['id'])
    pb = next(p for p in s['people'] if p['id'] == b['id'])
    assert pa['keepsake_v'] == 1 and pb['keepsake_v'] == 0
    f = tmp_path / 'keepsakes' / ('%d.png' % a['id'])
    assert f.exists()
    r = client.get('/img/keepsake/%d.png?v=1' % a['id'])
    assert r.status_code == 200 and r.content == f.read_bytes()
    assert Image.open(io.BytesIO(r.content)).size == (1000, 1000)
    # Alex's next turn replaces the file and bumps the version (only the latest is kept)
    for _ in range(12):
        finish(client)
        clock.t += 61
        tb.flush()
        if next(p for p in state(client)['people'] if p['id'] == a['id'])['keepsake_v'] > 1:
            break
    assert next(p for p in state(client)['people'] if p['id'] == a['id'])['keepsake_v'] > 1
    assert len(list((tmp_path / 'keepsakes').glob('%d*' % a['id']))) == 1
    assert client.delete('/api/people/%d' % a['id']).status_code == 204
    assert not f.exists()
    assert client.get('/img/keepsake/%d.png' % a['id']).status_code == 404


def test_keepsake_with_the_simulated_clock(client, clock, tmp_path):
    client.post('/api/host/settings', json={'auto_advance': True})
    a = add(client, 'Alex')
    tb = client.app.state.tables
    clock.t += 300                      # 4.5 min turn ran out; a lone person with few interests is not redrawn
    state(client)
    tb.flush()
    assert (tmp_path / 'keepsakes' / ('%d.png' % a['id'])).exists()
    assert next(p for p in state(client)['people'] if p['id'] == a['id'])['keepsake_v'] == 1


def test_skipped_turn_makes_no_keepsake(client, clock, tmp_path):
    a = add(client, 'Alex')
    add(client, 'Bea')
    tb = client.app.state.tables
    client.post('/api/host/skip')
    tb.flush()
    assert not (tmp_path / 'keepsakes' / ('%d.png' % a['id'])).exists()


def test_late_drawn_post_refreshes_the_keepsake(client, clock, tmp_path):
    a = add(client, 'Alex')
    add(client, 'Bea')
    tb = client.app.state.tables
    t = state(client)['table']['current']['turn']
    finish(client)
    tb.flush()
    f = tmp_path / 'keepsakes' / ('%d.png' % a['id'])
    before = f.read_bytes()
    assert post_drawn(client, t, 'centre', [[[0.01 * i - 0.2, 0.05] for i in range(40)]]).status_code == 200
    tb.flush()
    assert f.read_bytes() != before
    assert next(p for p in state(client)['people'] if p['id'] == a['id'])['keepsake_v'] == 2


# ---------- the guest list ----------

def test_host_can_remove_any_guest_even_one_not_joined(client):
    a = add(client, 'Alex', join=False)
    b = add(client, 'Bea')
    names = lambda: [p['name'] for p in state(client)['people']]
    assert names() == ['Alex', 'Bea']
    assert client.delete('/api/people/%d' % a['id']).status_code == 204
    assert names() == ['Bea']
    assert client.delete('/api/people/%d' % b['id']).status_code == 204
    assert names() == [] and state(client)['table']['current'] is None


def plan_with_centre_next(client, clock, limit=30):
    for _ in range(limit):
        plan = client.get('/api/worker/plan', headers=W).json()
        n = plan['next']
        if plan['current'] and n and n['zone'] == 'centre' and n['kind'] == 'draw':
            return plan
        finish(client)
        clock.t += 61
    raise AssertionError('no centre turn came up as next')


def test_next_centre_turn_carries_its_pictures_and_keeps_them(client, clock):
    """The driver builds the next turn early: `next` shows the centre pictures and the turn number it will have."""
    for n in ('A', 'B'):
        add(client, n)
    set_art(client, 'pie', 'turkey', 'leaf', 'corn')
    plan = plan_with_centre_next(client, clock)
    nxt = plan['next']
    assert nxt['turn'] == plan['current']['turn'] + 1
    promised = [a['key'] for a in nxt['centre_art']]
    assert len(promised) == 2 and all(a['strokes'] == ST for a in nxt['centre_art'])
    for _ in range(5):                         # asking again never changes the promise
        again = client.get('/api/worker/plan', headers=W).json()['next']
        assert [a['key'] for a in again['centre_art']] == promised
    # switching one off afterwards does not break the promise (the driver may have built the turn already)
    client.post('/api/host/centre-art', json={'key': promised[0], 'enabled': False})
    finish(client)
    clock.t += 61
    plan2 = client.get('/api/worker/plan', headers=W).json()
    cur = plan2['current']
    assert cur['turn'] == nxt['turn'] and cur['person_id'] == nxt['person_id'] and cur['zone'] == 'centre'
    assert [a['key'] for a in cur['centre_art']] == promised
    # a later centre turn gets its own fresh promise, from the enabled ones only
    later = [a['key'] for a in plan_with_centre_next(client, clock)['next']['centre_art']]
    assert len(later) == 2 and promised[0] not in later


def test_promised_pictures_are_redone_when_the_next_person_changes(client, clock):
    for n in ('A', 'B', 'C'):
        add(client, n)
    set_art(client, 'pie', 'turkey', 'leaf', 'corn')
    nxt = plan_with_centre_next(client, clock)['next']
    assert client.delete('/api/people/%d' % nxt['person_id']).status_code == 204
    plan = client.get('/api/worker/plan', headers=W).json()
    new = plan['next']
    assert new is None or new['person_id'] != nxt['person_id']
    if new and new['zone'] == 'centre' and new['kind'] == 'draw':
        assert len(new['centre_art']) == 2
    # whoever does get the centre next still has two pictures when the turn starts
    upcoming = plan_with_centre_next(client, clock)['next']
    keys = [a['key'] for a in upcoming['centre_art']]
    finish(client)
    clock.t += 61
    cur = client.get('/api/worker/plan', headers=W).json()['current']
    assert cur['person_id'] == upcoming['person_id'] and [a['key'] for a in cur['centre_art']] == keys


def test_host_feature_and_pin(client, clock):
    ps = [add(client, n) for n in ('A', 'B', 'C', 'D')]
    kev = ps[3]['id']
    assert client.post('/api/host/feature', json={'person_id': kev, 'zones': ['nowhere']}).status_code == 400
    assert client.post('/api/host/feature', json={'person_id': 999, 'zones': ['centre']}).status_code == 404
    r = client.post('/api/host/feature', json={'person_id': kev, 'zones': ['centre', 'inner-4']})
    assert r.status_code == 200 and [f['zone'] for f in r.json()['table']['forced']] == ['centre', 'inner-4']
    assert [(u['zone'], u['person_id']) for u in r.json()['table']['upcoming'][:2]] == [('centre', kev), ('inner-4', kev)]
    finish(client)
    clock.t += 61
    plan = client.get('/api/worker/plan', headers=W).json()
    assert (plan['current']['zone'], plan['current']['person_id']) == ('centre', kev)
    assert (plan['next']['zone'], plan['next']['person_id']) == ('inner-4', kev)
    finish(client)
    cur = state(client)['table']['current']
    assert (cur['zone'], cur['person_id']) == ('inner-4', kev) and state(client)['table']['forced'] == []
    # pinning: order kept, unknown people refused, removed people drop out
    assert client.post('/api/host/pin', json={'person_ids': [kev, 999]}).status_code == 404
    r = client.post('/api/host/pin', json={'person_ids': [kev, ps[1]['id']]})
    assert r.json()['table']['pinned'] == [kev, ps[1]['id']]
    client.delete('/api/people/%d' % ps[1]['id'])
    assert state(client)['table']['pinned'] == [kev]
    assert client.post('/api/host/pin', json={'person_ids': []}).json()['table']['pinned'] == []


def test_host_erase_request_holds_turns_until_the_driver_resets(client, clock):
    for n in ('A', 'B', 'C'):
        add(client, n)
    cur = state(client)['table']['current']
    assert client.post('/api/host/erase', json={'dir': 'sideways'}).status_code == 400
    r = client.post('/api/host/erase', json={'dir': 'in'}).json()
    e = r['table']['erase']
    assert (e['dir'], e['status']) == ('in', 'waiting')
    plan = client.get('/api/worker/plan', headers=W).json()
    assert plan['erase']['id'] == e['id'] and plan['current']['turn'] == cur['turn']      # the running turn is untouched
    assert plan['next'] is not None                                                        # the forecast still shows what comes after
    finish(client)                                                                         # the turn ends: nothing new starts
    clock.t += 300
    assert state(client)['table']['current']['turn'] == cur['turn']
    # cancel while waiting: the rotation carries on
    assert client.post('/api/host/erase', json={'dir': None}).json()['table']['erase'] is None
    clock.t += 61
    nxt = state(client)['table']['current']
    assert nxt['turn'] == cur['turn'] + 1
    # ask again, other way; a stale id is refused, the right one starts it; then it cannot be cancelled or replaced
    e2 = client.post('/api/host/erase', json={'dir': 'out'}).json()['table']['erase']
    assert e2['id'] != e['id'] and e2['dir'] == 'out'
    assert client.post('/api/worker/erase', json={'id': e2['id'], 'status': 'running'}).status_code in (401, 403)
    assert client.post('/api/worker/erase', headers=W, json={'id': e['id'], 'status': 'running'}).json()['accepted'] is False
    assert client.post('/api/worker/erase', headers=W, json={'id': e2['id'], 'status': 'running'}).json()['accepted'] is True
    assert state(client)['table']['erase']['status'] == 'running'
    assert client.post('/api/host/erase', json={'dir': None}).status_code == 409
    assert client.post('/api/host/erase', json={'dir': 'in'}).status_code == 409
    # the driver reports the table clean: request gone, zones empty, rotation starts from the centre
    s = client.post('/api/worker/reset', headers=W).json()
    assert s['table']['erase'] is None and s['table']['current']['zone'] == 'centre'
    assert all(z['person_id'] is None for z in s['table']['zones'] if z['zone'] != 'centre')
