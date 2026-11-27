#!/usr/bin/env python3
"""Crop a camera frame to the sand table and upscale 2x, so the ball is easy to see.
Usage: crop.py in.jpg out.jpg"""
import sys
from PIL import Image
im = Image.open(sys.argv[1])
box = (780, 530, 1420, 1080)         # table region in the 1920x1080 frame; re-check if the laptop moves
c = im.crop(box); c = c.resize((c.width*2, c.height*2), Image.LANCZOS)
c.save(sys.argv[2], quality=88)
