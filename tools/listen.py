"""Ears for the table: record the laptop microphone and report loudness and sudden bangs.
Runs under the WINDOWS venv python (needs sounddevice). Use tools/listen.sh from WSL.

  listen.py SECONDS [out.wav] [device]

Prints one JSON line: start (unix time), secs, level_db (median 20 ms RMS, dBFS), p95_db, peak_db,
and bangs = [[seconds_from_start, peak_db, rise_db], ...] for 20 ms frames that jump at least 15 dB above
the running median of the previous second. A stepper buzz is steady, so it raises level_db, not bangs."""
import sys, json, time, wave
import numpy as np, sounddevice as sd

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 5
out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "none" else None
want = sys.argv[3] if len(sys.argv) > 3 else "Microphone Array 1"
# Only the raw WDM-KS devices give real sound here: the normal Windows paths (MME, WASAPI) return digital silence.
dev = None
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0 and want.lower() in d["name"].lower() and sd.query_hostapis(d["hostapi"])["name"] == "Windows WDM-KS":
        dev = i; break
info = sd.query_devices(dev)
sr = int(info["default_samplerate"]); ch = min(info["max_input_channels"], 4)
t0 = time.time()
x = sd.rec(int(secs * sr), samplerate=sr, channels=ch, dtype="int16", device=dev)
time.sleep(secs + 0.3); sd.stop()
x = x.astype(np.float64).mean(axis=1) / 32768.0
x = x - x.mean()
if out:
    w = wave.open(out, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(x * 8, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
# motor band (150 Hz - 4 kHz) level, to compare how loud different drive settings are
X = np.fft.rfft(x * np.hanning(len(x))); f = np.fft.rfftfreq(len(x), 1 / sr)
band = (f > 150) & (f < 4000)
motor_db = 10 * np.log10((np.abs(X[band]) ** 2).sum() / len(x) ** 2 * 4 + 1e-18)
n = int(sr * 0.02)
fr = x[: len(x) // n * n].reshape(-1, n)
rms = np.sqrt((fr ** 2).mean(axis=1)) + 1e-9
pk = np.abs(fr).max(axis=1) + 1e-9
db = 20 * np.log10(rms); pdb = 20 * np.log10(pk)
bangs = []
for i in range(len(db)):
    lo = max(0, i - 50)
    base = np.median(db[lo:i]) if i - lo >= 10 else np.median(db[: max(10, i + 1)])
    if db[i] - base >= 15 and pdb[i] > -45 and (not bangs or i * 0.02 - bangs[-1][0] > 0.15):
        bangs.append([round(i * 0.02, 2), round(float(pdb[i]), 1), round(float(db[i] - base), 1)])
print(json.dumps(dict(start=round(t0, 2), secs=secs, device=dev, level_db=round(float(np.median(db)), 1), motor_db=round(float(motor_db), 1),
                      p95_db=round(float(np.percentile(db, 95)), 1), peak_db=round(float(pdb.max()), 1), bangs=bangs)))
