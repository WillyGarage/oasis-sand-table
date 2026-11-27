#!/usr/bin/env python3
"""Test the normal capture commands locally with a fake Windows host and camera."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2

import oasislib


TOOLS = Path(__file__).resolve().parent
POWERSHELL = r"""#!/usr/bin/env python3
from pathlib import Path, PureWindowsPath
import os, re, runpy, sys, time
import cv2, numpy as np

root = Path(os.environ['CAMERA_TEST_ROOT'])
mode = os.environ.get('CASE', 'ok')
command = sys.argv[-1]
assert command.endswith('; exit $LASTEXITCODE')
python, reader, idx, out, exposure = (value.replace("''","'") for value in re.findall(r"'((?:[^']|'')*)'",command))
assert PureWindowsPath(python).name == 'python.exe'
def local(path):
    assert PureWindowsPath(path).parts[:-2] == PureWindowsPath(r'C:\Users\bill\AppData\Local\WillyGarage\oasis').parts
    return root.joinpath('windows', *PureWindowsPath(path).parts[-2:])
script, frame = map(local,(reader,out))
assert script.read_bytes() == Path(os.environ['EXPECTED_READER']).read_bytes()
(root/('ready-'+idx)).write_text(str(frame.parent))
if mode == 'no-file': sys.exit(0)
if mode == 'false-success':
    frame.write_bytes(b'incomplete new image')
    sys.exit(7)
if mode == 'parallel':
    deadline = time.monotonic()+15
    while not (root/'release').exists() and time.monotonic()<deadline: time.sleep(.01)
    assert (root/'release').exists()

class Camera:
    def __init__(self, index, backend):
        self.index, self.backend, self.count = index, backend, 0
        (root/('backend-'+idx)).open('a').write(str(backend)+'\n')
    def isOpened(self):
        return mode!='open-error' and not (mode=='fallback' and self.backend==cv2.CAP_MSMF)
    def set(self,key,value):
        if key==cv2.CAP_PROP_EXPOSURE: assert value==float(exposure)
        return True
    def get(self,key):
        if key == cv2.CAP_PROP_EXPOSURE:
            return -6 if mode == 'different-exposure' or exposure == 'auto' else float(exposure)
        if key == cv2.CAP_PROP_WB_TEMPERATURE: return float('nan')
        return 0
    def read(self):
        self.count += 1
        if mode=='read-error' and self.count==20: return False, None
        return True, np.full((25,36,3),self.index*36,dtype='uint8')
    def release(self): pass

cv2.VideoCapture = Camera
if mode=='encode-error': cv2.imencode = lambda *args: (False,None)
time.sleep = lambda _: None
sys.argv = [str(script),idx,str(frame),exposure]
runpy.run_path(str(script),run_name='__main__')
"""


def executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


def wait_file(path):
    deadline = time.monotonic() + 15
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert path.exists(), path


class CameraCapture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        self.windows = self.root/'windows'
        self.windows.mkdir()
        (self.windows/'_camtmp.jpg').write_bytes(b'previous Windows frame')
        self.destination = self.root/'family photo.jpg'
        self.destination.write_bytes(b'previous requested output')
        self.env = dict(os.environ, CAMERA_TEST_ROOT=str(self.root), EXPECTED_READER=str(TOOLS/'cap_win.py'),
                        PATH=str(self.bin)+os.pathsep+os.environ['PATH'])
        executable(self.bin/'powershell',POWERSHELL)
        executable(self.bin/'wslpath',"""#!/bin/sh
case "$2" in
  *powershell.exe) echo "$CAMERA_TEST_ROOT/bin/powershell";;
  *WillyGarage*oasis) echo "$CAMERA_TEST_ROOT/windows";;
  *) exit 90;;
esac
""")
        executable(self.bin/'cp',"""#!/bin/sh
if [ "$CASE" = copy-error ] && [ "${2##*/}" = frame.jpg ]; then
  echo 'half a file' > "$3"
  exit 8
fi
if [ "$CASE" = slow-copy ] && [ "${2##*/}" = frame.jpg ]; then
  head -c 15 "$2" > "$3"
  touch "$CAMERA_TEST_ROOT/copying"
  while [ ! -e "$CAMERA_TEST_ROOT/release" ]; do sleep .02; done
