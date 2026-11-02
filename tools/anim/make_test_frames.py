#!/usr/bin/env python
"""make_test_frames.py — draw simple placeholder character frames (idle + run) with PIL.

Use this when you need a sprite sheet to test with and have no art yet (no ComfyUI needed).
    ~/media-stack/tools/.venv/bin/python make_test_frames.py OUT_DIR [--size 64] [--idle 4] [--run 6]
Writes OUT_DIR/idle_000.png ... and OUT_DIR/run_000.png ... (RGBA, transparent background).
"""
import argparse
import math
import os

from PIL import Image, ImageDraw


def draw_frame(size, phase, running):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 64.0
    bob = (math.sin(phase * 2 * math.pi) * (3 if running else 1)) * s
    cx, ground = size / 2, size - 4 * s
    # legs
    swing = math.sin(phase * 2 * math.pi) * (10 if running else 0) * s
    d.line([(cx - 4 * s, ground - 16 * s), (cx - 4 * s + swing, ground)], fill=(40, 40, 60, 255), width=int(4 * s))
    d.line([(cx + 4 * s, ground - 16 * s), (cx + 4 * s - swing, ground)], fill=(40, 40, 60, 255), width=int(4 * s))
    # body
    top = ground - 36 * s + bob
    d.rounded_rectangle([cx - 10 * s, top, cx + 10 * s, ground - 14 * s + bob], radius=4 * s, fill=(220, 90, 60, 255))
    # head
    d.ellipse([cx - 9 * s, top - 16 * s, cx + 9 * s, top + 2 * s], fill=(250, 210, 170, 255))
    d.ellipse([cx + 2 * s, top - 10 * s, cx + 5 * s, top - 7 * s], fill=(0, 0, 0, 255))
    # arms
    d.line([(cx - 10 * s, top + 4 * s), (cx - 14 * s - swing * 0.5, top + 16 * s)], fill=(250, 210, 170, 255), width=int(3 * s))
    d.line([(cx + 10 * s, top + 4 * s), (cx + 14 * s + swing * 0.5, top + 16 * s)], fill=(250, 210, 170, 255), width=int(3 * s))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--idle", type=int, default=4)
    ap.add_argument("--run", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    for i in range(a.idle):
        draw_frame(a.size, i / a.idle, False).save(os.path.join(a.out_dir, f"idle_{i:03d}.png"))
    for i in range(a.run):
        draw_frame(a.size, i / a.run, True).save(os.path.join(a.out_dir, f"run_{i:03d}.png"))
    print(f"wrote {a.idle} idle + {a.run} run frames to {a.out_dir}")


if __name__ == "__main__":
    main()
