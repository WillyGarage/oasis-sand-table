#!/usr/bin/env python3
"""Draw an offline reference PNG for a guest's words on Bill's Oasis host.

    python3 tools/phrase_drawing.py "a hand-cranked coffee grinder" -o /mnt/c/Users/bill/Downloads/grinder.png

Start the shared room with --phrase-drawings to offer a preview on the requesting phone.
For an explicit number of rotary blades, spokes or petals, the host can repeat one
model-drawn unit about its hub and keep the handle or support stationary.
For a manual import in the large garden, open Middle ring → Draw from a guest photo, choose
“A pet, object or drawing” and select the PNG. On the Mini use Photo → Trace the whole
photo, select the guest place under Size in the sand, and preview. Either form
has a separate confirmation. Preview the result: the model can omit distinctive
features, and fine details can merge in sand.

Runs the installed Windows Qwen3.8-27B model once. No account or running model
server is needed. A cold generation commonly takes 1–3 minutes on this laptop.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

MODEL_DIR = Path(r"C:\Users\bill\local-models")
MODEL = MODEL_DIR / "models/qwen3.8-27b/Qwen3.8-27B-UD-IQ3_XXS.gguf"
ENGINE = MODEL_DIR / "llama.cpp/cuda13/llama-completion.exe"
WINDOWS_PYTHON = ((Path(r"C:\Users\bill") if os.name == "nt" else Path("/mnt/c/Users/bill"))
                  / "AppData/Local/WillyGarage/oasis/venv/Scripts/python.exe")
SYSTEM = """Draw an original, recognizable black-line illustration of the guest's subject for a sand table.
Plan the composition in the brief. For each defining part give its shape and bounding box as (left,top)-(right,bottom) in the 100 by 100 square.
Draw the subject upright in a side or three-quarter view that separates its defining parts. If it rests on a base or support, anchor that support across the bottom and put the working parts above it.
Use a few large strokes to establish a silhouette someone could guess with the caption hidden. Fit each part to its planned box. Where parts overlap, stop the hidden edge at the nearer outline.
Compose a single picture without lettering, labels, gray shading, a frame or scenery. Keep the main shapes large.
Use a 100 by 100 square, x increasing right, y increasing down. Use nonnegative integers from 4 to 96.
Leave at least 7 units between important details so wide sand grooves do not merge. Join details to an outline where that makes sense.
Return JSON strokes with a short part name and an SVG path. Use only absolute M, L, Q, C and Z commands. Each M starts a new pen stroke."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["brief", "strokes"], "properties": {
    "brief": {"type": "string", "maxLength": 350},
    "strokes": {"type": "array", "minItems": 1, "maxItems": 15, "items": {
        "type": "object", "additionalProperties": False, "required": ["part", "path"], "properties": {
            "part": {"type": "string", "pattern": "^[a-zA-Z ]+$"},
            "path": {"type": "string", "pattern": "^M[-0-9MLQCZ ,.]+$"}}}}}}


def parse_paths(response):
    """Read the single JSON completion, ignoring only llama.cpp's terminal marker."""
    data = json.loads(re.sub(r"\s*\[end of text\]\s*$", "", response).strip())
    if not isinstance(data, dict) or not isinstance(data.get("strokes"), list) or not 1 <= len(data["strokes"]) <= 15:
        raise ValueError("The model returned no usable drawing.")
    return [item["path"] for item in data["strokes"]]


