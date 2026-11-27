#!/usr/bin/env python3
"""Check the durable garden queue with a simulated clock and controller. No table required."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from garden_playback import PlaybackError, Worker, enqueue, init_schema, status


DOCK = '-1.57080 1.00000'
MID = '-1.57080 0.98000'
SETUP = [{'name':'setup-1.thr', 'text':f'{DOCK}\n{MID}\n'},
         {'name':'setup-2.thr', 'text':f'{MID}\n{DOCK}\n'}]
RING = [{'name':'guest-ring-1.thr', 'text':f'{DOCK}\n-1.55300 0.99000\n{DOCK}\n'}]


class Controller:
    def __init__(self, db):
        self.db = db
        self.calls = []
        self.token, self.outcome = '', 'unknown'
        self.at_dock = True
        self.drop = ''
        self.replace_before_submit = False

    def check(self, part):
        if not self.at_dock:
            raise PlaybackError('The starting position does not match.')

    def play(self, part, token, predecessor=None):
        # A crash could happen even before the response from this method.
        # The other connection must already see durable intent for the exact part.
        with closing(sqlite3.connect(self.db)) as db:
            name, phase = db.execute("""SELECT p.name,j.phase FROM playback_part p JOIN playback_job j
                USING(layout,revision) WHERE p.token=? AND j.part=p.part""", (token,)).fetchone()
            assert name == part['name'] and phase == 'submitted'
        assert all(old != token for (_, old) in self.calls)
        if self.calls:
            assert predecessor == (self.calls[-1][1], self.last_file)
        else:
            assert predecessor is None
        if self.replace_before_submit:
            self.token = 'an-external-drawing'
        if predecessor and self.inspect(*predecessor) != 'complete':
            raise PlaybackError('The controller rejected an outdated predecessor.')
        self.calls.append((part['name'], token))
        self.last_file = part
        if self.drop != 'before':
            self.token, self.outcome = token, 'running'
        if self.drop:
            raise PlaybackError('Lost submission response.')
        return self.outcome

    def inspect(self, token, part):
        return self.outcome if token == self.token else 'unknown'


class QueueTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'garden.db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        with self.db:
            init_schema(self.db)
        self.now = 100.
        self.controller = Controller(self.path)
        self.worker = self.restart()

    def restart(self):
        return Worker(self.path, 'garden', self.controller, clock=lambda: self.now, poll_seconds=.01)

    def view(self):
        return status(self.db, 'garden', self.worker, now=self.now)

    def step(self, seconds=0):
        self.now += seconds
        self.worker.step()
        return status(self.db, 'garden', now=self.now)

    def put(self, number, zone, files):
        with self.db:
            enqueue(self.db, 'garden', number, zone, files)

    def test_multipart_receipts_and_persistent_viewing_time(self):
        self.put(0, 'setup', SETUP)
        self.put(3, 'middle', RING)
        self.step()
        self.worker = self.restart()
        self.assertEqual(self.step(90)['state'], 'drawing')
        self.assertEqual(len(self.controller.calls), 1)
        self.controller.outcome = 'paused'
        self.assertEqual(self.step(30)['state'], 'paused')
        self.controller.outcome = 'complete'
        next_part = self.step()
        self.assertEqual((next_part['part'], next_part['holdSeconds']), (2, 0))
        self.step()
        self.assertEqual([name for name, _ in self.controller.calls], [file['name'] for file in SETUP])
        self.controller.outcome = 'complete'
        held = self.step()
        self.assertEqual((held['state'], held['holdSeconds'], held['queued']), ('hold', 30, 1))
        self.assertEqual(held['lastCompleted'], {'revision':0, 'zone':'setup'})
        self.worker = self.restart()
        self.assertEqual(self.step(29)['holdSeconds'], 1)
        self.assertEqual(len(self.controller.calls), 2)
        self.controller.outcome = 'failed'
        self.assertEqual(self.step(5)['state'], 'blocked')
        self.assertEqual(len(self.controller.calls), 2)
        self.controller.outcome = 'complete'
        self.step()
        self.step()
        self.assertEqual(self.controller.calls[-1][0], RING[0]['name'])
        self.controller.outcome = 'complete'
        self.step()
        self.assertEqual(self.step(30)['lastCompleted'], {'revision':3, 'zone':'middle'})
        self.assertEqual(len(self.controller.calls), 3)

    def test_lost_response_never_replays(self):
        self.put(1, 'outer', RING)
        self.controller.drop = 'before'
        self.assertEqual(self.step()['state'], 'blocked')
        self.worker = self.restart()
        self.assertEqual(self.step(60)['state'], 'blocked')
        token = self.controller.calls[0][1]
        self.controller.token = token
        for outcome in ('staged', 'failed', 'unknown'):
            self.controller.outcome = outcome
            self.assertEqual(self.step()['state'], 'blocked')
        self.assertEqual(len(self.controller.calls), 1)
        self.controller.outcome = 'complete'
        self.assertEqual(self.step()['state'], 'hold')
        self.step(30)
        self.controller.token = 'unrelated-work'
        self.put(2, 'middle', RING)
        self.assertEqual(self.step()['state'], 'blocked')
        self.assertEqual(len(self.controller.calls), 1)

    def test_lost_response_after_acceptance(self):
        self.put(1, 'center', RING)
        self.controller.drop = 'after'
        self.assertEqual(self.step()['state'], 'blocked')
        self.worker = self.restart()
        self.assertEqual(self.step()['state'], 'drawing')
        self.controller.outcome = 'complete'
        self.assertEqual(self.step()['state'], 'hold')
        self.assertEqual(len(self.controller.calls), 1)

    def test_unrelated_motion_between_check_and_submission(self):
        self.put(1, 'setup', SETUP)
        self.step()
        self.controller.outcome = 'complete'
        self.step()
        self.controller.replace_before_submit = True
        self.assertEqual(self.step()['state'], 'blocked')
        self.worker = self.restart()
        self.assertEqual(self.step()['state'], 'blocked')
        self.assertEqual(len(self.controller.calls), 1)

    def test_fifo_joins_transactions_and_layout_isolation(self):
        self.db.execute('CREATE TABLE room(revision INTEGER)')
        self.db.execute('INSERT INTO room VALUES(4)')
        enqueue(self.db, 'garden', 4, 'middle', RING)
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM room').fetchone()[0], 0)
        self.assertEqual(self.step()['state'], 'idle')
        broken = [SETUP[0], dict(SETUP[1], text=f'{DOCK}\n{MID}\n')]
        with self.assertRaises(PlaybackError):
            self.put(1, 'setup', broken)
        self.put(4, 'outer', RING)
        with self.assertRaises(ValueError):
            self.put(3, 'middle', RING)
        with self.db:
            enqueue(self.db, 'portrait', 1, 'center', RING)
        self.controller.at_dock = False
        self.assertEqual(self.step()['state'], 'blocked')
        self.assertFalse(self.controller.calls)
        self.controller.at_dock = True
        self.step()
        self.assertEqual(len(self.controller.calls), 1)
        self.assertEqual(status(self.db, 'portrait')['state'], 'queued')

    def test_ready_requires_live_and_healthy_last_receipt(self):
        self.put(1, 'center', RING)
        self.step()
        self.controller.outcome = 'complete'
        self.step()
        self.step(30)
        self.assertFalse(self.view()['ready'], 'A stopped worker cannot vouch for the device.')
        self.worker.start()
        self.addCleanup(self.worker.stop)
        with self.assertRaises(RuntimeError):
            self.restart().start()

        def wait_for(predicate):
            end = time.monotonic() + 3
            while time.monotonic() < end:
                if predicate(self.view()):
                    return
                time.sleep(.01)
            self.fail(self.view())

        wait_for(lambda s: s['ready'])
        self.controller.outcome = 'paused'
        wait_for(lambda s: s['state'] == 'paused' and not s['ready'])
        self.controller.token = 'external'
        wait_for(lambda s: s['state'] == 'blocked' and not s['ready'])
        self.worker.stop()
        self.assertFalse(self.view()['ready'])
        self.assertEqual(self.view()['lastCompleted']['revision'], 1)


if __name__ == '__main__':
    unittest.main()
