"""Shared helpers for calibration: table HTTP, camera + locate. Used by calibrate.py."""
import json, subprocess, time, urllib.request, os, re
D = "/home/bill/dev/WillyGarage/oasis"
URL = "http://10.0.0.204"

def get(path, timeout=5, retries=4):
    last = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(URL + path, timeout=timeout) as r:
                t = r.read().decode()
            try: return json.loads(t)
            except Exception: return t.strip()
        except Exception as e:
            last = e; time.sleep(1.5)
    raise RuntimeError("table unreachable: %s %s" % (path, last))

def status(): return get("/status")

def wait_idle(timeout=240):
    t0 = time.time(); time.sleep(0.4)
    while time.time() - t0 < timeout:
        s = status()
        if s["state"] == "idle": return s
        time.sleep(0.5)
    raise RuntimeError("timeout waiting idle")        # never send /stop from here: the table may be busy with a drawing someone started

def raw(m1, m2, wait=True):
    r = get("/raw?m1=%d&m2=%d" % (m1, m2))
    if isinstance(r, str) and "busy" in r: raise RuntimeError(r)
    return wait_idle() if wait else r

def photo(prev=None):
    """settle, take photo, return (locator dict, photo path)."""
    time.sleep(1.5)  # coils off after 1 s idle; let ball/sand settle
    cmd = ["bash", D + "/tools/track.sh"] + ([prev] if prev else [])
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()
    j = json.loads(out[-1]) if out else {"ok": False}
    jpg = None
    # find the newest track jpg
    fs = sorted([f for f in os.listdir(D + "/captures") if re.match(r"track_\d+\.jpg$", f)])
    if fs: jpg = "captures/" + fs[-1]
    return j, jpg

def good(j, minconf=0.5):
    return j.get("ok") and j.get("confidence", 0) >= minconf and j.get("rho", 9) < 0.95

HOME_STEPS = 5500   # relative m1 move inward; > full radial travel so the centre stop is always hit

def home(zero2=False):
    """Firmware /home: drive m1 inward into the centre stop, then cur1=0 (cur2 too if zero2)."""
    wait_idle()
    get("/home" + ("?zero2=1" if zero2 else ""))
    return wait_idle()

# ---------------------------------------------------------------- camera measurement
import sys, numpy as np
sys.path.insert(0, D + "/tools")
import locate, cv2

REF_FILE = D + "/captures/ellipse_ref.json"

# Photo settings follow the room light. Night: ring dim, exposure -3. Day: the room light washes out the ring's
# reflection on the ball, so the ring goes bright and the exposure short (-6), which gives the same picture.
MODEF = D + "/captures/photo_mode.json"
# lin=1&tmp=1 (firmware v8.4+): raw linear light, no fade, not saved; "/led?restore=1" gives the ring back to the owner's setting.
MODES = {"night": dict(led="mode=solid&c=fff4e0&b=25&lin=1&tmp=1", exp="-3", hdr=("-3", "-4", "-6")),
         "day":   dict(led="mode=solid&c=fff4e0&b=200&lin=1&tmp=1", exp="-6", hdr=("-6", "-7", "-9"))}
def light_restore(): get("/led?restore=1")
def photo_mode():
    try:
        j = json.load(open(MODEF)); return j["mode"], j["t"]
    except Exception: return "night", 0
def set_photo_mode(name): json.dump(dict(mode=name, t=time.time()), open(MODEF, "w"))

def _grab(rel, exp):
    result = subprocess.run(["bash", D + "/tools/cam.sh", D + "/" + rel], capture_output=True, text=True,
                            env=dict(os.environ, OASIS_EXP=exp))
    if result.returncode:
        return None
    return cv2.imread(D + "/" + rel)

