# sand-app: guest app for the 36-inch table (sand.example.com)

Public, no security by Bill's decision (name-only identity, no passwords, no party code, no approval gate).
Design source: `tools/sand_app_mockup.py` (the TEMPLATE string is the approved mockup: copy its CSS, wording and
screen structure). Design record: memory file `sand-app design notes`.

Not wired to the table. The public server never calls the private side. A home-side worker polls the public server
(worker API below) and pushes results back. Turns only finish when the table driver says so (or the host skips, or a person is removed); time passing never ends one.

## Layout

```
sand-app/
  server/app.py        FastAPI app (uvicorn), SQLite in $SAND_DATA/sand.db, uploads in $SAND_DATA/faces/
  server/scheduler.py  pure rotation logic, no I/O, unit-tested
  server/render.py     sand-look icon PNG (relief_png), placeholder SVG, face stand-in preview, the whole-table picture
                       (render_table: zone geometry, name lettering, layout, grooves, rim) (Pillow, numpy, scipy, cv2, matplotlib)
  server/icons.py      makes the drawings: Claude -> SVG -> strokes, background worker, cache, spending caps
  server/svgstrokes.py hostile-safe SVG flattening to strokes
  server/lucide/       the Lucide icon set flattened to strokes (icons.json), build.py, ISC LICENSE
  server/tests/        pytest
  static/              index.html, app.js, app.css, vendor/ (face detector)   <- frontend agent owns this
  worker/icon_worker.py  optional outside poller: same server/icons.py code, posts strokes via the worker API
  Dockerfile, docker-compose.yml, requirements.txt, deploy/
```

Run locally: `SAND_DATA=/tmp/sand-data SAND_WORKER_TOKEN=dev uvicorn server.app:app --port 8787` from `sand-app/`.
The server serves `static/` at `/` (index.html for `/`), JSON under `/api`, images under `/img`.

## Data

- Person: `id` (int), `name` (unique, case-insensitive, trimmed, 1-30 chars), `joined` (bool: tapped "Add me to the
  table"; preloaded names are not joined), `color` (index 0-7 or null), `faces` (0-2 uploaded crops), `face_v` (int,
  bumps on change, for cache busting), `face_pending` (bool: crops are uploaded and the drawing is being made in the
  background; the upload answers at once, `/img/face` is 404 and the plan has no `face_strokes` until it is done,
  then `face_v` goes up by one), `keepsake_v` (int, 0 = no keepsake picture yet, +1 each time one is saved),
  `interests` (ordered list, unlimited).
- Centre picture (Thanksgiving art): `key` (1-40 chars of a-z, 0-9, hyphen), `label` (1-40 chars), `strokes` (same
  format and limits as interests), `enabled` (host switch, default true), `v` (bumps when label or strokes change).
  The driver owns the set; the app shows it and lets the host switch items on and off.
- Interest: `id`, `person_id`, `label` (1-40 chars), `status` `pending` (waiting for AI) | `ready`, `source`
  `ai` | `sketch`, `strokes`, `v` (bumps on change).
- Strokes format (icons and sketches): `{"strokes": [[[x,y],[x,y],...], ...]}`, x and y in 0..1, y down, at most 40
  strokes and 4000 points total. Server clamps and rejects anything else with 400.

## Guest/host API (no auth, JSON)

`GET /api/state` - one poll gives the UI everything (poll every 4 s):

```json
{
 "now": 1795590000, "paused": false, "clock": "idle", "ring": "interests",
 "centre_art": [{"key": "turkey", "label": "Turkey", "enabled": true, "v": 1}],
 "people": [{"id": 3, "name": "Bill", "joined": true, "color": 2, "faces": 1, "face_v": 4,
   "interests": [{"id": 9, "label": "star wars", "status": "ready", "source": "ai", "v": 2,
                  "shared_with": ["Maria", "Sam"],
                  "related": [{"name": "Diego", "label": "soccer", "theme": "sports"}]}],
   "zone": "centre", "zones": ["centre", "outer-4"], "next_at": 1795590630, "next_in": 2, "next_zone": "centre", "featured": 2,
   "keepsake_v": 3}],
 "table": {
   "current": {"turn": 17, "kind": "draw", "person_id": 3, "zone": "centre", "started_at": 1795589700, "ends_at": 1795590180,
               "percent": 62, "done": false, "steps": ["Clearing the spot", "Writing Bill's name", "Drawing Bill's face",
               "Adding Bill's interests"], "step": 2, "interest_ids": [9], "centre_art": ["turkey", "pie"]},
   "zones": [{"zone": "centre", "person_id": 3, "dirty": false, "interest_ids": [9], "centre_art": ["turkey", "pie"]},
             {"zone": "inner-1", "person_id": null, "dirty": true, "interest_ids": []}],
   "upcoming": [{"kind": "clear", "person_id": null, "zone": "inner-1", "at": 1795590180, "interest_ids": []},
                {"kind": "draw", "person_id": 5, "zone": "inner-2", "at": 1795590288, "interest_ids": [12, 13]}],
   "hold_until": null
 }
}
```

