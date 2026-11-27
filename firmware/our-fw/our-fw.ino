/* Oasis Mini - our own firmware, drawing engine v6 (ESP32-S3, Arduino-ESP32 core 3.1.3).
 *
 * WHAT CHANGED IN v6 (2026-11-20): positions are kept in 1/16 full steps ("ticks") so the coils can be driven with
 *   smooth sine currents (drive=sine, PWM) as well as full or half steps; a look-ahead speed planner replaces the
 *   old "restart slow on every reversal" ramp; the web server runs on core 0 so the motion task owns core 1 and
 *   steps with no pauses; the position and calibration survive a reboot (NVS); input pins can be watched to find the
 *   home sensors (/inputs); the ring can follow the ball (/led?mode=follow); /home is generic (direction, steps).
 *   Everything the web API takes or reports is still in FULL STEPS (cur1/cur2 may now have a fraction).
 *
 * MECHANISM (worked out 2026-11-20 with camera + microphone; README "THE CATCH"). Two-link folding arm, link length
 *   L, elbow angle e. Motor 2 turns the main arm (one turn = about 10237 steps; GPIO13 goes high for about 178 steps
 *   once per turn = the arm's home sensor). Motor 1 turns the elbow, and the elbow can go round and round. Near the
 *   folded position there is a ONE-WAY CATCH at e = 0.336 (mod 2*pi): turning the elbow toward smaller e stops dead
 *   on it (ball 0.15 R from the centre); turning toward larger e the arm can be forced THROUGH it, which is the loud
 *   snap Bill heard and must never be done. Legal travel: e from 0.336 (home stop) out to pi (rim) and on to 2*pi
 *   (exact centre, reached from the rim side). We draw on e in [pi, 2*pi]; e > 2*pi is forbidden.
 * KINEMATICS:
 *       e   = EF - B1*m1 + B2*(m2 - M2H)             elbow angle, rad (m1 = 0 on the home stop, e = EF = 0.336 there;
 *                                                    m1 goes NEGATIVE toward the rim and the centre, centre about -9760)
 *       r   = 2*L*sin(e/2)                           distance from the rotation centre C, sand radii
 *       phi = PHI0 + A*m2 + A1*m1 + K*M2H            ball angle about C (A = G - B2/2, A1 = B1/2, K = B2/2)
 *   Polar target (theta rad cumulative, rho 0..1): phi = theta + TH0, r = rho*RMAX, e = 2*pi - 2*asin(r/(2L)).
 *   M2H = m2 at the moment the elbow was homed. All constants: /cal, saved with /cal?save=1.
 *   Polar jobs refuse until homed (unhomed=1 overrides). /raw is never limited: keep m1 above m1_centre.
 * HOMING (/home): m1 positive into the stop (stalls quietly in sine drive), m1 = 0, back off 400 steps; then m2
 *   positive until GPIO13 rises, m2 = IDX there. theta is then absolute with no camera. If the position is already
 *   known the elbow only travels as far as it needs.
 * SLIP GUARD: every time the arm passes its sensor going forward, /status idx_err = how many m2 steps the count is
 *   off (idx_n = passes seen). While homed, a job is aborted (coils off, homed = 0, /status fault) if that error exceeds
 *   60 steps (fault 1, motor 2 slipped) or the sensor is not seen for 1.3 turns of m2 travel (fault 2, motor 2 stalled).
 *   This matters: with one motor stalled the other keeps going and can drive the arm into the catch. /home clears it.
 *   /raw?guard=0 switches it off for one move. Motor 1 has no sensor: keep speed and torque conservative.
 * BACKLASH: bl1/bl2 steps of slack are taken up alongside the move whenever a motor reverses (/cfg?bl1=&bl2=).
 *
 * HARDWARE (measured, firmware-notes/hardware-map.md): Motor1 = GPIO 1,2,3,4 [1,2|3,4]; Motor2 = GPIO 7,8,9,10
 *   [7,8|9,10]; DRV8833 H-bridges, nSLEEP = GPIO34 + GPIO14 held HIGH. LED ring = 43x WS2812 on GPIO38 (GRB) via the
 *   core's rmtInit/rmtWrite (FastLED / NeoPixel clash with this core's RMT driver; do not add them).
 *
 * DRIVE MODES (/cfg?drive=full|half|sine): full = 2-phase-on full steps, half = half steps, both with digitalWrite.
 *   sine = 20 kHz 10-bit LEDC PWM on all 8 coil pins, coil currents AMP*cos / AMP*sin clipped at 1 (amp 1 = pure
 *   sine, 1.41 = same peak torque as full step); decay=1 slow decay (other input held high), decay=0 fast decay.
 *   An integer full-step position energises the same coil state in every mode, so switching does not move the ball.
 *
 * SPEED PLANNER (all in full steps of the faster motor): VMAX top speed (steps/s), VJ = speed change one motor may
 *   take in a single instant (also the start/stop speed), ACC = acceleration (steps/s^2), ACCC = acceleration allowed
 *   round a smooth bend. 128 points of look-ahead: it slows for a corner before it reaches it and no longer drops to
 *   the start speed when the slower motor merely changes direction. /cfg?vmax=&vj=&acc=&accc= (legacy: min= us per
 *   step sets VMAX, start= sets VJ). Old limits for full steps: VMAX 400 (2500 us), VJ 200 (5000 us).
 *
 * TASKS: motion (core 1, prio 2, busy-waits between ticks), web server (core 0, prio 2), LED ring (core 0, prio 3,
 *   500 frames/s output, scene worked out 100 times a second).
 *   Coils are released on /stop and after 1 s idle. Position is written to flash 3 s after a job ends; a reboot in
 *   the middle of a job comes back with homed = 0.
 *
 * ENDPOINTS (GET unless noted; motion jobs accept force=1 to replace a running job, else 409 when busy):
 *   /                      small control page
 *   /status                JSON: state (idle|moving|drawing|stopping), job, progress, index/total, cur1, cur2 (full
 *                          steps), theta, rho, e, r, speed (steps/s now), drive, homed, planner and model constants
 *   /stop  /off            stop now, coils off
 *   /zero[?m=1|2]          zero both (or one) counter; clears homed
 *   /set?m1=&m2=&homed=    declare the counters (full steps) without moving (idle only)
 *   /cal?l=&ef=&b1=&b2=&phi0=&a=&a1=&k=&rmax=&th0=&m2h=&idx=&home=&save=1   model constants (idle only)
 *   /home[?steps=N&full=1&us=U&elbow=0&index=0]   home the elbow on its stop (m1 +N steps, default: as far as needed), then
 *                          the arm on its sensor. elbow=0 / index=0 skip a stage. /status home_err: 1 = sensor never
 *                          seen, 2 = sensor stuck high
 *   /cfg?drive=&amp=&decay=&vmax=&vj=&acc=&accc=&bl1=&bl2=&start=&min=&half=   drive mode, planner, backlash steps
 *   /goto?th=<rad>&rho=<0..1>         straight coordinated move to a polar point
 *   /raw?m1=&m2=[&us=U]               straight move to absolute motor steps, optional speed cap for this move
 *   /circle?rho=0.7&turns=1   /spiral?loops=4&dir=out|in   /rose?k=5   /clear
 *   Every polar job starts from the arm's present angle: whole turns are added to its thetas so it never unwinds
 *   the turns left by the previous drawing.
 *   /gen?kind=random|bloom|vortex|weave|arms|super|ripple|lotus|erase_out|erase_in&n=&d=&g=&T=&w=&q=&e=&pitch=
 *                          draw one generative piece computed on the table (formulas: tools/gen.py). Pieces run rim ->
 *                          centre; erase_out runs centre -> rim (pitch 0.035 by default). /status gen = what it is.
 *   /auto?on=1|0&hold=600&boot=0|1   the table on its own: erase outward, random piece inward, leave it on show for
 *                          `hold` seconds, repeat. Needs homed. Any /stop, fault or abort turns it off. boot=1 (saved):
 *                          20 s after power-up it homes fully and starts auto by itself; /stop in that time cancels.
 *   STORED DRAWINGS (v8, LittleFS on the 11 MB "spiffs" partition; tools/sync_table.py fills it over Wi-Fi):
 *     /lib/<name>.pat (float32 theta, float32 rho per point, little-endian, max 12000 points), /lib/<name>.jpg
 *     thumbnail, /lib/index.json list, /www/index.html the control page (served at "/"; "/basic" = built-in page).
 *   /patterns              the list (/lib/index.json)
 *   /draw?spec=<description>   same, for a self-made design by the text /status shows in `now` ("bloom n=7 d=0.34 ...")
 *   /fav                   favourites (JSON array of such descriptions); /fav?add=now|<description>, /fav?del=<description>
 *   /smooth                queue: check, erase out, erase in (levels the sand)
 *   The table also answers at http://oasis.local (mDNS). /led?drift=1: the light colour wanders slowly.
 *   /draw?name=<n>[&erase=0][&now=1]   queue a stored drawing. By default the table first re-homes its elbow (if
 *                          rehome is on), erases toward the drawing's starting point, then draws. now=1 replaces
 *                          whatever is running or waiting. The queue holds 12 steps. /queue?clear=1 empties it.
 *     OUTSIDE-IN ERASE (v8.11): if /lib/<name>.bg.pat exists (tools/sync_table.py makes one for each hand-made picture:
 *                          it erases only the sand the picture will not cover, rim inward, and ends on the picture's
 *                          first point), the erase step plays that file instead of the spiral (same speed as drawings;
 *                          /status now = "erase <name>"), reached by going straight out to the rim at the ball's angle
 *                          and then along the rim. The picture after it is always played forwards. A missing, oversized
 *                          or mismatched file falls back to the spiral erase. Auto mode's stored drawings do the same.
 *                          <name>.bg.pat is never offered as a drawing. erase=0 / erase_first=0: unchanged.
 *   POST /fs               store a file: raw body, headers X-Path: /lib/x.pat and X-Key: K. GET /fs lists files and free
 *                          space; GET /fs?del=<path>&key=K deletes.
 *   POST /update           firmware update over Wi-Fi: raw body = the .bin, header X-Key: K. Only when idle. Restarts, and does not
 *                          start by itself on that one restart. K is ADMIN_KEY in wifi_creds.h.
 *   THE BUTTON (GPIO37, low while pressed): one press pauses the running job where it is, the next carries on.
 *     While idle a press starts drawing by itself (homing first if it has to), or stops that if it is waiting
 *     between pieces. The ring flashes once to acknowledge. /pause?on=1|0 does the same from the page; /status paused.
 *   ERASE FIRST OR NOT (/cfg?erase_first=0|1, default 1): with 0 a new drawing goes on top of the last.
 *     It is then started from whichever of its ends is nearer the ball (self-made pieces are drawn outward when the
 *     ball is at the centre), so no travel line crosses the sand. /draw?erase=1|0 overrides it for one drawing.
 *     The self-check goes with an erase; without erasing it is forced after 10 drawings (/status unchecked).
 *   SELF-CHECK WITHOUT A CAMERA: before every erase the sequencer re-homes the elbow on its stop ("check" in the
 *     queue, about 50 s with the trip back). Motor 2 is checked every turn by the arm sensor. /cfg?rehome=0 turns it off.
 *   /cfg?turn=<deg> or down=<deg>: which side of the table is the bottom of a picture (saved; only while idle). The ring
 *     shows a bright marker there for 7 s (/cfg?mark=1 shows it again). /auto?mix=0|1|2: auto mode draws its own
 *     designs, stored drawings, or both (default).
 *   /cfg?epitch=0.012..0.06: ring spacing of the erase in front of a stored picture (default 0.02 = flat background,
 *     about 17 min; self-made pieces keep 0.035). Outside-in erase files (<name>.bg.pat, v8.11) are no longer synced.
 *   /cfg also takes verase= (erase speed, default 500 steps/s), quiet_on=, quiet_from=, quiet_to= (minutes after
 *     midnight, Pacific; clock from NTP): in quiet hours auto mode starts no new piece and the ring is capped dim.
 *   /status adds now, queue, eta_s, time, quiet, quiet_on/from/to, rehome, verase, fs, fs_free.
 *   /guest-state           {rev,known,pending,slots}: one revision shared by every phone, reset to unknown on reboot.
 *   POST /guest-evolve    on=1, rev=current, a/b/c=comma-separated catalog subjects per slot, hold=seconds (default 300).
 *                         on=0 disarms future edits. The table holds a finished picture, then erases uniformly and redraws
 *                         the three places with one subject changed, respecting quiet hours. Any guest upload or other motion ends that schedule.
 *   POST /guest-draw       little-endian float32 theta/rho pairs, up to 12000 per subject. X-Guest-Mode=fresh/edit/photo,
 *                         X-Guest-Rev and X-Guest-Slots (3 comma-separated slugs). For fresh/edit, X-Guest-Counts gives
 *                         three raw point counts. Fresh concatenates independent slot paths in order; an edit supplies
 *                         just its changed slot. Replacing clears and redraws the complete scene. An empty place can
 *                         be filled without clearing when the ball is at the rim and the position check is current.
 *   /guest-part?slot=&rev=  read the stored binary route for a known current slot. The firmware keeps the source
 *                         routes including sketches and photos, so any phone can preview or request the next change.
 *   POST /thr              body: lines "theta rho" (theta rad cumulative, rho 0..1; '#' lines ignored; max 12000)
 *   /play[?loop=1]         play the stored pattern; loop = forward/reverse forever
 *   Optional shared-gallery playback: POST /thr with X-Oasis-Run (64 hex digits) and X-Guest-Rev, then
 *   POST /play with the same X-Oasis-Run. /status.receipt identifies staged, running, complete or failed.
 *   Tagged playback starts where the ball is, once, forward. A reboot or other motion retires the receipt.
 *   /led?mode=auto|show|follow|solid|arc|off|comet|breathe|progress|idx|aurora|breath|fireflies&c=RRGGBB&b=0..255&i=0..42&aw=<leds>&led0=<deg>&base=0..1&w=<deg>
 *                          auto (default): follow while drawing, dim while erasing, show light while resting, slow pulse
 *                          when paused, red pulse on a fault, white sweep while finding home. show: warm light from one
 *                          side with a cool fill opposite (c2=RRGGBB), circling once per period= seconds (240).
 *                          v8.10: the ring sends 500 frames/s (hz=55..500 changes it); every change goes through a
 *                          two-stage soft fade (0.18 s each, up to 0.6 s for 2.5 s after the scene changes, so scenes
 *                          dissolve); brightness changes glide (about 1 s); output = level squared (eye-corrected), then
 *                          FAST temporal dither (dith=0..4, most bits, default 3; 0 = none as in v8.5 to v8.9): its
 *                          pattern repeats at least 125 times/s from 1 to 4 output steps, 62 below 1 and up to 16, 31 above; frames are
 *                          not sent while flash is written. Capped at ma= milliamps (1000). The button flash is a soft
 *                          swell (flash=1 shows it). warm=1 (default): through the evening the light also turns warmer.
 *                          trail=1 (default): while drawing, a soft glow lingers for about 25 s where the ball has been.
 *                          mode=fireflies: a few soft lights slowly swell and fade at random places (rest=2 makes
 *                          Automatic use it while resting).
 *                          Copied from the stock app's list (firmware-notes/stock/): mode=aurora (slow colour waves; rest=1
 *                          makes Automatic use it while resting), mode=breath (4-7-8 breathing guide), a two-tone follow
 *                          light, fill=1 (the ring fills as the piece progresses), speed=0.25..4 for the moving lights.
 *                          mood=1: each piece gets its own colour. evening=1 (default):
 *                          the ring dims from 7pm to 35% by 10pm, and comes back up from 6am to 8am. lin=1&tmp=1: raw linear light for the camera tools, not
 *                          saved; restore=1 gives the ring back (mode, colour, brightness, drift, mood, rest, fill, evening,
 *                          warm, trail, period, speed, c2). The owner's light choice is kept across restarts.
 *   /ledlog?stats=1[&reset=1]   frame-interval statistics of the light since boot (or the last reset)
 *   /ledlog?n=N&leds=a,b,..&k=K   record N records of up to 8 LEDs (K frames summed per record); GET /ledlog returns
 *                          them (binary, read by tools/led_smooth.py); /ledlog?n=0 frees the memory
 *                          arc: LEDs within aw of LED i lit (light from one side, shows the grooves in relief).
 *                          follow: a glow on the rim next to the ball, spreading round the ring as the ball nears the
 *                          centre. led0 = theta (deg) at which LED 0 sits; LEDs run clockwise (theta decreasing).
 *   /inputs[?clear=1&pull=up|down|none]   levels of the watched input pins and the last pin changes with the motor
 *                          positions at which they happened (for finding home sensors and the button)
 *   /gpio?pin=N&out=0|1    drive one of the spare pins (experiments only);  /gpio?pin=N&in=1 back to input
 */
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <LittleFS.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <time.h>
#include <math.h>
#include "esp_crc.h"
#include "mbedtls/sha256.h"
#include "soc/gpio_reg.h"
#include "wifi_creds.h"

#define FW_NAME "v8.17"
#define TPS 16                         // ticks per full step

WebServer server(80);
Preferences prefs;

// types first: Arduino auto-prototypes are inserted before the first function
enum JobType { JT_POLAR, JT_RAW, JT_CIRCLE, JT_SPIRAL, JT_ROSE, JT_CLEAR, JT_PLAY, JT_HOME, JT_GEN };
// Generative pieces (same formulas as tools/gen.py): an inward spiral from the rim to the centre with a modulated
// outline, or a plain erase spiral.
enum { GK_BLOOM = 0, GK_VORTEX, GK_WEAVE, GK_ERASE_OUT, GK_ERASE_IN, GK_ARMS, GK_SUPER, GK_RIPPLE, GK_LOTUS };
struct GenP { uint8_t kind; int n, q; float d, g, T, w, e; };
#define GEN_PPT 360
struct Job { uint8_t type; const char* name; float a, b; long l1, l2, l3; float vmax; bool loop, noguard, rev, tagged; GenP g; };
enum { ST_IDLE = 0, ST_MOVING, ST_DRAWING };
enum { SK_REHOME = 0, SK_GEN, SK_FILE, SK_BG, SK_GUEST };   // SK_BG (v8.11): play /lib/<name>.bg.pat as the erase; g = the spiral erase to use if it is unusable
struct Step { uint8_t kind, piece, fwd, guest, guestSlot, guestLast; GenP g; char name[28]; };   // sequencer step; piece = 1: a finished drawing (start the on-show hold after it); fwd = 1: play a stored drawing first point first
struct Seg { long t1, t2; double x1, x2; float len, u1, u2, fj2, vexit2, vcap; long k; };   // vcap: speed cap for this segment (0 = none)
struct Ev { uint32_t ms; uint8_t pin, level; long c1, c2; };

// ---------------------------------------------------------------- motor hardware
const int SEQ4[4][4] = {{1,0,1,0},{0,1,1,0},{0,1,0,1},{1,0,0,1}};
const int SEQ8[8][4] = {{1,0,0,0},{1,0,1,0},{0,0,1,0},{0,1,1,0},{0,1,0,0},{0,1,0,1},{0,0,0,1},{1,0,0,1}};
const int MP[2][4] = {{1,2,3,4}, {7,8,9,10}};