def polylines(paths):
    import numpy as np

    lines = []
    arity = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}
    for path in paths:
        if not isinstance(path, str) or not re.fullmatch(r"M[-MLQCZ\d ,.]+", path):
            raise ValueError("The model returned an unsupported drawing command.")
        tokens = re.findall(r"[MLQCZ]|-?[\d.]+", path)
        if ''.join(tokens) != re.sub(r'[ ,]+', '', path):
            raise ValueError("The model returned an invalid coordinate.")
        i, line = 0, []
        while i < len(tokens):
            op = tokens[i]
            if op in arity:
                command = op
                i += 1
            elif command == "Z":
                raise ValueError("A new stroke needs a starting point.")
            n = arity[command]
            nums = [float(s) for s in tokens[i:i+n]]
            if len(nums) != n or not np.all(np.isfinite(nums)):
                raise ValueError("The model returned an invalid coordinate.")
            i += n
            points = list(np.asarray(nums, dtype=float).reshape(-1, 2))
            if command == "M":
                if len(line) > 1:
                    lines.append(line)
                line = points
                command = "L"  # Additional coordinates after M are straight segments.
            elif command == "Z":
                line.append(line[0])
            elif command == "L":
                line.extend(points)
            else:
                # Sample the quadratic or cubic curve without changing its controls.
                curve = np.array([line[-1], *points])
                for t in np.linspace(0, 1, 33)[1:]:
                    p = curve
                    while len(p) > 1:
                        p = (1-t)*p[:-1] + t*p[1:]
                    line.append(p[0])
        if len(line) > 1:
            lines.append(line)
    if not lines:
        raise ValueError("The model returned no lines.")
    return lines


def reference_png(paths):
    return render_lines(polylines(paths))


def render_lines(lines):
    import cv2
    import numpy as np

    points = np.concatenate(lines)
    lo, hi = points.min(axis=0), points.max(axis=0)
    with np.errstate(over='ignore'):
        extent = hi-lo
    if not np.all(np.isfinite(extent)):
        raise ValueError("The model returned an invalid coordinate range.")
    span = max(extent)
    if span < 4:
        raise ValueError("The model drew too little to preview.")
    # Fit the whole illustration, including a part that extends past the
    # requested 100-unit canvas. Clipping it would change the silhouette.
    center = lo + extent/2
    canvas = np.full((640, 640), 255, dtype=np.uint8)
    for line in lines:
        xy = (np.asarray(line) - center) * (548/span) + 320
        cv2.polylines(canvas, [np.rint(xy).astype(np.int32)], False, 0, 7, cv2.LINE_AA)
    ok, png = cv2.imencode(".png", canvas)
    if not ok:
        raise ValueError("Could not make the PNG.")
    return png.tobytes()


