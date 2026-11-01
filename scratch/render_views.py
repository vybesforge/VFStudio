"""Render a GLB from named sides: front / back / left / right / three-quarter.

Separate from render_asset.py on purpose — that file is the other session's
fixed-camera A/B tool and must not be edited mid-run.

blender -b --python render_views.py -- in.glb out_prefix [size]
Writes <out_prefix>_front.png, _back.png, _left.png, _right.png, _34.png
"""
import math
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, PREFIX = argv[0], argv[1]
SIZE = int(argv[2]) if len(argv) > 2 else 720

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)

meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

bb = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
xs = [v.x for v in bb]; ys = [v.y for v in bb]; zs = [v.z for v in bb]
cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

# three-point-ish lighting, fixed in world space so the sides compare
key = bpy.data.lights.new("key", "AREA"); key.energy = 900; key.size = span * 2
ko = bpy.data.objects.new("key", key); scene.collection.objects.link(ko)
ko.location = (cx + span * 2, cy - span * 2.4, cz + span * 2.2)
ko.rotation_euler = (math.radians(55), 0, math.radians(40))

fill = bpy.data.lights.new("fill", "AREA"); fill.energy = 400; fill.size = span * 2.5
fo = bpy.data.objects.new("fill", fill); scene.collection.objects.link(fo)
fo.location = (cx - span * 2.5, cy - span * 2.0, cz + span * 0.8)
fo.rotation_euler = (math.radians(75), 0, math.radians(-55))

rim = bpy.data.lights.new("rim", "AREA"); rim.energy = 500; rim.size = span * 2
ro = bpy.data.objects.new("rim", rim); scene.collection.objects.link(ro)
ro.location = (cx, cy + span * 3, cz + span * 1.6)
ro.rotation_euler = (math.radians(60), 0, 0)

world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.055, 0.06, 1)

bpy.ops.mesh.primitive_plane_add(size=span * 8, location=(cx, cy, min(zs) - 0.001))
plane = bpy.context.active_object
pmat = bpy.data.materials.new("floor"); pmat.use_nodes = True
pmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.19, 0.21, 1)
pmat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
plane.data.materials.append(pmat)

for _eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
    try:
        scene.render.engine = _eng
        break
    except Exception:
        continue
try:
    scene.eevee.taa_render_samples = 32
except Exception:
    try:
        scene.cycles.samples = 24
    except Exception:
        pass
scene.render.resolution_x = SIZE
scene.render.resolution_y = SIZE
scene.render.image_settings.file_format = "PNG"

DIST = span * 2.35
ELEV = span * 0.22
# azimuth in degrees measured from -Y (the assumed front), counter-clockwise seen from above
VIEWS = {"front": 0, "left": 90, "back": 180, "right": 270, "34": 35}

for name, az in VIEWS.items():
    a = math.radians(az)
    # key/fill ride with the camera: same exposure on every side, so a colour
    # difference between views is albedo and not shadow
    kd = math.radians(az - 35)
    ko.location = (cx + DIST * 1.05 * math.sin(kd), cy - DIST * 1.05 * math.cos(kd), cz + span * 1.5)
    ko.rotation_euler = (mathutils.Vector((cx, cy, cz)) - ko.location).to_track_quat("-Z", "Y").to_euler()
    fd = math.radians(az + 45)
    fo.location = (cx + DIST * math.sin(fd), cy - DIST * math.cos(fd), cz + span * 0.55)
    fo.rotation_euler = (mathutils.Vector((cx, cy, cz)) - fo.location).to_track_quat("-Z", "Y").to_euler()
    ro.location = (cx - DIST * 1.1 * math.sin(a), cy + DIST * 1.1 * math.cos(a), cz + span * 1.2)
    # -Y is the front; rotate around Z
    cam.location = (cx + DIST * math.sin(a), cy - DIST * math.cos(a), cz + ELEV)
    direction = mathutils.Vector((cx, cy, cz)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{PREFIX}_{name}.png"
    bpy.ops.render.render(write_still=True)
    print(f"[render] wrote {scene.render.filepath}")
