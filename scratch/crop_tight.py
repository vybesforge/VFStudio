"""Crop the reference to the subject's true bounding box.

Why this matters: the planar UV projection normalises the mesh's bounding box
against the whole image. If the photo carries white margin around the animal
(it did — the cutout is a dark hog on white), that margin lands on the model's
back and the paint reads as light on top / dark underneath. Cropping tight makes
the image and the mesh describe the same rectangle.
"""
from PIL import Image

SRC = "/Users/dcruse/media-stack/scratch/hog_cutout_1.png"
DST = "/Users/dcruse/media-stack/scratch/hog_cutout_tight.png"

im = Image.open(SRC).convert("RGB")
w, h = im.size
mask = im.convert("L").point(lambda v: 255 if v < 240 else 0)
bbox = mask.getbbox()
if not bbox:
    raise SystemExit("no subject found — image is entirely background")

pad = 4
box = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
       min(bbox[2] + pad, w), min(bbox[3] + pad, h))
crop = im.crop(box)
print(f"image {im.size} -> subject bbox {bbox} -> cropped {crop.size}")
print(f"margins were left={bbox[0]} top={bbox[1]} right={w-bbox[2]} bottom={h-bbox[3]}")
crop.save(DST)
print("wrote", DST)
