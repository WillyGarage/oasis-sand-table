#!/usr/bin/env python3
"""Put the drawings and the control page on the table over Wi-Fi (firmware v8+).

  sync_table.py            build captures/table_fs/ (binary patterns, thumbnails, index.json) and upload what changed
  sync_table.py --page     upload the web pages and their assets
  sync_table.py --guest-only FOLDER --build   stage just the Mini guest controls locally
  sync_table.py --guest-only FOLDER           install the verified staged files under /lib
  sync_table.py --list     show what is stored on the table
  sync_table.py --build    build only
  --bg-pitch P             ring pitch of the outside-in erase files (default 0.016)

Hand-made pictures (EXTRAS) can be stored bigger (scale_thr.py, factor in EXTRAS) and get a second file
/lib/<name>.bg.pat: ONLY the outside-in erase for that picture (bg_erase.py, background pass only, no inside pass, no
islands). It starts on the rim and ends exactly on the picture's first point. Firmware v8.11+ plays it instead of the
spiral erase when the picture is drawn with an erase. Thumbnails stay the plain picture; index.json lists only pictures.

Stored layout (see the firmware header): /lib/<name>.pat = float32 theta, float32 rho per point (little-endian),
/lib/<name>.jpg = 240 px thumbnail, /lib/index.json = the list the page shows, /www/index.html = the page.
The table refuses uploads while it is drawing. The key is ADMIN_KEY in firmware/our-fw/wifi_creds.h."""
import argparse, json, math, os, re, struct, sys, tempfile, time, urllib.request, hashlib
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scale_thr import scale
from build_guest_center import MINI_GENERATED_FILES, MINI_WEB_FILES, build_guest_web_assets
D = "/home/bill/dev/WillyGarage/oasis"
URL = "http://10.0.0.204"
OUT = D + "/captures/table_fs"
TITLES = dict(ribbon_spiral="Ribbon spiral", rose_7_3="Seven-petal rose", rose_9_4="Nine-lobed rose", rose_layers="Layered roses",
              spiro_hypo="Lace ring", spiro_epi="Looped garland", bloom_star="Star bloom", bloom_ruffle="Ruffled flower",
              sunflower="Sunflower", hex_vortex="Hexagon vortex", square_vortex="Square vortex", star_pinwheel="Star pinwheel",
              ripple_rings="Ripple rings", dunes="Dunes", taiji="Yin and yang", moire_a="Moire spiral", moire_b="Moire spiral, second layer",
              lissajous="Basket weave", lissajous_weave="Crossing bands", galaxy="Galaxy", mandala="Mandala", harmonograph="Pendulum drawing")
# drawings that are not in patterns/lib: name -> (thr file, preview image, title, minutes, scale factor or None)
# The people are drawn 25% bigger (measured on the table 2026-11-20: they read better). Maverick already spans
# x -0.98..0.93, so scaling would only clip him at the rim: unscaled. Minutes are the old (unscaled) estimates.
EXTRAS = dict(maverick=("patterns/dog/dog_filled.thr", "patterns/dog/dog_filled.png", "Maverick", 9, None),      # Bill's dog
              lek=("patterns/people/lek.thr", "patterns/people/lek.png", "Lek", 9, 1.25),
              bill=("patterns/people/bill.thr", "patterns/people/bill.png", "Bill", 7, 1.25),
              alex=("patterns/people/alex.thr", "patterns/people/alex.png", "Alex", 9, 1.25),
              thomas=("patterns/people/thomas.thr", "patterns/people/thomas.png", "Thomas", 8, 1.25))
BG_MAX = 11998            # the firmware puts two lead-in points (ball -> rim -> start) in front of the erase file
BG_TIME = 1.22            # bg_erase.motor_minutes() read 11.9 min for Bill erase + portrait at pitch 0.02; the table took 14.5
MEASURED_MIN = dict(galaxy=10, bloom_star=11, hex_vortex=10, mandala=10, sunflower=7)     # timed on the table at 400 steps/s

