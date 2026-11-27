/* Oasis 36-inch (coffee table) firmware: big-fw 2.9 - 2026-11-26 (slow spinning light in a guest's colour: /ledfx).
 * 2.8 - 2026-11-25 (centre touch from far out: wider edge search; fault 5 watchdog; outer limit 381 mm).
 * Board: "Oasis Side/Coffee Table MAIN PCB V0.6", ESP32-S3, two TMC2209 step/direction motor drivers.
 * The bench firmware (firmware/big-bench, v0.6: pins, guards, limits; see firmware-notes/big-qualification.md) plus the
 * drawing engine ported from the Mini's firmware/our-fw: pattern upload and playback, look-ahead speed planning,
 * pause, halt, spirals.
 *
 * SAFETY: at boot it drives NO pin (only Wi-Fi and the USB serial log) and never moves by itself. Drawing needs
 * /enable, /homearm and a known carriage position (/setcarriage, or the position saved before the restart).
 * Never flash the Mini build onto this board: its 20 kHz coil PWM on a STEP pin would spin a motor flat out.
 *
 * Geometry: polar. Arm 38,400 steps per turn; carriage (radius) 160 steps per mm from the arm's rotation centre; each
 * arm step also moves the carriage 1/6 step, so the radius motor counter is r = carriage + a/6. A pattern point
 * (theta in radians, counter-clockwise seen from above; rho 0..1) maps to a = thsign * (theta + th0) * 38400 / 2 pi
 * (thsign = -1: the arm's forward direction is clockwise from above, measured by camera) and carriage = rho * rmax,
 * never inside 800 steps (5 mm: the centre stop is at the centre and must not be pushed). Consecutive points are
 * joined by straight lines in (theta, rho), which is what the .thr format means.
 *
 * Drawing commands:
 *   POST /thr                     upload a pattern as text, one "theta rho" pair per line (# comments). Up to 12,000 points.
 *   /play                         draw the uploaded pattern from the ball's present position (the arm takes the
 *                                 nearest equivalent angle). 409 unless enabled, homed, idle and fault-free.
 *   /spiral?from=0&to=1&pitch=0.02    spiral from rho "from" to rho "to", pitch = rho per turn (negative = other way)
 *   /goto?th=1.57&rho=0.5         one straight move (in theta-rho) to that point; th defaults to the present angle
 *   /pause?on=1|0                 slow to a stop on the path and wait; on=0 continues
 *   /halt                         slow to a stop on the path and end the job (position stays valid)
 *   /stop                         stop at once, whatever is running; drivers stay on and hold. After a fast move the
 *                                 arm may have lost steps: the next sensor pass or /homearm settles it.
 *   /off                          stop at once and float every pin this firmware drove (the old bench /stop)
 *   /cfg?rmax=24000&vball=40&vclear=850&thsign=-1&th0=0   drawing radius for rho = 1 (carriage steps), ball speed for
 *                                 drawings and moves (mm/s), ball speed for /spiral clears (mm/s; 2.4: tested smooth to 927
 *                                 mm/s by Bill's eye, waves at about 1,100; default 850), theta
 *                                 direction and zero. Saved across restarts. rmax defaults to 24,000 (150 mm) because
 *                                 sand stays in the centre for now (Bill, 2026-11-22).
 * Position is saved 3 s after motion ends and restored at boot (run /enable then /homearm to confirm the arm).
 *
 * Planner: each segment runs on the faster motor's step clock (Bresenham for the other). Segment top speed = the
 * lowest of ball speed vball, 16,000 steps/s per motor (8,000 before 2.1); acceleration 100,000 steps/s^2 radius, 10,000 arm (30,000 in 2.2 tripped the stall alarm); at a corner the
 * speed is cut so no motor's step rate jumps by more than 1,000 (radius) or 300 (arm) steps/s; 64 segments look-ahead.
 *
 * Commands (GET; replies are JSON or short text):
 *   /status                       uptime, Wi-Fi, LED setup, driven pins, pulse job, watched inputs
 *   /led?pin=38&n=157&r=&g=&b=&i=0&k=157    one frame: LEDs i..i+k-1 in colour r,g,b (0..255), the rest off.
 *                                 pin and n stick until changed. /led?off=1 sends all off.
 *   /ledfx?mode=spin&r=&g=&b=&period=40&base=0.45&width=0.35[&pin=38&n=157]   2.9: the whole ring glows in r,g,b at
 *                                 `base` brightness with a soft brighter band (`width` of the ring) turning once every
 *                                 `period` seconds; colour changes ease over ~3 s. Any /led frame stops it. mode=off: dark.
 *   /inputs?pins=5,13&pull=up|down|none     make those pins inputs (with that pull) and report levels
 *   /watch?pins=5,13              watch those pins (already inputs) every 1 ms: change counts, last level, and the
 *                                 pulse count of the running job at each pin's last change. /watch?clear=1 resets.
 *   /pin?n=11&v=0                 drive pin n at level v. /float?n=11 makes it an input with no pull again.
 *   /pulse?step=1&dir=2&dv=0&n=200&hz=200   n pulses (5 us high) on pin step at hz; dir pin set to dv first if given.
 *                                 &until=21&lv=1 stops before the next pulse once that pin reads lv (max 1000 Hz then).
 *                                 Max 64000 pulses, max 6000 Hz, with a ramp from 100 Hz. Runs in the background.
 *   /move?r=-1600&a=2400&hz=1000&acc=2000   coordinated move of radius (r) and arm (a) microsteps, positive = DIR low
 *                                 (radius outward, arm one way). Needs both drivers enabled. Logs GPIO21 changes.
 *                                 Speed and acceleration are cut to the qualified limits (radius 8,000 steps/s and
 *                                 100,000 steps/s^2, arm 8,000 and 10,000); the reply says what was used. &raw=1 skips
 *                                 that for bench tests (up to 16,000 and 400,000).
 *   /zero?r=0&a=0                 set the position counters. /edges lists the logged GPIO21 changes [r, a, level].
 *   /enable?on=1                  both drivers on at factory current (IRUN 17 = about 1 A); on=0 turns them off
 *   /homearm                      sweep the arm forward to the sensor's rising edge (a = 6 there, as measured). After it,
 *                                 every pass of the sensor in either direction is checked: more than 64 steps off stops
 *                                 the move with fault 1. After a fault it snaps a to the nearest matching turn.
 *   /setcarriage?c=N              tell the firmware where the carriage is (steps from the arm's rotation centre, from the
 *                                 camera). After that, moves ending outside 800..61,000 carriage steps are refused.
 *   /homeradius[?hz=1600]         find the centre without a camera: parks the arm 5 steps inside its sensor edge and runs
 *                                 the radius inward until the centre stop nudges the arm off the edge (no stall, no thump),
 *                                 then backs out 1,600 steps. Needs /homearm first. "home" in /status: 1 running, 2 done.
 *   /sg                           StallGuard samples of the last move: [step, radius steps/s, arm steps/s, sg radius, sg arm]
 *   /guard?pr=85&pa=85&n=8&vmin=3000   stall alarm (average of the last n readings): slow to a stop (fault 2 radius, 3 arm) when that motor cruises at vmin
 *                                 steps/s or more and n readings in a row are under pr (pa) percent of the free-running
 *                                 value for that speed. 0 percent turns that alarm off. Blind below about 3,000 steps/s.
 *   /fault?clear=1                clear a fault (positions stay marked unknown until homed or set again)
 *   /tmc?a=1&r=6                  read TMC2209 register r (decimal or 0x..) at UART address a (factory uses 1 and 2)
 *   /tmc?a=1&r=0x10&v=0x60a04     write it. Replies with the register's value read back where readable.
 *   /tmcinit?irun=10&ihold=4      both drivers: internal current reference, StealthChop, 32 microsteps with interpolation,
 *                                 IRUN/IHOLD current scale (0..31; 10 = about 0.6 A rms with the board's 0.11 ohm sense
 *                                 resistors; the factory runs about 17 = 1 A). Reports what each driver reads back.
 *   POST /update                  firmware over Wi-Fi: raw body = .bin, header X-Key: ADMIN_KEY. Restarts.
 * The table answers at http://oasis-big.local and prints its address on the USB serial port (115200) at boot.
 */
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <Preferences.h>
#include "wifi_creds.h"

WebServer server(80);

// ---- pins ---------------------------------------------------------------------------------------------------
// Never touched: 19/20 USB, 26-32 flash and PSRAM, 43/44 the USB serial chip, 0/3/45/46 strapping pins.
bool protectedPin(int p) {
  return p < 0 || p > 48 || p == 0 || p == 3 || p == 19 || p == 20 || (p >= 22 && p <= 32) || p == 43 || p == 44 ||
         p == 45 || p == 46;
}
uint64_t driven = 0;                      // pins this firmware has made outputs
void floatPin(int p) { pinMode(p, INPUT); driven &= ~(1ULL << p); }
int8_t outLv[49];                         // level this firmware last drove on each pin
void drivePin(int p, int v) { pinMode(p, OUTPUT); digitalWrite(p, v ? HIGH : LOW); driven |= (1ULL << p); outLv[p] = v ? 1 : 0; }

