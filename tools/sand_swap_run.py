#!/usr/bin/env python3
"""Play one zone swap (patterns/sand-party/swaps/NN-*/) on the 36-inch table, file by file, at each file's speed.
  sand_swap_run.py SWAP_DIR [--home-before 2b] [--from 2b] [--shot captures/...jpg]
manifest.json lists the files in order with play_speed "clear" (played at cfg vclear) or "draw" (cfg vball as saved).
Every upload's point count is checked; any fault stops the run. --home-before PREFIX re-homes the arm on its sensor
and the radius on the centre stop just before the file whose name starts with PREFIX (the ball must already be at
the centre). One JSON line per event in captures/sand-app/swap_run.jsonl."""
import sys, os, json, time, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from big_lib import T, ROOT, get, status

args = sys.argv[1:]
home_before = shot = from_file = None
if '--home-before' in args:
    i = args.index('--home-before'); home_before = args[i + 1]; del args[i:i + 2]
if '--from' in args:
    i = args.index('--from'); from_file = args[i + 1]; del args[i:i + 2]
if '--shot' in args:
    i = args.index('--shot'); shot = args[i + 1]; del args[i:i + 2]
d = args[0]
man = json.load(open(os.path.join(d, 'manifest.json')))
LOG = os.path.join(ROOT, 'captures/sand-app/swap_run.jsonl')


def log(x):
    x['t'] = time.strftime('%Y-%m-%d %H:%M:%S'); print(json.dumps(x), flush=True)
    open(LOG, 'a').write(json.dumps(x) + '\n')


def wait(limit=1800):
    t = time.time()
    while time.time() - t < limit:
        s = status(); m, j = s['move'], s['job']
        if m['fault']:
            get('/stop'); log({'what': 'abort', 'why': 'fault', 'move': m}); sys.exit(1)
        if not j['run'] and not m['run'] and not s['pulse']['run'] and s['move'].get('home', 0) != 1:
            return s
        time.sleep(0.3)
    get('/stop'); log({'what': 'abort', 'why': 'timeout'}); sys.exit(1)


s = status(); cfg = s['cfg']; vdraw, vclear = cfg['vball'], cfg.get('vclear', 850)
if s['job']['run'] or s['move']['run'] or s['move']['fault'] or not s['move']['arm_homed'] or not s['move']['rad_homed']:
    raise SystemExit('table not ready: %s' % s['move'])
log({'what': 'swap start', 'dir': d, 'vdraw': vdraw, 'vclear': vclear})
t_all = time.time()
try:
    files = man['files']
    if from_file:
        files = files[[f['file'].startswith(from_file) for f in files].index(True):]
    for f in files:
        name = f['file']
        if home_before and name.startswith(home_before):
            for cmd in ('/homearm', '/homeradius'):
                rep = get(cmd, timeout=90); s = wait(180)
                log({'what': cmd, 'reply': rep, 'carriage': s['move']['carriage'], 'a': s['move']['a']})
        v = vclear if f['play_speed'] == 'clear' else vdraw
        get('/cfg?vball=%g' % v)
        body = open(os.path.join(d, name), 'rb').read()
        want = sum(1 for l in body.decode().splitlines() if l.strip() and not l.lstrip().startswith('#'))
        up = urllib.request.urlopen(urllib.request.Request(T + '/thr', data=body, headers={'Content-Type': 'text/plain'}, method='POST'), timeout=60).read().decode()
        u = json.loads(up)
        if u.get('points') != want or u.get('bad_lines') or u.get('dropped'):
            log({'what': 'abort', 'why': 'upload mismatch', 'file': name, 'reply': up}); sys.exit(1)
        rep = get('/play')
        if 'playing' not in rep:
            log({'what': 'abort', 'why': 'play refused', 'reply': rep}); sys.exit(1)
        t0 = time.time(); s = wait()
        log({'what': 'done', 'file': name, 'speed': v, 'secs': round(time.time() - t0, 1), 'carriage': s['move']['carriage'],
             'slip_err': s['move']['slip_err'], 'end': s['job']['end']})
finally:
    get('/cfg?vball=%g' % vdraw)
log({'what': 'swap done', 'dir': d, 'secs': round(time.time() - t_all, 1)})
if shot:
    subprocess.run([os.path.join(ROOT, 'tools/cam.sh'), shot, '1'], env=dict(os.environ, OASIS_EXP='-6'), capture_output=True, timeout=90)
