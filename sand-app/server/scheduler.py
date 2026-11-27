"""Pure rotation logic for the sand table. No I/O, no clock reads: time is passed in.

State is a plain JSON-able dict (see new_state). `info` is a dict
{person_id: {"name": str, "faces": int, "interests": [interest_id, ...]}} supplied by the caller.
"""
import copy
import re

ZONES = ['centre'] + ['inner-%d' % i for i in range(1, 5)] + ['outer-%d' % i for i in range(1, 7)]
SLICES = ZONES[1:]
# empty slices are filled in this spread-out order
FILL_ORDER = ['inner-1', 'outer-1', 'inner-2', 'outer-3', 'inner-3', 'outer-4', 'inner-4', 'outer-6', 'outer-2', 'outer-5']

MAX_CATCHUP = 50
TABLE_CLOCK_SECONDS = 120
CLEAR_FRACTION = 0.4
CENTRE_HOLD_SECONDS = 60
CLEAR_STEPS = ['Clearing a spot']
RINGS = ('interests', 'faces', 'leaves', 'wheat', 'lotus', 'waves')

# step name, weight in percent (clearing 0-30, name 30-45, face 45-75, interests 75-100)
_STEP_WEIGHTS = {'clear': 30, 'name': 15, 'face': 30, 'interests': 25}


# ---------- fuzzy interest match (port of key()/same() in tools/sand_app_mockup.py) ----------

STOP = {'movie', 'movies', 'film', 'films', 'the', 'playing', 'play', 'a', 'and'}


def key(label):
    words = re.sub(r'[^a-z0-9 ]', ' ', label.lower()).split()
    out = []
    for w in words:
        if not w or w in STOP:
            continue
        out.append(w[:-1] if w.endswith('s') else w)
    return ' '.join(out)


def same(a, b):
    x, y = key(a), key(b)
    if not x or not y:
        return False
    if x == y:
        return True
    xs, ys = x.split(' '), y.split(' ')
    sm, lg = (xs, ys) if len(xs) <= len(ys) else (ys, xs)
    return all(w in lg for w in sm)


# ---------- state ----------

def new_state():
    return {
        'queue': [],
        'zones': {z: {'person_id': None, 'interest_ids': [], 'dirty': False} for z in ZONES},
        'people': {},          # str(pid) -> {"c": centre turns, "s": slice turns, "cursor": int}
        'turn': 0,
        'last_drawn': {},      # zone -> turn number of its last draw (missing = 0)
        'last_kind': None,     # 'centre' or 'slice': what the last draw turn was (drives the alternation)
        'last_end': None,      # {zone, kind, person_id, at}: the turn that ended last (drives the centre hold)
        'dirty_q': [],         # zones in the order they became dirty (sand still holds unwanted content)
        'current': None,       # {turn, kind, person_id, zone, started_at, ends_at, dur, interest_ids, idle, closed, done, hold_until}
        'paused': False,
        'remaining': 0,
        'settings': {'centre_minutes': 4.5, 'slice_minutes': 4.5, 'auto_advance': False},
        'ring': 'interests',
        'driver': {'last_seen': 0, 'turn': 0, 'percent': 0},
    }


def _p(state, pid):
    return state['people'].setdefault(str(pid), {'c': 0, 's': 0, 'cursor': 0})


def featured(state, pid):
    p = state['people'].get(str(pid))
    return (p['c'] + p['s']) if p else 0


def on_table(state):
    return {z['person_id'] for z in state['zones'].values() if z['person_id'] is not None}


def person_zones(state, pid):
    """Every zone the person is in, centre first."""
    return [z for z in ZONES if state['zones'][z]['person_id'] == pid]


def person_zone(state, pid):
    zs = person_zones(state, pid)
    return zs[0] if zs else None


def duration(state, zone, fraction=1.0):
    m = state['settings']['centre_minutes' if zone == 'centre' else 'slice_minutes']
    return max(1, int(round(m * 60 * fraction)))


