"""face_art: a real face crop gives a drawing inside the unit square within the caps; bad input never raises."""
import io
import os

import pytest

pytest.importorskip('mediapipe')
np = pytest.importorskip('numpy')
Image = pytest.importorskip('PIL.Image')

from server import face_art  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
CANDIDATES = [os.path.join(ROOT, 'captures', 'photo2sand_test', n) for n in ('huffman.jpg', 'koch.jpg', 'ohara.jpg')]


def _crop_bytes():
    for p in CANDIDATES:
        if os.path.exists(p):
            im = Image.open(p).convert('RGB')
            s = min(im.size)
            im = im.crop(((im.width - s) // 2, 0, (im.width - s) // 2 + s, s)).resize((640, 640))
            b = io.BytesIO(); im.save(b, 'JPEG', quality=90)
            return b.getvalue()
    pytest.skip('no test photo available')


def test_real_face():
    r = face_art.face_strokes(_crop_bytes())
    assert r['ok'], r['note']
    st = r['strokes']
    assert 0 < len(st) <= face_art.MAX_STROKES
    assert sum(len(s) for s in st) <= face_art.MAX_POINTS
    pts = np.array([p for s in st for p in s], float)
    assert pts.min() >= 0.0 and pts.max() <= 1.0
    assert np.ptp(pts[:, 1]) > 0.8                    # fills most of the square


@pytest.mark.parametrize('data', [b'', b'not an image at all', b'\xff\xd8\xff\xe0garbage'])
def test_garbage(data):
    r = face_art.face_strokes(data)
    assert r['ok'] is False and r['strokes'] == [] and r['note']


def test_blank_image():
    b = io.BytesIO(); Image.new('RGB', (600, 600), (232, 220, 184)).save(b, 'JPEG')
    r = face_art.face_strokes(b.getvalue())
    assert r['ok'] is False and r['strokes'] == []
