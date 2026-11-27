# 36-inch table: motor qualification (November 22, 2026, 6:00-6:50 pm Pacific)

Bare tray, ball only, both drivers at the factory current (IRUN 17, IHOLD 8, about 1 A), StealthChop, 32 microsteps.
Everything here was measured on the table with the USB camera (index 1) and the firmware's own logs unless marked
otherwise. Raw logs: `captures/big-qual/*.jsonl` and `*.out` (gitignored). Scripts: `tools/big_lib.py`,
`big_q1_sensor.py`, `big_q2_circles.py`, `big_q2_fit.py`, `big_q3.py`, `big_flash.sh`.

Before this run a second chat session had flashed an uncommitted bench firmware 0.4 (homing, forward-only slip check,
a `/homeradius` that pushed 1,600 steps into the centre stop) and left the table homed at carriage 32,000. Its
calibration file was replaced here; its firmware was reviewed and reworked into 0.5 and 0.6.

## 1. Arm home sensor (GPIO21)

14 full turns, both directions, at 2,000 to 8,000 steps/s and carriage radii 75, 187, 200 and 300 mm.

| Edge | Arm counter (0..38,399), forward homing zero | Spread |
|---|---|---|
| Rising, arm forward (DIR13 low) | 3 to 12 | within 2 steps at one radius and speed |
| Falling, arm forward | 832 to 845 | same |
| Rising, arm backward | 805 to 812 | same |
| Falling, arm backward | 38,370 to 38,378 (-22 to -30) | same |

- The sensor is high for about 835 steps (7.8 degrees) per turn. Direction hysteresis is about 32 steps (0.3 degrees).
- The edges move a few steps later as the carriage goes out (rising edge 3 at 75 mm, 5 at 187 mm, 12 at 300 mm).
- One step is 0.0094 degrees, so a slip of one full motor step (32 microsteps) is visible on the next pass.
- The ball returned to its start within 1 px after every forward turn and within 2 px after a reversal.
- Firmware rule: the rising edge is expected at 6 going forward and 808 going backward, tolerance 64 steps.

## 2. Camera calibration (`firmware-notes/big-camera-calibration.json`)

51 stops on three circles (carriage 12,000, 30,000 and 48,000 steps, 16 stops each, radius held with the 1/6
compensation) plus a radial line out and back. Model: ball at rho (cos th, sin th), rho = r - c a + rho0, th = 2 pi a / 38,400,
seen through a plane homography. Fit: 1.32 px rms, 2.8 px worst (about 1.5 mm rms on the tray).

- **Coupling:** fitted free, c = 1/6.04 with standard error 0.13 on the 6, so the factory's 1/6 holds. A wrong ratio
  would turn the circles into spirals; they close within the camera noise.
- **Rotation centre against the centre stop:** the ball's camera position at the inner stop (recorded at 4:30 pm) maps to
  1.3 mm from the fitted rotation centre, inside the camera noise. The stop is at the centre to within about 1.5 mm.
  The previous session's carriage zero was 157 steps (1 mm, standard error 0.5 mm) outside the rotation centre; the
  carriage counter is now set from the camera (`/setcarriage`), so carriage = distance from the rotation centre.
- **Steps per mm:** not measurable from the camera without a known length on the tray. The factory constant is 160
  (6,400 steps per motor turn, 40 mm per turn). The lit rim maps to a radius of about 394 mm at 160 steps/mm, but the
  rim edge in the picture is too soft (sd 21 mm) to check the constant. A tape measurement would settle it.
- **Radial backlash or ball lag:** arriving at the same carriage position from outside and from inside leaves the ball
  about 300 to 450 steps (2 to 3 mm) apart on the bare tray. Arm reversals show about 1 px.
- The lit rim's centre is not the rotation centre in this fit (46 mm away); the rim outline is the LED glow, not the tray.

## 3. Speed and acceleration (quiet window 6:29-6:42 pm)

Out-and-back moves, camera check after each; arm moves also checked on the home sensor.

