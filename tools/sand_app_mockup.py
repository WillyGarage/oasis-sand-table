#!/usr/bin/env python3
"""Build the clickable phone mockup of the guest web app (sand.example.com).

Output: captures/sand-app/oasis-sand-app.html (self-contained).
Inlines whatever is in captures/sand-app/assets/ and draws a labelled placeholder
for anything missing. Mockup only: never talks to either table.

Rebuild + deploy:
  python3 tools/sand_app_mockup.py --deploy
"""
import base64, io, json, subprocess, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "captures/sand-app"
ASSETS = APP / "assets"
OUT = APP / "oasis-sand-app.html"

NAMES = {}
for p in ["bill", "lek", "alex", "thomas"]:
    NAMES[f"preview-{p}"] = (400, p.capitalize())
for k in ["reading", "star-wars", "clarinet-playing"]:
    for i in (1, 2, 3):
        NAMES[f"icon-{k}-{i}"] = (240, k.replace("-", " ") + f" ({i})")
for k in ["thai-temples", "hot-pot", "guitar", "teaching", "bacteriophages", "hiking"]:
    NAMES[f"icon-{k}"] = (240, k.replace("-", " "))
for i in range(1, 6):
    NAMES[f"table-turn-{i}"] = (720, f"whole table after turn {i}")
for k in ["leaves", "wheat", "lotus", "waves"]:
    NAMES[f"border-{k}"] = (240, f"{k} border")


def placeholder(label, size):
    words, lines, cur = label.split(), [], ""
    for w in words:
        if len(cur) + len(w) > 14 and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    fs = size * 0.075
    y0 = size / 2 - (len(lines) - 1) * fs * 0.6
    t = "".join(f'<text x="{size/2}" y="{y0 + i*fs*1.2}" text-anchor="middle" font-family="Georgia,serif" '
                f'font-size="{fs}" fill="#6b5a2e">{l}</text>' for i, l in enumerate(lines))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
           f'<circle cx="{size/2}" cy="{size/2}" r="{size/2-4}" fill="#e8dcb8" stroke="#c9b98a" stroke-width="4" stroke-dasharray="10 8"/>{t}</svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def img_uri(path, size):
    im = Image.open(path)
    im.thumbnail((size, size))
    buf = io.BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        im.convert("RGBA").save(buf, "PNG", optimize=True); mime = "png"
    else:
        im.convert("RGB").save(buf, "JPEG", quality=84); mime = "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def load_assets():
    out, missing = {}, []
    for name, (size, label) in NAMES.items():
        f = ASSETS / f"{name}.png"
        if f.exists():
            try:
                out[name] = img_uri(f, size); continue
            except Exception as e:
                print("bad asset", f, e)
        missing.append(name)
        out[name] = placeholder(label, size)
    return out, missing


def load_times():
    f = ASSETS / "times.json"
    if not f.exists():
        return None
    try:
        d = json.load(open(f))
        if isinstance(d, dict):
            for k in ("turns", "minutes", "per_turn", "turn_minutes"):
                if k in d:
                    d = d[k]; break
        if isinstance(d, dict):
            d = [d[k] for k in sorted(d)]
        vals = []
        for x in d:
            if isinstance(x, dict):
                x = x.get("total_minutes") or x.get("minutes") or x.get("min") or x.get("total") or next((v for v in x.values() if isinstance(v, (int, float))), None)
            vals.append(float(x))
        return vals or None
    except Exception as e:
        print("times.json unreadable:", e)
        return None


def photo_uri():
    return img_uri(APP / "src/bill-lek-700.jpg", 700)


def build():
    assets, missing = load_assets()
    times = load_times()
    html = TEMPLATE
    html = html.replace("/*ASSETS*/{}", "const A=" + json.dumps(assets) + ";")
    html = html.replace("/*PHOTO*/''", json.dumps(photo_uri()))
    html = html.replace("/*TIMES*/null", json.dumps(times))
    OUT.write_text(html)
    print("wrote", OUT, f"{OUT.stat().st_size/1e6:.2f} MB")
    print("placeholders:", ", ".join(missing) or "none")
    print("times.json:", "used" if times else "absent (21 min per turn, +20 min ring clear)")


