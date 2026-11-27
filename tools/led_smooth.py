#!/usr/bin/env python3
"""Measure how smooth the ring light really is, from the table's own frame log (firmware v8.9m+ /ledlog).

Sends LIGHT commands only (/led ... tmp=1, which is never saved; /cfg?mark=1 for the orientation marker) and hands the
ring back with /led?restore=1 at the end. Never sends a motion command. Refuses to run unless the table is idle.

    python3 tools/led_smooth.py [scenario ...] [--out captures/led_smooth_<label>.json] [--label before]
    python3 tools/led_smooth.py --list

Per scenario it reports, for each logged LED:
  interval   frame-to-frame time from the log: mean, p99, max (ms)
  step       the largest change in perceived light (luminance) between successive 1/60 s windows of the
             time-averaged output, relative to the brighter of the two (0.05 = a 5 % jump). `step_ideal` is the same
             for the unrounded values the light code wanted, so step - step_ideal is what rounding added.
  steps>2%   how many windows jumped more than 2 % beyond what the ideal did (visible stair steps in a slow fade)
  hue        the largest colour error of the time-averaged output against the ideal, at levels below 10 counts
             (distance in r/(r+g+b), g/(r+g+b); 0.02 is about where a tint shift is noticeable)
  flicker    only with full-rate logs (k=1): RMS of the output's 16 to 62 Hz content relative to its mean level.
             0 means no dither flicker; the v8.4 dither that Bill saw flicker was of order 0.3 at dim levels.
Also: /status response time and free_heap while the light runs, and the firmware's running frame statistics.
"""
import json, struct, sys, time, urllib.request, statistics as st

HOST = "http://10.0.0.204"
DUMP = "--dump" in sys.argv
WHILE_DRAWING = "--while-drawing" in sys.argv   # light-only tests are allowed while the table draws (never motion)
LEDS = [0, 21, 11, 32]
DAY, EVE, NIGHT = 220, 77, 18     # owner's brightness; x0.35 evening; quiet-hours cap 50 x0.35 evening

def get(path, timeout=8, raw=False):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        b = r.read()
    return b if raw else b.decode(errors="replace")

def status():
    return json.loads(get("/status"))

def led(q):
    return get("/led?" + q + "&tmp=1")

# name: (list of (seconds_from_start, light command or None), record seconds, note)
def scen():
    S = {}
    for nm, b in (("day", DAY), ("eve", EVE), ("night", NIGHT)):
        S[f"show_{nm}"] = ([(0, f"mode=show&c=ffb060&b={b}&period=60")], 12, "show light circling (period 60 s to see more motion)")
        S[f"aurora_{nm}"] = ([(0, f"mode=aurora&b={b}")], 12, "aurora")
        S[f"breath_{nm}"] = ([(0, f"mode=breath&c=ffb060&b={b}")], 19, "4-7-8 breathing, one full cycle")
        S[f"fadeout_{nm}"] = ([(0, f"mode=solid&c=ffb060&b={b}"), (3, f"mode=off&b={b}")], 6, "solid amber, then off: the fade tail")
    S["fireflies_eve"] = ([(0, f"mode=fireflies&c=ffb060&b={EVE}")], 12, "fireflies at evening level")
    S["follow_day"] = ([(0, f"mode=follow&c=ffb060&b={DAY}")], 6, "follow glow (ball resting)")
    S["cut_show_aurora"] = ([(0, f"mode=show&c=ffb060&b={DAY}&period=240"), (3, f"mode=aurora&b={DAY}")], 7, "scene change show -> aurora")
    S["cut_bright"] = ([(0, f"mode=solid&c=ffb060&b={DAY}"), (3, f"mode=solid&c=ffb060&b={NIGHT}")], 6, "brightness 220 -> 18 (as quiet hours start)")
    S["cut_colour"] = ([(0, f"mode=solid&c=ffb060&b={EVE}"), (3, f"mode=solid&c=5fd0c0&b={EVE}")], 6, "colour amber -> teal")
    S["flash"] = ([(0, f"mode=solid&c=ffb060&b={EVE}"), (3, "flash=1")], 5, "button acknowledge flash")
    S["fullrate_night"] = ([(0, f"mode=breath&c=ffb060&b={NIGHT}")], 4, "full-rate log, dim 4-7-8: flicker check")
    S["fullrate_eve"] = ([(0, f"mode=aurora&b={EVE}")], 4, "full-rate log, aurora at evening level: flicker check")
    return S

