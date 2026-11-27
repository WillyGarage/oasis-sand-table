#!/usr/bin/env python3
"""SUPERSEDED 2026-11-20 by calibrate_far.py (far branch, firmware v5). Kept for the near-half record.
Oasis calibration: collect camera-measured poses and fit the kinematic model.

  calibrate.py scan                 home, then step m1 outward in 200-step increments (finds the outer limit)
  calibrate.py blocks [N]           N blocks (default 4): home at the current m2, then ~12 poses each
  calibrate.py backlash             approach a few poses from both directions
  calibrate.py fit                  fit captures/calib_v3.jsonl -> firmware-notes/calibration.json

Needs the table on http://10.0.0.204 (firmware v3 + /home) and the camera. Raw data: captures/calib_v3.jsonl
(one JSON object per pose: tag, m1, m2, m2h, best/cands = ball candidates in table-plane coordinates).

MODEL (counters: m1 = 0 at the centre stop after /home, m1 < 0 is outward; m2 is absolute, never re-zeroed
by /home; m2h = m2 counter value at the last /home):
  position = C + r*(cos phi, sin phi)           (x right, y up on screen, unit = sand radius)
  u   = u0 + b2*(m2 - m2h) - b1*m1          elbow angle (rad)
  r   = 2*L*sin(u/2)                         radius about C: a two-link folding arm, link length L
  phi = phi0 + A*m2 + A1*m1 + K*m2h          (K = A1*b2/b1 physically)
Why m2h: the inner stop is a stop on the ELBOW, so homing at a different m2 re-defines where m1 = 0 is.
A linear r = rmin + B2*dm2 - B1*m1 fit about twice as badly (rms 0.015 vs 0.008 R); u0 is the fold-back stop.
Camera: the locator plane is perspective-distorted; gx, gy, s model that (distort()/undistort()).
"""
import sys, json, os, time, random
sys.path.insert(0, "/home/bill/dev/WillyGarage/oasis/tools")
import numpy as np
from oasislib import *

CAL = D + "/firmware-notes/calibration.json"
DEF = dict(Cx=-0.0243, Cy=0.0905, L=0.5084, u0=0.3005, b1=5.2e-4, b2=1.1e-4, phi0=2.1042, A=5.5e-4, A1=3.1e-4, K=6.0e-5, gx=-0.0106, gy=0.1176, s=0.0185, rlo=0.19, rhi=0.80)

def params():
    p = dict(DEF)
    if os.path.exists(CAL):
        j = json.load(open(CAL)); p.update(j.get("near_half_superseded", j)["params"])
    return p

def distort(p, x, y):
    """physical table-plane point -> what the locator reports (camera perspective, fitted)"""
    d = 1 + p["gx"] * x + p["gy"] * y
    return x / d, y * (1 + p["s"]) / d

def undistort(p, X, Y):
    """locator plane coords -> physical table-plane coords"""
    d = 1.0 / (1 - p["gx"] * X - p["gy"] * Y / (1 + p["s"]))
    return X * d, Y * d / (1 + p["s"])

def rmin_of(p): return 2 * p["L"] * np.sin(p["u0"] / 2)

def predict(p, m1, m2, m2h):
    u = p["u0"] + p["b2"] * (m2 - m2h) - p["b1"] * m1
    r = 2 * p["L"] * np.sin(u / 2)
    ph = p["phi0"] + p["A"] * m2 + p["A1"] * m1 + p["K"] * m2h
    return p["Cx"] + r * np.cos(ph), p["Cy"] + r * np.sin(ph), r

