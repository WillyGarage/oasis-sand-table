# Big (36 inch) table factory flash vs the Mini (fw 3.16)

Dated 2026-11-22. Analysis of the two USB dumps on disk only; no hardware or network touched.
Dumps: `backup/oasis-36in-factory-full-16MB.bin` (big) and `backup/oasis-mini-fw3.16-full-16MB.bin` (Mini).

How each fact was learned is tagged: **[dump]** read/decrypted straight from the dump,
**[disasm @addr]** found in the firmware 3.16 disassembly (app0 is byte-identical on both tables),
**[inferred]** reasoned from what was found, not proven.

## Headline

The firmware picks a **hardware model from the first two letters of the device id**
[disasm @0x4201b78c..0x4201b869]. The Mini's id starts `ON` (model 4). The big table's id is
`CT26xxxxxxx` (the board label and three older NVS entries say `CT26xxxxxxx`; same `CT` prefix), so it runs **model 3**: 157 LEDs instead of 43, a different motor/motion
parameter set, its own homing routine, its own kinematics branch, and different driver-enable
pin setup. Nothing else in the firmware differs, so the id alone changes how the same code
drives the table. [disasm for the existence of every branch; inferred for what each constant means]

## 1. Storage partition [dump]

Storage is LittleFS (4096 byte blocks) at 0x510000, read with `littlefs-python` in a scratch venv.

| Table | Files |
|---|---|
| Mini | `/device.csr` 936, `/device.pem` 915, `/deviceh.pem` 976, `/mqtt_ca.pem` 748, `/private.key` 1679, `/schedule.enc` 35, `/settings.enc` 409, `/tls_http_ca.pem` 1743 |
| Big | `/schedule.enc` 35, `/settings.enc` 410 |

The big table has **no device certificate, no private key and no CA files**: it was never
provisioned for Grounded's cloud (so there is no certificate CN to report). The Mini carries
the cloud identity files. No `.thr`/track files on either.

Both `.enc` files decrypt with the settings key in `tools/oasis_crypt.py` (tag verifies).
`schedule.enc` is `{}` on both. Nothing sensitive printed or saved here.

### settings.enc diff [dump]

Only three keys differ. Everything else (speed 400, cleanbefore 1, ledeffect 1,
ledeffectcolor 1, ledparameters #ffee00, ledbrightness 100, ledspeed 0, jobrepeat 0,
waitafter 0, oasismode 1, envir 1, all wifi_* empty) is identical.

| Key | Mini | Big |
|---|---|---|
| `oasisminiid` | `ON26xxxxxxx` | `CT26xxxxxxx` |
| `armoffset` | 0 | 5 |
| `ledoffset` | 0 | 34 |

(The id values carry a trailing CR LF in the file.)

## 2. NVS (0x9000, 0x5000) [dump, own parser]

Parsed with a small ESP-IDF NVS reader. Namespaces: Mini has `mig phy bt_config.conf identity
misc nvs.net80211 dhcp_state`; big has the same minus `dhcp_state`. Wi-Fi password values were
redacted (they are empty/zero anyway). The Bluetooth key blob was not printed.

Differences:

- `identity/oasisid`: Mini `ON26xxxxxxx`, big `CT26xxxxxxx` (same as settings.enc).
- `phy/cal_mac`: Mini `aa:bb:cc:xx:xx:xx`, big `aa:bb:cc:yy:yy:yy`. `phy/cal_data` differs
  (per-chip RF calibration, expected).
- `bt_config.conf/bt_cfg_key0`: differs (per-device Bluetooth keys, expected).
- Wi-Fi: Mini has station settings (`sta.*`), a saved AP record naming the factory test network
  `OasisTest`, soft-AP name `OasisMini` on channel 1, and `dhcp_state`. The big table has none of
  the station entries, no `dhcp_state`, a blank soft-AP name (zeros), AP channel 6.
  [inferred] The Mini went through a factory Wi-Fi test; the big table did not (or was wiped).
- Everything else (`phy/cal_version` 610, opmode 1, AP limits, beacon interval) is identical.
- No NVS key holds a model, size, motor or LED setting. The only identity in NVS is `oasisid`.

## 3. What the firmware does with these

