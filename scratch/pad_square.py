"""Pad a cutout onto a square white canvas.

TRELLIS.2 force-crops to a 1024x1024 square around the subject's mask bbox
(`ImageCropToMask` width/height 1024, pad_factor 1.1). A 2:3 portrait therefore loses
head and feet before the model ever sees it. Squaring the canvas ourselves, with the
subject centred and ~10% margin, means the template's crop has nothing left to cut.
"""
import sys

from PIL import Image

SRC, DST = sys.argv[1], sys.argv[2]
SIZE = int(sys.argv[3]) if len(sys.argv) > 3 else 1024

im = Image.open(SRC).convert("RGB")
# Treat near-white as background so the subject bbox is tight.
mask = im.convert("L").point(lambda v: 255 if v < 240 else 0)
bbox = mask.getbbox()
if not bbox:
    raise SystemExit("no subject found")

subject = im.crop(bbox)
sw, sh = subject.size
side = int(max(sw, sh) * 1.22)          # ~10% margin all round
canvas = Image.new("RGB", (side, side), (255, 255, 255))
canvas.paste(subject, ((side - sw) // 2, (side - sh) // 2))
canvas = canvas.resize((SIZE, SIZE), Image.LANCZOS)
canvas.save(DST)
print(f"[pad] subject {sw}x{sh} -> square {side} -> {SIZE}x{SIZE} -> {DST}")
