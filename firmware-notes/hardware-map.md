# Hardware map (fw 3.16 disassembly) — for our-own-firmware route

All from the rebuilt ELF + objdump. Windowed-ABI call args land in a10+. Each
stepper is a small object in RAM holding its two pins as bytes: offset 0 = STEP,
offset 1 = DIR (proven from the pulse/dir code at 0x42003e00).

| GPIO | Role | Proven? |
|---|---|---|
| 1 | Stepper **A STEP** | pin proven |
| 2 | Stepper **A DIR** | proven |
| 14 | Stepper **B STEP** | proven |
| 13 | Stepper **B DIR** | proven |
| 11, 5, 34 | Driver **enable/sleep/reset** group (all driven LOW then HIGH together at motor init) | pins proven; which is which, inferred |
| 37 | Input, pull-up — home/limit switch or button | inferred |
| 48 | **WS2812 LED data**, driven over RMT, GRB order; count not in firmware | pin proven |
| 17 (TX) / 18 (RX) | UART1 @115200 (not the USB/CH340 port) | inferred |

- Two **independent polar axes** (arm rotation + radius), not coreXY. One axis is
  theta, the other rho; which is A vs B is not proven (bench test tells us).
- Microstepping is set by jumpers on the driver board, not firmware.
- No steps-per-rev constant survived (float radian math); measure it on the bench.
- Homing is soft: saved `armoffset` applied at boot, `PARKED_OK` from the park
  routine. GPIO37 is the only candidate real home switch.

**First bench experiment (de-risks everything):** drivers current-limited, arm/belt
disengaged, send ~200 slow STEP pulses on GPIO1 then GPIO14 one axis at a time,
toggling 11/5/34 to find which gates motion. Never drive both axes blind — wrong
pin or direction can run the arm into a hard stop.

This is enough to write a minimal firmware that accepts a `.thr` over the table's
own Wi-Fi and plays it, if we go the replacement-firmware route.

## LED ring — RESOLVED by probing (2026-11-19)

**43× WS2812 on GPIO38.** Found by driving every usable GPIO at once (ring lit),
then binary-searching with a parallel white/black driver. Disassembly's guesses
(GPIO48 = onboard status LED; GPIO34/14 = LED-init outputs) were all decoys. Pins
0 and 43 gave false "lit" readings from **crosstalk + the LEDs latching their last
value** — the fix was to drive a white set and a black set simultaneously so every
test is live, not a held state. Color order GRB, data 3.3V direct (no inverter,
no enable pin). Our firmware (`firmware/our-fw`) drives it cleanly via core RMT.

Lesson for the motors next: same method — drive/observe live, never trust a held
state, and the disassembly pin guesses need physical confirmation.

## Motors — DRV8833 PWM microstepping (firmware-derived 2026-11-19, bench-confirm before trusting)

Two DRV8833 dual H-bridges (U2, U4), each driving one bipolar stepper with 4 PWM
inputs. From the LEDC init at app0 0x42009a7c (verified HAL arg order), all 8 inputs
are 20 kHz, 10-bit PWM, driven with sine/cosine duties (current-control microstepping):

| Motor | Role | Coil A pins | Coil B pins |
|---|---|---|---|
| A (motor 0, set up first) | **J7_A1** = main arm / theta | GPIO7, GPIO8 | GPIO9, GPIO10 |
| B (motor 1) | **J7_A2** = second motor / rho | GPIO1, GPIO2 | GPIO3, GPIO4 |

- To drive: PWM each input 0-1023 at 20 kHz; coil current = sin/cos of the microstep
  phase. Coil-to-silkscreen pairing is inferred — confirm on the bench.
- **Likely nSLEEP/enable: GPIO34 and GPIO14** (two outputs held LOW at boot in the
  motor init, 0x42009c33). Drive HIGH to wake the drivers — or nSLEEP may be tied
  high in hardware (then they're something else). Unconfirmed.
- **Home/endstop inputs: GPIO5** (reliable) and GPIO11 (ambiguous, also an output).
  `/armoffset.txt` holds the arm home offset; HOME handler at 0x42018f5c.
- Param constant 40 stored at [0x3fc984d0] (0x4201361d) — possible microstep/speed, unconfirmed.

**Safe bring-up order (all watched, arm free, sand out):** wake enables; apply ONE
coil a LOW holding duty (~20%) and confirm the motor just detents/holds (does NOT
spin); identify which GPIO pair is which motor; then a slow single-microstep ramp;
measure steps/rev; only then play a .thr. Wrong coil pairing or direction can drive
the arm into a hard stop — never energize a full step sequence blind.

## Motors — RESOLVED EMPIRICALLY (2026-11-19 night). Disassembly pin guesses were WRONG.

Found by: buzz-sweep (all 8 pins are coil inputs) -> rotation config sweep -> long-step
confirmation. **Drive each coil input as plain digitalWrite (full on/off), NOT ledcWrite
PWM — the LEDC/PWM path is silently broken on these pins and produces no output.**

- **8 coil inputs**: GPIO 1,2,3,4,7,8,9,10 (all confirmed by audible buzz).
- **Enables (nSLEEP), hold HIGH**: GPIO 34 and 14. (No boost converter — U1 is just an
  AMS1117 3.3V LDO; motors run on USB 5V. U9=CH340, U3=ESP32.)
- **Motor 1** = pins **1,2,3,4**, coil pairing **[1,2]+[3,4]** (sequence order 1,2,3,4).
  Rotates the ball around an arc (theta-ish). ~1500 full steps ≈ 45° of ball travel,
  so ≈ 12,000 steps per full circle — heavily geared.
- **Motor 2** = pins **7,8,9,10**, pairing **[7,8]+[9,10]** (order 7,8,9,10). Moves the
  ball along the arm at an angle (rho-ish). ~1500 steps ≈ 1".
- Full-step 2-phase-on sequence {1010,0110,0101,1010...}: SEQ[4][4]=
  {{1,0,1,0},{0,1,1,0},{0,1,0,1},{1,0,0,1}} applied to the 4 pins in order.
- Step rate: ms=9-12/step worked (slower if it skips). Needs an accel ramp + microstepping
  for smooth/fast motion later (stock does sine/cos microstepping).
- **Exact kinematics (which is pure theta vs rho, and any coupling) still need calibration**
  — both motors move the ball at angles, typical of a coupled polar/arm mechanism.
- Home/endstop inputs: GPIO 5, 11 (unconfirmed which axis).