### 3.1 id prefix selects the model [disasm @0x4201b78c-0x4201b869]

Boot code (in the large function at 0x4201a7cc) reads the id and stores an integer in the global
at 0x3fca3454 (call it `model`):

| Id starts with | model |
|---|---|
| `OM` | 1 |
| `ST` | 2 |
| `CT` | 3 (**big table**) |
| `ON` | 4 (**Mini**) |
| anything else (2+ chars) | 1 |
| shorter than 2 chars | 0 |

The default/unprovisioned id string in the firmware is `XX999999999` (defaults function at
0x4201a4e4, also checked at boot), which would give model 1.
Product names for models 1 and 2 are not known; the only ones we can tie to hardware are
4 = this Mini and 3 = the big table (inferred from the id on each dump).

### 3.2 LED count per model [disasm @0x42004ad8]

Sets `0x3fc985a8` (LED count; used as the modulus for `ledoffset`) and `0x3fc985a4`:

| model | LED count | 0x3fc985a4 |
|---|---|---|
| 1, 4 | 43 | 200 |
| 2 | 89 | 255 |
| 3 | **157** | 255 |

43 matches the 43 WS2812 LEDs we measured on the Mini. [inferred] The big table has 157 LEDs on
the same data line. Confirm by probing before trusting.
Also `0x42004b20` sets `0x3fc985a0` to 13 (models 1, 4) or 21 (models 2, 3); meaning unknown.

### 3.3 Motion parameter set per model [disasm @0x42004b48-0x42004d90]

One function writes ~25 globals per model. Values (floats shown decoded). Names of the
parameters are **not** known; meanings below are guesses.

| Global | Mini (m4) | Big (m3) |
|---|---|---|
| 0x3fca3300 | 100 | 200 |
| 0x3fca3304 | 500 | 2000 |
| 0x3fc985f8, 0x3fc985fc | not set (stays 1) | **32**, **32** |
| 0x3fc985d0, 0x3fc985d4 | not set | 32, 32 |
| 0x3fca32dc, 0x3fca32e0 | not set | **6400**, **6400** |
| 0x3fca32d0 | 5 | 6 |
| 0x3fc985d8 | 5.0 | 6.0 |
| 0x3fc985bc | 100.0 | 200.0 |
| 0x3fc985c4 | 0.6 | 0.35 |
| 0x3fc985b8 | 300.0 | 700.0 |
| 0x3fc985f4 | 0.97 | 1.0 |
| 0x3fc985cc | stays 6 | 6 |
| 0x3fc985c8 | not set | 160.0 |
| 0x3fc985f0 | not set | 355.0 |
| 0x3fca32d4 / 0x3fca32d8 | not set | 160.0 / 106.67 |
| 0x3fc985ec | 512 | not set |
| 0x3fc98600 | 1 | not set |

Model 2 (`ST`) is close to model 3 (same 32, 32, 6400, 6400). Models 1 and 4 share a family.

[inferred] 6400 = 200 full steps x 32 microsteps, and 32 is the microstep factor, i.e. the big
table's motors are driven with fixed 32x microstepping and a 6400 steps-per-motor-turn constant.
The Mini has no such constants (1 / 1), consistent with its own sine/cosine PWM microstepping.
Not proven: the code that consumes 0x3fc985f8/0x3fca32dc was only read in part (0x4200b56c,
0x4200bb38, 0x4200bcc0).

### 3.4 Different pin setup, homing and kinematics per model [disasm]

These are proven to branch on `model`; what exactly each branch does is **not** decoded.

- **Driver pins at start** (`0x42009a38`): models 1 and 4 drive GPIO 11 and GPIO 5 high. Models
  2 and 3 drive GPIO 34 low, GPIO 11 low, then GPIO 5 high. Two helpers (0x420098ac,
  0x420098ec) also treat models 1/4 differently from 2/3 (a flag at 0x3fc9fce4/e8).
- **Motor/homing state machine** (`0x4200b56c`) calls a different routine per model:
  model 1 -> 0x4200a57c, model 2 -> 0x4200b26c, model 3 -> 0x4200ae30, model 4 -> 0x4200a9c4.
  Models 1 and 4 routines are near-twins and use the flags above plus 0x3fc985a0; models 2 and 3
  do not use those flags and instead read `armoffset` (0x3fca32c4) and the 6400/32 values.
  [inferred] The Mini homes against a sensor input; the big table computes position in steps with
  the stored arm offset instead (or uses a different sensor scheme). Needs bench confirmation.
