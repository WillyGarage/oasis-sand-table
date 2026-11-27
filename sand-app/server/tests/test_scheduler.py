import copy

from server import scheduler as S


def make(n, interests=2, faces=1, auto=True):
    """Most tests here are about time-driven turns, so auto_advance is on unless auto=False."""
    st = S.new_state()
    st['settings']['auto_advance'] = auto
    info = {}
    for i in range(1, n + 1):
        info[i] = {'name': 'P%d' % i, 'faces': faces,
                   'interests': list(range(i * 100, i * 100 + interests))}
        S.add_person(st, i)
    return st, info


def go(st, info, t):
    """Start the next turn at time t, or at the end of the centre hold if one is running. Returns the start time
    (None if nothing can start)."""
    if S.start_turn(st, info, t):
        return t
    cur = st['current']
    if cur is not None and cur.get('done'):
        t = cur['hold_until']
        assert S.start_turn(st, info, t)
        return t
    return None


def run(st, info, turns, unique=False):
    """Start `turns` turns back to back (waiting out centre holds); returns [(zone, pid)].
    unique=True also asserts nobody is on the table twice (true only while N > 10)."""
    out = []
    t = 1000
    for _ in range(turns):
        before = st['turn']
        t = go(st, info, t)
        if t is None:
            break
        assert st['turn'] == before + 1
        c = st['current']
        out.append((c['zone'], c['person_id']))
        if unique:
            occ = [z['person_id'] for z in st['zones'].values() if z['person_id'] is not None]
            assert len(occ) == len(set(occ)), occ
        t += c['dur']
    return out


def filled(n):
    """n people, the fill done (n+1 turns for n <= 10: centre, a slice each, the centre person's own slice last;
    11 turns for n > 10), the last turn just finished at the returned time."""
    st, info = make(n)
    t = 1000
    for _ in range(min(n, 10) + 1):
        t = go(st, info, t) + st['current']['dur']
    return st, info, t


FILL = ['inner-1', 'outer-1', 'inner-2', 'outer-3', 'inner-3', 'outer-4', 'inner-4', 'outer-6', 'outer-2', 'outer-5']


# ---------- rules 2-4: empty table, fill, centre-only steady state ----------

def test_fill_order_and_who_gets_picked():
    assert S.FILL_ORDER == FILL and sorted(FILL) == sorted(S.SLICES)
    st, info = make(5)
    seq = run(st, info, 6)
    # centre first (first in queue), then one slice per turn in the spread order, centre person last
    assert seq == [('centre', 1), ('inner-1', 2), ('outer-1', 3), ('inner-2', 4), ('outer-3', 5), ('inner-3', 1)]
    assert st['zones']['centre']['person_id'] == 1 and st['zones']['inner-3']['person_id'] == 1  # on the table twice
    # 11 people: all 10 slices are used, in the same order, before the centre moves again
    st, info = make(11)
    seq = run(st, info, 11)
    assert [z for z, _ in seq] == ['centre'] + FILL
    assert [p for _, p in seq] == list(range(1, 12))


def test_empty_table_first_turn_is_centre_for_first_in_queue():
    st, info = make(7)
    S.move(st, 4, -1)
    S.move(st, 4, -1)
    S.move(st, 4, -1)
    assert st['queue'][0] == 4
    S.start_turn(st, info, 1000)
    assert (st['current']['zone'], st['current']['person_id']) == ('centre', 4)


def test_two_people_fill_then_only_centre():
    st, info = make(2)
    seq = run(st, info, 6)
    # centre 1, slice for 2 (not in the centre), slice for 1 last, then only centre turns
    assert seq == [('centre', 1), ('inner-1', 2), ('outer-1', 1), ('centre', 2), ('centre', 1), ('centre', 2)]


def test_all_ten_slices_usable_and_unneeded_slices_stay_empty():
    st, info = make(5)
    run(st, info, 40)
    held = {z for z in S.SLICES if st['zones'][z]['person_id'] is not None}
    assert held == set(FILL[:5])
    assert all(st['zones'][z] == {'person_id': None, 'interest_ids': [], 'dirty': False} for z in FILL[5:])
    up = S.project(st, info, 5000)
    assert all(u['kind'] == 'draw' and u['zone'] == 'centre' for u in up)   # no clear turn for slices that never held anyone


def test_steady_state_centre_only_cycles_evenly_with_hold():
    n = 6
    st, info, t = filled(n)
    assert [z for z in S.SLICES if st['zones'][z]['person_id'] is not None] == sorted(FILL[:6], key=S.SLICES.index)
    starts, people, ends = [], [], []
    for _ in range(4 * n):
        t = go(st, info, t)
        c = st['current']
        assert c['zone'] == 'centre'
        starts.append(t)
        people.append(c['person_id'])
        t += c['dur']
        ends.append(t)
    # nobody twice in a row, each person once in every 6 turns
    for k in range(len(people) - n + 1):
        assert sorted(people[k:k + n]) == list(range(1, n + 1)), people
    # first centre follows a slice turn at once; every later one starts 60 s after the previous centre ended
    assert all(b - a == 60 for a, b in zip(ends, starts[1:]))


