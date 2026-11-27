#!/usr/bin/env bash
# Drive a fixed set of motor poses (firmware v2 blocking /raw) and record where the camera
# sees the ball after each. Output: captures/calib.jsonl  (one line: m1 m2 + locate JSON)
cd /home/bill/dev/WillyGarage/oasis
OUT=captures/calib.jsonl; : > $OUT
curl -s -m5 "http://10.0.0.204/speed?us=5000" >/dev/null; curl -s -m5 "http://10.0.0.204/zero" >/dev/null
prev=""
for pose in "0 0" "0 1500" "0 3000" "0 4500" "1500 4500" "3000 4500" "4500 4500" "6000 4500" \
            "6000 6000" "6000 7500" "6000 9000" "6000 10500" "9000 13500" "12000 16500"; do
  set -- $pose
  curl -s -m60 "http://10.0.0.204/raw?m1=$1&m2=$2" >/dev/null
  sleep 0.5
  f=captures/cal_$1_$2.jpg
  bash tools/cam.sh "$f" >/dev/null || exit 1
  if [ -n "$prev" ]; then j=$(python3 tools/locate.py $f --prev $prev 2>/dev/null); else j=$(python3 tools/locate.py $f 2>/dev/null); fi
  echo "{\"m1\":$1,\"m2\":$2,\"loc\":$j}" >> $OUT
  prev=$f
done
echo DONE >> $OUT
