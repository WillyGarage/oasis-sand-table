"""Put the Oasis Mini on Wi-Fi without the app: the CONNECT message read from Grounded's
Android app (see README). NOT RUN YET. Changes the table's saved Wi-Fi; needs Bill's yes.
Usage (Windows Python): oasis_join.py <ssid>
The password is read from this laptop's saved Wi-Fi profile for that network (netsh) and is
never printed or logged. Sends CONNECT, then polls WIFISTATUS until connected/failed.
Does not send ATTACH (that is the cloud-account binding we are avoiding)."""
import asyncio, json, re, subprocess, sys, time
from bleak import BleakClient, BleakScanner
ADDR = "AA:BB:CC:DD:EE:FF"
CHAR = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
MEANING = {"0": "pending", "1": "connected", "2": "could not connect", "3": "wrong password"}

def saved_password(ssid):
    out = subprocess.run(["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"],
                         capture_output=True, text=True).stdout
    m = re.search(r"Key Content\s*:\s*(.+)", out)
    if not m:
        sys.exit(f"no saved Wi-Fi password for {ssid!r} on this laptop")
    return m.group(1).strip()

async def main():
    ssid = sys.argv[1]
    pw = saved_password(ssid)
    if len(ssid) > 31 or len(pw) > 31:
        sys.exit("ssid or password longer than 31 characters: the app refuses these")
    dev = await BleakScanner.find_device_by_filter(lambda d, a: d.address.upper() == ADDR, timeout=25)
    if not dev:
        sys.exit("NOT FOUND")
    last = {}
    def on(_c, data):
        text = bytes(data).decode(errors="replace")
        print("  <-", text, flush=True)
        try:
            m = json.loads(text)
            if m.get("command", "").startswith("WIFISTATUS"):
                last.update(m)
        except ValueError:
            pass
    async def send(payload, show=None):
        print("->", show or json.dumps(payload, separators=(",", ":")), flush=True)
        await c.write_gatt_char(CHAR, json.dumps(payload, separators=(",", ":")).encode(), response=True)
    async with BleakClient(dev, timeout=30) as c:
        print("mtu", c.mtu_size)
        await c.start_notify(CHAR, on)
        await asyncio.sleep(1.2)
        await send({"command": "CONNECT", "ssid": ssid, "pass": pw},
                   show=f'{{"command":"CONNECT","ssid":"{ssid}","pass":"<hidden, {len(pw)} chars>"}}')
        t0 = time.time()
        while time.time() - t0 < 45:
            await asyncio.sleep(1.5)
            await send({"command": "WIFISTATUS"})
            await asyncio.sleep(0.5)
            if last.get("status") in ("1", "2", "3", 1, 2, 3):
                break
        print("RESULT:", MEANING.get(str(last.get("status")), "no answer"), {k: v for k, v in last.items() if k != "command"})
        await asyncio.sleep(3)
        await send({"command": "WIFISTATUS"}); await asyncio.sleep(1.5)
        await send({"command": "GETSOFTWAREVER"}); await asyncio.sleep(1.5)
asyncio.run(main())