- **Kinematics** (`0x42009458` and the switch at 0x420095fb): model 2 -> path at 0x42009681
  (uses 0x3fca32ec), model 3 -> path at 0x420096ac (uses 0x3fc985f0 = 355.0 and the threshold
  0x3fc985c8 = 160.0, calls the helper 0x42009458), models 1 and 4 -> path at 0x4200962a (0x3fca32ec).
  So the big table uses a different arm geometry branch from the Mini.
- **Not model dependent:** the PWM pin init (0x42009a7c) does not read `model`. [inferred] the
  physical motor pin numbers that firmware drives are the same set on every model, though
  models 2/3 may use them differently (e.g. step/direction rather than coil PWM) - unproven.

### 3.5 What the three settings.enc differences do

- **`oasisminiid`** -> chooses model (above), also used as MQTT/HTTP identity and checked
  against the certificate CN ("Certificate CN does not match current oasisid" string). Proven.
- **`armoffset`** (int degrees). Saved by 0x42015bbc to `/armoffset.txt`; global 0x3fca32c4.
  Wrapped to 0..359 (compare with 0x167 at 0x4200bca0..bcb8); in 0x4200b008 it is converted to
  float and divided by 360.0 (0x43b40000) before use as a rotation of the arm angle. Proven for
  the degrees and wrap; "applied as the theta home offset" is inferred. The big table has 5.
  [inferred] a small factory calibration trim; the Mini is 0.
- **`ledoffset`** (int). Global 0x3fc98608, file `/ledoffset.txt`. The animation code
  (0x4200bb38) takes it modulo the LED count (`rems` against 0x3fc985a8), so it is a rotation of
  the LED pattern around the ring. Proven. The big table has 34 (valid for 43 or 157 LEDs).
- **`oasismode`** (both 1) and **`envir`** (both 1): `envir` is clamped to 1..3 and selects the
  cloud environment (default host string `dev.mqtt.grounded.so` is used when envir != 1)
  [disasm @0x42013314, 0x4201b880]. No motor effect. `oasismode` is reset to the string "1" by
  the boot path; no motor effect found.
- `speed` 400 identical on both; read only through the settings map, no per-model difference.

## 4. Implications for our own firmware on the big table

1. Do not assume the Mini's LED count (43), pins, steps or kinematics. The factory firmware
   itself treats this table as a different machine (model 3).
2. Probe order suggested by the findings: LED count (157?), GPIO 34/11/5 behaviour and whether
   the drivers are enabled by 34 low, motor pins and step counts per turn (6400 per motor turn is
   a hypothesis), homing method. Use the same live-drive method as the Mini (camera, small moves).
3. Starting values to carry over from the factory flash: `armoffset` 5 and `ledoffset` 34.

## What is unproven

- Names and exact meanings of the model-3 constants in 3.3 and which motor each applies to.
- Whether the big table has a home/limit sensor and which pin.
- Whether the big table really has 157 LEDs (firmware says so; hardware not checked).
- What 0x3fc985a0 (13 vs 21) and 0x3fc985a4 (200 vs 255) control.

Working files (not in the repo): scratch venv, dumps of the LittleFS images, NVS output, ELF
rebuilt with `firmware-notes/mkelf.py` and its objdump, under the session scratchpad.

## 5. Model 3 pins, homing and kinematics (disasm)

Added 2026-11-22 from the same fw 3.16 disassembly. "proven" = read directly in the code at the
address given; "inferred" = reasoned from that code. Hardware not touched. Model 3 = id prefix `CT`.
Which init runs per model: `0x420135dc` calls the LEDC/coil-PWM init `0x42009a7c` only for models 1 and 4
(branch at 0x420135fa-0x42013618). Models 2 and 3 call `0x42009b94` instead (0x42013643). So **the 20 kHz
LEDC init never runs on model 3** (proven), and the step/direction code at 0x42003ddc/0x42003e05 is the
model 2/3 path (proven; the old guess in hardware-map.md for GPIO 1/2/14/13 was right for these models and
wrong for the Mini).