def pose(m1, m2, m2h, tag, prev=None, approach="std", extra=None):
    """Go to (m1, m2) approaching from the 'outward, m2-increasing' side (backlash-consistent), then measure."""
    # approach codes: std = arrive moving m1 outward (m1 falling) and m2 rising;
    #   m1opp = arrive moving m1 inward; m2opp = arrive moving m2 falling; bothopp = both opposite
    ov1, ov2 = (200, 300) if approach == "std" else (500, 800)
    d1 = +1 if approach in ("std", "m2opp") else -1      # sign of the m1 overshoot (+ = start from inner side)
    d2 = -1 if approach in ("std", "m1opp") else +1
    raw(m1 + d1 * ov1, m2 + d2 * ov2)
    s = raw(m1, m2)
    r = measure(prev)
    r.update(tag=tag, m1=m1, m2=m2, m2h=m2h, approach=approach, cur1=s["cur1"], cur2=s["cur2"])
    if extra: r.update(extra)
    log(r)
    return r

def cmd_backlash():
    p = params(); m2h = do_home()
    print("backlash block, m2h", m2h, flush=True)
    for dm2, m1 in [(1500, -1000), (3000, -1500), (4500, -800), (800, -1800)]:
        m2 = m2h + dm2
        x, y, r = predict(p, m1, m2, m2h); print(" pose", m1, m2, "pred r %.2f" % r, flush=True)
        assert 0.3 < r < 0.7
        for ap in ("std", "m1opp", "std", "m2opp", "std", "bothopp"):
            q = pose(m1, m2, m2h, "backlash", approach=ap)
            print("   ", ap, q["best"]["X"], q["best"]["Y"], q["best"]["score"], flush=True)

def phys(p, c):
    """candidate dict -> (x, y, r about C, theta rad about C) in the undistorted table plane"""
    x, y = undistort(p, c["X"], c["Y"])
    return x, y, float(np.hypot(x - p["Cx"], y - p["Cy"])), float(np.arctan2(y - p["Cy"], x - p["Cx"]))

def cmd_sync():
    """After a reboot: /home, find the ball at the stop with the camera, tell the firmware its angle (/sync)."""
    p = params(); home()
    r = measure(); log(dict(r, tag="sync", m1=0, m2=status()["cur2"], m2h=status()["cur2"]))
    c = min(r["cands"], key=lambda c: abs(phys(p, c)[2] - rmin_of(p)))
    x, y, rr, th = phys(p, c)
    print("ball at home: r=%.3f (rmin %.3f) theta=%.1f deg score %.2f" % (rr, rmin_of(p), np.degrees(th), c["score"]))
    print(get("/sync?th=%.5f" % th)); print(status())

def goto(th, rho):
    r = get("/goto?th=%.5f&rho=%.5f" % (th, rho))
    if "started" not in str(r): raise RuntimeError(r)
    return wait_idle()

def pick(p, r, th=None, rho=None):
    """choose the ball among candidates: top score, but report whether the candidate nearest the target differs"""
    cs = r["cands"]; top = cs[0]
    out = dict(top=top)
    if th is not None:
        pr = p["rlo"] + rho * (p["rhi"] - p["rlo"])
        tx, ty = p["Cx"] + pr * np.cos(th), p["Cy"] + pr * np.sin(th)
        near = min(cs, key=lambda c: np.hypot(phys(p, c)[0] - tx, phys(p, c)[1] - ty))
        out["near"] = near
    return out

def cmd_hometest():
    p = params(); rng = np.random.default_rng(5)
    res = []
    for rho, th in [(1.0, 1.0), (0.5, 3.5), (0.9, 5.5), (0.2, 7.0), (0.75, 2.2), (0.35, 9.0), (1.0, 10.5), (0.6, 4.0)]:
        goto(th, rho)
        a = measure(); log(dict(a, tag="hometest_start", rho_cmd=rho, th_cmd=th))
        s = home()
        b = measure(); log(dict(b, tag="hometest_home", m1=0, m2=s["cur2"], m2h=s["cur2"]))
        c = min(b["cands"], key=lambda c: abs(phys(p, c)[2] - rmin_of(p)))
        x, y, rr, t = phys(p, c)
        _, _, r0, _ = phys(p, a["cands"][0])
        res.append(rr)
        print("start rho_cmd %.2f (measured r %.3f) -> home r=%.3f theta=%.1f  score %.2f" % (rho, r0, rr, np.degrees(t) % 360, c["score"]), flush=True)
    print("home radius mean %.4f sd %.4f range %.3f..%.3f (units of sand radius)" % (np.mean(res), np.std(res, ddof=1), min(res), max(res)))