def parse(b):
    nl_end = b.index(b"\n"); hdr = b[:nl_end].decode().split(); body = b[nl_end + 1:]
    assert hdr[0] == "OASISLOG2", hdr
    nl, n, k = int(hdr[1]), int(hdr[2]), int(hdr[3]); leds = [int(x) for x in hdr[4:4 + nl]]
    rec = 8 + 12 * nl; out = []
    for j in range(n):
        p = body[j * rec:(j + 1) * rec]
        t, w, m = struct.unpack_from("<IHb", p, 0)
        L = []
        for q in range(nl):
            v = struct.unpack_from("<6H", p, 8 + 12 * q)
            L.append(([x / k for x in v[:3]], [x / 256 for x in v[3:]]))
        out.append((t, w, m, L))
    return k, leds, out

def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

def chroma(c):
    s = c[0] + c[1] + c[2]
    return (c[0] / s, c[1] / s) if s > 0 else (0, 0)

def box(x, n):
    o, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n: s -= x[i - n]
        o.append(s / min(i + 1, n))
    return o

def analyse(k, leds, recs, fps):
    ts = [r[0] for r in recs]; iv = [(b - a) / 1000.0 / k for a, b in zip(ts, ts[1:])]
    res = {"records": len(recs), "k": k, "interval_ms": {"mean": round(st.mean(iv), 2), "p99": round(sorted(iv)[int(0.99 * (len(iv) - 1))], 2), "max": round(max(iv), 2)} if iv else {},
           "work_us_max": max(r[1] for r in recs)}
    win = max(1, round(fps / 60 / k))      # records per 1/60 s window (1 unless full rate)
    per = []
    for q, li in enumerate(leds):
        o = [r[3][q][0] for r in recs]; idl = [r[3][q][1] for r in recs]
        # 1/60 s windows of the time-averaged output (the ideal: its last value in the window)
        W = [[sum(o[j + a][c] for a in range(win)) / win for c in range(3)] for j in range(0, len(o) - win + 1, win)]
        I = [idl[j + win - 1] for j in range(0, len(o) - win + 1, win)]
        def steps(S):
            Y = [lum(c) for c in S]
            return [abs(b - a) / max(a, b, 0.5) for a, b in zip(Y, Y[1:])]
        so, si = steps(W), steps(I)
        exc = [a - b for a, b in zip(so, si)]
        # hue: 50 ms averages, where the ideal is below 10 counts and above 0.3
        h = max(1, round(3))
        hue = 0.0; hue_at = None
        for j in range(0, len(W) - h + 1, h):
            Wa = [sum(W[j + a][c] for a in range(h)) / h for c in range(3)]; Ia = [sum(I[j + a][c] for a in range(h)) / h for c in range(3)]
            if 0.3 <= max(Ia) <= 10:
                co, ci = chroma(Wa), chroma(Ia); d = ((co[0] - ci[0]) ** 2 + (co[1] - ci[1]) ** 2) ** 0.5
                if d > hue: hue, hue_at = d, round(max(Ia), 2)
        d = {"led": li, "step": round(max(so), 3) if so else 0, "step_ideal": round(max(si), 3) if si else 0,
             "excess": round(max(exc), 3) if exc else 0, "steps>2%": sum(1 for e in exc if e > 0.02),
             "hue": round(hue, 3), "hue_at": hue_at, "peak": round(max(lum(c) for c in W), 2) if W else 0}
        if k == 1:                                        # flicker: 16-80 Hz content of the raw bytes
            n80, n16 = max(1, round(fps / 62)), max(2, round(fps / 16)); fl = 0.0
            for c in range(3):
                x = [v[c] for v in o]; m = st.mean(x)
                if m < 0.05: continue
                a, b = box(x, n80), box(x, n16)
                r = (st.mean([(p - s) ** 2 for p, s in zip(a[n16:], b[n16:])]) ** 0.5) / m if len(x) > n16 + 2 else 0
                fl = max(fl, r)
            d["flicker"] = round(fl, 3)
        per.append(d)
    # the whole ring as the eye takes it in: the logged LEDs summed
    Wt = [sum(lum([sum(recs[j + a][3][q][0][c] for a in range(win)) / win for c in range(3)]) for q in range(len(leds))) for j in range(0, len(recs) - win + 1, win)]
    It = [sum(lum(recs[j + win - 1][3][q][1]) for q in range(len(leds))) for j in range(0, len(recs) - win + 1, win)]
    so = [abs(b - a) / max(a, b, 0.5) for a, b in zip(Wt, Wt[1:])]; si = [abs(b - a) / max(a, b, 0.5) for a, b in zip(It, It[1:])]
    res["ring"] = {"step": round(max(so), 3) if so else 0, "excess": round(max(a - b for a, b in zip(so, si)), 3) if so else 0,
                   "steps>2%": sum(1 for a, b in zip(so, si) if a - b > 0.02)}
    res["leds"] = per
    res["worst"] = {key: max(p[key] for p in per) for key in ("step", "excess", "steps>2%", "hue") }
    if k == 1: res["worst"]["flicker"] = max(p.get("flicker", 0) for p in per)
    return res

