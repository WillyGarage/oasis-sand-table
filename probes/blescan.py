import asyncio, sys
from bleak import BleakScanner
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 25
async def main():
    seen = {}
    def cb(d, a):
        e = seen.setdefault(d.address, {"name": None, "rssi": -999, "uuids": set(), "mfr": {}, "svc": {}, "n": 0})
        e["n"] += 1
        nm = a.local_name or d.name
        if nm: e["name"] = nm
        e["rssi"] = max(e["rssi"], a.rssi)
        e["uuids"].update(a.service_uuids or [])
        for k, v in (a.manufacturer_data or {}).items(): e["mfr"][k] = v.hex()
        for k, v in (a.service_data or {}).items(): e["svc"][k] = v.hex()
    async with BleakScanner(cb, scanning_mode="active"):
        await asyncio.sleep(SECS)
    for addr, e in sorted(seen.items(), key=lambda kv: -kv[1]["rssi"]):
        print(f'{addr} rssi={e["rssi"]} n={e["n"]} name={e["name"]!r} uuids={sorted(e["uuids"])} mfr={e["mfr"]} svc={e["svc"]}')
    print("TOTAL", len(seen))
asyncio.run(main())
