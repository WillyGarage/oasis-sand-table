#!/usr/bin/env bash
# The noisy part of qualification 3 (speeds raised until position is lost). Run only inside an agreed quiet window.
cd /home/bill/dev/WillyGarage/oasis/tools
python3 big_q3.py radius 4000,6000,8000,12000,16000 8000
python3 big_q3.py arm 4000,6000,8000,12000,16000 8000 12000
python3 big_q3.py arm 3000,4000,5000,6000 8000 44000
echo WINDOW-PART1-DONE
