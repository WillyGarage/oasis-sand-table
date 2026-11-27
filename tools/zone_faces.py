"""Face library for the table-option mockups (simulation only). Splits .oasisportrait files into single people
and draws each as outline strokes at any head size, so small faces keep 4 mm lines."""
import json, math, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path):
    return json.load(open(os.path.join(ROOT, path)))['marks']


def split_people(path):
    """Return a list of persons, each a list of (kind, closed, points) around one head."""
    marks = _load(path)
    heads = [np.array(m['points'], float) for m in marks if m['kind'] == 'head']
    boxes = [(h.min(0), h.max(0)) for h in heads]
    people = [[] for _ in heads]
    for m in marks:
        pts = np.array(m['points'], float)
        c = pts.mean(0)
        best, bd = 0, 1e18
        for i, (lo, hi) in enumerate(boxes):
            ctr = (lo + hi) / 2
            inside = np.all(c > lo - 0.35 * (hi - lo)) and np.all(c < hi + 0.35 * (hi - lo))
            d = np.hypot(*(c - ctr)) - (1e6 if inside else 0)
            if d < bd:
                best, bd = i, d
        people[best].append((m['kind'], bool(m.get('closed')), pts))
    return people


def person_paths(marks, head_h, shade=True, y_flip=True):
    """Marks -> strokes (mm), centred on the head, head height scaled to head_h. y is flipped when the source is y down."""
    allp = np.vstack([p for k, c, p in marks if k == 'head'])
    lo, hi = allp.min(0), allp.max(0)
    ctr = (lo + hi) / 2
    s = head_h / (hi[1] - lo[1])
    out = []
    for k, c, p in marks:
        if k == 'shade' and not shade:
            continue
        q = (p - ctr) * s
        if y_flip:
            q[:, 1] *= -1
        if c:
            q = np.vstack([q, q[:1]])
        out.append(q)
    return out


LIB = {
    'alex': ('patterns/guest-rings/alex-wide-brows.oasisportrait', 0),
    'lek': ('patterns/guest-rings/lek-group-wide-smile.oasisportrait', 0),
    'thomas': ('patterns/guest-rings/thomas-wide-nose.oasisportrait', 0),
    'bill': ('captures/bill-portrait-glasses/verified/redwood-pair-0/new/portrait.oasisportrait', 0),
}
for i in range(4):
    LIB['crew%d' % (i + 1)] = ('captures/four-in-the-center/crew-four-ordinary/portrait.oasisportrait', i)
    LIB['family%d' % (i + 1)] = ('patterns/portrait-gallery/drawings/four-faces-together-engraved.oasisportrait', i)
for i in range(3):
    LIB['dinner%d' % (i + 1)] = ('patterns/portrait-gallery/drawings/three-at-dinner-engraved.oasisportrait', i)
LIB['mom'] = ('captures/cropped-crown/mom/grain-1.0/portrait.oasisportrait', 0)

_cache = {}


def person(key):
    path, idx = LIB[key]
    if path not in _cache:
        _cache[path] = split_people(path)
    return _cache[path][idx]