def clock_is_table(state, now):
    last = state['driver']['last_seen']
    return last > 0 and now - last < TABLE_CLOCK_SECONDS


def auto_advance(state):
    """Old time-driven behaviour (turns finish when their time runs out). Off by default and in old saved states."""
    return bool(state['settings'].get('auto_advance', False))


def clock_mode(state, now):
    """'table' (the driver reported in the last 2 minutes), else 'simulated' (auto_advance on) or 'idle'."""
    if clock_is_table(state, now):
        return 'table'
    return 'simulated' if auto_advance(state) else 'idle'


# ---------- dirty zones ----------

def _make_dirty(state, zone):
    """The zone's content is no longer wanted, but the sand keeps it until a turn wipes the zone."""
    state['zones'][zone] = {'person_id': None, 'interest_ids': [], 'dirty': True}
    q = state.setdefault('dirty_q', [])
    if zone in q:
        q.remove(zone)
    q.append(zone)


def dirty_zones(state):
    zs = state['zones']
    q = [z for z in state.get('dirty_q', []) if zs[z].get('dirty')]
    return q + [z for z in ZONES if zs[z].get('dirty') and z not in q]


def _finish_clear(state):
    """A clear turn that has ended leaves its zone clean and empty."""
    cur = state['current']
    if cur and cur.get('kind', 'draw') == 'clear':
        v = state['zones'][cur['zone']]
        if v['person_id'] is None:
            v['dirty'] = False
        if cur['zone'] in state.get('dirty_q', []) and not v['dirty']:
            state['dirty_q'].remove(cur['zone'])


# ---------- people ----------

def add_person(state, pid):
    """A newcomer goes behind every never-featured person and ahead of everyone already featured."""
    if pid in state['queue']:
        return
    _p(state, pid)
    idx = 0
    for i, q in enumerate(state['queue']):
        if featured(state, q) == 0:
            idx = i + 1
    state['queue'].insert(idx, pid)


def remove_person(state, pid, now):
    if pid in state['queue']:
        state['queue'].remove(pid)
    state['people'].pop(str(pid), None)
    if state.get('forced'):
        state['forced'] = [f for f in state['forced'] if f['person_id'] != pid]
    for z, v in state['zones'].items():
        if v['person_id'] == pid:
            _make_dirty(state, z)
    cur = state['current']
    if cur and cur['person_id'] == pid:
        # their turn is over right now; advance() starts the next one
        _close_current(state, now)
        state['current'] = None
        state['remaining'] = 0


# ---------- turn picking ----------

def _best(state, cands, kind):
    """Never-featured first (queue order), then fewest turns of this kind ('c' or 's'), ties by queue order.
    `cands` must already be in queue order."""
    for p in cands:
        if featured(state, p) == 0:
            return p
    best = None
    for p in cands:
        c = state['people'][str(p)][kind]
        if best is None or c < best[0]:
            best = (c, p)
    return best[1] if best else None


def _slice_people(state):
    return {state['zones'][z]['person_id'] for z in SLICES if state['zones'][z]['person_id'] is not None}


def _pick_slice(state, exclude=None):
    """A person who is in no slice, preferring one who is not in the centre either."""
    inside = _slice_people(state)
    cands = [p for p in state['queue'] if p not in inside and p != exclude]
    centre = state['zones']['centre']['person_id']
    return _best(state, [p for p in cands if p != centre] or cands, 's')


def _pick_centre(state, info, exclude=(), lone_ok=False):
    """Someone off the table if there is anyone, else (everyone is on the table) anyone but `exclude`.
    With lone_ok, a lone person is redrawn when they have more than 3 interests (not after a skip)."""
    queue = state['queue']
    cands = [p for p in queue if p not in exclude]
    if lone_ok and not cands and len(queue) == 1 and len(info.get(queue[0], {}).get('interests', [])) > 3:
        cands = list(queue)
    occupied = on_table(state)
    return _best(state, [p for p in cands if p not in occupied] or cands, 'c')


