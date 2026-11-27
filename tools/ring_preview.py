#!/usr/bin/env python3
"""Build a self-contained comparison from ring_scene.py's actual ball paths."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re

import numpy as np
import cv2

from sandsim import MOCK, Sand
from thrcommon import motion_files_hash, read_thr


def picture(sand):
    canvas = sand.image(contrast=1.15)
    # Crop the simulator's square frame. The page provides the lip of the bowl.
    middle = sand.size / 2
    edges = (round(middle - sand.R), round(middle + sand.R))
    canvas = canvas.crop((edges[0], edges[0], edges[1], edges[1]))
    stream = io.BytesIO()
    canvas.save(stream, "WEBP", quality=90)
    return "data:image/webp;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def scene_data(manifest, size):
    scene = json.loads(manifest.read_text())
    sand = Sand(size, groove=scene["groove_width"])
    if "prepared_erase_pitch" in scene:
        sand.erase(pitch=scene["prepared_erase_pitch"])

    def draw_files(filenames):
        for filename in filenames:
            sand.draw(read_thr(manifest.parent / filename))

    draw_files(scene["setup"])
    initial = sand.h.copy()
    result = {"zones": {}}
    result["layout"] = scene.get("layout", "garden")
    if "guest_plan" in scene or result["layout"] == "portrait":
        # Reuse the physical model's actual height field, so new cuts can cross
        # older grooves and leave displaced sand from previous suggestions.
        diameter = round(2 * sand.R)
        axis = np.linspace(-sand.R, sand.R, diameter, dtype=np.float32) + sand.pad + size / 2
        x, y = np.meshgrid(axis, axis)
        bed = cv2.remap(initial, x, y, cv2.INTER_LINEAR)
        quantized = np.rint((np.clip(bed, -1, .5) + 1) * 170).astype(np.uint8)
        # Earlier guest gardens keyed saved drawings on the full manifest before
        # the optional portrait erase was added. Those beds still fit this layout.
        old_zones = {name: {key: value for key, value in zone.items() if key != "photoErase"}
                     for name, zone in scene["zones"].items()}
        for zone in old_zones.values():
            zone["variants"] = [{key: value for key, value in variant.items() if key != "reveal"}
                                for variant in zone["variants"]]
        # Later border designs do not change the starting bed or the two
        # choices stored in a garden from that original gallery.
        old_zones["outer"]["variants"] = old_zones["outer"]["variants"][:2]
        old_scene = dict(scene, zones=old_zones)
        if "guest_plan" in scene:
            # This browser key was used only by the original 19-subject gallery.
            original_ids = set("phage books temple guitar_books guitar pumpkin classroom clapper clapper_alt "
                               "turkey elephant thailand hotpot rocket aztec dna hunt trex raptor".split())
            def original_subjects(items):
                return {key:value for key, value in items.items() if key in original_ids}
            catalog = scene["guest_plan"]
            old_scene["guest_plan"] = dict(catalog, subjects=original_subjects(catalog["subjects"]),
                                          excursions=[original_subjects(row) for row in catalog["excursions"]])
            for field in ("places", "openSubject", "styles", "preferredSubjects", "fillTours", "librarySubjects"):
                old_scene["guest_plan"].pop(field, None)
            if catalog.get("preferredSubjects") and catalog["defaults"] == [catalog["openSubject"]] * 3:
                # The legacy hash of an empty opening included the optional guitar
                # preview even though that preview was never cut into the starting bed.
                from ring_scene import coords, file_parts, guest_band_drawing, join, stem
                middle = old_zones["middle"]
                low, high = middle["safe_bounds"]
                drawing = guest_band_drawing(catalog["geometry"], ("guitar", "books", "temple"))
                art = join(drawing, stem(high, low), stem(low, high))
                route = join(middle["transit"], middle["erase"], art, middle["transit"][::-1])
                middle["variants"][1].update(path=coords(art), replace=[name for name, _ in file_parts("replace-middle-1", route)])
        old_bytes = (json.dumps(old_scene, separators=(",", ":")) + "\n").encode()
        # Only the Mini portrait layout has this fine prepared bed and working
        # radius. Light its existing height field so previously saved drawings
        # keep their geometry and edition, including those in a shared room.
        profile = MOCK
        if (result["layout"] == "portrait" and scene["assumed_working_radius_mm"] == 114
                and "prepared_erase_pitch" in scene):
            profile = dict(MOCK, lighting="mini")
        result["live"] = dict(bed=base64.b64encode(quantized.tobytes()).decode("ascii"),
                              edition=hashlib.sha256(quantized.tobytes()).hexdigest()[:16],
                              previousEdition=hashlib.sha256(old_bytes).hexdigest()[:16],
                              size=diameter, groove=scene["groove_width"], profile=profile,
                              planner=scene.get("guest_plan"),
                              radiusMM=scene["assumed_working_radius_mm"],
                              setup=[dict(name=name, text=(manifest.parent / name).read_text())
                                     for name in scene["setup"]])
        if "guest_plan" in scene:
            # The ring excursions include their rail travel. A composition needs
            # each original upright contour on its own, before those approaches.
            from ring_scene import SUBJECTS, motif, pack_path
            catalog = scene["guest_plan"]
            result["live"]["planner"] = dict(catalog,
                pairMotifs={key: pack_path(motif(key)) for key in catalog["subjects"] if key in SUBJECTS},
                pairGroove=scene["groove_width"] / catalog["geometry"]["scale"])
            border = scene["zones"]["outer"]
            low, high = border["safe_bounds"]
            if (len(catalog["geometry"]["angles"]) == 3 and len(border["variants"]) > 2
                    and high-low > 2.4*scene["groove_width"] and border.get("erase")
                    and result["live"]["planner"]["pairMotifs"].keys() == catalog["subjects"].keys()):
                result["live"]["guestBorder"] = True
                from garden_border import grain_probes, make_sectors
                sectors = make_sectors(border, catalog["geometry"]["angles"],
                                       border.get("erase_pitch", scene["erase_pitch"]), scene["groove_width"])
                if sectors:
                    result["live"].update(guestBorderProgressive=True, guestBorderSeat=True, guestBorderSectors=sectors,
                                          guestBorderGrain=grain_probes(border,sectors,diameter,scene["groove_width"]))
            if "guest_clearance_mm" in scene and catalog["geometry"].get("faceEdge") and catalog.get("places"):
                result["live"]["planner"]["customReveal"] = dict(groove=scene["groove_width"],
                                                                margin=scene["tracking_margin"])
            if catalog.get("openSubject") and catalog["defaults"] == [catalog["openSubject"]] * len(catalog["slots"]):
                result["live"]["storageKey"] = "oasis-ring-garden-open-v1"
            if catalog["geometry"].get("faceEdge"):
                # Both open layouts have identical starting sand. A saved
                # portrait or sketch must keep the orientation it was drawn in.
                live = result["live"]
                live["storageKey"] = live.get("storageKey", "oasis-ring-garden-v1") + "-facing-guests"
                live["edition"] = hashlib.sha256(b"facing-guests\0" + quantized.tobytes()).hexdigest()[:16]
            if "erase_pitch" in scene["zones"]["middle"]:
                live = result["live"]
                live["storageKey"] = live.get("storageKey", "oasis-ring-garden-v1") + "-" + live["edition"]
        live = result["live"]
        radius = live["radiusMM"]
        live["trackingMarginMM"] = radius * scene["tracking_margin"]
        # Proportional tables can have identical normalized paths and identical sand images.
        # Keep their physical gardens separate, retaining the two established table profiles.
        dimensions = tuple(format(mm, ".12g") for mm in
                           (radius, radius * live["groove"], live["trackingMarginMM"]))
        fitted = "guest_clearance_mm" in scene
        if fitted or dimensions not in {("450", "5", "2.5"), ("114", "5", "2")}:
            physical_key = ",".join(dimensions)
            geometry = (live["planner"] or {}).get("geometry", {})
            if not geometry.get("refitted") and geometry.get("independentPlaces") is not False:
                live["legacyBedEdition"] = live["edition"]
            # An open garden's bed doesn't include an engraving from which to infer its size.
            shape = json.dumps(geometry, separators=(",", ":"), sort_keys=True) if fitted else ""
            live["edition"] = hashlib.sha256(f'{physical_key}:{live["edition"]}:{shape}'.encode()).hexdigest()[:16]
            key = live.get("storageKey", f'oasis-ring-{result["layout"]}-v1')
            live["legacyStorageKey"] = key
            live["storageKey"] = f'{key}-mm-{physical_key}-{live["edition"]}'
    else:
        result["original"] = picture(sand)
    for name, zone in scene["zones"].items():
        variants = zone["variants"]
        if "live" in result:
            result["zones"][name] = dict(names=[v["name"] for v in variants])
            if name != "middle":
                result["zones"][name].update(transit=zone["transit"], erase=zone["erase"],
                                             drawings=[v["path"] for v in variants])
                if name == "outer" and any("reveal" in variant for variant in variants):
                    from ring_scene import pack_path
                    result["zones"][name]["reveal"] = {
                        str(i): {"path": pack_path(variant["reveal"]["path"]),
                                 "finished": variant["reveal"]["finished"]}
                        for i, variant in enumerate(variants) if "reveal" in variant
                    }
                if "photoErase" in zone:
                    result["zones"][name]["photoErase"] = zone["photoErase"]
            continue
        original, alternate = variants[:2]
        sand.h = initial.copy()
        sand.draw(np.asarray(zone["transit"]))
        sand.draw(np.asarray(zone["erase"]))
        cleared = picture(sand)
        sand.h = initial.copy()
        draw_files(alternate["replace"])
        result["zones"][name] = {
            "before": original["name"], "after": alternate["name"],
            "cleared": cleared, "redrawn": picture(sand),
        }

    return result


def compatible_flowers(previous, current):
    """Check the dimensions and the actual engravings a saved garden can contain."""
    old, live = previous["live"], current["live"]
    if any(old.get(k) != live.get(k) for k in ("size", "radiusMM", "groove", "trackingMarginMM")):
        return False
    before, after = previous["zones"], current["zones"]
    if before.keys() != after.keys() or after["center"]["names"] != ["Lotus", "Sunflower"]:
        return False
    for key in ("transit", "photoErase", "names"):
        if before["center"].get(key) != after["center"].get(key):
            return False
    a, b = before["outer"], after["outer"]
    if a["transit"] != b["transit"] or a["erase"] != b["erase"]:
        return False
    if any(a[k] != b[k][:len(a[k])] for k in ("names", "drawings")):
        return False
    a, b = old.get("planner") or {}, live.get("planner") or {}
    if any(a.get(k) != b.get(k) for k in ("defaults", "geometry", "fixed", "transit", "erase")):
        return False
    old_seats, new_seats = a.get("excursions", []), b.get("excursions", [])
    return len(old_seats) == len(new_seats) and all(
        all(strokes == new_seat.get(name) for name, strokes in old_seat.items())
        for old_seat, new_seat in zip(old_seats, new_seats))


def retain_previous_openings(source, scenes, *, explicit):
    """Carry the real former opening when upgrading a gallery at the same physical size."""
    try:
        text = source.read_text(encoding="utf-8")
        blocks = re.findall(r'<script type="application/json" id="(?:scene|otherScene)">(.*?)</script>', text, re.S)
        prior = {}
        for block in blocks:
            item = json.loads(block)
            if isinstance(item, dict) and "live" in item and "layout" in item:
                prior[item["layout"]] = item
    except (UnicodeError, json.JSONDecodeError) as error:
        if explicit:
            raise ValueError("Could not read the previous gallery's sand layout.") from error
        return
    if explicit and not any("live" in s and s["layout"] in prior for s in scenes):
        raise ValueError("The previous gallery has no matching live sand layout.")
    for scene in scenes:
        old = prior.get(scene["layout"])
        if not old or "live" not in scene:
            continue
        past, now = old["live"], scene["live"]
        # Identical art at the same address is a page rebuild. Keep the original
        # upgrade record if the source already carries it.
        if past["edition"] == now["edition"] and past["setup"] == now["setup"]:
            if "previousOpening" in past:
                now["previousOpening"] = past["previousOpening"]
            if "familyBorder" in past and "familyBorder" not in now:
                now["familyBorder"] = past["familyBorder"]
            continue
        if not compatible_flowers(old, scene):
            if explicit:
                raise ValueError(f'The previous {scene["layout"]} gallery has different table dimensions or artwork.')
            continue
        opening = {k: past[k] for k in ("edition", "bed", "setup", "previousEdition", "legacyBedEdition", "legacyStorageKey")
                   if k in past}
        opening["storageKey"] = past.get("storageKey", f'oasis-ring-{scene["layout"]}-v1')
        opening["setupHash"] = motion_files_hash(past["setup"])
        now["previousOpening"] = opening


def add_wide_center(garden, companion):
    """Use the same physical border for both compositions in a live three-zone garden."""
    from ring_scene import GATE, TAU, join, line, pack_path
    from thrcommon import unpack_path

    a, b = garden["live"], companion["live"]
    if any(a[key] != b[key] for key in ("groove", "radiusMM", "trackingMarginMM")):
        return
    outer = garden["zones"]["outer"]
    other_outer = companion["zones"]["outer"]
    if outer["transit"] != other_outer["transit"] or outer["erase"] != other_outer["erase"]:
        return
    catalog = a["planner"]
    small, wide = garden["zones"]["center"], companion["zones"]["center"]
    if not catalog or not wide.get("photoErase"):
        return
    middle_entry = unpack_path(catalog["transit"])
    wide_entry = np.asarray(wide["transit"])
    if middle_entry.shape != wide_entry.shape or not np.allclose(middle_entry, wide_entry, atol=1e-7, rtol=0):
        return
    # Keep the guest ring's prepared spiral so later local edits still follow its grooves.
    # At its innermost turn, continue across the former gap instead of going back to the rim.
    middle = unpack_path(catalog["erase"])
    inner = np.min(middle[:, 1])
    small_gate = small["transit"][-1][1]
    if not 0 < small_gate < inner < wide_entry[-1, 1]:
        return
    end = np.flatnonzero(np.isclose(middle[:, 1], inner, atol=1e-8, rtol=0))[-1]
    turns = int(np.ceil((inner-small_gate) / (.4*a["groove"])))
    bridge = line(GATE, inner, GATE+TAU*turns, small_gate)
    clear = join(middle[:end+1], bridge, small["erase"])
    a["wideCenter"] = {key: wide[key] for key in ("transit", "erase", "photoErase")}
    a["wideCenter"].update(restoreClear=pack_path(clear),
                           restoreStem=pack_path(line(GATE, small_gate, GATE, wide_entry[-1, 1])))

    # The reviewed mixer is a 215 mm outline spliced into known turns of this rake.
    # A separately fitted table may have a different clear even at a similar size.
    mixer_file = Path(__file__).resolve().parents[1] / "patterns/guest-rings/stand-mixer-center.json"
    mixer = json.loads(mixer_file.read_text())
    rake_hash = hashlib.sha256(wide["photoErase"].encode("ascii")).hexdigest()
    if (rake_hash == mixer["rakeSha256"] and abs(a["radiusMM"] - 420) < .001
            and abs(2 * wide_entry[-1, 1] * a["radiusMM"] - mixer["diameterMm"]) < .01
            and abs(a["groove"] * a["radiusMM"] - mixer["grooveMm"]) < .001):
        a["wideCenter"]["standMixer"] = mixer


def build(manifest, output, size, example_portrait=None, example_group=None, portrait_layout=None, example_faces=None,
          *, upgrade_from=None, family_border=None):
    scene = scene_data(manifest, size)
    companion = scene_data(portrait_layout, size) if portrait_layout else None
    if companion and (scene["layout"] != "garden" or "live" not in scene or companion["layout"] != "portrait"):
        raise ValueError("A combined preview needs a guest garden and a portrait layout.")
    if companion:
        add_wide_center(scene, companion)
    if family_border:
        wide = companion if companion else scene
        if wide["layout"] != "portrait":
            raise ValueError("The family border example needs a two-zone portrait garden.")
        data = json.loads(family_border.read_text())
        live = wide["live"]
        diameter = 2 * wide["zones"]["center"]["transit"][-1][1] * live["radiusMM"]
        if (set(data) != {"format", "diameterMm", "grooveMm", "marks"}
                or data["format"] != "oasis-prepared-portrait-v1"
                or abs(diameter-data["diameterMm"]) > .01
                or abs(live["groove"]*live["radiusMM"]-data["grooveMm"]) > .01):
            raise ValueError("Choose a prepared engraving for these table dimensions.")
        live["familyBorder"] = data
    predecessor = upgrade_from or output
    if upgrade_from or predecessor.is_file():
        retain_previous_openings(predecessor, [s for s in (scene,companion) if s], explicit=upgrade_from is not None)
    root = Path(__file__).resolve().parents[1] / "web"
    scripts, portrait_tools, portrait_models = "", "", ""
    if "live" in scene:
        scene["live"]["examples"] = {
            mode: base64.b64encode(source.read_bytes()).decode("ascii")
            for mode, source in [("one", example_portrait), ("group", example_group), ("faces", example_faces)] if source
        }
        sources = ["guest-lettering.js", "guest-thai-lettering.js", "guest-portrait-caption.js",
                   "guest-art.js", "ring-planner.js", "ring-sand.js", "ring-people.js",
                   "ring-rotation.js", "ring-room.js", "guest-face-picker.js", "guest-photo-places.js", "ring-editor.js"]
        if scene["live"]["planner"]:
            sources.insert(sources.index("ring-editor.js"), "guest-keepsake-border.js")
        artwork_notice = Path(__file__).with_name("guest_line_art-LICENSE.txt").read_text()
        scripts = "/*\n" + artwork_notice + "\n*/\n" + "\n".join((root / name).read_text() for name in sources)
        notices = [(root / name).read_text() for name in ("guest-face-LICENSE.txt", "guest-face-verify-LICENSE.txt")]
        license_lines = "\n".join("// " + line for notice in notices for line in notice.splitlines())
        portrait_models = license_lines + "\n" + "\n;\n".join(
            (root / name).read_text() for name in
            ["guest-face-model.js", "guest-landmarks.js", "guest-face-verify.js", "ring-shadow.js"])
        portrait_tools = (root / "guest-photo.js").read_text()

    def encode(data):
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    template = (root / "ring-preview.html").read_text()
    output.write_text(template.replace("/*EDITOR_SCRIPTS*/", scripts)
                      .replace("/*PORTRAIT_TOOLS*/", portrait_tools)
                      .replace("/*PORTRAIT_MODELS*/", portrait_models)
                      .replace("/*SCENE_DATA*/", encode(scene))
                      .replace("/*OTHER_SCENE*/", encode(companion)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=820)
    parser.add_argument("--example-portrait", type=Path, help="Embed a sample single-person JPEG")
    parser.add_argument("--example-group", type=Path, help="Embed a sample group JPEG")
    parser.add_argument("--portrait-layout", type=Path, help="Add a second layout with a wider center")
    parser.add_argument("--example-faces", type=Path, help="Embed a group JPEG for the close-up composition")
    parser.add_argument("--family-border", type=Path, help="Open this prepared engraving in a private two-zone border example")
    parser.add_argument("--upgrade-from", type=Path,
                        help="carry a previous gallery's saved sand when building to a new filename")
    args = parser.parse_args()
    build(args.manifest, args.output, args.size, args.example_portrait, args.example_group, args.portrait_layout, args.example_faces,
          upgrade_from=args.upgrade_from, family_border=args.family_border)
