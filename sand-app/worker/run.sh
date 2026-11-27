#!/bin/sh
# Start the outside icon maker against the live site. Token and Anthropic key come from
# ~/.config/oasis/sand-app.env (made by deploy.py). The server makes drawings itself when it has the key,
# so this is only needed to fill in from another machine.
cd "$(dirname "$0")" || exit 1
set -a; . "$HOME/.config/oasis/sand-app.env"; set +a
unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN
export SAND_BASE="${SAND_BASE:-https://sand.example.com}"
exec python3 icon_worker.py
