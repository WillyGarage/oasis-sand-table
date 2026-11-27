# How to draw well in sand: running lessons

Living record of what makes a sand drawing look good on the Oasis Mini, updated after every round of testing.
Started November 22, 2026, from Bill's goal: "continually improve the ability to take an image like a photograph and
draw it as realistically as possible", by simulating and by drawing on the Mini, using the maker's techniques and our own.

Evidence labels: **[real]** measured on our Mini (photo), **[sim]** calibrated simulator, **[maker]** measured off the
maker's showcase photos, **[guess]** not yet tested. Newest round at the bottom of the log.

## Current rules (keep this section short and current)

1. **Comb, don't just draw lines.** An area is filled with back-and-forth strokes. The stroke ends form the area's edge
   and pile sand into a raised lip about 3-4 mm wide. **[real]**
2. **Rib spacing = 2 x stroke spacing.** 0.6 mm strokes give fine 1.2 mm ribs on a smooth pillow; 1.2 mm give 2.3 mm
   ribs; 2.3 mm give 4.5 mm flat tongues with creases; 5 mm give separate deep grooves. **[real]** The maker uses
   about 0.6 mm on head/chest/tail, 1.1 mm on thighs, ~5.4 mm rings for background. **[maker]**
3. **Stroke spacing is a tone and texture control**: fine = smooth and light, coarse = grooved and shadowed. **[real]**
   (Exact tone values per spacing: tone chart pending.)
4. **Strokes can and should curve with the form.** Combing across a curved band fans the ribs round the curve with a lip
   along both sides; it looks like the maker's tail. **[real]** The maker's fills are rarely straight. **[maker, Bill]**
5. **Background first, subject after** reads better for a whole picture in simulation; subject-first wipes the subject
   unless background stroke ends stay ~3-4 mm away from it. **[sim]** Not yet tested in real sand.
6. **Adjacent sections share an edge**: inset stroke ends ~0.5 mm so the boundary reads as lip / thin crease / lip;
   2-3 mm insets give flat plateaus and ditches. **[sim]**
7. **Erasing first is optional** when the whole tray is combed (the combing resurfaces it). **[sim]**
8. **The ball is about 9.8 mm wide** (measured off two phone photos with known scale). Parts narrower than about one
   ball width turn into lumps. **[real]**
9. **End with the ball parked where it helps the picture** (e.g. as the eye). **[maker, guess]**
10. **Travel moves scar the picture.** Route travel along section edges or through areas still to be drawn. **[real, sim]**

## Tools

- `tools/sim_thr.py OUT.png part1.thr ...`: calibrated whole-tray simulation (~2 min). Physics fitted to real photos
  (`tools/sand_calib.py`, `captures/relief-study/v4/STATUS.md`).
- `tools/section_comb.py`, `tools/section_flow.py`: sections and direction fields to a comb path.
- `tools/play_chunks.py`: play multi-file drawings on the Mini with photos.
- `tools/patch_test.py`, `tools/patch_test2.py`, `tools/tone_chart.py`: real-sand experiments.
- Page with pictures: https://preview.example.com/oasis-relief-study.html

## Log

### Round 1, Nov 22 evening: what the maker does
- Close-ups of the maker's dinosaur: pictures are tilings of combed sections with lips at the edges. **[maker]**
- Old simulator predicted lips 8 mm wide and wedge-shaped ribs: wrong. **[real]** Don't trust an uncalibrated sim.

### Round 2, Nov 22 7:15-8:00 pm: real patch tests on the Mini
- Test 1 (1.2 / 2.3 / 5 mm straight) and test 2 (0.6 mm straight, curved bands at 1.2 and 0.6) with phone close-ups.
  Gave rules 1-4 and 8. Phone close-ups are essential: the laptop camera (about 0.45 mm/px) can't resolve ribs.

### Round 3, Nov 22 8-11 pm: simulator calibrated, T-rex copies
- Simulator refitted to the phone photos: rib rhythm, lip width, groove width now match. A full real T-rex drawing
  and its simulation agreed, so the simulator can judge drawings. Still too faint on fine ribs, too contrasty on lips.
- Maker's T-rex decoded (sections, directions, spacings); v2 drawn on the Mini (51 min): positions right, but a jumble.
  Causes: ragged auto-traced sections, coarse strokes on limbs, travel scars. v3a/v4 iterations in sim helped a little.
- Lesson: getting the **shapes** (clean, smooth, anatomical outlines) right matters more than texture settings; an
  automatic segmentation of a photo gives ragged sections that read as a tangle.

