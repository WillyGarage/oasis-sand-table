#!/usr/bin/env bash
# Black-box microphone log (tools/earlog.py). Usage: ear.sh start | stop | status
# Output folder (Windows side): /mnt/c/Users/bill/AppData/Local/WillyGarage/oasis/ear/
D=/home/bill/dev/WillyGarage/oasis
W=/mnt/c/Users/bill/AppData/Local/WillyGarage/oasis
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
case "$1" in
  start)
    cp "$D/tools/earlog.py" "$W/earlog.py"
    "$PS" -NoProfile -Command "Start-Process -WindowStyle Hidden -FilePath 'C:\Users\bill\AppData\Local\WillyGarage\oasis\venv\Scripts\pythonw.exe' -ArgumentList 'C:\Users\bill\AppData\Local\WillyGarage\oasis\earlog.py'" ;;
  stop)
    "$PS" -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { \$_.CommandLine -like '*earlog.py*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" ;;
  status)
    "$PS" -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { \$_.CommandLine -like '*earlog.py*' } | Select-Object -ExpandProperty ProcessId" | tr -d '\r'
    tail -1 "$W/ear/levels.jsonl" 2>/dev/null; tail -2 "$W/ear/events.jsonl" 2>/dev/null ;;
esac