fi
exec /bin/cp "$@"
""")

    def start(self, index, mode='ok', *, output=None, exposure='-3'):
        return subprocess.Popen(['/bin/bash',str(TOOLS/'cam.sh'),str(output or self.destination),str(index)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env,CASE=mode,OASIS_EXP=exposure))

    def finished(self, job, success):
        log, _ = job.communicate(timeout=20)
        self.assertEqual(job.returncode==0,success,log)
        self.assertEqual('saved ' in log,success,log)
        return log

    def test_failure(self):
        for mode in ('open-error','read-error','encode-error','false-success','no-file','copy-error'):
            with self.subTest(mode=mode):
                self.finished(self.start(1,mode), False)
                self.assertEqual(self.destination.read_bytes(),b'previous requested output')
                self.assertEqual(list(self.windows.glob('capture.*')),[])
                self.assertEqual(list(self.root.glob('.oasis-frame.*')),[])
        missing = self.root/'new photo.jpg'
        self.finished(self.start(1,'no-file',output=missing),False)
        self.assertFalse(missing.exists())

    def test_overlap(self):
        other = self.root/'other.jpg'
        a = self.start(1,'parallel',exposure='-4')
        b = self.start(2,'parallel',output=other,exposure='-6')
        try:
            for i in (1,2): wait_file(self.root/f'ready-{i}')
            self.assertNotEqual((self.root/'ready-1').read_text(),(self.root/'ready-2').read_text())
        finally:
            (self.root/'release').touch()
            self.finished(a,True)
            self.finished(b,True)
        self.assertEqual(float(cv2.imread(str(self.destination)).mean()),36)
        self.assertEqual(float(cv2.imread(str(other)).mean()),72)
        self.assertEqual(list(self.windows.glob('capture.*')),[])

    def test_publish(self):
        job = self.start(1,'slow-copy')
        try:
            wait_file(self.root/'copying')
            self.assertEqual(self.destination.read_bytes(),b'previous requested output')
        finally:
            (self.root/'release').touch()
            self.finished(job,True)
        self.assertEqual(float(cv2.imread(str(self.destination)).mean()),36)
        self.finished(self.start(2,'fallback',exposure='auto'),True)
        backends = (self.root/'backend-2').read_text().splitlines()
        self.assertEqual(backends,[str(cv2.CAP_MSMF),str(cv2.CAP_DSHOW)])

    def test_reports_measured_exposure(self):
        log = self.finished(self.start(1, 'different-exposure', exposure='-4'), True)
        record = next(line for line in log.splitlines() if line.startswith('CAMERA '))
        measured = json.loads(record[7:])
        self.assertEqual(measured['exposure'], -6)
        self.assertIsNone(measured['whiteBalance'])

    def test_callers_decline_stale_files(self):
        # HDR reuses exposure filenames. Even a readable old JPEG must not be used.
        with patch.object(oasislib.subprocess,'run',return_value=subprocess.CompletedProcess([],2)), \
             patch.object(oasislib.cv2,'imread') as read:
            self.assertIsNone(oasislib._grab('captures/hdr_m3.jpg','-3'))
            read.assert_not_called()
        # Intercept every hardware command in the calibration script; keep its
        # outputs in the temporary directory and prove the locator never runs.
        (self.root/'captures').mkdir()
        (self.root/'captures/cal_0_0.jpg').write_bytes(b'old calibration photo')
        stubs=self.root/'stubs.sh'
        stubs.write_text('''cd() { builtin cd "$CAMERA_TEST_ROOT"; }
curl() { return 0; }
sleep() { return 0; }
bash() { return 1; }
python3() { touch "$CAMERA_TEST_ROOT/used-locator"; }
''')
        result=subprocess.run(['/bin/bash',str(TOOLS/'calib_collect.sh')],env=dict(self.env,BASH_ENV=str(stubs)))
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'used-locator').exists())
        self.assertEqual((self.root/'captures/calib.jsonl').read_text(),'')

    def test_missing_exposures_restore_display_light(self):
        with patch.object(oasislib, 'snap'), patch.object(oasislib, '_grab', return_value=None), \
             patch.object(oasislib.time, 'sleep'), patch.object(oasislib, 'photo_mode', return_value=('day', 0)), \
             patch.object(oasislib, 'light_restore') as restore:
            with self.assertRaisesRegex(RuntimeError, 'No usable exposures'):
                oasislib.portrait(str(self.destination))
        restore.assert_called_once_with()
        self.assertEqual(self.destination.read_bytes(), b'previous requested output')

    def test_unsaved_portrait_restores_display_light(self):
        with patch.object(oasislib, 'snap_hdr'), patch.object(oasislib, 'topdown_true'), \
             patch.object(oasislib.cv2, 'imwrite', return_value=False), patch.object(oasislib, 'light_restore') as restore:
            with self.assertRaisesRegex(OSError, 'Could not save sand photograph'):
                oasislib.portrait(str(self.destination))
        restore.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