def deploy():
    subprocess.run(["scp", str(OUT), "previewhost:~/mockups/oasis-sand-app.html"], check=True)
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "HTTP %{http_code}\n", "--resolve",
                        "preview.example.com:443:127.0.0.1", "https://preview.example.com/oasis-sand-app.html"],
                       capture_output=True, text=True)
    print(r.stdout.strip(), "https://preview.example.com/oasis-sand-app.html")


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sand table guest app (mockup)</title>
<style>
:root{color-scheme:light;--bg:#f5f2e9;--ink:#242c24;--green:#334c3c;--line:#d6d4c7;--cream:#fffdf7;--sand:#ece3c8;--gold:#c9a227;--dim:#6b7468}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.4 "DM Sans",system-ui,sans-serif}
button,input,textarea{font:inherit;color:inherit}
.top{max-width:760px;margin:auto;padding:14px 12px 4px;text-align:center}
.top h1{font:normal 1.35rem/1.2 Georgia,serif;margin:0 0 4px}
.top p{margin:0 0 8px;color:var(--dim);font-size:.85rem}
.tabs,.states{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:6px 0}
.tabs button{border:1px solid var(--line);background:#fff;border-radius:18px;padding:5px 11px;cursor:pointer;font-size:.85rem}
.tabs button.on{background:var(--green);color:#fff;border-color:var(--green)}
.states button{border:1px dashed #b9b59f;background:transparent;border-radius:14px;padding:3px 10px;cursor:pointer;font-size:.78rem;color:#4a554a}
.states button.on{background:#fff7d6;border-color:var(--gold)}
.states:empty{display:none}
.phone{width:390px;max-width:100%;margin:10px auto 30px;background:#2e3a31;border-radius:40px;padding:10px;box-shadow:0 10px 30px #0003}
.screen-wrap{position:relative;background:var(--bg);border-radius:30px;height:780px;overflow:hidden;display:flex;flex-direction:column}
.notch{height:22px;flex:none;display:flex;justify-content:center;align-items:center;font-size:.7rem;color:var(--dim);background:var(--cream);border-bottom:1px solid var(--line)}
.url{background:#fff;border:1px solid var(--line);border-radius:10px;padding:0 10px;font-size:.7rem;line-height:16px}
.body{flex:1;overflow-y:auto;padding:14px 14px 20px}
.nav{flex:none;display:flex;gap:8px;padding:8px 12px;border-top:1px solid var(--line);background:var(--cream)}
.nav button{flex:1;padding:9px;border-radius:10px;border:1px solid var(--line);background:#fff;cursor:pointer}
.nav .nx{background:var(--green);color:#fff;border-color:var(--green)}
.nav button:disabled{opacity:.35;cursor:default}
.sc{display:none}.sc.on{display:block}
h2{font:normal 1.6rem/1.15 Georgia,serif;margin:2px 0 4px;letter-spacing:-.01em}
h3{font:normal 1.1rem/1.2 Georgia,serif;margin:14px 0 6px}
.sub{color:#4a554a;margin:0 0 12px;font-size:.95rem}
.btn{display:block;width:100%;background:var(--green);color:#fff;border:0;border-radius:14px;padding:15px;font-size:1.1rem;font-weight:600;cursor:pointer;margin:10px 0}
.btn.sec{background:#fff;color:var(--green);border:2px solid var(--green)}
.btn:disabled{opacity:.4}
.link{background:none;border:0;color:var(--green);text-decoration:underline;cursor:pointer;padding:6px 2px;font-size:.95rem}
input[type=text],textarea{width:100%;border:1.5px solid #bdb9a6;border-radius:12px;padding:12px;background:#fff;font-size:1rem}
input:focus,textarea:focus{outline:2px solid var(--gold);border-color:var(--gold)}
.person{display:flex;align-items:center;gap:12px;width:100%;text-align:left;background:#fff;border:1px solid var(--line);border-radius:14px;padding:8px 12px;margin:0 0 8px;cursor:pointer;font-size:1.1rem}
.person:active{background:var(--sand)}
.th{flex:none;width:48px;height:48px;border-radius:50%;background:var(--sand);overflow:hidden;display:flex;align-items:center;justify-content:center;font-weight:700;color:#6b5a2e;border:1px solid #cdbf93}
.th img{width:100%;height:100%;object-fit:cover;transform:scale(1.75) translateY(4%)}
.th.sm{width:34px;height:34px;font-size:.8rem}
.notice{border-radius:12px;padding:10px 12px;margin:10px 0;font-size:.95rem}
.warn{background:#fff7d6;border:1.5px solid var(--gold)}
.ok{background:#e9f1e6;border:1.5px solid #9db79a}
.photo{position:relative;border-radius:12px;overflow:hidden;border:1px solid var(--line)}
.photo img{display:block;width:100%}
.fb{position:absolute;border:3px solid #fff;box-shadow:0 0 0 2px #0006;border-radius:8px;cursor:pointer;background:#fff1}
.fb b{position:absolute;left:-3px;top:-3px;background:#334c3c;color:#fff;border-radius:8px 0 8px 0;min-width:24px;height:24px;text-align:center;font:700 .85rem/24px system-ui}
.fb.sel{border-color:#e0a800;background:#e0a80033}
.fb.sel b{background:#e0a800;color:#242c24}
.fb.sm b{min-width:18px;height:18px;line-height:18px;font-size:.7rem}
.spin{width:34px;height:34px;border:4px solid var(--sand);border-top-color:var(--green);border-radius:50%;animation:sp 1s linear infinite;margin:18px auto 8px}
@keyframes sp{to{transform:rotate(360deg)}}
.center{text-align:center}
.round{width:min(100%,300px);aspect-ratio:1;border-radius:50%;display:block;margin:8px auto;box-shadow:0 2px 10px #0003;background:var(--sand)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{border:1px solid var(--line);background:#fff;border-radius:16px;padding:5px 11px;cursor:pointer;font-size:.9rem}
.opts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.opt{background:#fff;border:2px solid var(--line);border-radius:14px;padding:6px;cursor:pointer}
.opt img{width:100%;border-radius:50%;display:block;background:var(--sand);aspect-ratio:1}
.opt.sel{border-color:var(--green);background:#e9f1e6}
.opt div{text-align:center;font-size:.8rem;margin-top:3px}
.mine{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:6px 10px;margin:6px 0}
.mine img{width:40px;height:40px;border-radius:50%;background:var(--sand)}
.mine span{flex:1}
.shared{font-size:.82rem;color:var(--green);margin:1px 0 2px}.sh{display:block;font-size:.7rem;color:var(--green)}
.wd{background:none;border:0;text-align:left;padding:2px 0;cursor:pointer;font-size:1rem;display:block}.wd small{color:var(--dim);font-size:.72rem;margin-left:4px}
.ev{margin:0 0 8px}.ev .row{margin:0;cursor:pointer}.ev .ints{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}.ev .ints span{display:flex;align-items:center;gap:4px;background:var(--cream);border:1px solid var(--line);border-radius:14px;padding:2px 8px 2px 2px;font-size:.82rem}.ev .ints img{width:30px;height:30px;border-radius:50%;background:var(--sand)}
.ev .when{background:#fff7d6;border:1px solid var(--gold);border-radius:0 0 10px 10px;padding:5px 10px;font-size:.88rem;margin-top:-4px}
.sw{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}
.sw button{width:44px;height:44px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 1.5px #b9b59f;cursor:pointer}
.sw button.on{box-shadow:0 0 0 3px var(--green)}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px;margin:10px 0}
.sumrow{display:flex;gap:12px;align-items:center}
.sumrow .th{width:72px;height:72px}
.big{font:normal 1.9rem/1.1 Georgia,serif}
.prog{height:14px;background:var(--sand);border-radius:7px;overflow:hidden;margin:8px 0}
.prog i{display:block;height:100%;background:var(--green);width:64%}
.steps{list-style:none;margin:6px 0 0;padding:0;font-size:.95rem}
.steps li{padding:2px 0;color:var(--dim)}
.steps li.d{color:var(--green)}.steps li.d:before{content:"\2713  "}
.steps li.n{color:var(--ink);font-weight:700}.steps li.n:before{content:"\25B6  "}
.row{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:8px 10px;margin:0 0 8px}
.row.you{border:2px solid var(--gold);background:#fffbe8}
.row .nm{flex:1;min-width:0}
.row .nm b{display:block}
.row small{color:var(--dim);display:block;font-size:.8rem}
.row .tm{font-weight:700;font-size:.9rem;white-space:nowrap}
.mini{display:flex;gap:3px;margin-top:3px}
.mini img{width:22px;height:22px;border-radius:50%;background:var(--sand)}
.tag{display:inline-block;background:var(--gold);color:#242c24;border-radius:8px;padding:0 6px;font-size:.72rem;font-weight:700;margin-left:4px}
.clear{border:1.5px dashed #b9a86b;background:#fff7d6;border-radius:12px;padding:8px 10px;margin:0 0 8px;font-size:.88rem}
.sim{background:#fff7d6;border:1.5px solid var(--gold);border-radius:10px;padding:8px 10px;font-size:.85rem;margin:8px 0}
.tbl{width:100%;border-radius:12px;display:block;border:1px solid var(--line)}
.hrow{display:flex;align-items:center;gap:6px}
.hrow .nm{flex:1;min-width:0}
.ib{border:1px solid var(--line);background:#fff;border-radius:8px;width:34px;height:34px;cursor:pointer;font-size:1rem}
.ib.rm{color:#9a3b2f}
.themes{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.themes.two{grid-template-columns:repeat(2,1fr)}.coll{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;margin-bottom:3px}.coll img{border-radius:50%;width:100%;background:var(--sand)}.themes small{display:block;color:var(--dim);font-size:.68rem}
.themes button{border:2px solid var(--line);background:#fff;border-radius:12px;padding:4px;cursor:pointer;font-size:.72rem}
.themes button.on{border-color:var(--green);background:#e9f1e6}
.themes img{width:100%;border-radius:50%;display:block;background:var(--sand)}
.tog{display:flex;align-items:center;gap:10px;justify-content:space-between}
.sw2{width:50px;height:28px;border-radius:14px;background:#bdb9a6;border:0;position:relative;cursor:pointer;flex:none}
.sw2:after{content:"";position:absolute;left:3px;top:3px;width:22px;height:22px;border-radius:50%;background:#fff;transition:.15s}
.sw2.on{background:var(--green)}.sw2.on:after{left:25px}
.pad{position:absolute;inset:22px 0 0 0;background:var(--bg);z-index:5;padding:14px;display:none;flex-direction:column}
.pad.on{display:flex}
.pad canvas{background:#efe5c6;border-radius:50%;width:100%;aspect-ratio:1;touch-action:none;border:2px solid #cdbf93;cursor:crosshair}
.pgrid{display:flex;gap:8px;margin-top:10px}.pgrid .btn{margin:0;padding:12px;font-size:1rem}
.hostlink{text-align:center;margin-top:18px;font-size:.8rem}.hostlink button{color:var(--dim);font-size:.8rem}
.paused{background:#fde7e2;border:1.5px solid #d9847a;border-radius:12px;padding:8px 10px;margin:8px 0}
@media(max-width:430px){.phone{border-radius:0;padding:0;box-shadow:none;margin-top:4px}.screen-wrap{border-radius:0}}
</style></head><body>
<div class="top">
<h1>Sand table guest app <span style="font-size:.7em;color:#6b7468">sand.example.com</span></h1>
<p>Clickable mockup. Pictures are computer simulations, nothing here is connected to the table.</p>
<div class="tabs" id="tabs"></div><div class="states" id="states"></div>
</div>
<div class="phone"><div class="screen-wrap">
<div class="notch"><span class="url">sand.example.com</span></div>
<div class="body" id="body">

<!-- 1 WHO -->
<div class="sc" id="s1">
 <div id="returning" class="notice ok" style="display:none">
  <b style="font-size:1.15rem">Welcome back, Bill.</b><br>
  <button class="btn" style="margin:8px 0 2px" onclick="go(2)">That's me, keep going</button>
  <button class="link" onclick="setS1('list')">Not you? Switch</button></div>
 <div id="who-main">
  <h2>Who are you?</h2><p class="sub">Tap your name to join the party.</p>
  <input type="text" id="search" placeholder="Search names" oninput="renderPeople()">
  <div id="plist" style="margin-top:10px"></div>
  <button class="btn sec" onclick="setS1('new')">I'm not on the list</button>
 </div>
 <div id="who-new" style="display:none">
  <h2>What's your first name?</h2><p class="sub">We'll add you to the list.</p>
  <input type="text" id="newname" placeholder="First name" oninput="checkName()">
  <div id="taken" class="notice warn" style="display:none"></div>
  <button class="btn" id="newgo" onclick="newDone()">Continue</button>
  <button class="link" onclick="setS1('list')">Back to the list</button>
 </div>
 <div class="hostlink"><button class="link" onclick="go(8)">Host</button></div>
</div>

<!-- 2 PHOTO -->
<div class="sc" id="s2">
 <h2>Your photo</h2>
 <div id="p-up">
  <p class="sub">Any photo with your face works. Group photos are fine, we'll find everyone.</p>
  <div class="card center" style="border:2px dashed #b9b59f;padding:30px 12px">
   <div style="font-size:2.4rem">&#128247;</div>
   <button class="btn" onclick="setP('look')">Choose a photo</button>
   <div class="dim" style="color:var(--dim);font-size:.85rem">From your camera or your photos</div></div>
 </div>
 <div id="p-look" style="display:none" class="center"><div class="spin"></div><p>Finding faces...</p></div>
 <div id="p-faces" style="display:none">
  <p class="sub">We found 3 faces. Tap the one that's you. Pick two to be drawn side by side.</p>
  <div class="photo" id="photo"></div>
  <p id="pickline" style="margin:8px 0 0;font-weight:600"></p>
  <button class="btn" id="seesand" onclick="setP('sand')">Show me in sand</button>
  <button class="link" onclick="setP('up')">Use a different photo</button>
 </div>
 <div id="p-sand" style="display:none">
  <h3 style="margin-top:2px">Here's how you'll look in sand</h3>
  <div id="sandprev"></div>
  <div class="sim">A preview. The real sand will look a little softer.</div>
  <button class="btn" onclick="go(3)">Looks good</button>
  <button class="link" onclick="setP('faces')">Pick a different face</button>
 </div>
</div>

<!-- 3 INTERESTS -->
<div class="sc" id="s3">
 <h2>What do you like?</h2><p class="sub">Add as many as you like. Each one gets its own drawing on the table.</p>
 <div id="minelist"></div>
 <div id="i-input">
  <input type="text" id="itext" placeholder="Try: reading, star wars, clarinet playing" onkeydown="if(event.key==='Enter')addInterest()">
  <button class="btn" onclick="addInterest()">Add</button>
 </div>
 <div id="i-done" style="display:none"><button class="btn" onclick="go(4)">Next: pick a light color</button></div>
</div>

<!-- 4 COLOR -->
<div class="sc" id="s4">
 <h2>Your light color</h2><p class="sub">Optional. The table's light ring glows this color during your turn.</p>
 <div class="sw" id="sw"></div>
 <button class="link" onclick="pickColor(-1)">Skip, any color is fine</button>
 <h3>Here's you</h3>
 <div class="card" id="summary"></div>
 <button class="btn" onclick="addMe()">Add me to the table</button>
</div>

<!-- 5 IN LINE -->
<div class="sc" id="s5">
 <div class="center">
  <div class="th" style="width:90px;height:90px;margin:10px auto" id="inline-th"></div>
  <h2 id="inline-h">You're on the table</h2>
  <p class="big" style="font-size:1.1rem;line-height:1.35" id="inline-t"></p>
  <p class="sub">You don't have to wait here. Come back to this page any time to see how close you are.</p>
 </div>
 <button class="btn" onclick="go(6)">See the table</button>
 <button class="btn sec" style="margin-top:0" onclick="go(9)">See everyone at the party</button>
</div>

<!-- 6 TABLE -->
<div class="sc" id="s6">
 <h2>On the table</h2><p class="sub">Everyone is featured in turn, then it starts over. Anyone can watch. No sign-in.</p>
 <div id="pausedbar"></div>
 <div class="card" id="nowcard"></div>
 <h3>Coming up</h3>
 <div id="uplist"></div>
 <p class="sub" style="font-size:.82rem">People without a photo are featured by name and interests.</p>
 <button class="btn sec" onclick="go(9)">See everyone at the party</button>
 <div class="hostlink"><button class="link" onclick="go(8)">Host</button></div>
</div>

<!-- 9 EVERYONE -->
<div class="sc" id="s9">
 <h2>Everyone</h2><p class="sub">Everybody at the party and what they like. Tap a person to see when their turn is. No sign-in.</p>
 <div id="evlist"></div>
</div>

<!-- 7 KEEPSAKE -->
<div class="sc" id="s7">
 <h2 id="keep-h">Your keepsake</h2><p class="sub">The whole table right after your turn.</p>
 <img class="tbl" data-a="table-turn-2" alt="Preview of the table after your turn">
 <div class="sim"><b>A preview of the table, not a photo.</b> It's a computer picture of how the sand should look.</div>
 <a id="saveA" class="btn" style="text-align:center;text-decoration:none" download="my-sand-table.png">Save picture</a>
 <button class="btn sec" onclick="go(6)" style="margin-top:0">Back to the table</button>
</div>

<!-- 8 HOST -->
<div class="sc" id="s8">
 <h2>Host</h2><p class="sub">Only for whoever runs the party. No password.</p>
 <div class="card">
  <b id="pausetxt">Table is running</b>
  <button class="btn sec" id="pausesw" onclick="togglePause()" style="margin:8px 0 4px">Pause the table</button>
  <div style="color:var(--dim);font-size:.85rem">Pause holds the table where it is. Resume picks up again.</div></div>
 <h3>The rotation</h3>
 <div id="hline"></div>
 <button class="btn sec" onclick="skipNow()">Skip the current drawing</button>
 <h3>Outer ring shows:</h3>
 <div id="ringpick"></div>
 <h3>Add names</h3>
 <textarea id="addnames" rows="3" placeholder="One name per line, like Maria&#10;Sam&#10;Grandpa Joe"></textarea>
 <button class="btn sec" onclick="addNames()">Add to the list</button>
 <div id="addmsg"></div>
 <div class="hostlink"><button class="link" onclick="resetDemo()">Reset the demo</button></div>
</div>

<div class="pad" id="pad">
 <h3 style="margin-top:0">Draw it yourself</h3>
 <canvas id="cv" width="600" height="600"></canvas>
 <div class="pgrid"><button class="btn sec" onclick="clearPad()">Start over</button><button class="btn" onclick="donePad()">Use my drawing</button></div>
 <button class="link" onclick="closePad()">Cancel</button>
</div>
</div>
<div class="nav"><button id="back" onclick="step(-1)">Back</button><button class="nx" id="next" onclick="step(1)">Next</button></div>
</div></div>

<script>
/*ASSETS*/{}
const PHOTO=/*PHOTO*/'';
const TIMES=/*TIMES*/null;
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function imgTag(src,cls){return '<img src="'+src+'" '+(cls?'class="'+cls+'" ':'')+'alt="">'}
function thumb(p,cls){return '<div class="th '+(cls||'')+'">'+(p.face?imgTag(A[p.face]):esc(p.name.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase()))+'</div>'}
function phSvg(label,v){const t=esc(label);const rings=['<circle cx="100" cy="100" r="70" fill="none" stroke="#b9a86b" stroke-width="3"/>','<path d="M30 100 Q65 60 100 100 T170 100" fill="none" stroke="#b9a86b" stroke-width="3"/>','<path d="M100 30 L170 100 L100 170 L30 100 Z" fill="none" stroke="#b9a86b" stroke-width="3"/>'][v%3];
 return 'data:image/svg+xml;utf8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle cx="100" cy="100" r="96" fill="#e8dcb8"/>'+rings+'<text x="100" y="106" text-anchor="middle" font-family="Georgia,serif" font-size="17" fill="#6b5a2e">'+t+'</text></svg>')}

/* ---------- data ---------- */
let people=[{name:'Alex',face:'preview-alex'},{name:'Bill',face:'preview-bill'},{name:'Grandpa Joe'},{name:'Lek',face:'preview-lek'},{name:'Maria'},{name:'Sam'},{name:'Thomas',face:'preview-thomas'}];
const ICON={read:'icon-reading-1',star:'icon-star-wars-1',clarinet:'icon-clarinet-playing-2'};
function iconFor(label){const l=label.toLowerCase();for(const k in ICON)if(l.includes(k))return A[ICON[k]];return phSvg(label,0)}
const GUEST={lek:{face:'preview-lek',ints:[['Thai temples','icon-thai-temples'],['hot pot','icon-hot-pot']]},
 alex:{face:'preview-alex',ints:[['guitar','icon-guitar'],['teaching','icon-teaching']]},
 thomas:{face:'preview-thomas',ints:[['bacteriophages','icon-bacteriophages'],['hiking','icon-hiking']]},
 maria:{ints:[['reading'],['gardening'],['star wars']]},
 sam:{ints:[['star wars'],['board games']]}};
let me={name:'Bill',face:'preview-bill'};
let mine=[];let color=2;let ring='interests';let paused=false;
const COLORS=[['Sunset','#e8743b'],['Gold','#e0b030'],['Leaf green','#5a9a5a'],['Sky','#4a90c8'],['Violet','#8a62b8'],['Rose','#d86a8a'],['Warm white','#f3e7c9'],['Teal','#2a9a98']];
let rot=['lek','bill','alex','thomas','maria','sam'];
let nowStart=19*60+2;let nowStep='Drawing the face';
const T=TIMES?TIMES.slice(0,4).reduce((a,b)=>a+b)/4:21;
function fmt(m){m=Math.round(m);let h=Math.floor(m/60)%24,mm=m%60,ap=h>=12?'pm':'am';h=h%12||12;return h+':'+(mm<10?'0':'')+mm+' '+ap}
function who(id){
 if(id==='bill'){const m=mine.length?mine:defaultMine();return {id,name:me.name,face:me.face,ints:m.map(x=>x.src),labels:m.map(x=>x.label)}}
 const g=GUEST[id];return {id,name:id[0].toUpperCase()+id.slice(1),face:g.face,ints:g.ints.map(i=>i[1]?A[i[1]]:iconFor(i[0])),labels:g.ints.map(i=>i[0])}}
function defaultMine(){return ['reading','star wars','clarinet playing'].map(l=>({label:l,src:iconFor(l)}))}
const STOP=new Set(['movie','movies','film','films','the','playing','play','a','and']);
function key(l){return l.toLowerCase().replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w=>w&&!STOP.has(w)).map(w=>w.replace(/s$/,'')).join(' ')}
function same(a,b){const x=key(a),y=key(b);if(!x||!y)return false;if(x===y)return true;const X=x.split(' '),Y=y.split(' ');const[sm,lg]=X.length<=Y.length?[X,Y]:[Y,X];return sm.every(w=>lg.includes(w))}
function sharers(label,selfId){return ['lek','bill','alex','thomas','maria','sam'].filter(id=>id!==selfId).filter(id=>who(id).labels.some(l=>same(l,label))).map(id=>who(id).name).sort()}
function join(n){return n.length<2?n.join(''):n.slice(0,-1).join(', ')+' and '+n[n.length-1]}
function sharedLine(label,selfId){const n=sharers(label,selfId);return n.length?join(n)+(n.length===1?' likes':' like')+' this too':''}
function schedule(){let t=nowStart+T,out=[];
 for(let k=1;k<=rot.length;k++){out.push({id:rot[k%rot.length],start:t,wrap:k===rot.length});t+=T}return out}

/* ---------- navigation ---------- */
const TABS=['Who','Photo','Interests','Color','Added','Table','Keepsake','Host','Everyone'];
let from9=6;
let cur=1;
const STATES={1:[['list','List'],['new','Not on list'],['taken','Name taken'],['back','Welcome back']],
 2:[['up','Upload'],['look','Finding faces'],['faces','Faces found'],['sand','Sand preview']],
 3:[['empty','Empty'],['making','Making'],['list','One added'],['edit','Editing'],['pad','Draw myself'],['many','Five added']],
 6:[['run','Running'],['pause','Paused']]};
function buildTabs(){$('tabs').innerHTML=TABS.map((t,i)=>'<button data-i="'+(i+1)+'" onclick="go('+(i+1)+')">'+(i+1)+' '+t+'</button>').join('')}
function go(n){if(n===9&&cur!==9)from9=cur;cur=n;if(n>=4)ensureDemo();document.querySelectorAll('.sc').forEach(e=>e.classList.toggle('on',e.id==='s'+n));
 document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',+b.dataset.i===n));
 $('states').innerHTML=(STATES[n]||[]).map(s=>'<button onclick="setState('+n+',\''+s[0]+'\')">'+s[1]+'</button>').join('');
 $('back').disabled=n===1;$('next').disabled=n===8||n===9;$('next').textContent=n===4?'Add me':'Next';
 $('body').scrollTop=0;closePad();
 if(n===1)renderPeople();if(n===2)renderPhoto();if(n===3)renderMine();if(n===4)renderColor();if(n===5)renderInline();if(n===6)renderTable();if(n===7)renderKeep();if(n===8)renderHost();if(n===9)renderEveryone()}
function step(d){if(cur===9&&d<0)return go(from9);if(cur===4&&d>0)return addMe();go(cur+d)}
function setState(n,s){if(n===1){setS1(s==='back'?'back':s==='taken'?'taken':s)}
 if(n===2)setP(s);if(n===3)setI(s);if(n===6){paused=s==='pause';renderTable()}}
function ensureDemo(){if(!mine.length)mine=defaultMine()}

/* ---------- 1 who ---------- */
function setS1(s){go(1);$('returning').style.display=s==='back'?'block':'none';
 $('who-main').style.display=(s==='list'||s==='back')?'block':'none';
 $('who-new').style.display=(s==='new'||s==='taken')?'block':'none';
 if(s==='back'){$('who-main').style.display='none';}
 if(s==='new'){$('newname').value='';checkName()}
 if(s==='taken'){$('newname').value='Alex';checkName()}
 if(s==='list'){me={name:'Bill',face:'preview-bill'}}}
function renderPeople(){const q=$('search').value.trim().toLowerCase();
 $('plist').innerHTML=people.filter(p=>p.name.toLowerCase().includes(q)).map((p,i)=>'<button class="person" onclick="pickPerson('+people.indexOf(p)+')">'+thumb(p)+'<span>'+esc(p.name)+'</span></button>').join('')||'<p class="sub">No one by that name yet. Tap "I’m not on the list".</p>'}
function pickPerson(i){const p=people[i];me={name:p.name,face:p.face};setS1(p.name==='Bill'?'back':'list');if(p.name!=='Bill'){go(2)}}
function checkName(){const v=$('newname').value.trim();const t=$('taken');
 const hit=people.find(p=>p.name.toLowerCase()===v.toLowerCase());
 if(hit){t.style.display='block';t.innerHTML='There’s already '+(/^[aeiou]/i.test(v)?'an ':'a ')+'<b>'+esc(hit.name)+'</b> here. Add a last initial or nickname, like <b>'+esc(hit.name)+' H.</b>'}
 else t.style.display='none';
 $('newgo').disabled=!v||!!hit}
function newDone(){const v=$('newname').value.trim();if(!v)return;people.push({name:v});people.sort((a,b)=>a.name.localeCompare(b.name));me={name:v};go(2)}

/* ---------- 2 photo ---------- */
const BOX=[[58,118,172,205],[352,8,262,300],[222,276,32,46]];let sel=[0];let pstage='up';
function renderPhoto(){const W=700,H=525;
 $('photo').innerHTML='<img src="'+PHOTO+'" alt="Photo with three faces found">'+BOX.map((b,i)=>'<div class="fb'+(sel.includes(i)?' sel':'')+(i===2?' sm':'')+'" style="left:'+b[0]/W*100+'%;top:'+b[1]/H*100+'%;width:'+b[2]/W*100+'%;height:'+b[3]/H*100+'%" onclick="togFace('+i+')"><b>'+(i+1)+'</b></div>').join('');
 const n=sel.length;$('pickline').textContent=n?(n===1?'You picked face '+(sel[0]+1)+'.':'You picked faces '+sel.map(x=>x+1).join(' and ')+'. You’ll be drawn side by side.'):'Tap a face to pick it.';
 $('seesand').disabled=!n;
 $('sandprev').innerHTML=n>1?'<div style="display:flex;gap:6px"><img class="round" style="margin:0" src="'+A['preview-bill']+'"><img class="round" style="margin:0" src="'+A['preview-lek']+'"></div>':'<img class="round" src="'+A['preview-bill']+'" alt="Sand preview">';
 setP(pstage,true)}
function togFace(i){sel=sel.includes(i)?sel.filter(x=>x!==i):sel.concat(i).slice(-2);if(sel.length>2)sel=sel.slice(-2);renderPhoto()}
function setP(s,quiet){if(!quiet&&cur!==2)go(2);pstage=s==='look'?'look':s;
 ['up','look','faces','sand'].forEach(k=>$('p-'+k).style.display=k===s?'block':'none');
 if(s==='look'&&!quiet){setTimeout(()=>{if(pstage==='look')setP('faces')},1100)}}

/* ---------- 3 interests ---------- */
let ist='empty',busyNew=null,editing=-1,padIdx=-1,tmr=null;
function renderMine(){let h=mine.map((m,i)=>{
  if(m.busy)return '<div class="mine"><div class="spin" style="margin:0;width:30px;height:30px"></div><span>Making a drawing...</span></div>';
  if(editing===i)return '<div class="mine" style="flex-wrap:wrap"><img src="'+m.src+'"><input type="text" id="edit" value="'+esc(m.label)+'" style="flex:1;min-width:0;padding:8px"><div style="width:100%;display:flex;gap:8px;margin-top:6px"><button class="btn" style="margin:0;padding:9px;font-size:.95rem" onclick="saveEdit('+i+')">Redraw</button><button class="btn sec" style="margin:0;padding:9px;font-size:.95rem" onclick="editing=-1;renderMine()">Cancel</button></div></div>';
  return '<div class="mine">'+imgTag(m.src)+'<div style="flex:1;min-width:0"><button class="wd" onclick="editRow('+i+')">'+esc(m.label)+' <small>tap to change</small></button>'+(sharedLine(m.label,'bill')?'<div class="shared">'+esc(sharedLine(m.label,'bill'))+'</div>':'')+'<button class="link" style="font-size:.78rem;padding:0;color:var(--dim)" onclick="openPad('+i+')">Draw it myself instead</button></div><button class="link" onclick="rmRow('+i+')">Remove</button></div>'}).join('');
 if(busyNew)h+='<div class="mine"><div class="spin" style="margin:0;width:30px;height:30px"></div><span>Making a drawing...</span></div>';
 $('minelist').innerHTML=h;$('i-input').style.display=busyNew?'none':'block';
 $('i-done').style.display=mine.length&&!busyNew?'block':'none'}
function setI(s){go(3);clearTimeout(tmr);busyNew=null;editing=-1;mine.forEach(m=>m.busy=false);
 if(s==='empty')mine=[];
 if(s==='making'){mine=[];busyNew='reading'}
 if(s==='list'){mine=defaultMine().slice(0,1)}
 if(s==='many')mine=defaultMine().concat(['board games','gardening'].map(l=>({label:l,src:iconFor(l)})));
 if(s==='edit'){mine=defaultMine().slice(0,2);editing=1}
 if(s==='pad'){mine=defaultMine().slice(0,2);renderMine();openPad(1);return}
 renderMine()}
function addInterest(){const v=$('itext').value.trim();if(!v){$('itext').focus();return}
 busyNew=v;$('itext').value='';renderMine();tmr=setTimeout(()=>{if(busyNew===v){mine.push({label:v,src:iconFor(v)});busyNew=null;renderMine()}},1200)}
function editRow(i){editing=i;renderMine();const e=$('edit');e.focus();e.select()}
function saveEdit(i){const v=$('edit').value.trim();editing=-1;if(!v){renderMine();return}
 if(v===mine[i].label){renderMine();return}mine[i].busy=true;renderMine();
 setTimeout(()=>{mine[i].label=v;mine[i].src=iconFor(v);mine[i].busy=false;renderMine()},1200)}
function rmRow(i){mine.splice(i,1);editing=-1;renderMine()}
const cv=$('cv'),cx=cv.getContext('2d');let drawing=false;
function pos(e){const r=cv.getBoundingClientRect();return[(e.clientX-r.left)*cv.width/r.width,(e.clientY-r.top)*cv.height/r.height]}
cv.addEventListener('pointerdown',e=>{drawing=true;cv.setPointerCapture(e.pointerId);const[x,y]=pos(e);cx.beginPath();cx.moveTo(x,y);cx.lineTo(x+.1,y);cx.stroke()});
cv.addEventListener('pointermove',e=>{if(!drawing)return;const[x,y]=pos(e);cx.lineTo(x,y);cx.stroke()});
['pointerup','pointercancel'].forEach(t=>cv.addEventListener(t,()=>drawing=false));
function clearPad(){cx.clearRect(0,0,600,600);cx.fillStyle='#efe5c6';cx.fillRect(0,0,600,600);cx.strokeStyle='#4a3f22';cx.lineWidth=9;cx.lineCap=cx.lineJoin='round'}
function openPad(i){padIdx=i;clearPad();$('pad').classList.add('on')}
function closePad(){$('pad').classList.remove('on')}
function donePad(){const t=document.createElement('canvas');t.width=t.height=240;const c=t.getContext('2d');c.beginPath();c.arc(120,120,120,0,7);c.clip();c.drawImage(cv,0,0,240,240);
 if(mine[padIdx])mine[padIdx].src=t.toDataURL();closePad();renderMine()}

/* ---------- 4 color + summary ---------- */
function renderColor(){$('sw').innerHTML=COLORS.map((c,i)=>'<button title="'+c[0]+'" class="'+(i===color?'on':'')+'" style="background:'+c[1]+'" onclick="pickColor('+i+')"></button>').join('');
 const m=mine.length?mine:defaultMine();
 $('summary').innerHTML='<div class="sumrow">'+thumb(me)+'<div><b style="font-size:1.2rem">'+esc(me.name)+'</b><div style="color:var(--dim);font-size:.88rem">Face, name and '+m.length+' interests</div></div></div>'+
  '<div class="mini" style="gap:6px;margin-top:8px;flex-wrap:wrap">'+m.map(x=>'<img style="width:44px;height:44px" src="'+x.src+'" title="'+esc(x.label)+'">').join('')+'</div><div style="margin-top:6px;font-size:.9rem">'+m.map(x=>esc(x.label)).join(', ')+'</div>'+
  '<div style="margin-top:8px;font-size:.9rem;display:flex;align-items:center;gap:8px">Light: <i style="width:18px;height:18px;border-radius:50%;display:inline-block;background:'+(color>=0?COLORS[color][1]:'#ddd')+'"></i>'+(color>=0?COLORS[color][0]:'Any')+'</div>'}
function pickColor(i){color=i;renderColor()}
function addMe(){go(5)}

/* ---------- 5 on the table ---------- */
function renderInline(){const r=schedule().find(x=>x.id==='bill');$('inline-th').innerHTML=me.face?imgTag(A[me.face]):esc(me.name[0]);
 $('inline-t').textContent='Your face is featured next at about '+fmt(r.start)+'. Once everyone has had a turn, it comes around again.'}

/* ---------- 6 table ---------- */
function bigFace(n){return n.face?'<img src="'+A[n.face]+'" style="width:110px;height:110px;border-radius:50%;background:var(--sand);box-shadow:0 1px 6px #0003">':'<div class="th" style="width:110px;height:110px;font-size:2rem">'+esc(n.name[0])+'</div>'}
function renderTable(){const s=schedule(),n=who(rot[0]);
 $('pausedbar').innerHTML=paused?'<div class="paused"><b>The table is taking a short break.</b> It will pick up again soon.</div>':'';
 $('nowcard').innerHTML='<div style="font-size:.8rem;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Now featuring</div>'+
  '<div class="sumrow" style="margin-top:6px">'+bigFace(n)+'<div><div class="big">'+esc(n.name)+'</div><div style="color:var(--dim);font-size:.9rem">Started '+fmt(nowStart)+'</div></div></div>'+
  '<div class="prog"><i></i></div><div style="display:flex;justify-content:space-between"><b>'+esc('Drawing '+n.name+'\u2019s face')+'</b><span>64% done</span></div>'+
  '<ul class="steps"><li class="d">Clearing the middle</li><li class="n">Drawing '+esc(n.name)+'’s face</li><li>Adding '+esc(n.name)+'’s interests</li></ul>';
 $('uplist').innerHTML=s.map((r,k)=>{const p=who(r.id),you=r.id==='bill';
  return (k===3?'<div class="clear">The outer ring redraws with new pictures, about <b>'+fmt(r.start)+'</b></div>':'')+
  '<div class="row'+(you?' you':'')+'"><b style="width:18px;color:var(--dim)">'+(k+1)+'</b>'+thumb(p)+'<div class="nm"><b>'+esc(p.name)+(you?'<span class="tag">you</span>':'')+'</b>'+(r.wrap?'<small>Comes around again</small>':'')+'<div class="mini">'+p.ints.map(x=>'<img src="'+x+'">').join('')+'</div></div><div class="tm">'+fmt(r.start)+'</div></div>'}).join('')}

/* ---------- 9 everyone ---------- */
let openEv=null;
function renderEveryone(){const sch=schedule();
 let h=['lek','bill','alex','thomas','maria','sam'].map(id=>{const p=who(id),you=id==='bill';
  const r=sch.find(x=>x.id===id&&!x.wrap);
  let when=id===rot[0]?'Featuring now, since '+fmt(nowStart):'Featured next at about '+fmt(r.start);
  if(!p.face)when+='. No photo yet, so featured by name and interests.';
  return '<div class="ev"><div class="row'+(you?' you':'')+'" onclick="openEv=openEv===\''+id+'\'?null:\''+id+'\';renderEveryone()">'+thumb(p)+'<div class="nm"><b>'+esc(p.name)+(you?'<span class="tag">you</span>':'')+'</b><div class="ints">'+p.ints.map((x,k)=>{const sh=sharers(p.labels[k],id);return '<span><img src="'+x+'"><div>'+esc(p.labels[k])+(sh.length?'<small class="sh">shared with '+esc(join(sh))+'</small>':'')+'</div></span>'}).join('')+'</div></div></div>'+(openEv===id?'<div class="when">'+when+'</div>':'')+'</div>'}).join('');
 h+='<div class="ev"><div class="row">'+thumb({name:'Grandpa Joe'})+'<div class="nm"><b>Grandpa Joe</b><small>Hasn’t added a photo or interests yet</small></div></div></div>';
 $('evlist').innerHTML=h}

/* ---------- 7 keepsake ---------- */
function renderKeep(){$('keep-h').textContent=me.name+'’s keepsake';$('saveA').href=A['table-turn-2']}

/* ---------- 8 host ---------- */
function renderHost(){const rest=rot.slice(1),sch=schedule();
 $('hline').innerHTML='<div class="row" style="background:#f3f0e3"><b style="width:18px">1</b>'+thumb(who(rot[0]),'sm')+'<div class="nm"><b>'+esc(who(rot[0]).name)+'</b><small>Featuring now, 64%</small></div></div>'+
 rest.map((id,i)=>{const p=who(id);return '<div class="row hrow'+(id==='bill'?' you':'')+'"><b style="width:18px">'+(i+2)+'</b>'+thumb(p,'sm')+'<div class="nm"><b>'+esc(p.name)+'</b><small>'+fmt(sch[i].start)+'</small></div>'+
 '<button class="ib" title="Move up" '+(i===0?'disabled':'')+' onclick="mv('+i+',-1)">&#9650;</button><button class="ib" title="Move down" '+(i===rest.length-1?'disabled':'')+' onclick="mv('+i+',1)">&#9660;</button><button class="ib rm" title="Remove" onclick="rmq('+i+')">&#10005;</button></div>'}).join('')+
 '<p class="sub" style="font-size:.82rem">After the last person it goes back to the first, over and over.</p>';
 const sel=(k,inner,label,sub)=>'<button class="'+(ring===k?'on':'')+'" onclick="ring=\''+k+'\';renderHost()">'+inner+'<div>'+label+'</div>'+(sub?'<small>'+sub+'</small>':'')+'</button>';
 const col=a=>'<div class="coll">'+a.map(x=>'<img src="'+x+'">').join('')+'</div>';
 $('ringpick').innerHTML='<div class="themes two">'+sel('interests',col([A['icon-reading-1'],A['icon-star-wars-1'],A['icon-guitar'],A['icon-hiking']]),'Interests','Default')+sel('faces',col([A['preview-lek'],A['preview-bill'],A['preview-alex'],A['preview-thomas']]),'Faces','')+'</div>'+
  '<div style="font-size:.85rem;color:var(--dim);margin:8px 0 4px">Or a decoration:</div><div class="themes">'+[['leaves','Autumn leaves'],['wheat','Wheat'],['lotus','Lotus'],['waves','Waves']].map(t=>sel(t[0],'<img src="'+A['border-'+t[0]]+'">',t[1],'')).join('')+'</div>';
 $('pausesw').textContent=paused?'Resume the table':'Pause the table';$('pausetxt').textContent=paused?'Table is paused':'Table is running'}
function mv(i,d){const a=i+1,b=a+d;if(b<1||b>=rot.length)return;[rot[a],rot[b]]=[rot[b],rot[a]];renderHost()}
function rmq(i){rot.splice(i+1,1);renderHost()}
function togglePause(){paused=!paused;renderHost()}
function skipNow(){if(rot.length<2)return;rot.push(rot.shift());nowStart+=T;nowStep='Clearing the middle';renderHost()}
function addNames(){const v=$('addnames').value.split(/\n|,/).map(s=>s.trim()).filter(Boolean);let n=0;
 v.forEach(x=>{if(!people.find(p=>p.name.toLowerCase()===x.toLowerCase())){people.push({name:x});n++}});people.sort((a,b)=>a.name.localeCompare(b.name));
 $('addmsg').innerHTML='<div class="notice ok">Added '+n+' name'+(n===1?'':'s')+' to the list.</div>';$('addnames').value=''}
function resetDemo(){rot=['lek','bill','alex','thomas','maria','sam'];nowStart=19*60+2;nowStep='Drawing the face';paused=false;renderHost()}

document.querySelectorAll('[data-a]').forEach(e=>e.src=A[e.dataset.a]);
buildTabs();clearPad();go(+(location.hash.slice(1))||1);
</script></body></html>
'''

if __name__ == "__main__":
    build()
    if "--deploy" in sys.argv:
        deploy()
