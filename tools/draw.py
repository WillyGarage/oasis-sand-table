#!/usr/bin/env python3
"""Draw one or more patterns on the table and photograph the result.

  draw.py [--home] [--every 120] [--led MODE] name_or_path.thr [more ...]

For each pattern: photo before, POST /thr, /play, poll /status until idle (photo every
--every seconds so a stall is visible afterwards), photo after. Everything lands in
captures/draws/<stamp>_<name>/ with a log.json (start/end time, real duration, points,
progress samples). Names without a slash are looked up in patterns/lib/.

Exit code 0 only if every pattern ran to completion. A pattern is abandoned (and /stop sent)
if progress does not advance for --stall seconds.
"""
import argparse, json, os, subprocess, sys, time, urllib.request
D = "/home/bill/dev/WillyGarage/oasis"
URL = "http://10.0.0.204"
CROP = (700, 380, 1500, 1080)   # current laptop camera view of the table


def get(path, data=None, timeout=8, retries=5):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(URL + path, data=data)
            if data is not None:
                req.add_header("Content-Type", "text/plain")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                t = r.read().decode()
            try:
                return json.loads(t)
            except Exception:
                return t.strip()
        except Exception as e:
            last = e
            time.sleep(2)
    raise RuntimeError("table unreachable: %s %s" % (path, last))


def photo(path):
    """One frame, warped to a top-down square around the table (oasislib.topdown). Returns True on success."""
    sys.path.insert(0, D + "/tools")
    import cv2, oasislib
    try:
        rel = oasislib.snap()
        cv2.imwrite(path, oasislib.topdown_true(cv2.imread(D + "/" + rel)), [cv2.IMWRITE_JPEG_QUALITY, 93])
        open(path + ".src", "w").write(rel)          # raw frame, so the picture can be re-made after a better calibration
        return True
    except Exception as e:
        print("photo failed:", e, flush=True)
        return False