def test_centre_hold_simulated_clock():
    st, info, t = filled(6)
    S.advance(st, info, t)                       # the fill ended on a slice turn: the first centre starts at once
    assert st['current']['zone'] == 'centre' and not st['current'].get('done') and st['current']['started_at'] == t
    end = st['current']['ends_at']
    S.advance(st, info, end)
    cur = st['current']
    assert cur['done'] is True and cur['hold_until'] == end + 60
    d = S.describe_current(st, info, end + 10)
    assert d['done'] is True and d['percent'] == 100 and S.hold_until(st) == end + 60
    S.advance(st, info, end + 59)
    assert st['current']['turn'] == cur['turn'] and S.hold_until(st) == end + 60
    up = S.project(st, info, end + 10)
    assert up[0]['at'] == end + 60 and up[0]['zone'] == 'centre'
    assert up[1]['at'] == up[0]['at'] + 270 + 60
    S.advance(st, info, end + 61)
    assert st['current']['turn'] == cur['turn'] + 1 and st['current']['started_at'] == end + 60   # on time, not late
    assert S.hold_until(st) is None and S.describe_current(st, info, end + 61)['done'] is False
    # a read long after catches up through the holds
    S.advance(st, info, end + 61 + 3 * 330)
    assert st['current']['turn'] == cur['turn'] + 4


def test_centre_hold_table_clock_driven_by_progress():
    st, info, t = filled(6)
    S.advance(st, info, t)
    cur = st['current']
    assert S.progress(st, info, cur['turn'], 50, False, t + 100) and S.clock_is_table(st, t + 100)
    done_at = t + 130
    assert S.progress(st, info, cur['turn'], 100, True, done_at)
    assert st['current']['turn'] == cur['turn'] and st['current']['done'] is True
    assert st['current']['hold_until'] == done_at + 60          # measured from the done report
    assert S.describe_current(st, info, done_at + 1)['percent'] == 100
    assert S.progress(st, info, cur['turn'], 100, True, done_at + 5)   # a repeated report must not move the hold
    assert st['current']['hold_until'] == done_at + 60
    S.advance(st, info, done_at + 59)
    assert st['current']['turn'] == cur['turn']
    S.advance(st, info, done_at + 60)            # any read after the hold starts the next turn while the table keeps time
    nxt = st['current']
    assert nxt['turn'] == cur['turn'] + 1 and not nxt.get('done') and nxt['started_at'] == done_at + 60
    # nobody reads until well after the hold: the first read starts it
    done2 = done_at + 60 + 200
    S.progress(st, info, nxt['turn'], 100, True, done2)
    assert st['current']['done'] is True
    S.advance(st, info, done2 + 100)
    assert st['current']['turn'] == nxt['turn'] + 1 and st['current']['started_at'] == done2 + 100
    # "no current turn, not paused, not held" starts one on any read, table clock or not
    st['current'] = None
    S.advance(st, info, done2 + 101)
    assert st['current'] is not None


def test_no_hold_after_slice_or_clear_or_for_dirty_centre():
    st, info, t = filled(6)
    # the fill ended on a slice: the first centre is not held
    assert S.start_turn(st, info, t) and st['current']['zone'] == 'centre'
    # a skipped centre is redrawn at once (no hold), the skipped person is not the one drawn
    first = st['current']['person_id']
    S.skip(st, info, t + 30)
    assert st['current']['zone'] == 'centre' and st['current']['person_id'] != first and not st['current'].get('done')
    # a removed centre person: same
    S.remove_person(st, st['current']['person_id'], t + 40)
    S.advance(st, info, t + 40)
    assert st['current']['zone'] == 'centre' and st['current']['kind'] == 'draw' and not st['current'].get('done')


def test_newcomer_with_empty_slice_is_drawn_before_next_centre():
    st, info = make(6)
    run(st, info, 7 + 6)                  # fill done, then only centre turns
    cur = st['current']
    assert cur['zone'] == 'centre'
    info[7] = {'name': 'P7', 'faces': 1, 'interests': [700]}
    S.add_person(st, 7)
    S.advance(st, info, cur['ends_at'])   # centre person done; hold not over, but the newcomer's slice is not held
    c = st['current']
    assert (c['zone'], c['person_id'], c['kind']) == ('inner-4', 7, 'draw') and c['started_at'] == cur['ends_at']
    S.advance(st, info, c['ends_at'])     # then centre turns again, the hold counted from the last centre end
    assert st['current']['zone'] == 'centre'


def test_newcomer_joins_during_hold_goes_to_slice_at_once():
    st, info, t = filled(6)
    S.advance(st, info, t)
    end = st['current']['ends_at']
    S.advance(st, info, end)
    assert st['current']['done'] is True
    info[7] = {'name': 'P7', 'faces': 1, 'interests': [700]}
    S.add_person(st, 7)
    S.advance(st, info, end + 20)
    assert st['current']['zone'] == 'inner-4' and st['current']['person_id'] == 7 and st['current']['started_at'] == end + 20


# ---------- rule 6: N > 10, all slices full ----------

