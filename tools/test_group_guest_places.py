#!/usr/bin/env python3
"""Assign people from one phone photo to guest places, then recover the same sand from another phone."""

import argparse
import json
from pathlib import Path
import sqlite3
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright
from scipy.spatial import cKDTree

import check_ring_scene as check
from test_garden_family_portrait import bed, mobile_chairs
from test_garden_room import API, choose, drawing_files, keep, open_room, room, suggest
from test_guest_keepsake_border import reopen
from test_guest_place import contour, contour_samples
from test_ring_guest_border import MOBILE, preview, replay, save
from test_ring_lettering import seat_view
from test_ring_object_photo import PhoneTraffic, capture_stages, expand
from test_ring_photo import frame
from test_ring_shadows import ready


def prepare(previous, database, browser, center, requests):
    with room(previous, database) as url, browser.new_page(**MOBILE) as host:
        traffic = PhoneTraffic(url)
        host.route("http**://**/*", traffic.check)
        open_room(host, url)
        choose(host, "zone", "center")
        expand(host, "#centerPhoto")
        host.locator("#portraitFile").set_input_files(
            traffic.photo(center.name, center.read_bytes(), "image/jpeg")
        )
        host.locator("#portraitSubmit").click()
        ready(host)

        def keep():
            command, _ = save(host, url + API)
            requests.append(command)
            return command["state"]

        keep()
        choose(host, "zone", "outer")
        preview(host, 4, "Lek", order="progressive")
        keep()
        choose(host, "zone", "middle")
        suggest(host, "an open book for Alex")
        keep()
        expand(host, "#peopleBox")
        host.locator("#personPick").select_option("")
        host.locator("#personName").fill("Bill")
        host.locator("#personInterest").fill("acoustic guitars")
        host.locator("#personPlace").select_option("0")
        host.locator("#personDrawing").select_option("guitar_silhouette")
        host.locator("#personSubmit").click()
        state = keep()
        assert state["ids"] == ["guitar_silhouette", "books_open", "open_place"], state["ids"]
        assert (
            state["guestBook"]["active"] == ["bill", "alex", "lek"]
            and state["portrait"]
            and state["outer"] == 4
        )
        assert not traffic.violations, traffic.violations
        return state


def lateral_order(page, selector, count):
    boxes = page.locator(selector)
    expect(boxes).to_have_count(count, timeout=25000)
    centers = boxes.evaluate_all("items=>items.map(b=>parseFloat(b.style.left)+parseFloat(b.style.width)/2)")
    assert np.isfinite(centers).all() and len(set(centers)) == count, centers
    return np.argsort(centers).tolist()


def pick_single(page, url, source, slot, lateral, name, count, framing):
    reopen(page, url, "middle")
    expand(page, "#centerPhoto")
    page.locator("#guestPhotoKind").select_option("face")
    page.locator("#portraitPlace").select_option(str(slot))
    page.locator("#portraitName").fill(name)
    page.locator("#guestPortraitFrame").select_option(framing)
    page.locator("#portraitFile").set_input_files(source)
    page.locator("#portraitSubmit").click()
    boxes = page.locator("#faceBoxes button")
    order = lateral_order(page, "#faceBoxes button", count)
    boxes.nth(order[lateral]).click()
    expect(page.locator("#keep")).to_be_visible(timeout=25000)
    expect(page.locator(".caption")).to_contain_text("Portrait of " + name)
    files = drawing_files(page, "#downloads")
    command, _ = save(page, url + API)
    assert command["motion"]["place"] == slot
    state = command["state"]
    return state["custom"][state["ids"][slot]], files


def references(browser, gallery, database, root, group, picks, framing):
    # Each solo preview starts from this exact garden, including the latest recorded
    # guests. Later single requests change other slots, preserving the next source.
    refdb = root / "singles.db"
    with sqlite3.connect(database) as src, sqlite3.connect(refdb) as dst:
        src.backup(dst)
    with room(gallery, refdb) as url, browser.new_page(**MOBILE) as phone:
        traffic = PhoneTraffic(url)
        source = traffic.photo(group.name, group.read_bytes(), "image/jpeg")
        phone.route("http**://**/*", traffic.check)
        results = {
            slot: pick_single(phone, url, source, slot, lateral, name, len(picks), framing)
            for slot, (lateral, name) in picks.items()
        }
        assert not traffic.violations, traffic.violations
        return results