volatile long c1 = 0, c2 = 0;          // position in ticks (1/16 full step)
volatile int drive = 0;                // 0 full, 1 half, 2 sine (PWM)
volatile int ph[2] = {0, 0};           // coil phase offset per motor (ticks): phase = counter + ph, so counters can be redefined without a jump
volatile float AMP = 1.41f;
volatile int decay = 1;
bool pwmOn = false;
float cosT[64];
int lastDuty[2][4];
// calibrated model, full-step units (compiled defaults = rough far-branch probe values)
volatile double GL = 0.465, GEF = 0.336, GB1 = 6.09e-4, GB2 = 1.10e-4, PHI0 = 2.10303, GA = 5.59e-4, GA1 = 3.045e-4, GK = 5.5e-5;
volatile double RMAX = 0.88, EMARG = 0.05, TH0 = 0.0;
volatile double M2H = 0;               // m2 (full steps) at the moment the elbow was homed on its stop
volatile long HOME_STEPS = 10700;      // m1 POSITIVE drive that reaches the home stop from anywhere (full elbow turn is about 10320)
volatile double IDX_M2 = 0;            // value given to m2 at the rising edge of the arm sensor (GPIO13), approached with m2 increasing
volatile int homeErr = 0;              // 0 ok, 1 arm sensor never seen, 2 arm sensor stuck high
#define IDX_PIN 13
#define HOME_BACK 400                  // steps the elbow backs off its stop after homing
// backlash take-up: physical position = logical position + lashOff; lashOff swings to +-BL/2 with the direction of travel
volatile int BLT[2] = {33 * TPS, 56 * TPS};
volatile long lashOff[2] = {0, 0};
int lashTgt[2] = {0, 0}, lastDir[2] = {0, 0};
float lashAcc[2] = {0, 0};
volatile bool idxStop = false, idxHit = false;
volatile float idxErr = 0; volatile long idxN = 0;   // last arm-sensor pass (m2 rising): steps away from where it should be
volatile long idxPassC2 = 0;           // m2 (ticks) at the last change of the arm sensor
volatile long idxAcceptC2 = -100000000L; // m2 (ticks) at the last rising edge that was checked
volatile int fault = 0;                // 1 = motor 2 slipped (sensor seen in the wrong place), 2 = motor 2 stalled (sensor not seen for 1.3 turns)
volatile bool guardOn = false; long guardTicks = 0;
#define IDX_TOL 60.0                   // steps
volatile int homed = 0;
// planner, full steps
volatile float VMAX = 400, VJ = 200, ACC = 200, ACCC = 2000;
const float VMINF = 40;
volatile float curV = 0;               // current speed, full steps/s
bool energised = false;
volatile uint32_t lastMoveMs = 0;
volatile bool posDirty = false, posSavedOk = false;

void pwmAttach(bool on) {
  if (on == pwmOn) return;
  for (int m = 0; m < 2; m++) for (int i = 0; i < 4; i++) {
    int p = MP[m][i];
    if (on) { ledcAttach(p, 20000, 10); ledcWrite(p, 0); }
    else { ledcDetach(p); pinMode(p, OUTPUT); digitalWrite(p, LOW); }
    lastDuty[m][i] = 0;
  }
  pwmOn = on;
}
inline void setDuty(int m, int i, int d) {
  if (lastDuty[m][i] != d) { lastDuty[m][i] = d; ledcWrite(MP[m][i], d); }
}
inline void coil(int m, int ci, float v) {            // coil ci (0: pins 0,1; 1: pins 2,3), v in -1..1
  if (v > 1) v = 1; if (v < -1) v = -1;
  int d = (int)(fabsf(v) * 1023.0f + 0.5f), pp = 2 * ci, pn = 2 * ci + 1;
  if (v < 0) { int t = pp; pp = pn; pn = t; }
  if (decay) { setDuty(m, pp, 1023); setDuty(m, pn, 1023 - d); }
  else       { setDuty(m, pn, 0);    setDuty(m, pp, d); }
}
inline void applyM(int m, long c) {
  c += ph[m] + lashOff[m];
  if (drive == 2) {
    int p = (int)(((c + 8) % 64 + 64) % 64);
    float amp = AMP;
    coil(m, 0, amp * cosT[p]); coil(m, 1, amp * cosT[(p + 48) & 63]);
  } else {
    const int* s;
    if (drive == 1) { int q = (int)(((c + 4) % 64 + 64) % 64); s = SEQ8[(q / 8 + 1) & 7]; }
    else            { int q = (int)(((c + 8) % 64 + 64) % 64); s = SEQ4[q / 16]; }
    for (int i = 0; i < 4; i++) digitalWrite(MP[m][i], s[i]);
  }
}
void setC(int m, long nc) {            // redefine a counter (ticks) without changing the energised coil phase
  long oc = m ? c2 : c1;
  ph[m] = (int)((((oc + ph[m] - nc) % 64) + 64) % 64);
  if (m) { idxPassC2 += nc - oc; idxAcceptC2 += nc - oc; c2 = nc; } else c1 = nc;
}
void coilsOff() {
  for (int m = 0; m < 2; m++) for (int i = 0; i < 4; i++) {
    if (pwmOn) { ledcWrite(MP[m][i], 0); lastDuty[m][i] = 0; } else digitalWrite(MP[m][i], LOW);
  }
  energised = false;
}
void setDrive(int d) {                 // idle only
  coilsOff();
  pwmAttach(d == 2);
  drive = d;
}

// ---------------------------------------------------------------- input watcher
const uint8_t WPINS[] = {0, 5, 6, 11, 12, 13, 15, 16, 17, 18, 21, 35, 36, 37, 39, 40, 41, 42, 45, 46, 47, 48};
#define NW (sizeof(WPINS))
#define NEV 48
Ev evs[NEV]; volatile int evHead = 0; volatile long evTotal = 0;
volatile uint32_t wLast0 = 0, wLast1 = 0; uint32_t wMask0 = 0, wMask1 = 0;
long wCount[NW];
uint8_t outPin[NW];                    // 1 = switched to output by /gpio
portMUX_TYPE evMux = portMUX_INITIALIZER_UNLOCKED;

void watchInit(int pull) {
  wMask0 = wMask1 = 0;
  for (unsigned i = 0; i < NW; i++) {
    int p = WPINS[i]; outPin[i] = 0;
    pinMode(p, pull == 1 ? INPUT_PULLUP : (pull == 2 ? INPUT_PULLDOWN : INPUT));
    if (p < 32) wMask0 |= 1UL << p; else wMask1 |= 1UL << (p - 32);
  }
  delay(2);
  wLast0 = REG_READ(GPIO_IN_REG) & wMask0; wLast1 = REG_READ(GPIO_IN1_REG) & wMask1;
}
inline void watchPoll() {
  uint32_t a = REG_READ(GPIO_IN_REG) & wMask0, b = REG_READ(GPIO_IN1_REG) & wMask1;
  if (a == wLast0 && b == wLast1) return;
  portENTER_CRITICAL(&evMux);
  uint32_t da = a ^ wLast0, db = b ^ wLast1;
  for (unsigned i = 0; i < NW; i++) {
    int p = WPINS[i];
    bool ch = p < 32 ? (da >> p) & 1 : (db >> (p - 32)) & 1;
    if (!ch) continue;
    Ev& e = evs[evHead]; evHead = (evHead + 1) % NEV; evTotal++; wCount[i]++;
    e.ms = millis(); e.pin = p; e.level = p < 32 ? (a >> p) & 1 : (b >> (p - 32)) & 1; e.c1 = c1; e.c2 = c2;
    if (p == IDX_PIN) idxPassC2 = c2;
    // Arm entered the sensor window going forward: check the count. Ignore a rising edge within 400 steps of the last
    // one checked (chatter at either edge of the 165-step window, or the same edge crossed again after a reversal).
    if (p == IDX_PIN && e.level && lastDir[1] > 0 && homed && labs(c2 - idxAcceptC2) > 400L * TPS) {
      idxAcceptC2 = c2;
      double per = 2 * M_PI / (GA + GK), d = (double)c2 / TPS - IDX_M2;
      d -= per * floor(d / per + 0.5);
      idxErr = (float)d; idxN++;
      if (guardOn && fabs(d) > IDX_TOL) fault = 1;
    }
  }
  wLast0 = a; wLast1 = b;
  portEXIT_CRITICAL(&evMux);
}

// ---------------------------------------------------------------- patterns
struct Pt { float theta, rho; };
#define MAXPTS 12000
Pt* pat = NULL;
volatile long patN = 0;
char lineBuf[48]; int lineLen = 0; bool lineOver = false;
long upN = 0, upSkipped = 0; bool upOverflow = false, upReject = false, upNoMem = false;
enum { TAG_NONE, TAG_STAGED, TAG_RUNNING, TAG_COMPLETE, TAG_FAILED };
const char* const tagNames[] = {"none","staged","running","complete","failed"};
char tagId[65] = "";                      // web task owns the string and staged buffer signature
char boardId[25] = "";                    // stable digest of this chip's eFuse identity
volatile int tagState = TAG_NONE;         // read/changed with stepMux on both cores
uint32_t tagRev = 0, tagCrc = 0;
bool tagUpload = false;

// ---------------------------------------------------------------- jobs
Job jobBuf;
volatile bool jobPending = false;
volatile bool stopFlag = false;
volatile bool pauseFlag = false;        // pause the running job where it is (button, /pause); cleared by /stop and when a job ends
volatile bool pausedNow = false;
volatile uint32_t jobT0 = 0;            // when the running job started (for the time-left estimate)
volatile int  stateV = ST_IDLE;
const char* volatile jobName = "none";
volatile float progress = 0;
volatile long ptIdx = 0, ptTotal = 0, passNo = 0;

long jobPoints(const Job& j) {
  switch (j.type) {
    case JT_POLAR: case JT_RAW: return 1;
    case JT_HOME: return 0;
    case JT_CIRCLE: return (long)(j.b * 360) + 1;
    case JT_SPIRAL: return (long)(j.a * 360) + 1;
    case JT_ROSE:   return 1441;
    case JT_CLEAR:  return 2L * 12 * 360 + 1;
    case JT_PLAY:   return patN;
    case JT_GEN:    return (long)(j.g.T * GEN_PPT) + 1;
  }
  return 0;
}
double thOff = 0;                      // whole turns added to every theta of the running job (see runJob)
inline void polarSteps(double rad, double rho, double& t1, double& t2) {   // -> full steps (fractional)
  rad += thOff;
  double r = rho * RMAX;
  if (r > RMAX) r = RMAX;
  if (r < 0) r = 0;
  double qq = r / (2 * GL); if (qq > 0.999) qq = 0.999;
  double e = 2 * M_PI - 2 * asin(qq);                 // far branch: rim (e near pi) .. exact centre (e = 2*pi)
  double phi = rad + TH0;
  double Ph = phi - PHI0 - GK * M2H, Rr = e - GEF + GB2 * M2H;
  double det = -GA * GB1 - GA1 * GB2;
  t2 = (-GB1 * Ph - GA1 * Rr) / det;
  t1 = (GA * Rr - GB2 * Ph) / det;
}
void genPoint(const GenP& p, long k, double& th, double& rho) {
  long N = (long)(p.T * GEN_PPT); if (N < 1) N = 1;
  double u = (double)k / N; th = 2 * M_PI * p.T * u;
  if (p.kind == GK_ERASE_OUT) { rho = u; return; }
  if (p.kind == GK_ERASE_IN)  { rho = 1 - u; return; }
  double sh = 1;
  if (p.kind == GK_BLOOM) { double c = fabs(cos(p.n * (th + p.w * u) / 2.0)); sh = 1.0 - p.d * (1.0 - pow(c, (double)p.g)); }
  else if (p.kind == GK_ARMS) { double c = fabs(cos(p.n * (th + p.w * log(1.0 / (1.0 - u + 0.04))) / 2.0)); sh = 1.0 - p.d * (1.0 - pow(c, (double)p.g)); }
  else if (p.kind == GK_SUPER) {
    double ph = p.n * (th + p.w * u) / 4.0, g = p.g, nr = pow(2.0, 0.5 - 1.0 / g);
    sh = pow(pow(fabs(cos(ph)), g) + pow(fabs(sin(ph)), g), -1.0 / g) / (nr > 1 ? nr : 1);
  } else if (p.kind == GK_RIPPLE) sh = 1.0 - p.d * (0.5 + 0.5 * cos(p.n * th)) * (0.5 - 0.5 * cos(2 * M_PI * p.q * u));
  else if (p.kind == GK_LOTUS) {
    double x = (1 - u) * p.q; int b = (int)x; if (b > p.q - 1) b = p.q - 1; double f = x - b, sn = sin(M_PI * f);
    double c = fabs(cos((p.n + 2 * b) * th / 2.0));
    sh = 1.0 - p.d * sqrt(sn > 0 ? sn : 0) * (1.0 - pow(c, (double)p.g));
  }
  else if (p.kind == GK_VORTEX) {
    double seg = 2 * M_PI / p.n, ph = fmod(th + p.w * u, seg); if (ph < 0) ph += seg;
    sh = cos(M_PI / p.n) / cos(ph - M_PI / p.n);
  } else { double m = p.n + 1.0 / p.q; sh = (1.0 + p.e * sin(m * th)) / (1.0 + p.e); }
  rho = (1 - u) * sh; if (rho < 0) rho = 0; if (rho > 1) rho = 1;
}
void jobPoint(const Job& j, long k, bool rev, double& t1, double& t2) {     // -> full steps
  switch (j.type) {
    case JT_POLAR: polarSteps(j.a, j.b, t1, t2); break;
    case JT_RAW:   t1 = j.l1; t2 = j.l2; break;
    case JT_HOME:  t1 = (double)c1 / TPS; t2 = (double)c2 / TPS; break;
    case JT_CIRCLE: polarSteps(2 * M_PI * k / 360.0, j.a, t1, t2); break;
    case JT_SPIRAL: {
      long N = (long)(j.a * 360); if (N < 1) N = 1;
      double r = (double)k / N; if (j.b < 0) r = 1.0 - r;
      polarSteps(2 * M_PI * k / 360.0, r, t1, t2); break; }
    case JT_ROSE: {
      double t = 2 * M_PI * k / 1440.0;
      polarSteps(t, fabs(cos(j.a * t)), t1, t2); break; }
    case JT_CLEAR: {
      long N = 12L * 360, m = k <= N ? k : 2 * N - k;
      polarSteps(2 * M_PI * m / 360.0, (double)m / N, t1, t2); break; }
    case JT_PLAY: {
      long i = rev ? patN - 1 - k : k;
      polarSteps(pat[i].theta, pat[i].rho, t1, t2); break; }
    case JT_GEN: { double th, rho; genPoint(j.g, rev ? (long)(j.g.T * GEN_PPT) - k : k, th, rho); polarSteps(th, rho, t1, t2); break; }
  }
}

void modelPolar(long t1, long t2, double& th, double& rho, double* eOut);
// Full steps of +m1 drive needed to put the elbow on its stop, with margin. From the MODEL's elbow angle, never from
// the m1 counter alone: every arm turn shifts the elbow by 2048 m1 steps and the counters are reduced by whole
// multiples, so |m1| says nothing about the distance. (2026-11-20 1:30pm: the old |m1| + 2500 stopped 2500 steps
// short after drawings that never re-homed, zeroed the elbow there, and the next portrait went through the catch.)
long elbowNeed(long t1, long t2) {
  double th_, rho_, e_ = 0; modelPolar(t1, t2, th_, rho_, &e_);
  long need = (e_ > GEF && e_ < 2 * M_PI + 0.5) ? lround((e_ - GEF) / GB1) + 2500 : (long)HOME_STEPS;
  if (need > HOME_STEPS || need < 2500) need = HOME_STEPS;
  return need;
}
// ---------------------------------------------------------------- planner + motion engine (task, core 1)
#define NQ 128
Seg q[NQ]; int qh = 0, qn = 0;
long srcK = 0, srcN = 0; bool srcRev = false;
double tailX1 = 0, tailX2 = 0; long tailT1 = 0, tailT2 = 0;
float jobVmax = 400;
static uint32_t nextT = 0;

// Append the next non-empty segment of the job to the look-ahead queue and update the speed limits behind it.
bool fillOne(const Job& j) {
  while (srcK < srcN && qn < NQ) {
    double x1, x2; jobPoint(j, srcK, srcRev, x1, x2);
    long k = srcK++;
    if (!isfinite(x1) || !isfinite(x2) || fabs(x1) > 5e7 || fabs(x2) > 5e7) {
      if (j.tagged) { stopFlag = true; return false; }
      continue;
    }
    long t1 = lround(x1 * TPS), t2 = lround(x2 * TPS);
    long d1 = t1 - tailT1, d2 = t2 - tailT2;
    if (!d1 && !d2) continue;
    int ti = (qh + qn) % NQ;
    Seg& s = q[ti];
    double e1 = x1 - tailX1, e2 = x2 - tailX2;        // exact (unrounded) direction, so rounding does not look like a bend
    double m = fabs(e1) > fabs(e2) ? fabs(e1) : fabs(e2);
    if (m < 1e-9) { e1 = d1; e2 = d2; m = labs(d1) > labs(d2) ? labs(d1) : labs(d2); }
    s.t1 = t1; s.t2 = t2; s.x1 = x1; s.x2 = x2; s.k = k; s.vcap = 0;
    // Erase spirals run faster than drawings, but the main motor's load grows with radius: at 600 steps/s it stalled
    // at 0.89 of the radius (2026-11-20 10:16, caught by the arm-sensor guard). So taper from VERASE inside 0.6 of the
    // radius down to the drawing speed at the rim.
    if (j.type == JT_GEN && (j.g.kind == GK_ERASE_OUT || j.g.kind == GK_ERASE_IN) && jobVmax > VMAX) {
      double eth, erho; genPoint(j.g, srcRev ? (long)(j.g.T * GEN_PPT) - k : k, eth, erho);
      s.vcap = erho <= 0.6 ? jobVmax : (float)(VMAX + (jobVmax - VMAX) * (1.0 - erho) / 0.4);
    }
    s.len = (float)(labs(d1) > labs(d2) ? labs(d1) : labs(d2)) / TPS;
    s.u1 = (float)(e1 / m); s.u2 = (float)(e2 / m);
    float vm2 = jobVmax * jobVmax, vj = VJ < jobVmax ? (float)VJ : jobVmax;
    s.fj2 = vm2;
    s.vexit2 = (srcK >= srcN) ? vj * vj : VMINF * VMINF;       // last segment of the pass: arrive at the stop speed
    if (s.vexit2 > vm2) s.vexit2 = vm2;
    if (qn > 0) {                                               // junction between the previous segment and this one
      Seg& p = q[(ti + NQ - 1) % NQ];
      float du = fabsf(s.u1 - p.u1), dv = fabsf(s.u2 - p.u2); if (dv > du) du = dv;
      float f2 = vm2;
      if (du > 1e-4f) {
        float a = vj / du, a2 = a * a, b2 = ACCC * 0.5f * (s.len + p.len) / du;
        f2 = a2 < b2 ? a2 : b2;
        if (f2 > vm2) f2 = vm2;
        if (f2 < VMINF * VMINF) f2 = VMINF * VMINF;
      }
      p.fj2 = f2;
      float acc2 = 2 * ACC;
      for (int n = qn - 1, i = (ti + NQ - 1) % NQ, nx = ti; n >= 0; n--, nx = i, i = (i + NQ - 1) % NQ) {
        float nv = q[nx].vexit2 + acc2 * q[nx].len;
        if (nv > q[i].fj2) nv = q[i].fj2;
        if (nv == q[i].vexit2) break;
        q[i].vexit2 = nv;
      }
    }
    tailX1 = x1; tailX2 = x2; tailT1 = t1; tailT2 = t2;
    qn++;
    return true;
  }
  return false;
}

void energise() {
  if (energised) return;
  applyM(0, c1); applyM(1, c2); energised = true;
  vTaskDelay(pdMS_TO_TICKS(30));       // let the rotors settle on the held phase
}