WITH_BG = False
def bg_file(n, pts, pitch):
    """the outside-in erase for one picture (background pass only) -> (points, minutes on the table)"""
    import numpy as np
    sys.path.insert(0, D + "/tools")
    import bg_erase as bg
    port = np.asarray(pts, float)
    path, shift, stats, A = bg.plan(port, pitch=pitch, inside_pitch=0, islands=False)
    pre = np.array(path.P)
    er = bg.densify(pre)
    if len(er) > BG_MAX: er = bg.densify(pre, thin=True)
    p0 = port[0]
    da = (er[-1][0] - p0[0] + math.pi) % (2 * math.pi) - math.pi
    if len(er) > BG_MAX: sys.exit("%s: erase file has %d points, over the firmware's %d: raise --bg-pitch" % (n, len(er), BG_MAX))
    if er[0][1] < 0.98: sys.exit("%s: erase file does not start on the rim (rho %.3f)" % (n, er[0][1]))
    if abs(da) > 1e-3 or abs(er[-1][1] - p0[1]) > 1e-3: sys.exit("%s: erase file does not end on the picture's first point" % n)
    if er[:, 1].min() < 0.01 or er[:, 1].max() > 1.0 + 1e-9: sys.exit("%s: erase file leaves 0.01..1 in rho" % n)
    return [(float(t), float(r)) for t, r in er], bg.motor_minutes(er) * BG_TIME

def build_guest_pool(catalog_path, destination):
    """Store the same routes the phone uses in one seekable file for unattended changes."""
    catalog = json.loads(catalog_path.read_text())
    entries = []  # Guest replacements use the normal full-table erase; this file holds art only.
    for name, subject in catalog["subjects"].items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,31}', name) or name == 'erase' or len(subject["paths"]) != 3:
            raise ValueError(f"Invalid guest pool subject: {name}")
        entries.extend((name, i, path) for i, path in enumerate(subject["paths"]))
    if not 0 < len(entries) <= 512:
        raise ValueError("The Mini accepts at most 512 guest pool entries.")
    header = struct.Struct("<4sI")
    index = struct.Struct("<32sB3xII")
    offset = header.size + len(entries) * index.size
    with destination.open("wb") as output:
        output.write(header.pack(b"GSA1", len(entries)))
        for name, slot, points in entries:
            if not 2 <= len(points) <= 12000:
                raise ValueError(f"Invalid route for {name} in slot {slot}")
            output.write(index.pack(name.encode("ascii"), slot, offset, len(points)))
            offset += len(points) * 8
        for _, _, points in entries:
            output.write(b"".join(struct.pack("<ff", theta, rho) for theta, rho in points))


