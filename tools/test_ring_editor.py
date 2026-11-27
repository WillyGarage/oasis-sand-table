#!/usr/bin/env python3
"""Exercise the big table's self-contained browser preview with no hardware."""

import argparse
import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright


def check_layout_files(page, url):
    page.goto(url.split("#")[0] + "#example-group")
    layout = page.locator("#layout")
    if layout.locator("option").count() != 2 or page.locator("#sampleGroup").evaluate("button => button.hidden"):
        return
    page.locator("#keep:visible").wait_for()
    caption = page.locator(".caption").inner_text()
    photo = page.locator("#sourceImage").evaluate(
        "async im => Array.from(new Uint8Array(await (await fetch(im.src)).arrayBuffer()))")
    upload = page.locator("#portraitFile")
    upload.set_input_files({"name": "family.jpg", "mimeType": "image/jpeg", "buffer": bytes(photo)})
    page.locator("#portraitSubmit").click()
    for key in ("portrait", "garden"):
        layout.select_option(key)
        page.locator("#keep:visible").wait_for()
        assert upload.evaluate("el => el.files[0].name") == "family.jpg"
        assert page.locator(".caption").inner_text() == caption
        assert page.locator("#reset").is_hidden()
        setup = page.locator("#setupFiles")
        setup.locator("summary").click()
        links = setup.locator("a")
        links.first.wait_for()
        files = page.evaluate("JSON.parse(document.getElementById('scene').textContent).live.setup")
        assert links.count() == len(files)
        for link, file in zip(links.all(), files):
            with page.expect_download() as save:
                link.click()
            assert save.value.suggested_filename == key + '-' + file["name"]
            assert save.value.path().read_text() == file["text"]
    print("Same uploaded photo retained at both sizes and both starting layouts downloaded in order.")


def run(url, screenshot):
    with sync_playwright() as pw:
        chrome = next(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
        with pw.chromium.launch(executable_path=str(chrome)) as browser:
            page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url.split("#")[0] + "#guests")
            image = page.locator("#sand")
            caption = page.locator(".caption")
            preview = page.get_by_role("button", name="Preview suggestion")

            def frame():
                image.evaluate("im=>im.decode()")
                encoded = image.get_attribute("src").split(",")[1]
                return np.asarray(Image.open(io.BytesIO(base64.b64decode(encoded))).convert("L"), dtype=float)

            def suggestion(words):
                page.locator("#idea").fill(words)
                preview.click()

            initial = frame()
            suggestion("a violin for Thomas")
            assert page.locator("#error").is_hidden()
            assert "Thomas · violin" in caption.inner_text() and "Alex · Stack of books" in caption.inner_text()
            updated = frame()
            size = len(initial)
            ys, xs = np.mgrid[-1:1:complex(size), -1:1:complex(size)]
            rr = np.hypot(xs, ys)
            # Exclude the shared stem and the edges of the selected band.
            protected = ((rr < .32) | ((rr > .81) & (rr < .95))) & (abs(xs) > .06)
            delta = np.abs(initial - updated)
            assert not np.any(delta[protected]), delta[protected].max()
            violin_area = (xs < -.30) & (ys > .15) & (rr < .74)
            assert delta[violin_area].mean() > 1, delta[violin_area].mean()
            page.locator("#downloads summary").click()
            page.wait_for_selector("#downloads a")
            link = page.locator("#downloads a").first
            with page.expect_download() as save:
                link.click()
            assert save.value.suggested_filename.endswith(".thr")
            assert len(save.value.path().read_text().splitlines()) > 1000
            if screenshot:
                page.locator("#downloads summary").click()
                page.evaluate("scrollTo(0,0)")
                page.screenshot(path=screenshot, full_page=True)

            page.locator("#keep").click()
            suggestion("replace the books with a pumpkin")
            assert "Thomas · violin" in caption.inner_text() and "Alex · Pumpkin" in caption.inner_text()
            page.locator("#keep").click()
            page.locator('input[name=zone][value=outer] + span').click()
            page.locator('input[name=stage][value=redrawn] + span').click()
            outer_updated = frame()
            page.locator("#keep").click()
            page.locator('input[name=zone][value=middle] + span').click()
            assert "Alex · Pumpkin" in caption.inner_text()
            assert np.array_equal(frame(), outer_updated)
            page.reload()
            page.wait_for_function("document.querySelector('.caption').textContent.includes('Pumpkin')")
            assert "Thomas · violin" in caption.inner_text()
            suggestion("replace the phage with a rocket")
            assert page.locator("#error").is_visible() and page.locator("#keep").is_hidden()
            suggestion("a qzxwgy for Lek")
            assert page.locator("#sketch").get_attribute("open") is not None
            assert page.locator("input[value=redrawn]").is_disabled()
            pad = page.locator("#sketchPad")
            pad.scroll_into_view_if_needed()
            box = pad.bounding_box()
            cx, cy = box["x"] + box["width"]/2, box["y"] + box["height"]/2
            page.mouse.move(cx - 40, cy)
            page.mouse.down()
            page.mouse.move(cx, cy - 34, steps=8)
            page.mouse.move(cx + 40, cy + 10, steps=8)
            page.mouse.up()
            preview.click()
            assert "Lek · a qzxwgy" in caption.inner_text()
            page.locator("#reset").click()
            assert "Thomas · Bacteriophage" in caption.inner_text() and "Alex · Stack of books" in caption.inner_text()
            check_layout_files(page, url)
            assert not errors, errors
            print("Named suggestion, saved route, successive guest and border changes, unknown subject and sketch passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    url = Path(args.page).resolve().as_uri() if "://" not in args.page else args.page
    run(url, args.screenshot)