// Run the segment at the head of the queue. false = aborted by stop.
bool runSeg(const Seg& s) {
  long d1 = s.t1 - c1, d2 = s.t2 - c2;
  long a1 = labs(d1), a2 = labs(d2), n = a1 > a2 ? a1 : a2;
  if (!n) return true;
  int s1 = d1 > 0 ? 1 : -1, s2 = d2 > 0 ? 1 : -1;
  if (a1 && s1 != lastDir[0]) { lastDir[0] = s1; lashTgt[0] = s1 * (BLT[0] / 2); }
  if (a2 && s2 != lastDir[1]) { lastDir[1] = s2; lashTgt[1] = s2 * (BLT[1] / 2); }
  long e1 = n / 2, e2 = n / 2;
  float v = curV, acc = ACC, vm = (s.vcap > 0 && s.vcap < jobVmax) ? s.vcap : jobVmax, vjj = VJ;
  const float invT = 1.0f / TPS;
  for (long i = 0; i < n; i++) {
    if (stopFlag) { curV = v; return false; }
    if (pauseFlag) {
      if (v > vjj * 1.02f) { v -= 4 * acc / (v * TPS); if (v < vjj) v = vjj; }      // slow down first, then hold
      else {
        curV = 0; pausedNow = true; uint32_t tp = millis(); bool off = false;
        while (pauseFlag && !stopFlag) {                    // hold here: counters untouched, coils released after 1 s
          vTaskDelay(pdMS_TO_TICKS(20)); watchPoll();
          if (!off && millis() - tp > 1000) { coilsOff(); off = true; }
        }
        pausedNow = false; jobT0 += millis() - tp;
        if (stopFlag) { curV = 0; return false; }
        energise(); v = vjj < vm ? vjj : vm; nextT = micros();
      }
    }
    if (idxStop && ((REG_READ(GPIO_IN_REG) >> IDX_PIN) & 1)) { idxHit = true; curV = v; return true; }
    float lim2 = s.vexit2 + 2 * acc * (float)(n - i - 1) * invT;
    if (v * v > lim2) v = sqrtf(lim2);
    else if (!pauseFlag) { v += acc / (v * TPS); if (v * v > lim2) v = sqrtf(lim2); }
    if (v > vm) v = vm;
    if (v < VMINF) v = VMINF < vm ? VMINF : vm;
    e1 -= a1; if (e1 < 0) { e1 += n; c1 += s1; applyM(0, c1); }
    e2 -= a2; if (e2 < 0) { e2 += n; c2 += s2; applyM(1, c2); }
    for (int m = 0; m < 2; m++) if (lashOff[m] != lashTgt[m]) {       // take up backlash alongside the move, at no more than VJ
      lashAcc[m] += vjj / v;
      if (lashAcc[m] >= 1) { lashAcc[m] = 0; lashOff[m] += lashTgt[m] > lashOff[m] ? 1 : -1; applyM(m, m ? c2 : c1); }
    }
    watchPoll();
    if (guardOn) {
      if (labs(c2 - idxPassC2) > guardTicks) fault = 2;
      if (fault) { curV = v; return false; }
    }
    curV = v;
    nextT += (uint32_t)(1e6f / (v * TPS));
    int32_t late = (int32_t)(micros() - nextT);
    if (late > 600) nextT = micros();                  // fell behind (segment hand-over): resync, never burst
    while ((int32_t)(nextT - micros()) > 0) { }
  }
  return true;
}

// One straight move outside the look-ahead queue (homing). false = aborted by stop.
bool segTo(long t1, long t2, float vmax, bool untilIdx) {
  Seg s = {}; s.t1 = t1; s.t2 = t2;
  float vj = VJ < vmax ? (float)VJ : vmax;
  s.vexit2 = vj * vj; jobVmax = vmax; curV = vj; nextT = micros();
  idxHit = false; idxStop = untilIdx;
  bool ok = runSeg(s);
  idxStop = false;
  vTaskDelay(pdMS_TO_TICKS(150));
  return ok && !stopFlag;
}
// Homing. Elbow: drive m1 positive into the solid side of the catch near the centre (the motor stalls there), that is
// m1 = 0; then back off. Arm: turn m2 positive until the arm sensor (GPIO13) goes high, that is m2 = IDX_M2.
// Never goes near the centre on the working side and never pushes through the catch.
bool runHome(const Job& j) {
  float vh = jobVmax;
  homed = 0; homeErr = 0; fault = 0;
  if (!(j.l1 & 4)) {
    if (!segTo(c1 + j.l2 * TPS, c2, vh, false)) return false;
    setC(0, 0); M2H = (double)c2 / TPS;
    progress = 0.4f;
    if (!segTo(-(long)HOME_BACK * TPS, c2, vh, false)) return false;
  }
  if (!(j.l1 & 8)) {
    if (digitalRead(IDX_PIN)) {                        // already inside the sensor window: back out of it first
      if (!segTo(c1, c2 - 700L * TPS, vh, false)) return false;
      if (digitalRead(IDX_PIN)) { homeErr = 2; return true; }
    }
    progress = 0.5f;
    if (!segTo(c1, c2 + 11500L * TPS, vh < (float)VJ ? vh : (float)VJ, true)) return false;
    if (!idxHit) { homeErr = 1; return true; }
    long shift = c2 - lround(IDX_M2 * TPS);
    setC(1, c2 - shift); M2H -= (double)shift / TPS;
    idxPassC2 = c2; idxAcceptC2 = c2; idxErr = 0; idxN = 0;
  }
  homed = 1;
  return true;
}

volatile bool lastAborted = false;
// ---- sequencer: a short queue of steps the table works through on its own (motion task pops, web task pushes)
#define NSTEP 12
Step steps[NSTEP]; volatile int stepN = 0;
portMUX_TYPE stepMux = portMUX_INITIALIZER_UNLOCKED;
bool pushStep(const Step& st) {
  bool ok = false;
  portENTER_CRITICAL(&stepMux); if (stepN < NSTEP) { steps[stepN++] = st; ok = true; } portEXIT_CRITICAL(&stepMux);
  return ok;
}
bool popStep(Step& st) {
  bool ok = false;
  portENTER_CRITICAL(&stepMux);
  if (stepN > 0) { st = steps[0]; for (int i = 1; i < stepN; i++) steps[i - 1] = steps[i]; stepN--; ok = true; }
  portEXIT_CRITICAL(&stepMux);
  return ok;
}
#include "guest_state.h"
#include "guest_cache.h"
void clearSteps() {
  portENTER_CRITICAL(&stepMux);
  for (int i = 0; i < stepN; i++) {
    if (steps[i].guest) { forgetGuestLocked(); break; }
  }
  stepN = 0;
  portEXIT_CRITICAL(&stepMux);
}
char nowName[72] = "";                  // what is being drawn, or was drawn last
volatile uint32_t restartAt = 0;
// A flash write stalls both cores for milliseconds, so it must never overlap a move. Two flags, each side sets its own
// and then looks at the other's: the web task owns webFlash (uploads, updates, saved settings), the motion task owns
// seqBusy (about to start, or running, any job). Whoever sees the other's flag backs off and retries.
volatile bool webFlash = false, seqBusy = false, rehoming = false;
volatile uint32_t webFlashMs = 0;
volatile unsigned long fsFree = 0;
volatile bool fsOk = false;
// settings kept in flash (written by the web task only while the table is idle: a flash write stalls the motion core)
volatile bool rehomeOn = true;          // re-home the elbow before every erase: catches a slipped elbow motor with no camera
volatile float EPITCH = 0.02f;         // ring spacing of the erase in front of a stored picture (0.035 leaves rings that compete with it; 0.02 is flat, 17 min)
volatile float VERASE = 550;            // top speed for erase spirals, steps/s, tapered to VMAX toward the rim (pieces use VMAX)
volatile int quietOn = 0, quietFrom = 23 * 60, quietTo = 7 * 60;   // quiet hours, minutes after midnight (Pacific)
volatile bool settingsDirty = false, calDirty = false;
volatile bool eraseFirst = true;         // erase the sand before each new drawing (Bill, 2026-11-20: wanted the option; default on)
volatile int unchecked = 0;              // drawings since the elbow was last re-homed
#define MAX_UNCHECKED 10
volatile bool quietOverride = false;     // a button press in quiet hours allows one cycle
volatile int autoMix = 2;                // what auto mode draws: 0 its own designs, 1 stored drawings, 2 both
char lastStored[28] = "";
bool clockSet() { return time(NULL) > 1700000000; }
int nowMinutes() { time_t t = time(NULL); struct tm tmv; localtime_r(&t, &tmv); return tmv.tm_hour * 60 + tmv.tm_min; }
bool quietNow() {
  if (!quietOn || !clockSet()) return false;
  int m = nowMinutes(), a = quietFrom, b = quietTo;
  return a == b ? false : (a < b ? (m >= a && m < b) : (m >= a || m < b));
}
// ---- auto mode: erase outward, draw a random generative piece inward, hold, repeat. /auto?on=1
volatile bool autoBoot = false, bootPending = false;   // autoBoot: saved choice to home and start auto mode 20 s after power-up
volatile bool autoOn = false; volatile int autoPhase = 0; volatile uint32_t autoHoldS = 600, autoNextMs = 0; volatile long autoCount = 0;
char genDesc[72] = "none";
float rndF(float a, float b) { return a + (b - a) * (float)(esp_random() / 4294967296.0); }
int rndI(int a, int b) { return a + (int)(esp_random() % (uint32_t)(b - a + 1)); }
void describe(const GenP& p) {
  if (p.kind == GK_BLOOM) snprintf(genDesc, sizeof genDesc, "bloom n=%d d=%.2f g=%.1f T=%.0f w=%.1f", p.n, p.d, p.g, p.T, p.w);
  else if (p.kind == GK_ARMS) snprintf(genDesc, sizeof genDesc, "arms n=%d d=%.2f g=%.1f T=%.0f w=%.1f", p.n, p.d, p.g, p.T, p.w);
  else if (p.kind == GK_VORTEX) snprintf(genDesc, sizeof genDesc, "vortex n=%d T=%.0f w=%.1f", p.n, p.T, p.w);
  else if (p.kind == GK_SUPER) snprintf(genDesc, sizeof genDesc, "super n=%d g=%.1f T=%.0f w=%.1f", p.n, p.g, p.T, p.w);
  else if (p.kind == GK_RIPPLE) snprintf(genDesc, sizeof genDesc, "ripple n=%d d=%.2f q=%d T=%.0f", p.n, p.d, p.q, p.T);
  else if (p.kind == GK_LOTUS) snprintf(genDesc, sizeof genDesc, "lotus n=%d d=%.2f g=%.1f q=%d T=%.0f", p.n, p.d, p.g, p.q, p.T);
  else if (p.kind == GK_WEAVE) snprintf(genDesc, sizeof genDesc, "weave n=%d q=%d e=%.2f T=%.0f", p.n, p.q, p.e, p.T);
  else snprintf(genDesc, sizeof genDesc, "%s T=%.1f", p.kind == GK_ERASE_OUT ? "erase_out" : "erase_in", p.T);
}
GenP pickRandom() {                    // eight draws over seven families (flowers twice as likely), never the same family twice running
  static int lastF = -1;
  GenP p = {}; int k = rndI(0, 7), fam = k <= 1 ? 0 : k - 1;
  for (int i = 0; i < 8 && fam == lastF; i++) { k = rndI(0, 7); fam = k <= 1 ? 0 : k - 1; }
  lastF = fam;
  if (fam == 0) { const float gs[] = {0.5f, 0.7f, 1.0f, 1.6f, 2.5f}, ws[] = {0, 0, 0.8f, 1.6f, -1.2f, 3.1f};
    p.kind = GK_BLOOM; p.n = rndI(3, 9); p.d = rndF(0.25f, 0.55f); p.g = gs[rndI(0, 4)]; p.T = rndI(16, 22); p.w = ws[rndI(0, 5)]; }
  else if (fam == 1) { p.kind = GK_VORTEX; p.n = rndI(3, 7); p.T = rndI(15, 20); p.w = rndF(1.2f, 4.0f) * (rndI(0, 1) ? 1 : -1); }
  else if (fam == 2) { const int qs[] = {2, 2, 3, -3, 4}; p.kind = GK_WEAVE; p.n = rndI(5, 13); p.q = qs[rndI(0, 4)]; p.e = rndF(0.06f, 0.13f); p.T = rndI(18, 24); }
  else if (fam == 3) { const float gs[] = {1.0f, 1.6f, 2.0f};
    p.kind = GK_ARMS; p.n = rndI(4, 8); p.d = rndF(0.35f, 0.55f); p.g = gs[rndI(0, 2)]; p.T = rndI(18, 22); p.w = rndF(0.8f, 1.8f) * (rndI(0, 1) ? 1 : -1); }
  else if (fam == 4) { const float gs[] = {1.2f, 1.5f, 3.0f, 4.0f}; const int ns[] = {4, 6, 8};
    p.kind = GK_SUPER; p.n = ns[rndI(0, 2)]; p.g = gs[rndI(0, 3)]; p.T = rndI(18, 22); p.w = rndF(0.8f, 2.5f) * (rndI(0, 1) ? 1 : -1); }
  else if (fam == 5) { p.kind = GK_RIPPLE; p.n = rndI(6, 12); p.d = rndF(0.35f, 0.55f); p.q = rndI(2, 4); p.T = rndI(20, 24); }
  else { const float gs[] = {0.6f, 1.0f, 2.0f};
    p.kind = GK_LOTUS; p.n = rndI(5, 8); p.d = rndF(0.35f, 0.5f); p.g = gs[rndI(0, 2)]; p.q = rndI(3, 5); p.T = rndI(21, 25); }
  return p;
}
bool parseSpec(const String& sp, GenP& p) {
  p = {};
  String k = sp.substring(0, sp.indexOf(' ') < 0 ? sp.length() : sp.indexOf(' '));
  if (k == "bloom") p.kind = GK_BLOOM; else if (k == "arms") p.kind = GK_ARMS; else if (k == "vortex") p.kind = GK_VORTEX;
  else if (k == "weave") p.kind = GK_WEAVE; else if (k == "super") p.kind = GK_SUPER; else if (k == "ripple") p.kind = GK_RIPPLE;
  else if (k == "lotus") p.kind = GK_LOTUS; else return false;
  p.n = 6; p.q = 2; p.d = 0.45f; p.g = 1.0f; p.T = 20; p.w = 0; p.e = 0.1f;
  int i = sp.indexOf(' ');
  while (i >= 0 && i < (int)sp.length()) {
    int j = sp.indexOf(' ', i + 1); if (j < 0) j = sp.length();
    String tok = sp.substring(i + 1, j); int eq = tok.indexOf('=');
    if (eq == 1) {
      float v = tok.substring(2).toFloat();
      switch (tok[0]) { case 'n': p.n = (int)v; break; case 'q': p.q = (int)v; break; case 'd': p.d = v; break; case 'g': p.g = v; break;
                        case 'T': p.T = v; break; case 'w': p.w = v; break; case 'e': p.e = v; break; }
    }
    i = j;
  }
  p.n = constrain(p.n, 2, 24); if (p.q == 0) p.q = 2; p.q = constrain(p.q, -8, 8);
  if (p.kind == GK_LOTUS || p.kind == GK_RIPPLE) p.q = constrain(abs(p.q), 1, 8);
  p.d = constrain(p.d, 0.0f, 0.9f); p.g = constrain(p.g, 0.2f, 6.0f); p.T = constrain(p.T, 2.0f, 60.0f);
  p.w = constrain(p.w, -20.0f, 20.0f); p.e = constrain(p.e, 0.0f, 0.4f);
  return true;
}
GenP eraseP(bool out, float pitch) { GenP p = {}; p.kind = out ? GK_ERASE_OUT : GK_ERASE_IN; p.T = 1.0f / pitch; return p; }

void runJob(const Job& j, bool guest = false) {
  portENTER_CRITICAL(&stepMux);
  if (j.tagged && (tagState != TAG_RUNNING || !homed || fault || pauseFlag || stopFlag || stepN ||
                   autoOn || bootPending || guestState.pending || guestState.evolving)) {
    if (tagState == TAG_RUNNING) tagState = TAG_FAILED;
    stateV = ST_IDLE; portEXIT_CRITICAL(&stepMux); return;
  }
  if (!guest) forgetGuestLocked();
  if (j.tagged) tagRev = guestState.rev;
  else tagState = TAG_NONE;
  portEXIT_CRITICAL(&stepMux);
  jobName = j.name; ptIdx = 0; passNo = 0; progress = 0;
  bool aborted = false;
  srcRev = j.rev;                      // rev: draw it backwards (outward instead of inward, or the other way)
  jobVmax = j.vmax > 0 ? j.vmax : (float)VMAX;
  jobT0 = millis();
  guardTicks = (long)(1.3 * 2 * M_PI / (GA + GK) * TPS);
  guardOn = homed && j.type != JT_HOME && !j.noguard;
  // Keep the counters small. The gearing is whole numbers: 5 arm turns (m2 51200 steps) with 1 elbow-motor turn
  // (m1 10240 steps) is exactly the same arm pose and the same coil phase, so whole multiples can be dropped.
  // (v7.0 did not, and after 195 turns its "absurd target" check silently skipped the rest of every job.)
  if (j.type != JT_RAW && j.type != JT_HOME) {
    long k = lround((double)c2 / (51200.0 * TPS));
    if (k != 0) { c1 -= k * 10240L * TPS; c2 -= k * 51200L * TPS; idxPassC2 -= k * 51200L * TPS; idxAcceptC2 -= k * 51200L * TPS; }
  }
  thOff = 0;
  if (j.type != JT_HOME && j.type != JT_RAW) {       // start from the arm's present angle: never unwind earlier turns
    double thNow, rhoNow; modelPolar(c1, c2, thNow, rhoNow, NULL);
    double th0 = 0.0, r0u;
    if (j.type == JT_POLAR) th0 = j.a;
    else if (j.type == JT_PLAY && patN > 0) th0 = pat[j.rev ? patN - 1 : 0].theta;
    else if (j.type == JT_GEN) genPoint(j.g, j.rev ? (long)(j.g.T * GEN_PPT) : 0, th0, r0u);
    thOff = 2 * M_PI * floor((thNow - th0) / (2 * M_PI) + 0.5);
  }
  energise();
  if (j.type == JT_HOME) aborted = !runHome(j);
  else do {
    srcN = jobPoints(j); srcK = 0; qh = 0; qn = 0;
    tailT1 = c1; tailT2 = c2; tailX1 = (double)c1 / TPS; tailX2 = (double)c2 / TPS;
    ptTotal = srcN; ptIdx = 0; progress = 0;
    while (qn < NQ && fillOne(j)) { }
    curV = VJ < jobVmax ? (float)VJ : jobVmax;
    nextT = micros();
    while (qn > 0) {
      if (stopFlag || !runSeg(q[qh])) { aborted = true; break; }
      ptIdx = q[qh].k + 1; progress = srcN > 0 ? (float)ptIdx / (float)srcN : 1.0f;
      qh = (qh + 1) % NQ; qn--;
      fillOne(j);
    }
    srcRev = !srcRev; passNo++;
    if (stopFlag) aborted = true;
    if (j.loop && !aborted) vTaskDelay(pdMS_TO_TICKS(2));
  } while (j.loop && !aborted && patN > 0);
  curV = 0; guardOn = false; lastAborted = aborted; pauseFlag = false;
  if (fault) homed = 0;                 // the counters can no longer be trusted: /home again
  if (aborted) { coilsOff(); stopFlag = false; }
  else progress = 1.0f;
  lastMoveMs = millis(); posDirty = true;
  bool reached = !j.tagged || (patN >= 2 && tagAt(pat[patN-1].theta, pat[patN-1].rho));
  portENTER_CRITICAL(&stepMux);
  if (j.tagged && tagState == TAG_RUNNING) tagState = aborted || fault || !reached ? TAG_FAILED : TAG_COMPLETE;
  stateV = ST_IDLE;
  portEXIT_CRITICAL(&stepMux);
}

// Pick a stored drawing at random (not the one drawn last). name = "" if there is none. r0 = rho of its first point.
void pickStored(char* name, size_t n, float& r0) {
  name[0] = 0;
  if (!fsOk) return;
  int count = 0;
  for (int pass = 0; pass < 2; pass++) {
    File dir = LittleFS.open("/lib"); if (!dir || !dir.isDirectory()) return;
    int want = pass ? rndI(0, count - 1) : -1, k = 0;
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String fn = f.name(); if (!fn.endsWith(".pat") || fn.length() - 4 >= n) continue;
      fn = fn.substring(0, fn.length() - 4);
      if (fn.indexOf('.') >= 0) continue;                               // <name>.bg.pat is an erase, not a drawing
      if (fn == lastStored || fn.startsWith("moire_b")) continue;          // moire_b only makes sense on top of moire_a
      if (pass && k == want) { strlcpy(name, fn.c_str(), n); float p0[2] = {0, 1}; f.read((uint8_t*)p0, 8); r0 = p0[1]; }
      k++;
    }
    if (!pass) { count = k; if (!count) return; }
  }
  if (name[0]) strlcpy(lastStored, name, sizeof lastStored);
}

// Load a library pattern (/lib/<name>.pat: little-endian float32 theta, float32 rho per point) into the play buffer.
bool loadPat(const char* name) {
  if (!fsOk || !pat) return false;
  char path[48]; snprintf(path, sizeof path, "/lib/%s.pat", name);
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  long n = f.size() / 8; if (n > MAXPTS) n = MAXPTS;
  patN = 0;
  long got = f.read((uint8_t*)pat, n * 8) / 8;
  f.close();
  for (long i = 0; i < got; i++) { if (!isfinite(pat[i].theta) || !isfinite(pat[i].rho)) return false; pat[i].rho = constrain(pat[i].rho, 0.0f, 1.0f); }
  patN = got;
  return got > 1;
}