// ---- LEDs (WS2812-style over RMT, GRB, same timing as the Mini) -----------------------------------------------
#define LED_MAX 400
#define TICK_HZ 10000000
int ledPin = -1, ledN = 157;
rmt_data_t sym[LED_MAX * 24 + 1];
uint8_t LR[LED_MAX], LG[LED_MAX], LB[LED_MAX];
// 2.9: effects. Bill, 2026-11-26: the light takes the featured guest's chosen colour and moves slowly, "cool without being
// jarring". Animated by ledTask on core 0 (RMT hardware does the bit timing, so the motor task on core 1 is untouched).
volatile int fxMode = 0;                      // 0: static frames from /led; 1: spin
float fxTR = 0, fxTG = 0, fxTB = 0, fxR = 0, fxG = 0, fxB = 0;   // target colour, shown colour (eases toward the target)
uint32_t fxPeriod = 40000;                    // ms per turn of the bright band
float fxBase = 0.45f, fxWidth = 0.35f;        // floor brightness; band width as a fraction of the ring
SemaphoreHandle_t ledMux = nullptr;
bool ledAttach(int pin) {
  if (pin == ledPin) return true;
  if (ledPin >= 0) { fxMode = 0; xSemaphoreTake(ledMux, portMAX_DELAY); rmtDeinit(ledPin); floatPin(ledPin); ledPin = -1; xSemaphoreGive(ledMux); }
  if (!rmtInit(pin, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_4, TICK_HZ) && !rmtInit(pin, RMT_TX_MODE, RMT_MEM_NUM_BLOCKS_1, TICK_HZ))
    return false;
  ledPin = pin; driven |= (1ULL << pin);
  return true;
}
void ledShow() {
  int k = 0;
  for (int p = 0; p < ledN; p++) {
    uint8_t by[3] = {LG[p], LR[p], LB[p]};
    for (int c = 0; c < 3; c++) for (int b = 7; b >= 0; b--) {
      bool o = (by[c] >> b) & 1;
      sym[k].level0 = 1; sym[k].duration0 = o ? 8 : 4; sym[k].level1 = 0; sym[k].duration1 = o ? 4 : 8; k++;
    }
  }
  sym[k].level0 = 0; sym[k].duration0 = 400; sym[k].level1 = 0; sym[k].duration1 = 400;
  rmtWrite(ledPin, sym, ledN * 24 + 1, 200);
}

// ---- pulse job (core 1) -----------------------------------------------------------------------------------------
volatile bool pulseRun = false, pulseStop = false;
volatile int32_t pulseDone = 0;
int pStep = -1, pDir = -1, pDv = 0; int32_t pN = 0; float pHz = 0;
int pUntil = -1, pUntilLv = 1; volatile int32_t pHitAt = -1;   // stop when pin pUntil reads pUntilLv (home switch)
// ---- coordinated two-motor moves (v0.3) -------------------------------------------------------------------------
// Motor 0 = radius (STEP1, DIR2, enable GPIO11), motor 1 = arm (STEP14, DIR13, enable GPIO34). Positive = DIR low.
// Bresenham on the longer axis, trapezoid speed (start 100 steps/s, acceleration acc steps/s^2, top hz).
// GPIO21 (arm home sensor) is read after every step and each change is logged with both positions.
const int MSTEP[2] = {1, 14}, MDIR[2] = {2, 13};
volatile int32_t mpos[2] = {0, 0};
volatile bool softStop = false, mvUntilLow = false, homeRun = false; volatile int homeState = 0; volatile int32_t homeWent = 0; float homeHz = 1600;
volatile bool moveRun = false; int32_t mvN[2] = {0, 0}; float mvHz = 0, mvAcc = 0; volatile int32_t mvDone = 0;
struct Edge { int32_t r, a; uint8_t lv; };
Edge edges[64]; volatile uint32_t edgeN = 0; uint8_t s21 = 0;
// Guards (v0.4). Arm: after /homearm, a = 0 at the sensor's rising edge going forward (DIR13 low); every later forward
// rising edge must land on a multiple of 38400 (one arm turn) within SLIP_TOL steps, or the move stops with a fault.
// Radius: after /homeradius, carriage radius = r - a/6 (turning the arm forward pulls the carriage in 1/6 step per arm
// step) and every move whose end lies outside [RMIN, RMAX] is refused.
// RMAX 61,800 = 386 mm (2.0, 2026-11-24). The factory's 56,800 (355 mm) left sand at the edge that clears never
// reached (Bill saw two clears stop short). Creeping out with Bill listening: free to 62,032 (388 mm); each 508-step
// move from 62,540 to 64,064 thumped (the carriage hit the outer end of its track and the radius motor skipped), with
// the ball still about 1/4 inch from the sand's edge. So the end is between 62,032 and 62,540 steps, and the last
// ~1/4 inch of sand at the wall is out of reach. Use /cfg?rmax=61600 (385 mm): rho 1 = as far out as is safe.
// 2.7 (2026-11-25): RMAX 61,000 (381 mm), cfg rmax 60,800 (380 mm): 385 mm left too little margin to the track end once
// position estimates and the 2-3 mm ball lag are counted; clears at the rim thumped and stalled three times that night.
const int32_t ARM_TURN = 38400, SLIP_TOL = 64, RMIN = 800, RMAX = 61000;
// Sensor rising edge, measured 2026-11-22 over 14 turns at three radii: forward at a = 3..12, backward at 805..812.
const int32_t EDGE_FWD = 6, EDGE_BACK = 808;
bool armRef = false;                         // the arm counter has been tied to the sensor at least once since power-up
volatile int32_t lastEdgeA = -1000000, armRunLen = 0; volatile int lastEdgeSg = 0;       // arm counter at the previous sensor change (to ignore chatter at an edge)
// StallGuard sampling and alarm (v0.5). A task on core 0 reads SG_RESULT from both drivers during every move.
struct SgS { int32_t i; uint16_t vr, va; int16_t sr, sa; };
#define SGN 1500
SgS sgs[SGN]; volatile uint32_t sgN = 0;
volatile float curV[2] = {0, 0};             // present speed of each motor, steps/s
// Free-running SG_RESULT against speed, measured 2026-11-22 at IRUN 17 on both motors with the carriage near the centre.
// With the carriage at 44,000 steps the arm read 13% lower. Two real arm stalls read 73% (8,000 steps/s, carriage 12,000)
// and 63% (4,000 steps/s, carriage 44,000) of the free value for their speed and radius. Both drivers also report about 2
// for part of every electrical cycle even when free, so readings of 4 or less are ignored.
const float SGV[7] = {2000, 3000, 4000, 6000, 8000, 12000, 16000}, SGE[7] = {96, 120, 150, 207, 247, 290, 325};
// Arm at IRUN 20 (1.2 A), measured 2026-11-22 at five radii, both directions: 115, 146, 200, 238 at 3,000 to 8,000 steps/s with
// the carriage at 12,000; 3% lower at 30,000, 9% at 44,000, 13 to 15% at 52,000 and 56,000. Lowest single free reading: 78%
// of the value for its speed and radius, most above 87%.
const float SGA[7] = {92, 115, 146, 200, 238, 280, 313};
#define SGAVG 16
float sgRatio[2][SGAVG]; volatile float sgLast[2] = {0, 0};
volatile int sgPct[2] = {85, 85}, sgNeed = 8; volatile float sgVmin = 3000; int sgHits[2] = {0, 0};
// Qualified limits (2026-11-22): the radius never lost position up to 16,000 steps/s and 400,000 steps/s^2; the arm was
// fine to 16,000 steps/s but lost position starting at 200,000 steps/s^2 near the centre and at 50,000 far out.
const float VMAX[2] = {16000, 16000}, AMAX[2] = {100000, 10000};   // 2.5: arm back to 16,000 steps/s (proven Nov 22); at 24,000 (2.2-2.4) a centre-out clear lost 107 arm steps near the centre (slip fault, Nov 24 11:26 pm). 8,000 before 2.1. Arm acceleration stays 10,000 steps/s^2: 30,000 (2.2) tripped the stall alarm at the rim on its first start (Nov 24). Sand at 669 mm/s looked very smooth to Bill.
SemaphoreHandle_t tmcMux;
volatile bool armHomed = false, radHomed = false; volatile int fault = 0; volatile int32_t slipErr = 0, slipChecks = 0;
inline int32_t fdiv6(int32_t a) { return a >= 0 ? a / 6 : -((5 - a) / 6); }      // floor(a / 6), exact for any counter
inline int32_t carriageR(int32_t r, int32_t a) { return r - fdiv6(a); }
// One step of the major motor and, when stepMinor, of the other; counters, sensor log and the arm slip check.
// Returns true when the slip check failed (fault 1 is set).
inline bool stepOnce(int major, bool stepMinor, int sgM, int sgm) {
  int minor = 1 - major;
  digitalWrite(MSTEP[major], HIGH); if (stepMinor) digitalWrite(MSTEP[minor], HIGH);
  delayMicroseconds(5);
  digitalWrite(MSTEP[major], LOW); if (stepMinor) digitalWrite(MSTEP[minor], LOW);
  mpos[major] += sgM; if (stepMinor) mpos[minor] += sgm;
  if (major == 1 || stepMinor) {            // arm steps since the last sensor change or reversal
    int asg = major == 1 ? sgM : sgm;
    if (asg != lastEdgeSg) { lastEdgeSg = asg; armRunLen = 0; }
    armRunLen++;
  }
  uint8_t v21 = digitalRead(21);
  if (v21 != s21) {
    s21 = v21; Edge& e = edges[edgeN % 64]; e.r = mpos[0]; e.a = mpos[1]; e.lv = v21; edgeN++;
    bool armStepped = (major == 1) || stepMinor; int armSg = major == 1 ? sgM : sgm;
    // Only a rising edge reached after a long uninterrupted run with the sensor low is a real entry into its zone. Anything
    // sooner is chatter in the sensor's 32-step hysteresis band or a reversal beside the zone (a parked arm at a = 0 gave a
    // false fault on 2026-11-22 when it started backward and the sensor flickered).
    bool fresh = armRunLen > 2000;
    lastEdgeA = mpos[1]; armRunLen = 0;
    if (armHomed && v21 && armStepped && fresh) {                         // rising edge, either direction: check for slip
      int32_t m = (((mpos[1] - (armSg > 0 ? EDGE_FWD : EDGE_BACK)) % ARM_TURN) + ARM_TURN) % ARM_TURN;
      int32_t e2 = m > ARM_TURN / 2 ? m - ARM_TURN : m;
      slipErr = e2; slipChecks++;
      if (abs(e2) > SLIP_TOL) { fault = 1; armHomed = false; radHomed = false; return true; }
    }
  }
  // 2.6: arm-not-turning watchdog. The slip check above only runs when the sensor changes, so a fully stalled arm (Bill
  // heard it grinding at the rim, 2026-11-25) was never caught. The sensor changes at least twice per turn, so a net
  // commanded arm travel of more than a turn plus margin since the last change means the arm is not turning: fault 5.
  if (armHomed && lastEdgeA > -1000000 && (major == 1 || stepMinor)) {
    int32_t net = mpos[1] - lastEdgeA;
    if (net > ARM_TURN + 1500 || net < -(ARM_TURN + 1500)) { fault = 5; armHomed = false; radHomed = false; return true; }
  }
  return false;
}
void runMove() {
  pinMode(21, INPUT);                        // re-arm the sensor input every move: the boot-time setup did not stick (v0.4)
  int32_t n0 = abs(mvN[0]), n1 = abs(mvN[1]); int sg0 = mvN[0] < 0 ? -1 : 1, sg1 = mvN[1] < 0 ? -1 : 1;
  int major = n1 > n0 ? 1 : 0; int32_t N = max(n0, n1), nm = major ? n0 : n1; int minor = 1 - major;
  int sgM = major ? sg1 : sg0, sgm = major ? sg0 : sg1;
  int32_t err = N / 2; uint32_t t = micros(); s21 = digitalRead(21); sgN = 0; sgHits[0] = sgHits[1] = 0;
  float fMinor = N ? (float)nm / N : 0; int32_t Nend = N; bool soft = false;
  for (int32_t i = 0; i < Nend && !pulseStop; i++) {
    if (mvUntilLow && !digitalRead(21)) break;                            // centre touch: the stop turned the arm off its sensor edge
    float v = min(mvHz, min(sqrtf(1e4f + 2 * mvAcc * i), sqrtf(1e4f + 2 * mvAcc * (Nend - i))));
    if (softStop && !soft) { soft = true; Nend = min(Nend, i + (int32_t)(v * v / (2 * mvAcc)) + 1); }   // slow down and stop from here
    uint32_t period = (uint32_t)(1e6f / v);
    curV[major] = v; curV[minor] = v * fMinor;
    while ((uint32_t)(micros() - t) < period) { }
    t = micros();
    bool stepMinor = false; err -= nm; if (err < 0) { err += N; stepMinor = true; }
    bool slipped = stepOnce(major, stepMinor, sgM, sgm);
    mvDone = i + 1;
    if (slipped) break;
    if ((i & 255) == 255) vTaskDelay(0);
  }
  curV[0] = curV[1] = 0;
}

