"""sand-app backend: FastAPI + SQLite. Contract is in sand-app/API.md."""
import hashlib
import hmac
import io
import json
import logging
import math
import os
import random
import re
import sqlite3
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
import numpy as np
from PIL import Image, ImageOps

from . import icons as icons_mod
try:                                    # needs mediapipe + opencv; the app still runs without them
    from . import face_art
except Exception:                       # pragma: no cover
    face_art = None
from . import render
from . import scheduler as S
from . import themes as themes_mod

log = logging.getLogger('sand.app')

BASE = Path(__file__).resolve().parent.parent
MAX_PEOPLE = 300
MAX_INTERESTS = 60
MAX_BODY = 20 * 1024 * 1024
MAX_FACE_BYTES = 8 * 1024 * 1024
FACE_LINE_FRAC = 0.02          # groove width for face previews (finer than icons: more lines to fit)
PHOTO_LINE_FRAC = 0.028        # groove width for photo-subject drawings (about 25 strokes, bolder than a landmark face)
PHOTO_WAIT_SECONDS = 60        # the upload never waits longer than this for the photo drawing, then the sketch
MAX_STROKES = 40
MAX_POINTS = 4000
MAX_LABEL_PARTS = 20
MAX_LABEL_ENTRY = 400
MAX_ART_ITEMS = 40
ART_PER_TURN = 2
ART_KEY = re.compile(r'^[a-z0-9-]{1,40}$')
DRAWN_MAX_POINTS = 60000
DRAWN_MAX_STROKES = 2000
DRAWN_LIMIT = 1.05
TABLE_SIZE = 1000

Image.MAX_IMAGE_PIXELS = 60_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  joined INTEGER NOT NULL DEFAULT 0,
  color INTEGER,
  faces INTEGER NOT NULL DEFAULT 0,
  face_v INTEGER NOT NULL DEFAULT 0,
  preview_v INTEGER,
  face_path TEXT
);
CREATE TABLE IF NOT EXISTS interests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  label TEXT NOT NULL,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  strokes TEXT,
  v INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS interests_person ON interests(person_id);
