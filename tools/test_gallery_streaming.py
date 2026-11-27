"""Check exact portraits while the rest of the offline gallery is still in transit."""

import argparse
import json
import re
from pathlib import Path
from threading import Event

from playwright.sync_api import sync_playwright

from gallery_test_server import GalleryRequest, gallery_http
from wide_portrait import chromium


EARLY = "?compare=1&against=mini-redwoods-woodcut/4#mini-redwoods-woodcut/6/detail"
RECENT = "#room-for-the-smaller-faces/9/hair-outline"
IDS = ["mainImage", "otherImage"]


class PausedGallery(GalleryRequest):
    def send_document(self, data):
        self.document_headers(len(data))
        self.wfile.write(data[:self.server.cut])
        if self.server.resume.wait(20):
            self.wfile.write(data[self.server.cut:])

    def send_range(self, data, start, end):
        server = self.server
        server.range_seen.set()
        if not server.return_ranges.wait(20):
            return
        if server.mode == "unsupported":
            self.document_headers(len(data))
            return
        if server.mode == "stale":
            # Same endpoints and JSON shape, but from a different gallery revision.
            wrong = bytearray(data[start:end + 1])
            wrong[2:66] = b"0" * 64
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(wrong)))
            self.end_headers()
            self.wfile.write(wrong)
        else:
            super().send_range(data, start, end)


def expected(catalog, entry_id, version_index, partner_index, view):
    entry = next(e for e in catalog["entries"] if e["id"] == entry_id)
    return [entry["versions"][i]["views"][view] for i in (version_index, partner_index)]


def check_images(page, keys):
    # Comparing the URI recorded for the selected key also catches a stale
    # completion overwriting the freshly selected <img>.
    page.wait_for_function("""keys => keys.every((key, index) => {
        const img = document.getElementById(index ? 'otherImage' : 'mainImage');
        return !img.closest('[hidden]') && img.complete && img.naturalWidth > 0 &&
               img.getAttribute('src') === catalog.images[key];
    })""", arg=keys, timeout=8000)


def check_paused(browser, gallery, mode, recent_keys, early_keys, cut, photo):
    with gallery_http(gallery, PausedGallery) as server, browser.new_context(viewport={"width":390,"height":844}) as ctx:
        server.mode = mode
        server.resume, server.range_seen, server.return_ranges = Event(), Event(), Event()
        server.cut = cut
        if mode != "switch":
            server.return_ranges.set()
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(server.url + EARLY, wait_until="commit")
            assert server.range_seen.wait(8), "The older portrait did not ask for its distant image."
            if mode == "normal":
                check_images(page, early_keys)
            elif mode == "switch":
                # Change both pictures before the first selection's response is released.
                page.evaluate("hash => { location.hash = hash; }", RECENT)
                check_images(page, recent_keys)
                server.return_ranges.set()
                page.wait_for_function("keys => keys.every(key => catalog.images[key])", arg=early_keys)
                check_images(page, recent_keys)
            else:
                page.wait_for_function("""() => performance.getEntriesByType('resource')
                    .some(r => r.initiatorType === 'fetch')""")
                assert not page.evaluate("keys => keys.some(key => catalog.images[key])", early_keys)
            assert page.evaluate("document.readyState") == "loading"
            server.resume.set()
            page.wait_for_load_state("load", timeout=20000)
            check_images(page, recent_keys if mode == "switch" else early_keys)
            if mode == "switch" and photo:
                page.locator("#yourPhoto input").set_input_files(photo)
                page.wait_for_function("""() => {
                    const canvas = document.querySelector('#reference canvas');
                    return !document.getElementById('reference').hidden && canvas.width > 1 &&
                           document.getElementById('status').textContent === 'Aligned to the drawing.';
                }""")
            assert not errors, errors
        finally:
            server.return_ranges.set()
            server.resume.set()


def check_offline(browser, gallery, early_keys, images, drawings):
    with browser.new_context(offline=True) as ctx:
        page = ctx.new_page()
        requests = []
        page.on("request", lambda req: requests.append(req.url))
        page.goto(gallery.resolve().as_uri() + EARLY)
        check_images(page, early_keys)
        counts = page.evaluate("""() => { const c = JSON.parse(document.getElementById('catalog').textContent);
            return [Object.keys(c.images).length, Object.keys(c.drawings).length]; }""")
        assert counts == [images, drawings]
        assert not any(url.startswith(("http:", "https:")) for url in requests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gallery", type=Path)
    parser.add_argument("--restaurant-photo", type=Path)
    args = parser.parse_args()
    raw = args.gallery.read_bytes()
    meta = json.loads(re.search(rb'<script id="catalog" type="application/json">(.*?)</script>', raw).group(1))
    records = re.search(rb'const byteRanges=(\{[^\n]+?\}), byteOrigin=Number\("(\d+)"\)', raw)
    offsets = json.loads(records.group(1))
    origin = int(records.group(2))
    early = expected(meta, "mini-redwoods-woodcut", 5, 3, 1)
    restaurant = next(e for e in meta["entries"] if e["id"] == "room-for-the-smaller-faces")
    recent = expected(meta, restaurant["id"], 8, restaurant["compare"][8], restaurant["viewIds"].index("hair-outline"))
    # Deliver precisely through the block containing the newer pair. The older
    # pair must still be far away when a guest switches pictures.
    end = max(origin + sum(offsets[key]) for key in recent)
    marker = b"receiveGalleryAssets()</script>\n"
    cut = raw.index(marker, end) + len(marker)
    assert min(origin + offsets[key][0] for key in early) - cut > 2 * 1024 * 1024
    drawings = {v["drawing"] for e in meta["entries"] for v in e["versions"] if "drawing" in v}
    with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        for mode in ("normal", "switch", "unsupported", "stale"):
            check_paused(browser, args.gallery, mode, recent, early, cut, args.restaurant_photo)
        check_offline(browser, args.gallery, early, len(offsets), len(drawings))
    print("Exact old and recent photographs passed partial loading, navigation during delayed responses, "
          "unavailable ranges, changed offsets and offline use.")


if __name__ == "__main__":
    main()