// ---- drawing engine (big-fw 1.5) ----------------------------------------------------------------------------------
Preferences prefs;
struct Pt { float th, rho; };
#define MAXPTS 12000
Pt* pat = nullptr; volatile int patN = 0; int patBad = 0, patOver = 0;
int32_t cfgRmax = 24000; float cfgVball = 40, cfgVclear = 850; int cfgThSign = -1; float cfgTh0 = 0;
const float VSTART = 100, JERK[2] = {1000, 300};
enum { J_NONE = 0, J_PAT, J_SPIRAL, J_GOTO };
volatile int jobKind = J_NONE, jobEnd = 0;    // jobEnd: 1 finished, 2 halted, 3 stopped, 4 fault
volatile bool jobRun = false, pauseFlag = false, haltFlag = false, jobPaused = false;
volatile int jobI = 0, jobN = 0, jobDone = 0; volatile float jobV = 0; volatile uint32_t jobSteps = 0, jobMs = 0;
float spR0 = 0, spR1 = 1, spTurns = 1, gotoTh = 0, gotoRho = 0;
int32_t thOffSteps = 0;
bool savedOk = false; uint32_t lastBusy = 0;
const double KTH = ARM_TURN / (2 * PI);

void jobPoint(int i, float& th, float& rho) {
  if (jobKind == J_PAT) { th = pat[i].th; rho = pat[i].rho; }
  else if (jobKind == J_SPIRAL) { float u = jobN > 1 ? (float)i / (jobN - 1) : 1; rho = spR0 + (spR1 - spR0) * u; th = 2 * PI * spTurns * u; }
  else { th = gotoTh; rho = gotoRho; }
}
int32_t rawArm(float th) { return (int32_t)lround(((double)th + cfgTh0) * cfgThSign * KTH); }
void jobTarget(int i, int32_t& R, int32_t& A) {
  float th, rho; jobPoint(i, th, rho);
  A = rawArm(th) + thOffSteps;
  int32_t C = (int32_t)lroundf(constrain(rho, 0.0f, 1.0f) * cfgRmax);
  if (C < RMIN) C = RMIN; if (C > RMAX) C = RMAX;
  R = C + fdiv6(A);
}
struct Seg { int32_t dr, da, n; int idx; float fr, fa, vmax, acc, vj, ventry, vexit; };
#define NQ 192   // 2.2: was 64; at 1,000 mm/s, 64 one-degree segments were too short a look-ahead to brake in, which capped spirals near 700 mm/s
Seg sq[NQ]; int sqh = 0, sqn = 0; int32_t planR = 0, planA = 0; float lastFr = 0, lastFa = 0; bool haveLast = false;
void planAppend(int32_t R, int32_t A, int idx) {
  int32_t dr = R - planR, da = A - planA; int32_t n = max(abs(dr), abs(da)); if (!n) return;
  Seg& s = sq[(sqh + sqn) % NQ]; s.dr = dr; s.da = da; s.n = n; s.idx = idx; s.fr = (float)dr / n; s.fa = (float)da / n;
  float cmid = carriageR(planR, planA) + 0.5f * (dr - da / 6.0f);                  // carriage at mid-segment, steps
  float radial = fabsf(s.fr - s.fa / 6.0f) / 160.0f, tang = (cmid / 160.0f) * fabsf(s.fa) * (float)(2 * PI / ARM_TURN);
  float mmPer = sqrtf(radial * radial + tang * tang);                               // ball travel per major-axis step, mm
  float vm = mmPer > 1e-9f ? (jobKind == J_SPIRAL ? cfgVclear : cfgVball) / mmPer : 1e9f, ac = 1e9f;
  if (dr) { vm = min(vm, VMAX[0] / fabsf(s.fr)); ac = min(ac, AMAX[0] / fabsf(s.fr)); }
  if (da) { vm = min(vm, VMAX[1] / fabsf(s.fa)); ac = min(ac, AMAX[1] / fabsf(s.fa)); }
  s.vmax = max(vm, VSTART); s.acc = ac;
  float vj = VSTART;
  if (haveLast) {
    float d0 = fabsf(s.fr - lastFr), d1 = fabsf(s.fa - lastFa); vj = 1e9f;
    if (d0 > 1e-6f) vj = min(vj, JERK[0] / d0); if (d1 > 1e-6f) vj = min(vj, JERK[1] / d1);
  }
  s.vj = max(vj, VSTART); lastFr = s.fr; lastFa = s.fa; haveLast = true;
  planR = R; planA = A; sqn++;
}
// Backward pass over the queue: the fastest entry speed of each segment from which the path ahead can still be followed
// (the last queued segment ends at the start speed, so the look-ahead distance always covers a full stop).
void replan() {
  float vnext = VSTART;
  for (int k = sqn - 1; k >= 0; k--) {
    Seg& s = sq[(sqh + k) % NQ];
    s.vexit = min(vnext, s.vmax);
    s.ventry = min(min(s.vj, s.vmax), sqrtf(s.vexit * s.vexit + 2 * s.acc * s.n));
    vnext = s.ventry;
  }
}
void runJob() {
  pinMode(21, INPUT);
  sqh = sqn = 0; haveLast = false; planR = mpos[0]; planA = mpos[1];
  float v = VSTART; uint32_t nextT = micros(), t0 = millis(); int dirR = 0, dirA = 0; uint32_t steps = 0;
  s21 = digitalRead(21); sgN = 0; sgHits[0] = sgHits[1] = 0; jobEnd = 0; jobSteps = 0;
  for (;;) {
    while (sqn < NQ && jobI < jobN) { int32_t R, A; jobTarget(jobI, R, A); planAppend(R, A, jobI); jobI++; }
    if (!sqn) { jobEnd = 1; break; }
    replan();
    Seg s = sq[sqh]; sqh = (sqh + 1) % NQ; sqn--;
    int sr = s.dr < 0 ? -1 : 1, sa = s.da < 0 ? -1 : 1; bool turned = false;
    if (s.dr && sr != dirR) { digitalWrite(MDIR[0], sr < 0 ? HIGH : LOW); dirR = sr; turned = true; }
    if (s.da && sa != dirA) { digitalWrite(MDIR[1], sa < 0 ? HIGH : LOW); dirA = sa; turned = true; }
    if (turned) delayMicroseconds(4);
    int major = abs(s.da) > abs(s.dr) ? 1 : 0, minor = 1 - major; int32_t nm = major ? abs(s.dr) : abs(s.da);
    int sgM = major ? sa : sr, sgm = major ? sr : sa; float fm = (float)nm / s.n; int32_t err = s.n / 2;
    if (v > s.ventry) v = s.ventry;
    for (int32_t i = 0; i < s.n; i++) {
      if (pulseStop) { jobEnd = fault ? 4 : 3; goto out; }
      if (pauseFlag || haltFlag || softStop) {
        v -= s.acc / v;
        if (v <= VSTART) {
          v = VSTART;
          if (softStop) { jobEnd = 4; goto out; }
          if (haltFlag) { jobEnd = 2; goto out; }
          curV[0] = curV[1] = 0; jobV = 0; jobPaused = true;
          while (pauseFlag && !haltFlag && !pulseStop) vTaskDelay(1);
          jobPaused = false; nextT = micros();
          if (haltFlag) { jobEnd = 2; goto out; }
          if (pulseStop) { jobEnd = 3; goto out; }
        }
      } else {
        float allow = sqrtf(s.vexit * s.vexit + 2 * s.acc * (s.n - i - 1));
        v = min(min(s.vmax, allow), v + s.acc / v);
        if (v < 50) v = 50;
      }
      curV[major] = v; curV[minor] = v * fm;
      if ((int32_t)(micros() - nextT) > 600) nextT = micros();                     // fell behind (planning, Wi-Fi): do not catch up in a burst
      while ((int32_t)(micros() - nextT) < 0) { }
      nextT += (uint32_t)(1e6f / v);
      bool stepMinor = false; err -= nm; if (err < 0) { err += s.n; stepMinor = true; }
      if (stepOnce(major, stepMinor, sgM, sgm)) { jobEnd = 4; goto out; }
      if ((++steps & 255) == 0) { jobSteps = steps; jobV = v; jobMs = millis() - t0; vTaskDelay(0); }
    }
    jobDone = s.idx + 1;
  }
out:
  curV[0] = curV[1] = 0; jobV = 0; jobSteps = steps; jobMs = millis() - t0;
}
// ---- radius home by centre touch (v1.3) -----------------------------------------------------------------------------
// Measured 2026-11-22 (nine touches, camera watching): with the arm parked 5 steps inside its sensor's rising edge, driving
// the radius into the centre stop turns the arm backward through the mechanism's coupling, and the sensor drops about 8
// radius steps after contact, before any motor skips. The drop point repeated within 3 steps (0.02 mm) and moved about 1.5
// radius steps per arm step of parking depth. The camera put the ball about 300 steps (1.9 mm) from the rotation centre there.
const int32_t CTOUCH = 300;
void subMove(int32_t r, int32_t a, float hz, float acc) {
  mvN[0] = r; mvN[1] = a; mvHz = hz; mvAcc = acc; mvDone = 0;
  digitalWrite(MDIR[0], r < 0 ? HIGH : LOW); digitalWrite(MDIR[1], a < 0 ? HIGH : LOW); delayMicroseconds(50);
  runMove();
}
void armBy(int32_t d, float hz) { int32_t A = mpos[1]; subMove(fdiv6(A + d) - fdiv6(A), d, hz, 3000); }
void doHomeRadius() {                       // homeState: 1 running, 2 done, 10.. failed at that stage
  homeState = 1; homeWent = 0; pinMode(21, INPUT);
  int32_t m = ((mpos[1] % ARM_TURN) + ARM_TURN) % ARM_TURN, d = (ARM_TURN - 1500) - m;
  if (d > ARM_TURN / 2) d -= ARM_TURN; if (d < -ARM_TURN / 2) d += ARM_TURN;
  armBy(d, 2000); if (fault || pulseStop) { homeState = 10; return; }             // to 1,500 steps before the edge
  armBy(1500 + EDGE_FWD + 5, 700); if (fault || pulseStop) { homeState = 11; return; }   // forward to 5 steps inside it
  for (int k = 0; k < 600 && !digitalRead(21); k++) armBy(1, 200);                // far out the edge sits later (2.8: 600, was 40; homing
                                                                                   // from far out stopped at state 12 on 2026-11-25)
  if (!digitalRead(21)) { homeState = 12; return; }
  armBy(-45, 200); bool low = !digitalRead(21); armBy(45, 200);                   // prove the arm is at a live edge (going back it drops 32 steps before the edge)
  if (!low || !digitalRead(21)) { homeState = 13; return; }
  int32_t maxn = radHomed ? carriageR(mpos[0], mpos[1]) + 3200 : 62480;           // unknown position: the full travel
  radHomed = false;
  mvUntilLow = true; subMove(-maxn, 0, homeHz, 3000); mvUntilLow = false; homeWent = mvDone;
  if (pulseStop) { homeState = 14; return; }
  if (digitalRead(21)) { homeState = 15; return; }                                // ran the whole distance without a touch
  mpos[0] = CTOUCH + fdiv6(mpos[1]);
  subMove(1600, 0, 2000, 3000);
  if (!digitalRead(21)) { homeState = 16; return; }                               // the arm did not come back onto its edge
  radHomed = true; homeState = 2;
}
void pulseTask(void*) {
  for (;;) {
    if (homeRun) { moveRun = true; doHomeRadius(); moveRun = false; homeRun = false; pulseStop = false; softStop = false; continue; }
    if (jobRun) { moveRun = true; runJob(); moveRun = false; jobRun = false; pulseStop = false; softStop = false; haltFlag = false; pauseFlag = false; continue; }
    if (moveRun) { runMove(); moveRun = false; pulseStop = false; softStop = false; continue; }
    if (!pulseRun) { vTaskDelay(1); continue; }
    uint32_t t = micros();
    for (int32_t i = 0; i < pN && !pulseStop; i++) {
      float hz = min(pHz, 100.0f + 20.0f * i);                    // gentle ramp up: +20 Hz per pulse from 100 Hz
      int32_t left = pN - i; hz = min(hz, 100.0f + 20.0f * left);  // and down again at the end
      uint32_t period = (uint32_t)(1e6f / hz);
      while ((uint32_t)(micros() - t) < period) { }
      t = micros();
      if (pUntil >= 0 && digitalRead(pUntil) == pUntilLv) { pHitAt = i; break; }
      digitalWrite(pStep, HIGH); delayMicroseconds(5); digitalWrite(pStep, LOW);
      pulseDone = i + 1;
      if ((i & 255) == 255) vTaskDelay(0);
    }
    pulseRun = false; pulseStop = false;
  }
}

