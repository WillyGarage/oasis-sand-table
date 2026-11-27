#!/usr/bin/env python3
"""Exercise actual adapter HTTP requests and recovery on a loopback-only controller."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from oasis_player import OasisPlayer, PlaybackError, RecordedPart, points, validate_parts


A = {'name':'rim-1.thr', 'text':'0 1\n0.05 1\n'}
B = {'name':'rim-2.thr', 'text':'6.33318531 1\n6.38318531 1\n'}


class Controller:
    def reset(self):
        self.s = dict(state='idle', theta=0, rho=1, receipt=dict(state='none',id=''), homed=1, paused=0,
                      auto=0, boot_pending=0, fault=0, queue=[], device_id='52'*12, cal={'th0':0.37},
                      home_steps=10700, steps_rev=10240)
        self.g = dict(rev='22',evolving=False,pending=False)
        self.hook = None
        self.drop = ''
        self.end = (0, 1)

    def finished(self):
        self.s.update(state='idle',theta=self.end[0],rho=self.end[1])
        self.s['receipt']['state'] = 'complete'


@contextmanager
def controller():
    box = Controller()
    box.reset()
    box.calls = []
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, code=200):
            self.send_response(code)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            box.calls.append((self.path, None))
            self.reply(box.s if self.path == '/status' else box.g)

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get('Content-Length','0')))
            box.calls.append((self.path, data))
            receipt = box.s['receipt']
            if box.hook:
                hook, box.hook = box.hook, None
                hook(box)
            if self.headers.get('X-Oasis-Device') != box.s['device_id']:
                return self.reply('different controller', 409)
            rid = self.headers['X-Oasis-Run']
            if self.path == '/thr':
                previous = self.headers.get('X-Oasis-Previous')
                if (self.headers.get('X-Guest-Rev') != box.g['rev'] or
                        (previous and box.s['receipt'] != {'state':'complete','id':previous})):
                    return self.reply('revision changed',409)
                _, box.end, count = points({'name':'upload.thr','text':data.decode()})
                box.s['receipt'] = dict(id=rid,state='staged')
                result = {'points':count,'skipped':0}
            elif self.path == '/play' and receipt == dict(id=rid,state='staged'):
                box.s['state'] = 'drawing'
                receipt['state'] = 'running'
                result = 'started'
            else:
                return self.reply('unowned buffer',409)
            if box.drop == self.path:
                box.drop = ''
                self.close_connection = True
            else:
                self.reply(result)

        def log_message(self, *args):
            pass
    with ThreadingHTTPServer(('127.0.0.1',0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield box, f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


class PlayerTest(unittest.TestCase):
    def test_order_and_identity(self):
        validate_parts([A,B])
        with controller() as (box, url):
            player = OasisPlayer(url)
            identity = player.bind_identity()
            self.assertEqual(len(identity),89)
            player.check(A)
            self.assertEqual(player.play(A,'one'), 'running')
            box.finished()
            self.assertEqual(player.inspect('one',A),'complete')
            resumed = OasisPlayer(url)
            resumed.bind_identity(identity)
            self.assertEqual(resumed.play(A,'one'),'complete')
            self.assertEqual(resumed.play(B,'two',predecessor=('one',A)),'running')
            box.finished()
            self.assertEqual(resumed.inspect('two',B),'complete')
            self.assertEqual(resumed.inspect('one',A),'unknown')
            writes = [(p,b) for p,b in box.calls if b is not None]
            self.assertEqual(writes,[('/thr',A['text'].encode()),('/play',b''),('/thr',B['text'].encode()),('/play',b'')])
            for i,(path,_) in enumerate(box.calls):
                if path == '/play':
                    self.assertEqual([p for p,_ in box.calls[i-2:i]],['/guest-state','/status'])
                    self.assertEqual([p for p,_ in box.calls[i+1:i+3]],['/guest-state','/status'])
            box.s['cal']['th0'] += .01
            with self.assertRaises(PlaybackError):
                resumed.inspect('two',B)
            box.s['cal']['th0'] -= .01
            box.s['device_id'] = '39'*12
            with self.assertRaises(PlaybackError):
                resumed.inspect('two',B)

    def test_gates(self):
        with controller() as (box,url):
            player = OasisPlayer(url)
            for field, bad in [('fault',1),('auto',1),('boot_pending',1),('homed',0),('state','moving'),
                               ('paused',1),('queue',['check']),('theta',.2),('rho',.98)]:
                with self.subTest(field=field):
                    original,box.s[field] = box.s[field],bad
                    with self.assertRaises(PlaybackError): player.play(A,'rejected')
                    box.s[field] = original
            for flag in ('evolving','pending'):
                box.g[flag] = True
                with self.assertRaises(PlaybackError): player.play(A,'rejected')
                box.g[flag] = False
            del box.s['receipt']
            with self.assertRaises(PlaybackError): player.play(A,'old-firmware')
            self.assertFalse(any(body is not None for _,body in box.calls))
        with self.assertRaises(PlaybackError): validate_parts([A,dict(B,text='0.1 1\n0.2 1\n')])
        with self.assertRaises(PlaybackError): validate_parts([A,A])

    def test_interruption_and_reboot(self):
        with controller() as (box,url):
            player = OasisPlayer(url)
            box.drop = '/thr'
            self.assertEqual(player.play(A,'lost-upload'),'staged')
            self.assertEqual(player.play(A,'lost-upload'),'staged')
            self.assertFalse(any(p == '/play' for p,_ in box.calls))
            box.reset()
            self.assertEqual(player.play(A,'lost-upload'),'unknown')
            box.drop = '/play'
            self.assertEqual(player.play(A,'lost-play'),'running')
            self.assertEqual(OasisPlayer(url).inspect('lost-play',A),'running')
            box.s['paused'] = 1
            self.assertEqual(player.inspect('lost-play',A),'paused')
            box.s['paused'] = 0
            box.finished()
            box.s['rho'] = .6
            self.assertEqual(player.inspect('lost-play',A),'failed')
            box.s['rho'] = 1
            box.g['evolving'] = True
            self.assertEqual(player.inspect('lost-play',A),'failed')
            box.reset()
            box.s.update(theta=.05,progress=1,index=2,total=2)   # unrelated old idle drawing at the same place
            self.assertEqual(player.inspect('lost-play',A),'unknown')
            self.assertEqual(sum(p == '/play' for p,_ in box.calls),1)

    def test_intervening_move_at_same_dock(self):
        with controller() as (box,url):
            player = OasisPlayer(url)
            player.play(A,'a')
            box.finished()
            def external(box):
                box.s['receipt'] = {'state':'none','id':''}
            box.hook = external
            with self.assertRaises(PlaybackError):
                player.play(B,'b',predecessor=('a',A))
            self.assertEqual(sum(p == '/play' for p,_ in box.calls),1)

    def test_follow_phone_drawing(self):
        phone_receipt = 'da13' * 16
        prior = RecordedPart(phone_receipt, A)
        with controller() as (box, url):
            player = OasisPlayer(url)
            box.s.update(theta=.05, index=1, total=2, receipt=dict(id=phone_receipt, state='complete'))
            with self.assertRaises(PlaybackError):
                player.play(B, 'after-phone', prior)
            box.s['index'] = 2
            for other in ('invalid', 'ff' * 32):
                with self.assertRaises(PlaybackError):
                    player.play(B, 'after-phone', RecordedPart(other, A))
            self.assertFalse(any(body is not None for _, body in box.calls))
            box.hook = lambda table: table.s.update(receipt=dict(state='complete', id='aa' * 32))
            with self.assertRaises(PlaybackError):
                player.play(B, 'lost-race', prior)
            self.assertFalse(any(path == '/play' for path, _ in box.calls))
            box.s['receipt']['id'] = phone_receipt
            self.assertEqual(player.play(B, 'after-phone', prior), 'running')
            self.assertEqual(player.play(B, 'after-phone', prior), 'running')
            self.assertEqual(sum(path == '/play' for path, _ in box.calls), 1)


if __name__ == '__main__':
    unittest.main()
