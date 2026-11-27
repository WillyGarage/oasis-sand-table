"""Copy the Oasis Mini's whole flash to a file over USB, in 1 MB pieces with retries.
Read-only. Windows Python with esptool. Usage: dump_flash.py COM3 out.bin [baud]
One long read at 460800 or 921600 died twice on this table's CH340 cable ("Serial data stream
stopped"); 230400 in pieces works."""
import hashlib, os, subprocess, sys
port, out = sys.argv[1], sys.argv[2]
baud = sys.argv[3] if len(sys.argv) > 3 else "230400"
SIZE, CHUNK = 0x1000000, 0x100000
parts = []
for off in range(0, SIZE, CHUNK):
    part = f"{out}.{off:08x}.part"
    for attempt in range(1, 6):
        if os.path.exists(part) and os.path.getsize(part) == CHUNK:
            break
        r = subprocess.run([sys.executable, "-m", "esptool", "-p", port, "-b", baud, "--after", "no-reset",
                            "read-flash", hex(off), hex(CHUNK), part], capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.exists(part) and os.path.getsize(part) == CHUNK
        print(f"{off:#010x} attempt {attempt}: {'ok' if ok else 'FAILED ' + (r.stdout + r.stderr).strip().splitlines()[-1]}", flush=True)
        if ok:
            break
        if os.path.exists(part):
            os.remove(part)
    else:
        sys.exit(f"gave up at {off:#x}")
    parts.append(part)
h = hashlib.sha256()
with open(out, "wb") as f:
    for p in parts:
        b = open(p, "rb").read(); f.write(b); h.update(b)
for p in parts:
    os.remove(p)
print("DONE", out, os.path.getsize(out), "sha256", h.hexdigest(), flush=True)