// ---- input watch (core 0, every 1 ms) ---------------------------------------------------------------------------
uint64_t watchMask = 0;
volatile uint8_t wLevel[49]; volatile uint32_t wChanges[49], wLastMs[49]; volatile int32_t wLastPulse[49];
void watchTask(void*) {
  for (;;) {
    uint64_t m = watchMask;
    for (int p = 0; p < 49; p++) if (m & (1ULL << p)) {
      uint8_t v = digitalRead(p);
      if (v != wLevel[p]) { wLevel[p] = v; wChanges[p]++; wLastMs[p] = millis(); wLastPulse[p] = pulseDone; }
    }
    vTaskDelay(1);
  }
}

// ---- TMC2209 one-wire UART (factory: UART TX GPIO17, RX GPIO18, 115200, addresses 1 and 2) -------------------------
HardwareSerial tmc(2);
uint8_t tmcCrc(const uint8_t* d, int n) {
  uint8_t crc = 0;
  for (int i = 0; i < n; i++) { uint8_t b = d[i]; for (int j = 0; j < 8; j++) { crc = ((crc >> 7) ^ (b & 1)) ? (crc << 1) ^ 0x07 : (crc << 1); b >>= 1; } }
  return crc;
}
void tmcFlush() { while (tmc.available()) tmc.read(); }
bool tmcGet(uint8_t* buf, int n, uint32_t ms) {
  uint32_t t = millis(); int k = 0;
  while (k < n && millis() - t < ms) { if (tmc.available()) buf[k++] = tmc.read(); }
  return k == n;
}
void tmcWrite(uint8_t a, uint8_t r, uint32_t v) {
  uint8_t d[8] = {0x05, a, (uint8_t)(r | 0x80), (uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v, 0};
  d[7] = tmcCrc(d, 7);
  delay(3);                                               // a quiet gap first: the second driver missed writes without it
  tmcFlush(); tmc.write(d, 8); tmc.flush();
  uint8_t echo[8]; tmcGet(echo, 8, 5);                    // the one-wire bus hears its own bytes
  delay(2);
}
// returns false on no reply or a bad checksum
bool tmcRead(uint8_t a, uint8_t r, uint32_t& v) {
  uint8_t d[4] = {0x05, a, r, 0}; d[3] = tmcCrc(d, 3);
  tmcFlush(); tmc.write(d, 4); tmc.flush();
  uint8_t echo[4]; tmcGet(echo, 4, 5);
  uint8_t rep[8]; if (!tmcGet(rep, 8, 20)) return false;
  if (rep[0] != 0x05 || rep[1] != 0xFF || rep[2] != r || rep[7] != tmcCrc(rep, 7)) return false;
  v = ((uint32_t)rep[3] << 24) | ((uint32_t)rep[4] << 16) | ((uint32_t)rep[5] << 8) | rep[6];
  return true;
}
float sgExpect(int m, float v) {
  const float* E = m ? SGA : SGE; float e = E[6];
  if (v <= SGV[0]) e = E[0] * v / SGV[0];
  else for (int k = 1; k < 7; k++) if (v <= SGV[k]) { e = E[k - 1] + (E[k] - E[k - 1]) * (v - SGV[k - 1]) / (SGV[k] - SGV[k - 1]); break; }
  if (m == 1) e *= 1.0f - 0.14f * constrain((carriageR(mpos[0], mpos[1]) - 12000) / 40000.0f, 0.0f, 1.0f);
  return e;
}
void sgTask(void*) {
  for (;;) {
    if (!moveRun) { vTaskDelay(2); continue; }
    uint32_t v[2] = {0, 0}; float sp[2] = {curV[0], curV[1]}; int32_t i = mvDone;
    xSemaphoreTake(tmcMux, portMAX_DELAY);
    bool ok[2]; vTaskDelay(2); ok[0] = tmcRead(1, 0x41, v[0]); vTaskDelay(2); ok[1] = tmcRead(2, 0x41, v[1]);   // quiet gaps: back-to-back
    xSemaphoreGive(tmcMux);                                                                               // reads failed or returned junk
    float sp2[2] = {curV[0], curV[1]};
    if (!moveRun) continue;
    if (sgN < SGN) { SgS& g = sgs[sgN]; g.i = i; g.vr = sp[0]; g.va = sp[1]; g.sr = ok[0] ? (int)v[0] : -1; g.sa = ok[1] ? (int)v[1] : -1; sgN++; }
    for (int m = 0; m < 2; m++) {
      bool cruise = sp[m] >= sgVmin && fabsf(sp2[m] - sp[m]) < 0.03f * sp[m];
      if (!sgPct[m] || !cruise) { sgHits[m] = 0; continue; }
      if (!ok[m] || v[m] <= 4) continue;                                      // no reading, or the once-per-cycle blank
      // Average of the last sgNeed readings, each as a fraction of the free value for this speed (and radius, for the arm).
      // A stalled arm at 1.2 A read 63 to 81% reading by reading (average 73%), so single readings straddle any line that
      // clears the free ones (lowest 78%, most above 87%); the average separates them: free 93% or more, stalled about 73%.
      sgRatio[m][sgHits[m] % SGAVG] = (float)v[m] / sgExpect(m, sp[m]); sgHits[m]++;
      int n = min((int)sgNeed, SGAVG);
      if (sgHits[m] >= n) {
        float sum = 0; for (int k = 0; k < n; k++) sum += sgRatio[m][(sgHits[m] - 1 - k) % SGAVG];
        sgLast[m] = sum / n;
        // Slow down and stop on the path instead of stopping dead: a dead stop from speed cost the arm 1,000 steps when the
        // alarm was false (2026-11-22). Homed flags stay; a real arm stall is confirmed by the next sensor pass or /homearm.
        if (sum / n < sgPct[m] * 0.01f && !softStop) { fault = 2 + m; softStop = true; }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(8));
  }
}
void hSg() {
  String s = "{\"n\":" + String((uint32_t)sgN) + ",\"s\":["; uint32_t n = sgN;
  uint32_t st = n > 300 ? (n + 299) / 300 : 1;   // at most 300 samples in the reply (a longer one ran out of memory)
  for (uint32_t k = 0; k < n; k += st) { SgS& g = sgs[k]; if (k) s += ","; s += "[" + String(g.i) + "," + String(g.vr) + "," + String(g.va) + "," + String(g.sr) + "," + String(g.sa) + "]"; }
  reply(200, s + "]}");
}
void hGuard() {
  if (server.hasArg("pr")) sgPct[0] = constrain(argI("pr", 85), 0, 100);
  if (server.hasArg("pa")) sgPct[1] = constrain(argI("pa", 85), 0, 100);
  if (server.hasArg("n")) sgNeed = constrain(argI("n", 8), 2, SGAVG);
  if (server.hasArg("vmin")) sgVmin = max(2000.0f, server.arg("vmin").toFloat());
  reply(200, "{\"pr\":" + String((int)sgPct[0]) + ",\"pa\":" + String((int)sgPct[1]) + ",\"n\":" + String((int)sgNeed) + ",\"vmin\":" + String((float)sgVmin, 0) + "}");
}
void hFault() { if (server.hasArg("clear")) fault = 0; reply(200, "fault " + String(fault)); }
String hex32(uint32_t v) { char b[12]; snprintf(b, sizeof b, "0x%08lx", (unsigned long)v); return String(b); }
uint32_t argU(const char* k, uint32_t d) { return server.hasArg(k) ? strtoul(server.arg(k).c_str(), nullptr, 0) : d; }
void hTmc() {
  uint8_t a = argU("a", 1), r = argU("r", 6); uint32_t v;
  xSemaphoreTake(tmcMux, portMAX_DELAY);
  if (server.hasArg("v")) tmcWrite(a, r, argU("v", 0));
  bool ok = tmcRead(a, r, v);
  xSemaphoreGive(tmcMux);
  reply(200, "{\"a\":" + String(a) + ",\"r\":" + String(r) + (server.hasArg("v") ? ",\"wrote\":\"" + hex32(argU("v", 0)) + "\"" : "") +
             ",\"read\":" + (ok ? "\"" + hex32(v) + "\"" : String("null")) + "}");
}
void hTmcInit() {
  uint32_t irun = constrain((int)argU("irun", 10), 0, 31), ihold = constrain((int)argU("ihold", 4), 0, 31);
  if (irun > 20) { reply(400, "irun above 20 refused on the bench"); return; }
  String s = "{";
  xSemaphoreTake(tmcMux, portMAX_DELAY);
  for (uint8_t a = 1; a <= 2; a++) {
    tmcWrite(a, 0x00, (1 << 6) | (1 << 7) | (1 << 8));    // GCONF: pdn_disable, mstep_reg_select, multistep_filt; StealthChop; internal ref
    tmcWrite(a, 0x10, ihold | (irun << 8) | (6UL << 16)); // IHOLD_IRUN, IHOLDDELAY 6
    tmcWrite(a, 0x6C, 0x13000054);                        // CHOPCONF: toff 4, hstrt 5, MRES 3 = 32 microsteps, intpol
    uint32_t g = 0, c = 0, io = 0, cnt = 0;
    bool ok = tmcRead(a, 0x00, g) && tmcRead(a, 0x6C, c) && tmcRead(a, 0x06, io) && tmcRead(a, 0x02, cnt);
    if (a > 1) s += ",";
    s += "\"" + String(a) + "\":" + (ok ? "{\"gconf\":\"" + hex32(g) + "\",\"chopconf\":\"" + hex32(c) + "\",\"ioin\":\"" + hex32(io) +
                                          "\",\"writes\":" + String(cnt & 255) + "}" : String("null"));
  }
  xSemaphoreGive(tmcMux);
  reply(200, s + "}");
}

// ---- web --------------------------------------------------------------------------------------------------------
void reply(int code, const String& s) { server.send(code, s.startsWith("{") ? "application/json" : "text/plain", s + "\n"); }
int argI(const char* k, int d) { return server.hasArg(k) ? server.arg(k).toInt() : d; }
// "5,13,37" -> list of pins; refuses protected pins
int parsePins(String s, int* out, int maxn, String& bad) {
  int n = 0; s += ",";
  int st = 0;
  for (int i = 0; i < (int)s.length(); i++) if (s[i] == ',') {
    String t = s.substring(st, i); st = i + 1; t.trim(); if (!t.length()) continue;
    int p = t.toInt();
    if (protectedPin(p)) { bad += t + " "; continue; }
    if (n < maxn) out[n++] = p;
  }
  return n;
}
String pinsList(uint64_t m) {
  String s = "["; bool f = true;
  for (int p = 0; p < 49; p++) if (m & (1ULL << p)) { if (!f) s += ","; s += p; f = false; }
  return s + "]";
}
void hStatus() {
  String s = "{\"fw\":\"big-fw 2.9\",\"up_s\":" + String(millis() / 1000) + ",\"ip\":\"" + WiFi.localIP().toString() +
             "\",\"rssi\":" + WiFi.RSSI() + ",\"led_pin\":" + ledPin + ",\"led_n\":" + ledN + ",\"driven\":" + pinsList(driven) +
             ",\"pulse\":{\"run\":" + (pulseRun ? 1 : 0) + ",\"step\":" + pStep + ",\"dir\":" + pDir + ",\"dv\":" + pDv +
             ",\"n\":" + pN + ",\"hz\":" + String(pHz, 0) + ",\"done\":" + String((int32_t)pulseDone) + ",\"until\":" + pUntil + ",\"hit_at\":" + String((int32_t)pHitAt) + "},\"move\":{\"run\":" + String(moveRun ? 1 : 0) + ",\"done\":" + String((int32_t)mvDone) + ",\"r\":" + String((int32_t)mpos[0]) +
       ",\"a\":" + String((int32_t)mpos[1]) + ",\"edges\":" + String((uint32_t)edgeN) + ",\"s21\":" + String(digitalRead(21)) + ",\"arm_homed\":" + String(armHomed ? 1 : 0) +
       ",\"rad_homed\":" + String(radHomed ? 1 : 0) + ",\"carriage\":" + String(carriageR(mpos[0], mpos[1])) + ",\"fault\":" + String(fault) +
       ",\"slip_err\":" + String((int32_t)slipErr) + ",\"slip_checks\":" + String((int32_t)slipChecks) +
       ",\"pr\":" + String((int)sgPct[0]) + ",\"pa\":" + String((int)sgPct[1]) + ",\"sg_avg\":[" + String((float)sgLast[0], 2) + "," + String((float)sgLast[1], 2) + "],\"home\":" + String((int)homeState) + ",\"home_went\":" + String((int32_t)homeWent) + "},\"job\":{\"run\":" + String(jobRun ? 1 : 0) +
       ",\"kind\":" + String((int)jobKind) + ",\"paused\":" + String(jobPaused ? 1 : 0) + ",\"pt\":" + String((int)jobDone) + ",\"n\":" + String((int)jobN) +
       ",\"end\":" + String((int)jobEnd) + ",\"v\":" + String((float)jobV, 0) + ",\"steps\":" + String((uint32_t)jobSteps) + ",\"ms\":" + String((uint32_t)jobMs) +
       ",\"pat_n\":" + String((int)patN) + "},\"cfg\":{\"rmax\":" + String(cfgRmax) + ",\"vball\":" + String(cfgVball, 1) + ",\"vclear\":" + String(cfgVclear, 0) + ",\"thsign\":" + String(cfgThSign) +
       ",\"th0\":" + String(cfgTh0, 4) + ",\"saved\":" + String(savedOk ? 1 : 0) + "},\"watch\":{";
  bool f = true;
  for (int p = 0; p < 49; p++) if (watchMask & (1ULL << p)) {
    if (!f) s += ","; f = false;
    s += "\"" + String(p) + "\":[" + String((int)wLevel[p]) + "," + String((uint32_t)wChanges[p]) + "," +
         String((int32_t)wLastPulse[p]) + "," + String((uint32_t)wLastMs[p]) + "]";
  }
  reply(200, s + "}}");
}
void hLed() {
  if (pulseRun) { reply(409, "busy: pulse job running"); return; }
  if (server.hasArg("n")) ledN = constrain(argI("n", ledN), 1, LED_MAX);
  int pin = argI("pin", ledPin < 0 ? 38 : ledPin);
  if (protectedPin(pin)) { reply(400, "protected pin"); return; }
  if (!ledAttach(pin)) { reply(500, "rmt init failed"); return; }
  int i0 = argI("i", 0), k = argI("k", ledN), r = argI("r", 0), g = argI("g", 0), b = argI("b", 0);
  if (server.hasArg("off")) k = 0;
  fxMode = 0;                                 // a static frame stops any effect
  xSemaphoreTake(ledMux, portMAX_DELAY);
  for (int p = 0; p < ledN; p++) { bool on = p >= i0 && p < i0 + k; LR[p] = on ? r : 0; LG[p] = on ? g : 0; LB[p] = on ? b : 0; }
  ledShow();
  xSemaphoreGive(ledMux);
  reply(200, "led pin " + String(ledPin) + " n " + ledN + " lit " + i0 + ".." + (i0 + k - 1));
}
void hLedFx() {
  if (pulseRun) { reply(409, "busy: pulse job running"); return; }
  if (server.hasArg("n")) ledN = constrain(argI("n", ledN), 1, LED_MAX);
  int pin = argI("pin", ledPin < 0 ? 38 : ledPin);
  if (protectedPin(pin)) { reply(400, "protected pin"); return; }
  if (!ledAttach(pin)) { reply(500, "rmt init failed"); return; }
  String mode = server.hasArg("mode") ? server.arg("mode") : String("spin");
  if (mode == "off") {
    fxMode = 0;
    xSemaphoreTake(ledMux, portMAX_DELAY);
    for (int p = 0; p < ledN; p++) { LR[p] = LG[p] = LB[p] = 0; }
    ledShow();
    xSemaphoreGive(ledMux);
    reply(200, "{\"fx\":\"off\"}"); return;
  }
  if (fxMode != 1) { fxR = LR[0]; fxG = LG[0]; fxB = LB[0]; }    // ease from whatever is lit now
  fxTR = constrain(argI("r", 255), 0, 255); fxTG = constrain(argI("g", 244), 0, 255); fxTB = constrain(argI("b", 229), 0, 255);
  if (server.hasArg("period")) fxPeriod = (uint32_t)constrain((long)(server.arg("period").toFloat() * 1000), 2000L, 600000L);
  if (server.hasArg("base")) fxBase = constrain(server.arg("base").toFloat(), 0.0f, 1.0f);
  if (server.hasArg("width")) fxWidth = constrain(server.arg("width").toFloat(), 0.05f, 1.0f);
  fxMode = 1;
  reply(200, "{\"fx\":\"spin\",\"r\":" + String((int)fxTR) + ",\"g\":" + String((int)fxTG) + ",\"b\":" + String((int)fxTB) +
             ",\"period_s\":" + String(fxPeriod / 1000.0f, 1) + ",\"base\":" + String(fxBase, 2) + ",\"width\":" + String(fxWidth, 2) + "}");
}
void ledTask(void*) {
  uint32_t last = millis();
  for (;;) {
    vTaskDelay(40);                           // 25 frames a second
    uint32_t now = millis();
    if (fxMode != 1 || ledPin < 0) { last = now; continue; }
    float dt = (now - last) / 1000.0f; last = now;
    float k = 1.0f - expf(-dt / 1.0f);        // about 3 s to settle on a new colour
    fxR += (fxTR - fxR) * k; fxG += (fxTG - fxG) * k; fxB += (fxTB - fxB) * k;
    float ph = (float)(now % fxPeriod) / (float)fxPeriod, hw = fxWidth * 0.5f;
    xSemaphoreTake(ledMux, portMAX_DELAY);
    if (fxMode == 1) {
      for (int p = 0; p < ledN; p++) {
        float d = fabsf((float)p / ledN - ph); if (d > 0.5f) d = 1.0f - d;
        float w = d < hw ? 0.5f * (1.0f + cosf(PI * d / hw)) : 0.0f;
        float lv = fxBase + (1.0f - fxBase) * w;
        LR[p] = (uint8_t)constrain(fxR * lv + 0.5f, 0.0f, 255.0f);
        LG[p] = (uint8_t)constrain(fxG * lv + 0.5f, 0.0f, 255.0f);
        LB[p] = (uint8_t)constrain(fxB * lv + 0.5f, 0.0f, 255.0f);
      }
      ledShow();
    }
    xSemaphoreGive(ledMux);
  }
}
void hInputs() {
  int pins[49]; String bad; int n = parsePins(server.arg("pins"), pins, 49, bad);
  String pull = server.arg("pull");
  String s = "{";
  for (int i = 0; i < n; i++) {
    int p = pins[i];
    if ((driven >> p) & 1) { if (p == ledPin) { fxMode = 0; xSemaphoreTake(ledMux, portMAX_DELAY); rmtDeinit(ledPin); ledPin = -1; xSemaphoreGive(ledMux); } driven &= ~(1ULL << p); }
    pinMode(p, pull == "up" ? INPUT_PULLUP : (pull == "down" ? INPUT_PULLDOWN : INPUT));
  }
  delay(2);
  for (int i = 0; i < n; i++) { if (i) s += ","; s += "\"" + String(pins[i]) + "\":" + digitalRead(pins[i]); }
  if (bad.length()) s += String(n ? "," : "") + "\"refused\":\"" + bad + "\"";
  reply(200, s + "}");
}
void hWatch() {
  if (server.hasArg("clear")) { watchMask = 0; reply(200, "watch cleared"); return; }
  int pins[49]; String bad; int n = parsePins(server.arg("pins"), pins, 49, bad);
  for (int i = 0; i < n; i++) {
    int p = pins[i]; wLevel[p] = digitalRead(p); wChanges[p] = 0; wLastPulse[p] = -1; wLastMs[p] = 0; watchMask |= (1ULL << p);
  }
  reply(200, "watching " + pinsList(watchMask) + (bad.length() ? " refused " + bad : ""));
}
void hPin() {
  int p = argI("n", -1), v = argI("v", 0);
  if (protectedPin(p)) { reply(400, "protected pin"); return; }
  if (pulseRun && (p == pStep || p == pDir)) { reply(409, "busy"); return; }
  if (p == ledPin) { fxMode = 0; xSemaphoreTake(ledMux, portMAX_DELAY); rmtDeinit(ledPin); ledPin = -1; xSemaphoreGive(ledMux); }
  drivePin(p, v); reply(200, "pin " + String(p) + " = " + v);
}
void hFloat() {
  int p = argI("n", -1);
  if (protectedPin(p)) { reply(400, "protected pin"); return; }
  if (pulseRun && (p == pStep || p == pDir)) { reply(409, "busy"); return; }
  if (p == ledPin) { fxMode = 0; xSemaphoreTake(ledMux, portMAX_DELAY); rmtDeinit(ledPin); ledPin = -1; xSemaphoreGive(ledMux); }
  floatPin(p); reply(200, "pin " + String(p) + " floating");
}
void hPulse() {
  if (pulseRun) { reply(409, "busy"); return; }
  int st = argI("step", -1), dr = argI("dir", -1);
  int32_t n = argI("n", 0); float hz = server.hasArg("hz") ? server.arg("hz").toFloat() : 200;
  if (protectedPin(st) || (dr >= 0 && protectedPin(dr)) || st == dr) { reply(400, "bad pins"); return; }
  if (n < 1 || n > 64000 || hz < 1 || hz > 6000) { reply(400, "n 1..64000, hz 1..6000"); return; }
  if (st == ledPin || dr == ledPin) { fxMode = 0; xSemaphoreTake(ledMux, portMAX_DELAY); rmtDeinit(ledPin); ledPin = -1; xSemaphoreGive(ledMux); }
  pStep = st; pDir = dr; pDv = argI("dv", 0); pN = n; pHz = hz; pulseDone = 0; pHitAt = -1;
  pUntil = argI("until", -1); pUntilLv = argI("lv", 1);
  markMoving(); armHomed = radHomed = armRef = false;      // raw pulses are not counted: positions are unknown afterwards
  if (pUntil >= 0 && protectedPin(pUntil)) { reply(400, "bad until pin"); return; }
  if (pUntil >= 0 && hz > 1000) { reply(400, "stop-on-switch moves are limited to 1000 Hz"); return; }
  if (dr >= 0) drivePin(dr, pDv);
  drivePin(st, 0);
  delayMicroseconds(50);
  pulseStop = false; pulseRun = true;
  reply(200, "pulsing " + String(n) + " on " + st + (dr >= 0 ? " dir " + String(dr) + "=" + pDv : "") + " at " + String(hz, 0) + " Hz");
}
void hMove() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (((driven >> 11) & 1) == 0 || ((driven >> 34) & 1) == 0 || outLv[11] || outLv[34]) {
    reply(409, "enable both drivers first: /pin?n=11&v=0 and /pin?n=34&v=0"); return;
  }
  int32_t r = argI("r", 0), a = argI("a", 0); float hz = server.hasArg("hz") ? server.arg("hz").toFloat() : 1000;
  float acc = server.hasArg("acc") ? server.arg("acc").toFloat() : 2000;
  if (abs(r) > 64000 || abs(a) > 160000 || hz < 50 || hz > 16000 || acc < 100 || acc > 400000) { reply(400, "limits: |r|<=64000 |a|<=160000 hz 50..16000 acc 100..400000"); return; }
  if (radHomed) {
    int32_t endR = carriageR(mpos[0] + r, mpos[1] + a);
    if (endR < RMIN || endR > RMAX) { reply(400, "refused: carriage would end at " + String(endR) + " steps, limits " + String(RMIN) + ".." + String(RMAX)); return; }
  }
  else if (abs(carriageR(r, a)) > 8000) { reply(400, "refused: carriage position unknown, so one move may shift it 8000 steps at most"); return; }
  if (fault) { reply(409, "fault " + String(fault) + " (1 arm slipped, 2 radius stall alarm, 3 arm stall alarm); /homearm or /fault?clear=1"); return; }
  if (!server.hasArg("raw")) {               // cut the major-axis speed and acceleration so each motor stays inside its limits
    float N = max(abs(r), abs(a)); if (N < 1) N = 1;
    for (int m = 0; m < 2; m++) {
      float f = abs(m ? a : r) / N; if (f <= 0) continue;
      hz = min(hz, VMAX[m] / f); acc = min(acc, AMAX[m] / f);
    }
  }
  markMoving();
  mvN[0] = r; mvN[1] = a; mvHz = hz; mvAcc = acc; mvDone = 0;
  drivePin(MDIR[0], r < 0 ? 1 : 0); drivePin(MDIR[1], a < 0 ? 1 : 0); drivePin(MSTEP[0], 0); drivePin(MSTEP[1], 0);
  delayMicroseconds(50);
  pulseStop = false; moveRun = true;
  reply(200, "moving r " + String(r) + " a " + String(a) + " hz " + String(hz, 0) + " acc " + String(acc, 0));
}
void hZero() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  markMoving();
  if (server.hasArg("r")) mpos[0] = argI("r", 0);
  if (server.hasArg("a")) { mpos[1] = argI("a", 0); lastEdgeA = -1000000; }   // 2.6: re-arm the not-turning watchdog at the next sensor change
  reply(200, "pos r " + String((int32_t)mpos[0]) + " a " + String((int32_t)mpos[1]));
}
void hEdges() {
  String s = "{\"n\":" + String((uint32_t)edgeN) + ",\"edges\":[";
  uint32_t n = edgeN, first = n > 64 ? n - 64 : 0;
  for (uint32_t i = first; i < n; i++) { Edge& e = edges[i % 64]; if (i > first) s += ","; s += "[" + String(e.r) + "," + String(e.a) + "," + String(e.lv) + "]"; }
  if (server.hasArg("clear")) edgeN = 0;
  reply(200, s + "]}");
}
void hEnable() {                          // /enable?on=1: both drivers at factory current (IRUN 17, IHOLD 8)
  bool on = argI("on", 1);
  if (on) {
    xSemaphoreTake(tmcMux, portMAX_DELAY);
    // Radius IRUN 17 (about 1.0 A), arm IRUN 20 (about 1.2 A, the factory's higher setting): at 1.0 A the arm skipped whole
    // electrical cycles at slow speed with the carriage beyond about 335 mm (measured 2026-11-22); at 1.2 A it did not.
    for (uint8_t a = 1; a <= 2; a++) { tmcWrite(a, 0x00, 0x1C0); tmcWrite(a, 0x6C, 0x13000054); tmcWrite(a, 0x10, 8 | ((a == 2 ? 20UL : 17UL) << 8) | (6UL << 16)); }
    xSemaphoreGive(tmcMux);
    drivePin(MSTEP[0], 0); drivePin(MSTEP[1], 0); drivePin(MDIR[0], 0); drivePin(MDIR[1], 0);   // step lines are outputs before any move
    drivePin(11, 0); drivePin(34, 0);
  } else { markMoving(); drivePin(11, 1); drivePin(34, 1); armHomed = radHomed = armRef = false; }
  reply(200, on ? "drivers on: radius 1.0 A, arm 1.2 A" : "drivers off (position forgotten)");
}
// arm home: forward sweep (radius held) up to 1.3 turns until the sensor rises; that point becomes a = 0
void hHomeArm() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (outLv[11] || outLv[34] || !((driven >> 11) & 1)) { reply(409, "drivers off: /enable first"); return; }
  markMoving();
  bool radWas = radHomed || fault == 1; armHomed = false; fault = 0; uint32_t n0 = edgeN;
  if (digitalRead(21)) { mvN[0] = -6400 / 4; mvN[1] = -ARM_TURN / 4; }    // start inside the zone: back off a quarter turn
  else { mvN[0] = 0; mvN[1] = 0; }
  drivePin(MDIR[0], mvN[0] < 0); drivePin(MDIR[1], mvN[1] < 0); mvHz = 3000; mvAcc = 3000; pulseStop = false;
  if (mvN[1]) { moveRun = true; while (moveRun) delay(5); }
  n0 = edgeN;
  mvN[0] = 49920 / 6; mvN[1] = 49920; drivePin(MDIR[0], 0); drivePin(MDIR[1], 0); mvHz = 2000; mvAcc = 3000; pulseStop = false;
  moveRun = true;
  int32_t hitA = 0; bool hit = false;
  while (moveRun) { if (edgeN > n0) { for (uint32_t i = n0; i < edgeN; i++) if (edges[i % 64].lv) { hit = true; hitA = edges[i % 64].a; } if (hit) { pulseStop = true; } } delay(1); }
  if (!hit) { reply(500, "sensor not found in 1.3 turns"); return; }
  int32_t over = mpos[1] - hitA;            // steps travelled past the edge while stopping
  int32_t oldA = mpos[1], want = EDGE_FWD + over, corr = 0;
  if (armRef) {                             // the counter was tied to the sensor before: snap to the nearest matching turn,
    corr = (((want - oldA) % ARM_TURN) + ARM_TURN) % ARM_TURN; if (corr > ARM_TURN / 2) corr -= ARM_TURN;   // and leave r alone, so
    mpos[1] = oldA + corr; lastEdgeA = mpos[1];   // the carriage estimate r - a/6 picks up the arm steps that were lost
    radHomed = radWas && abs(corr) < ARM_TURN / 4;
  } else {
    mpos[1] = want; lastEdgeA = mpos[1];
    mpos[0] += fdiv6(want) - fdiv6(oldA);   // keep the carriage estimate unchanged
  }
  armHomed = armRef = true;
  reply(200, "{\"a\":" + String((int32_t)mpos[1]) + ",\"corrected\":" + String(corr) + ",\"rad_homed\":" + String(radHomed ? 1 : 0) + "}");
}
// /setcarriage?c=N: the carriage's distance from the arm's rotation centre, in steps, as measured by the camera.
void hSetCarriage() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (!server.hasArg("c")) { reply(400, "c= is required"); return; }
  int32_t c = argI("c", 0); if (c < 0 || c > 60000) { reply(400, "c 0..60000"); return; }
  markMoving(); mpos[0] = c + fdiv6(mpos[1]); radHomed = true;
  reply(200, "carriage " + String(carriageR(mpos[0], mpos[1])));
}
// /homeradius[?hz=1600]: find the centre by touching the stop (see doHomeRadius). Runs in the background; watch
// "home" in /status: 1 running, 2 done, 10 and up = failed at that stage. Needs the arm homed first.
void hHomeRadius() {
  if (pulseRun || moveRun || jobRun || homeRun) { reply(409, "busy"); return; }
  if (outLv[11] || outLv[34] || !((driven >> 11) & 1)) { reply(409, "drivers off: /enable first"); return; }
  if (fault) { reply(409, "fault " + String(fault)); return; }
  if (!armHomed) { reply(409, "home the arm first: /homearm"); return; }
  homeHz = constrain(server.hasArg("hz") ? server.arg("hz").toFloat() : 1600.0f, 400.0f, 2000.0f);
  markMoving(); drivePin(MSTEP[0], 0); drivePin(MSTEP[1], 0);
  pulseStop = false; homeState = 1; homeRun = true;
  reply(200, "homing the radius");
}
void hOff() {                               // stop at once and float every pin this firmware drove
  pulseStop = true; uint32_t t = millis(); while ((pulseRun || moveRun) && millis() - t < 300) delay(1);
  if (ledPin >= 0) { fxMode = 0; xSemaphoreTake(ledMux, portMAX_DELAY); rmtDeinit(ledPin); ledPin = -1; xSemaphoreGive(ledMux); }
  for (int p = 0; p < 49; p++) if ((driven >> p) & 1) floatPin(p);
  armHomed = false;
  reply(200, "stopped at pulse " + String((int32_t)pulseDone) + "; all pins floating");
}
void hStop() {                              // stop at once; drivers stay on and hold
  bool was = pulseRun || moveRun;
  if (was) { pulseStop = true; uint32_t t = millis(); while ((pulseRun || moveRun) && millis() - t < 300) delay(1); }
  reply(200, was ? "stopped" : "idle");       // the motion task clears the stop flag itself when it has stopped
}
void hHalt() { if (jobRun) haltFlag = true; reply(200, jobRun ? "halting" : "idle"); }
void hPause() { pauseFlag = jobRun && argI("on", 1); reply(200, pauseFlag ? "pausing" : "running"); }
// ---- persistence: settings, and the position once motion has been over for 3 s ------------------------------------
void markMoving() { if (savedOk) { prefs.putBool("ok", false); savedOk = false; } lastBusy = millis(); }
void loadState() {
  prefs.begin("big", false);
  cfgRmax = constrain(prefs.getInt("rmax", 24000), 1600, RMAX); cfgVball = prefs.getFloat("vball", 40); cfgVclear = prefs.getFloat("vclear", 850);
  cfgThSign = prefs.getInt("thsign", -1) < 0 ? -1 : 1; cfgTh0 = prefs.getFloat("th0", 0);
  if (prefs.getBool("ok", false)) {         // the motors were at rest at a saved position: trust it until /homearm confirms the arm
    mpos[0] = prefs.getInt("r", 0); mpos[1] = prefs.getInt("a", 0); radHomed = prefs.getBool("radh", false); armRef = true; savedOk = true;
  }
}
void savePos() {
  prefs.putInt("r", mpos[0]); prefs.putInt("a", mpos[1]); prefs.putBool("radh", radHomed); prefs.putBool("ok", true); savedOk = true;
}
void hCfg() {
  if (jobRun || moveRun || pulseRun) { reply(409, "busy"); return; }
  if (server.hasArg("rmax")) { cfgRmax = constrain(argI("rmax", cfgRmax), 1600, RMAX); prefs.putInt("rmax", cfgRmax); }
  if (server.hasArg("vball")) { cfgVball = constrain(server.arg("vball").toFloat(), 2.0f, 1500.0f); prefs.putFloat("vball", cfgVball); }
  if (server.hasArg("vclear")) { cfgVclear = constrain(server.arg("vclear").toFloat(), 2.0f, 1500.0f); prefs.putFloat("vclear", cfgVclear); }
  if (server.hasArg("thsign")) { cfgThSign = argI("thsign", -1) < 0 ? -1 : 1; prefs.putInt("thsign", cfgThSign); }
  if (server.hasArg("th0")) { cfgTh0 = server.arg("th0").toFloat(); prefs.putFloat("th0", cfgTh0); }
  reply(200, "{\"rmax\":" + String(cfgRmax) + ",\"vball\":" + String(cfgVball, 1) + ",\"vclear\":" + String(cfgVclear, 0) + ",\"thsign\":" + String(cfgThSign) + ",\"th0\":" + String(cfgTh0, 4) + "}");
}
// ---- pattern upload and jobs --------------------------------------------------------------------------------------
char thrLine[96]; int thrLen = 0; bool thrOk = false;
void thrFeed(char c) {
  if (c != '\n' && c != '\r') { if (thrLen < 95) thrLine[thrLen++] = c; return; }
  thrLine[thrLen] = 0; thrLen = 0;
  char* p = thrLine; while (*p == ' ' || *p == '\t') p++;
  if (!*p || *p == '#') return;
  char* e; float th = strtof(p, &e); if (e == p) { patBad++; return; }
  while (*e == ' ' || *e == ',' || *e == '\t') e++;
  char* e2; float rho = strtof(e, &e2); if (e2 == e) { patBad++; return; }
  if (patN < MAXPTS) { pat[patN].th = th; pat[patN].rho = rho; patN = patN + 1; } else patOver++;
}
void thrRaw() {
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    thrOk = !jobRun;
    if (!pat) thrOk = false;
    if (thrOk) { patN = 0; patBad = 0; patOver = 0; thrLen = 0; }
  } else if (r.status == RAW_WRITE) { if (thrOk) for (size_t i = 0; i < r.currentSize; i++) thrFeed((char)r.buf[i]); }
  else if (r.status == RAW_END) { if (thrOk) thrFeed('\n'); }
}
void thrDone() {
  reply(thrOk ? 200 : 409, thrOk ? "{\"points\":" + String((int)patN) + ",\"bad_lines\":" + String(patBad) + ",\"dropped\":" + String(patOver) + "}" : String("busy or out of memory"));
}
// Start a job. The arm keeps its present turn count: patterns take the nearest equivalent angle, spirals start where the arm is.
bool startJob(int kind, int n) {
  if (pulseRun || moveRun || jobRun) { reply(409, "busy"); return false; }
  if (outLv[11] || outLv[34] || !((driven >> 11) & 1) || !((driven >> 34) & 1)) { reply(409, "drivers off: /enable first"); return false; }
  if (fault) { reply(409, "fault " + String(fault) + ": /homearm or /fault?clear=1"); return false; }
  if (!armHomed || !radHomed) { reply(409, String("not homed: ") + (armHomed ? "" : "/homearm ") + (radHomed ? "" : "/setcarriage")); return false; }
  if (n < 1) { reply(400, "nothing to draw"); return false; }
  markMoving();
  int32_t k = mpos[1] / (6 * ARM_TURN);     // keep the counters small: drop whole multiples of 6 turns (6,400 radius steps per turn)
  if (k) { mpos[1] -= k * 6 * ARM_TURN; mpos[0] -= k * 6 * 6400; lastEdgeA -= k * 6 * ARM_TURN; }
  jobKind = kind; jobN = n; jobI = 0; jobDone = 0; haltFlag = pauseFlag = jobPaused = false; pulseStop = false;
  float th, rho; jobPoint(0, th, rho); int32_t raw = rawArm(th);
  if (kind == J_SPIRAL || (kind == J_GOTO && !server.hasArg("th"))) thOffSteps = mpos[1] - raw;
  else thOffSteps = (int32_t)lround((double)(mpos[1] - raw) / ARM_TURN) * ARM_TURN;
  drivePin(MSTEP[0], 0); drivePin(MSTEP[1], 0);
  jobRun = true;
  return true;
}
void hPlay() {
  if (!pat || patN < 1) { reply(409, "no pattern: POST /thr first"); return; }
  if (startJob(J_PAT, patN)) reply(200, "{\"playing\":" + String((int)patN) + "}");
}
void hSpiral() {
  float from = server.hasArg("from") ? server.arg("from").toFloat() : 0, to = server.hasArg("to") ? server.arg("to").toFloat() : 1;
  float pitch = server.hasArg("pitch") ? server.arg("pitch").toFloat() : 0.02f;
  if (fabsf(pitch) < 0.002f || from < 0 || from > 1 || to < 0 || to > 1 || from == to) { reply(400, "from, to 0..1 and different; |pitch| >= 0.002"); return; }
  spR0 = from; spR1 = to; spTurns = fabsf(to - from) / pitch;                     // sign of pitch = direction of rotation
  int n = (int)(fabsf(spTurns) * 360) + 2;
  if (startJob(J_SPIRAL, n)) reply(200, "{\"spiral_turns\":" + String(spTurns, 2) + ",\"points\":" + String(n) + "}");
}
void hGoto() {
  if (!server.hasArg("rho")) { reply(400, "rho= is required"); return; }
  gotoRho = server.arg("rho").toFloat(); gotoTh = server.hasArg("th") ? server.arg("th").toFloat() : 0;
  if (startJob(J_GOTO, 1)) reply(200, "going");
}
bool keyOk() { return server.header("X-Key") == ADMIN_KEY || server.arg("key") == ADMIN_KEY; }
bool otaOk = false; String otaErr; uint32_t restartAt = 0;
void otaRaw() {
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    otaOk = false; otaErr = "";
    if (!keyOk()) { otaErr = "bad key"; return; }
    if (pulseRun || moveRun || jobRun) { otaErr = "busy"; return; }
    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) { otaErr = Update.errorString(); return; }
    otaOk = true;
  } else if (r.status == RAW_WRITE) {
    if (otaOk && Update.write(r.buf, r.currentSize) != r.currentSize) { otaOk = false; otaErr = Update.errorString(); }
  } else if (r.status == RAW_END) {
    if (otaOk && !Update.end(true)) { otaOk = false; otaErr = Update.errorString(); }
  } else if (r.status == RAW_ABORTED) { Update.abort(); otaOk = false; otaErr = "aborted"; }
}
void otaDone() {
  if (otaOk) { reply(200, "updated, restarting"); restartAt = millis() + 800; }
  else reply(otaErr == "bad key" ? 403 : (otaErr == "busy" ? 409 : 500), "update failed: " + otaErr);
}

