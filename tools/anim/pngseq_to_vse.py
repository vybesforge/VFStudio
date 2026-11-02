"""pngseq_to_vse.py — Blender 5.x headless: put a PNG sequence (Krita / Tahoma2D / gp_anim export) on
the VSE timeline as ONE image-sequence strip and render an mp4 (optionally over a background colour).

  ~/media-stack/bin/blender -b --python ~/media-stack/tools/anim/pngseq_to_vse.py -- \
      --frames /abs/dir_with_pngs --out /abs/out.mp4 [--fps 24] [--bg 1,1,1] [--hold 1] [--save-blend /abs/f.blend]

--hold N  repeats every drawing N frames (Krita "animate on twos" = --hold 2 when you exported one PNG per drawing).
Prints `[pngseq] ...` lines and a final JSON line {"ok": true, "frames": N, "mp4": "...", "res": [w, h]}.
To composite with other clips, edit the saved .blend or use tools/video/vse_build.py (clips/images/titles).
"""
import argparse
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--frames", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--bg", default="", help="r,g,b 0-1 background colour strip under the sequence (for alpha PNGs)")
ap.add_argument("--hold", type=int, default=1)
ap.add_argument("--save-blend", default="")
args = ap.parse_args(argv)

files = sorted(f for f in os.listdir(args.frames) if f.lower().endswith(".png"))
if not files:
    sys.exit(f"no PNGs in {args.frames}")

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.sequence_editor_create()
strips = scene.sequence_editor.strips  # Blender 5.x name (was .sequences)

# resolution from the first frame
img = bpy.data.images.load(os.path.join(args.frames, files[0]))
W, H = img.size
bpy.data.images.remove(img)
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.fps = args.fps
n_frames = len(files) * args.hold
scene.frame_start, scene.frame_end = 1, n_frames

ch = 1
if args.bg:
    r, g, b = (float(v) for v in args.bg.split(","))
    bgs = strips.new_effect(name="BG", type="COLOR", channel=ch, frame_start=1, length=n_frames)
    bgs.color = (r, g, b)
    ch = 2

seq = strips.new_image(name="seq", filepath=os.path.join(args.frames, files[0]), channel=ch, frame_start=1)
# hold = repeat each PNG N times as strip elements (simplest, exact, no retiming API needed)
for i, f in enumerate(files):
    for _ in range(args.hold if i else args.hold - 1):
        seq.elements.append(f)
seq.blend_type = "ALPHA_OVER"
print(f"[pngseq] {len(files)} PNGs {W}x{H} -> {n_frames} frames @ {scene.render.fps} fps")

r = scene.render
if hasattr(r.image_settings, "media_type"):  # Blender 5.x: FFMPEG only appears after media_type=VIDEO
    r.image_settings.media_type = "VIDEO"
r.image_settings.file_format = "FFMPEG"
r.image_settings.color_mode = "RGB"
r.ffmpeg.format = "MPEG4"
r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"
r.filepath = args.out
os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)
bpy.ops.render.render(animation=True)
ok = os.path.exists(args.out) and os.path.getsize(args.out) > 0
print(f"[pngseq] wrote {args.out} ({os.path.getsize(args.out) / 1e6:.2f} MB)" if ok else "[pngseq] render produced nothing")
print(json.dumps({"ok": ok, "frames": n_frames, "mp4": args.out, "res": [W, H]}))