VLOG = D + "/captures/verify_v4.jsonl"
def vmeasure(p, th, rho, tag):
    """measure the ball after a commanded polar move; compare with the target in the undistorted plane about C"""
    r = measure()
    pr = p["rlo"] + rho * (p["rhi"] - p["rlo"])
    tx, ty = p["Cx"] + pr * np.cos(th), p["Cy"] + pr * np.sin(th)
    def err(c):
        x, y, rr, t = phys(p, c)
        dth = (np.degrees(t - th) + 180) % 360 - 180
        return dict(photo=r["photo"], err_R=float(np.hypot(x - tx, y - ty)), radial_err=float(rr - pr), angle_err_deg=float(dth),
                    meas_r=rr, meas_th_deg=float(np.degrees(t) % 360), score=c["score"])
    top = err(r["cands"][0]); near = min((err(c) for c in r["cands"]), key=lambda e: e["err_R"])
    rec = dict(tag=tag, th_cmd=th, rho_cmd=rho, r_cmd=pr, top=top, nearest=near, status=status())
    with open(VLOG, "a") as f: f.write(json.dumps(rec) + "\n")
    flag = "" if abs(top["err_R"] - near["err_R"]) < 1e-6 else "  [top differs from nearest: nearest err %.3f]" % near["err_R"]
    print("%-8s th=%6.1f rho=%.2f -> err %.3f R (radial %+.3f, angle %+.1f deg) score %.2f%s" % (
        tag, np.degrees(th) % 360, rho, top["err_R"], top["radial_err"], top["angle_err_deg"], top["score"], flag), flush=True)
    return rec

def cmd_verify(which="all"):
    p = params()
    if which in ("all", "a"):
        print("(a) 8 goto targets")
        for th, rho in [(0.3, 0.15), (1.6, 0.85), (2.7, 0.45), (3.9, 0.95), (5.0, 0.25), (6.0, 0.65), (7.5, 0.55), (9.0, 0.75)]:
            goto(th, rho); vmeasure(p, th, rho, "goto")
    if which in ("all", "b"):
        for rho in (0.35, 0.7):
            print("(b) circle rho", rho)
            home(); th0 = status()["theta"]
            goto(0.0, rho); vmeasure(p, 0.0, rho, "circ_start")
            get("/circle?rho=%.2f&turns=1" % rho); wait_idle(timeout=400)
            s = status(); vmeasure(p, 2 * np.pi, rho, "circ_end")
            for k in range(8):
                th = 2 * np.pi + (k + 1) * np.pi / 4
                goto(th, rho); vmeasure(p, th, rho, "circ_pt")
    if which in ("all", "c"):
        print("(c) spiral 3 loops")
        home()
        get("/spiral?loops=3"); wait_idle(timeout=600)
        r = vmeasure(p, 3 * 2 * np.pi, 1.0, "spiral_end")
        subprocess.run(["cp", D + "/" + r["top"]["photo"], D + "/captures/verify_spiral.jpg"])

