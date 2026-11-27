#!/usr/bin/env python3
"""Build the page Bill reads in the morning: one self-contained HTML file with the night's drawings.

  morning_page.py            build captures/morning/oasis-overnight.html from captures/morning/page.json and copy it
                             to the preview host (preview.example.com/oasis-overnight.html). Prints the HTTP status.
  morning_page.py --local    build only.

page.json: {"updated": "...", "summary": [..lines..], "needs_you": [..steps..],
            "pieces": [{"title":, "caption":, "image": path relative to the repo, "minutes": n}, ...],
            "sequence": {"title": ..., "frames": [{"label": ..., "image": ..., "caption": ...}]},
            "changes": [..lines..]}
Light mode, no external files (images are embedded), written for a phone."""
import base64, html, json, os, subprocess, sys
from pathlib import Path
import cv2
D = "/home/bill/dev/WillyGarage/oasis"
SRC = D + "/captures/morning/page.json"
OUT = D + "/captures/morning/oasis-overnight.html"
SLUG = "oasis-overnight"
for i, a in enumerate(sys.argv):      # --src other.json --slug other-page : build a different page the same way
    if a == "--src": SRC = sys.argv[i + 1]
    if a == "--slug": SLUG = sys.argv[i + 1]; OUT = D + "/captures/morning/%s.html" % SLUG

def img_uri(path, width=820, q=84):
    im = cv2.imread(D + "/" + path)
    if im is None: return None
    h, w = im.shape[:2]
    if w > width: im = cv2.resize(im, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()

def main():
    j = json.load(open(SRC)); e = html.escape
    parts = ["""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>
:root{color-scheme:light}
body{font:17px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d1d1f;background:#f6f4ef;margin:0}
main{max-width:860px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:26px;margin:8px 0 2px} h2{font-size:20px;margin:34px 0 8px}
.sub{color:#6b6b70;font-size:14px;margin-bottom:14px}
.card{background:#fff;border-radius:14px;padding:16px 18px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}
ul,ol{margin:6px 0;padding-left:22px} li{margin:5px 0}
figure{margin:18px 0;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
figure img{display:block;width:100%;height:auto;background:#000}
figcaption{padding:12px 16px 14px} figcaption b{display:block;font-size:18px}
figcaption span{color:#6b6b70;font-size:14px}
.need{border-left:5px solid #c9772b}
</style></head><body><main>"""]
    parts[0] = parts[0].replace("__TITLE__", e(j.get("title", "Oasis overnight")))
    parts.append("<h1>%s</h1><div class=sub>%s</div>" % (e(j.get("title", "Oasis overnight")), e(j.get("updated", ""))))
    if j.get("summary"):
        parts.append("<div class=card><ul>%s</ul></div>" % "".join("<li>%s</li>" % e(x) for x in j["summary"]))
    if j.get("needs_you"):
        parts.append("<h2>Needs you</h2><div class='card need'><ol>%s</ol></div>" % "".join("<li>%s</li>" % e(x) for x in j["needs_you"]))
    if j.get("sequence"):
        sequence = j["sequence"]
        buttons, figures = [], []
        for index, frame in enumerate(sequence["frames"]):
            uri = img_uri(frame["image"])
            if not uri: raise FileNotFoundError(frame["image"])
            selected = "true" if index == 0 else "false"
            buttons.append(f'<button type="button" aria-pressed="{selected}">{e(frame["label"])}</button>')
            hidden = "" if index == 0 else " hidden"
            figures.append(f'<figure{hidden}><img alt="{e(frame["alt"])}" src="{uri}"><figcaption>{e(frame["caption"])}</figcaption></figure>')
        clip = ""
        if sequence.get("video"):
            video = base64.b64encode(Path(D, sequence["video"]).read_bytes()).decode()
            clip = ('<details><summary>Watch the drawings take shape</summary>'
                    f'<video controls playsinline preload="none" aria-label="Time-lapse of the Mini drawing in sand" '
                    f'src="data:video/mp4;base64,{video}"></video></details>')
        parts.append(f'<section id="sequence"><h2>{e(sequence["title"])}</h2>'
                     f'<div class="choices" role="group" aria-label="Choose a drawing">{"".join(buttons)}</div>'
                     f'<div aria-live="polite">{"".join(figures)}</div>{clip}</section>')
        parts.append("""<style>
#sequence .choices{display:flex;gap:6px;flex-wrap:wrap}
#sequence button{padding:9px 14px;border-radius:100px;border:1px solid #b9c1b4;background:white;color:#284831;font:inherit;cursor:pointer}
#sequence button[aria-pressed=true]{background:#284831;border-color:#284831;color:white}
#sequence figure{margin-top:10px}#sequence figure img{aspect-ratio:1;object-fit:contain}
#sequence summary{cursor:pointer;color:#284831}#sequence video{width:100%;margin-top:8px}
</style><script>
const sequence=document.getElementById('sequence');
const buttons=Array.from(sequence.querySelectorAll('button'));
const frames=Array.from(sequence.querySelectorAll('figure'));
buttons.forEach((button,index)=>button.addEventListener('click',()=>{
  buttons.forEach((item,i)=>item.setAttribute('aria-pressed',String(i===index)));
  frames.forEach((frame,i)=>{frame.hidden=i!==index;});
}));
</script>""")
    if j.get("pieces"):
        parts.append("<h2>%s</h2>" % e(j.get("pieces_title", "What it drew")))
        for p in j["pieces"]:
            uri = img_uri(p["image"])
            if not uri: continue
            mins = " &middot; %s min" % p["minutes"] if p.get("minutes") else ""
            parts.append("<figure><img alt='%s' src='%s'><figcaption><b>%s</b><span>%s%s</span></figcaption></figure>"
                         % (e(p["title"]), uri, e(p["title"]), e(p.get("caption", "")), mins))
    if j.get("changes"):
        parts.append("<h2>What changed overnight</h2><div class=card><ul>%s</ul></div>" % "".join("<li>%s</li>" % e(x) for x in j["changes"]))
    parts.append("</main></body></html>")
    open(OUT, "w").write("\n".join(parts))
    print("built", OUT, os.path.getsize(OUT) // 1024, "KB")
    if "--local" in sys.argv: return
    subprocess.run(["scp", "-q", "-o", "ConnectTimeout=10", OUT, "previewhost:~/mockups/%s.html" % SLUG], check=True)
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "HTTP %{http_code}", "--resolve", "preview.example.com:443:127.0.0.1",
                        "https://preview.example.com/%s.html" % SLUG], capture_output=True, text=True)
    print(r.stdout)

main()