// v8.11: the outside-in erase made for a stored drawing (/lib/<name>.bg.pat, written by tools/sync_table.py from
// tools/bg_erase.py: it erases only the sand the drawing will not cover, from the rim inward, and ends on the drawing's
// first point). Loaded into the play buffer behind two lead-in points: straight out to the file's starting radius (the
// rim) at the ball's present angle, then along the rim the short way to the file's first point, so the trip to the
// start does not cut across the sand. Refused (the caller falls back to the spiral erase) unless the file is whole,
// fits, starts on the rim and ends on the drawing's first point. Play it forwards only.
bool loadBg(const char* name) {
  if (!fsOk || !pat) return false;
  char path[48]; float p0[2] = {0, 0};
  snprintf(path, sizeof path, "/lib/%s.pat", name);
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  bool okp = f.read((uint8_t*)p0, 8) == 8; f.close();
  if (!okp || !isfinite(p0[0]) || !isfinite(p0[1])) return false;
  snprintf(path, sizeof path, "/lib/%s.bg.pat", name);
  if (!LittleFS.exists(path)) return false;
  f = LittleFS.open(path, "r");
  if (!f) return false;
  long sz = f.size(), n = sz / 8;
  patN = 0;
  if (sz % 8 || n < 2 || n > MAXPTS - 2) { f.close(); return false; }
  long got = f.read((uint8_t*)(pat + 2), n * 8) / 8;
  f.close();
  if (got != n) return false;
  for (long i = 2; i < n + 2; i++) if (!isfinite(pat[i].theta) || !(pat[i].rho >= 0.0f && pat[i].rho <= 1.001f)) return false;
  Pt a = pat[2], z = pat[n + 1];
  double dz = fmod((double)z.theta - p0[0], 2 * M_PI); if (dz > M_PI) dz -= 2 * M_PI; if (dz < -M_PI) dz += 2 * M_PI;
  if (a.rho < 0.97f || fabs(dz) > 0.01 || fabsf(z.rho - p0[1]) > 0.01f) return false;
  double thn, rhn; modelPolar(c1, c2, thn, rhn, NULL);
  pat[0].theta = (float)(thn + 2 * M_PI * floor((a.theta - thn) / (2 * M_PI) + 0.5));   // the ball's angle, within half a turn of the start
  pat[0].rho = a.rho; pat[1] = a;
  patN = n + 2;
  return true;
}

// The erase in front of a stored drawing (/draw and auto mode): its own outside-in erase if it has one (v8.11), else
// the spiral erase that ends where the drawing starts. With the outside-in erase the drawing is then played forwards
// (it ends on the drawing's first point; the spiral fallback also ends at that end).
void pushEraseFor(const char* name, float r0, Step& draw) {
  Step st = {}; st.kind = SK_GEN; st.g = eraseP(r0 >= 0.5f, EPITCH);
  char path[48]; snprintf(path, sizeof path, "/lib/%s.bg.pat", name);
  if (fsOk && LittleFS.exists(path)) { st.kind = SK_BG; strlcpy(st.name, name, sizeof st.name); draw.fwd = 1; }
  pushStep(st);
}

