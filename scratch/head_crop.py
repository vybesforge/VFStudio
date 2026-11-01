"""Crop a head-and-neck square from a photo, for head-only reconstruction.

The body recon gets ~5% of a 4096 atlas for the face, so eyes come out as voids.
Feeding the head as its own subject gives it the whole frame and the whole atlas.

Usage: python head_crop.py in.png out.png [x1 y1 x2 y2]
"""
import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGB")

if len(sys.argv) >= 6:
    x1, y1, x2, y2 = (int(v) for v in sys.argv[3:7])
else:  # measured face bbox on ppimage.png
    x1, y1, x2, y2 = 590, 160, 1070, 840

# Grow to a square that includes the hairline and the neck, because TRELLIS needs
# closed silhouettes — a chin-only crop reconstructs an open shell.
cx = (x1 + x2) / 2
side = (y2 - y1) * 1.55
half = side / 2
top = y1 - side * 0.16
left, right = cx - half, cx + half
bottom = top + side

box = (max(0, int(left)), max(0, int(top)), min(im.width, int(right)), min(im.height, int(bottom)))
crop = im.crop(box)
print(f"crop {box} -> {crop.size}")
crop.save(dst)
