#!/usr/bin/env python3
"""Oasis calibration, FAR branch (firmware v5): collect camera-measured poses with e between pi and 2*pi and fit.

  calibrate_far.py blocks [N] [PER]   N blocks (default 4) of PER poses (default 14): each block homes at a different m2
                                      (/home?wrap=0, far stop), then visits PER poses sorted by m2, radii 0.03..0.88 plus a
                                      few just past the centre. Always approaches with m1 and m2 both INCREASING.
  calibrate_far.py fit [--write]      fit captures/calib_far.jsonl -> firmware-notes/calibration.json ("params")
  calibrate_far.py sync               /home, find the ball at the far stop by camera, /sync the firmware angle

MODEL (counters: /home drives m1 NEGATIVE into the far stop, m1 = 0 there, m1 > 0 toward the centre; m2 absolute,
never re-zeroed; m2h = m2 counter at the last /home):
  e   = EF - b1*m1 + b2*(m2 - m2h)          elbow angle (rad); the far stop is e = EF
  r   = 2*L*sin(e/2)                        signed radius about C (r = 0 at e = 2*pi, the centre; r < 0 past it)
  phi = phi0 + A*m2 + A1*m1 + K*m2h
  position = C + r*(cos phi, sin phi), unit = sand radius, x right / y up on screen; camera perspective gx, gy, s.
The near-half model (calibrate.py) is superseded: see README "Calibration v2: far branch".
"""
import sys, json, os, time
sys.path.insert(0, "/home/bill/dev/WillyGarage/oasis/tools")
import numpy as np
import oasislib as o
from oasislib import get, status, wait_idle, raw, measure, D

CAL = D + "/firmware-notes/calibration.json"
LOGF = D + "/captures/calib_far.jsonl"
NAMES = ["Cx", "Cy", "L", "EF", "b1", "b2", "phi0", "A", "A1", "K", "gx", "gy", "s"]
DEF = dict(Cx=-0.0243, Cy=0.0904, L=0.46, EF=6.82, b1=6.09e-4, b2=1.10e-4, phi0=2.10, A=5.52e-4, A1=3.045e-4, K=5.5e-5,
           gx=-0.0107, gy=0.1169, s=0.0188, rmax=0.86)

def params():
    p = dict(DEF)
    if os.path.exists(CAL):
        j = json.load(open(CAL))
        if "EF" in j.get("params", {}): p.update(j["params"])
    return p