def centre_probe(tag, m2steps, m1push=0, label=""):
    """From the inner stop: step m2 through m2steps (offsets from m2h), optionally with m1 pushed inward by m1push;
    measure radius about C each time. (Deliberate stalls: counters are only valid again after the next /home.)"""
    p = params(); s = home(); m2h = s["cur2"]
    r0 = measure(); c = min(r0["cands"], key=lambda c: abs(phys(p, c)[2] - rmin_of(p)))
    print(label, "home r=%.3f" % phys(p, c)[2], flush=True)
    out = []
    for d in m2steps:
        raw(m1push, m2h + d)
        r = measure(); log(dict(r, tag=tag, m1=m1push, m2=m2h + d, m2h=m2h, d=d))
        x, y, rr, t = phys(p, r["cands"][0])
        pu = predict(p, m1push, m2h + d, m2h)[2]
        print("  %s d=%+5d m1=%d: r=%.3f theta=%.0f score %.2f  (model r %.3f)" % (label, d, m1push, rr, np.degrees(t) % 360, r["cands"][0]["score"], pu), flush=True)
        out.append((d, rr))
    return out

def do_home():
    s = home()
    return s["cur2"]

def cmd_scan(cont=False):
    if cont:
        s = status(); m2h = s["cur2"]; start = s["cur1"] - 200   # continue outward from here (m2h assumed = m2 at last home)
        m2h = int(sys.argv[3]) if len(sys.argv) > 3 else m2h
    else:
        m2h = do_home(); start = -200
    r = measure(); r.update(tag="scan", m1=start + 200, m2=status()["cur2"], m2h=m2h); log(r)
    last = r["best"]["px"]; print("m1=0", last, r["best"]["rho"], flush=True)
    stuck = 0
    for m1 in range(start, -6001, -200):
        s = raw(m1, status()['cur2'])
        r = measure(); r.update(tag="scan", m1=m1, m2=m2h, m2h=m2h, cur1=s["cur1"]); log(r)
        px = r["best"]["px"]; d = np.hypot(px[0] - last[0], px[1] - last[1])
        print("m1=%d" % m1, px, "rho", r["best"]["rho"], "moved %.1fpx" % d, "score", r["best"]["score"], flush=True)
        stuck = stuck + 1 if d < 6 else 0
        last = px
        if r["best"]["rho"] > 0.9 or stuck >= 2: break
    return m2h

def design(p, m2h, n, rng):
    out = []
    while len(out) < n:
        m1 = -int(rng.integers(300, 3400)); m2 = int(m2h + rng.integers(-5000, 9000))
        x, y, r = predict(p, m1, m2, m2h)
        pre = predict(p, m1 + 200, m2 - 300, m2h)[2]
        if 0.30 <= r <= 0.85 and pre >= rmin_of(p) + 0.10:
            out.append((m1, m2))
    return out