def test_n15_alternates_nobody_twice_oldest_slice_fairness():
    n, turns = 15, 400
    st, info = make(n)
    t = 1000
    seq = []
    for k in range(turns):
        before_last = dict(st['last_drawn'])
        before_zones = {z: v['person_id'] for z, v in st['zones'].items()}
        t = go(st, info, t)
        c = st['current']
        seq.append((c['zone'], c['person_id']))
        occ = [z['person_id'] for z in st['zones'].values() if z['person_id'] is not None]
        assert len(occ) == len(set(occ)), (k, occ)
        if k >= 11:
            # strict alternation after the fill: centre, slice, centre, slice
            assert (c['zone'] == 'centre') == ((k - 11) % 2 == 0), (k, c['zone'])
            if c['zone'] != 'centre':
                oldest = min(S.SLICES, key=lambda z: (before_last.get(z, 0), S.SLICES.index(z)))
                assert c['zone'] == oldest, (k, c['zone'], oldest)   # the slice drawn longest ago is replaced
                assert before_zones[c['zone']] is not None
        t += c['dur']
    assert [z for z, _ in seq[:11]] == ['centre'] + FILL
    cs = [v['c'] for v in st['people'].values()]
    ss = [v['s'] for v in st['people'].values()]
    # bound, measured (not proven): centre counts differ by at most 2, slice counts by at most 1
    assert max(cs) - min(cs) <= 2 and max(ss) - min(ss) <= 1, (cs, ss)
    assert min(cs) + min(ss) >= 1   # everyone got featured


def test_fairness_spread_over_many_n():
    # N = 11..30 and 40: from turn 3N on, up to turn 1200, the centre-count spread is never above 2 and the
    # slice-count spread never above 1 (measured over these runs; not a proof for every N)
    for n in list(range(11, 31)) + [40]:
        st, info = make(n)
        t = 1000
        for k in range(1200):
            t = go(st, info, t) + st['current']['dur']
            if k >= 3 * n:
                cs = [v['c'] for v in st['people'].values()]
                ss = [v['s'] for v in st['people'].values()]
                assert max(cs) - min(cs) <= 2 and max(ss) - min(ss) <= 1, (n, k, cs, ss)


def test_n11_does_not_deadlock():
    st, info = make(11)
    t = 1000
    seq = []
    for k in range(300):
        t = go(st, info, t)
        assert t is not None
        c = st['current']
        seq.append((c['zone'], c['person_id']))
        t += c['dur']
    assert sum(1 for z, _ in seq[11:] if z == 'centre') > 100 and sum(1 for z, _ in seq[11:] if z != 'centre') > 100
    assert {p for _, p in seq[11:]} == set(range(1, 12))


def test_n11_exception_centre_takes_a_person_in_a_slice():
    st, info = make(11)
    run(st, info, 11)
    assert st['zones']['centre']['person_id'] == 1 and not (set(st['queue']) - S.on_table(st))   # nobody is off the table
    t = 1000 + 11 * 270
    assert S.start_turn(st, info, t)                    # centre: takes someone who is in a slice
    c = st['current']
    taken = c['person_id']
    assert c['zone'] == 'centre' and taken in {v['person_id'] for k, v in st['zones'].items() if k != 'centre'}
    assert S.start_turn(st, info, t + 270)              # next: a slice, and the freed previous centre person gets it
    assert st['current']['zone'] != 'centre' and st['current']['person_id'] == 1


def test_slice_state_defaults_and_old_saved_state_loads():
    import json
    st, info = make(8)
    run(st, info, 9)
    old = json.loads(json.dumps(st))
    for k in ('last_drawn', 'last_kind', 'last_end'):
        del old[k]
    old['pos'] = 7                                      # the old pointer is simply ignored
    old['current'].pop('closed', None)
    t = old['current']['ends_at']
    S.advance(old, info, t + 5000)                      # loads and keeps going (missing last_drawn counts as 0)
    assert old['turn'] > 9 and old['current'] is not None
    assert S.project(old, info, t + 5000)
    # an old state from the capped rules: 5 people, centre + 3 slices, slice 4..10 empty; the fifth is off the table
    old = S.new_state()
    old['settings']['auto_advance'] = True
    old['queue'] = [1, 2, 3, 4, 5]
    for i in range(1, 6):
        old['people'][str(i)] = {'c': 1, 's': 1, 'cursor': 0}
    for z, p in (('centre', 1), ('inner-1', 2), ('inner-2', 3), ('inner-3', 4)):
        old['zones'][z] = {'person_id': p, 'interest_ids': [], 'dirty': False}
    old['current'] = {'turn': 9, 'kind': 'draw', 'person_id': 4, 'zone': 'inner-3', 'started_at': 100, 'ends_at': 370,
                      'dur': 270, 'interest_ids': [], 'idle': False}
    old['turn'] = 9
    info5 = make(5)[1]
    S.advance(old, info5, 370)
    c = old['current']
    assert (c['zone'], c['person_id']) == ('outer-1', 5)   # the person off the table fills the next empty slice


def test_newcomer_ordering():
    st, info = make(4)
    assert st['queue'] == [1, 2, 3, 4]
    run(st, info, 2)  # two people featured and moved to the back
    assert st['queue'][:2] == [3, 4]
    info[5] = {'name': 'P5', 'faces': 0, 'interests': []}
    S.add_person(st, 5)
    # behind never-featured 3 and 4, ahead of the featured pair
    assert st['queue'][:3] == [3, 4, 5]
    assert S.featured(st, 5) == 0
    info[6] = {'name': 'P6', 'faces': 0, 'interests': []}
    S.add_person(st, 6)
    assert st['queue'][:4] == [3, 4, 5, 6]


def test_never_featured_first_in_queue_order():
    st, info = make(6)
    seq = run(st, info, 4)
    assert [p for _, p in seq] == [1, 2, 3, 4]