CREATE TABLE IF NOT EXISTS sched (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS centre_art (
  key TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  strokes TEXT NOT NULL,
  pos INTEGER NOT NULL,
  v INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS centre_art_pref (key TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS label_themes (
  key TEXT PRIMARY KEY, themes TEXT NOT NULL, created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS drawn (
  zone TEXT PRIMARY KEY,
  turn INTEGER NOT NULL,
  person_id INTEGER,
  strokes BLOB NOT NULL,
  posted INTEGER NOT NULL,
  rev INTEGER NOT NULL
);
"""


class ApiError(Exception):
    def __init__(self, status, error, **extra):
        self.status, self.body = status, dict(extra, error=error)


_CTRL = re.compile(r'[\x00-\x1f\x7f]')


def clean_text(s, lo, hi, what):
    if not isinstance(s, str):
        raise ApiError(400, what)
    s = _CTRL.sub(' ', s).strip()
    s = re.sub(r'\s+', ' ', s)
    if not (lo <= len(s) <= hi):
        raise ApiError(400, what)
    return s


_SPLIT = re.compile(r'[,;\n\r]+')


def split_labels(text, have=()):
    """One typed entry -> separate interest labels. Splits on commas, semicolons and line breaks only (never on
    "and" or spaces), trims, drops empties and case-insensitive duplicates (also of `have`). Each part must be
    1-40 characters."""
    if not isinstance(text, str) or len(text) > MAX_LABEL_ENTRY:
        raise ApiError(400, 'bad_label')
    seen = {h.casefold() for h in have}
    out = []
    for part in _SPLIT.split(text):
        part = re.sub(r'\s+', ' ', _CTRL.sub(' ', part)).strip()
        if not part:
            continue
        if len(part) > 40:
            raise ApiError(400, 'bad_label')
        if part.casefold() in seen:
            continue
        seen.add(part.casefold())
        out.append(part)
    if len(out) > MAX_LABEL_PARTS:
        raise ApiError(400, 'bad_label')
    return out


def clean_strokes(obj):
    """Accepts the list of strokes, or {"strokes": [...]}. Clamps to 0..1; raises 400 on anything else."""
    if isinstance(obj, dict):
        obj = obj.get('strokes')
    if not isinstance(obj, list) or not obj or len(obj) > MAX_STROKES:
        raise ApiError(400, 'bad_strokes')
    out, total = [], 0
    for s in obj:
        if not isinstance(s, list) or not s:
            raise ApiError(400, 'bad_strokes')
        pts = []
        for p in s:
            if (not isinstance(p, (list, tuple)) or len(p) != 2
                    or any(isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c) for c in p)):
                raise ApiError(400, 'bad_strokes')
            pts.append([round(min(1.0, max(0.0, float(p[0]))), 4), round(min(1.0, max(0.0, float(p[1]))), 4)])
        total += len(pts)
        if total > MAX_POINTS:
            raise ApiError(400, 'bad_strokes')
        out.append(pts)
    return out


def clean_drawn_strokes(obj):
    """Strokes the table really left in a zone, table frame (x, y in -1.05..1.05, y up). At most 2000 strokes and
    60000 points. An empty list is fine (nothing is left visible). Rounded to 4 decimals."""
    if not isinstance(obj, list) or len(obj) > DRAWN_MAX_STROKES:
        raise ApiError(400, 'bad_strokes')
    out, total = [], 0
    for s in obj:
        if not isinstance(s, list) or not s:
            raise ApiError(400, 'bad_strokes')
        total += len(s)
        if total > DRAWN_MAX_POINTS:
            raise ApiError(400, 'bad_strokes')
        try:
            a = np.array(s)
        except Exception:
            raise ApiError(400, 'bad_strokes')
        if a.ndim != 2 or a.shape[1] != 2 or a.dtype.kind not in 'if' or not np.isfinite(a).all() \
                or np.abs(a).max() > DRAWN_LIMIT:
            raise ApiError(400, 'bad_strokes')
        out.append(np.round(a.astype(np.float64), 4).tolist())
    return out


def clean_art_items(items):
    """The driver's Thanksgiving picture set: [{"key", "label", "strokes"}], order kept."""
    if not isinstance(items, list) or len(items) > MAX_ART_ITEMS:
        raise ApiError(400, 'bad_items')
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(400, 'bad_items')
        key = it.get('key')
        if not isinstance(key, str) or not ART_KEY.match(key) or key in seen:
            raise ApiError(400, 'bad_key')
        seen.add(key)
        out.append({'key': key, 'label': clean_text(it.get('label'), 1, 40, 'bad_label'),
                    'strokes': clean_strokes(it.get('strokes'))})
    return out


def clean_image(raw):
    """Verify, apply EXIF orientation, long side <= 1024, re-encode JPEG. Raises 400 for non-images."""
    try:
        im = Image.open(io.BytesIO(raw))
        im.verify()
        im = Image.open(io.BytesIO(raw))
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ('RGBA', 'LA', 'P'):
            im = im.convert('RGBA')
            bg = Image.new('RGB', im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3])
            im = bg
        else:
            im = im.convert('RGB')
        im.thumbnail((1024, 1024), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, 'JPEG', quality=88)
        return out.getvalue()
    except ApiError:
        raise
    except Exception:
        raise ApiError(400, 'not_an_image')


def create_app(data_dir=None, token=None, clock=None, icon_gen=None, start_icons=True, photo_gen=None,
               photo_wait=PHOTO_WAIT_SECONDS, theme_gen=None, face_sync=None):
    data = Path(data_dir or os.environ.get('SAND_DATA') or './data').resolve()
    token = os.environ.get('SAND_WORKER_TOKEN') if token is None else token
    clock = clock or time.time
    faces_dir = data / 'faces'
    faces_dir.mkdir(parents=True, exist_ok=True)
    db_path = data / 'sand.db'
    static_dir = BASE / 'static'
    lock = threading.RLock()
    face_lock = threading.Lock()      # the face models are not thread-safe

    boot = sqlite3.connect(db_path)
    boot.execute('PRAGMA journal_mode=WAL')
    boot.executescript(SCHEMA)
    if 'keepsake_v' not in {r[1] for r in boot.execute('PRAGMA table_info(people)')}:
        boot.execute('ALTER TABLE people ADD COLUMN keepsake_v INTEGER NOT NULL DEFAULT 0')
    if 'face_pending' not in {r[1] for r in boot.execute('PRAGMA table_info(people)')}:
        boot.execute('ALTER TABLE people ADD COLUMN face_pending INTEGER NOT NULL DEFAULT 0')
    boot.commit()
    boot.close()
    # Face drawings are made after the upload answers, so the guest never waits (Bill, 2026-11-26). face_sync
    # (tests, or SAND_FACE_SYNC=1) makes them inline, through the same code.
    if face_sync is None:
        face_sync = os.environ.get('SAND_FACE_SYNC') == '1'
    face_pool = ThreadPoolExecutor(2, thread_name_prefix='face')

    icons_dir = data / 'icons'
    icons_dir.mkdir(parents=True, exist_ok=True)
    keeps_dir = data / 'keepsakes'
    keeps_dir.mkdir(parents=True, exist_ok=True)
    art_dir = data / 'centre-art'
    art_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random()

    # Drawings are made here when ANTHROPIC_API_KEY is set (or a generator is passed in). Without a key the
    # interests stay pending for an outside worker (worker API below).
    icon_service = None
    if icon_gen is not None or photo_gen is not None or theme_gen is not None or icons_mod.api_key_set():
        icon_service = icons_mod.IconService(db_path, lock, gen=icon_gen, clock=clock, photo_gen=photo_gen,
                                           theme_gen=theme_gen)
    photo_pool = ThreadPoolExecutor(4, thread_name_prefix='photo')

    @asynccontextmanager
    async def lifespan(_app):
        if icon_service is not None and start_icons:
            icon_service.start()
        requeue_faces()                 # drawings that were still being made when the server last stopped
        yield
        if icon_service is not None:
            icon_service.stop()

    app = FastAPI(title='sand-app', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.icons = icon_service

    @app.exception_handler(ApiError)
    async def _api_error(request, exc):
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc):
        return JSONResponse({'error': 'bad_request'}, status_code=400)

    @app.middleware('http')
    async def _headers(request: Request, call_next):
        cl = request.headers.get('content-length')
        if cl and cl.isdigit() and int(cl) > MAX_BODY:
            return JSONResponse({'error': 'too_large'}, status_code=413)
        resp = await call_next(request)
        p = request.url.path
        if p.startswith('/api'):
            resp.headers['Cache-Control'] = 'no-store'
        elif p.startswith('/img') and 'cache-control' not in resp.headers:
            resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    # ---------- storage helpers ----------

    def face_file(pid, n):
        return faces_dir / ('%d_%d.jpg' % (pid, n))

    def standin_file(pid, n):
        return faces_dir / ('%d_%d_sk.jpg' % (pid, n))

    def preview_file(pid):
        return faces_dir / ('%d_preview.jpg' % pid)

    def face_strokes_file(pid, n):
        return faces_dir / ('%d_%d_strokes.json' % (pid, n))

    def fit_strokes(strokes, span=0.86):
        """Centre the drawing and scale it so its longer side fills `span` of the unit square."""
        pts = [p for st in strokes for p in st]
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        k = span / max(x1 - x0, y1 - y0, 1e-6)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return [[[round(0.5 + (x - cx) * k, 4), round(0.5 + (y - cy) * k, 4)] for x, y in st] for st in strokes]

    def photo_drawing(crop):
        """Line drawing of the photo's main subject from the model, or None (no key, cap reached, failure,
        or no answer within photo_wait seconds). No lock is held: this takes 10 to 25 seconds."""
        if icon_service is None:
            return None
        fut = photo_pool.submit(icon_service.draw_photo, crop)
        try:
            st = fut.result(timeout=photo_wait)
        except FutureTimeout:
            icons_mod.log.warning('photo drawing gave up after %s s', photo_wait)
            return None
        except Exception:
            return None
        return st or None          # already centred and fitted inside the disc by svgstrokes.fit_strokes

    def draw_face(crop):
        """Face crop -> (line drawing for the table or None, sand-look preview JPEG).
        Order: the face_art landmark portrait; else a model line drawing of the photo's main subject (pets,
        profiles, objects); only when both are unavailable does the preview fall back to the sketch filter."""
        strokes, frac = None, FACE_LINE_FRAC
        if face_art is not None:
            with face_lock:
                r = face_art.face_strokes(crop)
            if r.get('ok') and r.get('strokes'):
                strokes = fit_strokes(r['strokes'])
        if not strokes:
            strokes, frac = photo_drawing(crop), PHOTO_LINE_FRAC
        if not strokes:
            return None, render.face_standin(crop)
        out = io.BytesIO()
        render.relief_image(strokes, 480, True, frac, '#f5f2e9').convert('RGB').save(out, 'JPEG', quality=90)
        return strokes, out.getvalue()

    def store_face(pid, n, crop):
        strokes, jpg = draw_face(crop)
        standin_file(pid, n).write_bytes(jpg)
        if strokes:
            face_strokes_file(pid, n).write_text(json.dumps(strokes))
        else:
            face_strokes_file(pid, n).unlink(missing_ok=True)

    def finish_faces(pid, token):
        """Make the drawings for this person's stored face crops (upload `token`), then mark them ready. A newer
        upload, a delete or a removed person makes this one a no-op."""
        crops = [(n, face_file(pid, n).read_bytes()) for n in (1, 2) if face_file(pid, n).exists()]
        drawn = []
        for n, c in crops:
            try:
                drawn.append((n, draw_face(c)))
            except Exception:
                log.exception('face drawing failed for person %s', pid)
                try:
                    drawn.append((n, (None, render.face_standin(c))))
                except Exception:
                    log.exception('face stand-in failed for person %s', pid)
        with session() as ctx:
            r = ctx.conn.execute('SELECT face_pending FROM people WHERE id = ?', (pid,)).fetchone()
            if not r or r['face_pending'] != token:
                return
            for n, (strokes, jpg) in drawn:
                standin_file(pid, n).write_bytes(jpg)
                if strokes:
                    face_strokes_file(pid, n).write_text(json.dumps(strokes))
                else:
                    face_strokes_file(pid, n).unlink(missing_ok=True)
            # the new version number is what tells the phones and the table driver that the drawing is there
            ctx.conn.execute('UPDATE people SET face_pending = 0, face_v = face_v + 1, preview_v = NULL, '
                             'face_path = NULL WHERE id = ?', (pid,))

    def queue_faces(pid, token):
        if face_sync:
            finish_faces(pid, token)
        else:
            face_pool.submit(finish_faces, pid, token)

    def requeue_faces():
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            rows = conn.execute('SELECT id, face_pending FROM people WHERE face_pending != 0').fetchall()
        finally:
            conn.close()
        for pid, token in rows:
            face_pool.submit(finish_faces, pid, token)

    def rm_face_files(pid):
        for f in faces_dir.glob('%d_*' % pid):
            f.unlink(missing_ok=True)

    def rm_icon_files(iid):
        for f in icons_dir.glob('%d_*' % iid):
            f.unlink(missing_ok=True)

    def keepsake_file(pid):
        return keeps_dir / ('%d.png' % pid)

    def rm_art_files(key):
        for f in art_dir.glob(key + '_*'):
            f.unlink(missing_ok=True)

    def pack(strokes):
        return zlib.compress(json.dumps(strokes, separators=(',', ':')).encode(), 6)

    def unpack(blob):
        return json.loads(zlib.decompress(blob).decode())

    class Ctx:
        def __init__(self, conn, st, now):
            self.conn, self.st, self.now = conn, st, now
            self.keeps = []          # (person_id, table inputs) to render once this change is saved

        def info(self):
            rows = self.conn.execute('SELECT id, name, faces FROM people').fetchall()
            info = {r['id']: {'name': r['name'], 'faces': r['faces'], 'interests': []} for r in rows}
            for r in self.conn.execute('SELECT id, person_id FROM interests ORDER BY id'):
                if r['person_id'] in info:
                    info[r['person_id']]['interests'].append(r['id'])
            return info

        def advance(self):
            S.advance(self.st, self.info(), self.now)

    # ---------- the table picture and keepsakes ----------

    def db_read():
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def table_light(ctx):
        """Small, JSON-able description of what the table picture would show now. Its hash is the picture's version:
        it changes when a turn starts or finishes, a drawn post arrives, the table is reset, or a person, face,
        interest or picture changes. The heavy data (strokes) is loaded later, by the render thread."""
        st, conn = ctx.st, ctx.conn
        cur = st.get('current')
        busy = cur['zone'] if cur and not cur.get('done') and not cur.get('idle') else None
        drawn = {r['zone']: r for r in conn.execute('SELECT zone, turn, person_id, rev FROM drawn')}
        art_v = {r['key']: r['v'] for r in conn.execute('SELECT key, v FROM centre_art')}
        prow = {r['id']: r for r in conn.execute('SELECT id, name, faces, face_v FROM people')}
        irow = {r['id']: r['v'] for r in conn.execute(
            "SELECT id, v FROM interests WHERE status = 'ready' AND strokes IS NOT NULL")}
        zones = {}
        for z in S.ZONES:
            if z == busy:                                  # being wiped right now: plain sand
                continue
            zs = st['zones'][z]
            occ = zs['person_id']
            if occ is None or occ not in prow:
                continue
            d = drawn.get(z)
            if d and d['person_id'] == occ and d['turn'] >= st.get('last_drawn', {}).get(z, 0):
                zones[z] = {'m': 'drawn', 'rev': d['rev']}
                continue
            p = prow[occ]
            art = [[k, art_v[k]] for k in zs.get('centre_art', []) if k in art_v] if z == 'centre' else []
            zones[z] = {'m': 'layout', 'pid': occ, 'name': p['name'], 'nf': p['faces'], 'fv': p['face_v'],
                        'ints': [[i, irow[i]] for i in zs['interest_ids'][:3] if i in irow], 'art': art}
        fr = drawn.get('frame')
        return {'zones': zones, 'frame': fr['rev'] if fr else 0}

    def table_load(inputs):
        """The strokes behind table_light's description: (zones for render.render_table, frame strokes or None)."""
        zones, frame = {}, None
        with lock:
            conn = db_read()
            try:
                if inputs.get('frame'):
                    r = conn.execute("SELECT strokes FROM drawn WHERE zone = 'frame'").fetchone()
                    frame = (unpack(r['strokes']) or None) if r else None
                for z, it in inputs['zones'].items():
                    if it['m'] == 'drawn':
                        r = conn.execute('SELECT strokes FROM drawn WHERE zone = ?', (z,)).fetchone()
                        if r:
                            zones[z] = {'strokes': unpack(r['strokes'])}
                        continue
                    ints = []
                    for iid, _v in it['ints']:
                        r = conn.execute('SELECT strokes FROM interests WHERE id = ?', (iid,)).fetchone()
                        if r and r['strokes']:
                            ints.append(json.loads(r['strokes']))
                    art = []
                    for key, _v in it['art']:
                        r = conn.execute('SELECT strokes FROM centre_art WHERE key = ?', (key,)).fetchone()
                        if r:
                            art.append(json.loads(r['strokes']))
                    faces = []
                    for n in range(1, it['nf'] + 1):
                        f = face_strokes_file(it['pid'], n)
                        try:
                            faces.append(json.loads(f.read_text()))
                        except (OSError, ValueError):
                            pass
                    zones[z] = {'name': it['name'], 'faces': faces, 'interests': ints, 'art': art}
            finally:
                conn.close()
        return zones, frame

    class Tables:
        """Renders the table picture on one background thread, never inside the DB lock. The latest picture per size
        is cached by its version; while a new one renders the previous one is served."""

        def __init__(self):
            self.pool = ThreadPoolExecutor(1, thread_name_prefix='table')
            self.mu = threading.Lock()
            self.cache = {}              # size -> (version, png bytes)
            self.inflight = {}           # (version, size) -> Future

        @staticmethod
        def version(inputs):
            return hashlib.sha1(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]

        def _render(self, inputs, size, ver):
            zones, frame = table_load(inputs)
            data = render.table_png(zones, frame, size)
            with self.mu:
                self.cache.pop(size, None)
                self.cache[size] = (ver, data)
                while len(self.cache) > 4:
                    self.cache.pop(next(iter(self.cache)))
            return data

        def _job(self, inputs, size, ver):
            try:
                return self._render(inputs, size, ver)
            finally:
                with self.mu:
                    self.inflight.pop((ver, size), None)

        def get(self, inputs, size):
            ver = self.version(inputs)
            with self.mu:
                hit = self.cache.get(size)
                if hit and hit[0] == ver:
                    return hit[1]
                fut = self.inflight.get((ver, size))
                if fut is None:
                    fut = self.inflight[(ver, size)] = self.pool.submit(self._job, inputs, size, ver)
            if hit:
                return hit[1]
            return fut.result(timeout=120)

        def keepsake(self, pid, inputs):
            self.pool.submit(self._keep, pid, inputs)

        def _keep(self, pid, inputs):
            try:
                ver = self.version(inputs)
                with self.mu:
                    hit = self.cache.get(TABLE_SIZE)
                data = hit[1] if hit and hit[0] == ver else self._render(inputs, TABLE_SIZE, ver)
                with lock:
                    conn = db_read()
                    try:
                        if conn.execute('SELECT 1 FROM people WHERE id = ?', (pid,)).fetchone():
                            f = keepsake_file(pid)
                            tmp = f.with_suffix('.tmp')
                            tmp.write_bytes(data)
                            tmp.replace(f)
                            conn.execute('UPDATE people SET keepsake_v = keepsake_v + 1 WHERE id = ?', (pid,))
                            conn.commit()
                    finally:
                        conn.close()
            except Exception:
                icons_mod.log.exception('keepsake render failed')

        def flush(self):
            """Wait for everything queued so far (tests)."""
            self.pool.submit(lambda: None).result(timeout=120)

    tables = Tables()
    app.state.tables = tables

    def pick_art(ctx):
        on = [r['key'] for r in ctx.conn.execute(
            'SELECT c.key FROM centre_art c LEFT JOIN centre_art_pref p ON p.key = c.key '
            'WHERE COALESCE(p.enabled, 1) = 1 ORDER BY c.pos')]
        return rng.sample(on, min(ART_PER_TURN, len(on)))

    def reserve_art(ctx, pid):
        """The pictures the NEXT centre turn (person pid) will get, picked once so the driver can build that turn early.
        Kept in the state until the next turn starts; ensure_centre_art hands it over if that turn is this person's."""
        res = ctx.st.get('next_art')
        if not res or res.get('person_id') != pid:
            res = ctx.st['next_art'] = {'person_id': pid, 'keys': pick_art(ctx)}
        return res['keys']

    def ensure_centre_art(ctx):
        """Pick the Thanksgiving pictures for a centre draw turn, once, when it first shows as the current turn
        (or take the pick already promised to the driver in the plan's `next`).
        The keys stay on the current-turn record (and on the centre zone record, for the person drawn there)."""
        st = ctx.st
        cur = st.get('current')
        if not cur or cur.get('centre_art') is not None:
            return
        res = st.pop('next_art', None)      # a promise only lasts until the next turn starts
        if cur.get('kind', 'draw') != 'draw' or cur['zone'] != 'centre' or cur['person_id'] is None:
            cur['centre_art'] = []
            return
        if res and res.get('person_id') == cur['person_id']:
            have = {r['key'] for r in ctx.conn.execute('SELECT key FROM centre_art')}
            keys = [k for k in res['keys'] if k in have]
        else:
            keys = pick_art(ctx)
        cur['centre_art'] = keys
        z = st['zones']['centre']
        if z['person_id'] == cur['person_id']:
            z['centre_art'] = list(keys)

    def want_keepsake(st, end):
        return (end.get('kind') == 'draw' and end.get('person_id') is not None
                and st['zones'][end['zone']]['person_id'] == end['person_id'])

    def settle(ctx):
        """Things that follow a change of turn: the centre pictures, and a keepsake for whoever just finished."""
        st = ctx.st
        ensure_centre_art(ctx)
        end = st.get('last_end')
        if end and end != st.get('keep_mark'):
            st['keep_mark'] = dict(end)
            if want_keepsake(st, end):
                ctx.keeps.append((end['person_id'], table_light(ctx)))

    @contextmanager
    def session():
        with lock:
            conn = sqlite3.connect(db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            try:
                row = conn.execute('SELECT json FROM sched WHERE id = 1').fetchone()
                st = json.loads(row['json']) if row else S.new_state()
                ctx = Ctx(conn, st, int(clock()))
                ctx.advance()
                settle(ctx)
                yield ctx
                settle(ctx)
                conn.execute('INSERT OR REPLACE INTO sched (id, json) VALUES (1, ?)', (json.dumps(st),))
                conn.commit()
                for pid, inputs in ctx.keeps:
                    tables.keepsake(pid, inputs)
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ---------- views ----------

    def art_rows(conn):
        return conn.execute('SELECT c.key, c.label, c.v, COALESCE(p.enabled, 1) AS enabled FROM centre_art c '
                            'LEFT JOIN centre_art_pref p ON p.key = c.key ORDER BY c.pos').fetchall()

    def build_state(ctx):
        ctx.advance()
        conn, st, now = ctx.conn, ctx.st, ctx.now
        info = ctx.info()
        prow = conn.execute('SELECT * FROM people ORDER BY name COLLATE NOCASE').fetchall()
        irows = conn.execute('SELECT * FROM interests ORDER BY id').fetchall()
        by_person = {}
        for r in irows:
            by_person.setdefault(r['person_id'], []).append(r)
        joined_ids = {r['id'] for r in prow if r['joined']}
        names = {r['id']: r['name'] for r in prow}
        n_joined = len(st['queue'])
        # look further ahead than the list we show, so most people on the table still get a next time
        projected = S.project(st, info, now, count=max(12, min(3 * n_joined + 2, 120)))
        upcoming = projected[:max(12, n_joined + 2)]
        mode = S.clock_mode(st, now)
        next_turn = {}
        for k, u in enumerate(projected):
            next_turn.setdefault(u['person_id'], (k, u))
        live = set(r['id'] for r in irows)
        arts = art_rows(conn)
        art_keys = {a['key'] for a in arts}

        def shared(r):
            out = set()
            for pid in joined_ids:
                if pid == r['person_id']:
                    continue
                if any(S.same(o['label'], r['label']) for o in by_person.get(pid, [])):
                    out.add(names[pid])
            return sorted(out)

        theme_of = themes_mod.load_all(conn)

        def themes_of(r):
            return theme_of.get(icons_mod.norm_label(r['label']), [])

        def related(r):
            mine = themes_of(r)
            if not mine:
                return []
            have = set(shared(r))
            out = []
            for pid in sorted(joined_ids, key=lambda p: names[p].casefold()):
                if pid == r['person_id'] or names[pid] in have:
                    continue
                for o in by_person.get(pid, []):
                    if S.same(o['label'], r['label']):
                        continue
                    common = set(themes_of(o))
                    t = next((x for x in mine if x in common), None)
                    if t:
                        out.append({'name': names[pid], 'label': o['label'], 'theme': t})
                        break
            return out

        people = []
        for r in prow:
            zones = S.person_zones(st, r['id']) if r['joined'] else []
            zone = zones[0] if zones else None
            k, nxt = next_turn.get(r['id'], (None, None)) if r['joined'] else (None, None)
            people.append({
                'id': r['id'], 'name': r['name'], 'joined': bool(r['joined']), 'color': r['color'],
                'faces': r['faces'], 'face_v': r['face_v'], 'face_pending': bool(r['face_pending']),
                'interests': [{'id': i['id'], 'label': i['label'], 'status': i['status'], 'source': i['source'],
                               'v': i['v'], 'shared_with': shared(i), 'related': related(i)} for i in by_person.get(r['id'], [])],
                'zone': zone, 'zones': zones,
                'next_at': nxt['at'] if nxt and mode != 'idle' else None, 'next_in': k,
                'next_zone': nxt['zone'] if nxt else None,
                'featured': S.featured(st, r['id']), 'keepsake_v': r['keepsake_v'],
            })
        table = {
            'current': S.describe_current(st, info, now),
            'zones': [dict({'zone': z, 'person_id': st['zones'][z]['person_id'], 'dirty': bool(st['zones'][z].get('dirty')),
                            'interest_ids': [i for i in st['zones'][z]['interest_ids'] if i in live]},
                           **({'centre_art': [k for k in st['zones'][z].get('centre_art', []) if k in art_keys]}
                              if z == 'centre' else {})) for z in S.ZONES],
            'erase': dict(st['erase']) if st.get('erase') else None,
            'forced': [dict(f) for f in st.get('forced', [])],
            'pinned': [i for i in st.get('pinned', []) if i in names],
            'upcoming': [{'kind': u['kind'], 'person_id': u['person_id'], 'zone': u['zone'],
                          'at': u['at'] if mode != 'idle' else None,
                          'interest_ids': [i for i in u['interest_ids'] if i in live]} for u in upcoming],
            'hold_until': S.hold_until(st),
        }
        if table['current']:
            table['current']['interest_ids'] = [i for i in table['current']['interest_ids'] if i in live]
            table['current']['centre_art'] = [k for k in st['current'].get('centre_art', []) if k in art_keys]
        return {'now': now, 'paused': st['paused'],
                'clock': mode,
                'ring': st['ring'], 'people': people, 'table': table,
                'centre_art': [{'key': a['key'], 'label': a['label'], 'enabled': bool(a['enabled']), 'v': a['v']}
                               for a in arts]}

    def person_view(ctx, pid):
        for p in build_state(ctx)['people']:
            if p['id'] == pid:
                return p
        raise ApiError(404, 'not_found')

    def interest_view(ctx, iid):
        for p in build_state(ctx)['people']:
            for i in p['interests']:
                if i['id'] == iid:
                    return i
        raise ApiError(404, 'not_found')

    def need_person(ctx, pid):
        r = ctx.conn.execute('SELECT * FROM people WHERE id = ?', (pid,)).fetchone()
        if not r:
            raise ApiError(404, 'not_found')
        return r

    def need_interest(ctx, iid):
        r = ctx.conn.execute('SELECT * FROM interests WHERE id = ?', (iid,)).fetchone()
        if not r:
            raise ApiError(404, 'not_found')
        return r

    def insert_person(ctx, name):
        key = name.casefold()
        if ctx.conn.execute('SELECT 1 FROM people WHERE name_key = ?', (key,)).fetchone():
            raise ApiError(409, 'taken', name=ctx.conn.execute(
                'SELECT name FROM people WHERE name_key = ?', (key,)).fetchone()['name'])
        if ctx.conn.execute('SELECT COUNT(*) FROM people').fetchone()[0] >= MAX_PEOPLE:
            raise ApiError(400, 'too_many_people')
        cur = ctx.conn.execute('INSERT INTO people (name, name_key) VALUES (?, ?)', (name, key))
        return cur.lastrowid

    # ---------- guest / host API ----------

    @app.get('/api/state')
    def get_state():
        with session() as ctx:
            return build_state(ctx)

    @app.post('/api/people', status_code=201)
    def add_person(body: dict = Body(...)):
        name = clean_text(body.get('name'), 1, 30, 'bad_name')
        with session() as ctx:
            pid = insert_person(ctx, name)
            return person_view(ctx, pid)

    @app.post('/api/people/bulk')
    def add_bulk(body: dict = Body(...)):
        names = body.get('names')
        if not isinstance(names, list) or len(names) > MAX_PEOPLE:
            raise ApiError(400, 'bad_names')
        added = 0
        with session() as ctx:
            for n in names:
                try:
                    insert_person(ctx, clean_text(n, 1, 30, 'bad_name'))
                    added += 1
                except ApiError:
                    pass
            return {'added': added}

    @app.patch('/api/people/{pid}')
    def patch_person(pid: int, body: dict = Body(...)):
        with session() as ctx:
            row = need_person(ctx, pid)
            if 'color' in body:
                c = body['color']
                if c is not None and (isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 7):
                    raise ApiError(400, 'bad_color')
                ctx.conn.execute('UPDATE people SET color = ? WHERE id = ?', (c, pid))
            if 'joined' in body:
                if body['joined'] is not True:
                    raise ApiError(400, 'bad_joined')
                if not row['joined']:
                    ctx.conn.execute('UPDATE people SET joined = 1 WHERE id = ?', (pid,))
                    S.add_person(ctx.st, pid)
            return person_view(ctx, pid)

    @app.delete('/api/people/{pid}', status_code=204)
    def delete_person(pid: int):
        with session() as ctx:
            need_person(ctx, pid)
            S.remove_person(ctx.st, pid, ctx.now)
            for r in ctx.conn.execute('SELECT id FROM interests WHERE person_id = ?', (pid,)).fetchall():
                rm_icon_files(r['id'])
            ctx.conn.execute('DELETE FROM interests WHERE person_id = ?', (pid,))
            ctx.conn.execute('DELETE FROM people WHERE id = ?', (pid,))
            ctx.conn.execute('DELETE FROM drawn WHERE person_id = ?', (pid,))
            rm_face_files(pid)
            keepsake_file(pid).unlink(missing_ok=True)
        return Response(status_code=204)

    def read_upload(f):
        raw = f.file.read(MAX_FACE_BYTES + 1)
        if len(raw) > MAX_FACE_BYTES:
            raise ApiError(413, 'too_large')
        return raw

    @app.post('/api/people/{pid}/faces')
    def upload_faces(pid: int, face1: UploadFile = File(...), face2: UploadFile = File(None)):
        crops = [clean_image(read_upload(face1))]
        if face2 is not None and face2.filename:
            crops.append(clean_image(read_upload(face2)))
        # Answer at once: keep the crops, mark the face as being made, draw it afterwards (finish_faces).
        token = rng.randrange(1, 2 ** 31)
        with session() as ctx:
            need_person(ctx, pid)
            rm_face_files(pid)
            for n, c in enumerate(crops, start=1):
                face_file(pid, n).write_bytes(c)
            ctx.conn.execute('UPDATE people SET faces = ?, face_pending = ?, preview_v = NULL, face_path = NULL '
                             'WHERE id = ?', (len(crops), token, pid))
        queue_faces(pid, token)
        with session() as ctx:
            return person_view(ctx, pid)

    @app.delete('/api/people/{pid}/faces')
    def delete_faces(pid: int):
        with session() as ctx:
            need_person(ctx, pid)
            rm_face_files(pid)
            ctx.conn.execute('UPDATE people SET faces = 0, face_pending = 0, face_v = face_v + 1, preview_v = NULL, '
                             'face_path = NULL WHERE id = ?', (pid,))
            return person_view(ctx, pid)

    def wake_icons():
        if icon_service is not None:
            icon_service.wake()

    @app.post('/api/people/{pid}/interests', status_code=201)
    def add_interest(pid: int, body: dict = Body(...)):
        has_strokes = body.get('strokes') is not None
        strokes = clean_strokes(body['strokes']) if has_strokes else None
        # Several interests in one entry ("computers, AI, music") become several. With strokes it is one label.
        raw = body.get('label')
        multi = not has_strokes and isinstance(raw, str) and _SPLIT.search(raw) is not None
        label = None if multi else clean_text(raw, 1, 40, 'bad_label')
        with session() as ctx:
            need_person(ctx, pid)
            rows = ctx.conn.execute('SELECT label FROM interests WHERE person_id = ?', (pid,)).fetchall()
            if multi:
                labels = split_labels(raw, have=[r['label'] for r in rows])
                if not split_labels(raw):
                    raise ApiError(400, 'bad_label')
            else:
                labels = [label]
            if len(rows) + len(labels) > MAX_INTERESTS:
                raise ApiError(400, 'too_many_interests')
            ids = []
            for lab in labels:
                cur = ctx.conn.execute(
                    'INSERT INTO interests (person_id, label, status, source, strokes) VALUES (?, ?, ?, ?, ?)',
                    (pid, lab, 'ready' if strokes else 'pending', 'sketch' if strokes else 'ai',
                     json.dumps(strokes) if strokes else None))
                ids.append(cur.lastrowid)
            views = [interest_view(ctx, i) for i in ids]
        if not strokes:
            wake_icons()
        return {'interests': views} if multi else views[0]

    @app.patch('/api/interests/{iid}')
    def patch_interest(iid: int, body: dict = Body(...)):
        label = clean_text(body['label'], 1, 40, 'bad_label') if body.get('label') is not None else None
        strokes = clean_strokes(body['strokes']) if body.get('strokes') is not None else None
        if label is None and strokes is None:
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            row = need_interest(ctx, iid)
            if strokes is not None:
                ctx.conn.execute('UPDATE interests SET label = ?, status = ?, source = ?, strokes = ?, v = v + 1 '
                                 'WHERE id = ?', (label or row['label'], 'ready', 'sketch', json.dumps(strokes), iid))
            elif row['source'] == 'sketch' and row['strokes']:
                # Renaming a hand-drawn interest keeps the guest's own drawing.
                ctx.conn.execute('UPDATE interests SET label = ?, v = v + 1 WHERE id = ?', (label, iid))
            else:
                ctx.conn.execute('UPDATE interests SET label = ?, status = ?, source = ?, strokes = NULL, v = v + 1 '
                                 'WHERE id = ?', (label, 'pending', 'ai', iid))
            view = interest_view(ctx, iid)
        if strokes is None:
            wake_icons()
        return view

    @app.delete('/api/interests/{iid}', status_code=204)
    def delete_interest(iid: int):
        with session() as ctx:
            need_interest(ctx, iid)
            ctx.conn.execute('DELETE FROM interests WHERE id = ?', (iid,))
            rm_icon_files(iid)
        return Response(status_code=204)

    @app.post('/api/host/pause')
    def host_pause(body: dict = Body(...)):
        if not isinstance(body.get('paused'), bool):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            S.set_paused(ctx.st, body['paused'], ctx.now)
            return build_state(ctx)

    @app.post('/api/host/skip')
    def host_skip():
        with session() as ctx:
            S.skip(ctx.st, ctx.info(), ctx.now)
            return build_state(ctx)

    @app.post('/api/host/move')
    def host_move(body: dict = Body(...)):
        pid, d = body.get('person_id'), body.get('dir')
        if isinstance(pid, bool) or not isinstance(pid, int) or d not in (-1, 1) or isinstance(d, bool):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            S.move(ctx.st, pid, d)
            return build_state(ctx)

    @app.post('/api/host/feature')
    def host_feature(body: dict = Body(...)):
        """Feature now: the next turn(s) draw this person in the given zones (default: the centre)."""
        pid, zones = body.get('person_id'), body.get('zones', ['centre'])
        if (isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(zones, list) or not 1 <= len(zones) <= 3
                or any(z not in S.ZONES for z in zones) or len(set(zones)) != len(zones)):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            need_person(ctx, pid)
            if not S.feature(ctx.st, pid, zones):
                raise ApiError(409, 'not_joined')
            ctx.advance()
            return build_state(ctx)

    @app.post('/api/host/erase')
    def host_erase(body: dict = Body(...)):
        """Erase the whole table, spiralling in or out; `dir` null cancels a request that has not started."""
        d = body.get('dir')
        if d not in ('in', 'out', None):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            if not S.request_erase(ctx.st, d, ctx.now):
                raise ApiError(409, 'erase_running')
            ctx.advance()
            return build_state(ctx)

    @app.post('/api/host/pin')
    def host_pin(body: dict = Body(...)):
        """The people shown first on the Everyone page, in this order (an empty list clears it)."""
        ids = body.get('person_ids')
        if (not isinstance(ids, list) or len(ids) > 50 or len(set(map(str, ids))) != len(ids)
                or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            for i in ids:
                need_person(ctx, i)
            ctx.st['pinned'] = list(ids)
            return build_state(ctx)

    @app.post('/api/host/ring')
    def host_ring(body: dict = Body(...)):
        if body.get('ring') not in S.RINGS:
            raise ApiError(400, 'bad_ring')
        with session() as ctx:
            S.set_ring(ctx.st, body['ring'])
            return build_state(ctx)

    @app.post('/api/host/centre-art')
    def host_centre_art(body: dict = Body(...)):
        key, on = body.get('key'), body.get('enabled')
        if not isinstance(key, str) or not isinstance(on, bool):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            if not ctx.conn.execute('SELECT 1 FROM centre_art WHERE key = ?', (key,)).fetchone():
                raise ApiError(404, 'not_found')
            ctx.conn.execute('INSERT OR REPLACE INTO centre_art_pref (key, enabled) VALUES (?, ?)', (key, int(on)))
            return build_state(ctx)

    @app.post('/api/host/settings')
    def host_settings(body: dict = Body(...)):
        vals = {}
        if 'auto_advance' in body:
            if not isinstance(body['auto_advance'], bool):
                raise ApiError(400, 'bad_auto_advance')
            vals['auto_advance'] = body['auto_advance']
        for k in ('centre_minutes', 'slice_minutes'):
            if k in body:
                v = body[k]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 240:
                    raise ApiError(400, 'bad_' + k)
                vals[k] = v
        with session() as ctx:
            S.set_settings(ctx.st, **vals)
            return build_state(ctx)

    # ---------- images ----------

    def icon_row(iid):
        with lock:
            conn = sqlite3.connect(db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                r = conn.execute('SELECT * FROM interests WHERE id = ?', (iid,)).fetchone()
            finally:
                conn.close()
        if not r:
            raise ApiError(404, 'not_found')
        return r

    @app.get('/img/icon/{iid}.svg')
    def icon(iid: int):
        r = icon_row(iid)
        if r['status'] == 'ready' and r['strokes']:
            svg = render.icon_svg_ready(json.loads(r['strokes']))
        else:
            svg = render.icon_svg_pending(r['label'], r['id'])
        return Response(svg, media_type='image/svg+xml')

    @app.get('/img/icon/{iid}.png')
    def icon_png(iid: int, s: int = Query(240)):
        """Ready: the drawing as grooves in sand (cached on disk by id, v and size). Pending: the lettered
        placeholder, which is SVG, behind the same URL."""
        r = icon_row(iid)
        if not (r['status'] == 'ready' and r['strokes']):
            return Response(render.icon_svg_pending(r['label'], r['id']), media_type='image/svg+xml')
        size = min((120, 240, 480), key=lambda k: abs(k - s))
        f = icons_dir / ('%d_%d_%d.png' % (iid, r['v'], size))
        if not f.exists():
            for old in icons_dir.glob('%d_*' % iid):
                if not old.name.startswith('%d_%d_' % (iid, r['v'])):
                    old.unlink(missing_ok=True)   # an older version of this drawing
            data_png = render.relief_png(json.loads(r['strokes']), size)
            tmp = f.with_suffix('.tmp')
            tmp.write_bytes(data_png)
            tmp.replace(f)
        return FileResponse(f, media_type='image/png')

    @app.get('/img/centre-art/{key}.png')
    def centre_art_png(key: str, s: int = Query(240)):
        if not ART_KEY.match(key):
            raise ApiError(404, 'not_found')
        with lock:
            conn = db_read()
            try:
                r = conn.execute('SELECT strokes, v FROM centre_art WHERE key = ?', (key,)).fetchone()
            finally:
                conn.close()
        if not r:
            raise ApiError(404, 'not_found')
        size = min((120, 240, 480), key=lambda k: abs(k - s))
        f = art_dir / ('%s_%d_%d.png' % (key, r['v'], size))
        if not f.exists():
            for old in art_dir.glob(key + '_*'):
                if not old.name.startswith('%s_%d_' % (key, r['v'])):
                    old.unlink(missing_ok=True)
            tmp = f.with_suffix('.tmp')
            tmp.write_bytes(render.relief_png(json.loads(r['strokes']), size))
            tmp.replace(f)
        return FileResponse(f, media_type='image/png')

    def live_table(size):
        with session() as ctx:
            inputs = table_light(ctx)
        return Response(tables.get(inputs, size), media_type='image/png', headers={'Cache-Control': 'no-cache'})

    @app.get('/img/table.png')
    def table_img(s: int = Query(TABLE_SIZE)):
        """The table as it stands now, in the sand-relief look. Rendered on a background thread; the previous
        picture is served while a new one renders."""
        return live_table(min(2000, max(200, s)))

    @app.get('/img/keepsake/{pid}.png')
    def keepsake_img(pid: int):
        with lock:
            conn = db_read()
            try:
                r = conn.execute('SELECT keepsake_v FROM people WHERE id = ?', (pid,)).fetchone()
            finally:
                conn.close()
        if not r:
            raise ApiError(404, 'not_found')
        f = keepsake_file(pid)
        if r['keepsake_v'] > 0 and f.exists():
            return FileResponse(f, media_type='image/png')
        return live_table(TABLE_SIZE)

    @app.get('/img/face/{pid}.jpg')
    def face_img(pid: int, n: int = Query(1)):
        with lock:
            conn = sqlite3.connect(db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                r = conn.execute('SELECT faces, face_v, preview_v, face_pending FROM people WHERE id = ?', (pid,)).fetchone()
            finally:
                conn.close()
        if not r or n not in (1, 2) or r['faces'] < n or r['face_pending']:
            raise ApiError(404, 'not_found')        # while the drawing is being made the phones show a spinner
        if n == 1 and r['preview_v'] == r['face_v'] and preview_file(pid).exists():
            return FileResponse(preview_file(pid), media_type='image/jpeg')
        sk = standin_file(pid, n)
        if not sk.exists():
            if not face_file(pid, n).exists():
                raise ApiError(404, 'not_found')
            store_face(pid, n, face_file(pid, n).read_bytes())
        return FileResponse(sk, media_type='image/jpeg')

    # ---------- worker API ----------

    def worker_auth(x_worker_token: str = Header(None)):
        if not token or not x_worker_token or not hmac.compare_digest(x_worker_token.encode(), token.encode()):
            raise ApiError(401, 'unauthorized')

    @app.get('/api/worker/jobs', dependencies=[Depends(worker_auth)])
    def worker_jobs():
        with session() as ctx:
            ints = ctx.conn.execute("SELECT id, label, v FROM interests WHERE status = 'pending' ORDER BY id").fetchall()
            faces = ctx.conn.execute('SELECT id, face_v FROM people WHERE faces > 0 AND '
                                     '(preview_v IS NULL OR preview_v != face_v) ORDER BY id').fetchall()
            return {'interests': [{'id': r['id'], 'label': r['label'], 'v': r['v']} for r in ints],
                    'faces': [{'person_id': r['id'], 'face_v': r['face_v'], 'n': 1} for r in faces]}

    @app.post('/api/worker/interests/{iid}', dependencies=[Depends(worker_auth)])
    def worker_interest(iid: int, body: dict = Body(...)):
        strokes = clean_strokes(body.get('strokes'))
        with session() as ctx:
            row = need_interest(ctx, iid)
            if body.get('v') != row['v'] or row['status'] != 'pending':
                raise ApiError(409, 'stale', v=row['v'])
            ctx.conn.execute("UPDATE interests SET status = 'ready', source = 'ai', strokes = ?, v = v + 1 "
                             'WHERE id = ?', (json.dumps(strokes), iid))
            return interest_view(ctx, iid)

    @app.get('/api/worker/face/{pid}/{n}', dependencies=[Depends(worker_auth)])
    def worker_face(pid: int, n: int):
        f = face_file(pid, n)
        if not f.exists():
            raise ApiError(404, 'not_found')
        return FileResponse(f, media_type='image/jpeg')

    @app.post('/api/worker/faces/{pid}', dependencies=[Depends(worker_auth)])
    def worker_post_face(pid: int, preview: UploadFile = File(...), face_v: int = Form(...),
                         path: str = Form(None)):
        img = clean_image(read_upload(preview))
        if path is not None:
            try:
                json.loads(path)
            except ValueError:
                raise ApiError(400, 'bad_path')
        with session() as ctx:
            row = need_person(ctx, pid)
            if row['faces'] < 1 or row['face_v'] != face_v:
                raise ApiError(409, 'stale', face_v=row['face_v'])
            preview_file(pid).write_bytes(img)
            ctx.conn.execute('UPDATE people SET preview_v = ?, face_path = ? WHERE id = ?', (face_v, path, pid))
            return {'ok': True}

    @app.post('/api/worker/centre-art', dependencies=[Depends(worker_auth)])
    def worker_centre_art(body: dict = Body(...)):
        """The driver's Thanksgiving picture set. Upsert by key, absent keys are deleted, order is post order; the
        host's on/off choice per key is remembered (also for a key that drops out and comes back)."""
        items = clean_art_items(body.get('items'))
        with session() as ctx:
            conn = ctx.conn
            have = {r['key']: r for r in conn.execute('SELECT key, label, strokes, v FROM centre_art')}
            for key in set(have) - {i['key'] for i in items}:
                conn.execute('DELETE FROM centre_art WHERE key = ?', (key,))
                rm_art_files(key)
            for pos, it in enumerate(items):
                strokes = json.dumps(it['strokes'])
                old = have.get(it['key'])
                if old is None:
                    conn.execute('INSERT INTO centre_art (key, label, strokes, pos, v) VALUES (?, ?, ?, ?, 1)',
                                 (it['key'], it['label'], strokes, pos))
                else:
                    changed = old['label'] != it['label'] or json.loads(old['strokes']) != it['strokes']
                    conn.execute('UPDATE centre_art SET label = ?, strokes = ?, pos = ?, v = v + ? WHERE key = ?',
                                 (it['label'], strokes, pos, int(changed), it['key']))
            return {'items': [{'key': a['key'], 'label': a['label'], 'enabled': bool(a['enabled']), 'v': a['v']}
                              for a in art_rows(conn)]}

    @app.post('/api/worker/drawn', dependencies=[Depends(worker_auth)])
    def worker_drawn(body: dict = Body(...)):
        """What the table really left visible in a zone (or "frame": the lines that belong to no zone) after a turn,
        table frame. A post replaces the earlier one for that zone."""
        turn, zone = body.get('turn'), body.get('zone')
        if isinstance(turn, bool) or not isinstance(turn, int) or zone not in S.ZONES + ['frame']:
            raise ApiError(400, 'bad_request')
        strokes = clean_drawn_strokes(body.get('strokes'))
        blob = pack(strokes)
        with session() as ctx:
            st = ctx.st
            cur = st.get('current')
            finished = turn != cur['turn'] if cur else True      # a turn that is over, not the one running
            ok = turn > st.get('drawn_floor', 0) and (
                (cur and turn == cur['turn']) or turn == (cur['turn'] - 1 if cur else st['turn']))
            if ok and finished and cur and zone == cur['zone'] and not cur.get('done'):
                ok = False                                       # that zone has been taken by the running turn
            if not ok:
                raise ApiError(409, 'stale', turn=cur['turn'] if cur else st['turn'])
            st['drawn_rev'] = rev = st.get('drawn_rev', 0) + 1
            person = None if zone == 'frame' else st['zones'][zone]['person_id']
            ctx.conn.execute('INSERT OR REPLACE INTO drawn (zone, turn, person_id, strokes, posted, rev) '
                             'VALUES (?, ?, ?, ?, ?, ?)', (zone, turn, person, blob, ctx.now, rev))
            end = st.get('last_end')
            if (finished or (cur and cur.get('closed'))) and end and want_keepsake(st, end):
                ctx.keeps.append((end['person_id'], table_light(ctx)))   # the keepsake gets the late post too
            return {'ok': True, 'rev': rev}

    @app.post('/api/worker/erase', dependencies=[Depends(worker_auth)])
    def worker_erase(body: dict = Body(...)):
        """The driver is starting the erase the host asked for. `accepted` false: that request was cancelled."""
        eid = body.get('id')
        if isinstance(eid, bool) or not isinstance(eid, int) or body.get('status') != 'running':
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            ok = S.erase_started(ctx.st, eid)
            state = build_state(ctx)
            state['accepted'] = ok
            return state

    @app.post('/api/worker/reset', dependencies=[Depends(worker_auth)])
    def worker_reset():
        """The table was cleared: empty every zone and start the rotation again from the centre."""
        with session() as ctx:
            ctx.conn.execute('DELETE FROM drawn')
            ctx.st['drawn_floor'] = ctx.st['turn']
            S.reset_table(ctx.st)
            if not ctx.st['paused']:        # start at once, even while the table (not the simulated clock) keeps time
                S.start_turn(ctx.st, ctx.info(), ctx.now)
            return build_state(ctx)

    @app.get('/api/worker/plan', dependencies=[Depends(worker_auth)])
    def worker_plan():
        with session() as ctx:
            state = build_state(ctx)
            conn, st = ctx.conn, ctx.st
            prow = {r['id']: r for r in conn.execute('SELECT * FROM people')}
            irow = {r['id']: r for r in conn.execute('SELECT * FROM interests')}
            arow = {r['key']: r for r in conn.execute('SELECT key, label, strokes FROM centre_art')}

            def entry(zone, pid, ids, **extra):
                p = prow.get(pid)
                if p is None:
                    return dict(extra, zone=zone, person_id=None, name=None, interests=[])
                path = None
                if p['face_path']:
                    path = json.loads(p['face_path'])
                return dict(extra, zone=zone, person_id=pid, name=p['name'], color=p['color'], ring=st['ring'],
                            faces=p['faces'], face_v=p['face_v'],
                            has_preview=p['preview_v'] == p['face_v'], face_path=path,
                            face_strokes=[json.loads(f.read_text()) for f in
                                          (face_strokes_file(pid, n) for n in (1, 2)[:p['faces']]) if f.exists()],
                            interests=[{'id': i, 'label': irow[i]['label'], 'status': irow[i]['status'], 'v': irow[i]['v'],
                                        'strokes': json.loads(irow[i]['strokes']) if irow[i]['strokes'] else None}
                                       for i in ids if i in irow])

            cur = state['table']['current']
            if cur and cur['done']:   # a finished centre being held: no turn in progress, `next` says when it starts
                cur = None
            hold = state['table']['hold_until']   # known even when no one can estimate `at`
            nxt = state['table']['upcoming'][0] if state['table']['upcoming'] else None
            def art_of(keys):
                return [{'key': k, 'label': arow[k]['label'], 'strokes': json.loads(arow[k]['strokes'])} for k in keys if k in arow]

            art = art_of(cur['centre_art'] if cur else [])
            # `next` carries what that turn will have when it starts, so the driver can build it early
            next_art = []
            if nxt and nxt['kind'] == 'draw' and nxt['zone'] == 'centre' and nxt['person_id'] is not None:
                next_art = art_of(reserve_art(ctx, nxt['person_id']))
            return {
                'state': state,
                'erase': state['table']['erase'],
                'ring': st['ring'],
                'current': entry(cur['zone'], cur['person_id'], cur['interest_ids'], turn=cur['turn'], kind=cur['kind'],
                                 centre_art=art) if cur else None,
                'zones': [entry(z['zone'], z['person_id'], z['interest_ids'], dirty=z['dirty'],
                                **({'centre_art': z['centre_art']} if 'centre_art' in z else {}))
                          for z in state['table']['zones']],
                'next': entry(nxt['zone'], nxt['person_id'], nxt['interest_ids'], at=hold if hold else nxt['at'], kind=nxt['kind'],
                              turn=st['turn'] + 1, centre_art=next_art) if nxt else None,
            }

    @app.post('/api/worker/progress', dependencies=[Depends(worker_auth)])
    def worker_progress(body: dict = Body(...)):
        turn, pct, done = body.get('turn'), body.get('percent'), body.get('done', False)
        if (isinstance(turn, bool) or not isinstance(turn, int) or isinstance(pct, bool)
                or not isinstance(pct, (int, float)) or not isinstance(done, bool)):
            raise ApiError(400, 'bad_request')
        with session() as ctx:
            ok = S.progress(ctx.st, ctx.info(), turn, pct, done, ctx.now)
            state = build_state(ctx)
            state['accepted'] = ok
            return state

    # ---------- frontend ----------

    @app.get('/{path:path}')
    def frontend(path: str):
        if path.startswith(('api/', 'img/')):
            raise ApiError(404, 'not_found')
        root = static_dir.resolve()
        f = (root / (path or 'index.html')).resolve()
        if f.is_dir():
            f = f / 'index.html'
        if root.is_dir() and f.is_file() and (root == f or root in f.parents):
            return FileResponse(f, headers={'Cache-Control': 'no-cache'})
        if path in ('', 'index.html'):
            return HTMLResponse('<!doctype html><title>Sand table</title><p>frontend not built yet</p>',
                                headers={'Cache-Control': 'no-cache'})
        raise ApiError(404, 'not_found')

    return app


app = create_app()
