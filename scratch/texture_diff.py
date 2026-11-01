"""Compare base-colour texture sharpness between two GLBs.

More mesh resolution does not automatically mean a better bake — the texture stage can
produce a softer or flatter albedo at higher settings. Laplacian variance is a standard
focus/detail metric: higher means more high-frequency structure.

Usage: python texture_diff.py A.glb B.glb
"""
import io
import json
import struct
import sys

import numpy as np
from PIL import Image


def load(path):
    with open(path, "rb") as f:
        _, _, total = struct.unpack("<III", f.read(12))
        chunks = {}
        while f.tell() < total:
            cl, ct = struct.unpack("<II", f.read(8))
            chunks[ct] = f.read(cl)
            if cl % 4:
                f.read(4 - (cl % 4))
    js = json.loads(chunks[0x4E4F534A].decode("utf-8").rstrip("\x00 "))
    binc = chunks[0x004E4942]

    # Follow the material binding, not images[0].
    tex = js.get("textures", [])
    idx = None
    for m in js.get("materials", []):
        i = m.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index")
        if i is not None:
            idx = tex[i].get("source")
            break
    if idx is None:
        idx = 0
    bv = js["bufferViews"][js["images"][idx]["bufferView"]]
    off = bv.get("byteOffset", 0)
    im = Image.open(io.BytesIO(binc[off:off + bv["byteLength"]])).convert("L")
    return im, len(js.get("images", []))


def detail(im):
    a = np.asarray(im.resize((512, 512)), dtype=np.float64)
    lap = (4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:])
    return float(lap.var()), float(a.mean()), float(a.std())


for p in sys.argv[1:]:
    im, n = load(p)
    v, mean, std = detail(im)
    print(f"{p}: size={im.size} images={n} laplacian_var={v:.1f} mean={mean:.1f} std={std:.1f}")
