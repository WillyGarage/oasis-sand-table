#!/usr/bin/env python3
"""Deploy sand-app/ to the server (sand.example.com) and rebuild the container.

  deploy/deploy.py              upload, back up the DB, build, swap the container, wait for /api/state
  deploy/deploy.py --no-build   upload only
  deploy/deploy.py run 'CMD'    run one shell command on the box and print its output
  deploy/deploy.py site         first-time only: install the nginx block and get the TLS certificate

Login comes from
~/.config/sand-app/deploy.env (WG_HOST, WG_USER, WG_PASSWORD); nothing from it is copied to the box.
The worker token and the AI key live in ~/.config/oasis/sand-app.env (SAND_WORKER_TOKEN, ANTHROPIC_API_KEY)
and are written to .env on the box (chmod 600, never into the image or git).
The worker/ folder is home-side only and is never uploaded.
"""
import os
import posixpath
import secrets
import shlex
import sys
import time
from pathlib import Path

import paramiko

HERE = Path(__file__).resolve().parent.parent          # sand-app/
WG_CFG = Path.home() / ".config/sand-app/deploy.env"
APP_CFG = Path.home() / ".config/oasis/sand-app.env"
APP_DIR = "apps/sand-app"                          # relative to the login's home
NAME = "sand-app"
PORT = 8091
FILES = ["requirements.txt", "Dockerfile", "docker-compose.yml", ".dockerignore", "API.md", "deploy/nginx-sand.conf"]
TREES = ["server", "static"]
SKIP_PARTS = {"__pycache__", "tests", ".pytest_cache", "data"}


def read_env(path):
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def worker_token():
    env = read_env(APP_CFG)
    if not env.get("SAND_WORKER_TOKEN"):
        APP_CFG.parent.mkdir(parents=True, exist_ok=True)
        env["SAND_WORKER_TOKEN"] = secrets.token_urlsafe(32)
        APP_CFG.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
        APP_CFG.chmod(0o600)
        print(f"made a new worker token in {APP_CFG}")
    return env["SAND_WORKER_TOKEN"]


def connect():
    c = read_env(WG_CFG)
    for k in ("WG_HOST", "WG_USER", "WG_PASSWORD"):
        if not c.get(k):
            raise SystemExit(f"{WG_CFG} is missing {k}")
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cl.connect(c["WG_HOST"], username=c["WG_USER"], password=c["WG_PASSWORD"], timeout=20,
               look_for_keys=False, allow_agent=False)
    return cl, c


def run(cl, cmd, timeout=600, stdin=None, quiet=False):
    i, o, e = cl.exec_command(cmd, timeout=timeout)
    if stdin is not None:
        i.write(stdin)
        i.flush()
        i.channel.shutdown_write()
    out, err = o.read().decode(errors="replace"), e.read().decode(errors="replace")
    rc = o.channel.recv_exit_status()
    if not quiet:
        if out.strip():
            print(out.rstrip())
        if err.strip():
            print(err.rstrip(), file=sys.stderr)
    return rc


def sudo(cl, c, cmd, timeout=600):
    """Run cmd as root. The password goes over stdin, never onto a command line."""
    return run(cl, "sudo -S -p '' sh -c " + shlex.quote(cmd), timeout=timeout, stdin=c["WG_PASSWORD"] + "\n")


def local_files():
    files = [f for f in FILES if (HERE / f).exists()]
    for t in TREES:
        for p in sorted((HERE / t).rglob("*")):
            if p.is_file() and not (set(p.relative_to(HERE).parts) & SKIP_PARTS) and p.suffix != ".pyc":
                files.append(str(p.relative_to(HERE)))
    return files


