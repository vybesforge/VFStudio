"""Render a GLB to a PNG from a fixed 3/4 camera so two assets can be compared.

blender -b --python render_asset.py -- in.glb out.png [size]
"""
import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], argv[1]
SIZE = int(argv[2]) if len(argv) > 2 else 900

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

bpy.ops.import_scene.gltf(filepath=SRC)
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit("no mesh")

# frame the whole asset
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

bb = [obj.matrix_world @ __import__("mathutils").Vector(c) for c in obj.bound_box]
xs = [v.x for v in bb]; ys = [v.y for v in bb]; zs = [v.z for v in bb]
cx, cy, cz = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2
span = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
dist = span * 2.6
if "--top" in sys.argv:
    cam.location = (cx, cy, cz + dist * 1.4)
elif "--front" in sys.argv:
    # glTF imports face -Y, so the default 3/4 camera at +Y photographs the BACK.
    cam.location = (cx, cy - dist * 1.15, cz + dist * 0.10)
elif "--side" in sys.argv:
    cam.location = (cx + dist * 1.15, cy, cz + dist * 0.10)
else:
    cam.location = (cx + dist * 0.55, cy + dist * 1.05, cz + dist * 0.38)
# aim at the asset
import mathutils
direction = mathutils.Vector((cx, cy, cz)) - cam.location
# --head: close-up on the top 16% of the bbox so facial detail is judged at size.
if "--head" in sys.argv:
    tz = max(zs) - (max(zs) - min(zs)) * 0.09
    cam.location = (cx, cy - span * 0.9, tz)
    cam_data.lens = 85
    direction = mathutils.Vector((cx, cy, tz)) - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

# three-point-ish lighting so texture detail reads
key = bpy.data.lights.new("key", "AREA"); key.energy = 900; key.size = span * 2
ko = bpy.data.objects.new("key", key); scene.collection.objects.link(ko)
ko.location = (cx + span * 2, cy - span * 2.4, cz + span * 2.2)
ko.rotation_euler = (math.radians(55), 0, math.radians(40))

fill = bpy.data.lights.new("fill", "AREA"); fill.energy = 350; fill.size = span * 2.5
fo = bpy.data.objects.new("fill", fill); scene.collection.objects.link(fo)
fo.location = (cx - span * 2.5, cy - span * 1.5, cz + span * 0.8)
fo.rotation_euler = (math.radians(75), 0, math.radians(-55))

world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.055, 0.06, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

# ground so it doesn't float
bpy.ops.mesh.primitive_plane_add(size=span * 6, location=(cx, cy, min(zs) - 0.001))
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
print(f"[render] engine={scene.render.engine}")
try:
    scene.eevee.taa_render_samples = 32
except Exception:
    try:
        scene.cycles.samples = 24
    except Exception:
        pass
scene.render.resolution_x = SIZE
scene.render.resolution_y = SIZE
scene.render.film_transparent = False
scene.render.filepath = OUT
scene.render.image_settings.file_format = "PNG"

if "--frame" in sys.argv:
    scene.frame_set(int(sys.argv[sys.argv.index("--frame") + 1]))

bpy.ops.render.render(write_still=True)
print(f"[render] wrote {OUT}")
