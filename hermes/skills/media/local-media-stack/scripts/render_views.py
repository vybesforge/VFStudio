"""Render a GLB from named sides: front / back / left / right / three-quarter.

Kept separate from render_asset.py on purpose — that one is the fixed-camera A/B
tool, and a second session may be editing it.

The point of this script is the LIGHTING: key and fill are re-derived from each
view's own azimuth so every side gets the same exposure. Pin lights in world space
and the far side goes dark, which reads as a different material and produces
false "the texture is different front-to-back" verdicts.

Assumes the asset faces -Y after glTF import (glTF is Y-up; Blender imports Z-up).
If the first render shows the back of the subject, the model faces +Y — swap the
VIEWS azimuths by 180.

    blender -b --python render_views.py -- in.glb out_prefix [size]
Writes <prefix>_front.png, _left.png, _back.png, _right.png, _34.png
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

key = bpy.data.lights.new("key", "AREA"); key.energy = 900; key.size = span * 2
ko = bpy.data.objects.new("key", key); scene.collection.objects.link(ko)
fill = bpy.data.lights.new("fill", "AREA"); fill.energy = 400; fill.size = span * 2.5
fo = bpy.data.objects.new("fill", fill); scene.collection.objects.link(fo)
rim = bpy.data.lights.new("rim", "AREA"); rim.energy = 500; rim.size = span * 2
ro = bpy.data.objects.new("rim", rim); scene.collection.objects.link(ro)

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
# azimuth in degrees from -Y (the assumed front), counter-clockwise from above
VIEWS = {"front": 0, "left": 90, "back": 180, "right": 270, "34": 35}


def aim(light_obj, radians_az, dist, height):
    light_obj.location = (cx + dist * math.sin(radians_az),
                          cy - dist * math.cos(radians_az), cz + height)
    light_obj.rotation_euler = (mathutils.Vector((cx, cy, cz)) - light_obj.location
                                ).to_track_quat("-Z", "Y").to_euler()


for name, az in VIEWS.items():
    a = math.radians(az)
    cam.location = (cx + DIST * math.sin(a), cy - DIST * math.cos(a), cz + ELEV)
    cam.rotation_euler = (mathutils.Vector((cx, cy, cz)) - cam.location
                          ).to_track_quat("-Z", "Y").to_euler()

    # lights ride with the camera: same exposure from every side, so a colour
    # difference between views is albedo and not shadow
    aim(ko, math.radians(az - 35), DIST * 1.05, span * 1.5)
    aim(fo, math.radians(az + 45), DIST, span * 0.55)
    aim(ro, math.radians(az + 180), DIST * 1.1, span * 1.2)

    scene.render.filepath = f"{PREFIX}_{name}.png"
    bpy.ops.render.render(write_still=True)
    print(f"[render] wrote {scene.render.filepath}")