void motionTask(void*) {
  for (;;) {
    if (stopFlag) { stopFlag = false; coilsOff(); }
    seqBusy = true; __sync_synchronize();                         // claim the right to move; back off while the web task writes flash
    if (webFlash) { seqBusy = false; vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    if (jobPending) {
      Job j = jobBuf;
      stateV = (j.type == JT_POLAR || j.type == JT_RAW || j.type == JT_HOME) ? ST_MOVING : ST_DRAWING;
      __sync_synchronize();
      jobPending = false;
      runJob(j);
      seqBusy = false;
      continue;
    }
    if (bootPending && millis() > 20000 && !jobPending) {        // plugged in with "start by itself" on: home fully, then auto
      bootPending = false;
      Job j = {}; j.type = JT_HOME; j.name = "home"; j.l2 = HOME_STEPS;
      stateV = ST_MOVING; runJob(j);
      if (homed && !lastAborted) { autoNextMs = millis(); autoOn = true; }
      seqBusy = false;
      continue;
    }
    if (fault || !homed) { autoOn = false; if (stepN) clearSteps(); }
    // auto mode: when nothing is queued and the on-show time is over, queue the next cycle
    if (autoOn && stepN == 0 && (int32_t)(millis() - autoNextMs) >= 0 && (!quietNow() || quietOverride)) {
      char nm[28] = ""; float r0 = 1;
      if (autoMix == 1 || (autoMix == 2 && rndI(0, 1))) pickStored(nm, sizeof nm, r0);      // slow (reads the folder): do it before the re-check
      if (!autoOn || stepN) { seqBusy = false; continue; }      // stopped while we were looking: do not queue anything
      quietOverride = false;
      Step st = {};
      // The self-check drags the ball across the sand, so it goes with an erase; without erasing it is forced only
      // after MAX_UNCHECKED drawings.
      if (rehomeOn && (eraseFirst || unchecked >= MAX_UNCHECKED)) { st.kind = SK_REHOME; pushStep(st); }
      if (nm[0]) {                                                // a stored drawing
        Step dr = {}; dr.kind = SK_FILE; dr.piece = 1; strlcpy(dr.name, nm, sizeof dr.name);
        if (eraseFirst) pushEraseFor(nm, r0, dr);
        pushStep(dr);
      } else {
        if (eraseFirst) { st = {}; st.kind = SK_GEN; st.g = eraseP(true, 0.035f); pushStep(st); }
        st = {}; st.kind = SK_GEN; st.g = pickRandom(); st.piece = 1; pushStep(st);
      }
    }
    Step st;
    if (stepN > 0) stateV = ST_MOVING;                            // busy from before the pop, so the web task never sees an idle gap
    if (stateV == ST_MOVING && !popStep(st)) stateV = ST_IDLE;
    else if (stateV == ST_MOVING) {
      Job j = {}; bool ok = true;
      if (st.kind == SK_REHOME) {          // elbow only: the arm sensor already checks motor 2 every turn
        long need = elbowNeed(c1, c2);
        j.type = JT_HOME; j.name = "rehome"; j.l1 = 8; j.l2 = need; stateV = ST_MOVING; rehoming = true; unchecked = 0;
      } else if (st.kind == SK_GEN) {
        j.type = JT_GEN; j.name = "gen"; j.g = st.g;
        if (st.g.kind == GK_ERASE_OUT || st.g.kind == GK_ERASE_IN) j.vmax = VERASE;
        else {                               // a piece runs rim -> centre; if the ball is nearer the centre, draw it centre -> rim
          double thn, rhn; modelPolar(c1, c2, thn, rhn, NULL); j.rev = rhn < 0.5; unchecked++;
        }
        describe(st.g); strlcpy(nowName, genDesc, sizeof nowName); stateV = ST_DRAWING;
      } else if (st.kind == SK_GUEST) {
        j.type = JT_PLAY; j.name = "play"; stateV = ST_DRAWING;
        strlcpy(nowName, "Guest drawing", sizeof nowName);
        ok = guestState.pending && (st.guestSlot ? loadGuestSlot(st.guestSlot-1) : patN >= 2);
        if (st.guestLast) unchecked++;
      } else if (st.kind == SK_BG) {         // v8.11: the drawing's own outside-in erase, at drawing speed; "erase <name>" keeps the page and the light on "erasing"
        stateV = ST_DRAWING;
        if (loadBg(st.name)) { j.type = JT_PLAY; j.name = "play"; j.rev = false; snprintf(nowName, sizeof nowName, "erase %s", st.name); }
        else { j.type = JT_GEN; j.name = "gen"; j.g = st.g; j.vmax = VERASE; describe(st.g); strlcpy(nowName, genDesc, sizeof nowName); }   // unusable file: the spiral erase
      } else {
        stateV = ST_DRAWING; strlcpy(nowName, st.name, sizeof nowName);
        ok = loadPat(st.name);
        j.type = JT_PLAY; j.name = "play"; unchecked++;
        if (ok && !st.fwd) {                 // start from whichever end of the drawing is nearer the ball: no line across the sand
          double thn, rhn; modelPolar(c1, c2, thn, rhn, NULL);
          j.rev = fabs(rhn - pat[patN - 1].rho) + 0.05 < fabs(rhn - pat[0].rho);
        }
      }
      if (!ok) { if (st.guest) forgetGuest(); stateV = ST_IDLE; rehoming = false; seqBusy = false; pauseFlag = false; clearSteps(); continue; }   // stored drawing unreadable: drop the rest
      if (posSavedOk) { prefs.putUChar("ok", 0); posSavedOk = false; }
      runJob(j, st.guest);
      if (st.kind == SK_GUEST && st.guestLast && !lastAborted && !fault) finishGuest();
      rehoming = false; seqBusy = false;
      if (lastAborted || fault) { autoOn = false; forgetGuest(); clearSteps(); }
      else if (st.piece) { autoCount++; autoNextMs = millis() + autoHoldS * 1000UL; }
      continue;
    }
    seqBusy = false;
    if (energised && millis() - lastMoveMs > 1000) coilsOff();
    watchPoll();
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

// ---------------------------------------------------------------- ring light settings (the light task is further down)
enum { LM_OFF = 0, LM_SOLID, LM_COMET, LM_BREATHE, LM_PROGRESS, LM_IDX, LM_FOLLOW, LM_ARC, LM_SHOW, LM_AUTO, LM_AURORA, LM_BREATH478, LM_FIREFLY };
volatile float ledArcW = 6;
volatile int ledIdx = 0;
volatile int ledMode = LM_AUTO;
volatile uint32_t ledColor = 0xFFB060;   // warm amber-white
volatile uint32_t ledFill = 0x2C4C9C;    // the cool tone opposite the key light in the show light
volatile int ledBright = 140;
volatile int ledLin = 0;                 // 1 = raw linear output with no fade (camera tools); 0 = eye-corrected and smoothed
volatile float SHOW_PERIOD = 20;         // seconds for the show light to go once round the bowl
volatile int ledMaxmA = 1000;            // cap on the ring's estimated current (43 LEDs at full white would be about 2.6 A)
volatile int ledCap = 255, ledPrevMode = LM_AUTO, ledDrift = 0;
volatile int ledRest = 0;                // what Automatic shows while resting: 0 the circling show light, 1 aurora
volatile int ledFillRing = 0;            // 1 = while drawing, the ring also fills up dimly as the piece progresses
volatile float ledSpeed = 1.0f;          // speed of the moving lights (show light, aurora, colour drift): 0.25 .. 4
volatile int ledMood = 0;                // 1 = each piece gets its own colour (picked from its name)
volatile int ledEvening = 1;             // 1 = dimmer in the evening and at night (needs the clock)
volatile int ledWarm = 1;                // 1 = the light also turns warmer through the evening (with evening=1)
volatile int ledTrail = 1;               // 1 = while drawing, a soft trail lingers where the ball has just been
volatile int ledDith = 2;                // most bits of temporal dither (0 = none, as v8.5 to v8.9)
volatile int ledPeriodMs = 2;            // output frame period: 2 ms = 500 frames/s (v8.9: about 17 ms)
volatile uint32_t ledNow = 0xFFB060;
volatile uint32_t ledFlashAt = 0; volatile bool ledFlashOn = false;   // the ring flashes briefly to acknowledge a button press
// a camera tool may borrow the ring (tmp=1); restore=1 gives back what was set before
volatile bool ledTmp = false; int svMode = LM_AUTO, svBright = 140, svDrift = 0, svMood = 0, svRest = 0, svFillRing = 0, svEvening = 1, svWarm = 1, svTrail = 1; uint32_t svColor = 0xFFB060, svFill = 0x2C4C9C; float svPeriod = 240, svSpeed = 1;

// ---------------------------------------------------------------- saved state (NVS)
struct CalBlob { uint32_t ver; double l, ef, b1, b2, phi0, a, a1, k, rmax, emarg, th0, idx; long home; float led0; int bl1, bl2; };
#define CAL_VER 7
volatile float LED0 = 102.0f, LEDBASE = 0.06f, LEDW = 14.0f;
void saveCal() {
  CalBlob b = {CAL_VER, GL, GEF, GB1, GB2, PHI0, GA, GA1, GK, RMAX, EMARG, TH0, IDX_M2, HOME_STEPS, LED0, BLT[0], BLT[1]};
  prefs.putBytes("cal", &b, sizeof b);
}
void loadState() {
  CalBlob b;
  if (prefs.getBytes("cal", &b, sizeof b) == sizeof b && b.ver == CAL_VER) {
    GL = b.l; GEF = b.ef; GB1 = b.b1; GB2 = b.b2; PHI0 = b.phi0; GA = b.a; GA1 = b.a1; GK = b.k;
    RMAX = b.rmax; EMARG = b.emarg; TH0 = b.th0; IDX_M2 = b.idx; HOME_STEPS = b.home; LED0 = b.led0; BLT[0] = b.bl1; BLT[1] = b.bl2;
  }
  c1 = prefs.getLong("c1", 0); c2 = prefs.getLong("c2", 0); M2H = prefs.getDouble("m2hd", 0);
  lashOff[0] = prefs.getLong("lo0", 0); lashOff[1] = prefs.getLong("lo1", 0);
  for (int m = 0; m < 2; m++) { lashTgt[m] = lashOff[m]; lastDir[m] = lashOff[m] > 0 ? 1 : (lashOff[m] < 0 ? -1 : 0); }
  ph[0] = prefs.getUChar("ph0", 0) & 63; ph[1] = prefs.getUChar("ph1", 0) & 63;
  posSavedOk = prefs.getUChar("ok", 0) == 1;
  homed = posSavedOk ? prefs.getUChar("homed", 0) : 0;
  int d = prefs.getUChar("drive", 0); drive = d > 2 ? 0 : d;
  autoBoot = prefs.getUChar("aboot", 0) == 1; autoHoldS = prefs.getULong("ahold", 600); bootPending = autoBoot;
  autoMix = prefs.getUChar("amix", 2); if (autoMix > 2) autoMix = 2;
  eraseFirst = prefs.getUChar("erasef", 1) == 1;
  rehomeOn = prefs.getUChar("rehome", 1) == 1; VERASE = prefs.getFloat("verase", 550); EPITCH = constrain(prefs.getFloat("epitch", 0.02f), 0.012f, 0.06f);
  ledMode = prefs.getUChar("lmode", LM_AUTO); if (ledMode > LM_FIREFLY || ledMode == LM_IDX) ledMode = LM_AUTO;
  ledBright = prefs.getUChar("lbri", 140); ledColor = prefs.getULong("lcol", 0xFFB060); ledDrift = prefs.getUChar("ldrift", 0); ledMood = prefs.getUChar("lmood", 0); ledEvening = prefs.getUChar("leve", 1);
  ledRest = prefs.getUChar("lrest", 0); ledFillRing = prefs.getUChar("lfill", 0); ledSpeed = prefs.getFloat("lspd", 1.0f);
  SHOW_PERIOD = prefs.getFloat("lper", 20); ledMaxmA = prefs.getInt("lma", 1000);
  ledWarm = prefs.getUChar("lwarm", 1); ledTrail = prefs.getUChar("ltrail", 1); ledDith = prefs.getUChar("ldith", 2); if (ledDith > 4) ledDith = 2;
  ledPeriodMs = prefs.getUChar("lper2", 2); if (ledPeriodMs < 2 || ledPeriodMs > 17) ledPeriodMs = 2; if (ledRest > 2) ledRest = 0;
  quietOn = prefs.getUChar("qon", 0); quietFrom = prefs.getInt("qfrom", 23 * 60); quietTo = prefs.getInt("qto", 7 * 60);
  if (prefs.getUChar("skipboot", 0)) { prefs.putUChar("skipboot", 0); bootPending = false; }   // restart after an update: do not start by itself this once
  idxPassC2 = c2;
}
void saveSettings() {
  prefs.putUChar("aboot", autoBoot ? 1 : 0); prefs.putULong("ahold", autoHoldS);
  prefs.putUChar("amix", autoMix); prefs.putUChar("erasef", eraseFirst ? 1 : 0);
  prefs.putUChar("rehome", rehomeOn ? 1 : 0); prefs.putFloat("verase", VERASE); prefs.putFloat("epitch", EPITCH);
  if (!ledTmp) { prefs.putUChar("lmode", ledMode); prefs.putUChar("lbri", ledBright); prefs.putULong("lcol", ledColor); prefs.putUChar("ldrift", ledDrift); prefs.putUChar("lmood", ledMood); prefs.putUChar("leve", ledEvening);
    prefs.putUChar("lrest", ledRest); prefs.putUChar("lfill", ledFillRing); prefs.putFloat("lspd", ledSpeed);
    prefs.putFloat("lper", SHOW_PERIOD); prefs.putInt("lma", ledMaxmA);
    prefs.putUChar("lwarm", ledWarm); prefs.putUChar("ltrail", ledTrail); prefs.putUChar("ldith", ledDith); prefs.putUChar("lper2", ledPeriodMs); }
  prefs.putUChar("qon", quietOn); prefs.putInt("qfrom", quietFrom); prefs.putInt("qto", quietTo);
  settingsDirty = false;
}
void savePos() {
  prefs.putLong("c1", c1); prefs.putLong("c2", c2); prefs.putDouble("m2hd", M2H);
  prefs.putLong("lo0", lashOff[0]); prefs.putLong("lo1", lashOff[1]);
  prefs.putUChar("ph0", ph[0]); prefs.putUChar("ph1", ph[1]);
  prefs.putUChar("homed", homed); prefs.putUChar("drive", drive); prefs.putUChar("ok", 1);
  posSavedOk = true; posDirty = false;
}

// ---------------------------------------------------------------- LED ring (task, core 0)
#define LED_PIN 38
#define NLED 43
#define TICK_HZ 10000000
rmt_data_t sym[NLED * 24 + 1];
uint8_t R[NLED], G[NLED], B[NLED];
float tR[NLED], tG[NLED], tB[NLED];      // what the scene wants (0..1, as the eye sees it)
float fR[NLED], fG[NLED], fB[NLED];      // what is shown: follows the target with a soft fade
volatile uint32_t ledMarkAt = 0; volatile bool ledMarkOn = false;     // for 7 s a bright marker shows which side is the bottom of a picture
float iR[NLED], iG[NLED], iB[NLED];      // the ideal (unrounded) output of the last frame, in 0..255 counts (frame log)

// Frame log (/ledlog, measuring only): the light task copies each frame's real output bytes, the unrounded ideal
// values, a microsecond timestamp and the time it spent computing, for up to 8 chosen LEDs. Running statistics of
// frame intervals are kept all the time (/ledlog?stats=1). tools/led_smooth.py reads both.
#define LOG_MAXL 8
uint8_t* logBuf = NULL; volatile int logState = 0, logN = 0, logCap = 0, logNL = 0, logRec = 0, logK = 1, logKi = 0; uint8_t logLed[LOG_MAXL];
uint32_t logAcc[LOG_MAXL][3]; uint32_t logWork = 0;
volatile uint32_t stN = 0, stMax = 0, stG5 = 0, stG10 = 0, stG20 = 0, stG50 = 0, stWMax = 0, stLast = 0; volatile uint64_t stSum = 0, stWSum = 0;
// One record per logK frames: u32 time (us), u16 compute time (us, the largest of the k), i8 scene, u8 0, then per LED
// u16 x3 = SUM of the output bytes over the k frames (k = 1: the bytes themselves), u16 x3 = ideal x 256 (last frame).
void ledLogFrame(uint32_t t, uint32_t work, int mode) {
  if (stLast) { uint32_t g = t - stLast; stN++; stSum += g; if (g > stMax) stMax = g; if (g > 5000) stG5++; if (g > 10000) stG10++; if (g > 20000) stG20++; if (g > 50000) stG50++; }
  stLast = t; stWSum += work; if (work > stWMax) stWMax = work;
  if (logState != 1 || !logBuf) return;
  for (int k = 0; k < logNL; k++) { int i = logLed[k]; logAcc[k][0] += R[i]; logAcc[k][1] += G[i]; logAcc[k][2] += B[i]; }
  if (work > logWork) logWork = work;
  if (++logKi < logK) return;
  uint8_t* p = logBuf + (size_t)logN * logRec;
  memcpy(p, &t, 4); uint16_t w = logWork > 65535 ? 65535 : logWork; memcpy(p + 4, &w, 2); p[6] = (uint8_t)(int8_t)mode; p[7] = 0; p += 8;
  for (int k = 0; k < logNL; k++) {
    int i = logLed[k]; float v[3] = {iR[i], iG[i], iB[i]};
    for (int c = 0; c < 3; c++) {
      uint16_t a = logAcc[k][c] > 65535 ? 65535 : logAcc[k][c]; memcpy(p + 2 * c, &a, 2); logAcc[k][c] = 0;
      float x = v[c] * 256.0f; uint16_t u = x < 0 ? 0 : (x > 65535 ? 65535 : (uint16_t)(x + 0.5f)); memcpy(p + 6 + 2 * c, &u, 2);
    }
    p += 12;
  }
  logKi = 0; logWork = 0;
  if (++logN >= logCap) logState = 2;
}

void modelPolar(long t1, long t2, double& th, double& rho, double* eOut) {   // from ticks; eOut may be NULL
  double m1 = (double)t1 / TPS, m2 = (double)t2 / TPS;
  double e = GEF - GB1 * m1 + GB2 * (m2 - (double)M2H);
  double r = 2 * GL * sin(e / 2);
  double phi = PHI0 + GA * m2 + GA1 * m1 + GK * (double)M2H;
  th = phi - TH0; rho = RMAX > 0 ? r / RMAX : 0.0;
  if (eOut) *eOut = e;
}
void ledShow() {
  int k = 0;
  for (int p = 0; p < NLED; p++) {
    uint8_t by[3] = {G[p], R[p], B[p]};
    for (int c = 0; c < 3; c++) for (int b = 7; b >= 0; b--) {
      bool o = (by[c] >> b) & 1;
      sym[k].level0 = 1; sym[k].duration0 = o ? 8 : 4; sym[k].level1 = 0; sym[k].duration1 = o ? 4 : 8; k++;
    }
  }
  sym[k].level0 = 0; sym[k].duration0 = 400; sym[k].level1 = 0; sym[k].duration1 = 400;
  rmtWrite(LED_PIN, sym, NLED * 24 + 1, 100);
}
inline void setC2(int i, float v, uint32_t c) {      // LED i = colour c at level v (0..1)
  if (!(v >= 0)) v = 0; if (v > 1) v = 1;
  tR[i] = v * ((c >> 16) & 255) / 255.0f; tG[i] = v * ((c >> 8) & 255) / 255.0f; tB[i] = v * (c & 255) / 255.0f;
}
inline void addC2(int i, float v, uint32_t c) {
  if (!(v > 0)) return;
  tR[i] += v * ((c >> 16) & 255) / 255.0f; tG[i] += v * ((c >> 8) & 255) / 255.0f; tB[i] += v * (c & 255) / 255.0f;
}
inline void setPx(int i, float v) { setC2(i, v, ledNow); }
inline float ledAngle(int i) { return LED0 - i * (360.0f / NLED); }           // where LED i sits, degrees of theta
inline float angDist(float a, float b) { float d = fmodf(fabsf(a - b), 360.0f); return d > 180 ? 360 - d : d; }

// What the Automatic light does, by what the table is doing.
int sceneMode() {
  if (fault) return -1;                                           // a motor slipped: slow red pulse
  if (pauseFlag && stateV != ST_IDLE) return -2;                  // paused: slow breathing
  const char* jn = jobName;
  if (stateV != ST_IDLE && (!strcmp(jn, "home") || !strcmp(jn, "rehome"))) return -3;   // finding home: a white sweep
  if (stateV != ST_IDLE && !strncmp(nowName, "erase", 5)) return -4;                      // erasing: dim and even
  if (stateV != ST_IDLE) return LM_FOLLOW;                        // drawing: the glow follows the ball
  return ledRest == 2 ? LM_FIREFLY : (ledRest ? LM_AURORA : LM_SHOW);   // resting: the circling show light, aurora or fireflies
}

// The light runs in two layers. The SCENE (what each LED should show, as the eye sees it) is worked out about 100
// times a second. The OUTPUT stage runs every frame (500 a second by default; a 43-LED frame takes 1.4 ms on the
// wire): it fades toward the scene through two soft stages (so every change starts and ends gently, never a cut),
// applies brightness (also faded), evening warmth, the eye curve and the current cap, and then spreads each LED's
// fraction of a step over the next few frames (temporal dithering) so dim fades move in fine steps instead of
// whole 1/255 jumps. The dither is kept FAST: from 1 to 4 steps of output (where one step is a large relative change)
// its pattern repeats at least 125 times a second; below 1 step (the faintest light, where the eye is slowest) and
// from 4 to 16 steps at least 62 times; above that 31 times (one step is then under 6 %); v8.4
// dithered at 60 frames/s (pattern at 30 Hz) and Bill saw the dim reds and blues flicker.
#define SCENE_US 10000
float aR[NLED], aG[NLED], aB[NLED];      // first fade stage (fR.. is the second, the one shown)
float dE[NLED * 3];                      // dither error carried to the next frame, per LED and colour
float heat[NLED];                        // where the ball has been lately (the trail behind the follow glow)
volatile bool ledTx = false;             // a frame is on the wire; flashBegin() waits for it (flash writes stall the RMT refill)

float eveningFactor(float* warmOut) {    // evening dimming 1 .. 0.35 and how far into the evening (0..1), to the second
  float eve = 1.0f;
  if (ledEvening && clockSet()) {
    time_t t = time(NULL); struct tm tmv; localtime_r(&t, &tmv);
    float hr = tmv.tm_hour + tmv.tm_min / 60.0f + tmv.tm_sec / 3600.0f;
    if (hr >= 22 || hr < 6) eve = 0.35f; else if (hr >= 19) eve = 1.0f - 0.65f * (hr - 19) / 3.0f; else if (hr < 8) eve = 0.35f + 0.65f * (hr - 6) / 2.0f;
  }
  if (warmOut) *warmOut = (1.0f - eve) / 0.65f;
  return eve;
}

void ledScene(int m, float dt, uint32_t nowMs) {
  static float head = 0;
  float tsec = (nowMs % 1140000UL) / 1000.0f;                   // wraps on a common multiple of the 2.5, 3, 4 and 19 s cycles
  if (ledDrift) {                                               // amber -> rose -> violet -> teal -> amber, 8 minutes round
    static const uint32_t pal[4] = {0xFFB060, 0xFF7A6E, 0xA78BFF, 0x5FD0C0};
    static float dph = 0; dph = fmodf(dph + dt * ledSpeed / 120.0f, 4.0f);
    float t = dph; int a = (int)t, b2 = (a + 1) & 3; float f = t - a;
    uint32_t ca = pal[a], cb = pal[b2];
    int r = ((ca >> 16) & 255) * (1 - f) + ((cb >> 16) & 255) * f, g = ((ca >> 8) & 255) * (1 - f) + ((cb >> 8) & 255) * f, bl = (ca & 255) * (1 - f) + (cb & 255) * f;
    ledNow = ((uint32_t)r << 16) | ((uint32_t)g << 8) | bl;
  } else if (ledMood && nowName[0] && strncmp(nowName, "erase", 5)) {     // a colour mood per piece, the same every time for the same piece
    static const uint32_t moods[6] = {0xFFB060, 0xFFF0D8, 0xFF8A70, 0x7FD8C8, 0xB49CFF, 0xFFD070};
    uint32_t h = 2166136261u; for (const char* q2 = nowName; *q2; q2++) h = (h ^ (uint8_t)*q2) * 16777619u;
    ledNow = moods[h % 6];
  } else ledNow = ledColor;
  for (int i = 0; i < NLED; i++) { tR[i] = tG[i] = tB[i] = 0; }
  float hk = expf(-dt / 25.0f);                                 // the trail fades over about 25 s
  for (int i = 0; i < NLED; i++) heat[i] *= hk;
  if (m == LM_OFF) { }
  else if (m == LM_SOLID) { for (int i = 0; i < NLED; i++) setPx(i, 1); }
  else if (m == LM_IDX) { setPx(ledIdx, 1.0f); }
  else if (m == LM_ARC) {                                        // soft-edged arc centred on LED ledIdx: light from one side
    for (int i = 0; i < NLED; i++) {
      float d = fabsf((float)(i - ledIdx)); if (d > NLED / 2.0f) d = NLED - d;
      setPx(i, (ledArcW - d) / 1.5f + 0.5f);
    }
  } else if (m == LM_SHOW) {                                     // key light from one side, a cool fill opposite, slowly circling
    static float showPh = 0; showPh = fmodf(showPh + dt * ledSpeed / SHOW_PERIOD, 1.0f);
    float A = showPh * 360.0f;
    for (int i = 0; i < NLED; i++) {
      float d = angDist(ledAngle(i), A);
      float key = d < 62 ? powf(cosf(d * (float)M_PI / 124.0f), 1.6f) : 0;
      float fil = d > 118 ? 0.38f * powf(cosf((180 - d) * (float)M_PI / 124.0f), 1.6f) : 0;
      setC2(i, key, ledNow); addC2(i, fil, ledFill);
    }
  } else if (m == LM_AURORA) {                                   // slow soft colour waves moving round the ring (stock "Aurora Flow")
    static float a1 = 0, a2 = 0, a3 = 0;                        // three wave phases, each kept within one turn
    a1 = fmodf(a1 + dt * ledSpeed * 0.44f, 2 * (float)M_PI); a2 = fmodf(a2 + dt * ledSpeed * 0.28f, 2 * (float)M_PI); a3 = fmodf(a3 + dt * ledSpeed * 0.20f, 2 * (float)M_PI);
    static const uint32_t au[3] = {0x40E0B0, 0x6080FF, 0xB070FF};
    for (int i = 0; i < NLED; i++) {
      float x = i * (2 * (float)M_PI / NLED);
      float w1 = 0.5f + 0.5f * sinf(x * 2 + a1), w2 = 0.5f + 0.5f * sinf(x * 3 - a2 + 1.3f), w3 = 0.5f + 0.5f * sinf(x - a3 + 2.9f);
      setC2(i, 0.55f * w1 * w1, au[0]); addC2(i, 0.5f * w2 * w2, au[1]); addC2(i, 0.45f * w3 * w3, au[2]);
    }
  } else if (m == LM_FIREFLY) {                                  // a few soft lights swelling and fading at random places (stock "Firefly Flicker", slowed right down)
    #define NFF 5
    static float fp[NFF], fage[NFF], flife[NFF], famp[NFF]; static bool fInit = false;
    if (!fInit) { for (int k = 0; k < NFF; k++) { fage[k] = 0; flife[k] = 1; famp[k] = 0; fp[k] = 0; } fInit = true; }
    for (int i = 0; i < NLED; i++) setPx(i, 0.035f);            // a faint even base so the bowl never goes fully dark
    for (int k = 0; k < NFF; k++) {
      fage[k] += dt * ledSpeed;
      if (fage[k] >= flife[k]) {                                // rest, then come back somewhere else
        fage[k] = -rndF(0.5f, 6.0f); flife[k] = rndF(5.0f, 10.0f); famp[k] = rndF(0.45f, 1.0f); fp[k] = rndF(0, 360);
      }
      if (fage[k] <= 0) continue;
      float s = sinf((float)M_PI * fage[k] / flife[k]), env = famp[k] * s * s;   // raised-cosine swell: no edge anywhere
      for (int i = 0; i < NLED; i++) { float d = angDist(ledAngle(i), fp[k]) / 11.0f; if (d < 3.5f) addC2(i, env * expf(-d * d), ledNow); }
    }
  } else if (m == LM_BREATH478) {                                // breathing guide: brighten 4 s, hold 7 s, fade 8 s (stock "Breathing Exercise 4-7-8")
    float t = fmodf(tsec, 19.0f), v = t < 4 ? t / 4 : (t < 11 ? 1.0f : 1.0f - (t - 11) / 8);
    v = 0.08f + 0.92f * (0.5f - 0.5f * cosf(v * (float)M_PI));
    for (int i = 0; i < NLED; i++) setPx(i, v);
  } else if (m == LM_BREATHE || m == -2) {
    float v = m == -2 ? 0.25f + 0.2f * sinf(tsec * (2 * (float)M_PI / 3.0f)) : 0.2f + 0.8f * (0.5f + 0.5f * sinf(tsec * (2 * (float)M_PI / 4.0f)));
    for (int i = 0; i < NLED; i++) setPx(i, v);
  } else if (m == -1) {
    float v = 0.3f + 0.25f * sinf(tsec * (2 * (float)M_PI / 2.5f));
    for (int i = 0; i < NLED; i++) setC2(i, v, 0xFF2408);
  } else if (m == -4) { for (int i = 0; i < NLED; i++) setPx(i, 0.35f); }
  else if (m == LM_COMET || m == -3) {
    head += dt * 12.0f; if (head >= NLED) head -= NLED;
    for (int i = 0; i < NLED; i++) {
      float d = fabsf(i - head); if (d > NLED / 2.0f) d = NLED - d;
      setC2(i, (m == -3 ? 0.12f : 0.0f) + expf(-d * 0.6f), m == -3 ? 0xFFF4E0 : (uint32_t)ledNow);
    }
  } else if (m == LM_FOLLOW) {
    double th, rho; modelPolar(c1, c2, th, rho, NULL);
    float deg = (float)((th + TH0) * 180.0 / M_PI); if (rho < 0) { deg += 180; rho = -rho; }
    float rr = rho > 1 ? 1 : (float)rho;
    float w = LEDW + 150.0f * (1 - rr) * (1 - rr), base = LEDBASE + 0.5f * (1 - rr) * (1 - rr);
    bool drawing = stateV != ST_IDLE;
    for (int i = 0; i < NLED; i++) {
      float d = angDist(ledAngle(i), deg);
      if (ledTrail && drawing) { float q = d / 9.0f; heat[i] += dt * 0.16f * expf(-q * q); if (heat[i] > 1) heat[i] = 1; }
      setPx(i, base + (1 - base) * expf(-(d / w) * (d / w)));
      addC2(i, 0.22f * rr * powf(d / 180.0f, 2.0f), ledFill);               // a cool tone on the far side from the ball
      if (ledTrail) addC2(i, 0.30f * heat[i], ledNow);                       // a soft memory of where the ball has just been
      if (ledFillRing && drawing && i < (int)(progress * NLED)) addC2(i, 0.10f, ledNow);   // the ring fills as the piece progresses
    }
  } else {                                                      // progress
    float lit = (stateV == ST_IDLE ? 0.0f : progress) * NLED;
    for (int i = 0; i < NLED; i++) { float v = lit - i; setPx(i, v >= 1 ? 1 : (v > 0 ? v : 0)); }
  }
  if (ledMarkOn && nowMs - ledMarkAt > 7000) ledMarkOn = false;
  if (ledMarkOn) {                    // orientation marker: one bright spot at the bottom of pictures
    float down = (float)(TH0 * 180.0 / M_PI) - 90.0f;
    for (int i = 0; i < NLED; i++) { float d = angDist(ledAngle(i), down); setC2(i, d < 5 ? 1.0f : (d < 13 ? 0.35f : 0.04f), 0xFFF4E0); }
  }
}

// How many bits of dither a value v (output steps) may use at F frames/s: the pattern must repeat fast enough.
inline int ditherBits(float v, float F) {
  float fmin = v < 1 ? 62.0f : (v < 4 ? 125.0f : (v < 16 ? 62.0f : 31.0f)), P = F / fmin;
  int b = P >= 16 ? 4 : (P >= 8 ? 3 : (P >= 4 ? 2 : (P >= 2 ? 1 : 0)));
  return b < ledDith ? b : ledDith;
}

void ledTask(void*) {
  if (!rmtInit(LED_PIN, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_4, TICK_HZ))   // 4 blocks: the refill interrupt has 4x longer to answer
    rmtInit(LED_PIN, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_1, TICK_HZ);
  for (int i = 0; i < NLED * 3; i++) dE[i] = ((i * 5) % 16) / 16.0f - 0.5f;   // stagger the dither so the LEDs do not pulse together
  uint32_t lastUs = micros(), lastScene = 0, boostAt = 0; int lastM = -99; bool boosting = false;
  float brS1 = -1, brS = 0, warmS = 0, eve = 1, warm = 0;
  TickType_t wake = xTaskGetTickCount();
  for (;;) {
    uint32_t t0us = micros(), nowMs = millis();
    float dt = (t0us - lastUs) / 1e6f; lastUs = t0us; if (dt > 0.2f) dt = 0.2f;
    int m = ledMode;
    if (m == LM_AUTO) m = sceneMode();
    if (m != lastM) { if (lastM != -99) { boostAt = nowMs; boosting = true; } lastM = m; lastScene = 0; }
    if (!lastScene || t0us - lastScene >= SCENE_US) {
      float sdt = lastScene ? (t0us - lastScene) / 1e6f : 0.0f; if (sdt > 0.2f) sdt = 0.2f;
      lastScene = t0us ? t0us : 1;
      ledCap = quietNow() ? 50 : 255;
      eve = eveningFactor(&warm);
      ledScene(m, sdt, nowMs);
    }
    // Fade: two first-order stages in a row. 0.18 s each normally (about like the old 0.35 s fade, but starting and
    // ending gently); for 2.5 s after the scene changes, up to 0.6 s each, so one scene dissolves into the next.
    float tau = 0.18f;
    if (boosting) { float u = (nowMs - boostAt) / 2500.0f; if (u >= 1) boosting = false; else tau = 0.18f + 0.42f * (1 - u); }
    float kf = ledLin ? 1.0f : 1.0f - expf(-dt / tau);
    float brT = (ledBright < ledCap ? ledBright : ledCap) / 255.0f * (ledLin ? 1.0f : eve);
    if (brS1 < 0 || ledLin) { brS1 = brS = brT; }               // brightness changes glide too (about 1 s), e.g. when quiet hours begin
    else { float kb = 1.0f - expf(-dt / 0.3f); brS1 += (brT - brS1) * kb; brS += (brS1 - brS) * kb; }
    float wT = ledWarm && !ledLin ? warm : 0.0f; warmS += (wT - warmS) * (1.0f - expf(-dt / 2.0f));
    float wG = 1.0f - 0.30f * warmS, wB = 1.0f - 0.65f * warmS;   // evening warmth: green and blue drawn down, like a lower colour temperature
    float br = brS, sum = 0;
    static float oR[NLED], oG[NLED], oB[NLED];
    for (int i = 0; i < NLED; i++) {
      aR[i] += (tR[i] - aR[i]) * kf; aG[i] += (tG[i] - aG[i]) * kf; aB[i] += (tB[i] - aB[i]) * kf;
      fR[i] += (aR[i] - fR[i]) * kf; fG[i] += (aG[i] - fG[i]) * kf; fB[i] += (aB[i] - fB[i]) * kf;
      // The eye correction is applied to each LED's LEVEL (its brightest channel), not per colour, so dim amber stays amber.
      float mx = fR[i] > fG[i] ? fR[i] : fG[i]; if (fB[i] > mx) mx = fB[i];
      float lvl = mx * br; if (lvl > 1) lvl = 1;
      float g = ledLin ? br : br * lvl;
      oR[i] = fR[i] * g * 255; oG[i] = fG[i] * wG * g * 255; oB[i] = fB[i] * wB * g * 255; sum += oR[i] + oG[i] + oB[i];
    }
    float mA = sum / 255.0f * 20.0f, sc = mA > ledMaxmA ? ledMaxmA / mA : 1.0f;
    // the button's acknowledge flash: a quick soft swell of warm light added on top, scaled to the room's brightness
    float fl = 0;
    if (ledFlashOn) {
      uint32_t a = millis() - ledFlashAt;
      if (a > 1100) ledFlashOn = false;
      else { float x = a / 70.0f; fl = a < 70 ? x * x * (3 - 2 * x) : expf(-((float)a - 70.0f) / 220.0f); float s = br / 0.55f; fl *= s < 0.2f ? 0.2f : (s > 1 ? 1 : s); }
    }
    float F = 1000.0f / ledPeriodMs;
    for (int i = 0; i < NLED; i++) {
      float v[3] = {oR[i] * sc + 90 * fl, oG[i] * sc + 70 * fl, oB[i] * sc + 40 * fl};
      iR[i] = v[0]; iG[i] = v[1]; iB[i] = v[2];
      uint8_t o8[3];
      for (int c = 0; c < 3; c++) {
        float x = v[c]; if (x > 255) x = 255; if (!(x > 0)) x = 0;
        int bits = ledLin ? 0 : ditherBits(x, F); int o;
        if (bits == 0) o = (int)(x + 0.5f);
        else {
          float S = (float)(1 << bits), q = floorf(x * S + 0.5f) / S, y = q + dE[i * 3 + c];
          o = (int)floorf(y + 0.5f); dE[i * 3 + c] = y - o;
          if (o > 255) { o = 255; dE[i * 3 + c] = 0; } if (o < 0) { o = 0; dE[i * 3 + c] = 0; }
        }
        o8[c] = o > 255 ? 255 : o;
      }
      R[i] = o8[0]; G[i] = o8[1]; B[i] = o8[2];
    }
    { uint32_t tf = micros(); ledLogFrame(tf, tf - t0us, m); }
    ledTx = true; __sync_synchronize();
    if (!webFlash) ledShow();                                    // never start a frame while flash is being written
    ledTx = false;
    int per = ledPeriodMs; TickType_t now = xTaskGetTickCount();
    if ((int32_t)(now - wake) > 4 * per) wake = now;             // after a long stall, do not rush to catch up
    vTaskDelayUntil(&wake, pdMS_TO_TICKS(per));
  }
}

// ---------------------------------------------------------------- HTTP (task, core 0)
inline bool busy() { return jobPending || stateV != ST_IDLE || guestState.pending; }
bool flashBegin() {                    // web task: may I write flash now?
  for (int i = 0; i < 40; i++) {       // the motion task holds seqBusy for a few microseconds every 5 ms even when idle: retry
    webFlash = true; webFlashMs = millis(); __sync_synchronize();
    for (int w = 0; ledTx && w < 5; w++) vTaskDelay(1);   // let a light frame already on the wire finish (its refill interrupt stops while flash is written)
    if (!seqBusy && stateV == ST_IDLE && !jobPending) return true;
    webFlash = false;
    if (stateV != ST_IDLE || jobPending) return false;
    delay(1);
  }
  return false;
}
inline void flashEnd() { webFlash = false; }
inline bool homedOk() { return (homed || rehoming) && !fault; }
void reply(int code, const String& s) { server.send(code, "text/plain", s + "\n"); }

void submit(const Job& j) {
  if (!homedOk() && j.type != JT_RAW && j.type != JT_HOME && server.arg("unhomed") != "1") {
    reply(409, "not homed: polar moves need /home first (or unhomed=1 to override)"); return;
  }
  if (busy()) {
    if (server.arg("force") != "1") { reply(409, "busy: a job is running (use force=1 or /stop)"); return; }
    if (guestState.pending) { clearSteps(); forgetGuest(); }
    jobPending = false;
    if (stateV != ST_IDLE) stopFlag = true;
    uint32_t t0 = millis(); while (stateV != ST_IDLE && millis() - t0 < 500) delay(2);
  }
  if (posSavedOk) {                      // a reboot during the job must not trust the saved position
    for (int i = 0; i < 100 && !flashBegin(); i++) delay(5);
    prefs.putUChar("ok", 0); posSavedOk = false; flashEnd();
  }
  jobBuf = j;
  __sync_synchronize();
  jobPending = true;
  reply(200, String("started ") + j.name);
}
float clamp01(float v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

const char* stateStr() {
  if (stateV == ST_IDLE) return jobPending ? "moving" : "idle";
  if (stopFlag) return "stopping";
  return stateV == ST_MOVING ? "moving" : "drawing";
}
const char* driveStr() { return drive == 2 ? "sine" : (drive == 1 ? "half" : "full"); }
void hStatus() {
  portENTER_CRITICAL(&stepMux);
  long t1 = c1, t2 = c2;
  int receipt = tagRev == guestState.rev ? tagState : TAG_NONE;
  const char* observedState = stateStr();
  portEXIT_CRITICAL(&stepMux);
  double th, rho, e; modelPolar(t1, t2, th, rho, &e);
  float v = curV;
  char x[640]; int xn = 0;                 // v8 fields: what is drawing, the queue, time left, clock, quiet hours
  float pr = progress; uint32_t el = millis() - jobT0;
  long eta = (stateV != ST_IDLE && pr > 0.03f && pr < 1.0f) ? (long)((double)el * (1.0 - pr) / pr / 1000.0) : 0;
  char tm_s[8] = "";
  if (clockSet()) { int m = nowMinutes(); snprintf(tm_s, sizeof tm_s, "%02d:%02d", m / 60, m % 60); }
  xn += snprintf(x + xn, sizeof x - xn, ",\"now\":\"%s\",\"eta_s\":%ld,\"time\":\"%s\",\"quiet\":%d,\"quiet_on\":%d,\"quiet_from\":%d,\"quiet_to\":%d,"
                 "\"down\":%.0f,\"erase_first\":%d,\"unchecked\":%d,\"auto_mix\":%d,\"rehome\":%d,\"verase\":%.0f,\"fs\":%d,\"fs_free\":%lu,\"queue\":[",
                 nowName, eta, tm_s, quietNow() ? 1 : 0, (int)quietOn, (int)quietFrom, (int)quietTo, TH0 * 180.0 / M_PI - 90.0, eraseFirst ? 1 : 0, (int)unchecked, (int)autoMix, rehomeOn ? 1 : 0, (double)VERASE,
                 fsOk ? 1 : 0, (unsigned long)fsFree);
  portENTER_CRITICAL(&stepMux);
  Step qs[NSTEP]; int qn2 = stepN; for (int i = 0; i < qn2; i++) qs[i] = steps[i];
  portEXIT_CRITICAL(&stepMux);
  for (int i = 0; i < qn2 && xn < (int)sizeof x - 48; i++) {
    const char* nm = qs[i].kind == SK_GUEST ? "guest drawing" : qs[i].kind == SK_REHOME ? "check" : qs[i].kind == SK_BG ? "erase" : (qs[i].kind == SK_FILE ? qs[i].name :
                     (qs[i].g.kind == GK_ERASE_OUT || qs[i].g.kind == GK_ERASE_IN ? "erase" : "new piece"));
    xn += snprintf(x + xn, sizeof x - xn, "%s\"%s\"", i ? "," : "", nm);
  }
  xn += snprintf(x + xn, sizeof x - xn, "]");
  char b[2700];
  snprintf(b, sizeof b,
    "{\"fw\":\"" FW_NAME "\",\"state\":\"%s\",\"job\":\"%s\",\"progress\":%.4f,\"index\":%ld,\"total\":%ld,\"pass\":%ld,"
    "\"cur1\":%.3f,\"cur2\":%.3f,\"theta\":%.5f,\"rho\":%.5f,\"e\":%.5f,\"r\":%.5f,\"speed\":%.0f,\"step_us\":%d,\"start_us\":%d,\"min_us\":%d,"
    "\"homed\":%d,\"drive\":\"%s\",\"amp\":%.2f,\"decay\":%d,\"vmax\":%.0f,\"vj\":%.0f,\"acc\":%.0f,\"accc\":%.0f,"
    "\"steps_rev\":%.0f,\"home_steps\":%ld,\"m2h\":%.3f,\"home_err\":%d,\"fault\":%d,\"paused\":%d,\"idx\":%d,\"idx_err\":%.2f,\"idx_n\":%ld,\"bl1\":%.1f,\"bl2\":%.1f,\"m1_centre\":%.0f,\"m1_rim\":%.0f,"
    "\"cal\":{\"l\":%.6g,\"ef\":%.6g,\"b1\":%.6g,\"b2\":%.6g,\"phi0\":%.6g,\"a\":%.6g,\"a1\":%.6g,\"k\":%.6g,"
    "\"rmax\":%.4g,\"emarg\":%.4g,\"th0\":%.6g},\"led0\":%.1f,\"saved\":%d,\"auto\":%d,\"auto_boot\":%d,\"auto_hold\":%lu,\"auto_wait\":%ld,\"auto_phase\":%d,\"auto_pieces\":%ld,\"led_mode\":%d,\"led_b\":%d,\"led_c\":\"%06lx\",\"led_drift\":%d,\"led_mood\":%d,\"led_evening\":%d,\"led_rest\":%d,\"led_fill\":%d,\"led_speed\":%.2f,\"led_warm\":%d,\"led_trail\":%d,\"led_hz\":%d,\"led_dith\":%d,\"gen\":\"%s\","
    "\"pattern_points\":%ld,\"uptime_ms\":%lu,\"free_heap\":%u,\"boot_pending\":%d,\"device_id\":\"%s\",\"receipt\":{\"id\":\"%s\",\"state\":\"%s\"}%s}",
    observedState, (const char*)jobName, (double)progress, (long)ptIdx, (long)ptTotal, (long)passNo,
    (double)t1 / TPS, (double)t2 / TPS, th, rho, e, rho * RMAX, (double)v, v > 0 ? (int)(1e6f / v) : 0, (int)(1e6f / VJ), (int)(1e6f / VMAX),
    (int)(homed || rehoming), driveStr(), (double)AMP, (int)decay, (double)VMAX, (double)VJ, (double)ACC, (double)ACCC,
    2 * M_PI / GA, (long)HOME_STEPS, (double)M2H, (int)homeErr, (int)fault, pauseFlag ? 1 : 0, (int)digitalRead(IDX_PIN), (double)idxErr, (long)idxN, (double)BLT[0] / TPS, (double)BLT[1] / TPS,
    (GEF - 2 * M_PI) / GB1, (GEF - (2 * M_PI - 2 * asin(fmin(0.999, RMAX / (2 * GL))))) / GB1,
    (double)GL, (double)GEF, (double)GB1, (double)GB2, (double)PHI0, (double)GA, (double)GA1, (double)GK,
    (double)RMAX, (double)EMARG, (double)TH0, (double)LED0, posSavedOk ? 1 : 0, autoOn ? 1 : 0, autoBoot ? 1 : 0, (unsigned long)autoHoldS,
    (long)(autoOn && stateV == ST_IDLE ? ((int32_t)(autoNextMs - millis()) > 0 ? (int32_t)(autoNextMs - millis()) / 1000 : 0) : 0),
    (int)autoPhase, (long)autoCount, (int)ledMode, (int)ledBright, (unsigned long)ledColor, (int)ledDrift, (int)ledMood, (int)ledEvening, (int)ledRest, (int)ledFillRing, (double)ledSpeed, (int)ledWarm, (int)ledTrail, 1000 / ledPeriodMs, (int)ledDith, genDesc,
    (long)patN, (unsigned long)millis(), (unsigned)ESP.getFreeHeap(), bootPending ? 1 : 0,
    boardId, receipt == TAG_NONE ? "" : tagId, tagNames[receipt], x);
  server.send(200, "application/json", b);
}

const char PAGE[] PROGMEM = R"HTML(<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Oasis</title>
<style>
:root{color-scheme:light}
body{font:17px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;background:#f6f4ef;margin:0}
main{max-width:520px;margin:0 auto;padding:16px}
h1{font-size:24px;margin:6px 0 10px}
.card{background:#fff;border-radius:14px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h2{font-size:14px;margin:0 0 8px;color:#6b6b70;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
#now{font-size:20px;font-weight:600} #sub{color:#6b6b70;font-size:15px;margin-top:2px}
.bar{height:8px;background:#e8e4da;border-radius:4px;margin-top:10px;overflow:hidden} .bar div{height:100%;background:#c9772b;width:0}
button{font:inherit;padding:11px 14px;margin:4px 4px 4px 0;border-radius:10px;border:1px solid #d6d1c4;background:#faf8f3;color:#1d1d1f}
button.on{background:#1d1d1f;color:#fff;border-color:#1d1d1f} button.stop{background:#b3261e;color:#fff;border-color:#b3261e}
input[type=range]{width:100%} details{color:#6b6b70;font-size:13px} pre{white-space:pre-wrap;word-break:break-all}
#msg{color:#6b6b70;font-size:14px;min-height:20px}
</style></head><body><main>
<h1>Oasis</h1>
<div class=card><div id=now>...</div><div id=sub></div><div class=bar><div id=bar></div></div></div>
<div class=card><h2>Drawing</h2>
<button id=aon onclick="c('/auto?on=1')">Let it draw by itself now</button>
<button class=stop onclick="c('/stop')">Stop</button><br>
<button onclick="c('/gen?kind=random')">One new piece</button>
<button onclick="c('/gen?kind=erase_out')">Erase</button>
<button onclick="c('/home')">Find home</button>
<div id=msg></div></div>
<div class=card><h2>Light</h2>
<button id=l6 onclick="c('/led?mode=follow&c=ffb060')">Follow the ball</button>
<button id=l1 onclick="c('/led?mode=solid&c=fff4e0')">Even</button>
<button id=l7 onclick="c('/led?mode=arc&i=12&aw=5&c=fff4e0')">From one side</button>
<button id=l0 onclick="c('/led?mode=off')">Off</button>
<input id=br type=range min=0 max=255 onchange="c('/led?b='+this.value)"></div>
<div class=card><h2>Next time it is powered up</h2>
<button id=b1 onclick="c('/auto?boot=1')">Start by itself</button>
<button id=b0 onclick="c('/auto?boot=0')">Wait for me</button>
<div id=hold style="color:#6b6b70;font-size:14px"></div></div>
<details><summary>Details</summary><pre id=raw></pre></details>
<script>
var K={bloom:'a flower',vortex:'a turning shape',weave:'a woven spiral',arms:'a pinwheel',erase_out:'erasing',erase_in:'erasing'};
function c(u){fetch(u).then(function(x){return x.text()}).then(function(t){msg.textContent=t.trim();p()})}
function cls(id,on){document.getElementById(id).className=on?'on':''}
function p(){fetch('/status').then(function(x){return x.json()}).then(function(d){
 var g=(d.gen||'').split(' ')[0],what=K[g]||'a pattern',t,s2='';
 if(d.fault)t='Stopped: a motor slipped. Press Find home.';
 else if(!d.homed&&d.state=='idle')t='Not homed yet. Press Find home.';
 else if(d.job=='home'&&d.state!='idle')t='Finding home';
 else if(d.state=='drawing'){t=(g.indexOf('erase')==0?'Erasing':'Drawing '+what);s2=Math.round(d.progress*100)+'% done';}
 else if(d.state=='moving')t='Moving';
 else if(d.auto&&d.auto_wait>0){t='Finished piece on show';s2='Next one starts in '+Math.ceil(d.auto_wait/60)+' min';}
 else t='Idle';
 now.textContent=t;sub.textContent=s2+(d.auto?(s2?' · ':'')+'drawing by itself, '+d.auto_pieces+' made':'');
 bar.style.width=(d.state=='idle'?0:Math.round(d.progress*100))+'%';
 cls('aon',d.auto);cls('b1',d.auto_boot);cls('b0',!d.auto_boot);
 [0,1,6,7].forEach(function(m){cls('l'+m,d.led_mode==m)});
 if(document.activeElement!=br)br.value=d.led_b;
 hold.textContent='A finished piece stays on show for '+Math.round(d.auto_hold/60)+' minutes.';
 raw.textContent=JSON.stringify(d,null,1);
}).catch(function(e){now.textContent='Table not answering'})}
setInterval(p,1500);p();
</script></main></body></html>)HTML";

void hCfg() {
  int nd = -1;
  if (server.hasArg("half")) nd = server.arg("half").toInt() ? 1 : 0;
  if (server.hasArg("drive")) { String d = server.arg("drive"); nd = d == "sine" ? 2 : (d == "half" ? 1 : (d == "full" ? 0 : -1)); }
  if (nd >= 0 && nd != drive) {
    if (busy()) { reply(409, "busy: drive switch needs idle"); return; }
    setDrive(nd); posDirty = true;
  }
  if (server.hasArg("amp"))   AMP   = constrain(server.arg("amp").toFloat(), 0.2f, 1.6f);
  if (server.hasArg("decay")) decay = server.arg("decay").toInt() ? 1 : 0;
  if (server.hasArg("start")) VJ    = 1e6f / constrain(server.arg("start").toInt(), 300, 20000);
  if (server.hasArg("min"))   VMAX  = 1e6f / constrain(server.arg("min").toInt(), 300, 20000);
  if (server.hasArg("vmax"))  VMAX  = constrain(server.arg("vmax").toFloat(), 50.0f, 3000.0f);
  if (server.hasArg("vj"))    VJ    = constrain(server.arg("vj").toFloat(), 40.0f, 3000.0f);
  if (server.hasArg("acc"))   ACC   = constrain(server.arg("acc").toFloat(), 10.0f, 20000.0f);
  if (server.hasArg("accc"))  ACCC  = constrain(server.arg("accc").toFloat(), 10.0f, 100000.0f);
  if (server.hasArg("down") || server.hasArg("turn")) {       // which side of the table is the bottom of a picture (degrees, table frame)
    if (busy() || stepN) { reply(409, "wait until it has finished drawing"); return; }
    double d = server.hasArg("down") ? server.arg("down").toDouble() : TH0 * 180.0 / M_PI - 90.0 + server.arg("turn").toDouble();
    d = fmod(d, 360.0); if (d > 180) d -= 360; if (d < -180) d += 360;
    forgetGuest();
    TH0 = (d + 90.0) * M_PI / 180.0; calDirty = true; ledMarkAt = millis(); ledMarkOn = true;
  }
  if (server.hasArg("mark")) { ledMarkAt = millis(); ledMarkOn = true; }
  if (server.hasArg("quiet_on"))   { quietOn = server.arg("quiet_on").toInt() ? 1 : 0; settingsDirty = true; }
  if (server.hasArg("quiet_from")) { quietFrom = constrain(server.arg("quiet_from").toInt(), 0, 1439); settingsDirty = true; }
  if (server.hasArg("quiet_to"))   { quietTo = constrain(server.arg("quiet_to").toInt(), 0, 1439); settingsDirty = true; }
  if (server.hasArg("rehome"))     { rehomeOn = server.arg("rehome").toInt() != 0; settingsDirty = true; }
  if (server.hasArg("erase_first")) { eraseFirst = server.arg("erase_first").toInt() != 0; settingsDirty = true; }
  if (server.hasArg("epitch"))     { EPITCH = constrain(server.arg("epitch").toFloat(), 0.012f, 0.06f); settingsDirty = true; }
  if (server.hasArg("verase"))     { VERASE = constrain(server.arg("verase").toFloat(), 100.0f, 700.0f); settingsDirty = true; }
  if (server.hasArg("bl1"))   BLT[0] = (int)(constrain(server.arg("bl1").toFloat(), 0.0f, 300.0f) * TPS);
  if (server.hasArg("bl2"))   BLT[1] = (int)(constrain(server.arg("bl2").toFloat(), 0.0f, 300.0f) * TPS);
  reply(200, String("drive=") + driveStr() + " amp=" + String((double)AMP, 2) + " decay=" + String(decay) + " vmax=" + String((double)VMAX, 0) +
             " vj=" + String((double)VJ, 0) + " acc=" + String((double)ACC, 0) + " accc=" + String((double)ACCC, 0) +
             " bl1=" + String((double)BLT[0] / TPS, 1) + " bl2=" + String((double)BLT[1] / TPS, 1));
}

void hInputs() {
  if (server.hasArg("pull")) { String p = server.arg("pull"); watchInit(p == "up" ? 1 : (p == "down" ? 2 : 0)); }
  if (server.arg("clear") == "1") { portENTER_CRITICAL(&evMux); evHead = 0; evTotal = 0; for (unsigned i = 0; i < NW; i++) wCount[i] = 0; portEXIT_CRITICAL(&evMux); }
  String s = "{\"levels\":{";
  for (unsigned i = 0; i < NW; i++) { s += "\"" + String(WPINS[i]) + "\":" + String(digitalRead(WPINS[i])); if (i + 1 < NW) s += ","; }
  s += "},\"changes\":{";
  bool first = true;
  for (unsigned i = 0; i < NW; i++) if (wCount[i]) { if (!first) s += ","; first = false; s += "\"" + String(WPINS[i]) + "\":" + String(wCount[i]); }
  s += "},\"total\":" + String((long)evTotal) + ",\"events\":[";
  long n = evTotal < NEV ? evTotal : NEV; int start = (evHead + NEV - (int)n) % NEV;
  for (long i = 0; i < n; i++) {
    Ev& e = evs[(start + i) % NEV];
    char b[96]; snprintf(b, sizeof b, "%s[%lu,%d,%d,%.2f,%.2f]", i ? "," : "", (unsigned long)e.ms, e.pin, e.level, (double)e.c1 / TPS, (double)e.c2 / TPS);
    s += b;
  }
  s += "]}\n";
  server.send(200, "application/json", s);
}

bool tagIdle() {
  return homed && !busy() && !rehoming && !fault && !pauseFlag && !stopFlag && !stepN &&
    !autoOn && !bootPending && !guestState.evolving && !restartAt;
}
bool tagAt(float targetTheta, float targetRadius) {
  double theta, rho;
  modelPolar(c1, c2, theta, rho, NULL);
  return fabs(remainder(theta - targetTheta, 2 * M_PI)) <= .002 && fabs(rho - targetRadius) <= .001;
}
uint32_t patternCrc() {
  return esp_crc32_le(0, (const uint8_t*)pat, (uint32_t)patN * sizeof(Pt));
}
void taggedPlay(const String& id) {
  if (!tagIdle() || !flashBegin()) { reply(409, "table is not available"); return; }
  // Hold off the motion core through the final comparison and publication of the job.
  if (!tagIdle() || server.header("X-Oasis-Device") != boardId || id != tagId || tagState != TAG_STAGED || tagRev != guestState.rev ||
      patN < 2 || patternCrc() != tagCrc || !tagAt(pat[0].theta, pat[0].rho)) {
    flashEnd(); reply(409, "staged drawing or starting position changed"); return;
  }
  if (posSavedOk) {
    if (prefs.putUChar("ok", 0) != 1) { flashEnd(); reply(503, "could not save motion intent"); return; }
    posSavedOk = false;
  }
  Job j = {}; j.type = JT_PLAY; j.name = "play"; j.tagged = true;
  strlcpy(nowName, "shared garden", sizeof nowName);
  portENTER_CRITICAL(&stepMux);
  tagState = TAG_RUNNING; jobBuf = j; jobPending = true;
  portEXIT_CRITICAL(&stepMux);
  flashEnd(); reply(200, "started tagged drawing");
}

void thrRaw() {                         // streamed body of POST /thr
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    lineLen = 0; lineOver = false; upN = 0; upSkipped = 0; upOverflow = false;
    upReject = busy() || guestState.pending; upNoMem = (pat == NULL);
    String id = server.header("X-Oasis-Run");
    tagUpload = false;
    if (id.length()) {
      bool valid = id.length() == 64;
      for (unsigned i = 0; valid && i < id.length(); i++) valid = isxdigit((unsigned char)id[i]);
      if (valid && !upNoMem && tagIdle() && flashBegin()) {
        String previous = server.header("X-Oasis-Previous");
        bool follows = !previous.length() || (previous == tagId && tagState == TAG_COMPLETE && tagRev == guestState.rev);
        tagUpload = tagIdle() && server.header("X-Oasis-Device") == boardId && follows &&
                    id != tagId && (tagState != TAG_STAGED || tagRev != guestState.rev) &&
                    server.header("X-Guest-Rev") == String((unsigned long)guestState.rev);
        if (!tagUpload) flashEnd();
      }
      upReject = !tagUpload;
    }
    if (!upReject && !upNoMem) {
      patN = 0;
      portENTER_CRITICAL(&stepMux); tagState = TAG_NONE; portEXIT_CRITICAL(&stepMux);
    }
    return;
  }
  if (r.status == RAW_ABORTED && tagUpload) { patN = 0; tagUpload = false; flashEnd(); return; }
  if (upReject || upNoMem) return;
  if (r.status == RAW_WRITE || r.status == RAW_END) {
    size_t n = r.status == RAW_WRITE ? r.currentSize : 0;
    for (size_t i = 0; i <= n; i++) {
      bool end = (i == n);
      char ch = end ? '\n' : (char)r.buf[i];
      if (end && r.status == RAW_WRITE) break;
      if (ch == '\r') continue;
      if (ch != '\n') { if (lineLen < (int)sizeof(lineBuf) - 1) lineBuf[lineLen++] = ch; else lineOver = true; continue; }
      lineBuf[lineLen] = 0;
      char* p = lineBuf;
      for (char* qq = p; *qq; qq++) if (*qq == ',' || *qq == '\t') *qq = ' ';
      while (*p == ' ') p++;
      if (*p && *p != '#') {
        char *e1, *e2;
        float th = strtof(p, &e1); float rh = e1 != p ? strtof(e1, &e2) : 0;
        if (lineOver || e1 == p || e2 == e1 || !isfinite(th) || !isfinite(rh) ||
            (tagUpload && (rh < 0 || rh > 1))) upSkipped++;
        else if (upN >= MAXPTS) upOverflow = true;
        else { pat[upN].theta = th; pat[upN].rho = constrain(rh, 0.0f, 1.0f); upN++; }
      }
      lineLen = 0; lineOver = false;
    }
    if (r.status == RAW_END && !upOverflow) patN = upN;
  }
}
void thrDone() {
  if (tagUpload) {
    tagUpload = false;
    bool valid = !upOverflow && !upSkipped && patN >= 2 && tagAt(pat[0].theta, pat[0].rho);
    if (valid) {
      strlcpy(tagId, server.header("X-Oasis-Run").c_str(), sizeof tagId);
      tagCrc = patternCrc();
      portENTER_CRITICAL(&stepMux); tagRev = guestState.rev; tagState = TAG_STAGED; portEXIT_CRITICAL(&stepMux);
    } else patN = 0;
    flashEnd();
    if (!valid) { reply(409, "invalid drawing or starting position"); return; }
  }
  if (upNoMem) { reply(500, "no memory for pattern buffer"); return; }
  if (upReject) { reply(409, "busy: a job is running"); return; }
  if (upOverflow) { patN = 0; reply(413, "too many points (max " + String(MAXPTS) + "), pattern discarded"); return; }
  server.send(200, "application/json", "{\"points\":" + String((long)patN) + ",\"skipped\":" + String(upSkipped) + "}\n");
}

// ---------------------------------------------------------------- storage (LittleFS, the 11 MB "spiffs" partition) and updates
File upFile; bool upOk = false; String upErr;
// The library parses URL arguments only AFTER a raw body, so uploads carry the key and path in headers (X-Key, X-Path).
bool keyOk() { return server.header("X-Key") == ADMIN_KEY || server.arg("key") == ADMIN_KEY; }
String upPath() { return server.hasHeader("X-Path") ? server.header("X-Path") : server.arg("path"); }
#include "guest_people.h"
#include "guest_upload.h"
#include "guest_evolve.h"
void fsRaw() {                          // body of POST /fs?path=/lib/x.pat&key=...
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    upOk = false; upErr = "";
    if (!fsOk) { upErr = "no storage"; return; }
    if (!keyOk()) { upErr = "bad key"; return; }
    if (stepN || autoOn || !flashBegin()) { upErr = "busy"; return; }
    String path = upPath();
    if (!path.startsWith("/") || path.indexOf("..") >= 0 || path.length() > 40) { upErr = "bad path"; flashEnd(); return; }
    int sl = path.lastIndexOf('/'); if (sl > 0) LittleFS.mkdir(path.substring(0, sl));
    upFile = LittleFS.open(path, "w"); upOk = (bool)upFile; if (!upOk) { upErr = "cannot open"; flashEnd(); }
  } else if (r.status == RAW_WRITE) {
    if (upOk && upFile.write(r.buf, r.currentSize) != r.currentSize) { upOk = false; upErr = "write failed (full?)"; }
  } else if (r.status == RAW_END) { if (upFile) upFile.close(); }
  else if (r.status == RAW_ABORTED) { if (upFile) upFile.close(); upOk = false; upErr = "aborted"; flashEnd(); }
}
void fsDone() {
  if (upOk || upErr == "write failed (full?)") { fsFree = LittleFS.totalBytes() - LittleFS.usedBytes(); flashEnd(); }
  if (upOk) reply(200, "saved " + upPath());
  else reply(upErr == "bad key" ? 403 : (upErr == "busy" ? 409 : 500), upErr);
}
bool otaOk = false; String otaErr;
void otaRaw() {                         // body of POST /update?key=... : the firmware .bin
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    otaOk = false; otaErr = "";
    if (!keyOk()) { otaErr = "bad key"; return; }
    if (stepN || bootPending || !flashBegin()) { otaErr = "busy"; return; }
    autoOn = false;
    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) { otaErr = Update.errorString(); flashEnd(); return; }
    otaOk = true;
  } else if (r.status == RAW_WRITE) {
    if (otaOk && Update.write(r.buf, r.currentSize) != r.currentSize) { otaOk = false; otaErr = Update.errorString(); }
  } else if (r.status == RAW_END) {
    if (otaOk && !Update.end(true)) { otaOk = false; otaErr = Update.errorString(); }
  } else if (r.status == RAW_ABORTED) { Update.abort(); otaOk = false; otaErr = "aborted"; flashEnd(); }
}
void otaDone() {
  if (otaOk) { prefs.putUChar("skipboot", 1); savePos(); reply(200, "updated, restarting"); restartAt = millis() + 800; }   // webFlash stays set until the restart
  else { if (otaErr != "busy" && otaErr != "bad key") flashEnd(); reply(otaErr == "bad key" ? 403 : (otaErr == "busy" ? 409 : 500), "update failed: " + otaErr); }
}

// The button on the table is GPIO37, low while pressed (found 2026-11-20: Bill pressed it once, low for 275 ms).
// One short press: while a job runs, pause it where it is / carry on. While idle: start drawing by itself (homing first
// if needed), or, if it is waiting between self-made pieces, stop drawing by itself. (A hold-2-s light toggle was tried
// and dropped the same morning: Bill found it unreliable and unnecessary.)
#define BTN_PIN 37
void buttonPoll() {
  static uint32_t downAt = 0, lastCh = 0; static bool down = false;
  bool lv = digitalRead(BTN_PIN) == LOW; uint32_t now = millis();
  if (lv == down || now - lastCh < 40) return;
  lastCh = now; down = lv;
  if (down) { downAt = now; return; }
  if (now - downAt < 40) return;                             // released: act once
  ledFlashAt = now; ledFlashOn = true;
  bool wasEvolving = guestState.evolving;
  stopGuestEvolution();
  if (stateV != ST_IDLE) pauseFlag = !pauseFlag;
  else if (wasEvolving) clearSteps();
  else if (autoOn || bootPending || stepN > 0) { autoOn = false; bootPending = false; clearSteps(); }
  else if (homedOk()) { autoNextMs = now; quietOverride = true; autoOn = true; }
  else bootPending = true;
}

void webTask(void*) {
  uint32_t lastSave = 0;
  for (;;) {
    server.handleClient();
    buttonPoll();
    guestEvolvePoll();
    savePeopleWhenIdle();
    if (posDirty && !busy() && millis() - lastMoveMs > 3000 && millis() - lastSave > 3000 && flashBegin()) { savePos(); flashEnd(); lastSave = millis(); }
    if (settingsDirty && !busy() && flashBegin()) { saveSettings(); flashEnd(); }
    if (calDirty && !busy() && flashBegin()) { saveCal(); calDirty = false; flashEnd(); }
    if (webFlash && millis() - webFlashMs > 180000) webFlash = false;      // an upload that died without telling us
    if (restartAt && (int32_t)(millis() - restartAt) > 0) { delay(100); ESP.restart(); }
    vTaskDelay(1);
  }
}

void setup() {
  for (int m = 0; m < 2; m++) for (int i = 0; i < 4; i++) { pinMode(MP[m][i], OUTPUT); digitalWrite(MP[m][i], LOW); }
  pinMode(34, OUTPUT); digitalWrite(34, HIGH); pinMode(14, OUTPUT); digitalWrite(14, HIGH);
  for (int i = 0; i < 64; i++) cosT[i] = cosf(2 * (float)M_PI * i / 64.0f);
  guestState.rev = esp_random();
  uint64_t chip = ESP.getEfuseMac(); uint8_t digest[32];
  mbedtls_sha256((const unsigned char*)&chip, sizeof chip, digest, 0);
  for (int i = 0; i < 12; i++) snprintf(boardId + 2*i, 3, "%02x", digest[i]);
  prefs.begin("oasis", false);
  loadState();
  if (drive == 2) pwmAttach(true);
  watchInit(1);
  pat = (Pt*)malloc(sizeof(Pt) * MAXPTS);
  xTaskCreatePinnedToCore(ledTask, "led", 4096, NULL, 3, NULL, 0);   // above the web task: a busy page request must not stall the light
  xTaskCreatePinnedToCore(motionTask, "motion", 8192, NULL, 2, NULL, 1);

  WiFi.mode(WIFI_STA); WiFi.setHostname("oasis-ours"); WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis(); while (WiFi.status() != WL_CONNECTED && millis() - t0 < 25000) delay(300);

  static const char* hdrs[] = {"X-Key", "X-Path", "X-Guest-Mode", "X-Guest-Rev", "X-Guest-Slots", "X-Guest-Counts",
    "X-Oasis-Run", "X-Oasis-Device", "X-Oasis-Previous"};
  server.collectHeaders(hdrs, sizeof(hdrs) / sizeof(hdrs[0]));
  fsOk = LittleFS.begin(false, "/littlefs", 12, "spiffs");   // never format by itself: POST-free /fs?format=1&key=K does it on request
  if (fsOk) fsFree = LittleFS.totalBytes() - LittleFS.usedBytes();
  loadPeople();
  configTzTime("PST8PDT,M3.2.0,M11.1.0", "pool.ntp.org", "time.nist.gov");     // clock for quiet hours (Pacific)
  if (MDNS.begin("oasis")) MDNS.addService("http", "tcp", 80);                  // http://oasis.local on the home network
  server.on("/", []() {                  // the page stored on the table, else the built-in one
    if (fsOk && LittleFS.exists("/www/index.html")) { File f = LittleFS.open("/www/index.html", "r"); server.streamFile(f, "text/html"); f.close(); }
    else server.send_P(200, "text/html", PAGE);
  });
  server.on("/basic", []() { server.send_P(200, "text/html", PAGE); });
  server.on("/guests", HTTP_GET, []() {
    server.sendHeader("Location", "/lib/guest.html?v=15");
    server.send(302, "text/plain", "");
  });
  if (fsOk) server.serveStatic("/lib/guest", LittleFS, "/lib/guest", "no-cache");
  if (fsOk) server.serveStatic("/lib/", LittleFS, "/lib/", "max-age=86400");
  server.on("/patterns", []() {
    if (fsOk && LittleFS.exists("/lib/index.json")) { File f = LittleFS.open("/lib/index.json", "r"); server.streamFile(f, "application/json"); f.close(); }
    else server.send(200, "application/json", "[]");
  });
  server.on("/draw", []() {              // queue a stored drawing: [check] [erase] drawing
    String name = server.arg("name"); GenP gp; bool isGen = false;
    float first[2] = {0, 1};
    if (server.hasArg("spec")) {         // a self-made piece by its description (favourites): "bloom n=7 d=0.34 g=0.5 T=19 w=0.0"
      if (!parseSpec(server.arg("spec"), gp)) { reply(404, "unknown design"); return; }
      isGen = true; name = "that design";
    } else {
      bool nameOk = fsOk && name.length() > 0 && name.length() <= 24;
      for (unsigned i = 0; nameOk && i < name.length(); i++) { char ch = name[i]; nameOk = isalnum((unsigned char)ch) || ch == '_' || ch == '-'; }
      if (!nameOk) { reply(404, "unknown drawing"); return; }
      File f = LittleFS.open("/lib/" + name + ".pat", "r");
      if (!f || f.size() < 16) { if (f) f.close(); reply(404, "unknown drawing: " + name); return; }
      f.read((uint8_t*)first, 8); f.close();
    }
    if (!homedOk()) { reply(409, "not homed: press Find home first"); return; }
    bool now = server.arg("now") == "1", erase = server.hasArg("erase") ? server.arg("erase") != "0" : (bool)eraseFirst;
    bool check = rehomeOn && (erase || unchecked >= MAX_UNCHECKED);
    if (now) {                           // replace whatever is running or waiting
      jobPending = false; clearSteps();
      if (stateV != ST_IDLE) { stopFlag = true; uint32_t t0 = millis(); while (stateV != ST_IDLE && millis() - t0 < 1500) delay(5); }
      delay(40); clearSteps();
    }
    int need = 1 + (erase ? 1 : 0) + (check ? 1 : 0);
    if (stepN + need > NSTEP) { reply(409, "the queue is full"); return; }
    Step st = {};
    if (check) { st.kind = SK_REHOME; pushStep(st); }
    st = {};
    if (isGen) { st.kind = SK_GEN; st.g = gp; st.piece = 1; }
    else { st.kind = SK_FILE; st.piece = 1; strlcpy(st.name, name.c_str(), sizeof st.name); }
    if (erase && isGen) { Step e = {}; e.kind = SK_GEN; e.g = eraseP(true, 0.035f); pushStep(e); }   // as before: a self-made piece gets the spiral erase
    else if (erase) pushEraseFor(st.name, first[1], st);   // the drawing's own outside-in erase, or the spiral erase ending where it starts
    pushStep(st);
    reply(200, String(now ? "drawing " : "queued ") + name);
  });
  server.on("/smooth", []() {            // level the sand: check, erase out, erase in
    if (!homedOk()) { reply(409, "not homed: press Find home first"); return; }
    if (stepN + 3 > NSTEP) { reply(409, "the queue is full"); return; }
    Step st = {};
    if (rehomeOn) { st.kind = SK_REHOME; pushStep(st); }
    st = {}; st.kind = SK_GEN; st.g = eraseP(true, 0.035f); pushStep(st);
    st = {}; st.kind = SK_GEN; st.g = eraseP(false, 0.035f); pushStep(st);
    reply(200, "queued smoothing");
  });
  server.on("/fav", []() {               // favourites: self-made designs kept by their description, one per line in /www/fav.txt
    if (!fsOk) { reply(500, "no storage"); return; }
    String all; { File f = LittleFS.open("/www/fav.txt", "r"); if (f) { all = f.readString(); f.close(); } }
    if (server.hasArg("add") || server.hasArg("del")) {
      String sp = server.hasArg("add") ? server.arg("add") : server.arg("del");
      if (sp == "now") sp = nowName;
      bool plain = sp.length() <= 70;
      for (unsigned i = 0; plain && i < sp.length(); i++) { char ch = sp[i]; plain = isalnum((unsigned char)ch) || ch == ' ' || ch == '=' || ch == '.' || ch == '-'; }
      GenP gp; if (!plain || !parseSpec(sp, gp)) { reply(400, "only self-made designs can be kept"); return; }
      String out; int n = 0; bool had = false; int i = 0;
      while (i < (int)all.length()) { int j = all.indexOf('\n', i); if (j < 0) j = all.length(); String ln = all.substring(i, j); i = j + 1;
        if (ln.length() < 3) continue; if (ln == sp) { had = true; if (server.hasArg("del")) continue; } out += ln + "\n"; n++; }
      if (server.hasArg("add") && !had) { if (n >= 24) { reply(409, "favourites are full (24)"); return; } out += sp + "\n"; }
      if (!flashBegin()) { reply(409, "busy drawing: try again when it has finished"); return; }
      File f = LittleFS.open("/www/fav.txt", "w"); bool ok = f && f.print(out) == out.length(); if (f) f.close(); flashEnd();
      reply(ok ? 200 : 500, ok ? (server.hasArg("add") ? "kept" : "removed") : "could not save"); return;
    }
    String js = "["; int i = 0; bool first = true;
    while (i < (int)all.length()) { int j = all.indexOf('\n', i); if (j < 0) j = all.length(); String ln = all.substring(i, j); i = j + 1;
      if (ln.length() < 3) continue; js += String(first ? "" : ",") + "\"" + ln + "\""; first = false; }
    server.send(200, "application/json", js + "]");
  });
  server.on("/queue", []() { if (server.arg("clear") == "1") { stopGuestEvolution(); clearSteps(); } reply(200, "queue has " + String((int)stepN) + " steps"); });
  server.on("/fs", HTTP_POST, fsDone, fsRaw);
  server.on("/fs", HTTP_GET, []() {      // list, or del=<path>&key=
    if (server.arg("format") == "1") {
      if (!keyOk()) { reply(403, "bad key"); return; }
      if (stepN || autoOn || !flashBegin()) { reply(409, "busy"); return; }
      LittleFS.end(); bool ok = LittleFS.begin(true, "/littlefs", 12, "spiffs") && LittleFS.format() && LittleFS.begin(false, "/littlefs", 12, "spiffs");
      fsOk = ok; if (ok) fsFree = LittleFS.totalBytes() - LittleFS.usedBytes(); flashEnd();
      reply(ok ? 200 : 500, ok ? "formatted" : "format failed"); return;
    }
    if (!fsOk) { reply(500, "no storage"); return; }
    if (server.hasArg("del")) {
      if (!keyOk()) { reply(403, "bad key"); return; }
      if (stepN || autoOn || !flashBegin()) { reply(409, "busy"); return; }
      bool ok = LittleFS.remove(server.arg("del")); fsFree = LittleFS.totalBytes() - LittleFS.usedBytes(); flashEnd();
      reply(ok ? 200 : 404, "del " + server.arg("del")); return;
    }
    String out = "{\"free\":" + String((unsigned long)fsFree) + ",\"files\":[";
    const char* dirs[] = {"/lib", "/www"}; bool first = true;
    for (int d = 0; d < 2; d++) {
      File dir = LittleFS.open(dirs[d]);
      if (!dir || !dir.isDirectory()) continue;
      for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
        out += String(first ? "" : ",") + "{\"path\":\"" + dirs[d] + "/" + f.name() + "\",\"size\":" + String((unsigned long)f.size()) + "}"; first = false;
      }
    }
    server.send(200, "application/json", out + "]}\n");
  });
  server.on("/update", HTTP_POST, otaDone, otaRaw);
  server.on("/status", hStatus);
  server.on("/guest-state", HTTP_GET, guestStateReply);
  server.on("/guest-part", HTTP_GET, getGuestPart);
  server.on("/guest-people", HTTP_GET, guestPeopleReply);
  server.on("/guest-people", HTTP_POST, guestPersonUpdate);
  server.on("/guest-draw", HTTP_POST, guestDone, guestRaw);
  server.on("/guest-evolve", HTTP_POST, guestEvolveRequest);
  server.on("/cfg", hCfg);
  server.on("/inputs", hInputs);
  auto stopFn = []() { stopGuestEvolution(); if (guestState.pending) forgetGuest(); autoOn = false; bootPending = false; jobPending = false; clearSteps(); pauseFlag = false; stopFlag = true;
    portENTER_CRITICAL(&stepMux); if (tagState != TAG_NONE) tagState = TAG_FAILED; portEXIT_CRITICAL(&stepMux);
    reply(200, "stopping"); };
  server.on("/pause", []() {            // on=1 pause the running job where it is, on=0 carry on
    if (server.hasArg("on")) stopGuestEvolution();
    if (server.hasArg("on")) pauseFlag = server.arg("on").toInt() != 0 && stateV != ST_IDLE;
    reply(200, pauseFlag ? "paused" : "running");
  });
  server.on("/stop", stopFn);
  server.on("/off", stopFn);
  server.on("/zero", []() {
    if (busy()) { reply(409, "busy"); return; }
    forgetGuest();
    int m = server.arg("m").toInt();
    if (m != 2) setC(0, 0);
    if (m != 1) { setC(1, 0); M2H = 0; }
    homed = 0; posDirty = true;
    reply(200, "zeroed");
  });
  server.on("/set", []() {
    if (busy()) { reply(409, "busy"); return; }
    if (server.args()) forgetGuest();
    if (server.hasArg("m1")) setC(0, lround(server.arg("m1").toDouble() * TPS));
    if (server.hasArg("m2")) setC(1, lround(server.arg("m2").toDouble() * TPS));
    if (server.hasArg("m2h")) M2H = server.arg("m2h").toDouble();
    if (server.hasArg("homed")) { homed = server.arg("homed").toInt() ? 1 : 0; fault = 0; idxPassC2 = c2; }
    posDirty = true;
    reply(200, "set");
  });
  server.on("/home", []() {
    Job j = {}; j.type = JT_HOME; j.name = "home";
    j.l1 = (server.arg("elbow") == "0" ? 4 : 0) | (server.arg("index") == "0" ? 8 : 0);
    long need = homed ? elbowNeed(c1, c2) : (long)HOME_STEPS;    // position believed known: go well past the stop
    if (server.arg("full") == "1") need = HOME_STEPS;
    j.l2 = server.hasArg("steps") ? constrain(server.arg("steps").toInt(), 1, 100000) : (need > HOME_STEPS ? (long)HOME_STEPS : need);
    if (server.hasArg("us")) { j.vmax = 1e6f / constrain(server.arg("us").toInt(), 300, 50000); if (j.vmax > VMAX) j.vmax = VMAX; }
    submit(j);
  });
  server.on("/cal", []() {
    if (busy()) { reply(409, "busy"); return; }
    if (server.args()) forgetGuest();
    if (server.hasArg("l"))    GL   = server.arg("l").toDouble();
    if (server.hasArg("ef"))   GEF  = server.arg("ef").toDouble();
    if (server.hasArg("b1"))   GB1   = server.arg("b1").toDouble();
    if (server.hasArg("b2"))   GB2   = server.arg("b2").toDouble();
    if (server.hasArg("phi0")) PHI0 = server.arg("phi0").toDouble();
    if (server.hasArg("a"))    GA    = server.arg("a").toDouble();
    if (server.hasArg("a1"))   GA1   = server.arg("a1").toDouble();
    if (server.hasArg("k"))    GK    = server.arg("k").toDouble();
    if (server.hasArg("rmax")) RMAX = constrain(server.arg("rmax").toDouble(), 0.05, 0.92);
    if (server.hasArg("emarg")) EMARG = constrain(server.arg("emarg").toDouble(), 0.0, 1.0);
    if (server.hasArg("th0"))  TH0  = server.arg("th0").toDouble();
    if (server.hasArg("m2h"))  M2H  = server.arg("m2h").toDouble();
    if (server.hasArg("idx"))  IDX_M2 = server.arg("idx").toDouble();
    if (server.hasArg("rev") && server.arg("rev").toDouble() > 100) GA = 2 * M_PI / server.arg("rev").toDouble();
    if (server.hasArg("home")) HOME_STEPS = constrain(server.arg("home").toInt(), 100, 100000);
    if (fabs(GA * GB1 + GA1 * GB2) < 1e-12) { GA = 5.59e-4; GB1 = 6.09e-4; GA1 = 3.045e-4; GB2 = 1.10e-4; reply(400, "degenerate model: reset a,b1,a1,b2 to defaults"); return; }
    if (server.arg("save") == "1" && flashBegin()) { saveCal(); flashEnd(); }
    reply(200, "ok (see /status cal)");
  });
  server.on("/goto", []() {
    if (!server.hasArg("th") || !server.hasArg("rho")) { reply(400, "need th and rho"); return; }
    Job j = {}; j.type = JT_POLAR; j.name = "goto";
    j.a = server.arg("th").toFloat(); j.b = constrain(server.arg("rho").toFloat(), 0.0f, 1.0f); submit(j);
  });
  server.on("/raw", []() {
    if (!server.hasArg("m1") || !server.hasArg("m2")) { reply(400, "need m1 and m2"); return; }
    Job j = {}; j.type = JT_RAW; j.name = "raw";
    j.l1 = lround(server.arg("m1").toDouble()); j.l2 = lround(server.arg("m2").toDouble());
    if (server.hasArg("us")) { j.vmax = 1e6f / constrain(server.arg("us").toInt(), 300, 50000); if (j.vmax > VMAX) j.vmax = VMAX; }
    j.noguard = server.arg("guard") == "0";
    submit(j);
  });
  server.on("/circle", []() {
    Job j = {}; j.type = JT_CIRCLE; j.name = "circle";
    j.a = server.hasArg("rho") ? clamp01(server.arg("rho").toFloat()) : 0.7f;
    j.b = server.hasArg("turns") ? constrain(server.arg("turns").toFloat(), 0.01f, 50.0f) : 1.0f; submit(j);
  });
  server.on("/spiral", []() {
    Job j = {}; j.type = JT_SPIRAL; j.name = "spiral";
    j.a = server.hasArg("loops") ? constrain(server.arg("loops").toFloat(), 0.25f, 40.0f) : 4.0f;
    j.b = server.arg("dir") == "in" ? -1.0f : 1.0f; submit(j);
  });
  server.on("/rose", []() {
    Job j = {}; j.type = JT_ROSE; j.name = "rose";
    j.a = (float)constrain(server.arg("k").toInt(), 1, 12); submit(j);
  });
  server.on("/clear", []() { Job j = {}; j.type = JT_CLEAR; j.name = "clear"; submit(j); });
  server.on("/gen", []() {               // one generative piece (or erase spiral) now
    Job j = {}; j.type = JT_GEN; j.name = "gen";
    String k = server.arg("kind");
    if (k == "random" || k == "") j.g = pickRandom();
    else if (k == "erase_out" || k == "erase_in") j.g = eraseP(k == "erase_out", server.hasArg("pitch") ? constrain(server.arg("pitch").toFloat(), 0.01f, 0.2f) : 0.035f);
    else {
      j.g.kind = k == "vortex" ? GK_VORTEX : (k == "weave" ? GK_WEAVE : (k == "arms" ? GK_ARMS : (k == "super" ? GK_SUPER : (k == "ripple" ? GK_RIPPLE : (k == "lotus" ? GK_LOTUS : GK_BLOOM)))));
      j.g.n = server.hasArg("n") ? constrain(server.arg("n").toInt(), 2, 24) : 6;
      j.g.q = server.hasArg("q") && server.arg("q").toInt() != 0 ? constrain(server.arg("q").toInt(), -8, 8) : 2;
      j.g.d = server.hasArg("d") ? constrain(server.arg("d").toFloat(), 0.0f, 0.9f) : 0.45f;
      j.g.g = server.hasArg("g") ? constrain(server.arg("g").toFloat(), 0.2f, 6.0f) : 0.6f;
      j.g.T = server.hasArg("T") ? constrain(server.arg("T").toFloat(), 2.0f, 60.0f) : 20.0f;
      j.g.w = server.hasArg("w") ? constrain(server.arg("w").toFloat(), -20.0f, 20.0f) : 0.0f;
      j.g.e = server.hasArg("e") ? constrain(server.arg("e").toFloat(), 0.0f, 0.4f) : 0.10f;
      if (j.g.kind == GK_LOTUS || j.g.kind == GK_RIPPLE) j.g.q = constrain(abs(j.g.q), 1, 8);
    }
    if (j.g.kind == GK_ERASE_OUT || j.g.kind == GK_ERASE_IN) j.vmax = VERASE;
    if (!busy() || server.arg("force") == "1") { describe(j.g); strlcpy(nowName, genDesc, sizeof nowName); }
    submit(j);
  });
  server.on("/auto", []() {              // on=1: erase, random piece, hold, repeat. hold = seconds a finished piece is left on show
    if (server.hasArg("hold")) { autoHoldS = constrain(server.arg("hold").toInt(), 0, 86400); settingsDirty = true; }
    if (server.hasArg("boot")) { autoBoot = server.arg("boot").toInt() != 0; settingsDirty = true; }
    if (server.hasArg("mix")) { autoMix = constrain(server.arg("mix").toInt(), 0, 2); settingsDirty = true; }
    if (server.arg("skipboot") == "1" && flashBegin()) { prefs.putUChar("skipboot", 1); flashEnd(); }
    if (server.hasArg("on")) {
      bool on = server.arg("on").toInt() != 0;
      if (on && !homedOk()) { reply(409, "not homed (or fault): /home first"); return; }
      if (on && !autoOn) autoNextMs = millis();
      stopGuestEvolution();
      if (!on) clearSteps();
      autoOn = on;
    }
    reply(200, String("auto=") + (autoOn ? 1 : 0) + " hold=" + String((unsigned long)autoHoldS) + " boot=" + (autoBoot ? 1 : 0) + " pieces=" + String((long)autoCount));
  });
  server.on("/thr", HTTP_POST, thrDone, thrRaw);
  server.on("/play", []() {
    String id = server.header("X-Oasis-Run");
    if (id.length()) { taggedPlay(id); return; }
    if (patN < 1) { reply(400, "no pattern stored (POST /thr first)"); return; }
    Job j = {}; j.type = JT_PLAY; j.name = "play"; j.loop = server.arg("loop") == "1";
    if (!busy()) strlcpy(nowName, "uploaded pattern", sizeof nowName);
    submit(j);
  });
  server.on("/led", []() {
    if (server.arg("restore") == "1") {                        // a camera tool gives the ring back
      if (ledTmp) { ledMode = svMode; ledBright = svBright; ledColor = svColor; ledDrift = svDrift; ledMood = svMood; ledLin = 0; ledTmp = false;
                    ledRest = svRest; ledFillRing = svFillRing; ledEvening = svEvening; ledFill = svFill; SHOW_PERIOD = svPeriod; ledSpeed = svSpeed; ledWarm = svWarm; ledTrail = svTrail; }
      reply(200, "led restored"); return;
    }
    bool tmp = server.arg("tmp") == "1";
    if (tmp && !ledTmp) { svMode = ledMode; svBright = ledBright; svColor = ledColor; svDrift = ledDrift; svMood = ledMood; ledTmp = true;
                          svRest = ledRest; svFillRing = ledFillRing; svEvening = ledEvening; svFill = ledFill; svPeriod = SHOW_PERIOD; svSpeed = ledSpeed; svWarm = ledWarm; svTrail = ledTrail; }
    if (server.hasArg("flash")) { ledFlashAt = millis(); ledFlashOn = true; }      // the button's acknowledge flash (for testing)
    if (!tmp) ledTmp = false;
    String m = server.arg("mode");
    if (m == "off") ledMode = LM_OFF; else if (m == "solid") ledMode = LM_SOLID;
    else if (m == "comet") ledMode = LM_COMET; else if (m == "breathe") ledMode = LM_BREATHE;
    else if (m == "progress") ledMode = LM_PROGRESS; else if (m == "idx") ledMode = LM_IDX;
    else if (m == "follow") ledMode = LM_FOLLOW; else if (m == "arc") ledMode = LM_ARC;
    else if (m == "show") ledMode = LM_SHOW; else if (m == "auto") ledMode = LM_AUTO;
    else if (m == "aurora") ledMode = LM_AURORA; else if (m == "breath") ledMode = LM_BREATH478;
    else if (m == "fireflies") ledMode = LM_FIREFLY;
    else if (m != "") { reply(400, "bad mode"); return; }
    if (m != "" || server.hasArg("lin")) ledLin = server.arg("lin").toInt() ? 1 : 0;
    if (server.hasArg("aw")) ledArcW = constrain(server.arg("aw").toFloat(), 0.5f, 21.5f);
    if (server.hasArg("i")) ledIdx = constrain(server.arg("i").toInt(), 0, NLED - 1);
    if (server.hasArg("c")) { ledColor = strtoul(server.arg("c").c_str(), 0, 16) & 0xFFFFFF; ledDrift = 0; ledMood = 0; }
    if (server.hasArg("c2")) ledFill = strtoul(server.arg("c2").c_str(), 0, 16) & 0xFFFFFF;
    if (server.hasArg("drift")) { ledDrift = server.arg("drift").toInt() ? 1 : 0; if (ledDrift) ledMood = 0; }
    if (server.hasArg("mood")) { ledMood = server.arg("mood").toInt() ? 1 : 0; if (ledMood) ledDrift = 0; }
    if (server.hasArg("evening")) ledEvening = server.arg("evening").toInt() ? 1 : 0;
    if (server.hasArg("rest")) ledRest = constrain(server.arg("rest").toInt(), 0, 2);
    if (server.hasArg("warm")) ledWarm = server.arg("warm").toInt() ? 1 : 0;
    if (server.hasArg("trail")) ledTrail = server.arg("trail").toInt() ? 1 : 0;
    if (server.hasArg("dith")) ledDith = constrain(server.arg("dith").toInt(), 0, 4);
    if (server.hasArg("hz")) ledPeriodMs = constrain((int)lroundf(1000.0f / constrain(server.arg("hz").toFloat(), 55.0f, 500.0f)), 2, 17);
    if (server.hasArg("fill")) ledFillRing = server.arg("fill").toInt() ? 1 : 0;
    if (server.hasArg("speed")) ledSpeed = constrain(server.arg("speed").toFloat(), 0.25f, 4.0f);
    if (server.hasArg("b")) ledBright = constrain(server.arg("b").toInt(), 0, 255);
    if (server.hasArg("period")) SHOW_PERIOD = constrain(server.arg("period").toFloat(), 10.0f, 3600.0f);
    if (server.hasArg("ma")) ledMaxmA = constrain(server.arg("ma").toInt(), 100, 2600);
    if (server.hasArg("led0") && isfinite(server.arg("led0").toFloat())) LED0 = server.arg("led0").toFloat();
    if (server.hasArg("base")) LEDBASE = clamp01(server.arg("base").toFloat());
    if (server.hasArg("w")) LEDW = constrain(server.arg("w").toFloat(), 3.0f, 180.0f);
    if (!tmp) settingsDirty = true;                            // the owner's light choice survives a restart
    reply(200, "led mode=" + String(ledMode) + " b=" + String(ledBright));
  });
  server.on("/ledlog", []() {                                  // measuring the light: see ledLogFrame()
    if (server.arg("stats") == "1") {
      char b[260];
      snprintf(b, sizeof b, "{\"frames\":%lu,\"mean_us\":%.0f,\"max_us\":%lu,\"over5ms\":%lu,\"over10ms\":%lu,\"over20ms\":%lu,\"over50ms\":%lu,\"work_mean_us\":%.0f,\"work_max_us\":%lu,\"free_heap\":%u}",
               (unsigned long)stN, stN ? (double)stSum / stN : 0.0, (unsigned long)stMax, (unsigned long)stG5, (unsigned long)stG10, (unsigned long)stG20, (unsigned long)stG50,
               stN ? (double)stWSum / stN : 0.0, (unsigned long)stWMax, (unsigned)ESP.getFreeHeap());
      if (server.arg("reset") == "1") { stLast = 0; stN = 0; stSum = 0; stMax = 0; stG5 = stG10 = stG20 = stG50 = 0; stWSum = 0; stWMax = 0; }
      server.send(200, "application/json", b); return;
    }
    if (server.hasArg("n")) {                                  // start recording n frames of the listed LEDs
      logState = 0; delay(20); if (logBuf) { free(logBuf); logBuf = NULL; }
      if (server.arg("n") == "0") { reply(200, "log freed"); return; }
      int nl = 0; String L = server.arg("leds"); if (L == "") L = "0";
      for (int a = 0; a < (int)L.length() && nl < LOG_MAXL;) { int c = L.indexOf(',', a); if (c < 0) c = L.length(); logLed[nl++] = constrain(L.substring(a, c).toInt(), 0, NLED - 1); a = c + 1; }
      int rec = 8 + 12 * nl, n = constrain(server.arg("n").toInt(), 1, 20000);
      logK = server.hasArg("k") ? constrain(server.arg("k").toInt(), 1, 250) : 1; logKi = 0; logWork = 0; memset(logAcc, 0, sizeof logAcc);
      if ((size_t)n * rec > 48000 || heap_caps_get_largest_free_block(MALLOC_CAP_8BIT) < (size_t)n * rec + 8000 || ESP.getFreeHeap() < (size_t)n * rec + 40000) { reply(400, "log too big for memory"); return; }
      logBuf = (uint8_t*)malloc((size_t)n * rec); if (!logBuf) { reply(500, "no memory"); return; }
      logNL = nl; logRec = rec; logCap = n; logN = 0; logState = 1;
      reply(200, "recording " + String(n) + " frames of " + String(nl) + " leds"); return;
    }
    if (logState != 2 || !logBuf) { reply(200, String(logState == 1 ? "recording " : "none ") + String((int)logN) + "/" + String((int)logCap)); return; }
    String hdr = "OASISLOG2 " + String((int)logNL) + " " + String((int)logN) + " " + String((int)logK);
    for (int k = 0; k < logNL; k++) hdr += " " + String((int)logLed[k]);
    hdr += "\n"; size_t len = (size_t)logN * logRec;
    server.setContentLength(hdr.length() + len); server.send(200, "application/octet-stream", "");
    server.sendContent(hdr); server.sendContent((const char*)logBuf, len);
  });
  server.on("/gpio", []() {
    int p = server.arg("pin").toInt(); int idx = -1;
    for (unsigned i = 0; i < NW; i++) if (WPINS[i] == p) idx = i;
    if (idx < 0) { reply(400, "pin not in the spare list"); return; }
    if (server.hasArg("out")) { pinMode(p, OUTPUT); digitalWrite(p, server.arg("out").toInt() ? HIGH : LOW); outPin[idx] = 1; reply(200, "pin " + String(p) + " driven"); }
    else { pinMode(p, INPUT_PULLUP); outPin[idx] = 0; reply(200, "pin " + String(p) + " input"); }
  });
  server.onNotFound([]() { reply(404, "not found"); });
  server.begin();
  xTaskCreatePinnedToCore(webTask, "web", 12288, NULL, 2, NULL, 0);
}

void loop() { delay(1000); }