def _take_interests(state, info, pid):
    ids = list(info.get(pid, {}).get('interests', []))
    p = _p(state, pid)
    k = len(ids)
    if k <= 3:
        p['cursor'] = 0
        return ids
    start = p['cursor'] % k
    chosen = [ids[(start + i) % k] for i in range(3)]
    p['cursor'] = (start + 3) % k
    return chosen


def _begin(state, t, zone, kind, pid, ids, dur):
    state['turn'] += 1
    state['current'] = {'turn': state['turn'], 'kind': kind, 'person_id': pid, 'zone': zone, 'started_at': t,
                        'ends_at': t + dur, 'dur': dur, 'interest_ids': list(ids), 'idle': False}
    if state['paused']:
        state['remaining'] = dur


def _draw(state, info, zone, pid):
    p = _p(state, pid)
    p['c' if zone == 'centre' else 's'] += 1
    ids = _take_interests(state, info, pid)
    state['zones'][zone] = {'person_id': pid, 'interest_ids': ids, 'dirty': False}
    if state.get('forced'):                # a "feature now" request is used up by the draw it asked for
        state['forced'] = [f for f in state['forced'] if not (f['person_id'] == pid and f['zone'] == zone)]
    state.setdefault('last_drawn', {})[zone] = state['turn'] + 1   # the turn about to begin
    state['last_kind'] = 'centre' if zone == 'centre' else 'slice'
    if zone in state.get('dirty_q', []):
        state['dirty_q'].remove(zone)
    state['queue'].remove(pid)
    state['queue'].append(pid)
    return ids


def _close_current(state, t):
    """The running turn is over at time t (ran out, reported done, skipped or its person left). Idempotent."""
    cur = state['current']
    if cur and not cur.get('closed'):
        cur['closed'] = True
        state['last_end'] = {'zone': cur['zone'], 'kind': cur.get('kind', 'draw'), 'person_id': cur['person_id'], 'at': t}


def _decide(state, info, exclude=None):
    """The next turn as (zone, kind, person_id), or None. Does not change anything.

    1. Dirty zones first (draw for the next eligible person, else a clear turn).
    2. Empty centre (so an empty table): the centre.
    3. Fill: an empty slice and someone in no slice: that person takes the first empty slice in FILL_ORDER.
    4. Everyone has a slice (N <= 10): only the centre refreshes, never the person already there.
    5. Otherwise (N > 10, all 10 slices full): centre and slice alternate."""
    if not state['queue']:
        return None
    for f in state.get('forced', []):      # 0. the host said "feature now": that person, that zone, before anything else
        if f['person_id'] in state['queue'] and f['zone'] in ZONES and f['person_id'] != exclude:
            return f['zone'], 'draw', f['person_id']
    for zone in dirty_zones(state):
        pid = _pick_centre(state, info, {exclude}) if zone == 'centre' else _pick_slice(state, exclude)
        if pid is None:
            return zone, 'clear', None
        return zone, 'draw', pid
    centre = state['zones']['centre']['person_id']
    if centre is None:
        pid = _pick_centre(state, info)
        return ('centre', 'draw', pid) if pid is not None else None
    empties = [z for z in FILL_ORDER if state['zones'][z]['person_id'] is None]
    inside = _slice_people(state)
    unslotted = [p for p in state['queue'] if p not in inside]
    if empties and unslotted:
        return empties[0], 'draw', _pick_slice(state)
    if not unslotted:
        pid = _pick_centre(state, info, {centre}, True)
        return ('centre', 'draw', pid) if pid is not None else None
    order = ['slice', 'centre'] if state.get('last_kind') == 'centre' else ['centre', 'slice']
    for kind in order:
        if kind == 'centre':
            pid = _pick_centre(state, info, {centre}, True)
            if pid is not None:
                return 'centre', 'draw', pid
        else:
            occupied = on_table(state)
            off = [p for p in state['queue'] if p not in occupied]
            if off:
                last = state.get('last_drawn', {})
                zone = min(SLICES, key=lambda z: (last.get(z, 0), SLICES.index(z)))
                return zone, 'draw', _best(state, off, 's')
    return None


