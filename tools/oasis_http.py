#!/usr/bin/env python3
"""Send local HTTP commands to the Oasis Mini once it's on a network (no cloud).
The firmware's local web server answers GET http://<ip>/?NAME=value. Commands here
are the ones proven to run with the cloud unreachable.

  oasis_http.py <ip> status               -> GETSTATUS
  oasis_http.py <ip> play <id>            -> WRIJOBLIST=<id> then CMDPLAY (draw a cached track)
  oasis_http.py <ip> pause|stop           -> CMDPAUSE / CMDSTOP
  oasis_http.py <ip> raw NAME[=value]     -> any single command

Nothing here contacts Grounded; it talks only to the table on the LAN.
"""
import sys, urllib.request, urllib.parse

def cmd(ip, name, value=""):
    url = f"http://{ip}/?{name}=" + urllib.parse.quote(str(value))
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8", "replace")

def main():
    ip, op = sys.argv[1], sys.argv[2]
    if op == "status":
        print(*cmd(ip, "GETSTATUS"))
    elif op == "play":
        tid = sys.argv[3]
        print("WRIJOBLIST:", *cmd(ip, "WRIJOBLIST", tid))
        print("CMDPLAY:", *cmd(ip, "CMDPLAY"))
    elif op in ("pause", "stop"):
        print(*cmd(ip, "CMDPAUSE" if op == "pause" else "CMDSTOP"))
    elif op == "raw":
        name, _, val = sys.argv[3].partition("=")
        print(*cmd(ip, name, val))
    else:
        sys.exit("unknown op")

if __name__ == "__main__":
    main()
