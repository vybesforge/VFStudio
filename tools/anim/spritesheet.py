#!/usr/bin/env python
"""spritesheet.py — pack PNG frames into a sprite sheet + Godot 4 SpriteFrames .tres

Run with the stack venv:  ~/media-stack/tools/.venv/bin/python spritesheet.py ...

Input layout (one directory, one PNG per frame, frames sorted by filename):
    frames/idle_000.png idle_001.png ... run_000.png run_001.png ...
Animations are selected with --anim NAME (files matching NAME*.png). With no --anim,
every PNG in the directory becomes one animation called "default".

Examples
    # two animations, 8 fps, trim transparent padding, 64x64 cells, write .tres
    spritesheet.py frames/ --anim idle --anim run --fps 8 --trim --frame-size 64x64 \
        --out player_sheet.png --tres player_frames.tres --res-path res://player/player_sheet.png

    # frames generated on a flat magenta background (gen image): key the colour out first
    spritesheet.py gen_frames/ --key auto --key-tol 60 --trim --frame-size 128x128 --out hero.png

Output: the sheet PNG, optionally a .tres (SpriteFrames; drop it on an AnimatedSprite2D's
`sprite_frames` property, or load("res://...tres") in GDScript), and one JSON line on stdout:
    {"ok": true, "sheet": "...", "size": [W, H], "frame": [w, h], "cols": N, "rows": N,
     "animations": {"idle": 4, "run": 6}, "tres": "..."}
Each animation starts on its own row so a human can read the sheet; the .tres uses
AtlasTexture regions, so the layout does not matter to Godot.
"""
import argparse
import glob
import json
import os
import sys

from PIL import Image

try:
    import numpy as np
except ImportError:  # keying needs numpy; everything else works without it
    np = None


def parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def key_color(img, color, tol):
    """Make pixels within `tol` (euclidean RGB distance) of `color` transparent."""
    if np is None:
        sys.exit("numpy required for --key (pip install numpy)")
    a = np.asarray(img.convert("RGBA")).astype(np.int32)
    d = np.sqrt(((a[..., :3] - np.array(color)[None, None, :]) ** 2).sum(-1))
    alpha = np.clip((d - tol * 0.5) / (tol * 0.5), 0, 1)  # soft edge over half the tolerance
    a[..., 3] = (a[..., 3] * alpha).astype(np.int32)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def load_frames(args):
    anims = {}
    if args.anim:
        for name in args.anim:
            files = sorted(glob.glob(os.path.join(args.frames_dir, f"{name}*.png")))
            if not files:
                sys.exit(f"no frames match {args.frames_dir}/{name}*.png")
            anims[name] = files
    else:
        files = sorted(glob.glob(os.path.join(args.frames_dir, "*.png")))
        if not files:
            sys.exit(f"no PNG frames in {args.frames_dir}")
        anims[args.name] = files
    out = {}
    for name, files in anims.items():
        imgs = []
        for f in files:
            im = Image.open(f).convert("RGBA")
            if args.key:
                if args.key == "auto":
                    color = im.getpixel((0, 0))[:3]
                else:
                    c = args.key.lstrip("#")
                    color = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
                im = key_color(im, color, args.key_tol)
            imgs.append(im)
        out[name] = imgs
    return out


def trim_all(anims):
    """Crop every frame to the union alpha bbox (same box for all → stable pivot)."""
    box = None
    for imgs in anims.values():
        for im in imgs:
            b = im.getbbox()  # bbox of non-zero (alpha counts because mode is RGBA)
            if b is None:
                continue
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        return anims
    return {n: [im.crop(box) for im in imgs] for n, imgs in anims.items()}