def test_interest_cycling_past_3():
    st, info = make(3, interests=2)
    info[1]['interests'] = [11, 12, 13, 14, 15]
    shown = []
    for _ in range(4):
        # put person 1 on the table repeatedly by forcing a clean state
        st['zones']['centre'] = {'person_id': None, 'interest_ids': []}
        st['zones']['inner-1'] = {'person_id': None, 'interest_ids': []}
        ids = S._take_interests(st, info, 1)
        shown.append(ids)
    assert shown[0] == [11, 12, 13]
    assert shown[1] == [14, 15, 11]
    assert shown[2] == [12, 13, 14]
    assert all(len(s) == 3 for s in shown)
    covered = {i for s in shown for i in s}
    assert covered == {11, 12, 13, 14, 15}


def test_three_or_fewer_interests_all_shown():
    st, info = make(3, interests=3)
    assert S._take_interests(st, info, 2) == [200, 201, 202]


def test_single_person_few_interests():
    st, info = make(1, interests=3)
    S.advance(st, info, 5000)
    assert st['current']['person_id'] == 1 and st['current']['zone'] == 'centre'
    S.advance(st, info, 5000 + 10 * 3600)
    # centre, then the same person's own slice (rule 3), then nothing: a lone person with 3 or fewer interests
    # is not redrawn
    assert st['turn'] == 2 and st['current']['zone'] == 'inner-1'
    assert st['current']['idle'] is True
    assert S.percent(st, 5000 + 10 * 3600) == 100
    # someone arrives: next turn starts immediately
    info[2] = {'name': 'P2', 'faces': 0, 'interests': []}
    S.add_person(st, 2)
    S.advance(st, info, 5000 + 10 * 3600 + 1)
    assert st['current']['person_id'] == 2 and st['current']['idle'] is False
    assert st['current']['zone'] == 'outer-1'


def test_single_person_many_interests_redraws_self():
    st, info = make(1, interests=5)
    seq = run(st, info, 5)
    assert [p for _, p in seq] == [1] * 5
    assert [z for z, _ in seq] == ['centre', 'inner-1', 'centre', 'centre', 'centre']


def test_nothing_joined():
    st, info = make(0)
    S.advance(st, info, 100)
    assert st['current'] is None
    assert S.describe_current(st, info, 100) is None


def test_remove_person_on_table():
    st, info = make(8)
    run(st, info, 6)
    victim = st['zones']['inner-2']['person_id']
    assert victim is not None
    S.remove_person(st, victim, 2000)
    del info[victim]
    assert st['zones']['inner-2']['person_id'] is None
    assert victim not in st['queue'] and str(victim) not in st['people']
    seq = run(st, info, 40)
    assert victim not in [p for _, p in seq]
    # removing the person whose turn is running ends that turn
    cur = st['current']['person_id']
    S.remove_person(st, cur, 3000)
    del info[cur]
    assert st['current'] is None
    S.advance(st, info, 3000)
    assert st['current']['person_id'] != cur


def test_remove_last_person():
    st, info = make(1)
    S.advance(st, info, 100)
    S.remove_person(st, 1, 200)
    assert st['current'] is None and st['queue'] == []
    assert all(z['person_id'] is None for z in st['zones'].values())


def test_pause_resume_keeps_remaining_time():
    st, info = make(5)
    S.advance(st, info, 1000)
    cur = st['current']
    assert (cur['started_at'], cur['ends_at']) == (1000, 1000 + 270)
    S.set_paused(st, True, 1100)
    assert st['remaining'] == 170
    S.advance(st, info, 1000 + 100000)  # paused: nothing moves
    assert st['turn'] == 1
    assert S.percent(st, 999999) == int(100 * 100 / 270)
    S.set_paused(st, False, 5000)
    assert st['current']['ends_at'] == 5170
    S.advance(st, info, 5169)
    assert st['turn'] == 1
    S.advance(st, info, 5170)
    assert st['turn'] == 2 and st['current']['started_at'] == 5170


def test_skip():
    st, info = make(5)
    S.advance(st, info, 1000)
    S.skip(st, info, 1100)
    # the skipped zone is redrawn at once by someone else; the normal order is untouched
    assert st['turn'] == 2
    assert st['current']['started_at'] == 1100
    assert st['current']['zone'] == 'centre' and st['current']['person_id'] == 2
    assert st['current']['ends_at'] == 1100 + 270
    # skip while paused starts the next turn, still paused, with a full turn left
    S.set_paused(st, True, 1200)
    S.skip(st, info, 1200)
    assert st['turn'] == 3 and st['paused'] and st['remaining'] == 270


def test_host_move():
    st, info = make(5)
    S.move(st, 3, -1)
    assert st['queue'] == [1, 3, 2, 4, 5]
    S.move(st, 3, -1)
    S.move(st, 3, -1)  # already first: no-op
    assert st['queue'] == [3, 1, 2, 4, 5]
    S.move(st, 5, 1)
    assert st['queue'] == [3, 1, 2, 4, 5]
    seq = run(st, info, 2)
    assert [p for _, p in seq] == [3, 1]


def test_catch_up_is_lazy_and_bounded():
    st, info = make(8)
    S.advance(st, info, 1000)
    S.advance(st, info, 1000 + 270 * 3 + 5)
    assert st['turn'] == 4
    S.advance(st, info, 1000 + 86400 * 30)
    assert st['current']['ends_at'] > 1000 + 86400 * 30
    assert st['turn'] <= 4 + S.MAX_CATCHUP