`zone` on a person is where they are on the table now (the centre if they are in the centre and a slice; null if nowhere);
`zones` lists every zone they are in (centre first). `next_at` and `next_zone` are the start and zone of the person's next
projected turn, also while they are on the table (null only when not joined or nothing is projected; the look-ahead is
`min(3N+2, 120)` turns, the `upcoming` list shows the first `max(12, N+2)`). `table.current` is null when nobody has joined.
A `clear` turn has `person_id` null, `steps` `["Clearing a spot"]`. During a centre hold (below) `table.current` is the finished
centre turn with `percent` 100 and `done` true, and `table.hold_until` is when the next turn starts (else `done` false,
`hold_until` null). `clock` is `idle`
until a table driver has posted progress in the last 2 minutes, then `table` (with `auto_advance` on, `simulated` instead of `idle`).
While `idle`: `percent` is what the driver last reported for that turn (0 if never), `started_at`/`ends_at` are placeholders
(not facts), `next_at` and `upcoming[].at` are null. `next_in` (every mode) is how many turns start before the person's
next one (0 = theirs is the next to start; null when not joined or not projected; clear turns count). `shared_with` uses the mockup's
fuzzy match (`key()`/`same()` in the mockup script), computed server-side, joined people only, sorted by name.
`related` links guests whose interests differ but share a theme: one entry per other joined person at most (their first
matching interest by id, never someone already in this interest's `shared_with`, never the same label), sorted by name;
`theme` is the first of this interest's own themes that the two share. `[]` while themes are unknown. Themes come from a
background Claude call (batches of up to 30 new labels, 0-2 themes each, stored in `label_themes`, at most 300 calls a day,
model `SAND_THEME_MODEL`). The fixed list, in order: sports, fitness, music, dance, food and drink, the outdoors, animals,
gardening, art, making things, books, games, movies and TV, science, technology, travel, cars and machines, history,
fashion, teaching.

| Call | Body | Result |
|---|---|---|
| `POST /api/people` | `{"name"}` | 201 person; 409 `{"error":"taken","name":"Alex"}`; 400 bad name |
| `POST /api/people/bulk` | `{"names":[...]}` | `{"added": n}` (skips duplicates) |
| `PATCH /api/people/{id}` | any of `{"color": 0-7 or null, "joined": true}` | person |
| `DELETE /api/people/{id}` | | 204; their zone goes dirty, they leave the rotation |
| `POST /api/people/{id}/faces` | multipart `face1`, optional `face2` (JPEG/PNG, each max 8 MB) | person; replaces old faces |
| `DELETE /api/people/{id}/faces` | | person |
| `POST /api/people/{id}/interests` | `{"label"}` or `{"label","strokes"}` | 201 interest (`pending` unless strokes given). A label with commas, semicolons or line breaks (and no strokes) is several interests: 201 `{"interests":[...]}` (splits on those only, never on "and" or spaces; trims; drops empties, duplicates inside the entry and ones the person already has, case-insensitive; max 20 parts, each 1-40 chars, whole entry max 400 chars; 400 `bad_label` if nothing is left). A single label keeps the single-interest shape. |
| `PATCH /api/interests/{id}` | `{"label"}` (back to `pending`, old strokes dropped) or `{"strokes"}` (`ready`, `sketch`) | interest |
| `DELETE /api/interests/{id}` | | 204 |
| `POST /api/host/pause` | `{"paused": bool}` | state |
| `POST /api/host/skip` | | state (ends the current draw turn now; its zone goes dirty and is redrawn at once; no-op during a clear turn) |
| `POST /api/host/move` | `{"person_id", "dir": -1 or 1}` | state (swap with neighbour in the queue) |
| `POST /api/host/feature` | `{"person_id", "zones": ["centre", "inner-4"]}` (1 to 3 zones, default `["centre"]`) | state. "Feature now": the next turns draw this person in these zones, in this order, ahead of every other rule; whoever is in a zone is replaced and leaves the table; the person may be in several zones at once. Pending requests are in `table.forced` (`[{"person_id","zone"}]`) and show in `upcoming`. 409 `not_joined`. |
| `POST /api/host/erase` | `{"dir": "in" or "out" or null}` | state. Host asks for a whole-table erase ("in": rim to middle, "out": middle to rim); null cancels while it has not started. `table.erase` (and the plan's top-level `erase`) is `{"id","dir","status": "waiting" or "running","at"}` or null. While it is set no new turn starts. The driver finishes the file it is on, posts `POST /api/worker/erase {"id","status":"running"}` (reply `accepted` false = cancelled), erases, then `POST /api/worker/reset`, which clears the request and restarts the rotation from the centre. 409 `erase_running` once it has started. |
| `POST /api/host/pin` | `{"person_ids": [..]}` | state. The people shown first on the Everyone page, in this order (`table.pinned`); empty list clears it. |
| `POST /api/host/ring` | `{"ring": "interests"|"faces"|"leaves"|"wheat"|"lotus"|"waves"}` | state. **Deprecated** (old design, no UI any more): stored only, the plan still carries `ring`, nothing uses it |
| `POST /api/host/centre-art` | `{"key", "enabled": bool}` | state; 404 unknown key. The choice is remembered per key |
| `POST /api/host/settings` | any of `{"centre_minutes", "slice_minutes", "auto_advance": bool}` | state (no UI for this). `auto_advance` (default false, also for old saved states) brings back the time-driven turns: a turn ends when its time runs out, `clock` reads `simulated` when no driver reports; for demos |

`centre_art` in the state is the registered set in post order. `table.current.centre_art` is the list of keys picked for the
running turn (empty for slices, clear turns and a centre turn that started before any picture existed). `table.zones[centre]
.centre_art` is the keys drawn with the centre's present occupant (kept after later slice turns, dropped when the centre
changes hands). `ring` is deprecated (see `/api/host/ring`).

Images (cacheable, clients add `?v=`):
- `GET /img/icon/{interest_id}.png` - what the app uses. `ready`: the strokes carved as grooves with raised lips in
  smooth sand, lit from the upper left (`render.relief_png`, the look of the approved mockup icons), circular, transparent
  outside. `?s=120|240|480` (default 240, snapped). Cached on disk in `$SAND_DATA/icons/` by id, v and size.
  `pending`: the lettered placeholder (SVG, `image/svg+xml`, behind the same URL).
- `GET /img/icon/{interest_id}.svg` - the older flat version (dark line plus light offset), still served.
- `GET /img/face/{person_id}.jpg` - square sand-style drawing made by the server from the first crop: the landmark
  portrait when a face is found; otherwise (pets, objects) a model line drawing of the photo's main subject (counts as
  one generation against the icon caps; the upload waits at most 60 s for it, 10-25 s typical); only if that is
  unavailable, a pencil-sketch
  in sand tones; replaced by the worker's real preview when one is posted). `?n=2` for the second face. 404 if none.

