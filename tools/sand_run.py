#!/usr/bin/env python3
"""Play a sequence of zone .thr files on the 36-inch table, one upload per zone, with a camera frame after each.
  sand_run.py DIR_OR_FILES... [--shots DIR] [--start N]
Each file is uploaded (POST /thr) and played (/play) only when the table is idle, homed and fault-free; the next file
waits for the previous job to end. Any fault (an arm slip beyond tolerance sets one) or refused upload stops the run (no further files). One JSON
line per event goes to captures/sand-app/sand_run.jsonl. No erase is sent: the files draw on whatever sand is there."""
import sys, os, glob, json, time, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from big_lib import T, ROOT, get, status

args = sys.argv[1:]
shots = None
start = 1
if '--shots' in args:
    i = args.index('--shots'); shots = args[i + 1]; del args[i:i + 2]
if '--start' in args:
    i = args.index('--start'); start = int(args[i + 1]); del args[i:i + 2]
files = []
for a in args:
    files += sorted(glob.glob(os.path.join(a, '*.thr'))) if os.path.isdir(a) else [a]
files = files[start - 1:]
LOG = os.path.join(ROOT, 'captures/sand-app/sand_run.jsonl')


def log(d):
    d['t'] = time.strftime('%Y-%m-%d %H:%M:%S')
    print(json.dumps(d), flush=True)
    with open(LOG, 'a') as f:
        f.write(json.dumps(d) + '\n')


def ready(s):
    m, j = s['move'], s['job']
    return (not m['run'] and not j['run'] and not s['pulse']['run'] and not m['fault']
            and m['arm_homed'] and m['rad_homed'])


def shot(tag):
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    out = os.path.join(shots, tag + '.jpg')
    try:
        r = subprocess.run([os.path.join(ROOT, 'tools/cam.sh'), out, '1'], env=dict(os.environ, OASIS_EXP='-6'),
                           capture_output=True, text=True, timeout=60)
        log({'what': 'shot', 'file': out, 'ok': r.returncode == 0 and os.path.exists(out)})
    except Exception as e:
        log({'what': 'shot', 'file': out, 'ok': False, 'err': str(e)})


s = status()
if not ready(s):
    raise SystemExit('table not ready: move=%s job=%s' % (s['move'], s['job']))
log({'what': 'start', 'files': [os.path.basename(f) for f in files], 'up_s': s['up_s']})
shot('00-before')
for k, f in enumerate(files, start):
    s = status()
    if not ready(s):
        log({'what': 'abort', 'why': 'not ready before upload', 'move': s['move'], 'job': s['job']}); sys.exit(1)
    body = open(f, 'rb').read()
    req = urllib.request.Request(T + '/thr', data=body, headers={'Content-Type': 'text/plain'}, method='POST')
    up = urllib.request.urlopen(req, timeout=60).read().decode().strip()
    log({'what': 'upload', 'file': os.path.basename(f), 'reply': up})
    want = sum(1 for l in body.decode().splitlines() if l.strip() and not l.lstrip().startswith('#'))
    try:
        u = json.loads(up)
    except ValueError:
        u = {}
    if u.get('points') != want or u.get('bad_lines') or u.get('dropped'):
        log({'what': 'abort', 'why': 'upload mismatch', 'want': want}); sys.exit(1)
    rep = get('/play')
    log({'what': 'play', 'file': os.path.basename(f), 'reply': rep})
    if 'playing' not in rep:
        log({'what': 'abort', 'why': 'play refused'}); sys.exit(1)
    t0 = time.time()
    while True:
        time.sleep(2)
        s = status(); m, j = s['move'], s['job']
        if m['fault']:
            get('/stop')
            log({'what': 'abort', 'why': 'fault', 'move': m, 'job': j}); sys.exit(1)
        if not j['run']:
            break
    log({'what': 'done', 'file': os.path.basename(f), 'secs': round(time.time() - t0), 'end': j['end'],
         'pt': j['pt'], 'n': j['n'], 'checks': m['slip_checks'], 'slip_err': m['slip_err'], 'carriage': m['carriage']})
    shot('%02d-%s' % (k, os.path.splitext(os.path.basename(f))[0]))
log({'what': 'finished'})
