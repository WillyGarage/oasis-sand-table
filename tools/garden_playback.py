"""Durable playback of the ordered motion files from one garden layout."""
from contextlib import closing
import fcntl
import math
from pathlib import Path
import sqlite3
import threading
import time
import uuid
import zlib

from oasis_player import PlaybackError, validate_parts


def init_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS playback_job(
        layout TEXT NOT NULL, revision INTEGER NOT NULL, zone TEXT NOT NULL,
        parts INTEGER NOT NULL, part INTEGER NOT NULL DEFAULT 1, phase TEXT NOT NULL DEFAULT 'queued',
        until REAL NOT NULL DEFAULT 0, problem TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(layout,revision))""")
    db.execute("""CREATE TABLE IF NOT EXISTS playback_part(
        layout TEXT NOT NULL, revision INTEGER NOT NULL, part INTEGER NOT NULL,
        name TEXT NOT NULL, track BLOB NOT NULL, token TEXT NOT NULL,
        PRIMARY KEY(layout,revision,part))""")


def enqueue(db, layout, revision, zone, files):
    """Call inside the room save transaction. Jobs for a layout follow room revision order."""
    validate_parts(files)
    if layout not in ('garden', 'portrait') or type(revision) is not int or revision < 0:
        raise ValueError('Invalid playback layout or revision.')
    allowed = ('setup', 'center', 'outer', 'middle') if layout == 'garden' else ('setup', 'center', 'outer')
    if zone not in allowed:
        raise ValueError('Unknown zone in this layout.')
    latest, = db.execute('SELECT MAX(revision) FROM playback_job WHERE layout=?', (layout,)).fetchone()
    if latest is not None and revision <= latest:
        raise ValueError('A newer or identical drawing is already queued.')
    db.execute('INSERT INTO playback_job(layout,revision,zone,parts) VALUES(?,?,?,?)',
               (layout, revision, zone, len(files)))
    for number, file in enumerate(files, 1):
        db.execute('INSERT INTO playback_part VALUES(?,?,?,?,?,?)',
                   (layout, revision, number, file['name'], zlib.compress(file['text'].encode('ascii'), 1),
                    uuid.uuid4().hex))


def status(db, layout, worker=None, now=None):
    """The oldest unfinished drawing, its viewing time, and the last confirmed finish."""
    now = time.time() if now is None else now
    # A reader can be on a different HTTP thread from either a save or a finish.
    rows = db.execute("""SELECT revision,zone,parts,part,phase,until,problem,reason
                         FROM playback_job WHERE layout=? ORDER BY revision""", (layout,)).fetchall()
    last = next((row for row in reversed(rows) if row[4] in ('hold', 'done')), None)
    pending = [row for row in rows if row[4] != 'done']
    current = pending[0] if pending else last
    result = dict(state='idle', queued=len(pending), drawing=None, part=0, parts=0, holdSeconds=0,
                  lastCompleted={'revision':last[0], 'zone':last[1]} if last else None, ready=False, reason='')
    if current:
        rev, zone, count, part, phase, until, problem, reason = current
        if phase != 'done':
            result.update(drawing={'revision':rev, 'zone':zone}, part=part, parts=count,
                          queued=len(pending) if phase == 'queued' else len(pending)-1,
                          holdSeconds=max(0, math.ceil(until-now)) if phase=='hold' else 0)
        result['state'] = problem or {'ready':'drawing', 'submitted':'drawing', 'done':'idle'}.get(phase, phase)
        result['reason'] = reason
    if worker is not None:
        health, why = worker.health(layout)
        if why:
            result.update(state='blocked', reason=why)
        result['ready'] = bool(last and health == last[0] and not pending and result['state'] == 'idle')
    return result


class Worker:
    def __init__(self, db_path, layout, controller, hold_seconds=30, poll_seconds=1, clock=time.time):
        if not math.isfinite(hold_seconds) or hold_seconds < 0 or not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise ValueError('Invalid hold or poll interval.')
        self.path = Path(db_path).resolve()
        self.layout, self.controller = layout, controller
        self.hold_seconds, self.poll_seconds, self.clock = hold_seconds, poll_seconds, clock
        self._stop = threading.Event()
        self._thread = None
        self._verified = (None, 0.)
        self._error = ''
        self._recent_parts = {}

    def health(self, layout):
        if layout != self.layout or not self._thread or not self._thread.is_alive() or self._stop.is_set():
            return None, 'The playback worker is offline.'
        if self._error:
            return None, self._error
        revision, at = self._verified
        if time.monotonic() - at > max(3 * self.poll_seconds, 3):
            return None, 'Waiting for the table to confirm its position.' if revision is not None else ''
        return revision, ''

    def start(self):
        """Only one worker can own this database, even across two service processes."""
        if self._thread and self._thread.is_alive():
            return self
        lock = self.path.with_name(self.path.name + '.playback.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError('Another playback worker already owns this database.') from None
        self._stop.clear()
        self._verified, self._error = (None, 0.), ''
        self._recent_parts.clear()

        def run():
            with lock:
                while not self._stop.is_set():
                    try:
                        self.step()
                        self._error = ''
                    except sqlite3.Error:
                        self._verified = (None, 0.)
                        self._error = 'Playback storage is unavailable.'
                    self._stop.wait(self.poll_seconds)
        self._thread = threading.Thread(target=run, name='garden-playback', daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Release the worker after its current request. Never interrupt controller motion."""
        self._stop.set()
        if self._thread:
            self._thread.join()

    def _file(self, db, revision, number):
        key = (revision, number)
        if key in self._recent_parts:
            return self._recent_parts[key]
        name, blob, token = db.execute("""SELECT name,track,token FROM playback_part
            WHERE layout=? AND revision=? AND part=?""", (self.layout, revision, number)).fetchone()
        if len(self._recent_parts) == 2:
            del self._recent_parts[next(iter(self._recent_parts))]
        self._recent_parts[key] = {'name':name, 'text':zlib.decompress(blob).decode('ascii')}, token
        return self._recent_parts[key]

    def _problem(self, db, job, issue='', reason=''):
        if issue != job['problem'] or reason != job['reason']:
            with db:
                db.execute('UPDATE playback_job SET problem=?,reason=? WHERE layout=? AND revision=?',
                           (issue, reason, self.layout, job['revision']))

    def _receipt(self, db, job, outcome):
        if outcome == 'paused':
            self._problem(db, job, 'paused', 'The table is paused.')
        elif outcome == 'running' and job['phase'] == 'submitted':
            self._problem(db, job)
        else:
            reasons = {'failed':'The controller reported that the drawing stopped.',
                       'staged':'The file is on the table, but its motion has not been confirmed.'}
            self._problem(db, job, 'blocked', reasons.get(outcome, 'The controller cannot confirm this drawing.'))

    def step(self):
        """One observation or dispatch. The background loop is the sole caller in service."""
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            job = db.execute("""SELECT * FROM playback_job WHERE layout=? AND phase!='done'
                                ORDER BY revision LIMIT 1""", (self.layout,)).fetchone()
            last = db.execute("""SELECT * FROM playback_job WHERE layout=? AND phase='done'
                                 ORDER BY revision DESC LIMIT 1""", (self.layout,)).fetchone()
            if job is None:
                job = last
            if job is None:
                return
            rev, part, phase = job['revision'], job['part'], job['phase']
            file, token = self._file(db, rev, part)
            try:
                if phase in ('queued', 'ready'):
                    self._verified = (None, 0.)
                    # A move between drawings (or files) invalidates the prepared bed.
                    predecessor = None
                    if part > 1 or last is not None:
                        previous = (rev, part-1) if part > 1 else (last['revision'], last['parts'])
                        prior_file, prior_token = self._file(db, *previous)
                        predecessor = (prior_token, prior_file)
                        outcome = self.controller.inspect(prior_token, prior_file)
                        if outcome != 'complete':
                            self._receipt(db, job, outcome)
                            return
                    self.controller.check(file)
                    if self._stop.is_set():
                        return
                    # Commit intent BEFORE the first request that can move anything. A crash
                    # after this commit is indistinguishable from a lost acceptance response.
                    with db:
                        claimed = db.execute("""UPDATE playback_job SET phase='submitted',problem='',reason=''
                            WHERE layout=? AND revision=? AND phase=? AND part=?""",
                                             (self.layout, rev, phase, part)).rowcount
                    if not claimed:
                        return
                    outcome = self.controller.play(file, token, predecessor=predecessor)
                    job = dict(job, phase='submitted', problem='', reason='')
                else:
                    outcome = self.controller.inspect(token, file)
            except PlaybackError as error:
                self._verified = (None, 0.)
                # The intent remains submitted even when the client lost the response.
                with db:
                    db.execute("""UPDATE playback_job SET problem='blocked',reason=?
                        WHERE layout=? AND revision=? AND (problem!='blocked' OR reason!=?)""",
                               (str(error), self.layout, rev, str(error)))
                return

            if outcome != 'complete':
                self._verified = (None, 0.)
                self._receipt(db, job, outcome)
                return
            now = self.clock()
            if phase == 'done':
                self._problem(db, job)
                self._verified = (rev, time.monotonic())
            elif phase == 'hold':
                self._problem(db, job)
                if now >= job['until']:
                    with db:
                        db.execute("UPDATE playback_job SET phase='done' WHERE layout=? AND revision=?",
                                   (self.layout, rev))
                    self._verified = (rev, time.monotonic())
            else:
                with db:
                    if part < job['parts']:
                        db.execute("""UPDATE playback_job SET phase='ready',part=part+1,problem='',reason=''
                                      WHERE layout=? AND revision=?""", (self.layout, rev))
                    else:
                        db.execute("""UPDATE playback_job SET phase='hold',until=?,problem='',reason=''
                                      WHERE layout=? AND revision=?""", (now + self.hold_seconds, self.layout, rev))
                        # Only the latest completed part can still be the physical table's receipt.
                        db.execute("""DELETE FROM playback_part WHERE layout=? AND
                                      (revision<? OR (revision=? AND part<?))""", (self.layout, rev, rev, part))
                        db.execute("DELETE FROM playback_job WHERE layout=? AND revision<? AND phase='done'",
                                   (self.layout, rev))
