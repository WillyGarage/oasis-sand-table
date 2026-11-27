#!/usr/bin/env bash
# Build firmware/our-fw and put it on the table.
#   flash.sh [--no-build]            over USB (COM3), as before
#   flash.sh [--no-build] --ota      over Wi-Fi (firmware v8+, table must be idle): POST /update
# Either way the table is told not to start drawing by itself on the restart that follows.
export PATH="/home/bill/.local/bin:/usr/bin:/bin"
D=/home/bill/dev/WillyGarage/oasis
cd $D/firmware || exit 1
BUILD=1; OTA=0
for a in "$@"; do [ "$a" = "--no-build" ] && BUILD=0; [ "$a" = "--ota" ] && OTA=1; done
if [ $BUILD = 1 ]; then
  arduino-cli compile -b esp32:esp32:esp32s3:FlashSize=16M,PSRAM=disabled,PartitionScheme=custom --output-dir ./build-out ./our-fw 2>&1 | grep -iE "error|Sketch uses" | head -5
fi
KEY=$(grep ADMIN_KEY our-fw/wifi_creds.h | sed 's/.*"\(.*\)".*/\1/')
if [ $OTA = 1 ]; then
  R=$(curl -s -m 120 -X POST -H 'Content-Type: application/octet-stream' -H "X-Key: $KEY" --data-binary @build-out/our-fw.ino.bin "http://10.0.0.204/update")
  echo "$R"
  case "$R" in updated*) ;; *) echo "update refused"; exit 1;; esac
  sleep 6
else
  curl -s -m 3 "http://10.0.0.204/auto?skipboot=1" >/dev/null
  cp build-out/our-fw.ino.bin /mnt/c/Users/bill/AppData/Local/WillyGarage/oasis/our-app.bin || exit 1
  PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe; PY='C:\Users\bill\AppData\Local\WillyGarage\oasis\venv\Scripts\python.exe'
  # The USB route always writes the first app slot. A Wi-Fi update may have switched the table to the second slot, so
  # wipe the slot selector (otadata, 0xe000) as well: the bootloader then starts the first slot again.
  $PS -NoProfile -Command "& '$PY' -m esptool -p COM3 -b 230400 --chip esp32s3 --after no-reset erase-region 0xe000 0x2000 2>&1 | Select-Object -Last 1; & '$PY' -m esptool -p COM3 -b 230400 --chip esp32s3 write-flash --flash_mode dio --flash_freq 80m --flash_size 16MB 0x10000 'C:\Users\bill\AppData\Local\WillyGarage\oasis\our-app.bin' 2>&1 | Select-Object -Last 2" 2>&1 | tr -d '\r' | grep -iE "verified|error|fatal|erase"
fi
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do sleep 3; s=$(curl -s -m3 http://10.0.0.204/status) && [ -n "$s" ] && { echo "$s" | cut -c1-200; exit 0; }; done; echo "table did not come back on Wi-Fi"; exit 1
