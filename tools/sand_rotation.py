#!/usr/bin/env python3
"""Rotation simulation for the equal-zones table. SIMULATION ONLY. Pure python, no table, no drawing.

Two pointers walk one circle of P people, one step per (centre job + slice job). The centre pointer runs d places ahead
of the slice pointer.  Centre job: the person at the centre pointer is featured (the previous centre person leaves the
table).  Slice job: the oldest slice is wiped and the person at the slice pointer is drawn into it.
"""
from collections import deque


def pick_d(P, n):
    d = int((P - n + 1) / 2.0 + 0.5)          # round half up
    return max(2, min(d, P - n - 1))


def rotate(R, n, d=None, minutes=300.0, cj=13.6, sj=8.0, c0=1, newcomers=None, clamp=True):
    """R: list of person ids in circle order. n: slices. Returns dict with events and per-person results.
    newcomers: list of (pair_index, id). A newcomer joins just before that pair, behind every newcomer not yet
    featured but ahead of everyone already featured."""
    R = list(R)
    P = len(R)
    if clamp:
        n = max(0, min(n, P - 3))
    d = d or (pick_d(P, n) if clamp else int((P - n + 1) / 2.0 + 0.5))
    c = c0 % P
    s = (c - d) % P
    centre = R[(c - 1) % P]
    slices = [R[(s - n + k) % P] for k in range(n)]
    events, dups = [], []
    t_now, t = 0.0, 0
    appear = {centre: 0.0}
    appear.update({p: 0.0 for p in slices})
    mins = {}
    ctn, stn = {}, {}
    q = 0

    def leave(p, when):
        a = appear.pop(p, None)
        if a is None:
            return
        mins[p] = mins.get(p, 0.0) + max(0.0, min(when, minutes) - min(a, minutes))

    def check(tag):
        tab = [centre] + slices
        if len(set(tab)) != len(tab):
            dups.append((t, tag, sorted(x for x in set(tab) if tab.count(x) > 1)))

    while t_now < minutes:
        for nt, nid in (newcomers or []):
            if nt == t:
                pos = (c + q) % P
                if pos == 0 and q:
                    pos = P
                R.insert(pos, nid)
                if pos != P:
                    if s >= pos:
                        s += 1
                    if c > pos:
                        c += 1
                P += 1
                q += 1
        # centre job
        out, new = centre, R[c % P]
        if q:
            q -= 1
        events.append(dict(t=t, kind='centre', who=new, out=out, start=t_now, end=t_now + cj))
        # the person who was in the middle leaves when the wipe starts
        leave(out, t_now)
        # during the job the middle is empty; the new person shows when the job ends
        centre = new
        check('centre')
        appear[new] = t_now + cj
        ctn[new] = ctn.get(new, 0) + 1
        t_now += cj
        c = (c + 1) % P
        if n:
            k = t % n
            out, new = slices[k], R[s % P]
            events.append(dict(t=t, kind='slice', slot=k, who=new, out=out, start=t_now, end=t_now + sj))
            leave(out, t_now)
            slices[k] = new
            check('slice')
            appear[new] = t_now + sj
            stn[new] = stn.get(new, 0) + 1
            t_now += sj
            s = (s + 1) % P
        t += 1
    for p in list(appear):
        leave(p, minutes)
    return dict(R=R, P=P, n=n, d=d, events=events, dups=dups, centre_turns=ctn, slice_turns=stn, minutes=mins,
                final=(centre, list(slices)))


def check_newcomers(res, newcomers):
    """Each newcomer is featured in join order, and the only people featured between joining and their own turn
    are newcomers who joined earlier (so nobody gets a second middle turn first)."""
    ev = [e for e in res['events'] if e['kind'] == 'centre']
    seq = [e['who'] for e in ev]
    ids = [i for _, i in sorted(newcomers)]
    when = {}
    for nid in ids:
        when[nid] = seq.index(nid) if nid in seq else None
    ok = all(when[i] is not None for i in ids) and [when[i] for i in ids] == sorted(when[i] for i in ids)
    for (nt, nid) in sorted(newcomers):
        if when[nid] is None:
            continue
        between = seq[nt:when[nid]]
        earlier = {i for (t2, i) in newcomers if (t2, i) < (nt, nid)}
        if any(b not in earlier for b in between):
            ok = False
    return ok, {i: when[i] for i in ids}


def summary(res, everyone):
    ct = [res['centre_turns'].get(p, 0) for p in everyone]
    st = [res['slice_turns'].get(p, 0) for p in everyone]
    mn = [res['minutes'].get(p, 0.0) for p in everyone]
    return dict(dups=len(res['dups']), max_gap=max(abs(a - b) for a, b in zip(ct, st)),
                c_range=(min(ct), max(ct)), s_range=(min(st), max(st)), m_range=(min(mn), max(mn)),
                ct=ct, st=st, mn=mn)


if __name__ == '__main__':
    for P in (12, 13, 14, 20):
        for mins in (300, 3600):
            r = rotate(range(P), 10, minutes=mins)
            sm = summary(r, list(range(P)))
            print(P, 'd', r['d'], mins, 'dups', sm['dups'], 'gap', sm['max_gap'], sm['c_range'], sm['s_range'])
    nw = [(2, 'A'), (3, 'B'), (9, 'C'), (14, 'D')]
    r = rotate(range(14), 10, newcomers=nw, cj=7.6, sj=7.4)
    print('newcomers dups', len(r['dups']), check_newcomers(r, nw))
    r = rotate(range(8), 10)
    print('P=8 n', r['n'], 'dups', len(r['dups']))
    r = rotate(range(12), 10, clamp=False)
    print('P=12 forced 10 slices: d', r['d'], 'dups', len(r['dups']), r['dups'][:2])
    r = rotate(range(13), 10, d=3, clamp=False)
    print('P=13 d=3 forced: dups', len(r['dups']))