def run(name, spec, fps):
    cmds, secs, note = spec
    full = name.startswith("fullrate")
    k = 1 if full else max(1, round(fps / 60))            # one record per 1/60 s window (the bytes are summed over it)
    nl = len(LEDS); need = int(secs * fps / k) + 2
    for cap_bytes in (46000, 22000):
        nl = len(LEDS)
        while nl > 1 and need * (8 + 12 * nl) > cap_bytes: nl -= 1
        n = min(need, cap_bytes // (8 + 12 * nl)); leds = LEDS[:nl]
        try:
            get(f"/ledlog?n={n}&k={k}&leds={','.join(map(str, leds))}"); get("/ledlog?n=0"); break
        except Exception:
            continue
    get("/ledlog?stats=1&reset=1")
    t0 = time.time(); led(cmds[0][1]); time.sleep(2.5)    # let the first scene settle
    get(f"/ledlog?n={n}&k={k}&leds={','.join(map(str, leds))}")
    t1 = time.time(); lat = []
    for at, c in cmds[1:]:
        while time.time() - t1 < at: time.sleep(0.05)
        if c.startswith("flash"): led(c)
        else: led(c)
    while True:
        s0 = time.time(); r = get("/ledlog"); lat.append(time.time() - s0)
        if not r.startswith("recording"): break
        time.sleep(0.4)
    k, leds, recs = parse(get("/ledlog", raw=True, timeout=20))
    get("/ledlog?n=0")
    res = analyse(k, leds, recs, fps)
    if DUMP: res["raw"] = [[r[0], r[3]] for r in recs]
    res["note"] = note; res["fw_stats"] = json.loads(get("/ledlog?stats=1"))
    res["poll_ms_max"] = round(1000 * max(lat), 1)
    return res

def main():
    a = [x for x in sys.argv[1:] if x not in ("--dump", "--while-drawing")]; S = scen()
    if "--list" in a:
        for k, v in S.items(): print(k, "-", v[2])
        return
    label = "run"; out = None
    if "--label" in a: i = a.index("--label"); label = a[i + 1]; del a[i:i + 2]
    if "--out" in a: i = a.index("--out"); out = a[i + 1]; del a[i:i + 2]
    names = a or list(S)
    s = status()
    if (s["state"] != "idle" or s["queue"] or s["auto"]) and not WHILE_DRAWING:
        sys.exit("table is busy: not touching the light (add --while-drawing for light-only tests)")
    fps = 1e6 / json.loads(get("/ledlog?stats=1"))["mean_us"]
    print(f"fw {s['fw']}  light runs at about {fps:.0f} frames/s")
    lat = []
    for _ in range(15):
        t = time.time(); status(); lat.append(1000 * (time.time() - t))
    results = {"fw": s["fw"], "fps": round(fps, 1), "label": label, "time": time.strftime("%Y-%m-%d %H:%M"),
               "status_ms": {"median": round(st.median(lat), 1), "max": round(max(lat), 1)}, "free_heap": s["free_heap"], "scenarios": {}}
    try:
        for nm in names:
            s = status()
            if (s["state"] != "idle" or s["queue"] or s["auto"]) and not WHILE_DRAWING:
                print("table became busy: stopping"); break
            r = run(nm, S[nm], fps); results["scenarios"][nm] = r
            w = r["worst"]; iv = r["interval_ms"]
            print(f"{nm:16s} int {iv.get('mean')}/{iv.get('p99')}/{iv.get('max')} ms  step {w['step']:.3f} excess {w['excess']:.3f} "
                  f"n>2% {w['steps>2%']:3d}  hue {w['hue']:.3f}" + (f"  flicker {w['flicker']:.3f}" if "flicker" in w else "")
                  + f"  ring {r['ring']['excess']:.3f}/{r['ring']['steps>2%']}  work<= {r['work_us_max']} us")
    finally:
        get("/led?restore=1")
    lat = []
    for _ in range(15):
        t = time.time(); status(); lat.append(1000 * (time.time() - t))
    results["status_ms_after"] = {"median": round(st.median(lat), 1), "max": round(max(lat), 1)}
    results["free_heap_after"] = status()["free_heap"]
    print("status ms before", results["status_ms"], "after", results["status_ms_after"], "free_heap", results["free_heap"], "->", results["free_heap_after"])
    if out:
        json.dump(results, open(out, "w"), indent=1); print("saved", out)

if __name__ == "__main__":
    main()