def available_layers():
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            result = subprocess.run([smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, check=True, timeout=5)
            # On this quantization 32 layers used about 6.2 GiB, including the context.
            return max(0, min(32, (int(result.stdout.splitlines()[0]) - 2900) // 200))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
    return 0


def radial_request(phrase):
    """Find an explicit number of blades, petals or spokes around one hub."""
    numbers = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
    count_word = r"\b(" + "|".join(numbers) + r"|[2-9]|1[0-2])"
    separator = r"[\s\u2010-\u2015-]+"
    adjective = r"(?:folded|curved|straight|thin|broad|wide|narrow|paper|wooden|metal|pointed|rounded)"
    repeated_unit = separator + "(?:" + adjective + separator + r"){0,2}(blades?|bladed|petals?|petall?ed|spokes?|spoked)\b"
    clauses = re.split(r"\b(?:beside|next to|alongside|behind|in front of)\b", phrase.lower())
    requests = [(clause, match) for clause in clauses for match in re.finditer(count_word + repeated_unit, clause)]
    if len(requests) != 1:
        return None
    clause, match = requests[0]
    number, part = match.groups()
    if part.startswith("blade"):
        family = r"pinwheels?|windmills?|propellers?|impellers?|fans?|rotors?|turbines?"
        unit = "blades"
    elif part.startswith("spok"):
        family = r"wheels?|rims?"
        unit = "spokes"
    else:
        family = r"dais(?:y|ies)|sunflowers?|flowers?|blooms?|blossoms?|dahlias?|lotuses?|lil(?:y|ies)"
        unit = "petals"
    if not re.search(r"\b(?:" + family + r")\b", clause):
        return None
    count = int(number) if number.isdigit() else numbers.index(number) + 2
    return count, unit


def radial_spec(count, part):
    # The host applies an exact rotation to every point of the unit, including
    # curve controls. The model draws the unique support and one repeated unit.
    strokes = SCHEMA["properties"]["strokes"]
    spec = {**SCHEMA,
            "required": ["brief", "hub", "unit", "strokes"],
            "properties": {
                "brief": SCHEMA["properties"]["brief"],
                "hub": {"type": "array", "minItems": 2, "maxItems": 2,
                        "items": {"type": "integer", "minimum": 4, "maximum": 96}},
                "unit": {**strokes, "maxItems": 3},
                "strokes": {**strokes, "minItems": 0}}}
    instruction = (f" The guest specifies {count} {part} around one hub. Draw that face straight on. "
                   f"Choose hub [x,y] and put exactly one repeated unit in its {360/count:.0f}-degree sector. "
                   "The host rotates exact copies about this hub. Preserve the physical shape of that part: "
                   "a broad blade that catches the wind sweeps to one side of its radius with a wide outer edge; "
                   "a spoke is a slender support. Leave at least one third of the sector open between neighboring tips. A broad blade has one long tip and a shorter return edge: outline its leading point and the corner trailing it at about half the radius. Where a sheet folds back onto itself, include one curved fold only if there is room. "
                   "Put its strokes in unit. Put stationary parts and the central fastening in strokes. "
                   "Where the head covers a stand or stick, start the visible support at a real edge of the head "
                   "and extend it far enough below to read. Avoid an enclosing circle unless it belongs to the object.")
    return SYSTEM + instruction, spec


def separate_blades(shape, hub, count):
    """Leave room between blades when a model tiles the full turn with adjoining sectors."""
    import numpy as np

    points = np.vstack(shape) - hub
    radius = np.linalg.norm(points, axis=1)
    extent = radius.max()
    if extent < 2:
        raise ValueError("The repeated blade is too small to draw.")
    edge = points[radius >= .35 * extent]
    angles = np.unique(np.arctan2(edge[:, 1], edge[:, 0]))
    if len(angles) < 2:
        return shape
    gaps = np.diff(np.r_[angles, angles[0] + 2*np.pi])
    largest = int(np.argmax(gaps))
    width = 2*np.pi - gaps[largest]
    sector = 2*np.pi / count
    if width <= .68*sector:
        return shape
    middle = angles[(largest+1) % len(angles)] + width/2
    fit = .68*sector / width
    # If two equally long radial edges tile a sector, their repeated outline
    # becomes a polygon. Retain the first outer tip and bring the opposite
    # corner inward to make the trailing edges visible in coarse sand.

    def offset(v):
        return (np.arctan2(v[:, 1], v[:, 0]) - middle + np.pi) % (2*np.pi) - np.pi

    outer = points[radius >= .85*extent]
    signed = offset(outer)
    taper = bool(width >= .86*sector and signed.min() < -.4*width and signed.max() > .4*width)
    leading = 1 if signed[0] > 0 else -1
    result = []
    for line in shape:
        rel = np.asarray(line) - hub
        before = offset(rel)
        angle = middle + before*fit
        reach = np.linalg.norm(rel, axis=1)
        if taper:
            reach *= 1-.38*np.clip(.5-leading*before/width, 0, 1)
        result.append(hub + np.column_stack((reach*np.cos(angle), reach*np.sin(angle))))
    return result


def radial_png(response, count, part="spokes"):
    import math
    import numpy as np
    data = json.loads(re.sub(r"\s*\[end of text\]\s*$", "", response).strip())
    try:
        hub = np.asarray(data["hub"], dtype=float)
        unit = data["unit"]
        fixed = data["strokes"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("The model returned no usable repeated part.") from exc
    if (hub.shape != (2,) or not np.isfinite(hub).all() or not np.all((hub >= 4) & (hub <= 96))
            or not isinstance(unit, list) or not 1 <= len(unit) <= 3
            or not isinstance(fixed, list) or len(fixed) > 15
            or not all(isinstance(p, dict) and "path" in p for p in [*fixed, *unit])):
        raise ValueError("The model returned an invalid hub or repeated part.")
    lines = polylines([p["path"] for p in fixed]) if fixed else []
    shape = polylines([p["path"] for p in unit])
    if part == "blades":
        shape = separate_blades(shape, hub, count)
    for i in range(count):
        a = 2 * math.pi * i / count
        rotation = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
        lines.extend((np.asarray(line) - hub) @ rotation + hub for line in shape)
    return render_lines(lines)


def generate(phrase, folder):
    if not ENGINE.is_file() or not MODEL.is_file():
        raise FileNotFoundError("The Windows Oasis host needs its installed Qwen3.8-27B weights and llama-completion.exe.")
    prompt = folder / "prompt.txt"
    schema = folder / "drawing.schema.json"
    radial = radial_request(phrase)
    system, schema_data = radial_spec(*radial) if radial else (SYSTEM, SCHEMA)
    prompt.write_text("<|im_start|>system\n" + system + "<|im_end|>\n<|im_start|>user\nDraw " + phrase
                      + "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n", encoding="utf-8")
    schema.write_text(json.dumps(schema_data), encoding="utf-8")
    args = [str(ENGINE), "-m", str(MODEL), "-ngl", str(available_layers()), "-t", "8", "-tb", "8",
            "-c", "3072", "-n", "1500", "-b", "128", "-ub", "64", "--offline", "--no-warmup",
            "--no-conversation", "--no-display-prompt", "--no-escape", "--simple-io", "--temp", "0.25",
            "--seed", "37", "-jf", str(schema), "-f", str(prompt)]
    with subprocess.Popen(args, cwd=ENGINE.parent, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS) as child:
        try:
            out, err = child.communicate(timeout=300)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    if child.returncode:
        reason = err.decode(errors="replace").strip().splitlines()
        raise RuntimeError("The local model failed. " + (reason[-1] if reason else "Check the model installation."))
    response = out.decode("utf-8-sig")
    return radial_png(response, *radial) if radial else reference_png(parse_paths(response))


def windows_path(path):
    if os.name == "nt":
        return str(path)
    return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()


def installed_renderer():
    """Check this host once and return a callable that runs the offline CLI for each request."""
    setup_error = "Phrase drawings need the Oasis Windows Python, its image tools, and the installed local model."
    if not WINDOWS_PYTHON.is_file() or (os.name != "nt" and not shutil.which("wslpath")):
        raise ValueError(setup_error)
    script = Path(__file__).resolve()
    try:
        files = (ENGINE, MODEL)
        if os.name != "nt":
            files = [Path(subprocess.check_output(["wslpath", "-u", str(path)], text=True).strip()) for path in files]
        if not script.is_file() or not all(path.is_file() for path in files):
            raise ValueError(setup_error)
        entry = windows_path(script)
        subprocess.run([str(WINDOWS_PYTHON), "-c", "import cv2, numpy"], check=True, timeout=30,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(setup_error) from exc

    def render(phrase):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "drawing.png"
            subprocess.run([str(WINDOWS_PYTHON), entry, "-o", windows_path(output), "--", phrase],
                           check=True, timeout=345, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return output.read_bytes()

    return render


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phrase", help="the subject to draw, optionally with a few distinctive features")
    parser.add_argument("-o", "--output", required=True, type=Path, help="destination PNG")
    args = parser.parse_args()
    phrase = args.phrase.strip()
    if not phrase or len(phrase) > 600 or any(ord(c) < 32 for c in phrase) or "<|" in phrase:
        parser.error("Use 1–600 characters of ordinary text on one line.")
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".png" or not output.parent.is_dir():
        parser.error("Choose a .png filename in an existing folder.")
    if os.name != "nt":
        if not WINDOWS_PYTHON.is_file() or not shutil.which("wslpath"):
            parser.error("Run on the Oasis Windows host or its WSL installation.")
        os.execv(str(WINDOWS_PYTHON), [str(WINDOWS_PYTHON), windows_path(Path(__file__).resolve()),
                                     "-o", windows_path(output), "--", phrase])
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as temp:
            png = generate(phrase, Path(temp))
        # An interrupted or unsuccessful generation must leave an existing PNG intact.
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as store:
            tmp = Path(store.name)
        try:
            tmp.write_bytes(png)
            os.replace(tmp, output)
        finally:
            tmp.unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        parser.exit(1, "The model exceeded five minutes. Try a simpler description.\n")
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(f"Saved {output} ({time.monotonic()-started:.0f} seconds).")


if __name__ == "__main__":
    main()