def start_group(page, source, picks, framing):
    choose(page, "zone", "middle")
    expand(page, "#centerPhoto")
    page.locator("#guestPhotoKind").select_option("groupPlaces")
    expect(page.locator("#guestPortraitFrame")).to_have_value("head")
    page.locator("#portraitFile").set_input_files(source)
    order = lateral_order(page, "#faceBoxes .numbered-face", len(picks))
    expect(page.locator("#portraitSubmit")).to_be_disabled()
    if framing != "head":
        page.locator("#guestPortraitFrame").select_option(framing)
    for slot, (lateral, name) in picks.items():
        page.locator(f"#guestFace{slot}").select_option(str(order[lateral]))
        page.locator(f"#guestFaceName{slot}").fill(name)
    expect(page.locator("#portraitSubmit")).to_be_enabled()
    page.locator("#portraitSubmit").click()
    expect(page.locator("#keep")).to_be_visible(timeout=30000)


def signed_face(route, state, slot, geom, radius_mm):
    # Find the complete, uninterrupted engraving inside the physical five-decimal
    # download. A crossing of two portraits or an erase touching an eye cannot
    # satisfy a two-sided comparison of this whole closed stroke.
    shape = contour(state, slot, geom)
    anchor = shape[np.argmax(np.linalg.norm(shape, axis=1))]
    xy = route[:, 1, None] * np.column_stack((np.cos(route[:, 0]), np.sin(route[:, 0])))
    hits = np.flatnonzero(np.linalg.norm(xy - anchor, axis=1) < 0.000035)
    expected = contour_samples(shape, 0.12 / radius_mm)
    target = cKDTree(expected)
    length = np.linalg.norm(np.diff(shape, axis=0), axis=1).sum()
    distances = check.travel(route)
    best = None
    for i, left in enumerate(hits):
        for right in hits[i + 1 :]:
            if abs((distances[right] - distances[left]) - length) > 0.004:
                continue
            walk = check.sample_walk(route[left : right + 1], 0.12 / radius_mm)
            err = max(target.query(walk)[0].max(), cKDTree(walk).query(expected)[0].max()) * radius_mm
            if err < 0.3 and (best is None or right < best[2]):
                best = (err, int(left), int(right))
    assert best and best[0] < 0.3, (slot, best, hits)
    return {
        "max_seated_error_mm": round(float(best[0]), 3),
        "start_row": best[1],
        "end_row": best[2],
        "complete_at_m": round(float(distances[best[2]] * radius_mm / 1000), 3),
    }


def proof_image(folder, final, geo, names, slots):
    width = 650
    out = Image.new("RGB", (width, 520 + 225 * len(slots)), "#f7f1e7")
    draw = ImageDraw.Draw(out)
    title = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
    text = ImageFont.truetype("DejaVuSans.ttf", 18)
    draw.text((20, 14), "One photo, separate guest places", font=title, fill="#292720")
    draw.text((20, 52), "Simulated sand · from above and facing each chair", font=text, fill="#514e45")
    out.paste(Image.fromarray(final).resize((426, 426), Image.Resampling.LANCZOS), (112, 84))
    for i, slot in enumerate(slots):
        top = 522 + i * 225
        crop = seat_view(final, geo, slot)
        out.paste(crop.resize((211, 211), Image.Resampling.LANCZOS), (20, top))
        draw.text((257, top + 68), names[slot], font=title, fill="#292720")
        draw.text((257, top + 105), ("Bill", "Alex", "Lek")[slot] + "’s place", font=text, fill="#514e45")
    out.save(folder / "chair-portraits.jpg", quality=94)


