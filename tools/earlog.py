"""Black-box sound recorder for the table. Runs under the WINDOWS venv python until killed (tools/ear.sh start).
Writes into C:\\Users\\bill\\AppData\\Local\\WillyGarage\\oasis\\ear\\ :
  levels.jsonl   one line per second: {"t": unix, "db": median 20 ms level, "motor": 150 Hz-4 kHz band level, "peak": dB}
  events.jsonl   one line per sudden loud sound: {"t": unix, "peak": dBFS, "rise": dB over the last second, "wav": file}
  ev_<t>.wav     1.5 s around each event (amplified 8x)
Uses the raw WDM-KS microphone array; the normal Windows paths return silence on this laptop."""
import json, os, sys, time, wave, collections
import numpy as np, sounddevice as sd

OUT = r"C:\Users\bill\AppData\Local\WillyGarage\oasis\ear"
os.makedirs(OUT, exist_ok=True)
want = sys.argv[1] if len(sys.argv) > 1 else "Microphone Array 1"
dev = None
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0 and want.lower() in d["name"].lower() and sd.query_hostapis(d["hostapi"])["name"] == "Windows WDM-KS":
        dev = i; break
info = sd.query_devices(dev); sr = int(info["default_samplerate"]); ch = min(info["max_input_channels"], 4)
N = int(sr * 0.02)
buf = collections.deque(maxlen=int(sr * 4))          # last 4 s of mono samples
hist = collections.deque(maxlen=50)                    # last second of frame levels
sec = []; pend = []; last_ev = 0.0; carry = np.zeros(0)
lev = open(os.path.join(OUT, "levels.jsonl"), "a"); evf = open(os.path.join(OUT, "events.jsonl"), "a")

def save(t_ev):
    x = np.array(buf, dtype=np.float64); n = len(x)
    age = time.time() - t_ev                              # event is `age` seconds before the end of the buffer
    a = max(0, n - int((age + 0.5) * sr)); b = min(n, n - int((age - 1.0) * sr))
    fn = "ev_%d.wav" % int(t_ev * 10)
    w = wave.open(os.path.join(OUT, fn), "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(x[a:b] * 8, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
    return fn

def cb(indata, frames, tinfo, status):
    global carry, last_ev, sec
    x = indata.astype(np.float64).mean(axis=1) / 32768.0
    buf.extend(x)
    x = np.concatenate([carry, x]); k = len(x) // N; carry = x[k * N:]
    now = time.time()
    for f in x[:k * N].reshape(-1, N):
        f = f - f.mean()
        db = 20 * np.log10(np.sqrt((f ** 2).mean()) + 1e-9); pk = 20 * np.log10(np.abs(f).max() + 1e-9)
        base = np.median(hist) if len(hist) >= 10 else db
        if pk > -28 and db - base >= 15 and now - last_ev > 0.3:      # -35 caught ordinary daytime room sounds; the real snap was -18
            last_ev = now; pend.append((now, round(float(pk), 1), round(float(db - base), 1)))
        hist.append(db); sec.append((db, pk, f))
    if len(sec) >= 50:
        fr = np.concatenate([s[2] for s in sec]); X = np.abs(np.fft.rfft(fr * np.hanning(len(fr)))) ** 2
        fq = np.fft.rfftfreq(len(fr), 1 / sr); band = (fq > 150) & (fq < 4000)
        lev.write(json.dumps(dict(t=round(now, 2), db=round(float(np.median([s[0] for s in sec])), 1),
                                  motor=round(float(10 * np.log10(X[band].sum() / len(fr) ** 2 * 4 + 1e-18)), 1),
                                  peak=round(float(max(s[1] for s in sec)), 1))) + "\n"); lev.flush()
        sec = []

with sd.InputStream(device=dev, samplerate=sr, channels=ch, dtype="int16", callback=cb, blocksize=N * 5):
    print("earlog running", dev, sr, ch, flush=True)
    while True:
        time.sleep(0.25)
        while pend and time.time() - pend[0][0] > 1.1:
            t_ev, pk, rise = pend.pop(0)
            evf.write(json.dumps(dict(t=round(t_ev, 2), peak=pk, rise=rise, wav=save(t_ev))) + "\n"); evf.flush()
