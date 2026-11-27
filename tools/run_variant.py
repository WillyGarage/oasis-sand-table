#!/usr/bin/env python3
"""Draw test versions of a picture one after another, each on a fresh erase, and photograph each.

  run_variant.py LABEL:THR:PITCH [LABEL:THR:PITCH ...]
     LABEL  photo goes to captures/variants/LABEL.jpg (+ _raw.jpg)
     THR    a .thr file (uploaded with POST /thr and played), or stored=<name> for a drawing already on the table
     PITCH  erase spiral pitch (0.02 = the usual fine background; 0 = no erase)
  --wait   first wait for the job already running on the table (e.g. an erase) to finish

Each version: wait for idle -> erase outward at PITCH -> draw without the built-in erase -> photo -> 3 min idle gap.
Never sends /stop. Gives up (and says so) on any fault, on a job it did not start, or if the table is busy.
captures/draw.lock exists while a version is in progress; it waits while captures/ota.lock exists (firmware update)."""
import os, sys, time, urllib.request
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o
D = o.D; LOCK = D + '/captures/draw.lock'; OTA = D + '/captures/ota.lock'
os.makedirs(D + '/captures/variants', exist_ok=True)
def say(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)

def st():
    for _ in range(40):
        try: return o.status()
        except Exception: time.sleep(5)
    raise SystemExit('table not answering')

def idle_wait(what, limit):
    """wait until idle with an empty queue; return the last status. No /stop on timeout."""
    t0 = time.time(); time.sleep(4)
    while True:
        s = st()
        if s.get('fault'): say('FAULT', s['fault'], 'during', what); return None
        if s['state'] == 'idle' and not s.get('queue'): return s
        if time.time() - t0 > limit: say('timeout waiting for', what); return None
        time.sleep(5)

def send(path):
    try: return urllib.request.urlopen('http://10.0.0.204' + path, timeout=10).read().decode().strip()
    except Exception as e: return 'ERR %s' % e

def one(label, thr, pitch):
    while os.path.exists(OTA): time.sleep(5)
    s = st()
    if '--wait' in sys.argv:                       # let whatever is running (an erase already under way) finish first
        s = idle_wait('the job already running', 1500)
        if not s: return False
    if s['state'] != 'idle' or s.get('queue') or s.get('auto') or s.get('paused'):
        say('table busy (%s %s), not starting' % (s['state'], s.get('queue')), label); return False
    if not s.get('homed') or s.get('fault'): say('not homed or fault, not starting', label); return False
    open(LOCK, 'w').write(label)
    try:
        if pitch > 0:
            say(label, 'erase pitch', pitch, '->', send('/gen?kind=erase_out&pitch=%s' % pitch))
            s = idle_wait('erase', 1500)
            if not s: return False
            say('erase done', 'idx_err', s.get('idx_err'))
        if thr.startswith('stored='):
            say('draw ->', send('/draw?name=%s&erase=0' % thr[7:]))
        else:
            body = open(thr, 'rb').read()
            r = urllib.request.urlopen(urllib.request.Request('http://10.0.0.204/thr', data=body, method='POST'), timeout=30).read().decode().strip()
            say('upload ->', r, '| play ->', send('/play'))
        s = idle_wait('drawing', 2700)
        if not s: return False
        if s.get('progress', 0) < 0.99: say('ended early, progress', s.get('progress')); return False
        out = D + '/captures/variants/%s.jpg' % label
        o.portrait(out); os.system('python3 %s/tools/brighten.py %s' % (D, out)); say('photo', out, 'idx_err', s.get('idx_err'))
        return True
    finally:
        if os.path.exists(LOCK): os.remove(LOCK)

ARGS = [a for a in sys.argv[1:] if a != '--wait']
for i, a in enumerate(ARGS):
    label, thr, pitch = a.split(':')
    ok = one(label, thr, float(pitch))
    if not ok: say('STOPPED at', label); break
    if i < len(ARGS) - 1: time.sleep(180)
say('all done')