def wait_idle(timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = get("/status")
        if s.get("state") == "idle":
            return s
        time.sleep(1)
    raise RuntimeError("table never went idle")


def draw(path, every, stall, led):
    fw = path.startswith("fw:")              # "fw:gen?kind=random": a piece the table generates itself
    name = path[3:].split("kind=")[-1].split("&")[0] if fw else os.path.splitext(os.path.basename(path))[0]
    out = "%s/captures/draws/%s_%s" % (D, time.strftime("%m%d_%H%M%S"), name)
    os.makedirs(out, exist_ok=True)
    log = {"name": name, "file": path, "started": time.strftime("%F %T"), "samples": []}
    wait_idle()
    get("/led?mode=solid&c=fff4e0&b=25")
    time.sleep(1.5)
    photo(out + "/before.jpg")
    if not fw:
        body = open(path, "rb").read()
        up = get("/thr", data=body, timeout=30)
        log["upload"] = up
        if not isinstance(up, dict) or not up.get("points"):
            log["error"] = "upload rejected: %r" % (up,)
            json.dump(log, open(out + "/log.json", "w"), indent=1)
            return False, out
    if led:
        get("/led?" + led)
    r = get("/" + path[3:]) if fw else get("/play")
    log["play"] = r
    if fw:
        time.sleep(0.5); log["gen"] = get("/status").get("gen"); print("gen:", log["gen"], flush=True)
    t0 = time.time(); last_shot = t0; last_prog = -1; last_change = t0; n = 0; ok = True
    st0 = get("/status"); idx0 = None; n_idx0 = st0.get("idx_n", 0); ie0 = None
    time.sleep(1.5)
    while True:
        s = get("/status")
        prog = s.get("progress", 0)
        now = time.time()
        if s.get("state") == "idle":
            break
        # slip watchdog: the arm sensor must be passed once per turn, within a few steps of where it should be
        ie, inn, th = s.get("idx_err"), s.get("idx_n"), s.get("theta")
        if ie is not None:
            if idx0 is None: idx0 = (inn, th, ie)
            if inn != idx0[0]: idx0 = (inn, th, idx0[2]); 
            if inn > n_idx0 and ie0 is None: ie0 = ie if abs(ie) <= 40 else 0.0     # first pass of this drawing sets the baseline
            if inn > n_idx0 and abs(ie - ie0) > 40:
                get("/stop"); log["error"] = "motor 2 slipped: arm sensor off by %.0f steps at progress %s" % (ie - ie0, prog); ok = False
                break
        if prog != last_prog:
            last_prog = prog; last_change = now
        elif now - last_change > stall:
            get("/stop"); log["error"] = "stalled at progress %s" % prog; ok = False
            break
        if now - last_shot >= every:
            n += 1; last_shot = now
            get("/led?mode=solid&c=fff4e0&b=25") if led else None
            photo("%s/mid_%03d.jpg" % (out, n))
            get("/led?" + led) if led else None
            log["samples"].append({"t": round(now - t0), "progress": prog, "theta": s.get("theta"), "rho": s.get("rho"),
                                   "idx_err": s.get("idx_err"), "idx_n": s.get("idx_n"), "speed": s.get("speed")})
            json.dump(log, open(out + "/log.json", "w"), indent=1)
        time.sleep(2)
    log["seconds"] = round(time.time() - t0)
    log["final"] = get("/status")
    if log["final"].get("fault"):
        ok = False; log["error"] = "firmware stopped the drawing: fault %s (1 = motor 2 slipped, 2 = motor 2 stalled)" % log["final"]["fault"]
    elif ok and log["final"].get("progress", 1) < 0.999:
        ok = False; log["error"] = "stopped early at progress %s" % log["final"].get("progress")
    try:                                   # what the microphone heard, and where the camera sees the ball vs the model
        sys.path.insert(0, D + "/tools")
        import math, oasislib, calib2
        log["heard"] = oasislib.heard(t0)
        f = log["final"]; p = calib2.load_params()
        get("/led?mode=solid&c=fff4e0&b=25"); time.sleep(1.5)
        bb, near, ph, cs = calib2.see(p, f["cur1"], f["cur2"], f["m2h"], tol=0.2)
        mx, my, _, _ = calib2.model(p, f["cur1"], f["cur2"], f["m2h"])
        log["final_err_mm"] = round(math.hypot(bb["x"] - mx, bb["y"] - my) * 126, 1)
        log["final_r_err_mm"] = round((math.hypot(bb["x"], bb["y"]) - math.hypot(mx, my)) * 126, 1)
        log["final_ball_score"] = bb["score"]; log["final_ball_near_model"] = near
    except Exception as e:
        log["check_error"] = str(e)
    get("/led?mode=solid&c=fff4e0&b=25")
    time.sleep(2)
    try:
        import oasislib
        oasislib.portrait(out + "/after.jpg")          # fused exposures, straightened: the picture for people
    except Exception as e:
        print("portrait failed:", e, flush=True); photo(out + "/after.jpg")
    log["ended"] = time.strftime("%F %T")
    json.dump(log, open(out + "/log.json", "w"), indent=1)
    return ok, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="+")
    ap.add_argument("--home", action="store_true", help="run /home first")
    ap.add_argument("--every", type=int, default=120, help="seconds between progress photos")
    ap.add_argument("--stall", type=int, default=90, help="abandon if progress frozen this long")
    ap.add_argument("--led", default="", help="LED query while drawing, e.g. 'mode=comet&c=ffb060&b=120'")
    a = ap.parse_args()
    if a.home:
        wait_idle(); print("home:", get("/home")); s = wait_idle()
        if not s.get("homed"): print("homing failed", s.get("home_err")); sys.exit(2)
    allok = True
    for p in a.patterns:
        if "/" not in p and not p.startswith("fw:"):
            p = "%s/patterns/lib/%s%s" % (D, p, "" if p.endswith(".thr") else ".thr")
        ok, out = draw(p, a.every, a.stall, a.led)
        print(("done " if ok else "FAILED ") + out, flush=True)
        allok &= ok
        if not ok:
            break
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
