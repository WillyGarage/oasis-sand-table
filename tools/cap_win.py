"""Capture a Windows camera frame: cap_win.py [INDEX [OUTPUT [EXPOSURE|auto]]]."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

import cv2


def capture(index, output, exposure):
    manual = exposure != 'auto'
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW if manual else cv2.CAP_MSMF)
    try:
        if not manual and not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise RuntimeError(f'Could not open camera {index}.')
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        if manual:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
            cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
        for _ in range(20):
            ok, frame = cap.read()
            time.sleep(.05)
        if not ok or frame is None:
            raise RuntimeError(f'Could not read camera {index}.')
        settings = {}
        for name, prop in (
                ('exposure', cv2.CAP_PROP_EXPOSURE), ('autoExposure', cv2.CAP_PROP_AUTO_EXPOSURE),
                ('gain', cv2.CAP_PROP_GAIN), ('autoWB', cv2.CAP_PROP_AUTO_WB),
                ('whiteBalance', cv2.CAP_PROP_WB_TEMPERATURE)):
            value = cap.get(prop)
            settings[name] = value if math.isfinite(value) else None
    finally:
        cap.release()

    ok, encoded = cv2.imencode(output.suffix, frame)
    if not ok or encoded is None or not len(encoded):
        raise RuntimeError(f'Could not encode the frame as {output.suffix}.')
    fd, temporary = tempfile.mkstemp(prefix='.oasis-frame-', dir=output.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(encoded)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print('CAMERA ' + json.dumps(settings))
    print('OK', index, frame.shape)


if __name__ == '__main__':
    try:
        capture(int(sys.argv[1]) if len(sys.argv) > 1 else 0,
                Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r'C:\Users\bill\AppData\Local\WillyGarage\oasis\cam.jpg'),
                sys.argv[3] if len(sys.argv) > 3 else '-3')
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        sys.exit(f'Capture failed: {error}')