### Round 4, Nov 22 night: photo to sand
- Started a general pipeline (`tools/photo_sand.py`): photo -> tone-matched sections with direction fields -> comb path,
  scored against the photo in the simulator. Tone chart of 16 patches (8 spacings x 2 directions) to be drawn for real.

### Round 4b, Nov 22 ~11 pm: the maker's library
- The public catalogue of Grounded's 1,173 drawings (from the ha-oasis-control GitHub project) lists names, authors,
  point counts and file locations: `captures/maker-tracks/tracks.json`. Only 150x150 path previews are public
  (`captures/maker-tracks/*.png`, `sheet.png`); the path files themselves need a login. **[maker]**
- What the previews show: photo-real work (Otávio Bitencourt's "Portrait of a Man", 29,045 points; "Tiger"; "The
  Frog") is built from regions of back-and-forth combing whose density and direction carry the tone, with highlights
  left almost empty and a few crisp contour lines for eyes, mouth and jaw. The "Velociraptor" in the library is a
  different pose from the showcase photo. Drawings run 15,000-110,000 points (several upload files on our firmware).

### Round 5, Nov 22 10:35 pm-12:10 am: T-rex v3a on the Mini
- v3a (cleaner merged sections, 0.6 mm strokes on smooth parts, thin lanes) drawn for real (erase 17 min + 2 files,
  61 min). Laptop photo beside v2 and the maker: head and neck read a little better, the body is still a jumble.
  **[real]** Matches the simulator's verdict, so sim-first iteration is valid for this kind of change. **[real, sim]**
- Technique study on small pieces (in sim): 1.2 mm strokes show ribs, 0.6 mm reads smooth; ~0.5 mm inset gives
  lip / crease / lip; body-first keeps background tongues clean against the outline (foot, tail) but whole-animal
  results favoured background-first. An outline loop and "ploughing round toes" both failed. **[sim]**
- Conclusion so far: the remaining gap is mostly **shape design** (clean anatomical outlines; nothing narrower than
  a ball width) and photography (the maker's photo is lit hard by the ring and contrast-boosted), not stroke settings.
- Grounded login works from the laptop (Bill's account), but path files need the table-only route; our factory
  certificate is no longer the active one, so it needs a certificate renewal (awaiting Bill's yes).

### Round 6, Nov 22 11:30 pm-Nov 23 12:15 am: real tone chart
- 16 patches (0.6-7 mm, two directions) drawn and photographed (`captures/tonechart/`). **[real]**
- **Mean brightness barely depends on stroke spacing** (181-192 on 0-255; erased sand 187). What changes is
  **texture contrast**: 0.6 mm is as flat as erased sand (std 3), 1.2 mm and 5-7 mm are the busiest (std 12-16).
  So shading in sand works like an engraving: smooth = highlight, coarse shadowed grooves = shadow. Score drawings
  against a photo with a local-contrast map, not average grey. **[real]**
- Our photos are lit mostly by room light from one side; the table's LEDs (40-255 brightness) change little.
  The maker's showcase look (hard ring light, dark room, contrast boost) is a photography choice. **[real]**
- The maker-library download route stays blocked: the cert renewal needs a device serial value that could not be
  pinned down without letting a table talk to Grounded (off-limits). Parked; details in captures/maker-tracks/DOWNLOAD.md.

### Round 7, Nov 23 12:20-12:45 am: shading plate (ramp, directions, sphere)
- `tools/shade_test.py`, photos in `captures/shadetest/`. **[real]** and the same path in the simulator **[sim]**.
- **A gradual change of stroke spacing reads as a smooth tone gradient** (0.6 -> 6 mm strip: flat to grooved with no
  visible steps). So tone can vary continuously inside one section; sections are not needed for every tone step. **[real]**
- **Graded spacing gives form**: a disc combed 0.7 mm at the top to 5 mm at the bottom reads as a lit, rounded ball. **[real]**
- Stroke direction at 3.5 mm changes the look only modestly under our room light. **[real]**
- The simulator reproduced the layout and gradients; it shows coarse areas with more relief than the camera does. **[sim vs real]**

### Round 8, Nov 23 12:30 am: single-family "engraving" (`tools/engrave.py`)
- One family of lines across the disc with spacing following the photo tone (level sets of the integrated 1/spacing)
  **fails**: to change spacing along a line, neighbouring lines must bend, so tone differences across the picture turn
  into large wavy stripes; the face disappears. **[sim]** Not drawn.
- Lesson: tone changes need **line terminations** (where a line stops, a new spacing can start), i.e. sections with
  their own spacing, which is what the maker does. Continuous ramps only work when the tone changes along the strokes'
  advance direction, not across it.

### Round 9, Nov 23 ~1 am: photo-to-sections pipeline (`tools/photo_sand.py`, `captures/photo-sand/`)
- Photo -> tone-matched sections with flow directions, real palette, feature lines cut last, scored in sim.
- Biggest gain: **leave highlights and background empty** (idea from the maker's portrait preview): score 0.08 -> 0.41,
  time 28 -> 12 min. Very small sections hurt; fine 0.6 mm combing doubled time for no gain. **[sim]**
- Still **far less recognisable than the gallery line portrait**: features under ~10 mm become lumps, ragged section
  outlines read as noise. Score did not track likeness (it rewarded emptiness). **[sim]**
- Lesson: at Mini scale, likeness comes from **clean continuous contour lines**; tone must come as a few large,
  smooth-edged masses added to a line drawing, not from a tone-segmentation of the photo. Next: hybrid portrait.

### Round 10, Nov 23 12:55-1:15 am: feature-size test (`tools/feature_test.py`, `captures/featuretest/`)
- Circles cut as single grooves, 8 / 12 / 16 / 20 mm across, an almond "eye" 14 x 7 mm and a 12 mm "smile", once on
  erased sand and once on a smooth 0.6 mm combed patch. **[real, laptop camera]**
- **A closed shape needs about 16 mm across to read as a ring with a hole**; 12 mm barely, 8 mm is a blob. The 14 x 7 mm
  almond reads as a small lump, not an eye. The combed backdrop changes little. So on the Mini, eyes must be single
  open strokes (lid lines) or shapes of at least ~16 mm; a whole face needs to fill most of the tray.

### Round 11, Nov 23 1:20-1:50 am: section-based Lek drawn for real
- `captures/photo-sand/lek/lek_lek_feat_part1.thr` drawn on the Mini (15 min). The laptop photo and the calibrated
  simulation match almost line for line (`captures/photo-sand/real_lek_feat/real_vs_sim.jpg`). **[real = sim]**
- So the simulator now predicts whole face drawings, not just test patches: iterate in software and spend Mini time
  only on finalists and on effects the sim can't show (fine ribs, room-light tone).
- Hybrid portrait in sim (`tools/portrait_hybrid.py`, `captures/portrait-hybrid/`): adding hair as one combed mass
  along the head outline (2.4-3.6 mm) to the line portrait helped both faces; grading the face's line spacing by the
  photo's shading, adding background masses, or the photo's own brow/nose shapes all hurt likeness. **[sim]**
  Real comparison (gallery Lek vs hair-mass Lek, same camera) queued.

### Round 12, Nov 23 1:50-2:35 am: gallery Lek vs gallery + hair mass, real
- Same camera, each after an erase (`captures/portrait-hybrid/real_gallery_vs_A.jpg`). **[real]**
- **Hair as one combed mass following the head outline (2.4-3.6 mm), plus a ponytail combed along its length, looks more
  like hair** than the gallery's wavy scribble fill; the face is unchanged. First realism gain on a face. **[real]**
- Rule: give big dark masses (hair, beard, dark clothes) their own combed texture whose strokes follow the form,
  drawn before the feature lines; keep the face itself as clean contour lines.

### Round 13, Nov 23 ~3 am: automatic portrait from face landmarks (`tools/auto_portrait.py`, `captures/auto-portrait/`)
- Lines from the photo's 478 face landmarks + masks, hair as a combed mass first, lines after. **[sim]**
- Trade-off seen: the automatic faces have **true proportions and look more like real faces**; the hand-made gallery
  faces read faster at thumbnail but are cartoons (big ring eyes). Automatic features are too thin; beards don't read
  as single strokes; a walk from the centre leaves a groove up the forehead. Next: bold multi-pass features, iris
  as a small dark combed disc, beard/shirt as combed masses, hair strokes along the photo's own flow, enter from the rim.
- Round 13b (sim): **bold features** (brows and upper lids as 3 close passes, iris as a small tight spiral that reads
  as a dark dot, doubled mouth outline), a **hairline from landmarks**, hair strokes along the photo's own strand
  direction, and **entering from the rim after an outward erase** (no groove up the forehead) made the automatic
  faces read clearly while keeping true proportions. Beards as combed masses still don't read as dark; shirts are
  mostly outside the aligned photo. Nose triangle now the heaviest shape (to fix). **[sim]**

### Round 14, Nov 23 2:35-4:25 am: six real portraits, same camera (`captures/auto-portrait/real_six.jpg`)
- Lek and Thomas, each: hand-made gallery, hand-made + hair mass, automatic v2 (landmarks, bold features, rim entry). **[real]**
- **The automatic portraits look most like real people** (true proportions, natural hair mass); the hand-made ones read
  instantly but look like cartoons. Hair mass improves the hand-made ones too. **[real]**
- Fix list from the real photos: the ball ends parked on the face (distracting; end at the rim or on an earring/pupil),
  Lek's eyes too faint (need longer, bolder lids), the nose triangle too heavy, Thomas's goatee missing.

### Round 15, Nov 23 ~5:15 am: eye styles at real size (`tools/eye_test.py`, `captures/eyetest/real.jpg`)
- Four eye designs, 22 mm wide (single lids; 3-pass upper lid; + iris spiral; + wing and 3-pass brow). **[real]**
- At 22 mm with a 9.8 mm ball, **every style merges into a blob**; stacked passes and the iris spiral don't separate.
  The pair with a brow above reads most like an eye (the brow gives the shape context).
- **Spur travel lines are as visible as the features** (each eye looked like a "P" from its 12 mm stem). Features must
  be reached along their own contours or along other drawn lines, never by spur moves.
- Rule: at Mini scale an eye is one strong lid stroke + one dark dot + a brow; anything finer merges. Bigger faces help.

### Round 16, Nov 23 5:15-5:50 am: automatic portraits round 3, real (`captures/auto-portrait/real_v2_v3.jpg`)
- Ending at the rim (travel back along drawn lines) removes the ball-on-the-face problem. **[real]**
- Single nose-side line + nostrils reads cleaner than the triangle (Lek). Heavier winged lids help a little. **[real]**
- The goatee as a combed patch with a double outline reads as a **box**: small masses (< ~30 mm) with outlines look
  like objects. Better: a few strokes following the jaw/chin, no outline. **[real]**

### Round 17, Nov 23 ~6:30 am: general photos (`tools/auto_picture.py`, `captures/auto-picture/`, CC0 test photos)
- Cat, eagle-owl, lighthouse. Only the cat would be named by a stranger (outline + ears + one dark combed face). **[sim]**
- Contour lines from the blurred photo's **tone contours** come out smooth and continuous; edges traced from fur come
  out as fragments. Keep ~10 lines at least 6 mm apart. Draw the outline first and enter/leave at the rim point
  nearest the subject (removes long scar lines). **[sim]**
- Automatic subject masks fail on busy backgrounds; one rough hand outline per photo fixes it. Fur and feather texture
  cannot be drawn as lines at this ball size. Eyes need a real eye detector (the automatic "dark spot" picks wrong).

### Round 18, Nov 23 6:00-6:35 am: automatic Alex (bearded), real (`captures/auto-portrait/real_alex_v3/crop.jpg`)
- **The beard reads in real sand** as a band of strokes following the jaw below the mouth (the sim said it wouldn't).
  The shirt strokes read as fabric. Glasses-like eye band from the bold lids; ball parked at the rim. **[real]**
- Real sand shows grooves and masses a little better than the sim's flat render; the sim is conservative on texture.
- Round 18b: cat photo drawn for real (`captures/auto-picture/real_cat/cmp.jpg`): reads as a cat (ears, head,
  shoulders); the combed face mass is a tangle and the eyes don't read. Matches the sim. **[real]**

### Round 19, Nov 23 ~7:30 am: v4 in sim (`captures/auto-portrait/compare_v4.png`, `captures/auto-picture/cat_v4_sheet.png`)
- Eye = one wide upper-lid stroke + a second pass 2.6 mm above + an iris dot wound and unwound along the same groove
  (no spur); no lower lid. Reads as "eye with pupil" at thumbnail. Face 4% larger. **[sim]**
- Goatee as a few chin-parallel strokes with no outline: no longer a box (reads as a chin tuft). **[sim]**
- Cat: OpenCV cat-face detector places eyes and nose. A face mass combed in rays from the nose reads as a starburst;
  almond-ring eyes (18 x 10 mm) + nose triangle without the starburst looks more like a cat to me. **[sim]**
- Queued for real: Thomas v4, cat almond-eye version, Lek v4.