def _start(state, info, t, exclude=None):
    """Try to start the next turn at time t. Returns 'started', 'held' (a finished centre must stay up until
    cur['hold_until'] before the next centre turn; the finished turn is marked `done`) or 'none'."""
    _close_current(state, t)
    _finish_clear(state)
    if state.get('erase'):                 # the host asked for a whole-table erase: no new turn until it is done
        return 'none'
    d = _decide(state, info, exclude)
    if d is None:
        return 'none'
    zone, kind, pid = d
    if kind == 'draw' and zone == 'centre':
        le = state.get('last_end')
        z = state['zones']['centre']
        if (le and le['zone'] == 'centre' and le['kind'] == 'draw' and not z.get('dirty')
                and z['person_id'] == le['person_id'] and t < le['at'] + CENTRE_HOLD_SECONDS):
            cur = state['current']
            if cur is not None:
                cur['done'] = True
                cur['hold_until'] = le['at'] + CENTRE_HOLD_SECONDS
                cur['ends_at'] = min(cur['ends_at'], le['at'])   # the table may finish before the simulated end
            return 'held'
    if kind == 'clear':
        _begin(state, t, zone, 'clear', None, [], duration(state, zone, CLEAR_FRACTION))
    else:
        ids = _draw(state, info, zone, pid)
        _begin(state, t, zone, 'draw', pid, ids, duration(state, zone))
    return 'started'


def start_turn(state, info, t, exclude=None):
    """Start the next possible turn at time t. Returns True if one started (False: nothing to do, or the centre
    hold is still running)."""
    return _start(state, info, t, exclude) == 'started'


def advance(state, info, now):
    """Start a turn when there is none, end a centre hold that is over, and (auto_advance only) lazily catch the
    simulated clock up to now. Without auto_advance time never finishes a turn. Safe to call on every read."""
    if state['paused']:
        return
    table = clock_is_table(state, now)
    started = 0
    for _ in range(3 * MAX_CATCHUP):
        if started >= MAX_CATCHUP:
            break
        cur = state['current']
        if cur is None or cur['idle']:
            r = _start(state, info, now)
            if r != 'started':
                return
        elif cur.get('done'):
            hold = cur['hold_until']
            r = _start(state, info, now if (table or now < hold) else hold)
            if r != 'started':
                return
        elif table or not auto_advance(state):
            return
        elif cur['ends_at'] <= now:
            r = _start(state, info, cur['ends_at'])
            if r == 'none':
                cur['idle'] = True
                return
            if r == 'held':
                if cur['hold_until'] > now:
                    return
                continue
        else:
            return
        started += 1
    cur = state['current']
    if cur and not cur.get('done') and cur['ends_at'] <= now and auto_advance(state):  # far behind: re-anchor instead of replaying forever
        cur['started_at'] = now
        cur['ends_at'] = now + cur['dur']


def feature(state, pid, zones):
    """Host override ("feature now"): the next turns draw this person in these zones, in this order, ahead of the
    normal rotation; whoever is in a zone is replaced and simply leaves the table. The person may end up in several
    zones at once (the host asked for it). A newer request goes ahead of older ones and replaces this person's own
    earlier request. Returns False if the person has not joined."""
    if pid not in state['queue']:
        return False
    cur = state['current']
    busy = cur['zone'] if cur and not cur.get('closed') and cur.get('kind', 'draw') == 'draw' and cur['person_id'] == pid else None
    mine = [{'person_id': pid, 'zone': z} for z in dict.fromkeys(zones) if z in ZONES and z != busy]
    state['forced'] = mine + [f for f in state.get('forced', []) if f['person_id'] != pid]
    return True


