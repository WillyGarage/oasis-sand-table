"""Read-only look at the Oasis Mini over Bluetooth: list services/characteristics and read the
readable ones. Never writes a value, never subscribes, never pairs."""
import asyncio, json
from bleak import BleakClient, BleakScanner
ADDR = "AA:BB:CC:DD:EE:FF"
async def main():
    dev = await BleakScanner.find_device_by_filter(
        lambda d, a: d.address.upper() == ADDR or (a.local_name or d.name or "").startswith("Mini ("), timeout=25)
    if not dev:
        print("NOT FOUND"); return
    print("found", dev.address, dev.name)
    async with BleakClient(dev, timeout=30, winrt={"use_cached_services": False}) as c:
        print("connected mtu", c.mtu_size)
        for s in c.services:
            print(f"SERVICE {s.uuid} ({s.description}) handle={s.handle}")
            for ch in s.characteristics:
                line = f"  CHAR {ch.uuid} ({ch.description}) h={ch.handle} props={ch.properties}"
                if "read" in ch.properties:
                    try:
                        v = await asyncio.wait_for(c.read_gatt_char(ch), 8)
                        line += f"\n    value hex={bytes(v).hex()} text={bytes(v)!r}"
                    except Exception as ex:
                        line += f"\n    read failed: {type(ex).__name__}: {ex}"
                print(line)
                for d in ch.descriptors:
                    dl = f"    DESC {d.uuid} h={d.handle}"
                    try:
                        v = await asyncio.wait_for(c.read_gatt_descriptor(d.handle), 5)
                        dl += f" value={bytes(v).hex()} {bytes(v)!r}"
                    except Exception as ex:
                        dl += f" read failed: {type(ex).__name__}"
                    print(dl)
    print("disconnected cleanly")
asyncio.run(main())