def cmd_blocks(nb=4, per=12):
    rng = np.random.default_rng(int(time.time()) % 100000)
    p = params()
    for b in range(nb):
        s = status(); m2h = do_home()
        print("block", b, "m2h", m2h, flush=True)
        prev = None
        for (m1, m2) in design(p, m2h, per, rng):
            r = pose(m1, m2, m2h, "block")
            x, y, rr = predict(p, m1, m2, m2h)
            print(" ", m1, m2, "meas", r["best"]["X"], r["best"]["Y"], "pred %.3f %.3f" % (x, y), "score", r["best"]["score"], flush=True)

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "scan": cmd_scan()
    elif c == "scan2": cmd_scan(True)
    elif c == "sync": cmd_sync()
    elif c == "hometest": cmd_hometest()
    elif c == "verify": cmd_verify(sys.argv[2] if len(sys.argv) > 2 else "all")
    elif c == "probe":
        centre_probe("probe_dec", [-500, -1000, -1500, -2000, -2500, -3000], 0, "m2 down")
    elif c == "probe2":
        p = params()
        print("(b) push m1 inward past the stop with m2 offsets; and from the other side")
        for d in (-1500, +1500, -3000):
            for m1push in (+300, +900):
                s = home(); m2h = s["cur2"]
                raw(m1push, m2h + d); r = measure(); log(dict(r, tag="probe_b", m1=m1push, m2=m2h + d, m2h=m2h))
                x, y, rr, t = phys(p, r["cands"][0]); print("  d=%+5d m1=%+d -> r=%.3f theta=%.0f score %.2f" % (d, m1push, rr, np.degrees(t) % 360, r["cands"][0]["score"]), flush=True)
        # m2 UP from the stop with m1 pulled out a little, then m2 down again (other approach direction)
        print("  other approach: m1 out 400, m2 down 3000 (u would go to ~0 if m1 were free), then m1 back in")
        s = home(); m2h = s["cur2"]
        for m1, d in ((-400, 0), (-400, -1500), (-400, -3000), (-200, -3000), (0, -3000)):
            raw(m1, m2h + d); r = measure(); log(dict(r, tag="probe_b2", m1=m1, m2=m2h + d, m2h=m2h))
            x, y, rr, t = phys(p, r["cands"][0]); print("  m1=%d d=%+5d -> r=%.3f (model %.3f) score %.2f" % (m1, d, rr, predict(p, m1, m2h + d, m2h)[2], r["cands"][0]["score"]), flush=True)
    elif c == "probe3":
        p = params()
        print("(c) slow inward push, then half-step")
        get("/cfg?start=8000&min=8000&accel=0")
        res = []
        for k in range(3):
            raw(status()["cur1"] - 1500, status()["cur2"] + 800 * k)   # go out a bit, differing m2
            s = home(); r = measure(); log(dict(r, tag="probe_c_slow", m1=0, m2=s["cur2"], m2h=s["cur2"]))
            c_ = min(r["cands"], key=lambda c: abs(phys(p, c)[2] - rmin_of(p))); rr = phys(p, c_)[2]; res.append(rr)
            print("  slow(8000us) home r=%.3f" % rr, flush=True)
        get("/cfg?start=5000&min=2500&accel=2")
        get("/cfg?half=1"); get("/cfg?start=5000&min=2500&accel=2")
        res2 = []
        for k in range(3):
            s = status(); raw(s["cur1"] - 3000, s["cur2"] + 1600 * k) if s["homed"] else None
            s = home(); r = measure(); log(dict(r, tag="probe_c_half", m1=0, m2=s["cur2"], m2h=s["cur2"]))
            c_ = min(r["cands"], key=lambda c: abs(phys(p, c)[2] - rmin_of(p))); rr = phys(p, c_)[2]; res2.append(rr)
            print("  half-step home r=%.3f" % rr, flush=True)
        get("/cfg?half=0"); get("/cfg?start=5000&min=2500&accel=2")
        print("slow mean %.3f  half mean %.3f  (full-step baseline 0.158 +-0.004)" % (np.mean(res), np.mean(res2)))
    elif c == "speed":
        p = params()
        for st, mn, ac in [tuple(int(x) for x in a.split(",")) for a in sys.argv[2:]] or [(5000, 2500, 2), (5000, 2000, 2)]:
            get("/cfg?start=%d&min=%d&accel=%d" % (st, mn, ac))
            home(); t0 = time.time()
            get("/spiral?loops=3"); wait_idle(timeout=900); dt = time.time() - t0
            r = vmeasure(p, 6 * np.pi, 1.0, "speed_%d_%d_%d" % (st, mn, ac))
            print("   ^ min_us=%d accel=%d  spiral+home took %.0f s" % (mn, ac, dt), flush=True)
        get("/cfg?start=5000&min=2500&accel=2")
    elif c == "backlash": cmd_backlash()
    elif c == "blocks": cmd_blocks(int(sys.argv[2]) if len(sys.argv) > 2 else 4)
    elif c != "fit": print(__doc__)

# ------------------------------------------------------------------ fitting
from scipy.optimize import least_squares
NAMES = ["Cx", "Cy", "L", "u0", "b1", "b2", "phi0", "A", "A1", "K", "gx", "gy", "s"]