def snap(path=None):
    """Light the ring for a photo (night or day setting, chosen by how bright the frame comes out), take one frame.
    Returns the jpg path relative to D. The ring is left in photo light: the caller restores any art light."""
    name, t = photo_mode()
    if name == "day" and time.time() - t > 1800: name = "night"          # room may have gone dark again: try night first
    for _ in range(5):
        get("/led?" + MODES[name]["led"]); time.sleep(1.0)
        rel = "captures/cal_%d.jpg" % int(time.time() * 1000)
        im = _grab(rel, MODES[name]["exp"])
        if im is None or im.mean() < 6: time.sleep(1); continue            # black: two captures collided
        if name == "night" and im.mean() > 60: name = "day"; continue      # room light is on
        if im.mean() > 120: time.sleep(1); continue                        # noise frame
        cur, _t = photo_mode()
        if cur != name or name == "day" and time.time() - _t > 1800: set_photo_mode(name)
        return rel
    raise RuntimeError("camera gave black/no frames")

def find_outline(im):
    """The bowl's outline in a camera frame, as a normalised ellipse dict, or None. locate.find_ellipse wants the whole
    sand disc bright; in the short-exposure day mode only the lit ring is, so fall back to fitting the ring itself."""
    try:
        e, q = locate.find_ellipse(im)
        if e is not None: return locate._norm_ellipse(e)
    except Exception: pass
    g = cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (0, 0), 3)
    _, th = cv2.threshold(g, max(120, float(np.percentile(g, 99.0)) * 0.7), 255, cv2.THRESH_BINARY)
    cs, _ = cv2.findContours(th.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cs = [c for c in cs if len(c) >= 200]
    if not cs: return None
    e = locate._norm_ellipse(cv2.fitEllipse(max(cs, key=cv2.contourArea)))
    return e if 120 < e["b"] <= e["a"] < 500 and e["a"] / e["b"] < 1.6 else None

def ref_ellipse(refresh=False, n=5):
    if not refresh and os.path.exists(REF_FILE):
        return json.load(open(REF_FILE))
    es = []
    for _ in range(n):
        e = find_outline(cv2.imread(D + "/" + snap()))
        if e is not None: es.append(e)
        time.sleep(0.5)
    if not es: raise RuntimeError("cannot see the table's outline in the camera")
    keys = ["cx", "cy", "a", "b"]
    ref = {k: float(np.median([e[k] for e in es])) for k in keys}
    ref["angle_deg"] = float(np.median([e["angle_deg"] for e in es]))
    ref["spread_px"] = {k: float(np.std([e[k] for e in es])) for k in keys}
    ref["n"] = len(es)
    json.dump(ref, open(REF_FILE, "w"))
    return ref

def _ring_kern(r0, r1, n=25):
    y, x = np.mgrid[-(n // 2):n // 2 + 1, -(n // 2):n // 2 + 1]; d = np.hypot(x, y)
    k = ((d >= r0) & (d < r1)).astype(np.float32); return k / k.sum()
_KC, _KR, _KO = _ring_kern(0, 3.5), _ring_kern(5.5, 8.5), _ring_kern(10, 12.5)

def ring_cands(img, ell, n=4):
    """Night-look ball finder that does not depend on the background: the ball is a dark middle (3 px) inside a
    brighter ring (6-8 px), a little brighter than what lies just outside it. Real ball scores 0.5-0.8 anywhere in the
    bowl, rim included; sand marks stay under about 0.45 (checked on 16 photos, 2026-11-20)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    c = cv2.filter2D(g, -1, _KC); r = cv2.filter2D(g, -1, _KR); ou = cv2.filter2D(g, -1, _KO)
    sc = (r - c) / (r + 20) + 0.5 * np.clip(r - ou, -50, 50) / (r + 20)
    sc[locate.ellipse_mask(img.shape, ell, 0.99) == 0] = -9
    out = []
    for _ in range(n):
        yy, xx = np.unravel_index(np.argmax(sc), sc.shape); v = float(sc[yy, xx])
        if v < -1: break
        w = sc[max(0, yy - 2):yy + 3, max(0, xx - 2):xx + 3]; w = np.clip(w - (v - 0.1), 0, None)   # sub-pixel centroid
        ys, xs = np.mgrid[max(0, yy - 2):yy + 3, max(0, xx - 2):xx + 3][:, :w.shape[0], :w.shape[1]]
        out.append((float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum()), v))
        sc[max(0, yy - 14):yy + 15, max(0, xx - 14):xx + 15] = -9
    return out

TEMPL = None
def ncc_cands(img, ell, n=4):
    """Ball candidates (x, y, score), best first. Night look (dark frame): ring_cands. Day look: template match."""
    global TEMPL
    if img.mean() < 60: return ring_cands(img, ell, n)
    if TEMPL is None: TEMPL = np.load(D + "/captures/ball_template.npy")
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    r = cv2.matchTemplate(g, TEMPL, cv2.TM_CCOEFF_NORMED)
    t2 = D + "/captures/ball_template2.npy"      # second look: dark sphere with a small highlight (heavily marked sand)
    if os.path.exists(t2):
        r = np.maximum(r, cv2.matchTemplate(g, np.load(t2), cv2.TM_CCOEFF_NORMED))
    h = TEMPL.shape[0] // 2
    mask = locate.ellipse_mask(img.shape, ell, 1.0)[h:h + r.shape[0], h:h + r.shape[1]]
    r = np.where(mask > 0, r, -1)
    out = []
    rr = r.copy()
    for _ in range(n):
        yy, xx = np.unravel_index(np.argmax(rr), rr.shape)
        v = float(rr[yy, xx])
        if v < 0: break
        out.append((xx + h, yy + h, v))
        rr[max(0, yy - 15):yy + 16, max(0, xx - 15):xx + 16] = -1
    return out

LAST = [None]
def measure(prev_rel="auto", ell=None):
    """Photo + ball candidates (NCC) in table-plane coords w.r.t. the FIXED reference ellipse.
    Candidates that also match in the previous photo (static sand features that look like the ball) are dropped,
    unless that would drop everything (ball did not move)."""
    time.sleep(1.5)
    ell = ell or ref_ellipse()
    if prev_rel == "auto": prev_rel = LAST[0]
    rel = snap()
    img = cv2.imread(D + "/" + rel)
    cs = ncc_cands(img, ell, 8)
    dropped = 0
    if prev_rel:
        pimg = cv2.imread(D + "/" + prev_rel)
        if pimg is not None:
            pc = [c for c in ncc_cands(pimg, ell, 8) if c[2] > 0.5]
            keep = [c for c in cs if all(np.hypot(c[0] - q[0], c[1] - q[1]) > 4 for q in pc)]
            if keep: dropped = len(cs) - len(keep); cs = keep
    LAST[0] = rel
    out = []
    for x, y, v in cs[:5]:
        rho, th = locate.to_polar((x, y), ell); t = np.radians(th)
        out.append(dict(px=[round(float(x), 1), round(float(y), 1)], X=round(float(rho * np.cos(t)), 4),
                        Y=round(float(rho * np.sin(t)), 4), rho=round(rho, 3), score=round(v, 3)))
    best = out[0] if out else None
    conf = 0.0
    if best:
        second = out[1]["score"] if len(out) > 1 else 0.0
        conf = round(best["score"] - second, 3)
    return dict(photo=rel, cands=out, best=best, margin=conf, mean=float(img.mean()), static_dropped=dropped)

LOG = D + "/captures/calib_v3.jsonl"
def log(rec):
    rec["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(LOG, "a") as f: f.write(json.dumps(rec) + "\n")

# ---------------------------------------------------------------- ears (tools/earlog.py black box, tools/ear.sh start)
EAR = "/mnt/c/Users/bill/AppData/Local/WillyGarage/oasis/ear"
def heard(t0, t1=None):
    """What the microphone logged between unix times t0 and t1 (default now): loud sudden sounds and motor-band level."""
    t1 = t1 or time.time()
    ev, lv = [], []
    try:
        for l in open(EAR + "/events.jsonl"):
            d = json.loads(l)
            if t0 - 0.3 <= d["t"] <= t1 + 0.3: ev.append([round(d["t"] - t0, 2), d["peak"], d["rise"]])
        for l in open(EAR + "/levels.jsonl").readlines()[-4000:]:
            d = json.loads(l)
            if t0 + 1 <= d["t"] <= t1: lv.append(d)
    except Exception as e:
        return dict(error=str(e))
    out = dict(bangs=ev)
    if lv:
        out.update(motor_db=round(float(np.median([d["motor"] for d in lv])), 1), peak_db=max(d["peak"] for d in lv), secs=len(lv))
    return out

# ---------------------------------------------------------------- pictures for people
def topdown(img, ell=None, size=900, margin=1.10):
    """Warp a camera frame so the sand's outline becomes a circle (no rotation), cropped square around the table."""
    ell = ell or ref_ellipse()
    th = np.radians(ell["angle_deg"]); c, s = np.cos(th), np.sin(th)
    R = size / 2 / margin
    rot = np.array([[c, -s], [s, c]])
    A = rot @ np.diag([R / ell["a"], R / ell["b"]]) @ rot.T
    t = np.array([size / 2, size / 2]) - A @ np.array([ell["cx"], ell["cy"]])
    M = np.hstack([A, t.reshape(2, 1)]).astype(np.float32)
    return cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_AREA if R < ell["a"] else cv2.INTER_CUBIC, borderValue=(255, 255, 255))

PHOTO_LED = "mode=solid&c=fff4e0&b=25"      # ring setting for photos with the camera at manual exposure -3
def beauty(path, led=PHOTO_LED, size=900, restore=None):
    """Light the ring as asked, photograph, save a top-down square picture to `path`. Returns the raw frame path."""
    get("/led?" + led); time.sleep(1.2)
    rel = snap()
    cv2.imwrite(path, topdown(cv2.imread(D + "/" + rel), size=size), [cv2.IMWRITE_JPEG_QUALITY, 92])
    if restore: get("/led?" + restore)
    return rel

def topdown_true(img, size=900, extent=1.0, mask=0.955, cal=None):
    """True top-down picture of the sand: undoes the camera's perspective with the fitted homography
    (firmware-notes/calibration.json via calib2.load_params), centred on the arm's rotation centre, theta = 0 to the
    right. extent = plane units from the centre to the picture edge (bowl wall is at about 0.93); everything beyond
    `mask` is blacked out (None = keep)."""
    import calib2
    p = cal or calib2.load_params()
    j, i = np.mgrid[0:size, 0:size].astype(np.float64)
    k = (size / 2) / extent
    x = (i - size / 2) / k; y = -(j - size / 2) / k
    u, v = calib2.plane_to_px(p, x, y)
    out = cv2.remap(img, u.astype(np.float32), v.astype(np.float32), cv2.INTER_CUBIC, borderValue=(0, 0, 0))
    if mask:
        r = np.hypot(x, y)
        a = np.clip((mask - r) * k / 2.0, 0, 1)[..., None]          # 2 px soft edge
        out = (out * a).astype(np.uint8)
    return out

def snap_hdr(exps=None):
    """Several manual exposures fused into one evenly exposed frame (Mertens). The lit sand near the wall is far
    brighter than the middle, and a single exposure hides the grooves at one end or the other. Returns a BGR image."""
    snap()                                              # settles night/day mode and sets the ring
    exps = exps or MODES[photo_mode()[0]]["hdr"]
    ims = []
    for ex in exps:
        for _ in range(3):
            im = _grab("captures/hdr_%s.jpg" % ex.replace("-", "m"), ex)
            if im is not None and 2 < im.mean() < 120: ims.append(im); break
            time.sleep(1)
    if not ims:
        raise RuntimeError("No usable exposures for the sand photograph.")
    f = cv2.createMergeMertens(1.0, 1.0, 1.0).process(ims)
    return np.clip(f * 255, 0, 255).astype(np.uint8)

def portrait(path, size=1000, led=None):
    """Finished-drawing picture for people: fused exposures, straightened to a true top-down view."""
    try:
        if led: get("/led?" + led); time.sleep(1.2)
        im = snap_hdr()
        corrected = topdown_true(im, size=size)
        for filename, frame in ((path, corrected), (path.replace(".jpg", "_raw.jpg"), im)):
            if not cv2.imwrite(filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 93]):
                raise OSError(f"Could not save sand photograph to {filename}")
    finally:
        light_restore()
    return path