- `GET /img/centre-art/{key}.png` - the picture as grooves in sand (`render.relief_png`), circular, transparent outside.
  `?s=120|240|480` (default 240). Cache-bust with `?v=` from the state's `centre_art[].v`. 404 unknown key.
- `GET /img/table.png` - the whole table as it stands now, the sand-relief look (see "The table picture"). `?s=` pixels,
  200..2000, default 1000. `Cache-Control: no-cache`. Rendered on a background thread and cached by a version; while a new
  one renders the previous one is served (the first ever request waits for its render).
- `GET /img/keepsake/{person_id}.png` - the table picture saved right after that person's last turn (1000 px), or the live
  table picture when they have none yet (`keepsake_v` 0; `no-cache`). Cache-bust with `?v=keepsake_v`. 404 unknown person.

Limits (sanity, not security): 300 people, 60 interests per person, request body 20 MB (the `drawn` call needs about 2 MB).

## Drawings (server/icons.py)

Interests are drawn on the server. Needs env `ANTHROPIC_API_KEY`; without it the server does not generate and
interests stay `pending` for the worker API (or an outside `worker/icon_worker.py`).

- Model `claude-opus-5-5` (`SAND_ICON_MODEL`), `output_config.effort` `medium` (`SAND_ICON_EFFORT`), default thinking, non-streaming,
  `max_tokens` 8000, JSON schema output: `subject`, `shapes` (the plan), `lucide_icon`, `lucide_fit`, `svg`. The long fixed
  system prompt is first and marked for prompt caching. Guest text is data: it appears only in the user message,
  capped at 40 chars, control characters stripped, inside `<topic>` tags.
