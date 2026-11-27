/* Oasis 36-inch (coffee table) bench firmware v0.6 - 2026-11-22.
 * Board: "Oasis Side/Coffee Table MAIN PCB V0.6", ESP32-S3, two TMC2209 step/direction motor drivers.
 * Purpose: find the pins and learn the mechanism safely, before the drawing engine is ported.
 *
 * SAFETY: at boot it drives NO pin (only Wi-Fi and the USB serial log). Every output is an explicit web command,
 * protected pins are refused, pulse jobs are capped in count and rate, and /stop floats every pin it drove.
 * Never flash the Mini build onto this board: its 20 kHz coil PWM on a STEP pin would spin a motor flat out.
 *
 * Commands (GET; replies are JSON or short text):
 *   /status                       uptime, Wi-Fi, LED setup, driven pins, pulse job, watched inputs
 *   /led?pin=38&n=157&r=&g=&b=&i=0&k=157    one frame: LEDs i..i+k-1 in colour r,g,b (0..255), the rest off.
 *                                 pin and n stick until changed. /led?off=1 sends all off.
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
 *                                 camera). After that, moves ending outside 800..56,800 carriage steps are refused.
 *   /homeradius?pct=82&hz=3000&max=N  UNTESTED. Inward run of at most N steps with the stall alarm armed on the radius
 *                                 driver; if it trips (centre stop), backs out 1,600 and calls that carriage = 1,600.
 *   /sg                           StallGuard samples of the last move: [step, radius steps/s, arm steps/s, sg radius, sg arm]
 *   /guard?pr=82&pa=82&n=6&vmin=3000   stall alarm: stop the move (fault 2 radius, 3 arm) when that motor cruises at vmin
 *                                 steps/s or more and n readings in a row are under pr (pa) percent of the free-running
 *                                 value for that speed. 0 percent turns that alarm off. Blind below about 3,000 steps/s.
 *   /fault?clear=1                clear a fault (positions stay marked unknown until homed or set again)
 *   /stop                         end the pulse job and float every pin this firmware drove
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
bool ledAttach(int pin) {
  if (pin == ledPin) return true;
  if (ledPin >= 0) { rmtDeinit(ledPin); floatPin(ledPin); ledPin = -1; }
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
volatile bool moveRun = false; int32_t mvN[2] = {0, 0}; float mvHz = 0, mvAcc = 0; volatile int32_t mvDone = 0;
struct Edge { int32_t r, a; uint8_t lv; };
Edge edges[64]; volatile uint32_t edgeN = 0; uint8_t s21 = 0;
// Guards (v0.4). Arm: after /homearm, a = 0 at the sensor's rising edge going forward (DIR13 low); every later forward
// rising edge must land on a multiple of 38400 (one arm turn) within SLIP_TOL steps, or the move stops with a fault.
// Radius: after /homeradius, carriage radius = r - a/6 (turning the arm forward pulls the carriage in 1/6 step per arm
// step) and every move whose end lies outside [RMIN, RMAX] is refused.
const int32_t ARM_TURN = 38400, SLIP_TOL = 64, RMIN = 800, RMAX = 56800;
// Sensor rising edge, measured 2026-11-22 over 14 turns at three radii: forward at a = 3..12, backward at 805..812.
const int32_t EDGE_FWD = 6, EDGE_BACK = 808;
bool armRef = false;                         // the arm counter has been tied to the sensor at least once since power-up
volatile int32_t lastEdgeA = -1000000; volatile int lastEdgeSg = 0;       // arm counter at the previous sensor change (to ignore chatter at an edge)
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
volatile int sgPct[2] = {82, 82}, sgNeed = 6; volatile float sgVmin = 3000; int sgHits[2] = {0, 0};
// Qualified limits (2026-11-22): the radius never lost position up to 16,000 steps/s and 400,000 steps/s^2; the arm was
// fine to 16,000 steps/s but lost position starting at 200,000 steps/s^2 near the centre and at 50,000 far out.
const float VMAX[2] = {8000, 8000}, AMAX[2] = {100000, 10000};
SemaphoreHandle_t tmcMux;
volatile bool armHomed = false, radHomed = false; volatile int fault = 0; volatile int32_t slipErr = 0, slipChecks = 0;
inline int32_t carriageR(int32_t r, int32_t a) { return r - (int32_t)floorf(a / 6.0f); }
void runMove() {
  pinMode(21, INPUT);                        // re-arm the sensor input every move: the boot-time setup did not stick (v0.4)
  int32_t n0 = abs(mvN[0]), n1 = abs(mvN[1]); int sg0 = mvN[0] < 0 ? -1 : 1, sg1 = mvN[1] < 0 ? -1 : 1;
  int major = n1 > n0 ? 1 : 0; int32_t N = max(n0, n1), nm = major ? n0 : n1; int minor = 1 - major;
  int sgM = major ? sg1 : sg0, sgm = major ? sg0 : sg1;
  int32_t err = N / 2; uint32_t t = micros(); s21 = digitalRead(21); sgN = 0; sgHits[0] = sgHits[1] = 0;
  float fMinor = N ? (float)nm / N : 0;
  for (int32_t i = 0; i < N && !pulseStop; i++) {
    float v = min(mvHz, min(sqrtf(1e4f + 2 * mvAcc * i), sqrtf(1e4f + 2 * mvAcc * (N - i))));
    uint32_t period = (uint32_t)(1e6f / v);
    curV[major] = v; curV[minor] = v * fMinor;
    while ((uint32_t)(micros() - t) < period) { }
    t = micros();
    bool stepMinor = false; err -= nm; if (err < 0) { err += N; stepMinor = true; }
    digitalWrite(MSTEP[major], HIGH); if (stepMinor) digitalWrite(MSTEP[minor], HIGH);
    delayMicroseconds(5);
    digitalWrite(MSTEP[major], LOW); if (stepMinor) digitalWrite(MSTEP[minor], LOW);
    mpos[major] += sgM; if (stepMinor) mpos[minor] += sgm;
    mvDone = i + 1;
    uint8_t v21 = digitalRead(21);
    if (v21 != s21) {
      s21 = v21; Edge& e = edges[edgeN % 64]; e.r = mpos[0]; e.a = mpos[1]; e.lv = v21; edgeN++;
      bool armStepped = (major == 1) || stepMinor; int armSg = major == 1 ? sgM : sgm;
      // chatter = a second change close to the last one while still moving the same way (a reversal is not chatter)
      bool fresh = abs(mpos[1] - lastEdgeA) > 200 || armSg != lastEdgeSg;
      lastEdgeA = mpos[1]; lastEdgeSg = armSg;
      if (armHomed && v21 && armStepped && fresh) {                         // rising edge, either direction: check for slip
        int32_t m = (((mpos[1] - (armSg > 0 ? EDGE_FWD : EDGE_BACK)) % ARM_TURN) + ARM_TURN) % ARM_TURN;
        int32_t e2 = m > ARM_TURN / 2 ? m - ARM_TURN : m;
        slipErr = e2; slipChecks++;
        if (abs(e2) > SLIP_TOL) { fault = 1; armHomed = false; radHomed = false; break; }
      }
    }
    if ((i & 255) == 255) vTaskDelay(0);
  }
  curV[0] = curV[1] = 0;
}
void pulseTask(void*) {
  for (;;) {
    if (moveRun) { runMove(); moveRun = false; pulseStop = false; continue; }
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
  float e = SGE[6];
  if (v <= SGV[0]) e = SGE[0] * v / SGV[0];
  else for (int k = 1; k < 7; k++) if (v <= SGV[k]) { e = SGE[k - 1] + (SGE[k] - SGE[k - 1]) * (v - SGV[k - 1]) / (SGV[k] - SGV[k - 1]); break; }
  if (m == 1) e *= 1.0f - 0.13f * constrain((carriageR(mpos[0], mpos[1]) - 12000) / 32000.0f, 0.0f, 1.4f);
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
      if ((float)v[m] < sgPct[m] * 0.01f * sgExpect(m, sp[m])) {
        if (++sgHits[m] >= sgNeed && !pulseStop) { fault = 2 + m; if (m) armHomed = false; else radHomed = false; pulseStop = true; }
      } else sgHits[m] = 0;
    }
    vTaskDelay(pdMS_TO_TICKS(8));
  }
}
void hSg() {
  String s = "{\"n\":" + String((uint32_t)sgN) + ",\"s\":["; uint32_t n = sgN;
  for (uint32_t k = 0; k < n; k++) { SgS& g = sgs[k]; if (k) s += ","; s += "[" + String(g.i) + "," + String(g.vr) + "," + String(g.va) + "," + String(g.sr) + "," + String(g.sa) + "]"; }
  reply(200, s + "]}");
}
void hGuard() {
  if (server.hasArg("pr")) sgPct[0] = constrain(argI("pr", 82), 0, 100);
  if (server.hasArg("pa")) sgPct[1] = constrain(argI("pa", 82), 0, 100);
  if (server.hasArg("n")) sgNeed = constrain(argI("n", 6), 2, 100);
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
  String s = "{\"fw\":\"big-bench 0.6\",\"up_s\":" + String(millis() / 1000) + ",\"ip\":\"" + WiFi.localIP().toString() +
             "\",\"rssi\":" + WiFi.RSSI() + ",\"led_pin\":" + ledPin + ",\"led_n\":" + ledN + ",\"driven\":" + pinsList(driven) +
             ",\"pulse\":{\"run\":" + (pulseRun ? 1 : 0) + ",\"step\":" + pStep + ",\"dir\":" + pDir + ",\"dv\":" + pDv +
             ",\"n\":" + pN + ",\"hz\":" + String(pHz, 0) + ",\"done\":" + String((int32_t)pulseDone) + ",\"until\":" + pUntil + ",\"hit_at\":" + String((int32_t)pHitAt) + "},\"move\":{\"run\":" + String(moveRun ? 1 : 0) + ",\"done\":" + String((int32_t)mvDone) + ",\"r\":" + String((int32_t)mpos[0]) +
       ",\"a\":" + String((int32_t)mpos[1]) + ",\"edges\":" + String((uint32_t)edgeN) + ",\"s21\":" + String(digitalRead(21)) + ",\"arm_homed\":" + String(armHomed ? 1 : 0) +
       ",\"rad_homed\":" + String(radHomed ? 1 : 0) + ",\"carriage\":" + String(carriageR(mpos[0], mpos[1])) + ",\"fault\":" + String(fault) +
       ",\"slip_err\":" + String((int32_t)slipErr) + ",\"slip_checks\":" + String((int32_t)slipChecks) +
       ",\"pr\":" + String((int)sgPct[0]) + ",\"pa\":" + String((int)sgPct[1]) + "},\"watch\":{";
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
  for (int p = 0; p < ledN; p++) { bool on = p >= i0 && p < i0 + k; LR[p] = on ? r : 0; LG[p] = on ? g : 0; LB[p] = on ? b : 0; }
  ledShow();
  reply(200, "led pin " + String(ledPin) + " n " + ledN + " lit " + i0 + ".." + (i0 + k - 1));
}
void hInputs() {
  int pins[49]; String bad; int n = parsePins(server.arg("pins"), pins, 49, bad);
  String pull = server.arg("pull");
  String s = "{";
  for (int i = 0; i < n; i++) {
    int p = pins[i];
    if ((driven >> p) & 1) { if (p == ledPin) { rmtDeinit(ledPin); ledPin = -1; } driven &= ~(1ULL << p); }
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
  if (p == ledPin) { rmtDeinit(ledPin); ledPin = -1; }
  drivePin(p, v); reply(200, "pin " + String(p) + " = " + v);
}
void hFloat() {
  int p = argI("n", -1);
  if (protectedPin(p)) { reply(400, "protected pin"); return; }
  if (pulseRun && (p == pStep || p == pDir)) { reply(409, "busy"); return; }
  if (p == ledPin) { rmtDeinit(ledPin); ledPin = -1; }
  floatPin(p); reply(200, "pin " + String(p) + " floating");
}
void hPulse() {
  if (pulseRun) { reply(409, "busy"); return; }
  int st = argI("step", -1), dr = argI("dir", -1);
  int32_t n = argI("n", 0); float hz = server.hasArg("hz") ? server.arg("hz").toFloat() : 200;
  if (protectedPin(st) || (dr >= 0 && protectedPin(dr)) || st == dr) { reply(400, "bad pins"); return; }
  if (n < 1 || n > 64000 || hz < 1 || hz > 6000) { reply(400, "n 1..64000, hz 1..6000"); return; }
  if (st == ledPin || dr == ledPin) { rmtDeinit(ledPin); ledPin = -1; }
  pStep = st; pDir = dr; pDv = argI("dv", 0); pN = n; pHz = hz; pulseDone = 0; pHitAt = -1;
  pUntil = argI("until", -1); pUntilLv = argI("lv", 1);
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
  mvN[0] = r; mvN[1] = a; mvHz = hz; mvAcc = acc; mvDone = 0;
  drivePin(MDIR[0], r < 0 ? 1 : 0); drivePin(MDIR[1], a < 0 ? 1 : 0); drivePin(MSTEP[0], 0); drivePin(MSTEP[1], 0);
  delayMicroseconds(50);
  pulseStop = false; moveRun = true;
  reply(200, "moving r " + String(r) + " a " + String(a) + " hz " + String(hz, 0) + " acc " + String(acc, 0));
}
void hZero() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (server.hasArg("r")) mpos[0] = argI("r", 0);
  if (server.hasArg("a")) mpos[1] = argI("a", 0);
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
    for (uint8_t a = 1; a <= 2; a++) { tmcWrite(a, 0x00, 0x1C0); tmcWrite(a, 0x6C, 0x13000054); tmcWrite(a, 0x10, 8 | (17 << 8) | (6UL << 16)); }
    xSemaphoreGive(tmcMux);
    drivePin(MSTEP[0], 0); drivePin(MSTEP[1], 0); drivePin(MDIR[0], 0); drivePin(MDIR[1], 0);   // step lines are outputs before any move
    drivePin(11, 0); drivePin(34, 0);
  } else { drivePin(11, 1); drivePin(34, 1); armHomed = radHomed = armRef = false; }
  reply(200, on ? "drivers on at factory current" : "drivers off (position forgotten)");
}
// arm home: forward sweep (radius held) up to 1.3 turns until the sensor rises; that point becomes a = 0
void hHomeArm() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (outLv[11] || outLv[34] || !((driven >> 11) & 1)) { reply(409, "drivers off: /enable first"); return; }
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
    mpos[1] = oldA + corr;                  // the carriage estimate r - a/6 picks up the arm steps that were lost
    radHomed = radWas && abs(corr) < ARM_TURN / 4;
  } else {
    mpos[1] = want;
    mpos[0] += (int32_t)floorf(want / 6.0f) - (int32_t)floorf(oldA / 6.0f);   // keep the carriage estimate unchanged
  }
  armHomed = armRef = true;
  reply(200, "{\"a\":" + String((int32_t)mpos[1]) + ",\"corrected\":" + String(corr) + ",\"rad_homed\":" + String(radHomed ? 1 : 0) + "}");
}
// /setcarriage?c=N: the carriage's distance from the arm's rotation centre, in steps, as measured by the camera.
void hSetCarriage() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (!server.hasArg("c")) { reply(400, "c= is required"); return; }
  int32_t c = argI("c", 0); if (c < 0 || c > 60000) { reply(400, "c 0..60000"); return; }
  mpos[0] = c + (int32_t)floorf(mpos[1] / 6.0f); radHomed = true;
  reply(200, "carriage " + String(carriageR(mpos[0], mpos[1])));
}
// radius home without a switch: creep inward with the stall alarm armed on the radius driver; when it trips (the carriage
// met the centre stop), back out 1,600 steps and call that carriage 1,600. Without a trip nothing is changed.
void hHomeRadius() {
  if (pulseRun || moveRun) { reply(409, "busy"); return; }
  if (outLv[11] || outLv[34] || !((driven >> 11) & 1)) { reply(409, "drivers off: /enable first"); return; }
  int pct = argI("pct", 0); int32_t maxn = argI("max", 0); float hz = server.hasArg("hz") ? server.arg("hz").toFloat() : 3000;
  if (pct <= 0 || pct > 100 || maxn < 1 || maxn > 62000 || hz < 3000 || hz > 8000) { reply(400, "pct 1..100, max 1..62000, hz 3000..8000 are required"); return; }
  if (fault) { reply(409, "fault " + String(fault)); return; }
  int oldPct = sgPct[0]; float oldV = sgVmin;
  sgPct[0] = pct; sgVmin = hz * 0.95f;
  mvN[0] = -maxn; mvN[1] = 0; drivePin(MDIR[0], 1); drivePin(MDIR[1], 0); mvHz = hz; mvAcc = 8000; pulseStop = false;
  moveRun = true; while (moveRun) delay(5);
  int32_t went = mvDone; bool hit = fault == 2;
  sgPct[0] = oldPct; sgVmin = oldV;
  if (!hit) { reply(200, "{\"hit\":0,\"went\":" + String(went) + "}"); return; }
  fault = 0;
  mvN[0] = 1600; drivePin(MDIR[0], 0); mvHz = 2000; mvAcc = 3000; pulseStop = false; moveRun = true; while (moveRun) delay(5);
  mpos[0] = 1600 + (int32_t)floorf(mpos[1] / 6.0f); radHomed = true;
  reply(200, "{\"hit\":1,\"went\":" + String(went) + ",\"carriage\":1600}");
}
void hStop() {
  pulseStop = true; uint32_t t = millis(); while ((pulseRun || moveRun) && millis() - t < 300) delay(1);
  if (ledPin >= 0) { rmtDeinit(ledPin); ledPin = -1; }
  for (int p = 0; p < 49; p++) if ((driven >> p) & 1) floatPin(p);
  reply(200, "stopped at pulse " + String((int32_t)pulseDone) + "; all pins floating");
}
bool keyOk() { return server.header("X-Key") == ADMIN_KEY || server.arg("key") == ADMIN_KEY; }
bool otaOk = false; String otaErr; uint32_t restartAt = 0;
void otaRaw() {
  HTTPRaw& r = server.raw();
  if (r.status == RAW_START) {
    otaOk = false; otaErr = "";
    if (!keyOk()) { otaErr = "bad key"; return; }
    if (pulseRun) { otaErr = "busy"; return; }
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
  Serial.begin(115200);
  Serial.println("\nbig-bench 0.6: no pins driven except the motor drivers' serial line (17/18)");
  tmcMux = xSemaphoreCreateMutex();
  tmc.begin(115200, SERIAL_8N1, 18, 17);
  pinMode(21, INPUT);                       // arm home sensor; reads 0 forever if never set up as an input (found 2026-11-22)
  drivePin(5, 1);                           // sensor supply as the factory drives it (models 2/3: GPIO5 high)
  WiFi.mode(WIFI_STA); WiFi.setHostname("oasis-big"); WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  Serial.print("ip "); Serial.println(WiFi.localIP());
  if (MDNS.begin("oasis-big")) MDNS.addService("http", "tcp", 80);
  static const char* hdrs[] = {"X-Key"};
  server.collectHeaders(hdrs, 1);
  server.on("/status", hStatus); server.on("/led", hLed); server.on("/inputs", hInputs); server.on("/watch", hWatch);
  server.on("/pin", hPin); server.on("/float", hFloat); server.on("/pulse", hPulse); server.on("/stop", hStop);
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
}
// The web server runs on core 0 so the pulse task can own core 1 without starving it.
void webTask(void*) {
  uint32_t lastPrint = 0, lastTry = 0;
  for (;;) {
    server.handleClient();
    if (restartAt && millis() > restartAt) ESP.restart();
    if (millis() - lastPrint > 10000) { lastPrint = millis(); Serial.print("ip "); Serial.println(WiFi.localIP()); }
    if (WiFi.status() != WL_CONNECTED && millis() - lastTry > 15000) { lastTry = millis(); WiFi.reconnect(); }
    vTaskDelay(1);
  }
}
void loop() { vTaskDelay(1000); }