### 5.1 Pin table (model 3)

| Function | GPIO | Level / mode | Evidence |
|---|---|---|---|
| LED data (FastLED RMT, WS2812 timings 60/150/90, 157 LEDs) | 38 | same pin on every model | proven: ctor `0x420362ec` called with 38 from 0x4200df10 (models 1/4) and 0x4200df88 (models 2/3); count = `0x3fc985a8` |
| Stepper A STEP / DIR | 1 / 2 | DIR high = positive steps (0x42003e41) | proven: object 0x3fc9fc64 filled `0x0201` at 0x42009cb0-0x42009cb8, pinMode OUTPUT at 0x42009cdd/ced |
| Stepper B STEP / DIR | 14 / 13 | same | proven: object 0x3fc9fc8c = `0x0d0e` at 0x42009caa; pinMode at 0x42009cbd/ccd |
| Driver enable (ENN) | 34 and 11 | OUTPUT, driven LOW = enabled at init (0x42009c9d, 0x42009ca4) and by "drivers on" 0x42009a38; HIGH = disabled by "drivers off" 0x420099f4 (called from the stop/pause code 0x42015821) | proven. Which of 34/11 goes to which TMC is not known; they are always switched together |
| GPIO 5 | 5 | HIGH with drivers on, LOW with drivers off | proven it is written; **no pinMode(5) exists on the model 3 path** (only in the Mini init 0x42009b88), so its role is unknown (inferred: leftover or fixed by the board) |
| TMC UART | TX 17, RX 18 | 115200 8N1 | proven: `begin(0x1c200, 0x800001c, rx=18, tx=17)` at 0x42009ba5-0x42009bb1; port object built as `HardwareSerial(2)` at 0x4201c0cd-0x4201c0e1 -> UART2 (inferred from the ctor argument) |
| Home switch input | **21** (Mini: 13) | `pinMode(pin, INPUT)` - no internal pull-up (0x4201b8c9, mode 1); `digitalRead` | proven: pin number lives in `0x3fc985a0`, set to 21 for models 2/3 and 13 for models 1/4 at 0x42004b20 |
| Other | 37 | INPUT_PULLUP at boot (0x4201acf9) | proven; role unknown (a button) |

No other GPIO is read in the model 3 motion code, and there is no attachInterrupt/DIAG read, so the TMC DIAG
and INDEX outputs are unused by the firmware (inferred from the absence of any other digitalRead).

### 5.2 TMC2209 over UART (proven, 0x42009b94-0x42009c8b)

Two TMCStepper-style driver objects are built at boot (0x4201c0e4-0x4201c126) with sense resistor
0.11 ohm (0x3de147ae) and **UART addresses 1 (obj 0x3fc9fd40) and 2 (obj 0x3fc9fd00)**. For each:
- GCONF: pdn_disable=1 and mstep_reg_select=1 (0x42036558 -> 0x42138b58/0x42138b84, bits 6/7), en_spreadCycle=0
  (0x42138b2c, StealthChop on).
- CHOPCONF (reg 0x6C): toff=4 (0x42138ab8), microsteps from `0x3fc985d0/d4` = **32** (0x42138ca4), intpol=1 (0x42138ae8).
- PWMCONF (reg 0x70): pwm_autoscale=1 (0x42138bac), pwm_autograd=0 (0x42138bdc).
- IHOLD_IRUN (reg 0x10): irun=31 and ihold=31 (0x42036508, 0x420364dc), then `rms_current(1000 mA)`, or
  1200 mA when `0x3fc9861c` != 0 (0x42009bdc, 0x420368b8). rms_current overwrites the 31s; with the
  0.11 ohm sense value that is about IRUN 17 at 1000 mA (inferred from the TMCStepper formula constants at 0x420368c4-0x420368ff).
- No SGTHRS, TCOOLTHRS, SEMIN/SEMAX or stall-guard writes anywhere. MS pins are not driven by GPIO; the
  microstep value is set through the UART (mstep_reg_select). Addresses 1/2 imply MS1/MS2 are strapped on
  the board (inferred).
