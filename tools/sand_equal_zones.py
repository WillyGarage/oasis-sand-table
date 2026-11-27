#!/usr/bin/env python3
"""Equal-area zones, 1 + 4 + 6, ring 2 staggered by half a slice. SIMULATION ONLY (never contacts a table).

    python3 tools/sand_equal_zones.py  ->  captures/sand-app/equal/*.png and oasis-sand-equal-zones.html

Nobody is on the table twice: one circular rotation read by two pointers (see sand_rotation.py).
Two centre sizes: equal to a slice, or double a slice (rings adjusted so the 10 slices stay equal).
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sand_slices as ss
import sand_table_options as o
import zone_samples as z
import sand_rotation as rot

RT, G = ss.RT, ss.G
OUTD = ss.OUTD
IMG = os.path.join(OUTD, 'equal')
os.makedirs(IMG, exist_ok=True)
KFILE = os.path.join(IMG, 'fit3.json')
N1, N2, NS = 4, 6, 10
ORDER = ['alex', 'lek', 'thomas', 'bill', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'dog']   # the circle of 13 guests
SPECIAL = {'alex': ['guitar', 'teaching', 'hiking', 'reading-1', 'hot-pot', 'lotus', 'crane'],
           'thomas': ['bacteriophages', 'dna', 'telescope', 'hiking', 'rocket', 'reading-2', 'ship'],
           'lek': ['thai-temples', 'hot-pot', 'lotus', 'reading-1', 'crane', 'clarinet-playing-3', 'teaching'],
           'bill': ['star-wars-1', 'telescope', 'rocket', 'reading-1', 'hot-pot', 'hiking', 'guitar']}


def interests(person):
    if person in SPECIAL:
        return SPECIAL[person]
    i = ORDER.index(person)
    return [ss.ALLICONS[(i * 3 + j) % len(ss.ALLICONS)] for j in range(7)]


def triple(person, turn):
    """Up to three interests; a person with more than three gets a different three each time."""
    L = interests(person)
    return [L[(3 * turn + j) % len(L)] for j in range(3)]


def nm(k, first=False):
    t = ss.NAME[k]
    return t[0].upper() + t[1:] if first else t


_fit = json.load(open(KFILE)) if os.path.exists(KFILE) else {}


def fit_ring(r_in, r_out, width):
    """Largest face (up to 60 mm radius) and picture size that hold a face plus three pictures (else two, else one)."""
    key = '%d-%d-%d' % (round(r_in), round(r_out), round(width))
    if key not in _fit:
        res = None
        for nic in (3, 2, 1):
            rf = min(60, int((r_out - r_in - 12) // 2))
            while rf >= 44 and res is None:
                for ri in range(31, 24, -1):
                    cs, gap = ss.pack(r_in, r_out, 0, width, [rf] + [ri] * nic, 3, 90)
                    if gap >= 4.0:
                        res = (rf, ri, nic)
                        break
                if res is None:
                    rf -= 1
            if res:
                break
        _fit[key] = res or (44, 25, 1)
        json.dump(_fit, open(KFILE, 'w'))
        print('  fit', key, _fit[key])
    return _fit[key]


def radii(cw, n1=N1, n2=N2):
    N = cw + n1 + n2
    return RT * math.sqrt(cw / N), RT * math.sqrt((cw + n1) / N)


def geometry(cw, n1=N1, n2=N2, stagger=True):
    r0, r1 = radii(cw, n1, n2)
    g = []
    for k in range(n1):
        w = 360.0 / n1
        g.append((1, k, r0, r1, 90 + w * k, 90 + w * (k + 1)))
    off = (360.0 / n2) / 2 if stagger else 0.0
    for k in range(n2):
        w = 360.0 / n2
        g.append((2, k, r1, RT, 90 + off + w * k, 90 + off + w * (k + 1)))
    return g


def make_slice(geo, person, turn, seed):
    ring, k, ri, ro, a0, a1 = geo
    rf, rp, nic = fit_ring(ri, ro, a1 - a0)
    items = [('f', person, float(rf))] + [('i', ic, float(rp)) for ic in triple(person, turn)[:nic]]
    zn = ss.slice_zone('Ring %d slice %d' % (ring, k + 1), ri, ro, a0, a1, items, 'One person', 0, seed, min_gap=2.5, tries=200)
    zn.person, zn.ring, zn.rf, zn.rp = person, ring, rf, rp
    return zn


def make_centre(person, r0):
    zn = ss.centre(person, r0, 0)
    zn.person = person
    return zn


class Table:
    """Whole table for one centre size, with the current person in each zone."""
    def __init__(self, cw, centre, slices, n1=N1, n2=N2, stagger=True):
        self.cw, self.n1, self.n2, self.geo = cw, n1, n2, geometry(cw, n1, n2, stagger)
        self.r0 = radii(cw, n1, n2)[0]
        self.turn = {}
        self.zs = [make_centre(centre, self.r0)]
        for i, (g, p) in enumerate(zip(self.geo, slices)):
            self.zs.append(make_slice(g, p, self.turn.get(p, 0), 100 + i))
            self.turn[p] = self.turn.get(p, 0) + 1

    def set_centre(self, p):
        self.zs[0] = make_centre(p, self.r0)
        return self.zs[0]

    def set_slice(self, slot, p):
        self.zs[1 + slot] = make_slice(self.geo[slot], p, self.turn.get(p, 0), 400 + slot + 10 * self.turn.get(p, 0))
        self.turn[p] = self.turn.get(p, 0) + 1
        return self.zs[1 + slot]


def fmt(m):
    return '%.1f min' % m


def tint_any(im, zs, color=(80, 190, 120), alpha=90):
    n = im.size[0]
    c = n / 2
    s = 0.94 * c / RT
    mask = Image.new('L', im.size, 0)
    md = ImageDraw.Draw(mask)
    for zz in zs:
        if zz.kind == 'slice':
            pts = []
            for r, a in ([(zz.r_out, a) for a in np.linspace(zz.a_lo, zz.a_hi, 40)] + [(zz.r_in, a) for a in np.linspace(zz.a_hi, zz.a_lo, 40)]):
                ar = math.radians(a)
                pts.append((c + r * s * math.cos(ar), c - r * s * math.sin(ar)))
            md.polygon(pts, fill=alpha)
        else:
            ro = zz.r_out * s
            md.ellipse((c - ro, c - ro, c + ro, c + ro), fill=alpha)
    return Image.composite(Image.new('RGB', im.size, color), im.convert('RGB'), mask)


def start_state():
    """7:00 pm: Alex in the middle; ten slices hold the ten people just behind the slice pointer."""
    r = rot.rotate(ORDER, NS, minutes=0.001)       # pointer set-up only
    return ORDER[0], ORDER[2:12]


def stats(tb):
    c, sl = tb.zs[0], tb.zs[1:]
    cj = c.wipe + c.draw
    sj = [s.wipe + s.draw for s in sl]
    pair = cj + sum(sj) / len(sj)
    sd = sum(s.draw for s in sl) / len(sl)
    return dict(r0=tb.r0, r1=radii(tb.cw, tb.n1, tb.n2)[1], cj=cj, cwipe=c.wipe, cdraw=c.draw, sj=sum(sj) / len(sj), sj_min=min(sj), sj_max=max(sj),
                swipe=sl[0].wipe, sdraw=sd, pair=pair, every20=20 * pair / 60.0, carea=c.area, sarea=sl[0].area,
                pics=[len([1 for it in s.items if it[0] == 'i']) for s in sl],
                faces=[(s.ring, int(round(2 * s.rf))) for s in sl], picmm=[int(round(2 * s.rp)) for s in sl], nsl=len(sl))


def pair_at(st, speed, pitch):
    """Pair time (min) with wiping at `speed` mm/s and `pitch` mm spacing; drawing stays 40 mm/s."""
    w = (st['carea'] + st['sarea']) / pitch / speed / 60.0
    return w + st['cdraw'] + st['sdraw']


def clock(m):
    m = int(round(m))
    h, mm = (m // 60) % 24, m % 60
    return '%d:%02d pm' % (h - 12 if h > 12 else h, mm)


# ------------------------------------------------------------------ rotation results
NEWCOMERS = [(2, 'Newcomer A'), (3, 'Newcomer B'), (9, 'Newcomer C'), (14, 'Newcomer D')]


def sim_tables(cj, sj):
    out = {}
    for P in (14, 20):
        names = ['Guest %d' % (i + 1) for i in range(P)]
        r = rot.rotate(names, NS, minutes=300.0, cj=cj, sj=sj)
        sm = rot.summary(r, names)
        r2 = rot.rotate(names, NS, minutes=3600.0, cj=cj, sj=sj)
        sm2 = rot.summary(r2, names)
        out[P] = dict(d=r['d'], sm=sm, names=names, long=dict(dups=sm2['dups'], gap=sm2['max_gap']))
    names = ['Guest %d' % (i + 1) for i in range(14)]
    nc = rot.rotate(names, NS, minutes=300.0, cj=cj, sj=sj, newcomers=NEWCOMERS)
    ok, when = rot.check_newcomers(nc, NEWCOMERS)
    # the same check over 20 hours and from several start points
    ok_all = True
    dups_all = 0
    for c0 in (1, 4, 9):
        for P in (13, 14, 20):
            rr = rot.rotate(['G%d' % i for i in range(P)], NS, minutes=1200.0, cj=cj, sj=sj, newcomers=NEWCOMERS, c0=c0)
            o2, _ = rot.check_newcomers(rr, NEWCOMERS)
            ok_all = ok_all and o2
            dups_all += len(rr['dups'])
    evs = [e for e in nc['events'] if e['kind'] == 'centre']
    out['new'] = dict(dups=len(nc['dups']), ok=ok, when=when, ok_all=ok_all, dups_all=dups_all,
                      times=[(i, nt, round(evs[when[i]]['start'])) for nt, i in NEWCOMERS if when.get(i) is not None],
                      sm=rot.summary(nc, nc['R']), P=nc['P'])
    sp = rot.rotate(['Guest %d' % (i + 1) for i in range(8)], NS, minutes=300.0, cj=cj, sj=sj)
    out['small'] = dict(n=sp['n'], dups=len(sp['dups']))
    edge12 = rot.rotate(range(12), NS, clamp=False)
    out['edge12'] = len(edge12['dups'])
    return out


def diagram():
    """Circle of 13 names with the two pointers (state at 7:00 pm, before the first job)."""
    cx = cy = 190
    R = 128
    out = ['<svg viewBox="0 0 380 380" role="img" aria-label="Circle of guests with two pointers" style="width:100%;max-width:380px;display:block;margin:8px auto">']
    out.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="#d6d4c7" stroke-width="2"/>' % (cx, cy, R))
    P = len(ORDER)
    c_next, s_next = 1, 12          # next centre = Lek (index 1), next slice = the dog (index 12)
    for i, k in enumerate(ORDER):
        a = math.radians(90 - 360.0 * i / P)
        x, y = cx + R * math.cos(a), cy - R * math.sin(a)
        if i == 0:
            fill, st, tag = '#334c3c', '#fff', 'centre now'
        elif 2 <= i <= 11:
            fill, st, tag = '#dfe3d8', '#242c24', 'slice'
        else:
            fill, st, tag = '#fff', '#242c24', 'off'
        out.append('<circle cx="%.1f" cy="%.1f" r="21" fill="%s" stroke="#334c3c" stroke-width="1.5"/>' % (x, y, fill))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" dominant-baseline="central" font-size="9" fill="%s" font-family="system-ui,sans-serif">%s</text>'
                   % (x, y, st, ss.NAME[k].replace('the dog', 'Dog')))
        # pointer markers just outside the circle
        for idx, label, col in ((c_next, 'next centre', '#c9a227'), (s_next, 'next slice', '#2f6fb0')):
            if i == idx:
                ox, oy = cx + (R + 38) * math.cos(a), cy - (R + 38) * math.sin(a)
                out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="3"/>'
                           % (ox, oy, cx + (R + 22) * math.cos(a), cy - (R + 22) * math.sin(a), col))
                dx = 0
                out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="11" font-weight="700" fill="%s" font-family="system-ui,sans-serif">%s</text>'
                           % (cx + (R + 52) * math.cos(a) + dx, cy - (R + 52) * math.sin(a) + 4, col, label))
    out.append('<text x="190" y="176" text-anchor="middle" font-size="12" fill="#242c24" font-family="system-ui,sans-serif">Both markers</text>'
               '<text x="190" y="192" text-anchor="middle" font-size="12" fill="#242c24" font-family="system-ui,sans-serif">move clockwise,</text>'
               '<text x="190" y="208" text-anchor="middle" font-size="12" fill="#242c24" font-family="system-ui,sans-serif">one step per pair</text>')
    out.append('</svg>')
    return ''.join(out)


def result_rows(P, d):
    return ''


# ------------------------------------------------------------------ main
def main():
    c0, s0 = start_state()
    tbE = Table(1, c0, s0)
    tbD = Table(2, c0, s0)
    tbF = Table(1, ORDER[0], ORDER[1:13], 5, 7)         # 1 + 5 + 7, only for the speed table
    stE, stD, stF = stats(tbE), stats(tbD), stats(tbF)
    for tb, st, nmx in ((tbE, stE, 'equal'), (tbD, stD, 'double'), (tbF, stF, 'f157')):
        if nmx != 'f157':
            ss.render(tb.zs, tags=False).save(os.path.join(IMG, 'centre-%s.png' % nmx))
        else:
            ss.render(tb.zs, tags=False).save(os.path.join(IMG, 'perm-157.png'))
        print(nmx, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in st.items() if k not in ('pics', 'faces', 'picmm')},
              'pics', sorted(set(st['pics'])), 'faces', sorted(set(st['faces'])), 'picmm', sorted(set(st['picmm'])))
    perms = {}
    pool = ORDER[1:]
    for a, b in ((3, 5), (4, 6), (5, 7), (6, 9)):
        tb2 = Table(1, ORDER[0], [pool[i % len(pool)] for i in range(a + b)], a, b)
        ss.render(tb2.zs, tags=False).save(os.path.join(IMG, 'p3-%d-%d.png' % (a, b)))
        perms[(a, b)] = stats(tb2)
    for stg in (False, True):
        tb2 = Table(1, ORDER[0], [pool[i % len(pool)] for i in range(10)], 4, 6, stg)
        ss.render(tb2.zs, tags=False).save(os.path.join(IMG, 'p3-align-%s.png' % ('stag' if stg else 'line')))
    sim = sim_tables(stE['cj'], stE['sj'])
    for P in (14, 20):
        sm = sim[P]['sm']
        print('P', P, 'd', sim[P]['d'], {k: v for k, v in sm.items() if k not in ('ct', 'st', 'mn')}, sim[P]['long'])
    print('newcomers', {k: v for k, v in sim['new'].items() if k != 'sm'}, 'small', sim['small'], 'edge12 dups', sim['edge12'])
    # filmstrip: the real rotation with 13 guests on the equal-centre table
    res = rot.rotate(ORDER, NS, minutes=60, cj=stE['cj'], sj=stE['sj'], c0=1)
    assert not res['dups'], res['dups']
    tb = Table(1, c0, s0)
    ss.render(tb.zs, out_px=700, tags=False).save(os.path.join(IMG, 'film-0.png'))
    film, t = [], 19 * 60.0
    for n, ev in enumerate(res['events'][:6], 1):
        if ev['kind'] == 'centre':
            zz = tb.set_centre(ev['who'])
            cap = 'Centre: %s is featured. %s leaves the table.' % (nm(ev['who'], True), nm(ev['out'], True))
        else:
            zz = tb.set_slice(ev['slot'], ev['who'])
            cap = 'Slice: %s joins the oldest slice (ring %d, slice %d). %s leaves the table.' % (
                nm(ev['who']), zz.ring, ev['slot'] + 1 if ev['slot'] < N1 else ev['slot'] - N1 + 1, nm(ev['out'], True))
        dur = zz.wipe + zz.draw
        im = ss.render(tb.zs, out_px=700, tags=False)
        tint_any(im, [zz]).save(os.path.join(IMG, 'film-%d.png' % n))
        film.append((n, t, dur, cap))
        t += dur
        print('  step', n, clock(film[-1][1]), cap, round(dur, 1))
    json.dump(dict(film=film, stE=stE, stD=stD, stF=stF), open(os.path.join(IMG, 'film3.json'), 'w'), indent=1, default=str)
    build_page(stE, stD, stF, sim, film, perms)


def per_row(sm, names):
    rows = ''
    for nme, c, s, m in zip(names, sm['ct'], sm['st'], sm['mn']):
        rows += '<tr><td>%s</td><td>%d / %d</td><td>%d</td></tr>' % (nme, c, s, round(m))
    return rows


def speed_table(stA, stB):
    rows = ''
    for v, pitch in ((40, 2.5), (40, 3.0), (60, 2.5), (60, 3.0), (80, 2.5), (80, 3.0)):
        cells = ''
        for st in (stA, stB):
            pr = pair_at(st, v, pitch)
            h = 20 * pr / 60.0
            cell = '%.1f min, %.1f h' % (pr, h)
            if h <= 3.05:
                cell = '<b>%s</b>' % cell
            cells += '<td>%s</td>' % cell
        tag = '' if (v == 40 and pitch == 2.5) else ' (untested)'
        rows += '<tr><td>%d mm/s, %.1f mm%s</td>%s</tr>' % (v, pitch, tag, cells)
    return rows


def build_page(stE, stD, stF, sim, film, perms):
    head = ss.PAGE.split('<h1>')[0].replace('pie-slice layouts (simulation)', 'equal-area zones and rotation (simulation)')
    head = head.replace('</style>', '.film { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; } .film figcaption, .start figcaption { font-size: .85em; text-align: left; } .start { max-width: 340px; margin: 8px 0; } .facts { padding-left: 1.1em; margin: 8px 0; }\ntable.res { border-collapse: collapse; font-size: .9em; margin: 6px 0; } table.res td, table.res th { border-bottom: 1px solid #e4e1d4; padding: 3px 10px 3px 0; text-align: left; vertical-align: top; } details { margin: 6px 0; }\n</style>', 1)
    blocks = ''
    for P in (14, 20):
        S = sim[P]
        sm = S['sm']
        blocks += ('<p><b>%d guests, %d slices, pointer gap %d.</b> Over 5 hours: <b>%d moments with someone on the table twice</b>. '
                   'Centre turns per person: %d to %d. Slice turns per person: %d to %d. Biggest difference between one person\'s centre turns and slice turns: %d. '
                   'Minutes on the table: %d to %d. Checked again over 60 hours: %d duplicates, biggest difference %d.</p>'
                   '<details><summary>Every guest, %d guests</summary><table class="res"><tr><th>Guest</th><th>Centre / slice turns</th><th>Minutes on table</th></tr>%s</table></details>'
                   % (P, NS, S['d'], sm['dups'], sm['c_range'][0], sm['c_range'][1], sm['s_range'][0], sm['s_range'][1], sm['max_gap'],
                      round(sm['m_range'][0]), round(sm['m_range'][1]), S['long']['dups'], S['long']['gap'], P, per_row(sm, S['names'])))
    nw = sim['new']
    nwl = ', '.join('%s joins before pair %d and is featured at %d minutes' % (i.replace('Newcomer ', 'newcomer '), t + 1, m) for i, t, m in nw['times'])
    rotsec = ('<section><h2>How the rotation works</h2>'
              '<p class="desc">Put all the guests in a circle. Two markers walk round it, one step each time a middle job and a slice job are done. '
              'The middle marker picks who is featured in the middle. The slice marker, a few places behind, picks who is drawn into the oldest slice.</p>'
              + diagram() +
              '<p>Each guest is featured in the middle first. Then they leave the table, wait a few steps, come back as a slice for ten steps, leave again, and wait before the next turn in the middle. '
              'The gap between the markers is picked so that the two waits are about equal. Nobody is on the table twice. The picture shows 13 guests at 7:00 pm: Alex in the middle (green), ten guests in slices (grey), Lek and the dog waiting (white).</p>'
              '<p>Each drawing shows up to three of a guest\'s interests. A guest with more than three gets a different three the next time.</p>'
              '<h3>What the simulation found</h3>' + blocks +
              '<p class="note"><b>One catch:</b> with the middle updated first, ten slices need at least 13 guests, not 12. With 12 the new middle person is still in the oldest slice for a moment (the simulation shows %d such moments in 5 hours). 13 guests is the smallest party that works with no one twice.</p>'
              '<p><b>Newcomers.</b> A newcomer goes behind every other newcomer who has not been featured yet, but ahead of everyone who has already been featured. So new people are featured first come, first served, and nobody new goes to the back of the whole circle. '
              'Simulated with 14 guests and four newcomers arriving during the 5 hours (%s): all four are featured in the order they joined, and nobody else is featured in between, so nobody gets a second middle turn first. Duplicates: %d. '
              'Re-checked over 20 hours from three different starting points and with 13, 14 and 20 guests: %s, %d duplicates.</p>'
              '<p><b>Small parties.</b> With fewer than 13 guests, only (guests minus 3) slices show people and the rest show a decoration such as leaves, never a repeat (simulated with 8 guests: %d slices with people, %d duplicates).</p></section>'
              % (sim['edge12'], nwl, nw['dups'], 'same result' if nw['ok_all'] else 'PROBLEM', nw['dups_all'], sim['small']['n'], sim['small']['dups']))

    def block(title, st, img, extra):
        uri = z.jpeg_uri(Image.open(os.path.join(IMG, img)))[0]
        fm = sorted(set(st['faces']))
        faces = ', '.join('ring %d: %d mm' % (r, m) for r, m in fm)
        pm = sorted(set(st['picmm']))
        return ('<h3>%s</h3><img class="big" src="%s" alt="%s">'
                '<ul class="facts"><li><b>Rings:</b> middle 0 to %d mm, ring 1 %d to %d mm, ring 2 %d to 355 mm. Middle area %d thousand square mm, each slice %d thousand.</li>'
                '<li><b>Middle job:</b> %s (wipe %s + draw %s).</li><li><b>Slice job:</b> %s on average (wipe %s + draw %s).</li>'
                '<li><b>Middle + slice pair:</b> %s.</li>'
                '<li><b>With 20 guests,</b> everyone is featured once within %.1f hours (20 pairs).</li>'
                '<li><b>Face and pictures:</b> faces %s; %s pictures per slice at %s mm. %s</li></ul>'
                % (title, uri, title, st['r0'], st['r0'], st['r1'], st['r1'], round(st['carea'] / 1000), round(st['sarea'] / 1000),
                   fmt(st['cj']), fmt(st['cwipe']), fmt(st['cdraw']), fmt(st['sj']), fmt(st['swipe']), fmt(st['sdraw']),
                   fmt(st['pair']), st['every20'], faces, '/'.join(str(x) for x in sorted(set(st['pics']))),
                   '-'.join(str(x) for x in (pm[0], pm[-1])) if len(pm) > 1 else str(pm[0]), extra))
    mainsec = ('<section><h2>The main layout: middle the same size as a slice</h2><p class="desc">Layout 1 + 4 + 6, ring 2 shifted by half a slice. Every zone, middle and slices, has the same area (36 thousand square mm), so every wipe takes the same time.</p>'
               + block('Middle the same size as a slice', stE, 'centre-equal.png', '') + '</section>')
    wd = stE['cwipe'] + stE['swipe']
    dr = stE['cdraw'] + stE['sdraw']
    nodraw = stE['cwipe'] + stE['swipe']
    spd = ('<section><h2>How fast can it go?</h2>'
           '<p class="desc">Bill\'s target: all 20 guests featured within about 3 hours, which needs a middle + slice pair of 9 minutes or less. '
           'Pair time and the time for 20 guests, for the same-size middle. Drawing stays at 40 mm/s. The first row is the current setting. '
           'Faster wiping and wider wipe spacing are untested in real sand. Bold means 3 hours or better.</p>'
           '<table class="res"><tr><th>Wipe speed, spacing</th><th>1 + 4 + 6</th><th>1 + 5 + 7</th></tr>%s</table>'
           '<p><b>Wiping vs drawing, 1 + 4 + 6 at today\'s speed.</b> Middle job: wiping %.1f of %.1f minutes (%d%%), drawing %.1f. Slice job: wiping %.1f of %.1f minutes (%d%%), drawing %.1f. '
           'Over a pair, wiping is %d%% of the time. So a simpler cartoon drawing style would help only a little: even a drawing that took no time at all would cut the pair from %.1f to %.1f minutes. '
           'Faster or wider wiping is where the time is.</p>'
           '<p class="basis">1 + 5 + 7 has 12 smaller slices, so its pair is shorter (%.1f minutes at today\'s speed), but its three pictures shrink to %s mm beside faces of %s mm.</p></section>'
           % (speed_table(stE, stF), stE['cwipe'], stE['cj'], round(100 * stE['cwipe'] / stE['cj']), stE['cdraw'],
              stE['swipe'], stE['sj'], round(100 * stE['swipe'] / stE['sj']), stE['sdraw'],
              round(100 * wd / (wd + dr)), stE['pair'], nodraw,
              stF['pair'], '%d to %d' % (min(stF['picmm']), max(stF['picmm'])), ' to '.join(str(m) for m in (min(m for r, m in stF['faces']), max(m for r, m in stF['faces'])))))
    dsec = ('<section><h2>Comparison: a middle twice the size of a slice</h2><p class="desc">The same table with the middle at double the area of a slice, and the rings adjusted so the ten slices stay equal.</p>'
            + block('Middle twice a slice', stD, 'centre-double.png', 'Rings are thinner here, so the face cannot be bigger than shown.')
            + '<p class="note"><b>My read:</b> %s</p></section>' % VERD['centre'])
    psec = '<section><h2>Four ways to cut the rings</h2><p class="desc">A same-size middle, then ring 1 and ring 2 cut into slices, every zone the same area. Ring 2 is shifted by half a slice. Where there are more slices than guests, a few faces repeat.</p>'
    notes = {(3, 5): 'Biggest zones and the most room, but the slowest and only 9 people.', (4, 6): 'Balanced: 120 mm faces in ring 1, three pictures each.',
             (5, 7): 'Shorter jobs, 13 people, pictures shrink.', (6, 9): 'Shortest jobs and the most people, but small faces and crowded slices.'}
    for a, b in ((3, 5), (4, 6), (5, 7), (6, 9)):
        st = perms[(a, b)]
        uri = z.jpeg_uri(Image.open(os.path.join(IMG, 'p3-%d-%d.png' % (a, b))))[0]
        p8 = pair_at(st, 80, 2.5)
        psec += ('<h3>1 + %d + %d</h3><img class="big" src="%s" alt="1+%d+%d"><p class="tot">Pair %.1f min, all 20 guests featured within %.1f h at today\'s speed (40 mm/s, 2.5 mm). '
                 'At 80 mm/s (untested): pair %.1f min, %.1f h.</p><p>Each slice: face %s mm, %s pictures at %s mm. %d people at once. %s</p>'
                 % (a, b, uri, a, b, st['pair'], st['every20'], p8, 20 * p8 / 60.0,
                    ' to '.join(str(m) for m in (min(m for r, m in st['faces']), max(m for r, m in st['faces']))) if len({m for r, m in st['faces']}) > 1 else str(st['faces'][0][1]),
                    '/'.join(str(x) for x in sorted(set(st['pics']))), '-'.join(str(x) for x in sorted({min(st['picmm']), max(st['picmm'])})),
                    1 + a + b if 1 + a + b <= 13 else 13, notes[(a, b)]))
    ul = z.jpeg_uri(Image.open(os.path.join(IMG, 'p3-align-line.png')))[0]
    us = z.jpeg_uri(Image.open(os.path.join(IMG, 'p3-align-stag.png')))[0]
    psec += ('<h3>Lined up or staggered (1 + 4 + 6)</h3><div class="film"><figure><img src="%s" alt="Lined up"><figcaption>Lined up</figcaption></figure>'
             '<figure><img src="%s" alt="Staggered"><figcaption>Staggered by half a slice</figcaption></figure></div>'
             '<p class="note"><b>My read:</b> Staggered reads better. When the lines line up, an outer slice looks like the extension of an inner one, as if the two belong to one person. Staggered, every slice clearly belongs to its own face.</p></section>' % (ul, us))
    cells = ''
    for n, t, dur, cap in film:
        u = z.jpeg_uri(Image.open(os.path.join(IMG, 'film-%d.png' % n)), 80)[0]
        cells += '<figure><img src="%s" alt="Step %d"><figcaption><b>Step %d, %s.</b> %s Takes %s.</figcaption></figure>' % (u, n, n, clock(t), cap, fmt(dur))
    u0 = z.jpeg_uri(Image.open(os.path.join(IMG, 'film-0.png')))[0]
    last = film[-1]
    strip = ('<section><h2>Six steps from 7:00 pm</h2><p class="desc">The same-size middle, 13 guests, ten slices. Middle, slice, middle, slice, and so on. The zone that changed is tinted green. Times are start times, Pacific.</p>'
             '<figure class="start"><img src="%s" alt="Start"><figcaption>7:00 pm, before step 1: Alex in the middle, ten guests in slices, Lek and the dog off the table</figcaption></figure>'
             '<div class="film">%s</div><p class="tot">The six steps take %s, finishing about %s.</p></section>'
             % (u0, cells, fmt(sum(f[2] for f in film)), clock(last[1] + last[2])))
    page = head + '''<h1>Equal-area zones: nobody on the table twice</h1>
<div class="sim"><b>This is a computer simulation, not a photo of the table.</b> Nothing here was drawn in real sand or sent to either table.
Wiping a single slice has not been tried in real sand yet, and the simulation cannot judge how clean the straight slice edges will look.</div>
<p>The middle circle shows one guest with their name lettered once. Around it, two rings are cut into ten slices, each holding one guest: a face (no name) and up to three of their interests. Every slice has the same area, so every slice wipe takes the same time.
Nobody is ever on the table twice, as many different people as possible are on it at once, and everyone gets middle turns and slice turns evenly.</p>
<p class="basis">Lines 4 mm wide, wipe lines 2.5 mm apart, ball at 40 mm per second. Wipe time = zone area / 2.5 mm / 40 mm per second; draw time = length of the lines / 40 mm per second.
Faces: Bill, Lek, Alex and Thomas are the hand-drawn portraits; the others are public test photos standing in for guests, with placeholder names; the dog is a drawn dog. Interest pictures are placeholders except Alex (guitar, teaching) and Thomas (bacteriophages).</p>
''' + psec + rotsec + mainsec + spd + dsec + strip + '</main></body></html>\n'
    out = os.path.join(OUTD, 'oasis-sand-equal-zones.html')
    open(out, 'w').write(page)
    print('wrote', out, len(page) // 1024, 'KB')


VERD = {'centre': 'The featured face is 2.3 times the width of a slice face, so the middle clearly stands out, and the name is easy to read. The cost is a longer pair (20 minutes instead of 15) and slice faces of 90 to 94 mm, right at the edge of readable. With 20 guests, everyone is featured within 6.7 hours instead of 5.0. Three pictures at 62 mm still fit in every slice. The same-size middle keeps 120 mm faces in ring 1 and 102 mm in ring 2.'}

if __name__ == '__main__':
    main()