def verify_case(host, second, url, before, picks, independent, dest, requests):
    dest.mkdir(mode=0o700, exist_ok=True)
    api = url + API
    frozen = {z: host.request.get(api + "/drawings/" + z).json() for z in ("center", "outer")}
    assert all(d["revision"] and d["files"] for d in frozen.values())
    scene = host.evaluate("""()=>{const s=JSON.parse(document.querySelector('#scene').textContent);
       return {g:s.live.planner.geometry,groove:s.live.groove,size:s.live.size,mm:s.live.radiusMM,dock:s.zones.center.transit[0]};}""")
    files = drawing_files(host, "#downloads")
    images = capture_stages(host)
    assert host.request.get(api).json()["state"] == before
    kept, revision = save(host, api)
    requests.append(kept)
    state = kept["state"]
    motion = kept["motion"]
    assert motion["zone"] == "middle" and files == [(f["name"], f["text"].encode()) for f in motion["files"]]
    signed = [np.loadtxt(raw.splitlines()) for _, raw in files]
    route = check.joined(signed, scene["dock"], scene["dock"], "separate guest portraits")
    parts = motion.get("parts", [])
    assert {p["place"] for p in parts} == set(picks), motion.keys()
    strata = {}
    offset = 0
    names = {}
    for part in parts:
        slot = part["place"]
        count = part["count"]
        subfiles = files[offset : offset + count]
        offset += count
        callback, solo = independent[slot]
        # Full, ordinary paths can be differently named in a combined download.
        assert [raw for _, raw in subfiles] == [raw for _, raw in solo], slot
        shape = state["custom"][state["ids"][slot]]
        np.testing.assert_array_equal(shape, callback)
        name = picks[slot][1]
        names[slot] = name
        assert state["labels"][state["ids"][slot]] == "Portrait of " + name
        strata[slot] = signed_face(route, state, slot, scene["g"], scene["mm"])
        strata[slot]["source"] = name
    assert offset == len(files) and len(set(state["ids"])) == 3
    for z in ("center", "outer"):
        assert host.request.get(api + "/drawings/" + z).json() == frozen[z]
    for key in ("center", "portrait", "outer", "borderGuest", "widePortrait", "portraitSeats"):
        assert state.get(key) == before.get(key), key
    n = scene["size"]
    y, x = np.mgrid[-1 : 1 : complex(n), -1 : 1 : complex(n)]
    r = np.hypot(x, y)
    lower, upper = scene["g"]["bounds"]
    groove = scene["groove"]
    masks = {
        "center": r < lower - 2 * groove,
        "rim": (r > upper + 2 * groove) & (r < 0.99) & ((y < 0) | (abs(x) > 2 * groove)),
    }
    unchanged_clearance = {}
    for slot in set(range(3)) - set(picks):
        older_ink = contour_samples(contour(before, slot, scene["g"]), 0.15 / scene["mm"])
        trip = cKDTree(check.sample_walk(route, 0.15 / scene["mm"]))
        distance = float(trip.query(older_ink)[0].min()) * scene["mm"]
        assert distance > scene["mm"] * groove * 1.65, (slot, distance)
        unchanged_clearance[slot] = round(distance, 2)
        assert state["ids"][slot] == before["ids"][slot]
        a = scene["g"]["angles"][slot]
        cx, cy = scene["g"]["center"] * np.array([np.cos(a), np.sin(a)])
        masks["unchanged_guest"] = np.hypot(x - cx, -y - cy) < scene["g"]["scale"]
    for mask in masks.values():
        np.testing.assert_array_equal(bed(before, n)[mask], bed(state, n)[mask])
        for img in images[1:]:
            np.testing.assert_array_equal(images[0][mask], img[mask])
    rebuilt = replay(host, before["bed"], *signed)
    delta = np.abs(rebuilt.astype(np.int16) - images[-1].astype(np.int16))
    assert delta.mean() < 1.1 and np.percentile(delta, 99) < 6, (delta.mean(), np.percentile(delta, 99))
    reopen(second, url, "middle")
    assert second.request.get(api).json()["state"] == state
    assert drawing_files(second, "#roomFiles") == files
    assert second.locator("#portraitFile").evaluate("el=>el.files.length") == 0
    mobile_chairs(second, ["Bill’s chair", "Alex’s chair", "Lek’s chair"], dest)
    for title, img in zip(("before", "during", "finished"), images):
        Image.fromarray(img).save(dest / (title + ".png"))
    for fname, raw in files:
        (dest / fname).write_bytes(raw)
    proof_image(dest, images[-1], scene["g"], names, sorted(picks))
    return state, {
        "revision": revision,
        "parts": parts,
        "faces": strata,
        "meters": round(float(check.travel(route)[-1] * scene["mm"] / 1000), 3),
        "protected": {k: int(mask.sum()) for k, mask in masks.items()},
        "unchanged_art_clearance_mm": unchanged_clearance,
        "files": len(files),
    }