Which driver goes with which motor: the order of construction and init suggests addr 1 = stepper A (GPIO1/2)
and addr 2 = stepper B (GPIO14/13), but that is inferred only.

### 5.3 Step generation and speed (model 3)

- `0x42004300(stepsB, stepsA, speedB, speedA)` queues a move: stepper B (0x3fc9fc8c) gets arg 1 and arg 3, stepper A
  (0x3fc9fc64) arg 2 and arg 4 (proven, raw bytes at 0x42004318). `0x42003ddc` sets direction (DIR high when steps >= 0),
  stores |steps|, and the interval in microseconds = 1,000,000 / speed(steps/s) + 0.5, never below 7 us (0x42003e4a-0x42003e72).
  Steps are issued from a stepper-update routine at 0x42003e05+ (STEP low, then pulses). No acceleration ramp was seen
  in 0x42003ddc/0x42003e05: constant rate per move (inferred; the update routine was only skimmed).
- Model 3 constants (table in section 3.3): 32 microsteps, 6400 steps per motor turn (`0x3fca32dc`, `0x3fca32e0`),
  gear 6 (`0x3fc985cc`), 160 steps per radius unit (`0x3fca32d4`), 106.667 steps per degree (`0x3fca32d8`).
  Homing/jog speeds in the code: 1600 steps/s (32 x 50), 800 steps/s (32 x 25) and 133.3 steps/s (800/6).
- The `speed` setting (400) goes through a shaping function at 0x42008d58 with constants 700.0 (`0x3fc985b8`),
  cap 200.0 (`0x3fc985bc`) and 0.35 (`0x3fc985c4`) (model 3 values; Mini 300 / 100 / 0.6). It returns a factor
  capped at 200.0 for the segment speed. The exact curve (pow/exp calls at 0x4211e55c/e58c/e7ac) was not worked out.
  `0x3fca3300` (200) is written but never read. `0x3fca3304` (2000) is the default saved to `/oasisminispeed.txt`
  (0x420154a4) and is used as a clamp only in the Mini coil-PWM routine (0x42009d11).

### 5.4 Homing (model 3) - 0x4200ae30 plus the state machine 0x4200b778

Partly decoded; the state numbers are real, the physical meaning is inferred.
- State variable `0x3fca3360`. The shared state machine `0x4200b778` advances when both steppers are idle
  (`0x420098ec`/`0x42009934` return "busy" if steps remain) and, in states 3 and 5, reads the home pin
  `digitalRead(21)`. State 3: pin non-zero (HIGH) means the switch is hit, so both steppers are stopped and it goes to
  state 4. State 5: waits until the pin reads LOW again, then stops and goes to state 6. So the switch is
  **active HIGH** with a plain INPUT (needs an external pull-down or a switch that drives the pin high) (proven in
  0x4200b7a4-0x4200b814; polarity inferred from the branch sense).
- Model 3 routine `0x4200ae30` (called through 0x4200b56c -> 0x4200b5e8) issues the moves:
  - state 0: stepper A (GPIO1/2, the radial axis) moves **+16000 steps (160 x 100) at 1600 steps/s** when the
    "retry" flag `0x3fc9fcd0` is set, otherwise **-800 steps**; goes to state 1.
  - state 4: B moves -5 steps (nudge) at 800 steps/s.
  - state 5: A moves **+62480 steps (= 1.1 x 355 x 160)** at 800 steps/s, i.e. 110 % of the full radial stroke, toward the switch.
  - state 6: further small coupled move; state 7 similar (formulas at 0x4200af43-0x4200afc4, not simplified).
  - state 8: applies `armoffset` (see 5.5), then state 16 = finished (0x4200b265).
  So **stepper A (radius) moves first and is the homing axis; theta (B) is not driven to find home** (inferred from the
  state-0/5 moves; direction signs not tied to a physical direction).
- If the switch is never seen, the retry path (0x4200b7d7) sets the flag and repeats the +16000 chunk.

### 5.5 armoffset in model 3 (proven, 0x4200b008-0x4200b0b9)

`armoffset` degrees (global `0x3fca32c4`) at state 8: if non-zero and flag `0x3fc9fcd1` is clear, f = armoffset / 360
and one coupled move is queued: **B (theta) = -38400 x f steps at 800 steps/s, A = -6400 x f steps at 133.3 steps/s**
(both finish in 48 x f seconds). So armoffset rotates the arm by -armoffset degrees and A follows the coupling below.
The big table's factory value 5 is therefore about -5 degrees (sign relative to DIR levels, not the physical direction).