void setup() {
  ledMux = xSemaphoreCreateMutex();
  Serial.begin(115200);
  Serial.println("\nbig-fw 2.9: no pins driven except the motor drivers' serial line (17/18)");
  pat = (Pt*)malloc(sizeof(Pt) * MAXPTS);   // 96 KB, taken before Wi-Fi fragments the heap
  tmcMux = xSemaphoreCreateMutex();
  loadState();
  tmc.begin(115200, SERIAL_8N1, 18, 17);
  pinMode(21, INPUT);                       // arm home sensor; reads 0 forever if never set up as an input (found 2026-11-22)
  drivePin(5, 1);                           // sensor supply as the factory drives it (models 2/3: GPIO5 high)
  WiFi.mode(WIFI_STA); WiFi.setHostname("oasis-big"); WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  Serial.print("ip "); Serial.println(WiFi.localIP());
  if (MDNS.begin("oasis-big")) MDNS.addService("http", "tcp", 80);
  static const char* hdrs[] = {"X-Key"};
  server.collectHeaders(hdrs, 1);
  server.on("/status", hStatus); server.on("/led", hLed); server.on("/ledfx", hLedFx); server.on("/inputs", hInputs); server.on("/watch", hWatch);
  server.on("/pin", hPin); server.on("/float", hFloat); server.on("/pulse", hPulse); server.on("/stop", hStop); server.on("/off", hOff);
  server.on("/halt", hHalt); server.on("/pause", hPause); server.on("/cfg", hCfg); server.on("/play", hPlay); server.on("/spiral", hSpiral);
  server.on("/goto", hGoto); server.on("/thr", HTTP_POST, thrDone, thrRaw);
  server.on("/enable", hEnable); server.on("/homearm", hHomeArm); server.on("/homeradius", hHomeRadius);
  server.on("/move", hMove); server.on("/zero", hZero); server.on("/edges", hEdges);
  server.on("/setcarriage", hSetCarriage); server.on("/sg", hSg); server.on("/guard", hGuard); server.on("/fault", hFault);
  server.on("/tmc", hTmc); server.on("/tmcinit", hTmcInit);
  server.on("/update", HTTP_POST, otaDone, otaRaw);
  server.begin();
  xTaskCreatePinnedToCore(pulseTask, "pulse", 4096, nullptr, 5, nullptr, 1);
  xTaskCreatePinnedToCore(watchTask, "watch", 4096, nullptr, 2, nullptr, 0);
  xTaskCreatePinnedToCore(sgTask, "sg", 4096, nullptr, 2, nullptr, 0);
  xTaskCreatePinnedToCore(webTask, "web", 8192, nullptr, 1, nullptr, 0);
  xTaskCreatePinnedToCore(ledTask, "led", 4096, nullptr, 1, nullptr, 0);
}
// The web server runs on core 0 so the pulse task can own core 1 without starving it.
void webTask(void*) {
  uint32_t lastPrint = 0, lastTry = 0;
  for (;;) {
    server.handleClient();
    if (restartAt && millis() > restartAt) ESP.restart();
    if (pulseRun || moveRun || jobRun) lastBusy = millis();
    else if (!savedOk && armRef && millis() - lastBusy > 3000) savePos();
    if (millis() - lastPrint > 10000) { lastPrint = millis(); Serial.print("ip "); Serial.println(WiFi.localIP()); }
    if (WiFi.status() != WL_CONNECTED && millis() - lastTry > 15000) { lastTry = millis(); WiFi.reconnect(); }
    vTaskDelay(1);
  }
}
void loop() { vTaskDelay(1000); }
