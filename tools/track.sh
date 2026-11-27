#!/usr/bin/env bash
# Take a table photo and print the ball position JSON. Read-only (camera only).
# Usage: track.sh [prev.jpg]   -> captures/track_<unixtime>.jpg and track_<unixtime>_dbg.jpg
D=/home/bill/dev/WillyGarage/oasis
T=$(date +%s)
F=$D/captures/track_$T.jpg
bash $D/tools/cam.sh "$F" >&2 || exit 1
[ -s "$F" ] || { echo '{"ok":false,"note":"capture failed"}'; exit 1; }
python3 $D/tools/locate.py "$F" --debug "$D/captures/track_${T}_dbg.jpg" ${1:+--prev "$1"}