def test_fairness_30_people():
    st, info = make(30)
    worst_c = worst_s = 0
    t = 1000
    for k in range(1, 2001):
        S.start_turn(st, info, t)
        t += 1
        if k >= 100:  # after everyone has been featured at least once
            c = [v['c'] for v in st['people'].values()]
            s = [v['s'] for v in st['people'].values()]
            worst_c = max(worst_c, max(c) - min(c))
            worst_s = max(worst_s, max(s) - min(s))
    print('worst centre spread', worst_c, 'worst slice spread', worst_s)
    # measured (not proven): centre counts within 2, slice counts within 1 on every turn from 100 to 2000.
    # (the old rules held centre within 1; now slice sitters cannot be picked for the centre until they leave)
    assert worst_c <= 2
    assert worst_s <= 1


def test_project_does_not_mutate_and_matches_reality():
    st, info = make(12)
    S.advance(st, info, 1000)
    before = copy.deepcopy(st)
    up = S.project(st, info, 1000)
    assert st == before
    assert len(up) == 14
    real = []
    t = 1000
    for _ in range(14):
        S.advance(st, info, st['current']['ends_at'])
        c = st['current']
        real.append((c['person_id'], c['zone'], c['started_at']))
    assert [(u['person_id'], u['zone'], u['at']) for u in up] == real


def test_steps_split():
    labels, step = S.steps_for('Bill', True, True, 0)
    assert labels == ['Clearing the spot', "Writing Bill's name", "Drawing Bill's face", "Adding Bill's interests"]
    assert S.steps_for('Bill', True, True, 29)[1] == 0
    assert S.steps_for('Bill', True, True, 30)[1] == 1
    assert S.steps_for('Bill', True, True, 45)[1] == 2
    assert S.steps_for('Bill', True, True, 75)[1] == 3
    assert S.steps_for('Bill', True, True, 100)[1] == 3
    labels, _ = S.steps_for('Bill', False, False, 0)
    assert len(labels) == 2
    # re-spread: clearing 30/45 of the range
    assert S.steps_for('Bill', False, False, 66)[1] == 0
    assert S.steps_for('Bill', False, False, 67)[1] == 1


def test_progress_from_table():
    st, info = make(5)
    S.advance(st, info, 1000)
    assert S.progress(st, info, 99, 10, False, 1010) is False  # wrong turn
    assert S.progress(st, info, 1, 40, False, 1010) is True
    assert S.clock_is_table(st, 1010)
    assert S.percent(st, 1011) == 40
    S.advance(st, info, 1000 + 100)  # sim stands down while table reports are fresh
    assert st['turn'] == 1
    assert S.progress(st, info, 1, 100, True, 1020) is True
    assert st['turn'] == 2


def test_key_same():
    assert S.key('Star Wars movies') == 'star war'
    assert S.same('star wars', 'Star Wars movie')
    assert S.same('reading', 'Reading')
    assert S.same('clarinet', 'clarinet playing')
    assert not S.same('hiking', 'biking')
    assert not S.same('the', 'a')


# ---------- dirty zones and clear turns ----------

def test_default_minutes():
    st = S.new_state()
    assert st['settings'] == {'centre_minutes': 4.5, 'slice_minutes': 4.5, 'auto_advance': False}
    assert S.duration(st, 'centre') == 270 and S.duration(st, 'inner-1', 0.4) == 108


def test_turns_carry_kind():
    st, info = make(8)
    S.advance(st, info, 1000)
    assert st['current']['kind'] == 'draw'
    assert S.describe_current(st, info, 1000)['kind'] == 'draw'
    assert all(u['kind'] == 'draw' for u in S.project(st, info, 1000))


def test_delete_on_table_redraws_zone_at_once():
    st, info = make(8)
    run(st, info, 6)
    victim = st['zones']['inner-2']['person_id']
    S.remove_person(st, victim, 2000)
    del info[victim]
    z = st['zones']['inner-2']
    assert z['person_id'] is None and z['dirty'] is True
    assert S.start_turn(st, info, 2000)
    cur = st['current']
    assert cur['zone'] == 'inner-2' and cur['kind'] == 'draw'
    assert cur['person_id'] not in (None, victim)
    assert st['zones']['inner-2']['dirty'] is False


def test_delete_current_turn_person():
    st, info = make(8)
    S.advance(st, info, 1000)
    cur = st['current']['person_id']
    S.remove_person(st, cur, 1100)
    del info[cur]
    assert st['current'] is None and st['zones']['centre']['dirty'] is True
    S.advance(st, info, 1100)
    assert st['current']['zone'] == 'centre' and st['current']['kind'] == 'draw'
    assert st['current']['person_id'] != cur


