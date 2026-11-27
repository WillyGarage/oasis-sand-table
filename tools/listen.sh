#!/usr/bin/env bash
# Record the laptop microphone for N seconds and print loudness + bangs as one JSON line.
# Usage: listen.sh SECONDS [out.wav in captures/]     (see tools/listen.py)
D=/home/bill/dev/WillyGarage/oasis
W=/mnt/c/Users/bill/AppData/Local/WillyGarage/oasis
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
PY='C:\Users\bill\AppData\Local\WillyGarage\oasis\venv\Scripts\python.exe'
cp "$D/tools/listen.py" "$W/listen.py"
WAV=""; [ -n "$2" ] && WAV="'C:\\Users\\bill\\AppData\\Local\\WillyGarage\\oasis\\_listen.wav'"
"$PS" -NoProfile -Command "& '$PY' 'C:\Users\bill\AppData\Local\WillyGarage\oasis\listen.py' $1 $WAV" 2>&1 | tr -d '\r' | grep '^{' | tail -1
[ -n "$2" ] && cp "$W/_listen.wav" "$2"
