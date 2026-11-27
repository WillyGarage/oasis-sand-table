"""Concurrent phones share one illustration and can retry a failed rendering."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
import unittest
from unittest.mock import patch

from garden_room import PhraseBusy, PhrasePreviews


PNG = b'\x89PNG\r\n\x1a\n'


class PhonePreviews(unittest.TestCase):
    def test_shared_request_and_cached_subject_while_other_subject_is_busy(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                active, joined, finish = Event(), Event(), Event()
                calls = []

                class ObservedRequest(Future):
                    def result(self, timeout=None):
                        if not self.done():
                            joined.set()
                        return super().result(timeout)

                def render(subject):
                    calls.append(subject)
                    if calls == ['rose', 'fork']:
                        active.set()
                        if not finish.wait(3):
                            raise TimeoutError('Test did not release the renderer')
                        if fail:
                            raise ValueError('Render failed')
                    return PNG + subject.encode()

                previews = PhrasePreviews(render)
                with patch('garden_room.Future', ObservedRequest), ThreadPoolExecutor(2) as pool:
                    rose = previews('rose')
                    first = pool.submit(previews, 'fork')
                    try:
                        self.assertTrue(active.wait(2))
                        second = pool.submit(previews, 'fork')
                        self.assertTrue(joined.wait(2))
                        self.assertEqual(previews('rose'), rose)
                        with self.assertRaises(PhraseBusy):
                            previews('rake')
                    finally:
                        finish.set()
                    for result in (first, second):
                        if fail:
                            with self.assertRaisesRegex(ValueError, 'Render failed'):
                                result.result(timeout=2)
                        else:
                            self.assertEqual(result.result(timeout=2), PNG + b'fork')
                    self.assertEqual(previews('fork'), PNG + b'fork')
                    self.assertEqual(calls, ['rose', 'fork'] + (['fork'] if fail else []))

    def test_limit_recent_drawings_and_return_large_images_without_retaining_them(self):
        calls = []

        def render(word):
            calls.append(word)
            return PNG + (bytes(1024*1024) if word == 'large' else word.encode())

        previews = PhrasePreviews(render)
        for i in range(16):
            previews(str(i))
        previews('0')
        previews('16')
        previews('1')
        self.assertEqual(calls.count('0'), 1)
        self.assertEqual(calls.count('1'), 2)
        self.assertEqual(previews('large'), previews('large'))
        self.assertEqual(calls.count('large'), 2)


if __name__ == '__main__':
    unittest.main()
