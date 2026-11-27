"""Compare normal group-photo downloads with explicit choices on the previous editor.

Pass a fitted editor, its previous version, and a photograph with three nearby
guests and a small person at the edge. Additional --control photos should keep
every detected face. Original photos remain in the offline browser.
"""

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from test_garden_room import drawing_files
from test_ring_group_shadows import MOBILE, submit, toggle
from test_ring_shadows import ready
from wide_portrait import chromium


def upload(page, editor, photo, layout):
    page.goto("about:blank")
    page.goto(editor.resolve().as_uri() + "?layout=" + layout + "#photos")
    submit(page, photo, "heads")


def selections(page):
    return page.locator("#faceBoxes button").evaluate_all(
        "items=>items.map(b=>b.getAttribute('aria-pressed')==='true')"
    )


def check(browser, current, previous, source, controls, bystander):
    with browser.new_page(offline=True, **MOBILE) as phone, browser.new_page(offline=True, **MOBILE) as old:
        for layout in ("portrait", "garden"):
            upload(old, previous, source, layout)
            all_faces = selections(old)
            assert all(all_faces) and len(all_faces) >= 4
            earlier_all = drawing_files(old, "#downloads")
            toggle(old, bystander)
            foreground = selections(old)
            earlier_foreground = drawing_files(old, "#downloads")
            assert earlier_all != earlier_foreground

            upload(phone, current, source, layout)
            assert (
                selections(phone) == foreground and drawing_files(phone, "#downloads") == earlier_foreground
            )
            expect(phone.locator("#portraitSource")).to_have_attribute("open", "")
            expect(phone.locator("#portraitStatus")).to_contain_text(
                f"{sum(foreground)} of {len(foreground)} faces"
            )
            button = phone.locator("#toggleDistantFace")
            expect(button).to_have_text("Include the smaller face")
            button.tap()
            ready(phone)
            assert selections(phone) == all_faces and drawing_files(phone, "#downloads") == earlier_all
            expect(button).to_have_text("Leave out the smaller face")

            # Two taps while the converter is still rendering must both survive.
            phone.evaluate(
                """i=>{
              const boxes=document.querySelectorAll('#faceBoxes button');
              boxes[i].click(); boxes[[...boxes].findIndex((_,j)=>j!==i)].click();
            }""",
                bystander,
            )
            ready(phone)
            first = 0 if bystander != 0 else 1
            assert not selections(phone)[first] and not selections(phone)[bystander]
            phone.evaluate(
                """i=>{
              const boxes=document.querySelectorAll('#faceBoxes button');
              boxes[[...boxes].findIndex((_,j)=>j!==i)].click(); boxes[i].click();
            }""",
                bystander,
            )
            ready(phone)
            assert selections(phone) == all_faces

            # Explicitly leave out a large face while retaining the small one.
            other = 0 if bystander != 0 else 1
            toggle(phone, other)
            chosen = selections(phone)
            assert not chosen[other] and chosen[bystander]
            for style in ("pose", "heads"):
                phone.locator("#portraitStyle").select_option(style)
                ready(phone)
                assert selections(phone) == chosen
            other_layout = "garden" if layout == "portrait" else "portrait"
            for name in (other_layout, layout):
                phone.locator("#layout").select_option(name)
                ready(phone)
                assert selections(phone) == chosen
            toggle(phone, other)
            button.tap()
            ready(phone)
            assert (
                selections(phone) == foreground and drawing_files(phone, "#downloads") == earlier_foreground
            )

            for photo in controls:
                upload(old, previous, photo, layout)
                expected = selections(old)
                assert len(expected) >= 2 and all(expected), (layout, photo)
                upload(phone, current, photo, layout)
                assert selections(phone) == expected and drawing_files(phone, "#downloads") == drawing_files(
                    old, "#downloads"
                ), (layout, photo)
                expect(button).to_be_hidden()
            print(
                layout,
                "passed automatic foreground, manual inclusion and exclusion, layout/style changes and",
                len(controls),
                "unaffected group photos",
                flush=True,
            )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("editor", "previous", "group"):
        cli.add_argument(name, type=Path)
    cli.add_argument("--bystander", type=int, default=4, help="Number of the background face in the picker.")
    cli.add_argument("--control", type=Path, action="append", default=[])
    args = cli.parse_args()
    with sync_playwright() as pw, pw.chromium.launch(executable_path=chromium(pw, None)) as browser:
        check(browser, args.editor, args.previous, args.group, args.control, args.bystander - 1)