def test_delete_nobody_eligible_clears_then_clean():
    st, info = make(2)
    run(st, info, 3)    # centre 1, inner-1 for 2, outer-1 for 1: everyone is in a slice
    victim = st['zones']['inner-1']['person_id']
    S.remove_person(st, victim, 2000)
    del info[victim]
    assert st['zones']['inner-1']['dirty'] is True
    assert S.start_turn(st, info, 2000)       # nobody is in no slice: nobody is eligible for the freed zone
    cur = st['current']
    assert cur['kind'] == 'clear' and cur['person_id'] is None and cur['zone'] == 'inner-1'
    assert cur['dur'] == S.duration(st, 'inner-1', 0.4) == 108
    d = S.describe_current(st, info, 2000)
    assert d['kind'] == 'clear' and d['person_id'] is None and d['steps'] == ['Clearing a spot'] and d['step'] == 0
    assert st['zones']['inner-1'] == {'person_id': None, 'interest_ids': [], 'dirty': True}  # dirty until done
    S.advance(st, info, 2000 + 108)
    assert st['zones']['inner-1'] == {'person_id': None, 'interest_ids': [], 'dirty': False}
    assert st['current']['idle'] is True      # the lone remaining person is not redrawn (3 or fewer interests)


def test_skip_redraws_same_zone_other_person_skipped_to_back():
    st, info = make(8)
    S.advance(st, info, 1000)
    first = st['current']['person_id']
    S.skip(st, info, 1050)
    cur = st['current']
    assert cur['zone'] == 'centre' and cur['kind'] == 'draw' and cur['person_id'] != first
    assert first not in S.on_table(st)
    assert st['queue'][-1] == cur['person_id']
    assert st['queue'][-2] == first  # skipped person is behind everyone who has not just drawn
    S.start_turn(st, info, 1400)      # not a centre turn, so no hold: the fill goes on with inner-1
    assert st['current']['zone'] == 'inner-1'


def test_skip_only_person_gives_clear_turn():
    st, info = make(1, interests=5)
    S.advance(st, info, 1000)
    S.skip(st, info, 1010)
    assert st['current']['kind'] == 'clear' and st['current']['zone'] == 'centre'
    assert st['zones']['centre']['dirty'] is True


def _shrink(st, info, keep):
    """Delete people who are off the table until `keep` joined people remain."""
    for p in list(st['queue']):
        if len(st['queue']) <= keep:
            break
        if p not in S.on_table(st):
            S.remove_person(st, p, 3000)
            del info[p]


def test_removal_empties_slices_nothing_is_retired():
    st, info = make(8)
    run(st, info, 9)    # centre and all 8 slices (the centre person has a slice too)
    gone = [st['zones'][z]['person_id'] for z in ('inner-1', 'outer-1', 'inner-2')]
    for p in gone:
        S.remove_person(st, p, 3000)
        del info[p]
    kept = {z: st['zones'][z]['person_id'] for z in S.ZONES if z not in ('inner-1', 'outer-1', 'inner-2')}
    t, order = 3000, []
    for _ in range(3):      # everybody left already has a slice, so each freed slice is only cleared, oldest first
        assert S.start_turn(st, info, t)
        cur = st['current']
        assert cur['kind'] == 'clear' and cur['person_id'] is None
        order.append(cur['zone'])
        t += cur['dur']
    assert order == ['inner-1', 'outer-1', 'inner-2']
    S.start_turn(st, info, t)
    assert st['current']['zone'] == 'centre' and st['current']['kind'] == 'draw'
    for z, p in kept.items():           # nobody else was moved
        assert st['zones'][z]['person_id'] == p or z == 'centre'
    assert all(st['zones'][z] == {'person_id': None, 'interest_ids': [], 'dirty': False} for z in order)


def test_skip_during_clear_and_when_idle_is_noop():
    st, info = make(1, interests=5)
    S.advance(st, info, 1000)
    S.skip(st, info, 1010)
    before = copy.deepcopy(st)
    S.skip(st, info, 1020)
    assert st == before
    st2 = S.new_state()
    S.skip(st2, {}, 100)
    assert st2 == S.new_state()


def test_upcoming_includes_clear_turns():
    st, info = make(5)
    run(st, info, 6)
    victim = st['zones']['inner-1']['person_id']
    S.remove_person(st, victim, 3000)
    del info[victim]
    up = S.project(st, info, 3000)
    assert up[0]['kind'] == 'clear' and up[0]['zone'] == 'inner-1'
    assert up[0]['person_id'] is None and up[0]['interest_ids'] == []
    assert all(u['kind'] == 'draw' and u['person_id'] is not None for u in up[1:])
    assert up[1]['at'] >= up[0]['at'] + 108


def test_at_most_centre_plus_slice_with_random_deletes_and_skips():
    import random
    for seed in range(8):
        rnd = random.Random(seed)
        n = rnd.choice([3, 5, 8, 12, 30])
        st, info = make(n)
        nxt = n + 1
        t = 1000
        for _ in range(200):
            r = rnd.random()
            if r < 0.12 and st['queue']:
                v = rnd.choice(st['queue'])
                S.remove_person(st, v, t)
                info.pop(v)
                if rnd.random() < 0.7:
                    info[nxt] = {'name': 'P%d' % nxt, 'faces': 1, 'interests': [nxt * 100]}
                    S.add_person(st, nxt)
                    nxt += 1
            elif r < 0.3:
                S.skip(st, info, t)
            elif not S.start_turn(st, info, t):
                pass
            for p in S.on_table(st):
                zs = S.person_zones(st, p)
                assert len(zs) <= 2 and (len(zs) == 1 or zs[0] == 'centre'), (seed, p, zs)  # twice only centre + slice
            for z in st['zones'].values():
                assert not (z.get('dirty') and z['person_id'] is not None)
            cur = st['current']
            if cur:
                assert cur['kind'] == ('clear' if cur['person_id'] is None else 'draw')
                t += cur['dur']


