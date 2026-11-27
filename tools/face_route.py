#!/usr/bin/env python3
"""Touring a face drawing on the 36-inch table without stray lines into the face.

    face_walk(strokes, entry, kind='face', hop=HOP_MM) -> [(kind, polyline)]      (same contract as sand_update_plan.item_walk)

Why (2026-11-26): sand_update_plan.item_walk enters an OPEN stroke only at one of its two ends, prices a straight bridge at
6 x its length against retracing, and forgets every stroke it has retraced past.  A face from the app's face_art has
isolated features (eyes, nose, mouth, beard lines) whose ends are the mouth and eye corners, and neck lines that stop a
ball width short of the jaw.  So the tour bridges from the neck's top end across the chin into a mouth corner (Bill's
photos: "an entry or exit line that goes from the mouth"), and on from the mouth corners down to the beard and neck lines
(the centre face); the final retrace back to the entry runs over the same bridges a second time.

Here:
  * everything drawn so far is a graph; the ball moves between strokes along it (shortest retrace, Dijkstra), so no
    drawn line is ever out of reach;
  * a stroke can be entered at ANY of its points; an open stroke entered in the middle is drawn as two halves (out to
    the nearer end, back along itself, out to the other end);
  * hops up to `hop` (about 0.6 of a groove: they vanish inside the two grooves they join) cost only a little;
    longer hops ('bridge') are taken only when nothing else remains, the shortest first;
  * the tour ends back at `entry`.
Pair it with tools/face_small.py, whose parts are built to touch.  Pure numpy/scipy: runs in the driver's python.
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

HOP_MM = 5.7              # design mm (x 375/355 = 6 mm on the table), about 0.6 of the measured 10 mm groove
TOUCH = 0.6               # design mm: points of different strokes this close are joined in the graph
FAR = 1e5


class _Graph:
    def __init__(self, p0):
        self.P = [np.asarray(p0, float)]
        self.E = []                                   # (i, j, w)

    def add_path(self, pl, start_node):
        """append a drawn polyline that starts at node `start_node`; returns the node index of its last point"""
        prev = start_node
        old = np.array(self.P)
        tree = cKDTree(old) if len(old) > 1 else None
        for q in pl[1:]:
            self.P.append(np.asarray(q, float))
            i = len(self.P) - 1
            self.E.append((prev, i, float(np.hypot(*(self.P[prev] - q)))))
            if tree is not None:
                for j in tree.query_ball_point(q, TOUCH):
                    if j != prev:
                        self.E.append((j, i, float(np.hypot(*(old[j] - q)))))
            prev = i
        return prev

    def solve(self, src):
        n = len(self.P)
        if not self.E:
            return np.r_[0.0, np.full(n - 1, np.inf)], np.full(n, -9999)
        a = np.array(self.E)
        i, j, w = a[:, 0].astype(int), a[:, 1].astype(int), np.maximum(a[:, 2], 1e-6)
        m = coo_matrix((np.r_[w, w], (np.r_[i, j], np.r_[j, i])), shape=(n, n)).tocsr()
        return dijkstra(m, indices=src, return_predecessors=True)

    def path(self, pred, src, dst):
        out = [dst]
        while out[-1] != src:
            out.append(int(pred[out[-1]]))
        return np.array([self.P[k] for k in out[::-1]])


def _dens(pl, step):
    pl = np.asarray(pl, float)
    out = [pl[:1]]
    for a, b in zip(pl[:-1], pl[1:]):
        n = max(1, int(np.ceil(np.hypot(*(b - a)) / step)))
        out.append(a + (b - a) * (np.arange(1, n + 1)[:, None] / n))
    return np.vstack(out)


def face_walk(strokes, entry, kind='face', hop=HOP_MM, step=1.0):
    entry = np.asarray(entry, float)
    # dense points (the centre's strokes come simplified, with long straight runs): hops and joins are measured point
    # to point, so a stroke that touches the middle of a long segment must see a point there
    todo = [_dens(s, step) for s in strokes if len(s) >= 2]
    g = _Graph(entry)
    cur = 0
    seq = []
    while todo:
        dist, pred = g.solve(cur)
        P = np.array(g.P)
        tree = cKDTree(P)
        best = None
        for j, s in enumerate(todo):
            dd, kk = tree.query(s, k=min(6, len(P)))
            if dd.ndim == 1:
                dd, kk = dd[:, None], kk[:, None]
            back = dist[kk]
            cost = np.where(dd <= hop, back + 2.0 * dd, FAR + 50.0 * dd + back)
            e, m = np.unravel_index(int(np.argmin(cost)), cost.shape)
            c = float(cost[e, m])
            if best is None or c < best[0]:
                best = (c, j, int(e), int(kk[e, m]), float(dd[e, m]))
        _, j, e, k, d = best
        s = todo.pop(j)
        if k != cur:
            seq.append(('retrace', g.path(pred, cur, k)))
        node = k
        if d > 1e-6:
            hp = np.array([g.P[k], s[e]])
            seq.append(('bridge' if d > hop else kind, hp))
            node = g.add_path(hp, k)
        closed = np.hypot(*(s[0] - s[-1])) < 1.2
        if closed:
            loop = np.vstack([s[e:], s[1:e + 1]]) if e > 0 else s
            seq.append((kind, loop))
            cur = g.add_path(loop, node)
        elif e == 0 or e == len(s) - 1:
            p = s if e == 0 else s[::-1]
            seq.append((kind, p))
            cur = g.add_path(p, node)
        else:
            a, b = s[:e + 1][::-1], s[e:]                         # two halves from the entry point
            first, second = (a, b) if len(a) <= len(b) else (b, a)
            seq.append((kind, first))
            g.add_path(first, node)
            seq.append(('retrace', first[::-1]))
            seq.append((kind, second))
            cur = g.add_path(second, node)
    if cur != 0:
        dist, pred = g.solve(cur)
        seq.append(('retrace', g.path(pred, cur, 0)))
    # drop zero-length pieces, keep the path continuous
    return [(k_, pl) for k_, pl in seq if len(pl) >= 2]


def walk_report(seq, hop=HOP_MM):
    """-> dict(bridges=[lengths of hops longer than `hop`], retrace_mm, drawn_mm) in design mm"""
    L = lambda pl: float(np.hypot(*np.diff(pl, axis=0).T).sum())
    return dict(bridges=[round(L(pl), 1) for k, pl in seq if k == 'bridge'],
                retrace_mm=round(sum(L(pl) for k, pl in seq if k == 'retrace'), 1),
                drawn_mm=round(sum(L(pl) for k, pl in seq if k not in ('retrace', 'bridge')), 1))
