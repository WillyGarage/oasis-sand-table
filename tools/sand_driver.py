#!/usr/bin/env python3
"""Home-side driver: plays the sand app's table plan on the 36-inch table (or, by default, only pretends to).

    python3 tools/sand_driver.py --base http://127.0.0.1:8791 --token dev            # DRY-RUN (default): no table is contacted
    python3 tools/sand_driver.py --base http://127.0.0.1:8791 --token dev --once     # one turn, then stop
    python3 tools/sand_driver.py --base URL --token T --real                         # REAL: drives the table; see the guards below

Loop: GET /api/worker/plan -> build the current turn's files (tools/sand_turn.py: travel, clear, recut, name, face, pictures,
starting from the last file's last row) -> play them -> POST /api/worker/progress per file and within files -> done=true.
If a progress reply says accepted=false (turn skipped or removed in the app) the driver finishes the file it is in (the ball is
never stopped mid-file), records the zone as dirty, and takes the new current turn; if the ball is then off the frame lines
the next turn starts with a short recovery line to the nearest line of the same zone (that zone is wiped next anyway).

Progress map: clearing 0-30 (travel, clear, recut), name 30-45, face 45-75, pictures 75-100; steps without content are dropped and the
rest re-spread; a clear turn is 0-100 clearing.

State (JSON): captures/sand-app/driver-state.json in real mode, driver-state-dryrun.json in dry-run, so pretend runs never feed
the real ball position.  Per turn files: captures/sand-app/driver[-dryrun]/turn-NNNN-zone/ (manifest.json, preview.png).

Guards: --real refuses unless --base is 127.0.0.1/localhost, or --allow-live is also given.  Real mode also checks the table is idle
and homed first (same as tools/sand_swap_run.py).  Dry-run never imports the table libraries.
"""
import argparse, fcntl, json, math, os, pickle, sys, time, urllib.parse, urllib.request, urllib.error
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
CAP = os.path.join(ROOT, 'captures', 'sand-app')


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def log(*a):
    print(now(), *a, flush=True)


class App:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip('/'), token

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                     headers={'Content-Type': 'application/json', 'X-Worker-Token': self.token})
        return json.loads(urllib.request.urlopen(req, timeout=20).read() or b'null')

    def raw(self, path):
        req = urllib.request.Request(self.base + path, headers={'X-Worker-Token': self.token})
        return urllib.request.urlopen(req, timeout=60).read()

    def post_face(self, pid, preview_png, path_json, face_v):
        import uuid
        bd = uuid.uuid4().hex
        parts = []
        for k, v in (('path', path_json), ('face_v', str(face_v))):
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (bd, k, v)).encode())
        parts.append(('--%s\r\nContent-Disposition: form-data; name="preview"; filename="preview.png"\r\nContent-Type: image/png\r\n\r\n' % bd).encode() + preview_png + b'\r\n')
        parts.append(('--%s--\r\n' % bd).encode())
        req = urllib.request.Request(self.base + '/api/worker/faces/%d' % pid, data=b''.join(parts), method='POST',
                                     headers={'X-Worker-Token': self.token, 'Content-Type': 'multipart/form-data; boundary=' + bd})
        return json.loads(urllib.request.urlopen(req, timeout=60).read() or b'null')

    def post_drawn(self, turn, zone, strokes):
        return self.call('POST', '/api/worker/drawn', dict(turn=turn, zone=zone, strokes=strokes))

    def plan(self):
        return self.call('GET', '/api/worker/plan')

    def host_pause(self, flag):
        """The host's Pause button (POST /api/host/pause): used to hold the queue when a human is needed."""
        try:
            self.call('POST', '/api/host/pause', dict(paused=bool(flag)))
        except Exception as e:
            log('  could not set the app pause (%r)' % (e,))

    def paused(self):
        """The app's host Pause is the table's pause/start (Bill, 2026-11-25). Unreachable app counts as not paused."""
        try:
            return bool(self.call('GET', '/api/state').get('paused'))
        except Exception:
            return False

    def progress(self, turn, percent, done=False):
        """A failed post (app redeploying) is logged and ignored: playback carries on and the next post catches up."""
        try:
            return self.call('POST', '/api/worker/progress', dict(turn=turn, percent=int(round(percent)), done=bool(done)))
        except Exception as e:
            now_ = time.time()
            if now_ - getattr(self, '_last_fail_log', 0) > 10:
                log('  progress post failed (%r); carrying on' % (e,))
                self._last_fail_log = now_
            return dict(accepted=True, offline=True)

    def progress_final(self, turn):
        """The done=true post: retried every few seconds until the app answers (accepted true or false)."""
        tries = 0
        while True:
            try:
                return self.call('POST', '/api/worker/progress', dict(turn=turn, percent=100, done=True))
            except Exception as e:
                tries += 1
                if tries == 1 or tries % 10 == 0:
                    log('  done post failed (%r); retrying every 3 s until the app answers' % (e,))
                time.sleep(3)


class State:
    def __init__(self, path, start_file):
        self.path = path
        self.d = dict(last_file=start_file, dirs={}, holds={}, turns_done=0, recover_zone=None, world_file=None, layers_file=None, history=[])
        if os.path.exists(path):
            self.d.update(json.load(open(path)))
        self.world_path = path.replace('.json', '-world.npy')
        self.layers_path = path.replace('.json', '-layers.pkl')

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        json.dump(self.d, open(tmp, 'w'), indent=1)
        os.replace(tmp, self.path)

    def world(self):
        # no world file = the table was just cleared whole (every whole-table clear deletes it): an EMPTY table. Returning None
        # made build_turn assume revision 3's old drawing was still there, and on 2026-11-26 Alex's centre face was dropped as
        # "too close to a neighbouring drawing" on a freshly erased table.
        return np.load(self.world_path) if os.path.exists(self.world_path) else np.zeros((0, 2))

    def set_world(self, w):
        np.save(self.world_path, w)

    def layers(self):
        return pickle.load(open(self.layers_path, 'rb')) if os.path.exists(self.layers_path) else []

    def set_layers(self, L):
        pickle.dump(L, open(self.layers_path, 'wb'))


def strokes_of(x):
    if isinstance(x, dict):
        x = x.get('strokes')
    return x or []


