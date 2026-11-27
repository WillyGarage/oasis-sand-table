#!/usr/bin/env python3
"""Eye and nose finder for front-facing animal photos (simulation tooling; works on the source photo only).
OpenCV's haarcascade_frontalcatface gives the face box; inside it the eyes are the two strongest light blobs on a dark face
(difference of Gaussians, one per side of the box centre) and the nose is the strongest dark blob below them near the middle.
Returns dict(box, eyes=[(x, y, r), (x, y, r)], nose=(x, y, r)) in source pixels, or None."""
import cv2, numpy as np

def find_face(g):
    c = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalcatface_extended.xml')
    best = None
    for sf, mn in ((1.05, 3), (1.1, 2), (1.03, 2)):
        r = c.detectMultiScale(g, sf, mn, minSize=(int(0.08 * max(g.shape)),) * 2)
        for b in r:
            if best is None or b[2] > best[2]: best = tuple(int(v) for v in b)
        if best is not None: break
    return best

def blobs(g, box, sign, y0, y1, x0=0.0, x1=1.0, s=None):
    x, y, w, h = box; s = s or 0.035 * w
    f = g.astype(np.float32); dog = sign * (cv2.GaussianBlur(f, (0, 0), s) - cv2.GaussianBlur(f, (0, 0), 3.2 * s))
    m = np.zeros(g.shape, bool); m[int(y + y0 * h):int(y + y1 * h), int(x + x0 * w):int(x + x1 * w)] = True
    return dog, m

def detect(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); box = find_face(g)
    if box is None: return None
    x, y, w, h = box; cx = x + w / 2
    dog, m = blobs(g, box, +1, 0.30, 0.55, s=0.022 * w)
    eyes = []
    for lo, hi in ((0.05, 0.5), (0.5, 0.95)):                    # left and right half of the face box
        mm = m.copy(); mm[:, :int(x + lo * w)] = False; mm[:, int(x + hi * w):] = False
        d = np.where(mm, dog, -1e9); iy, ix = np.unravel_index(int(np.argmax(d)), d.shape)
        eyes.append((float(ix), float(iy), 0.07 * w))
    dog, m = blobs(g, box, -1, 0.45, 0.80, 0.3, 0.7, 0.05 * w)
    d = np.where(m, dog, -1e9); iy, ix = np.unravel_index(int(np.argmax(d)), d.shape)
    return dict(box=box, eyes=eyes, nose=(float(ix), float(iy), 0.06 * w))

if __name__ == '__main__':
    import sys
    img = cv2.imread(sys.argv[1]); r = detect(img); print(r)
    if r:
        x, y, w, h = r['box']; cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 0), 6)
        for ex, ey, er in r['eyes']: cv2.circle(img, (int(ex), int(ey)), int(er), (0, 0, 255), 6)
        nx, ny, nr = r['nose']; cv2.circle(img, (int(nx), int(ny)), int(nr), (255, 0, 0), 6)
        cv2.imwrite(sys.argv[2], cv2.resize(img, None, fx=0.35, fy=0.35))
