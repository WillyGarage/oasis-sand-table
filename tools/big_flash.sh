#!/usr/bin/env bash
# Usage: big_flash.sh [sketch=big-fw]   (big-bench is the older bench-only firmware)
# Build firmware/<sketch> and put it on the 36-inch table over Wi-Fi, keeping its position: the counters are read
# before the update and restored after it (the drivers stay powered and hold the motors through the restart), then the
# arm is re-homed on its sensor, which also proves the arm did not move. Refuses while the table is moving.
export PATH="/home/bill/.local/bin:/usr/bin:/bin"
D=/home/bill/dev/WillyGarage/oasis; T=http://10.0.0.149
cd $D/firmware || exit 1
SK=${1:-big-fw}; shift $#
OUT=$(arduino-cli compile -b esp32:esp32:esp32s3:FlashSize=16M,PSRAM=disabled,PartitionScheme=custom --output-dir ./build-$SK ./$SK 2>&1)
echo "$OUT" | grep -iE "error|Sketch uses" | head -8
echo "$OUT" | grep -q "Sketch uses" || { echo "build failed: nothing sent to the table"; exit 1; }
S=$(curl -s -m5 $T/status) || { echo "table not answering"; exit 1; }
set -- $(echo "$S" | python3 -c "import json,sys; m=json.load(sys.stdin)['move']; print('r=%d&a=%d'%(m['r'],m['a']), m['carriage'], m['run'], m['rad_homed'])")
[ "$3" = 0 ] || { echo "table is moving"; exit 1; }
KEY=$(grep ADMIN_KEY $SK/wifi_creds.h | sed 's/.*"\(.*\)".*/\1/')
R=$(curl -s -m 120 -X POST -H 'Content-Type: application/octet-stream' -H "X-Key: $KEY" --data-binary @build-$SK/$SK.ino.bin $T/update); echo "$R"
case "$R" in updated*) ;; *) exit 1;; esac
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do sleep 3; s=$(curl -s -m3 $T/status) && [ -n "$s" ] && break; done
curl -s -m5 "$T/enable?on=1"; echo; curl -s -m5 "$T/zero?$1"; echo; curl -s -m40 $T/homearm
[ "$4" = 1 ] && curl -s -m5 "$T/setcarriage?c=$2"; echo
curl -s -m5 $T/status | cut -c1-40,290-
