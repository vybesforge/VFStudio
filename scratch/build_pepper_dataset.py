"""Build a LoRA training dataset from the Pepper angle/pose/outfit manifest.

Reads <angles-dir>/manifest.json (written by pp_angles.py) and writes:
  train/datasets/pepper/<name>.png     1024 px long side, RGB
  train/datasets/pepper/<name>.txt     "pepper, <caption>"

The trigger token is `pepper`. Captions name the outfit/pose/camera so the token binds
to her identity rather than to one costume (see studio-lora skill rules).

  python build_pepper_dataset.py [--src output/image/pepper_angles] [--dest train/datasets/pepper]
"""
import argparse
import json
import shutil
from pathlib import Path

from PIL import Image

TRIGGER = "pepper"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/Users/dcruse/media-stack/output/image/pepper_angles")
    ap.add_argument("--dest", default="/Users/dcruse/media-stack/train/datasets/pepper")
    ap.add_argument("--long-side", type=int, default=1024)
    a = ap.parse_args()

    src, dest = Path(a.src), Path(a.dest)
    man = json.loads((src / "manifest.json").read_text())
    dest.mkdir(parents=True, exist_ok=True)

    made = []
    for name, meta in sorted(man.items()):
        f = src / meta["file"]
        if not f.exists():
            print(f"[ds] missing {name}")
            continue
        im = Image.open(f).convert("RGB")
        w, h = im.size
        s = a.long_side / max(w, h)
        if s < 1:
            im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        out = dest / f"{name}.png"
        im.save(out)
        (dest / f"{name}.txt").write_text(f"{TRIGGER}, {meta['caption']}\n")
        made.append(name)

    extra = dest / "pepper_face.png"
    face = Path("/Users/dcruse/media-stack/output/image/pepper_face_MASTER.png")
    if face.exists():
        im = Image.open(face).convert("RGB")
        w, h = im.size
        s = a.long_side / max(w, h)
        if s < 1:
            im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        im.save(extra)
        (dest / "pepper_face.txt").write_text(
            f"{TRIGGER}, close-up neck-up face portrait, front view, dark brown hair bun, "
            f"studio background\n")
        made.append("pepper_face")

    print(f"[ds] wrote {len(made)} image/caption pairs to {dest}")
    print("[ds] names: " + ", ".join(made))


if __name__ == "__main__":
    main()