def load_data(tags=None):
    """All usable pose records. 'best' is replaced later by the candidate nearest the model prediction."""
    rows = []
    for l in open(LOG):
        r = json.loads(l)
        if not r.get("cands") or r.get("bad"): continue
        tag = r.get("tag")
        if tag == "homesweep": r["m2h"] = 0
        elif tag == "hometrial_home": r["m2h"] = r["m2"]
        elif tag == "hometrial_start" or "m2h" not in r: continue
        if tags and tag not in tags: continue
        if str(tag).startswith(("probe", "speed")): continue    # deliberate stalls / bad-speed runs
        if "cur1" in r and (r["cur1"] != r["m1"] or r.get("cur2", r["m2"]) != r["m2"]): continue   # counter mismatch
        rows.append(r)
    return rows

def assign(rows, v, tol):
    """Pick for every row the candidate closest to the model prediction (within tol); drop the rest."""
    out = []
    for r in rows:
        x, y = model_xy(v, r["m1"], r["m2"], r["m2h"])
        c = min(r["cands"], key=lambda c: np.hypot(c["X"] - x, c["Y"] - y))
        if np.hypot(c["X"] - x, c["Y"] - y) <= tol and c["rho"] <= 0.88:
            out.append(dict(r, best=c))
    return out

def model_xy(v, m1, m2, m2h):
    p = dict(zip(NAMES, v))
    x, y, r = predict(p, m1, m2, m2h)
    return distort(p, x, y)

def fit_rows(rows, v0=None):
    m1 = np.array([r["m1"] for r in rows], float); m2 = np.array([r["m2"] for r in rows], float)
    m2h = np.array([r["m2h"] for r in rows], float)
    P = np.array([[r["best"]["X"], r["best"]["Y"]] for r in rows])
    def res(v):
        x, y = model_xy(v, m1, m2, m2h)
        return np.r_[x - P[:, 0], y - P[:, 1]]
    best = None
    starts = [v0] if v0 is not None else []
    if v0 is None:
        for L in (0.5, 0.7):
            for ph in np.linspace(0, 2 * np.pi, 6, endpoint=False):
                starts.append([-0.02, 0.08, L, 0.3, 5.2e-4 / L * 0.5, 1.1e-4 / L * 0.5, ph, 5.5e-4, 3e-4, 6e-5, 0, 0.1, 0.03])
    for s0 in starts:
        try: s = least_squares(res, s0, loss="soft_l1", f_scale=0.02)
        except Exception: continue
        if best is None or s.cost < best.cost: best = s
    r = res(best.x); n = len(rows)
    e = np.hypot(r[:n], r[n:])
    return best.x, e

def cmd_fit(write=False):
    rows = load_data()
    v = np.array([params()[k] for k in NAMES])
    for tol in (0.15, 0.10, 0.08, 0.06, 0.06):
        sel = assign(rows, v, tol)
        v, e = fit_rows(sel, v0=v)
    p = dict(zip(NAMES, [float(x) for x in v]))
    p["rlo"], p["rhi"] = params()["rlo"], params()["rhi"]
    n = len(sel)
    # tangential / radial error split (degrees = tangential error / radius about C)
    tang, rad, ang = [], [], []
    for r in sel:
        x, y = model_xy(v, r["m1"], r["m2"], r["m2h"])
        px, py, rr = predict(p, r["m1"], r["m2"], r["m2h"])
        ph = np.arctan2(py - p["Cy"], px - p["Cx"])
        dx, dy = r["best"]["X"] - x, r["best"]["Y"] - y
        rad.append(dx * np.cos(ph) + dy * np.sin(ph)); t = -dx * np.sin(ph) + dy * np.cos(ph)
        tang.append(t); ang.append(np.degrees(t / max(rr, 0.15)))
    out = dict(n_used=n, n_total=len(rows), rms_R=float(np.sqrt(np.mean(e ** 2))), median_R=float(np.median(e)),
               max_R=float(e.max()), rms_radial_R=float(np.sqrt(np.mean(np.square(rad)))),
               rms_tangential_R=float(np.sqrt(np.mean(np.square(tang)))), rms_angle_deg=float(np.sqrt(np.mean(np.square(ang)))))
    A, A1, b1, b2, L, u0 = p["A"], p["A1"], p["b1"], p["b2"], p["L"], p["u0"]
    out["steps_per_rev_m2_alone"] = 2 * np.pi / A
    k = A + A1 * b2 / b1
    out["steps_per_rev_const_radius_m2"] = 2 * np.pi / k
    out["steps_per_rev_const_radius_m1"] = 2 * np.pi / k * b2 / b1
    out["K_predicted_from_A1_b2_b1"] = A1 * b2 / b1
    out["rmin_about_C"] = float(rmin_of(p))
    ulim = lambda r: 2 * np.arcsin(min(r / (2 * L), 1))
    out["radial_travel_m1_steps_rmin_to_rhi"] = (ulim(p["rhi"]) - u0) / b1
    out["radial_travel_m1_steps_rmin_to_0.92"] = (ulim(0.92) - u0) / b1
    return sel, v, e, p, out

