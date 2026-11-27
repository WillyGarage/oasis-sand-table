"""Ask the Oasis Mini about itself over Bluetooth. Sends only query commands whose meaning is
known from natekspencer/ha-oasis-control (clients/ble_client.py), never anything that changes
the table. Usage: oasis_query.py [COMMAND ...]   (default: the identity/status set below)
Each command is written as compact JSON {"command": NAME}, >= 1.2 s apart, replies are JSON
notifications on the same characteristic (may arrive in fragments)."""
import asyncio, json, sys, time
from bleak import BleakClient, BleakScanner
ADDR = "AA:BB:CC:DD:EE:FF"
CHAR = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
SAFE = {"GETSOFTWAREVER", "GETID", "GETMAC", "WIFISTATUS", "GETSTATUS", "LINESTATUS",
        "DOWNLOADSTATUS", "GETPLAYLIST", "GETSCH", "GETWIFILIST", "GEHTTPSTATUS", "ATTACH_STATUS"}
DEFAULT = ["GETSOFTWAREVER", "GETID", "GETMAC", "WIFISTATUS", "GETSTATUS", "LINESTATUS",
           "DOWNLOADSTATUS", "GETPLAYLIST"]

async def main():
    cmds = sys.argv[1:] or DEFAULT
    bad = [c for c in cmds if c not in SAFE]
    if bad:
        sys.exit(f"refusing non-query command(s): {bad}")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, a: d.address.upper() == ADDR or (a.local_name or d.name or "").startswith("Mini ("), timeout=25)
    if not dev:
        sys.exit("NOT FOUND")
    t0 = time.time()
    def on(_c, data):
        print(f"  <- +{time.time()-t0:5.1f}s {bytes(data)!r}", flush=True)
    async with BleakClient(dev, timeout=30) as c:
        await c.start_notify(CHAR, on)
        await asyncio.sleep(1.0)
        for name in cmds:
            payload = {"command": name}
            if name == "GETPLAYLIST":
                payload["part"] = "0"
            data = json.dumps(payload, separators=(",", ":")).encode()
            print(f"-> +{time.time()-t0:5.1f}s {data.decode()}", flush=True)
            await c.write_gatt_char(CHAR, data, response=True)
            await asyncio.sleep(12.0 if name == "GETWIFILIST" else 3.0)
        await asyncio.sleep(2.0)
        await c.stop_notify(CHAR)
    print("disconnected cleanly")
asyncio.run(main())
