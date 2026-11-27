#!/usr/bin/env python3
"""Small supervised moves with eyes (camera) and ears (microphone).

  t.py where                    ball position about the rotation centre C: r (sand radii), angle (deg)
  t.py step DM1 DM2 [--quiet]   relative raw move; prints before/after position and what the mic heard
  t.py to M1 M2                 absolute raw move, same report
Every line is appended to captures/t.log as JSON."""
import json, math, subprocess, sys, time, threading
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o, calib2 as c
D = o.D
P = c.load_params()

LASTF = D + '/captures/ball_last.json'
def where(near_px=None):
    """near_px: only accept a ball within this many pixels of the last accepted position (small moves on marked
    sand: the sand has ball-like marks, and the previous-frame filter would drop a ball that barely moved)."""
    m = o.measure(prev_rel=None)
    cs = m.get('cands') or []
    if near_px:
        try: lx, ly = json.load(open(LASTF))
        except Exception: lx = None
        if lx is not None:
            cs = [q for q in cs if math.hypot(q['px'][0] - lx, q['px'][1] - ly) <= near_px] or cs[:1]
    b = cs[0] if cs else None
    if not b: return dict(ok=False, photo=m.get('photo'))
    json.dump(b['px'], open(LASTF, 'w'))
    x, y = c.px_to_plane(P, b['px'][0], b['px'][1])
    return dict(ok=True, r=round(math.hypot(x, y), 3), ang=round(math.degrees(math.atan2(y, x)), 1),
                score=b['score'], margin=m['margin'], photo=m['photo'])

def move(t1, t2, hear=True, us=None):
    t0 = time.time()
    r = o.get("/raw?m1=%d&m2=%d%s" % (t1, t2, "&us=%d" % us if us else ""))
    if isinstance(r, str) and "busy" in r: raise RuntimeError(r)
    o.wait_idle()
    time.sleep(1.6)          # coils release 1 s after the move: keep listening through that
    return (o.heard(t0) if hear else {}), [round(t0, 2), round(time.time(), 2)]

def main():
    a = sys.argv[1:]
    hear = '--quiet' not in a; a = [x for x in a if x != '--quiet']
    if a[0] == 'where':
        rec = dict(cmd='where', st={k: o.status()[k] for k in ('cur1', 'cur2', 'homed')}, pos=where())
    else:
        st = o.status(); before = where()
        if a[0] == 'step': t1, t2 = st['cur1'] + int(a[1]), st['cur2'] + int(a[2])
        else: t1, t2 = int(a[1]), int(a[2])
        heard, tm = move(t1, t2, hear)
        n = max(abs(t1 - st['cur1']), abs(t2 - st['cur2']))
        after = where(near_px=25 + n * 0.25 if n < 700 else None)
        rec = dict(cmd=a[0], frm=[st['cur1'], st['cur2']], to=[t1, t2], before=before, after=after, heard=heard)
    rec['t'] = time.strftime('%H:%M:%S')
    open(D + '/captures/t.log', 'a').write(json.dumps(rec) + '\n')
    for k in ('before', 'after', 'pos'):
        if k in rec and isinstance(rec[k], dict): rec[k].pop('photo', None)
    print(json.dumps(rec))

main()