- Rule `exact` (`SAND_ICON_RULE`, other value `custom`): the model may name a real Lucide icon (2431 of them in
  `server/lucide/icons.json`) only when that icon IS the subject (guitar, sailboat, music note, open book). Otherwise it
  draws its own 24-grid SVG (stroke only; path, circle, ellipse, rect, line, polyline, polygon). Decided on a 16-subject
  contact sheet: loose library matches (church for temple, virus for bacteriophage, sword for lightsaber) were worse
  than own drawings; exact matches were as good or better.
- The SVG is parsed as hostile input (`svgstrokes.py`): unknown elements, scripts, hrefs, `url()`, DOCTYPE, entities, huge
  paths all rejected. It is flattened to polylines, centred and scaled to fit the disc, then stored as normal strokes.
- Background service (3 at a time, started with the app): picks up every `pending` `ai` interest, including ones left over
  from before a restart. Same label (case-insensitive) from two guests reuses one drawing (`icon_cache` table). Caps: 150
  fresh generations per hour and 1500 per day (`SAND_ICON_MAX_PER_HOUR`, `SAND_ICON_MAX_PER_DAY`), counted in the
  `icon_usage` table so restarts do not reset them; at the cap interests stay as lettered placeholders and a warning is
  logged. 3 failed tries on one interest, then it is left alone for 10 minutes. A rejected API key pauses generation 5 minutes.