### 5.6 Kinematics (model 3) - 0x420096ac -> 0x42009458

Not a two-link arm. It is **polar: a rotating arm (theta) plus a linear radius axis (rho), with a coupling term**
(proven for the arithmetic, inferred for the mechanical picture).
Inputs per move: previous and new theta (radians) and rho (0..1), where rho is first multiplied by **355.0**
(`0x3fc985f0`, a full-radius value, probably mm; inferred). Then (0x42009458):
1. dtheta = wrap(theta_new - theta_old) to +-pi, converted to degrees (x180/pi, 0x420094e1-0x42009503).
2. nB = trunc(106.667 x dtheta_deg + carry); the fractional remainder is kept in `0x3fc9fde0` (carry). 106.667 x 360 = **38400
   steps per arm revolution** = 6400 steps per motor turn x 6:1 reduction. Output `B_steps = -nB`.
3. A steps = nB / 6 (the coupling: [`0x3fca32e4`=1] x nB / [`0x3fca32d0`=6], 0x42009523-0x42009541) **+ 160 x
   (rho_new - rho_old)x355** (`0x3fca32d4` = 160 steps per rho unit, i.e. 6400 per motor turn is 40 units, which would be
   a 40 mm per turn belt pulley if the unit is mm; inferred). Output `A_steps = -(that)`.
   Carries for A are in `0x3fc9fddc/0x3fc9fdd8`.
4. Moves where |A pending| is below 160 steps are accumulated in `0x3fca32cc/0x3fca32c8` instead of being issued
   (threshold `0x3fc985c8` = 160.0, 0x420096ea-0x42009700).
Mapping: **motor B (STEP 14 / DIR 13) = theta, motor A (STEP 1 / DIR 2) = rho**; one full arm turn also moves A by 6400
steps (one motor turn) unless rho is commanded the other way (so the arm turn drags the radius axis, as in
the armoffset move). Both output signs are inverted relative to the positive-theta/positive-rho convention (proven
negation at 0x4200956a/0x42009576), so verify direction on the bench.
For comparison models 1/4 (Mini) go through a different path (0x4200962a, scale `0x3fca32ec`) and model 2 through 0x42009681.

### 5.7 What is still unproven
- Which TMC address maps to which motor, and which of GPIO 34/11 enables which driver.
- The role of GPIO5 on model 3 and whether the home pin 21 has a board pull-down.
- Physical directions for each sign, whether 355/160 are millimetres, and the real speed curve.
- States 6 and 7 of homing and the exact order the radius axis, then theta, come to rest.

## 6. Model 3 homing, step by step (disasm)

Added 2026-11-22. Read-only decode of fw 3.16 for model 3 (`CT`). "proven" = read in the code at the address;
"inferred" = reasoned. Sign convention in the firmware: `0x42004300(stepsB, stepsA, speedB, speedA)` queues
a move; stepper B = STEP14/DIR13 (arm), stepper A = STEP1/DIR2 (radius) (0x42004318, 0x42003e41).
**A positive step count drives DIR high, a negative count DIR low.** Speeds are steps/s (interval = 1e6/speed us).
Bench says DIR2 low = outward, so A negative = outward, A positive = inward (bench fact, not from firmware).
Constants (model 3, section 3.3): 6400 steps per motor turn, gear 6, 38400 per arm turn, 160 steps/mm,
355 = full radius, 1600 = 32 x 50, 800 = 32 x 25, 133.33 = 800 / 6.

### 6.1 Machinery
- `startHoming()` = **0x420136a4**: init hardware once (guard `0x3fc9fcd2`), mode `0x3fca3378` = 3, **S (`0x3fca3360`) = 0**,
  call the model routine. Mode 3 means "homing": the main loop (0x42013fb9-0x42013fe5) then polls the state machine
  **0x4200b778** every pass for model 3 (proven).