def recovery_file(sz, last_file, zone_name, st, out_path):
    """The ball stopped off the frame lines inside zone `zone_name`: a straight line to the nearest point of that zone's boundary."""
    import sand_turn as t
    from shapely.geometry import Point
    import sand_update_plan as u
    geo = t.zone_geometry(zone_name)
    if geo['kind'] == 'centre':
        zp = u.zone_poly(dict(kind='centre'))
    else:
        zd = u.make_zone('slice', geo['ring'], geo['a'][0], geo['a'][1])
        zd['kind'] = 'slice'
        zp = u.zone_poly(zd)
    rows = sz.read_rows(last_file)
    xy = sz.rows_xy(rows[-1:])[0]
    b = zp.exterior
    q = b.interpolate(b.project(Point(xy)))
    tgt = np.array([q.x, q.y])
    if np.hypot(*(tgt - xy)) < 0.5:
        return None
    out = sz.draw_rows([np.array([xy, tgt])], rows[-1])
    sz.write_rows(out_path, out)
    return out_path


MAX_DRAWN_POINTS = 60000


def off_frame_zone(sz, last_file, tol=1.0):
    """If the ball (last row of last_file) is farther than tol mm from every frame line, the name of the zone it is in; else None."""
    import sand_update_plan as u
    from shapely.geometry import Point
    xy = sz.rows_xy(sz.read_rows(last_file)[-1:])[0]
    if min(g.distance(Point(*xy)) for _, g in u.frame_geoms()) <= tol:
        return None
    r = math.hypot(*xy)
    a = math.degrees(math.atan2(xy[1], xy[0])) % 360
    if r < u.f0:
        return 'centre'
    if r < u.f1:
        return 'inner-%d' % (int(a // 90) + 1)
    return 'outer-%d' % (int(a // 60) + 1)


def drawn_payload(b, kind, turn, zone):
    """What stays visible in the zone, for the keepsake: travel, recut and content files (never the clear files); a clear turn sends only
    its recut.  x = rho cos(theta), y = rho sin(theta) straight from the rows (y up), one polyline per file, thinned to < 60,000 points."""
    rows = []
    for path in b['file_paths']:
        name = os.path.basename(path)
        keep = name.startswith('3') if kind == 'clear' else name[0] in '134'
        if keep:
            a = np.loadtxt(path, ndmin=2)
            rows.append(np.column_stack((a[:, 1] * np.cos(a[:, 0]), a[:, 1] * np.sin(a[:, 0]))))
    total = sum(len(r) for r in rows)
    k = max(1, int(math.ceil(total / (MAX_DRAWN_POINTS * 0.92))))
    strokes = []
    for r in rows:
        idx = list(range(0, len(r), k))
        if idx[-1] != len(r) - 1:
            idx.append(len(r) - 1)
        strokes.append([[round(float(x), 4), round(float(y), 4)] for x, y in r[idx]])
    return dict(turn=turn, zone=zone, strokes=strokes)


FACE_FAILED = set()
CARTOON_PY = os.path.join(ROOT, 'build', 'p2s-venv', 'bin', 'python')


def face_jobs(app, outroot_faces):
    """Faces the app has no real preview for: photo -> cartoon (tools/auto_cartoon.py in its own venv) -> post the preview and path."""
    import subprocess
    try:
        jobs = app.call('GET', '/api/worker/jobs').get('faces', [])
    except (urllib.error.URLError, OSError) as e:
        log('jobs unreachable: %r' % e)
        return 0
    n = 0
    for j in jobs:
        pid, fv, k = j['person_id'], j['face_v'], j.get('n', 1)
        if (pid, fv) in FACE_FAILED:
            continue
        os.makedirs(outroot_faces, exist_ok=True)
        base = os.path.join(outroot_faces, 'face-%d-v%d' % (pid, fv))
        try:
            open(base + '.jpg', 'wb').write(app.raw('/api/worker/face/%d/%d' % (pid, k)))
            t0 = time.time()
            r = subprocess.run([CARTOON_PY, os.path.join(HERE, 'auto_cartoon.py'), base + '.jpg', '-o', base], capture_output=True, text=True, timeout=600)
            if r.returncode or not os.path.exists(base + '.json'):
                raise RuntimeError('converter failed: %s' % (r.stderr or r.stdout)[-300:])
            js = json.load(open(base + '.json'))
            if js.get('ok') is False or not js.get('strokes'):
                raise RuntimeError('converter found no usable face: %s' % js.get('note'))
            rep = app.post_face(pid, open(base + '.png', 'rb').read(), json.dumps(js['strokes']), fv)
            log('face job: person %d v%d converted in %d s, posted: %s' % (pid, fv, time.time() - t0, rep))
            n += 1
        except Exception as e:
            FACE_FAILED.add((pid, fv))
            log('face job for person %d failed (will not retry this version): %r' % (pid, e))
    return n


# ------------------------------------------------------------------ playing files
class TableFault(Exception):
    """The table stopped a file with a fault. code: 1 arm slipped, 2 radius stall alarm, 3 arm stall alarm, 5 arm not turning. pt: points done."""
    def __init__(self, code, pt):
        super().__init__('table fault %s at point %s' % (code, pt))
        self.code, self.pt = code, pt


def rows_of(path):
    return [l.strip() for l in open(path).read().splitlines() if l.strip() and not l.lstrip().startswith('#')]


def recover_play(table, path, kind, est_s, tick, host_pause, is_paused, max_resumes=2, poll=5.0, say=None):
    """Play one file; recover from table faults instead of exiting.
      fault 2 or 3 (stall alarm: the job slows to a stop on its path and the position stays valid): log, clear the fault, upload rows[pt:]
        and play on; at most max_resumes resumes per file, then pause the app and wait for a human;
      fault 1 or 5 (arm lost steps / not turning): move nothing, pause the app and wait for a human.
    After a human un-pauses the app the table must be fault-free and homed, then the file resumes from where it stopped.
    `table` needs run_rows(lines, kind, est_s, tick) (raises TableFault), clear_fault(), healthy() -> (ok, why)."""
    say = say or log
    rows = rows_of(path)
    n = len(rows)
    start, resumes = 0, 0
    while True:
        frac0 = start / max(1, n)
        scale = (n - start) / max(1, n)
        try:
            table.run_rows(rows[start:], kind, est_s * scale, lambda f, f0=frac0, sc=scale: tick(f0 + f * sc))
            return dict(resumes=resumes)
        except TableFault as f:
            start = min(n - 1, start + max(0, f.pt))
            say('  TABLE FAULT %d at point %d of %d in %s' % (f.code, start, n, os.path.basename(path)))
            if f.code in (2, 3):
                if resumes < max_resumes:
                    resumes += 1
                    say('  stall alarm (fault %d): clearing it and resuming %s from point %d (resume %d of %d)' % (f.code, os.path.basename(path), start, resumes, max_resumes))
                    table.clear_fault()
                    ok, why = table.healthy()
                    if ok:
                        continue
                    say('  table not usable after the clear (%s)' % why)
                else:
                    say('  %d resumes used on this file: pausing the app and waiting for a human' % max_resumes)
            else:
                say('  fault %d (arm lost steps / not turning): moving NOTHING; pausing the app and waiting for a human' % f.code)
            host_pause(True)
            while True:
                while is_paused():
                    time.sleep(poll)
                ok, why = table.healthy()
                if not ok and f.code in (2, 3):
                    table.clear_fault()                      # the human wants it to go on: a stall alarm only needs clearing
                    ok, why = table.healthy()
                if ok:
                    break
                say('  app resumed but the table is not ready (%s): pausing again' % why)
                host_pause(True)
            say('  human resumed the app; table fault-free: continuing %s from point %d' % (os.path.basename(path), start))
            resumes = 0


class DryTable:
    """Pretends to be the table: sleeps a scaled estimate per file; optionally raises scripted faults (a list of codes, one per file run;
    0 = no fault) at the middle of the file, for testing recovery."""
    def __init__(self, speedup, fault_script=None):
        self.speedup = speedup
        self.script = list(fault_script or [])
        self.fault = 0
        self.runs = []

    def run_rows(self, lines, kind, est_s, tick):
        code = self.script.pop(0) if self.script else 0
        self.runs.append(len(lines))
        total = max(0.05, est_s / self.speedup)
        t0 = time.time()
        stop_at = 0.5 if code else 2.0
        while True:
            f = min(1.0, (time.time() - t0) / total)
            tick(min(f, stop_at))
            if code and f >= stop_at:
                self.fault = code
                raise TableFault(code, int(len(lines) * stop_at))
            if f >= 1.0:
                return
            time.sleep(min(0.4, total * 0.25))

    def clear_fault(self):
        self.fault = 0

    def healthy(self):
        return (self.fault == 0, 'fault %d' % self.fault if self.fault else 'ok')


class DryPlayer:
    """Contacts nothing."""
    def __init__(self, speedup, app=None, fault_script=None):
        self.table = DryTable(speedup, fault_script)
        self.app = app

    def start(self, turn_info):
        pass

    def play(self, path, kind, est_s, tick):
        hp = (lambda flag: self.app.host_pause(flag)) if self.app else (lambda flag: None)
        ip = self.app.paused if self.app else (lambda: False)
        recover_play(self.table, path, kind, est_s, tick, hp, ip, poll=0.5)

    def home(self, why):
        pass


class RealTable:
    """The 36-inch table's web interface (imports the table libraries here only)."""
    def __init__(self):
        import urllib.request as ur
        from big_lib import T, get, status
        self.T, self.get, self.status, self.ur = T, get, status, ur
        s = status()
        self.cfg = s['cfg']
        self.vdraw, self.vclear = self.cfg['vball'], self.cfg.get('vclear', 850)
        if s['job']['run'] or s['move']['run'] or s['move']['fault'] or not s['move']['arm_homed'] or not s['move']['rad_homed']:
            raise SystemExit('table not ready: %s' % s['move'])

    def healthy(self):
        s = self.status()
        m, j = s['move'], s['job']
        if m['fault']:
            return False, 'fault %s' % m['fault']
        if not m['arm_homed'] or not m['rad_homed']:
            return False, 'not homed'
        if j['run'] or m['run']:
            return False, 'still moving'
        return True, 'ok'

    def clear_fault(self):
        self.get('/fault?clear=1')

    def wait_idle(self, tick, est_s=60.0, limit=1800, paused_fn=lambda: False, held_state=None):
        t0 = time.time(); next_check = 0.0; held = False; held_s = 0.0
        while time.time() - t0 - held_s < limit:
            s = self.status()
            m, j = s['move'], s['job']
            if m['fault']:
                # a stall alarm slows the job to a stop on its path: let it finish stopping, then read how far it got
                t1 = time.time()
                while time.time() - t1 < 15:
                    s = self.status()
                    if not s['job']['run'] and not s['move']['run']:
                        break
                    time.sleep(0.3)
                raise TableFault(int(s['move']['fault']), int(s['job'].get('pt', 0)))
            if not j['run'] and not m['run'] and not s['pulse']['run'] and m.get('home', 0) != 1:
                if held:
                    self.get('/pause?on=0')
                return s
            if time.time() >= next_check:
                next_check = time.time() + 3.0
                p = paused_fn()
                if p and not held and j['run']:
                    self.get('/pause?on=1'); held = True; hold_t = time.time(); log('  app paused: table pausing on its path')
                elif not p and held:
                    self.get('/pause?on=0'); held = False; held_s += time.time() - hold_t; log('  app resumed: table continuing')
            if not held:
                tick(min(0.98, (time.time() - t0 - held_s) / est_s))
            time.sleep(0.5)
        self.get('/stop')
        raise SystemExit('timeout')

    def run_rows(self, lines, kind, est_s, tick, paused_fn=lambda: False):
        v = self.vclear if kind == 'clear' else self.vdraw
        self.get('/cfg?vball=%g' % v)
        body = ('\n'.join(lines) + '\n').encode()
        up = json.loads(self.ur.urlopen(self.ur.Request(self.T + '/thr', data=body, headers={'Content-Type': 'text/plain'}, method='POST'), timeout=60).read().decode())
        if up.get('points') != len(lines) or up.get('bad_lines') or up.get('dropped'):
            raise SystemExit('upload mismatch %s' % (up,))
        rep = self.get('/play')
        if 'playing' not in rep:
            raise SystemExit('play refused: %s' % rep)
        self.wait_idle(tick, est_s=est_s * 2, paused_fn=paused_fn)
        tick(1.0)


class RealPlayer:
    """Same logic as tools/sand_swap_run.py, one file at a time, with fault recovery (recover_play)."""
    def __init__(self, app):
        self.app = app
        self.table = RealTable()
        self.vdraw = self.table.vdraw
        self.get = self.table.get

    def start(self, turn_info):
        pass

    def home(self, why):
        for cmd in ('/homearm', '/homeradius'):
            self.get(cmd, timeout=90)
            self.table.wait_idle(lambda f: None, 180)

    def play(self, path, kind, est_s, tick):
        if self.app.paused():
            log('  app paused: waiting before the next file')
            while self.app.paused():
                time.sleep(3)
            log('  app resumed')
        pf = self.app.paused
        tbl = self.table
        wrapper = type('T', (), dict(run_rows=lambda _s, lines, k, e, tk: tbl.run_rows(lines, k, e, tk, paused_fn=pf), clear_fault=tbl.clear_fault, healthy=tbl.healthy))()
        recover_play(wrapper, path, kind, est_s, tick, self.app.host_pause, self.app.paused)

    def finish(self):
        self.get('/cfg?vball=%g' % self.vdraw)


def file_kind(name):
    return 'clear' if name.startswith('2') else 'draw'


# ------------------------------------------------------------------ one turn
# ------------------------------------------------------------------ prebuild: the next turn's files are made while this one plays
LOCK_FD = None
PRE = dict(proc=None, key=None, inp=None, started=0.0)
LAST_END = [None]
FACE_WAIT = {}                                            # (person_id, face_v) -> when the wait began (-1 once given up)


def _last_row(path):
    with open(path) as f:
        rows = [l for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith('#')]
    return rows[-1].strip() if rows else ''


def make_inputs(cur, holds, dirs, start_file):
    """Everything that decides what a turn's files look like, and a key over all of it."""
    import hashlib
    zone, kind = cur['zone'], cur['kind']
    turn = cur.get('turn')
    # Bill, 2026-11-26: the centre ALWAYS clears inward (outward thinned the middle), and so do the 4 inner-ring slices around it
    # ("erases of non-pie zones erase inward as well as the center zone"); the 6 outer slices keep alternating in/out
    clear_dir = 'in' if (zone == 'centre' or zone.startswith('inner')) else ('out' if dirs.get(zone) == 'in' else 'in')
    blank = kind == 'draw' and zone not in holds          # nothing drawn here since the last whole-table clear: don't re-clear it
    ints = [i for i in cur.get('interests', []) if i.get('status') == 'ready' and strokes_of(i.get('strokes'))][:3]
    interests = [strokes_of(i.get('strokes')) for i in cur.get('interests', []) if i.get('status') == 'ready' and strokes_of(i.get('strokes'))]
    centre_art = [i.get('strokes') or [] for i in cur['centre_art']] if cur.get('centre_art') is not None else ([] if 'centre_art' in cur else None)
    face_path = None
    if kind == 'draw':
        fs = cur.get('face_strokes') or []
        face_path = (fs[0] if fs else None) or cur.get('face_path')      # Bill chose the app's face style (2026-11-25): server strokes > a posted path > cartoon by name > none
    parts = dict(zone=zone, kind=kind, person_id=cur.get('person_id'), name=cur.get('name'), face=face_path,
                 interests=[(i.get('id'), i.get('v'), strokes_of(i.get('strokes'))) for i in ints],
                 centre_art=(None if 'centre_art' not in cur else [(i.get('key'), i.get('strokes')) for i in (cur.get('centre_art') or [])]),
                 turn=turn, face_v=cur.get('face_v'), start=_last_row(start_file), blank=blank, clear_dir=clear_dir)
    key = hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:20]
    return dict(zone=zone, kind=kind, turn=turn, clear_dir=clear_dir, blank=blank, interests=interests, centre_art=centre_art, face_path=face_path,
                name=cur.get('name') or '', key=key, parts=parts, start_file=start_file)


# The guest's "light color" from the app (sand-app/static/app.js COLORS, same order), as LED-friendly colours: the app's
# swatches are muted screen colours that look washed out on LEDs. None ("Any") = the table's usual warm white.
LIGHT_RGB = [(255, 90, 20), (255, 170, 0), (40, 200, 50), (40, 140, 255), (150, 60, 255), (255, 60, 120), (255, 200, 140), (0, 200, 170)]
LIGHT_NAMES = ['Sunset', 'Gold', 'Leaf green', 'Sky', 'Violet', 'Rose', 'Warm white', 'Teal']


def set_lights(color):
    """Bill, 2026-11-26: the LEDs take the featured (centre) guest's colour and spin slowly (firmware 2.9 /ledfx: a 45% glow with
    a soft brighter band turning once every 40 s, colour changes easing over ~3 s). Never fatal."""
    try:
        from big_lib import get
        rgb = LIGHT_RGB[color] if isinstance(color, int) and 0 <= color < len(LIGHT_RGB) else (255, 244, 229)
        r = get('/ledfx?mode=spin&pin=38&n=157&r=%d&g=%d&b=%d&period=40&base=0.45&width=0.35' % rgb)
        if 'spin' not in str(r):                                   # firmware before 2.9: a plain steady colour
            get('/led?pin=38&n=157&r=%d&g=%d&b=%d&i=0&k=157' % rgb)
        log('  lights: %s %s' % (LIGHT_NAMES[color] if isinstance(color, int) and 0 <= color < len(LIGHT_NAMES) else 'warm white (no colour picked)', rgb))
    except Exception as e:
        log('  lights not set (%r)' % (e,))


def groove_face(inp, cur, app, outroot):
    """Bill, 2026-11-26 ("make them the ones that get used"): faces from the app's photo are redrawn for the real ~10 mm line
    (tools/face_small.py, routed by tools/face_route.py). Any failure keeps the app's own face. Touch
    captures/sand-app/faces-app-style to go back to the app's faces without a restart."""
    if os.path.exists(os.path.join(CAP, 'faces-app-style')):
        return inp
    try:
        import face_small
        return face_small.groove_inputs(inp, cur, app, outroot, log)
    except Exception as e:
        log('  groove face skipped (%r); keeping the app face' % (e,))
        return inp


def build_with_fallback(inp, out, world, tag=''):
    """The layout attempts (as asked, other seed, no face, name and one picture); returns the build dict or None."""
    import sand_turn as t
    kind, interests, face_path = inp['kind'], inp['interests'], inp['face_path']
    attempts = [(5, face_path, interests[:3], 'as asked'), (11, face_path, interests[:3], 'other layout seed'),
                (5, False, interests[:3], 'without the face'), (5, False, interests[:1], 'name and one picture')] if kind == 'draw' else [(5, None, [], 'clear')]
    t0 = time.time()
    for seed, fp, ints, why in attempts:
        try:
            b = t.build_turn(inp['zone'], kind, inp['name'], fp or None, ints, inp['start_file'], inp['clear_dir'], out, world=world, seed=seed,
                             allow_cartoon=fp is not False, turn=inp['turn'], centre_art=inp['centre_art'], skip_clear=inp['blank'],
                             face_route=bool(inp.get('face_route')) and fp is not False)
        except Exception as e:
            log('  %sbuild failed (%s): %r' % (tag, why, e))
            continue
        c = b['checks']
        log('  %sbuilt (%s) in %d s: %s; estimated %d s on the table; face=%s pictures=%d overlap=%s outside=%s' % (
            tag, why, time.time() - t0, ', '.join(b['progress']['files']), b['est_total_seconds'], b['face_source'], b['pictures'],
            c['overlap_violations'], c['touched_outside_zone_and_boundary_lines']))
        if not c['overlap_violations'] and not c['touched_outside_zone_and_boundary_lines']:
            return b
        log('  %schecks failed: %s' % (tag, c['overlap_violation_list']))
    return None


def cache_dir(outroot, key):
    return os.path.join(outroot, 'cache', key)


def load_cache(outroot, key):
    f = os.path.join(cache_dir(outroot, key), 'build.pkl')
    if os.path.exists(f):
        try:
            return pickle.load(open(f, 'rb'))
        except Exception as e:
            log('  cache entry unreadable (%r)' % (e,))
    return None


def _prebuild_child(outroot, inp, world):
    if LOCK_FD is not None:
        try:
            os.close(LOCK_FD.fileno())               # the child must not keep the driver lock alive
        except OSError:
            pass
    try:
        os.nice(10)                                        # never compete with the playback loop
    except OSError:
        pass
    d = cache_dir(outroot, inp['key'])
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    b = build_with_fallback(inp, d, world, tag='prebuild: ')
    if b is None:
        log('  prebuild: no layout for turn %s %s; it will be built when it comes up' % (inp['turn'], inp['zone']))
        os._exit(0)
    tmp = os.path.join(d, 'build.pkl.tmp')
    pickle.dump(b, open(tmp, 'wb'))
    os.replace(tmp, os.path.join(d, 'build.pkl'))
    log('  prebuild: turn %s %s ready in the cache after %d s (key %s)' % (inp['turn'], inp['zone'], time.time() - t0, inp['key'][:8]))
    os._exit(0)


def start_prebuild(app, cur, inp, b, st, outroot):
    """Called when playback of the current turn starts: build what the plan says comes next, from where this turn will leave the ball."""
    import multiprocessing
    try:
        nxt = (app.plan() or {}).get('next')
    except Exception as e:
        log('  prebuild skipped (plan unreadable: %r)' % (e,))
        return
    if not nxt or not nxt.get('zone') or not nxt.get('kind'):
        log('  prebuild skipped (the plan has no next turn)')
        return
    holds = dict(st.d['holds'])
    holds[inp['zone']] = dict(person_id=cur.get('person_id') if inp['kind'] == 'draw' else None)
    dirs = dict(st.d['dirs'])
    if not inp['blank']:
        dirs[inp['zone']] = b.get('clear_dir') or inp['clear_dir']
    nxt = dict(nxt)
    nxt.setdefault('turn', (cur.get('turn') or 0) + 1)
    inp2 = make_inputs(nxt, holds, dirs, b['last_file'])
    inp2 = groove_face(inp2, nxt, app, outroot)
    if os.path.exists(os.path.join(cache_dir(outroot, inp2['key']), 'build.pkl')):
        return
    world = b['world']
    p = multiprocessing.get_context('fork').Process(target=_prebuild_child, args=(outroot, inp2, world), daemon=True)
    p.start()
    PRE.update(proc=p, key=inp2['key'], inp=inp2['parts'], started=time.time())
    log('  prebuild started for the next turn: %s %s %s (key %s)' % (inp2['kind'], inp2['zone'], inp2['name'], inp2['key'][:8]))


def reap_prebuild(want_key):
    """Before a turn is built or fetched: wait for a prebuild that is for this very turn; drop one that is for another."""
    p = PRE.get('proc')
    if p is None:
        return
    if p.is_alive():
        if PRE['key'] == want_key:
            log('  waiting for the prebuild of this turn to finish')
            p.join()
        else:
            log('  prebuild was for a different turn: dropped')
            p.terminate()
            p.join()
    else:
        p.join()


def why_miss(inp):
    old = PRE.get('inp')
    if old is None:
        return 'no prebuild was started'
    diff = [k for k in inp['parts'] if inp['parts'][k] != old.get(k)]
    return 'changed since the prebuild: ' + ', '.join(diff) if diff else 'prebuild did not finish'


def trim_cache(outroot, keep=8):
    d = os.path.join(outroot, 'cache')
    if not os.path.isdir(d):
        return
    items = sorted((os.path.getmtime(os.path.join(d, x)), x) for x in os.listdir(d))
    for _, x in items[:-keep]:
        import shutil
        shutil.rmtree(os.path.join(d, x), ignore_errors=True)


def run_turn(app, cur, st, player, args, outroot, all_state):
    import sand_zone_swap as sz
    import sand_turn as t
    zone, kind, turn = cur['zone'], cur['kind'], cur['turn']
    out = os.path.join(outroot, 'turn-%04d-%s' % (turn, zone))
    os.makedirs(out, exist_ok=True)
    start_file = st.d['last_file']
    if not start_file or not os.path.exists(start_file):
        start_file = None
        if getattr(args, 'real', False):
            # 2026-11-25: the last file had been deleted with the build cache and the driver planned turn 209 from revision 3's end
            # (the outer arc) while the ball sat on the centre circle; stopped before it moved. Read the ball from the table instead.
            try:
                from big_lib import status
                s = status(); m, c = s['move'], s['cfg']
                if not m['run'] and not s['job']['run'] and m['arm_homed'] and m['rad_homed']:
                    th = (m['a'] / (c.get('thsign', -1) * 38400 / (2 * math.pi)) - c.get('th0', 0.0)) % (2 * math.pi)
                    rho = m['carriage'] / float(c['rmax'])
                    start_file = os.path.join(outroot, 'start-from-table-before-turn-%04d.thr' % turn)
                    open(start_file, 'w').write('%.5f %.5f\n' % (th, rho))
                    log('no usable last file; read the ball position from the table: %.1f deg, %.1f mm' % (math.degrees(th), m['carriage'] / 160.0))
            except Exception as e:
                log('no usable last file, and the table position could not be read: %r' % (e,))
        if start_file is None:
            start_file = os.path.join(sz.REV3, '19-frame-lines.thr')
            log('no usable last file; assuming the ball is where revision 3 ended (frame lines)')
    recov = None
    if st.d.get('recover_zone'):
        recov = recovery_file(sz, start_file, st.d['recover_zone'], st, os.path.join(outroot, 'recover-before-turn-%04d.thr' % turn))
        if recov:
            log('ball stopped off the frame lines in %s: recovery line written' % st.d['recover_zone'])
            start_file = recov
    if recov is None and not st.d.get('recover_zone'):
        zoff = off_frame_zone(sz, start_file)
        if zoff:
            recov = recovery_file(sz, start_file, zoff, st, os.path.join(outroot, 'recover-before-turn-%04d.thr' % turn))
            if recov:
                log('ball is off the frame lines (in %s): a short straight move to the nearest frame point comes first' % zoff)
                start_file = recov
    inp = make_inputs(cur, st.d['holds'], st.d['dirs'], start_file)
    inp = groove_face(inp, cur, app, outroot)
    clear_dir, blank = inp['clear_dir'], inp['blank']
    t0 = time.time()
    log('turn %d: %s %s %s, clear %s' % (turn, kind, zone, cur.get('name'), 'skipped (zone already blank)' if blank else clear_dir))
    reap_prebuild(inp['key'])
    b = None if args.no_prebuild else load_cache(outroot, inp['key'])
    if b is not None:
        log('  cache hit (key %s): files ready in %.1f s' % (inp['key'][:8], time.time() - t0))
    else:
        if not args.no_prebuild:
            log('  cache miss: %s; building files' % why_miss(inp))
        b = build_with_fallback(inp, out, st.world())
    PRE.update(proc=None, key=None, inp=None)
    if b is None:
        raise SystemExit('no layout passed the checks for turn %d; not playing' % turn)
    build_wait = time.time() - t0
    try:
        dp = drawn_payload(b, kind, turn, zone)
        rep = app.post_drawn(turn, zone, dp['strokes'])
        log('  posted drawn strokes: %d polylines, %d points: %s' % (len(dp['strokes']), sum(len(x) for x in dp['strokes']), rep))
    except Exception as e:
        log('  drawn strokes not posted (continuing): %r' % (e,))
    files = list(zip(b['file_paths'], b['progress']['files']))
    knots = b['progress']['knots']
    state = dict(stale=False, pct=0, last_post=0.0)

    def post(pct, done=False, force=False):
        if state['stale']:
            return False
        if not force and not done and time.time() - state['last_post'] < 0.8 and abs(pct - state['pct']) < 4:
            return True
        r = app.progress(turn, pct, done)
        state['last_post'], state['pct'] = time.time(), pct
        if not r.get('accepted', True):
            state['stale'] = True
            log('  turn %d is stale in the app (skipped or removed): finishing the current file, then moving on' % turn)
            return False
        return True

    post(0, force=True)
    gap = (time.time() - LAST_END[0]) if LAST_END[0] else None
    log('  playback starts: %s between turns (waited %.1f s for files)' % ('%.1f s' % gap if gap is not None else 'first turn', build_wait))
    if args.real and kind == 'draw' and zone == 'centre':
        set_lights(cur.get('color'))
    if not args.no_prebuild:
        try:
            start_prebuild(app, cur, inp, b, st, outroot)
        except Exception as e:
            log('  prebuild not started (%r)' % (e,))
    played = 0
    if recov and not state['stale']:
        player.play(recov, 'draw', 3.0, lambda f: True)
    last_done = None
    for i, (path, name) in enumerate(files):
        if state['stale']:
            break
        if kind == 'draw' and zone == 'centre' and name.startswith('2b') and args.real and args.home_at_centre:
            player.home('before the centre spiral')
        est = b['est_seconds'][name]
        player.play(path, file_kind(name), est, lambda f, i=i: post(t.percent_at(knots, i + f)))
        last_done = (i, name)
        log('  file %s done (%s)' % (name, 'stale' if state['stale'] else '%d%%' % t.percent_at(knots, i + 1)))
        if not state['stale'] and i < len(files) - 1 and erase_requested(app):
            state['stale'] = True
            log('  the host asked for a whole-table erase: this turn stops here (after %s)' % name)
    if hasattr(player, 'finish'):
        player.finish()
    # ---- bookkeeping
    if state['stale']:
        i, name = last_done if last_done else (None, None)
        st.d['last_file'] = files[i][0] if last_done else st.d['last_file']
        clear_started = last_done is not None and i >= 1
        on_frame = last_done is None or name.startswith('1') or name.startswith('3') or (name.startswith('4') and i == len(files) - 1)
        st.d['recover_zone'] = None if on_frame else zone
        if clear_started:
            st.d['holds'][zone] = dict(person_id=None, name=None, dirty=True, note='turn %d interrupted' % turn)
        st.d['history'].append(dict(turn=turn, zone=zone, result='stale after %s' % (name,), at=now()))
        st.save()
        return 'stale', b
    r = app.progress_final(turn)
    LAST_END[0] = time.time()
    st.d['last_file'] = b['last_file']
    st.d['recover_zone'] = None
    if not blank:
        st.d['dirs'][zone] = b.get('clear_dir') or clear_dir      # what was really done (the centre can fall back to out); a skipped clear does not count toward the in/out alternation
    st.d['holds'][zone] = dict(person_id=cur.get('person_id'), name=cur.get('name'), dirty=False, face=b['face_source'], pictures=b['pictures'], turn=turn) if kind == 'draw' \
        else dict(person_id=None, name=None, dirty=False)
    st.set_world(b['world'])
    layers = [L for L in st.layers() if L['zone_name'] != zone] + [b['zone_layer']]
    st.set_layers(layers)
    st.d['turns_done'] += 1
    st.d['history'].append(dict(turn=turn, zone=zone, result='done' if r.get('accepted', True) else 'done but not accepted', est_seconds=b['est_total_seconds'], at=now()))
    img = t.preview_image(layers)
    img.save(os.path.join(out, 'preview.png'))
    pv = os.path.join(outroot, 'previews')
    os.makedirs(pv, exist_ok=True)
    img.save(os.path.join(pv, 'turn-%04d-%s.png' % (turn, zone)))
    st.save()
    return 'done', b


# ------------------------------------------------------------------ host-requested whole-table erase (app contract, 2026-11-26)
def erase_requested(app):
    """True if the app has a whole-table erase waiting or running (checked after every file, so the ball finishes its file)."""
    try:
        e = app.plan().get('erase')
    except Exception:
        return False
    return bool(e and e.get('status') in ('waiting', 'running'))


def _table_wait_idle(status, limit=1800):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            s = status()
            if not s['move']['run'] and not s['job']['run'] and not s['pulse']['run'] and s['move'].get('home', 0) != 1:
                return s
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit('the table was still busy after %d s' % limit)


def do_erase(app, st, er, args, outroot):
    """Bill asked (via the app, 2026-11-26) for host buttons to erase the whole table spiral in or spiral out.
    App contract: plan['erase'] = {id, dir in|out, status waiting|running}. waiting -> POST /api/worker/erase {id, status: running}
    (accepted false = the host cancelled: carry on); then the usual full-reach whole-table clear in that direction
    (tools/big_full_clear.py, which also records the direction for the in/out alternation), park on the centre circle's edge at
    0 degrees, forget what the zones held, POST /api/worker/reset (empties the zones, clears the request, rotation restarts from
    the centre). Found already 'running' (the driver restarted during it): erase again. Host pause holds the ball on its path.
    A stall alarm gets one automatic retry; any other failure sets the host pause and waits for a human, then erases again."""
    import subprocess
    eid, d = er.get('id'), er.get('dir')
    if d not in ('in', 'out'):
        log('erase request %r has no usable direction; ignoring it' % (er,))
        time.sleep(args.poll)
        return
    if er.get('status') == 'waiting':
        try:
            r = app.call('POST', '/api/worker/erase', dict(id=eid, status='running'))
        except Exception as e:
            log('erase %s: could not mark it running (%r); trying again shortly' % (eid, e))
            time.sleep(args.poll)
            return
        if not (r or {}).get('accepted'):
            log('erase %s: the host cancelled it before it started; carrying on' % eid)
            return
    else:
        log('erase %s was already marked running (the driver restarted during it): erasing again' % eid)
    words = 'spiral in (rim to middle)' if d == 'in' else 'spiral out (middle to rim)'
    start_file = os.path.join(outroot, 'start.thr')
    if args.real:
        from big_lib import status, get
        tries = 0
        while True:
            s = _table_wait_idle(status)
            m = s['move']
            if m['fault'] in (2, 3):
                get('/fault?clear=1')
                s = status(); m = s['move']
            if m['fault'] or not m['arm_homed'] or not m['rad_homed']:
                log('erase %s: the table is not ready (fault %s, homed %s/%s): pausing the app and waiting for a human' % (eid, m['fault'], m['arm_homed'], m['rad_homed']))
                app.host_pause(True)
                while app.paused():
                    time.sleep(args.poll)
                continue
            log('erase %s: whole-table erase, %s, starting' % (eid, words))
            t0 = time.time()
            elog = open(os.path.join(CAP, 'erase-%s.log' % eid), 'a')
            proc = subprocess.Popen(['python3', '-u', os.path.join(HERE, 'big_full_clear.py'), '--dir', d], cwd=ROOT, stdout=elog, stderr=subprocess.STDOUT)
            held = False
            while proc.poll() is None:                     # the host's Pause holds the ball on its path (the job watcher ignores a paused job)
                p = app.paused()
                try:
                    j = status()['job']
                    if p and j['run'] and not j['paused']:  # also re-sent when a new job (the spiral after the move) starts unpaused
                        get('/pause?on=1')
                        if not held:
                            log('erase %s: app paused: the ball holds on its path' % eid)
                        held = True
                    elif not p and held:
                        get('/pause?on=0'); held = False; log('erase %s: app resumed: erasing on' % eid)
                except Exception as e:
                    log('erase %s: pause check failed (%r)' % (eid, e))
                time.sleep(3)
            if held:
                get('/pause?on=0')
            elog.close()
            tail = ' | '.join(open(os.path.join(CAP, 'erase-%s.log' % eid)).read().strip().splitlines()[-2:])
            if proc.returncode == 0:
                log('erase %s: done in %.1f min (%s)' % (eid, (time.time() - t0) / 60, tail))
                break
            tries += 1
            s = _table_wait_idle(status); m = s['move']
            log('erase %s: the erase stopped (exit %d, fault %s): %s' % (eid, proc.returncode, m['fault'], tail))
            if m['fault'] in (2, 3) and tries < 2:
                log('erase %s: stall alarm: clearing it and erasing again' % eid)
                continue
            log('erase %s: pausing the app and waiting for a human; it erases again after the un-pause' % eid)
            app.host_pause(True)
            while app.paused():
                time.sleep(args.poll)
            tries = 0
        # park on the centre circle's edge at 0 degrees: round at the present radius to 0 degrees, then along the 0-degree slice
        # line (a frame line in both rings), so nothing is dragged across the fresh sand but frame lines
        s = status()
        rho = s['move']['carriage'] / float(s['cfg']['rmax'])
        get('/goto?th=0&rho=%.5f' % max(rho, 0.0134)); _table_wait_idle(status, 120)
        get('/goto?th=0&rho=0.29588'); s = _table_wait_idle(status, 120)
        log('erase %s: parked on the centre circle at 0 degrees (carriage %d)' % (eid, s['move']['carriage']))
    else:
        log('erase %s: dry run, pretending to erase (%s)' % (eid, words))
    open(start_file, 'w').write('0.00000 0.29588\n0.00000 0.29588\n')
    st.d['holds'] = {}
    st.d['recover_zone'] = None
    st.d['last_file'] = start_file
    st.d['history'].append(dict(turn=None, zone='all', result='host erase %s (%s)' % (eid, d), at=now()))
    for f in (st.world_path, st.layers_path):
        if os.path.exists(f):
            os.remove(f)
    st.save()
    LAST_END[0] = None
    while True:
        try:
            r = app.call('POST', '/api/worker/reset')
            log('erase %s: app reset: the rotation starts again from the centre' % eid)
            return
        except Exception as e:
            log('erase %s: app reset failed (%r); retrying' % (eid, e))
            time.sleep(args.poll)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', default='http://127.0.0.1:8791')
    ap.add_argument('--token', default=os.environ.get('SAND_WORKER_TOKEN'))
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--dry-run', action='store_true', help='default: never contact the table')
    g.add_argument('--real', action='store_true', help='drive the table (local app only unless --allow-live)')
    ap.add_argument('--allow-live', action='store_true', help='permit --real against a non-local app (only when Bill says so)')
    ap.add_argument('--once', action='store_true', help='play one turn and stop')
    ap.add_argument('--max-turns', type=int, default=0)
    ap.add_argument('--speedup', type=float, default=60.0, help='dry-run: seconds of table time per second of waiting')
    ap.add_argument('--poll', type=float, default=5.0)
    ap.add_argument('--state', default=None)
    ap.add_argument('--start-file', default=None, help='file whose last row is where the ball is (default: end of revision 3)')
    ap.add_argument('--home-at-centre', action='store_true', help='re-home arm and radius at the centre during centre turns (off: the centre touch failed from far out on 2026-11-25 and pushed into the stop)')
    ap.add_argument('--sim-faults', default=None, help='dry-run: comma list of fault codes, one per file played (0 = none), to test recovery')
    ap.add_argument('--lock-file', default=None, help='exclusive lock (default captures/sand-app/driver.lock real, driver-dryrun.lock dry-run)')
    ap.add_argument('--no-prebuild', action='store_true', help='do not build the next turn while this one plays')
    ap.add_argument('--stop-file', default=None, help='if this file exists when a turn ends, delete it and exit 0 (default: captures/sand-app/driver.stop)')
    ap.add_argument('--face-jobs', action='store_true', help='post our own cartoon faces (off: Bill chose the app style on 2026-11-25)')
    args = ap.parse_args()
    args.real = bool(args.real)
    if not args.token:
        raise SystemExit('need --token or SAND_WORKER_TOKEN')
    host = urllib.parse.urlparse(args.base).hostname
    if args.real and host not in ('127.0.0.1', 'localhost') and not args.allow_live:
        raise SystemExit('refusing --real against %s: only a local app is allowed until Bill enables the live site (--allow-live)' % host)
    global LOCK_FD
    lock_path = args.lock_file or os.path.join(CAP, 'driver.lock' if args.real else 'driver-dryrun.lock')
    LOCK_FD = open(lock_path, 'a+')
    try:
        fcntl.flock(LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('another driver is already running (it holds %s): this one is exiting' % lock_path, flush=True)
        sys.exit(3)
    LOCK_FD.seek(0); LOCK_FD.truncate(); LOCK_FD.write('%d\n' % os.getpid()); LOCK_FD.flush()
    import sand_zone_swap as sz
    mode = 'real' if args.real else 'dryrun'
    sfile = args.state or os.path.join(CAP, 'driver-state.json' if args.real else 'driver-state-dryrun.json')
    outroot = os.path.join(CAP, 'driver' if args.real else 'driver-dryrun')
    st = State(sfile, args.start_file or os.path.join(sz.REV3, '19-frame-lines.thr'))
    if args.start_file:
        st.d['last_file'] = args.start_file
    app = App(args.base, args.token)
    player = RealPlayer(app) if args.real else DryPlayer(args.speedup, app, [int(x) for x in args.sim_faults.split(',') if x] if args.sim_faults else None)
    log('driver started: %s mode, app %s, state %s' % (mode, args.base, sfile))
    n = 0
    was_paused = False
    while True:
        if args.face_jobs:
            face_jobs(app, os.path.join(CAP, 'driver-faces'))
        try:
            plan = app.plan()
        except Exception as e:
            log('app unreachable (%s); retrying' % e)
            time.sleep(args.poll)
            continue
        if (plan.get('state') or {}).get('paused'):
            if not was_paused:
                log('app paused: no new turn until it is resumed')
            was_paused = True
            time.sleep(args.poll)
            continue
        if was_paused:
            log('app resumed')
            was_paused = False
        er = plan.get('erase')
        if er and er.get('status') in ('waiting', 'running'):
            do_erase(app, st, er, args, outroot)
            continue
        cur = plan.get('current')
        if not cur:
            if args.once:
                log('nothing to do')
                return
            time.sleep(args.poll)
            continue
        # the app draws faces in the background (2026-11-26): a person can be current while their face is still being made
        # (face_pending, or faces >= 1 with no strokes yet; usually 2-5 s, pets up to a minute). Wait once per face version.
        if cur.get('kind') == 'draw' and (cur.get('face_pending') or ((cur.get('faces') or 0) >= 1 and not (cur.get('face_strokes') or []))):
            fk = (cur.get('person_id'), cur.get('face_v'))
            if fk not in FACE_WAIT:
                FACE_WAIT[fk] = time.time()
                log("turn %s: %s's face is still being made; waiting up to 90 s" % (cur.get('turn'), cur.get('name')))
            if time.time() - FACE_WAIT[fk] < 90:
                time.sleep(3)
                continue
            if FACE_WAIT[fk] > 0:
                log('  the face is still not ready after 90 s; drawing without it')
                FACE_WAIT[fk] = -1.0
        res, b = run_turn(app, cur, st, player, args, outroot, mode)
        n += 1
        try:
            trim_cache(outroot)
        except OSError:
            pass
        stop = args.stop_file or os.path.join(CAP, 'driver.stop')
        if os.path.exists(stop):
            os.remove(stop)
            p = PRE.get('proc')
            if p is not None and p.is_alive():
                p.terminate()
            log('stop file: exiting after turn %d' % cur['turn'])
            sys.exit(0)
        if (args.once and res == 'done') or (args.max_turns and n >= args.max_turns):
            log('stopping after %d turn(s)' % n)
            return


if __name__ == '__main__':
    main()