def reset_table(state):
    """The sand was wiped by hand (or was never drawn): forget who is in which zone and every turn count, keep the
    people, their order, the settings and the pause. The turn number keeps counting so stale progress is refused."""
    state['zones'] = {z: {'person_id': None, 'interest_ids': [], 'dirty': False} for z in ZONES}
    for rec in state['people'].values():
        rec['c'] = rec['s'] = 0
    state['last_drawn'] = {}
    state['last_kind'] = None
    state['last_end'] = None
    state['dirty_q'] = []
    state['current'] = None
    state['remaining'] = 0
    state['erase'] = None                  # the table is clean: any erase the host asked for is done


def request_erase(state, direction, now):
    """Host asks for a whole-table erase ('in': rim to middle, 'out': middle to rim), or cancels with None. The
    driver does the erasing; until it reports the table clean (reset) no new turn starts. Returns False when it
    cannot be changed any more (the erase is already running)."""
    e = state.get('erase')
    if e and e.get('status') == 'running':
        return False
    if direction is None:
        state['erase'] = None
        return True
    state['erase_seq'] = state.get('erase_seq', 0) + 1
    state['erase'] = {'id': state['erase_seq'], 'dir': direction, 'status': 'waiting', 'at': now}
    return True


def erase_started(state, eid):
    """The driver is starting erase `eid`. False if that request is gone (cancelled or replaced)."""
    e = state.get('erase')
    if not e or e['id'] != eid:
        return False
    e['status'] = 'running'
    return True


def set_paused(state, paused, now):
    paused = bool(paused)
    if paused == state['paused']:
        return
    cur = state['current']
    hold = cur is not None and cur.get('done')
    if paused:
        if hold:
            state['remaining'] = max(0, cur['hold_until'] - now)
        else:
            state['remaining'] = max(0, cur['ends_at'] - now) if cur else 0
        state['paused'] = True
    else:
        state['paused'] = False
        if hold:   # the hold picks up with the time it had left
            cur['hold_until'] = now + state['remaining']
            state['last_end']['at'] = cur['hold_until'] - CENTRE_HOLD_SECONDS
        elif cur:
            cur['ends_at'] = now + state['remaining']
            cur['started_at'] = cur['ends_at'] - cur['dur']
        state['remaining'] = 0


def skip(state, info, now):
    """Host skips the running draw turn: its zone goes dirty and is redrawn at once by someone else.
    No-op when nothing is current, a clear turn is running, or the finished centre is just being held."""
    cur = state['current']
    if cur is None or cur.get('kind', 'draw') == 'clear' or cur.get('done'):
        return
    skipped = None
    if not cur['idle'] and cur['person_id'] is not None:
        skipped = cur['person_id']
        _make_dirty(state, cur['zone'])
        if skipped in state['queue']:
            state['queue'].remove(skipped)
            state['queue'].append(skipped)
    if not start_turn(state, info, now, exclude=skipped):
        cur['idle'] = True
        cur['ends_at'] = now
        state['remaining'] = 0


def move(state, pid, direction):
    q = state['queue']
    if pid not in q or direction not in (-1, 1):
        return
    i = q.index(pid)
    j = i + direction
    if 0 <= j < len(q):
        q[i], q[j] = q[j], q[i]


def set_ring(state, ring):
    state['ring'] = ring


def set_settings(state, centre_minutes=None, slice_minutes=None, auto_advance=None):
    if centre_minutes is not None:
        state['settings']['centre_minutes'] = centre_minutes
    if slice_minutes is not None:
        state['settings']['slice_minutes'] = slice_minutes
    if auto_advance is not None:
        state['settings']['auto_advance'] = bool(auto_advance)