- The model 3 move routine is **0x4200ae30**, reached through 0x4200b56c (0x4200b5e8). It acts on the current S once per call.
- State machine 0x4200b778 advances S when **both** steppers are idle (0x420098ec / 0x42009934 = "steps remaining" for
  B / A) except where noted. It calls 0x4200b56c on each change (then delay(10)).
- Drivers: GPIO34 and GPIO11 are written only in init (0x42009c9d, 0x42009ca4, 0x42009a38) and "drivers off" 0x420099f4
  (reached from the stop/sleep path 0x42015821, not from homing). **Nothing in homing touches the enables, so both drivers stay
  enabled (LOW) for the whole sequence; the arm is held, not free** (proven by absence of any digitalWrite in 0x4200ae30
  and 0x4200b778). Hardware init also runs at boot (0x4201bb1c) but boot does not start homing.
- No timeout: the start time stored in `0x3fca335c` (millis, at S0 and S2) is never compared in the model 3 path (its only
  readers are the Mini/model 2 code). No retry counter either (proven: no reference).

### 6.2 State by state (S = state value; moves are B arm / A radius)

| S | What is queued (address) | Ends when |
|---|---|---|
| 0, first pass (flag `0x3fc9fcd0` = 0) | A **-800** (DIR2 low = 5 mm outward) at 1600/s, B 0; store millis (0x4200b0c0-0x4200b102) | go to S1 at once |
| 0, retry (flag = 1) | A **+16000** (DIR2 high, 100 mm inward) at 1600/s, B 0; flag cleared (0x4200ae50-0x4200ae83) | go to S1 at once |
| 1 | nothing new | both idle, then S2 (0x4200b791) |
| 2 | store millis; **read GPIO21** (0x4200b117). If HIGH: B **+3840**, A **+640** (DIR13 high, DIR2 high; 36 deg of arm, radius held) at 800 / 133.3/s. If LOW: go straight to S3 (0x4200b126, 0x4200b1c4) | after the 36 deg move, both idle then S3 |
| 3 | B **-49920**, A **-8320** (DIR13 low, DIR2 low) at 800 / 133.3/s = 1.3 arm turns (468 deg) with radius held, 62.4 s (0x4200b1ca-0x4200b25f) | **GPIO21 reads non-zero (HIGH)**: both steppers stopped (0x4200986c, 0x420098ac), S4. If both finish without a HIGH: flag = 1, S = 0 (retry above) (0x4200b7aa-0x4200b7e1) |
| 4 | B **-5** steps at 800/s, A 0 (0x4200ae88-0x4200aef1) | both idle, then S5 |
| 5 | A **+62480** (= 1.1 x 355 x 160; DIR2 high, inward) at 800/s, B 0 (0x4200aef6-0x4200af38) | **GPIO21 reads anything but 1 (LOW)**: stop both, S6 (0x4200b800-0x4200b814). It never checks "idle", so if the pin stays HIGH the state just sits after the 78 s move |
| 6 | B **+384**, A **+64** (DIR high, high; 3.6 deg arm, radius held) at 800 / 133.3/s (0x4200af43-0x4200afc4) | both idle, then S7 |
| 7 | A **-160** (DIR2 low, 1 mm outward) at 800/s, B 0 (0x4200afcc-0x4200affd) | both idle, then S8 |
| 8 | if `armoffset` != 0 and flag `0x3fc9fcd1` = 0: B **-38400 x a/360**, A **-6400 x a/360** at 800 / 133.3/s (0x4200b008-0x4200b0b9); else S = 16 at once (0x4200b265) | both idle, then S16 |
| 16 | done (0x4200b853): see 6.4 | |

Proven facts: all the constants and addresses above. Inferred: that S2/S3 are "get off the sensor, then scan the arm for its
rising edge" and S5 is "drive the radius inward until the sensor falls", and that the sensor sits at the centre
of the table; the firmware does not say what GPIO21 is attached to.
The firmware expects GPIO21 **HIGH** at the S3 edge and LOW at the S5 edge. With GPIO21 stuck LOW (as on the bench)
it can never leave S3: every pass is -5 mm radius once, then loops forever: arm 1.3 turns, A +16000 (inward, into the
hard stop after a few passes where steps are lost), arm 1.3 turns, ... with the arm driver on (inferred from the retry branch, proven in code).

