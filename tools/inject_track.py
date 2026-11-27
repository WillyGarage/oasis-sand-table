#!/usr/bin/env python3
"""Add a cached-track file to a copy of the Oasis Mini's LittleFS image, so the stock
firmware can play it offline (it treats /spiffs/<id> as "already cached" and skips the
Grounded download). Reversible: the original image is untouched; flash the OUTPUT image
to the spiffs partition (offset 0x510000) over USB, with the full backup as undo.

Every existing file (certs, keys, settings) is preserved byte-for-byte.

Usage: inject_track.py spiffs_in.bin track_id track.omj2 spiffs_out.bin [path/to/littlefs/pkg]
"""
import sys, os
LFS_PKG = sys.argv[5] if len(sys.argv) > 5 else None
if LFS_PKG:
    sys.path.insert(0, LFS_PKG)
from littlefs import LittleFS

def inject(img_in: bytes, track_id: str, omj2: bytes) -> bytes:
    img = bytearray(img_in)
    fs = LittleFS(block_size=4096, block_count=len(img)//4096, mount=False)
    fs.context.buffer = img
    fs.mount()
    path = "/" + track_id
    with fs.open(path, "wb") as f:
        f.write(omj2)
    fs.unmount()
    return bytes(fs.context.buffer)

if __name__ == "__main__":
    img_in = open(sys.argv[1], "rb").read()
    track_id = sys.argv[2]
    omj2 = open(sys.argv[3], "rb").read()
    out = inject(img_in, track_id, omj2)
    assert len(out) == len(img_in)
    open(sys.argv[4], "wb").write(out)
    # verify
    fs = LittleFS(block_size=4096, block_count=len(out)//4096, mount=False)
    fs.context.buffer = bytearray(out); fs.mount()
    files = fs.listdir("/")
    with fs.open("/"+track_id, "rb") as f: got = f.read()
    print("files now:", sorted(files))
    print("track present & intact:", got == omj2)
    changed = sum(1 for i in range(0,len(img_in),4096) if img_in[i:i+4096]!=out[i:i+4096])
    print(f"changed 4K blocks: {changed} of {len(img_in)//4096}  (reflash just these or the whole partition)")
