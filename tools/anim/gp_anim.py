"""gp_anim.py — Blender 5.x headless Grease Pencil demo: programmatic 2D animation -> PNG sequence + mp4.

  ~/media-stack/bin/blender -b --python ~/media-stack/tools/anim/gp_anim.py -- \
      --out /abs/dir [--mode ball|line] [--frames 48] [--fps 24] [--res 1280x720] [--no-mp4] [--save-blend /abs/f.blend]

Creates a Grease Pencil object (Blender 5 GP v3 API: bpy.data.grease_pencils, layer.frames.new(),
frame.drawing.add_strokes()), draws one keyframe per frame, renders frame_0001.png ... with Workbench
on a white background, then concatenates with ffmpeg (libx264, yuv420p) into <out>/gp_anim.mp4.
Prints `[gp_anim] ...` lines and one final JSON line:
  {"ok": true, "frames": 48, "png_dir": "...", "mp4": "...", "res": [1280, 720]}

Modes
  ball  bouncing ball with squash & stretch, a ground line and a fading motion trail
  line  a line that grows across the screen and wiggles (classic "growing line" test)
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--mode", default="ball", choices=["ball", "line"])
ap.add_argument("--frames", type=int, default=48)
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--res", default="1280x720")
ap.add_argument("--no-mp4", action="store_true")
ap.add_argument("--save-blend", default="")
args = ap.parse_args(argv)
W, H = (int(v) for v in args.res.lower().split("x"))
os.makedirs(args.out, exist_ok=True)


def log(m):
    print(f"[gp_anim] {m}", flush=True)


# ── scene ──────────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, args.frames
scene.render.fps = args.fps
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "MATERIAL"
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.view_settings.view_transform = "Standard"
world = bpy.data.worlds.new("World")
world.color = (1.0, 1.0, 1.0)
scene.world = world
scene.display.shading.background_type = "WORLD"

# orthographic camera looking along +Y at the XZ plane; visible area = 16 x 9 units (res aspect)
ASPECT = W / H
VIEW_W = 16.0
VIEW_H = VIEW_W / ASPECT
cam = bpy.data.cameras.new("Cam")
cam.type = "ORTHO"
cam.ortho_scale = VIEW_W if ASPECT >= 1 else VIEW_H
cam_ob = bpy.data.objects.new("Cam", cam)
cam_ob.location = (0, -10, 0)
cam_ob.rotation_euler = (math.pi / 2, 0, 0)
scene.collection.objects.link(cam_ob)
scene.camera = cam_ob

# ── grease pencil object + materials ───────────────────────────────────────
gp = bpy.data.grease_pencils.new("GP")
gp_ob = bpy.data.objects.new("GP", gp)
scene.collection.objects.link(gp_ob)


def gp_material(name, stroke_rgba, fill_rgba=None):
    mat = bpy.data.materials.new(name)
    bpy.data.materials.create_gpencil_data(mat)
    g = mat.grease_pencil
    g.color = stroke_rgba
    if fill_rgba:
        g.fill_color = fill_rgba  # alpha > 0 enables the fill (show_fill is deprecated in 5.x)
    gp.materials.append(mat)
    return len(gp.materials) - 1


MAT_INK = gp_material("Ink", (0.05, 0.05, 0.08, 1.0))  # fill_color default alpha 0 = no fill
MAT_BALL = gp_material("Ball", (0.6, 0.1, 0.05, 1.0), (0.9, 0.3, 0.2, 1.0))
MAT_TRAIL = gp_material("Trail", (0.3, 0.5, 0.9, 1.0))

layer = gp.layers.new("Lines")


def add_stroke(drawing, points, radius=0.05, material=MAT_INK, cyclic=False, opacity=1.0):
    """points: list of (x, z) in view units (origin centre, +z up). Returns the stroke."""
    drawing.add_strokes([len(points)])
    s = drawing.strokes[-1]
    s.cyclic = cyclic
    s.material_index = material
    s.fill_opacity = 1.0  # strokes made by add_strokes() default to 0 -> material fill invisible
    for p, (x, z) in zip(s.points, points):
        p.position = Vector((x, 0.0, z))
        p.radius = radius
        p.opacity = opacity
    return s


def circle(cx, cz, rx, rz, n=48):
    return [(cx + rx * math.cos(2 * math.pi * i / n), cz + rz * math.sin(2 * math.pi * i / n)) for i in range(n)]


GROUND = -VIEW_H / 2 + 1.0
N = args.frames
history = []
for f in range(1, N + 1):
    t = (f - 1) / max(1, N - 1)
    frame = layer.frames.new(f)
    d = frame.drawing
    if args.mode == "ball":
        # two bounces across the screen; parabola per bounce, squash on contact, stretch in flight
        x = -VIEW_W / 2 + 1.5 + t * (VIEW_W - 3.0)
        bounce_t = (t * 2.0) % 1.0
        h = 4.0 * bounce_t * (1 - bounce_t) * (VIEW_H - 3.0)
        r = 0.7
        contact = max(0.0, 1.0 - h / 0.6)        # 1 at the floor, 0 above 0.6 units
        rx, rz = r * (1 + 0.35 * contact), r * (1 - 0.35 * contact)
        if contact == 0:
            stretch = min(0.25, abs(1 - 2 * bounce_t) * 0.3)
            rz *= 1 + stretch
            rx *= 1 - stretch * 0.5
        cz = GROUND + rz + h
        add_stroke(d, [(-VIEW_W / 2 + 0.5, GROUND), (VIEW_W / 2 - 0.5, GROUND)], radius=0.06)
        history.append((x, cz))
        for i, (hx, hz) in enumerate(history[-8:-1]):
            add_stroke(d, circle(hx, hz, 0.25, 0.25, 16), radius=0.03, material=MAT_TRAIL,
                       cyclic=True, opacity=0.15 + 0.1 * i)
        add_stroke(d, circle(x, cz, rx, rz), radius=0.08, material=MAT_BALL, cyclic=True)
        # highlight
        add_stroke(d, circle(x - rx * 0.35, cz + rz * 0.35, rx * 0.18, rz * 0.18, 12), radius=0.03, cyclic=True)
    else:
        # growing, wiggling line + a dot that leads it
        n_pts = 2 + int(t * 120)
        pts = []
        for i in range(n_pts):
            u = i / 120.0
            px = -VIEW_W / 2 + 1.0 + u * (VIEW_W - 2.0)
            pz = math.sin(u * 4 * math.pi + t * 6) * 1.5 + math.sin(u * 13) * 0.3
            pts.append((px, pz))
        add_stroke(d, pts, radius=0.09)
        add_stroke(d, circle(*pts[-1], 0.3, 0.3, 24), radius=0.04, material=MAT_BALL, cyclic=True)
log(f"drew {N} GP frames, mode={args.mode}, {len(gp.materials)} materials")

# ── render ─────────────────────────────────────────────────────────────────
png_dir = os.path.join(args.out, "frames")
os.makedirs(png_dir, exist_ok=True)
scene.render.filepath = os.path.join(png_dir, "frame_")
if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)
bpy.ops.render.render(animation=True)
pngs = sorted(p for p in os.listdir(png_dir) if p.endswith(".png"))
log(f"rendered {len(pngs)} PNGs to {png_dir}")

# ── mp4 ────────────────────────────────────────────────────────────────────
mp4 = None
if not args.no_mp4:
    ff = os.path.expanduser("~/.hermes/tools/ffmpeg-9.0.1-darwin-arm64/ffmpeg")
    if not os.path.exists(ff):
        ff = shutil.which("ffmpeg") or "ffmpeg"
    mp4 = os.path.join(args.out, "gp_anim.mp4")
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(args.fps),
           "-i", os.path.join(png_dir, "frame_%04d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"ffmpeg failed: {r.stderr.strip()}")
        mp4 = None
    else:
        log(f"wrote {mp4} ({os.path.getsize(mp4) / 1e6:.2f} MB)")

print(json.dumps({"ok": len(pngs) == N and (mp4 is not None or args.no_mp4), "frames": len(pngs),
                  "png_dir": png_dir, "mp4": mp4, "res": [W, H]}))