# ---------- removal, skip, pause, reset under the new rules ----------

def test_removal_in_fill_mode_redraws_with_someone_not_in_a_slice():
    st, info = make(8)
    run(st, info, 4)                          # centre + inner-1, outer-1, inner-2; five people still in no slice
    victim = st['zones']['outer-1']['person_id']
    S.remove_person(st, victim, 2000)
    del info[victim]
    assert S.start_turn(st, info, 2000)
    c = st['current']
    assert (c['zone'], c['kind']) == ('outer-1', 'draw') and c['person_id'] in (5, 6, 7, 8)   # never-featured, queue order
    assert c['person_id'] == 5


def test_removal_in_steady_state_clears_the_slice_and_centre_goes_on():
    st, info = make(6)
    run(st, info, 9)
    cur_centre = st['current']['person_id']
    victim = st['zones']['inner-2']['person_id']
    S.remove_person(st, victim, 2000)
    del info[victim]
    t = st['current']['ends_at']
    S.advance(st, info, t)
    assert st['current']['kind'] == 'clear' and st['current']['zone'] == 'inner-2'
    assert st['zones']['inner-2']['dirty'] is True
    S.advance(st, info, t + 108)
    assert st['zones']['inner-2']['dirty'] is False and st['zones']['inner-2']['person_id'] is None
    assert st['current']['zone'] == 'centre'
    # only centre turns from now on, nobody drawn into inner-2 (everyone left has a slice)
    seq = run(st, info, 8)
    assert {z for z, _ in seq} == {'centre'} and victim not in {p for _, p in seq}


def test_removal_in_alternation_mode_is_redrawn_by_someone_off_the_table():
    st, info = make(15)
    run(st, info, 20, unique=True)
    victim = next(z for z in S.SLICES if st['zones'][z]['person_id'] is not None)
    pid = st['zones'][victim]['person_id']
    off_before = set(st['queue']) - S.on_table(st)
    S.remove_person(st, pid, 9000)
    del info[pid]
    assert S.start_turn(st, info, 9000)
    c = st['current']
    assert (c['zone'], c['kind']) == (victim, 'draw') and c['person_id'] in off_before


def test_skip_in_fill_and_in_alternation():
    st, info = make(8)
    run(st, info, 3)
    first = st['current']['person_id']
    zone = st['current']['zone']
    S.skip(st, info, 2000)
    c = st['current']
    assert c['zone'] == zone and c['person_id'] not in (first, None) and first not in S.on_table(st)
    st, info = make(15)
    run(st, info, 14)
    zone, first = st['current']['zone'], st['current']['person_id']
    S.skip(st, info, 9000)
    c = st['current']
    assert c['zone'] == zone and c['person_id'] != first and c['kind'] == 'draw'
    assert first not in S.on_table(st)


def test_skip_during_hold_is_noop_and_pause_freezes_hold():
    st, info, t = filled(6)
    S.advance(st, info, t)
    end = st['current']['ends_at']
    S.advance(st, info, end)
    assert st['current']['done'] is True and st['current']['hold_until'] == end + 60
    before = copy.deepcopy(st)
    S.skip(st, info, end + 5)
    assert st == before                                   # nothing is in progress to skip
    S.set_paused(st, True, end + 20)
    assert st['remaining'] == 40
    S.advance(st, info, end + 5000)
    assert st['current']['done'] is True and st['turn'] == before['turn']        # frozen
    up = S.project(st, info, end + 5000)
    assert up[0]['at'] == end + 5000 + 40
    S.set_paused(st, False, end + 6000)
    assert st['current']['hold_until'] == end + 6040
    S.advance(st, info, end + 6039)
    assert st['turn'] == before['turn']
    S.advance(st, info, end + 6040)
    assert st['turn'] == before['turn'] + 1 and st['current']['started_at'] == end + 6040


def test_worker_reset_then_fill_from_scratch():
    st, info = make(6)
    run(st, info, 10)
    S.reset_table(st)
    assert st['current'] is None and all(z['person_id'] is None for z in st['zones'].values())
    assert st['last_drawn'] == {} and st['last_end'] is None and all(v['c'] == v['s'] == 0 for v in st['people'].values())
    turn = st['turn']
    seq = run(st, info, 7)
    assert [z for z, _ in seq] == ['centre'] + FILL[:6]
    assert st['turn'] == turn + 7
    assert len({p for _, p in seq}) == 6


# ---------- auto_advance off (the default): only the table, the host or a removal finishes a turn ----------

def test_auto_advance_defaults_off_also_for_old_saved_states():
    assert S.new_state()['settings']['auto_advance'] is False
    old = S.new_state()
    del old['settings']['auto_advance']
    assert S.auto_advance(old) is False and S.clock_mode(old, 5000) == 'idle'
    S.set_settings(old, auto_advance=True)
    assert S.auto_advance(old) is True and S.clock_mode(old, 5000) == 'simulated'


def test_time_never_finishes_or_advances_a_turn_when_off():
    st, info = make(4, auto=False)
    S.advance(st, info, 1000)
    first = copy.deepcopy(st['current'])
    assert first['turn'] == 1
    for t in (1000 + 270, 1000 + 5000, 1000 + 10 ** 6):
        S.advance(st, info, t)
        assert st['current']['turn'] == 1 and not st['current']['idle'] and not st['current'].get('closed')
        assert S.percent(st, t) == 0
    assert st['current']['started_at'] == first['started_at'] and st['turn'] == 1


