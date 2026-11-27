# Icon worker (optional)

The server makes drawings itself now (`server/icons.py`, started with the app when `ANTHROPIC_API_KEY` is set).
This worker is only for filling in from another machine, for example when the server has no key. It polls the
site's worker API for interests with no picture yet, makes each drawing with the same `server/icons.py` code, and
posts it back. Needs Python 3.10 and `pip install -r requirements.txt` (anthropic, svgelements, numpy, Pillow) plus
`requests`.

## Run

```
./run.sh        # reads SAND_WORKER_TOKEN and ANTHROPIC_API_KEY from ~/.config/oasis/sand-app.env
```

or

```
SAND_BASE=https://<site> SAND_WORKER_TOKEN=<token> ANTHROPIC_API_KEY=<key> python3 icon_worker.py
```

`run.sh` unsets `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` so the SDK talks to the real API. One log line per
icon. Up to 3 at a time. A failing interest is retried 3 times, then skipped for 10 minutes. Stale (409) and
deleted (404) answers count as done. Do not run it while the server is also generating, they would both pay for
the same interests (the worker API just takes the first answer).

Test one drawing without a site (writes a 240 px sand-look PNG):

```
python3 icon_worker.py --once "clarinet playing" -o out.png
```

## Env vars

- `SAND_BASE` default `http://127.0.0.1:8787`
- `SAND_WORKER_TOKEN` required for the loop
- `ANTHROPIC_API_KEY` required
- `SAND_ICON_MODEL` (default `claude-opus-5-5`), `SAND_ICON_EFFORT` (default `medium`),
  `SAND_ICON_RULE` (`exact` default, or `custom`), `SAND_ICON_MAX_PER_HOUR` (default 150, this process only)

How the drawings are made, the Lucide library rule and the prompt: see `server/icons.py` and `API.md`.