- Refusals, `max_tokens` stops, rate limits (after the SDK's own backoff), 5xx and timeouts are failures that count as a
  try, never crashes.

## Centre pictures

The driver registers a set of Thanksgiving pictures (`POST /api/worker/centre-art`); the host switches items on and off
(Host page, "Thanksgiving pictures in the middle"). For every centre turn of kind `draw` the app picks up to 2 enabled items
at random, once, when that turn first becomes the current turn, and keeps the keys on the current-turn record
(`current.centre_art`, set in the app layer; scheduler.py is untouched). They never change for that turn, whatever the host
switches afterwards. A turn that was already running before any picture existed has none. The keys also go on the centre zone
record for its occupant. Slices and clear turns get `[]`. Stored in the `centre_art` table (key, label, strokes, pos, v) and
`centre_art_pref` (key, enabled: kept even while a key is missing from the set).

## The table picture and keepsakes (server/render.py, `render_table`)

What the table really drew comes from the driver (`POST /api/worker/drawn`); where it has not, the app lays the zone out
itself. One round picture, sand disc to the full reach (rho 1.0 = 385 mm), dark rim and light ring outside, groove width
0.011 of the picture width (the 9.8 mm ball on a 770 mm circle; the app's own layout uses finer grooves so faces stay readable).

Coordinates (table frame): x = rho*cos(theta), y = rho*sin(theta), rho 0..1 at the full reach, theta counter-clockwise from 0
degrees pointing right, y up. Geometry constants are in one place at the top of that section of `render.py` (rho of full reach):
design circle 0.9831, inner ring boundary 0.6688, centre circle 0.2959, inner slices every 90 degrees (inner-1 is 0-90,
counter-clockwise), outer slices every 60 (outer-1 is 0-60). `TABLE_ROT_DEG = 0` turns the whole picture.

What a zone shows, first match wins:
1. its turn is in progress (current, not done): plain sand (it has just been wiped);
2. the driver's `drawn` strokes for its present occupant, if posted by or after the turn that drew them (a post for someone
   else, or from before the occupant's latest draw, is ignored);
3. an occupant: the app's layout. The name lettered in DejaVu Sans Bold (matplotlib TextPath outlines, filled), the stored
   face drawing (both if two), up to 3 interest drawings, and in the centre its chosen `centre_art` beside the face. Filled
   to the zone with a clear gap to the zone lines, the name smaller than the face; in a slice every item stands radially with
   its top toward the table centre;
4. empty (or dirty): plain sand.

Zone lines: the posted `frame` strokes if any (non-empty), otherwise the design geometry above.

Rendering is numpy plus scipy's distance transform and OpenCV line drawing (about 1.2 s for 1000 px with 11 full zones, laptop).
It runs on one background thread, never inside the DB lock. The version is a hash of a small description (who is in each zone,
which zone is being wiped, `drawn` revisions, face, interest and picture versions), so it changes when a turn starts or
finishes, a post arrives or the table is reset.

Keepsake: when a draw turn for person P finishes (table clock, simulated clock, any mode), a background render saves the
table picture to `$SAND_DATA/keepsakes/{person_id}.png` (only the latest per person) and bumps `keepsake_v`. A skipped turn or
one whose person left makes none. A late `drawn` post for the turn that just finished renders P's keepsake again. Deleting
the person deletes the file.

## Rotation rules (scheduler.py)

Zones: `centre`, `inner-1..4`, `outer-1..6` (equal areas). One turn redraws one whole zone for one person: name
first, then face, then up to 3 interests. N = joined people.

- Dirty zones first (any mode): a zone goes dirty (`person_id` null, `dirty` true) when its person is deleted or the host
  skips its turn. The very next turn is on the oldest dirty zone: a normal `draw` for the next eligible person, else a
  `clear` turn (`person_id` null, steps `["Clearing a spot"]`, 40% of the zone's minutes, then clean and empty). Eligible for a
  slice: joined, in no slice, not the skipped person, preferring someone not in the centre. For the centre: someone off
  the table if there is one, else anyone but the skipped person. When N drops nothing is "retired": slices just empty out this way.
- Empty centre (so an empty table): the next turn is the centre, for the first person by the pick rule.
- Fill: while a slice is empty and a joined person is in no slice, the next turn puts such a person into the first empty
  slice in this order: inner-1, outer-1, inner-2, outer-3, inner-3, outer-4, inner-4, outer-6, outer-2, outer-5. Someone not in
  the centre first. All 10 slices are usable; a slice nobody needs stays empty (no clear turn).
- Everyone has a slice (N <= 10): only the centre turns, cycling everyone (fewest centre turns, ties by queue order, never
  the person already in the centre). The centre person is also in their slice, on purpose. A lone person is redrawn only
  with more than 3 interests.
- N > 10 and all 10 slices full: centre, slice, centre, slice. Centre: the next person not on the table (never-featured
  first, then fewest centre turns, ties by queue order). Slice: the slice drawn longest ago (`last_drawn` turn number) gets
  the next person not on the table (never-featured first, then fewest slice turns). Nobody is on the table twice, except
  when nobody is off it (N = 11 right after the fill): the centre then takes the person with fewest centre turns from a
  slice, which frees the old centre person for the next slice turn. Measured (not proven): centre counts stay within 2 of
  each other and slice counts within 1 for N = 11..40.
- Centre hold: a finished centre stays up at least 60 s before the next centre turn. If the next turn is a centre draw and the
  previous turn was a centre draw that ended at T, it starts at max(now, T+60). Slice turns and clear turns are never
  held, so a newcomer's slice (fill) goes at once. During the hold nothing is in progress: `table.current` is the finished
  turn (`done` true, percent 100), `table.hold_until` its end, the worker plan's `current` is null and its `next` carries the
  start in `at`. The next turn starts by itself on any read of state or plan once the hold is over, in both clock modes
  (with the table as the clock the hold is measured from the `done` progress report). Starting a turn when there is none, ending a hold and dirty-zone turns happen with no driver too. Pause freezes the hold. Skip
  during a hold does nothing.
- `queue`: persisted ordered list of joined people. A newcomer goes behind every other never-featured person and ahead of
  everyone already featured (with an empty slice they are drawn into it first).
- Pick = never-featured first, in queue order; otherwise fewest turns of that kind (centre or slice), ties by queue
  order. The chosen person moves to the back of the queue. A skipped person goes to the back and is not eligible
  for the redraw. Deleting the person whose turn is running ends the turn.
- Interests: each turn shows up to 3, starting at the person's cursor; the cursor advances so more than 3 cycle on
  later turns. Pending interests count (the worker may finish them in time).
- No eligible person: no turn, the current one idles (percent 100) and the next read tries again. Nothing joined: no current turn.
- Durations: centre 4.5 min, slice 4.5 min by default (settings; existing saved states keep theirs). With `auto_advance` on: when
  `ends_at` passes and not paused, the next turn starts; off (default): never by time. Pause freezes the remaining time. Skip ends the turn now.
- Old saved states load: `last_drawn`, `last_kind`, `last_end` default to empty (missing = turn 0), `pos` is ignored.
  Worker reset empties them too.
- `upcoming`: run the same logic forward on a copy for max(12, N+2) turns, including hold delays; clear turns appear
  with `kind` `clear`.
- Step split by percent: clearing 0-30, name 30-45, face 45-75, interests 75-100 (steps without content are
  dropped and the rest re-spread).

## Worker API (home side only; header `X-Worker-Token: $SAND_WORKER_TOKEN`, 401 otherwise)

| Call | Result |
|---|---|
| `GET /api/worker/jobs` | `{"interests":[{"id","label","v"}], "faces":[{"person_id","face_v","n":1}]}` - pending interests, and faces with no real preview yet |
| `POST /api/worker/interests/{id}` body `{"v", "strokes"}` | sets `ready` if `v` still matches, else 409 |
| `GET /api/worker/face/{person_id}/{n}` | the uploaded crop (JPEG) |
| `POST /api/worker/faces/{person_id}` multipart `preview` (PNG/JPEG), optional `path` (JSON), form `face_v` | stores the real sand preview and the drawable path |
| `GET /api/worker/plan` | full table plan: state plus `current`, `next` and every zone, each with `kind` (turns), `dirty` (zones), name, color, ring, face path (if any) and interest strokes; a clear turn has name null and no interests. `current` is null while there is no turn in progress, including the 60 s hold after a centre turn (then `next.at` is when the next turn starts; the driver just waits). `next.at` is null while the clock is `idle`, except during a hold, where it stays the hold end. `current.centre_art` is `[{"key","label","strokes"}]` (the picked pictures; `[]` for slices and clear turns). `next` carries what that turn will have when it starts, so the driver can build it early: `turn` (current turn number + 1) and `centre_art` in the same form (`[]` unless it is a centre draw turn). The centre pictures are picked the first time `next` shows that person's centre turn and are kept when it becomes `current`, even if the host switches one off in between. `next` is still a forecast: a skip, a removal, a new guest or an edit can change it, so compare turn, zone, person, face_v, interest ids and versions and picture keys before playing a turn built early. The centre entry of `zones` has `centre_art`: the keys drawn with its occupant. |
| `POST /api/worker/centre-art` body `{"items":[{"key","label","strokes"}]}` | `{"items": [state's centre_art list]}`. Upsert by key (1-40 chars a-z 0-9 hyphen; label 1-40; strokes as interests: 0..1, y down, upright, max 40 strokes and 4000 points; at most 40 items); keys missing from the post are deleted; order is post order; `enabled` is remembered per key. 400 `bad_items`, `bad_key`, `bad_label`, `bad_strokes` |
| `POST /api/worker/drawn` body `{"turn": int, "zone": zone name or "frame", "strokes": [[[x,y],...],...]}` | `{"ok": true, "rev": n}`. What is left visible in that zone after that turn (re-cut boundary, lettering, face, pictures, extras), table frame (see "The table picture"), x and y within -1.05..1.05, at most 60000 points and 2000 strokes (else 400 `bad_strokes`; an empty list is fine). `"frame"` holds the lines that belong to no zone. Accepted when `turn` is the current turn or the most recently finished one, 409 `stale` otherwise (also for the zone of the running turn when `turn` is the previous one, and for anything from before a reset). A post replaces the earlier one for that zone. Stored zlib-compressed in the `drawn` table (zone, turn, person_id at post time, strokes, posted, rev) |
| `POST /api/worker/progress` body `{"turn", "percent", "done": bool}` | the real table reports progress; `done` advances the rotation (the only thing that does, besides skip and removal, unless `auto_advance` is on) |
| `POST /api/worker/reset` | the table was wiped: every zone empty, turn counts zeroed, the fill starts again from the centre (people, order, settings and pause are kept; the turn number keeps counting). Also deletes every `drawn` post and refuses posts for turns before it |

The plan's interest strokes are 0..1 with y down, so y = 0 is the top of the picture; erase direction is tracked by the table side, not the app.
