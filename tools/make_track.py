#!/usr/bin/env python3
"""Wrap a theta-rho .thr (plain text, one "theta rho" pair per line, theta in radians,
rho 0..1) into an Oasis Mini cached-track file ("OMJ2", AES-256-GCM, job key).

Container (reverse-engineered from fw3.16, proven byte-for-byte):
    magic "OMJ2" | version 0x01 | nonce[12] | tag[16] | ciphertext
GCM over the plaintext only, no associated data. The firmware reads exactly 33
header bytes, decrypts, and plays the text. The decrypted file is the .thr itself.

Usage: make_track.py in.thr out.omj2
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oasis_crypt as oc

def build_track(thr_text: bytes, nonce: bytes = None) -> bytes:
    if isinstance(thr_text, str):
        thr_text = thr_text.encode()
    return oc.encrypt_file(thr_text, oc.JOB_KEY, magic=oc.MAGIC_JOB, version=1, nonce=nonce)

if __name__ == "__main__":
    thr = open(sys.argv[1], "rb").read()
    out = build_track(thr)
    open(sys.argv[2], "wb").write(out)
    # self-check: decrypt back
    assert oc.decrypt_file(out, oc.JOB_KEY) == thr
    print(f"wrote {sys.argv[2]}  {len(out)} bytes (thr {len(thr)} + 33 header)  verified decrypts back")
