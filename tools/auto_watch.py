#!/usr/bin/env python3
"""Chaperone for the table's own auto mode (/auto): photograph every finished piece and keep it safe.

  auto_watch.py [--hold 300] [--until HH:MM] [--led "mode=follow&c=ffb060&b=70"]

Turns auto mode on, then loops: when a piece finishes (auto_pieces goes up, the table holds it on show) it switches the
ring to photo light, takes the straightened portrait into captures/auto/NNN_<what>.jpg, checks with the camera that the
ball really is at the centre, and puts the light back. If the table reports a fault (main motor slipped) or the ball is
more than 6 mm from where it should be (elbow motor slipped), it re-homes and turns auto back on; three recoveries in a
row and it stops. Everything is logged to captures/auto/log.jsonl. Stops auto mode at --until (default: never)."""
import argparse, json, math, os, sys, time
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o, calib2
D = o.D; OUT = D + '/captures/auto'
os.makedirs(OUT, exist_ok=True)
ap = argparse.ArgumentParser()
ap.add_argument('--hold', type=int, default=300); ap.add_argument('--until', default=None)
ap.add_argument('--led', default='')      # unused since firmware v8.4: the ring is on Automatic and photos borrow it with tmp=1
a = ap.parse_args()

def log(**k):
    k['t'] = time.strftime('%H:%M:%S'); open(OUT + '/log.jsonl', 'a').write(json.dumps(k) + '\n'); print(json.dumps(k), flush=True)

def past_until():
    return a.until is not None and time.strftime('%H:%M') >= a.until and time.strftime('%H') < '12'

def home_and_start():
    o.get('/stop'); time.sleep(2); o.wait_idle()
    o.get('/home'); s = o.wait_idle(300)
    if not s.get('homed'): log(event='home failed', home_err=s.get('home_err')); return False
    o.get('/auto?on=1&hold=%d' % a.hold)
    return True

p = calib2.load_params()
s = o.wait_idle(900)
if not s.get('homed') or s.get('fault'):
    if not home_and_start(): sys.exit(1)
else:
    print(o.get('/auto?on=1&hold=%d' % a.hold), flush=True)
n_seen = o.status().get('auto_pieces', 0); n_img = len([f for f in os.listdir(OUT) if f.endswith('.jpg') and '_raw' not in f])
t_piece = time.time(); recov = 0; last_gen = ''
while True:
    time.sleep(4)
    try: s = o.status()
    except Exception as e:
        log(event='status failed', err=str(e)); time.sleep(20); continue
    if s.get('state') == 'drawing' and s.get('now') and not s['now'].startswith('erase'): last_gen = s['now']
    if s.get('auto_pieces', 0) > n_seen and s.get('state') == 'idle':          # a piece is finished and on show
        n_seen = s['auto_pieces']; n_img += 1
        name = '%03d_%s' % (n_img, last_gen.split(' ')[0] or 'piece')
        rec = dict(event='piece', n=n_img, gen=last_gen, minutes=round((time.time() - t_piece) / 60, 1), heard=o.heard(t_piece))
        try:
            b, near, ph, cs = calib2.see(p, s['cur1'], s['cur2'], s['m2h'], tol=0.2)
            mx, my, _, _ = calib2.model(p, s['cur1'], s['cur2'], s['m2h'])
            rec['err_mm'] = round(math.hypot(b['x'] - mx, b['y'] - my) * 126, 1); rec['score'] = b['score']
            o.portrait('%s/%s.jpg' % (OUT, name)); rec['image'] = 'captures/auto/%s.jpg' % name
        except Exception as e:
            rec['photo_error'] = str(e)
        o.light_restore()
        rec['idx_err'] = s.get('idx_err'); log(**rec)
        t_piece = time.time()
        if rec.get('err_mm', 0) > 6 and rec.get('score', 0) > 0.5:
            recov += 1; log(event='ball off by %.1f mm: re-homing' % rec['err_mm'], recoveries=recov)
            if recov >= 3 or not home_and_start(): break
        else: recov = 0
        if past_until():
            o.get('/auto?on=0'); log(event='stopped at --until, piece left on show'); break
        continue
    if not s.get('auto') and s.get('state') == 'idle':                          # auto dropped out: fault, or someone pressed stop
        if s.get('fault') or not s.get('homed'):
            recov += 1; log(event='fault %s: re-homing' % s.get('fault'), recoveries=recov)
            if recov >= 3 or not home_and_start(): break
            t_piece = time.time()
        else:
            log(event='auto was turned off (stop pressed?): leaving it off'); break
log(event='watcher exit')
