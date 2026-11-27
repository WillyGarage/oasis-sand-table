#!/usr/bin/env python3
"""Wait until the table stops being moved around in the camera view.
Finds the sand outline every ~8 s; exits 0 once it has stayed within 2 px for STABLE_S seconds (default 120),
printing the settled outline. Exits 1 after MAX_S (default 1500). Log: captures/scene_watch.log"""
import sys, time, json
sys.path.insert(0, '/home/bill/dev/WillyGarage/oasis/tools')
import oasislib as o, locate, cv2
stable_s = float(sys.argv[1]) if len(sys.argv) > 1 else 120
max_s = float(sys.argv[2]) if len(sys.argv) > 2 else 1500
log = open(o.D + '/captures/scene_watch.log', 'a')
t0 = time.time(); anchor = None; since = None
while time.time() - t0 < max_s:
    try:
        im = cv2.imread(o.D + '/' + o.snap())
        e, q = locate.find_ellipse(im)
        e = locate._norm_ellipse(e) if e is not None else None
    except Exception as ex:
        e = None
    now = time.time()
    log.write(json.dumps(dict(t=time.strftime('%H:%M:%S'), e=e)) + '\n'); log.flush()
    if e is None: anchor = None
    elif anchor is None or abs(e['cx'] - anchor['cx']) > 2 or abs(e['cy'] - anchor['cy']) > 2 or abs(e['a'] - anchor['a']) > 2:
        anchor = e; since = now
    elif now - since >= stable_s:
        print('STABLE', json.dumps(anchor)); sys.exit(0)
    time.sleep(6)
print('TIMEOUT', json.dumps(anchor)); sys.exit(1)
