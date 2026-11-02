"""Photoreal studio render of a reconstructed GLB (Cycles, PBR maps, per-view lighting).

  bin/blender -b -P scratch/render_hero.py -- in.glb outdir [--views front,threequarter,side,back,head]
                                                   [--size 1200x1600] [--samples 256]

Why this exists next to render_asset.py: that one is a fast EEVEE comparison tool. This
one is the deliverable renderer — Cycles path tracing, colour-managed filmic look,
a seamless studio sweep, and key/fill/rim re-derived per view so the far side of the
asset is lit (otherwise a shaded surface reads as a different material, not less light).
"""
import math
import sys
from pathlib import Path

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
SRC = Path(argv[0])
OUTDIR = Path(argv[1])
OUTDIR.mkdir(parents=True, exist_ok=True)

VIEWS = ["threequarter", "front", "side", "back", "head"]
if "--views" in argv:
    VIEWS = argv[argv.index("--views") + 1].split(",")
SIZE = (1200, 1600)
if "--size" in argv:
    w, h = argv[argv.index("--size") + 1].lower().split("x")
    SIZE = (int(w), int(h))
SAMPLES = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 256
TAG = argv[argv.index("--tag") + 1] if "--tag" in argv else SRC.stem

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

bpy.ops.import_scene.gltf(filepath=str(SRC))
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh in GLB")

# Keep every material: the TRELLIS asset ships body + (merged) head as separate
# materials, and joining would be fine but re-assigning slots is not worth it.
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

pts = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
cx = (min(xs) + max(xs)) / 2
cy = (min(ys) + max(ys)) / 2
height = max(zs) - min(zs)
width = max(xs) - min(xs)
span = max(height, width)
zmid = (min(zs) + max(zs)) / 2
top = max(zs)

# --- studio sweep: floor + curved backdrop, matte neutral grey -----------------
def make_grey():
    m = bpy.data.materials.new("studio")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.20, 0.205, 0.215, 1)
    bsdf.inputs["Roughness"].default_value = 0.75
    return m

grey = make_grey()
bpy.ops.mesh.primitive_plane_add(size=span * 14, location=(cx, cy + span * 2.0, min(zs)))
floor = bpy.context.active_object
floor.name = "floor"
floor.data.materials.append(grey)

bpy.ops.mesh.primitive_plane_add(size=span * 14, location=(cx, cy + span * 5.0, zmid),
                                 rotation=(math.radians(90), 0, 0))
back = bpy.context.active_object
back.name = "backdrop"
back.data.materials.append(grey)

# --- world: dim neutral, the lights do the work --------------------------------
world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.03, 0.032, 0.038, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.35


def area(name, energy, size, loc, look_at):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.size = size
    ld.shape = "DISK"
    ob = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(ob)
    ob.location = loc
    d = mathutils.Vector(look_at) - mathutils.Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


def frame_view(name):
    """Camera position + light rig for one view. Angles are degrees around +Z from -Y
    (the direction glTF imports face)."""
    cfg = {
        "front":        (0,   62, 0.98),   # az, lens, cam height factor
        "threequarter": (38,  70, 0.98),
        "side":         (90,  70, 0.98),
        "back":         (180, 70, 0.98),
        "head":         (22,  85, 0.0),    # height handled separately
    }[name]
    az_deg, lens, hf = cfg
    az = math.radians(az_deg)
    if name == "head":
        target = mathutils.Vector((cx, cy, top - height * 0.085))
        dist = height * 0.42
        cam_z = target.z
    else:
        target = mathutils.Vector((cx, cy, zmid))
        dist = span * 1.85
        cam_z = min(zs) + height * hf
    cam_loc = mathutils.Vector((cx - math.sin(az) * dist, cy - math.cos(az) * dist, cam_z))
    return cam_loc, target, lens


def build_cam(loc, target, lens):
    cd = bpy.data.cameras.new("cam")
    cd.lens = lens
    cam = bpy.data.objects.new("cam", cd)
    scene.collection.objects.link(cam)
    cam.location = loc
    d = target - loc
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    return cam


def clear_lights():
    for o in [o for o in scene.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(o, do_unlink=True)


def rig(loc, target):
    """Key/fill/rim placed relative to the CURRENT camera so every view is exposed
    the same way — the rule learned the hard way on the multi-view comparison."""
    az = math.atan2(-(loc.x - cx), -(loc.y - cy))          # camera azimuth
    R = span * 2.6
    key_az = az + math.radians(38)
    fill_az = az - math.radians(52)
    rim_az = az + math.radians(180)

    def at(a, radius, z):
        return (cx - math.sin(a) * radius, cy - math.cos(a) * radius, z)

    tgt = tuple(target)
    area("key", 1600 * (span ** 2), span * 2.0, at(key_az, R, zmid + height * 0.55), tgt)
    area("fill", 420 * (span ** 2), span * 3.0, at(fill_az, R * 0.9, zmid + height * 0.15), tgt)
    area("rim", 900 * (span ** 2), span * 1.2, at(rim_az, R * 0.7, zmid + height * 0.75), tgt)
    # soft top light for hair/skin falloff
    area("top", 260 * (span ** 2), span * 2.5, (cx, cy - span * 0.2, zmid + height * 1.4), tgt)


# --- render settings ----------------------------------------------------------
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
try:
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:
    pass
scene.cycles.max_bounces = 8
scene.cycles.transparent_max_bounces = 8
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.render.resolution_x, scene.render.resolution_y = SIZE
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass
scene.view_settings.exposure = 0.25

# Materials: give skin/cloth a touch of realism where the GLB has no explicit values.
for m in bpy.data.materials:
    if not m.use_nodes or "Principled BSDF" not in m.node_tree.nodes:
        continue
    b = m.node_tree.nodes["Principled BSDF"]
    if b.inputs["Roughness"].is_linked or b.inputs["Roughness"].default_value == 0.5:
        b.inputs["Roughness"].default_value = 0.62
    if "Subsurface Weight" in b.inputs and not b.inputs["Subsurface Weight"].is_linked:
        b.inputs["Subsurface Weight"].default_value = 0.06
        b.inputs["Subsurface Radius"].default_value = (0.9, 0.35, 0.22)

for v in VIEWS:
    loc, target, lens = frame_view(v)
    clear_lights()
    for o in [o for o in scene.objects if o.type == "CAMERA"]:
        bpy.data.objects.remove(o, do_unlink=True)
    build_cam(loc, target, lens)
    rig(loc, target)
    out = OUTDIR / f"{TAG}_{v}.png"
    scene.render.filepath = str(out)
    print(f"[render] {v} -> {out}", flush=True)
    bpy.ops.render.render(write_still=True)
    print(f"[render] done {v}", flush=True)
