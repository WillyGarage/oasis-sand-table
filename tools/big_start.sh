#!/usr/bin/env bash
# Bring the 36-inch table from power-on (or any unknown position) to ready, without a camera:
# drivers on, arm homed on its sensor, radius homed by the centre touch. Prints the final status line.
T=http://10.0.0.149
S=$(curl -s -m5 $T/status) || { echo "table not answering"; exit 1; }
echo "$S" | grep -q '"run":1' && { echo "table is moving"; exit 1; }
curl -s -m5 "$T/enable?on=1"; echo
curl -s -m90 "$T/homearm"; echo
curl -s -m5 "$T/homeradius"; echo
for i in $(seq 1 240); do sleep 0.5; H=$(curl -s -m5 $T/status | grep -o '"home":[0-9]*' | cut -d: -f2); [ "$H" != 1 ] && break; done
curl -s -m5 $T/status | grep -o '"arm_homed":[0-9],"rad_homed":[0-9],"carriage":[0-9]*,"fault":[0-9]\|"home":[0-9]*,"home_went":[0-9]*'
[ "$H" = 2 ] || { echo "radius home failed (state $H)"; exit 1; }
