import os
import tempfile

# server.app builds a module-level app on import; keep its data out of the repo
os.environ.setdefault('SAND_DATA', tempfile.mkdtemp(prefix='sand-test-import-'))

# tests want the face drawing finished when the upload answers; test_api has its own tests for the background path
os.environ.setdefault('SAND_FACE_SYNC', '1')