def fit(im, size, pixel_art):
    """Scale `im` to fit inside `size`, centre horizontally, bottom-align."""
    fw, fh = size
    w, h = im.size
    s = min(fw / w, fh / h)
    if abs(s - 1.0) > 1e-6:
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))),
                       Image.NEAREST if pixel_art else Image.LANCZOS)
    cell = Image.new("RGBA", size, (0, 0, 0, 0))
    cell.paste(im, ((fw - im.width) // 2, fh - im.height), im)
    return cell


def write_tres(path, res_path, anims, frame, cols, fps, loop, order):
    lines = []
    n_atlas = sum(len(v) for v in anims.values())
    lines.append(f'[gd_resource type="SpriteFrames" load_steps={n_atlas + 2} format=3]\n')
    lines.append(f'[ext_resource type="Texture2D" path="{res_path}" id="1_sheet"]\n')
    anim_blocks = []
    k = 0
    for name in order:
        frames_txt = []
        for (col, row) in anims[name]:
            k += 1
            lines.append(f'[sub_resource type="AtlasTexture" id="Atlas_{k}"]\n'
                         f'atlas = ExtResource("1_sheet")\n'
                         f'region = Rect2({col * frame[0]}, {row * frame[1]}, {frame[0]}, {frame[1]})\n')
            frames_txt.append('{\n"duration": 1.0,\n"texture": SubResource("Atlas_%d")\n}' % k)
        anim_blocks.append('{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %.1f\n}'
                           % (", ".join(frames_txt), "true" if loop else "false", name, fps))
    lines.append("[resource]\nanimations = [%s]\n" % ", ".join(anim_blocks))
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames_dir")
    ap.add_argument("--anim", action="append", help="animation name = filename prefix (repeatable)")
    ap.add_argument("--name", default="default", help="animation name when --anim is not used")
    ap.add_argument("--out", required=True, help="sheet PNG path")
    ap.add_argument("--frame-size", type=parse_size, help="WxH of each cell (default: largest frame)")
    ap.add_argument("--cols", type=int, default=0, help="columns per row (default: longest animation)")
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--no-loop", action="store_true")
    ap.add_argument("--trim", action="store_true", help="crop transparent padding (same box for all frames)")
    ap.add_argument("--smooth", action="store_true", help="LANCZOS resize instead of NEAREST (pixel art)")
    ap.add_argument("--key", help="'auto' (top-left pixel) or hex like ff00ff: make that colour transparent")
    ap.add_argument("--key-tol", type=float, default=60.0, help="RGB distance tolerance for --key")
    ap.add_argument("--tres", help="write a Godot SpriteFrames .tres here")
    ap.add_argument("--res-path", help="res:// path of the sheet inside the Godot project (for .tres)")
    args = ap.parse_args()

    anims = load_frames(args)
    if args.trim:
        anims = trim_all(anims)
    order = list(anims)
    frame = args.frame_size or (max(im.width for v in anims.values() for im in v),
                                max(im.height for v in anims.values() for im in v))
    cols = args.cols or max(len(v) for v in anims.values())

    # layout: each animation starts a new row, wrapping at `cols`
    placed, row = {}, 0
    for name in order:
        cells = []
        for i, _ in enumerate(anims[name]):
            cells.append((i % cols, row + i // cols))
        placed[name] = cells
        row += (len(cells) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * frame[0], row * frame[1]), (0, 0, 0, 0))
    for name in order:
        for im, (c, r) in zip(anims[name], placed[name]):
            sheet.paste(fit(im, frame, not args.smooth), (c * frame[0], r * frame[1]))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    sheet.save(args.out)

    result = {"ok": True, "sheet": os.path.abspath(args.out), "size": list(sheet.size),
              "frame": list(frame), "cols": cols, "rows": row,
              "animations": {n: len(v) for n, v in anims.items()}}
    if args.tres:
        res_path = args.res_path or ("res://" + os.path.basename(args.out))
        write_tres(args.tres, res_path, placed, frame, cols, args.fps, not args.no_loop, order)
        result["tres"] = os.path.abspath(args.tres)
        result["res_path"] = res_path
    print(json.dumps(result))


if __name__ == "__main__":
    main()
