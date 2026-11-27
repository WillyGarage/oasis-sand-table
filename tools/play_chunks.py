#!/usr/bin/env python3
"""Play a drawing that is split into several .thr files (firmware limit 12,000 points per upload) on the Mini, one
after another, with laptop-camera photos. Each file must start where the previous one ended.

    python3 tools/play_chunks.py OUTDIR part1.thr part2.thr ... [--erase 0.02] [--every 300]

Before anything: the table must be idle (never stops a job someone else started). --erase P runs an inward erase
spiral of pitch P first (the ball then sits at the centre, so the first file should start at the centre).
Stops (and sends /stop) if progress does not advance for 120 s or the table reports a fault. Writes OUTDIR/log.json.
Run it in the background (nohup); WSL kills shell commands after about 2 minutes.
"""
import argparse, json, os, subprocess, sys, time, urllib.request

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'http://10.0.0.204'


def get(path, data=None, timeout=10):
    for i in range(5):
        try:
            req = urllib.request.Request(URL + path, data=data)
            if data is not None:
                req.add_header('Content-Type', 'text/plain')
            with urllib.request.urlopen(req, timeout=timeout) as r:
                t = r.read().decode()
            try:
                return json.loads(t)
            except Exception:
                return t.strip()
        except Exception as e:
            last = e
            time.sleep(3)
    raise RuntimeError('table unreachable: %s %s' % (path, last))


def photo(out, name):
    try:
        get('/led?mode=solid&c=ffffff&b=60&tmp=1')
        time.sleep(1.5)
        subprocess.run(['bash', D + '/tools/cam.sh', os.path.join(out, name), '0'], timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print('photo failed', e, flush=True)
    finally:
        try:
            get('/led?restore=1')
        except Exception:
            pass


def run_job(log, label, every, out):
    last_p, last_t, t0, next_photo = -1.0, time.time(), time.time(), time.time() + every
    while True:
        s = get('/status')
        p = float(s.get('progress', 0))
        if s.get('fault'):
            get('/stop')
            raise RuntimeError('%s: fault %s' % (label, s.get('fault')))
        if s.get('state') == 'idle' and time.time() - t0 > 3:
            log.append(dict(label=label, seconds=round(time.time() - t0), end=s.get('rho')))
            print('%s done in %.0f s' % (label, time.time() - t0), flush=True)
            return
        if p != last_p:
            last_p, last_t = p, time.time()
        elif time.time() - last_t > 120:
            get('/stop')
            raise RuntimeError('%s: no progress for 120 s' % label)
        if every and time.time() > next_photo:
            photo(out, '%s_%03d.jpg' % (label, int(time.time() - t0) // 60))
            next_photo = time.time() + every
        time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--erase', type=float, default=0.0)
    ap.add_argument('--erase-out', action='store_true', help='erase centre -> rim (ball ends at the rim) instead of inward')
    ap.add_argument('--every', type=float, default=0.0, help='photo interval in seconds while drawing (0 = off)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    log = []
    s = get('/status')
    if s.get('state') != 'idle':
        sys.exit('table is busy (%s); not touching it' % s.get('state'))
    photo(a.out, 'before.jpg')
    try:
        if a.erase:
            print(get('/gen?kind=%s&pitch=%g' % ('erase_out' if a.erase_out else 'erase_in', a.erase)), flush=True)
            run_job(log, 'erase', 0, a.out)
            photo(a.out, 'after_erase.jpg')
        for i, f in enumerate(a.files):
            up = get('/thr', data=open(f, 'rb').read(), timeout=60)
            print('upload', os.path.basename(f), up, flush=True)
            if not isinstance(up, dict) or not up.get('points'):
                raise RuntimeError('upload rejected: %r' % (up,))
            print(get('/play'), flush=True)
            run_job(log, 'part%d' % (i + 1), a.every, a.out)
            photo(a.out, 'after_part%d.jpg' % (i + 1))
    finally:
        json.dump(log, open(os.path.join(a.out, 'log.json'), 'w'), indent=1)
    photo(a.out, 'final.jpg')
    print('ALL DONE', flush=True)


if __name__ == '__main__':
    main()