def upload(cl):
    sftp = cl.open_sftp()
    files = local_files()
    dirs = sorted({posixpath.dirname(posixpath.join(APP_DIR, f)) for f in files})
    run(cl, "mkdir -p " + " ".join(shlex.quote(d) for d in dirs))
    sent = 0
    for rel in files:
        src, dst = HERE / rel, posixpath.join(APP_DIR, rel)
        # Big files that never change (face models, vendored libraries) are skipped when the size matches:
        # the link from this laptop drops on long uploads.
        if rel.startswith(("server/models/", "static/vendor/", "server/lucide/")):
            try:
                if sftp.stat(dst).st_size == src.stat().st_size:
                    continue
            except IOError:
                pass
        sftp.put(str(src), dst)
        sent += 1
    print(f"  sent {sent} of {len(files)} files")
    # drop files that no longer exist locally (server/ and static/ only)
    keep = set(files)
    for t in TREES:
        _, o, _ = cl.exec_command(f"cd {APP_DIR} && find {t} -type f")
        for rel in o.read().decode().split():
            if rel not in keep:
                run(cl, f"rm -f {shlex.quote(posixpath.join(APP_DIR, rel))}")
                print(f"  removed stale {rel}")
    env = f"SAND_WORKER_TOKEN={worker_token()}\nSAND_DATA=/app/data\n"
    ai_key = read_env(APP_CFG).get("ANTHROPIC_API_KEY")       # Bill's key for this app, pasted 2026-11-25
    if not ai_key:
        # Never drop the key silently: on 2026-11-26 the local file had lost its key line and two deploys switched
        # the server's drawing off during the party. Keep whatever key the box already has, else stop.
        try:
            with sftp.open(posixpath.join(APP_DIR, ".env")) as f:
                for line in f.read().decode().splitlines():
                    if line.startswith("ANTHROPIC_API_KEY=") and line.split("=", 1)[1].strip():
                        ai_key = line.split("=", 1)[1].strip()
                        print(f"  WARNING: no ANTHROPIC_API_KEY in {APP_CFG}; keeping the key already on the box")
        except IOError:
            pass
    if ai_key:
        env += f"ANTHROPIC_API_KEY={ai_key}\n"
    elif os.environ.get("SAND_DEPLOY_NO_KEY") == "1":
        print(f"  note: no ANTHROPIC_API_KEY anywhere; the server will not make drawings itself")
    else:
        raise SystemExit(f"STOP: no ANTHROPIC_API_KEY in {APP_CFG} or on the box. The server could not make drawings. "
                         "Put the key back, or set SAND_DEPLOY_NO_KEY=1 to deploy without it on purpose.")
    with sftp.open(posixpath.join(APP_DIR, ".env"), "w") as f:
        f.write(env)
    sftp.chmod(posixpath.join(APP_DIR, ".env"), 0o600)
    sftp.close()
    print(f"  uploaded {len(files)} files")


def deploy(build=True):
    cl, c = connect()
    print(f"== uploading to {c['WG_HOST']}:~/{APP_DIR}")
    upload(cl)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # data/ is root-owned (made by the container), so back up from inside the container.
    run(cl, f"docker exec {NAME} sh -c 'test -f /app/data/sand.db && cp /app/data/sand.db /app/data/sand.db.bak-{stamp} "
            f"&& echo db backed up to data/sand.db.bak-{stamp}' 2>/dev/null || echo 'no running container or no db yet'")
    if build:
        compose = "docker compose" if run(cl, "docker compose version >/dev/null 2>&1") == 0 else "docker-compose"
        print(f"== {compose} build")
        rc = run(cl, f"cd {APP_DIR} && {compose} build > /tmp/sand-build.log 2>&1; rc=$?; tail -3 /tmp/sand-build.log; exit $rc")
        if rc != 0:
            raise SystemExit(f"image build failed rc={rc}; see /tmp/sand-build.log on the box")
        # compose v1 on this box cannot recreate a running container (KeyError 'ContainerConfig'):
        # remove by exact name, then start fresh. data/ is a bind mount, so nothing is lost.
        rc = run(cl, f"cd {APP_DIR} && (docker ps -aq --filter name={NAME} | xargs -r docker rm -f >/dev/null); "
                     f"{compose} up -d 2>&1 | tail -3")
        if rc != 0:
            raise SystemExit(f"container swap failed rc={rc}")
        for _ in range(40):
            time.sleep(1)
            _, o, _ = cl.exec_command(f"curl -s -m 3 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{PORT}/api/state")
            if o.read().decode().strip() == "200":
                print("== app answers on the box")
                break
        else:
            raise SystemExit(f"container did not come up; check `docker logs {NAME}`")
    cl.close()


def site():
    """First-time web-server setup. Only ever adds one new file; reloads nginx only if its config test passes."""
    cl, c = connect()
    conf = "/etc/nginx/conf.d/sand-app.conf"
    rc = sudo(cl, c, f"test -e {conf} && echo 'already installed: {conf}' || "
                     f"(cp ~{c['WG_USER']}/{APP_DIR}/deploy/nginx-sand.conf {conf} && echo installed {conf})")
    if rc != 0:
        raise SystemExit("could not install the nginx block")
    if sudo(cl, c, "nginx -t 2>&1") != 0:
        sudo(cl, c, f"rm -f {conf}")
        raise SystemExit("nginx config test failed; the new block was removed and nginx was NOT reloaded")
    sudo(cl, c, "systemctl reload nginx && echo nginx reloaded")
    sudo(cl, c, "certbot --nginx -d sand.example.com --non-interactive --agree-tos --redirect "
                "--register-unsafely-without-email 2>&1 | tail -8", timeout=180)
    if sudo(cl, c, "nginx -t 2>&1") == 0:
        sudo(cl, c, "systemctl reload nginx")
    cl.close()


def pages():
    """Page-only change (static/): upload, then copy into the RUNNING container. No rebuild, no restart, so the
    site never goes away (a normal deploy is unreachable for about 15 s). Server code changes still need deploy()."""
    cl, _ = connect()
    upload(cl)
    rc = run(cl, f"cd {APP_DIR} && docker cp static/. {NAME}:/app/static/ && echo '== pages updated in the running container'")
    cl.close()
    sys.exit(rc)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["pages"]:
        pages()
    if args[:1] == ["run"]:
        cl, _ = connect()
        sys.exit(run(cl, " ".join(args[1:])))
    if args[:1] == ["site"]:
        site()
    else:
        deploy(build="--no-build" not in args)
