#!/bin/bash
# Restart the sand driver if it is not running.  Meant to run every minute (cron: * * * * * /path/tools/sand_supervisor.sh)
# or in a loop (while true; do tools/sand_supervisor.sh; sleep 60; done).
#   - respects the driver's own lock (captures/sand-app/driver.lock): if the driver holds it, nothing happens;
#   - respects the stop file (captures/sand-app/driver.stop): while it exists nothing is started (a running driver deletes it
#     and exits after its turn; if it is still there with no driver running, a human asked for a stop);
#   - only one supervisor at a time.
# Extra arguments are passed to the driver.  Env: SAND_BASE (default https://sand.example.com), SAND_DRIVER_ARGS (default "--real --allow-live"),
# SAND_LOCK / SAND_STOP / SAND_LOG override the paths (for tests).  The worker token is read from ~/.config/oasis/sand-app.env.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAP="$ROOT/captures/sand-app"
LOCK="${SAND_LOCK:-$CAP/driver.lock}"
STOP="${SAND_STOP:-$CAP/driver.stop}"
LOG="${SAND_LOG:-$CAP/driver.log}"
BASE="${SAND_BASE:-https://sand.example.com}"
DARGS="${SAND_DRIVER_ARGS---real --allow-live}"
mkdir -p "$CAP"
exec 9>"$CAP/supervisor.lock"
flock -n 9 || exit 0
touch "$LOCK"
if ! flock -n 8 8>>"$LOCK"; then
    exit 0                                    # the driver is running (it holds the lock)
fi
exec 8>&-                                     # free again: release it so the driver can take it
if [ -e "$STOP" ]; then
    echo "$(date '+%F %T') supervisor: stop file present, not starting the driver" >> "$LOG"
    exit 0
fi
if [ -z "$SAND_WORKER_TOKEN" ] && [ -r "$HOME/.config/oasis/sand-app.env" ]; then
    SAND_WORKER_TOKEN="$(grep '^SAND_WORKER_TOKEN=' "$HOME/.config/oasis/sand-app.env" | head -1 | cut -d= -f2-)"
    export SAND_WORKER_TOKEN
fi
echo "$(date '+%F %T') supervisor: driver not running, starting it" >> "$LOG"
cd "$ROOT"
# shellcheck disable=SC2086
nohup python3 -u tools/sand_driver.py $DARGS --base "$BASE" "$@" >> "$LOG" 2>&1 9>&- &
disown