def test_turn_starts_by_itself_on_an_empty_idle_table():
    st, info = make(0, auto=False)
    S.advance(st, info, 1000)
    assert st['current'] is None
    S.add_person(st, 1)
    info[1] = {'name': 'P1', 'faces': 1, 'interests': [100]}
    S.advance(st, info, 1001)
    assert st['current']['turn'] == 1 and st['current']['zone'] == 'centre' and S.clock_mode(st, 1001) == 'idle'


def test_driver_done_advances_and_percent_is_the_drivers_last_value():
    st, info = make(4, auto=False)
    S.advance(st, info, 1000)
    assert S.progress(st, info, 1, 40, False, 1010)
    assert S.clock_mode(st, 1010) == 'table' and S.percent(st, 1010) == 40
    # the driver goes quiet: idle again, the last reported value stays (not time based)
    assert S.clock_mode(st, 1010 + 130) == 'idle' and S.percent(st, 1010 + 5000) == 40
    assert S.progress(st, info, 1, 100, True, 2000)
    assert st['current']['turn'] == 2
    assert S.percent(st, 2000) == 0 and S.percent(st, 2000 + 5000) == 0      # nothing reported for turn 2
    assert not S.progress(st, info, 1, 50, False, 2001)                     # stale turn refused


def test_hold_end_without_driver_starts_next():
    st, info = make(6, auto=False)
    S.advance(st, info, 1000)
    t = 1000
    while True:                                           # driver finishes turns until a centre hold shows up
        cur = st['current']
        S.progress(st, info, cur['turn'], 100, True, t)
        t += 10
        if st['current'].get('done'):
            break
        assert st['turn'] < 30
    done_turn = st['current']['turn']
    hold = st['current']['hold_until']
    S.advance(st, info, hold - 1)
    assert st['current']['turn'] == done_turn and st['current']['done']
    S.advance(st, info, hold + 500)                       # the driver has been quiet for minutes
    assert st['current']['turn'] == done_turn + 1 and not st['current'].get('done')
    assert S.clock_mode(st, hold + 500) == 'idle'


def test_skip_and_removal_still_work_when_off():
    st, info = make(3, auto=False)
    S.advance(st, info, 1000)
    S.skip(st, info, 1100)
    assert st['current']['turn'] == 2 and st['zones']['centre']['person_id'] != 1
    cur = st['current']
    S.remove_person(st, cur['person_id'], 1200)
    S.advance(st, info, 1200)
    assert st['current']['turn'] == 3 and st['current']['person_id'] != cur['person_id']
    S.advance(st, info, 10 ** 6)
    assert st['current']['turn'] == 3


def test_project_is_unchanged_in_shape_when_off():
    st, info = make(4, auto=False)
    S.advance(st, info, 1000)
    pr = S.project(st, info, 1000)
    assert len(pr) >= 4 and [u['person_id'] for u in pr][:3] == [2, 3, 4]


def test_feature_now_goes_first_then_normal_rotation():
    st, info = make(14, auto=False)
    t = 0
    for _ in range(12):                         # fill the table
        t = go(st, info, t) + 300
    victim = st['zones']['inner-4']['person_id']
    centre_before = st['zones']['centre']['person_id']
    assert S.feature(st, 14, ['centre', 'inner-4'])
    assert [(u['zone'], u['person_id']) for u in S.project(st, info, t, count=2)] == [('centre', 14), ('inner-4', 14)]
    t = go(st, info, t) + 300
    assert (st['current']['zone'], st['current']['person_id'], st['current']['kind']) == ('centre', 14, 'draw')
    assert st['forced'] == [{'person_id': 14, 'zone': 'inner-4'}]
    t = go(st, info, t) + 300
    assert (st['current']['zone'], st['current']['person_id']) == ('inner-4', 14)
    assert st['forced'] == []
    assert S.person_zones(st, 14)[:1] == ['centre'] and 'inner-4' in S.person_zones(st, 14)
    assert victim not in (14, None) and 'inner-4' not in S.person_zones(st, victim)   # replaced, just off the table
    assert centre_before != 14
    for _ in range(30):                         # the rotation carries on and everyone still gets turns
        t = go(st, info, t) + 300
        assert st['current']['kind'] in ('draw', 'clear')
    assert all(S.featured(st, p) > 0 for p in range(1, 15))


def test_feature_needs_a_joined_person_and_is_dropped_on_removal():
    st, info = make(3, auto=False)
    assert not S.feature(st, 99, ['centre'])
    go(st, info, 0)
    assert S.feature(st, 3, ['centre', 'outer-2', 'nowhere', 'outer-2'])
    assert st['forced'] == [{'person_id': 3, 'zone': 'centre'}, {'person_id': 3, 'zone': 'outer-2'}]
    assert S.feature(st, 2, ['centre'])          # a newer request goes ahead
    assert st['forced'][0] == {'person_id': 2, 'zone': 'centre'}
    S.remove_person(st, 3, 10)
    assert st['forced'] == [{'person_id': 2, 'zone': 'centre'}]
    cur = st['current']
    if cur and cur['person_id'] == 2 and cur['zone'] == 'centre':    # already drawing there: nothing to add
        S.feature(st, 2, ['centre'])
        assert st['forced'] == []