def build(pitch=0.016):
    import cv2
    import shutil; shutil.rmtree(OUT + "/lib", ignore_errors=True)
    os.makedirs(OUT + "/lib", exist_ok=True); os.makedirs(OUT + "/www", exist_ok=True)
    idx = []
    items = [(m["name"], "patterns/lib/%s.thr" % m["name"], "patterns/lib/%s.png" % m["name"], None, m) for m in json.load(open(D + "/patterns/lib/manifest.json"))]
    items = [(n, t, i, ti, dict(start=None, end=None, estimated_minutes=mn)) for n, (t, i, ti, mn, k) in EXTRAS.items()] + items
    for n, thr, img, title, m in items:
        if n.startswith("erase"): continue
        pts = []
        for l in open("%s/%s" % (D, thr)):
            l = l.strip()
            if not l or l[0] == "#": continue
            a = l.replace(",", " ").split()
            pts.append((float(a[0]), min(1.0, max(0.0, float(a[1])))))
        bgmin = None
        if n in EXTRAS:
            if EXTRAS[n][4]: pts = scale(pts, EXTRAS[n][4])
            # Outside-in erase files are OFF since 2026-11-20 2:30pm (Bill: "scrap the idea of selective erase"): slower than a
            # plain spiral for most pictures, rings in the background, and the one-picture swap looked terrible.
            # --bg brings them back; without them the firmware does its plain fine spiral erase (/cfg?epitch=).
            if WITH_BG:
                er, bgmin = bg_file(n, pts, pitch)
                open("%s/lib/%s.bg.pat" % (OUT, n), "wb").write(b"".join(struct.pack("<ff", t, r) for t, r in er))
                print("%-9s %5d points, erase file %5d points (%6d bytes), erase about %.0f min" % (n, len(pts), len(er), 8 * len(er), bgmin), flush=True)
        if not 2 <= len(pts) <= 12000: sys.exit("%s: %d points (the firmware takes 2..12000)" % (n, len(pts)))
        open("%s/lib/%s.pat" % (OUT, n), "wb").write(b"".join(struct.pack("<ff", t, r) for t, r in pts))
        im = cv2.imread("%s/%s" % (D, img))
        h, w = im.shape[:2]; s = min(h, w); im = im[(h - s) // 2:(h + s) // 2, (w - s) // 2:(w + s) // 2]
        cv2.imwrite("%s/lib/%s.jpg" % (OUT, n), cv2.resize(im, (240, 240), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 80])
        idx.append(dict(name=n, title=title or TITLES.get(n, n.replace("_", " ").capitalize()), points=len(pts),
                        start=m["start"] or ("rim" if pts[0][1] >= 0.5 else "centre"), end=m["end"] or ("rim" if pts[-1][1] >= 0.5 else "centre"),
                        minutes=m["estimated_minutes"] if title else MEASURED_MIN.get(n, max(1, round(m["estimated_minutes"] * 0.9)))))
        if bgmin: idx[-1]["erase_minutes"] = round(bgmin)
    json.dump(idx, open(OUT + "/lib/index.json", "w"))
    build_guest_pool(Path(D, "web/guest-paths.json"), Path(OUT, "lib/guest-pool.bin"))
    build_guest_web_assets(Path(D, "web"), Path(OUT, "lib"))
    open(OUT + "/www/index.html", "wb").write(open(D + "/web/index.html", "rb").read())
    return idx


def get(path):
    with urllib.request.urlopen(URL + path, timeout=15) as r: return r.read().decode()

def admin_key():
    return re.search(r'ADMIN_KEY\s+"([^"]+)"', Path(D, "firmware/our-fw/wifi_creds.h").read_text()).group(1)

def put(local, remote):
    body = open(local, "rb").read()
    req = urllib.request.Request(URL + "/fs", data=body, headers={"Content-Type": "application/octet-stream", "X-Key": admin_key(), "X-Path": remote})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return r.read().decode().strip()
        except urllib.error.HTTPError as e:
            return "HTTP %d %s" % (e.code, e.read().decode().strip())
        except Exception as e:
            err = e; time.sleep(2)
    return "failed: %s" % err

def stored_sha1(remote):
    with urllib.request.urlopen(URL + remote, timeout=60) as response:
        return hashlib.sha1(response.read()).hexdigest()


def upload(files, prune=False, verify_guest=False):
    have = {f["path"]: f["size"] for f in json.loads(get("/fs"))["files"]}
    if verify_guest:
        shadowed = [remote[:-3] for remote, _ in files if remote.endswith('.gz') and remote[:-3] in have]
        if shadowed:
            raise ValueError('The Mini would serve these existing uncompressed files first: ' + ', '.join(shadowed))
    sent = 0
    # Skip a file only if the table has it at the same size AND it is what we sent last time (sha1 record). Size alone
    # missed the bigger portraits (scaling keeps the point count, so the size).
    SENT = D + "/captures/table_fs.sent.json"
    rec = json.load(open(SENT)) if os.path.exists(SENT) else {}
    for remote, local in files:
        size = os.path.getsize(local); h = hashlib.sha1(open(local, "rb").read()).hexdigest()
        if have.get(remote) == size:
            if verify_guest and stored_sha1(remote) == h: continue
            if not verify_guest and rec.get(remote) == h and not remote.endswith((".html", ".json")): continue
        r = put(local, remote); sent += 1
        print(remote, size, "->", r, flush=True)
        if not r.startswith("saved"): json.dump(rec, open(SENT, "w"), indent=0); sys.exit(1)
        if verify_guest and stored_sha1(remote) != h:
            raise ValueError(f'The uploaded bytes did not match {remote}. Rerun the staged installation.')
        rec[remote] = h
    json.dump(rec, open(SENT, "w"), indent=0)
    if prune:                                              # drop stored drawings that are no longer built (after a rename)
        keep = {r for r, _ in files}
        for path in have:
            if path.startswith("/lib/") and path not in keep:
                print("removing", path, get("/fs?del=%s&key=%s" % (path, admin_key())).strip(), flush=True)
    j = json.loads(get("/fs")); print("sent %d files; table has %d files, %.1f MB free" % (sent, len(j["files"]), j["free"] / 1e6))


def mini_bundle(folder, build_only):
    names = ['guest-pool.bin', *(name+'.gz' for name in (*MINI_WEB_FILES, *MINI_GENERATED_FILES))]
    # A phone can open the page during an upload. Make the new route pool and
    # runtime dependencies available before the catalog, script and entry page.
    last = {'guest-paths.json.gz': 1, 'guest.js.gz': 2, 'guest.html.gz': 3}
    names.sort(key=lambda name: (last.get(name, 0), name))
    manifest = folder/'sha256.json'
    if build_only:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            stage = Path(temp)
            web = Path(D, 'web')
            build_guest_web_assets(web, stage, mini_only=True)
            build_guest_pool(web/'guest-paths.json', stage/'guest-pool.bin')
            digests = {name: hashlib.sha256((stage/name).read_bytes()).hexdigest() for name in names}
            (stage/manifest.name).write_text(json.dumps(digests, sort_keys=True, indent=2)+'\n')
            for name in [*names, manifest.name]:
                (stage/name).replace(folder/name)
        print(f'Staged {len(names)} Mini guest files in {folder}')
        return
    digests = json.loads(manifest.read_text())
    if set(digests) != set(names):
        raise ValueError('The guest bundle has an incomplete or unexpected file list.')
    # Freeze the validated bytes for this run even if someone rebuilds the folder.
    with tempfile.TemporaryDirectory() as temp:
        snapshot = Path(temp)
        for name in names:
            contents = (folder/name).read_bytes()
            if hashlib.sha256(contents).hexdigest() != digests[name]:
                raise ValueError(f'{name} no longer matches the staged Mini guest bundle.')
            (snapshot/name).write_bytes(contents)
        upload([('/lib/'+name, snapshot/name) for name in names], verify_guest=True)


def main():
    global WITH_BG
    parser = argparse.ArgumentParser(description='Build or install Oasis Mini artwork and controls.', allow_abbrev=False)
    scopes = parser.add_mutually_exclusive_group()
    scopes.add_argument('--guest-only', type=Path, metavar='FOLDER', help='Use this staged bundle of Mini guest controls')
    scopes.add_argument('--page', action='store_true', help='Upload the web pages and their assets')
    scopes.add_argument('--list', action='store_true', help='List the files on the table')
    parser.add_argument('--build', action='store_true', help='Only build local files')
    parser.add_argument('--bg', action='store_true', help='Build outside-in erase files for hand-made pictures')
    parser.add_argument('--bg-pitch', type=float, default=0.016, help='Ring pitch of the outside-in erase files')
    args = parser.parse_args()
    if args.guest_only is not None:
        try:
            mini_bundle(args.guest_only, args.build)
        except (OSError, ValueError) as error:
            parser.exit(1, f'{error}\n')
        return
    WITH_BG = args.bg
    if args.list: print(get("/fs")); return
    build(args.bg_pitch)
    if args.build: return
    # /lib/ is the device's static route. Publish dependencies before either page links to them.
    guest_assets = sorted(Path(OUT, "lib").glob("guest*"), key=lambda f: (f.name.endswith(".html.gz"), f.name))
    files = [("/lib/" + f.name, str(f)) for f in guest_assets]
    files.append(("/www/index.html", OUT + "/www/index.html"))
    if not args.page:
        files += [("/lib/" + f, OUT + "/lib/" + f) for f in sorted(os.listdir(OUT + "/lib")) if not f.startswith("guest")]
    upload(files, prune=not args.page)

if __name__ == "__main__":
    main()