| Motor | Speed, steps/s (acceleration 8,000) | Acceleration, steps/s^2 |
|---|---|---|
| Radius | no loss at 4,000 to 16,000 (firmware ceiling, 100 mm/s), 30,000-step moves | no loss at 20,000 to 400,000 (ceiling), 8,000 steps/s |
| Arm, carriage 12,000 (75 mm) | no loss at 4,000 to 16,000 | fine to 100,000; **stalled at 200,000** (8,000 steps/s) |
| Arm, carriage 44,000 (275 mm) | no loss at 3,000 to 6,000 (ball 270 mm/s; not taken higher) | fine at 20,000; **stalled at 50,000** (4,000 steps/s) |

- Both arm stalls were complete (the arm moved about 140 of 9,600 steps). With the arm stalled, the radius
  compensation still ran, so the carriage moved 1,560 steps (10 mm) outward. `/homearm` then found the sensor,
  corrected the arm counter by -9,465 and -9,353 steps, and the carriage estimate that follows from it matched the
  camera within 250 steps.
- **Limits now in the firmware:** radius 8,000 steps/s and 100,000 steps/s^2; arm 8,000 steps/s and 10,000 steps/s^2
  (half the acceleration that passed far out, one fifth of the one that stalled).
- Start speed is 100 steps/s in every move.

## 4. StallGuard (SG_RESULT, register 0x41), sampled about 50 times a second during moves

Free-running median at cruise, both motors alike with the carriage near the centre:

| steps/s | 1,000 | 2,000 | 3,000 | 4,000 | 6,000 | 8,000 | 12,000 | 16,000 |
|---|---|---|---|---|---|---|---|---|
| SG_RESULT | 38 | 96 | 120 | 150 | 207 | 247 | 290 | 325 |

- The arm reads about 13% lower with the carriage at 44,000 steps (108 at 3,000, 136 at 4,000, 176 at 6,000).
- **Both drivers report about 2 for part of every electrical cycle even when free** (phase-locked to the 128-microstep
  cycle), so single low readings mean nothing. Back-to-back reads of the two drivers failed or returned junk; a 2 ms
  gap before each read fixed that.
- The two real arm stalls read 166 to 194 at 8,000 steps/s (73% of free) and 68 to 102 at 4,000 steps/s far out (63%).
  So a stalled motor reads clearly lower, not zero.
- **Alarm rule in the firmware:** at cruise speed of 3,000 steps/s or more, six readings in a row (blanks of 4 or less
  skipped) under 82% of the free value for that speed (arm: scaled for carriage radius) stop the move: fault 2 radius,
  fault 3 arm. Checked against the recordings of the two real stalls (every reading under the line) and against 22
  normal moves at 3,000 to 8,000 steps/s (no trip, lowest normal reading 12% above the line). It has not been
  triggered live, and the radius motor has never stalled, so its stall reading is assumed to be like the arm's.
- **Below about 3,000 steps/s the alarm is blind** (readings too small and noisy). At drawing speeds the protection is
  the per-turn sensor check on the arm and the hard radius limits.
- Microphone: the recording (11 minutes) ended before the two stalls, and the three bangs it flagged do not line up
  with any stall. Nothing learned from sound.

## 5. Guards in bench firmware 0.6

- Arm slip check on every pass of the sensor, both directions; more than 64 steps off stops the move (fault 1).
  `/homearm` afterwards snaps the arm counter to the nearest matching turn and keeps the radius counter, which repairs
  the carriage estimate as long as less than a quarter turn was lost.
- Stall alarm as above (`/guard`), on by default.
- Radius limits: once the carriage position is known, a move ending outside 800 to 56,800 carriage steps (5 to 355 mm
  from the rotation centre) is refused. Before that, one move may shift the carriage 8,000 steps at most.
- Speed and acceleration cut to the limits above unless `&raw=1`.
- `/homeradius` no longer pushes into the stop. A StallGuard-guarded version is in the code but untested; the carriage
  position currently comes from the camera (`/setcarriage`). **There is still no camera-free radius home.** The factory
  firmware homes the radius by driving inward until GPIO21 goes low (section 6 of `big-table-factory.md`), which
  suggests the arm sensor also sees the carriage near the centre; that is the next thing to test.
- `tools/big_flash.sh` updates over Wi-Fi and keeps position: counters saved and restored, arm re-homed on the sensor.