### 6.3 Other pins and who reads them
- **GPIO21 is read only in S3 and S5** (0x4200b7b0 and 0x4200b806, `digitalRead` through the pin number held in
  `0x3fc985a0`). The only other digitalRead calls in the whole image are the same state machine's twins for model 2
  (0x4200b894/0x4200b8d2, same pin variable) and the Mini (pin 13, 0x4200a5f7, 0x4200aa3f, 0x4200b971-0x4200ba50).
  No raw GPIO register read exists (the only GPIO-base literal is the Arduino core's 0x60004000 use). So **there is no slip or
  position check against GPIO21 while drawing** (proven; the state machine is only polled in mode 3).
- GPIO4: no reference at all. GPIO5: digitalWrite only (HIGH/LOW with the drivers). GPIO37: `pinMode(37, INPUT_PULLUP)`
  at 0x4201acf9 and nothing reads it (a button or leftover; proven absent from digitalRead). TMC DIAG/INDEX: never read.
  `pinMode(21, INPUT)` is at 0x4201b8c9: no pull-up, no pull-down set by the firmware (proven).

### 6.4 Triggers and what happens after homing
Homing runs only when `startHoming()` is called; **nothing calls it at power-on** (boot calls only the hardware init 0x420135dc
at 0x4201bb1c) and there is no timer (proven). Callers and the "post-homing action" word S2 (`0x3fca3364`) they set:
- **`HOME` command** (compare at 0x42018f5c, call at 0x42018c49): S2 = 3.
- **`CMDPLAY`** (0x42018f70-0x42018fa1): if mode `0x3fca3378` == 5 and the "already homed for this job" byte `0x3fca3368` is
  clear: S2 = 1 then startHoming; otherwise it just starts playing.
- **Job reader** (0x420138e8): at 0x4201386b-0x42013875 and 0x42013992-0x4201399d it sets S2 = 1 and homes; the second one when the
  job id string equals `"119"` (0x42013984). Other fixed ids "8574/8575/8576/117" are compared at 0x42013749-0x4201377e. Exact meaning of those ids unknown.
- **`PARK`** (0x4201a104 and 0x420146d9, answers `PARKED_OK`): sets flag `0x3fc9fcd1` = 1 (so S8 skips armoffset) and S2 = 6, then homes.
- A command at 0x42014549 (near the `FULLTEST`/LED strings, after reading `/ledoffset.txt`) homes with S2 = 5.
- On S = 16 (0x4200b585-0x4200b59b) the firmware **zeroes the current polar position variables** (`0x3fca2a00/04/08/0c` = 0.0) and
  the start time, then acts on S2 (0x4200b5a3-0x4200b6a8):
  - S2 = 3 (HOME) and any other value: homed byte `0x3fca3369` = 1, mode = 2, S = 0. **No further move.**
  - S2 = 1 (play): mode = 4, homed byte = 1.
  - S2 = 6 (PARK) with mode 3: arm **B -1608**, radius **A -268** (-15.08 deg of arm, radius held), at 800/s and 133.3/s
    (0x4200b60d-0x4200b69a), then mode 16.
  - S2 = 5 with mode 2: B **-9600**, A **-17600** (-90 deg of arm and 110 mm outward, A -16000 -1600 coupling) at 4800 / 800/s.
- So the logical origin (theta = 0, rho = 0) is the pose reached at S16: the point where GPIO21 fell LOW during S5, plus the
  fixed S6/S7 offsets (+384 B, +64 A, then A -160) and the `armoffset` move (B -38400a/360, A -6400a/360; a = 5 on this table, so -534 B, -89 A).
  There is no separate "park to centre" move in plain HOME: the ball is left at the origin. Whether that origin is the centre of the
  table is not in the firmware (inferred only if GPIO21's falling edge marks the centre).

### 6.5 Unproven
- What GPIO21's sensor is, and why it is stuck LOW on the bench (the code wants a HIGH to leave S3).
- Whether DIR high/low corresponds to your measured inward/outward in S3's coupled arm move: S3 moves arm DIR low and A DIR low, which
  in your measurement (arm low = inward, A low = outward) is exactly the radius-holding pair, so it is consistent.
- The "119" and other job ids, and who uses S2 = 5 (the LED-offset command path).