def backlash_fit(v):
    """Backlash in steps per motor from the 'backlash' records: displacement between approach directions,
    projected on the model's per-step motion of that motor. Positive = ball lags (stops short) when arriving
    from the opposite direction than the std approach."""
    rows = [json.loads(l) for l in open(LOG)]
    rows = [r for r in rows if r.get("tag") == "backlash" and r.get("best") and r["best"]["score"] > 0.55
            and r.get("cur1") == r["m1"]]
    groups = {}
    for r in rows: groups.setdefault((r["m1"], r["m2"]), []).append(r)
    res = {"m1": [], "m2": [], "both": [], "std_sd_R": []}
    for (m1, m2), g in groups.items():
        m2h = g[0]["m2h"]
        P = lambda a: np.array([[r["best"]["X"], r["best"]["Y"]] for r in g if r["approach"] == a])
        std = P("std")
        if len(std) < 2: continue
        mu = std.mean(axis=0); res["std_sd_R"].append(float(np.sqrt(np.mean(np.sum((std - mu) ** 2, axis=1)))))
        x0 = np.array(model_xy(v, m1, m2, m2h))
        g1 = np.array(model_xy(v, m1 + 1, m2, m2h)) - x0
        g2 = np.array(model_xy(v, m1, m2 + 1, m2h)) - x0
        for key, a in (("m1", "m1opp"), ("m2", "m2opp"), ("both", "bothopp")):
            q = P(a)
            if len(q):
                d = q[0] - mu
                if key == "m1": res[key].append(float(d @ g1 / (g1 @ g1)))
                elif key == "m2": res[key].append(float(d @ g2 / (g2 @ g2)))
                else:   # solve d = g1*a + g2*b
                    sol = np.linalg.lstsq(np.c_[g1, g2], d, rcond=None)[0]; res[key].append([float(sol[0]), float(sol[1])])
    return res

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "fit":
    sel, v, e, p, out = cmd_fit()
    print(json.dumps(p)); print(json.dumps(out, indent=1))
    if "--write" in sys.argv:
        bl = backlash_fit(v)
        out["backlash_steps_m1"] = float(np.mean(np.abs(bl["m1"]))) if bl["m1"] else None
        out["backlash_steps_m2"] = float(np.mean(np.abs(bl["m2"]))) if bl["m2"] else None
        out["backlash_raw"] = bl
        json.dump({"date": "2026-11-19 night", "params": p, "stats": out, "theta0": "theta = 0 is the camera +x axis (3 o'clock on screen)"},
                  open(CAL, "w"), indent=1)
        print("wrote", CAL)
    for r, ei in sorted(zip(sel, e), key=lambda t: -t[1])[:6]:
        print("  worst", r["tag"], r["m1"], r["m2"], r["m2h"], round(ei, 3), r["photo"])