def conflict(browser, gallery, database, target, photo):
    with sqlite3.connect(database) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    with (
        room(gallery, target) as url,
        browser.new_page(**MOBILE) as first,
        browser.new_page(**MOBILE) as second,
    ):
        traffic = PhoneTraffic(url)
        first.route("http**://**/*", traffic.check)
        second.route("http**://**/*", traffic.check)
        source = traffic.photo(photo.name, photo.read_bytes(), "image/jpeg")
        reopen(first, url, "middle")
        reopen(second, url, "middle")

        # Hold the first phone's next background poll so its actual PUT reaches
        # the server with an older revision. These are independent browser rooms.
        def previous_poll(route):
            tag = route.request.headers.get("if-none-match")
            if route.request.method == "GET" and tag:
                route.fulfill(status=304, headers={"ETag": tag})
            else:
                route.fallback()

        first.route("**" + API, previous_poll)
        start_group(first, source, {0: (0, "Bill"), 2: (1, "Lek")}, "head")
        draft = frame(first)
        suggest(second, "a field pumpkin for Bill")
        latest, revision = save(second, url + API)
        assert latest["state"]["ids"][0] == "pumpkin_ribbed"
        assert keep(first, status=409) == revision
        assert first.request.get(url + API).json()["state"] == latest["state"]
        np.testing.assert_array_equal(frame(first), draft)
        first.unroute("**" + API, previous_poll)
        expect(first.locator("#roomReload")).to_be_visible()
        first.locator("#roomReload").click()
        expect(first.locator(".caption")).to_contain_text("Pumpkin")
        assert not traffic.violations, traffic.violations
        return {"rejected_status": 409, "preserved_newer_subject": "pumpkin_ribbed"}


def exercise(browser, previous, gallery, root, trio, out):
    out.mkdir(mode=0o700, exist_ok=True, parents=True)
    requests = []
    with tempfile.TemporaryDirectory() as temp:
        tmp = Path(temp)
        db = tmp / "garden.db"
        before = prepare(previous, db, browser, root / "lek.jpg", requests)
        (out / "requests.json").write_text(json.dumps(requests, separators=(",", ":")))
        report = {}
        with (
            room(gallery, db) as url,
            browser.new_context(**MOBILE, service_workers="block") as c1,
            browser.new_context(**MOBILE, service_workers="block") as c2,
        ):
            traffic = PhoneTraffic(url)
            c1.route("http**://**/*", traffic.check)
            c2.route("http**://**/*", traffic.check)
            host = c1.new_page()
            second = c2.new_page()
            reopen(host, url, "middle")
            reopen(second, url, "middle")
            assert second.request.get(url + API).json()["state"] == before
            for label, photo, picks, framing in [
                ("two", root / "bill-with-lek.jpg", {0: (0, "Bill"), 2: (1, "Lek")}, "head"),
                (
                    "three",
                    trio,
                    {0: (2, "Right crewmate"), 1: (0, "Left crewmate"), 2: (1, "Middle crewmate")},
                    "head",
                ),
            ]:
                ref = tmp / label
                ref.mkdir()
                independent = references(browser, gallery, db, ref, photo, picks, framing)
                reopen(host, url, "middle")
                source = traffic.photo(photo.name, photo.read_bytes(), "image/jpeg")
                start_group(host, source, picks, framing)
                before, record = verify_case(
                    host, second, url, before, picks, independent, out / label, requests
                )
                report[label] = record
                (out / "requests.json").write_text(json.dumps(requests, separators=(",", ":")))
                assert not traffic.violations, traffic.violations
                assert traffic.writes == len(report), traffic.writes
            assert sorted(p["place"] for p in report["two"]["parts"] if p.get("fill")) == [2]
            assert not any(p.get("fill") for p in report["three"]["parts"])
            report["stale_photo_draft"] = conflict(
                browser, gallery, db, tmp / "conflict.db", root / "bill-with-lek.jpg"
            )
            (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gallery", type=Path)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--family", type=Path, required=True)
    parser.add_argument("--three", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    with sync_playwright() as pw:
        chrome = next(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            exercise(browser, args.previous, args.gallery, args.family, args.three, args.evidence)
