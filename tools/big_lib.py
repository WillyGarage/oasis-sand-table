#!/usr/bin/env python3
"""Shared helpers for qualification runs on the 36-inch table (bench firmware at 10.0.0.149).
get(path) -> text, status() -> dict, move(r, a, hz, acc) waits until the move ends and returns the status,
ball(tag) -> (x_px, y_px, score) from one frame of the USB camera (index 1), log(obj) appends JSON lines to the
run's log. Every script that uses this refuses to start if the table reports a fault or a move in progress."""
import json, os, subprocess, sys, time, urllib.request

T = 'http://10.0.0.149'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'captures', 'big-qual')
os.makedirs(OUT, exist_ok=True)
ARM_TURN = 38400


def get(path, timeout=10):
    for attempt in range(3):
        try:
            return urllib.request.urlopen(T + path, timeout=timeout).read().decode().strip()
        except urllib.error.HTTPError as e:
            return 'HTTP %d %s' % (e.code, e.read().decode().strip())
        except Exception as e:
            err = e
            time.sleep(1)
    raise RuntimeError('table did not answer %s: %s' % (path, err))


def status():
    return json.loads(get('/status'))


def mv(s=None):
    return (s or status())['move']


def wait_idle(limit=400):
    t = time.time()
    while time.time() - t < limit:
        s = status()
        if not s['move']['run'] and not s['pulse']['run']:
            return s
        time.sleep(0.25)
    get('/stop')
    raise RuntimeError('move did not finish in %d s; stopped' % limit)


def move(r, a, hz=1000, acc=2000):
    """Coordinated move; returns the status after it ends. Raises if the table refuses."""
    rep = get('/move?r=%d&a=%d&hz=%g&acc=%g' % (r, a, hz, acc))
    if not rep.startswith('moving'):
        raise RuntimeError('move refused: ' + rep)
    return wait_idle(max(abs(r), abs(a)) / hz * 1.5 + 30)


def hold(a):
    """Radius steps that keep the carriage still while the arm moves a steps (1/6 coupling), whole steps,
    exact over a run because it is computed from the absolute arm counter."""
    A = mv()['a']
    return (A + a) // 6 - A // 6


def turn(a, hz=1000, acc=2000):
    """Arm move with the radius held."""
    return move(hold(a), a, hz, acc)


def edges(clear=True):
    return json.loads(get('/edges' + ('?clear=1' if clear else '')))['edges']


def ball(tag='f'):
    f = os.path.join(OUT, tag + '.jpg')
    env = dict(os.environ, OASIS_EXP='-6')
    for attempt in range(3):
        subprocess.run([os.path.join(ROOT, 'tools', 'cam.sh'), f, '1'], env=env, capture_output=True, text=True)
        o = subprocess.run(['python3', os.path.join(ROOT, 'tools', 'big_ball.py'), f], capture_output=True, text=True).stdout.split()
        if len(o) >= 3 and o[0] != 'none':
            return float(o[0]), float(o[1]), float(o[2])
        time.sleep(1)
    raise RuntimeError('ball not found in ' + f)


def sg(addr):
    """StallGuard reading (SG_RESULT, register 0x41) of driver addr, or None."""
    try:
        v = json.loads(get('/tmc?a=%d&r=0x41' % addr))['read']
        return int(v, 16) if v else None
    except Exception:
        return None


_logf = None


def log(obj, name=None):
    global _logf
    if _logf is None:
        _logf = open(os.path.join(OUT, (name or os.path.basename(sys.argv[0]).replace('.py', '')) + '.jsonl'), 'a')
    obj = dict(obj, t=time.strftime('%H:%M:%S'))
    _logf.write(json.dumps(obj) + '\n'); _logf.flush()
    print(json.dumps(obj), flush=True)


def precheck():
    s = status()
    m = s['move']
    if m['run'] or s['pulse']['run'] or m['fault']:
        raise SystemExit('table busy or faulted: %s' % m)
    return s
