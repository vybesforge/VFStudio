"""Compare base-colour texture detail between two GLBs.

More mesh resolution does not automatically mean a better bake: the texture stage can
produce a softer or flatter albedo at higher settings, and renders misjudge it (a dim
rear view of a sharper texture reads as "no detail"). Laplacian variance is a standard
focus metric -- higher means more high-frequency structure.

    python texture_diff.py A.glb B.glb

Compare a rebuild against its predecessor and report the delta, not a description.
Needs Pillow + numpy: run it with ComfyUI's venv, the audio venv has no PIL.
"""

import io
import json
import struct
import sys

import numpy as np
from PIL import Image


def load_base_colour(path):
    """Return the PBR base-colour image, following the material binding."""
    with open(path, "rb") as f:
        _, _, total = struct.unpack("<III", f.read(12))
        chunks = {}
        while f.tell() < total:
            cl, ct = struct.unpack("<II", f.read(8))
            chunks[ct] = f.read(cl)
            if cl % 4:  # glTF chunks are 4-byte aligned
                f.read(4 - (cl % 4))
    js = json.loads(chunks[0x4E4F534A].decode("utf-8").rstrip("\x00 "))
    binc = chunks[0x004E4942]

    # images[0] is not the albedo on a PBR asset -- the exporter reorders them.
    textures = js.get("textures", [])
    idx = None
    for mat in js.get("materials", []):
        i = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index")
        if i is not None:
            idx = textures[i].get("source")
            break
    if idx is None:
        idx = 0

    bv = js["bufferViews"][js["images"][idx]["bufferView"]]
    off = bv.get("byteOffset", 0)
    img = Image.open(io.BytesIO(binc[off:off + bv["byteLength"]])).convert("L")
    return img, len(js.get("images", []))


def metrics(img):
    a = np.asarray(img.resize((512, 512)), dtype=np.float64)
    lap = (4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1]
           - a[1:-1, :-2] - a[1:-1, 2:])
    return float(lap.var()), float(a.mean()), float(a.std())


def main(paths):
    rows = []
    for p in paths:
        img, n = load_base_colour(p)
        var, mean, std = metrics(img)
        rows.append((p, img.size, n, var, mean, std))
        print(f"{p}: size={img.size} images={n} "
              f"laplacian_var={var:.1f} mean={mean:.1f} std={std:.1f}")
    if len(rows) == 2:
        a, b = rows[0][3], rows[1][3]
        if a > 0:
            print(f"detail delta: {(b - a) / a * 100:+.1f}%  "
                  f"({'B is sharper' if b > a else 'A is sharper'})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