def progress(state, info, turn, percent, done, now):
    """Real table reports progress. Returns False when the report is for a different turn."""
    cur = state['current']
    if cur is None or turn != cur['turn']:
        return False
    d = state['driver']
    d['last_seen'] = now
    d['turn'] = turn
    if cur.get('done'):   # already finished and held; the hold runs from the first done report
        return True
    d['percent'] = max(0, min(100, int(percent)))
    if done:
        r = _start(state, info, now)
        if r == 'none':
            cur['idle'] = True
            d['percent'] = 100
        elif r == 'held':
            d['percent'] = 100
    else:
        # keep the simulated end a little ahead so it resumes smoothly if reports stop
        cur['ends_at'] = max(cur['ends_at'], now + TABLE_CLOCK_SECONDS)
    return True


# ---------- views ----------

def _times(state, now):
    cur = state['current']
    if state['paused'] and not cur.get('done'):
        ends = now + state['remaining']
        return ends - cur['dur'], ends
    return cur['started_at'], cur['ends_at']


def percent(state, now):
    cur = state['current']
    if cur is None:
        return 0
    if cur['idle'] or cur.get('done'):
        return 100
    if clock_is_table(state, now) and state['driver']['turn'] == cur['turn']:
        return state['driver']['percent']
    if clock_mode(state, now) == 'idle':   # nobody can know: only what the driver last said for this turn
        return state['driver']['percent'] if state['driver']['turn'] == cur['turn'] else 0
    if state['paused']:
        elapsed = cur['dur'] - state['remaining']
    else:
        elapsed = now - cur['started_at']
    return max(0, min(100, int(100 * elapsed / cur['dur'])))


def steps_for(name, has_face, has_interests, pct):
    names = [('clear', 'Clearing the spot'), ('name', "Writing %s's name" % name)]
    if has_face:
        names.append(('face', "Drawing %s's face" % name))
    if has_interests:
        names.append(('interests', "Adding %s's interests" % name))
    total = sum(_STEP_WEIGHTS[k] for k, _ in names)
    labels, acc, step = [], 0.0, None
    for i, (k, label) in enumerate(names):
        labels.append(label)
        acc += 100.0 * _STEP_WEIGHTS[k] / total
        if step is None and pct < acc - 1e-9:
            step = i
    if step is None:
        step = len(names) - 1
    return labels, step


def describe_current(state, info, now):
    cur = state['current']
    if cur is None:
        return None
    pct = percent(state, now)
    kind = cur.get('kind', 'draw')
    if kind == 'clear':
        steps, step = list(CLEAR_STEPS), 0
    else:
        pi = info.get(cur['person_id'], {})
        steps, step = steps_for(pi.get('name', ''), pi.get('faces', 0) > 0, bool(cur['interest_ids']), pct)
    started, ends = _times(state, now)
    return {'turn': cur['turn'], 'kind': kind, 'person_id': cur['person_id'], 'zone': cur['zone'],
            'started_at': started, 'ends_at': ends, 'percent': pct, 'steps': steps, 'step': step,
            'interest_ids': list(cur['interest_ids']), 'done': bool(cur.get('done'))}


def hold_until(state):
    """Epoch seconds when the held (finished) centre turn lets the next one start, else None."""
    cur = state['current']
    return cur['hold_until'] if cur and cur.get('done') else None


def project(state, info, now, count=None):
    """Run the same logic forward on a copy. Returns [{kind, person_id, zone, at, interest_ids}]."""
    n = len(state['queue'])
    if count is None:
        count = max(12, n + 2)
    st = copy.deepcopy(state)
    st['erase'] = None                     # the forecast shows what comes after a pending erase
    cur = st['current']
    if cur is None:
        t = now
    elif cur['idle']:
        t = now
    elif st['paused']:
        t = now + st['remaining']
    else:
        t = max(cur['ends_at'], now)
    out = []
    for _ in range(count):
        r = _start(st, info, t)
        if r == 'held':
            t = max(t, st['last_end']['at'] + CENTRE_HOLD_SECONDS)
            r = _start(st, info, t)
        if r != 'started':
            break
        c = st['current']
        out.append({'kind': c['kind'], 'person_id': c['person_id'], 'zone': c['zone'], 'at': t,
                    'interest_ids': list(c['interest_ids'])})
        t += c['dur']
    return out
