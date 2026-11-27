#!/usr/bin/env python3
"""Outside icon worker for the sand table guest app (optional: the server now makes drawings itself).

Polls the site's worker API for pending interests, makes each drawing with the same code the server uses
(server/icons.py, needs ANTHROPIC_API_KEY) and posts the strokes back. See README.md.

  SAND_BASE=https://sand.example.com SAND_WORKER_TOKEN=... ANTHROPIC_API_KEY=... python3 icon_worker.py
  python3 icon_worker.py --once "clarinet playing" -o out.png
"""
import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import icons, render  # noqa: E402

BASE = os.environ.get("SAND_BASE", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.environ.get("SAND_WORKER_TOKEN", "")
MAX_PER_HOUR = int(os.environ.get("SAND_ICON_MAX_PER_HOUR", "150"))
POLL_SECONDS = 2
PARALLEL = icons.PARALLEL
MAX_TRIES = icons.MAX_TRIES
SKIP_SECONDS = icons.SKIP_SECONDS

HEADERS = {"X-Worker-Token": TOKEN}
_lock = threading.Lock()
_inflight = set()          # interest ids being worked
_tries = {}                # id -> failures
_skip_until = {}           # id -> monotonic time
_calls = []                # times of fresh generations, for the hourly cap
_done = {}                 # normalised label -> strokes, so repeats in one run are free


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def make(label):
    """Strokes for a label, with a per-run cache and an hourly cap on fresh calls."""
    key = icons.norm_label(label)
    with _lock:
        if key in _done:
            return _done[key]
        now = time.time()
        while _calls and now - _calls[0] > 3600:
            _calls.pop(0)
        if len(_calls) >= MAX_PER_HOUR:
            raise RuntimeError("hourly icon cap reached (%d); raise SAND_ICON_MAX_PER_HOUR" % MAX_PER_HOUR)
        _calls.append(now)
    strokes = icons.generate(label)["strokes"]
    with _lock:
        _done[key] = strokes
    return strokes


def work(job):
    iid, label, v = job["id"], job.get("label", ""), job.get("v")
    t0 = time.time()
    try:
        strokes = make(label)
        r = requests.post("%s/api/worker/interests/%s" % (BASE, iid), headers=HEADERS,
                          json={"v": v, "strokes": strokes}, timeout=20)
        if r.status_code in (409, 404):
            log("%r: server says %d (stale or deleted), done" % (label, r.status_code))
        elif r.status_code != 200:
            raise RuntimeError("post %d %s" % (r.status_code, r.text[:100]))
        log("icon %r %.1fs" % (label, time.time() - t0))
        with _lock:
            _tries.pop(iid, None)
    except Exception as e:
        with _lock:
            n = _tries.get(iid, 0) + 1
            _tries[iid] = n
            if n >= MAX_TRIES:
                _skip_until[iid] = time.monotonic() + SKIP_SECONDS
                _tries.pop(iid, None)
        log("FAILED %r (try %d/%d, %.1fs): %s" % (label, n, MAX_TRIES, time.time() - t0, e))
    finally:
        with _lock:
            _inflight.discard(iid)


def run():
    if not TOKEN:
        sys.exit("SAND_WORKER_TOKEN is not set")
    if not icons.api_key_set():
        sys.exit("ANTHROPIC_API_KEY is not set")
    log("worker up: %s model=%s" % (BASE, icons.MODEL))
    with ThreadPoolExecutor(PARALLEL) as pool:
        while True:
            try:
                r = requests.get(BASE + "/api/worker/jobs", headers=HEADERS, timeout=15)
                if r.status_code == 401:
                    log("401 from server: wrong SAND_WORKER_TOKEN")
                else:
                    r.raise_for_status()
                    for job in r.json().get("interests", []):
                        iid = job.get("id")
                        with _lock:
                            if (iid in _inflight or len(_inflight) >= PARALLEL
                                    or _skip_until.get(iid, 0) > time.monotonic()):
                                continue
                            _inflight.add(iid)
                        pool.submit(work, job)
            except Exception as e:
                log("poll error: %s" % e)
            time.sleep(POLL_SECONDS)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", metavar="LABEL", help="generate one icon, no site")
    ap.add_argument("-o", "--out", default="out.png", help="preview PNG path for --once")
    a = ap.parse_args()
    if a.once:
        t0 = time.time()
        res = icons.generate(a.once)
        strokes = res["strokes"]
        Path(a.out).write_bytes(render.relief_png(strokes, 240))
        print("%s: %s, %d strokes, %d points, %.1fs -> %s" % (
            a.once, res["source"], len(strokes), sum(len(s) for s in strokes), time.time() - t0, a.out))
    else:
        run()


if __name__ == "__main__":
    main()