def log(rec):
    rec["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    open(LOGF, "a").write(json.dumps(rec) + "\n")

def distort(p, x, y):
    d = 1 + p["gx"] * x + p["gy"] * y
    return x / d, y * (1 + p["s"]) / d

def undistort(p, X, Y):
    d = 1.0 / (1 - p["gx"] * X - p["gy"] * Y / (1 + p["s"]))
    return X * d, Y * d / (1 + p["s"])

def predict(p, m1, m2, m2h):
    e = p["EF"] - p["b1"] * m1 + p["b2"] * (m2 - m2h)
    r = 2 * p["L"] * np.sin(e / 2)
    ph = p["phi0"] + p["A"] * m2 + p["A1"] * m1 + p["K"] * m2h
    return p["Cx"] + r * np.cos(ph), p["Cy"] + r * np.sin(ph), r, e

def phys(p, c):
    """candidate dict -> (x, y, r about C, angle about C) in the undistorted table plane"""
    x, y = undistort(p, c["X"], c["Y"])
    return x, y, float(np.hypot(x - p["Cx"], y - p["Cy"])), float(np.arctan2(y - p["Cy"], x - p["Cx"]))

def home_wait(wrap=False):
    wait_idle(); get("/home" + ("" if wrap else "?wrap=0")); return wait_idle(timeout=200)

def pose(m1, m2, m2h, tag, extra=None):
    """Arrive with m1 and m2 both INCREASING (backlash-consistent), then measure."""
    raw(m1 - 200, m2 - 300)
    s = raw(m1, m2)
    r = measure()
    r.update(tag=tag, m1=m1, m2=m2, m2h=m2h, cur1=s["cur1"], cur2=s["cur2"], e_fw=s.get("e"))
    if extra: r.update(extra)
    log(r); return r

def design(p, m2h, n, rng, dlo=-5000, dhi=10000):
    ds = np.sort(np.linspace(dlo, dhi, n) + rng.uniform(-200, 200, n)).astype(int)
    rs = rng.uniform(0.03, 0.88, n)
    es = 2 * np.pi - 2 * np.arcsin(rs / (2 * p["L"]))
    for i in rng.choice(n, 3, replace=False): es[i] = rng.uniform(6.28, 6.45)       # just past the centre
    out = []
    for d, e in zip(ds, es):
        m1 = int(round((p["EF"] + p["b2"] * d - e) / p["b1"])); out.append((m1, int(m2h + d)))
    return out

def cmd_blocks(nb=4, per=14):
    rng = np.random.default_rng(int(time.time()) % 100000); p = params()
    for b in range(nb):
        if b:       # change m2 before homing: back m1 off the stop first (so the elbow is not pushed into it)
            s = status(); raw(1500, s["cur2"] + int(rng.integers(-7000, 7000)))
        s = home_wait(); m2h = s["cur2"]
        print("block", b, "m2h", m2h, flush=True)
        for (m1, m2) in design(p, m2h, per, rng):
            x, y, r, e = predict(p, m1, m2, m2h)
            if e > 6.55 or m1 < 250: print("skip", m1, m2, e); continue
            q = pose(m1, m2, m2h, "far_block")
            bb = q["best"]
            print(" ", m1, m2, "e=%.2f pred r=%.3f" % (e, r), "meas", bb["X"], bb["Y"] if bb else None, "score", bb["score"] if bb else None, flush=True)

# ------------------------------------------------------------------ fitting
from scipy.optimize import least_squares

def load_data():
    rows = []
    for l in open(LOGF):
        r = json.loads(l)
        if not r.get("cands") or r.get("bad") or not str(r.get("tag", "")).startswith("far"): continue
        if r.get("cur1") != r["m1"] or r.get("cur2") != r["m2"]: continue
        rows.append(r)
    return rows

def model_xy(v, m1, m2, m2h):
    p = dict(zip(NAMES, v)); x, y, r, e = predict(p, m1, m2, m2h)
    return distort(p, x, y)

def assign(rows, v, tol):
    out = []
    for r in rows:
        x, y = model_xy(v, r["m1"], r["m2"], r["m2h"])
        c = min(r["cands"], key=lambda c: np.hypot(c["X"] - x, c["Y"] - y))
        if np.hypot(c["X"] - x, c["Y"] - y) <= tol: out.append(dict(r, best=c))
    return out

def fit_rows(rows, v0):
    m1 = np.array([r["m1"] for r in rows], float); m2 = np.array([r["m2"] for r in rows], float)
    m2h = np.array([r["m2h"] for r in rows], float)
    P = np.array([[r["best"]["X"], r["best"]["Y"]] for r in rows])
    def res(v):
        x, y = model_xy(v, m1, m2, m2h)
        return np.r_[x - P[:, 0], y - P[:, 1]]
    s = least_squares(res, v0, loss="soft_l1", f_scale=0.02, x_scale=np.abs(v0) + 1e-3)
    r = res(s.x); n = len(rows)
    return s.x, np.hypot(r[:n], r[n:])

def cmd_fit(write=False):
    rows = load_data(); p0 = params()
    v = np.array([p0[k] for k in NAMES])
    for tol in (0.25, 0.15, 0.10, 0.08, 0.06, 0.06):
        sel = assign(rows, v, tol)
        v, e = fit_rows(sel, v)
    p = dict(zip(NAMES, [float(x) for x in v])); p["rmax"] = p0["rmax"]
    tang, rad, ang = [], [], []
    for r in sel:
        x, y = model_xy(v, r["m1"], r["m2"], r["m2h"])
        px, py, rr, ee = predict(p, r["m1"], r["m2"], r["m2h"])
        ph = np.arctan2(py - p["Cy"], px - p["Cx"]) + (np.pi if rr < 0 else 0)
        dx, dy = r["best"]["X"] - x, r["best"]["Y"] - y
        rad.append(dx * np.cos(ph) + dy * np.sin(ph)); t = -dx * np.sin(ph) + dy * np.cos(ph)
        tang.append(t); ang.append(np.degrees(t / max(abs(rr), 0.15)))
    st = dict(n_used=len(sel), n_total=len(rows), rms_R=float(np.sqrt(np.mean(e ** 2))), median_R=float(np.median(e)),
              max_R=float(e.max()), rms_radial_R=float(np.sqrt(np.mean(np.square(rad)))),
              rms_tangential_R=float(np.sqrt(np.mean(np.square(tang)))), rms_angle_deg_r_over_0p15=float(np.sqrt(np.mean(np.square(ang)))))
    st["steps_per_rev_m2_alone"] = 2 * np.pi / p["A"]
    st["m1_centre_from_far_stop"] = (p["EF"] - 2 * np.pi) / p["b1"]
    st["A1_vs_b1_over_2"] = [p["A1"], p["b1"] / 2]; st["K_vs_b2_over_2"] = [p["K"], p["b2"] / 2]
    st["m1_rim_rmax"] = (p["EF"] - (2 * np.pi - 2 * np.arcsin(p["rmax"] / (2 * p["L"])))) / p["b1"]
    return sel, v, e, p, st

def cmd_sync():
    p = params(); home_wait(wrap=True)
    r = measure(); c = max(r["cands"], key=lambda c: c["score"])
    x, y, rr, th = phys(p, c)
    print("ball at far stop: r=%.3f theta=%.1f deg score %.2f" % (rr, np.degrees(th), c["score"]))
    print(get("/sync?th=%.5f" % th)); print(status())

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "blocks": cmd_blocks(int(sys.argv[2]) if len(sys.argv) > 2 else 4, int(sys.argv[3]) if len(sys.argv) > 3 else 14)
    elif c == "sync": cmd_sync()
    elif c == "fit":
        sel, v, e, p, st = cmd_fit()
        print(json.dumps(p)); print(json.dumps(st, indent=1))
        for r, ei in sorted(zip(sel, e), key=lambda t: -t[1])[:6]: print("  worst", r["m1"], r["m2"], r["m2h"], round(ei, 3), r["photo"])
        if "--write" in sys.argv:
            j = json.load(open(CAL)) if os.path.exists(CAL) else {}
            if "EF" not in j.get("params", {}) and "near_half_superseded" not in j:
                j = {"near_half_superseded": dict(j)}      # keep the old near-half fit for reference
            j.update(date=time.strftime("%Y-%m-%d %H:%M"), branch="far", params=p, stats=st,
                     theta0="theta = 0 is the camera +x axis (3 o'clock on screen); /home at the far stop")
            json.dump(j, open(CAL, "w"), indent=1); print("wrote", CAL)
    else: print(__doc__)
