# Firmware notes (fw 3.16)

How the table stores and protects its files, recovered from the USB backup
(`../backup/oasis-mini-fw3.16-full-16MB.bin`) so we can make our own patterns and,
if we go that way, our own firmware. Nothing here talks to Grounded.

## File crypto (proven)

The table's own files are **AES-256-GCM** (mbedTLS). Two 256-bit keys are baked
into the firmware as plain constants (so they are the same on every Oasis Mini on
this firmware, not unique to ours):

| Purpose | Magic | Key constant lives at (app image offset) |
|---|---|---|
| `/settings.enc`, `/schedule.enc` | `OMSE` | app0 `0x72f9` |
| cached tracks + `/joblist.enc` | `OMJ2` | app0 `0x72d9` |

The key bytes themselves are in [`../tools/oasis_crypt.py`](../tools/oasis_crypt.py).

**File layout** (both kinds): `magic[4]` + `version[1]=0x01` + `nonce[12]` +
`tag[16]` + `ciphertext[N]`. No associated data. The 16-byte tag comes *before*
the ciphertext. Storage is **LittleFS** (4096-byte blocks), not SPIFFS.

**Proven, not guessed:** decrypting the real `/settings.enc` off this table gives
a verifying tag and clean JSON ([`settings.decrypted.json`](settings.decrypted.json)),
and re-encrypting with the same nonce reproduces the file byte-for-byte.

## What that unlocks

- Read/modify the table's own settings and schedule files.
- Make a track file (`OMJ2`, job key) the stock firmware will accept, write it
  into LittleFS over USB, and play it locally with no Grounded account. Two
  details are still being pinned from the backup before we try it: the exact
  `OMJ2` header (about 0x1d bytes of id/size fields before the nonce) and the
  filename the firmware expects a cached track to have, which `/joblist.txt`
  points at. The pattern itself, once decrypted, is a plain `.thr`: one
  `theta rho` pair per line (units not yet confirmed).

## Hardware (for a possible own-firmware route)

Confirmed from the code: two bit-banged steppers (axes A and B, polar
theta/rho, `armoffset` calibration, default speed 400), LEDs driven over RMT
(WS2812-class), ESPAsyncWebServer, Bluedroid BLE. **The exact pin numbers, LED
count and steps-per-turn are not yet pulled** - they come from a deeper read of
the backup or from opening the table. Factory/test commands (`FULLTEST`,
`MOTORAON`, `SETID`, `LEDCAL`, ...) arrive over Bluetooth, not the USB port; the
USB port prints nothing after the boot banner.

## Re-deriving this

The reusable tooling is here (`mkelf.py` builds an ELF from the app image,
`xref.py`/`q.py` index which code uses which string/constant). The disassembler
is Espressif's prebuilt `xtensa-esp32s3-elf-objdump`; `cryptography` and
`littlefs-python` do the file work. None of it is committed as binaries.

## If this repo is ever made public

Pull the two key constants out of `tools/oasis_crypt.py` first (or keep the repo
private). They are Grounded's keys, not ours.

## Current storage contents (from the backup)

The table's LittleFS today holds only its identity and settings - **no track files,
no job list**, so it has never played anything:

```
/device.csr /device.pem /deviceh.pem /private.key   device identity (certs + key)
/mqtt_ca.pem /tls_http_ca.pem                        cloud CA bundles
/settings.enc (OMSE)                                 LED/speed/armoffset etc. (decrypts clean)
/schedule.enc (OMSE)                                 "{}"
```

`/device.pem` + `/private.key` are the device's **real private key and client
certificate** - secrets. They stay in the backup only (gitignored), never copied
into the repo.

## Injecting a pattern is mechanically proven

Adding a file to the LittleFS image and re-reading it is a clean, reversible
round-trip: all existing files stay byte-identical, the image stays the same size,
and only 2 of 2784 blocks change. So a track we build can be written in and the
partition reflashed over USB, with the full backup as the undo. What's still
needed before the first real injection is the exact `OMJ2` track header and the
`/joblist.txt` format (being pulled from the firmware now), and confirmation of
how playback is triggered offline (local HTTP in the table's own access-point
mode would avoid the home network and Grounded entirely).

## Route 1 toolchain (built and verified)

- `../tools/thr_gen.py` — make a theta-rho pattern.
- `../tools/make_track.py in.thr out.omj2` — wrap it as an `OMJ2` cached track
  (job key). Proven: the firmware reads exactly 33 header bytes (magic+version+
  nonce+tag) then the encrypted theta-rho text; our file decrypts at those exact
  offsets.
- `../tools/inject_track.py spiffs_in id track.omj2 spiffs_out <lfs-pkg>` — add
  `/spiffs/<id>` to a copy of the storage image. Every existing file stays
  byte-identical. Flash the output to the spiffs partition (0x510000) over USB.
- Proven offline: the firmware treats `/spiffs/<id>` as "already cached" and
  skips the Grounded download (exists-bit test at 0x42022088 → "already cached").

A first image is built: `../build/spiffs-with-90001.bin` carries track id `90001`
(a 30-loop spiral, 10,802 points), verified by decrypting it back out of the
finished image. The open piece is the **play trigger on 3.16** (BLE is setup-only
here, so CMDPLAY is HTTP-only): being resolved — ideally start the table's own
`OasisMini` hotspot so Grounded is never reachable.
