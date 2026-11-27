#!/usr/bin/env python3
"""Apply surgical byte patches to the Oasis Mini app image, with verification.

Each patch: (offset_in_app0, original_hex, new_hex). We refuse to write unless the
original bytes match exactly, so a wrong offset can't silently corrupt the image.
Outputs a patched app0.bin AND a patched full 16MB image (app0 lives at flash
0x10000). Flash either the app0 region (write-flash 0x10000 app0_patched.bin) or
the whole image. Backup is always the undo.

Usage: apply_patch.py app0_in.bin full16_in.bin out_prefix  patch1 [patch2 ...]
  where each patch is  OFFSET:ORIGHEX:NEWHEX   (offset decimal or 0x..)
"""
import sys

def parse(p):
    off, orig, new = p.split(":")
    off = int(off, 0)
    orig = bytes.fromhex(orig); new = bytes.fromhex(new)
    assert len(orig) == len(new), f"patch {p}: length mismatch (must not change instruction length)"
    return off, orig, new

def main():
    app0 = bytearray(open(sys.argv[1], "rb").read())
    full = bytearray(open(sys.argv[2], "rb").read())
    out = sys.argv[3]
    APP0_IN_FULL = 0x10000
    for p in sys.argv[4:]:
        off, orig, new = parse(p)
        have = bytes(app0[off:off+len(orig)])
        if have != orig:
            sys.exit(f"ABORT patch @{off:#x}: expected {orig.hex()} but found {have.hex()}")
        app0[off:off+len(new)] = new
        full[APP0_IN_FULL+off:APP0_IN_FULL+off+len(new)] = new
        print(f"patched app0 @{off:#x} (full @{APP0_IN_FULL+off:#x}): {orig.hex()} -> {new.hex()}")
    open(out+"-app0.bin", "wb").write(app0)
    open(out+"-full16.bin", "wb").write(full)
    print("wrote", out+"-app0.bin", "and", out+"-full16.bin")

if __name__ == "__main__":
    main()
