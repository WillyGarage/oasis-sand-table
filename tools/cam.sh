#!/usr/bin/env bash
# Capture one frame. Usage: [OASIS_EXP=-3|-4|-6|auto] cam.sh [outfile.jpg] [index]
set -euo pipefail

out=${1:-/home/bill/dev/WillyGarage/oasis/captures/cam.jpg}
index=${2:-0}
exposure=${OASIS_EXP:--3}
tools_dir=$(dirname -- "${BASH_SOURCE[0]}")
windows_dir='C:\Users\bill\AppData\Local\WillyGarage\oasis'
wsldir=$(wslpath -u "$windows_dir")
powershell=$(wslpath -u 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
work=$(mktemp -d -- "$wsldir/capture.XXXXXXXXXX")
stage=
cleanup() {
    rm -rf -- "$work"
    if [[ -n "$stage" ]]; then rm -f -- "$stage"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Windows gets the exact reader from this checkout. Each caller owns its frame.
cp -- "$tools_dir/cap_win.py" "$work/cap_win.py"
winwork="$windows_dir\\${work##*/}"
python="$windows_dir\venv\Scripts\python.exe"
# PowerShell quotes an apostrophe inside a literal by doubling it.
index=${index//\'/\'\'}
exposure=${exposure//\'/\'\'}
"$powershell" -NoProfile -NonInteractive -Command \
    "& '$python' '$winwork\cap_win.py' '$index' '$winwork\frame.jpg' '$exposure'; exit \$LASTEXITCODE" 2>&1 | tr -d '\r'
if [[ ! -s "$work/frame.jpg" ]]; then
    echo "Capture failed: Windows did not produce a frame." >&2
    exit 1
fi

# Copy across filesystems first, then publish the complete file in one rename.
stage=$(mktemp -- "$(dirname -- "$out")/.oasis-frame.XXXXXXXXXX")
cp -- "$work/frame.jpg" "$stage"
mv -fT -- "$stage" "$out"
echo "saved $out"
